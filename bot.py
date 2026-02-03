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

# print("OPENAI_API_KEY =", OPENAI_API_KEY)
# print("TOKEN =", TOKEN)

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

    display_name = (update.effective_user.full_name or update.effective_user.first_name or "Пользователь").strip()
    buffers.setdefault(chat_id, []).append(f"{display_name}: {text.strip()}")

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

        messages=[
            {
                "role": "system", 
                "content": (
                    "Ты — помощник, который читает сообщения из Telegram-чата "
                    "и пересказывает, что в нём происходило."
                )
            },
            {
                "role": "user", 
                "content": (
                    "Тебе пришлют сообщения из чата."
                    "Каждое ссообщение имеет формат: 'Имя: текст сообщения'. "
                )
            },
            {
                "role": "user", 
                "content": (
                    "Твоя задача - написать связный текст, как небольшой рассказ,"
                    "о том, что обсуждалось в чате."
                )
            },
            {
                "role": "user", 
                "content": (
                    "Ты должене упомянуть каждого человека по ИМЕНИ"
                    "(имя указано в начале сообщения до двоеточия)."
                )
            },
            {
                "role": "user", 
                "content": (
                    "Описывая каждого человека, используй формулировки вида:\n"
                    "— «Имя сказал(а), что …»\n"
                    "— «Имя говорил(а) о том, что …»\n\n"
                    "Глагол подбирай по контексту и по звучанию фразы. "
                    "Не используй формат 'Имя: ...'."
                )
            },
            {
                "role": "user", 
                "content": (
                    "После слов «сказал(а) / говорил(а) о том, что» "
                    "кратко опиши суть сообщений этого человека, "
                    "не повторяя текст дословно."
                )
            },
            {
                "role": "user", 
                "content": (
                    "Не выдумывай факты и не добавляй того, чего нет в сообщениях. "
                    "Не используй @username и технические никнеймы."
                )
            },
            {
                "role": "user", 
                "content": (
                    "Не используй списки, пункты или маркировку. "
                    "Ответ должен быть обычным связным текстом."
                )
            },
            {
                "role": "user", 
                "content": {
                    "В конце добавь одно краткое предложение "
                    "про общую атмосферу чата(например активная, веселая, деловая и т.д.),"
                    "если это ощущается по сообщениям."
                }
            },
            {
                "role": "system",
                "content": combined_text
            }
        ]
    
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=300
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