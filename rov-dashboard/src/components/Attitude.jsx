import { useEffect, useRef } from "react";

export default function Attitude({ pitch = 0, roll = 0, radius = 90 }) {
  const ref = useRef(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas.getContext("2d");
    const size = radius * 2 + 4;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    canvas.style.width = `${size}px`;
    canvas.style.height = `${size}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const cx = size / 2;
    const cy = size / 2;
    const rollRad = (roll * Math.PI) / 180;

    ctx.clearRect(0, 0, size, size);
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.clip();

    ctx.translate(cx, cy);
    ctx.rotate(-rollRad);

    ctx.fillStyle = "rgb(20,80,160)";
    ctx.fillRect(-radius * 4, -radius * 4, radius * 8, radius * 8);

    const horizon = -pitch * 1.8;
    ctx.fillStyle = "rgb(110,70,20)";
    ctx.fillRect(-radius * 4, horizon, radius * 8, radius * 8);

    ctx.strokeStyle = "rgba(255,255,255,0.47)";
    ctx.lineWidth = 1;
    for (let deg = -30; deg <= 30; deg += 10) {
      if (deg === 0) continue;
      const py = -(pitch - deg) * 1.8;
      const lw = deg % 20 === 0 ? 20 : 12;
      ctx.beginPath();
      ctx.moveTo(-lw, py);
      ctx.lineTo(lw, py);
      ctx.stroke();
    }

    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(-radius * 2, horizon);
    ctx.lineTo(radius * 2, horizon);
    ctx.stroke();
    ctx.restore();

    ctx.strokeStyle = "rgb(255,215,0)";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(cx - 50, cy);
    ctx.lineTo(cx - 16, cy);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(cx + 16, cy);
    ctx.lineTo(cx + 50, cy);
    ctx.stroke();
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(cx - 6, cy);
    ctx.lineTo(cx + 6, cy);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(cx, cy - 6);
    ctx.lineTo(cx, cy + 6);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(cx, cy, 4, 0, Math.PI * 2);
    ctx.stroke();

    ctx.strokeStyle = "rgb(45,50,65)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.stroke();
  }, [pitch, roll, radius]);

  return <canvas ref={ref} className="attitude" />;
}
