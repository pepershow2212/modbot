"""Модерация в стиле Paxel: /mod → панель Бан/Таймаут/Мут/Кик/Варн/Отмена. Логи в той же категории."""
import re
import discord
from discord import app_commands
from discord.ext import commands
from database import db
import aiosqlite


def parse_duration(text: str) -> int | None:
    """'10m/1h/7d' → секунды. None если перм/пусто."""
    t = (text or "").strip().lower().replace(" ", "")
    if not t or t in ("perm", "перм", "навсегда", "0"):
        return None
    m = re.fullmatch(r"(\d+)(m|м|h|ч|d|д)?", t)
    if not m:
        return None
    n, u = int(m.group(1)), (m.group(2) or "m")
    if u in ("m", "м"):
        return n * 60
    if u in ("h", "ч"):
        return n * 3600
    return n * 86400


def build_mod_panel(target: discord.Member, reason: str, mod: discord.Member, lang: str = "ru") -> discord.ui.LayoutView:
    from utils.i18n import t_sync
    v = discord.ui.LayoutView(timeout=None)
    try:
        av = target.display_avatar.url
    except Exception:
        av = None
    head = discord.ui.Section(
        discord.ui.TextDisplay(f"{t_sync(lang, 'md_title')}\n**{target.mention}** `{target}`\n-# {t_sync(lang, 'md_reason')}: {reason or '—'} • {t_sync(lang, 'md_moder')}: {mod.mention}"),
        accessory=discord.ui.Thumbnail(av) if av else discord.ui.Button(emoji="🛡️", custom_id=f"mod:noop:{target.id}", style=discord.ButtonStyle.secondary),
    )
    rows = [
        ("md_ban", "md_ban_d", "⛔", f"mod:ban:{target.id}", discord.ButtonStyle.danger, t_sync(lang, "md_ban")),
        ("md_timeout", "md_timeout_d", "⏱️", f"mod:timeout:{target.id}", discord.ButtonStyle.secondary, t_sync(lang, "md_timeout")),
        ("md_mute", "md_mute_d", "🔇", f"mod:mute:{target.id}", discord.ButtonStyle.secondary, t_sync(lang, "md_mute")),
        ("md_kick", "md_kick_d", "❌", f"mod:kick:{target.id}", discord.ButtonStyle.secondary, t_sync(lang, "md_kick")),
        ("md_warn", "md_warn_d", "⚠️", f"mod:warn:{target.id}", discord.ButtonStyle.secondary, t_sync(lang, "md_warn")),
        ("md_un", "md_un_d", "↩️", f"mod:un:{target.id}", discord.ButtonStyle.success, t_sync(lang, "md_un")),
    ]
    c = discord.ui.Container(head, discord.ui.Separator(), accent_color=0xFFC800)
    for tk, dk, em, cid, style, label in rows:
        c.add_item(discord.ui.Section(
            discord.ui.TextDisplay(f"**{t_sync(lang, tk)}**\n{t_sync(lang, dk)}"),
            accessory=discord.ui.Button(label=label, emoji=em, custom_id=cid, style=style),
        ))
    v.add_item(c)
    return v


class ModActionModal(discord.ui.Modal):
    def __init__(self, action: str, user_id: int, lang: str = "ru"):
        from utils.i18n import t_sync
        titles = {"ban": t_sync(lang, "md_ban"), "timeout": t_sync(lang, "md_timeout"),
                  "mute": f"{t_sync(lang, 'md_mute')} (voice)", "kick": t_sync(lang, "md_kick"),
                  "warn": t_sync(lang, "md_warn")}
        super().__init__(title=titles.get(action, "..."))
        self.action = action
        self.user_id = user_id
        self.lang = lang
        if action in ("timeout", "mute"):
            self.dur = discord.ui.TextInput(label=t_sync(lang, "mm_dur_l"), placeholder=t_sync(lang, "mm_dur_ph"), max_length=10, required=False)
            self.add_item(self.dur)
        else:
            self.dur = None
        self.reason = discord.ui.TextInput(label=t_sync(lang, "mm_reason_l"), placeholder=t_sync(lang, "mm_reason_ph"), style=discord.TextStyle.long, max_length=500)
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await apply_mod(interaction, self.action, self.user_id,
                        (self.dur.value if self.dur else ""), self.reason.value, self.lang)


async def mod_log(guild: discord.Guild, text: str):
    try:
        g = await db.get_guild(guild.id)
        ch = guild.get_channel(g.get("mod_log_channel") or 0)
        if isinstance(ch, discord.TextChannel):
            await ch.send(text[:1900])
    except Exception:
        pass


def _need(perms: discord.Permissions, name: str) -> bool:
    return getattr(perms, name, False) or getattr(perms, "administrator", False)


async def apply_mod(interaction: discord.Interaction, action: str, user_id: int, dur_text: str, reason: str, lang: str = "ru"):
    from utils.i18n import t_sync
    guild = interaction.guild
    me = interaction.user
    target = guild.get_member(user_id)
    if target is None:
        await interaction.response.send_message(t_sync(lang, "md_notguild"), ephemeral=True)
        return
    if target.id == me.id or target.bot:
        await interaction.response.send_message(t_sync(lang, "md_nope"), ephemeral=True)
        return
    need = {"ban": "ban_members", "kick": "kick_members"}.get(action, "moderate_members")
    if not _need(me.guild_permissions, need):
        await interaction.response.send_message(t_sync(lang, "md_noperm"), ephemeral=True)
        return
    if target.top_role >= me.top_role and me.id != guild.owner_id:
        await interaction.response.send_message(t_sync(lang, "md_higher"), ephemeral=True)
        return
    reason = reason or "—"
    audit = f"{me} | {reason}"[:500]
    try:
        if action == "ban":
            await target.ban(reason=audit, delete_message_days=0)
            out = t_sync(lang, "md_banned").format(user=target.mention, reason=reason)
        elif action == "kick":
            await target.kick(reason=audit)
            out = t_sync(lang, "md_kicked").format(user=target.mention, reason=reason)
        elif action == "timeout":
            secs = parse_duration(dur_text) or 600
            import datetime
            until = discord.utils.utcnow() + datetime.timedelta(seconds=min(secs, 28 * 86400))
            await target.timeout(until, reason=audit)
            out = t_sync(lang, "md_timeouted").format(user=target.mention, dur=dur_text or "10m", reason=reason)
        elif action == "mute":
            if not (target.voice and target.voice.channel):
                await interaction.response.send_message(t_sync(lang, "md_notvoice"), ephemeral=True)
                return
            await target.edit(mute=True, reason=audit)
            out = t_sync(lang, "md_muted").format(user=target.mention, reason=reason)
        elif action == "warn":
            async with db.conn() as dbc:
                await dbc.execute("INSERT INTO warns(guild_id, user_id, mod_id, reason) VALUES(?,?,?,?)",
                                  (guild.id, target.id, me.id, reason))
                await dbc.commit()
                cur = await dbc.execute("SELECT COUNT(*) FROM warns WHERE guild_id=? AND user_id=?", (guild.id, target.id))
                total = (await cur.fetchone())[0]
            try:
                await target.send(t_sync(lang, "md_warn_dm").format(guild=guild.name, reason=reason, n=total))
            except Exception:
                pass
            out = t_sync(lang, "md_warned").format(user=target.mention, n=total, reason=reason)
            if total >= 3:
                try:
                    import datetime
                    until = discord.utils.utcnow() + datetime.timedelta(hours=12)
                    await target.timeout(until, reason=f"auto 3 warns by {me}")
                    out += "\n" + t_sync(lang, "md_automute").format(user=target.mention)
                except Exception:
                    pass
        else:
            return
        await mod_log(guild, f"{out}\n-# {t_sync(lang, 'md_moder')}: {me.mention}")
        from utils.alog import send_log
        await send_log(guild, f"🛡️ {out} | {me.mention}")
        await interaction.response.send_message(out, ephemeral=False)
    except discord.Forbidden:
        await interaction.response.send_message(t_sync(lang, "md_nobotperm"), ephemeral=True)
    except Exception as e:
        try:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        except Exception:
            pass


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="mod", description="Модерация пользователя / Moderate user")
    @app_commands.describe(user="Кого модерировать", reason="Причина")
    async def mod(self, interaction: discord.Interaction, user: discord.Member, reason: str = ""):
        from utils.i18n import get_lang as _tgl, t_sync
        lang = await _tgl(interaction.guild.id)
        if not await db.is_on(interaction.guild.id, "moderation"):
            await interaction.response.send_message(t_sync(lang, "md_mod_off"), ephemeral=True)
            return
        if not (_need(interaction.user.guild_permissions, "moderate_members") or _need(interaction.user.guild_permissions, "kick_members") or _need(interaction.user.guild_permissions, "ban_members")):
            await interaction.response.send_message(t_sync(lang, "md_only"), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        g = await db.get_guild(interaction.guild.id)
        dest = interaction.guild.get_channel(g.get("mod_panel_channel") or 0)
        if not isinstance(dest, discord.TextChannel):
            dest = interaction.channel
        await dest.send(view=build_mod_panel(user, reason, interaction.user, lang))
        await interaction.followup.send(t_sync(lang, "md_panel_here").format(user=user.mention, ch=dest.mention), ephemeral=True)

    @app_commands.command(name="warns", description="Варны / Warns (модерация/mods)")
    async def warns(self, interaction: discord.Interaction, user: discord.Member):
        from utils.i18n import get_lang as _tgl, t_sync
        lang = await _tgl(interaction.guild.id)
        if not (_need(interaction.user.guild_permissions, "moderate_members") or _need(interaction.user.guild_permissions, "kick_members") or _need(interaction.user.guild_permissions, "ban_members")):
            await interaction.response.send_message(t_sync(lang, "md_only"), ephemeral=True)
            return
        async with db.conn() as dbc:
            dbc.row_factory = aiosqlite.Row
            async with dbc.execute("SELECT * FROM warns WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10",
                                   (interaction.guild.id, user.id)) as cur:
                rows = await cur.fetchall()
        if not rows:
            await interaction.response.send_message(t_sync(lang, "md_nowarns").format(user=user.mention), ephemeral=True)
            return
        lines = [f"#{r['id']} • {r['reason']} • <@{r['mod_id']}> • {r['created_at']}" for r in rows]
        await interaction.response.send_message(t_sync(lang, "md_warns").format(user=user.mention, n=len(rows)) + "\n" + "\n".join(lines), ephemeral=True)

    @app_commands.command(name="unwarn", description="Снять варны / Remove warns (модерация/mods)")
    @app_commands.describe(user="Кого", count="Сколько снять (0 = все)")
    async def unwarn(self, interaction: discord.Interaction, user: discord.Member, count: int = 1):
        from utils.i18n import get_lang as _tgl, t_sync
        lang = await _tgl(interaction.guild.id)
        if not (_need(interaction.user.guild_permissions, "moderate_members") or _need(interaction.user.guild_permissions, "kick_members") or _need(interaction.user.guild_permissions, "ban_members")):
            await interaction.response.send_message(t_sync(lang, "md_only"), ephemeral=True)
            return
        async with db.conn() as dbc:
            if count <= 0:
                await dbc.execute("DELETE FROM warns WHERE guild_id=? AND user_id=?", (interaction.guild.id, user.id))
                n = -1
            else:
                cur = await dbc.execute(
                    "DELETE FROM warns WHERE id IN (SELECT id FROM warns WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT ?)",
                    (interaction.guild.id, user.id, count))
                n = cur.rowcount
            await dbc.commit()
        if n == 0:
            await interaction.response.send_message(t_sync(lang, "md_unwarn_none"), ephemeral=True)
            return
        out = t_sync(lang, "md_unwarned").format(n=t_sync(lang, "md_all") if n < 0 else n, user=user.mention)
        await mod_log(interaction.guild, f"{out} • {interaction.user.mention}")
        await interaction.response.send_message(out, ephemeral=True)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        if interaction.response.is_done():
            return
        cid = (interaction.data or {}).get("custom_id", "")
        if not cid.startswith("mod:"):
            return
        if not await db.is_on(interaction.guild.id, "moderation"):
            return
        try:
            _, action, uid = cid.split(":")
            uid = int(uid)
        except Exception:
            return
        if action == "noop":
            await interaction.response.defer()
            return
        if action == "un":
            from utils.i18n import get_lang as _tgl, t_sync
            lang = await _tgl(interaction.guild.id)
            target = interaction.guild.get_member(uid)
            if target is None:
                await interaction.response.send_message(t_sync(lang, "md_notguild"), ephemeral=True)
                return
            if not _need(interaction.user.guild_permissions, "moderate_members"):
                await interaction.response.send_message(t_sync(lang, "md_noperm"), ephemeral=True)
                return
            done = []
            try:
                await target.timeout(None, reason=f"un by {interaction.user}")
                done.append(t_sync(lang, "md_w_timeout"))
            except Exception:
                pass
            try:
                await target.edit(mute=False, reason=f"un by {interaction.user}")
                done.append(t_sync(lang, "md_w_mute"))
            except Exception:
                pass
            try:
                async with db.conn() as dbc:
                    await dbc.execute("DELETE FROM warns WHERE id=(SELECT MAX(id) FROM warns WHERE guild_id=? AND user_id=?)",
                                      (interaction.guild.id, uid))
                    await dbc.commit()
                    done.append(t_sync(lang, "md_w_warn"))
            except Exception:
                pass
            out = t_sync(lang, "md_un_done").format(user=target.mention, what=", ".join(done) or t_sync(lang, "md_nothing"))
            await mod_log(interaction.guild, f"{out} • {interaction.user.mention}")
            await interaction.response.send_message(out, ephemeral=False)
            return
        from utils.i18n import get_lang as _tgl2
        await interaction.response.send_modal(ModActionModal(action, uid, await _tgl2(interaction.guild.id)))


async def setup(bot):
    await bot.add_cog(Moderation(bot))
