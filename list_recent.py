
import firebase_admin
from firebase_admin import credentials, firestore
import os
from dotenv import load_dotenv

load_dotenv()

if not firebase_admin._apps:
    cred = credentials.Certificate(os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH"))
    firebase_admin.initialize_app(cred)

db = firestore.client()

APP_ID = "default-app-id"
FIREBASE_USER_ID = os.getenv("FIREBASE_USER_ID")

def list_recent():
    transactions_ref = db.collection(f"artifacts/{APP_ID}/users/{FIREBASE_USER_ID}/transactions")
    # Get last 20
    docs = transactions_ref.order_by("createdAt", direction=firestore.Query.DESCENDING).limit(20).stream()
    
    print("Recent Transactions:")
    for doc in docs:
        d = doc.to_dict()
        desc = d.get('description', 'No Desc')
        amt = d.get('amount', 0)
        date = d.get('date')
        print(f"ID: {doc.id} | Desc: {desc} | Amt: {amt} | Date: {date}")

if __name__ == "__main__":
    list_recent()
