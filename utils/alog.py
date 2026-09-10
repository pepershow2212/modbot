"""Админ-логи: V2 компоненты с цветом и эмодзи."""
import re

import discord
from database import db


MENTION_CH = re.compile(r"<#(\d+)>")
MENTION_USER = re.compile(r"<@!?(\d+)>")
MENTION_ROLE = re.compile(r"<@&(\d+)>")

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


def _plain_mentions(guild: discord.Guild, text: str) -> str:
    """V2 TextDisplay не резолвит <#id> — пишет #неизвестно. Подставляем имена."""
    def ch_sub(m):
        ch = guild.get_channel(int(m.group(1)))
        return f"`#{ch.name}`" if ch else f"`#{m.group(1)}`"

    def user_sub(m):
        mem = guild.get_member(int(m.group(1)))
        return f"**{mem.display_name}**" if mem else m.group(0)

    def role_sub(m):
        role = guild.get_role(int(m.group(1)))
        return f"**@{role.name}**" if role else m.group(0)

    text = MENTION_CH.sub(ch_sub, text)
    text = MENTION_USER.sub(user_sub, text)
    text = MENTION_ROLE.sub(role_sub, text)
    return text


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
        text = _plain_mentions(guild, text)

        v = discord.ui.LayoutView(timeout=None)
        c = discord.ui.Container(
            discord.ui.TextDisplay(text[:1900]),
            accent_color=color,
        )
        v.add_item(c)

        await ch.send(view=v)
    except Exception:
        pass
