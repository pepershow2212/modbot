"""Живые привязки: если БД пустая или ID мёртвый — берём канал с сервера по имени."""
from __future__ import annotations

import re

import discord
from database import db
from utils.reattach import _alive_ch, _has, _pick_named

SEARCH_NAMES = ("поиск отряда", "поиск-отряда", "squad search", "squad-search", "trupp suche")
CLAN_NAMES = ("набор в клан", "набор-в-клан", "clan recruitment", "clan-recruitment", "clan rekrutierung")
LOBBY_NAMES = ("создать комнату", "create room", "raum erstellen")
VOICE_CAT_NAMES = ("приватный войс", "private voice", "privater voice")
ID_KEYS = (
    "ticket_panel_channel", "ticket_category", "ticket_archive_category",
    "ticket_staff_role", "ticket_senior_role",
    "search_channel", "search_stats_channel", "search_panel_id",
    "clan_channel", "clan_leader_role", "clan_archive_channel", "clan_panel_id",
    "voice_lobby", "voice_category", "voice_text_category",
    "admin_log_channel", "mod_category", "mod_panel_channel", "mod_log_channel",
    "welcome_channel",
    "faction_role_lonestar", "faction_role_valkyra", "faction_role_manticore",
)


def _iid(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def get_ch(guild: discord.Guild, g: dict, key: str):
    return _alive_ch(guild, g.get(key))


def looks_like_lobby(ch) -> bool:
    if not isinstance(ch, discord.VoiceChannel):
        return False
    name = ch.name or ""
    return _has(name, *LOBBY_NAMES) or name.startswith("➕")


def find_lobby(guild: discord.Guild):
    voices = [c for c in guild.channels if isinstance(c, discord.VoiceChannel)]
    return _pick_named(voices, *LOBBY_NAMES) or next((v for v in voices if (v.name or "").startswith("➕")), None)


def find_voice_category(guild: discord.Guild, lobby=None):
    if lobby is None:
        lobby = find_lobby(guild)
    if isinstance(lobby, discord.VoiceChannel) and lobby.category:
        return lobby.category
    cats = list(guild.categories)
    return _pick_named(cats, *VOICE_CAT_NAMES)


def is_lobby_channel(ch, g: dict | None = None) -> bool:
    """Лобби по имени (даже дубли) или по ID, если канал переименовали."""
    if looks_like_lobby(ch):
        return True
    if not isinstance(ch, discord.VoiceChannel) or not g:
        return False
    return ch.id == _iid(g.get("voice_lobby"))


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


def parse_voice_status(status: str | None) -> tuple[str, str]:
    """Достать server_id и фракцию из статуса войса."""
    raw = (status or "").strip()
    if not raw:
        return "", ""
    m = re.search(r"Server id:\s*(\S+)(?:\s+(\S+))?", raw, re.I)
    if m:
        sid = m.group(1) or ""
        fac = (m.group(2) or "").strip()
        if fac in {"—", "-", "–"}:
            fac = ""
        return sid, fac
    return "", ""


async def conf(guild: discord.Guild) -> dict:
    """Конфиг гильдии с подстановкой живых каналов. Дописывает дыры в БД."""
    g = dict(await db.get_guild(guild.id))
    for k in ID_KEYS:
        if k in g:
            g[k] = _iid(g.get(k))
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

    cur_lobby = get_ch(guild, g, "voice_lobby")
    real_lobby = find_lobby(guild)
    if real_lobby and (cur_lobby is None or not looks_like_lobby(cur_lobby)):
        patch["voice_lobby"] = real_lobby.id
        cur_lobby = real_lobby
    lobby = real_lobby if looks_like_lobby(real_lobby) else cur_lobby
    vcat = find_voice_category(guild, lobby)
    cur_cat = get_ch(guild, g, "voice_category")
    if vcat and (cur_cat is None or (lobby and lobby.category and cur_cat.id != lobby.category.id)):
        if lobby and lobby.category:
            patch["voice_category"] = lobby.category.id
        elif isinstance(vcat, discord.CategoryChannel):
            patch["voice_category"] = vcat.id

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
        for k in ID_KEYS:
            if k in g:
                g[k] = _iid(g.get(k))
    return g
