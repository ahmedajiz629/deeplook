import { useEffect, useRef, useState } from "react";

function clamp(v, a, b) {
  return Math.max(a, Math.min(b, v));
}

function readPad() {
  const pads = navigator.getGamepads ? navigator.getGamepads() : [];
  const js = [...pads].find(Boolean);
  if (!js) return null;
  const btn = (i) => !!(js.buttons[i] && js.buttons[i].pressed);
  const val = (i) => (js.buttons[i] ? js.buttons[i].value : 0);
  let throttle = 0;
  if (js.axes.length > 5) throttle = clamp((js.axes[5] + 1) / 2, 0, 1);
  throttle = Math.max(throttle, val(7));
  return {
    id: js.id || "Gamepad",
    throttle,
    vlvr: btn(0),
    forward: btn(11) || btn(12),
    left: btn(14),
    right: btn(13) || btn(15),
    circle: btn(1),
    square: btn(2) || btn(3),
  };
}

export function useControls({ onRecord, onShot }) {
  const keys = useRef(Object.create(null));
  const virt = useRef(null);
  const prev = useRef({ circle: false, square: false });
  const recFn = useRef(onRecord);
  const shotFn = useRef(onShot);
  recFn.current = onRecord;
  shotFn.current = onShot;

  const [hasPad, setHasPad] = useState(false);
  const [padName, setPadName] = useState("");
  const [mode, setMode] = useState("STOP");
  const [speed, setSpeed] = useState(1000);

  useEffect(() => {
    const down = (e) => {
      keys.current[e.code] = true;
      if (e.repeat) return;
      if (e.code === "KeyR") recFn.current();
      if (e.code === "KeyS") shotFn.current();
    };
    const up = (e) => {
      keys.current[e.code] = false;
    };
    const blur = () => {
      keys.current = Object.create(null);
      virt.current = null;
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    const onPad = (e) => {
      setHasPad(true);
      setPadName(e.gamepad?.id || "Joystick");
    };
    const offPad = () => {
      setHasPad(false);
      setPadName("");
    };
    window.addEventListener("gamepadconnected", onPad);
    window.addEventListener("gamepaddisconnected", offPad);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
      window.removeEventListener("gamepadconnected", onPad);
      window.removeEventListener("gamepaddisconnected", offPad);
    };
  }, []);

  useEffect(() => {
    let raf;
    const tick = () => {
      const gp = readPad();
      setHasPad(!!gp);
      setPadName(gp ? gp.id : "");

      if (gp) {
        if (gp.circle && !prev.current.circle) recFn.current();
        if (gp.square && !prev.current.square) shotFn.current();
        prev.current = { circle: gp.circle, square: gp.square };
      } else {
        prev.current = { circle: false, square: false };
      }

      let next = "STOP";
      let spd = 1000;
      const k = keys.current;
      if (gp) {
        spd = Math.floor(1000 + gp.throttle * 500);
        if (gp.vlvr) next = "VLVR";
        else if (gp.forward) next = "FORWARD";
        else if (gp.left) next = "LEFT";
        else if (gp.right) next = "RIGHT";
      } else {
        spd = k.ShiftLeft || k.ShiftRight ? 1500 : 1000;
        if (virt.current) next = virt.current;
        else if (k.KeyV) next = "VLVR";
        else if (k.KeyW || k.ArrowUp) next = "FORWARD";
        else if (k.KeyA || k.ArrowLeft) next = "LEFT";
        else if (k.KeyD || k.ArrowRight) next = "RIGHT";
      }
      setMode(next);
      setSpeed(spd);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  const hold = (next) => {
    virt.current = next;
  };
  const release = () => {
    virt.current = null;
  };

  return { hasPad, padName, mode, speed, hold, release };
}
