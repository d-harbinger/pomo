#!/usr/bin/env python3
"""Generate the Pomo app icon.

Lean look: dark rounded surface, thin colored ring (matches the running
app's stroke weight), small accent dot in the center to echo the
wordmark's `●`.
"""

import sys
from pathlib import Path
from PIL import Image, ImageDraw


def generate_icon(output_path: str, size: int = 256):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bg = "#1a1a2e"
    accent = "#e94560"
    accent_dim = "#8b2a3a"

    # Rounded surface — slightly inset so the ring has breathing room.
    pad = 12
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=size // 6,
        fill=bg,
    )

    # Ring — thin (~size/22) for the lean aesthetic. ~72% progress
    # arc on a dim track so the icon reads as a timer mid-run.
    ring_pad = pad + 26
    ring_w = max(6, size // 22)
    box = [ring_pad, ring_pad, size - ring_pad, size - ring_pad]
    draw.arc(box, start=0, end=360, fill=accent_dim, width=ring_w)
    draw.arc(box, start=-90, end=-90 + int(360 * 0.72),
             fill=accent, width=ring_w)

    # Center accent dot — matches the wordmark's `●`.
    dot_r = max(8, size // 18)
    cx, cy = size // 2, size // 2
    draw.ellipse(
        [cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
        fill=accent,
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    print(f"Icon saved to {output_path}")


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "pomo.png"
    generate_icon(output)
