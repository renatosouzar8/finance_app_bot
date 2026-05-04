# Telegram Bot - Análise e Plano de Melhoria com Analista Financeiro Sênior

- [x] Explorar estrutura do projeto: bot/main.py (python-telegram-bot + Gemini), functions/index.js (Firebase), Firestore
- [x] Mapear os comandos/fluxos atuais: REGISTER (salva + confirmação simples), QUERY (total sem categoria), FALLBACK
- [x] Avaliar viabilidade: ambas as melhorias são viáveis com a stack atual (Python, Firestore, APScheduler)
- [x] Esboçar arquitetura: analyst.py como módulo Sofia, alertas pós-registro, scheduler para proativos, ConversationHandler para diálogo
- [x] Escrever plano detalhado com arquivos, exemplos de mensagens e ordem de implementação
- [x] Resultado salvo em .dispatch/tasks/telegram-bot-analyst/output.md
