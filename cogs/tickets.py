"""Система тикетов как на скрине: баннер + категории + FAQ (всё V2)."""
import discord
from discord import app_commands
from discord.ext import commands
import config
from database import db


def build_ticket_panel(lang: str = "ru", banner_url: str = "") -> discord.ui.LayoutView:
    from utils.i18n import t_sync
    view = discord.ui.LayoutView(timeout=None)

    banner = discord.ui.Container(
        discord.ui.TextDisplay(t_sync(lang, "sup_banner")),
        accent_color=config.ACCENT_YELLOW,
    )
    if banner_url:
        try:
            banner.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(media=banner_url)))
        except Exception:
            pass
    view.add_item(banner)

    # 2) Основная панель
    c = discord.ui.Container(
        discord.ui.TextDisplay(t_sync(lang, "sup_title") + "\n" + t_sync(lang, "sup_info")),
        discord.ui.Separator(),
        discord.ui.TextDisplay(t_sync(lang, "c_h")),
        discord.ui.Section(
            discord.ui.TextDisplay(t_sync(lang, "t_player")),
            accessory=discord.ui.Button(emoji="👥", custom_id="ticket:create:player_report", style=discord.ButtonStyle.secondary),
        ),
        discord.ui.Section(
            discord.ui.TextDisplay(t_sync(lang, "t_staff")),
            accessory=discord.ui.Button(emoji="🛡️", custom_id="ticket:create:staff_report", style=discord.ButtonStyle.secondary),
        ),
        discord.ui.Separator(),
        discord.ui.TextDisplay(t_sync(lang, "r_h")),
        discord.ui.Section(
            discord.ui.TextDisplay(t_sync(lang, "t_appeal")),
            accessory=discord.ui.Button(emoji="🧾", custom_id="ticket:create:appeal", style=discord.ButtonStyle.secondary),
        ),
        discord.ui.Separator(),
        discord.ui.TextDisplay(t_sync(lang, "i_h")),
        discord.ui.Section(
            discord.ui.TextDisplay(t_sync(lang, "t_bug")),
            accessory=discord.ui.Button(emoji="🎯", custom_id="ticket:create:bug", style=discord.ButtonStyle.secondary),
        ),
        discord.ui.Section(
            discord.ui.TextDisplay(t_sync(lang, "t_suggest")),
            accessory=discord.ui.Button(emoji="🎯", custom_id="ticket:create:suggest", style=discord.ButtonStyle.secondary),
        ),
        accent_color=config.ACCENT_RED,
    )
    view.add_item(c)

    # 3) FAQ селект
    faq_row = discord.ui.ActionRow()
    faq = discord.ui.Select(
        custom_id="faq:select",
        placeholder=t_sync(lang, "faq_ph"),
        options=[
            discord.SelectOption(label=t_sync(lang, "faq_cash_l"), emoji="💰", value="how_cash"),
            discord.SelectOption(label=t_sync(lang, "faq_fac_l"), emoji="⚔️", value="how_factions"),
        ],
    )
    faq_row.add_item(faq)

    faq_container = discord.ui.Container(faq_row, accent_color=None)
    view.add_item(faq_container)

    # единый обработчик Tickets.on_interaction ниже, колбэки не вешаем
    return view


async def faq_callback(interaction: discord.Interaction):
    try:
        from utils.i18n import get_lang, t_sync
        lang = await get_lang(interaction.guild.id)
        key = interaction.data["values"][0]
        labels = {"how_cash": ("faq_cash_l", "faq_cash_a"), "how_factions": ("faq_fac_l", "faq_fac_a")}
        if key not in labels:
            await interaction.response.send_message("...", ephemeral=True)
            return
        lk, ak = labels[key]
        v = discord.ui.LayoutView(timeout=60)
        v.add_item(discord.ui.Container(
            discord.ui.TextDisplay(f"## {t_sync(lang, lk)}\n{t_sync(lang, ak)}"),
            accent_color=config.ACCENT_RED,
        ))
        await interaction.response.send_message(view=v, ephemeral=True)
    except (discord.errors.InteractionResponded, discord.errors.HTTPException, discord.errors.NotFound):
        pass


def ticket_meta(type_key: str, lang: str = "ru") -> dict:
    from utils.i18n import t_sync
    base = config.TICKET_TYPES.get(type_key, {"emoji": "🎫"})
    return {"emoji": base["emoji"], "label": t_sync(lang, "tt_" + type_key)}


class TicketModal(discord.ui.Modal):
    def __init__(self, type_key: str, lang: str = "ru"):
        from utils.i18n import t_sync
        meta = ticket_meta(type_key, lang)
        super().__init__(title=meta["label"][:45])
        self.type_key = type_key
        self.nick = discord.ui.TextInput(label=t_sync(lang, "tm_nick_l"), placeholder=t_sync(lang, "tm_nick_ph"), max_length=100)
        self.desc = discord.ui.TextInput(label=t_sync(lang, "tm_desc_l"), style=discord.TextStyle.long, max_length=1500, placeholder=t_sync(lang, "tm_desc_ph"))
        self.add_item(self.nick)
        self.add_item(self.desc)

    async def on_submit(self, interaction: discord.Interaction):
        from utils.i18n import get_lang as _tgl, t_sync
        lang = await _tgl(interaction.guild.id)
        body = f"**{t_sync(lang, 'tk_from')}:** {interaction.user.mention} (`{self.nick.value}`)\n\n{self.desc.value}"
        await create_ticket(interaction, self.type_key, body)


async def open_ticket_modal(interaction: discord.Interaction, type_key: str):
    try:
        from utils.i18n import get_lang
        await interaction.response.send_modal(TicketModal(type_key, await get_lang(interaction.guild.id)))
    except (discord.errors.InteractionResponded, discord.errors.HTTPException, discord.errors.NotFound):
        pass


async def create_ticket(interaction: discord.Interaction, type_key: str, body: str):
    guild = interaction.guild
    from utils.i18n import get_lang as _tgl, t_sync
    lang = await _tgl(guild.id)
    if not await db.is_on(guild.id, "tickets"):
        await interaction.response.send_message(t_sync(lang, "tk_mod_off"), ephemeral=True)
        return
    g = await db.get_guild(guild.id)
    cat_id = g.get("ticket_category")
    category = guild.get_channel(cat_id) if cat_id else None
    staff_id = g.get("ticket_staff_role")
    staff = guild.get_role(staff_id) if staff_id else None

    num = await db.next_ticket_num(guild.id)
    meta = ticket_meta(type_key, lang)
    name = f"🎫・{type_key}-{num:04d}"

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }
    if staff:
        overwrites[staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

    channel = await guild.create_text_channel(name, category=category if isinstance(category, discord.CategoryChannel) else None, overwrites=overwrites, reason=f"Ticket {type_key} by {interaction.user}")

    import aiosqlite
    async with db.conn() as dbc:
        await dbc.execute("INSERT INTO tickets(guild_id, channel_id, owner_id, type_key) VALUES(?,?,?,?)",
                          (guild.id, channel.id, interaction.user.id, type_key))
        await dbc.commit()

    v = build_in_ticket_panel(channel.id, meta, body, interaction.user, num, None, lang)

    mention = f"{staff.mention} " if staff else ""
    if mention.strip():
        await channel.send(f"{mention}{interaction.user.mention}")
    else:
        await channel.send(f"{interaction.user.mention} {t_sync(lang, 'tk_created_here')}")
    await channel.send(view=v)
    from utils.alog import send_log
    await send_log(guild, f"🎫 Тикет {channel.mention} `#{num:04d}` • {meta['label']} • от {interaction.user.mention}")
    await interaction.followup.send(t_sync(lang, "tk_created").format(ch=channel.mention), ephemeral=True) if interaction.response.is_done() else await interaction.response.send_message(t_sync(lang, "tk_created").format(ch=channel.mention), ephemeral=True)


def build_in_ticket_panel(channel_id: int, meta: dict, body: str, owner, num: int, claimed, lang: str = "ru") -> discord.ui.LayoutView:
    """Крутая панель внутри тикета: взять в работу, старший, добавить/убрать, архив, закрыть."""
    from utils.i18n import t_sync
    v = discord.ui.LayoutView(timeout=None)
    if claimed:
        status = f"{t_sync(lang, 'tk_inwork')}: {claimed.mention}"
    else:
        status = t_sync(lang, "tk_open")
    c = discord.ui.Container(
        discord.ui.TextDisplay(f"## {meta['emoji']} {meta['label']} — #{num:04d}\n{body}\n\n-# {t_sync(lang, 'tk_owner')}: {owner.mention} • {status}"),
        discord.ui.Separator(),
        discord.ui.Section(
            discord.ui.TextDisplay(f"**{t_sync(lang, 'tk_take')}**\n{t_sync(lang, 'tk_take_d')}"),
            accessory=discord.ui.Button(emoji="🙋", custom_id=f"ticket:claim:{channel_id}", style=discord.ButtonStyle.primary),
        ),
        discord.ui.Section(
            discord.ui.TextDisplay(f"**{t_sync(lang, 'tk_senior')}**\n{t_sync(lang, 'tk_senior_d')}"),
            accessory=discord.ui.Button(emoji="⭐", custom_id=f"ticket:senior:{channel_id}", style=discord.ButtonStyle.secondary),
        ),
        discord.ui.Section(
            discord.ui.TextDisplay(f"**{t_sync(lang, 'tk_add')}**\n{t_sync(lang, 'tk_add_d')}"),
            accessory=discord.ui.Button(emoji="➕", custom_id=f"ticket:add:{channel_id}", style=discord.ButtonStyle.secondary),
        ),
        discord.ui.Section(
            discord.ui.TextDisplay(f"**{t_sync(lang, 'tk_remove')}**\n{t_sync(lang, 'tk_remove_d')}"),
            accessory=discord.ui.Button(emoji="➖", custom_id=f"ticket:remove:{channel_id}", style=discord.ButtonStyle.secondary),
        ),
        discord.ui.Section(
            discord.ui.TextDisplay(f"**{t_sync(lang, 'tk_archive')}**\n{t_sync(lang, 'tk_archive_d')}"),
            accessory=discord.ui.Button(emoji="🗃️", custom_id=f"ticket:archive:{channel_id}", style=discord.ButtonStyle.secondary),
        ),
        accent_color=config.ACCENT_YELLOW,
    )
    v.add_item(c)
    row = discord.ui.ActionRow()
    row.add_item(discord.ui.Button(label=t_sync(lang, "tk_close"), emoji="🔒", custom_id=f"ticket:close:{channel_id}", style=discord.ButtonStyle.danger))
    v.add_item(row)
    return v


async def _ticket_row(guild_id: int, channel_id: int):
    import aiosqlite
    async with db.conn() as dbc:
        dbc.row_factory = aiosqlite.Row
        async with dbc.execute("SELECT * FROM tickets WHERE guild_id=? AND channel_id=?", (guild_id, channel_id)) as cur:
            return await cur.fetchone()


async def _resolve_member(guild: discord.Guild, text: str):
    import re
    t = text.strip()
    m = re.search(r"\d{15,}", t)
    if m:
        mem = guild.get_member(int(m.group(0)))
        if mem:
            return mem
    if t.isdigit():
        return guild.get_member(int(t))
    low = t.strip("@").lower()
    for mem in guild.members:
        if mem.name.lower() == low or mem.display_name.lower() == low:
            return mem
    return None


class TicketUserModal(discord.ui.Modal):
    def __init__(self, action: str, channel_id: int, lang: str = "ru"):
        from utils.i18n import t_sync
        super().__init__(title=t_sync(lang, "tum_add_t") if action == "add" else t_sync(lang, "tum_remove_t"))
        self.action = action
        self.channel_id = channel_id
        self.lang = lang
        self.target = discord.ui.TextInput(
            label=t_sync(lang, "tum_user_l"),
            placeholder=t_sync(lang, "tum_user_ph"),
            max_length=100,
        )
        self.add_item(self.target)

    async def on_submit(self, interaction: discord.Interaction):
        from utils.i18n import t_sync
        lang = self.lang
        guild = interaction.guild
        channel = guild.get_channel(self.channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(t_sync(lang, "tk_gone"), ephemeral=True)
            return
        g = await db.get_guild(guild.id)
        val = self.target.value.strip()
        from utils.alog import send_log
        if val.lower() in ("senior", "старший", "senior support"):
            role = guild.get_role(g.get("ticket_senior_role") or 0)
            if not role:
                await interaction.response.send_message(t_sync(lang, "tk_nosenior"), ephemeral=True)
                return
            if self.action == "add":
                await channel.set_permissions(role, view_channel=True, send_messages=True, reason=f"ticket by {interaction.user}")
                await channel.send(f"⭐ {role.mention} позвал {interaction.user.mention}")
                await send_log(guild, f"⭐ В {channel.mention} добавлен старший ({role.name}) — {interaction.user.mention}")
                await interaction.response.send_message(t_sync(lang, "tu_senior_added").format(role=role.name), ephemeral=True)
            else:
                await channel.set_permissions(role, overwrite=None, reason=f"ticket by {interaction.user}")
                await send_log(guild, f"➖ Из {channel.mention} убран старший — {interaction.user.mention}")
                await interaction.response.send_message(t_sync(lang, "tu_senior_removed"), ephemeral=True)
            return
        mem = await _resolve_member(guild, val)
        if not mem:
            await interaction.response.send_message(t_sync(lang, "tu_nouser"), ephemeral=True)
            return
        if self.action == "add":
            await channel.set_permissions(mem, view_channel=True, send_messages=True, attach_files=True, reason=f"ticket by {interaction.user}")
            await channel.send(f"➕ {mem.mention} добавлен — позвал {interaction.user.mention}")
            await send_log(guild, f"➕ В {channel.mention} добавлен {mem.mention} — {interaction.user.mention}")
            await interaction.response.send_message(t_sync(lang, "tu_added").format(user=mem.mention), ephemeral=True)
        else:
            await channel.set_permissions(mem, overwrite=None, reason=f"ticket by {interaction.user}")
            await send_log(guild, f"➖ Из {channel.mention} убран {mem.mention} — {interaction.user.mention}")
            await interaction.response.send_message(t_sync(lang, "tu_removed").format(user=mem.mention), ephemeral=True)


async def _is_staff(guild: discord.Guild, member: discord.Member) -> bool:
    """Support / Senior / админ."""
    if member.guild_permissions.administrator:
        return True
    try:
        g = await db.get_guild(guild.id)
        ids = {g.get("ticket_staff_role") or 0, g.get("ticket_senior_role") or 0}
        return any(r.id in ids for r in member.roles)
    except Exception:
        return False


async def save_transcript(guild: discord.Guild, channel: discord.TextChannel) -> str | None:
    """История тикета в .txt → канал 📄・транскрипты в категории архива. Возвращает имя файла."""
    try:
        msgs = []
        async for m in channel.history(limit=200, oldest_first=True):
            ts = m.created_at.strftime("%d.%m %H:%M")
            att = " [файлы: " + ", ".join(a.filename for a in m.attachments) + "]" if m.attachments else ""
            msgs.append(f"[{ts}] {m.author} ({m.author.id}): {m.content}{att}")
        if not msgs:
            return None
        import io, pathlib
        g = await db.get_guild(guild.id)
        arch = guild.get_channel(g.get("ticket_archive_category") or 0)
        dest = None
        if isinstance(arch, discord.CategoryChannel):
            for ch in arch.text_channels:
                if "транскрипт" in ch.name or "transcript" in ch.name:
                    dest = ch
                    break
            if dest is None:
                try:
                    dest = await guild.create_text_channel("📄・транскрипты", category=arch)
                except Exception:
                    dest = None
        if dest is None:
            return None
        data = f"Тикет #{channel.name} | {guild.name}\n" + "=" * 40 + "\n" + "\n".join(msgs)
        f = discord.File(io.BytesIO(data.encode("utf-8")), filename=f"transcript-{channel.name}.txt")
        await dest.send(f"📄 Транскрипт {channel.mention} (`{channel.name}`)", file=f)
        return f.filename
    except Exception:
        return None


async def ticket_control(interaction: discord.Interaction, cid: str):
    try:
        from utils.i18n import get_lang as _tgl, t_sync
        lang = await _tgl(interaction.guild.id)
        _, action, ch_id = cid.split(":")
        channel = interaction.guild.get_channel(int(ch_id))
        if channel is None:
            await interaction.response.send_message(t_sync(lang, "tk_gone"), ephemeral=True)
            return
        from utils.alog import send_log
        staff = await _is_staff(interaction.guild, interaction.user)
        row = await _ticket_row(interaction.guild.id, channel.id)
        owner_id = row["owner_id"] if row else 0
        # управлять тикетом может стафф; закрыть — ещё и владелец
        if action in ("claim", "senior", "add", "remove", "archive") and not staff:
            await interaction.response.send_message(t_sync(lang, "tk_staff_only"), ephemeral=True)
            return
        if action == "close" and not (staff or interaction.user.id == owner_id):
            await interaction.response.send_message(t_sync(lang, "tk_close_perm"), ephemeral=True)
            return
        if action == "close":
            await interaction.response.send_message(t_sync(lang, "tk_close_soon"), ephemeral=True)
            await send_log(interaction.guild, f"🔒 Тикет {channel.mention} закрыл {interaction.user.mention}")
            try:
                fn = await save_transcript(interaction.guild, channel)
                if fn:
                    await send_log(interaction.guild, f"📄 Транскрипт {channel.name} сохранён ({fn})")
            except Exception:
                pass
            import asyncio
            await asyncio.sleep(3)
            try:
                await channel.delete(reason=f"Closed by {interaction.user}")
            except Exception:
                pass
        elif action == "claim":
            async with db.conn() as dbc:
                await dbc.execute("UPDATE tickets SET claimed_by=? WHERE guild_id=? AND channel_id=?",
                                  (interaction.user.id, interaction.guild.id, channel.id))
                await dbc.commit()
            row = await _ticket_row(interaction.guild.id, channel.id)
            owner = interaction.guild.get_member(row["owner_id"]) if row else None
            meta = ticket_meta(row["type_key"], lang) if row else {"emoji": "🎫", "label": "🎫"}
            try:
                num = int(channel.name.split("-")[-1])
            except Exception:
                num = 0
            try:
                _lang2 = lang
                await interaction.message.edit(view=build_in_ticket_panel(
                    channel.id, meta, f"**{t_sync(lang, 'tk_from')}:** {(owner.mention if owner else '?')}",
                    owner or interaction.user, num, interaction.user, _lang2))
            except Exception:
                pass
            await channel.send(t_sync(lang, "tk_claim_msg").format(mod=interaction.user.mention, owner=owner.mention if owner else "?"))
            await send_log(interaction.guild, f"🙋 Тикет {channel.mention} взял {interaction.user.mention}")
            await interaction.response.send_message(t_sync(lang, "tk_claimed"), ephemeral=True)
        elif action == "senior":
            g = await db.get_guild(interaction.guild.id)
            role = interaction.guild.get_role(g.get("ticket_senior_role") or 0)
            if not role:
                await interaction.response.send_message(t_sync(lang, "tk_nosenior"), ephemeral=True)
                return
            await channel.set_permissions(role, view_channel=True, send_messages=True, reason=f"ticket by {interaction.user}")
            await channel.send(f"⭐ {role.mention} — позвал {interaction.user.mention}, нужна помощь.")
            await send_log(interaction.guild, f"⭐ В {channel.mention} позван старший — {interaction.user.mention}")
            await interaction.response.send_message(t_sync(lang, "tk_senior_in").format(role=role.name), ephemeral=True)
        elif action == "add":
            await interaction.response.send_modal(TicketUserModal("add", channel.id, lang))
        elif action == "remove":
            await interaction.response.send_modal(TicketUserModal("remove", channel.id, lang))
        elif action == "archive":
            g = await db.get_guild(interaction.guild.id)
            arch = interaction.guild.get_channel(g.get("ticket_archive_category") or 0)
            if isinstance(arch, discord.CategoryChannel):
                await channel.edit(category=arch, sync_permissions=False)
                await interaction.response.send_message(t_sync(lang, "tk_archived"), ephemeral=True)
            else:
                await interaction.response.send_message(t_sync(lang, "tk_noarch"), ephemeral=True)
    except (discord.errors.InteractionResponded, discord.errors.HTTPException, discord.errors.NotFound):
        pass


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="post_tickets", description="Панель тикетов / Tickets panel (админ/admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def post_tickets(self, interaction: discord.Interaction):
        from utils.i18n import get_lang as _tgl, t_sync
        lang = await _tgl(interaction.guild.id)
        await interaction.response.defer(ephemeral=True)
        g = await db.get_guild(interaction.guild.id)
        await interaction.channel.send(view=build_ticket_panel(lang, g.get("banner_url") or ""))
        await interaction.followup.send(t_sync(lang, "tk_published"), ephemeral=True)

    @app_commands.command(name="setbanner", description="Баннер панелей / Panels banner (админ/admin)")
    @app_commands.describe(picture="Картинка / Image (без неё = убрать / empty = clear)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setbanner(self, interaction: discord.Interaction, picture: discord.Attachment | None = None):
        from utils.i18n import get_lang as _tgl, t_sync
        lang = await _tgl(interaction.guild.id)
        if picture is None:
            await db.set_guild(interaction.guild.id, banner_url="")
            await interaction.response.send_message(t_sync(lang, "bn_cleared"), ephemeral=True)
            return
        if not (picture.content_type or "").startswith("image/"):
            await interaction.response.send_message(t_sync(lang, "bn_bad"), ephemeral=True)
            return
        await db.set_guild(interaction.guild.id, banner_url=picture.url)
        await interaction.response.send_message(t_sync(lang, "bn_set"), ephemeral=True)

    @app_commands.command(name="setsenior", description="Роль старшего / Senior role (админ/admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setsenior(self, interaction: discord.Interaction, роль: discord.Role):
        from utils.i18n import get_lang as _tgl, t_sync
        lang = await _tgl(interaction.guild.id)
        await db.set_guild(interaction.guild.id, ticket_senior_role=роль.id)
        await interaction.response.send_message(t_sync(lang, "tk_senior_set").format(role=роль.mention), ephemeral=True)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        if interaction.response.is_done():
            return
        cid = (interaction.data or {}).get("custom_id", "")
        if cid.startswith("ticket:create:"):
            if not await db.is_on(interaction.guild.id, "tickets"):
                from utils.i18n import get_lang as _tgl, t_sync
                await interaction.response.send_message(t_sync(await _tgl(interaction.guild.id), "tk_mod_off"), ephemeral=True)
                return
            await open_ticket_modal(interaction, cid.split(":")[-1])
        elif cid == "faq:select":
            await faq_callback(interaction)
        elif cid.startswith("ticket:"):
            if not await db.is_on(interaction.guild.id, "tickets"):
                return
            await ticket_control(interaction, cid)


async def setup(bot):
    await bot.add_cog(Tickets(bot))
