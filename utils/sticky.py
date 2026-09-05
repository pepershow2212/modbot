"""Липкая панель: всегда внизу канала. Удаляем старую, постим новую. С дебаунсом против спама в API."""
import time
import discord
from database import db

STICKY_COOLDOWN = 45  # секунд между переклейками (защита от рейт-лимита)
_last_stick: dict[int, float] = {}


async def restick(channel: discord.TextChannel, guild_id: int, id_column: str, build_view, force: bool = False):
    """Удалить старую панель и запостить новую внизу. Возвращает message.

    force=False — пропустит если с прошлой переклейки прошло < STICKY_COOLDOWN.
    """
    now = time.monotonic()
    if not force and now - _last_stick.get(channel.id, 0) < STICKY_COOLDOWN:
        return None
    from utils.i18n import get_lang
    g = await db.get_guild(guild_id)
    old_id = g.get(id_column) or 0
    if old_id:
        try:
            old = channel.get_partial_message(old_id)
            await old.delete()
        except Exception:
            pass
    try:
        lang = await get_lang(guild_id)
    except Exception:
        lang = "ru"
    try:
        view = build_view(lang=lang)
    except TypeError:
        view = build_view()
    msg = await channel.send(view=view)
    await db.set_guild(guild_id, **{id_column: msg.id})
    _last_stick[channel.id] = now
    return msg


async def ensure_sticky_on_message(message: discord.Message, id_column: str, build_view, cooldown_s: int = 0):
    """Вызывать из on_message: если пишут в канале панели — переклеить её вниз."""
    if message.author.bot or not message.guild:
        return
    g = await db.get_guild(message.guild.id)
    chan_id = g.get("search_channel" if id_column == "search_panel_id" else "clan_channel") or 0
    if message.channel.id != chan_id:
        return
    # не дёргать панель на каждое сообщение чаще чем раз в N сек? пока просто переклеиваем
    try:
        await restick(message.channel, message.guild.id, id_column, build_view)
    except Exception:
        pass
