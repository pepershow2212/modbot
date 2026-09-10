"""Восстановить привязки из Discord: бот ищет свои каналы/панели/тики и пишет ID в БД.

Ничего не создаёт и не удаляет. Живые ID в БД не трогает.
"""
from __future__ import annotations

import logging
import re

import discord

from database import db

log = logging.getLogger("wardogs.reattach")

TICKET_TYPES = ("player_report", "staff_report", "appeal", "bug", "suggest")
TICKET_NAME_RE = re.compile(
    r"(?:🎫[・.\s-]*)?(player_report|staff_report|appeal|bug|suggest)[.\s-]*(\d+)",
    re.I,
)
HISTORY_LIMIT = 40

ROLE_SUPPORT = ("Support",)
ROLE_SENIOR = ("Senior Support",)
NOT_STAFF_ROLES = (
    "пользователь", "member", "members", "verified", "верифиц",
    "everyone", "новичок", "игрок", "player",
)
ROLE_LEADER = ("Лидер клана", "Clan Leader", "Clan-Anführer")
FACTION_ROLES = {
    "faction_role_lonestar": "LONESTAR",
    "faction_role_valkyra": "VALKYRA",
    "faction_role_manticore": "MANTICORE",
}


def _norm(name: str) -> str:
    s = (name or "").casefold()
    for ch in ("・", "‧", "•", "|", "_", "-", ".", ",", "—"):
        s = s.replace(ch, " ")
    return " ".join(s.split())


def _has(name: str, *needles: str) -> bool:
    n = _norm(name)
    return any(_norm(x) in n or x.casefold() in n for x in needles if x)


def _alive_ch(guild: discord.Guild, cid) -> discord.abc.GuildChannel | None:
    try:
        cid = int(cid or 0)
    except (TypeError, ValueError):
        return None
    return guild.get_channel(cid) if cid else None


def _alive_role(guild: discord.Guild, rid) -> discord.Role | None:
    try:
        rid = int(rid or 0)
    except (TypeError, ValueError):
        return None
    return guild.get_role(rid) if rid else None


def _need_ch(guild: discord.Guild, g: dict, col: str) -> bool:
    return _alive_ch(guild, g.get(col)) is None


def _need_role(guild: discord.Guild, g: dict, col: str) -> bool:
    return _alive_role(guild, g.get(col)) is None


def _walk_custom_ids(obj, acc: list[str] | None = None) -> list[str]:
    acc = acc if acc is not None else []
    if obj is None:
        return acc
    if isinstance(obj, (list, tuple)):
        for item in obj:
            _walk_custom_ids(item, acc)
        return acc
    if isinstance(obj, dict):
        cid = obj.get("custom_id")
        if cid:
            acc.append(str(cid))
        for val in obj.values():
            _walk_custom_ids(val, acc)
        return acc
    cid = getattr(obj, "custom_id", None)
    if cid:
        acc.append(str(cid))
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        try:
            _walk_custom_ids(to_dict(), acc)
        except Exception:
            pass
    for attr in ("children", "items", "components", "accessory"):
        if hasattr(obj, attr):
            try:
                _walk_custom_ids(getattr(obj, attr), acc)
            except Exception:
                pass
    return acc


def _ids_from_message(message: discord.Message) -> list[str]:
    ids = _walk_custom_ids(getattr(message, "components", None))
    raw = getattr(message, "_data", None) or getattr(message, "_payload", None)
    if isinstance(raw, dict):
        _walk_custom_ids(raw.get("components"), ids)
    # unique, keep order
    seen: set[str] = set()
    out = []
    for cid in ids:
        if cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def _pick_named(channels, *needles: str, cls=None, exclude: tuple[str, ...] = ()):
    for ch in channels:
        if cls and not isinstance(ch, cls):
            continue
        if exclude and _has(ch.name, *exclude):
            continue
        if _has(ch.name, *needles):
            return ch
    return None


def peek_modules(guild: discord.Guild) -> dict[str, bool]:
    """Быстрая проверка по именам — для галок в /setupbot, без записи в БД."""
    texts = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
    forums = [c for c in guild.channels if isinstance(c, discord.ForumChannel)]
    voices = [c for c in guild.channels if isinstance(c, discord.VoiceChannel)]
    cats = list(guild.categories)
    ticket_ch = _pick_named(
        texts, "📩", "поддержка-тикет", "поддержка тикет",
        exclude=("архив", "мод", "mod", "лог", "log", "поддержка-нас"),
    )
    if ticket_ch is None:
        ticket_ch = next((c for c in texts if TICKET_NAME_RE.search(c.name)), None)
    return {
        "tickets": bool(ticket_ch) or bool(_pick_named(cats, "🎫", "поддержка", "support", exclude=("архив", "archive", "archiv"))),
        "search": bool(_pick_named(forums, "поиск отряда", "squad search", "поиск") or _pick_named(texts, "поиск отряда", "squad search")),
        "clans": bool(_pick_named(forums, "набор в клан", "clan recruitment", "кланов") or _pick_named(texts, "набор в клан", "clan recruitment")),
        "voices": bool(_pick_named(voices, "создать комнату", "create room") or next((v for v in voices if v.name.startswith("➕")), None)),
        "logs": bool(_pick_named(texts, "admin logs", "admin-logs", "логи-сервера", "логи сервера", exclude=("мод", "mod"))),
        "moderation": bool(_pick_named(texts, "мод панель", "mod panel", "мод-панель")),
        "welcome": bool(_pick_named(texts, "welcome", "велком", "приветствие")),
    }


def _ticket_owner_id(channel: discord.TextChannel, me_id: int, staff_ids: set[int]) -> int:
    for target, ow in (channel.overwrites or {}).items():
        if getattr(ow, "view_channel", None) is not True:
            continue
        tid = getattr(target, "id", 0)
        if not tid or tid == me_id or tid in staff_ids or tid == channel.guild.id:
            continue
        if isinstance(target, (discord.Member, discord.User)):
            return tid
    return 0


async def _scan_bot_messages(channel, me: discord.ClientUser) -> list[tuple[discord.Message, list[str]]]:
    found = []
    if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
        return found
    try:
        async for msg in channel.history(limit=HISTORY_LIMIT):
            if msg.author.id != me.id:
                continue
            cids = _ids_from_message(msg)
            if cids:
                found.append((msg, cids))
    except (discord.Forbidden, discord.HTTPException):
        pass
    return found


async def _collect_forum_threads(forum: discord.ForumChannel) -> list[discord.Thread]:
    threads = list(forum.threads)
    seen = {t.id for t in threads}
    try:
        async for t in forum.archived_threads(limit=100):
            if t.id not in seen:
                threads.append(t)
                seen.add(t.id)
    except Exception:
        pass
    return threads


async def reattach_guild(
    guild: discord.Guild,
    me: discord.ClientUser,
    scan_messages: bool = True,
    recover_children: bool = True,
) -> dict:
    g = await db.get_guild(guild.id)
    found: dict[str, str] = {}
    updates: dict = {}

    text_chs = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
    forums = [c for c in guild.channels if isinstance(c, discord.ForumChannel)]
    voices = [c for c in guild.channels if isinstance(c, discord.VoiceChannel)]
    cats = list(guild.categories)
    existing_tickets = [c for c in text_chs if TICKET_NAME_RE.search(c.name)]

    # --- имя / тип ---
    if _need_ch(guild, g, "ticket_panel_channel"):
        ch = _pick_named(
            text_chs, "📩", "поддержка-тикет", "поддержка тикет",
            exclude=("архив", "мод", "mod", "лог", "log", "поддержка-нас"),
        )
        if isinstance(ch, discord.TextChannel):
            updates["ticket_panel_channel"] = ch.id
            found["ticket_panel_channel"] = ch.name

    if _need_ch(guild, g, "ticket_category"):
        ch = None
        panel = _alive_ch(guild, updates.get("ticket_panel_channel") or g.get("ticket_panel_channel"))
        if isinstance(panel, discord.TextChannel) and isinstance(panel.category, discord.CategoryChannel):
            ch = panel.category
        if ch is None:
            for tch in existing_tickets:
                if isinstance(tch.category, discord.CategoryChannel) and not _has(tch.category.name, "архив", "archive", "archiv"):
                    ch = tch.category
                    break
        if ch is None:
            ch = _pick_named(cats, "🎫", "поддержка", "support", exclude=("архив", "archive", "archiv"))
        if isinstance(ch, discord.CategoryChannel):
            updates["ticket_category"] = ch.id
            found["ticket_category"] = ch.name

    if _need_ch(guild, g, "ticket_archive_category"):
        ch = _pick_named(cats, "архив-тикет", "ticket archive", "ticket-archiv", "🗃")
        if ch is None:
            ch = _pick_named(cats, "архив", "archive", "archiv")
        if isinstance(ch, discord.CategoryChannel):
            updates["ticket_archive_category"] = ch.id
            found["ticket_archive_category"] = ch.name

    if _need_ch(guild, g, "search_channel"):
        ch = _pick_named(forums, "поиск отряда", "squad search", "trupp suche", "поиск")
        if ch is None:
            ch = _pick_named(text_chs, "поиск отряда", "squad search", "trupp suche")
        if ch is not None:
            updates["search_channel"] = ch.id
            found["search_channel"] = ch.name

    if _need_ch(guild, g, "clan_channel"):
        ch = _pick_named(forums, "набор в клан", "clan recruitment", "clan rekrutierung", "кланов")
        if ch is None:
            ch = _pick_named(text_chs, "набор в клан", "clan recruitment", "clan rekrutierung")
        if ch is not None:
            updates["clan_channel"] = ch.id
            found["clan_channel"] = ch.name

    lobby_hit = _pick_named(voices, "создать комнату", "create room", "raum erstellen")
    if lobby_hit is None:
        lobby_hit = next((v for v in voices if (v.name or "").startswith("➕")), None)
    cur_lobby = _alive_ch(guild, g.get("voice_lobby"))
    need_lobby = cur_lobby is None or (
        isinstance(cur_lobby, discord.VoiceChannel)
        and not (_has(cur_lobby.name, "создать комнату", "create room", "raum erstellen") or (cur_lobby.name or "").startswith("➕"))
    )
    if need_lobby and isinstance(lobby_hit, discord.VoiceChannel):
        updates["voice_lobby"] = lobby_hit.id
        found["voice_lobby"] = lobby_hit.name
        if lobby_hit.category:
            updates["voice_category"] = lobby_hit.category.id
            found["voice_category"] = lobby_hit.category.name

    if "voice_category" not in updates and _need_ch(guild, g, "voice_category"):
        ch = None
        live_lobby = lobby_hit if isinstance(lobby_hit, discord.VoiceChannel) else cur_lobby
        if isinstance(live_lobby, discord.VoiceChannel) and live_lobby.category:
            ch = live_lobby.category
        if ch is None:
            ch = _pick_named(cats, "приватный войс", "private voice", "privater voice")
        if isinstance(ch, discord.CategoryChannel):
            updates["voice_category"] = ch.id
            found["voice_category"] = ch.name

    if _need_ch(guild, g, "admin_log_channel"):
        ch = _pick_named(text_chs, "admin logs", "admin-logs", "логи-сервера", "логи сервера", exclude=("мод", "mod"))
        if isinstance(ch, discord.TextChannel):
            updates["admin_log_channel"] = ch.id
            found["admin_log_channel"] = ch.name

    if _need_ch(guild, g, "mod_category"):
        ch = _pick_named(cats, "модерация", "moderation")
        if isinstance(ch, discord.CategoryChannel):
            updates["mod_category"] = ch.id
            found["mod_category"] = ch.name

    if _need_ch(guild, g, "mod_panel_channel"):
        ch = _pick_named(text_chs, "мод панель", "mod panel", "мод-панель")
        if isinstance(ch, discord.TextChannel):
            updates["mod_panel_channel"] = ch.id
            found["mod_panel_channel"] = ch.name

    if _need_ch(guild, g, "mod_log_channel"):
        ch = _pick_named(text_chs, "мод логи", "mod logs", "мод-логи", "mod-logs")
        if isinstance(ch, discord.TextChannel):
            updates["mod_log_channel"] = ch.id
            found["mod_log_channel"] = ch.name

    if _need_ch(guild, g, "welcome_channel"):
        ch = _pick_named(text_chs, "welcome", "велком", "приветствие")
        if isinstance(ch, discord.TextChannel):
            updates["welcome_channel"] = ch.id
            found["welcome_channel"] = ch.name

    # роли — только Support, не «Пользователь» и не любая роль категории
    from utils.live import find_ticket_staff, is_ticket_staff_role
    cur_staff = _alive_role(guild, g.get("ticket_staff_role"))
    if not is_ticket_staff_role(cur_staff):
        role = find_ticket_staff(guild)
        if role:
            updates["ticket_staff_role"] = role.id
            found["ticket_staff_role"] = role.name
    if _need_role(guild, g, "ticket_senior_role"):
        role = next((r for n in ROLE_SENIOR for r in [discord.utils.get(guild.roles, name=n)] if r), None)
        if role:
            updates["ticket_senior_role"] = role.id
            found["ticket_senior_role"] = role.name
    if _need_role(guild, g, "clan_leader_role"):
        role = next((r for n in ROLE_LEADER for r in [discord.utils.get(guild.roles, name=n)] if r), None)
        if role:
            updates["clan_leader_role"] = role.id
            found["clan_leader_role"] = role.name
    for col, needle in FACTION_ROLES.items():
        if _need_role(guild, g, col):
            role = next((r for r in guild.roles if needle.lower() in r.name.lower()), None)
            if role:
                updates[col] = role.id
                found[col] = role.name

    # --- панели по custom_id (если имя не совпало / канал переименовали) ---
    ticket_from_buttons: set[int] = set()
    voice_from_buttons: set[int] = set()
    panel_hits = {
        "ticket_panel_channel": None,
        "search_channel": None,
        "search_panel_id": None,
        "clan_channel": None,
        "clan_panel_id": None,
        "welcome_channel": None,
    }

    if scan_messages:
        scan_targets = [
            ch for ch in guild.channels
            if isinstance(ch, (discord.TextChannel, discord.VoiceChannel))
        ]
        for ch in scan_targets:
            hits = await _scan_bot_messages(ch, me)
            for msg, cids in hits:
                for cid in cids:
                    if cid.startswith("ticket:create:") or cid == "faq:select":
                        if panel_hits["ticket_panel_channel"] is None:
                            panel_hits["ticket_panel_channel"] = ch.id
                            found.setdefault("ticket_panel_channel", ch.name)
                    elif cid.startswith("ticket:") and cid.count(":") >= 2:
                        try:
                            ticket_from_buttons.add(int(cid.split(":")[-1]))
                        except ValueError:
                            pass
                    elif cid in ("party:create", "party:scam", "party:mkvoice", "party:joininfo"):
                        panel_hits["search_channel"] = ch.id
                        panel_hits["search_panel_id"] = msg.id
                        found.setdefault("search_channel", ch.name)
                    elif cid in ("clan:create", "clan:scam", "clan:transfer", "clan:howpost"):
                        panel_hits["clan_channel"] = ch.id
                        panel_hits["clan_panel_id"] = msg.id
                        found.setdefault("clan_channel", ch.name)
                    elif cid.startswith("welcome:faction:"):
                        if panel_hits["welcome_channel"] is None:
                            panel_hits["welcome_channel"] = ch.id
                            found.setdefault("welcome_channel", ch.name)
                    elif cid.startswith("voice:") and cid.count(":") >= 2:
                        try:
                            voice_from_buttons.add(int(cid.split(":")[-1]))
                        except ValueError:
                            pass

        if _need_ch(guild, g, "ticket_panel_channel") and panel_hits["ticket_panel_channel"]:
            updates["ticket_panel_channel"] = panel_hits["ticket_panel_channel"]
            hit = guild.get_channel(panel_hits["ticket_panel_channel"])
            if _need_ch(guild, g, "ticket_category") and isinstance(hit, discord.TextChannel) and hit.category:
                updates["ticket_category"] = hit.category.id
                found["ticket_category"] = hit.category.name
        if _need_ch(guild, g, "search_channel") and panel_hits["search_channel"]:
            updates["search_channel"] = panel_hits["search_channel"]
        if (g.get("search_panel_id") or 0) == 0 and panel_hits["search_panel_id"]:
            updates["search_panel_id"] = panel_hits["search_panel_id"]
        if _need_ch(guild, g, "clan_channel") and panel_hits["clan_channel"]:
            updates["clan_channel"] = panel_hits["clan_channel"]
        if (g.get("clan_panel_id") or 0) == 0 and panel_hits["clan_panel_id"]:
            updates["clan_panel_id"] = panel_hits["clan_panel_id"]
        if _need_ch(guild, g, "welcome_channel") and panel_hits["welcome_channel"]:
            updates["welcome_channel"] = panel_hits["welcome_channel"]

    if updates:
        await db.set_guild(guild.id, **updates)
        g = await db.get_guild(guild.id)

    tickets_n = 0
    threads_n = 0
    voices_n = 0
    max_ticket_num = int(g.get("ticket_counter") or 0)

    ticket_cat = _alive_ch(guild, g.get("ticket_category"))
    arch_id = int(g.get("ticket_archive_category") or 0)
    panel_id = int(g.get("ticket_panel_channel") or 0)
    if isinstance(ticket_cat, discord.CategoryChannel):
        for ch in existing_tickets:
            if ch.id == panel_id:
                continue
            if ch.category_id in (ticket_cat.id, arch_id):
                continue
            try:
                await ch.edit(category=ticket_cat, reason="WARDOGS: вернуть тикет в категорию поддержки")
                found[f"moved:{ch.id}"] = ch.name
            except Exception:
                pass

    if not recover_children:
        return {
            "guild": guild.name,
            "bindings": {k: v for k, v in found.items() if ":" not in k},
            "tickets": tickets_n,
            "threads": threads_n,
            "voices": voices_n,
        }

    staff_ids = {int(g.get("ticket_staff_role") or 0), int(g.get("ticket_senior_role") or 0)}
    me_id = me.id

    ticket_channels: list[discord.TextChannel] = []
    if isinstance(ticket_cat, discord.CategoryChannel):
        ticket_channels.extend(c for c in ticket_cat.channels if isinstance(c, discord.TextChannel))
    for cid in ticket_from_buttons:
        ch = guild.get_channel(cid)
        if isinstance(ch, discord.TextChannel) and ch not in ticket_channels:
            ticket_channels.append(ch)
    for ch in text_chs:
        if TICKET_NAME_RE.search(ch.name) and ch not in ticket_channels:
            ticket_channels.append(ch)

    async with db.conn() as dbc:
        for ch in ticket_channels:
            if ch.id == (g.get("ticket_panel_channel") or 0):
                continue
            if ch.id == (g.get("admin_log_channel") or 0):
                continue
            m = TICKET_NAME_RE.search(ch.name)
            type_key = (m.group(1).lower() if m else "player_report")
            if type_key not in TICKET_TYPES:
                type_key = "player_report"
            try:
                num = int(m.group(2)) if m else 0
            except Exception:
                num = 0
            if num > max_ticket_num:
                max_ticket_num = num
            owner_id = _ticket_owner_id(ch, me_id, staff_ids)
            cur = await dbc.execute(
                "SELECT id FROM tickets WHERE guild_id=? AND channel_id=?",
                (guild.id, ch.id),
            )
            if await cur.fetchone():
                continue
            status = "open"
            arch = g.get("ticket_archive_category") or 0
            if arch and ch.category_id == arch:
                status = "archived"
            await dbc.execute(
                "INSERT INTO tickets(guild_id, channel_id, owner_id, type_key, status) VALUES(?,?,?,?,?)",
                (guild.id, ch.id, owner_id, type_key, status),
            )
            tickets_n += 1
            found[f"ticket:{ch.id}"] = ch.name

        search_ch = _alive_ch(guild, g.get("search_channel"))
        if isinstance(search_ch, discord.ForumChannel):
            for t in await _collect_forum_threads(search_ch):
                if t.name.startswith("📌"):
                    continue
                await dbc.execute(
                    "INSERT INTO lfg_threads(guild_id, thread_id, owner_id, title, last_bump) VALUES(?,?,?,?,0) "
                    "ON CONFLICT(thread_id) DO UPDATE SET guild_id=excluded.guild_id, "
                    "owner_id=excluded.owner_id, title=excluded.title",
                    (guild.id, t.id, t.owner_id or 0, (t.name or "")[:90]),
                )
                threads_n += 1

        clan_ch = _alive_ch(guild, g.get("clan_channel"))
        if isinstance(clan_ch, discord.ForumChannel):
            for t in await _collect_forum_threads(clan_ch):
                if t.name.startswith("📌"):
                    continue
                await dbc.execute(
                    "INSERT INTO clan_threads(guild_id, thread_id, owner_id, clan_name, last_bump) VALUES(?,?,?,?,0) "
                    "ON CONFLICT(thread_id) DO UPDATE SET guild_id=excluded.guild_id, "
                    "owner_id=excluded.owner_id, clan_name=excluded.clan_name",
                    (guild.id, t.id, t.owner_id or 0, (t.name or "")[:60]),
                )
                threads_n += 1

        lobby_id = int(g.get("voice_lobby") or 0)
        vcat = _alive_ch(guild, g.get("voice_category"))
        voice_ids = set(voice_from_buttons)
        if isinstance(vcat, discord.CategoryChannel):
            for vc in vcat.channels:
                if isinstance(vc, discord.VoiceChannel) and vc.id != lobby_id:
                    voice_ids.add(vc.id)
        for vid in voice_ids:
            vc = guild.get_channel(vid)
            if not isinstance(vc, discord.VoiceChannel) or vc.id == lobby_id:
                continue
            if _has(vc.name, "создать комнату", "create room", "raum erstellen") or (vc.name or "").startswith("➕"):
                continue
            cur = await dbc.execute(
                "SELECT voice_id FROM temp_voices WHERE guild_id=? AND voice_id=?",
                (guild.id, vc.id),
            )
            existed = await cur.fetchone()
            owner_id = 0
            humans = [m for m in vc.members if not m.bot]
            if humans:
                owner_id = humans[0].id
            else:
                low = _norm(vc.name)
                for member in guild.members:
                    if member.bot:
                        continue
                    if _norm(member.display_name) and _norm(member.display_name) in low:
                        owner_id = member.id
                        break
            sid, fac = "", ""
            try:
                from utils.live import parse_voice_status
                sid, fac = parse_voice_status(getattr(vc, "status", None))
            except Exception:
                pass
            await dbc.execute(
                "INSERT INTO temp_voices(guild_id, voice_id, text_id, owner_id, server_id, faction) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(guild_id, voice_id) DO UPDATE SET "
                "owner_id=CASE WHEN excluded.owner_id!=0 THEN excluded.owner_id ELSE temp_voices.owner_id END, "
                "server_id=CASE WHEN excluded.server_id NOT IN ('', '—') THEN excluded.server_id ELSE temp_voices.server_id END, "
                "faction=CASE WHEN excluded.faction NOT IN ('', '—') THEN excluded.faction ELSE temp_voices.faction END",
                (guild.id, vc.id, 0, owner_id, sid or "—", fac or "—"),
            )
            if not existed:
                voices_n += 1
                found[f"voice:{vc.id}"] = vc.name

        await dbc.commit()

    from utils.live import find_ticket_senior, find_ticket_staff, harden_ticket_channel, is_ticket_staff_role
    staff_role = _alive_role(guild, g.get("ticket_staff_role"))
    if not is_ticket_staff_role(staff_role):
        staff_role = find_ticket_staff(guild)
    senior_role = _alive_role(guild, g.get("ticket_senior_role")) or find_ticket_senior(guild)
    for ch in ticket_channels:
        if ch.id == (g.get("ticket_panel_channel") or 0):
            continue
        if ch.id == (g.get("admin_log_channel") or 0):
            continue
        owner_id = _ticket_owner_id(ch, me_id, staff_ids)
        owner = guild.get_member(owner_id) if owner_id else None
        await harden_ticket_channel(ch, owner, staff_role, senior_role)

    if max_ticket_num > int(g.get("ticket_counter") or 0):
        await db.set_guild(guild.id, ticket_counter=max_ticket_num)

    return {
        "guild": guild.name,
        "bindings": {k: v for k, v in found.items() if ":" not in k},
        "tickets": tickets_n,
        "threads": threads_n,
        "voices": voices_n,
    }


async def reattach_all(bot: discord.Client) -> list[dict]:
    out = []
    me = bot.user
    if me is None:
        return out
    for guild in bot.guilds:
        try:
            stats = await reattach_guild(guild, me)
            out.append(stats)
            log.info("reattach %s: %s", guild.id, stats)
        except Exception:
            log.exception("reattach failed for guild %s", getattr(guild, "id", "?"))
    return out


def format_stats(stats: dict) -> str:
    lines = []
    for key, name in (stats.get("bindings") or {}).items():
        lines.append(f"• `{key}` → {name}")
    lines.append(f"• тикеты: +{stats.get('tickets', 0)}")
    lines.append(f"• треды: +{stats.get('threads', 0)}")
    lines.append(f"• войсы: +{stats.get('voices', 0)}")
    return "\n".join(lines) if lines else "—"
