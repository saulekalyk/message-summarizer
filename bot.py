import os

from telegram.error import TelegramError
from pathlib import Path
from dotenv import load_dotenv
from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

env_path = Path(__file__).with_name(".env")
load_dotenv(dotenv_path=env_path)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

print("OPENAI_API_KEY =", OPENAI_API_KEY)
print("TOKEN =", TOKEN)

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

buffers: dict[int, list[str]] = {}
MAX_BUFFER = 500


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('Привет! Напиши сообщения, потом используй /sum N для краткого резюме.')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text
    if not text:
        return

    buffers.setdefault(chat_id, []).append(text)

    if len(buffers[chat_id]) > MAX_BUFFER:
        buffers[chat_id].pop(0)

   

async def sum_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    try:
        count = int(context.args[0]) if context.args else 5

        chat_buffer = buffers.get(chat_id, [])
        selected_messages = [m for m in chat_buffer[-count:] if m.strip() and not m.startswith("/")]

        if not selected_messages:
            await update.message.reply_text("В буфере нет подходящих сообщений для суммирования.")
            return
        
        combined_text = "\n".join(selected_messages)

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "Ты — помощник, который суммирует текстовые сообщения.\n"
                    "Сделай краткое резюме по ключевым идеям.\n"
                    "не повторяя каждое сообщение полностью."
                )},
                {"role": "user", "content": combined_text}
            ],
            max_tokens=200
        )

        summary = response.choices[0].message.content
        await update.message.reply_text(summary)

        buffers[chat_id] = []

    except ValueError:
        await update.message.reply_text("Пожалуйста, укажи число после команды, например: /sum 5")
    except Exception as e:
        await update.message.reply_text(f"Ошибка при генерации резюме: {e}")

async def clear_buffer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    buffers[chat_id] = []

    try:
        await context.bot.send_message(chat_id=chat_id, text="Буфер очищен")
    except TelegramError as e:
        print("Не смог отправить сообщение в clear_buffer:", e)


#temporary function 
async def debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"Сообщений в буфере: {len(buffers.get(chat_id, []))}")

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("sum", sum_messages))
    app.add_handler(CommandHandler("debug", debug))
    app.add_handler(CommandHandler("clear", clear_buffer))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


    print("Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()