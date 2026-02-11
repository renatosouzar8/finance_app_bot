
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from dotenv import load_dotenv
import os
import datetime

load_dotenv(dotenv_path='bot/.env')

# Hardcoded for verification
cred = credentials.Certificate("my-finance-app.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

APP_ID = "default-app-id"
FIREBASE_USER_ID = "o6ne3LYVAxbb3jWJ2klqwAjfFxH2"

# Simulate "Today" query
today = datetime.date.today()
start_dt = datetime.datetime.combine(today, datetime.time.min)
end_dt = datetime.datetime.combine(today, datetime.time.max)

print(f"Simulating query for date range: {start_dt} to {end_dt}")

try:
    path = f"artifacts/{APP_ID}/users/{FIREBASE_USER_ID}/transactions"
    query_ref = db.collection(path)
    
    # The failing query structure (Date + Type + Category)
    query_ref = query_ref.where('date', '>=', start_dt).where('date', '<=', end_dt)
    query_ref = query_ref.where('type', '==', 'expense')
    query_ref = query_ref.where('category', '==', 'Alimentação') # Using a likely category
    
    docs = query_ref.stream()
    
    count = 0
    for doc in docs:
        d = doc.to_dict()
        print(f"Result: {doc.id} | Desc: {d.get('description')} | Date: {d.get('date')} | Created: {d.get('createdAt')}")
        count += 1
    print(f"Query successful. Found {count} docs.")

except Exception as e:
    print("\n!!! QUERY FAILED !!!")
    print(f"Error: {e}")

