import { useCallback, useEffect, useRef, useState } from "react";
import Attitude from "./components/Attitude.jsx";
import { useControls } from "./hooks/useControls.js";
import { useRovSocket } from "./hooks/useRovSocket.js";
import "./App.css";

const CAM_PORT = 5000;

const CMD_COL = {
  FORWARD: "#3dd68c",
  BACK: "#ff6b6b",
  LEFT: "#5aa7ff",
  RIGHT: "#ffb44c",
  VLVR: "#c084fc",
  STOP: "#8b93a7",
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
  const types = ["video/webm;codecs=vp8", "video/webm", "video/webm;codecs=vp9", "video/mp4"];
  return types.find((t) => MediaRecorder.isTypeSupported(t)) || "";
}

function cameraSrc() {
  if (import.meta.env.DEV) return `http://deeplook.local:${CAM_PORT}/video`;
  return "/video";
}

function clamp(v, a, b) {
  return Math.max(a, Math.min(b, v));
}

function fmt(n, sign = false) {
  const v = n.toFixed(1);
  return sign && n >= 0 ? `+${v}` : v;
}

function isStandalone() {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true
  );
}

function installSteps() {
  const ua = navigator.userAgent;
  const ios =
    /iPad|iPhone|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  if (ios) return "Tap the Share button, then Add to Home Screen.";
  if (/^((?!chrome|android).)*safari/i.test(ua)) return "File → Add to Dock, or Share → Add to Dock.";
  return "Open the browser menu and choose Install app.";
}

function StatusDot({ ok, okLabel, badLabel, hint }) {
  return (
    <span className={`status ${ok ? "ok" : "bad"}`} title={hint || (ok ? okLabel : badLabel)}>
      <i />
      {ok ? okLabel : badLabel}
    </span>
  );
}

function HoldBtn({ label, hint, mode, hold, release, active }) {
  const start = (e) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    hold(mode);
  };
  return (
    <button
      type="button"
      className={`pad-btn ${active ? "on" : ""}`}
      aria-label={label}
      aria-pressed={active}
      onPointerDown={start}
      onPointerUp={release}
      onPointerCancel={release}
      onContextMenu={(e) => e.preventDefault()}
    >
      {hint}
    </button>
  );
}

export default function App() {
  const [clock, setClock] = useState(clockStr);
  const [log, setLog] = useState([]);
  const [shotCount, setShotCount] = useState(0);
  const [isRecording, setIsRecording] = useState(false);
  const [recLabel, setRecLabel] = useState("00:00");
  const [flash, setFlash] = useState(0);
  const [toasts, setToasts] = useState([]);
  const [camOk, setCamOk] = useState(false);
  const [railOpen, setRailOpen] = useState(true);
  const [installed, setInstalled] = useState(isStandalone);
  const [installHelp, setInstallHelp] = useState(false);
  const installPrompt = useRef(null);
  const [sensors, setSensors] = useState({
    temp: 24,
    hum: 62,
    wtemp: 18,
    depth: 0,
  });

  const camRef = useRef(null);
  const recCanvasRef = useRef(null);
  const recRef = useRef(null);
  const recLoop = useRef(0);
  const recStart = useRef(0);
  const lastMode = useRef("STOP");

  const camUrl = cameraSrc();
  const { wsOk, motorOk, imu, sendCmd } = useRovSocket();

  useEffect(() => {
    const onPrompt = (e) => {
      e.preventDefault();
      installPrompt.current = e;
    };
    const onInstalled = () => {
      installPrompt.current = null;
      setInstalled(true);
      setInstallHelp(false);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    const ua = navigator.userAgent;
    const safari =
      /iPad|iPhone|iPod/.test(ua) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1) ||
      /^((?!chrome|android).)*safari/i.test(ua);
    if (safari && !isStandalone() && !sessionStorage.getItem("deeplook-install-seen")) {
      sessionStorage.setItem("deeplook-install-seen", "1");
      setInstallHelp(true);
    }
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  const askInstall = useCallback(async () => {
    if (isStandalone()) {
      setInstalled(true);
      return;
    }
    const ev = installPrompt.current;
    if (ev) {
      ev.prompt();
      const choice = await ev.userChoice;
      installPrompt.current = null;
      if (choice.outcome === "accepted") setInstalled(true);
      return;
    }
    setInstallHelp((open) => !open);
  }, []);

  const addToast = useCallback((msg, color = "#3dd68c") => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, msg, color, expire: Date.now() + 3200 }]);
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
    ctx.fillStyle = "#0b0d12";
    ctx.fillRect(0, 0, 640, 480);
    try {
      if (cam && cam.naturalWidth) ctx.drawImage(cam, 0, 0, 640, 480);
    } catch {
      addToast("Camera blocked screenshot (CORS)", "#ffb44c");
    }
    canvas.toBlob((blob) => blob && downloadBlob(blob, name), "image/jpeg", 0.92);
    addToast(`Screenshot ${name}`, "#3dd68c");
  }, [addToast, shotCount]);

  const toggleRecord = useCallback(() => {
    if (recRef.current) {
      try {
        recRef.current.requestData();
      } catch {
        /* ignore */
      }
      recRef.current.stop();
      return;
    }
    const cam = camRef.current;
    const canvas = recCanvasRef.current;
    if (!canvas) {
      addToast("Recorder not ready", "#ff5d5d");
      return;
    }
    const ctx = canvas.getContext("2d", { alpha: false });
    const paint = () => {
      ctx.fillStyle = "#0b0d12";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      try {
        if (cam && cam.naturalWidth) ctx.drawImage(cam, 0, 0, canvas.width, canvas.height);
      } catch {
        /* tainted */
      }
    };
    paint();

    const stream = canvas.captureStream(25);
    const track = stream.getVideoTracks()[0];
    const mime = recMime();
    let recorder;
    try {
      recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : {});
    } catch {
      addToast("Recording not supported here", "#ff5d5d");
      return;
    }

    const draw = () => {
      paint();
      if (track && typeof track.requestFrame === "function") track.requestFrame();
      recLoop.current = requestAnimationFrame(draw);
    };

    const chunks = [];
    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size) chunks.push(e.data);
    };
    recorder.onerror = () => {
      cancelAnimationFrame(recLoop.current);
      recRef.current = null;
      setIsRecording(false);
      addToast("Recording failed", "#ff5d5d");
    };
    recorder.onstop = () => {
      cancelAnimationFrame(recLoop.current);
      recRef.current = null;
      setIsRecording(false);
      track?.stop();
      const type = recorder.mimeType || "video/webm";
      const ext = type.includes("mp4") ? "mp4" : "webm";
      const name = `ROV_REC_${fileStamp()}.${ext}`;
      const blob = new Blob(chunks, { type });
      if (!blob.size) {
        addToast("Recording was empty — try again", "#ff5d5d");
        return;
      }
      downloadBlob(blob, name);
      const dur = Math.floor((performance.now() - recStart.current) / 1000);
      addToast(`Saved ${name} (${dur}s, ${(blob.size / 1024).toFixed(0)} KB)`, "#ffb44c");
    };
    recLoop.current = requestAnimationFrame(draw);
    recorder.start(200);
    recRef.current = recorder;
    recStart.current = performance.now();
    setIsRecording(true);
    addToast("Recording", "#ff5d5d");
  }, [addToast]);

  const { hasPad, padName, mode, speed, throttle, hold, release } = useControls({
    onRecord: toggleRecord,
    onShot: takeShot,
  });

  useEffect(() => {
    const id = setInterval(() => setClock(clockStr()), 250);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const id = setInterval(() => {
      const cam = camRef.current;
      if (cam && cam.naturalWidth > 0) setCamOk(true);
    }, 400);
    return () => clearInterval(id);
  }, [camUrl]);

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
    const sent = speed <= 0 ? "STOP" : mode;
    sendCmd(sent, speed);
    if (sent !== lastMode.current) {
      lastMode.current = sent;
      setLog((rows) => {
        const next = [...rows, { mode: sent, speed, ts: clockStr() }];
        return next.slice(-10);
      });
    }
  }, [mode, speed, sendCmd]);

  useEffect(() => {
    if (window.innerWidth < 960) setRailOpen(false);
  }, []);

  const cmdColor = CMD_COL[mode] || CMD_COL.STOP;
  const barPct = speed <= 0 ? 0 : Math.max(0, (speed - 1000) / 500);
  const linked = motorOk;

  return (
    <div className={`shell${railOpen ? " rail-open" : ""}`}>
      <header className="topbar">
        <div className="top-left">
          <StatusDot ok={wsOk} okLabel="Link" badLabel="No link" />
          <StatusDot ok={linked} okLabel="Arduino" badLabel="No Arduino" />
          <StatusDot ok={camOk} okLabel="Camera" badLabel="No camera" />
          <StatusDot
            ok={hasPad}
            okLabel={padName ? padName.replace(/\s*\(.*\)$/, "").slice(0, 18) : "Joystick"}
            badLabel="No joystick"
            hint={hasPad ? padName : "Press any button on the controller to connect"}
          />
        </div>
        <div className="brand" aria-hidden="true">
          ROV
        </div>
        <div className="top-right">
          {!installed && (
            <button type="button" className="install-btn" onClick={askInstall}>
              Install
            </button>
          )}
          <time dateTime={clock}>{clock}</time>
          <button
            type="button"
            className={`icon-btn ${railOpen ? "on" : ""}`}
            aria-label={railOpen ? "Hide telemetry" : "Show telemetry"}
            aria-pressed={railOpen}
            onClick={() => setRailOpen((v) => !v)}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="4" width="7" height="16" rx="1.5" />
              <rect x="14" y="4" width="7" height="7" rx="1.5" />
              <rect x="14" y="13" width="7" height="7" rx="1.5" />
            </svg>
          </button>
        </div>
      </header>

      {installHelp && !installed && (
        <div className="install-help" role="dialog" aria-label="Install DeepLook">
          <p>
            {location.protocol === "https:"
              ? installSteps()
              : "Safari will not offer install over HTTP. Open https://deeplook.local/ then tap Share → Add to Home Screen (iPhone) or File → Add to Dock (Mac)."}
          </p>
          {location.protocol !== "https:" && (
            <a className="install-btn" href="https://deeplook.local/">
              Open https://deeplook.local
            </a>
          )}
          <button type="button" className="install-dismiss" onClick={() => setInstallHelp(false)}>
            Close
          </button>
        </div>
      )}

      <div className="body">
        <main className="stage">
          <img
            key={camUrl}
            ref={camRef}
            className="cam"
            src={camUrl}
            alt="ROV live camera"
            onLoad={() => setCamOk(true)}
            onError={() => setCamOk(false)}
          />
          <canvas ref={recCanvasRef} className="rec-canvas" width={640} height={480} />
          {!camOk && (
            <div className="cam-wait">
              <strong>Waiting for camera</strong>
              <span>{camUrl}</span>
            </div>
          )}
          {flash > 0 && <div className="flash" style={{ opacity: (flash / 10) * 0.78 }} />}

          <div className="scrim top" />
          <div className="scrim bot" />

          {isRecording && (
            <div className="rec-badge" aria-live="polite">
              <span className="rec-dot" />
              REC {recLabel}
            </div>
          )}

          <div className="hud-att">
            <Attitude pitch={imu.pitch} roll={imu.roll} radius={52} />
            <div>
              <small>PITCH</small>
              <b className="teal">{fmt(imu.pitch, true)}°</b>
              <small>ROLL</small>
              <b className="amber">{fmt(imu.roll, true)}°</b>
            </div>
          </div>

          <div className="hud-readouts">
            <div>
              <small>DEPTH</small>
              <b>{sensors.depth.toFixed(1)} m</b>
            </div>
            <div>
              <small>WATER</small>
              <b>{sensors.wtemp.toFixed(1)}°C</b>
            </div>
          </div>

          <div className="hud-cmd">
            <div className={`cmd-pill${mode === "STOP" ? " stop" : ""}`} style={{ color: cmdColor }}>
              {mode}
            </div>
            <div className="throttle" aria-label={`Throttle ${Math.round(barPct * 100)} percent`}>
              <span style={{ width: `${barPct <= 0 ? 0 : Math.max(6, barPct * 100)}%`, background: cmdColor }} />
            </div>
            <small>
              {speed} µs
              {hasPad ? `  ·  R2 ${Math.round(throttle * 100)}%` : ""}
            </small>
          </div>

          <div className="pad" aria-label="Drive">
            <span />
            <HoldBtn label="Forward" hint="▲" mode="FORWARD" hold={hold} release={release} active={mode === "FORWARD"} />
            <span />
            <HoldBtn label="Left" hint="◀" mode="LEFT" hold={hold} release={release} active={mode === "LEFT"} />
            <HoldBtn label="Vertical" hint="V" mode="VLVR" hold={hold} release={release} active={mode === "VLVR"} />
            <HoldBtn label="Right" hint="▶" mode="RIGHT" hold={hold} release={release} active={mode === "RIGHT"} />
            <span />
            <HoldBtn label="Back" hint="▼" mode="BACK" hold={hold} release={release} active={mode === "BACK"} />
            <span />
          </div>

          <div className="media-btns">
            <button
              type="button"
              className={`fab rec ${isRecording ? "on" : ""}`}
              aria-label={isRecording ? "Stop recording" : "Start recording"}
              title="Record (R)"
              onClick={toggleRecord}
            >
              <span />
            </button>
            <button
              type="button"
              className="fab shot"
              aria-label="Take screenshot"
              title="Screenshot (S)"
              onClick={takeShot}
            >
              <i />
            </button>
          </div>

          <div className="toasts" aria-live="polite">
            {[...toasts].reverse().map((t) => (
              <div key={t.id} style={{ "--c": t.color }}>
                {t.msg}
              </div>
            ))}
          </div>
        </main>

        <aside className="rail" aria-label="Telemetry">
          <section>
            <h2>Environment</h2>
            <div className="env-grid">
              {[
                ["Air", `${sensors.temp.toFixed(1)}°C`, "#ff8a4c", sensors.temp / 40],
                ["Humidity", `${sensors.hum.toFixed(0)}%`, "#5aa7ff", sensors.hum / 100],
                ["Water", `${sensors.wtemp.toFixed(1)}°C`, "#3dd68c", sensors.wtemp / 30],
                ["Depth", `${sensors.depth.toFixed(1)} m`, "#c084fc", sensors.depth / 20],
              ].map(([label, val, color, pct]) => (
                <div key={label} className="env-item">
                  <span>{label}</span>
                  <strong style={{ color }}>{val}</strong>
                  <div className="bar">
                    <div style={{ width: `${pct * 100}%`, background: color }} />
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="log-sec">
            <h2>Command log</h2>
            <div className="log">
              {log.length === 0 && <p className="empty">Drive to see commands</p>}
              {[...log].reverse().map((row, i) => (
                <div key={`${row.ts}-${i}`} className="log-row">
                  <i style={{ background: CMD_COL[row.mode] || CMD_COL.STOP }} />
                  <b style={{ color: CMD_COL[row.mode] || CMD_COL.STOP }}>{row.mode}</b>
                  <span>{row.speed}µs</span>
                  <em>{row.ts}</em>
                </div>
              ))}
            </div>
          </section>

          <p className="hints">
            {hasPad
              ? "D-pad drive · R2 throttle · Circle record · Square screenshot"
              : "WASD drive · V vertical · Shift boost · R record · S screenshot"}
          </p>
        </aside>
      </div>

      {railOpen && <button type="button" className="sheet-bg" aria-label="Close telemetry" onClick={() => setRailOpen(false)} />}
    </div>
  );
}
