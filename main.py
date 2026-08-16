import os
import logging
import asyncio
import requests
import nest_asyncio

# تفعيل nest-asyncio لتجنب أخطاء Event Loop على Render نهائياً
nest_asyncio.apply()

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
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading


# ==========================
# Logging
# ==========================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)


# ==========================
# Environment Variables
# ==========================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not all([
    TELEGRAM_BOT_TOKEN,
    GEMINI_API_KEY,
    SUPABASE_URL,
    SUPABASE_KEY
]):
    raise Exception("Missing environment variables")


# ==========================
# Gemini
# ==========================
genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel(
    "gemini-1.5-flash"
)


# ==========================
# Supabase
# ==========================
supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


# ==========================
# Assistant Prompt
# ==========================
SYSTEM_PROMPT = """
أنت مساعد ذكي تابع لعيادة.

القواعد:
- أجب بالعربية.
- كن محترماً ومهنياً.
- لا تقدم تشخيصاً نهائياً.
- لا تصف أدوية تحتاج وصفة طبية.
- عند ظهور أعراض خطيرة اطلب مراجعة الطبيب.
"""


# ==========================
# Database Functions
# ==========================
def save_message(patient_id, role, content):
    try:
        supabase.table("messages").insert({
            "patient_id": str(patient_id),
            "role": role,
            "content": content
        }).execute()
    except Exception as e:
        logger.error(f"DB Save Error: {e}")


def get_history(patient_id):
    try:
        result = (
            supabase.table("messages")
            .select("*")
            .eq("patient_id", str(patient_id))
            .order("id")
            .limit(15)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"DB Read Error: {e}")
        return []


# ==========================
# Telegram Commands
# ==========================
async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "مرحباً 👋\nأنا المساعد الذكي للعيادة.\nكيف يمكنني مساعدتك؟"
    )


# ==========================
# Message Handler
# ==========================
async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_text = update.message.text
    patient_id = update.effective_user.id

    try:
        history = get_history(patient_id)
        prompt = SYSTEM_PROMPT + "\n\n"

        for msg in history:
            role = msg["role"]
            content = msg["content"]
            prompt += f"{role}: {content}\n"

        prompt += f"\nالمريض: {user_text}"

        response = await asyncio.to_thread(
            model.generate_content,
            prompt
        )

        answer = getattr(
            response,
            "text",
            "عذراً، لم أتمكن من معالجة الطلب."
        )

        save_message(
            patient_id,
            "user",
            user_text
        )

        save_message(
            patient_id,
            "assistant",
            answer
        )

        await update.message.reply_text(answer)

    except Exception as e:
        logger.exception(e)
        await update.message.reply_text(
            "حدث خطأ أثناء معالجة الرسالة."
        )


# ==========================
# Error Handler
# ==========================
async def error_handler(
    update,
    context
):
    logger.error(
        f"Update {update} caused error {context.error}"
    )


# ==========================
# Dummy Web Server for Render
# ==========================
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is active and running!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    logger.info(f"Dummy web server started on port {port}")
    server.serve_forever()


# ==========================
# Main
# ==========================
def main():
    # 1. تشغيل خادم الويب الوهمي في Thread مستقل لإرضاء منصة Render
    server_thread = threading.Thread(target=run_dummy_server, daemon=True)
    server_thread.start()

    # 2. حذف الـ Webhook القديم لمنع تضارب التحديثات (خطأ 409)
    try:
        requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook?drop_pending_updates=true",
            timeout=10
        )
        logger.info("Webhook deleted successfully")
    except Exception as e:
        logger.warning(
            f"Webhook delete failed: {e}"
        )

    # 3. إعداد تطبيق تيليجرام
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    app.add_error_handler(
        error_handler
    )

    logger.info("Bot started successfully and polling...")

    # 4. تشغيل البوت بنظام التشغيل المستمر
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
