# Validação — fluxo funcional local — 18/09/2026

## Resultados

- Backend: 92 testes aprovados, 2 placeholders legados explicitamente ignorados.
- Módulos operacionais (`app/live` e `app/main`): 91% de cobertura.
- Frontend: 8 testes aprovados; TypeScript, ESLint e compilação de produção aprovados.
- Testes novos isolam dados sintéticos em bancos temporários; não gravam na carteira real do aplicativo.
- SQLite reaberto após reinício: histórico e resultado do backtest preservados.
- GET /api/engine/status: dados válidos da Binance, calendário disponível e análise calculada.
- GET /api/engine/history/{id}: snapshot completo com 600 candles, indicadores e decisão.
- POST /api/engine/backtest: 30 dias reais, 1 operação, saldo final 9.900 USDT (-1%).
  Este é o resultado do conjunto de dados testado, não promessa nem validação estatística da estratégia.
- Origem externa em POST /api/engine/paper: HTTP 403.
- Falhas da fonte, dados antigos, calendário indisponível, gaps, duplicação, custos,
  stop prioritário, entrada na abertura seguinte e ausência de lookahead cobertos por testes.
- Auditoria do sinal e filtros usados na confirmação persistidos. Cancelamento e encerramento
  simulados verificados em testes isolados; nenhuma operação real é executada.

## Ambiente e limites

Python 3.13 e dependências fixadas nos manifests. Serviços locais em 127.0.0.1:8000 e :3000.
A automação do navegador ficou indisponível neste turno por falha do ambiente; a versão
integrada foi verificada por compilação, testes e requisições reais através das rotas do painel.
Não foi executado Docker neste computador. O modo implementado é pessoal/local, sem
contas multiusuário ou execução financeira. Backtest é técnico, com custos e sem calendário
macro histórico; não valida todos os filtros ao vivo nem resultados futuros.
