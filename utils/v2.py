"""Хелперы для Components V2 (discord.py 2.6+: LayoutView)."""
import discord


def section_row(text: str, button_label: str = "", button_emoji: str = "", custom_id: str = "", style=discord.ButtonStyle.secondary, url: str = None):
    """Section = TextDisplay + accessory-кнопка справа (как на скринах)."""
    if url:
        btn = discord.ui.Button(label=button_label, emoji=button_emoji, url=url, style=discord.ButtonStyle.link)
    elif custom_id:
        btn = discord.ui.Button(label=button_label or " ", emoji=button_emoji, custom_id=custom_id, style=style)
    else:
        btn = discord.ui.Button(label=button_label or " ", emoji=button_emoji, style=style)
    return discord.ui.Section(discord.ui.TextDisplay(text), accessory=btn)


def text_container(*blocks: str, accent: int | None = None, spoiler: bool = False):
    """Быстрый Container из текстовых блоков. Разделители добавляются вручную через Separator."""
    items = [discord.ui.TextDisplay(b) for b in blocks]
    return discord.ui.Container(*items, accent_color=accent, spoiler=spoiler)
