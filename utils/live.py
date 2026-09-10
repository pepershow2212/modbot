"""Живые привязки: если БД пустая или ID мёртвый — берём канал с сервера по имени."""
from __future__ import annotations

import discord
from database import db
from utils.reattach import _alive_ch, _has, _pick_named

SEARCH_NAMES = ("поиск отряда", "поиск-отряда", "squad search", "squad-search", "trupp suche")
CLAN_NAMES = ("набор в клан", "набор-в-клан", "clan recruitment", "clan-recruitment", "clan rekrutierung")


def _iid(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def get_ch(guild: discord.Guild, g: dict, key: str):
    return _alive_ch(guild, g.get(key))


def _find_search(guild: discord.Guild):
    forums = [c for c in guild.channels if isinstance(c, discord.ForumChannel)]
    ch = _pick_named(forums, *SEARCH_NAMES)
    if ch:
        return ch
    texts = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
    return _pick_named(texts, *SEARCH_NAMES)


def _find_clan(guild: discord.Guild):
    forums = [c for c in guild.channels if isinstance(c, discord.ForumChannel)]
    ch = _pick_named(forums, *CLAN_NAMES)
    if ch:
        return ch
    texts = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
    return _pick_named(texts, *CLAN_NAMES)


def is_search_forum(guild: discord.Guild, parent_id, g: dict) -> bool:
    pid = _iid(parent_id)
    if pid and pid == _iid(g.get("search_channel")):
        return True
    p = guild.get_channel(pid)
    return isinstance(p, discord.ForumChannel) and _has(p.name, *SEARCH_NAMES)


def is_clan_forum(guild: discord.Guild, parent_id, g: dict) -> bool:
    pid = _iid(parent_id)
    if pid and pid == _iid(g.get("clan_channel")):
        return True
    p = guild.get_channel(pid)
    return isinstance(p, discord.ForumChannel) and _has(p.name, *CLAN_NAMES)


async def conf(guild: discord.Guild) -> dict:
    """Конфиг гильдии с подстановкой живых каналов. Дописывает дыры в БД."""
    g = dict(await db.get_guild(guild.id))
    patch = {}

    search = get_ch(guild, g, "search_channel")
    if not isinstance(search, discord.ForumChannel):
        found = _find_search(guild)
        if found and (search is None or isinstance(found, discord.ForumChannel)):
            patch["search_channel"] = found.id

    clan = get_ch(guild, g, "clan_channel")
    if not isinstance(clan, discord.ForumChannel):
        found = _find_clan(guild)
        if found and (clan is None or isinstance(found, discord.ForumChannel)):
            patch["clan_channel"] = found.id

    if get_ch(guild, g, "ticket_panel_channel") is None:
        texts = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
        ch = _pick_named(texts, "📩", "поддержка-тикет", "поддержка тикет", exclude=("архив", "мод", "лог", "поддержка-нас"))
        if ch:
            patch["ticket_panel_channel"] = ch.id
            if get_ch(guild, g, "ticket_category") is None and ch.category:
                patch["ticket_category"] = ch.category.id

    if get_ch(guild, g, "ticket_category") is None and "ticket_category" not in patch:
        panel = get_ch(guild, {**g, **patch}, "ticket_panel_channel") or get_ch(guild, g, "ticket_panel_channel")
        if isinstance(panel, discord.TextChannel) and panel.category:
            patch["ticket_category"] = panel.category.id

    if get_ch(guild, g, "voice_lobby") is None:
        voices = [c for c in guild.channels if isinstance(c, discord.VoiceChannel)]
        ch = _pick_named(voices, "создать комнату", "create room", "raum erstellen") or next((v for v in voices if v.name.startswith("➕")), None)
        if ch:
            patch["voice_lobby"] = ch.id
            if get_ch(guild, g, "voice_category") is None and ch.category:
                patch["voice_category"] = ch.category.id

    if get_ch(guild, g, "admin_log_channel") is None:
        texts = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
        ch = _pick_named(texts, "admin logs", "admin-logs", "логи-сервера", "логи сервера", exclude=("мод", "mod"))
        if ch:
            patch["admin_log_channel"] = ch.id

    if get_ch(guild, g, "welcome_channel") is None:
        texts = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
        ch = _pick_named(texts, "welcome", "велком", "приветствие")
        if ch:
            patch["welcome_channel"] = ch.id

    if get_ch(guild, g, "mod_log_channel") is None:
        texts = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
        ch = _pick_named(texts, "мод логи", "mod logs", "мод-логи", "mod-logs")
        if ch:
            patch["mod_log_channel"] = ch.id

    if patch:
        await db.set_guild(guild.id, **patch)
        g.update(patch)
    return g
