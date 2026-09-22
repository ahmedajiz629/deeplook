import { useCallback, useEffect, useRef, useState } from "react";

function socketUrl() {
  if (import.meta.env.DEV) return "ws://deeplook.local:5003/ws";
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws`;
}

export function useRovSocket() {
  const [wsOk, setWsOk] = useState(false);
  const [motorOk, setMotorOk] = useState(false);
  const [imu, setImu] = useState({ pitch: 0, roll: 0 });
  const wsRef = useRef(null);
  const lastSent = useRef("");
  const pending = useRef({ mode: "STOP", speed: 0 });

  useEffect(() => {
    let closed = false;
    let retry;
    let beat;
    let ping;

    const connect = () => {
      if (closed) return;
      const ws = new WebSocket(socketUrl());
      wsRef.current = ws;

      ws.onopen = () => {
        if (closed) return;
        setWsOk(true);
        const { mode, speed } = pending.current;
        const payload = JSON.stringify({ type: "command", mode, speed });
        lastSent.current = payload;
        ws.send(payload);
      };
      ws.onclose = () => {
        setWsOk(false);
        setMotorOk(false);
        if (!closed) retry = setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === "telemetry" || msg.type === "imu") {
            setImu({ pitch: Number(msg.pitch) || 0, roll: Number(msg.roll) || 0 });
          } else if (msg.type === "hello" || msg.type === "status") {
            if ("arduino_connected" in msg) setMotorOk(!!msg.arduino_connected);
            if ("motor" in msg) setMotorOk(!!msg.motor);
            if ("pitch" in msg) {
              setImu({ pitch: Number(msg.pitch) || 0, roll: Number(msg.roll) || 0 });
            }
          }
        } catch {
          /* ignore non-JSON */
        }
      };
    };

    connect();
    beat = setInterval(() => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      const { mode, speed } = pending.current;
      ws.send(JSON.stringify({ type: "command", mode, speed }));
    }, 80);
    ping = setInterval(() => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({ type: "ping", t: Date.now() }));
    }, 5000);

    return () => {
      closed = true;
      clearTimeout(retry);
      clearInterval(beat);
      clearInterval(ping);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, []);

  const sendCmd = useCallback((mode, speed) => {
    pending.current = { mode, speed };
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const payload = JSON.stringify({ type: "command", mode, speed });
    if (payload === lastSent.current) return;
    lastSent.current = payload;
    ws.send(payload);
  }, []);

  return { wsOk, motorOk, imu, sendCmd };
}
