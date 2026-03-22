from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TOKEN = "ТВОЙ_ТОКЕН_БОТА"
ALLOWED_USER_ID = 123456789  # твой Telegram ID

async def forward_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Игнорируем всех кроме тебя
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    msg = update.message

    # Если сообщение переслано от пользователя
    if msg.forward_from:
        await msg.reply_text(f"ID отправителя: {msg.forward_from.id}")
        return

    # Если сообщение переслано от канала или бота
    if msg.forward_from_chat:
        await msg.reply_text(f"ID чата/бота: {msg.forward_from_chat.id}")
        return

    # Если обычное сообщение, ничего не делаем
    await msg.reply_text("Сообщение не переслано, айди не определён.")

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.ALL, forward_id))

app.run_polling()