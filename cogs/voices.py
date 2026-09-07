"""Приватные голосовые: лобби ➕ → автовойс + текстовый чат с панелью управления (V2)."""
import discord
from discord.ext import commands
import config
from database import db
import aiosqlite


GAMEMODES = ["Штурм", "Стройка", "Логистика", "Пилот", "Медик"]  # fallback RU

def gamemodes(lang: str) -> list:
    from utils.i18n import t_sync
    return [t_sync(lang, f"gm{i}") for i in range(1, 6)]

def build_voice_panel(owner: discord.Member, voice: discord.VoiceChannel, filt_game="—", filt_18="—", filt_hours="—", server_id="—", faction="—", lang: str = "ru") -> discord.ui.LayoutView:
    from utils.i18n import t_sync
    v = discord.ui.LayoutView(timeout=None)
    c = discord.ui.Container(
        discord.ui.TextDisplay(f"## {t_sync(lang, 'v_title')}\n**{t_sync(lang, 'v_owner')}:** {owner.mention}\n**{t_sync(lang, 'v_room')}:** 🔊 {voice.name}\n**{t_sync(lang, 'v_server')}:** `{server_id}` • **{t_sync(lang, 'v_faction')}:** {faction}"),
        discord.ui.Separator(),
        discord.ui.Section(discord.ui.TextDisplay(f"**{t_sync(lang, 'v_limit')}**"), accessory=discord.ui.Button(emoji="♾️", custom_id=f"voice:limit:{voice.id}", style=discord.ButtonStyle.secondary)),
        discord.ui.Section(discord.ui.TextDisplay(f"**{t_sync(lang, 'v_bump')}**"), accessory=discord.ui.Button(emoji="⬆️", custom_id=f"voice:bump:{voice.id}", style=discord.ButtonStyle.secondary)),
        discord.ui.Section(discord.ui.TextDisplay(f"**{t_sync(lang, 'v_invite')}**"), accessory=discord.ui.Button(emoji="➕", custom_id=f"voice:invite:{voice.id}", style=discord.ButtonStyle.secondary)),
        discord.ui.Section(discord.ui.TextDisplay(f"**{t_sync(lang, 'v_transfer')}**"), accessory=discord.ui.Button(emoji="⏩", custom_id=f"voice:transfer:{voice.id}", style=discord.ButtonStyle.secondary)),
        discord.ui.Section(discord.ui.TextDisplay(f"**{t_sync(lang, 'v_kick')}**"), accessory=discord.ui.Button(emoji="❌", custom_id=f"voice:kick:{voice.id}", style=discord.ButtonStyle.secondary)),
        discord.ui.Section(discord.ui.TextDisplay(f"**{t_sync(lang, 'v_block')}**"), accessory=discord.ui.Button(emoji="🚫", custom_id=f"voice:block:{voice.id}", style=discord.ButtonStyle.secondary)),
        discord.ui.Section(discord.ui.TextDisplay(f"**{t_sync(lang, 'v_serverid')}**\n`{server_id}` • {faction}"), accessory=discord.ui.Button(emoji="🖥️", custom_id=f"voice:serverid:{voice.id}", style=discord.ButtonStyle.secondary)),
        discord.ui.Separator(),
        discord.ui.TextDisplay(f"**{t_sync(lang, 'v_filters')}**"),
        accent_color=config.ACCENT_RED,
    )
    v.add_item(c)

    # селекты фильтров (без колбэков — единый on_interaction)
    for ph, cid, opts in [
        (t_sync(lang, "v_ph_game"), f"voice:fgame:{voice.id}", gamemodes(lang)),
        (t_sync(lang, "v_ph_18"), f"voice:f18:{voice.id}", ["18+", t_sync(lang, "v_no_limit")]),
        (t_sync(lang, "v_ph_hours"), f"voice:fhours:{voice.id}", ["0+", "1k+", "3k+", "5k+"]),
    ]:
        row = discord.ui.ActionRow()
        sel = discord.ui.Select(custom_id=cid, placeholder=ph,
                                options=[discord.SelectOption(label=o, value=o) for o in opts])
        row.add_item(sel)
        v.add_item(row)

    return v


class VoiceModal(discord.ui.Modal):
    def __init__(self, action: str, voice_id: int, lang: str = "ru"):
        from utils.i18n import t_sync
        titles = {"rename": t_sync(lang, "vm_rename_t"), "limit": t_sync(lang, "vm_limit_t"),
                  "invite": t_sync(lang, "vm_invite_t"), "transfer": t_sync(lang, "vm_transfer_t"),
                  "kick": t_sync(lang, "vm_kick_t"), "block": t_sync(lang, "vm_block_t"),
                  "serverid": t_sync(lang, "vm_server_t")}
        super().__init__(title=titles.get(action, "..."))
        self.action = action
        self.voice_id = voice_id
        self.lang = lang
        self.target = discord.ui.TextInput(label=t_sync(lang, "vm_val_l"), max_length=100, placeholder=t_sync(lang, "vm_val_ph"))
        self.add_item(self.target)
        if action == "serverid":
            self.target.label = t_sync(lang, "vm_sid_l")
            self.target.placeholder = t_sync(lang, "vm_sid_ph")
            self.target.max_length = 30
            self.faction = discord.ui.TextInput(label=t_sync(lang, "vm_fac_l"), max_length=30, placeholder=t_sync(lang, "vm_fac_ph"))
            self.add_item(self.faction)

    async def on_submit(self, interaction: discord.Interaction):
        from utils.i18n import t_sync
        lang = getattr(self, "lang", "ru")
        guild = interaction.guild
        voice = guild.get_channel(self.voice_id)
        if not isinstance(voice, discord.VoiceChannel):
            await interaction.response.send_message(t_sync(lang, "vr_noroom"), ephemeral=True)
            return
        # проверка владельца
        async with db.conn() as dbc:
            dbc.row_factory = aiosqlite.Row
            async with dbc.execute("SELECT * FROM temp_voices WHERE guild_id=? AND voice_id=?", (guild.id, voice.id)) as cur:
                row = await cur.fetchone()
        if not row or row["owner_id"] != interaction.user.id:
            # админам можно
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message(t_sync(lang, "vr_owner_only"), ephemeral=True)
                return
        val = self.target.value.strip()
        try:
            if self.action == "rename":
                await voice.edit(name=val[:100])
                # обновить панель
                await refresh_panel(interaction, voice)
                await interaction.response.send_message(t_sync(lang, "vr_renamed").format(v=val), ephemeral=True)
            elif self.action == "limit":
                await voice.edit(user_limit=int(val) if val.isdigit() else 0)
                await interaction.response.send_message(t_sync(lang, "vr_limit").format(v=val), ephemeral=True)
            elif self.action == "invite":
                m = await resolve_member(guild, val)
                if m:
                    await voice.set_permissions(m, connect=True, view_channel=True)
                    if m.voice and m.voice.channel != voice:
                        try: await m.move_to(voice)
                        except Exception: pass
                    await interaction.response.send_message(t_sync(lang, "vr_invited").format(user=m.mention), ephemeral=True)
                else: await interaction.response.send_message(t_sync(lang, "vr_nouser"), ephemeral=True)
            elif self.action == "transfer":
                m = await resolve_member(guild, val)
                if m:
                    async with db.conn() as dbc:
                        await dbc.execute("UPDATE temp_voices SET owner_id=? WHERE guild_id=? AND voice_id=?", (m.id, guild.id, voice.id))
                        await dbc.commit()
                    try:
                        await voice.edit(name=f"🔊 {m.display_name}"[:100])
                    except Exception:
                        pass
                    await refresh_panel(interaction, voice, new_owner=m)
                    await interaction.response.send_message(t_sync(lang, "vr_newowner").format(user=m.mention), ephemeral=True)
                else: await interaction.response.send_message(t_sync(lang, "vr_nouser"), ephemeral=True)
            elif self.action == "kick":
                m = await resolve_member(guild, val)
                if m and m.voice and m.voice.channel == voice:
                    await m.move_to(None)
                    await interaction.response.send_message(t_sync(lang, "vr_kicked").format(user=m), ephemeral=True)
                else: await interaction.response.send_message(t_sync(lang, "vr_notin"), ephemeral=True)
            elif self.action == "block":
                m = await resolve_member(guild, val)
                if m:
                    ow = voice.overwrites_for(m)
                    # toggle: если уже запрещён — разрешить
                    if ow.connect is False:
                        await voice.set_permissions(m, connect=True)
                        await interaction.response.send_message(t_sync(lang, "vr_unblocked").format(user=m.mention), ephemeral=True)
                    else:
                        await voice.set_permissions(m, connect=False)
                        if m.voice and m.voice.channel == voice:
                            try: await m.move_to(None)
                            except Exception: pass
                        await interaction.response.send_message(t_sync(lang, "vr_blocked").format(user=m.mention), ephemeral=True)
                else: await interaction.response.send_message(t_sync(lang, "vr_nouser"), ephemeral=True)
            elif self.action == "serverid":
                sid = val[:30]
                fac = getattr(self, "faction", None)
                fac_val = (fac.value.strip().upper() if fac else "") or "—"
                async with db.conn() as dbc:
                    await dbc.execute("UPDATE temp_voices SET server_id=?, faction=? WHERE guild_id=? AND voice_id=?", (sid, fac_val, guild.id, voice.id))
                    await dbc.commit()
                # статус войса как на скрине мониторинга: 🖥️ Server id: 916153 VALKYRA
                try:
                    status = f"🖥️ Server id: {sid} {fac_val}"[:500] if fac_val != "—" else f"🖥️ Server id: {sid}"[:500]
                    await voice.edit(status=status)
                except Exception:
                    pass
                await refresh_panel(interaction, voice)
                from utils.alog import send_log
                await send_log(guild, f"🖥️ Войс `{voice.name}`: статус `{status}` поставил {interaction.user.mention}")
                await interaction.response.send_message(t_sync(lang, "vr_status").format(v=status), ephemeral=True)
        except Exception as e:
            try:
                await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            except Exception:
                pass


async def resolve_member(guild: discord.Guild, text: str):
    text = text.strip().strip("@<>! ")
    if text.isdigit():
        return guild.get_member(int(text))
    # по нику
    text_low = text.lower()
    for m in guild.members:
        if m.name.lower() == text_low or m.display_name.lower() == text_low:
            return m
    # по упоминанию
    import re
    mm = re.search(r"\d{15,}", text)
    if mm:
        return guild.get_member(int(mm.group(0)))
    return None


async def refresh_panel(interaction: discord.Interaction, voice: discord.VoiceChannel, new_owner=None):
    async with db.conn() as dbc:
        dbc.row_factory = aiosqlite.Row
        async with dbc.execute("SELECT * FROM temp_voices WHERE guild_id=? AND voice_id=?", (voice.guild.id, voice.id)) as cur:
            row = await cur.fetchone()
    if not row:
        return
    owner = new_owner or voice.guild.get_member(row["owner_id"])
    if not owner:
        return
    try:
        server_id = row["server_id"] or "—"
    except Exception:
        server_id = "—"
    try:
        faction = row["faction"] or "—"
    except Exception:
        faction = "—"
    from utils.i18n import get_lang
    lang = await get_lang(voice.guild.id)
    # отдельный #комнаты-текст больше не создаём — только встроенный чат войса.
    # старый text_id чистим тихо, если остался.
    text_ch = voice.guild.get_channel(row["text_id"]) if row["text_id"] else None
    if isinstance(text_ch, discord.TextChannel):
        try:
            async for msg in text_ch.history(limit=5):
                if msg.author == voice.guild.me:
                    try:
                        await msg.edit(view=build_voice_panel(owner, voice, server_id=server_id, faction=faction, lang=lang))
                        break
                    except Exception:
                        continue
        except Exception:
            pass
    # встроенный чат войса — основное место панели
    try:
        async for msg in voice.history(limit=10):
            if msg.author == voice.guild.me:
                try:
                    await msg.edit(view=build_voice_panel(owner, voice, server_id=server_id, faction=faction, lang=lang))
                    break
                except Exception:
                    continue
    except Exception:
        pass


async def handle_voice_button(interaction: discord.Interaction, cid: str):
    try:
        from utils.i18n import get_lang as _tgl, t_sync
        lang = await _tgl(interaction.guild.id)
        _, action, vid = cid.split(":")
        vid = int(vid)
        if action == "bump":
            voice = interaction.guild.get_channel(vid)
            if isinstance(voice, discord.VoiceChannel):
                await voice.edit(position=0)
                await interaction.response.send_message(t_sync(lang, "vr_bumped"), ephemeral=True)
            else:
                await interaction.response.send_message(t_sync(lang, "vr_noroom"), ephemeral=True)
        else:
            await interaction.response.send_modal(VoiceModal(action, vid, lang))
    except (discord.errors.InteractionResponded, discord.errors.HTTPException, discord.errors.NotFound):
        pass


async def handle_voice_select(interaction: discord.Interaction, cid: str):
    try:
        from utils.i18n import t_sync, get_lang as _tgl
        lang = await _tgl(interaction.guild.id)
        val = interaction.data["values"][0]
        # сохранить режим игры
        if cid.startswith("voice:fgame:"):
            try:
                vid = int(cid.split(":")[-1])
                async with db.conn() as dbc:
                    await dbc.execute("UPDATE temp_voices SET gamemode=? WHERE guild_id=? AND voice_id=?", (val, interaction.guild.id, vid))
                    await dbc.commit()
            except Exception:
                pass
        await interaction.response.send_message(t_sync(lang, "vr_filter").format(v=val), ephemeral=True)
    except (discord.errors.InteractionResponded, discord.errors.HTTPException, discord.errors.NotFound):
        pass


class Voices(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        import logging
        vlog = logging.getLogger("wardogs.voice")
        guild = member.guild
        g = await db.get_guild(guild.id)
        lobby_id = g.get("voice_lobby")
        vlog.info(f"voice_update {member} before={before.channel.id if before.channel else None} after={after.channel.id if after.channel else None} lobby={lobby_id}")
        # зашёл в лобби → создать приват (панель ТОЛЬКО во встроенный чат войса)
        if after.channel and lobby_id and after.channel.id == lobby_id and await db.is_on(guild.id, "voices"):
            vcat = guild.get_channel(g.get("voice_category") or 0)
            try:
                vc = await guild.create_voice_channel(f"🔊 {member.display_name}", category=vcat if isinstance(vcat, discord.CategoryChannel) else None, reason="temp voice")
                await member.move_to(vc)
                async with db.conn() as dbc:
                    await dbc.execute("INSERT OR REPLACE INTO temp_voices(guild_id, voice_id, text_id, owner_id) VALUES(?,?,?,?)", (guild.id, vc.id, 0, member.id))
                    await dbc.commit()
                try:
                    from utils.i18n import get_lang as _gl
                    _lang = await _gl(guild.id)
                    await vc.send(view=build_voice_panel(member, vc, lang=_lang))
                    vlog.info(f"panel posted into voice chat {vc.id} for {member}")
                except Exception as e:
                    vlog.warning(f"voice-chat send failed {vc.id}: {e}")
                    # фолбэк: если войс-чат недоступен — кинуть панель в лички владельцу
                    try:
                        from utils.i18n import t_sync as _tt
                        await member.send(_tt(_lang, "vr_dm_fallback"), view=build_voice_panel(member, vc, lang=_lang))
                    except Exception:
                        pass
                vlog.info(f"created temp voice {vc.id} for {member}")
                from utils.alog import send_log
                await send_log(guild, f"🔊 Войс `{vc.name}` создал {member.mention}")
            except Exception as e:
                vlog.exception(f"voice create error for {member}: {e}")
        # чистка пустых приваток (отдельных #комнат больше нет — удаляем только войс + старый текст если остался)
        # + автопередача: вышел владелец, а люди остались → владелец = первый оставшийся
        if before.channel and before.channel.id != lobby_id:
            async with db.conn() as dbc:
                dbc.row_factory = aiosqlite.Row
                async with dbc.execute("SELECT * FROM temp_voices WHERE guild_id=? AND voice_id=?", (guild.id, before.channel.id)) as cur:
                    row = await cur.fetchone()
                if row:
                    members = list(before.channel.members)
                    if len(members) == 0:
                        try:
                            await before.channel.delete(reason="empty temp voice")
                            if row["text_id"]:
                                tc = guild.get_channel(row["text_id"])
                                if isinstance(tc, discord.TextChannel):
                                    await tc.delete(reason="empty temp voice (legacy)")
                        except Exception:
                            pass
                        await dbc.execute("DELETE FROM temp_voices WHERE guild_id=? AND voice_id=?", (guild.id, before.channel.id))
                        await dbc.commit()
                        from utils.alog import send_log as _slog
                        await _slog(guild, f"🧹 Войс `{before.channel.name}` удалён (пустой)")
                    elif member.id == row["owner_id"]:
                        new_owner = next((m for m in members if not m.bot), members[0])
                        await dbc.execute("UPDATE temp_voices SET owner_id=? WHERE guild_id=? AND voice_id=?",
                                          (new_owner.id, guild.id, before.channel.id))
                        await dbc.commit()
                        try:
                            await before.channel.edit(name=f"🔊 {new_owner.display_name}"[:100])
                        except Exception:
                            pass
                        try:
                            await refresh_panel(None, before.channel, new_owner=new_owner)
                        except Exception:
                            pass
                        vlog.info(f"voice {before.channel.id} owner {member} -> {new_owner}")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        if interaction.response.is_done():
            return
        cid = (interaction.data or {}).get("custom_id", "")
        if not cid.startswith("voice:"):
            return
        if not await db.is_on(interaction.guild.id, "voices"):
            return
        if ":f" in cid or cid.startswith("voice:fgame") or cid.startswith("voice:f18") or cid.startswith("voice:fhours"):
            await handle_voice_select(interaction, cid)
        else:
            await handle_voice_button(interaction, cid)


async def setup(bot):
    await bot.add_cog(Voices(bot))
