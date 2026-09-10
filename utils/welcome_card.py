"""Карточка входа как у WDINFO: градиент, круглый аватар, ник, «Добро пожаловать!»."""
from __future__ import annotations

import io
import pathlib

from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
W, H = 960, 420
AVATAR = 210
RING = 4


def _font(path_name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        ASSETS / path_name,
        pathlib.Path(r"C:\Windows\Fonts\segoeuib.ttf") if "bold" in path_name else pathlib.Path(r"C:\Windows\Fonts\segoeui.ttf"),
        pathlib.Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if "bold" in path_name else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        pathlib.Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if "bold" in path_name else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ]
    for p in candidates:
        try:
            if p and p.exists():
                return ImageFont.truetype(str(p), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _lerp(a, b, t: float):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _gradient() -> Image.Image:
    img = Image.new("RGB", (W, H))
    px = img.load()
    top, mid, bot = (102, 86, 22), (48, 40, 12), (0, 0, 0)
    for y in range(H):
        t = y / (H - 1)
        if t < 0.42:
            c = _lerp(top, mid, t / 0.42)
        else:
            c = _lerp(mid, bot, (t - 0.42) / 0.58)
        for x in range(W):
            px[x, y] = c
    return img.filter(ImageFilter.GaussianBlur(0.6))


def _circle_avatar(src: Image.Image) -> Image.Image:
    inner = AVATAR
    outer = AVATAR + RING * 2
    av = src.convert("RGBA").resize((inner, inner), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (outer, outer), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((0, 0, outer - 1, outer - 1), fill=(232, 232, 232, 255))
    mask = Image.new("L", (inner, inner), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, inner - 1, inner - 1), fill=255)
    canvas.paste(av, (RING, RING), mask)
    return canvas


def _fit_font(text: str, max_width: int, start: int, path_name: str) -> ImageFont.ImageFont:
    size = start
    while size >= 28:
        font = _font(path_name, size)
        box = font.getbbox(text)
        if box[2] - box[0] <= max_width:
            return font
        size -= 4
    return _font(path_name, 28)


def render_welcome_card(avatar_bytes: bytes, username: str, hello: str) -> io.BytesIO:
    base = _gradient().convert("RGBA")
    try:
        av_src = Image.open(io.BytesIO(avatar_bytes))
    except Exception:
        av_src = Image.new("RGB", (AVATAR, AVATAR), (40, 40, 40))
    avatar = _circle_avatar(av_src)
    ax = (W - avatar.width) // 2
    ay = 36
    base.alpha_composite(avatar, (ax, ay))

    draw = ImageDraw.Draw(base)
    name = (username or "user")[:32]
    name_font = _fit_font(name, W - 80, 72, "welcome_bold.ttf")
    hello_font = _font("welcome_regular.ttf", 32)
    nb = name_font.getbbox(name)
    nw, nh = nb[2] - nb[0], nb[3] - nb[1]
    nx = (W - nw) // 2
    ny = ay + avatar.height + 22 - nb[1]
    draw.text((nx, ny), name, font=name_font, fill=(232, 176, 46, 255))

    hb = hello_font.getbbox(hello)
    hw = hb[2] - hb[0]
    hx = (W - hw) // 2
    hy = ny + nh + 14 - hb[1]
    draw.text((hx, hy), hello, font=hello_font, fill=(158, 158, 158, 255))

    out = io.BytesIO()
    base.convert("RGB").save(out, format="PNG", optimize=True)
    out.seek(0)
    return out
