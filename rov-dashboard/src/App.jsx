import { useCallback, useEffect, useRef, useState } from "react";
import Attitude from "./components/Attitude.jsx";
import SpeedArc from "./components/SpeedArc.jsx";
import { useControls } from "./hooks/useControls.js";
import { useRovSocket } from "./hooks/useRovSocket.js";
import "./App.css";

const DEFAULT_HOST = "192.168.137.10";
const BRIDGE_PORT = 5003;
const CAM_PORT = 5000;

const CMD_COL = {
  FORWARD: "#50d25a",
  LEFT: "#3c8cff",
  RIGHT: "#ffaf32",
  VLVR: "#a564ff",
  STOP: "#646978",
};

function pad(n, w = 2) {
  return String(n).padStart(w, "0");
}

function clockStr() {
  const d = new Date();
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function fileStamp() {
  const d = new Date();
  return `${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

function downloadBlob(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

function recMime() {
  const types = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm", "video/mp4"];
  return types.find((t) => MediaRecorder.isTypeSupported(t)) || "";
}

function clamp(v, a, b) {
  return Math.max(a, Math.min(b, v));
}

export default function App() {
  const [host, setHost] = useState(
    () => localStorage.getItem("rov-pi-host") || DEFAULT_HOST
  );
  const [clock, setClock] = useState(clockStr);
  const [log, setLog] = useState([]);
  const [shotCount, setShotCount] = useState(0);
  const [isRecording, setIsRecording] = useState(false);
  const [recLabel, setRecLabel] = useState("00:00");
  const [flash, setFlash] = useState(0);
  const [toasts, setToasts] = useState([]);
  const [camOk, setCamOk] = useState(false);
  const [sensors, setSensors] = useState({
    temp: 24,
    hum: 62,
    wtemp: 18,
    depth: 0,
  });

  const camRef = useRef(null);
  const recRef = useRef(null);
  const recStart = useRef(0);
  const lastMode = useRef("STOP");

  const camUrl = `http://${host}:${CAM_PORT}/video`;
  const { wsOk, motorOk, imu, sendCmd } = useRovSocket(host, BRIDGE_PORT);

  const addToast = useCallback((msg, color = "#1dc896") => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, msg, color, expire: Date.now() + 3500 }]);
  }, []);

  const takeShot = useCallback(() => {
    setShotCount((n) => n + 1);
    setFlash(10);
    const n = shotCount + 1;
    const name = `ROV_${fileStamp()}_${pad(n, 3)}.jpg`;
    const cam = camRef.current;
    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 480;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#12141c";
    ctx.fillRect(0, 0, 640, 480);
    try {
      if (cam && cam.naturalWidth) ctx.drawImage(cam, 0, 0, 640, 480);
    } catch {
      /* canvas tainted without CORS */
    }
    canvas.toBlob((blob) => blob && downloadBlob(blob, name), "image/jpeg", 0.92);
    addToast(`■ SCREENSHOT  ${name}`, "#50d25a");
  }, [addToast, shotCount]);

  const toggleRecord = useCallback(() => {
    if (recRef.current) {
      recRef.current.stop();
      return;
    }
    const cam = camRef.current;
    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 480;
    const ctx = canvas.getContext("2d");
    const timer = setInterval(() => {
      ctx.fillStyle = "#12141c";
      ctx.fillRect(0, 0, 640, 480);
      try {
        if (cam && cam.naturalWidth) ctx.drawImage(cam, 0, 0, 640, 480);
      } catch {
        /* canvas tainted without CORS */
      }
    }, 50);

    const mime = recMime();
    let recorder;
    try {
      recorder = new MediaRecorder(canvas.captureStream(20), mime ? { mimeType: mime } : {});
    } catch {
      clearInterval(timer);
      addToast("Recording not supported in this browser", "#dc4141");
      return;
    }
    const chunks = [];
    recorder.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    recorder.onstop = () => {
      clearInterval(timer);
      recRef.current = null;
      setIsRecording(false);
      const type = recorder.mimeType || "video/webm";
      const ext = type.includes("mp4") ? "mp4" : "webm";
      const name = `ROV_REC_${fileStamp()}.${ext}`;
      downloadBlob(new Blob(chunks, { type }), name);
      const dur = Math.floor((performance.now() - recStart.current) / 1000);
      addToast(`■ SAVED ${name}  (${dur}s)`, "#ffaf32");
    };
    recorder.start(250);
    recRef.current = recorder;
    recStart.current = performance.now();
    setIsRecording(true);
    addToast("● REC STARTED", "#dc4141");
  }, [addToast]);

  const { hasPad, mode, speed } = useControls({
    onRecord: toggleRecord,
    onShot: takeShot,
  });

  useEffect(() => {
    const id = setInterval(() => setClock(clockStr()), 250);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const id = setInterval(() => {
      setSensors((s) => ({
        temp: clamp(s.temp + (Math.random() - 0.5) * 0.4, 18, 40),
        hum: clamp(s.hum + (Math.random() - 0.5) * 1, 30, 95),
        wtemp: clamp(s.wtemp + (Math.random() - 0.5) * 0.2, 10, 30),
        depth: clamp(s.depth + (Math.random() - 0.5) * 0.1, 0, 20),
      }));
    }, 2000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const id = setInterval(() => {
      setToasts((t) => t.filter((x) => x.expire > Date.now()));
    }, 250);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (flash <= 0) return;
    const id = setTimeout(() => setFlash((f) => f - 1), 33);
    return () => clearTimeout(id);
  }, [flash]);

  useEffect(() => {
    if (!isRecording) return;
    const id = setInterval(() => {
      const elapsed = Math.floor((performance.now() - recStart.current) / 1000);
      setRecLabel(`${pad(Math.floor(elapsed / 60))}:${pad(elapsed % 60)}`);
    }, 250);
    return () => clearInterval(id);
  }, [isRecording]);

  useEffect(() => {
    sendCmd(`${mode} ${speed}`);
    if (mode !== lastMode.current) {
      lastMode.current = mode;
      setLog((rows) => {
        const next = [...rows, { mode, speed, ts: clockStr() }];
        return next.slice(-8);
      });
    }
  }, [mode, speed, sendCmd]);

  const applyHost = (value) => {
    const next = value.trim() || DEFAULT_HOST;
    setCamOk(false);
    setHost(next);
    localStorage.setItem("rov-pi-host", next);
  };

  const cmdColor = CMD_COL[mode] || CMD_COL.STOP;
  const barPct = (speed - 1000) / 500;
  const recCol = isRecording ? "#dc4141" : "#5a5f6e";

  return (
    <div className="page">
      <div className="dash" id="dash">
        <header className="hdr">
          <div className="hdr-left">
            <span className={`dot ${motorOk ? "ok" : "bad"}`} />
            <span className={motorOk ? "ok" : "bad"}>{motorOk ? "MOTOR OK" : "NO MOTOR"}</span>
            <span className={`link ${wsOk ? "ok" : "bad"}`}>{wsOk ? "WS" : "NO WS"}</span>
            <span className={`link ${hasPad ? "ok" : ""}`}>{hasPad ? "PAD" : "KEYS"}</span>
          </div>
          <h1>ROV  CONTROL  DASHBOARD</h1>
          <div className="hdr-right">
            <label className="host">
              PI
              <input
                defaultValue={host}
                onBlur={(e) => applyHost(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && applyHost(e.target.value)}
              />
            </label>
            <time>{clock}</time>
          </div>
        </header>

        <section className="cam-wrap">
          <img
            key={camUrl}
            ref={camRef}
            className={camOk ? "cam" : "cam hidden"}
            src={camUrl}
            alt="ROV camera"
            onLoad={() => setCamOk(true)}
            onError={() => setCamOk(false)}
          />
          {!camOk && (
            <div className="cam-wait">waiting for camera  {host}:5000/video</div>
          )}
          {flash > 0 && (
            <div className="flash" style={{ opacity: (flash / 10) * 0.82 }} />
          )}
          {isRecording && (
            <div className="rec-overlay">
              <span className="rec-dot" />
              REC  {recLabel}
            </div>
          )}
        </section>

        <div className="btns">
          <button
            type="button"
            className="btn rec"
            style={{ borderColor: recCol, color: recCol }}
            onClick={toggleRecord}
          >
            <span className={`rec-circle ${isRecording ? "on" : ""}`} style={{ background: isRecording ? recCol : "transparent", borderColor: recCol }} />
            CIRCLE / R  →  RECORD / STOP
          </button>
          <button type="button" className="btn shot" onClick={takeShot}>
            <span className="sq" />
            SQUARE / S  →  SCREENSHOT  #{shotCount}
          </button>
        </div>

        <div className="toasts">
          {[...toasts].reverse().map((t) => (
            <div key={t.id} style={{ color: t.color }}>
              {t.msg}
            </div>
          ))}
        </div>

        <aside className="side">
          <section className="panel attitude-panel">
            <h2>ATTITUDE  ·  MPU-6050</h2>
            <div className="attitude-row">
              <Attitude pitch={imu.pitch} roll={imu.roll} />
              <div className="imu-vals">
                <span className="lbl">PITCH</span>
                <strong className="teal">
                  {imu.pitch >= 0 ? "+" : ""}
                  {imu.pitch.toFixed(1)}°
                </strong>
                <span className="lbl">ROLL</span>
                <strong className="amber">
                  {imu.roll >= 0 ? "+" : ""}
                  {imu.roll.toFixed(1)}°
                </strong>
              </div>
            </div>
          </section>

          <section className="panel cmd-panel">
            <h2>COMMAND</h2>
            <div className="cmd-row">
              <div className={`cmd-badge${mode === "STOP" ? " stop" : ""}`} style={{ background: cmdColor }}>
                {mode}
              </div>
              <SpeedArc pct={barPct} color={cmdColor} label={speed} />
            </div>
            <div className="cmd-meta">
              {Math.floor(barPct * 100)}%  {speed}us
            </div>
          </section>

          <section className="panel env-panel">
            <h2>ENVIRONMENT  ·  SIMULATED</h2>
            <div className="env-grid">
              {[
                ["AIR TEMP", `${sensors.temp.toFixed(1)}C`, "#ff823c", sensors.temp / 40],
                ["HUMIDITY", `${sensors.hum.toFixed(0)}%`, "#50a0ff", sensors.hum / 100],
                ["WATER TEMP", `${sensors.wtemp.toFixed(1)}C`, "#1dc896", sensors.wtemp / 30],
                ["DEPTH", `${sensors.depth.toFixed(1)}m`, "#a564ff", sensors.depth / 20],
              ].map(([label, val, color, pct]) => (
                <div key={label} className="env-item">
                  <span className="lbl">{label}</span>
                  <span style={{ color }}>{val}</span>
                  <div className="bar">
                    <div style={{ width: `${pct * 100}%`, background: color }} />
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="panel log-panel">
            <h2>COMMAND  LOG</h2>
            <div className="log">
              {[...log].reverse().map((row, i) => (
                <div key={`${row.ts}-${i}`} className="log-row">
                  <i style={{ background: CMD_COL[row.mode] || CMD_COL.STOP }} />
                  <div>
                    <b style={{ color: CMD_COL[row.mode] || CMD_COL.STOP }}>
                      {row.mode.padEnd(8)} {row.speed}us
                    </b>
                    <span>{row.ts}</span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
