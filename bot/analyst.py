import datetime
import logging
import calendar
from typing import Optional, Union, Dict, Any, List

from firestore_queries import (
    get_monthly_category_total,
    get_monthly_totals_by_category,
    get_weekly_totals_by_category,
    get_weekly_totals_by_category_prev,
    get_sofia_state,
    save_sofia_state,
    get_user_budget,
    get_monthly_income,
)

logger = logging.getLogger(__name__)

HIGH_SPEND_CATEGORIES = {"Lazer", "Alimentação", "Compras"}

SOFIA_PERSONA = """
Você é Sofia, analista financeira sênior com 15 anos de experiência em finanças pessoais.
Seu estilo é empático, direto e encorajador — como uma amiga especialista.
Fale de forma simples, sem jargão. Use no máximo 2 emojis por mensagem.
Seja breve: detalhes só se o usuário pedir.
Nunca julgue escolhas de estilo de vida.
Nunca seja dramática com valores pequenos.
"""

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
    def __init__(self, db, app_id: str, gemini_client, user_id: str):
        self.db = db
        self.app_id = app_id
        self.client = gemini_client
        self.user_id = user_id
        self._state: Optional[dict] = None
        self._budget: Optional[dict] = None

    def _get_budget(self) -> dict:
        """Loads and caches the user's budget (categoryLimits) from Firestore."""
        if self._budget is None:
            self._budget = get_user_budget(self.db, self.app_id, self.user_id)
        return self._budget

    def _get_category_limits(self) -> dict:
        """Returns the dict of {category: limit_value} configured by the user."""
        return self._get_budget().get("categoryLimits", {})

    def _load_state(self) -> dict:
        if self._state is None:
            self._state = get_sofia_state(self.db, self.app_id, self.user_id)
        return self._state

    def _save_state(self) -> None:
        if self._state is not None:
            save_sofia_state(self.db, self.app_id, self.user_id, self._state)

    def _reset_daily_counters_if_needed(self) -> None:
        state = self._load_state()
        today_str = datetime.date.today().isoformat()
        if state.get("last_proactive_date") != today_str:
            state["alerts_sent_today"] = 0

    def _can_send_proactive(self) -> bool:
        self._reset_daily_counters_if_needed()
        return self._load_state().get("alerts_sent_today", 0) < 1

    def _mark_proactive_sent(self) -> None:
        state = self._load_state()
        state["alerts_sent_today"] = state.get("alerts_sent_today", 0) + 1
        state["last_proactive_date"] = datetime.date.today().isoformat()
        self._save_state()

    def _call_gemini(self, prompt: str) -> str:
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

    async def check_after_register(self, amount: float, category: str) -> Optional[str]:
        state = self._load_state()
        limits = self._get_category_limits()
        monthly_income = get_monthly_income(self.db, self.app_id, self.user_id)

        # Only check high-spend tip if category has a limit configured
        high_spend_msg = None
        limit = limits.get(category)
        if limit and category in HIGH_SPEND_CATEGORIES:
            # Tip if single expense >= 40% of the category limit
            if amount >= limit * 0.40:
                high_spend_msg = await self._build_high_spend_tip(amount, category, limit, monthly_income)

        alert_msg = None
        if limit:
            cat_total, cat_count = get_monthly_category_total(
                self.db, self.app_id, self.user_id, category
            )
            pct = cat_total / limit
            cat_alerts = state.setdefault("category_alerts", {})
            prev_alert = cat_alerts.get(category, "none")

            if pct >= 1.0 and prev_alert != "red_sent":
                alert_msg = await self._build_red_alert(category, cat_total, limit, cat_count, monthly_income)
                cat_alerts[category] = "red_sent"
                self._save_state()
            elif 0.80 <= pct < 1.0 and prev_alert == "none":
                alert_msg = await self._build_yellow_alert(category, cat_total, limit, pct, monthly_income)
                cat_alerts[category] = "yellow_sent"
                self._save_state()

        if alert_msg:
            return alert_msg
        if high_spend_msg:
            return high_spend_msg
        return None

    async def build_query_response(self, start_date: str, end_date: str,
                                    category: Optional[str]) -> str:
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

        limits = self._get_category_limits()
        monthly_income = get_monthly_income(self.db, self.app_id, self.user_id)

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

        lines = []
        for cat, val in sorted(totals_by_cat.items(), key=lambda x: -x[1]):
            emoji = CATEGORY_EMOJI.get(cat, "•")
            lim = limits.get(cat)
            pct_str = f" ({int(val/lim*100)}% do limite)" if lim else ""
            lines.append(f"{emoji} {cat}: R${val:.2f}".replace(".", ",") + pct_str)

        breakdown = "\n".join(lines)
        total_fmt = f"R${total:.2f}".replace(".", ",")
        income_ctx = f"Receita do mês: R${monthly_income:.2f}. " if monthly_income > 0 else ""

        context_prompt = (
            f"O usuário perguntou sobre seus gastos {date_label}.\n"
            f"{income_ctx}Total gasto: {total_fmt}\nDetalhes:\n{breakdown}\n\n"
            "Escreva apenas 1 linha curta de análise ou encorajamento (sem repetir os números). "
            "Se estiver tudo bem, diga algo neutro e útil. Não use saudação."
        )
        insight = self._call_gemini(context_prompt)

        msg = f"📊 Gastos {date_label}:\n\n{breakdown}\n\n──────\nTotal: {total_fmt}"
        if insight:
            msg += f"\n\n{insight}"
        return msg

    async def build_monthly_summary(self) -> str:
        today = datetime.date.today()
        totals = get_monthly_totals_by_category(
            self.db, self.app_id, self.user_id, today.year, today.month
        )
        total = sum(totals.values())
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        days_remaining = days_in_month - today.day
        daily_avg = total / today.day if today.day > 0 else 0
        projection = daily_avg * days_in_month

        limits = self._get_category_limits()
        monthly_income = get_monthly_income(self.db, self.app_id, self.user_id)

        lines = []
        for cat, val in sorted(totals.items(), key=lambda x: -x[1]):
            emoji = CATEGORY_EMOJI.get(cat, "•")
            lim = limits.get(cat)
            pct_str = f" ({int(val/lim*100)}% do planejado)" if lim else ""
            lines.append(f"{emoji} {cat}: R${val:.2f}".replace(".", ",") + pct_str)

        breakdown = "\n".join(lines) if lines else "Nenhum gasto registrado ainda."
        month_name = calendar.month_name[today.month]
        income_ctx = f"Receita do mês (transações): R${monthly_income:.2f}.\n" if monthly_income > 0 else ""
        pct_income_str = f" ({int(total/monthly_income*100)}% da receita)" if monthly_income > 0 else ""

        context_prompt = (
            f"Resumo de {month_name} até o dia {today.day}:\n"
            f"{income_ctx}"
            f"Total gasto: R${total:.2f}{pct_income_str}\n"
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
        today = datetime.date.today()
        this_week = get_weekly_totals_by_category(self.db, self.app_id, self.user_id, today)
        prev_week = get_weekly_totals_by_category_prev(self.db, self.app_id, self.user_id, today)

        total_this = sum(this_week.values())
        total_prev = sum(prev_week.values())

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

    async def _build_yellow_alert(self, category: str, cat_total: float,
                                   limit: float, pct: float,
                                   monthly_income: float = 0.0) -> str:
        remaining = limit - cat_total
        pct_int = int(pct * 100)
        today = datetime.date.today()
        days_remaining = calendar.monthrange(today.year, today.month)[1] - today.day
        income_pct_str = ""
        if monthly_income > 0:
            income_pct = int(cat_total / monthly_income * 100)
            income_pct_str = f" ({income_pct}% da sua receita)"

        prompt = (
            f"O usuário acabou de gastar em {category} e atingiu {pct_int}% do limite planejado.\n"
            f"Gastou no total: R${cat_total:.2f}{income_pct_str} | Limite planejado: R${limit:.2f} | "
            f"Restam: R${remaining:.2f} | Dias no mês: {days_remaining}\n"
            + (f"Receita do mês: R${monthly_income:.2f}\n" if monthly_income > 0 else "") +
            f"\nEscreva uma mensagem de alerta amarelo no formato:\n"
            f"⚠️ [Você + categoria + % do planejado]\n"
            f"[Quanto falta + dias restantes]\n"
            f"[Pergunta ou sugestão opcional — 1 linha]\n"
            f"Seja breve, sem julgamento, máx 3 linhas."
        )
        msg = self._call_gemini(prompt)
        return msg or (
            f"⚠️ Você está em {pct_int}% do planejado para {category} esse mês.\n"
            f"Faltam R${remaining:.2f} para o limite ({days_remaining} dias ainda)."
        )

    async def _build_red_alert(self, category: str, cat_total: float,
                                limit: float, count: int,
                                monthly_income: float = 0.0) -> str:
        excess = cat_total - limit
        income_pct_str = ""
        if monthly_income > 0:
            income_pct = int(cat_total / monthly_income * 100)
            income_pct_str = f" ({income_pct}% da sua receita)"

        prompt = (
            f"O usuário ultrapassou o limite planejado de {category} este mês.\n"
            f"Gastou: R${cat_total:.2f}{income_pct_str} | Limite planejado: R${limit:.2f} | "
            f"Excesso: R${excess:.2f} | Transações: {count}\n"
            + (f"Receita do mês: R${monthly_income:.2f}\n" if monthly_income > 0 else "") +
            f"\nEscreva uma mensagem de alerta vermelho:\n"
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

    async def _build_high_spend_tip(self, amount: float, category: str,
                                     limit: float = 0.0,
                                     monthly_income: float = 0.0) -> str:
        _, count = get_monthly_category_total(
            self.db, self.app_id, self.user_id, category
        )
        limit_ctx = f" (limite planejado: R${limit:.2f})" if limit > 0 else ""
        income_ctx = f"Receita do mês: R${monthly_income:.2f}.\n" if monthly_income > 0 else ""
        pct_limit = int(amount / limit * 100) if limit > 0 else 0
        pct_str = f" — {pct_limit}% do limite da categoria" if pct_limit > 0 else ""

        prompt = (
            f"O usuário registrou um gasto significativo: R${amount:.2f} em {category}{pct_str}.\n"
            f"É o {count}º registro nessa categoria este mês{limit_ctx}.\n"
            f"{income_ctx}"
            f"\nEscreva uma dica contextual no formato:\n"
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
