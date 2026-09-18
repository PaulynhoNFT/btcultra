-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ============================================================
-- CANDLES (hypertable)
-- ============================================================
CREATE TABLE candles (
    timestamp        TIMESTAMPTZ       NOT NULL,
    symbol           TEXT              NOT NULL,
    timeframe        TEXT              NOT NULL,  -- '1m', '5m', '15m', '1h', '4h', '1d'
    open             DOUBLE PRECISION  NOT NULL,
    high             DOUBLE PRECISION  NOT NULL,
    low              DOUBLE PRECISION  NOT NULL,
    close            DOUBLE PRECISION  NOT NULL,
    volume           DOUBLE PRECISION  NOT NULL,
    source           TEXT              NOT NULL DEFAULT 'ccxt',  -- exchange source
    is_final         BOOLEAN           NOT NULL DEFAULT true,    -- false = candle still open
    ingested_at      TIMESTAMPTZ       NOT NULL DEFAULT now()
);

SELECT create_hypertable('candles', 'timestamp', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);

CREATE UNIQUE INDEX idx_candles_unique ON candles (symbol, timeframe, timestamp);
CREATE INDEX idx_candles_symbol_tf_time ON candles (symbol, timeframe, timestamp DESC);

-- Continuous aggregates for common timeframes
CREATE MATERIALIZED VIEW candles_5m
WITH (timescaledb.continuous) AS
SELECT time_bucket('5 minutes', timestamp) AS bucket,
       symbol,
       FIRST(open, timestamp) AS open,
       MAX(high) AS high,
       MIN(low) AS low,
       LAST(close, timestamp) AS close,
       SUM(volume) AS volume
FROM candles
WHERE timeframe = '1m'
GROUP BY bucket, symbol
WITH NO DATA;

CREATE MATERIALIZED VIEW candles_1h
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', timestamp) AS bucket,
       symbol,
       FIRST(open, timestamp) AS open,
       MAX(high) AS high,
       MIN(low) AS low,
       LAST(close, timestamp) AS close,
       SUM(volume) AS volume
FROM candles
WHERE timeframe = '1m'
GROUP BY bucket, symbol
WITH NO DATA;

-- Refresh policies
ADD_CONTINUOUS_AGGREGATE_POLICY('candles_5m', start_offset => INTERVAL '10 minutes', end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '1 minute');
ADD_CONTINUOUS_AGGREGATE_POLICY('candles_1h', start_offset => INTERVAL '2 hours', end_offset => INTERVAL '10 minutes', schedule_interval => INTERVAL '10 minutes');

-- Retention policies (match §4.3)
SELECT add_retention_policy('candles', INTERVAL '90 days', if_not_exists => TRUE);  -- 1m
-- 5m, 15m: 1 year (handled by continuous aggregates)
-- 1h: 3 years, 1d: 10 years - would need separate tables or partitioning

-- ============================================================
-- ORDERBOOK (recent high-res)
-- ============================================================
CREATE TABLE orderbook_l2 (
    timestamp    TIMESTAMPTZ       NOT NULL,
    symbol       TEXT              NOT NULL,
    exchange     TEXT              NOT NULL,
    bids         JSONB             NOT NULL,  -- [[price, size], ...]
    asks         JSONB             NOT NULL,
    sequence     BIGINT            NOT NULL
);

SELECT create_hypertable('orderbook_l2', 'timestamp', chunk_time_interval => INTERVAL '1 hour', if_not_exists => TRUE);
CREATE INDEX idx_orderbook_symbol_time ON orderbook_l2 (symbol, timestamp DESC);
SELECT add_retention_policy('orderbook_l2', INTERVAL '7 days', if_not_exists => TRUE);

-- ============================================================
-- FUNDING & OPEN INTEREST
-- ============================================================
CREATE TABLE derivatives_data (
    timestamp    TIMESTAMPTZ       NOT NULL,
    symbol       TEXT              NOT NULL,
    exchange     TEXT              NOT NULL,
    funding_rate DOUBLE PRECISION,
    open_interest DOUBLE PRECISION,
    mark_price   DOUBLE PRECISION,
    index_price  DOUBLE PRECISION
);

SELECT create_hypertable('derivatives_data', 'timestamp', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
CREATE UNIQUE INDEX idx_deriv_unique ON derivatives_data (symbol, exchange, timestamp);

-- ============================================================
-- SIGNALS (audit trail)
-- ============================================================
CREATE TABLE signals (
    id              UUID              PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp       TIMESTAMPTZ       NOT NULL,
    symbol          TEXT              NOT NULL,
    timeframe       TEXT              NOT NULL,  -- trigger timeframe
    side            TEXT              NOT NULL,  -- 'BUY', 'SELL'
    score           INTEGER           NOT NULL,
    reason          TEXT              NOT NULL,
    ok              BOOLEAN           NOT NULL,
    entry_price     DOUBLE PRECISION  NOT NULL,
    stop_price      DOUBLE PRECISION  NOT NULL,
    tp1             DOUBLE PRECISION  NOT NULL,
    tp2             DOUBLE PRECISION  NOT NULL,
    tp3             DOUBLE PRECISION  NOT NULL,
    rr              DOUBLE PRECISION  NOT NULL,
    mode            TEXT              NOT NULL,  -- 'swing', 'scalp'
    engine_version  TEXT              NOT NULL,
    score_version   TEXT              NOT NULL,
    risk_version    TEXT              NOT NULL,
    snapshot_hash   TEXT              NOT NULL,  -- sha256 of full snapshot
    snapshot_json   JSONB             NOT NULL,  -- full indicator snapshot
    created_at      TIMESTAMPTZ       NOT NULL DEFAULT now()
);

CREATE INDEX idx_signals_symbol_time ON signals (symbol, timestamp DESC);
CREATE INDEX idx_signals_ok_time ON signals (ok, timestamp DESC);

-- ============================================================
-- SIGNAL SNAPSHOTS (immutable, for replay)
-- ============================================================
CREATE TABLE signal_snapshots (
    signal_id       UUID              PRIMARY KEY REFERENCES signals(id),
    tf1_indicators  JSONB             NOT NULL,
    tf2_indicators  JSONB             NOT NULL,
    tf3_indicators  JSONB             NOT NULL,
    regime_report   JSONB             NOT NULL,
    correction_report JSONB           NOT NULL,
    trigger_report  JSONB             NOT NULL,
    score_breakdown JSONB             NOT NULL,
    derivatives_ctx JSONB,
    news_blackout   BOOLEAN           NOT NULL DEFAULT false,
    candle_hashes   JSONB             NOT NULL,  -- {tf1: hash, tf2: hash, tf3: hash}
    ipfs_cid        TEXT              -- optional IPFS pin
);

-- ============================================================
-- SHADOW PORTFOLIO (blocked signals)
-- ============================================================
CREATE TABLE shadow_portfolio (
    id              UUID              PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id       UUID              NOT NULL REFERENCES signals(id),
    block_reason    TEXT              NOT NULL,  -- which N-rule blocked it
    entry_price     DOUBLE PRECISION  NOT NULL,
    stop_price      DOUBLE PRECISION  NOT NULL,
    tp1             DOUBLE PRECISION  NOT NULL,
    tp2             DOUBLE PRECISION  NOT NULL,
    tp3             DOUBLE PRECISION  NOT NULL,
    rr              DOUBLE PRECISION  NOT NULL,
    score           INTEGER           NOT NULL,
    outcome         TEXT,             -- 'win', 'loss', 'open', 'expired'
    pnl_r           DOUBLE PRECISION, -- realized R multiple
    closed_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ       NOT NULL DEFAULT now()
);

CREATE INDEX idx_shadow_signal ON shadow_portfolio (signal_id);
CREATE INDEX idx_shadow_outcome ON shadow_portfolio (outcome);

-- ============================================================
-- WEIGHTS HISTORY (meta-learning)
-- ============================================================
CREATE TABLE weights_history (
    id              UUID              PRIMARY KEY DEFAULT gen_random_uuid(),
    version         TEXT              NOT NULL,
    weights         JSONB             NOT NULL,  -- feature -> weight
    feature_importance JSONB          NOT NULL,
    trained_on_from TIMESTAMPTZ       NOT NULL,
    trained_on_to   TIMESTAMPTZ       NOT NULL,
    n_signals       INTEGER           NOT NULL,
    oos_sharpe      DOUBLE PRECISION,
    oos_pbo         DOUBLE PRECISION,
    created_at      TIMESTAMPTZ       NOT NULL DEFAULT now()
);

-- ============================================================
-- USERS & AUTH
-- ============================================================
CREATE TABLE users (
    id              UUID              PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT              UNIQUE NOT NULL,
    password_hash   TEXT              NOT NULL,
    totp_secret     TEXT,             -- encrypted, for 2FA
    totp_enabled    BOOLEAN           NOT NULL DEFAULT false,
    plan            TEXT              NOT NULL DEFAULT 'free',  -- 'free', 'pro', 'institutional'
    quota_daily     INTEGER           NOT NULL DEFAULT 100,
    quota_monthly   INTEGER           NOT NULL DEFAULT 1000,
    is_active       BOOLEAN           NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ       NOT NULL DEFAULT now(),
    last_login      TIMESTAMPTZ
);

CREATE TABLE refresh_tokens (
    id              UUID              PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID              NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      TEXT              NOT NULL,
    expires_at      TIMESTAMPTZ       NOT NULL,
    created_at      TIMESTAMPTZ       NOT NULL DEFAULT now(),
    revoked_at      TIMESTAMPTZ
);

CREATE INDEX idx_refresh_user ON refresh_tokens (user_id);
CREATE INDEX idx_refresh_expires ON refresh_tokens (expires_at);

-- ============================================================
-- API KEYS (encrypted)
-- ============================================================
CREATE TABLE user_api_keys (
    id              UUID              PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID              NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exchange        TEXT              NOT NULL,
    api_key_enc     TEXT              NOT NULL,  -- AES-256-GCM encrypted
    api_secret_enc  TEXT              NOT NULL,
    passphrase_enc  TEXT,             -- for OKX
    label           TEXT,
    is_active       BOOLEAN           NOT NULL DEFAULT true,
    permissions     JSONB             NOT NULL DEFAULT '{"read": true, "trade": false}',
    created_at      TIMESTAMPTZ       NOT NULL DEFAULT now(),
    last_used       TIMESTAMPTZ
);

CREATE UNIQUE INDEX idx_user_exchange ON user_api_keys (user_id, exchange) WHERE is_active;

-- ============================================================
-- PAPER TRADING
-- ============================================================
CREATE TABLE paper_trades (
    id              UUID              PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID              NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    signal_id       UUID              REFERENCES signals(id),
    symbol          TEXT              NOT NULL,
    side            TEXT              NOT NULL,
    entry_price     DOUBLE PRECISION  NOT NULL,
    stop_price      DOUBLE PRECISION  NOT NULL,
    tp1             DOUBLE PRECISION  NOT NULL,
    tp2             DOUBLE PRECISION  NOT NULL,
    tp3             DOUBLE PRECISION  NOT NULL,
    size_usd        DOUBLE PRECISION  NOT NULL,
    leverage        INTEGER           NOT NULL DEFAULT 1,
    status          TEXT              NOT NULL DEFAULT 'open',  -- 'open', 'closed', 'cancelled'
    pnl_r           DOUBLE PRECISION,
    closed_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ       NOT NULL DEFAULT now()
);

CREATE INDEX idx_paper_user ON paper_trades (user_id, created_at DESC);

-- ============================================================
-- ECONOMIC CALENDAR (news blackout)
-- ============================================================
CREATE TABLE economic_events (
    id              UUID              PRIMARY KEY DEFAULT gen_random_uuid(),
    event_name      TEXT              NOT NULL,
    country         TEXT              NOT NULL,
    currency        TEXT              NOT NULL,
    impact          TEXT              NOT NULL,  -- 'high', 'medium', 'low'
    forecast        TEXT,
    previous        TEXT,
    event_time      TIMESTAMPTZ       NOT NULL,
    actual          TEXT,
    source          TEXT              NOT NULL,
    created_at      TIMESTAMPTZ       NOT NULL DEFAULT now()
);

CREATE INDEX idx_econ_time ON economic_events (event_time);
CREATE INDEX idx_econ_currency_impact ON economic_events (currency, impact, event_time);

-- ============================================================
-- METRICS (Prometheus scrape target)
-- ============================================================
CREATE TABLE engine_metrics (
    timestamp       TIMESTAMPTZ       NOT NULL,
    metric_name     TEXT              NOT NULL,
    metric_value    DOUBLE PRECISION  NOT NULL,
    labels          JSONB             NOT NULL DEFAULT '{}'
);

SELECT create_hypertable('engine_metrics', 'timestamp', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
CREATE INDEX idx_metrics_name_time ON engine_metrics (metric_name, timestamp DESC);

-- ============================================================
-- AUDIT LOG (immutable chain)
-- ============================================================
CREATE TABLE audit_log (
    id              UUID              PRIMARY KEY DEFAULT gen_random_uuid(),
    prev_hash       TEXT              NOT NULL,
    curr_hash       TEXT              NOT NULL,
    event_type      TEXT              NOT NULL,
    payload         JSONB             NOT NULL,
    timestamp       TIMESTAMPTZ       NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_time ON audit_log (timestamp DESC);
