import os
import sqlite3

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

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

buffers: dict[int, list[str]] = {}
MAX_BUFFER = 500

DB_PATH = "bot.db"

def get_conn():
    return sqlite3.connect(DB_PATH)

def init_db():
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            nickname TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()

def set_nickname(telegram_id: int, nickname: str) -> None:
    with get_conn() as conn:
        conn.execute("""
        INSERT INTO users (telegram_id, nickname, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(telegram_id) DO UPDATE SET
            nickname=excluded.nickname,
            updated_at=CURRENT_TIMESTAMP;
        """, (telegram_id, nickname))
        conn.commit()

def delete_nickname(telegram_id: int) -> None:
    with get_conn() as conn:
        conn.execute("""
        UPDATE users
        SET nickname=NULL, updated_at=CURRENT_TIMESTAMP
        WHERE telegram_id=?;
        """, (telegram_id,))
        conn.commit()

def get_nickname(telegram_id: int) -> str | None:
    with get_conn() as conn:
        cursor = conn.execute("SELECT nickname FROM users WHERE telegram_id=?;", (telegram_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return row[0]
    
def get_display_name(user) -> str:
    if not user:
        return "Пользователь"
    nick = get_nickname(user.id)
    if nick and str(nick).strip():
        return nick.strip()
    return (user.full_name or user.first_name or "Пользователь").strip()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я помогу кратко суммировать переписку.\n\n"
        "Что я умею:\n"
        "• /nickname — установить или изменить свой ник\n"
        "• /nickoff — убрать ник\n"
        "• /sum N — сделать краткое резюме последних N сообщений\n\n"
        "Просто пиши сообщения в чат, а когда понадобится — вызови /sum."
    )

async def nickname_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    telegram_id = user.id

    if not context.args:
        current_nick = get_nickname(telegram_id)
        if current_nick:
            await update.message.reply_text(
                f"Твой никнейм сейчас: {current_nick}\n"
                f"Изменить: /nickname НовыйНик\n"
                f"Удалить: /nickname off"
            )
        else:
            await update.message.reply_text(
                "У тебя нет установленного никнейма.\n"
                "Установить: /nickname НовыйНик\n"
                "Удалить: /nickname off"
            )
        return
    
    raw = " ".join(context.args).strip()

    if raw.lower() in {"off", "delete", "remove", "clear", "reset"}:
        delete_nickname(telegram_id)
        await update.message.reply_text("Твой никнейм был удалён.")
        return
    
    if len(raw) > 32:
        await update.message.reply_text("Никнейм слишком длинный. Максимум 32 символа.")
        return
    
    set_nickname(telegram_id, raw)
    await update.message.reply_text(f"Твой никнейм был изменен на: {raw}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text
    if not text:
        return

    display_name = get_display_name(update.effective_user)
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
                "role": "system", 
                "content": (
                    "Тебе пришлют сообщения из чата."
                    "Каждое ссообщение имеет формат: 'Имя: текст сообщения'. "
                )
            },
            {
                "role": "system", 
                "content": (
                    "Твоя задача - написать связный текст, как небольшой рассказ,"
                    "о том, что обсуждалось в чате."
                )
            },
            {
                "role": "system", 
                "content": (
                    "Ты должене упомянуть каждого человека по ИМЕНИ"
                    "(имя указано в начале сообщения до двоеточия)."
                )
            },
            {
                "role": "system", 
                "content": (
                    "Описывая каждого человека, используй формулировки вида:\n"
                    "— «Имя сказал(а), что …»\n"
                    "— «Имя говорил(а) о том, что …»\n\n"
                    "Глагол подбирай по контексту и по звучанию фразы. "
                    "Не используй формат 'Имя: ...'."
                )
            },
            {
                "role": "system", 
                "content": (
                    "После слов «сказал(а) / говорил(а) о том, что» "
                    "кратко опиши суть сообщений этого человека, "
                    "не повторяя текст дословно."
                )
            },
            {
                "role": "system", 
                "content": (
                    "Игнорируй второстепенные детали, "
                    "выделяй лишь самые важные идеи, "
                    "даже если говорящих много."
                )
            },
            {
                "role": "system", 
                "content": (
                    "Не выдумывай факты и не добавляй того, чего нет в сообщениях. "
                    "Не используй @username и технические никнеймы."
                )
            },
            {
                "role": "system", 
                "content": (
                    "Не используй списки, пункты или маркировку. "
                    "Ответ должен быть обычным связным текстом."
                )
            },
            {
                "role": "system", 
                "content": (
                    "В конце добавь одно краткое предложение "
                    "про общую атмосферу чата(например активная, веселая, деловая и т.д.),"
                    "если это ощущается по сообщениям."
                )
            },
            {
                "role": "user",
                "content": combined_text
            }
        ]
    
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=200,
            temperature=0.7
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
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("nickname", nickname_cmd))
    app.add_handler(CommandHandler("sum", sum_messages))
    app.add_handler(CommandHandler("debug", debug))
    app.add_handler(CommandHandler("clear", clear_buffer))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


    print("Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()