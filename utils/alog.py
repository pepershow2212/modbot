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
        g = await db.get_guild(guild.id)
        ch_id = g.get("admin_log_channel") or 0
        if not ch_id:
            return
        ch = guild.get_channel(ch_id)
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
