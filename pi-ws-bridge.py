#!/usr/bin/env python3
"""
ROV WebSocket bridge — run this on the Raspberry Pi.

Keeps the existing TCP motor (5001) and IMU (5002) servers.
Adds a browser-facing HTTP + WebSocket service on port 5003.

Install once:
    sudo apt update
    sudo apt install -y python3-pip
    python3 -m pip install aiohttp

Run:
    python3 pi-ws-bridge.py

Endpoints:
    ws://<pi-ip>:5003/ws      motor commands in, IMU + status out
    http://<pi-ip>:5003/video camera proxy (CORS enabled)
    http://<pi-ip>:5003/health
"""

from __future__ import annotations

import asyncio
import json
import time

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

MOTOR_HOST = "127.0.0.1"
MOTOR_PORT = 5001
IMU_HOST = "127.0.0.1"
IMU_PORT = 5002
CAM_URL = "http://127.0.0.1:5000/video"
LISTEN_PORT = 5003
WATCHDOG_S = 1.0
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}

clients = set()
motor_ok = False
imu_ok = False
imu = {"pitch": 0.0, "roll": 0.0}
cmd_q: asyncio.Queue | None = None
last_cmd_at = 0.0
last_sent = ""


def now() -> float:
    return time.monotonic()


async def broadcast(payload: dict) -> None:
    msg = json.dumps(payload)
    dead = []
    for ws in list(clients):
        try:
            await ws.send_str(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


async def motor_loop() -> None:
    global motor_ok, last_sent
    writer = None
    while True:
        try:
            _reader, writer = await asyncio.open_connection(MOTOR_HOST, MOTOR_PORT)
            motor_ok = True
            print("Motor TCP connected")
            await broadcast({"type": "status", "motor": True, "imu": imu_ok})
            while True:
                try:
                    msg = await asyncio.wait_for(cmd_q.get(), timeout=0.2)  # type: ignore[union-attr]
                except asyncio.TimeoutError:
                    msg = None
                if now() - last_cmd_at > WATCHDOG_S:
                    msg = "STOP 1000\n"
                if not msg:
                    continue
                if not msg.endswith("\n"):
                    msg += "\n"
                if msg == last_sent and not msg.startswith("STOP"):
                    continue
                writer.write(msg.encode())
                await writer.drain()
                last_sent = msg
        except Exception as exc:
            motor_ok = False
            print("Motor TCP down:", exc)
            await broadcast({"type": "status", "motor": False, "imu": imu_ok})
            await asyncio.sleep(2)
        finally:
            if writer is not None:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
                writer = None


async def imu_loop() -> None:
    global imu_ok
    while True:
        try:
            reader, writer = await asyncio.open_connection(IMU_HOST, IMU_PORT)
            imu_ok = True
            print("IMU TCP connected")
            await broadcast({"type": "status", "motor": motor_ok, "imu": True})
            buf = ""
            while True:
                chunk = await reader.read(256)
                if not chunk:
                    raise ConnectionError("IMU closed")
                buf += chunk.decode(errors="ignore")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line.startswith("IMU"):
                        continue
                    parts = line.split()
                    if len(parts) != 3:
                        continue
                    imu["pitch"] = float(parts[1])
                    imu["roll"] = float(parts[2])
                    await broadcast(
                        {"type": "imu", "pitch": imu["pitch"], "roll": imu["roll"]}
                    )
        except Exception as exc:
            imu_ok = False
            print("IMU TCP down:", exc)
            await broadcast({"type": "status", "motor": motor_ok, "imu": False})
            await asyncio.sleep(2)


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    global last_cmd_at
    ws = web.WebSocketResponse(heartbeat=20.0)
    await ws.prepare(request)
    clients.add(ws)
    await ws.send_str(
        json.dumps(
            {
                "type": "hello",
                "motor": motor_ok,
                "imu": imu_ok,
                "pitch": imu["pitch"],
                "roll": imu["roll"],
            }
        )
    )
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            text = msg.data.strip()
            if not text:
                continue
            last_cmd_at = now()
            if cmd_q is not None:
                await cmd_q.put(text if text.endswith("\n") else text + "\n")
    finally:
        clients.discard(ws)
        if cmd_q is not None:
            await cmd_q.put("STOP 1000\n")
    return ws


async def video_handler(request: web.Request) -> web.StreamResponse:
    timeout = ClientTimeout(total=None, sock_connect=5, sock_read=None)
    async with ClientSession(timeout=timeout) as session:
        try:
            async with session.get(CAM_URL) as resp:
                ctype = resp.headers.get(
                    "Content-Type", "multipart/x-mixed-replace; boundary=frame"
                )
                response = web.StreamResponse(
                    status=200,
                    headers={
                        **CORS,
                        "Content-Type": ctype,
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                    },
                )
                await response.prepare(request)
                async for chunk in resp.content.iter_chunked(4096):
                    await response.write(chunk)
                return response
        except Exception:
            raise web.HTTPBadGateway(text="camera unavailable")


async def health_handler(_request: web.Request) -> web.Response:
    return web.json_response(
        {
            "motor": motor_ok,
            "imu": imu_ok,
            "clients": len(clients),
            "pitch": imu["pitch"],
            "roll": imu["roll"],
        },
        headers=CORS,
    )


async def options_handler(_request: web.Request) -> web.Response:
    return web.Response(headers=CORS)


async def on_startup(app: web.Application) -> None:
    global cmd_q, last_cmd_at
    cmd_q = asyncio.Queue()
    last_cmd_at = now()
    app["tasks"] = [
        asyncio.create_task(motor_loop()),
        asyncio.create_task(imu_loop()),
    ]


async def on_cleanup(app: web.Application) -> None:
    for task in app.get("tasks", []):
        task.cancel()


def main() -> None:
    app = web.Application()
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/video", video_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_route("OPTIONS", "/{path:.*}", options_handler)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    print(f"ROV bridge on 0.0.0.0:{LISTEN_PORT}")
    web.run_app(app, host="0.0.0.0", port=LISTEN_PORT, print=None)


if __name__ == "__main__":
    main()
