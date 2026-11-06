#!/usr/bin/env python3
"""Иконки приложения: тёмный квадрат с надписью V2 (как логотип портала)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent
SIZES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def font(size):
    for path in FONTS:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def make(size: int) -> Image.Image:
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(s * 0.22)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=(29, 29, 31, 255))
    f = font(int(s * 0.40))
    text = "V2"
    box = d.textbbox((0, 0), text, font=f)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((s - w) / 2 - box[0], (s - h) / 2 - box[1]), text, font=f, fill=(255, 255, 255, 255))
    return img.resize((size, size), Image.LANCZOS)


for dens, px in SIZES.items():
    out = BASE / "res" / f"mipmap-{dens}" / "ic_launcher.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    make(px).save(out)
    print("иконка:", out.relative_to(BASE), f"{px}px")
