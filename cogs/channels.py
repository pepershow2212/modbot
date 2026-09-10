"""Ручная привязка функционала к каналам по ID: /setchannel + /channels."""
import discord
from discord import app_commands
from discord.ext import commands
from database import db

MODULES = {
    "tickets": ("ticket_panel_channel", "m_tickets", "t_text"),
    "ticket_category": ("ticket_category", "chm_ticket_cat", "t_cat"),
    "ticket_archive": ("ticket_archive_category", "chm_ticket_archive", "t_cat"),
    "search": ("search_channel", "m_search", "t_text"),
    "clans": ("clan_channel", "m_clans", "t_forum"),
    "voice_lobby": ("voice_lobby", "chm_voice_lobby", "t_voice"),
    "voice_category": ("voice_category", "chm_voice_cat", "t_cat"),
    "logs": ("admin_log_channel", "m_logs", "t_text"),
    "mod_panel": ("mod_panel_channel", "chm_mod_panel", "t_text"),
    "mod_logs": ("mod_log_channel", "chm_mod_logs", "t_text"),
    "welcome": ("welcome_channel", "m_welcome", "t_text"),
}


def _label(lang: str, key: str) -> str:
    from utils.i18n import t_sync
    col, lkey, tkey = MODULES[key]
    return f"{t_sync(lang, lkey)} ({t_sync(lang, tkey)})"


class Channels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="channels", description="Привязки / Bindings (админ/admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def channels(self, interaction: discord.Interaction):
        from utils.i18n import get_lang as _tgl, t_sync
        lang = await _tgl(interaction.guild.id)
        g = await db.get_guild(interaction.guild.id)
        lines = []
        for key, (col, _l, _t) in MODULES.items():
            try:
                cid = int(g.get(col) or 0)
            except (TypeError, ValueError):
                cid = 0
            ch = interaction.guild.get_channel(cid) if cid else None
            lines.append(f"{_label(lang, key)}: {ch.mention if ch else '`' + t_sync(lang, 'ch_unset') + '`'} (`{cid or '-'}`)")
        v = discord.ui.LayoutView(timeout=60)
        v.add_item(discord.ui.Container(
            discord.ui.TextDisplay(t_sync(lang, "ch_title") + "\n" + "\n".join(lines) + f"\n\n-# {t_sync(lang, 'ch_hint')}"),
            accent_color=0xFFC800,
        ))
        await interaction.response.send_message(view=v, ephemeral=True)

    @app_commands.command(name="setchannel", description="Привязать модуль / Bind module (админ/admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(module="Модуль", channel="Канал (выбери или вставь ID через выбор)")
    @app_commands.choices(module=[
        app_commands.Choice(name="🎫 Tickets / Тикеты", value="tickets"),
        app_commands.Choice(name="📁 Ticket category / Категория тикетов", value="ticket_category"),
        app_commands.Choice(name="🗃 Ticket archive / Архив тикетов", value="ticket_archive"),
        app_commands.Choice(name="🔍 Search / Поиск", value="search"),
        app_commands.Choice(name="👑 Clans / Кланы", value="clans"),
        app_commands.Choice(name="🔊 Voice lobby / Войс-лобби", value="voice_lobby"),
        app_commands.Choice(name="📁 Voice category / Категория", value="voice_category"),
        app_commands.Choice(name="📜 Logs / Логи", value="logs"),
        app_commands.Choice(name="🛡️ Mod panel / Мод-панель", value="mod_panel"),
        app_commands.Choice(name="📜 Mod logs / Мод-логи", value="mod_logs"),
        app_commands.Choice(name="👋 Welcome / Велком", value="welcome"),
    ])
    async def setchannel(self, interaction: discord.Interaction, module: str, channel: discord.abc.GuildChannel):
        from utils.i18n import get_lang as _tgl, t_sync
        lang = await _tgl(interaction.guild.id)
        if module not in MODULES:
            await interaction.response.send_message(t_sync(lang, "ch_badtype").format(label=module), ephemeral=True)
            return
        col, _l, _t = MODULES[module]
        label = _label(lang, module)
        # валидация типов
        ok = True
        if module in ("tickets", "logs", "mod_panel", "mod_logs", "welcome"):
            ok = isinstance(channel, discord.TextChannel)
        elif module in ("search", "clans"):
            ok = isinstance(channel, (discord.TextChannel, discord.ForumChannel))
        elif module == "voice_lobby":
            ok = isinstance(channel, discord.VoiceChannel)
        elif module in ("voice_category", "ticket_category", "ticket_archive"):
            ok = isinstance(channel, discord.CategoryChannel)
        if not ok:
            await interaction.response.send_message(t_sync(lang, "ch_badtype").format(label=label), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        extra_cols = {col: channel.id}
        if module == "voice_lobby" and isinstance(channel, discord.VoiceChannel) and channel.category:
            extra_cols["voice_category"] = channel.category.id
            extra_cols["en_voices"] = 1
        elif module == "voice_category":
            extra_cols["en_voices"] = 1
        await db.set_guild(interaction.guild.id, **extra_cols)
        extra = ""
        try:
            if module == "tickets" and isinstance(channel, discord.TextChannel):
                from cogs.tickets import build_ticket_panel
                _gg = await db.get_guild(interaction.guild.id)
                await channel.send(view=build_ticket_panel(lang, _gg.get("banner_url") or ""))
                extra = t_sync(lang, "ch_posted")
            elif module == "search" and isinstance(channel, discord.ForumChannel):
                from cogs.search_party import ensure_lfg_example
                await ensure_lfg_example(channel)
                extra = t_sync(lang, "ch_example")
            elif module == "search" and isinstance(channel, discord.TextChannel):
                from cogs.search_party import build_search_panel
                from utils.sticky import restick
                await restick(channel, interaction.guild.id, "search_panel_id", build_search_panel)
                extra = t_sync(lang, "ch_bottom")
            elif module == "clans" and isinstance(channel, discord.ForumChannel):
                from cogs.clans import ensure_forum_example
                await ensure_forum_example(channel)
                extra = t_sync(lang, "ch_example")
            elif module == "logs":
                extra = t_sync(lang, "ch_logsgo")
        except Exception as e:
            extra = f" (пост панели: {e})"
        from utils.alog import send_log
        await send_log(interaction.guild, f"📌 {label} → {channel.mention} поставил {interaction.user.mention}")
        await interaction.followup.send(t_sync(lang, "ch_done").format(label=label, ch=channel.mention, extra=extra), ephemeral=True)

    @app_commands.command(name="reattach", description="Найти свои каналы и панели / Rebind existing setup (админ/admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def reattach(self, interaction: discord.Interaction):
        from utils.i18n import get_lang as _tgl, t_sync
        from utils.reattach import reattach_guild, format_stats
        lang = await _tgl(interaction.guild.id)
        await interaction.response.defer(ephemeral=True, thinking=True)
        stats = await reattach_guild(interaction.guild, interaction.client.user)
        body = format_stats(stats)
        await interaction.followup.send(t_sync(lang, "reattach_ok").format(lines=body), ephemeral=True)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        try:
            from utils.reattach import reattach_guild
            await reattach_guild(guild, self.bot.user)
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(Channels(bot))
