# Sofia — Implementação Completa

## FILE: bot/firestore_queries.py

```python
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
            # Merge with defaults to handle missing keys
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
```

---

## FILE: bot/analyst.py

```python
"""
analyst.py — Sofia, analista financeira sênior.

Responsável por:
- Gerar alertas pós-registro (80%+ e 100%+ de limites de categoria)
- Gerar dicas contextuais para gastos altos pontuais
- Gerar resumos semanais, quinzenais e mensais
- Respeitar as regras de silêncio definidas no sofia-design
"""

import datetime
import logging
import json
from google import genai
from google.genai import types

from firestore_queries import (
    get_monthly_category_total,
    get_monthly_totals_by_category,
    get_monthly_total,
    get_weekly_totals_by_category,
    get_weekly_totals_by_category_prev,
    get_sofia_state,
    save_sofia_state,
)

logger = logging.getLogger(__name__)

# ── Limites padrão por categoria ─────────────────────────────────────────────
DEFAULT_LIMITS: dict[str, float] = {
    "Alimentação": 700.0,
    "Transporte": 400.0,
    "Lazer": 400.0,
    "Outros": 300.0,
}

# Categorias "variáveis" onde um gasto pontual alto merece dica
HIGH_SPEND_CATEGORIES = {"Lazer", "Alimentação", "Compras"}
HIGH_SPEND_THRESHOLD = 200.0

# Persona base de Sofia
SOFIA_PERSONA = """
Você é Sofia, analista financeira sênior com 15 anos de experiência em finanças pessoais.
Seu estilo é empático, direto e encorajador — como uma amiga especialista.
Fale de forma simples, sem jargão. Use no máximo 2 emojis por mensagem.
Seja breve: detalhes só se o usuário pedir.
Nunca julgue escolhas de estilo de vida.
Nunca seja dramática com valores pequenos.
"""

# Emojis por categoria
CATEGORY_EMOJI = {
    "Alimentação": "🍽️",
    "Transporte": "🚗",
    "Lazer": "🎮",
    "Moradia": "🏠",
    "Saúde": "💊",
    "Educação": "📚",
    "Compras": "🛍️",
    "Impostos": "🧾",
    "Serviços": "⚙️",
    "Dívidas": "💳",
    "Outros": "📦",
}


class Sofia:
    """
    Analista financeira Sofia.
    Recebe db, app_id, gemini_client e user_id no construtor.
    """

    def __init__(self, db, app_id: str, gemini_client, user_id: str):
        self.db = db
        self.app_id = app_id
        self.client = gemini_client
        self.user_id = user_id
        self._state: dict | None = None  # lazy-loaded

    # ── State helpers ─────────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        if self._state is None:
            self._state = get_sofia_state(self.db, self.app_id, self.user_id)
        return self._state

    def _save_state(self) -> None:
        if self._state is not None:
            save_sofia_state(self.db, self.app_id, self.user_id, self._state)

    def _reset_daily_counters_if_needed(self) -> None:
        """Resets per-day counters when the date has changed."""
        state = self._load_state()
        today_str = datetime.date.today().isoformat()
        if state.get("last_proactive_date") != today_str:
            state["alerts_sent_today"] = 0
            # Do NOT reset category_alerts here — they are monthly

    def _can_send_proactive(self) -> bool:
        """Returns True if Sofia hasn't sent a proactive message today yet."""
        self._reset_daily_counters_if_needed()
        return self._load_state().get("alerts_sent_today", 0) < 1

    def _mark_proactive_sent(self) -> None:
        state = self._load_state()
        state["alerts_sent_today"] = state.get("alerts_sent_today", 0) + 1
        state["last_proactive_date"] = datetime.date.today().isoformat()
        self._save_state()

    # ── Gemini helper ─────────────────────────────────────────────────────────

    def _call_gemini(self, prompt: str) -> str:
        """Calls Gemini with Sofia's persona prepended. Returns plain text."""
        try:
            full_prompt = f"{SOFIA_PERSONA}\n\n{prompt}"
            response = self.client.models.generate_content(
                model="gemini-flash-latest",
                contents=[full_prompt],
            )
            return response.text.strip() if response and response.text else ""
        except Exception as e:
            logger.error(f"Sofia Gemini error: {e}")
            return ""

    # ── Public API ────────────────────────────────────────────────────────────

    async def check_after_register(self, amount: float, category: str) -> str | None:
        """
        Called right after a REGISTER is saved.
        Returns a Sofia message string if an alert/tip should be sent,
        or None if Sofia should stay silent.
        """
        state = self._load_state()
        today = datetime.date.today()

        # ── Rule 1: high single spend in variable category ────────────────
        high_spend_msg = None
        if category in HIGH_SPEND_CATEGORIES and amount >= HIGH_SPEND_THRESHOLD:
            high_spend_msg = await self._build_high_spend_tip(amount, category)

        # ── Rule 2: category limit alerts (80% / 100%) ────────────────────
        limit = DEFAULT_LIMITS.get(category)
        alert_msg = None
        if limit:
            cat_total, cat_count = get_monthly_category_total(
                self.db, self.app_id, self.user_id, category
            )
            pct = cat_total / limit
            cat_alerts = state.setdefault("category_alerts", {})
            prev_alert = cat_alerts.get(category, "none")

            if pct >= 1.0 and prev_alert != "red_sent":
                alert_msg = await self._build_red_alert(category, cat_total, limit, cat_count)
                cat_alerts[category] = "red_sent"
                self._save_state()
            elif 0.80 <= pct < 1.0 and prev_alert == "none":
                alert_msg = await self._build_yellow_alert(category, cat_total, limit, pct)
                cat_alerts[category] = "yellow_sent"
                self._save_state()

        # Priority: limit alert > high spend tip; return only one message
        if alert_msg:
            return alert_msg
        if high_spend_msg:
            return high_spend_msg
        return None

    async def build_query_response(self, start_date: str, end_date: str,
                                    category: str | None) -> str:
        """
        Builds an enriched QUERY response with Sofia's analysis.
        """
        start_dt = datetime.datetime.fromisoformat(start_date)
        end_dt = datetime.datetime.fromisoformat(end_date) + datetime.timedelta(
            hours=23, minutes=59, seconds=59
        )

        from firestore_queries import query_expenses_by_period
        expenses = query_expenses_by_period(
            self.db, self.app_id, self.user_id, start_dt, end_dt, category=category
        )

        if not expenses:
            return "Não encontrei gastos nesse período."

        total = sum(float(e.get("amount", 0)) for e in expenses)
        totals_by_cat: dict[str, float] = {}
        for e in expenses:
            cat = e.get("category", "Outros")
            totals_by_cat[cat] = totals_by_cat.get(cat, 0.0) + float(e.get("amount", 0))

        # Date label
        today = datetime.date.today().isoformat()
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        if start_date == end_date:
            if start_date == today:
                date_label = "hoje"
            elif start_date == yesterday:
                date_label = "ontem"
            else:
                d = datetime.datetime.strptime(start_date, "%Y-%m-%d")
                date_label = f"em {d.strftime('%d/%m')}"
        else:
            s = datetime.datetime.strptime(start_date, "%Y-%m-%d")
            ex = datetime.datetime.strptime(end_date, "%Y-%m-%d")
            date_label = f"de {s.strftime('%d/%m')} a {ex.strftime('%d/%m')}"

        # Build breakdown
        lines = []
        for cat, val in sorted(totals_by_cat.items(), key=lambda x: -x[1]):
            emoji = CATEGORY_EMOJI.get(cat, "•")
            limit = DEFAULT_LIMITS.get(cat)
            pct_str = f" ({int(val/limit*100)}% do limite)" if limit else ""
            lines.append(f"{emoji} {cat}: R${val:.2f}".replace(".", ",") + pct_str)

        breakdown = "\n".join(lines)
        total_fmt = f"R${total:.2f}".replace(".", ",")

        # Ask Gemini to add 1-line Sofia insight
        context_prompt = (
            f"O usuário perguntou sobre seus gastos {date_label}.\n"
            f"Total: {total_fmt}\nDetalhes:\n{breakdown}\n\n"
            "Escreva apenas 1 linha curta de análise ou encorajamento (sem repetir os números). "
            "Se estiver tudo bem, diga algo neutro e útil. Não use saudação."
        )
        insight = self._call_gemini(context_prompt)

        msg = f"📊 Gastos {date_label}:\n\n{breakdown}\n\n──────\nTotal: {total_fmt}"
        if insight:
            msg += f"\n\n{insight}"
        return msg

    async def build_monthly_summary(self) -> str:
        """Returns a full monthly summary with Sofia's analysis."""
        today = datetime.date.today()
        totals = get_monthly_totals_by_category(
            self.db, self.app_id, self.user_id, today.year, today.month
        )
        total = sum(totals.values())
        days_in_month = (
            datetime.date(today.year, today.month % 12 + 1, 1)
            if today.month < 12
            else datetime.date(today.year + 1, 1, 1)
        ) - datetime.timedelta(days=1)
        days_in_month = days_in_month.day
        days_remaining = days_in_month - today.day
        daily_avg = total / today.day if today.day > 0 else 0
        projection = daily_avg * days_in_month

        lines = []
        for cat, val in sorted(totals.items(), key=lambda x: -x[1]):
            emoji = CATEGORY_EMOJI.get(cat, "•")
            limit = DEFAULT_LIMITS.get(cat)
            pct_str = f" ({int(val/limit*100)}% do limite)" if limit else ""
            lines.append(f"{emoji} {cat}: R${val:.2f}".replace(".", ",") + pct_str)

        breakdown = "\n".join(lines) if lines else "Nenhum gasto registrado ainda."
        month_name = today.strftime("%B").capitalize()

        context_prompt = (
            f"Resumo de {month_name} até o dia {today.day}:\n"
            f"Total gasto: R${total:.2f}\n"
            f"Projeção para o mês: R${projection:.2f}\n"
            f"Dias restantes: {days_remaining}\n"
            f"Detalhes:\n{chr(10).join(lines)}\n\n"
            "Escreva 1 frase de análise: se está no controle, no limite ou acima. "
            "Inclua 1 sugestão prática se aplicável. Seja breve."
        )
        insight = self._call_gemini(context_prompt)

        total_fmt = f"R${total:.2f}".replace(".", ",")
        proj_fmt = f"R${projection:.2f}".replace(".", ",")

        msg = (
            f"📊 {month_name} até agora:\n\n"
            f"{breakdown}\n\n"
            f"──────\n"
            f"Total: {total_fmt} | Projeção: {proj_fmt}\n"
            f"Faltam {days_remaining} dias"
        )
        if insight:
            msg += f"\n\n{insight}"
        return msg

    async def build_weekly_summary(self) -> str:
        """Returns weekly summary comparing to previous week."""
        today = datetime.date.today()
        this_week = get_weekly_totals_by_category(self.db, self.app_id, self.user_id, today)
        prev_week = get_weekly_totals_by_category_prev(self.db, self.app_id, self.user_id, today)

        total_this = sum(this_week.values())
        total_prev = sum(prev_week.values())

        # Week date range
        start = today - datetime.timedelta(days=today.weekday())
        end = start + datetime.timedelta(days=6)
        week_label = f"{start.strftime('%d/%m')} a {end.strftime('%d/%m')}"

        lines = []
        all_cats = set(this_week) | set(prev_week)
        for cat in sorted(all_cats, key=lambda c: -this_week.get(c, 0)):
            emoji = CATEGORY_EMOJI.get(cat, "•")
            val = this_week.get(cat, 0.0)
            prev = prev_week.get(cat, 0.0)
            if prev > 0:
                diff_pct = int((val - prev) / prev * 100)
                arrow = "↑" if diff_pct > 5 else ("↓" if diff_pct < -5 else "→")
                comp = f"({arrow}{abs(diff_pct)}%)"
            else:
                comp = ""
            lines.append(f"{emoji} {cat}: R${val:.2f} {comp}".replace(".", ",").rstrip())

        breakdown = "\n".join(lines) if lines else "Nenhum gasto esta semana."
        total_fmt = f"R${total_this:.2f}".replace(".", ",")
        prev_fmt = f"R${total_prev:.2f}".replace(".", ",")
        diff_abs = abs(total_this - total_prev)
        diff_fmt = f"R${diff_abs:.2f}".replace(".", ",")
        direction = "acima" if total_this > total_prev else "abaixo"

        context_prompt = (
            f"Resumo da semana de {week_label}.\n"
            f"Total: {total_fmt} ({diff_fmt} {direction} da semana passada).\n"
            f"Detalhes:\n{chr(10).join(lines)}\n\n"
            "Escreva 1 frase curta de análise ou encorajamento. Seja Sofia, empática e direta."
        )
        insight = self._call_gemini(context_prompt)

        msg = (
            f"📅 Semana de {week_label}\n\n"
            f"Você gastou {total_fmt} (semana passada: {prev_fmt}):\n"
            f"{breakdown}"
        )
        if insight:
            msg += f"\n\n{insight}"
        return msg

    # ── Internal builders ─────────────────────────────────────────────────────

    async def _build_yellow_alert(self, category: str, cat_total: float,
                                   limit: float, pct: float) -> str:
        remaining = limit - cat_total
        pct_int = int(pct * 100)
        today = datetime.date.today()
        import calendar
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        days_remaining = days_in_month - today.day

        prompt = (
            f"O usuário acabou de gastar em {category} e atingiu {pct_int}% do limite mensal.\n"
            f"Gastou no total: R${cat_total:.2f} | Limite: R${limit:.2f} | "
            f"Restam: R${remaining:.2f} | Dias no mês: {days_remaining}\n\n"
            f"Escreva uma mensagem de alerta amarelo no formato:\n"
            f"⚠️ [Você + categoria + % do limite]\n"
            f"[Quanto falta + dias restantes]\n"
            f"[Pergunta ou sugestão opcional — 1 linha]\n"
            f"Seja breve, sem julgamento, máx 3 linhas."
        )
        msg = self._call_gemini(prompt)
        return msg or (
            f"⚠️ Você está em {pct_int}% do limite de {category} esse mês.\n"
            f"Faltam R${remaining:.2f} para o limite ({days_remaining} dias ainda)."
        )

    async def _build_red_alert(self, category: str, cat_total: float,
                                limit: float, count: int) -> str:
        excess = cat_total - limit
        prompt = (
            f"O usuário ultrapassou o limite de {category} este mês.\n"
            f"Gastou: R${cat_total:.2f} | Limite: R${limit:.2f} | "
            f"Excesso: R${excess:.2f} | Transações: {count}\n\n"
            f"Escreva uma mensagem de alerta vermelho:\n"
            f"🚨 [Limite atingido + excesso]\n"
            f"[Frase empática — sem drama]\n"
            f"[Pergunta propositiva — 1 linha]\n"
            f"Máx 3 linhas."
        )
        msg = self._call_gemini(prompt)
        return msg or (
            f"🚨 Limite de {category} atingido — você está R${excess:.2f} acima do planejado.\n"
            f"Acontece. Quer ver onde compensar?"
        )

    async def _build_high_spend_tip(self, amount: float, category: str) -> str:
        _, count = get_monthly_category_total(
            self.db, self.app_id, self.user_id, category
        )
        prompt = (
            f"O usuário registrou um gasto pontual alto: R${amount:.2f} em {category}.\n"
            f"É o {count}º registro nessa categoria este mês.\n\n"
            f"Escreva uma dica contextual no formato:\n"
            f"💡 [R$valor em categoria — observação leve]\n"
            f"[Insight sobre o padrão]\n"
            f"[Sugestão prática em 1 linha]\n"
            f"Seja Sofia: empática, não julgue. Máx 3 linhas."
        )
        msg = self._call_gemini(prompt)
        return msg or (
            f"💡 R${amount:.2f} em {category} — é o {count}º registro esse mês.\n"
            f"Fique de olho nessa categoria até o fim do mês."
        )
```

---

## FILE: bot/main.py (versão completa modificada)

```python
import os
import datetime
import logging
import json
from dotenv import load_dotenv

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from keep_alive import keep_alive

from firestore_queries import (
    get_monthly_totals_by_category,
    get_monthly_total,
)
from analyst import Sofia, CATEGORY_EMOJI

# ── Load env ──────────────────────────────────────────────────────────────────
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
FIREBASE_SERVICE_ACCOUNT = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
APP_ID = os.getenv("APP_ID") or "default-app-id"

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Firebase ──────────────────────────────────────────────────────────────────
if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ── Gemini ────────────────────────────────────────────────────────────────────
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# ── Categories ────────────────────────────────────────────────────────────────
CATEGORIES = [
    "Moradia", "Alimentação", "Transporte", "Lazer", "Saúde",
    "Educação", "Compras", "Impostos", "Serviços", "Dívidas", "Outros",
]


# ── Firestore helpers ─────────────────────────────────────────────────────────

async def get_firebase_user_id(telegram_id: str) -> str | None:
    try:
        doc_ref = db.collection(f"artifacts/{APP_ID}/user_mappings").document(str(telegram_id))
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict().get("firebaseUserId")
        return None
    except Exception as e:
        logger.error(f"Mapping Error: {e}")
        return None


async def save_user_mapping(telegram_id: str, firebase_user_id: str) -> tuple[bool, str]:
    try:
        doc_ref = db.collection(f"artifacts/{APP_ID}/user_mappings").document(str(telegram_id))
        doc_ref.set({
            "telegramId": telegram_id,
            "firebaseUserId": firebase_user_id,
            "linkedAt": firestore.SERVER_TIMESTAMP,
        })
        return True, ""
    except Exception as e:
        logger.error(f"Save Mapping Error: {e}")
        return False, str(e)


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


# ── Gemini intent extraction ──────────────────────────────────────────────────

async def process_with_gemini(text: str = None, audio_file: str = None) -> dict:
    current_date = datetime.date.today().isoformat()
    system_prompt = f"""
You are a financial assistant.
Current Date: {current_date}
Available Categories: {', '.join(CATEGORIES)}

Analyze the user's input and determine the intent.

Return a JSON object (no markdown wrapping):

### REGISTER
{{"intent":"REGISTER","amount":<number>,"category":<category>,"description":<text>,"date":<YYYY-MM-DD>}}

### QUERY
{{"intent":"QUERY","category":<category or null>,"start_date":<YYYY-MM-DD>,"end_date":<YYYY-MM-DD>}}

### SUMMARY_MONTH
If the user says "resumo do mês", "como estou", "relatório", "situação dos gastos":
{{"intent":"SUMMARY_MONTH"}}

### FALLBACK
{{"intent":"FALLBACK"}}

For "today" → start/end = {current_date}
For "yesterday" → both = yesterday's date.
"""
    try:
        parts = [system_prompt]
        if text:
            parts.append(f"User Message: {text}")
        if audio_file:
            with open(audio_file, "rb") as f:
                uploaded = gemini_client.files.upload(file=f, config={"mime_type": "audio/ogg"})
            parts.append(uploaded)

        response = gemini_client.models.generate_content(
            model="gemini-flash-latest",
            contents=parts,
        )
        if not response or not response.text:
            return {"error": "Sem resposta do Gemini"}
        raw = response.text.strip()
        if raw.startswith("```json"):
            raw = raw[7:]
        if raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        return json.loads(raw.strip())
    except Exception as e:
        logger.error(f"Gemini Error: {e}")
        return {"error": str(e)}


# ── Expense persistence ───────────────────────────────────────────────────────

async def save_expense(data: dict, user_id: str) -> bool:
    try:
        transaction_data = {
            "description": data["description"],
            "amount": float(data["amount"]),
            "category": data["category"],
            "type": "expense",
            "date": datetime.datetime.fromisoformat(data["date"]).replace(
                hour=12, minute=0, second=0
            ),
            "createdAt": firestore.SERVER_TIMESTAMP,
            "userId": user_id,
            "isInstallmentOriginal": False,
        }
        db.collection(f"artifacts/{APP_ID}/users/{user_id}/transactions").add(transaction_data)
        return True
    except Exception as e:
        logger.error(f"Firestore Save Error: {e}")
        return False


async def query_expenses(filters_dict: dict, user_id: str) -> tuple[float, int]:
    try:
        collection_path = f"artifacts/{APP_ID}/users/{user_id}/transactions"
        query_ref = db.collection(collection_path)
        start_dt = datetime.datetime.fromisoformat(filters_dict["start_date"])
        end_dt = (
            datetime.datetime.fromisoformat(filters_dict["end_date"])
            + datetime.timedelta(days=1)
            - datetime.timedelta(seconds=1)
        )
        query_ref = (
            query_ref
            .where("date", ">=", start_dt)
            .where("date", "<=", end_dt)
            .where("type", "==", "expense")
        )
        if filters_dict.get("category"):
            query_ref = query_ref.where("category", "==", filters_dict["category"])
        docs = query_ref.stream()
        total = 0.0
        count = 0
        for doc in docs:
            d = doc.to_dict()
            total += d.get("amount", 0)
            count += 1
        return total, count
    except Exception as e:
        logger.error(f"Firestore Query Error: {e}")
        return None, 0


# ── Telegram handlers ─────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    args = context.args

    if args:
        firebase_uid = args[0]
        success, error_msg = await save_user_mapping(user_id, firebase_uid)
        if success:
            await update.message.reply_text(
                f"🔐 Conta vinculada com sucesso!\nID: {firebase_uid}\n\n"
                "Agora você pode registrar gastos por texto ou áudio."
            )
        else:
            await update.message.reply_text(f"❌ Falha ao vincular conta.\nErro: {error_msg}")
    else:
        existing_uid = await get_firebase_user_id(user_id)
        if existing_uid:
            await update.message.reply_text(
                f"👋 Você já está conectado (ID: ...{existing_uid[-5:]}).\nPode enviar seus gastos!"
            )
        else:
            await update.message.reply_text(
                "Olá! Para usar o bot, você precisa vincular sua conta.\n\n"
                "1. Abra o App Web\n"
                "2. Clique no ícone do Telegram (canto superior)\n"
                "3. Siga as instruções para copiar seu código.\n\n"
                "Ou envie: `/start <SEU_ID_DO_FIREBASE>`",
                parse_mode="Markdown",
            )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    firebase_uid = await get_firebase_user_id(user_id)

    if not firebase_uid:
        await update.message.reply_text(
            "⚠️ Você precisa vincular sua conta primeiro.\nEnvie `/start <SEU_ID>`"
        )
        return

    user_text = update.message.text
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    extracted = await process_with_gemini(text=user_text)
    await respond_to_user(update, context, extracted, firebase_uid)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    firebase_uid = await get_firebase_user_id(user_id)

    if not firebase_uid:
        await update.message.reply_text("⚠️ Você precisa vincular sua conta primeiro.")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    voice_file = await context.bot.get_file(update.message.voice.file_id)
    file_path = f"voice_{user_id}.ogg"
    await voice_file.download_to_drive(file_path)
    extracted = await process_with_gemini(audio_file=file_path)
    await respond_to_user(update, context, extracted, firebase_uid)

    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        logger.warning(f"Failed to delete temp file {file_path}: {e}")


async def respond_to_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    extracted: dict,
    firebase_uid: str,
):
    if not extracted:
        await update.message.reply_text("Desculpe, não entendi. Tente de novo.")
        return

    if extracted.get("error"):
        await update.message.reply_text(f"❌ Erro no Gemini: {extracted['error']}")
        return

    intent = extracted.get("intent")

    # ── FALLBACK ──────────────────────────────────────────────────────────
    if intent == "FALLBACK":
        await update.message.reply_text(
            "📱 Para estas informações e muito mais, acesse o app completo: "
            "https://my-finance-app-24d0f.web.app"
        )
        return

    # ── REGISTER ──────────────────────────────────────────────────────────
    if intent == "REGISTER":
        success = await save_expense(extracted, firebase_uid)
        if not success:
            await update.message.reply_text("❌ Erro ao salvar no banco de dados.")
            return

        amount = float(extracted["amount"])
        category = extracted["category"]
        desc = extracted["description"]
        formatted = f"{amount:.2f}".replace(".", ",")
        confirm_msg = f"✅ Registrado: R$ {formatted} em {category} ({desc})."
        await update.message.reply_text(confirm_msg)

        # Sofia alert check (async, non-blocking for UX)
        sofia = Sofia(db, APP_ID, gemini_client, firebase_uid)
        alert = await sofia.check_after_register(amount, category)
        if alert:
            await update.message.reply_text(alert)
        return

    # ── QUERY ─────────────────────────────────────────────────────────────
    if intent == "QUERY":
        sofia = Sofia(db, APP_ID, gemini_client, firebase_uid)
        msg = await sofia.build_query_response(
            extracted["start_date"],
            extracted["end_date"],
            extracted.get("category"),
        )
        await update.message.reply_text(msg)
        return

    # ── SUMMARY_MONTH ─────────────────────────────────────────────────────
    if intent == "SUMMARY_MONTH":
        sofia = Sofia(db, APP_ID, gemini_client, firebase_uid)
        msg = await sofia.build_monthly_summary()
        await update.message.reply_text(msg)
        return

    await update.message.reply_text(
        "Não entendi se é para registrar ou consultar. Tente ser mais claro."
    )


# ── Proactive scheduler ───────────────────────────────────────────────────────

async def job_weekly_summary(bot):
    """Sends weekly summary every Sunday at 20h (BRT = UTC-3 → 23h UTC)."""
    logger.info("Running weekly summary job...")
    users = await get_all_mapped_users()
    for user in users:
        try:
            telegram_id = user["telegram_id"]
            firebase_uid = user["firebase_uid"]
            if not telegram_id or not firebase_uid:
                continue
            sofia = Sofia(db, APP_ID, gemini_client, firebase_uid)
            if not sofia._can_send_proactive():
                continue
            msg = await sofia.build_weekly_summary()
            await bot.send_message(chat_id=telegram_id, text=msg)
            sofia._mark_proactive_sent()
        except Exception as e:
            logger.error(f"Weekly summary error for user {user}: {e}")


async def job_monthly_closure(bot):
    """Sends monthly closure on the 1st of each month at 9h (BRT → 12h UTC)."""
    logger.info("Running monthly closure job...")
    users = await get_all_mapped_users()
    for user in users:
        try:
            telegram_id = user["telegram_id"]
            firebase_uid = user["firebase_uid"]
            if not telegram_id or not firebase_uid:
                continue
            sofia = Sofia(db, APP_ID, gemini_client, firebase_uid)
            if not sofia._can_send_proactive():
                continue
            # Use previous month for closure
            today = datetime.date.today()
            if today.month == 1:
                prev_month = 12
                prev_year = today.year - 1
            else:
                prev_month = today.month - 1
                prev_year = today.year
            from firestore_queries import get_monthly_totals_by_category
            totals = get_monthly_totals_by_category(db, APP_ID, firebase_uid, prev_year, prev_month)
            total = sum(totals.values())
            import calendar
            month_name = calendar.month_name[prev_month]
            lines = []
            for cat, val in sorted(totals.items(), key=lambda x: -x[1]):
                emoji = CATEGORY_EMOJI.get(cat, "•")
                lines.append(f"{emoji} {cat}: R${val:.2f}".replace(".", ","))
            breakdown = "\n".join(lines) or "Nenhum gasto registrado."
            total_fmt = f"R${total:.2f}".replace(".", ",")
            msg = (
                f"📊 Fechamento de {month_name}\n\n"
                f"{breakdown}\n\n──────\nTotal: {total_fmt}\n\n"
                "Quer revisar metas para este mês? Me diga uma categoria para focar."
            )
            await bot.send_message(chat_id=telegram_id, text=msg)
            sofia._mark_proactive_sent()
        except Exception as e:
            logger.error(f"Monthly closure error for user {user}: {e}")


async def job_biweekly_checkin(bot):
    """Sends biweekly check-in on the 15th at 9h (BRT → 12h UTC)."""
    logger.info("Running biweekly check-in job...")
    users = await get_all_mapped_users()
    for user in users:
        try:
            telegram_id = user["telegram_id"]
            firebase_uid = user["firebase_uid"]
            if not telegram_id or not firebase_uid:
                continue
            sofia = Sofia(db, APP_ID, gemini_client, firebase_uid)
            if not sofia._can_send_proactive():
                continue
            msg = await sofia.build_monthly_summary()
            # Prepend check-in header
            today = datetime.date.today()
            import calendar
            month_name = calendar.month_name[today.month]
            header = f"📍 Metade de {month_name}.\n\n"
            await bot.send_message(chat_id=telegram_id, text=header + msg)
            sofia._mark_proactive_sent()
        except Exception as e:
            logger.error(f"Biweekly check-in error for user {user}: {e}")


def setup_scheduler(app) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")

    # Sunday 20h BRT
    scheduler.add_job(
        job_weekly_summary,
        trigger=CronTrigger(day_of_week="sun", hour=20, minute=0, timezone="America/Sao_Paulo"),
        args=[app.bot],
        id="weekly_summary",
        replace_existing=True,
    )
    # 1st of month 9h BRT
    scheduler.add_job(
        job_monthly_closure,
        trigger=CronTrigger(day=1, hour=9, minute=0, timezone="America/Sao_Paulo"),
        args=[app.bot],
        id="monthly_closure",
        replace_existing=True,
    )
    # 15th of month 9h BRT
    scheduler.add_job(
        job_biweekly_checkin,
        trigger=CronTrigger(day=15, hour=9, minute=0, timezone="America/Sao_Paulo"),
        args=[app.bot],
        id="biweekly_checkin",
        replace_existing=True,
    )

    return scheduler


# ── Error handler ─────────────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not TELEGRAM_TOKEN:
        print("Telegram Token not found!")
        exit(1)

    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_error_handler(error_handler)

    scheduler = setup_scheduler(application)
    scheduler.start()

    print("Bot Version: 2.0 (Sofia enabled)")
    print(f"Bot is running in MULTI-USER mode (APP_ID: {APP_ID})...")
    keep_alive()
    application.run_polling()
```

---

## FILE: bot/requirements.txt (versão atualizada)

```
python-telegram-bot==21.6
firebase-admin==6.5.0
google-genai==0.8.0
python-dotenv==1.0.1
APScheduler==3.10.4
flask==3.0.3
```
