import pygame
import socket
import threading
import time
import cv2
import numpy as np
import urllib.request
import math
import os
import random
from datetime import datetime

PI_IP      = "192.168.137.10"
MOTOR_PORT = 5001
IMU_PORT   = 5002
CAM_URL    = f"http://{PI_IP}:5000/video"

save_dir = os.path.join(os.path.expanduser("~"), "rov_captures")
os.makedirs(save_dir, exist_ok=True)
print("Saving captures to:", save_dir)

# ── CAMERA ────────────────────────────────────────────────────────────
latest_frame = [None]

def recv_video():
    while True:
        try:
            stream = urllib.request.urlopen(CAM_URL, timeout=5)
            buf = b""
            while True:
                buf += stream.read(4096)
                a  = buf.find(b'\xff\xd8')
                b_ = buf.find(b'\xff\xd9')
                if a != -1 and b_ != -1:
                    jpg = buf[a:b_+2]
                    buf = buf[b_+2:]
                    frame = cv2.imdecode(
                        np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                    if frame is not None:
                        latest_frame[0] = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        except:
            time.sleep(2)

threading.Thread(target=recv_video, daemon=True).start()

# ── MOTOR SOCKET ──────────────────────────────────────────────────────
cmd_sock  = [None]
sock_lock = threading.Lock()

def connect_motor():
    while True:
        try:
            s = socket.socket()
            s.settimeout(5)
            s.connect((PI_IP, MOTOR_PORT))
            s.settimeout(None)
            with sock_lock:
                cmd_sock[0] = s
            print("Motor connected")
            return
        except:
            time.sleep(2)

def send_cmd(msg):
    with sock_lock:
        s = cmd_sock[0]
    if s is None:
        return
    try:
        s.sendall(msg.encode())
    except:
        with sock_lock:
            cmd_sock[0] = None
        threading.Thread(target=connect_motor, daemon=True).start()

threading.Thread(target=connect_motor, daemon=True).start()

# ── IMU SOCKET ────────────────────────────────────────────────────────
imu_data = {"pitch": 0.0, "roll": 0.0}

def recv_imu():
    while True:
        try:
            s = socket.socket()
            s.connect((PI_IP, IMU_PORT))
            buf = ""
            while True:
                buf += s.recv(256).decode(errors="ignore")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if line.startswith("IMU"):
                        parts = line.split()
                        if len(parts) == 3:
                            imu_data["pitch"] = float(parts[1])
                            imu_data["roll"]  = float(parts[2])
        except:
            time.sleep(2)

threading.Thread(target=recv_imu, daemon=True).start()

# ── FAKE SENSORS ──────────────────────────────────────────────────────
temp  = 24.0
hum   = 62.0
wtemp = 18.0
depth = 0.0

def update_sensors():
    global temp, hum, wtemp, depth
    temp  += random.uniform(-0.2, 0.2)
    hum   += random.uniform(-0.5, 0.5)
    wtemp += random.uniform(-0.1, 0.1)
    depth += random.uniform(-0.05, 0.05)
    temp  = max(18, min(40, temp))
    hum   = max(30, min(95, hum))
    wtemp = max(10, min(30, wtemp))
    depth = max(0,  min(20, depth))

# ── PYGAME SETUP ──────────────────────────────────────────────────────
pygame.init()
pygame.joystick.init()
try:
    js     = pygame.joystick.Joystick(0)
    js.init()
    HAS_JS = True
except:
    HAS_JS = False

WIN_W, WIN_H = 1280, 660
screen = pygame.display.set_mode((WIN_W, WIN_H))
pygame.display.set_caption("ROV Dashboard")

font_title = pygame.font.SysFont("monospace", 11)
font_val   = pygame.font.SysFont("monospace", 22, bold=True)
font_md    = pygame.font.SysFont("monospace", 15)
font_sm    = pygame.font.SysFont("monospace", 13)
clock_tk   = pygame.time.Clock()

# ── COLORS ────────────────────────────────────────────────────────────
BG     = (12,  14,  18)
PANEL  = (20,  23,  30)
SURF   = (32,  36,  46)
BORDER = (45,  50,  65)
WHITE  = (220, 225, 235)
GRAY   = (90,  95,  110)
TEAL   = (29,  200, 150)
BLUE   = (60,  140, 255)
RED    = (220,  65,  65)
AMBER  = (255, 175,  50)
GREEN  = (80,  210,  90)
PURPLE = (165, 100, 255)

CMD_COL = {
    "FORWARD": GREEN,
    "LEFT":    BLUE,
    "RIGHT":   AMBER,
    "VLVR":    PURPLE,
    "STOP":    (100, 105, 120),
}

# ── STATE ─────────────────────────────────────────────────────────────
log           = []
mode          = "STOP"
speed         = 1000
shot_count    = 0
rec_count     = 0
is_recording  = False
rec_start     = 0.0
video_writer  = [None]
flash_timer   = 0
toasts        = []
frame_count   = 0

def clamp(v, a, b):
    return max(a, min(b, v))

def add_toast(msg, color=TEAL):
    toasts.append({"msg": msg, "color": color, "expire": time.time() + 3.5})

def draw_rounded_rect(surf, color, rect, r=8, border=0, border_color=None):
    pygame.draw.rect(surf, color, rect, border_radius=r)
    if border and border_color:
        pygame.draw.rect(surf, border_color, rect, border, border_radius=r)

# ── ATTITUDE INDICATOR ────────────────────────────────────────────────
def draw_attitude(surf, cx, cy, radius, pitch, roll):
    ai       = pygame.Surface((radius*2, radius*2), pygame.SRCALPHA)
    horizon  = radius - pitch * 1.8
    roll_rad = math.radians(roll)

    pygame.draw.rect(ai, (20, 80, 160), (0, 0, radius*2, radius*2))

    gnd = pygame.Surface((radius*6, radius*6))
    gnd.fill((110, 70, 20))
    gnd = pygame.transform.rotate(gnd, roll)
    gw, gh = gnd.get_size()
    ai.blit(gnd, (radius - gw//2, int(radius - horizon) - gh//2))

    for deg in range(-30, 31, 10):
        if deg == 0:
            continue
        py2 = radius - (pitch - deg) * 1.8
        lw  = 20 if deg % 20 == 0 else 12
        x1  = int(radius + (-lw) * math.cos(roll_rad) - (py2-radius) * math.sin(roll_rad))
        y1  = int(py2   + (-lw) * math.sin(roll_rad) + (py2-radius) * math.cos(roll_rad))
        x2  = int(radius + lw   * math.cos(roll_rad) - (py2-radius) * math.sin(roll_rad))
        y2  = int(py2   + lw    * math.sin(roll_rad) + (py2-radius) * math.cos(roll_rad))
        pygame.draw.line(ai, (255, 255, 255, 120), (x1,y1), (x2,y2), 1)

    hx1 = int(radius + (-radius*2) * math.cos(roll_rad))
    hy1 = int(horizon + (-radius*2) * math.sin(roll_rad))
    hx2 = int(radius + (radius*2)  * math.cos(roll_rad))
    hy2 = int(horizon + (radius*2)  * math.sin(roll_rad))
    pygame.draw.line(ai, (255,255,255), (hx1,hy1), (hx2,hy2), 2)

    mask = pygame.Surface((radius*2, radius*2), pygame.SRCALPHA)
    pygame.draw.circle(mask, (255,255,255,255), (radius,radius), radius)
    ai.blit(mask, (0,0), special_flags=pygame.BLEND_RGBA_MIN)
    surf.blit(ai, (cx-radius, cy-radius))

    pygame.draw.line(surf, (255,215,0), (cx-50, cy), (cx-16, cy), 3)
    pygame.draw.line(surf, (255,215,0), (cx+16, cy), (cx+50, cy), 3)
    pygame.draw.line(surf, (255,215,0), (cx-6,  cy), (cx+6,  cy), 2)
    pygame.draw.line(surf, (255,215,0), (cx,  cy-6), (cx,  cy+6), 2)
    pygame.draw.circle(surf, (255,215,0), (cx,cy), 4, 2)
    pygame.draw.circle(surf, BORDER, (cx,cy), radius, 2)

# ── SPEED ARC ─────────────────────────────────────────────────────────
def draw_speed_arc(surf, cx, cy, r, pct, color):
    pygame.draw.circle(surf, SURF, (cx,cy), r, 8)
    if pct > 0:
        start_a = math.radians(220)
        sweep   = math.radians(-260 * pct)
        steps   = max(2, int(abs(sweep) / 0.05))
        for i in range(steps):
            a1 = start_a + sweep * i / steps
            a2 = start_a + sweep * (i+1) / steps
            x1 = int(cx + r * math.cos(a1))
            y1 = int(cy - r * math.sin(a1))
            x2 = int(cx + r * math.cos(a2))
            y2 = int(cy - r * math.sin(a2))
            pygame.draw.line(surf, color, (x1,y1), (x2,y2), 8)

# ── HELPERS ───────────────────────────────────────────────────────────
def section(surf, x, y, w, h, title=None):
    draw_rounded_rect(surf, PANEL, (x,y,w,h), r=10, border=1, border_color=BORDER)
    if title:
        t = font_title.render(title.upper(), True, GRAY)
        surf.blit(t, (x+12, y+8))

def bar(surf, x, y, w, pct, color, h=6):
    draw_rounded_rect(surf, SURF, (x,y,w,h), r=3)
    if pct > 0.01:
        draw_rounded_rect(surf, color, (x,y,int(w*pct),h), r=3)

# ── MAIN LOOP ─────────────────────────────────────────────────────────
while True:
    clock_tk.tick(30)
    frame_count += 1
    now = time.time()

    for e in pygame.event.get():
        if e.type == pygame.QUIT:
            if video_writer[0]:
                video_writer[0].release()
            pygame.quit()
            exit()

        if e.type == pygame.JOYBUTTONDOWN:
            # CIRCLE (button 1) = record toggle
            if e.button == 1:
                if not is_recording:
                    is_recording = True
                    rec_start    = now
                    vfname = os.path.join(
                        save_dir,
                        f"ROV_REC_{datetime.now().strftime('%H%M%S')}.mp4")
                    video_writer[0] = cv2.VideoWriter(
                        vfname,
                        cv2.VideoWriter_fourcc(*'mp4v'),
                        20, (640, 480))
                    add_toast(f"● REC STARTED  {os.path.basename(vfname)}", RED)
                else:
                    is_recording = False
                    rec_count   += 1
                    if video_writer[0]:
                        video_writer[0].release()
                        video_writer[0] = None
                    dur = int(now - rec_start)
                    add_toast(f"■ SAVED ROV_REC_{rec_count:03d}.mp4  ({dur}s)", AMBER)

            # SQUARE (button 3) = screenshot
            if e.button == 3:
                shot_count  += 1
                flash_timer  = 10
                fname = os.path.join(
                    save_dir,
                    f"ROV_{datetime.now().strftime('%H%M%S')}_{shot_count:03d}.jpg")
                pygame.image.save(screen, fname)
                add_toast(f"■ SCREENSHOT  {os.path.basename(fname)}", GREEN)

    # joystick
    if HAS_JS:
        pygame.event.pump()
        r2       = js.get_axis(5)
        throttle = clamp((r2+1)/2, 0.0, 1.0)
        speed    = int(1000 + throttle * 500)
        new_mode = "STOP"
        if   js.get_button(0):  new_mode = "VLVR"
        elif js.get_button(11): new_mode = "FORWARD"
        elif js.get_button(14): new_mode = "LEFT"
        elif js.get_button(13): new_mode = "RIGHT"
    else:
        speed    = 1000
        new_mode = "STOP"

    if new_mode != mode:
        mode = new_mode
        log.append((mode, speed, time.strftime("%H:%M:%S")))
        if len(log) > 8:
            log.pop(0)

    send_cmd(f"{mode} {speed}\n")

    if frame_count % 60 == 0:
        update_sensors()

    # ── DRAW ──────────────────────────────────────────────────────────
    screen.fill(BG)

    # header
    draw_rounded_rect(screen, PANEL, (0,0,WIN_W,36), r=0)
    pygame.draw.line(screen, BORDER, (0,36), (WIN_W,36), 1)
    ht = font_md.render("ROV  CONTROL  DASHBOARD", True, TEAL)
    screen.blit(ht, (WIN_W//2 - ht.get_width()//2, 9))
    ct = font_sm.render(time.strftime("%H:%M:%S"), True, GRAY)
    screen.blit(ct, (WIN_W - ct.get_width() - 14, 11))
    connected = cmd_sock[0] is not None
    dc = GREEN if connected else RED
    pygame.draw.circle(screen, dc, (16,18), 5)
    screen.blit(font_sm.render("MOTOR OK" if connected else "NO MOTOR", True, dc), (25,11))

    TOP = 44

    # ── CAMERA ────────────────────────────────────────────────────────
    CAM_X, CAM_Y, CAM_W, CAM_H = 8, TOP, 640, 480
    draw_rounded_rect(screen, PANEL,
                      (CAM_X-2, CAM_Y-2, CAM_W+4, CAM_H+4),
                      r=10, border=1, border_color=BORDER)

    if latest_frame[0] is not None:
        f = pygame.surfarray.make_surface(
            np.transpose(latest_frame[0], (1,0,2)))
        f = pygame.transform.scale(f, (CAM_W, CAM_H))
        screen.blit(f, (CAM_X, CAM_Y))
        if is_recording and video_writer[0] is not None:
            bgr = cv2.cvtColor(latest_frame[0], cv2.COLOR_RGB2BGR)
            bgr = cv2.resize(bgr, (640, 480))
            video_writer[0].write(bgr)
    else:
        draw_rounded_rect(screen, (18,20,28), (CAM_X, CAM_Y, CAM_W, CAM_H), r=8)
        nm = font_md.render("waiting for camera  192.168.137.10:5000", True, (50,55,70))
        screen.blit(nm, (CAM_X + CAM_W//2 - nm.get_width()//2,
                         CAM_Y + CAM_H//2))

    # flash
    if flash_timer > 0:
        fl = pygame.Surface((CAM_W, CAM_H))
        fl.fill((255,255,255))
        fl.set_alpha(int(flash_timer/10*210))
        screen.blit(fl, (CAM_X, CAM_Y))
        flash_timer -= 1

    # recording overlay
    if is_recording:
        elapsed = int(now - rec_start)
        m_, s_  = divmod(elapsed, 60)
        if (frame_count//15) % 2 == 0:
            pygame.draw.circle(screen, RED, (CAM_X+18, CAM_Y+18), 8)
        rt = font_md.render(f" REC  {m_:02d}:{s_:02d}", True, RED)
        screen.blit(rt, (CAM_X+30, CAM_Y+10))

    # buttons
    BTN_Y = CAM_Y + CAM_H + 6
    BTN_H = 36
    rec_col = RED if is_recording else GRAY
    draw_rounded_rect(screen, PANEL, (CAM_X, BTN_Y, 314, BTN_H),
                      r=8, border=1, border_color=rec_col)
    pygame.draw.circle(screen, rec_col,
                       (CAM_X+22, BTN_Y+18), 10, 0 if is_recording else 2)
    screen.blit(font_sm.render("  CIRCLE  →  RECORD / STOP", True, rec_col),
                (CAM_X+38, BTN_Y+10))

    draw_rounded_rect(screen, PANEL, (CAM_X+322, BTN_Y, 318, BTN_H),
                      r=8, border=1, border_color=GRAY)
    pygame.draw.rect(screen, GRAY, (CAM_X+334, BTN_Y+8, 20, 20), 2)
    screen.blit(font_sm.render(f"  SQUARE  →  SCREENSHOT  #{shot_count}", True, GRAY),
                (CAM_X+360, BTN_Y+10))

    # toasts
    toasts[:] = [t for t in toasts if t["expire"] > now]
    for ti, t in enumerate(reversed(toasts)):
        screen.blit(font_sm.render(t["msg"], True, t["color"]),
                    (CAM_X, BTN_Y+BTN_H+6+ti*18))

    # ── RIGHT PANEL ───────────────────────────────────────────────────
    RX = CAM_X + CAM_W + 14
    RW = WIN_W - RX - 8
    ry = TOP

    # attitude
    A_H = 260
    section(screen, RX, ry, RW, A_H, "ATTITUDE  ·  MPU-6050")
    AI_R  = 90
    ai_cx = RX + AI_R + 16
    ai_cy = ry + 22 + AI_R + 4
    draw_attitude(screen, ai_cx, ai_cy, AI_R,
                  imu_data["pitch"], imu_data["roll"])
    vx = ai_cx + AI_R + 14
    vy = ry + 50
    screen.blit(font_title.render("PITCH", True, GRAY), (vx, vy))
    screen.blit(font_val.render(f"{imu_data['pitch']:+.1f}°", True, TEAL), (vx, vy+12))
    vy += 56
    screen.blit(font_title.render("ROLL", True, GRAY), (vx, vy))
    screen.blit(font_val.render(f"{imu_data['roll']:+.1f}°", True, AMBER), (vx, vy+12))
    ry += A_H + 8

    # command
    C_H = 116
    section(screen, RX, ry, RW, C_H, "COMMAND")
    col = CMD_COL.get(mode, GRAY)
    draw_rounded_rect(screen, col, (RX+8, ry+26, RW-16, 46), r=8)
    lbl = font_val.render(mode, True, BG)
    screen.blit(lbl, (RX+8+(RW-16-lbl.get_width())//2, ry+36))
    arc_cx  = RX + RW - 44
    arc_cy  = ry + 26 + 23
    bar_pct = (speed-1000)/500
    draw_speed_arc(screen, arc_cx, arc_cy, 28, bar_pct, col)
    sv = font_sm.render(f"{speed}", True, WHITE)
    screen.blit(sv, (arc_cx - sv.get_width()//2, arc_cy - sv.get_height()//2))
    screen.blit(font_sm.render(f"{int(bar_pct*100)}%  {speed}us", True, GRAY),
                (RX+12, ry+78))
    ry += C_H + 8

    # sensors
    S_H = 110
    section(screen, RX, ry, RW, S_H, "ENVIRONMENT  ·  SIMULATED")
    sx    = RX+12
    sy    = ry+26
    col_w = (RW-24)//2
    pairs = [
        ("AIR TEMP",   f"{temp:.1f}C",  (255,130,60), temp/40),
        ("HUMIDITY",   f"{hum:.0f}%",   (80,160,255), hum/100),
        ("WATER TEMP", f"{wtemp:.1f}C", TEAL,         wtemp/30),
        ("DEPTH",      f"{depth:.1f}m", PURPLE,       depth/20),
    ]
    for i, (lbl2, val2, c2, pct2) in enumerate(pairs):
        cx2 = sx + (i%2)*col_w
        cy2 = sy + (i//2)*42
        screen.blit(font_title.render(lbl2, True, GRAY), (cx2, cy2))
        screen.blit(font_md.render(val2, True, c2), (cx2, cy2+12))
        bar(screen, cx2, cy2+30, col_w-10, pct2, c2)
    ry += S_H + 8

    # log
    L_H = WIN_H - ry - 8
    section(screen, RX, ry, RW, L_H, "COMMAND  LOG")
    ly = ry + 26
    for m2, sp2, ts2 in reversed(log):
        if ly + 30 > ry + L_H - 4:
            break
        c2 = CMD_COL.get(m2, GRAY)
        draw_rounded_rect(screen, SURF, (RX+8, ly, RW-16, 28), r=6)
        pygame.draw.rect(screen, c2, (RX+8, ly, 4, 28), border_radius=2)
        screen.blit(font_sm.render(f"{m2:<8} {sp2}us", True, c2), (RX+18, ly+4))
        screen.blit(font_sm.render(ts2, True, GRAY),               (RX+18, ly+17))
        ly += 32

    pygame.display.flip()
