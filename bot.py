import re
import json
import os
from collections import defaultdict
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from collections import defaultdict
import copy

# ======================= Настройки =======================

TOKEN = os.environ.get("TOKEN")
SECOND_BOT_CHAT_ID = int(os.environ.get("SECOND_BOT_CHAT_ID"))  # ID второго бота, которому отправляем прайс
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID"))     # твой ID


SIM_MAP = {
    "🇪🇺": "1 SIM + eSIM",
    "🇯🇵": "Только eSIM, без физической!",
    "🇨🇳": "2 SIM (физические)",
}
DEFAULT_KEYS = [
    "iphone 16e", "iphone 16", "iphone 16 plus",
    "iphone 16 pro", "iphone 16 pro max",
    "iphone 17 pro", "iphone 17 pro max",
    "samsung s25", "samsung s25 ultra", "samsung s26 ultra",
    "ps5 slim", "ps5 pro", "gamepad ps5"
]

WRITE_MODE = False
RAW_TEXT = ""
PRICES_FILE = "prices.json"

# Словарь для хранения прайса в памяти
PRICES = {key: defaultdict(lambda: defaultdict(list)) for key in DEFAULT_KEYS}
# ======================= Функции =======================

# Функция для добавления наценки
def add_margin(price: int) -> int:
    return price + 5000

# функция для создания пустой структуры по ключу
def create_empty_model_structure():
    return defaultdict(lambda: defaultdict(list))  # sim_type -> memory -> список цветов

# создаём словарь с дефолтными ключами
PRICES = {key: create_empty_model_structure() for key in DEFAULT_KEYS}

# Функция для парсинга текста поставщика
        
def parse_supplier_text(text: str):
    from collections import defaultdict
    import re

    data = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))

    # Приводим ключи категорий к нижнему регистру для сравнения
    lowercase_keys = [k.lower() for k in DEFAULT_KEYS]

    current_category = None

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        lower_line = line.lower()

        # ---------- КАТЕГОРИИ ----------  
        for key in lowercase_keys:
            if lower_line.startswith(key):
                current_category = key  # ключ из DEFAULT_KEYS
                break

        # Если это строка с ценой
        price_match = re.search(r'(.+?)\s[-–]\s?([\d\.]+)', line)
        if price_match and current_category:

            spec = price_match.group(1).strip()
            price = price_match.group(2).strip()

            # определяем регион (если есть)
            region = None
            for reg_emoji in SIM_MAP.keys():
                if spec.startswith(reg_emoji):
                    region = reg_emoji
                    spec = spec.replace(reg_emoji, "").strip()
                    break

            sim_type = SIM_MAP.get(region, "Обычная версия")

            # память
            mem_match = re.search(r'(\d{3,4}GB|\dTB|\d/\d{3,4}|\b\d{3}\b)', spec)
            if mem_match:
                memory = mem_match.group(1)
                color = spec.replace(memory, "").strip()
            else:
                memory = "Стандарт"
                color = spec

            # модель = ключ категории
            model = current_category

            data[current_category][model][sim_type][memory].append(f"{color} – {price}₽")

    # ---------- сборка текста ----------
    formatted = {}
    for category in data:
        for model in data[category]:
            text_out = f"{model}:\n\n"
            for sim_type in data[category][model]:
                if sim_type != "Обычная версия":
                    text_out += f"{sim_type}:\n\n"
                for memory in data[category][model][sim_type]:
                    text_out += f"{memory}:\n"
                    for line in data[category][model][sim_type][memory]:
                        text_out += f"{line}\n"
                    text_out += "\n"
            formatted[f"{category.lower()} {model.lower()}"] = text_out.strip()

    return formatted

# ======================= Хендлеры =======================

# /new — очищаем словарь PRICES
async def new_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    global PRICES
    # создаём словарь с пустыми структурами для ключей
    PRICES = {key: create_empty_model_structure() for key in DEFAULT_KEYS}
    # очищаем RAW_TEXT
    global RAW_TEXT
    RAW_TEXT = ""
    # сохраняем пустой прайс в файл
    with open(PRICES_FILE, "w", encoding="utf-8") as f:
        json.dump(PRICES, f, ensure_ascii=False, indent=2)
    await update.message.reply_text(
        "Старый прайс очищен. Структура ключей сохранена. Теперь можно добавлять новые данные."
    )

async def test_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    await update.message.reply_text(f"Текущий словарь PRICES:\n{PRICES}")

# Обработка любого текстового сообщения от тебя
async def go(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    global WRITE_MODE, RAW_TEXT
    WRITE_MODE = True
    RAW_TEXT = ""
    await update.message.reply_text(
        "Бот готов к записи. Отправляйте сообщения поставщика, они сразу будут добавляться в прайс."
    )


# /send — сохраняем JSON и отправляем второму боту
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    global WRITE_MODE, RAW_TEXT, PRICES

    if not WRITE_MODE:
        await update.message.reply_text("Сначала введите /go")
        return

    # Добавляем текст к RAW_TEXT
    RAW_TEXT += "\n" + update.message.text

    # Парсим весь накопленный текст
    parsed = parse_supplier_text(RAW_TEXT)

    # Обновляем глобальный PRICES
    PRICES.update(parsed)

    # Сохраняем сразу в JSON
    with open(PRICES_FILE, "w", encoding="utf-8") as f:
        json.dump(PRICES, f, ensure_ascii=False, indent=2)

    await update.message.reply_text("Добавлено и сохранено в прайс.")

# /send — отправка JSON второму боту
async def send_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    global WRITE_MODE
    WRITE_MODE = False  # закрываем запись

    try:
        with open(PRICES_FILE, "rb") as f:
            await context.bot.send_document(
                chat_id=SECOND_BOT_CHAT_ID,
                document=f
            )
        await update.message.reply_text("Прайс отправлен второму боту.")
    except FileNotFoundError:
        await update.message.reply_text("Прайс пустой, нечего отправлять.")


async def send_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляем текущий прайс второму боту"""
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    global WRITE_MODE

    WRITE_MODE = False  # закрываем запись

    try:
        with open(PRICES_FILE, "rb") as f:
            await context.bot.send_document(
                chat_id=SECOND_BOT_CHAT_ID,
                document=f
            )
        await update.message.reply_text("Прайс отправлен второму боту.")
    except FileNotFoundError:
        await update.message.reply_text("Прайс пустой, нечего отправлять.")

# Команда для вывода ID чата, из которого пришло сообщение
async def get_id(update, context):
    if update.effective_user.id != ALLOWED_USER_ID:
        return  # Игнорируем всех кроме разрешенного пользователя
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"Chat ID этого чата: {chat_id}")

# ======================= Запуск бота =======================

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("new", new_prices))
app.add_handler(CommandHandler("send", send_prices))
app.add_handler(CommandHandler("test", test_prices))
app.add_handler(CommandHandler("id", get_id))
app.add_handler(CommandHandler("go", go))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

app.run_polling()