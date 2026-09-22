#!/usr/bin/env python3
"""Write 192 and 512 PNG app icons without extra deps."""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "public"


def png(path: Path, size: int) -> None:
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            raw.extend(pixel(x, y, size))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    chunks = [
        b"\x89PNG\r\n\x1a\n",
        chunk(b"IHDR", ihdr),
        chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
        chunk(b"IEND", b""),
    ]
    path.write_bytes(b"".join(chunks))


def chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def pixel(x: int, y: int, size: int) -> tuple[int, int, int, int]:
    s = size / 512
    pad = 28 * s
    radius = 96 * s
    if inside_round_rect(x, y, size, pad, radius):
        bg = (7, 8, 12, 255)
    else:
        bg = (0, 0, 0, 0)

    cx = cy = size / 2
    ring_r = 168 * s
    ring_w = 16 * s
    d = math.hypot(x - cx, y - cy)
    teal = (61, 214, 140, 255)
    if abs(d - ring_r) <= ring_w:
        return teal
    if d <= 14 * s:
        return teal

    # chevron
    ax, ay = 176 * s, 300 * s
    bx, by = 256 * s, 188 * s
    cx2, cy2 = 336 * s, 300 * s
    if near_segment(x, y, ax, ay, bx, by, 14 * s) or near_segment(x, y, bx, by, cx2, cy2, 14 * s):
        return teal
    return bg


def inside_round_rect(x: int, y: int, size: int, pad: float, radius: float) -> bool:
    x0 = y0 = pad
    x1 = y1 = size - 1 - pad
    if x0 + radius <= x <= x1 - radius and y0 <= y <= y1:
        return True
    if y0 + radius <= y <= y1 - radius and x0 <= x <= x1:
        return True
    corners = (
        (x0 + radius, y0 + radius),
        (x1 - radius, y0 + radius),
        (x0 + radius, y1 - radius),
        (x1 - radius, y1 - radius),
    )
    return any(math.hypot(x - cx, y - cy) <= radius for cx, cy in corners)


def near_segment(x: int, y: int, x1: float, y1: float, x2: float, y2: float, w: float) -> bool:
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (length * length)))
    px, py = x1 + t * dx, y1 + t * dy
    return math.hypot(x - px, y - py) <= w


def main() -> None:
    ROOT.mkdir(exist_ok=True)
    png(ROOT / "pwa-192.png", 192)
    png(ROOT / "pwa-512.png", 512)
    png(ROOT / "apple-touch-icon.png", 180)


if __name__ == "__main__":
    main()
