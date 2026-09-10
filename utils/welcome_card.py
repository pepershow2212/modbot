"""Карточка входа как у WDINFO: градиент, круглый аватар, ник, «Добро пожаловать!»."""
from __future__ import annotations

import io
import pathlib

from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
W, H = 1100, 430
AVATAR = 172
RING = 3
GOLD = (228, 176, 54, 255)
HELLO = (163, 163, 163, 255)
RING_COLOR = (232, 232, 232, 255)


def _font(path_name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    p = ASSETS / path_name
    if p.exists():
        try:
            return ImageFont.truetype(str(p), size)
        except Exception:
            pass
    return ImageFont.load_default()


def _lerp(a, b, t: float):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _gradient() -> Image.Image:
    img = Image.new("RGB", (W, H))
    px = img.load()
    top, mid, bot = (110, 92, 20), (42, 36, 10), (0, 0, 0)
    for y in range(H):
        t = y / (H - 1)
        if t < 0.38:
            c = _lerp(top, mid, t / 0.38)
        else:
            c = _lerp(mid, bot, (t - 0.38) / 0.62)
        for x in range(W):
            px[x, y] = c
    return img.filter(ImageFilter.GaussianBlur(0.4))


def _circle_avatar(src: Image.Image) -> Image.Image:
    inner = AVATAR
    outer = AVATAR + RING * 2
    av = src.convert("RGBA").resize((inner, inner), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (outer, outer), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((1, 1, outer - 2, outer - 2), fill=RING_COLOR)
    mask = Image.new("L", (inner, inner), 0)
    ImageDraw.Draw(mask).ellipse((1, 1, inner - 2, inner - 2), fill=255)
    canvas.paste(av, (RING, RING), mask)
    return canvas


def _fit_name(text: str, max_width: int) -> ImageFont.ImageFont:
    size = 68
    while size >= 36:
        font = _font("welcome_bold.ttf", size)
        left, _, right, _ = font.getbbox(text)
        if right - left <= max_width:
            return font
        size -= 2
    return _font("welcome_bold.ttf", 36)


def render_welcome_card(avatar_bytes: bytes, username: str, hello: str) -> io.BytesIO:
    base = _gradient().convert("RGBA")
    try:
        av_src = Image.open(io.BytesIO(avatar_bytes))
    except Exception:
        av_src = Image.new("RGB", (AVATAR, AVATAR), (40, 40, 40))
    avatar = _circle_avatar(av_src)
    ax = (W - avatar.width) // 2
    ay = 34
    base.alpha_composite(avatar, (ax, ay))

    draw = ImageDraw.Draw(base)
    name = (username or "user")[:32]
    name_font = _fit_name(name, W - 140)
    hello_font = _font("welcome_regular.ttf", 30)

    name_y = ay + avatar.height + 22
    draw.text((W // 2, name_y), name, font=name_font, fill=GOLD, anchor="mt")

    hello_y = name_y + int(name_font.size * 0.92) + 4
    draw.text((W // 2, hello_y), hello, font=hello_font, fill=HELLO, anchor="mt")

    out = io.BytesIO()
    base.convert("RGB").save(out, format="PNG", optimize=True)
    out.seek(0)
    return out
