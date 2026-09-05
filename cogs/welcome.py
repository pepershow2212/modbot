"""Велком-карточки + выбор фракции (онбординг)."""
import discord
from discord.ext import commands
from database import db

FACTIONS = ["🔵 LONESTAR", "🔴 VALKYRA", "🟢 MANTICORE"]


def build_welcome(member: discord.Member, lang: str = "ru") -> discord.ui.LayoutView:
    from utils.i18n import t_sync
    v = discord.ui.LayoutView(timeout=None)
    try:
        av = member.display_avatar.url
    except Exception:
        av = None
    sec = discord.ui.Section(
        discord.ui.TextDisplay(f"## {member.display_name}\n{t_sync(lang, 'w_hello')}"),
        accessory=discord.ui.Thumbnail(av) if av else discord.ui.Button(emoji="👋", custom_id="welcome:noop", style=discord.ButtonStyle.secondary),
    )
    v.add_item(discord.ui.Container(
        sec,
        discord.ui.Separator(),
        discord.ui.TextDisplay(t_sync(lang, "w_joined").format(user=member.mention, guild=member.guild.name) + f"\n-# {t_sync(lang, 'w_hint')}"),
        accent_color=0xFFC800,
    ))
    return v


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            if not await db.is_on(member.guild.id, "welcome"):
                return
            g = await db.get_guild(member.guild.id)
            ch = member.guild.get_channel(g.get("welcome_channel") or 0)
            if not isinstance(ch, discord.TextChannel):
                return
            from utils.i18n import get_lang as _tgl
            await ch.send(view=build_welcome(member, await _tgl(member.guild.id)))
            from utils.alog import send_log
            await send_log(member.guild, f"👋 Зашёл {member.mention} (`{member}`)")
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        cid = (interaction.data or {}).get("custom_id", "")
        if not cid.startswith("welcome:faction:"):
            return
        if interaction.response.is_done():
            return
        if not await db.is_on(interaction.guild.id, "welcome"):
            return
        from utils.i18n import get_lang as _tgl, t_sync
        lang = await _tgl(interaction.guild.id)
        fname = cid.split(":", 2)[-1]
        if fname not in FACTIONS:
            return
        member = interaction.user
        try:
            has = discord.utils.get(member.roles, name=fname)
            if has:
                await member.remove_roles(has, reason="faction off")
                await interaction.response.send_message(t_sync(lang, "wf_unset"), ephemeral=True)
                return
            for f in FACTIONS:
                r = discord.utils.get(member.roles, name=f)
                if r:
                    try:
                        await member.remove_roles(r, reason="faction switch")
                    except Exception:
                        pass
            role = discord.utils.get(interaction.guild.roles, name=fname)
            if role is None:
                try:
                    role = await interaction.guild.create_role(name=fname, reason="WARDOGS factions")
                except Exception:
                    await interaction.response.send_message("❌", ephemeral=True)
                    return
            await member.add_roles(role, reason="faction pick")
            await interaction.response.send_message(t_sync(lang, "wf_set").format(f=fname), ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("⛔", ephemeral=True)
        except (discord.errors.HTTPException, discord.errors.NotFound):
            pass


def build_factions_panel(lang: str = "ru") -> discord.ui.LayoutView:
    from utils.i18n import t_sync
    v = discord.ui.LayoutView(timeout=None)
    c = discord.ui.Container(
        discord.ui.TextDisplay(f"## {t_sync(lang, 'wf_title')}\n{t_sync(lang, 'wf_hint')}"),
        discord.ui.Separator(),
        accent_color=0xFFC800,
    )
    for f in FACTIONS:
        c.add_item(discord.ui.Section(
            discord.ui.TextDisplay(f"**{f}**"),
            accessory=discord.ui.Button(label=f, custom_id=f"welcome:faction:{f}", style=discord.ButtonStyle.secondary),
        ))
    v.add_item(c)
    return v


async def setup(bot):
    await bot.add_cog(Welcome(bot))
