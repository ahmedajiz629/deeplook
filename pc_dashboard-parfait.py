# ==============================================================================
#  PC CLIENT -- ROV CONTROL DASHBOARD  (Dark Grey Professional)
#  File: pc_dashboard.py
#  Connects to: DEEPLOOK  |  192.168.137.35
#
#  INSTALL:
#      import subprocess, sys
#      subprocess.run([sys.executable, "-m", "pip", "install",
#          "opencv-python", "Pillow", "requests", "numpy", "pygame"])
#
#  RUN:
#      1. pi_streamer.py must be running on the Pi
#      2. Plug PS4 controller via USB or Bluetooth
#      3. Press F5
# ==============================================================================

import os
import queue
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from datetime import datetime
import math

import cv2
import numpy as np
import requests
import pygame
from PIL import Image, ImageTk

# ------------------------------------------------------------------------------
# PI SETTINGS
# ------------------------------------------------------------------------------
PI_IP_ADDRESS = "192.168.137.10"
PI_NAME       = "DEEPLOOK"
STREAM_URL    = "http://" + PI_IP_ADDRESS + ":5000/video_feed"
MOTORS_URL    = "http://" + PI_IP_ADDRESS + ":5000/motors"
STOP_URL      = "http://" + PI_IP_ADDRESS + ":5000/stop"
GYRO_URL      = "http://" + PI_IP_ADDRESS + ":5000/gyro"
SNAPSHOT_DIR  = os.path.join(os.path.expanduser("~"), "Documents")

# ------------------------------------------------------------------------------
# ROV settings
# ------------------------------------------------------------------------------
ESC_STOP     = 1500
ESC_RANGE    = 300
SPEED_LIMIT  = 0.20
SEND_RATE_MS = 50
GYRO_RATE_MS = 100

# ------------------------------------------------------------------------------
# PS4 axis mapping
# ------------------------------------------------------------------------------
PS4_X        = 0
PS4_CIRCLE   = 1
PS4_SQUARE   = 2
PS4_TRIANGLE = 3
PS4_DEADZONE = 0.08

# ------------------------------------------------------------------------------
# Colour theme -- dark grey professional
# ------------------------------------------------------------------------------
C_BG         = "#1a1a1a"
C_PANEL      = "#242424"
C_PANEL2     = "#2e2e2e"
C_BORDER     = "#3a3a3a"
C_ACCENT     = "#00aaff"
C_ACCENT2    = "#0066cc"
C_TEXT       = "#e0e0e0"
C_SUBTEXT    = "#888888"
C_GREEN      = "#00cc66"
C_RED        = "#ff3333"
C_YELLOW     = "#ffaa00"
C_BTN        = "#2a2a2a"
C_BTN_HOV    = "#353535"

# ------------------------------------------------------------------------------
# Dashboard layout
# ------------------------------------------------------------------------------
REFRESH_MS   = 30
QUEUE_SIZE   = 2
VIDEO_W      = 480    # video feed width (quarter of 1920)
VIDEO_H      = 270    # video feed height (quarter of 1080)


# ==============================================================================
# MJPEG FETCHER
# ==============================================================================
class MJPEGFetcher(threading.Thread):
    def __init__(self, url, frame_queue, status_cb):
        super().__init__(daemon=True)
        self.url       = url
        self.queue     = frame_queue
        self.status_cb = status_cb
        self._stop     = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        self.status_cb("CONNECTING", C_YELLOW)
        while not self._stop.is_set():
            try:
                with requests.get(self.url, stream=True, timeout=10) as r:
                    r.raise_for_status()
                    self.status_cb("LIVE", C_GREEN)
                    buf = b""
                    for chunk in r.iter_content(chunk_size=4096):
                        if self._stop.is_set():
                            break
                        buf += chunk
                        s = buf.find(b"\xff\xd8")
                        e = buf.find(b"\xff\xd9")
                        if s != -1 and e != -1 and e > s:
                            jpg = buf[s:e+2]
                            buf = buf[e+2:]
                            arr = np.frombuffer(jpg, dtype=np.uint8)
                            f   = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                            if f is None:
                                continue
                            f = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
                            if self.queue.full():
                                try:
                                    self.queue.get_nowait()
                                except:
                                    pass
                            self.queue.put_nowait(f)
            except:
                self.status_cb("OFFLINE", C_RED)
                time.sleep(3)


# ==============================================================================
# PS4 CONTROLLER
# ==============================================================================
class PS4Controller(threading.Thread):
    def __init__(self, on_btn, on_axis, on_conn, on_disc):
        super().__init__(daemon=True)
        self.on_btn  = on_btn
        self.on_axis = on_axis
        self.on_conn = on_conn
        self.on_disc = on_disc
        self._stop   = threading.Event()
        self.connected = False

    def stop(self):
        self._stop.set()

    def run(self):
        pygame.init()
        pygame.joystick.init()
        while not self._stop.is_set():
            if pygame.joystick.get_count() > 0:
                if not self.connected:
                    j = pygame.joystick.Joystick(0)
                    j.init()
                    self.connected = True
                    self.on_conn(j.get_name())
                for ev in pygame.event.get():
                    if ev.type == pygame.JOYBUTTONDOWN:
                        self.on_btn(ev.button)
                    elif ev.type == pygame.JOYAXISMOTION:
                        v = ev.value if abs(ev.value) >= PS4_DEADZONE else 0.0
                        self.on_axis(ev.axis, round(v, 2))
                    elif ev.type == pygame.JOYDEVICEREMOVED:
                        self.connected = False
                        self.on_disc()
            else:
                if self.connected:
                    self.connected = False
                    self.on_disc()
                pygame.joystick.quit()
                pygame.joystick.init()
            time.sleep(0.016)
        pygame.quit()


# ==============================================================================
# MAIN DASHBOARD
# ==============================================================================
class ROVDashboard:

    def __init__(self, root):
        self.root        = root
        self.frame_queue = queue.Queue(maxsize=QUEUE_SIZE)
        self.photo_img   = None
        self.frame_count = 0
        self.fps_ts      = time.time()
        self.fps_val     = 0.0

        # Control state
        self.r2          = 0.0
        self.right_x     = 0.0
        self.right_y     = 0.0
        self.left_y      = 0.0

        # Gyro state
        self.pitch       = 0.0
        self.roll        = 0.0
        self.yaw         = 0.0

        self._build_ui()
        self._start_fetcher()
        self._start_controller()

        self.root.after(REFRESH_MS,   self._render_frame)
        self.root.after(SEND_RATE_MS, self._send_motors)
        self.root.after(GYRO_RATE_MS, self._fetch_gyro)
        self.root.after(50,           self._update_visuals)

    # --------------------------------------------------------------------------
    # UI BUILD
    # --------------------------------------------------------------------------
    def _build_ui(self):
        self.root.title("DEEPLOOK ROV -- Control Dashboard")
        self.root.configure(bg=C_BG)
        self.root.geometry("1280x780")
        self.root.minsize(1100, 700)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Fonts
        self.f_h1    = tkfont.Font(family="Courier", size=11, weight="bold")
        self.f_h2    = tkfont.Font(family="Courier", size=9,  weight="bold")
        self.f_body  = tkfont.Font(family="Courier", size=8)
        self.f_big   = tkfont.Font(family="Courier", size=18, weight="bold")
        self.f_med   = tkfont.Font(family="Courier", size=12, weight="bold")
        self.f_small = tkfont.Font(family="Courier", size=7)

        # ── TOP BAR ────────────────────────────────────────────────────────
        top = tk.Frame(self.root, bg=C_PANEL, height=44)
        top.pack(fill=tk.X)
        top.pack_propagate(False)

        tk.Label(top, text="  DEEPLOOK ROV  --  CONTROL DASHBOARD",
                 font=self.f_h1, fg=C_ACCENT, bg=C_PANEL).pack(side=tk.LEFT, pady=10)

        self.clock_var = tk.StringVar()
        tk.Label(top, textvariable=self.clock_var,
                 font=self.f_body, fg=C_SUBTEXT, bg=C_PANEL).pack(side=tk.RIGHT, padx=16)

        # Status pills
        self.stream_var = tk.StringVar(value="OFFLINE")
        self.stream_lbl = tk.Label(top, textvariable=self.stream_var,
                                   font=self.f_h2, fg=C_RED, bg=C_PANEL)
        self.stream_lbl.pack(side=tk.RIGHT, padx=8)
        tk.Label(top, text="STREAM:", font=self.f_body,
                 fg=C_SUBTEXT, bg=C_PANEL).pack(side=tk.RIGHT)

        self.ctrl_var = tk.StringVar(value="OFFLINE")
        self.ctrl_lbl = tk.Label(top, textvariable=self.ctrl_var,
                                 font=self.f_h2, fg=C_RED, bg=C_PANEL)
        self.ctrl_lbl.pack(side=tk.RIGHT, padx=8)
        tk.Label(top, text="CTRL:", font=self.f_body,
                 fg=C_SUBTEXT, bg=C_PANEL).pack(side=tk.RIGHT, padx=(16,0))

        self._tick_clock()

        # ── MAIN AREA ──────────────────────────────────────────────────────
        main = tk.Frame(self.root, bg=C_BG)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)

        # LEFT COLUMN
        left = tk.Frame(main, bg=C_BG)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Video feed (quarter size)
        self._build_video(left)

        # Gyroscope display below video
        self._build_gyro(left)

        # Motor PWM below gyro
        self._build_motors_display(left)

        # RIGHT COLUMN
        right = tk.Frame(main, bg=C_BG, width=300)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        right.pack_propagate(False)

        self._build_controls(right)

        # ── BOTTOM BAR ─────────────────────────────────────────────────────
        bot = tk.Frame(self.root, bg=C_PANEL, height=26)
        bot.pack(fill=tk.X, side=tk.BOTTOM)
        bot.pack_propagate(False)

        self.footer_var = tk.StringVar(value="System ready.")
        tk.Label(bot, textvariable=self.footer_var,
                 font=self.f_small, fg=C_SUBTEXT, bg=C_PANEL,
                 padx=10).pack(side=tk.LEFT, pady=4)
        tk.Label(bot, text=STREAM_URL,
                 font=self.f_small, fg=C_SUBTEXT, bg=C_PANEL,
                 padx=10).pack(side=tk.RIGHT, pady=4)

    def _card(self, parent, title, height=None):
        """Styled card widget."""
        outer = tk.Frame(parent, bg=C_BORDER, bd=0)
        if height:
            outer.pack(fill=tk.X, pady=(0, 6))
        else:
            outer.pack(fill=tk.X, pady=(0, 6))

        inner = tk.Frame(outer, bg=C_PANEL, bd=0)
        inner.pack(fill=tk.BOTH, padx=1, pady=1)

        hdr = tk.Frame(inner, bg=C_PANEL2, height=24)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text="  " + title, font=self.f_h2,
                 fg=C_ACCENT, bg=C_PANEL2).pack(side=tk.LEFT, pady=3)

        body = tk.Frame(inner, bg=C_PANEL)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
        return body

    def _build_video(self, parent):
        outer = tk.Frame(parent, bg=C_BORDER)
        outer.pack(fill=tk.X, pady=(0, 6))

        inner = tk.Frame(outer, bg=C_PANEL)
        inner.pack(fill=tk.BOTH, padx=1, pady=1)

        hdr = tk.Frame(inner, bg=C_PANEL2, height=24)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text="  LIVE FEED  --  " + PI_NAME,
                 font=self.f_h2, fg=C_ACCENT, bg=C_PANEL2).pack(side=tk.LEFT, pady=3)
        self.fps_var = tk.StringVar(value="-- fps")
        tk.Label(hdr, textvariable=self.fps_var,
                 font=self.f_small, fg=C_SUBTEXT, bg=C_PANEL2).pack(side=tk.RIGHT, padx=8)

        # Fixed size video label
        self.video_lbl = tk.Label(inner, bg="black",
                                  text="Waiting for stream ...",
                                  fg=C_SUBTEXT, font=self.f_body,
                                  width=VIDEO_W, height=VIDEO_H)
        self.video_lbl.pack(padx=1, pady=1)
        self.video_lbl.configure(width=VIDEO_W, height=VIDEO_H)

    def _build_gyro(self, parent):
        body = self._card(parent, "GYROSCOPE  --  MPU6050")

        # 3 gauges side by side
        gauges = tk.Frame(body, bg=C_PANEL)
        gauges.pack(fill=tk.X)

        self.pitch_canvas = self._gyro_gauge(gauges, "PITCH")
        self.roll_canvas  = self._gyro_gauge(gauges, "ROLL")
        self.yaw_canvas   = self._gyro_gauge(gauges, "YAW")

        # Numeric values
        vals = tk.Frame(body, bg=C_PANEL)
        vals.pack(fill=tk.X, pady=(4, 0))

        self.pitch_var = tk.StringVar(value="0.0")
        self.roll_var  = tk.StringVar(value="0.0")
        self.yaw_var   = tk.StringVar(value="0.0")

        for var, label in [(self.pitch_var, "PITCH"),
                           (self.roll_var,  "ROLL"),
                           (self.yaw_var,   "YAW")]:
            col = tk.Frame(vals, bg=C_PANEL)
            col.pack(side=tk.LEFT, expand=True)
            tk.Label(col, text=label, font=self.f_small,
                     fg=C_SUBTEXT, bg=C_PANEL).pack()
            tk.Label(col, textvariable=var, font=self.f_med,
                     fg=C_ACCENT, bg=C_PANEL).pack()

    def _gyro_gauge(self, parent, label):
        """Small arc gauge for gyro."""
        frame = tk.Frame(parent, bg=C_PANEL)
        frame.pack(side=tk.LEFT, expand=True, padx=4)
        tk.Label(frame, text=label, font=self.f_small,
                 fg=C_SUBTEXT, bg=C_PANEL).pack()
        c = tk.Canvas(frame, width=80, height=80,
                      bg=C_PANEL, highlightthickness=0)
        c.pack()
        return c

    def _build_motors_display(self, parent):
        body = self._card(parent, "MOTOR PWM VALUES")

        rows = tk.Frame(body, bg=C_PANEL)
        rows.pack(fill=tk.X)

        self.motor_vars = {}
        motors = [
            ("HLF", "H.Left  Front", 0, 0),
            ("HLB", "H.Left  Back",  0, 1),
            ("HRF", "H.Right Front", 1, 0),
            ("HRB", "H.Right Back",  1, 1),
            ("VL",  "Vert. Left",    2, 0),
            ("VR",  "Vert. Right",   2, 1),
        ]

        for key, label, row, col in motors:
            cell = tk.Frame(rows, bg=C_PANEL2, relief=tk.FLAT)
            cell.grid(row=row, column=col, padx=3, pady=2, sticky="ew")
            rows.columnconfigure(col, weight=1)

            tk.Label(cell, text=label, font=self.f_small,
                     fg=C_SUBTEXT, bg=C_PANEL2, padx=6).pack(side=tk.LEFT)
            var = tk.StringVar(value="1500")
            self.motor_vars[key] = var
            tk.Label(cell, textvariable=var, font=self.f_h2,
                     fg=C_ACCENT, bg=C_PANEL2, padx=6).pack(side=tk.RIGHT)

    def _build_controls(self, parent):
        # Throttle
        body = self._card(parent, "R2  THROTTLE")
        self.throttle_var = tk.StringVar(value="0%")
        tk.Label(body, textvariable=self.throttle_var,
                 font=self.f_big, fg=C_ACCENT, bg=C_PANEL).pack()

        # Throttle bar
        self.throttle_bar = tk.Canvas(body, height=12, bg=C_PANEL2,
                                      highlightthickness=0)
        self.throttle_bar.pack(fill=tk.X, pady=(2, 0))

        # Joysticks
        body2 = self._card(parent, "JOYSTICK POSITION")
        sticks = tk.Frame(body2, bg=C_PANEL)
        sticks.pack()

        tk.Label(sticks, text="RIGHT STICK", font=self.f_small,
                 fg=C_SUBTEXT, bg=C_PANEL).grid(row=0, column=0, padx=10)
        tk.Label(sticks, text="LEFT STICK", font=self.f_small,
                 fg=C_SUBTEXT, bg=C_PANEL).grid(row=0, column=1, padx=10)

        self.right_canvas = tk.Canvas(sticks, width=90, height=90,
                                      bg=C_PANEL2, highlightthickness=1,
                                      highlightbackground=C_BORDER)
        self.right_canvas.grid(row=1, column=0, padx=10, pady=4)

        self.left_canvas = tk.Canvas(sticks, width=90, height=90,
                                     bg=C_PANEL2, highlightthickness=1,
                                     highlightbackground=C_BORDER)
        self.left_canvas.grid(row=1, column=1, padx=10, pady=4)

        # PS4 buttons display
        body3 = self._card(parent, "CONTROLLER BUTTONS")
        btn_row1 = tk.Frame(body3, bg=C_PANEL)
        btn_row1.pack()

        self.lbl_X  = self._ps4_btn(btn_row1, "X",  "#0044cc")
        self.lbl_O  = self._ps4_btn(btn_row1, "O",  "#cc0000")
        self.lbl_SQ = self._ps4_btn(btn_row1, "SQ", "#cc00cc")
        self.lbl_TR = self._ps4_btn(btn_row1, "TR", "#007700")

        tk.Label(body3, text="X=STOP  TR=SNAPSHOT  SQ=FULLSCREEN",
                 font=self.f_small, fg=C_SUBTEXT, bg=C_PANEL).pack(pady=(4, 0))

        # Action buttons
        body4 = self._card(parent, "ACTIONS")
        self._btn(body4, "EMERGENCY STOP",   C_RED,    self._estop)
        self._btn(body4, "Take Snapshot",    C_ACCENT, self._snapshot)
        self._btn(body4, "Fullscreen",       C_SUBTEXT, self._fullscreen)

    def _ps4_btn(self, parent, label, color):
        lbl = tk.Label(parent, text=label, font=self.f_h2,
                       fg=C_BG, bg=color,
                       width=3, padx=4, pady=3, relief=tk.FLAT)
        lbl.pack(side=tk.LEFT, padx=3)
        return lbl

    def _btn(self, parent, text, color, command):
        b = tk.Button(parent, text=text, font=self.f_h2,
                      fg=color, bg=C_BTN,
                      activeforeground=C_TEXT,
                      activebackground=C_BTN_HOV,
                      relief=tk.FLAT, bd=0,
                      padx=8, pady=7,
                      cursor="hand2", command=command)
        b.pack(fill=tk.X, pady=2)
        b.bind("<Enter>", lambda e: b.configure(bg=C_BTN_HOV))
        b.bind("<Leave>", lambda e: b.configure(bg=C_BTN))
        return b

    # --------------------------------------------------------------------------
    # Clock
    # --------------------------------------------------------------------------
    def _tick_clock(self):
        self.clock_var.set(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
        self.root.after(1000, self._tick_clock)

    # --------------------------------------------------------------------------
    # Threads
    # --------------------------------------------------------------------------
    def _start_fetcher(self):
        def cb(msg, color):
            self.stream_var.set(msg)
            self.root.after(0, lambda: self.stream_lbl.configure(fg=color))
        self.fetcher = MJPEGFetcher(STREAM_URL, self.frame_queue, cb)
        self.fetcher.start()

    def _start_controller(self):
        self.controller = PS4Controller(
            on_btn  = self._on_btn,
            on_axis = self._on_axis,
            on_conn = self._on_conn,
            on_disc = self._on_disc,
        )
        self.controller.start()

    # --------------------------------------------------------------------------
    # PS4 callbacks
    # --------------------------------------------------------------------------
    def _on_btn(self, btn):
        if btn == PS4_X:
            self.root.after(0, self._estop)
            self.root.after(0, lambda: self._flash(self.lbl_X))
        elif btn == PS4_TRIANGLE:
            self.root.after(0, self._snapshot)
            self.root.after(0, lambda: self._flash(self.lbl_TR))
        elif btn == PS4_SQUARE:
            self.root.after(0, self._fullscreen)
            self.root.after(0, lambda: self._flash(self.lbl_SQ))
        elif btn == PS4_CIRCLE:
            self.root.after(0, lambda: self._flash(self.lbl_O))

    def _on_axis(self, axis, value):
        if axis == 5:      # R2 throttle
            self.r2 = (value + 1) / 2
            pct = int(self.r2 * 100)
            self.root.after(0, lambda: self.throttle_var.set(str(pct) + "%"))
        elif axis == 3:    # right stick X -- turn
            self.right_x = value
        elif axis == 4:    # right stick Y -- forward/back
            self.right_y = value
        elif axis == 1:    # left stick Y  -- dive/surface
            self.left_y = value

    def _on_conn(self, name):
        self.root.after(0, lambda: self.ctrl_var.set("ONLINE"))
        self.root.after(0, lambda: self.ctrl_lbl.configure(fg=C_GREEN))
        self.root.after(0, lambda: self.footer_var.set("PS4 connected: " + name))

    def _on_disc(self):
        self._estop()
        self.root.after(0, lambda: self.ctrl_var.set("OFFLINE"))
        self.root.after(0, lambda: self.ctrl_lbl.configure(fg=C_RED))
        self.root.after(0, lambda: self.footer_var.set("Controller disconnected -- motors stopped!"))

    def _flash(self, lbl):
        orig = lbl.cget("bg")
        lbl.configure(bg="white")
        self.root.after(150, lambda: lbl.configure(bg=orig))

    # --------------------------------------------------------------------------
    # Motor calculation
    # --------------------------------------------------------------------------
    def _calc_motors(self):
        t   = self.r2 * SPEED_LIMIT
        fwd = -self.right_y * t
        trn =  self.right_x * t
        div =  self.left_y  * t

        hlf = int(ESC_STOP + (fwd + trn) * ESC_RANGE)
        hlb = int(ESC_STOP + (fwd + trn) * ESC_RANGE)
        hrf = int(ESC_STOP + (fwd - trn) * ESC_RANGE)
        hrb = int(ESC_STOP + (fwd - trn) * ESC_RANGE)
        vl  = int(ESC_STOP + div * ESC_RANGE)
        vr  = int(ESC_STOP + div * ESC_RANGE)

        hi = int(ESC_STOP + ESC_RANGE * SPEED_LIMIT)
        lo = int(ESC_STOP - ESC_RANGE * SPEED_LIMIT)

        def cl(v):
            return max(lo, min(hi, v))

        return {"hlf": cl(hlf), "hlb": cl(hlb),
                "hrf": cl(hrf), "hrb": cl(hrb),
                "vl":  cl(vl),  "vr":  cl(vr)}

    def _send_motors(self):
        vals = self._calc_motors()
        for k, v in vals.items():
            key = k.upper()
            if key in self.motor_vars:
                self.motor_vars[key].set(str(v))

        def _do():
            try:
                requests.post(MOTORS_URL, json=vals, timeout=0.1)
            except:
                pass
        threading.Thread(target=_do, daemon=True).start()
        self.root.after(SEND_RATE_MS, self._send_motors)

    # --------------------------------------------------------------------------
    # Gyro fetch
    # --------------------------------------------------------------------------
    def _fetch_gyro(self):
        def _do():
            try:
                r = requests.get(GYRO_URL, timeout=0.5)
                d = r.json()
                self.pitch = d.get("pitch", 0.0)
                self.roll  = d.get("roll",  0.0)
                self.yaw   = d.get("yaw",   0.0)
                self.root.after(0, self._update_gyro_display)
            except:
                pass
        threading.Thread(target=_do, daemon=True).start()
        self.root.after(GYRO_RATE_MS, self._fetch_gyro)

    def _update_gyro_display(self):
        self.pitch_var.set(str(round(self.pitch, 1)))
        self.roll_var.set(str(round(self.roll,  1)))
        self.yaw_var.set(str(round(self.yaw,   1)))
        self._draw_gauge(self.pitch_canvas, self.pitch, C_ACCENT)
        self._draw_gauge(self.roll_canvas,  self.roll,  C_GREEN)
        self._draw_gauge(self.yaw_canvas,   self.yaw,   C_YELLOW)

    def _draw_gauge(self, canvas, value, color):
        """Draw arc gauge showing angle."""
        canvas.delete("all")
        cx, cy, r = 40, 40, 30
        # Background arc
        canvas.create_arc(cx-r, cy-r, cx+r, cy+r,
                          start=0, extent=270,
                          outline=C_BORDER, width=4, style=tk.ARC)
        # Value arc -- clamp to -180/180
        v     = max(-180, min(180, value))
        extent = (v / 180.0) * 135
        canvas.create_arc(cx-r, cy-r, cx+r, cy+r,
                          start=135, extent=extent,
                          outline=color, width=4, style=tk.ARC)
        # Center dot
        canvas.create_oval(cx-3, cy-3, cx+3, cy+3,
                           fill=color, outline="")

    # --------------------------------------------------------------------------
    # Visual updates
    # --------------------------------------------------------------------------
    def _update_visuals(self):
        self._draw_stick(self.right_canvas, self.right_x, self.right_y)
        self._draw_stick(self.left_canvas,  0.0,          self.left_y)
        self._draw_throttle_bar()
        self.root.after(50, self._update_visuals)

    def _draw_stick(self, canvas, x, y):
        canvas.delete("all")
        cx, cy, r = 45, 45, 35
        # Outer ring
        canvas.create_oval(cx-r, cy-r, cx+r, cy+r,
                           outline=C_BORDER, width=2)
        # Cross
        canvas.create_line(cx, cy-r, cx, cy+r, fill=C_BORDER, width=1)
        canvas.create_line(cx-r, cy, cx+r, cy, fill=C_BORDER, width=1)
        # Dot
        dx = cx + int(x * r)
        dy = cy + int(y * r)
        canvas.create_oval(dx-6, dy-6, dx+6, dy+6,
                           fill=C_ACCENT, outline=C_TEXT, width=1)

    def _draw_throttle_bar(self):
        self.throttle_bar.delete("all")
        w = self.throttle_bar.winfo_width()
        if w < 2:
            return
        fill = int(w * self.r2)
        color = C_GREEN if self.r2 < 0.5 else C_YELLOW if self.r2 < 0.8 else C_RED
        self.throttle_bar.create_rectangle(0, 0, fill, 12, fill=color, outline="")

    # --------------------------------------------------------------------------
    # Frame render
    # --------------------------------------------------------------------------
    def _render_frame(self):
        try:
            frame = self.frame_queue.get_nowait()
        except queue.Empty:
            self.root.after(REFRESH_MS, self._render_frame)
            return

        # Resize to fixed VIDEO_W x VIDEO_H
        pil = Image.fromarray(frame).resize((VIDEO_W, VIDEO_H), Image.LANCZOS)
        self.photo_img = ImageTk.PhotoImage(pil)
        self.video_lbl.configure(image=self.photo_img, text="",
                                 width=VIDEO_W, height=VIDEO_H)

        self.frame_count += 1
        if self.frame_count % 30 == 0:
            now          = time.time()
            self.fps_val = 30 / max(now - self.fps_ts, 1e-6)
            self.fps_ts  = now
            self.fps_var.set(str(round(self.fps_val, 1)) + " fps")

        self.root.after(REFRESH_MS, self._render_frame)

    # --------------------------------------------------------------------------
    # Actions
    # --------------------------------------------------------------------------
    def _estop(self):
        self.r2      = 0.0
        self.right_x = 0.0
        self.right_y = 0.0
        self.left_y  = 0.0
        self.throttle_var.set("0%")
        def _do():
            try:
                requests.post(STOP_URL, timeout=1)
            except:
                pass
        threading.Thread(target=_do, daemon=True).start()
        self.footer_var.set("EMERGENCY STOP -- all motors stopped!")

    def _snapshot(self):
        def _do():
            try:
                frame = self.frame_queue.get_nowait()
            except queue.Empty:
                self.root.after(0, lambda: self.footer_var.set("No frame available."))
                return
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(SNAPSHOT_DIR, "ROV_" + ts + ".jpg")
            bgr  = cv2.cvtColor(np.array(frame), cv2.COLOR_RGB2BGR)
            cv2.imwrite(path, bgr)
            print("[Snapshot] " + path)
            self.root.after(0, lambda: self.footer_var.set("Snapshot saved: " + path))
        threading.Thread(target=_do, daemon=True).start()

    def _fullscreen(self):
        f = self.root.attributes("-fullscreen")
        self.root.attributes("-fullscreen", not f)

    # --------------------------------------------------------------------------
    # Shutdown
    # --------------------------------------------------------------------------
    def _on_close(self):
        self._estop()
        time.sleep(0.2)
        self.fetcher.stop()
        self.controller.stop()
        self.root.destroy()


# ==============================================================================
# ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("  DEEPLOOK ROV Dashboard")
    print("  Stream  : " + STREAM_URL)
    print("  Controls:")
    print("    R2           = Throttle")
    print("    Right stick  = Forward/Back/Turn")
    print("    Left stick   = Dive/Surface")
    print("    X            = Emergency Stop")
    print("    Triangle     = Snapshot")
    print("    Square       = Fullscreen")
    print("=" * 60)

    root = tk.Tk()
    app  = ROVDashboard(root)
    root.mainloop()
