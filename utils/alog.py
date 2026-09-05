"""Админ-логи: бот пишет что делает, владелец не парится."""
import discord
from database import db


async def send_log(guild: discord.Guild, text: str):
    """Кинуть строку в #admin-logs если настроен. Тихо игнорит ошибки."""
    try:
        if not await db.is_on(guild.id, "logs"):
            return
        g = await db.get_guild(guild.id)
        ch_id = g.get("admin_log_channel") or 0
        if not ch_id:
            return
        ch = guild.get_channel(ch_id)
        if isinstance(ch, discord.TextChannel):
            await ch.send(text[:1900])
    except Exception:
        pass
