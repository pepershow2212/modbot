"""Админ-логи: V2 компоненты с цветом и эмодзи."""
import discord
from database import db

# Цвета по типу события
COLORS = {
    "🎫": 0xFFC800,
    "🔊": 0x5865F2,
    "🧹": 0x99AAB5,
    "🖥️": 0x57F287,
    "🔒": 0xED4245,
    "📄": 0x99AAB5,
    "🙋": 0x57F287,
    "⭐": 0xFEE75C,
    "➕": 0x57F287,
    "➖": 0xED4245,
    "🛡️": 0xEB459E,
    "⚙️": 0x99AAB5,
    "📌": 0xFFC800,
    "👑": 0xFEE75C,
    "👋": 0x5865F2,
    "❌": 0xED4245,
    "⚠️": 0xFEE75C,
    "🔇": 0x99AAB5,
    "⏱️": 0xFEE75C,
    "❌": 0xED4245,
}


def _get_color(text: str) -> int:
    for emoji, color in COLORS.items():
        if text.startswith(emoji):
            return color
    return 0x2B2D31


async def send_log(guild: discord.Guild, text: str):
    """V2 красивый лог в #admin-logs если настроен. Тихо игнорит ошибки."""
    try:
        if not await db.is_on(guild.id, "logs"):
            return
        from utils.live import conf, get_ch
        g = await conf(guild)
        ch = get_ch(guild, g, "admin_log_channel")
        if not isinstance(ch, discord.TextChannel):
            return

        color = _get_color(text)

        v = discord.ui.LayoutView(timeout=None)
        c = discord.ui.Container(
            discord.ui.TextDisplay(text[:1900]),
            accent_color=color,
        )
        v.add_item(c)

        await ch.send(view=v)
    except Exception:
        pass
