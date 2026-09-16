import { useCallback, useEffect, useRef, useState } from "react";

export function useRovSocket(host, port) {
  const [wsOk, setWsOk] = useState(false);
  const [motorOk, setMotorOk] = useState(false);
  const [imuOk, setImuOk] = useState(false);
  const [imu, setImu] = useState({ pitch: 0, roll: 0 });
  const wsRef = useRef(null);
  const lastSent = useRef("");
  const pending = useRef("STOP 1000\n");

  useEffect(() => {
    let closed = false;
    let retry;

    const connect = () => {
      if (closed) return;
      const ws = new WebSocket(`ws://${host}:${port}/ws`);
      wsRef.current = ws;

      ws.onopen = () => {
        if (closed) return;
        setWsOk(true);
        if (pending.current) {
          ws.send(pending.current);
          lastSent.current = pending.current;
        }
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
          if (msg.type === "imu") {
            setImu({ pitch: msg.pitch, roll: msg.roll });
          } else if (msg.type === "status" || msg.type === "hello") {
            if ("motor" in msg) setMotorOk(!!msg.motor);
            if ("imu" in msg) setImuOk(!!msg.imu);
            if ("pitch" in msg) setImu({ pitch: msg.pitch, roll: msg.roll });
          }
        } catch {
          /* ignore non-JSON */
        }
      };
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [host, port]);

  const sendCmd = useCallback((cmd) => {
    const line = cmd.endsWith("\n") ? cmd : `${cmd}\n`;
    pending.current = line;
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (line === lastSent.current) return;
    lastSent.current = line;
    ws.send(line);
  }, []);

  return { wsOk, motorOk, imuOk, imu, sendCmd };
}
