import re
import json
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# ======================= Настройки =======================

TOKEN = os.environ.get("8519012454:AAG6xSS68Q81foxqfij24Fp1D7V52GyhtbsА")
SECOND_BOT_CHAT_ID = int(os.environ.get("123456789"))  # ID второго бота, которому отправляем прайс
ALLOWED_USER_ID = int(os.environ.get("866973179"))     # твой ID

# Словарь для хранения прайса в памяти
PRICES = {}

# ======================= Функции =======================

# Функция для добавления наценки
def add_margin(price: int) -> int:
    if price <= 60000:
        return price + 5000
    elif price <= 80000:
        return price + 6000
    else:
        return price + 7000

# Функция для парсинга текста поставщика
def parse_supplier_text(text: str) -> dict:
    """
    Преобразует сообщения от поставщика в словарь вида:
    {
        "iphone 16": "📱 iPhone 16\n128GB — 80 000₽\n256GB — 90 000₽",
        "iphone 16 pro": "📱 iPhone 16 Pro\n128GB — 105 000₽\n256GB — 115 000₽"
    }
    """
    result = {}
    current_model = None
    lines = text.split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Определяем новую модель
        if line.startswith("📱"):
            current_model = line.replace("📱", "").strip().lower()  # "iphone 16"
            result[current_model] = {}
            continue

        # Парсим строки с ценой
        match = re.search(r'(.+?)\s–\s([\d\.]+)₽', line)
        if match and current_model:
            spec = match.group(1).strip()  # "16e 128 Black ⚫"
            price = int(match.group(2).replace(".", ""))
            price = add_margin(price)

            # Извлекаем память устройства
            mem_match = re.search(r'(\d{3,4}GB|\d{2,3}|\d{1}TB)', spec)
            memory = mem_match.group(1) if mem_match else spec

            # Добавляем в словарь модели
            if memory not in result[current_model]:
                result[current_model][memory] = price
            else:
                # Если несколько цен на один memory, берём минимальную
                result[current_model][memory] = min(result[current_model][memory], price)

    # Формируем готовый текст для каждой модели
    formatted = {}
    for model, items in result.items():
        text = f"📱 {model.title()}\n"
        for mem, price in sorted(items.items()):
            text += f"{mem} — {price:,}₽\n"
        formatted[model] = text.strip()

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

# Обработка любого текстового сообщения от тебя
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    global PRICES
    text = update.message.text
    new_prices = parse_supplier_text(text)
    for model, text in new_prices.items():
        PRICES[model] = text
    await update.message.reply_text("Прайс обновлен.")

# /send — сохраняем JSON и отправляем второму боту
async def send_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    if not PRICES:
        await update.message.reply_text("Прайс пустой, нечего отправлять.")
        return
    with open("prices.json", "w", encoding="utf-8") as f:
        json.dump(PRICES, f, ensure_ascii=False, indent=2)
    # Отправляем файл второму боту
    await context.bot.send_document(chat_id=SECOND_BOT_CHAT_ID, document=open("prices.json", "rb"))
    await update.message.reply_text("Прайс отправлен второму боту.")

# ======================= Запуск бота =======================

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("new", new_prices))
app.add_handler(CommandHandler("send", send_prices))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

app.run_polling()