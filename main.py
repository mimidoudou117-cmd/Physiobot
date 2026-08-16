import os
import logging
import asyncio

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters
)

import google.generativeai as genai
from supabase import create_client, Client


# =========================
# Logging
# =========================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)


# =========================
# Environment Variables
# =========================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

required_vars = {
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "GEMINI_API_KEY": GEMINI_API_KEY,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
}

missing = [k for k, v in required_vars.items() if not v]

if missing:
    raise ValueError(
        f"Missing environment variables: {', '.join(missing)}"
    )


# =========================
# Gemini
# =========================
genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel("gemini-1.5-flash")


# =========================
# Supabase
# =========================
supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


# =========================
# System Prompt
# =========================
SYSTEM_PROMPT = """
أنت مساعد ذكي تابع لعيادة طبية.

القواعد:

- كن مهذباً ومهنياً.
- لا تقدم تشخيصاً نهائياً.
- لا تصف أدوية تحتاج وصفة طبية.
- اجمع الأعراض بشكل منظم.
- إذا ظهرت أعراض خطيرة اطلب مراجعة الطبيب فوراً.
- أجب باللغة العربية.
"""


# =========================
# Database Functions
# =========================
def save_message(patient_id, role, content):
    try:
        supabase.table("messages").insert({
            "patient_id": str(patient_id),
            "role": role,
            "content": content
        }).execute()

    except Exception as e:
        logger.error(f"Save message error: {e}")


def get_history(patient_id, limit=10):
    try:
        result = (
            supabase.table("messages")
            .select("*")
            .eq("patient_id", str(patient_id))
            .order("id", desc=False)
            .limit(limit)
            .execute()
        )

        return result.data or []

    except Exception as e:
        logger.error(f"History error: {e}")
        return []


# =========================
# Telegram Commands
# =========================
async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user

    await update.message.reply_text(
        f"مرحباً {user.first_name} 👋\n\n"
        "أنا المساعد الذكي للعيادة.\n"
        "كيف يمكنني مساعدتك اليوم؟"
    )


# =========================
# Message Handler
# =========================
async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_text = update.message.text
    patient_id = update.effective_user.id

    try:

        history = get_history(patient_id)

        conversation = SYSTEM_PROMPT + "\n\n"

        for msg in history:
            role = msg["role"]
            content = msg["content"]

            conversation += f"{role}: {content}\n"

        conversation += f"\nالمريض: {user_text}"

        response = await asyncio.to_thread(
            model.generate_content,
            conversation
        )

        bot_reply = (
            response.text
            if hasattr(response, "text")
            else "عذراً، لم أتمكن من إنشاء رد."
        )

        save_message(
            patient_id,
            "user",
            user_text
        )

        save_message(
            patient_id,
            "assistant",
            bot_reply
        )

        await update.message.reply_text(bot_reply)

    except Exception as e:

        logger.exception(e)

        await update.message.reply_text(
            "حدث خطأ أثناء معالجة طلبك."
        )


# =========================
# Main
# =========================
def main():

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print("Bot is running...")

    app.run_polling()


if __name__ == "__main__":
    main()
