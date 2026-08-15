import os
import nest_asyncio
from google import genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

nest_asyncio.apply()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)
user_histories = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []
    await update.message.reply_text("أهلاً بك! أنا جاهز ومتاح على مدار 24 ساعة للإجابة على استفسارات العلاج الطبيعي والتأهيل.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text
    
    if user_id not in user_histories:
        user_histories[user_id] = []
    
    prompt = "أنت مساعد ذكي ومتخصص في العلاج الطبيعي والتأهيل. تتعلم وتتأقلم بناءً على ما يطلبه المستخدم.\n"
    for msg in user_histories[user_id]:
        prompt += f"\nالمستخدم: {msg['user']}\nالمساعد: {msg['bot']}"
    prompt += f"\nالمستخدم: {user_text}\nالمساعد:"

    try:
        interaction = client.interactions.create(
            model="gemini-3.6-flash",
            input=prompt
        )
        reply = interaction.output_text
        user_histories[user_id].append({"user": user_text, "bot": reply})
    except Exception as e:
        reply = f"حدث خطأ أثناء التواصل مع السيرفر: {e}"
        
    await update.message.reply_text(reply)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("البوت يعمل الآن على خادم Render...")
    app.run_polling()
