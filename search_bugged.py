
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

def search_bugged():
    transactions_ref = db.collection(f"artifacts/{APP_ID}/users/{FIREBASE_USER_ID}/transactions")
    # Search for descriptions starting with 'Troca' or 'troca'
    # Firestore filtering is case sensitive.
    
    docs = transactions_ref.where('description', '>=', 'Troca').where('description', '<=', 'Troca\uf8ff').stream()
    found = False
    for doc in docs:
        found = True
        print(f"FOUND: ID: {doc.id} | Desc: {doc.to_dict().get('description')}")
        # Uncomment to delete
        # transactions_ref.document(doc.id).delete()
        # print("Deleted.")

    docs_lower = transactions_ref.where('description', '>=', 'troca').where('description', '<=', 'troca\uf8ff').stream()
    for doc in docs_lower:
        found = True
        print(f"FOUND LOWER: ID: {doc.id} | Desc: {doc.to_dict().get('description')}")
        # Uncomment to delete
        # transactions_ref.document(doc.id).delete()
        # print("Deleted.")
    
    if not found:
        print("No 'Troca' or 'troca' found.")

if __name__ == "__main__":
    search_bugged()
