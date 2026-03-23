import os
import json
import re
from collections import defaultdict
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

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

WRITE_MODE = False
PRICES_FILE = "prices.json"

# Словарь для хранения прайса в памяти
PRICES = {key: defaultdict(lambda: defaultdict(list)) for key in DEFAULT_KEYS}

# ==================== Функции ====================

def add_margin(price: int) -> int:
    """Добавляет наценку 5000₽ к цене."""
    return price + 5000

def parse_supplier_text(text: str):
    """
    Парсит текст поставщика в формате твоего примера
    и возвращает словарь:
    PRICES[category][sim_type][memory] = [список цветов + цен]
    """
    from collections import defaultdict
    import re

    data = {key: defaultdict(lambda: defaultdict(list)) for key in DEFAULT_KEYS}

    # Для каждого ключа ищем все блоки в тексте
    for key in DEFAULT_KEYS:
        pattern = re.compile(rf'📱\s*({re.escape(key)})', re.IGNORECASE)
        matches = list(pattern.finditer(text))
        if not matches:
            continue

        # Если нашли категорию, берём текст после неё до следующей категории
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i+1].start() if i+1 < len(matches) else len(text)
            block = text[start:end]

            # Ищем все строки с ценами в этом блоке
            price_pattern = re.compile(
                r'([🇪🇺🇯🇵🇨🇳]+)\s+([\w\s+/]+)\s+(\d+(?:GB|TB))\s+([^\–]+?)\s*[-–]\s*([\d\.]+)'
            )
            for pm in price_pattern.finditer(block):
                region_flag = pm.group(1)
                model_name = pm.group(2).strip()
                memory = pm.group(3)
                color = pm.group(4).strip()
                price_str = pm.group(5)

                # конвертируем цену в int и добавляем наценку
                price_int = int(price_str.replace(".", ""))
                price_int = add_margin(price_int)

                sim_type = SIM_MAP.get(region_flag, "Обычная версия")

                data[key][sim_type][memory].append(f"{color} – {price_int}₽")

    return data

# ==================== Хендлеры ====================

async def new_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    global PRICES
    PRICES = {key: defaultdict(lambda: defaultdict(list)) for key in DEFAULT_KEYS}
    # Сохраняем пустой файл
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

    # Объединяем с текущим прайсом
    for key in parsed:
        for sim_type in parsed[key]:
            for memory in parsed[key][sim_type]:
                PRICES[key][sim_type][memory].extend(parsed[key][sim_type][memory])

    # Сохраняем в файл
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

# ==================== Запуск бота ====================

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("new", new_prices))
app.add_handler(CommandHandler("go", go))
app.add_handler(CommandHandler("send", send_prices))
app.add_handler(CommandHandler("test", test_prices))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

app.run_polling()