import datetime
import logging
from firebase_admin import firestore

logger = logging.getLogger(__name__)


def get_month_range(year: int, month: int):
    """Returns (start_dt, end_dt) for the given month."""
    start_dt = datetime.datetime(year, month, 1, 0, 0, 0)
    if month == 12:
        end_dt = datetime.datetime(year + 1, 1, 1, 0, 0, 0) - datetime.timedelta(seconds=1)
    else:
        end_dt = datetime.datetime(year, month + 1, 1, 0, 0, 0) - datetime.timedelta(seconds=1)
    return start_dt, end_dt


def get_week_range(reference_date: datetime.date):
    """Returns (start_dt, end_dt) for the ISO week containing reference_date."""
    start = reference_date - datetime.timedelta(days=reference_date.weekday())
    end = start + datetime.timedelta(days=6)
    start_dt = datetime.datetime(start.year, start.month, start.day, 0, 0, 0)
    end_dt = datetime.datetime(end.year, end.month, end.day, 23, 59, 59)
    return start_dt, end_dt


def query_expenses_by_period(db, app_id: str, user_id: str,
                              start_dt: datetime.datetime,
                              end_dt: datetime.datetime,
                              category: str = None) -> list[dict]:
    """
    Returns a list of expense dicts within the given datetime range.
    Optionally filtered by category.
    """
    try:
        collection_path = f"artifacts/{app_id}/users/{user_id}/transactions"
        query_ref = (
            db.collection(collection_path)
            .where("type", "==", "expense")
            .where("date", ">=", start_dt)
            .where("date", "<=", end_dt)
        )
        if category:
            query_ref = query_ref.where("category", "==", category)

        docs = query_ref.stream()
        return [doc.to_dict() for doc in docs]
    except Exception as e:
        logger.error(f"query_expenses_by_period error: {e}")
        return []


def get_monthly_totals_by_category(db, app_id: str, user_id: str,
                                    year: int = None, month: int = None) -> dict[str, float]:
    """
    Returns {category: total_amount} for all expenses in the given month.
    Defaults to the current month.
    """
    today = datetime.date.today()
    year = year or today.year
    month = month or today.month
    start_dt, end_dt = get_month_range(year, month)

    expenses = query_expenses_by_period(db, app_id, user_id, start_dt, end_dt)
    totals: dict[str, float] = {}
    for exp in expenses:
        cat = exp.get("category", "Outros")
        totals[cat] = totals.get(cat, 0.0) + float(exp.get("amount", 0))
    return totals


def get_monthly_total(db, app_id: str, user_id: str,
                       year: int = None, month: int = None) -> float:
    """Returns the sum of all expenses for the given month."""
    totals = get_monthly_totals_by_category(db, app_id, user_id, year, month)
    return sum(totals.values())


def get_monthly_category_total(db, app_id: str, user_id: str,
                                category: str,
                                year: int = None, month: int = None) -> tuple[float, int]:
    """Returns (total, count) for a specific category in the given month."""
    today = datetime.date.today()
    year = year or today.year
    month = month or today.month
    start_dt, end_dt = get_month_range(year, month)

    expenses = query_expenses_by_period(db, app_id, user_id, start_dt, end_dt, category=category)
    total = sum(float(e.get("amount", 0)) for e in expenses)
    return total, len(expenses)


def get_weekly_totals_by_category(db, app_id: str, user_id: str,
                                   reference_date: datetime.date = None) -> dict[str, float]:
    """Returns {category: total} for the ISO week of reference_date."""
    if reference_date is None:
        reference_date = datetime.date.today()
    start_dt, end_dt = get_week_range(reference_date)
    expenses = query_expenses_by_period(db, app_id, user_id, start_dt, end_dt)
    totals: dict[str, float] = {}
    for exp in expenses:
        cat = exp.get("category", "Outros")
        totals[cat] = totals.get(cat, 0.0) + float(exp.get("amount", 0))
    return totals


def get_weekly_totals_by_category_prev(db, app_id: str, user_id: str,
                                        reference_date: datetime.date = None) -> dict[str, float]:
    """Returns {category: total} for the previous ISO week."""
    if reference_date is None:
        reference_date = datetime.date.today()
    prev_week = reference_date - datetime.timedelta(weeks=1)
    return get_weekly_totals_by_category(db, app_id, user_id, reference_date=prev_week)


def get_sofia_state(db, app_id: str, user_id: str) -> dict:
    """Loads sofia_state from Firestore. Returns defaults if not found."""
    defaults = {
        "alerts_sent_today": 0,
        "last_proactive_date": None,
        "category_alerts": {},
        "ignored_alerts_count": 0,
        "monthly_context": {"special_events": []},
    }
    try:
        doc_ref = db.collection(f"artifacts/{app_id}/sofia_state").document(user_id)
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            for k, v in defaults.items():
                if k not in data:
                    data[k] = v
            return data
        return defaults
    except Exception as e:
        logger.error(f"get_sofia_state error: {e}")
        return defaults


def save_sofia_state(db, app_id: str, user_id: str, state: dict) -> None:
    """Persists sofia_state to Firestore."""
    try:
        doc_ref = db.collection(f"artifacts/{app_id}/sofia_state").document(user_id)
        doc_ref.set(state, merge=True)
    except Exception as e:
        logger.error(f"save_sofia_state error: {e}")


def get_user_budget(db, app_id: str, user_id: str) -> dict:
    """
    Loads the user's budget config from Firestore.
    Returns { "categoryLimits": { "Lazer": 500.0, ... } } or {} if not configured.
    """
    try:
        doc_ref = db.collection(f"artifacts/{app_id}/users/{user_id}/settings").document("budget")
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict()
        return {}
    except Exception as e:
        logger.error(f"get_user_budget error: {e}")
        return {}


def get_monthly_income(db, app_id: str, user_id: str,
                       year: int = None, month: int = None) -> float:
    """
    Returns the sum of all income-type transactions for the given month.
    Defaults to the current month.
    """
    today = datetime.date.today()
    year = year or today.year
    month = month or today.month
    start_dt, end_dt = get_month_range(year, month)
    try:
        collection_path = f"artifacts/{app_id}/users/{user_id}/transactions"
        query_ref = (
            db.collection(collection_path)
            .where("type", "==", "income")
            .where("date", ">=", start_dt)
            .where("date", "<=", end_dt)
        )
        docs = query_ref.stream()
        return sum(float(d.to_dict().get("amount", 0)) for d in docs)
    except Exception as e:
        logger.error(f"get_monthly_income error: {e}")
        return 0.0

def get_user_cards(db, app_id: str, user_id: str) -> list:
    """Returns list of {'id': doc_id, 'name': str} for user's credit cards."""
    try:
        col = db.collection(f"artifacts/{app_id}/users/{user_id}/cards")
        docs = col.order_by("name").stream()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        logger.error(f"get_user_cards error: {e}")
        return []


def create_card(db, app_id: str, user_id: str, name: str) -> str:
    """Creates a new credit card and returns its Firestore document ID."""
    try:
        col = db.collection(f"artifacts/{app_id}/users/{user_id}/cards")
        ref = col.add({"name": name.strip(), "createdAt": firestore.SERVER_TIMESTAMP})
        return ref[1].id
    except Exception as e:
        logger.error(f"create_card error: {e}")
        return ""


def save_income(db, app_id: str, user_id: str, data: dict) -> bool:
    """Saves an income transaction to Firestore."""
    try:
        col = db.collection(f"artifacts/{app_id}/users/{user_id}/transactions")
        col.add({
            "description": data["description"],
            "amount": float(data["amount"]),
            "category": data.get("category", "Outros"),
            "type": "income",
            "date": datetime.datetime.fromisoformat(data["date"]).replace(hour=12, minute=0, second=0),
            "createdAt": firestore.SERVER_TIMESTAMP,
            "userId": user_id,
            "isInstallmentOriginal": False,
        })
        return True
    except Exception as e:
        logger.error(f"save_income error: {e}")
        return False


def save_expense_with_card(db, app_id: str, user_id: str, data: dict,
                            credit_card_id: str = None) -> bool:
    """Saves a simple (non-installment) expense, optionally linked to a credit card."""
    try:
        col = db.collection(f"artifacts/{app_id}/users/{user_id}/transactions")
        doc_data = {
            "description": data["description"],
            "amount": float(data["amount"]),
            "category": data.get("category", "Outros"),
            "type": "expense",
            "date": datetime.datetime.fromisoformat(data["date"]).replace(hour=12, minute=0, second=0),
            "createdAt": firestore.SERVER_TIMESTAMP,
            "userId": user_id,
            "isInstallmentOriginal": False,
        }
        if credit_card_id:
            doc_data["creditCardId"] = credit_card_id
        col.add(doc_data)
        return True
    except Exception as e:
        logger.error(f"save_expense_with_card error: {e}")
        return False


def save_installment_purchase(db, app_id: str, user_id: str, data: dict,
                               num_installments: int,
                               credit_card_id: str = None) -> bool:
    """
    Replicates the App Web installment logic:
    - Creates 1 parent doc in installments/
    - Creates N child docs in installmentPayments/ (one per month from purchase date)
    """
    try:
        import dateutil.relativedelta as rdelta

        purchase_dt = datetime.datetime.fromisoformat(data["date"]).replace(hour=12, minute=0, second=0)
        amount_per = float(data["amount"])
        total_amount = amount_per * num_installments
        description = data["description"]
        category = data.get("category", "Outros")

        # 1. Parent doc
        installments_col = db.collection(f"artifacts/{app_id}/users/{user_id}/installments")
        parent_data = {
            "userId": user_id,
            "description": description,
            "totalAmount": total_amount,
            "valuePerInstallment": amount_per,
            "numberOfInstallments": num_installments,
            "purchaseDate": purchase_dt,
            "category": category,
            "isInstallmentOriginal": True,
            "createdAt": firestore.SERVER_TIMESTAMP,
        }
        if credit_card_id:
            parent_data["creditCardId"] = credit_card_id
        parent_ref = installments_col.add(parent_data)
        parent_id = parent_ref[1].id

        # 2. Child docs (one per installment)
        payments_col = db.collection(f"artifacts/{app_id}/users/{user_id}/installmentPayments")
        for i in range(num_installments):
            due_dt = purchase_dt + rdelta.relativedelta(months=i)
            payment_data = {
                "userId": user_id,
                "installmentId": parent_id,
                "description": description,
                "category": category,
                "type": "expense",
                "amount": amount_per,
                "date": due_dt,
                "dueDate": due_dt,
                "paymentNumber": i + 1,
                "totalInstallments": num_installments,
                "isPaid": False,
                "createdAt": firestore.SERVER_TIMESTAMP,
            }
            if credit_card_id:
                payment_data["creditCardId"] = credit_card_id
            payments_col.add(payment_data)

        return True
    except Exception as e:
        logger.error(f"save_installment_purchase error: {e}")
        return False
