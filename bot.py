"""WARDOGS Ecosystem Bot — точка входа. Всё на Components V2 (LayoutView)."""
import sys
# фикс кодировки Windows-консоли (cp1251 не умеет эмодзи)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import discord
from discord import app_commands
from discord.ext import commands
import config
from database import db
import logging
import pathlib
import traceback
from datetime import datetime

# --- Мониторинг ошибок: логи в файл с ротацией (5МБ x3) ---
LOG_DIR = pathlib.Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
BOT_LOG = LOG_DIR / "bot.log"
ERR_LOG = LOG_DIR / "errors.log"

from logging.handlers import RotatingFileHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        RotatingFileHandler(BOT_LOG, encoding="utf-8", maxBytes=5 * 1024 * 1024, backupCount=3),
        logging.StreamHandler(sys.stdout),
    ],
)
err_handler = RotatingFileHandler(ERR_LOG, encoding="utf-8", maxBytes=5 * 1024 * 1024, backupCount=3)
err_handler.setLevel(logging.ERROR)
err_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s\n%(message)s\n" + "-"*60))
logging.getLogger().addHandler(err_handler)
log = logging.getLogger("wardogs")

def log_error(where: str, exc: BaseException):
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    msg = f"[{datetime.now():%d.%m %H:%M:%S}] {where}\n{tb}"
    log.error(msg)
    print(f"[ERROR] {where}: {exc}", flush=True)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)


async def sync_slash_commands():
    """Replace Discord slash list with this bot's commands.

    Leftover /summary /ask from WARDOGS AI stay on this app until a full
    global + per-guild PUT. Guild sync alone is not enough if the stale
    command was registered globally.
    """
    names = []
    global_cmds = await bot.tree.sync()
    names.extend(sorted({cmd.name for cmd in global_cmds}))
    log.info(f"slash global={[cmd.name for cmd in global_cmds]}")
    synced_guilds = []
    for guild in bot.guilds:
        bot.tree.clear_commands(guild=guild)
        bot.tree.copy_global_to(guild=guild)
        guild_cmds = await bot.tree.sync(guild=guild)
        synced_guilds.append(str(guild.id))
        names.extend(cmd.name for cmd in guild_cmds)
        log.info(f"slash guild={guild.id} names={[cmd.name for cmd in guild_cmds]}")
    unique = sorted(set(names))
    print(f"🔄 Slash sync guilds={', '.join(synced_guilds) or 'none'} cmds={', '.join(unique) or 'none'}", flush=True)
    log.info(f"slash synced guilds={synced_guilds} cmds={unique}")
    return unique


@bot.command(name="syncslash")
@commands.has_permissions(administrator=True)
async def syncslash_cmd(ctx: commands.Context):
    """Admin fallback when slash menu is stuck on leftover /summary."""
    try:
        names = await sync_slash_commands()
        await ctx.send(
            "Slash перезаписан. Пиши `/help` у **WARDOGS MANAGER**.\n"
            f"Команды: `{', '.join(names) or 'нет'}`\n"
            "-# `/ask` `/summary` — это WARDOGS AI, не этот бот.",
            delete_after=30,
        )
    except Exception as e:
        log.warning(f"slash sync failed: {e}")
        await ctx.send(f"Не смог синкнуть slash: `{e}`", delete_after=20)


@bot.event
async def on_ready():
    await db.init_db()
    # бэкап БД при старте (если сегодняшнего ещё нет) + ежедневный цикл
    try:
        from datetime import date
        today = date.today().strftime("%Y%m%d")
        if not (db.BACKUP_DIR / f"ecosystem-{today}.db").exists():
            p = await bot.loop.run_in_executor(None, db.backup_db)
            log.info(f"db backup: {p}")
    except Exception as e:
        log.warning(f"backup failed: {e}")
    if not daily_backup.is_running():
        daily_backup.start()
    import time as _t
    bot.start_time = _t.monotonic()
    bot.started_at = datetime.now()
    try:
        await bot.change_presence(
            activity=discord.Activity(type=discord.ActivityType.playing, name="WARDOGS • /setupbot"),
            status=discord.Status.online,
        )
    except Exception:
        pass
    log.info(f"{bot.user} online | {len(bot.guilds)} guilds")
    print(f"✅ {bot.user} онлайн | {len(bot.guilds)} серверов", flush=True)
    if not getattr(bot, "_reattached", False):
        bot._reattached = True
        try:
            from utils.reattach import reattach_all
            stats = await reattach_all(bot)
            log.info(f"reattach: {stats}")
            print(f"🔗 Привязки восстановлены: {stats}", flush=True)
        except Exception as e:
            bot._reattached = False
            log.warning(f"reattach failed: {e}")
            print(f"⚠️ Не смог сам найти старые панели: {e}", flush=True)
    try:
        await sync_slash_commands()
    except Exception as e:
        print("⚠️ Sync error:", e)
        log.warning(f"slash sync failed: {e}")


async def load_cogs():
    for ext in ["cogs.setup", "cogs.tickets", "cogs.search_party", "cogs.clans", "cogs.voices", "cogs.language", "cogs.channels", "cogs.moderation", "cogs.welcome", "cogs.settings", "cogs.help"]:
        try:
            await bot.load_extension(ext)
            log.info(f"{ext} loaded")
            print(f"📦 {ext} загружен", flush=True)
        except Exception as e:
            log_error(f"load {ext}", e)
            print(f"❌ {ext}: {e}", flush=True)


@bot.event
async def on_error(event, *args, **kwargs):
    log_error(f"on_error:{event} args={args!r}", sys.exc_info()[1] or Exception("unknown"))


@bot.event
async def on_command_error(ctx, error):
    log_error(f"cmd:{ctx.command} by {ctx.author} in {ctx.guild}", error)
    try:
        await ctx.send(f"❌ Ошибка: `{error}`", delete_after=15)
    except Exception:
        pass


@bot.tree.error
async def on_app_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CommandNotFound):
        log.warning(f"stale slash ignored: {error}")
        try:
            msg = "Это не команда WARDOGS TOOLS. /ask /summary /explain — у бота **WARDOGS AI**."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass
        return
    log_error(f"slash:{interaction.command.name if interaction.command else '?'} by {interaction.user} in {interaction.guild}", error)
    try:
        msg = f"❌ Ошибка: `{str(error)[:300]}`"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception as e2:
        log_error("send error reply failed", e2)

async def main():
    async with bot:
        await load_cogs()
        if not config.TOKEN:
            print("❌ Нет DISCORD_TOKEN в .env (смотри .env.example)")
            return
        await bot.start(config.TOKEN)

from discord.ext import tasks

@tasks.loop(hours=24)
async def daily_backup():
    try:
        p = await bot.loop.run_in_executor(None, db.backup_db)
        log.info(f"daily db backup: {p}")
    except Exception as e:
        log.warning(f"daily backup failed: {e}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
