"""SQLite-слой для мультисерверной экосистемы. Один бот = много гильдий."""
import aiosqlite
import pathlib
import time

DB_PATH = pathlib.Path(__file__).parent / "ecosystem.db"
BACKUP_DIR = pathlib.Path(__file__).parent / "backups"


def conn():
    """Коннект с таймаутом против database is locked."""
    return aiosqlite.connect(DB_PATH, timeout=15)

SCHEMA = """
CREATE TABLE IF NOT EXISTS guilds (
    guild_id INTEGER PRIMARY KEY,
    -- tickets
    ticket_panel_channel INTEGER,
    ticket_category INTEGER,
    ticket_archive_category INTEGER,
    ticket_staff_role INTEGER,
    ticket_counter INTEGER DEFAULT 0,
    -- search (поиск отряда)
    search_channel INTEGER,
    search_stats_channel INTEGER,
    search_panel_id INTEGER DEFAULT 0,
    -- clans
    clan_channel INTEGER,
    clan_leader_role INTEGER,
    clan_archive_channel INTEGER,
    clan_panel_id INTEGER DEFAULT 0,
    -- voices
    voice_lobby INTEGER,
    voice_category INTEGER,
    voice_text_category INTEGER,
    banner_url TEXT DEFAULT '',
    -- i18n + wardogs
    language TEXT DEFAULT 'ru',
    faction_role_lonestar INTEGER,
    faction_role_valkyra INTEGER,
    faction_role_manticore INTEGER,
    admin_log_channel INTEGER DEFAULT 0,
    -- тумблеры модулей (1=вкл)
    en_tickets INTEGER DEFAULT 1,
    en_search INTEGER DEFAULT 1,
    en_clans INTEGER DEFAULT 1,
    en_voices INTEGER DEFAULT 1,
    en_logs INTEGER DEFAULT 1,
    en_moderation INTEGER DEFAULT 1,
    en_welcome INTEGER DEFAULT 1,
    -- модерация + старший + велком
    mod_category INTEGER DEFAULT 0,
    mod_panel_channel INTEGER DEFAULT 0,
    mod_log_channel INTEGER DEFAULT 0,
    ticket_senior_role INTEGER DEFAULT 0,
    welcome_channel INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    channel_id INTEGER,
    owner_id INTEGER,
    type_key TEXT,
    status TEXT DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS parties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    message_id INTEGER,
    owner_id INTEGER,
    text TEXT,
    voice_channel_id INTEGER,
    members TEXT DEFAULT '',
    status TEXT DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS clan_apps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    message_id INTEGER,
    owner_id INTEGER,
    clan_name TEXT,
    description TEXT,
    status TEXT DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS temp_voices (
    guild_id INTEGER,
    voice_id INTEGER,
    text_id INTEGER,
    owner_id INTEGER,
    server_id TEXT DEFAULT '—',
    gamemode TEXT DEFAULT '—',
    faction TEXT DEFAULT '—',
    PRIMARY KEY (guild_id, voice_id)
);
CREATE TABLE IF NOT EXISTS clan_threads (
    guild_id INTEGER,
    thread_id INTEGER PRIMARY KEY,
    owner_id INTEGER,
    clan_name TEXT DEFAULT '',
    last_bump INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS warns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER,
    mod_id INTEGER,
    reason TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS lfg_threads (
    guild_id INTEGER,
    thread_id INTEGER PRIMARY KEY,
    owner_id INTEGER,
    title TEXT DEFAULT '',
    last_bump INTEGER DEFAULT 0
);
"""

async def init_db():
    async with conn() as db:
        await db.executescript(SCHEMA)
        await db.commit()
        # WAL против database is locked при параллельных кликах
        try:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=15000")
            await db.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        # миграция для старых БД
        for col, ddl in [
            ("language", "ALTER TABLE guilds ADD COLUMN language TEXT DEFAULT 'ru'"),
            ("faction_role_lonestar", "ALTER TABLE guilds ADD COLUMN faction_role_lonestar INTEGER"),
            ("faction_role_valkyra", "ALTER TABLE guilds ADD COLUMN faction_role_valkyra INTEGER"),
            ("faction_role_manticore", "ALTER TABLE guilds ADD COLUMN faction_role_manticore INTEGER"),
            ("search_stats_channel", "ALTER TABLE guilds ADD COLUMN search_stats_channel INTEGER"),
            ("clan_archive_channel", "ALTER TABLE guilds ADD COLUMN clan_archive_channel INTEGER"),
            ("search_panel_id", "ALTER TABLE guilds ADD COLUMN search_panel_id INTEGER DEFAULT 0"),
            ("clan_panel_id", "ALTER TABLE guilds ADD COLUMN clan_panel_id INTEGER DEFAULT 0"),
            ("srv_server_id", "ALTER TABLE temp_voices ADD COLUMN server_id TEXT DEFAULT '—'"),
            ("srv_gamemode", "ALTER TABLE temp_voices ADD COLUMN gamemode TEXT DEFAULT '—'"),
            ("srv_faction", "ALTER TABLE temp_voices ADD COLUMN faction TEXT DEFAULT '—'"),
            ("t_claimed", "ALTER TABLE tickets ADD COLUMN claimed_by INTEGER DEFAULT 0"),
            ("admin_log", "ALTER TABLE guilds ADD COLUMN admin_log_channel INTEGER DEFAULT 0"),
            ("en_tickets", "ALTER TABLE guilds ADD COLUMN en_tickets INTEGER DEFAULT 1"),
            ("en_search", "ALTER TABLE guilds ADD COLUMN en_search INTEGER DEFAULT 1"),
            ("en_clans", "ALTER TABLE guilds ADD COLUMN en_clans INTEGER DEFAULT 1"),
            ("en_voices", "ALTER TABLE guilds ADD COLUMN en_voices INTEGER DEFAULT 1"),
            ("en_logs", "ALTER TABLE guilds ADD COLUMN en_logs INTEGER DEFAULT 1"),
            ("en_moderation", "ALTER TABLE guilds ADD COLUMN en_moderation INTEGER DEFAULT 1"),
            ("en_welcome", "ALTER TABLE guilds ADD COLUMN en_welcome INTEGER DEFAULT 1"),
            ("mod_category", "ALTER TABLE guilds ADD COLUMN mod_category INTEGER DEFAULT 0"),
            ("mod_panel", "ALTER TABLE guilds ADD COLUMN mod_panel_channel INTEGER DEFAULT 0"),
            ("mod_log", "ALTER TABLE guilds ADD COLUMN mod_log_channel INTEGER DEFAULT 0"),
            ("senior_role", "ALTER TABLE guilds ADD COLUMN ticket_senior_role INTEGER DEFAULT 0"),
            ("welcome_ch", "ALTER TABLE guilds ADD COLUMN welcome_channel INTEGER DEFAULT 0"),
            ("banner_url", "ALTER TABLE guilds ADD COLUMN banner_url TEXT DEFAULT ''"),
        ]:
            try:
                await db.execute(ddl)
            except Exception:
                pass
        await db.commit()

async def get_guild(guild_id: int) -> dict:
    async with conn() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM guilds WHERE guild_id=?", (guild_id,)) as cur:
            row = await cur.fetchone()
            if row:
                return dict(row)
    # создать пустую запись
    async with conn() as db:
        await db.execute("INSERT OR IGNORE INTO guilds(guild_id) VALUES(?)", (guild_id,))
        await db.commit()
    return {"guild_id": guild_id}

async def set_guild(guild_id: int, **kwargs):
    await get_guild(guild_id)
    cols = ", ".join(f"{k}=?" for k in kwargs)
    async with conn() as db:
        await db.execute(f"UPDATE guilds SET {cols} WHERE guild_id=?", (*kwargs.values(), guild_id))
        await db.commit()

async def next_ticket_num(guild_id: int) -> int:
    g = await get_guild(guild_id)
    n = (g.get("ticket_counter") or 0) + 1
    await set_guild(guild_id, ticket_counter=n)
    return n


TOGGLES = {
    "tickets": "en_tickets",
    "search": "en_search",
    "clans": "en_clans",
    "voices": "en_voices",
    "logs": "en_logs",
    "moderation": "en_moderation",
    "welcome": "en_welcome",
}

TOGGLE_LABELS = {
    "tickets": "🎫 Тикеты",
    "search": "🔍 Поиск отряда",
    "clans": "👑 Форум кланов",
    "voices": "🔊 Приватные войсы",
    "logs": "📜 Админ-логи",
    "moderation": "🛡️ Модерация",
    "welcome": "👋 Велком",
}


async def is_on(guild_id: int, module: str) -> bool:
    try:
        g = await get_guild(guild_id)
        return bool(g.get(TOGGLES[module], 1))
    except Exception:
        return True


async def toggle_module(guild_id: int, module: str) -> bool:
    g = await get_guild(guild_id)
    new = 0 if g.get(TOGGLES[module], 1) else 1
    await set_guild(guild_id, **{TOGGLES[module]: new})
    return bool(new)


def backup_db() -> str | None:
    """Копия БД в database/backups, держим последние 7. Возвращает путь или None."""
    try:
        import shutil
        from datetime import datetime
        if not DB_PATH.exists():
            return None
        BACKUP_DIR.mkdir(exist_ok=True)
        dst = BACKUP_DIR / f"ecosystem-{datetime.now():%Y%m%d}.db"
        # бэкап через SQLite API чтобы не ловить WAL-половину
        import sqlite3
        src = sqlite3.connect(DB_PATH, timeout=15)
        bkp = sqlite3.connect(dst, timeout=15)
        with bkp:
            src.backup(bkp)
        bkp.close()
        src.close()
        olds = sorted(BACKUP_DIR.glob("ecosystem-*.db"))
        for f in olds[:-7]:
            try:
                f.unlink()
            except Exception:
                pass
        return str(dst)
    except Exception:
        return None
