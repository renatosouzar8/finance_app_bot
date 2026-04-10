import os
import datetime
import logging
import json
import asyncio
from dotenv import load_dotenv

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from google import genai
from google.genai import types
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from keep_alive import keep_alive

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

# Gemini Setup
client = genai.Client(api_key=GEMINI_API_KEY)

# Categories (matching frontend)
CATEGORIES = [
    'Moradia', 'Alimentação', 'Transporte', 'Lazer', 'Saúde', 
    'Educação', 'Compras', 'Impostos', 'Serviços', 'Dívidas', 'Outros'
]

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
    You are a financial assistant. 
    Current Date: {current_date}
    Available Categories: {', '.join(CATEGORIES)}

    Analyze the user's input (Text or Audio).
    
    Determine if the user is REGISTERING an expense or QUERYING expenses.

    Format your response as a JSON object.

    ### Scenario 1: Registering an Expense
    If the user matches "spent", "paid", "bought" etc. return:
    {{
        "intent": "REGISTER",
        "amount": <number>,
        "category": <exact category from list or "Outros">,
        "description": <short text description>,
        "date": <ISO date string YYYY-MM-DD>
    }}
    
    ### Scenario 2: Querying Expenses
    If the user asks about spending history, return:
    {{
        "intent": "QUERY",
        "category": <specific category name OR null if all>,
        "start_date": <ISO date string YYYY-MM-DD>,
        "end_date": <ISO date string YYYY-MM-DD>
    }}
    
    ### Scenario 3: Fallback / More Details
    If the user asks something unrelated to finance, OR asks for complex charts/visuals, OR wants to see the dashboard, return:
    {{
        "intent": "FALLBACK"
    }}
    
    For "today", start/end = {current_date}.
    For "yesterday", both = yesterday's date.
    
    Do not wrap the JSON in markdown code blocks. Just valid JSON.
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
    await respond_to_user(update, extracted, firebase_uid)

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
    await respond_to_user(update, extracted, firebase_uid)
    
    # Cleanup afterwards
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"DEBUG: Deleted {file_path}")
    except Exception as e:
        logging.warning(f"Failed to delete temp file {file_path}: {e}")

async def respond_to_user(update, extracted, firebase_uid):
    if not extracted:
        await update.message.reply_text("Desculpe, não entendi. Tente de novo.")
        return

    if extracted.get("error"):
        await update.message.reply_text(f"❌ Erro no Gemini: {extracted['error']}")
        return

    # Check for FALLBACK intent
    if extracted.get('intent') == 'FALLBACK':
        await update.message.reply_text("📱 Para estas informações e muito mais, acesse o app completo: https://my-finance-app-24d0f.web.app")
        return

    if extracted.get('intent') == 'REGISTER':
        print("DEBUG: Processing REGISTER intent")
        success = await save_expense(extracted, firebase_uid)
        print(f"DEBUG: save_expense returned {success}")
        if success:
            formatted_amount = f"{extracted['amount']:.2f}".replace('.', ',')
            msg = f"✅ Registrado: R$ {formatted_amount} em {extracted['category']} ({extracted['description']})."
        else:
            msg = "❌ Erro ao salvar no banco de dados."
        await update.message.reply_text(msg)
        
    elif extracted.get('intent') == 'QUERY':
        total, count = await query_expenses(extracted, firebase_uid)
        if total is not None:
            cat_text = f" em {extracted['category']}" if extracted.get('category') else ""
            
            # Date Formatting Logic
            start = extracted['start_date']
            end = extracted['end_date']
            today = datetime.date.today().isoformat()
            yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
            
            if start == end:
                if start == today:
                    date_text = "hoje"
                elif start == yesterday:
                    date_text = "ontem"
                else:
                    # Format YYYY-MM-DD to DD/MM
                    d_obj = datetime.datetime.strptime(start, "%Y-%m-%d")
                    date_text = f"em {d_obj.strftime('%d/%m')}"
            else:
                s_obj = datetime.datetime.strptime(start, "%Y-%m-%d")
                e_obj = datetime.datetime.strptime(end, "%Y-%m-%d")
                date_text = f"de {s_obj.strftime('%d/%m')} até {e_obj.strftime('%d/%m')}"

            formatted_total = f"{total:.2f}".replace('.', ',')
            
            response_msg = (
                f"📊 Total gasto{cat_text} {date_text}: R$ {formatted_total} ({count} transações).\n\n"
                f"📱 Para ver detalhes das transações, acesse o app: https://my-finance-app-24d0f.web.app"
            )
            await update.message.reply_text(response_msg)
        else:
            await update.message.reply_text("❌ Erro ao consultar gastos.")
    
    else:
        await update.message.reply_text("Não entendi se é para registrar ou consultar. Tente ser mais claro.")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles interactions with inline buttons."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = str(update.effective_user.id)
    firebase_uid = await get_firebase_user_id(user_id)
    
    if not firebase_uid:
        await query.edit_message_text("⚠️ Conta não vinculada.")
        return

    if data.startswith("confirm_tx:"):
        tx_id = data.split(":")[1]
        try:
            tx_ref = db.collection(f"artifacts/{APP_ID}/users/{firebase_uid}/transactions").document(tx_id)
            doc = tx_ref.get()
            
            if not doc.exists:
                await query.edit_message_text("❌ Transação não encontrada.")
                return
            
            await tx_ref.update({
                "sync_status": "confirmed",
                "updatedAt": firestore.SERVER_TIMESTAMP
            })
            
            await query.edit_message_text(f"✅ Transação confirmada com sucesso! \n({doc.to_dict().get('description')})")
            
        except Exception as e:
            logging.error(f"Error confirming transaction: {e}")
            await query.edit_message_text(f"❌ Erro ao confirmar: {str(e)}")

    elif data.startswith("edit_tx:"):
        await query.edit_message_text("✏️ Para editar, acesse o app web: https://my-finance-app-24d0f.web.app")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logging.error(msg="Exception while handling an update:", exc_info=context.error)

async def setup_notification_listener(application, loop):
    """Listens for new notifications in the Firestore queue."""
    logging.info("Starting Firestore notification listener...")
    
    def on_snapshot(col_snapshot, changes, read_time):
        for change in changes:
            if change.type.name == 'ADDED':
                doc = change.document
                data = doc.to_dict()
                
                if data.get("status") == "pending":
                    # Submete a corotina para o loop principal do Telegram
                    asyncio.run_coroutine_threadsafe(
                        send_notification(application, doc.id, data),
                        loop
                    )

    col_query = db.collection(f"artifacts/{APP_ID}/notification_queue").where("status", "==", "pending")
    col_query.on_snapshot(on_snapshot)

async def send_notification(application, doc_id, data):
    """Sends the actual telegram message and marks as sent."""
    telegram_id = data.get("telegramId")
    tx = data.get("transaction")
    firebase_uid = data.get("firebaseUserId")
    
    if not telegram_id or not tx:
        return

    message = (
        f"📌 *Nova Transação (Open Finance)*\n\n"
        f"💰 *Valor:* R$ {abs(tx['amount']):.2f}\n"
        f"📝 *Descrição:* {tx['description']}\n"
        f"📂 *Categoria:* {tx.get('category', 'Open Finance')}\n\n"
        f"Deseja confirmar este lançamento?"
    )
    
    # Check if transaction exists to link it correctly
    # Note: We need the doc ID in our system, not the external Pluggy ID
    # But for now we can search for it
    tx_query = db.collection(f"artifacts/{APP_ID}/users/{firebase_uid}/transactions")\
                 .where("external_id", "==", tx['id']).limit(1).get()
    
    reply_markup = None
    if tx_query:
        internal_id = tx_query[0].id
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_tx:{internal_id}"),
                InlineKeyboardButton("✏️ Editar", callback_data=f"edit_tx:{internal_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await application.bot.send_message(
            chat_id=telegram_id,
            text=message,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        # Mark as sent
        db.collection(f"artifacts/{APP_ID}/notification_queue").document(doc_id).update({
            "status": "sent",
            "sentAt": firestore.SERVER_TIMESTAMP
        })
        logging.info(f"Notification sent to {telegram_id} for tx {tx['id']}")
        
    except Exception as e:
        logging.error(f"Error sending notification: {e}")

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
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_error_handler(error_handler)
    
    # Start Firestore Listener in background
    loop = asyncio.get_event_loop()
    loop.create_task(setup_notification_listener(application, loop))
    
    print(f"Bot is running in MULTI-USER mode (APP_ID: {APP_ID})...")
    keep_alive()
    application.run_polling()
