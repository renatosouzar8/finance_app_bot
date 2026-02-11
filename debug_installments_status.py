
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

def debug_installments():
    installments_ref = db.collection(f"artifacts/{APP_ID}/users/{FIREBASE_USER_ID}/installments")
    payments_ref = db.collection(f"artifacts/{APP_ID}/users/{FIREBASE_USER_ID}/installment_payments")
    
    inst_docs = list(installments_ref.stream())
    pay_docs = list(payments_ref.stream())
    
    print(f"Total Installments (Parents): {len(inst_docs)}")
    print(f"Total Payments (Children): {len(pay_docs)}")
    
    for inst in inst_docs:
        d = inst.to_dict()
        iid = inst.id
        total = d.get('numberOfInstallments', 0)
        desc = d.get('description', 'No Desc')
        
        # Count paid payments
        my_payments = [p for p in pay_docs if p.to_dict().get('installmentId') == iid]
        paid_count = len([p for p in my_payments if p.to_dict().get('isPaid')])
        
        is_finished = total > 0 and paid_count >= total
        
        print(f"ID: {iid} | Desc: {desc} | Paid: {paid_count}/{total} | Finished: {is_finished}")

if __name__ == "__main__":
    debug_installments()
