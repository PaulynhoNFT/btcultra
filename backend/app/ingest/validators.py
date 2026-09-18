# Data Validation — §4.2 Contractual Quality Checks
# All validations run on every incoming candle before persistence

from dataclasses import dataclass
from enum import Enum
from typing import Optional
import numpy as np
import pandas as pd


class ValidationResult(str, Enum):
    OK = "OK"
    GAP_ANOMALY = "GAP_ANOMALY"
    FLASH_CRASH = "FLASH_CRASH"
    CROSS_EXCHANGE_DIVERGENCE = "CROSS_EXCHANGE_DIVERGENCE"
    RSI_ANOMALY = "RSI_ANOMALY"
    INVALID_OHLC = "INVALID_OHLC"
    NEGATIVE_VOLUME = "NEGATIVE_VOLUME"
    STALE_DATA = "STALE_DATA"


@dataclass
class ValidationReport:
    result: ValidationResult
    message: str
    details: dict = None

    @property
    def is_ok(self) -> bool:
        return self.result == ValidationResult.OK


def validate_ohlc_structure(row: pd.Series) -> ValidationReport:
    """Basic OHLC structure: high ≥ max(o,c), low ≤ min(o,c), volume ≥ 0"""
    o, h, l, c, v = row.open, row.high, row.low, row.close, row.volume

    if h < max(o, c):
        return ValidationReport(ValidationResult.INVALID_OHLC, f"high({h}) < max(open,close)={max(o,c)}")
    if l > min(o, c):
        return ValidationReport(ValidationResult.INVALID_OHLC, f"low({l}) > min(open,close)={min(o,c)}")
    if v < 0:
        return ValidationReport(ValidationResult.NEGATIVE_VOLUME, f"volume={v} < 0")
    return ValidationReport(ValidationResult.OK, "OHLC structure valid")


def validate_price_deviation(
    close: float,
    recent_closes: pd.Series,
    sigma_threshold: float = 5.0
) -> ValidationReport:
    """|close - mean| ≤ sigma_threshold * std (rolling)"""
    if len(recent_closes) < 20:
        return ValidationReport(ValidationResult.OK, "Insufficient history for deviation check")

    mean = recent_closes.mean()
    std = recent_closes.std(ddof=0)
    if std == 0:
        return ValidationReport(ValidationResult.OK, "Zero std deviation")

    z_score = abs(close - mean) / std
    if z_score > sigma_threshold:
        return ValidationReport(
            ValidationResult.INVALID_OHLC,
            f"Price deviation {z_score:.2f}σ > {sigma_threshold}σ",
            {"z_score": z_score, "mean": mean, "std": std}
        )
    return ValidationReport(ValidationResult.OK, "Price deviation OK")


def validate_gap_anomaly(
    current_open: float,
    previous_close: float,
    atr: float,
    multiplier: float = 2.0
) -> ValidationReport:
    """Gap > multiplier * ATR(14) → GAP_ANOMALY"""
    if atr is None or atr == 0 or np.isnan(atr):
        return ValidationReport(ValidationResult.OK, "ATR not available")

    gap = abs(current_open - previous_close)
    threshold = multiplier * atr
    if gap > threshold:
        return ValidationReport(
            ValidationResult.GAP_ANOMALY,
            f"Gap {gap:.4f} > {multiplier}×ATR({threshold:.4f})",
            {"gap": gap, "atr": atr, "threshold": threshold}
        )
    return ValidationReport(ValidationResult.OK, "Gap OK")


def validate_flash_crash(
    current_close: float,
    recent_closes: pd.Series,
    threshold_pct: float = 8.0,
    window_min: int = 5
) -> ValidationReport:
    """Variation > threshold_pct in < window_min minutes → flash crash"""
    if len(recent_closes) < window_min:
        return ValidationReport(ValidationResult.OK, "Insufficient history")

    # Check max move in last N candles (assuming 1m timeframe)
    window = recent_closes.iloc[-window_min:]
    max_move = (window.max() - window.min()) / window.iloc[0] * 100
    if max_move > threshold_pct:
        return ValidationReport(
            ValidationResult.FLASH_CRASH,
            f"Flash crash detected: {max_move:.2f}% move in {window_min} min",
            {"max_move_pct": max_move, "window": window_min}
        )
    return ValidationReport(ValidationResult.OK, "Flash crash check OK")


def validate_cross_exchange_divergence(
    prices: dict[str, float],  # {exchange: price}
    threshold_pct: float = 0.5
) -> ValidationReport:
    """Divergence > threshold_pct between exchanges → stress"""
    if len(prices) < 2:
        return ValidationReport(ValidationResult.OK, "Need at least 2 exchanges")

    vals = list(prices.values())
    max_p = max(vals)
    min_p = min(vals)
    divergence = (max_p - min_p) / min_p * 100

    if divergence > threshold_pct:
        return ValidationReport(
            ValidationResult.CROSS_EXCHANGE_DIVERGENCE,
            f"Cross-exchange divergence {divergence:.3f}% > {threshold_pct}%",
            {"prices": prices, "divergence_pct": divergence}
        )
    return ValidationReport(ValidationResult.OK, "Cross-exchange OK")


def validate_rsi_anomaly(
    current_rsi: float,
    recent_rsi: pd.Series,
    sigma_threshold: float = 4.0,
    lookback: int = 100
) -> ValidationReport:
    """RSI > sigma_threshold * std of last lookback → suspect data"""
    if len(recent_rsi) < min(20, lookback):
        return ValidationReport(ValidationResult.OK, "Insufficient RSI history")

    recent = recent_rsi.iloc[-lookback:]
    mean = recent.mean()
    std = recent.std(ddof=0)
    if std == 0:
        return ValidationReport(ValidationResult.OK, "Zero RSI std")

    z_score = abs(current_rsi - mean) / std
    if z_score > sigma_threshold:
        return ValidationReport(
            ValidationResult.RSI_ANOMALY,
            f"RSI anomaly: {z_score:.2f}σ from {lookback}-candle mean",
            {"rsi": current_rsi, "z_score": z_score, "mean": mean, "std": std}
        )
    return ValidationReport(ValidationResult.OK, "RSI OK")


def validate_stale_data(
    candle_timestamp: pd.Timestamp,
    timeframe: str,
    max_age_multiplier: float = 1.0,
    now: pd.Timestamp = None
) -> ValidationReport:
    """Candle age > timeframe * multiplier → STALE_DATA"""
    if now is None:
        now = pd.Timestamp.now(tz='UTC')

    tf_minutes = {
        '1m': 1, '5m': 5, '15m': 15, '30m': 30,
        '1h': 60, '2h': 120, '4h': 240, '6h': 360,
        '12h': 720, '1d': 1440
    }
    period_min = tf_minutes.get(timeframe, 60)
    max_age = pd.Timedelta(minutes=period_min * max_age_multiplier)
    age = now - candle_timestamp

    if age > max_age:
        return ValidationReport(
            ValidationResult.STALE_DATA,
            f"Candle age {age} > {max_age} (TF={timeframe}×{max_age_multiplier})",
            {"age_seconds": age.total_seconds(), "max_age_seconds": max_age.total_seconds()}
        )
    return ValidationReport(ValidationResult.OK, "Data freshness OK")


def run_all_validations(
    row: pd.Series,
    recent_data: pd.DataFrame,
    cross_exchange_prices: dict = None,
    current_rsi: float = None,
    recent_rsi: pd.Series = None,
    atr: float = None,
    timeframe: str = '1m',
    config: dict = None
) -> list[ValidationReport]:
    """Run all §4.2 validations on a candle"""
    if config is None:
        config = {}

    reports = []

    # 1. OHLC structure
    reports.append(validate_ohlc_structure(row))

    # 2. Price deviation (σ check)
    if len(recent_data) >= 20:
        reports.append(validate_price_deviation(
            row.close,
            recent_data.close,
            config.get('max_price_deviation_sigma', 5.0)
        ))

    # 3. Gap anomaly
    if len(recent_data) >= 1 and atr is not None:
        reports.append(validate_gap_anomaly(
            row.open,
            recent_data.close.iloc[-1],
            atr,
            config.get('gap_atr_multiplier', 2.0)
        ))

    # 4. Flash crash
    if len(recent_data) >= config.get('flash_crash_window_min', 5):
        reports.append(validate_flash_crash(
            row.close,
            recent_data.close,
            config.get('flash_crash_threshold_pct', 8.0),
            config.get('flash_crash_window_min', 5)
        ))

    # 5. Cross-exchange divergence
    if cross_exchange_prices and len(cross_exchange_prices) >= 2:
        reports.append(validate_cross_exchange_divergence(
            cross_exchange_prices,
            config.get('cross_exchange_divergence_pct', 0.5)
        ))

    # 6. RSI anomaly
    if current_rsi is not None and recent_rsi is not None and len(recent_rsi) >= 20:
        reports.append(validate_rsi_anomaly(
            current_rsi,
            recent_rsi,
            config.get('rsi_anomaly_sigma', 4.0),
            config.get('rsi_lookback', 100)
        ))

    # 7. Stale data
    reports.append(validate_stale_data(
        row.name if hasattr(row, 'name') else pd.Timestamp.now(tz='UTC'),
        timeframe,
        config.get('stale_threshold_multiplier', 1.0)
    ))

    return reports
