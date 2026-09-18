# Validação local — 18/09/2026

- Backend: 66 testes aprovados; cobertura total de aproximadamente 49%.
- Frontend: 6 testes de integridade/falha da fonte aprovados; TypeScript e lint aprovados.
- Compilação de produção aprovada; gráfico de candles conferido no navegador.
- Consulta real: GET /api/market/btc retornou HTTP 200, fonte Binance Spot e 120 candles de BTC/USDT.
- O backend foi importado com sucesso, registrando 27 rotas.
- Python local 3.13; dependências de teste instaladas em .venv. Algumas versões locais
  diferem das fixadas em requirements.txt para a imagem Python 3.12.
- Docker não está instalado neste ambiente; PostgreSQL, Redis, persistência e a stack
  completa não foram verificados ponta a ponta.
- Dois testes legados A6/A7 no arquivo test_signal_core.py são placeholders sem asserts.
  O resultado agregado não substitui validação de integração, backtest real ou auditoria da estratégia.
