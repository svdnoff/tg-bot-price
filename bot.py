import os
import json
import re
import string
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from rapidfuzz import fuzz
 
# -------------------- Настройки --------------------
TOKEN = os.environ.get("TOKEN")
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID"))
 
SIM_MAP = {
    "🇨🇳": "2 SIM (физические)",
    "🇭🇰": "2 SIM (физические)",
    "🇮🇳": "1 SIM + eSIM",
    "🇯🇵": "1 SIM + eSIM",
    "🇦🇪": "1 SIM + eSIM",
    "🇪🇺": "1 SIM + eSIM",
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
    "Только eSIM (без физической SIM)",
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
 
    # Числа в цене: 49.200 или 49,200 или 49200
    price_pattern = re.compile(r"[-–]\s*([\d][.\d,]+)", re.UNICODE)
    memory_pattern = re.compile(r"\b(\d+)\s*(?:GB|gb)?\b")
 
    for line in text.splitlines():
        line = line.strip()
        if not line or "Заказать" in line:
            continue
 
        # Определяем флаг по началу строки
        flag = ""
        for f in SIM_MAP:
            if line.startswith(f):
                flag = f
                line = line[len(f):].strip()
                break
 
        sim_type = SIM_MAP.get(flag, "Обычная версия")
 
        # Ищем цену
        price_match = price_pattern.search(line)
        if not price_match:
            continue
        price_str = price_match.group(1).replace(".", "").replace(",", "")
        try:
            price_int = add_margin(int(price_str))
        except ValueError:
            continue
 
        # Убираем цену из строки чтобы найти модель и память
        line_no_price = line[:price_match.start()].strip()
 
        # Ищем объём памяти — только стандартные значения
        mem_match = re.search(r'\b(128|256|512|1024)\b', line_no_price)
        if not mem_match:
            continue
        memory = mem_match.group(1)
 
        # Определяем категорию по модели (ВАЖНО: сначала длинные варианты)
        line_lower = line_no_price.lower()
        if "16e" in line_lower:
            category = "iphone 16e"
        elif "16 pro max" in line_lower or "16pro max" in line_lower:
            category = "iphone 16 pro max"
        elif "16 pro" in line_lower or "16pro" in line_lower:
            category = "iphone 16 pro"
        elif "16 plus" in line_lower or "16plus" in line_lower:
            category = "iphone 16 plus"
        elif re.search(r'\b16\b', line_lower):
            category = "iphone 16"
        else:
            continue
 
        # Цвет — всё что после объёма памяти до цены
        color_part = line_no_price[mem_match.end():].strip().lstrip("GBgb").strip(" –-")
        if not color_part:
            color_part = "—"
 
        price_formatted = f"{price_int}₽"
        entry = f"{color_part} – {price_formatted}"
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
 
def normalize_query(text: str) -> str:
    """Заменяем русские варианты на английские для поиска по CATEGORY_MAP."""
    replacements = {
        "про макс": "pro max",
        "promах":   "pro max",
        "promax":   "pro max",
        "про":      "pro",
        "плюс":     "plus",
        "макс":     "max",
        "ультра":   "ultra",
        "слим":     "slim",
    }
    text = clean(text)
    for ru, en in replacements.items():
        text = text.replace(ru, en)
    return text
 
def detect_category(text: str, brand: str):
    text = normalize_query(text)
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
 
    # Бренд найден, модель не распознана → ищем похожие варианты
    query = normalize_query(text)
    scored = [
        (fuzz.partial_ratio(cat_model, query), cat_model, cat)
        for cat, (cat_brand, cat_model) in CATEGORY_MAP.items()
        if cat_brand == brand and cat in PRICES
    ]
    scored.sort(reverse=True)
    # Берём варианты с score > 40
    suggestions = [cat_model for score, cat_model, cat in scored if score > 40]
 
    if suggestions:
        examples = "\n".join(f"• {m}" for m in suggestions[:3])
        await update.message.reply_text(
            f"Такой модели нет, проверьте правильность написания ❌\n\nВозможно вы имели в виду:\n{examples}",
            reply_to_message_id=update.message.message_id
        )
    elif scored:
        # Есть товары бренда, но ничего похожего
        all_models = "\n".join(f"• {m}" for _, m, _ in scored)
        await update.message.reply_text(
            f"Такой модели нет, проверьте правильность написания ❌\n\nДоступные модели {brand.upper()}:\n{all_models}",
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
app.add_handler(CommandHandler("test", test_prices))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
 
app.run_polling()