import os
import json
import re
import string
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from rapidfuzz import fuzz
 
# -------------------- Настройки --------------------
TOKEN = os.environ.get("TOKEN")
SECOND_BOT_CHAT_ID = int(os.environ.get("SECOND_BOT_CHAT_ID"))
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID"))
 
SIM_MAP = {
    "🇨🇳": "2 SIM (физические)",
    "🇭🇰": "2 SIM (физические)",

    "🇮🇳": "1 SIM + eSIM",
    "🇯🇵": "1 SIM + eSIM",
    "🇦🇪": "1 SIM + eSIM",

    "🇺🇸": "Только eSIM (без физической SIM)",
}
 
PRICES_FILE = "prices.json"
PRICE_INCREASE = 5000
WRITE_MODE = False
THRESHOLD = 85
 
BRANDS = {
    "iphone": ["iphone", "айфон", "эпл", "apple"],
    "samsung": ["samsung", "самсунг", "самс"],
    "ps5": ["ps5", "пс5", "плойка", "playstation"],
    "gamepad": ["gamepad", "геймпад", "джойстик"],
}
 
CATEGORY_MAP = {
    "iphone 16e":        ("iphone", "16e"),
    "iphone 16":         ("iphone", "16"),
    "iphone 16 plus":    ("iphone", "16 plus"),
    "iphone 16 pro":     ("iphone", "16 pro"),
    "iphone 16 pro max": ("iphone", "16 pro max"),
    "iphone 17 pro":     ("iphone", "17 pro"),
    "iphone 17 pro max": ("iphone", "17 pro max"),
    "samsung s25":       ("samsung", "s25"),
    "samsung s25 ultra": ("samsung", "s25 ultra"),
    "samsung s26 ultra": ("samsung", "s26 ultra"),
    "ps5 slim":          ("ps5", "slim"),
    "ps5 pro":           ("ps5", "pro"),
    "gamepad ps5":       ("gamepad", "ps5"),
}
 
# Порядок вывода SIM-типов
SIM_ORDER = [
    "1 SIM + eSIM",
    "2 SIM (физические)",
    "Только eSIM, без физической!",
    "Обычная версия",
]
 
# -------------------- Работа с файлом --------------------
 
def load_prices() -> dict:
    try:
        with open(PRICES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
 
def save_prices(prices: dict):
    with open(PRICES_FILE, "w", encoding="utf-8") as f:
        json.dump(prices, f, ensure_ascii=False, indent=2)
 
def deep_set(d: dict, keys: list, value: list):
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d.setdefault(keys[-1], []).extend(value)
 
def merge_prices(base: dict, new: dict) -> dict:
    for category, sim_types in new.items():
        for sim_type, memories in sim_types.items():
            for memory, entries in memories.items():
                deep_set(base, [category, sim_type, memory], entries)
    return base
 
# -------------------- Парсинг прайса --------------------
 
def add_margin(price: int) -> int:
    return price + PRICE_INCREASE
 
def parse_price_from_entry(entry: str) -> int:
    """Извлекает число из строки вида 'Black – 112000₽'"""
    m = re.search(r"(\d+)₽", entry.replace(" ", "").replace(".", ""))
    return int(m.group(1)) if m else 999_999_999
 
def parse_supplier_text(text: str) -> dict:
    result = {}
 
    pattern = re.compile(
        r"([🇪🇺🇯🇵🇨🇳🇺🇸🇮🇳🇭🇰🇦🇪]?)\s*"
        r"([\w\s+]+?)\s+"
        r"(\d+(?:GB|TB)?)\s+"
        r"(.+?)\s*[-–]\s*"
        r"([\d\.,]+)",
        re.UNICODE
    )
 
    for line in text.splitlines():
        line = line.strip()
        if not line or "Заказать" in line:
            continue
 
        m = pattern.search(line)
        if not m:
            continue
 
        flag, model_raw, memory, color, price_str = m.groups()
        model_raw = model_raw.strip().lower()
        memory = memory.replace("GB", "").replace("gb", "")
        sim_type = SIM_MAP.get(flag, "Обычная версия")
        price_int = add_margin(int(price_str.replace(".", "").replace(",", "")))
 
        if model_raw.startswith("16e"):
            category = "iphone 16e"
        elif model_raw.startswith("16 pro max"):
            category = "iphone 16 pro max"
        elif model_raw.startswith("16 pro"):
            category = "iphone 16 pro"
        elif model_raw.startswith("16 plus"):
            category = "iphone 16 plus"
        elif model_raw.startswith("16"):
            category = "iphone 16"
        else:
            continue
 
        entry = f"{color.strip()} – {price_int}₽"
        deep_set(result, [category, sim_type, memory], [entry])
 
    return result
 
# -------------------- Поиск и форматирование --------------------
 
def clean(text: str) -> str:
    return text.lower().translate(str.maketrans('', '', string.punctuation)).strip()
 
def detect_brand(text: str):
    text = clean(text)
    for brand, variants in BRANDS.items():
        for word in variants:
            if fuzz.partial_ratio(word, text) >= THRESHOLD:
                return brand
    return None
 
def detect_category(text: str, brand: str):
    text = clean(text)
    best_category = None
    best_score = 0
 
    for category, (cat_brand, cat_model) in CATEGORY_MAP.items():
        if cat_brand != brand:
            continue
        score = fuzz.partial_ratio(cat_model, text)
        if score >= THRESHOLD and score > best_score:
            best_score = score
            best_category = category
 
    return best_category
 
def format_price_response(category: str, prices: dict) -> str:
    """
    Пример вывода:
 
    📱 iPhone 16 Pro
 
    🔹 1 SIM + eSIM
    128GB — 112 000₽
    256GB — 125 000₽
 
    🔹 2 SIM (физические)
    128GB — 108 000₽
    256GB — 120 000₽
    """
    data = prices.get(category)
    if not data:
        return None
 
    lines = [f"📱 *{category.title()}*\n"]
 
    # Сортируем SIM-типы в нужном порядке
    sim_types_sorted = sorted(
        data.keys(),
        key=lambda s: SIM_ORDER.index(s) if s in SIM_ORDER else 99
    )
 
    for sim_type in sim_types_sorted:
        memories = data[sim_type]
        lines.append(f"🔹 *{sim_type}*")
 
        # Сортируем объёмы памяти по возрастанию
        for memory in sorted(memories.keys(), key=lambda x: int(x) if x.isdigit() else 0):
            entries = memories[memory]
 
            # Берём минимальную цену среди всех цветов этого объёма
            min_price = min(parse_price_from_entry(e) for e in entries)
 
            # Форматируем с пробелом: 112000 → 112 000
            price_formatted = f"{min_price:,}".replace(",", " ")
 
            lines.append(f"{memory}GB — {price_formatted}₽")
 
        lines.append("")  # пустая строка между блоками SIM
 
    return "\n".join(lines).strip()
 
# -------------------- Хендлеры --------------------
 
PRICES = load_prices()
 
async def new_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    global PRICES
    PRICES = {}
    save_prices(PRICES)
    await update.message.reply_text("Старый прайс очищен. Готов к новым данным.")
 
async def go(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    global WRITE_MODE
    WRITE_MODE = True
    await update.message.reply_text("Режим записи включён. Отправляй прайс.")
 
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
    await update.message.reply_text(
        f"Текущий словарь PRICES:\n{json.dumps(PRICES, ensure_ascii=False, indent=2)}"
    )
 
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
 
    text = update.message.text
    user_id = update.effective_user.id
 
    # --- Админ в режиме записи прайса ---
    if user_id == ALLOWED_USER_ID and WRITE_MODE:
        global PRICES
        parsed = parse_supplier_text(text)
        PRICES = merge_prices(PRICES, parsed)
        save_prices(PRICES)
        await update.message.reply_text("Прайс добавлен и сохранён.")
        return
 
    # --- Пользователь ищет цену ---
    brand = detect_brand(text)
    if not brand:
        return  # не наш запрос — молчим
 
    category = detect_category(text, brand)
 
    if category:
        response = format_price_response(category, PRICES)
        if response:
            await update.message.reply_text(
                response,
                parse_mode="Markdown",
                reply_to_message_id=update.message.message_id
            )
        else:
            await update.message.reply_text(
                "Цены на эту модель пока не загружены 🙏",
                reply_to_message_id=update.message.message_id
            )
        return
 
    # Бренд найден, модель не распознана → показываем что есть в прайсе
    available = [
        cat_model
        for cat, (cat_brand, cat_model) in CATEGORY_MAP.items()
        if cat_brand == brand and cat in PRICES
    ]
    if available:
        examples = " / ".join(available)
        await update.message.reply_text(
            f"Уточни модель {brand.upper()} 📱\n\nДоступные варианты:\n{examples}",
            reply_to_message_id=update.message.message_id
        )
    else:
        await update.message.reply_text(
            f"Цены на {brand.upper()} пока не загружены 🙏",
            reply_to_message_id=update.message.message_id
        )
 
# -------------------- Запуск --------------------
 
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("new", new_prices))
app.add_handler(CommandHandler("go", go))
app.add_handler(CommandHandler("send", send_prices))
app.add_handler(CommandHandler("test", test_prices))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
 
app.run_polling()