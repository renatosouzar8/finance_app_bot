import os
import datetime
import logging
import json
import random
from dotenv import load_dotenv

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from google import genai
from google.genai import types
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from keep_alive import keep_alive
from analyst import Sofia, CATEGORY_EMOJI
from firestore_queries import get_monthly_totals_by_category

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
FIREBASE_SERVICE_ACCOUNT = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
# FIREBASE_USER_ID is no longer used globally in multi-user mode
# Handle empty string from env
APP_ID = os.getenv("APP_ID")
if not APP_ID:
    APP_ID = "default-app-id"

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Firebase Setup
if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
    firebase_admin.initialize_app(cred)

db = firestore.client()

logger = logging.getLogger(__name__)

# Gemini Setup
client = genai.Client(api_key=GEMINI_API_KEY)

# Categories (matching frontend)
CATEGORIES = [
    'Moradia', 'Alimentação', 'Transporte', 'Lazer', 'Saúde', 
    'Educação', 'Compras', 'Impostos', 'Serviços', 'Dívidas', 'Outros'
]

# Sofia off-topic replies (humorous, in character)
SOFIA_OFFTOPIC_REPLIES = [
    "😄 Adoro o entusiasmo! Mas minha especialidade é só dinheiro — receita de bolo fica pra outra conta! Posso te ajudar com seus gastos?",
    "🤭 Boa tentativa! Sou a Sofia, analista financeira. Código de programação e receitas de comida ficam fora do meu extrato. Fala de finanças?",
    "💸 Isso está bem fora do meu orçamento de conhecimento! Só processo números financeiros por aqui. Quer ver como estão seus gastos?",
    "😂 Interessante! Mas se não envolve R$, não é comigo. Sou especialista em controle de gastos, não em gastronomia (nem em programação). O que você gastou hoje?",
    "🙈 Sou uma analista financeira muito focada — só falo de dinheiro, orçamento e gastos. Pra tudo mais, existe o Google! 😄 Posso te ajudar com suas finanças?",
    "🏦 Hmm, isso foge das minhas atribuições! Minha mesa só tem planilhas financeiras. Quer registrar um gasto ou ver um resumo do mês?",
]

async def get_all_mapped_users() -> list[dict]:
    """Returns all {telegram_id, firebase_uid} pairs for proactive messages."""
    try:
        docs = db.collection(f"artifacts/{APP_ID}/user_mappings").stream()
        return [
            {
                "telegram_id": d.to_dict().get("telegramId"),
                "firebase_uid": d.to_dict().get("firebaseUserId"),
            }
            for d in docs
        ]
    except Exception as e:
        logger.error(f"get_all_mapped_users error: {e}")
        return []


async def get_firebase_user_id(telegram_id):
    """Downloads the mapping from Firestore."""
    try:
        doc_ref = db.collection(f"artifacts/{APP_ID}/user_mappings").document(str(telegram_id))
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict().get("firebaseUserId")
        return None
    except Exception as e:
        logging.error(f"Mapping Error: {e}")
        return None

async def save_user_mapping(telegram_id, firebase_user_id):
    """Saves the mapping to Firestore."""
    try:
        doc_ref = db.collection(f"artifacts/{APP_ID}/user_mappings").document(str(telegram_id))
        doc_ref.set({
            "telegramId": telegram_id,
            "firebaseUserId": firebase_user_id,
            "linkedAt": firestore.SERVER_TIMESTAMP
        })
        return True, ""
    except Exception as e:
        logging.error(f"Save Mapping Error: {e}")
        return False, str(e)

async def process_with_gemini(text=None, audio_file=None):
    """
    Uses Gemini to extract expense data or identify query intent.
    Supports Text OR Audio inputs.
    """
    
    current_date = datetime.date.today().isoformat()
    
    system_prompt = f"""
    You are a strict financial intent classifier for a personal finance bot named Sofia.
    Current Date: {current_date}
    Available Expense Categories: {', '.join(CATEGORIES)}

    Analyze the user's input (Text or Audio) and classify the intent.
    Return ONLY a valid JSON object. Do NOT wrap in markdown code blocks.

    ### Scenario 1: Registering an Expense
    If the user is reporting spending money ("gastei", "paguei", "comprei", "spent", "paid", "bought", etc.) return:
    {{"intent": "REGISTER", "amount": <number>, "category": <exact category from list or "Outros">, "description": <short text>, "date": <YYYY-MM-DD>}}

    ### Scenario 2: Querying Expenses
    If the user asks about their past or current spending history, return:
    {{"intent": "QUERY", "category": <category name or null>, "start_date": <YYYY-MM-DD>, "end_date": <YYYY-MM-DD>}}

    ### Scenario 3: Monthly Summary
    If the user asks for a monthly overview ("resumo", "como estou", "relatório", "quanto gastei esse mês", "situação"), return:
    {{"intent": "SUMMARY_MONTH"}}

    ### Scenario 4: Off-Topic (NOT related to personal finance at all)
    If the user asks about programming, recipes, jokes, sports, general knowledge, weather, homework,
    or ANYTHING that has absolutely no relation to personal finance, spending, or budget, return:
    {{"intent": "OFFTOPIC"}}

    ### Scenario 5: Dashboard / Visuals
    If the user asks for charts, graphs, or things better seen in the app dashboard, return:
    {{"intent": "FALLBACK"}}

    Rules:
    - For "hoje" / "today": start_date and end_date = {current_date}
    - For "ontem" / "yesterday": both = yesterday's date
    - When in doubt between QUERY and OFFTOPIC, prefer QUERY if there is ANY financial context.
    - When in doubt between OFFTOPIC and FALLBACK, use OFFTOPIC for clearly non-financial content.
    """
    
    try:
        content_parts = [system_prompt]
        
        if text:
            content_parts.append(f"User Message: {text}")
        
        if audio_file:
            # Upload file using the new SDK
            with open(audio_file, "rb") as f:
                uploaded_file = client.files.upload(file=f, config={'mime_type': 'audio/ogg'})
            content_parts.append(uploaded_file)
            logging.info(f"Uploaded audio file: {uploaded_file.name}")

        response = client.models.generate_content(
            model='gemini-flash-latest',
            contents=content_parts
        )
        if not response or not response.text:
            return {"error": "Sem resposta do Gemini"}
        text_response = response.text.strip()
        
        if text_response.startswith('```json'):
            text_response = text_response[7:-3]
        elif text_response.startswith('```'):
            text_response = text_response[3:-3]
            
        print(f"DEBUG: Gemini Response: {text_response}") 
        return json.loads(text_response)
    
    except Exception as e:
        logging.error(f"Gemini Error: {e}")
        return {"error": str(e)}

async def save_expense(data, user_id):
    """Saves the expense to Firestore for a specific user."""
    print(f"DEBUG: Entering save_expense for user {user_id}")
    try:
        transaction_data = {
            "description": data["description"],
            "amount": float(data["amount"]),
            "category": data["category"],
            "type": "expense",
            # Fix Timezone: Set to Noon (12:00)
            "date": datetime.datetime.fromisoformat(data["date"]).replace(hour=12, minute=0, second=0),
            "createdAt": firestore.SERVER_TIMESTAMP,
            "userId": user_id,
            "isInstallmentOriginal": False
        }
        
        collection_path = f"artifacts/{APP_ID}/users/{user_id}/transactions"
        print(f"DEBUG: Saving to {collection_path}")
        db.collection(collection_path).add(transaction_data)
        print("DEBUG: Firestore save successful")
        return True
    except Exception as e:
        logging.error(f"Firestore Save Error: {e}")
        return False

async def query_expenses(filters, user_id):
    """Queries Firestore for a specific user."""
    try:
        collection_path = f"artifacts/{APP_ID}/users/{user_id}/transactions"
        query_ref = db.collection(collection_path)
        
        # Date Filter
        start_dt = datetime.datetime.fromisoformat(filters['start_date'])
        end_dt = datetime.datetime.fromisoformat(filters['end_date']) + datetime.timedelta(days=1) - datetime.timedelta(seconds=1)
        
        query_ref = query_ref.where('date', '>=', start_dt).where('date', '<=', end_dt)
        query_ref = query_ref.where('type', '==', 'expense')
        
        # Category Filter
        if filters.get('category'):
            query_ref = query_ref.where('category', '==', filters['category'])
            
        docs = query_ref.stream()
        
        total = 0.0
        count = 0
        
        for doc in docs:
            data = doc.to_dict()
            total += data.get('amount', 0)
            count += 1
            
        return total, count
    except Exception as e:
        logging.error(f"Firestore Query Error: {e}")
        return None, 0

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    args = context.args
    
    if args and len(args) > 0:
        firebase_uid = args[0]
        success, error_msg = await save_user_mapping(user_id, firebase_uid)
        if success:
            await update.message.reply_text(f"🔐 Conta vinculada com sucesso!\nID: {firebase_uid}\n\nAgora você pode registrar gastos por texto ou áudio.")
        else:
            await update.message.reply_text(f"❌ Falha ao vincular conta.\nErro: {error_msg}")
    else:
        # Check if already linked
        existing_uid = await get_firebase_user_id(user_id)
        if existing_uid:
             await update.message.reply_text(f"👋 Você já está conectado (ID: ...{existing_uid[-5:]}).\nPode enviar seus gastos!")
        else:
            await update.message.reply_text(
                "Olá! Para usar o bot, você precisa vincular sua conta.\n\n"
                "1. Abra o App Web\n"
                "2. Clique no ícone do Telegram (canto superior)\n"
                "3. Siga as instruções para copiar seu código.\n\n"
                "Ou envie: `/start <SEU_ID_DO_FIREBASE>`",
                parse_mode='Markdown'
            )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    firebase_uid = await get_firebase_user_id(user_id)
    
    if not firebase_uid:
        await update.message.reply_text("⚠️ Você precisa vincular sua conta primeiro.\nEnvie `/start <SEU_ID>`")
        return

    user_text = update.message.text
    print(f"DEBUG: Processing for user {user_id} -> {firebase_uid}")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    
    extracted = await process_with_gemini(text=user_text)
    await respond_to_user(update, context, extracted, firebase_uid)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    firebase_uid = await get_firebase_user_id(user_id)
    
    if not firebase_uid:
        await update.message.reply_text("⚠️ Você precisa vincular sua conta primeiro.")
        return

    print("DEBUG: Received voice message")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    
    voice_file = await context.bot.get_file(update.message.voice.file_id)
    file_path = f"voice_{user_id}.ogg" # Unique filename
    await voice_file.download_to_drive(file_path)
    
    extracted = await process_with_gemini(audio_file=file_path)

    # Respond first to ensure user gets feedback
    await respond_to_user(update, context, extracted, firebase_uid)
    
    # Cleanup afterwards
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"DEBUG: Deleted {file_path}")
    except Exception as e:
        logging.warning(f"Failed to delete temp file {file_path}: {e}")

async def respond_to_user(update, context, extracted, firebase_uid):
    if not extracted:
        await update.message.reply_text("Desculpe, não entendi. Tente de novo.")
        return

    if extracted.get("error"):
        await update.message.reply_text(f"❌ Erro no Gemini: {extracted['error']}")
        return

    intent = extracted.get("intent")

    if intent == "OFFTOPIC":
        reply = random.choice(SOFIA_OFFTOPIC_REPLIES)
        await update.message.reply_text(reply)
        return

    if intent == "FALLBACK":
        await update.message.reply_text(
            "📱 Para gráficos e informações detalhadas, acesse o app completo: https://my-finance-app-24d0f.web.app"
        )
        return

    if intent == "REGISTER":
        success = await save_expense(extracted, firebase_uid)
        if not success:
            await update.message.reply_text("❌ Erro ao salvar no banco de dados.")
            return

        amount = float(extracted["amount"])
        category = extracted["category"]
        formatted_amount = f"{amount:.2f}".replace(".", ",")
        await update.message.reply_text(
            f"✅ Registrado: R$ {formatted_amount} em {category} ({extracted['description']})."
        )

        sofia = Sofia(db, APP_ID, client, firebase_uid)
        alert = await sofia.check_after_register(amount, category)
        if alert:
            await update.message.reply_text(alert)
        return

    if intent == "QUERY":
        sofia = Sofia(db, APP_ID, client, firebase_uid)
        msg = await sofia.build_query_response(
            extracted["start_date"],
            extracted["end_date"],
            extracted.get("category"),
        )
        await update.message.reply_text(msg)
        return

    if intent == "SUMMARY_MONTH":
        sofia = Sofia(db, APP_ID, client, firebase_uid)
        msg = await sofia.build_monthly_summary()
        await update.message.reply_text(msg)
        return

    await update.message.reply_text("Não entendi se é para registrar ou consultar. Tente ser mais claro.")

# ── Proactive scheduler ───────────────────────────────────────────────────────

async def job_weekly_summary(bot):
    users = await get_all_mapped_users()
    for user in users:
        try:
            tid, fuid = user["telegram_id"], user["firebase_uid"]
            if not tid or not fuid:
                continue
            sofia = Sofia(db, APP_ID, client, fuid)
            if not sofia._can_send_proactive():
                continue
            msg = await sofia.build_weekly_summary()
            await bot.send_message(chat_id=tid, text=msg)
            sofia._mark_proactive_sent()
        except Exception as e:
            logger.error(f"Weekly summary error for {user}: {e}")


async def job_monthly_closure(bot):
    import calendar
    users = await get_all_mapped_users()
    for user in users:
        try:
            tid, fuid = user["telegram_id"], user["firebase_uid"]
            if not tid or not fuid:
                continue
            sofia = Sofia(db, APP_ID, client, fuid)
            if not sofia._can_send_proactive():
                continue
            today = datetime.date.today()
            prev_month = today.month - 1 if today.month > 1 else 12
            prev_year = today.year if today.month > 1 else today.year - 1
            totals = get_monthly_totals_by_category(db, APP_ID, fuid, prev_year, prev_month)
            total = sum(totals.values())
            month_name = calendar.month_name[prev_month]
            lines = [
                f"{CATEGORY_EMOJI.get(cat, '•')} {cat}: R${val:.2f}".replace(".", ",")
                for cat, val in sorted(totals.items(), key=lambda x: -x[1])
            ]
            breakdown = "\n".join(lines) or "Nenhum gasto registrado."
            msg = (
                f"📊 Fechamento de {month_name}\n\n{breakdown}\n\n──────\n"
                f"Total: R${total:.2f}".replace(".", ",") +
                "\n\nQuer revisar metas para este mês?"
            )
            await bot.send_message(chat_id=tid, text=msg)
            sofia._mark_proactive_sent()
        except Exception as e:
            logger.error(f"Monthly closure error for {user}: {e}")


async def job_biweekly_checkin(bot):
    import calendar
    users = await get_all_mapped_users()
    for user in users:
        try:
            tid, fuid = user["telegram_id"], user["firebase_uid"]
            if not tid or not fuid:
                continue
            sofia = Sofia(db, APP_ID, client, fuid)
            if not sofia._can_send_proactive():
                continue
            today = datetime.date.today()
            month_name = calendar.month_name[today.month]
            summary = await sofia.build_monthly_summary()
            await bot.send_message(chat_id=tid, text=f"📍 Metade de {month_name}.\n\n{summary}")
            sofia._mark_proactive_sent()
        except Exception as e:
            logger.error(f"Biweekly check-in error for {user}: {e}")


def setup_scheduler(app) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(
        job_weekly_summary,
        trigger=CronTrigger(day_of_week="sun", hour=20, minute=0, timezone="America/Sao_Paulo"),
        args=[app.bot], id="weekly_summary", replace_existing=True,
    )
    scheduler.add_job(
        job_monthly_closure,
        trigger=CronTrigger(day=1, hour=9, minute=0, timezone="America/Sao_Paulo"),
        args=[app.bot], id="monthly_closure", replace_existing=True,
    )
    scheduler.add_job(
        job_biweekly_checkin,
        trigger=CronTrigger(day=15, hour=9, minute=0, timezone="America/Sao_Paulo"),
        args=[app.bot], id="biweekly_checkin", replace_existing=True,
    )
    return scheduler


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error(msg="Exception while handling an update:", exc_info=context.error)

if __name__ == '__main__':
    if not TELEGRAM_TOKEN:
        print("Telegram Token not found!")
        exit(1)
        
    application = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .build()
    )
    
    # Handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_error_handler(error_handler)
    
    
    scheduler = setup_scheduler(application)
    scheduler.start()

    print(f"Bot Version: 2.2 (Sofia dynamic budget)")
    print(f"Bot is running in MULTI-USER mode (APP_ID: {APP_ID})...")
    keep_alive()
    application.run_polling()
