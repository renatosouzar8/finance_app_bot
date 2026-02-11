import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from dotenv import load_dotenv
import os
import datetime

load_dotenv()

# Check credentials file
if not os.path.exists("my-finance-app.json"):
    print("FATAL: my-finance-app.json not found in current directory.")
    exit(1)

try:
    cred = credentials.Certificate("my-finance-app.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("Firebase initialized.")
except Exception as e:
    print(f"FATAL: Failed to initialize Firebase: {e}")
    exit(1)

APP_ID = os.getenv("APP_ID", "default-app-id")
print(f"Using APP_ID: {APP_ID}")

# Test Write to user_mappings
try:
    print("\n--- Testing Write Permission ---")
    test_id = "VERIFY_SCRIPT_TEST"
    doc_ref = db.collection(f"artifacts/{APP_ID}/user_mappings").document(test_id)
    doc_ref.set({
        "telegramId": test_id,
        "firebaseUserId": "test_uid",
        "linkedAt": firestore.SERVER_TIMESTAMP,
        "test": True
    })
    print("✅ Write to user_mappings successful!")
    
    # Clean up
    doc_ref.delete()
    print("✅ Clean up successful!")
    
except Exception as e:
    print(f"\n❌ WRITE FAILED: {e}")
