""" /language — смена языка сервера. Заготовка под все языки Discord."""
import discord
from discord import app_commands
from discord.ext import commands
from database import db
from utils.i18n import STRINGS, set_lang_cache

LANGS = [
    ("Русский", "ru", "🇷🇺"),
    ("English", "en", "🇬🇧"),
    ("Deutsch", "de", "🇩🇪"),
]

class Language(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="language", description="Язык бота / Bot language")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(lang="Язык / Language")
    @app_commands.choices(lang=[app_commands.Choice(name=f"{e} {n}", value=v) for n, v, e in LANGS])
    async def language(self, interaction: discord.Interaction, lang: str):
        await db.set_guild(interaction.guild.id, language=lang)
        set_lang_cache(interaction.guild.id, lang)
        msg = {"ru": "✅ Язык: Русский", "en": "✅ Language: English", "de": "✅ Sprache: Deutsch"}.get(lang, "✅ OK")
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Language(bot))
