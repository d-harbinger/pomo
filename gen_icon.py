#!/usr/bin/env python3
"""Generate a simple Pomo app icon."""

import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def generate_icon(output_path: str):
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background circle
    pad = 8
    draw.ellipse([pad, pad, size - pad, size - pad], fill="#1a1a2e")

    # Progress arc (decorative, ~75%)
    draw.arc(
        [pad + 12, pad + 12, size - pad - 12, size - pad - 12],
        start=-90, end=180,
        fill="#e94560", width=14,
    )

    # Background ring for remaining portion
    draw.arc(
        [pad + 12, pad + 12, size - pad - 12, size - pad - 12],
        start=180, end=270,
        fill="#8b2a3a", width=14,
    )

    # Center text
    try:
        font = ImageFont.truetype("/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Bold.ttf", 64)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)
        except (OSError, IOError):
            font = ImageFont.load_default()

    text = "P"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size - tw) / 2, (size - th) / 2 - 6),
        text, fill="#eaeaea", font=font,
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    print(f"Icon saved to {output_path}")


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "pomo.png"
    generate_icon(output)
