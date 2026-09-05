"""Заявки кланов — ФОРУМ (набор в клан) + бамп эмодзи раз в 3 дня."""
import time
import discord
from discord import app_commands
from discord.ext import commands, tasks
import config
from database import db
import aiosqlite

BUMP_EMOJI = "⬆️"
BUMP_COOLDOWN = 3 * 24 * 3600  # 3 дня

CLAN_EXAMPLE = (
    "🏛️ **НАБОР В КЛАН — шаблон анкеты**\n"
    "Скопируй блок ниже в свой пост и заполни. Картинку (лого/баннер клана) прикрепи к посту — она станет обложкой в галерее.\n"
    "```\n"
    "🏛️ НАБОР В КЛАН [ТЕГ]\n"
    "О нас:\n"
    "Кто вы, во что играете, атмосфера, Discord, голосовые, тактики.\n\n"
    "Кого ищем:\n"
    "Кого хотите видеть: новичок/ветеран, микрофон, главное — свой по духу.\n\n"
    "---\n\n"
    "📋 АНКЕТА КЛАНА\n\n"
    "🏷️ Название + тег:\n"
    "⚔️ Фракция (LONESTAR / VALKYRA / MANTICORE):\n"
    "👥 Состав / онлайн:\n"
    "🕒 Прайм-тайм:\n"
    "📋 Требования к новичкам:\n"
    "🎯 Цели (Control Zone, FOB, Hot Zone):\n"
    "💬 Связь (Discord / ЛС лидера):\n"
    "```\n"
    "---\n"
    "📋 **Хочешь ВСТУПИТЬ в клан?** Заполни в чужом посте ответом:\n"
    "```\n"
    "🎮 Игровой ник:\n"
    "📅 Возраст:\n"
    "🌍 Часовой пояс:\n"
    "🎯 Опыт (часов / уровень):\n"
    "⚔️ Роль в игре:\n"
    "🎙️ Микрофон:\n"
    "🕒 Когда играешь:\n"
    "💬 Почему хочешь к нам:\n"
    "```\n"
    "-# Посты только для анкет — писать в чужих постах нельзя, тред закрыт. Поднять свой пост: ⬆️ раз в 3 дня."
)

FORUM_GUIDE = (
    "👑 Набор в клан WARDOGS TOOLS. Создай пост по шаблону из закрепа 📌 (можно с картинкой — станет обложкой). "
    "Обсуждения в постах закрыты — только ⬆️ раз в 3 дня поднимает клан выше всех."
)


def build_clan_panel(lang: str = "ru") -> discord.ui.LayoutView:
    from utils.i18n import t_sync
    v = discord.ui.LayoutView(timeout=None)
    c = discord.ui.Container(
        discord.ui.Section(
            discord.ui.TextDisplay(f"**{t_sync(lang, 'cl_create')}**"),
            accessory=discord.ui.Button(emoji="👥", custom_id="clan:create", style=discord.ButtonStyle.secondary),
        ),
        discord.ui.Section(
            discord.ui.TextDisplay(f"**{t_sync(lang, 'cl_scam')}**"),
            accessory=discord.ui.Button(emoji="💀", custom_id="clan:scam", style=discord.ButtonStyle.secondary),
        ),
        discord.ui.Section(
            discord.ui.TextDisplay(f"**{t_sync(lang, 'cl_transfer')}**"),
            accessory=discord.ui.Button(emoji="⏩", custom_id="clan:transfer", style=discord.ButtonStyle.secondary),
        ),
        discord.ui.Section(
            discord.ui.TextDisplay(f"**{t_sync(lang, 'cl_howpost')}**"),
            accessory=discord.ui.Button(emoji="❓", custom_id="clan:howpost", style=discord.ButtonStyle.secondary),
        ),
        accent_color=config.ACCENT_YELLOW,
    )
    v.add_item(c)
    # ВАЖНО: колбэки НЕ вешаем — единый обработчик on_interaction ниже.
    # Иначе дабл-ответ: callback + on_interaction = Already acknowledged.
    return v


class ClanModal(discord.ui.Modal):
    def __init__(self, lang: str = "ru"):
        from utils.i18n import t_sync
        super().__init__(title=t_sync(lang, "cl_create")[:45])
        self.clan_name = discord.ui.TextInput(label=t_sync(lang, "cm_name_l"), max_length=60, placeholder="WARDOGS [WD]")
        self.faction = discord.ui.TextInput(label=t_sync(lang, "cm_fac_l"), max_length=30, placeholder="LONESTAR / VALKYRA / MANTICORE")
        self.squad = discord.ui.TextInput(label=t_sync(lang, "cm_squad_l"), max_length=200, placeholder="12 / 6-8 / 19:00-23:00")
        self.reqs = discord.ui.TextInput(label=t_sync(lang, "cm_reqs_l"), style=discord.TextStyle.long, max_length=500, placeholder="...")
        self.about = discord.ui.TextInput(label=t_sync(lang, "cm_about_l"), style=discord.TextStyle.long, max_length=500, placeholder="...")
        for _i in (self.clan_name, self.faction, self.squad, self.reqs, self.about):
            self.add_item(_i)

    async def on_submit(self, interaction: discord.Interaction):
        from utils.sticky import restick
        g = await db.get_guild(interaction.guild.id)
        ch = interaction.guild.get_channel(g.get("clan_channel") or 0) or interaction.channel
        full = (
            f"**Тег:** {self.clan_name.value}\n"
            f"**Фракция:** {self.faction.value}\n"
            f"**Состав/прайм:** {self.squad.value}\n"
            f"**Требования:** {self.reqs.value}\n"
            f"**О клане:** {self.about.value}"
        )
        async with db.conn() as dbc:
            cur = await dbc.execute("INSERT INTO clan_apps(guild_id, owner_id, clan_name, description) VALUES(?,?,?,?)",
                                    (interaction.guild.id, interaction.user.id, self.clan_name.value, full))
            await dbc.commit()
            cid = cur.lastrowid
        v = discord.ui.LayoutView(timeout=None)
        v.add_item(discord.ui.Container(
            discord.ui.TextDisplay(f"## 👑 {self.clan_name.value}\n{full}\n\n-# Лидер: {interaction.user.mention}"),
            accent_color=config.ACCENT_RED,
        ))
        row = discord.ui.ActionRow()
        b = discord.ui.Button(label="Вступить", emoji="✉️", custom_id=f"clan:join:{cid}", style=discord.ButtonStyle.primary)
        row.add_item(b)
        v.add_item(row)
        msg = await ch.send(view=v)
        async with db.conn() as dbc:
            await dbc.execute("UPDATE clan_apps SET message_id=? WHERE id=?", (msg.id, cid))
            await dbc.commit()
        try:
            await restick(ch, interaction.guild.id, "clan_panel_id", build_clan_panel, force=True)
        except Exception:
            pass
        from utils.i18n import get_lang as _tgl, t_sync
        await interaction.response.send_message(t_sync(await _tgl(interaction.guild.id), "cl_pub").format(ch=ch.mention), ephemeral=True)


async def handle_clan(interaction: discord.Interaction, cid: str):
    try:
        from utils.i18n import get_lang as _tgl, t_sync
        lang = await _tgl(interaction.guild.id)
        if cid == "clan:create":
            await interaction.response.send_modal(ClanModal(lang))
            return
        elif cid == "clan:scam":
            v = discord.ui.LayoutView(timeout=60)
            v.add_item(discord.ui.Container(discord.ui.TextDisplay(f"{t_sync(lang, 'cl_scam_t')}\n{t_sync(lang, 'cl_scam_b')}"), accent_color=config.ACCENT_RED))
            await interaction.response.send_message(view=v, ephemeral=True)
        elif cid == "clan:transfer":
            v = discord.ui.LayoutView(timeout=60)
            v.add_item(discord.ui.Container(discord.ui.TextDisplay(f"{t_sync(lang, 'cl_transfer_t')}\n{t_sync(lang, 'cl_transfer_b')}"), accent_color=config.ACCENT_RED))
            await interaction.response.send_message(view=v, ephemeral=True)
        elif cid == "clan:howpost":
            await interaction.response.send_message(t_sync(lang, "cl_howpost_b"), ephemeral=True)
        elif cid.startswith("clan:join:"):
            app_id = cid.split(":")[-1]
            async with db.conn() as dbc:
                dbc.row_factory = aiosqlite.Row
                async with dbc.execute("SELECT * FROM clan_apps WHERE id=?", (app_id,)) as cur:
                    row = await cur.fetchone()
            if not row:
                await interaction.response.send_message(t_sync(lang, "cl_noreq"), ephemeral=True)
                return
            try:
                owner = interaction.guild.get_member(row["owner_id"])
                if owner:
                    await owner.send(t_sync(lang, "cl_lead_dm").format(user=interaction.user, clan=row["clan_name"], guild=interaction.guild.name))
            except Exception:
                pass
            await interaction.response.send_message(t_sync(lang, "cl_lead_ok"), ephemeral=True)
    except (discord.errors.InteractionResponded, discord.errors.HTTPException, discord.errors.NotFound):
        pass


async def ensure_forum_example(forum: discord.ForumChannel):
    """Закрепа-пример в форуме: тред с шаблоном анкеты."""
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
        thread, msg = await forum.create_thread(
            name="📌 Пример анкеты клана",
            content=CLAN_EXAMPLE,
            reason="WARDOGS clan example",
        )
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


class Clans(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bump_reminder.start()

    def cog_unload(self):
        self.bump_reminder.cancel()

    @tasks.loop(hours=24)
    async def bump_reminder(self):
        """ЛС владельцам: пора бампать (3–4 дня с прошлого бампа — шлём один раз)."""
        try:
            now = int(time.time())
            for guild in self.bot.guilds:
                if not await db.is_on(guild.id, "clans"):
                    continue
                from utils.i18n import get_lang as _tgl, t_sync
                lang = await _tgl(guild.id)
                async with db.conn() as dbc:
                    dbc.row_factory = aiosqlite.Row
                    async with dbc.execute(
                        "SELECT * FROM clan_threads WHERE guild_id=? AND last_bump<=? AND last_bump>?",
                        (guild.id, now - 3 * 86400, now - 4 * 86400)) as cur:
                        rows = await cur.fetchall()
                for r in rows:
                    thread = guild.get_thread(r["thread_id"])
                    if thread is None or thread.archived:
                        continue
                    owner = guild.get_member(r["owner_id"])
                    if owner is None:
                        continue
                    try:
                        await owner.send(t_sync(lang, "rm_clan").format(t=thread.name))
                    except Exception:
                        pass
        except Exception:
            pass

    @bump_reminder.before_loop
    async def _before_reminder(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="post_clans", description="Форум кланов / Clan forum refresh (админ/admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def post_clans(self, interaction: discord.Interaction):
        from utils.i18n import get_lang as _tgl, t_sync
        lang = await _tgl(interaction.guild.id)
        await interaction.response.defer(ephemeral=True)
        g = await db.get_guild(interaction.guild.id)
        ch = interaction.guild.get_channel(g.get("clan_channel") or 0)
        if isinstance(ch, discord.ForumChannel):
            await ensure_forum_example(ch)
            await interaction.followup.send(t_sync(lang, "cl_panel_bottom"), ephemeral=True)
        elif isinstance(ch, discord.TextChannel):
            from utils.sticky import restick
            await restick(ch, interaction.guild.id, "clan_panel_id", build_clan_panel, force=True)
            await interaction.followup.send(t_sync(lang, "cl_panel_bottom"), ephemeral=True)
        else:
            await interaction.followup.send(t_sync(lang, "cl_nosetup"), ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # legacy текст-канал: липкая панель. Для форума не нужно.
        if message.author.bot or not message.guild:
            return
        if not await db.is_on(message.guild.id, "clans"):
            return
        g = await db.get_guild(message.guild.id)
        if message.channel.id != (g.get("clan_channel") or 0):
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        if message.author.id == self.bot.user.id:
            return
        from utils.sticky import restick
        try:
            await restick(message.channel, message.guild.id, "clan_panel_id", build_clan_panel)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        """Новый пост в форуме кланов → эмодзи ⬆️ + регистрация + лок (писать нельзя, только бамп)."""
        try:
            if not thread.guild:
                return
            if not await db.is_on(thread.guild.id, "clans"):
                return
            g = await db.get_guild(thread.guild.id)
            if thread.parent_id != (g.get("clan_channel") or 0):
                return
            if thread.name.startswith("📌"):
                return  # пример
            async with db.conn() as dbc:
                await dbc.execute(
                    "INSERT OR REPLACE INTO clan_threads(guild_id, thread_id, owner_id, clan_name, last_bump) VALUES(?,?,?,?,?)",
                    (thread.guild.id, thread.id, thread.owner_id or 0, thread.name[:60], int(time.time())),
                )
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
            # текст — в ЛС владельцу (в треде только анкета)
            from utils.i18n import get_lang as _gl, t_sync as _tt
            try:
                _lang = await _gl(thread.guild.id)
            except Exception:
                _lang = "ru"
            owner = thread.guild.get_member(thread.owner_id) if thread.owner_id else None
            if owner:
                try:
                    await owner.send(_tt(_lang, "clan_accept_dm"))
                except Exception:
                    try:
                        await thread.send(f"👑 Анкета принята! Жми {BUMP_EMOJI} на первом сообщении раз в 3 дня чтобы поднять клан.")
                    except Exception:
                        pass
            # жёсткий лок: не пишет НИКТО, даже владелец — только анкета + бамп
            try:
                await thread.edit(locked=True, archived=False, reason="WARDOGS: только анкета + бамп")
            except Exception as e:
                import logging
                logging.getLogger("wardogs").warning(f"clan lock failed {thread.id}: {e}")
            # закрыть обсуждение: писать в посте нельзя, только бамп
            try:
                await thread.edit(locked=True, reason="WARDOGS: только анкета + бамп")
            except Exception:
                pass
            from utils.alog import send_log
            await send_log(thread.guild, f"👑 Клан-пост **{thread.name}** создал {thread.owner.mention if thread.owner else '?'}")
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Бамп: ⬆️ на своём посте раз в 3 дня поднимает тред."""
        try:
            if str(payload.emoji) != BUMP_EMOJI or payload.member and payload.member.bot:
                return
            guild = self.bot.get_guild(payload.guild_id)
            if guild is None:
                return
            if not await db.is_on(guild.id, "clans"):
                return
            g = await db.get_guild(guild.id)
            if g.get("clan_channel") is None:
                return
            # реакция стоит на стартовом сообщении внутри треда: channel_id = id треда
            thread = guild.get_thread(payload.channel_id)
            if thread is None or thread.parent_id != (g.get("clan_channel") or 0):
                return
            if thread.name.startswith("📌"):
                return  # пример не бампим
            async with db.conn() as dbc:
                dbc.row_factory = aiosqlite.Row
                async with dbc.execute("SELECT * FROM clan_threads WHERE thread_id=?", (thread.id,)) as cur:
                    row = await cur.fetchone()
            now = int(time.time())
            owner_id = (row["owner_id"] if row else thread.owner_id) or 0
            if payload.user_id != owner_id and not (payload.member and payload.member.guild_permissions.administrator):
                # чужой жмёт — тихо снять
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
                from utils.i18n import get_lang as _gl3, t_sync as _tt3
                try:
                    _lang3 = await _gl3(guild.id)
                except Exception:
                    _lang3 = "ru"
                try:
                    await payload.member.send(_tt3(_lang3, "cl_bump_cd").format(clan=thread.name, h=left_h))
                except Exception:
                    pass
                try:
                    msg = await thread.fetch_message(payload.message_id)
                    await msg.remove_reaction(BUMP_EMOJI, payload.member)
                except Exception:
                    pass
                return
            # бамп: в тред только ⬆️ (поднимает вверх без спама), текст — в ЛС владельцу
            try:
                await thread.send(f"{BUMP_EMOJI}")
            except Exception:
                try:
                    await thread.edit(locked=False, reason="WARDOGS bump")
                    await thread.send(f"{BUMP_EMOJI}")
                    await thread.edit(locked=True, archived=False, reason="WARDOGS: только анкета + бамп")
                except Exception:
                    pass
            from utils.i18n import get_lang as _gl2, t_sync as _tt2
            try:
                _lang2 = await _gl2(guild.id)
            except Exception:
                _lang2 = "ru"
            member = guild.get_member(payload.user_id)
            if member:
                try:
                    await member.send(f"{BUMP_EMOJI} **{thread.name}** {_tt2(_lang2, 'cl_bumped')}\n{_tt2(_lang2, 'clan_accept_dm')}")
                except Exception:
                    pass
            from utils.alog import send_log as _cslog
            member = guild.get_member(payload.user_id)
            await _cslog(guild, f"⬆️ Бамп клана **{thread.name}** от {member.mention if member else payload.user_id}")
            async with db.conn() as dbc:
                await dbc.execute(
                    "INSERT OR REPLACE INTO clan_threads(guild_id, thread_id, owner_id, clan_name, last_bump) VALUES(?,?,?,?,?)",
                    (guild.id, thread.id, owner_id, thread.name[:60], now),
                )
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
        if not cid.startswith("clan:"):
            return
        if interaction.response.is_done():
            return
        if not await db.is_on(interaction.guild.id, "clans"):
            return
        await handle_clan(interaction, cid)


async def setup(bot):
    await bot.add_cog(Clans(bot))
