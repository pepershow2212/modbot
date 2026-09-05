"""/help — список команд, /stats — статистика сервера."""
import discord
from discord import app_commands
from discord.ext import commands
from database import db


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Команды бота / Bot commands")
    async def help(self, interaction: discord.Interaction):
        from utils.i18n import get_lang as _tgl, t_sync
        lang = await _tgl(interaction.guild.id)
        v = discord.ui.LayoutView(timeout=60)
        v.add_item(discord.ui.Container(
            discord.ui.TextDisplay(
                f"{t_sync(lang, 'help_title')}\n"
                "`/setupbot` — мастер-установщик\n"
                "`/mod @user` — модерация • `/unwarn @user` — снять варны\n"
                "`/settings` — вкл/выкл • `/language` — язык\n"
                "`/channels` • `/setchannel` — привязки • `/setbanner` — баннер\n"
                "`/post_tickets` • `/post_search` • `/post_clans` — панели\n"
                "`/stats` • `/ping` • `/warns`\n"
                f"-# {t_sync(lang, 'help_hint')}"
            ),
            accent_color=0xFFC800,
        ))
        await interaction.response.send_message(view=v, ephemeral=True)

    @app_commands.command(name="stats", description="Статистика сервера / Server stats")
    @app_commands.checks.has_permissions(administrator=True)
    async def stats(self, interaction: discord.Interaction):
        from utils.i18n import get_lang as _tgl, t_sync
        lang = await _tgl(interaction.guild.id)
        await interaction.response.defer(ephemeral=True)
        gid = interaction.guild.id
        async with db.conn() as dbc:
            async def _one(q, *a):
                cur = await dbc.execute(q, (*a,))
                return (await cur.fetchone())[0]
            tickets = await _one("SELECT COUNT(*) FROM tickets WHERE guild_id=?", gid)
            parties = await _one("SELECT COUNT(*) FROM parties WHERE guild_id=?", gid)
            warns = await _one("SELECT COUNT(*) FROM warns WHERE guild_id=?", gid)
            try:
                clans = await _one("SELECT COUNT(*) FROM clan_threads WHERE guild_id=?", gid)
            except Exception:
                clans = 0
            try:
                lfg = await _one("SELECT COUNT(*) FROM lfg_threads WHERE guild_id=?", gid)
            except Exception:
                lfg = 0
            try:
                voices = await _one("SELECT COUNT(*) FROM temp_voices WHERE guild_id=?", gid)
            except Exception:
                voices = 0
        g = await db.get_guild(gid)
        mods = sum(1 for k, col in db.TOGGLES.items() if g.get(col, 1))
        v = discord.ui.LayoutView(timeout=60)
        v.add_item(discord.ui.Container(
            discord.ui.TextDisplay(
                f"{t_sync(lang, 'stats_title')}\n"
                f"{t_sync(lang, 'st_tickets')}: **{tickets}**\n"
                f"{t_sync(lang, 'st_parties')}: **{parties}** (+forum: **{lfg}**)\n"
                f"{t_sync(lang, 'st_clans')}: **{clans}**\n"
                f"{t_sync(lang, 'st_voices')}: **{voices}**\n"
                f"{t_sync(lang, 'st_warns')}: **{warns}**\n"
                f"-# Модулей вкл: **{mods}/{len(db.TOGGLES)}**"
            ),
            accent_color=0xFFC800,
        ))
        await interaction.followup.send(view=v, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Help(bot))
