# Backtest Engine Configuration
# Institutional-grade backtesting parameters

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class BacktestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", env_prefix="BACKTEST_")

    # Walk-forward
    train_months: int = 6
    test_months: int = 2
    min_train_samples: int = 500

    # Purged K-Fold
    n_splits: int = 5
    embargo_pct: float = 0.01  # 1% of data as embargo

    # Monte Carlo
    mc_paths: int = 10000
    t_distribution_nu: float = 4.0  # Fat tails for crypto

    # Costs
    maker_fee_bps: float = 2.0    # 0.02%
    taker_fee_bps: float = 5.0    # 0.05%
    slippage_swing_bps: float = 5.0   # 0.05%
    slippage_scalp_bps: float = 10.0  # 0.10%
    latency_ms: int = 100

    # Metrics thresholds (from charter §13)
    min_deflated_sharpe: float = 0.8
    max_pbo: float = 0.30
    min_mc_p5_equity_pct: float = 0.70  # P5 equity > 70% of capital

    # Segmentation
    segment_by: List[str] = ["symbol", "timeframe", "regime", "session", "hour", "day"]

    # Output
    save_detailed: bool = True
    output_dir: str = "backtest_results"


backtest_settings = BacktestSettings()
