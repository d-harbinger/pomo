#!/usr/bin/env python3
"""Generate the Pomo app icon.

Glass look, matching the running app: a dark frosted panel (the window's
tint over a soft sheen, edged by the same faint white border), and the
timer's thin white ring — a dim full track with a round-capped progress
arc starting at twelve o'clock. Monochrome, like the app; no accent colour.
Drawn at four times the size and scaled down so the curves stay smooth.
"""

import math
import sys
from pathlib import Path
from PIL import Image, ImageDraw

# The app's THEME values, as RGBA.
TINT_TOP = (58, 66, 80, 240)       # frost lit from above
TINT_BOTTOM = (17, 21, 27, 245)    # _FALLBACK_BG, #11151b
BORDER = (255, 255, 255, 0x17)     # THEME["border"]
TRACK = (255, 255, 255, 0x1f)      # THEME["work_dim"]
RING = (255, 255, 255, 255)        # THEME["work"]
SS = 4                             # supersampling factor


def generate_icon(output_path: str, size: int = 256):
    big = size * SS
    pad = 12 * SS
    radius = big // 6
    box = [pad, pad, big - pad, big - pad]

    # Frosted panel: a vertical gradient clipped to the rounded square.
    grad = Image.new("RGBA", (1, big))
    for y in range(big):
        t = y / (big - 1)
        grad.putpixel((0, y), tuple(
            round(a + (b - a) * t) for a, b in zip(TINT_TOP, TINT_BOTTOM)))
    grad = grad.resize((big, big))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)

    # The border and the track are translucent white. PIL's draw replaces
    # pixels rather than blending, so they go on their own layer and are
    # composited, or they would cut see-through holes in the panel.
    ring_pad = pad + 34 * SS
    ring_w = max(6, size // 26) * SS
    ring = [ring_pad, ring_pad, big - ring_pad, big - ring_pad]
    faint = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    fd = ImageDraw.Draw(faint)
    fd.rounded_rectangle(box, radius=radius, outline=BORDER, width=SS * 2)
    fd.arc(ring, start=0, end=360, fill=TRACK, width=ring_w)
    img.alpha_composite(faint)

    # Ring: thin, as in RingTimer; ~72% progress so it reads as a timer
    # mid-run. PIL measures angles clockwise from three o'clock.
    draw = ImageDraw.Draw(img)
    start, end = -90, -90 + int(360 * 0.72)
    draw.arc(ring, start=start, end=end, fill=RING, width=ring_w)

    # Round caps on the progress arc, as Qt.RoundCap draws them.
    cx = cy = big / 2
    r = (ring[2] - ring[0]) / 2 - ring_w / 2
    for deg in (start, end):
        a = math.radians(deg)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        h = ring_w / 2
        draw.ellipse([x - h, y - h, x + h, y + h], fill=RING)

    img = img.resize((size, size), Image.LANCZOS)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    print(f"Icon saved to {output_path}")


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "pomo.png"
    generate_icon(output)
