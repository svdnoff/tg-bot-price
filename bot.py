import re
import json
import os
from collections import defaultdict
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# ======================= Настройки =======================

TOKEN = os.environ.get("TOKEN")
SECOND_BOT_CHAT_ID = int(os.environ.get("SECOND_BOT_CHAT_ID"))  # ID второго бота, которому отправляем прайс
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID"))     # твой ID

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
def parse_supplier_text(text: str):
    result = {}
    current_model = None

    # структура:
    # model -> sim_type -> memory -> [строки]
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # новая модель
        if line.startswith("📱"):
            current_model = line.replace("📱", "").strip()
            continue

        if not current_model:
            continue

        match = re.search(r'(🇪🇺|🇯🇵)\s(.+?)\s–\s([\d\.]+)₽', line)
        if not match:
            continue

        region = match.group(1)
        spec = match.group(2)
        price = match.group(3)

        # определяем тип сим
        if region == "🇪🇺":
            sim_type = "1 SIM + eSIM"
        else:
            sim_type = "Только eSIM, без физической!"

        # память
        mem_match = re.search(r'(\d{3,4}GB|\dTB)', spec)
        if not mem_match:
            continue

        memory = mem_match.group(1)

        # цвет (всё после памяти)
        color = spec.split(memory)[-1].strip()

        data[current_model][sim_type][memory].append(
            f"{color} – {price}₽"
        )

    # собираем текст
    formatted = {}

    for model in data:
        text_out = f"📱 {model}:\n\n"

        for sim_type in data[model]:
            text_out += f"{sim_type}:\n\n"

            for memory in data[model][sim_type]:
                text_out += f"{memory}:\n"

                for line in data[model][sim_type][memory]:
                    text_out += f"{line}\n"

                text_out += "\n"

        formatted[model.lower()] = text_out.strip()

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
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

app.run_polling()