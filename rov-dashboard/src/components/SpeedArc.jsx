import { useEffect, useRef } from "react";

export default function SpeedArc({ pct = 0, color = "#646978", label = "1000" }) {
  const ref = useRef(null);
  const r = 28;

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas.getContext("2d");
    const size = 64;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    canvas.style.width = `${size}px`;
    canvas.style.height = `${size}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const cx = size / 2;
    const cy = size / 2;
    ctx.clearRect(0, 0, size, size);

    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.strokeStyle = "rgb(32,36,46)";
    ctx.lineWidth = 8;
    ctx.stroke();

    if (pct > 0) {
      const start = (140 * Math.PI) / 180;
      const end = start - ((260 * pct * Math.PI) / 180);
      ctx.beginPath();
      ctx.arc(cx, cy, r, start, end, true);
      ctx.strokeStyle = color;
      ctx.lineWidth = 8;
      ctx.lineCap = "butt";
      ctx.stroke();
    }

    ctx.fillStyle = "rgb(220,225,235)";
    ctx.font = "13px ui-monospace, Consolas, monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(String(label), cx, cy);
  }, [pct, color, label]);

  return <canvas ref={ref} className="speed-arc" />;
}
