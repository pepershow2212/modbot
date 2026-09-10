"""Живые привязки: если БД пустая или ID мёртвый — берём канал с сервера по имени."""
from __future__ import annotations

import re

import discord
from database import db
from utils.reattach import TICKET_NAME_RE, _alive_ch, _has, _pick_named

SEARCH_NAMES = ("поиск отряда", "поиск-отряда", "squad search", "squad-search", "trupp suche")
CLAN_NAMES = ("набор в клан", "набор-в-клан", "clan recruitment", "clan-recruitment", "clan rekrutierung")
LOBBY_NAMES = ("создать комнату", "create room", "raum erstellen")
VOICE_CAT_NAMES = ("приватный войс", "private voice", "privater voice")
STAFF_EXACT = ("Support",)
STAFF_NEEDLES = ("support", "саппорт")
NOT_STAFF_ROLES = (
    "пользователь", "member", "members", "verified", "верифиц",
    "everyone", "новичок", "игрок", "player", "гость",
)
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


def is_ticket_staff_role(role) -> bool:
    if not isinstance(role, discord.Role) or role.is_default():
        return False
    if _has(role.name, *NOT_STAFF_ROLES):
        return False
    if role.name in STAFF_EXACT:
        return True
    return _has(role.name, *STAFF_NEEDLES)


def find_ticket_staff(guild: discord.Guild):
    for name in STAFF_EXACT:
        role = discord.utils.get(guild.roles, name=name)
        if is_ticket_staff_role(role):
            return role
    for role in guild.roles:
        if is_ticket_staff_role(role) and "senior" not in (role.name or "").casefold():
            return role
    return None


def find_ticket_senior(guild: discord.Guild):
    role = discord.utils.get(guild.roles, name="Senior Support")
    if isinstance(role, discord.Role):
        return role
    return next((r for r in guild.roles if _has(r.name, "senior support", "старший саппорт", "старший support")), None)


def ticket_private_overwrites(guild: discord.Guild, owner, staff, category, senior=None, keep_members=()):
    """Тикет видит автор и Support. @everyone и роль «Пользователь» закрыты.
    Чужие каналы и роли руководства не трогаем."""
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False, send_messages=False),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_channels=True,
            read_message_history=True, embed_links=True, attach_files=True,
        ),
    }
    if owner is not None:
        overwrites[owner] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, attach_files=True, read_message_history=True,
        )
    if is_ticket_staff_role(staff):
        overwrites[staff] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, attach_files=True, read_message_history=True,
        )
    senior_ok = (
        isinstance(senior, discord.Role)
        and senior != staff
        and ("senior" in (senior.name or "").casefold() or "старший" in (senior.name or "").casefold())
    )
    if senior_ok:
        overwrites[senior] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, attach_files=True, read_message_history=True,
        )
    for role in guild.roles:
        if role.is_default() or role in overwrites:
            continue
        if _has(role.name, *NOT_STAFF_ROLES):
            overwrites[role] = discord.PermissionOverwrite(view_channel=False)
    return overwrites


def is_ticket_channel_name(name: str) -> bool:
    return bool(TICKET_NAME_RE.search(name or ""))


def _looks_like_lockdown(channel: discord.TextChannel) -> bool:
    everyone = channel.overwrites_for(channel.guild.default_role)
    me = channel.overwrites_for(channel.guild.me)
    return everyone.view_channel is False and me.manage_channels is True


async def harden_ticket_channel(channel: discord.TextChannel, owner, staff, senior=None):
    if not is_ticket_channel_name(channel.name):
        return
    keep = []
    for target, ow in (channel.overwrites or {}).items():
        if isinstance(target, (discord.Member, discord.User)) and ow.view_channel is True:
            if owner is None or target.id != getattr(owner, "id", 0):
                keep.append(target)
    try:
        await channel.edit(
            overwrites=ticket_private_overwrites(channel.guild, owner, staff, channel.category, senior, keep),
            reason="WARDOGS: тикет только для автора и Support",
        )
    except Exception:
        pass


PROTECTED_NAMES = (
    "мод панель", "мод-панель", "mod panel", "мод логи", "мод-логи", "mod logs",
    "admin logs", "admin-logs", "логи-сервера", "логи сервера",
)


async def restore_hidden_channels(guild: discord.Guild, g: dict | None = None) -> list[str]:
    """Вернуть видимость каналам, которые закрыли как тикеты по ошибке."""
    g = g or {}
    skip_ids = {
        _iid(g.get("mod_panel_channel")),
        _iid(g.get("mod_log_channel")),
        _iid(g.get("admin_log_channel")),
    }
    restored = []
    for ch in guild.channels:
        if not isinstance(ch, discord.TextChannel):
            continue
        if ch.id in skip_ids:
            continue
        if is_ticket_channel_name(ch.name):
            continue
        if _has(ch.name, *PROTECTED_NAMES):
            continue
        if ch.permissions_synced:
            continue
        if not _looks_like_lockdown(ch):
            continue
        if ch.category is None:
            continue
        try:
            await ch.edit(sync_permissions=True, reason="WARDOGS: вернуть видимость канала")
            restored.append(ch.name)
        except Exception:
            pass
    return restored


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

    cur_staff = guild.get_role(_iid(g.get("ticket_staff_role")))
    if not is_ticket_staff_role(cur_staff):
        staff = find_ticket_staff(guild)
        if staff:
            patch["ticket_staff_role"] = staff.id
    cur_senior = guild.get_role(_iid(g.get("ticket_senior_role")))
    if cur_senior is None:
        senior = find_ticket_senior(guild)
        if senior:
            patch["ticket_senior_role"] = senior.id

    if patch:
        await db.set_guild(guild.id, **patch)
        g.update(patch)
        for k in ID_KEYS:
            if k in g:
                g[k] = _iid(g.get(k))
    return g
