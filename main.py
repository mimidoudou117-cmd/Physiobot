import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
import google.generativeai as genai
from supabase import create_client, Client

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# جلب المتغيرات البيئية
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# تهيئة Supabase و Gemini
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)

# استخدام موديل gemini-2.0-flash
model = genai.GenerativeModel('gemini-2.0-flash')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_first_name = update.effective_user.first_name
    await update.message.reply_text(
        f"أهلاً {user_first_name}! أنا بوت العيادة، كيف يمكنني مساعدتك اليوم؟"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    patient_id = update.effective_user.id

    try:
        response = model.generate_content(user_text)
        bot_reply = response.text if response.text else "عذراً، لم أستطع معالجة طلبك."
        
        try:
            supabase.table("patients").upsert({
                "patient_id": patient_id,
                "data": {"last_message": user_text}
            }).execute()
        except Exception as e:
            logger.error(f"Supabase error: {e}")

        await update.message.reply_text(bot_reply)

    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await update.message.reply_text("حدث خطأ أثناء معالجة الرسالة.")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("Bot is running...")
    app.run_polling()
