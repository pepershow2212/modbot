"""Конфиг экосистемы WARDOGS (BULKHEAD/Team17, EA 10.09.2026). Жёлтый дизайн."""
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN", "")
TEST_GUILD_ID = os.getenv("GUILD_ID")  # опционально для быстрого синка

# WARDOGS yellow — фирменный жёлто-чёрный стиль
ACCENT_YELLOW = 0xFFC800
ACCENT_RED = ACCENT_YELLOW  # алиас чтобы не ломать старые импорты
ACCENT_DARK = 0x111111

# Лор WARDOGS для панелей
LORE = {
    "factions": {
        "lonestar": "🔵 LONESTAR — техасские хеви-хиттеры (Western paramilitary)",
        "valkyra": "🔴 VALKYRA — возврат величия Soviet People's Republic",
        "manticore": "🟢 MANTICORE — теневая армия Тегерана",
    },
    "zone": "Control Zone 2x2км • Hot Zone = x2 кэш • первый до 100 очков",
    "cash": "Старт $10.000 • кэш за ревайв, транспорт и удержание зоны • персистит между матчами",
    "setting": "Колхия (Kolchia) • борьба за PV-1 • 256км² • строй/разрушай • локальный войс",
}

# Типы тикетов — под WARDOGS (лидер клана и 18+ убраны, система не реализуется)
TICKET_TYPES = {
    "player_report": {"label": "Жалоба на игрока", "emoji": "👥", "category": "Жалобы"},
    "staff_report": {"label": "Жалоба на персонал", "emoji": "🛡️", "category": "Жалобы"},
    "appeal": {"label": "Подать апелляцию", "emoji": "🧾", "category": "Заявки"},
    "bug": {"label": "Сообщить о баге", "emoji": "🎯", "category": "Улучшения"},
    "suggest": {"label": "Предложить улучшение", "emoji": "🎯", "category": "Улучшения"},
}

FAQ_ITEMS = {
    "how_cash": {
        "label": "💰 Как работает кэш в WARDOGS?",
        "answer": "Старт $10.000. Кэш дают за ревайв, подвоз к зоне и удержание Control Zone (Hot Zone = x2). Кэш персистит между матчами — трать на лоадаут, технику и FOB."
    },
    "how_factions": {
        "label": "⚔️ Какие фракции и что выбрать?",
        "answer": "🔵 LONESTAR (Техас), 🔴 VALKYRA (Soviet PR), 🟢 MANTICORE (Тегеран). Скиллов у фракций нет — решает лоадаут и сквад. Держи точку до 100 очков."
    },
}
