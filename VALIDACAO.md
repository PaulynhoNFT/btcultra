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


## Integração de estrutura Fornes — 20/09/2026

- Backend completo: 105 testes aprovados; 2 testes legados previamente ignorados. Após o ajuste de exibição de todos os critérios, os 13 testes de estrutura passaram novamente.
- Frontend: 14 testes aprovados, incluindo renderização com estrutura descritiva sem entrada, carregamento e ocultação de gráfico/plano com dados antigos.
- Compilação de produção, lint e verificação de tipos aprovados; verificação final de tipos aprovada após novos testes de renderização.
- API real local validada através do proxy Next: coleta pronta, fonte Binance, `fornes-structure-v1`, 200 velas em cada um dos três períodos, eventos e regiões calculados; nenhuma entrada fabricada quando falta alinhamento.
- Testes cobrem atraso de pivôs, estabilidade dos eventos em cada prefixo temporal, pavio versus fechamento, alta/baixa/faixa, possível mudança sem reversão imediata, preenchimento de faixa, alvo estrutural mais próximo, histórico insuficiente ou descontínuo, toque sem confirmação, invalidação, cobertura histórica, sequência completa e expiração, e bloqueio de dados antigos sem mutar snapshot.
- Limitação: a automação de navegador falhou ao iniciar (`helper_unknown_error: setup refresh had errors`). A interface foi compilada e teve renderização testada, mas a inspeção visual e interações em navegador não puderam ser verificadas nesta sessão.
- Não foi realizado backtest de rentabilidade do novo operacional. Carteira e backtest anteriores continuam associados aos filtros de médias.
