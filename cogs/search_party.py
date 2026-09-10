"""Поиск отряда / LFG-ФОРУМ: анкеты-тредами, лок, бамп ⬆️/3д (legacy текст-канал поддерживается)."""
import time
import discord
from discord import app_commands
from discord.ext import commands, tasks
import config
from database import db
import aiosqlite

BUMP_EMOJI = "⬆️"
BUMP_COOLDOWN = 24 * 3600  # LFG — раз в сутки (кланы — раз в 3 дня)

LFG_GUIDE = (
    "🔍 LFG WARDOGS TOOLS. Создай пост по шаблону из закрепа 📌 (можно с картинкой). "
    "Писать в чужих ветках нельзя — только ⬆️ раз в сутки поднимает пост."
)

LFG_EXAMPLE = (
    "📌 **Шаблон анкеты — скопируй в свой пост**\n"
    "```\n"
    "📋 АНКЕТА ДЛЯ ПОИСКА ОТРЯДА\n\n"
    "🎮 Игровой ник:\n"
    "⚔️ Режим игры (PVE/PVP/Смешанный):\n"
    "🎯 Роль / Специализация:\n"
    "📊 Уровень / Опыт (часов):\n"
    "🌍 Часовой пояс:\n"
    "🕒 Время игры:\n"
    "🎙️ Микрофон:\n"
    "💬 Ожидания от отряда:\n"
    "📝 Дополнительно о себе:\n"
    "```\n"
    "-# Новый пост = твоя анкета. Бот поставит ⬆️. Раз в сутки жми ⬆️ — пост поднимется выше всех."
)


def build_search_panel(lang: str = "ru") -> discord.ui.LayoutView:
    from utils.i18n import t_sync
    v = discord.ui.LayoutView(timeout=None)
    c = discord.ui.Container(
        discord.ui.Section(
            discord.ui.TextDisplay(f"**{t_sync(lang, 's_create_t')}**\n{t_sync(lang, 's_create_d')}"),
            accessory=discord.ui.Button(emoji="➕", custom_id="party:create", style=discord.ButtonStyle.secondary),
        ),
        discord.ui.Section(
            discord.ui.TextDisplay(f"**{t_sync(lang, 's_scam_t')}**\n{t_sync(lang, 's_scam_d')}"),
            accessory=discord.ui.Button(emoji="❗", custom_id="party:scam", style=discord.ButtonStyle.secondary),
        ),
        discord.ui.Section(
            discord.ui.TextDisplay(f"**{t_sync(lang, 's_mkvoice_t')}**\n{t_sync(lang, 's_mkvoice_d')}"),
            accessory=discord.ui.Button(emoji="🎙️", custom_id="party:mkvoice", style=discord.ButtonStyle.secondary),
        ),
        discord.ui.Section(
            discord.ui.TextDisplay(f"**{t_sync(lang, 's_join_t')}**\n{t_sync(lang, 's_join_d')}"),
            accessory=discord.ui.Button(emoji="👥", custom_id="party:joininfo", style=discord.ButtonStyle.secondary),
        ),
        accent_color=config.ACCENT_YELLOW,
    )
    v.add_item(c)
    # единый обработчик on_interaction ниже, колбэки не вешаем (дабл-ответ)
    return v


def build_party_post(owner: discord.Member, text: str, party_id: int, lang: str = "ru") -> discord.ui.LayoutView:
    from utils.i18n import t_sync
    v = discord.ui.LayoutView(timeout=None)
    c = discord.ui.Container(
        discord.ui.TextDisplay(f"{owner.mention}"),
        discord.ui.TextDisplay(f">>> {text}"),  # цитата как на скрине
        accent_color=config.ACCENT_RED,
    )
    v.add_item(c)
    row = discord.ui.ActionRow()
    b1 = discord.ui.Button(label=t_sync(lang, "ps_write"), emoji="✉️", custom_id=f"party:dm:{owner.id}", style=discord.ButtonStyle.secondary)
    b2 = discord.ui.Button(label=t_sync(lang, "ps_join"), emoji="➕", custom_id=f"party:join:{party_id}", style=discord.ButtonStyle.primary)
    row.add_item(b1)
    row.add_item(b2)
    v.add_item(row)
    return v


async def ensure_lfg_example(forum: discord.ForumChannel):
    try:
        for t in forum.threads:
            if t.name.startswith("📌"):
                try:
                    await t.edit(pinned=True)
                except Exception:
                    pass
                return t
    except Exception:
        pass
    try:
        thread, msg = await forum.create_thread(name="📌 Шаблон анкеты", content=LFG_EXAMPLE, reason="WARDOGS lfg example")
        try:
            await thread.edit(pinned=True)
        except Exception:
            pass
        try:
            await msg.pin(reason="example")
        except Exception:
            pass
        return thread
    except Exception:
        return None


class PartyModal(discord.ui.Modal):
    def __init__(self, lang: str = "ru"):
        from utils.i18n import t_sync
        super().__init__(title="Анкета" if lang == "ru" else ("Application" if lang == "en" else "Anzeige"))
        self.lang = lang
        self.nick = discord.ui.TextInput(label=t_sync(lang, "pm_nick_l"), max_length=60, placeholder="net5510")
        self.mode_role = discord.ui.TextInput(label=t_sync(lang, "pm_mode_l"), max_length=120, placeholder=t_sync(lang, "pm_mode_ph"))
        self.exp = discord.ui.TextInput(label=t_sync(lang, "pm_exp_l"), max_length=120, placeholder=t_sync(lang, "pm_exp_ph"))
        self.time_mic = discord.ui.TextInput(label=t_sync(lang, "pm_time_l"), max_length=120, placeholder=t_sync(lang, "pm_time_ph"))
        self.about = discord.ui.TextInput(label=t_sync(lang, "pm_about_l"), style=discord.TextStyle.long, max_length=500, placeholder=t_sync(lang, "pm_about_ph"))
        for _i in (self.nick, self.mode_role, self.exp, self.time_mic, self.about):
            self.add_item(_i)

    async def on_submit(self, interaction: discord.Interaction):
        from utils.i18n import t_sync
        lang = getattr(self, "lang", "ru")
        text = (
            f"🎮 {t_sync(lang, 'pm_nick_l')}: {self.nick.value}\n"
            f"⚔️ {t_sync(lang, 'pm_mode_l')}: {self.mode_role.value}\n"
            f"📊 {t_sync(lang, 'pm_exp_l')}: {self.exp.value}\n"
            f"🕒 {t_sync(lang, 'pm_time_l')}: {self.time_mic.value}\n"
            f"💬 {t_sync(lang, 'pm_about_l')}: {self.about.value}"
        )
        from utils.live import conf, get_ch
        g = await conf(interaction.guild)
        ch = get_ch(interaction.guild, g, "search_channel") or interaction.channel
        async with db.conn() as dbc:
            cur = await dbc.execute("INSERT INTO parties(guild_id, owner_id, text) VALUES(?,?,?)",
                                    (interaction.guild.id, interaction.user.id, text))
            await dbc.commit()
            pid = cur.lastrowid
        view = build_party_post(interaction.user, text, pid, lang)
        if isinstance(ch, discord.ForumChannel):
            # форум: анкета = тред
            try:
                thread, starter = await ch.create_thread(
                    name=f"{self.nick.value}"[:95] or f"party-{pid}",
                    content=f"{interaction.user.mention}\n{text}"[:1900],
                    view=view, reason="WARDOGS lfg post")
                async with db.conn() as dbc:
                    await dbc.execute("UPDATE parties SET message_id=? WHERE id=?", (starter.id, pid))
                    await dbc.execute(
                        "INSERT OR REPLACE INTO lfg_threads(guild_id, thread_id, owner_id, title, last_bump) VALUES(?,?,?,?,?)",
                        (interaction.guild.id, thread.id, interaction.user.id, thread.name[:90], int(time.time())))
                    await dbc.commit()
                try:
                    await starter.add_reaction(BUMP_EMOJI)
                except Exception:
                    pass
                try:
                    await thread.edit(locked=True, archived=False, reason="WARDOGS: только анкета + бамп")
                except Exception as e:
                    import logging
                    logging.getLogger("wardogs").warning(f"lfg lock failed {thread.id}: {e}")
                try:
                    await interaction.user.send(t_sync(lang, "lfg_accept_dm"))
                except Exception:
                    pass
                await interaction.response.send_message(t_sync(lang, "lfg_pub").format(ch=ch.mention), ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return
        msg = await ch.send(view=view)
        async with db.conn() as dbc:
            await dbc.execute("UPDATE parties SET message_id=? WHERE id=?", (msg.id, pid))
            await dbc.commit()
        # липкая панель — вниз (сразу, это действие пользователя)
        try:
            from utils.sticky import restick
            await restick(ch, interaction.guild.id, "search_panel_id", build_search_panel, force=True)
        except Exception:
            pass
        await interaction.response.send_message(t_sync(lang, "ps_created").format(ch=ch.mention), ephemeral=True)


async def handle_party_button(interaction: discord.Interaction, custom_id: str, party_id):
    try:
        from utils.i18n import get_lang as _tgl, t_sync
        lang = await _tgl(interaction.guild.id)
        if custom_id == "party:create":
            await interaction.response.send_modal(PartyModal(lang))
            return
        elif custom_id == "party:scam":
            v = discord.ui.LayoutView(timeout=60)
            v.add_item(discord.ui.Container(
                discord.ui.TextDisplay(f"{t_sync(lang, 'ps_scam_t')}\n{t_sync(lang, 'ps_scam_b')}"),
                accent_color=config.ACCENT_RED,
            ))
            await interaction.response.send_message(view=v, ephemeral=True)
        elif custom_id == "party:mkvoice":
            # быстрый пати-войс
            cat = interaction.guild.categories[0] if interaction.guild.categories else None
            vc = await interaction.guild.create_voice_channel(f"{t_sync(lang, 'party_pref')}{interaction.user.display_name}", category=cat, reason="party voice")
            await interaction.response.send_message(t_sync(lang, "ps_mkvoice").format(ch=vc.mention), ephemeral=True)
        elif custom_id == "party:joininfo":
            await interaction.response.send_message(t_sync(lang, "ps_joininfo"), ephemeral=True)
        elif custom_id.startswith("party:dm:"):
            owner_id = int(custom_id.split(":")[-1])
            owner = interaction.guild.get_member(owner_id)
            v = discord.ui.LayoutView(timeout=60)
            v.add_item(discord.ui.Container(
                discord.ui.TextDisplay(f"{t_sync(lang, 'ps_dm_t').format(owner=owner.mention if owner else '?')}\n{t_sync(lang, 'ps_dm_b')}"),
                accent_color=config.ACCENT_RED,
            ))
            await interaction.response.send_message(view=v, ephemeral=True)
        elif custom_id.startswith("party:join:"):
            pid = custom_id.split(":")[-1]
            async with db.conn() as dbc:
                dbc.row_factory = aiosqlite.Row
                async with dbc.execute("SELECT * FROM parties WHERE id=?", (pid,)) as cur:
                    row = await cur.fetchone()
                if not row:
                    await interaction.response.send_message(t_sync(lang, "ps_noparty"), ephemeral=True)
                    return
                members = (row["members"] or "").split(",") if row["members"] else []
                if str(interaction.user.id) not in members:
                    members.append(str(interaction.user.id))
                    await dbc.execute("UPDATE parties SET members=? WHERE id=?", (",".join(members), pid))
                    await dbc.commit()
            # уведомим владельца в ЛС
            try:
                owner = interaction.guild.get_member(row["owner_id"])
                if owner:
                    await owner.send(t_sync(lang, "ps_join_dm").format(user=interaction.user.mention, guild=interaction.guild.name))
            except Exception:
                pass
            await interaction.response.send_message(t_sync(lang, "ps_joined"), ephemeral=True)
    except (discord.errors.InteractionResponded, discord.errors.HTTPException, discord.errors.NotFound):
        pass


class SearchParty(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bump_reminder.start()

    def cog_unload(self):
        self.bump_reminder.cancel()

    @tasks.loop(hours=24)
    async def bump_reminder(self):
        """ЛС: пора бампать анкету (окно 1–2 дня — один раз в сутки)."""
        try:
            now = int(time.time())
            for guild in self.bot.guilds:
                if not await db.is_on(guild.id, "search"):
                    continue
                from utils.i18n import get_lang as _tgl, t_sync
                lang = await _tgl(guild.id)
                async with db.conn() as dbc:
                    dbc.row_factory = aiosqlite.Row
                    try:
                        async with dbc.execute(
                            "SELECT * FROM lfg_threads WHERE guild_id=? AND last_bump<=? AND last_bump>?",
                            (guild.id, now - 1 * 86400, now - 2 * 86400)) as cur:
                            rows = await cur.fetchall()
                    except Exception:
                        continue
                for r in rows:
                    thread = guild.get_thread(r["thread_id"])
                    if thread is None or thread.archived:
                        continue
                    owner = guild.get_member(r["owner_id"])
                    if owner is None:
                        continue
                    try:
                        await owner.send(t_sync(lang, "rm_lfg").format(t=thread.name))
                    except Exception:
                        pass
        except Exception:
            pass

    @bump_reminder.before_loop
    async def _before_reminder(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="post_search", description="Панель поиска / Search panel (админ/admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def post_search(self, interaction: discord.Interaction):
        from utils.i18n import get_lang as _tgl, t_sync
        lang = await _tgl(interaction.guild.id)
        await interaction.response.defer(ephemeral=True)
        from utils.live import conf, get_ch
        g = await conf(interaction.guild)
        ch = get_ch(interaction.guild, g, "search_channel")
        if isinstance(ch, discord.ForumChannel):
            await ensure_lfg_example(ch)
            await interaction.followup.send(t_sync(lang, "ps_panel_bottom"), ephemeral=True)
        else:
            from utils.sticky import restick
            await restick(interaction.channel, interaction.guild.id, "search_panel_id", build_search_panel, force=True)
            await interaction.followup.send(t_sync(lang, "ps_panel_bottom"), ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # legacy текст: панель вниз. Для форума не нужно.
        if message.author.bot or not message.guild:
            return
        if not await db.is_on(message.guild.id, "search"):
            return
        from utils.live import conf
        g = await conf(message.guild)
        if message.channel.id != (g.get("search_channel") or 0):
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        if message.author.id == self.bot.user.id:
            return
        from utils.sticky import restick
        try:
            await restick(message.channel, message.guild.id, "search_panel_id", build_search_panel)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        """Ручной пост в LFG-форуме → ⬆️ + регистрация + лок + ЛС."""
        try:
            if not thread.guild or not await db.is_on(thread.guild.id, "search"):
                return
            from utils.live import conf, is_search_forum
            g = await conf(thread.guild)
            if not is_search_forum(thread.guild, thread.parent_id, g):
                return
            if thread.name.startswith("📌"):
                return
            from utils.i18n import get_lang as _tgl, t_sync
            lang = await _tgl(thread.guild.id)
            async with db.conn() as dbc:
                await dbc.execute(
                    "INSERT OR REPLACE INTO lfg_threads(guild_id, thread_id, owner_id, title, last_bump) VALUES(?,?,?,?,?)",
                    (thread.guild.id, thread.id, thread.owner_id or 0, thread.name[:90], int(time.time())))
                await dbc.commit()
            try:
                starter = await thread.fetch_starter_message() if hasattr(thread, "fetch_starter_message") else None
            except Exception:
                starter = None
            if starter is not None:
                try:
                    await starter.add_reaction(BUMP_EMOJI)
                except Exception:
                    pass
            owner = thread.guild.get_member(thread.owner_id) if thread.owner_id else None
            if owner:
                try:
                    await owner.send(t_sync(lang, "lfg_accept_dm"))
                except Exception:
                    pass
            try:
                await thread.edit(locked=True, archived=False, reason="WARDOGS: только анкета + бамп")
            except Exception as e:
                import logging
                logging.getLogger("wardogs").warning(f"lfg lock failed {thread.id}: {e}")
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Бамп LFG: ⬆️ на своём посте раз в 3 дня."""
        try:
            if str(payload.emoji) != BUMP_EMOJI or (payload.member and payload.member.bot):
                return
            guild = self.bot.get_guild(payload.guild_id)
            if guild is None or not await db.is_on(guild.id, "search"):
                return
            from utils.live import conf, is_search_forum
            g = await conf(guild)
            thread = guild.get_thread(payload.channel_id)
            if thread is None or not is_search_forum(guild, thread.parent_id, g):
                return
            if thread.name.startswith("📌"):
                return
            from utils.i18n import get_lang as _tgl, t_sync
            lang = await _tgl(guild.id)
            async with db.conn() as dbc:
                dbc.row_factory = aiosqlite.Row
                async with dbc.execute("SELECT * FROM lfg_threads WHERE thread_id=?", (thread.id,)) as cur:
                    row = await cur.fetchone()
            now = int(time.time())
            owner_id = (row["owner_id"] if row else thread.owner_id) or 0
            if payload.user_id != owner_id and not (payload.member and payload.member.guild_permissions.administrator):
                try:
                    msg = await thread.fetch_message(payload.message_id)
                    user = payload.member or guild.get_member(payload.user_id)
                    await msg.remove_reaction(BUMP_EMOJI, user)
                except Exception:
                    pass
                return
            last = (row["last_bump"] if row else 0) or 0
            if now - last < BUMP_COOLDOWN:
                left_h = (BUMP_COOLDOWN - (now - last)) // 3600
                try:
                    await payload.member.send(t_sync(lang, "lfg_bump_cd").format(h=left_h))
                except Exception:
                    pass
                try:
                    msg = await thread.fetch_message(payload.message_id)
                    await msg.remove_reaction(BUMP_EMOJI, payload.member)
                except Exception:
                    pass
                return
            try:
                await thread.send(f"{BUMP_EMOJI}")
            except Exception:
                try:
                    await thread.edit(locked=False, reason="WARDOGS bump")
                    await thread.send(f"{BUMP_EMOJI}")
                    await thread.edit(locked=True, archived=False, reason="WARDOGS: только анкета + бамп")
                except Exception:
                    pass
            member = guild.get_member(payload.user_id)
            if member:
                try:
                    await member.send(f"{BUMP_EMOJI} **{thread.name}** {t_sync(lang, 'lfg_bumped')}\n{t_sync(lang, 'lfg_accept_dm')}")
                except Exception:
                    pass
            async with db.conn() as dbc:
                await dbc.execute(
                    "INSERT OR REPLACE INTO lfg_threads(guild_id, thread_id, owner_id, title, last_bump) VALUES(?,?,?,?,?)",
                    (guild.id, thread.id, owner_id, thread.name[:90], now))
                await dbc.commit()
            try:
                msg = await thread.fetch_message(payload.message_id)
                await msg.remove_reaction(BUMP_EMOJI, payload.member)
            except Exception:
                pass
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        cid = (interaction.data or {}).get("custom_id", "")
        if not cid.startswith("party:"):
            return
        if interaction.response.is_done():
            return
        if not await db.is_on(interaction.guild.id, "search"):
            return
        await handle_party_button(interaction, cid, None)


async def setup(bot):
    await bot.add_cog(SearchParty(bot))
