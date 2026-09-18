# btcultra — Signal Platform

## Dados reais de Bitcoin

O painel consulta **BTC/USDT na Binance Spot**, pela API pública oficial
`https://data-api.binance.vision`. Não exige chave de corretora.

- Cotação, variação, máxima, mínima e volume das últimas 24 horas.
- Gráfico com 120 candles de uma hora; o candle em formação é identificado.
- Atualização a cada 30 segundos; cache no servidor de até 15 segundos.
- Fonte e horário da cotação visíveis. Preços são em USDT, não BRL.
- Falhas, dados inconsistentes e cotações antigas não são substituídos por preços demonstrativos.
- O painel oculta dados após 90 segundos sem uma cotação recente válida.

### Abrir o painel de mercado

```sh
cd frontend
npm ci
npm run dev
```

Acesse http://localhost:3000. A cotação e o gráfico funcionam sem banco e sem a API Python.
A rota local `GET /api/market/btc` consulta os endpoints reais `/api/v3/ticker/24hr`,
`/api/v3/klines` e `/api/v3/time` da Binance. Indisponibilidade retorna HTTP 503.
Documentação da fonte: https://developers.binance.com/docs/binance-spot-api-docs/faqs/market_data_only

### Estado do restante da plataforma

A API Python, ingestão persistente, regime de mercado e histórico de sinais dependem
de PostgreSQL/TimescaleDB. O histórico privado exige autenticação. O regime fica
indisponível até haver pelo menos 120 candles fechados, contínuos e recentes no banco.
O painel não apresenta sinais ou indicadores inventados para preencher essas ausências.

A coleta está limitada a BTC/USDT Spot na Binance. A chave atual da tabela de candles
não distingue exchanges, portanto a gravação simultânea de várias fontes não está habilitada.
O projeto ainda contém módulos em desenvolvimento; a publicação do código não significa
validação da estratégia, implantação pública do site ou integração completa de todos os serviços.

### Testes

```sh
cd frontend
npm test
npm run type-check
npm run lint
npm run build
```

```sh
cd backend
python -m pytest tests/ -q --cov=app
```

Dados sintéticos existem apenas como fixtures de testes e cenários estatísticos de Monte Carlo;
não são uma fonte de cotação nem uma alternativa para falhas da API de mercado.
Arquivos `.env`, dependências, caches e o documento privado de planejamento não são publicados.

---

## Documentação original da arquitetura e planejamento

As seções abaixo descrevem também funcionalidades planejadas, não necessariamente concluídas.

# Signal Platform — Triple Screen Crypto Signals

Plataforma de sinais cripto baseada no **Triple Screen de Alexander Elder** adaptado para cripto, com **disciplina conservadora**, **transparência radical** e **engenharia de nível institucional**.

## Filosofia

> "Não operar é uma decisão. E é a decisão padrão."

- **Conservador por padrão**: Sinais só são emitidos quando TODOS os gatilhos se alinham
- **Transparência radical**: Todo sinal mostra decomposição completa do score (features + pesos)
- **Reprodutibilidade**: Mesmo input → mesmo output (determinístico, idempotente)
- **Auditoria completa**: Snapshots imutáveis de todos os indicadores no momento do sinal

## Arquitetura (7 Camadas)

```
┌─────────────────────────────────────────────────────────────┐
│  7. UI (Next.js + React + TS + Tailwind + TradingView LWC)  │
├─────────────────────────────────────────────────────────────┤
│  6. API Gateway (FastAPI + JWT + 2FA + Rate Limit)          │
├─────────────────────────────────────────────────────────────┤
│  5. Signal Core │ 4. Risk Engine │ 3. Meta Layer            │
│  (Triple Screen)│ (Breakers)     │ (Meta-labeling, Shadow)   │
├─────────────────────────────────────────────────────────────┤
│  2. Data Layer (TimescaleDB + Redis + S3)                   │
├─────────────────────────────────────────────────────────────┤
│  1. Ingest (CCXT Pro WS: Binance, Bybit, OKX, Coinbase)     │
└─────────────────────────────────────────────────────────────┘
```

## Regras Invioláveis (N1–N12)

| Regra | Descrição | Bloqueio |
|-------|-----------|----------|
| N1 | Nenhum sinal contra a Tela 1 | `DIRECTION_CONFLICT` |
| N2 | Nenhum sinal em mercado lateral (ADX < 20) | `REGIME_LATERAL` |
| N3 | Nenhum sinal com R:R < 2:1 | `RR_INSUFFICIENT` |
| N4 | Score < 70 não publica (60–69 = observação) | `SCORE_BELOW_70` |
| N5 | Sempre stop, TP1/2/3 e sizing | Schema rejeita incompleto |
| N6 | Sempre snapshot completo dos indicadores | Sem snapshot = sem sinal |
| N7 | Nunca com dado defasado (> 1× período) | `STALE_DATA` |
| N8 | Nunca com exchange degradada | Modo degradado global |
| N9 | Nunca durante janela macro (±15 min FOMC/CPI) | `NEWS_BLACKOUT` |
| N10 | Nunca violando circuit breaker | `RISK_CIRCUIT_BREAKER` |
| N11 | Nunca executar ordem sem confirmação humana | Modo leitura padrão |
| N12 | Nunca prometer lucro | Disclaimer + versão do motor |

## Quick Start

### Pré-requisitos
- Docker + Docker Compose
- (Opcional) chaves de API Binance/Bybit/OKX para ingest real

### Subir a stack completa

```bash
cd D:\melhorsitebtc
cp .env.example .env
# Edite .env com suas chaves (opcional para demo)
docker compose up -d --build
```

### Serviços disponíveis

| Serviço | URL | Credenciais |
|---------|-----|-------------|
| API Backend | http://localhost:8000 | - |
| API Docs (Swagger) | http://localhost:8000/docs | - |
| Frontend | http://localhost:3000 | - |
| Grafana | http://localhost:3001 | admin / admin |
| Prometheus | http://localhost:9090 | - |

### Motor de sinais

O motor recebe candles reais da camada de ingestão. A antiga demonstração com
preços gerados aleatoriamente foi removida. Para verificar a cotação pública,
abra o painel ou consulte `http://localhost:3000/api/market/btc`.

### Rodar testes

```bash
cd D:\melhorsitebtc\backend
pytest tests/ -v --cov=app
```

Critérios de aceite (§14):
- A1–A5: Testes unitários do motor
- A11: Backtest 1 ano BTC 4H → Deflated Sharpe ≥ 0.8, PBO < 30%
- A12: Monte Carlo t-Student P5 equity > 0.7× capital

## Estrutura do Projeto

```
melhorsitebtc/
├── backend/
│   ├── app/
│   │   ├── core/signal_core.py      # Motor puro (determinístico)
│   │   ├── routes/auth.py           # JWT + 2FA (TOTP)
│   │   ├── routes/signals.py        # CRUD sinais + shadow portfolio
│   │   ├── models.py                # SQLAlchemy models
│   │   ├── database.py              # Async DB session
│   │   ├── auth.py                  # Auth utils
│   │   ├── config.py                # Pydantic settings
│   │   └── main.py                  # FastAPI app
│   ├── tests/test_signal_core.py    # Testes A1–A5 + unitários
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── app/page.tsx             # Dashboard principal
│   │   ├── components/SignalCard.tsx
│   │   ├── components/RegimeBanner.tsx
│   │   ├── hooks/useSignals.ts
│   │   ├── hooks/useRegime.ts
│   │   └── lib/api.ts               # Axios + WS client
│   ├── package.json
│   └── Dockerfile
├── infra/
│   ├── sql/init.sql                 # Schema TimescaleDB completo
│   ├── prometheus/prometheus.yml
│   └── grafana/provisioning/        # Dashboards + datasources
├── docker-compose.yml
├── .env.example
└── .github/workflows/ci.yml         # CI/CD pipeline
```

## Desenvolvimento

### Backend (FastAPI)
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend (Next.js)
```bash
cd frontend
npm install
npm run dev
```

### Banco de dados
```bash
# Aplicar migrações (Alembic - quando configurado)
alembic upgrade head
```

## Próximas Fases (conforme §10)

| Fase | Duração | Entregável |
|------|---------|------------|
| **F0** ✅ | 2 sem | Infra completa (este repo) |
| **F1** | 3 sem | Ingest CCXT + Motor base + Testes A1–A7 |
| **F2** | 2 sem | Backtest rigoroso (Purged K-Fold, Monte Carlo t-Student) |
| **F3** | 3 sem | Meta-layer (LightGBM, Shadow portfolio, Recalibração) |
| **F4** | 2 sem | Contexto derivativos (Funding, OI, CVD real, Clusters) |
| **F5** | 2 sem | UI completa (TradingView, Decomposição score, Paper trading) |
| **F6** | 2 sem | Alertas (Telegram/Email/Push) + Observabilidade |
| **F7** | 3 sem | Self-learning (HMM, PBO contínuo) |

## Checklist de Lançamento (§13)

Antes do primeiro usuário pagante:
- [ ] Backtest ≥ 1 ano, walk-forward, custos incluídos
- [ ] Deflated Sharpe ≥ 0.8, PBO < 30%
- [ ] Monte Carlo P5 equity > 0.7× capital (risco 1%)
- [ ] Testes A1–A15 passando
- [ ] Shadow portfolio 30 dias com filter_value > 0
- [ ] Meta-model ligado (após 200 sinais) com P(win) ≥ 0.55
- [ ] Modo paper trading ativo para todo usuário novo
- [ ] Disclaimers em toda tela
- [ ] Log imutável com hash chain
- [ ] Replay de qualquer sinal histórico byte a byte
- [ ] Runbook de incidente testado
- [ ] 2FA obrigatório, API keys AES-256-GCM
- [ ] Modo leitura padrão, sem auto-execução
- [ ] Onboarding em 5 sinais
- [ ] Modo "só educacional" 30 dias antes de cobrar

## Stack Técnica

| Camada | Tecnologia |
|--------|------------|
| Frontend | Next.js 14 + React 18 + TypeScript + Tailwind + TradingView Lightweight Charts |
| Backend | Python 3.12 + FastAPI + SQLAlchemy 2.0 + Pydantic 2 |
| Database | PostgreSQL 16 + TimescaleDB (hypertables) + Redis 7 |
| Ingest | CCXT Pro WebSocket (Binance, Bybit, OKX, Coinbase) |
| ML | scikit-learn + LightGBM + hmmlearn |
| Monitoring | Prometheus + Grafana + OpenTelemetry |
| Deploy | Docker + Docker Compose (dev) / AWS ECS ou Railway (prod) |
| CI/CD | GitHub Actions |

## Licença

MIT — Use por sua conta e risco. Não é recomendação de investimento.

---

**Versão do motor:** `triple-screen-v1`  
**Score Engine:** `v1`  
**Risk Engine:** `v1`  
**Charter:** `1.0 — Build Document`