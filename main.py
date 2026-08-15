import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from supabase import create_client, Client
import google.generativeai as genai

# إعداد التسجيل (Logging)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# جلب متغيرات البيئة
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# تهيئة Supabase و Gemini
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')




def get_patient_data(patient_id: str) -> dict:
    """جلب بيانات المريض من Supabase"""
    try:
        response = supabase.table("patients").select("data").eq("patient_id", patient_id).execute()
        if response.data:
            return response.data[0]["data"]
    except Exception as e:
        logger.error(f"خطأ في جلب البيانات: {e}")
    
    # القالب الافتراضي إذا كان المريض جديداً
    return {
        "soap_notes": [],
        "pain_scores": [],
        "rehab_program": []
    }

def save_patient_data(patient_id: str, data: dict):
    """حفظ بيانات المريض في Supabase"""
    try:
        supabase.table("patients").upsert({
            "patient_id": patient_id,
            "data": data
        }).execute()
    except Exception as e:
        logger.error(f"خطأ في حفظ البيانات: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر البداية"""
    welcome_text = (
        "مرحباً بك في نظام PhysioBot للتقييم والمتابعة العلاجية! 🩺\n\n"
        "يمكنك إرسال الملاحظات السريرية، مستويات الألم، أو خطط العلاج لتوثيقها وحفظها آلياً."
    )
    await update.message.reply_text(welcome_text)

async def view_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض ملف المريض الحالي"""
    patient_id = str(update.effective_user.id)
    patient_data = get_patient_data(patient_id)
    
    # معالجة مستوى الألم الأخير بأسلوب آمن بدون أخطاء بناء جملة
    pain_list = patient_data.get("pain_scores", [])
    last_pain = pain_list[-1].get("score", "غير مسجل") if pain_list else "غير مسجل"
    
    notes_count = len(patient_data.get("soap_notes", []))
    rehab_count = len(patient_data.get("rehab_program", []))

    profile_text = (
        f"📊 **سجل المريض:**\n"
        f"• عدد الملاحظات السريرية (SOAP): {notes_count}\n"
        f"• 📈 آخر مستوى ألم مسجل: {last_pain}\n"
        f"• 🏋️ تمارين التأهيل المسجلة: {rehab_count}"
    )
    await update.message.reply_text(profile_text, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الرسائل الواردة باستخدام Gemini ومزامنتها مع Supabase"""
    patient_id = str(update.effective_user.id)
    user_text = update.message.text
    patient_data = get_patient_data(patient_id)

    # توجيه الذكاء الاصطناعي مع تحليلات العلاج الطبيعي
    prompt = f"""
    أنت مساعد ذكي متخصص في العلاج الطبيعي والإعادة التأهيلية.
    بناءً على رسالة المريض أو الأخصائي التالية: "{user_text}"
    قم بتقديم استجابة مهنية ودقيقة تشمل النصائح أو التقييم المناسب.
    """
    
    try:
        response = model.generate_content(prompt)
        reply_text = response.text

        # التوثيق والتحليلات الآلية
        if "ألم" in user_text or "pain" in user_text.lower():
            patient_data.setdefault("pain_scores", []).append({"score": user_text, "text": user_text})
        else:
            patient_data.setdefault("soap_notes", []).append({"note": user_text})

        # حفظ التحديثات في السحابة
        save_patient_data(patient_id, patient_data)
        await update.message.reply_text(reply_text)

    except Exception as e:
        logger.error(f"خطأ أثناء معالجة الرسالة: {e}")
        await update.message.reply_text("حدث خطأ أثناء معالجة طلبك، يرجى المحاولة لاحقاً.")

def main():
    """تشغيل البوت"""
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("profile", view_profile))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling()

if __name__ == "__main__":
    main()
