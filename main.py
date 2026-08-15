import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from supabase import create_client, Client

# إعداد التسجيل (Logging)
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

# استخدام موديل gemini-1.5-flash المباشر
model = genai.GenerativeModel('gemini-1.5-flash')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """أمر البداية /start"""
    user_first_name = update.effective_user.first_name
    await update.message.reply_text(
        f"أهلاً بك يا {user_first_name}! أنا بوت العيادة، كيف يمكنني مساعدتك اليوم؟"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة الرسائل القادمة واستدعاء Gemini"""
    user_text = update.message.text
    patient_id = update.effective_user.id

    try:
        # إرسال النص إلى Gemini
        response = model.generate_content(user_text)
        bot_reply = response.text if response.text else "عذراً، لم أستطع توليد إجابة مناسبة."

        # حفظ المراسلة في قاعدة بيانات Supabase (اختياري حسب جدولك)
        try:
            supabase.table("patients").upsert({
                "patient_id": patient_id,
                "data": {"last_message": user_text, "last_reply": bot_reply}
            }).execute()
        except Exception as db_err:
            logger.error(f"خطأ في قاعدة البيانات Supabase: {db_err}")

        # إرسال الرد للمستخدم في تليجرام
        await update.message.reply_text(bot_reply)

    except Exception as e:
        logger.error(f"خطأ أثناء معالجة الرسالة: {e}")
        # خطة بديلة تلقائية في حال تعثر الموديل الرئيسي
        try:
            fallback_model = genai.GenerativeModel('gemini-pro')
            fallback_response = fallback_model.generate_content(user_text)
            await update.message.reply_text(fallback_response.text)
        except Exception as fallback_err:
            logger.error(f"خطأ في الموديل البديل: {fallback_err}")
            await update.message.reply_text("حدث خطأ مؤقت أثناء معالجة طلبك، يرجى المحاولة لاحقاً.")

def main() -> None:
    """تشغيل البوت"""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("خطأ: لم يتم العثور على TELEGRAM_BOT_TOKEN في المتغيرات البيئية!")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # إضافة الموجهات (Handlers)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # بدء الاستماع للرسائل (Polling)
    logger.info("جاري تشغيل البوت...")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
