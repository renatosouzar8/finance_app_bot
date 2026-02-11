
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

def clean_installments():
    # Note: Installments path is different from transactions
    installments_ref = db.collection(f"artifacts/{APP_ID}/users/{FIREBASE_USER_ID}/installments")
    docs = installments_ref.stream()
    
    found_count = 0
    for doc in docs:
        data = doc.to_dict()
        desc = data.get('description', '').lower()
        if 'troca' in desc: # Broad search
            print(f"FOUND INSTALLMENT: ID: {doc.id} | Desc: {data.get('description')}")
            # Delete immediately as per request
            installments_ref.document(doc.id).delete()
            print("Deleted.")
            found_count += 1
            
    if found_count == 0:
        print("No installments found with 'troca'.")

if __name__ == "__main__":
    clean_installments()
