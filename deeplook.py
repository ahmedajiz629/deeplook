#!/usr/bin/env python3
"""
DeepLook ROV — camera + dashboard + browser bridge.

Run on the Raspberry Pi (copied to ~/deeplook.py).
Dashboard files live in ~/deeplook_web (Vite build).

  http://deeplook.local/           React dashboard
  http://deeplook.local/video      Picamera2 MJPEG
  ws://deeplook.local/ws           React control
  http://deeplook.local:5000/video legacy pygame camera
  TCP 5001 / 5002                  pygame motors / IMU

Arduino serial (same as codeparfait soutenence.py):
  out  "<MODE> <SPEED>\\n"     e.g. FORWARD 1320
  in   "IMU <pitch> <roll>\\n"

  python3 -m pip install aiohttp pyserial --break-system-packages
  sudo apt install -y python3-picamera2 python3-opencv

  python3 ~/deeplook.py
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from pathlib import Path

import cv2
import serial
from aiohttp import WSMsgType, web
from picamera2 import Picamera2

PI_HOST = "0.0.0.0"
CAM_PORT = 5000
MOTOR_PORT = 5001
IMU_PORT = 5002
BRIDGE_PORT = 5003
HTTP_PORTS = (80, CAM_PORT, BRIDGE_PORT)

ARDUINO_PORT = "/dev/ttyUSB0"
ARDUINO_BAUD = 115200
WATCHDOG_S = 1.0

WEB_ROOT = Path(__file__).resolve().parent / "deeplook_web"

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}

ser_lock = threading.Lock()
arduino = None
arduino_ok = False

try:
    arduino = serial.Serial(ARDUINO_PORT, ARDUINO_BAUD, timeout=1)
    time.sleep(2)
    arduino_ok = True
    print(f"Arduino on {ARDUINO_PORT}")
except Exception as exc:
    print(f"[WARN] Serial {ARDUINO_PORT}: {exc}")

state_lock = threading.Lock()
state = {
    "mode": "STOP",
    "speed": 0,
    "pitch": 0.0,
    "roll": 0.0,
    "last_cmd": time.monotonic(),
}

imu_clients: list[socket.socket] = []
imu_clients_lock = threading.Lock()

ws_loop: asyncio.AbstractEventLoop | None = None
ws_clients: set[web.WebSocketResponse] = set()
cmd_q: asyncio.Queue | None = None

jpeg_lock = threading.Lock()
latest_jpeg: bytes | None = None

picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration(main={"size": (640, 480)}))
picam2.start()


def send_serial(payload: bytes) -> None:
    if arduino is None:
        return
    try:
        with ser_lock:
            arduino.write(payload)
            arduino.flush()
    except Exception as exc:
        print("[ERROR] serial write:", exc)


def send_motor(mode: str, speed: int) -> None:
    mode = str(mode).strip().upper() or "STOP"
    requested = max(0, min(1500, int(speed)))
    # ESCs stay armed only with a 1000–1500 µs pulse. HUD may show 0 when idle.
    wire = requested if requested >= 1000 else 1000
    with state_lock:
        state["mode"] = mode
        state["speed"] = requested
        state["last_cmd"] = time.monotonic()
    line = f"{mode} {wire}\n"
    print(f"MOTOR {line.strip()}", flush=True)
    send_serial(line.encode())


def parse_command(raw: str) -> tuple[str, int] | None:
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if data.get("type") == "ping":
            return None
        if data.get("type") in (None, "command") or "mode" in data:
            return str(data.get("mode", "STOP")), int(data.get("speed", 0))
        return None
    parts = raw.split()
    if not parts:
        return None
    mode = parts[0].upper()
    speed = int(parts[1]) if len(parts) > 1 else 0
    return mode, speed


def camera_loop() -> None:
    global latest_jpeg
    while True:
        try:
            frame = picam2.capture_array()
            frame = cv2.rotate(frame, cv2.ROTATE_180)
            ok, buffer = cv2.imencode(".jpg", frame)
            if not ok:
                continue
            with jpeg_lock:
                latest_jpeg = buffer.tobytes()
        except Exception as exc:
            print("[ERROR] camera:", exc)
            time.sleep(0.2)


def jpeg_chunk() -> bytes | None:
    with jpeg_lock:
        jpg = latest_jpeg
    if not jpg:
        return None
    return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"


# ── TCP motor :5001 ──────────────────────────────────────────────────────
def motor_server() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((PI_HOST, MOTOR_PORT))
    server.listen(5)
    print("Motor TCP on", MOTOR_PORT)
    while True:
        conn, addr = server.accept()
        print("Motor client", addr)
        try:
            while True:
                data = conn.recv(1024)
                if not data:
                    break
                text = data.decode(errors="ignore")
                for line in text.splitlines():
                    parsed = parse_command(line)
                    if parsed:
                        send_motor(*parsed)
        except Exception as exc:
            print("Motor client error:", exc)
        finally:
            conn.close()
            send_motor("STOP", 0)
            print("Motor client gone")


# ── TCP IMU :5002 ────────────────────────────────────────────────────────
def imu_server() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((PI_HOST, IMU_PORT))
    server.listen(5)
    print("IMU TCP on", IMU_PORT)
    while True:
        conn, addr = server.accept()
        print("IMU client", addr)
        with imu_clients_lock:
            imu_clients.append(conn)


def broadcast_imu_tcp(line: str) -> None:
    data = (line + "\n").encode()
    with imu_clients_lock:
        dead = []
        for client in imu_clients:
            try:
                client.sendall(data)
            except Exception:
                dead.append(client)
        for client in dead:
            imu_clients.remove(client)
            try:
                client.close()
            except Exception:
                pass


def serial_reader() -> None:
    if arduino is None:
        return
    buf = b""
    while True:
        try:
            with ser_lock:
                waiting = arduino.in_waiting
                chunk = arduino.read(waiting) if waiting else b""
        except Exception as exc:
            print("Serial read error:", exc)
            time.sleep(0.2)
            continue
        if not chunk:
            time.sleep(0.01)
            continue
        buf += chunk
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            line = raw.decode(errors="ignore").strip()
            if not line:
                continue
            if line.startswith("IMU"):
                parts = line.split()
                if len(parts) == 3:
                    try:
                        pitch, roll = float(parts[1]), float(parts[2])
                    except ValueError:
                        continue
                    with state_lock:
                        state["pitch"] = pitch
                        state["roll"] = roll
                    broadcast_imu_tcp(line)
                    schedule_ws(
                        {
                            "type": "telemetry",
                            "pitch": pitch,
                            "roll": roll,
                        }
                    )
                    schedule_ws({"type": "imu", "pitch": pitch, "roll": roll})
            else:
                print("Arduino:", line)


def watchdog() -> None:
    while True:
        time.sleep(0.25)
        with state_lock:
            idle = time.monotonic() - state["last_cmd"]
            stopped = state["mode"] == "STOP"
        if idle > WATCHDOG_S and not stopped:
            send_motor("STOP", 0)
            schedule_ws({"type": "mode", "mode": "STOP", "speed": 0})


def schedule_ws(payload: dict) -> None:
    loop = ws_loop
    if loop is None:
        return
    asyncio.run_coroutine_threadsafe(ws_broadcast(payload), loop)


async def ws_broadcast(payload: dict) -> None:
    msg = json.dumps(payload)
    dead = []
    for ws in list(ws_clients):
        try:
            await ws.send_str(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.discard(ws)


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=20.0)
    await ws.prepare(request)
    ws_clients.add(ws)
    with state_lock:
        hello = {
            "type": "hello",
            "motor": arduino_ok,
            "arduino_connected": arduino_ok,
            "imu": arduino_ok,
            "pitch": state["pitch"],
            "roll": state["roll"],
        }
    await ws.send_str(json.dumps(hello))
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            text = msg.data.strip()
            if not text:
                continue
            if text.startswith("{") and '"ping"' in text:
                try:
                    data = json.loads(text)
                    if data.get("type") == "ping":
                        await ws.send_str(json.dumps({"type": "pong", "t": data.get("t")}))
                        continue
                except json.JSONDecodeError:
                    pass
            parsed = parse_command(text)
            if parsed:
                send_motor(*parsed)
    finally:
        ws_clients.discard(ws)
        if not ws_clients:
            send_motor("STOP", 0)
    return ws


async def health_handler(_request: web.Request) -> web.Response:
    with state_lock:
        body = {
            "motor": arduino_ok,
            "imu": arduino_ok,
            "clients": len(ws_clients),
            "pitch": state["pitch"],
            "roll": state["roll"],
            "mode": state["mode"],
            "speed": state["speed"],
        }
    return web.json_response(body, headers=CORS)


async def options_handler(_request: web.Request) -> web.Response:
    return web.Response(headers=CORS)


async def video_handler(request: web.Request) -> web.StreamResponse:
    resp = web.StreamResponse(
        headers={
            "Content-Type": "multipart/x-mixed-replace; boundary=frame",
            "Cache-Control": "no-cache, no-store",
            "Access-Control-Allow-Origin": "*",
            **CORS,
        }
    )
    await resp.prepare(request)
    try:
        while True:
            chunk = await asyncio.to_thread(jpeg_chunk)
            if chunk:
                await resp.write(chunk)
            else:
                await asyncio.sleep(0.03)
    except (ConnectionResetError, ConnectionAbortedError, asyncio.CancelledError):
        pass
    return resp


def index_path() -> Path:
    return WEB_ROOT / "index.html"


async def index_handler(_request: web.Request) -> web.StreamResponse:
    page = index_path()
    if page.is_file():
        return web.FileResponse(page)
    return web.Response(text="Dashboard not installed. Copy the Vite build to deeplook_web.", status=503)


async def spa_handler(request: web.Request) -> web.StreamResponse:
    name = request.match_info.get("tail", "")
    if name:
        candidate = (WEB_ROOT / name).resolve()
        try:
            candidate.relative_to(WEB_ROOT.resolve())
        except ValueError:
            return web.HTTPForbidden()
        if candidate.is_file():
            return web.FileResponse(candidate)
    return await index_handler(request)


async def run_http() -> None:
    global ws_loop
    ws_loop = asyncio.get_running_loop()
    app = web.Application()
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/video", video_handler)
    app.router.add_route("OPTIONS", "/{path:.*}", options_handler)
    assets = WEB_ROOT / "assets"
    if assets.is_dir():
        app.router.add_static("/assets", assets)
    app.router.add_get("/", index_handler)
    app.router.add_get("/{tail:.*}", spa_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    bound = []
    for port in HTTP_PORTS:
        try:
            site = web.TCPSite(runner, PI_HOST, port)
            await site.start()
            bound.append(port)
        except OSError as exc:
            print(f"[WARN] HTTP {port}: {exc}")
    print("HTTP on", bound or "no ports", "→ http://deeplook.local/")
    await asyncio.Event().wait()


def main() -> None:
    threading.Thread(target=camera_loop, daemon=True).start()
    threading.Thread(target=motor_server, daemon=True).start()
    threading.Thread(target=imu_server, daemon=True).start()
    threading.Thread(target=serial_reader, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    print("Camera MJPEG on /video")
    asyncio.run(run_http())


if __name__ == "__main__":
    main()
