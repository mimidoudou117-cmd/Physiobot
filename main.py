import os
import json
import asyncio
import nest_asyncio
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    CallbackQueryHandler, filters, ContextTypes
)
from supabase import create_client, Client

nest_asyncio.apply()

# ---------------------------------------------------------
# 1. تهيئة الخدمات (Gemini + Supabase)
# ---------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# إعداد قاعدة البيانات السحابية Supabase (إن توفرت البيئة)
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

system_instruction = (
    "أنت أخصائي علاج طبيعي وتأهيل حركي محترف وخبير في التوثيق السريري. "
    "تساعد في بناء برامج علاجية مخصصة، وتحليل الأعراض، وتوليد تقارير SOAP الطبية المعتمدة. "
    "عند اقتراح تمارين، اذكر اسمها، المجموعات، التكرارات، والتوجيهات الوقائية."
)

model = genai.GenerativeModel(
    model_name='gemini-1.5-flash',
    system_instruction=system_instruction
)

# ---------------------------------------------------------
# 2. إدارة البيانات المحلية والتزامن السحابي
# ---------------------------------------------------------
PATIENTS_DIR = "patients_db"
if not os.path.exists(PATIENTS_DIR):
    os.makedirs(PATIENTS_DIR)

active_patient = {}  # {user_id: patient_id}
user_chats = {}      # {user_id: chat_session}

def get_file_path(patient_id):
    clean_id = "".join(c for c in patient_id if c.isalnum() or c in (' ', '_', '-')).strip()
    return os.path.join(PATIENTS_DIR, f"{clean_id}.json")

def load_patient_data(patient_id):
    # محاولة التحميل من قاعدة البيانات السحابية أولاً
    if supabase:
        try:
            res = supabase.table("patients").select("*").eq("patient_id", patient_id).execute()
            if res.data:
                return res.data[0]["data"]
        except Exception as e:
            print(f"Cloud load error: {e}")

    # التحميل المحلي في حال عدم وجود سحابة
    path = get_file_path(patient_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"patient_id": patient_id, "history": [], "pain_scores": [], "hep": []}

def save_patient_data(patient_id, data):
    # حفظ محلي
    path = get_file_path(patient_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    # مزامنة سحابية
    if supabase:
        try:
            supabase.table("patients").upsert({"patient_id": patient_id, "data": data}).execute()
        except Exception as e:
            print(f"Cloud save error: {e}")

# ---------------------------------------------------------
# 3. واجهات المستخدم والأزرار التفاعلية
# ---------------------------------------------------------
def get_main_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("📊 تسجيل مستوى الألم", callback_data="btn_pain"),
            InlineKeyboardButton("📋 تقرير SOAP", callback_data="btn_soap")
        ],
        [
            InlineKeyboardButton("🏋️ برنامج التمارين (HEP)", callback_data="btn_hep"),
            InlineKeyboardButton("📂 ملف المريض", callback_data="btn_file")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ---------------------------------------------------------
# 4. معالجات الأوامر (Command Handlers)
# ---------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "مرحباً بك في **نظام العيادة الذكية للتأهيل والعلاج الطبيعي** 🩺\n\n"
        "يمكنك إدارة كافة حالات المرضى، متابعة مستويات الألم، وتوليد التقارير السريرية والبرامج التأهيلية بسهولة.\n\n"
        "📌 **الأوامر السريعة:**\n"
        "• `/new_patient <الاسم>` - فتح أو اختيار ملف مريض.\n"
        "• `/list_patients` - قائمة المرضى المسجلين.\n"
        "• `/menu` - عرض الأزرار التفاعلية للمريض الحالي."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def set_patient(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    if not context.args:
        await update.message.reply_text("يرجى كتابة اسم أو رقم المريض.\nمثال: `/new_patient أحمد_بناني`", parse_mode="Markdown")
        return

    patient_id = " ".join(context.args)
    active_patient[user_id] = patient_id
    
    patient_data = load_patient_data(patient_id)
    gemini_history = []
    for item in patient_data.get("history", []):
        gemini_history.append({"role": "user", "parts": [item["user"]]})
        gemini_history.append({"role": "model", "parts": [item["bot"]]})

    user_chats[user_id] = model.start_chat(history=gemini_history)

    msg = (
        f"✅ **تم الانتقال إلى ملف المريض:** `{patient_id}`\n"
        f"📊 عدد المدخلات المسجلة: {len(patient_data.get('history', []))}\n"
        f"📈 آخر مستوى ألم مسجل: {patient_data.get('pain_scores', [{'score': 'غير مسجل'})][-1]['score']}\n\n"
        "اختر خياراً من اللوحة أو ابدأ بكتابة المدخلات الطبيّة مباشرة:"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    if user_id not in active_patient:
        await update.message.reply_text("يرجى اختيار مريض أولاً عبر الأمر `/new_patient <الاسم>`")
        return
    await update.message.reply_text(f"🎮 **لوحة التحكّم - المريض:** `{active_patient[user_id]}`", parse_mode="Markdown", reply_markup=get_main_keyboard())

async def list_patients(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = [f.replace(".json", "") for f in os.listdir(PATIENTS_DIR) if f.endswith(".json")]
    if not files:
        await update.message.reply_text("لا يوجد مرضى مسجلون حالياً.")
        return

    msg = "📋 **قائمة المرضى المسجلين:**\n\n"
    for name in files:
        msg += f"• `{name}`\n"
    msg += "\nللإنتقال لأي ملف: `/new_patient <الاسم>`"
    await update.message.reply_text(msg, parse_mode="Markdown")

# ---------------------------------------------------------
# 5. معالجة الأزرار التفاعلية (Callback Query Handler)
# ---------------------------------------------------------
async def button_click_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.message.chat_id

    if user_id not in active_patient:
        await query.message.reply_text("يرجى حديد المريض أولاً باستخدام `/new_patient`")
        return

    patient_id = active_patient[user_id]
    patient_data = load_patient_data(patient_id)
    data = query.data

    if data == "btn_pain":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(str(i), callback_data=f"set_pain_{i}") for i in range(1, 6)],
            [InlineKeyboardButton(str(i), callback_data=f"set_pain_{i}") for i in range(6, 11)]
        ])
        await query.message.reply_text("قم بتحديد مستوى الألم الحالي للمريض من (1 إلى 10):", reply_markup=kb)

    elif data.startswith("set_pain_"):
        score = data.split("_")[-1]
        patient_data.setdefault("pain_scores", []).append({"score": score, "date": str(asyncio.get_event_loop().time())})
        save_patient_data(patient_id, patient_data)
        await query.message.reply_text(f"✅ تم تسجيل مستوى الألم: **{score}/10** للمريض `{patient_id}`", parse_mode="Markdown")

    elif data == "btn_soap":
        await query.message.reply_text("⏳ جاري توليد التقرير السريري المعتمد (SOAP Note)...")
        chat = user_chats.get(user_id)
        if chat:
            prompt = "قم بصياغة تقرير سريري منظم بتنسيق SOAP (Subjective, Objective, Assessment, Plan) بناءً على كل البيانات المسجلة لهذه الحالة."
            res = chat.send_message(prompt)
            await query.message.reply_text(res.text)

    elif data == "btn_hep":
        await query.message.reply_text("⏳ جاري صياغة برنامج التمارين المنزلية (Home Exercise Program)...")
        chat = user_chats.get(user_id)
        if chat:
            prompt = "أنشئ برنامج تمارين منزلية (HEP) واضح ومباشر للمريض يشمل اسم التمرين، التكرارات، المجموعات، ورابط بحث يوتيوب توضيحي للتكنيك."
            res = chat.send_message(prompt)
            await query.message.reply_text(res.text)

    elif data == "btn_file":
        history = patient_data.get("history", [])
        if not history:
            await query.message.reply_text("الملف فارغ حتى الآن.")
            return
        
        msg = f"📂 **ملف المريض:** `{patient_id}`\n\n"
        for idx, entry in enumerate(history[-3:], 1):  # عرض آخر 3 جلسات
            msg += f"🔹 **مدخل {idx}:** {entry['user']}\n"
            msg += f"💡 **الرد:** {entry['bot'][:100]}...\n---\n"
        await query.message.reply_text(msg, parse_mode="Markdown")

# ---------------------------------------------------------
# 6. معالجة الرسائل والوسائط النصية
# ---------------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    user_text = update.message.text

    if user_id not in active_patient:
        await update.message.reply_text(
            "⚠️ لم تقم باختيار مريض بعد!\n"
            "يرجى تحديد مريض عبر الأمر: `/new_patient <اسم المريض>`",
            parse_mode="Markdown"
        )
        return

    patient_id = active_patient[user_id]
    chat = user_chats.get(user_id)

    if not chat:
        patient_data = load_patient_data(patient_id)
        gemini_history = []
        for item in patient_data.get("history", []):
            gemini_history.append({"role": "user", "parts": [item["user"]]})
            gemini_history.append({"role": "model", "parts": [item["bot"]]})
        chat = model.start_chat(history=gemini_history)
        user_chats[user_id] = chat

    try:
        response = chat.send_message(user_text)
        
        patient_data = load_patient_data(patient_id)
        patient_data["history"].append({"user": user_text, "bot": response.text})
        save_patient_data(patient_id, patient_data)
        
        await update.message.reply_text(response.text, reply_markup=get_main_keyboard())
    except Exception as e:
        await update.message.reply_text("حدث خطأ أثناء معالجة البيانات.")

# ---------------------------------------------------------
# 7. تشغيل البوت
# ---------------------------------------------------------
if __name__ == '__main__':
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("new_patient", set_patient))
    app.add_handler(CommandHandler("list_patients", list_patients))
    app.add_handler(CommandHandler("menu", menu_command))
    
    app.add_handler(CallbackQueryHandler(button_click_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Physical Therapy Smart Clinic Bot is Running...")
    app.run_polling()
