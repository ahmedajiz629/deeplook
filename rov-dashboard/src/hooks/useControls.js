import { useEffect, useRef, useState } from "react";

const DEAD = 0.45;
const DROP_FRAMES = 45;

function clamp(v, a, b) {
  return Math.max(a, Math.min(b, v));
}

function pressed(js, i) {
  return !!(js.buttons[i] && js.buttons[i].pressed);
}

function axis(js, i) {
  return js.axes[i] ?? 0;
}

function pickPad() {
  const list = navigator.getGamepads ? [...navigator.getGamepads()] : [];
  return list.find((p) => p && p.connected) || null;
}

const triggerAxis = new Map();

function axisAsTrigger(js, i) {
  if (i >= js.axes.length) return 0;
  const a = axis(js, i);
  const key = `${js.index}:${i}`;
  if (a <= -0.75) triggerAxis.set(key, true);
  if (!triggerAxis.get(key)) return 0;
  return clamp((a + 1) / 2, 0, 1);
}

function trigger(js) {
  const a5 = axisAsTrigger(js, 5);
  if (triggerAxis.get(`${js.index}:5`)) return a5;
  return clamp(js.buttons[7]?.value ?? 0, 0, 1);
}

function dpad(js) {
  let up = false;
  let down = false;
  let left = false;
  let right = false;

  if (js.mapping === "standard") {
    up = pressed(js, 12);
    down = pressed(js, 13);
    left = pressed(js, 14);
    right = pressed(js, 15);
  } else {
    up = pressed(js, 11);
    down = pressed(js, 12);
    right = pressed(js, 13);
    left = pressed(js, 14);
  }

  const x = js.mapping === "standard" ? axis(js, 6) : axis(js, 6);
  const y = js.mapping === "standard" ? axis(js, 7) : axis(js, 7);
  if (x < -DEAD) left = true;
  if (x > DEAD) right = true;
  if (y < -DEAD) up = true;
  if (y > DEAD) down = true;

  const lx = axis(js, 0);
  const ly = axis(js, 1);
  if (lx < -DEAD) left = true;
  if (lx > DEAD) right = true;
  if (ly < -DEAD) up = true;
  if (ly > DEAD) down = true;

  return { up, down, left, right };
}

function readPad() {
  const js = pickPad();
  if (!js) return null;
  const pad = dpad(js);
  return {
    id: js.id || "Joystick",
    throttle: trigger(js),
    vlvr: pressed(js, 0),
    forward: pad.up,
    back: pad.down,
    left: pad.left,
    right: pad.right,
    circle: pressed(js, 1),
    square: pressed(js, 2) || pressed(js, 3),
    driving: pad.up || pad.down || pad.left || pad.right || pressed(js, 0),
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

  const lastPad = useRef(null);
  const missing = useRef(0);

  const [hasPad, setHasPad] = useState(false);
  const [padName, setPadName] = useState("");
  const [mode, setMode] = useState("STOP");
  const [speed, setSpeed] = useState(0);
  const [throttle, setThrottle] = useState(0);

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
    const onPad = (e) => {
      lastPad.current = {
        id: e.gamepad?.id || "Joystick",
        throttle: 0,
        vlvr: false,
        forward: false,
        back: false,
        left: false,
        right: false,
        circle: false,
        square: false,
        driving: false,
      };
      missing.current = 0;
      setHasPad(true);
      setPadName(e.gamepad?.id || "Joystick");
    };
    const offPad = () => {
      lastPad.current = null;
      missing.current = DROP_FRAMES;
      setHasPad(false);
      setPadName("");
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
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
      let gp = readPad();
      if (gp) {
        lastPad.current = gp;
        missing.current = 0;
      } else if (lastPad.current && missing.current < DROP_FRAMES) {
        missing.current += 1;
        gp = { ...lastPad.current, driving: false, throttle: 0 };
      } else {
        lastPad.current = null;
        gp = null;
      }

      const connected = !!lastPad.current;
      setHasPad((was) => (was === connected ? was : connected));
      const name = lastPad.current?.id || "";
      setPadName((was) => (was === name ? was : name));

      if (gp) {
        if (gp.circle && !prev.current.circle) recFn.current();
        if (gp.square && !prev.current.square) shotFn.current();
        prev.current = { circle: gp.circle, square: gp.square };
      } else {
        prev.current = { circle: false, square: false };
      }

      let next = "STOP";
      let spd = 0;
      const k = keys.current;
      const r2 = gp?.throttle ?? 0;

      if (gp?.driving) {
        if (gp.vlvr) next = "VLVR";
        else if (gp.forward) next = "FORWARD";
        else if (gp.back) next = "BACK";
        else if (gp.left) next = "LEFT";
        else if (gp.right) next = "RIGHT";
      }

      if (next === "STOP") {
        if (virt.current) next = virt.current;
        else if (k.KeyV) next = "VLVR";
        else if (k.KeyW || k.ArrowUp) next = "FORWARD";
        else if (k.ArrowDown) next = "BACK";
        else if (k.KeyA || k.ArrowLeft) next = "LEFT";
        else if (k.KeyD || k.ArrowRight) next = "RIGHT";
      }

      if (r2 > 0.02) spd = Math.round(1000 + r2 * 500);
      else if (k.ShiftLeft || k.ShiftRight) spd = 1500;
      else spd = 0;

      setMode((was) => (was === next ? was : next));
      setSpeed((was) => (was === spd ? was : spd));
      setThrottle((was) => (Math.abs(was - r2) < 0.01 ? was : r2));
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

  return { hasPad, padName, mode, speed, throttle, hold, release };
}
