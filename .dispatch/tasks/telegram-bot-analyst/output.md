# Plano de Melhoria: Bot Telegram + Skill Analista Financeiro Sênior

## Arquitetura Atual

### Bot (`bot/main.py`)
- Roda no Render com `python-telegram-bot`
- Usa Gemini (`gemini-flash-latest`) para classificar intenções: **REGISTER**, **QUERY**, **FALLBACK**
- **REGISTER**: salva despesa no Firestore → retorna apenas uma linha de confirmação
- **QUERY**: retorna total + contagem de transações por período — sem breakdown por categoria
- Firebase Functions (`functions/index.js`): lida com webhooks Pluggy/Open Finance e enfileira em `notification_queue`
- Bot é **reativo** apenas — nenhuma mensagem proativa implementada

---

## Melhorias Planejadas

### Fase 1 — Enriquecer Respostas Existentes

**1.1 REGISTER com resumo mensal**
- Após registrar a despesa, buscar total do mês atual por categoria no Firestore
- Retornar mensagem no formato:
  ```
  ✅ Registrado: Almoço R$35,00 (Alimentação)

  📊 Seu mês até agora:
  • Alimentação: R$420,00
  • Transporte: R$180,00
  • Lazer: R$90,00
  ─────────────────
  Total: R$690,00
  ```

**1.2 QUERY com breakdown por categoria**
- Adicionar agrupamento por `categoria` na query Firestore
- Retornar tabela formatada com total por categoria + total geral
- Suportar filtros: "esse mês", "semana passada", "últimos 30 dias"

**1.3 Nova intenção: SUMMARY_MONTH**
- Prompt Gemini expandido para reconhecer: "resumo do mês", "como estou nos gastos", "relatório"
- Retorna visão consolidada: total por categoria, maior gasto, média diária, dias restantes

---

### Fase 2 — Skill "Sofia": Analista Financeiro Sênior

**2.1 Módulo `bot/analyst.py`**

Criar personagem "Sofia" — analista financeiro sênior com tom empático, direto e encorajador.

```python
SOFIA_PERSONA = """
Você é Sofia, analista financeira sênior com 15 anos de experiência.
Seu estilo é empático, direto e encorajador. Você fala como uma amiga
especialista — sem jargão excessivo, com exemplos práticos.
Você conhece o histórico financeiro do usuário e personaliza cada mensagem.
"""
```

**2.2 Alertas pós-registro (gatilho automático)**

Após cada REGISTER, verificar regras:
- Categoria ultrapassou 80% do limite mensal → alerta amarelo
- Categoria ultrapassou 100% → alerta vermelho
- Gasto único acima de R$200 em lazer/alimentação → dica contextual

Exemplos de mensagens Sofia:
```
⚠️ Sofia aqui! Você acabou de registrar R$85 em Lazer.
Esse mês você já gastou R$320 nessa categoria — 91% do seu limite.
Quer que eu sugira onde cortar nos próximos dias?
```

```
💡 Dica rápida: esse almoço de R$35 é o 8º neste mês.
Cozinhar em casa 3x por semana pode economizar ~R$180/mês.
Pequeno ajuste, grande impacto! 💪
```

**2.3 Resumos proativos (APScheduler)**

Adicionar scheduler dentro do bot para enviar mensagens programadas:

| Frequência | Gatilho | Conteúdo |
|-----------|---------|----------|
| Semanal (dom 20h) | Automático | Resumo da semana + comparativo semana anterior |
| Mensal (dia 1, 9h) | Automático | Fechamento do mês + meta para o próximo |
| Quinzenal | Automático | "Check-in Sofia" — como estão os gastos até agora |

Exemplo mensagem semanal:
```
📅 Resumo da semana, [Nome]!

Você gastou R$890 esta semana:
🍽️ Alimentação: R$340 (↑12% vs semana passada)
🚗 Transporte: R$210 (→ estável)
🎮 Lazer: R$180 (↓8% — ótimo!)
🏠 Outros: R$160

🎯 No ritmo atual, você vai fechar o mês em ~R$3.200.
Seu objetivo é R$3.000 — precisamos economizar R$200 nas próximas 2 semanas.

Quer dicas de onde cortar? Responda "sim" ou me diga uma categoria para focar.
```

**2.4 Interação conversacional com Sofia**

Implementar botões inline para continuar conversa:
- Após alerta → botões: [Ver detalhes] [Sugerir cortes] [Ok, entendi]
- Após resumo semanal → [Quero dicas] [Ver por categoria] [Definir meta]

Manter contexto de conversa com `ConversationHandler` do `python-telegram-bot`.

---

### Fase 3 — Metas e Gamificação (futuro)

- Usuário define meta mensal por categoria via bot
- Sofia acompanha e celebra conquistas: "Você ficou dentro do orçamento em Lazer pelo 2º mês seguido! 🏆"
- Score de "saúde financeira" exibido no resumo mensal

---

## Arquivos a Criar/Modificar

| Arquivo | Ação | Descrição |
|---------|------|-----------|
| `bot/analyst.py` | Criar | Módulo Sofia: persona, alertas, dicas |
| `bot/firestore_queries.py` | Criar | Funções reutilizáveis de query por período/categoria |
| `bot/main.py` | Modificar | Integrar analyst.py, enriquecer REGISTER/QUERY, adicionar SUMMARY_MONTH, scheduler |
| `bot/prompts.py` | Criar | Centralizar prompts Gemini (classificação + geração de mensagens Sofia) |
| `bot/requirements.txt` | Modificar | Adicionar `APScheduler` |

---

## Ordem de Implementação Recomendada

1. `bot/firestore_queries.py` — base para tudo
2. Enriquecer REGISTER e QUERY (Fase 1) — valor imediato, baixo risco
3. `bot/analyst.py` com alertas pós-registro (Fase 2.1 e 2.2)
4. APScheduler com resumos proativos (Fase 2.3)
5. Botões inline e ConversationHandler (Fase 2.4)
