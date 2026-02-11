
import firebase_admin
from firebase_admin import credentials, firestore
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate(os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH"))
    firebase_admin.initialize_app(cred)

db = firestore.client()

APP_ID = "default-app-id"
FIREBASE_USER_ID = os.getenv("FIREBASE_USER_ID")

def delete_bugged():
    transactions_ref = db.collection(f"artifacts/{APP_ID}/users/{FIREBASE_USER_ID}/transactions")
    
    # Query for "troca de óleo" (case insensitive approach might be needed, but let's try exact first)
    # Firestore doesn't support generic case-insensitive search easily without external tools, 
    # so we'll fetch all and filter or try likely cases.
    
    # Ideally, we fetch all descriptions match 'troca'
    docs = transactions_ref.stream()
    
    count = 0
    for doc in docs:
        data = doc.to_dict()
        desc = data.get('description', '').lower()
        if 'troca de óleo' in desc or 'troca de oleo' in desc:
            print(f"Deleting {doc.id}: {data.get('description')} - {data.get('amount')}")
            transactions_ref.document(doc.id).delete()
            count += 1
            
    print(f"Deleted {count} records.")

if __name__ == "__main__":
    delete_bugged()
