"""/settings — тумблеры вкл/выкл каждого модуля (кастомизация)."""
import discord
from discord import app_commands
from discord.ext import commands
from database import db


def build_settings_view(states: dict, lang: str = "ru") -> discord.ui.LayoutView:
    from utils.i18n import t_sync
    v = discord.ui.LayoutView(timeout=180)
    items = []
    for key in ["tickets", "search", "clans", "voices", "logs", "moderation", "welcome"]:
        on = states.get(key, True)
        items.append(discord.ui.Section(
            discord.ui.TextDisplay(f"**{t_sync(lang, 'm_' + key)}**\n{'🟢 ' + t_sync(lang, 'st_on') if on else '🔴 ' + t_sync(lang, 'st_off')}"),
            accessory=discord.ui.Button(
                label=t_sync(lang, "st_off") if on else t_sync(lang, "st_on"),
                emoji="🟢" if on else "🔴",
                custom_id=f"settings:toggle:{key}",
                style=discord.ButtonStyle.secondary,
            ),
        ))
    c = discord.ui.Container(
        discord.ui.TextDisplay(f"## ⚙️ {t_sync(lang, 'set_title')}"),
        discord.ui.Separator(),
        *items,
        accent_color=0xFFC800,
    )
    v.add_item(c)
    return v


async def current_states(guild_id: int) -> dict:
    g = await db.get_guild(guild_id)
    return {k: db.flag_on(g, k) for k in db.TOGGLES}


class Settings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="settings", description="Модули вкл/выкл / Toggle modules (админ/admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def settings(self, interaction: discord.Interaction):
        from utils.i18n import get_lang as _tgl
        lang = await _tgl(interaction.guild.id)
        await interaction.response.send_message(view=build_settings_view(await current_states(interaction.guild.id), lang), ephemeral=True)

    @app_commands.command(name="ping", description="Пинг и аптайм / Ping and uptime")
    async def ping(self, interaction: discord.Interaction):
        import time as _t
        from datetime import datetime as _dt
        up = "?"
        try:
            secs = int(_t.monotonic() - self.bot.start_time)
            h, r = divmod(secs, 3600)
            m, s = divmod(r, 60)
            up = f"{h}ч {m}м {s}с"
        except Exception:
            pass
        ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 {ms}ms • uptime {up}", ephemeral=True)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        cid = (interaction.data or {}).get("custom_id", "")
        if not cid.startswith("settings:toggle:"):
            return
        if not interaction.user.guild_permissions.administrator:
            from utils.i18n import get_lang as _tgl, t_sync
            await interaction.response.send_message(t_sync(await _tgl(interaction.guild.id), "err_admin"), ephemeral=True)
            return
        key = cid.split(":")[-1]
        try:
            from utils.i18n import get_lang as _tgl, t_sync
            lang = await _tgl(interaction.guild.id)
            new = await db.toggle_module(interaction.guild.id, key)
            await interaction.response.edit_message(view=build_settings_view(await current_states(interaction.guild.id), lang))
            from utils.alog import send_log
            await send_log(interaction.guild, f"⚙️ {t_sync(lang, 'm_' + key)} → {t_sync(lang, 'st_on') if new else t_sync(lang, 'st_off')} ({interaction.user.mention})")
        except (discord.errors.InteractionResponded, discord.errors.HTTPException, discord.errors.NotFound):
            pass


async def setup(bot):
    await bot.add_cog(Settings(bot))
