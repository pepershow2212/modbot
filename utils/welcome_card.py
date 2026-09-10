"""Карточка входа как у WDINFO: золотой градиент, круглый аватар без обводки, крупный ник."""
from __future__ import annotations

import io
import pathlib

from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

# финальный размер; рисуем в 2x и уменьшаем — края круга без зубцов
SCALE = 2
W, H = 1200 * SCALE, 560 * SCALE
AVATAR = 248 * SCALE
GOLD = (232, 180, 48, 255)
HELLO = (168, 168, 168, 255)


def _font(path_name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    p = ASSETS / path_name
    if p.exists():
        try:
            return ImageFont.truetype(str(p), size)
        except Exception:
            pass
    return ImageFont.load_default()


def _lerp(a, b, t: float):
    t = 0 if t < 0 else 1 if t > 1 else t
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def _gradient() -> Image.Image:
    img = Image.new("RGB", (W, H))
    px = img.load()
    top, mid, bot = (150, 128, 28), (58, 48, 12), (0, 0, 0)
    cx = (W - 1) / 2
    for y in range(H):
        ty = y / (H - 1)
        if ty < 0.36:
            row = _lerp(top, mid, ty / 0.36)
        else:
            row = _lerp(mid, bot, (ty - 0.36) / 0.64)
        for x in range(W):
            edge = abs(x - cx) / cx
            k = 1 - 0.22 * (edge ** 2)
            px[x, y] = tuple(max(0, min(255, int(c * k))) for c in row)
    return img


def _square_crop(im: Image.Image) -> Image.Image:
    w, h = im.size
    s = min(w, h)
    left, top = (w - s) // 2, (h - s) // 2
    return im.crop((left, top, left + s, top + s))


def _circle_avatar(src: Image.Image, size: int) -> Image.Image:
    """Круг без кольца, маска 4x — гладкий край как у WDINFO."""
    ss = 4
    big = size * ss
    im = _square_crop(src.convert("RGBA")).resize((big, big), Image.Resampling.LANCZOS)
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((1, 1, big - 2, big - 2), fill=255)
    mask = mask.resize((size, size), Image.Resampling.LANCZOS)
    im = im.resize((size, size), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    return out


def _fit_name(text: str, max_width: int) -> ImageFont.ImageFont:
    size = 84 * SCALE
    while size >= 40 * SCALE:
        font = _font("welcome_bold.ttf", size)
        box = font.getbbox(text)
        if box[2] - box[0] <= max_width:
            return font
        size -= 2 * SCALE
    return _font("welcome_bold.ttf", 40 * SCALE)


def render_welcome_card(avatar_bytes: bytes, username: str, hello: str) -> io.BytesIO:
    base = _gradient().convert("RGBA")
    try:
        av_src = Image.open(io.BytesIO(avatar_bytes))
    except Exception:
        av_src = Image.new("RGB", (AVATAR, AVATAR), (40, 40, 40))
    avatar = _circle_avatar(av_src, AVATAR)
    ax = (W - avatar.width) // 2
    ay = 48 * SCALE
    base.alpha_composite(avatar, (ax, ay))

    draw = ImageDraw.Draw(base)
    name = (username or "user")[:32]
    name_font = _fit_name(name, W - 160 * SCALE)
    hello_font = _font("welcome_regular.ttf", 38 * SCALE)

    name_y = ay + avatar.height + 28 * SCALE
    draw.text((W // 2, name_y), name, font=name_font, fill=GOLD, anchor="mt")

    nb = name_font.getbbox(name)
    name_h = nb[3] - nb[1]
    hello_y = name_y + name_h + 18 * SCALE
    draw.text((W // 2, hello_y), hello, font=hello_font, fill=HELLO, anchor="mt")

    final = base.convert("RGB").resize((W // SCALE, H // SCALE), Image.Resampling.LANCZOS)
    final = final.filter(ImageFilter.UnsharpMask(radius=0.6, percent=80, threshold=2))
    out = io.BytesIO()
    final.save(out, format="PNG", optimize=True)
    out.seek(0)
    return out
