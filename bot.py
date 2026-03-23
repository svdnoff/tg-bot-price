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

# Словарь для хранения прайса в памяти
PRICES = {}
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
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))

    current_category = None
    current_model = None

    regions_pattern = "|".join(map(re.escape, SIM_MAP.keys()))

    # Приводим ключи категорий к нижнему регистру для сравнения
    lowercase_keys = [k.lower() for k in DEFAULT_KEYS]

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # ---------- КАТЕГОРИИ ----------
        # ищем строку, которая совпадает с ключом категории
        lower_line = line.lower()
        matched_key = None
        for key in lowercase_keys:
            if lower_line.startswith(key):
                matched_key = key
                break
        if matched_key:
            current_category = matched_key.title()  # Красиво с заглавной буквы
            current_model = None
            continue

        # ---------- МОДЕЛЬ ----------
        # новая модель считается любой строкой после категории, которая не содержит тире
        if current_category and "–" not in line:
            current_model = line
            continue

        if not current_model:
            continue  # пока нет модели — пропускаем строки

        # ---------- строки с ценами ----------
        match = re.search(
            rf'({regions_pattern})?\s*(.+?)\s[-–]\s?([\d\.]+)',
            line
        )
        if not match:
            continue

        region = match.group(1)
        spec = match.group(2)
        price = match.group(3)

        # SIM тип
        if region and region in SIM_MAP:
            sim_type = SIM_MAP[region]
        else:
            sim_type = "Обычная версия"

        # память (iPhone/Samsung)
        mem_match = re.search(r'(\d{3,4}GB|\dTB|\b\d{3}\b|\d/\d{3,4})', spec)
        if mem_match:
            memory = mem_match.group(1)
            color = spec.split(memory)[-1].strip()
        else:
            memory = "Стандарт"
            color = spec

        category = current_category or "Разное"
        model = current_model

        data[category][model][sim_type][memory].append(
            f"{color} – {price}₽"
        )

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
    PRICES = {}
    await update.message.reply_text(
        "Старый прайс очищен. Теперь отправляйте новые сообщения от поставщика."
    )

async def test_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    await update.message.reply_text(f"Текущий словарь PRICES:\n{PRICES}")

# Обработка любого текстового сообщения от тебя
async def go(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    global WRITE_MODE, RAW_TEXT, PRICES

    WRITE_MODE = True
    RAW_TEXT = ""
    PRICES = {}

    with open("prices.json", "w", encoding="utf-8") as f:
        json.dump({}, f)

    await update.message.reply_text(
        "Бот готов к записи.\nОтправляйте сообщения поставщика."
    )

# /send — сохраняем JSON и отправляем второму боту
async def send_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    global WRITE_MODE, RAW_TEXT, PRICES

    WRITE_MODE = False

    parsed = parse_supplier_text(RAW_TEXT)

    if not parsed:
        await update.message.reply_text("Прайс пустой")
        return

    PRICES.update(parsed)

    with open("prices.json", "w", encoding="utf-8") as f:
        json.dump(PRICES, f, ensure_ascii=False, indent=2)

    await context.bot.send_document(
        chat_id=SECOND_BOT_CHAT_ID,
        document=open("prices.json", "rb")
    )

    await update.message.reply_text("Прайс отправлен второму боту.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    global WRITE_MODE, RAW_TEXT

    if not WRITE_MODE:
        await update.message.reply_text("Сначала введите /go")
        return

    RAW_TEXT += "\n" + update.message.text
    await update.message.reply_text("Добавлено")

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