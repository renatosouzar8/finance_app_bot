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
from telegram.ext import (ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler,
                          filters, CallbackQueryHandler, ConversationHandler)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from keep_alive import keep_alive
from analyst import Sofia, CATEGORY_EMOJI
from firestore_queries import (
    get_monthly_totals_by_category,
    get_user_cards,
    create_card,
    save_income,
    save_expense_with_card,
    save_installment_purchase,
    get_user_categories,
    create_category,
)

# ── Conversation states ────────────────────────────────────────────────────────
ASK_CARD, ASK_WHICH_CARD, ASK_NEW_CARD_NAME, ASK_INSTALLMENT, ASK_NUM_INSTALLMENTS, \
    ASK_CATEGORY, ASK_NEW_CATEGORY_NAME = range(7)
CONV_TIMEOUT = 300  # 5 minutes

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

# Default categories (used by Gemini prompt when user has no custom categories)
CATEGORIES = [
    'Moradia', 'Alimentação', 'Transporte', 'Lazer', 'Saúde',
    'Educação', 'Compras', 'Impostos', 'Serviços', 'Dívidas', 'Outros'
]
INCOME_CATEGORIES = ['Salário', 'Freelance', 'Investimentos', 'Reembolso', 'Outros']

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

async def process_with_gemini(text=None, audio_file=None, user_categories: list = None):
    """
    Uses Gemini to extract expense data or identify query intent.
    Supports Text OR Audio inputs.
    user_categories: optional list of expense categories to use (overrides default CATEGORIES).
    """
    
    current_date = datetime.date.today().isoformat()
    expense_cats = user_categories if user_categories else CATEGORIES
    
    system_prompt = f"""
    You are a strict financial intent classifier for a personal finance bot named Sofia.
    Current Date: {current_date}
    Expense Categories: {', '.join(expense_cats)}
    Income Categories: {', '.join(INCOME_CATEGORIES)}

    Analyze the user's input and return ONLY a valid JSON object. No markdown.

    ### Scenario 1a: Registering an EXPENSE
    User reports spending money ("gastei", "paguei", "comprei", "spent", "paid", "bought", etc.):
    {{"intent": "REGISTER_EXPENSE", "amount": <number>, "category": <expense category or "Outros">, "description": <short text>, "date": <YYYY-MM-DD>}}

    ### Scenario 1b: Registering INCOME
    User reports receiving money ("recebi", "entrou", "salário", "received", "earned", etc.):
    {{"intent": "REGISTER_INCOME", "amount": <number>, "category": <income category or "Outros">, "description": <short text>, "date": <YYYY-MM-DD>}}

    ### Scenario 2: Querying Expenses
    User asks about past or current spending history:
    {{"intent": "QUERY", "category": <category or null>, "start_date": <YYYY-MM-DD>, "end_date": <YYYY-MM-DD>}}

    ### Scenario 3: Monthly Summary
    User asks for monthly overview ("resumo", "como estou", "relatório", "quanto gastei"):
    {{"intent": "SUMMARY_MONTH"}}

    ### Scenario 4: Off-Topic
    Unrelated to personal finance (programming, recipes, sports, weather, etc.):
    {{"intent": "OFFTOPIC"}}

    ### Scenario 5: Dashboard / Visuals
    User asks for charts, graphs, or dashboard:
    {{"intent": "FALLBACK"}}

    Rules:
    - "hoje"/"today": start_date = end_date = {current_date}
    - "ontem"/"yesterday": both = yesterday
    - Prefer QUERY over OFFTOPIC when any financial context exists.
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
    """Saves a plain expense to Firestore (legacy, used by scheduler). Use save_expense_with_card for new flows."""
    return save_expense_with_card(db, APP_ID, user_id, data)

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

def _expense_confirmation(data: dict) -> str:
    """Formats a short confirmation line for an expense."""
    amount = float(data['amount'])
    return f"✅ Entendido: R$ {amount:.2f} em {data['category']} — {data['description']}".replace(".", ",", 1)


async def _handle_classify(update: Update, context: ContextTypes.DEFAULT_TYPE, extracted: dict, firebase_uid: str) -> int:
    """Central dispatcher after Gemini classifies the message. Returns conversation state or ConversationHandler.END."""
    intent = extracted.get("intent")

    if intent == "OFFTOPIC":
        await update.message.reply_text(random.choice(SOFIA_OFFTOPIC_REPLIES))
        return ConversationHandler.END

    if intent == "FALLBACK":
        await update.message.reply_text("📱 Para gráficos e informações detalhadas, acesse o app: https://my-finance-app-24d0f.web.app")
        return ConversationHandler.END

    if intent == "REGISTER_INCOME":
        ok = save_income(db, APP_ID, firebase_uid, extracted)
        if ok:
            amount = float(extracted['amount'])
            await update.message.reply_text(
                f"💰 Receita registrada: R$ {amount:.2f} — {extracted['description']} ({extracted.get('category','Outros')})".replace(".", ",", 1)
            )
        else:
            await update.message.reply_text("❌ Erro ao salvar receita. Tente novamente.")
        return ConversationHandler.END

    if intent == "REGISTER_EXPENSE":
        # Store parsed data and start multi-step conversation
        context.user_data["tx"] = extracted
        context.user_data["firebase_uid"] = firebase_uid
        # Load and cache user categories for this conversation
        user_cats = get_user_categories(db, APP_ID, firebase_uid)
        context.user_data["user_categories"] = user_cats
        keyboard = [
            [InlineKeyboardButton("💳 Sim, foi no cartão", callback_data="card_yes"),
             InlineKeyboardButton("💵 Não, à vista", callback_data="card_no")],
            [InlineKeyboardButton("✏️ Alterar Categoria", callback_data="change_category")],
        ]
        await update.message.reply_text(
            f"{_expense_confirmation(extracted)}\n\n💳 Foi no cartão de crédito?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ASK_CARD

    if intent == "QUERY":
        sofia = Sofia(db, APP_ID, client, firebase_uid)
        msg = await sofia.build_query_response(extracted["start_date"], extracted["end_date"], extracted.get("category"))
        await update.message.reply_text(msg)
        return ConversationHandler.END

    if intent == "SUMMARY_MONTH":
        sofia = Sofia(db, APP_ID, client, firebase_uid)
        msg = await sofia.build_monthly_summary()
        await update.message.reply_text(msg)
        return ConversationHandler.END

    await update.message.reply_text("Não entendi. Tente descrever seu gasto ou digitar 'resumo'.")
    return ConversationHandler.END


# ── Entry points (text and voice) ──────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = str(update.effective_user.id)
    firebase_uid = await get_firebase_user_id(user_id)
    if not firebase_uid:
        await update.message.reply_text("⚠️ Você precisa vincular sua conta primeiro.\nEnvie `/start <SEU_ID>`")
        return ConversationHandler.END
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    user_cats = get_user_categories(db, APP_ID, firebase_uid)
    extracted = await process_with_gemini(text=update.message.text, user_categories=user_cats)
    if not extracted or extracted.get("error"):
        await update.message.reply_text("Desculpe, não entendi. Tente novamente.")
        return ConversationHandler.END
    return await _handle_classify(update, context, extracted, firebase_uid)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = str(update.effective_user.id)
    firebase_uid = await get_firebase_user_id(user_id)
    if not firebase_uid:
        await update.message.reply_text("⚠️ Você precisa vincular sua conta primeiro.")
        return ConversationHandler.END
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    voice_file = await context.bot.get_file(update.message.voice.file_id)
    file_path = f"voice_{user_id}.ogg"
    await voice_file.download_to_drive(file_path)
    user_cats = get_user_categories(db, APP_ID, firebase_uid)
    extracted = await process_with_gemini(audio_file=file_path, user_categories=user_cats)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass
    if not extracted or extracted.get("error"):
        await update.message.reply_text("Desculpe, não entendi o áudio. Tente novamente.")
        return ConversationHandler.END
    return await _handle_classify(update, context, extracted, firebase_uid)


# ── ConversationHandler step callbacks ───────────────────────────────────────────────

async def ask_card_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User chose Yes/No/ChangeCategory for credit card step."""
    query = update.callback_query
    await query.answer()

    if query.data == "change_category":
        # Show category picker
        user_cats = context.user_data.get("user_categories", get_user_categories(db, APP_ID, context.user_data.get("firebase_uid")))
        # Build buttons: 2 per row
        cat_buttons = []
        row = []
        for i, cat in enumerate(user_cats):
            row.append(InlineKeyboardButton(cat, callback_data=f"cat_pick_{cat}"))
            if len(row) == 2:
                cat_buttons.append(row)
                row = []
        if row:
            cat_buttons.append(row)
        cat_buttons.append([InlineKeyboardButton("➕ Nova Categoria", callback_data="cat_new")])
        await query.edit_message_text(
            "🏷️ Escolha a categoria:",
            reply_markup=InlineKeyboardMarkup(cat_buttons)
        )
        return ASK_CATEGORY

    if query.data == "card_no":
        # Save as plain expense
        tx = context.user_data.get("tx", {})
        fuid = context.user_data.get("firebase_uid")
        ok = save_expense_with_card(db, APP_ID, fuid, tx)
        if ok:
            amount = float(tx['amount'])
            msg = f"✅ Salvo: R$ {amount:.2f} em {tx['category']}".replace(".", ",", 1)
            await query.edit_message_text(msg)
            sofia = Sofia(db, APP_ID, client, fuid)
            alert = await sofia.check_after_register(amount, tx['category'])
            if alert:
                await context.bot.send_message(chat_id=query.message.chat_id, text=alert)
        else:
            await query.edit_message_text("❌ Erro ao salvar. Tente novamente.")
        return ConversationHandler.END

    # card_yes — show card list
    fuid = context.user_data.get("firebase_uid")
    cards = get_user_cards(db, APP_ID, fuid)
    context.user_data["cards"] = cards
    buttons = [[InlineKeyboardButton(c["name"], callback_data=f"card_id_{c['id']}")] for c in cards]
    buttons.append([InlineKeyboardButton("➕ Novo cartão", callback_data="card_new")])
    await query.edit_message_text("💳 Qual cartão?", reply_markup=InlineKeyboardMarkup(buttons))
    return ASK_WHICH_CARD


async def ask_which_card_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User selected a card or wants to create a new one."""
    query = update.callback_query
    await query.answer()
    if query.data == "card_new":
        await query.edit_message_text("💳 Qual é o nome do novo cartão? (ex: Nubank, Bradesco, Inter)")
        return ASK_NEW_CARD_NAME
    # Existing card selected
    card_id = query.data.replace("card_id_", "")
    context.user_data["credit_card_id"] = card_id
    cards = context.user_data.get("cards", [])
    card_name = next((c["name"] for c in cards if c["id"] == card_id), card_id)
    keyboard = [
        [InlineKeyboardButton("✅ Sim, parcelado", callback_data="inst_yes"),
         InlineKeyboardButton("💵 Não, à vista", callback_data="inst_no")]
    ]
    await query.edit_message_text(
        f"Cartão: {card_name}\n\n📊 É parcelado?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_INSTALLMENT


async def ask_new_card_name_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User typed the new card name."""
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Por favor, informe o nome do cartão.")
        return ASK_NEW_CARD_NAME
    fuid = context.user_data.get("firebase_uid")
    card_id = create_card(db, APP_ID, fuid, name)
    if not card_id:
        await update.message.reply_text("❌ Erro ao criar cartão. Tente novamente.")
        return ConversationHandler.END
    context.user_data["credit_card_id"] = card_id
    keyboard = [
        [InlineKeyboardButton("✅ Sim, parcelado", callback_data="inst_yes"),
         InlineKeyboardButton("💵 Não, à vista", callback_data="inst_no")]
    ]
    await update.message.reply_text(
        f"Cartão '{name}' criado! ✅\n\n📊 É parcelado?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_INSTALLMENT


async def ask_installment_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User chose Yes/No for installment."""
    query = update.callback_query
    await query.answer()
    tx = context.user_data.get("tx", {})
    fuid = context.user_data.get("firebase_uid")
    card_id = context.user_data.get("credit_card_id")
    if query.data == "inst_no":
        ok = save_expense_with_card(db, APP_ID, fuid, tx, credit_card_id=card_id)
        if ok:
            amount = float(tx['amount'])
            await query.edit_message_text(
                f"✅ Salvo: R$ {amount:.2f} em {tx['category']} (à vista no cartão)".replace(".", ",", 1)
            )
            sofia = Sofia(db, APP_ID, client, fuid)
            alert = await sofia.check_after_register(amount, tx['category'])
            if alert:
                await context.bot.send_message(chat_id=query.message.chat_id, text=alert)
        else:
            await query.edit_message_text("❌ Erro ao salvar. Tente novamente.")
        return ConversationHandler.END
    # inst_yes
    await query.edit_message_text("📅 Quantas parcelas?")
    return ASK_NUM_INSTALLMENTS


async def ask_num_installments_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User typed number of installments."""
    text = update.message.text.strip().replace("x", "").replace("X", "")
    if not text.isdigit() or int(text) < 2:
        await update.message.reply_text("⚠️ Informe um número de parcelas válido (mínimo 2).")
        return ASK_NUM_INSTALLMENTS
    n = int(text)
    tx = context.user_data.get("tx", {})
    fuid = context.user_data.get("firebase_uid")
    card_id = context.user_data.get("credit_card_id")
    ok = save_installment_purchase(db, APP_ID, fuid, tx, n, credit_card_id=card_id)
    if ok:
        total = float(tx['amount'])
        amount_per = total / n
        await update.message.reply_text(
            f"✅ Parcelamento salvo: {tx['description']}\n"
            f"{n}x de R$ {amount_per:.2f} = R$ {total:.2f} total\n"
            f"Categoria: {tx['category']}".replace(".", ",")
        )
        sofia = Sofia(db, APP_ID, client, fuid)
        alert = await sofia.check_after_register(amount_per, tx['category'])
        if alert:
            await update.message.reply_text(alert)
    else:
        await update.message.reply_text("❌ Erro ao salvar parcelamento. Tente novamente.")
    return ConversationHandler.END


async def ask_category_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User picked a category from the list or wants to create a new one."""
    query = update.callback_query
    await query.answer()
    if query.data == "cat_new":
        await query.edit_message_text("🏷️ Como quer chamar a nova categoria? (ex: Pets, Viagens, Academia)")
        return ASK_NEW_CATEGORY_NAME
    # Existing category selected
    cat = query.data.replace("cat_pick_", "")
    tx = context.user_data.get("tx", {})
    tx["category"] = cat
    context.user_data["tx"] = tx
    # Back to card question
    keyboard = [
        [InlineKeyboardButton("💳 Sim, foi no cartão", callback_data="card_yes"),
         InlineKeyboardButton("💵 Não, à vista", callback_data="card_no")],
        [InlineKeyboardButton("✏️ Alterar Categoria", callback_data="change_category")],
    ]
    amount = float(tx['amount'])
    await query.edit_message_text(
        f"✅ Categoria: {cat} | R$ {amount:.2f} — {tx['description']}".replace(".", ",", 1) +
        "\n\n💳 Foi no cartão de crédito?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_CARD


async def ask_new_category_name_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User typed the name for a new custom category."""
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Por favor, informe o nome da categoria.")
        return ASK_NEW_CATEGORY_NAME
    fuid = context.user_data.get("firebase_uid")
    ok = create_category(db, APP_ID, fuid, name)
    if not ok:
        await update.message.reply_text("❌ Erro ao criar categoria. Tente novamente.")
        return ConversationHandler.END
    # Update tx with new category
    tx = context.user_data.get("tx", {})
    tx["category"] = name
    context.user_data["tx"] = tx
    # Update cached category list
    user_cats = context.user_data.get("user_categories", [])
    if name not in user_cats:
        user_cats.append(name)
        context.user_data["user_categories"] = user_cats
    # Back to card question
    keyboard = [
        [InlineKeyboardButton("💳 Sim, foi no cartão", callback_data="card_yes"),
         InlineKeyboardButton("💵 Não, à vista", callback_data="card_no")],
        [InlineKeyboardButton("✏️ Alterar Categoria", callback_data="change_category")],
    ]
    amount = float(tx['amount'])
    await update.message.reply_text(
        f"✅ Categoria '{name}' criada!\n"
        f"R$ {amount:.2f} — {tx['description']}".replace(".", ",", 1) +
        "\n\n💳 Foi no cartão de crédito?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_CARD


async def conv_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Called when conversation times out."""
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "⏰ Tempo esgotado! O cadastro foi cancelado.\nSe quiser, comece novamente descrevendo o gasto."
        )
    return ConversationHandler.END


async def conv_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Cadastro cancelado.")
    return ConversationHandler.END

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
    
    # ── Conversation handler for expense registration ──
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
            MessageHandler(filters.VOICE, handle_voice),
        ],
        states={
            ASK_CARD: [
                CallbackQueryHandler(ask_card_cb, pattern="^(card_yes|card_no|change_category)$"),
            ],
            ASK_WHICH_CARD: [
                CallbackQueryHandler(ask_which_card_cb, pattern="^(card_id_.+|card_new)$"),
            ],
            ASK_NEW_CARD_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_new_card_name_cb),
            ],
            ASK_INSTALLMENT: [
                CallbackQueryHandler(ask_installment_cb, pattern="^inst_(yes|no)$"),
            ],
            ASK_NUM_INSTALLMENTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_num_installments_cb),
            ],
            ASK_CATEGORY: [
                CallbackQueryHandler(ask_category_cb, pattern="^(cat_pick_.+|cat_new)$"),
            ],
            ASK_NEW_CATEGORY_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_new_category_name_cb),
            ],
            ConversationHandler.TIMEOUT: [MessageHandler(filters.ALL, conv_timeout)],
        },
        fallbacks=[CommandHandler('cancel', conv_cancel)],
        conversation_timeout=CONV_TIMEOUT,
        per_message=False,
    )

    application.add_handler(CommandHandler('start', start))
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)
    
    
    scheduler = setup_scheduler(application)
    scheduler.start()

    print(f"Bot Version: 2.4 (income + card + installments + custom categories)")
    print(f"Bot is running in MULTI-USER mode (APP_ID: {APP_ID})...")
    keep_alive()
    application.run_polling()
