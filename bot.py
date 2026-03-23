import os
import json
import re
from collections import defaultdict
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# -------------------- Настройки --------------------
TOKEN = os.environ.get("TOKEN")
SECOND_BOT_CHAT_ID = int(os.environ.get("SECOND_BOT_CHAT_ID"))
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID"))

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

PRICES_FILE = "prices.json"
PRICE_INCREASE = 5000
WRITE_MODE = False

PRICES = {key: defaultdict(lambda: defaultdict(lambda: defaultdict(list))) for key in DEFAULT_KEYS}

# -------------------- Функции --------------------
def add_margin(price: int) -> int:
    return price + PRICE_INCREASE

def parse_supplier_text(text: str):
    """
    Построчный универсальный парсер.
    data[category][model][sim_type][memory] = [цвет – цена]
    """
    data = {key: defaultdict(lambda: defaultdict(lambda: defaultdict(list))) for key in DEFAULT_KEYS}

    lines = text.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("📱") or line.startswith("🎮") or "Заказать" in line:
            continue

        # паттерн: флаг (опционально), модель (iPhone/Samsung/PS5), память (опционально), цвет, цена
        m = re.match(
            r"([🇪🇺🇯🇵🇨🇳]?)\s*"        # флаг
            r"([\w\s\d+]+?)\s*"          # модель / подмодель
            r"(\d+(?:GB|TB)?)?\s*"       # память (опционально)
            r"([^\-–]+?)\s*[-–]\s*"      # цвет / вариант
            r"([\d\.,]+)",               # цена
            line
        )
        if not m:
            continue

        flag, model_name, memory, variant, price_str = m.groups()
        model_name = model_name.strip().lower()
        memory = memory if memory else "Стандарт"
        price_int = add_margin(int(price_str.replace(".", "").replace(",", "")))
        sim_type = SIM_MAP.get(flag, "Обычная версия")

        # Категорию ищем через вхождение модели в DEFAULT_KEYS
        category = None
        for key in DEFAULT_KEYS:
            if key in model_name:
                category = key
                break
        # если не нашли через вхождение, пробуем искать по первой цифре (iPhone 16/17, Samsung 25/26)
        if not category:
            for key in DEFAULT_KEYS:
                if key.split()[0] in model_name:
                    category = key
                    break
        if not category:
            continue  # не нашли категорию — пропускаем

        data[category][model_name][sim_type][memory].append(f"{variant.strip()} – {price_int}₽")

    return data

# -------------------- Хендлеры --------------------
async def new_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    global PRICES
    PRICES = {key: defaultdict(lambda: defaultdict(lambda: defaultdict(list))) for key in DEFAULT_KEYS}
    with open(PRICES_FILE, "w", encoding="utf-8") as f:
        json.dump(PRICES, f, ensure_ascii=False, indent=2)
    await update.message.reply_text("Старый прайс очищен. Готов к новым данным.")

async def go(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    global WRITE_MODE
    WRITE_MODE = True
    await update.message.reply_text("Режим записи включен. Отправляйте сообщение с прайсом.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    global WRITE_MODE, PRICES
    if not WRITE_MODE:
        await update.message.reply_text("Сначала введите /go")
        return

    text = update.message.text
    parsed = parse_supplier_text(text)

    # объединяем с текущим прайсом
    for key in parsed:
        for model_name in parsed[key]:
            for sim_type in parsed[key][model_name]:
                for memory in parsed[key][model_name][sim_type]:
                    PRICES[key][model_name][sim_type][memory].extend(
                        parsed[key][model_name][sim_type][memory]
                    )

    # сохраняем в файл
    with open(PRICES_FILE, "w", encoding="utf-8") as f:
        json.dump(PRICES, f, ensure_ascii=False, indent=2)

    await update.message.reply_text("Прайс добавлен и сохранён.")

async def send_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    global WRITE_MODE
    WRITE_MODE = False
    try:
        with open(PRICES_FILE, "rb") as f:
            await context.bot.send_document(chat_id=SECOND_BOT_CHAT_ID, document=f)
        await update.message.reply_text("Прайс отправлен второму боту.")
    except FileNotFoundError:
        await update.message.reply_text("Прайс пустой, нечего отправлять.")

async def test_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    await update.message.reply_text(f"Текущий словарь PRICES:\n{json.dumps(PRICES, ensure_ascii=False, indent=2)}")

# -------------------- Запуск бота --------------------
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("new", new_prices))
app.add_handler(CommandHandler("go", go))
app.add_handler(CommandHandler("send", send_prices))
app.add_handler(CommandHandler("test", test_prices))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

app.run_polling()
