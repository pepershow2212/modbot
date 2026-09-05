"""Мастер-установщик /setupbot + /wipebot — сердце экосистемы. Ставит и удаляет всё."""
import discord
from discord import app_commands
from discord.ext import commands
import config
from database import db


MODULE_ORDER = ["tickets", "search", "clans", "voices", "logs", "moderation", "welcome"]
MODULE_SHORT = {"tickets": "🎫", "search": "🔍", "clans": "👑", "voices": "🔊", "logs": "📜", "moderation": "🛡️", "welcome": "👋"}

import time as _time
_CD: dict[tuple[int, str], float] = {}
CD_ONE = 15
CD_ALL = 60


async def _cooldown_ok(interaction: discord.Interaction, key: str, secs: int) -> bool:
    now = _time.monotonic()
    k = (interaction.guild.id, key)
    left = secs - (now - _CD.get(k, 0))
    if left > 0:
        from utils.i18n import get_lang as _tgl, t_sync
        try:
            await interaction.response.send_message(
                t_sync(await _tgl(interaction.guild.id), "cd_wait").format(n=int(left) + 1), ephemeral=True)
        except Exception:
            pass
        return False
    _CD[k] = now
    return True


async def installed_map(guild: discord.Guild) -> dict:
    """Что реально стоит на сервере (ID из БД резолвится в канал/роль)."""
    g = await db.get_guild(guild.id)

    def has(*cols):
        for c in cols:
            if guild.get_channel(g.get(c) or 0) or guild.get_role(g.get(c) or 0):
                return True
        return False

    return {
        "tickets": has("ticket_panel_channel"),
        "search": has("search_channel"),
        "clans": has("clan_channel"),
        "voices": has("voice_lobby"),
        "logs": has("admin_log_channel"),
        "moderation": has("mod_panel_channel"),
        "welcome": has("welcome_channel"),
    }


async def build_setup_view(guild: discord.Guild) -> discord.ui.LayoutView:
    """Шаг 2: модули с живыми статусами + установить/удалить + тумблеры. Обновляется сама."""
    from utils.i18n import get_lang, t_sync
    lang = await get_lang(guild.id)
    T = lambda k: t_sync(lang, k)
    g = await db.get_guild(guild.id)
    states = {k: bool(g.get(col, 1)) for k, col in db.TOGGLES.items()}
    installed = await installed_map(guild)

    view = discord.ui.LayoutView(timeout=300)
    c = discord.ui.Container(
        discord.ui.TextDisplay(f"## {T('setup_maintitle')}\n{T('setup_step2')}"),
        discord.ui.Separator(),
        accent_color=config.ACCENT_YELLOW,
    )
    for key in MODULE_ORDER:
        ins, on = installed[key], states[key]
        mark = ("✅" if ins else "⬜") + ("🟢" if on else "🔴")
        if ins:
            btn = discord.ui.Button(label="🗑️", custom_id=f"setup:uninstall:{key}", style=discord.ButtonStyle.danger)
        else:
            btn = discord.ui.Button(label=T("install"), emoji=MODULE_SHORT[key], custom_id=f"setup:install:{key}", style=discord.ButtonStyle.primary)
        c.add_item(discord.ui.Section(
            discord.ui.TextDisplay(f"**{T('m_' + key)}** {mark}\n{T('m_' + key + '_d')}"),
            accessory=btn,
        ))
    c.add_item(discord.ui.Separator())
    c.add_item(discord.ui.TextDisplay(T("setup_footer")))
    view.add_item(c)

    # смена языка прямо отсюда (если выбрал не тот)
    lang_row = discord.ui.ActionRow()
    lang_sel = discord.ui.Select(
        custom_id="setup:lang",
        placeholder="🌍 Язык / Language / Sprache",
        options=[
            discord.SelectOption(label="Русский", emoji="🇷🇺", value="ru", default=(lang == "ru")),
            discord.SelectOption(label="English", emoji="🇬🇧", value="en", default=(lang == "en")),
            discord.SelectOption(label="Deutsch", emoji="🇩🇪", value="de", default=(lang == "de")),
        ],
    )

    async def _pick2(inter):
        await pick_lang_and_continue(inter)
    lang_sel.callback = _pick2
    lang_row.add_item(lang_sel)
    view.add_item(lang_row)

    for chunk in (MODULE_ORDER[:4], MODULE_ORDER[4:]):
        row = discord.ui.ActionRow()
        for key in chunk:
            on = states[key]
            b = discord.ui.Button(label=f"{T('m_' + key)} {'🟢' if on else '🔴'}",
                                  custom_id=f"setup:toggle:{key}", style=discord.ButtonStyle.secondary)

            async def _tg(inter, _k=key):
                await toggle_and_refresh(inter, _k)
            b.callback = _tg
            row.add_item(b)
        view.add_item(row)

    row = discord.ui.ActionRow()
    btn_all = discord.ui.Button(label=T("install_all"), emoji="🚀", custom_id="setup:all", style=discord.ButtonStyle.success)

    async def _all(inter):
        await install_all_and_refresh(inter)
    btn_all.callback = _all
    row.add_item(btn_all)
    btn_wipe = discord.ui.Button(label=T("wipe_all"), emoji="🧨", custom_id="setup:wipe", style=discord.ButtonStyle.danger)

    async def _wipe(inter):
        await wipe_all_and_refresh(inter)
    btn_wipe.callback = _wipe
    row.add_item(btn_wipe)
    view.add_item(row)

    for item in c.walk_children():
        if isinstance(item, discord.ui.Button) and item.custom_id:
            if item.custom_id.startswith("setup:install:"):
                key = item.custom_id.split(":")[-1]

                async def _in(inter, _k=key):
                    await install_one_and_refresh(inter, _k)
                item.callback = _in
            elif item.custom_id.startswith("setup:uninstall:"):
                key = item.custom_id.split(":")[-1]

                async def _un(inter, _k=key):
                    await uninstall_one_and_refresh(inter, _k)
                item.callback = _un
    return view


def build_lang_view() -> discord.ui.LayoutView:
    view = discord.ui.LayoutView(timeout=300)
    view.add_item(discord.ui.Container(
        discord.ui.TextDisplay("## 🛠️ Мастер-установщик WARDOGS TOOLS\n### Шаг 1 — язык / Step 1 — language / Schritt 1 — Sprache"),
        discord.ui.Separator(),
        accent_color=config.ACCENT_YELLOW,
    ))
    row = discord.ui.ActionRow()
    sel = discord.ui.Select(
        custom_id="setup:lang",
        placeholder="🌍 Язык / Language / Sprache",
        options=[
            discord.SelectOption(label="Русский", emoji="🇷🇺", value="ru"),
            discord.SelectOption(label="English", emoji="🇬🇧", value="en"),
            discord.SelectOption(label="Deutsch", emoji="🇩🇪", value="de"),
        ],
    )

    async def _pick(inter):
        await pick_lang_and_continue(inter)
    sel.callback = _pick
    row.add_item(sel)
    view.add_item(row)
    return view


async def pick_lang_and_continue(interaction: discord.Interaction):
    try:
        lang = interaction.data["values"][0]
        await db.set_guild(interaction.guild.id, language=lang)
        from utils.i18n import set_lang_cache
        set_lang_cache(interaction.guild.id, lang)
        await interaction.response.edit_message(view=await build_setup_view(interaction.guild))
    except (discord.errors.InteractionResponded, discord.errors.HTTPException, discord.errors.NotFound):
        pass


async def toggle_and_refresh(interaction: discord.Interaction, key: str):
    try:
        await db.toggle_module(interaction.guild.id, key)
        await interaction.response.edit_message(view=await build_setup_view(interaction.guild))
        from utils.alog import send_log
        g = await db.get_guild(interaction.guild.id)
        await send_log(interaction.guild, f"⚙️ {db.TOGGLE_LABELS.get(key, key)} → {'вкл' if g.get(db.TOGGLES[key]) else 'выкл'} ({interaction.user.mention})")
    except (discord.errors.InteractionResponded, discord.errors.HTTPException, discord.errors.NotFound):
        pass


async def _refresh_or_follow(interaction: discord.Interaction, text: str):
    try:
        await interaction.edit_original_response(view=await build_setup_view(interaction.guild))
    except Exception:
        pass
    try:
        await interaction.followup.send(text, ephemeral=True)
    except Exception:
        pass


async def install_one_and_refresh(interaction: discord.Interaction, key: str):
    if not await _cooldown_ok(interaction, f"install:{key}", CD_ONE):
        return
    try:
        await interaction.response.defer(ephemeral=True, thinking=True)
    except Exception:
        pass
    cog = interaction.client.get_cog("Setup")
    fn = {"tickets": cog.install_tickets, "search": cog.install_search, "clans": cog.install_clans,
          "voices": cog.install_voices, "logs": cog.install_logs,
          "moderation": cog.install_moderation, "welcome": cog.install_welcome}[key]
    try:
        await _refresh_or_follow(interaction, f"✅ {await fn(interaction.guild)}")
    except Exception as e:
        await _refresh_or_follow(interaction, f"❌ {e}")


async def uninstall_one_and_refresh(interaction: discord.Interaction, key: str):
    if not await _cooldown_ok(interaction, f"uninstall:{key}", CD_ONE):
        return
    try:
        await interaction.response.defer(ephemeral=True, thinking=True)
    except Exception:
        pass
    cog = interaction.client.get_cog("Setup")
    fn = {"tickets": cog.uninstall_tickets, "search": cog.uninstall_search, "clans": cog.uninstall_clans,
          "voices": cog.uninstall_voices, "logs": cog.uninstall_logs,
          "moderation": cog.uninstall_moderation, "welcome": cog.uninstall_welcome}[key]
    try:
        await _refresh_or_follow(interaction, f"🧨 {await fn(interaction.guild)}")
    except Exception as e:
        await _refresh_or_follow(interaction, f"❌ {e}")


async def install_all_and_refresh(interaction: discord.Interaction):
    if not await _cooldown_ok(interaction, "install:all", CD_ALL):
        return
    try:
        await interaction.response.defer(ephemeral=True, thinking=True)
    except Exception:
        pass
    cog = interaction.client.get_cog("Setup")
    out = []
    for fn in [cog.install_tickets, cog.install_search, cog.install_clans, cog.install_voices,
               cog.install_logs, cog.install_moderation, cog.install_welcome]:
        try:
            out.append(await fn(interaction.guild))
        except Exception as e:
            out.append(f"❌ {e}")
    await _refresh_or_follow(interaction, "✅ **Всё установлено:**\n• " + "\n• ".join(out))


async def wipe_all_and_refresh(interaction: discord.Interaction):
    if not await _cooldown_ok(interaction, "wipe:all", CD_ALL):
        return
    try:
        await interaction.response.defer(ephemeral=True, thinking=True)
    except Exception:
        pass
    cog = interaction.client.get_cog("Setup")
    try:
        out = await cog.uninstall_all(interaction.guild)
        ok = "🧨 **Всё удалено:**\n• " + "\n• ".join(out)
    except Exception as e:
        ok = f"❌ {e}"
    await _refresh_or_follow(interaction, ok)


class Setup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setupbot", description="Мастер-установщик / Setup wizard (только админ / admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setupbot(self, interaction: discord.Interaction):
        # Шаг 1 — язык, дальше панель сама перестроится на нём
        await interaction.response.send_message(view=build_lang_view(), ephemeral=True)

    @app_commands.command(name="wipebot", description="Удалить ВСЁ / Remove ALL (только админ / admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def wipebot(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        out = await self.uninstall_all(interaction.guild)
        await interaction.followup.send("🧨 **Всё удалено:**\n• " + "\n• ".join(out), ephemeral=True)

    # ---------- INSTALLERS ----------

    async def _rename(self, obj, name: str):
        """Переименовать под язык, тихо."""
        try:
            if obj and getattr(obj, "name", None) != name:
                await obj.edit(name=name)
        except Exception:
            pass

    async def install_tickets(self, guild: discord.Guild) -> str:
        from cogs.tickets import build_ticket_panel
        from utils.i18n import get_lang, t_sync
        g = await db.get_guild(guild.id)
        lang = await get_lang(guild.id)
        T = lambda k: t_sync(lang, k)
        cat = guild.get_channel(g.get("ticket_category") or 0)
        if not isinstance(cat, discord.CategoryChannel):
            cat = await guild.create_category(T("ch_ticket_cat"))
        else:
            await self._rename(cat, T("ch_ticket_cat"))
        arch = guild.get_channel(g.get("ticket_archive_category") or 0)
        if not isinstance(arch, discord.CategoryChannel):
            arch = await guild.create_category(T("ch_ticket_arch"))
        else:
            await self._rename(arch, T("ch_ticket_arch"))
        staff = discord.utils.get(guild.roles, name="Support")
        if not staff:
            staff = await guild.create_role(name="Support", reason="WARDOGS tickets")
        senior = discord.utils.get(guild.roles, name="Senior Support")
        if not senior:
            senior = await guild.create_role(name="Senior Support", reason="WARDOGS senior")
        panel_ch = guild.get_channel(g.get("ticket_panel_channel") or 0)
        if not isinstance(panel_ch, discord.TextChannel):
            panel_ch = await guild.create_text_channel(T("ch_ticket_panel"), category=cat)
        else:
            await self._rename(panel_ch, T("ch_ticket_panel"))

        await db.set_guild(guild.id, ticket_category=cat.id, ticket_archive_category=arch.id,
                           ticket_staff_role=staff.id, ticket_senior_role=senior.id,
                           ticket_panel_channel=panel_ch.id)
        await panel_ch.send(view=build_ticket_panel(lang, g.get("banner_url") or ""))
        return f"Тикеты → {panel_ch.mention} + Support/Senior"

    async def install_search(self, guild: discord.Guild) -> str:
        from cogs.search_party import ensure_lfg_example, LFG_GUIDE
        from utils.i18n import get_lang, t_sync
        g = await db.get_guild(guild.id)
        lang = await get_lang(guild.id)
        T = lambda k: t_sync(lang, k)
        ch = guild.get_channel(g.get("search_channel") or 0)
        # пересоздаём поиск как ФОРУМ (текстовый legacy удаляем)
        if isinstance(ch, discord.TextChannel):
            try:
                await ch.delete(reason="WARDOGS migrate search to forum")
            except Exception:
                pass
            ch = None
        if not isinstance(ch, discord.ForumChannel):
            cat = self._find_cat(guild, [T("ch_search_cat"), "🔍・ПОИСК", "🔍・SEARCH", "🔍・SUCHE"])
            if cat is None:
                cat = await guild.create_category(T("ch_search_cat"))
            tags = []
            try:
                tags = [
                    discord.ForumTag(name="PVP", emoji="⚔️"),
                    discord.ForumTag(name="PVE", emoji="🛡️"),
                    discord.ForumTag(name="MIC", emoji="🎙️"),
                    discord.ForumTag(name="18+", emoji="🔞"),
                ]
            except Exception:
                tags = []
            try:
                ch = await guild.create_forum(
                    T("ch_search"), category=cat,
                    topic=LFG_GUIDE,
                    default_reaction_emoji="⬆️",
                    default_sort_order=discord.ForumOrderType.latest_activity,
                    default_layout=discord.ForumLayoutType.gallery_view,
                    available_tags=tags or None,
                    reason="WARDOGS lfg forum",
                )
            except Exception:
                ch = await guild.create_text_channel(T("ch_search"), category=cat)
        else:
            try:
                await ch.edit(
                    name=T("ch_search"), topic=LFG_GUIDE,
                    default_sort_order=discord.ForumOrderType.latest_activity,
                    default_layout=discord.ForumLayoutType.gallery_view,
                    default_reaction_emoji="⬆️", reason="WARDOGS forum defaults")
            except Exception:
                pass
        await db.set_guild(guild.id, search_channel=ch.id)
        if isinstance(ch, discord.ForumChannel):
            await ensure_lfg_example(ch)
            try:
                for t in ch.threads:
                    if not t.name.startswith("📌"):
                        try:
                            await t.edit(locked=True, archived=False, reason="WARDOGS: только анкета + бамп")
                        except Exception:
                            pass
            except Exception:
                pass
            return f"Поиск отряда → форум {ch.mention} + шаблон + бамп ⬆️/3д"
        from cogs.search_party import build_search_panel
        from utils.sticky import restick
        await restick(ch, guild.id, "search_panel_id", build_search_panel)
        return f"Поиск отряда → {ch.mention} (панель липкая)"

    def _find_cat(self, guild: discord.Guild, names: list):
        for n in names:
            c = discord.utils.get(guild.categories, name=n)
            if c:
                return c
        return None

    async def install_clans(self, guild: discord.Guild) -> str:
        from cogs.clans import ensure_forum_example, FORUM_GUIDE
        from utils.i18n import get_lang, t_sync
        g = await db.get_guild(guild.id)
        lang = await get_lang(guild.id)
        T = lambda k: t_sync(lang, k)
        ch = guild.get_channel(g.get("clan_channel") or 0)
        # пересоздаём набор как ФОРУМ (текстовый legacy удаляем)
        if isinstance(ch, discord.TextChannel):
            try:
                await ch.delete(reason="WARDOGS migrate clans to forum")
            except Exception:
                pass
            ch = None
        if not isinstance(ch, discord.ForumChannel):
            cat = self._find_cat(guild, [T("ch_search_cat"), "🔍・ПОИСК", "🔍・SEARCH", "🔍・SUCHE"])
            if cat is None:
                cat = await guild.create_category(T("ch_search_cat"))
            tags = []
            try:
                tags = [
                    discord.ForumTag(name="LONESTAR", emoji="🔵"),
                    discord.ForumTag(name="VALKYRA", emoji="🔴"),
                    discord.ForumTag(name="MANTICORE", emoji="🟢"),
                    discord.ForumTag(name="Набор открыт", emoji="✅"),
                ]
            except Exception:
                tags = []
            try:
                ch = await guild.create_forum(
                    T("ch_clan_forum"), category=cat,
                    topic=FORUM_GUIDE,
                    default_reaction_emoji="⬆️",
                    default_sort_order=discord.ForumOrderType.latest_activity,
                    default_layout=discord.ForumLayoutType.gallery_view,
                    available_tags=tags or None,
                    reason="WARDOGS clans forum",
                )
            except Exception:
                ch = await guild.create_text_channel(T("ch_clan_text"), category=cat)
        else:
            # существующий форум — выставить галерею + сортировку + гайд + имя
            try:
                await ch.edit(
                    name=T("ch_clan_forum"),
                    topic=FORUM_GUIDE,
                    default_sort_order=discord.ForumOrderType.latest_activity,
                    default_layout=discord.ForumLayoutType.gallery_view,
                    default_reaction_emoji="⬆️",
                    reason="WARDOGS forum defaults",
                )
            except Exception:
                pass
        leader = discord.utils.get(guild.roles, name="Лидер клана") or discord.utils.get(guild.roles, name="Clan Leader") or discord.utils.get(guild.roles, name="Clan-Anführer")
        if not leader:
            leader = await guild.create_role(name=T("role_leader"), reason="WARDOGS clans")
        # роли фракций
        for fname in ["🔵 LONESTAR", "🔴 VALKYRA", "🟢 MANTICORE"]:
            if not discord.utils.get(guild.roles, name=fname):
                try:
                    await guild.create_role(name=fname, reason="WARDOGS factions")
                except Exception:
                    pass
        await db.set_guild(guild.id, clan_channel=ch.id, clan_leader_role=leader.id)
        if isinstance(ch, discord.ForumChannel):
            await ensure_forum_example(ch)
            # закрыть все старые посты: только анкета + бамп
            try:
                for t in ch.threads:
                    if not t.name.startswith("📌"):
                        try:
                            await t.edit(locked=True, archived=False, reason="WARDOGS: только анкета + бамп")
                        except Exception:
                            pass
            except Exception:
                pass
            return f"Клановые заявки → форум {ch.mention} + закрепа-пример + бамп ⬆️/3д"
        from cogs.clans import build_clan_panel
        from utils.sticky import restick
        await restick(ch, guild.id, "clan_panel_id", build_clan_panel)
        return f"Клановые заявки → {ch.mention} + фракции (панель липкая)"

    async def install_voices(self, guild: discord.Guild) -> str:
        from utils.i18n import get_lang, t_sync
        g = await db.get_guild(guild.id)
        lang = await get_lang(guild.id)
        T = lambda k: t_sync(lang, k)
        vcat = guild.get_channel(g.get("voice_category") or 0)
        if not isinstance(vcat, discord.CategoryChannel):
            vcat = await guild.create_category(T("ch_voice_cat"))
        else:
            await self._rename(vcat, T("ch_voice_cat"))
        # отдельных #комнат-текст больше не создаём — панель живёт в чате войса
        lobby = guild.get_channel(g.get("voice_lobby") or 0)
        if not isinstance(lobby, discord.VoiceChannel):
            lobby = await guild.create_voice_channel(T("ch_lobby"), category=vcat, user_limit=1)
        else:
            await self._rename(lobby, T("ch_lobby"))
        await db.set_guild(guild.id, voice_category=vcat.id, voice_text_category=0, voice_lobby=lobby.id)
        return f"Войсы → лобби {lobby.name} (панель в чате войса)"

    async def install_logs(self, guild: discord.Guild) -> str:
        from utils.i18n import get_lang, t_sync
        g = await db.get_guild(guild.id)
        lang = await get_lang(guild.id)
        T = lambda k: t_sync(lang, k)
        ch = guild.get_channel(g.get("admin_log_channel") or 0)
        if not isinstance(ch, discord.TextChannel):
            cat = guild.get_channel(g.get("ticket_category") or 0)
            ch = await guild.create_text_channel(T("ch_logs"), category=cat if isinstance(cat, discord.CategoryChannel) else None)
        else:
            await self._rename(ch, T("ch_logs"))
        await db.set_guild(guild.id, admin_log_channel=ch.id)
        return f"Логи → {ch.mention}"

    async def install_moderation(self, guild: discord.Guild) -> str:
        """Панель + мод-логи в ОДНОЙ категории."""
        from utils.i18n import get_lang, t_sync
        g = await db.get_guild(guild.id)
        lang = await get_lang(guild.id)
        T = lambda k: t_sync(lang, k)
        cat = guild.get_channel(g.get("mod_category") or 0)
        if not isinstance(cat, discord.CategoryChannel):
            cat = await guild.create_category(T("ch_mod_cat"))
        else:
            await self._rename(cat, T("ch_mod_cat"))
        panel = guild.get_channel(g.get("mod_panel_channel") or 0)
        if not isinstance(panel, discord.TextChannel):
            ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
            panel = await guild.create_text_channel(T("ch_mod_panel"), category=cat, overwrites=ow)
        else:
            await self._rename(panel, T("ch_mod_panel"))
        mlog = guild.get_channel(g.get("mod_log_channel") or 0)
        if not isinstance(mlog, discord.TextChannel):
            ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
            mlog = await guild.create_text_channel(T("ch_mod_log"), category=cat, overwrites=ow)
        else:
            await self._rename(mlog, T("ch_mod_log"))
        await db.set_guild(guild.id, mod_category=cat.id, mod_panel_channel=panel.id, mod_log_channel=mlog.id)
        from utils.i18n import t_sync
        v = discord.ui.LayoutView(timeout=None)
        v.add_item(discord.ui.Container(
            discord.ui.TextDisplay(t_sync(lang, "md_info")),
            accent_color=config.ACCENT_YELLOW,
        ))
        try:
            await panel.send(view=v)
        except Exception:
            pass
        return f"Модерация → {panel.mention} + {mlog.mention} (одна категория)"

    async def install_welcome(self, guild: discord.Guild) -> str:
        from utils.i18n import get_lang, t_sync
        from cogs.welcome import build_factions_panel
        g = await db.get_guild(guild.id)
        lang = await get_lang(guild.id)
        ch = guild.get_channel(g.get("welcome_channel") or 0)
        if not isinstance(ch, discord.TextChannel):
            ch = await guild.create_text_channel(t_sync(lang, "ch_welcome"))
        else:
            await self._rename(ch, t_sync(lang, "ch_welcome"))
        await db.set_guild(guild.id, welcome_channel=ch.id)
        try:
            await ch.send(view=build_factions_panel(lang))
        except Exception:
            pass
        return f"Велком → {ch.mention} + фракции"

    # ---------- UNINSTALL (по одному модулю) ----------

    async def _del_one(self, guild: discord.Guild, obj_id) -> str | None:
        if not obj_id:
            return None
        obj = guild.get_channel(obj_id) or guild.get_role(obj_id)
        if obj is None:
            return None
        name = getattr(obj, "name", str(obj_id))
        try:
            await obj.delete(reason="WARDOGS uninstall module")
            return name
        except Exception:
            return None

    async def uninstall_tickets(self, guild: discord.Guild) -> str:
        g = await db.get_guild(guild.id)
        n = 0
        for col in ("ticket_panel_channel", "ticket_category", "ticket_archive_category"):
            if await self._del_one(guild, g.get(col)):
                n += 1
        for rn in ("Support", "Senior Support"):
            r = discord.utils.get(guild.roles, name=rn)
            if r:
                try:
                    await r.delete(reason="WARDOGS uninstall")
                    n += 1
                except Exception:
                    pass
        await db.set_guild(guild.id, ticket_panel_channel=0, ticket_category=0, ticket_archive_category=0,
                           ticket_staff_role=0, ticket_senior_role=0)
        return f"Тикеты удалены ({n} объектов)"

    async def uninstall_search(self, guild: discord.Guild) -> str:
        import aiosqlite
        g = await db.get_guild(guild.id)
        name = await self._del_one(guild, g.get("search_channel"))
        await self._del_empty_cat(guild, "🔍・ПОИСК")
        async with db.conn() as dbc:
            try:
                await dbc.execute("DELETE FROM lfg_threads WHERE guild_id=?", (guild.id,))
                await dbc.execute("DELETE FROM parties WHERE guild_id=?", (guild.id,))
                await dbc.commit()
            except Exception:
                pass
        await db.set_guild(guild.id, search_channel=0, search_panel_id=0)
        return f"Поиск удалён ({name or 'канал уже нет'})"

    async def uninstall_clans(self, guild: discord.Guild) -> str:
        import aiosqlite
        g = await db.get_guild(guild.id)
        name = await self._del_one(guild, g.get("clan_channel"))
        await self._del_empty_cat(guild, "🔍・ПОИСК")
        async with db.conn() as dbc:
            await dbc.execute("DELETE FROM clan_threads WHERE guild_id=?", (guild.id,))
            await dbc.execute("DELETE FROM clan_apps WHERE guild_id=?", (guild.id,))
            await dbc.commit()
        await db.set_guild(guild.id, clan_channel=0, clan_panel_id=0)
        return f"Форум кланов удалён ({name or 'канал уже нет'})"

    async def uninstall_voices(self, guild: discord.Guild) -> str:
        import aiosqlite
        g = await db.get_guild(guild.id)
        n = 0
        async with db.conn() as dbc:
            dbc.row_factory = aiosqlite.Row
            async with dbc.execute("SELECT voice_id, text_id FROM temp_voices WHERE guild_id=?", (guild.id,)) as cur:
                rows = await cur.fetchall()
            for r in rows:
                for cid in (r["voice_id"], r["text_id"]):
                    if cid and await self._del_one(guild, cid):
                        n += 1
            await dbc.execute("DELETE FROM temp_voices WHERE guild_id=?", (guild.id,))
            await dbc.commit()
        if await self._del_one(guild, g.get("voice_lobby")):
            n += 1
        if await self._del_one(guild, g.get("voice_category")):
            n += 1
        await db.set_guild(guild.id, voice_lobby=0, voice_category=0, voice_text_category=0)
        return f"Войсы удалены ({n} каналов)"

    async def uninstall_logs(self, guild: discord.Guild) -> str:
        g = await db.get_guild(guild.id)
        name = await self._del_one(guild, g.get("admin_log_channel"))
        await db.set_guild(guild.id, admin_log_channel=0)
        return f"Логи удалены ({name or 'канал уже нет'})"

    async def uninstall_moderation(self, guild: discord.Guild) -> str:
        g = await db.get_guild(guild.id)
        n = 0
        for col in ("mod_panel_channel", "mod_log_channel", "mod_category"):
            if await self._del_one(guild, g.get(col)):
                n += 1
        await db.set_guild(guild.id, mod_panel_channel=0, mod_log_channel=0, mod_category=0)
        return f"Модерация удалена ({n} объектов)"

    async def uninstall_welcome(self, guild: discord.Guild) -> str:
        g = await db.get_guild(guild.id)
        name = await self._del_one(guild, g.get("welcome_channel"))
        await db.set_guild(guild.id, welcome_channel=0)
        return f"Велком удалён ({name or 'канал уже нет'})"

    async def _del_empty_cat(self, guild: discord.Guild, name: str):
        for n in [name, "🔍・ПОИСК", "🔍・SEARCH", "🔍・SUCHE"]:
            cat = discord.utils.get(guild.categories, name=n)
            if cat and len(cat.channels) == 0:
                try:
                    await cat.delete(reason="WARDOGS uninstall")
                except Exception:
                    pass

    # ---------- UNINSTALL ALL ----------

    async def _del(self, guild: discord.Guild, obj_id, label: str, out: list):
        if not obj_id:
            return
        obj = guild.get_channel(obj_id) or guild.get_role(obj_id)
        if obj is None:
            return
        try:
            await obj.delete(reason="WARDOGS wipe")
            out.append(f"{label}: удалён {getattr(obj, 'name', obj_id)}")
        except Exception as e:
            out.append(f"{label}: не смог ({e})")

    async def uninstall_all(self, guild: discord.Guild) -> list:
        import aiosqlite
        g = await db.get_guild(guild.id)
        out = []
        # 1) приватки + их остатки
        try:
            async with db.conn() as dbc:
                dbc.row_factory = aiosqlite.Row
                async with dbc.execute("SELECT voice_id, text_id FROM temp_voices WHERE guild_id=?", (guild.id,)) as cur:
                    rows = await cur.fetchall()
                for r in rows:
                    for cid in (r["voice_id"], r["text_id"]):
                        if cid:
                            ch = guild.get_channel(cid)
                            try:
                                if ch: await ch.delete(reason="WARDOGS wipe temp")
                            except Exception:
                                pass
                await dbc.execute("DELETE FROM temp_voices WHERE guild_id=?", (guild.id,))
                await dbc.execute("DELETE FROM tickets WHERE guild_id=?", (guild.id,))
                await dbc.execute("DELETE FROM parties WHERE guild_id=?", (guild.id,))
                await dbc.execute("DELETE FROM clan_apps WHERE guild_id=?", (guild.id,))
                await dbc.commit()
            out.append("Приватки и заявки в БД: очищены")
        except Exception as e:
            out.append(f"БД: {e}")
        # 2) каналы/категории
        for key, label in [
            ("ticket_panel_channel", "Панель тикетов"),
            ("ticket_category", "Категория тикетов"),
            ("ticket_archive_category", "Архив тикетов"),
            ("search_channel", "Поиск отряда"),
            ("clan_channel", "Набор в клан"),
            ("voice_lobby", "Войс-лобби"),
            ("voice_category", "Категория войсов"),
            ("voice_text_category", "Категория комнат-текст (legacy)"),
            ("admin_log_channel", "Админ-логи"),
            ("mod_panel_channel", "Мод-панель"),
            ("mod_log_channel", "Мод-логи"),
            ("mod_category", "Категория модерации"),
            ("welcome_channel", "Велком"),
        ]:
            await self._del(guild, g.get(key), label, out)
        # пустая категория ПОИСК если осталась
        leftover = discord.utils.get(guild.categories, name="🔍・ПОИСК")
        if leftover and len(leftover.channels) == 0:
            try:
                await leftover.delete(reason="WARDOGS wipe")
                out.append("Категория ПОИСК: удалена")
            except Exception:
                pass
        # 3) роли
        for rname in ["Support", "Senior Support", "Лидер клана", "🔵 LONESTAR", "🔴 VALKYRA", "🟢 MANTICORE"]:
            r = discord.utils.get(guild.roles, name=rname)
            if r:
                try:
                    await r.delete(reason="WARDOGS wipe")
                    out.append(f"Роль {rname}: удалена")
                except Exception as e:
                    out.append(f"Роль {rname}: {e}")
        # 4) сброс БД
        try:
            await db.set_guild(guild.id, ticket_panel_channel=0, ticket_category=0, ticket_archive_category=0,
                               ticket_staff_role=0, ticket_senior_role=0, ticket_counter=0, search_channel=0, clan_channel=0,
                               clan_leader_role=0, voice_lobby=0, voice_category=0, voice_text_category=0,
                               admin_log_channel=0, mod_panel_channel=0, mod_log_channel=0, mod_category=0,
                               welcome_channel=0, language="ru")
            out.append("Настройки сервера: сброшены")
        except Exception as e:
            out.append(f"Сброс: {e}")
        return out


async def setup(bot):
    await bot.add_cog(Setup(bot))
