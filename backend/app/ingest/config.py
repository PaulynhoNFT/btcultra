# Ingest Layer Configuration
# This is a Python module, not a .env file

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class IngestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", env_prefix="INGEST_")

    # Exchange WS endpoints (CCXT Pro handles these)
    # Binance: wss://stream.binance.com:9443/ws
    # Bybit: wss://stream.bybit.com/v5/public/linear
    # OKX: wss://ws.okx.com:8443/api/v5/market/ticker
    # Coinbase: wss://ws-feed.exchange.coinbase.com

    # Timeframes to ingest
    timeframes: List[str] = ["1m", "5m", "15m", "1h", "4h", "1d"]

    # Symbols (high liquidity only per charter)
    symbols: List[str] = ["BTC/USDT"]

    # Validation thresholds (§4.2)
    max_price_deviation_sigma: float = 5.0
    gap_atr_multiplier: float = 2.0
    flash_crash_threshold_pct: float = 8.0
    flash_crash_window_min: int = 5
    cross_exchange_divergence_pct: float = 0.5
    rsi_anomaly_sigma: float = 4.0
    rsi_lookback: int = 100

    # Data quality
    min_candles_for_indicators: int = 120
    stale_threshold_multiplier: float = 1.0  # 1x timeframe period

    # Circuit breakers
    exchange_degraded_threshold: int = 3  # failed connections before marking degraded
    exchange_recovery_time_seconds: int = 60

    # CCXT Pro settings
    ccxt_pro_version: str = "3.1.0"
    ws_reconnect_delay: float = 5.0
    ws_max_retries: int = 10
    ws_ping_interval: int = 30


ingest_settings = IngestSettings()
