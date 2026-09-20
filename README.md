# BTC Ultra

Aplicação pessoal de acompanhamento e análise de BTC/USDT com dados reais da Binance Spot.
O fluxo funcional inclui coleta, análise Triple Screen, filtros, histórico auditável,
carteira simulada e backtest. Não envia ordens à corretora.

## Executar no Windows

Pré-requisitos: Python 3.13 e Node.js 22 ou superior.

```powershell
.\start-local.ps1
```

O script instala as dependências, compila o painel e inicia dois processos locais ocultos.
Abra **http://127.0.0.1:3000**. A primeira coleta normalmente leva alguns segundos.
Se as portas 3000/8000 já estiverem ocupadas, o script não altera os serviços existentes.
Os logs ficam em `data/logs/`.

Alternativamente, em dois terminais, após instalar as dependências:

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm ci
npm run build
npm run start -- --hostname 127.0.0.1
```

## O que funciona

- Cotação, variação e volume de 24h; gráfico com 120 candles horários reais.
- Coleta automática a cada minuto: até 400 candles diários, 400 de 4h e 1.000 de 1h.
- Apenas candles fechados alimentam o motor. Lacunas, duplicações, preços inválidos,
  relógio inconsistente e dados antigos bloqueiam novas decisões.
- Tela 1: tendência diária e regime; tela 2: correção em 4h; tela 3: confirmações em 1h.
- Score com componentes, motivo para aguardar e plano com entrada, stop e TP1/TP2/TP3
  quando os filtros técnicos produzem um plano válido.
- Calendário semanal real Forex Factory/Fair Economy. Eventos de alto impacto em USD
  bloqueiam novas entradas por ±15 minutos. Calendário ausente ou vencido bloqueia entradas.
- Histórico persistente em SQLite. Cada snapshot contém os 600 candles utilizados,
  indicadores, decisão, versão do motor e hash SHA-256 reproduzível.
- Carteira virtual de 10.000 USDT: confirmação manual, risco máximo de 1%, exposição
  máxima 1x e custos estimados de 0,10% de taxa + 0,05% de slippage por lado.
- Entrada simulada na próxima abertura de 1 minuto, cancelada se o plano ou os filtros
  deixarem de ser válidos. Uma entrada sem coleta por 3 minutos expira.
- Stop tem prioridade se stop e TP2 forem atingidos no mesmo candle. Gaps no stop
  são executados no preço de abertura; saída integral em TP2. TP1/TP3 são referências.
- Cancelamento de entrada e encerramento manual pela cotação real, com confirmação.
- Limites de perdas: 300 USDT/dia, 700/7 dias e 1.500/30 dias, sobre o capital inicial.
  Três perdas reduzem o risco à metade; cinco perdas causam pausa de 24 horas.
- Backtest técnico de 7 ou 30 dias, com aquecimento, entrada na abertura seguinte,
  custos, stop/TP2 intrabar, histórico de operações e resultado persistente.

O backtest não inclui calendário macro histórico nem todos os filtros de carteira ao vivo.
A queda máxima é medida na curva de fechamentos horários e nas saídas registradas.
Venda na simulação é uma posição curta hipotética; não é uma ordem de venda Spot
nem inclui empréstimo ou funding. Zero operações é um resultado válido.

## Dados e privacidade

Banco local: `backend/data/btcultra.sqlite3` (fora do Git). O histórico começa na primeira
coleta e sobrevive a reinícios. Para mudar a pasta, defina `BTC_DATA_DIR`.

Este modo é de uso pessoal/local, sem contas de usuário. API e painel são vinculados
à interface local; as escritas verificam a origem do painel. Publicação multiusuário
na internet exige autenticação e autorização adicionais; não exponha este modo local
como um serviço público. Nenhuma chave de exchange é necessária.

As únicas fontes de preços são os endpoints oficiais de mercado da Binance:
https://developers.binance.com/docs/binance-spot-api-docs/faqs/market_data_only

Calendário: https://nfs.faireconomy.media/ff_calendar_thisweek.json

Dados sintéticos existem apenas nos testes automatizados isolados. Não alimentam o painel,
a carteira do usuário ou o histórico publicado. Falhas não são substituídas por preços inventados.

## Testar

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
cd backend
..\.venv\Scripts\python.exe -m pytest tests -q --cov=app.live --cov=app.main
```

```powershell
cd frontend
npm test
npm run type-check
npm run lint
npm run build
```

Os testes novos verificam dados incompletos, replay determinístico, persistência após
reinício, falhas da fonte, calendário, confirmação, duplicação, custos, cancelamento,
expiração, limites de risco e ausência de candles futuros no backtest.

## Docker opcional

```sh
docker compose up -d --build
```

O Compose atual usa apenas os dois serviços funcionais e um volume persistente SQLite,
com portas expostas somente em localhost. A configuração foi preparada, mas a imagem
não foi executada neste computador porque Docker não está instalado.

## Código anterior

O planejamento original está em `docs/architecture-plan.md`. A antiga inicialização
PostgreSQL/TimescaleDB está em `app/legacy_main.py`, `requirements-legacy.txt` e
`docker-compose.legacy.yml`; ela não é usada pelo aplicativo local atual. Os módulos
antigos de pesquisa permanecem para referência e possuem testes próprios. Recursos
como meta-modelo ML, alertas externos e múltiplos usuários não fazem parte deste modo pessoal.

Esta ferramenta não constitui recomendação de investimento. Resultado passado não garante resultado futuro.

## Leitura de estrutura no gráfico

O painel abre com a interpretação automática das aulas de Alexandre Fornes: estrutura no diário, regiões em 4 horas e confirmação em 1 hora. Marcações e explicações usam as velas reais do snapshot. Os filtros de médias do Triple Screen, carteira e backtest permanecem separados. Consulte [regras, sequência e limites](docs/fornes-operacional.md).
