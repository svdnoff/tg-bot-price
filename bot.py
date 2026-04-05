import os
import json
import re
import string
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from rapidfuzz import fuzz

# -------------------- Настройки --------------------
TOKEN = os.environ.get("TOKEN")
ADMIN_IDS = {
    8571929902,  # Сергей
    1132085874,  # Богдан
    866973179,  # Даня
}

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
    "iphone":  ["iphone", "айфон", "эпл", "apple"],
    "samsung": ["samsung", "самсунг", "самс", "санг"],
    "ps5":     ["ps5", "пс5", "плойка", "playstation"],
    "gamepad": ["gamepad", "геймпад", "джойстик"],
}

# Категории: ключ = название в прайсе, значение = (бренд, модель для поиска)
CATEGORY_MAP = {
    # iPhone
    "iphone 12":         ("iphone", "12"),
    "iphone 12 mini":    ("iphone", "12 mini"),
    "iphone 13":         ("iphone", "13"),
    "iphone 13 mini":    ("iphone", "13 mini"),
    "iphone 13 pro":     ("iphone", "13 pro"),
    "iphone 13 pro max": ("iphone", "13 pro max"),
    "iphone 14":         ("iphone", "14"),
    "iphone 14 plus":    ("iphone", "14 plus"),
    "iphone 14 pro":     ("iphone", "14 pro"),
    "iphone 14 pro max": ("iphone", "14 pro max"),
    "iphone 15":         ("iphone", "15"),
    "iphone 15 plus":    ("iphone", "15 plus"),
    "iphone 15 pro":     ("iphone", "15 pro"),
    "iphone 15 pro max": ("iphone", "15 pro max"),
    "iphone 16e":        ("iphone", "16e"),
    "iphone 16":         ("iphone", "16"),
    "iphone 16 plus":    ("iphone", "16 plus"),
    "iphone 16 pro":     ("iphone", "16 pro"),
    "iphone 16 pro max": ("iphone", "16 pro max"),
    "iphone 17e":        ("iphone", "17e"),
    "iphone 17":         ("iphone", "17"),
    "iphone 17 plus":    ("iphone", "17 plus"),
    "iphone 17 pro":     ("iphone", "17 pro"),
    "iphone 17 pro max": ("iphone", "17 pro max"),
    # Samsung
    "samsung a17":       ("samsung", "a17"),
    "samsung a36":       ("samsung", "a36"),
    "samsung a56":       ("samsung", "a56"),
    "samsung s25 fe":    ("samsung", "s25 fe"),
    "samsung s25":       ("samsung", "s25"),
    "samsung s25 ultra": ("samsung", "s25 ultra"),
    "samsung s26":       ("samsung", "s26"),
    "samsung s26 plus":  ("samsung", "s26 plus"),
    "samsung s26 ultra": ("samsung", "s26 ultra"),
    # PS5
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

def detect_iphone_category(line_lower: str):
    """Определяет категорию iPhone по тексту строки. Длинные варианты проверяются первыми."""
    # Порядок важен: от длинных к коротким чтобы "16 pro max" нашлось раньше "16"
    checks = [
        ("17 pro max", "iphone 17 pro max"),
        ("17 pro",     "iphone 17 pro"),
        ("17 plus",    "iphone 17 plus"),
        ("17e",        "iphone 17e"),
        ("17",         "iphone 17"),
        ("16 pro max", "iphone 16 pro max"),
        ("16 pro",     "iphone 16 pro"),
        ("16 plus",    "iphone 16 plus"),
        ("16e",        "iphone 16e"),
        ("16",         "iphone 16"),
        ("15 pro max", "iphone 15 pro max"),
        ("15 pro",     "iphone 15 pro"),
        ("15 plus",    "iphone 15 plus"),
        ("15",         "iphone 15"),
        ("14 pro max", "iphone 14 pro max"),
        ("14 pro",     "iphone 14 pro"),
        ("14 plus",    "iphone 14 plus"),
        ("14",         "iphone 14"),
        ("13 pro max", "iphone 13 pro max"),
        ("13 pro",     "iphone 13 pro"),
        ("13 mini",    "iphone 13 mini"),
        ("13",         "iphone 13"),
        ("12 mini",    "iphone 12 mini"),
        ("12",         "iphone 12"),
    ]
    for marker, category in checks:
        # Простое вхождение — порядок в списке гарантирует правильный приоритет
        if marker in line_lower:
            return category
    return None

def detect_samsung_category(line_lower: str):
    """Определяет категорию Samsung по тексту строки."""
    checks = [
        ("s25 ultra", "samsung s25 ultra"),
        ("s25 fe",    "samsung s25 fe"),
        ("s25",       "samsung s25"),
        ("s26 ultra", "samsung s26 ultra"),
        ("s26 plus",  "samsung s26 plus"),
        ("s26",       "samsung s26"),
        ("a56",       "samsung a56"),
        ("a36",       "samsung a36"),
        ("a17",       "samsung a17"),
    ]
    for marker, category in checks:
        if marker in line_lower:
            return category
    return None

def extract_memory(line: str):
    """
    Извлекает объём памяти из строки.
    Поддерживает форматы: 128, 256GB, 1TB, 2TB, 8/256 (RAM/ROM — берём ROM).
    Возвращает (memory_str, match_object) или (None, None).
    """
    # Формат Samsung: RAM/ROM (например 8/256 или 12/512 или 16/1Tb)
    slash_match = re.search(r'\d+\s*/\s*(\d+[Tt][Bb]|\d+)', line)
    if slash_match:
        rom = slash_match.group(1)
        rom_norm = re.sub(r'(?i)tb', 'TB', rom)
        if 'TB' in rom_norm:
            tb_num = re.match(r'(\d+)', rom_norm).group(1)
            return tb_num + 'TB', slash_match
        return rom_norm, slash_match

    # TB форматы: 1TB, 2TB, 1Tb итд
    tb_match = re.search(r'\b([12])\s*[Tt][Bb]\b', line)
    if tb_match:
        return tb_match.group(1) + 'TB', tb_match

    # Обычный формат: 128GB, 256GB, 512GB, 128, 256 итд
    mem_match = re.search(r'\b(128|256|512|1024)\s*(?:GB|gb)?', line)
    if mem_match:
        return mem_match.group(1), mem_match

    return None, None

def parse_supplier_text(text: str) -> dict:
    result = {}

    # Паттерн цены: – 49.200₽  или  – 49.200  или  -22000  или  -22000₽
    price_pattern = re.compile(r'[-–]\s*([\d][.\d,]+)\s*₽?', re.UNICODE)

    for line in text.splitlines():
        line = line.strip()
        # Пропускаем заголовки, пустые строки и "Заказать"
        if not line or "Заказать" in line:
            continue
        # Пропускаем строки-заголовки типа "📱 iPhone 16 ••••"
        if re.search(r'[•·]{3,}', line):
            continue

        # Убираем мусорные эмодзи в конце (🚛 и т.п.) — оставляем только флаги в начале
        line = re.sub(r'(?<!\A)[🚛🔥💥✅❌⚡🎮📦]', '', line).strip()

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

        # Часть строки до цены — содержит модель, память, цвет
        line_no_price = line[:price_match.start()].strip()
        line_lower = line_no_price.lower()

        # Определяем бренд и категорию (Samsung первым — иначе A17/S17 матчится как iPhone 17)
        category = detect_samsung_category(line_lower)
        if not category:
            category = detect_iphone_category(line_lower)
        if not category:
            continue

        # Извлекаем память
        memory, mem_match = extract_memory(line_no_price)
        if not memory:
            continue

        # Цвет — всё что после памяти
        after_mem = line_no_price[mem_match.end():]
        # Убираем GB/Tb/TB остатки
        after_mem = re.sub(r'(?i)^[\s/]*(gb|tb)?[\s–\-]*', '', after_mem)
        color_part = after_mem.strip().strip('–- ').strip()
        # Убираем эмодзи цветов (🖤⚪🔵 и т.п.) из цвета — они не нужны в тексте
        color_part = re.sub(r'[\U0001F300-\U0001FFFF]', '', color_part).strip()
        if not color_part:
            color_part = "—"

        entry = f"{color_part} – {price_int}₽"
        deep_set(result, [category, sim_type, memory], [entry])

    return result

# -------------------- Поиск и форматирование --------------------

def clean(text: str) -> str:
    return text.lower().translate(str.maketrans('', '', string.punctuation)).strip()

def detect_brand(text: str):
    text_clean = clean(text)
    for brand, variants in BRANDS.items():
        for word in variants:
            if fuzz.partial_ratio(word, text_clean) >= THRESHOLD:
                return brand
    return None

def normalize_query(text: str) -> str:
    """Переводим русские варианты в английские."""
    replacements = {
        # iPhone
        "про макс": "pro max",
        "про":      "pro",
        "плюс":     "plus",
        "макс":     "max",
        "мини":     "mini",
        "слим":     "slim",
        # Samsung
        "ультра":   "ultra",
        "фе":       "fe",
        "а17":      "a17",
        "а36":      "a36",
        "а56":      "a56",
        "с25 ультра": "s25 ultra",
        "с25 фе":   "s25 fe",
        "с25":      "s25",
        "с26 ультра": "s26 ultra",
        "с26 плюс": "s26 plus",
        "с26":      "s26",
    }
    text = clean(text)
    for ru, en in replacements.items():
        text = text.replace(ru, en)
    return text

def detect_category(text: str, brand: str):
    text = normalize_query(text)

    # Сортируем кандидатов по убыванию длины модели — длинные проверяются первыми
    candidates = sorted(
        [(cat, cat_model) for cat, (cat_brand, cat_model) in CATEGORY_MAP.items() if cat_brand == brand],
        key=lambda x: len(x[1]),
        reverse=True
    )

    # Сначала точное вхождение
    for category, cat_model in candidates:
        if re.search(r'\b' + re.escape(cat_model) + r'\b', text):
            return category

    # Потом нечёткий поиск с приоритетом длинных моделей
    best_category = None
    best_score = 0
    best_len = 0
    for category, cat_model in candidates:
        score = fuzz.partial_ratio(cat_model, text)
        if score >= THRESHOLD:
            if score > best_score or (score == best_score and len(cat_model) > best_len):
                best_score = score
                best_len = len(cat_model)
                best_category = category

    return best_category

def format_price_response(category: str, prices: dict) -> str:
    data = prices.get(category)
    if not data:
        return None

    lines = [f"📱 *{category.title()}*\n"]

    sim_types_sorted = sorted(
        data.keys(),
        key=lambda s: SIM_ORDER.index(s) if s in SIM_ORDER else 99
    )

    for sim_type in sim_types_sorted:
        memories = data[sim_type]
        lines.append(f"🔹 *{sim_type}*")

        def mem_sort_key(x):
            if x.isdigit(): return int(x)
            if x == "1TB": return 1024
            if x == "2TB": return 2048
            return 9999

        for memory in sorted(memories.keys(), key=mem_sort_key):
            entries = memories[memory]
            min_price = min(parse_price_from_entry(e) for e in entries)
            price_formatted = f"{min_price:,}".replace(",", " ")
            mem_label = memory if "TB" in memory else f"{memory}GB"
            lines.append(f"{mem_label} — {price_formatted}₽")

        lines.append("")

    footer = (
        "\n\n💬 Цены могут немного отличаться в зависимости от цвета, для заказа и вопросов напишите нам:\n"
        "@DrygoeMesto23\n"
        "Также можем привезти часы, PS5 и многое другое 🎮⌚"
    )
    return "\n".join(lines).strip() + footer

# -------------------- Хендлеры --------------------

PRICES = load_prices()

async def new_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    global PRICES
    PRICES = {}
    save_prices(PRICES)
    await update.message.reply_text("Старый прайс очищен. Готов к новым данным.")

async def go(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    global WRITE_MODE
    WRITE_MODE = True
    await update.message.reply_text("Режим записи включён. Отправляй прайс. Когда закончишь — /done")

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    global WRITE_MODE
    WRITE_MODE = False
    await update.message.reply_text("Режим записи выключен. Бот готов отвечать пользователям ✅")

async def test_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
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
    if user_id in ADMIN_IDS and WRITE_MODE:
        global PRICES
        parsed = parse_supplier_text(text)
        PRICES = merge_prices(PRICES, parsed)
        save_prices(PRICES)
        await update.message.reply_text("Прайс добавлен и сохранён.")
        return

    # --- Пользователь ищет цену ---
    brand = detect_brand(text)
    if not brand:
        return

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

    # Модель не распознана — ищем похожие
    query = normalize_query(text)
    scored = [
        (fuzz.partial_ratio(cat_model, query), cat_model, cat)
        for cat, (cat_brand, cat_model) in CATEGORY_MAP.items()
        if cat_brand == brand and cat in PRICES
    ]
    scored.sort(reverse=True)
    suggestions = [cat_model for score, cat_model, cat in scored if score > 40]

    if suggestions:
        examples = "\n".join(f"• {m}" for m in suggestions[:3])
        await update.message.reply_text(
            f"Такой модели нет, проверьте правильность написания ❌\n\nВозможно вы имели в виду:\n{examples}",
            reply_to_message_id=update.message.message_id
        )
    elif scored:
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
app.add_handler(CommandHandler("done", done))
app.add_handler(CommandHandler("test", test_prices))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

app.run_polling()