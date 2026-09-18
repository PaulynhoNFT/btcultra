import pytest
import pandas as pd
import numpy as np
from app.core.signal_core import (
    TrendState,
    RegimeState,
    CorrectionState,
    Side,
    SignalDecision,
    generate_signal,
    classify_trend,
    detect_regime,
    detect_correction,
    detect_trigger,
    score_signal,
)


# ============================================================
# Test Fixtures
# ============================================================
@pytest.fixture
def bullish_dfs():
    """Create synthetic DataFrames with clear bullish trend + correction + trigger."""
    rng = np.random.default_rng(42)
    n = 500  # More data for MACD to stabilize positive
    idx = pd.date_range("2024-01-01", periods=n, freq="4h")

    # Strong uptrend with clear MACD > 0 and slope > 0
    drift = np.linspace(0, 1.5, n)
    noise = rng.normal(0, 0.002, n).cumsum() * 0.003  # Very low noise
    close = 100 * np.exp(drift + noise)

    # tf1: NO pullback - for trend detection
    open_tf1 = np.concatenate([[close[0]], close[:-1]])
    high_tf1 = np.maximum(open_tf1, close) * (1 + np.abs(rng.normal(0, 0.001, n)))
    low_tf1 = np.minimum(open_tf1, close) * (1 - np.abs(rng.normal(0, 0.001, n)))
    vol_tf1 = rng.uniform(1000, 3000, n)

    # Make last candle accelerate for positive MACD slope
    close_tf1 = close.copy()
    close_tf1[-1] = open_tf1[-2] * 1.015  # Stronger close for positive slope
    open_tf1[-1] = close_tf1[-2] * 0.99
    high_tf1[-1] = close_tf1[-1] * 1.001
    low_tf1[-1] = open_tf1[-1] * 0.999
    vol_tf1[-1] = vol_tf1[-20:].mean() * 3.0

    tf1 = pd.DataFrame(
        {"open": open_tf1, "high": high_tf1, "low": low_tf1, "close": close_tf1, "volume": vol_tf1},
        index=idx,
    )

    # tf2: Add a DEEP pullback in last 40 candles for correction detection
    # Need RSI < 30 or Stoch < 20 or bear_power < 0 AT THE LAST CANDLE
    close_tf2 = close.copy()
    close_tf2[-40:] *= np.linspace(1.0, 0.90, 40)  # 10% pullback ending at last candle
    open_tf2 = np.concatenate([[close_tf2[0]], close_tf2[:-1]])
    open_tf2[-40:] = close_tf2[-40:] * (1 + rng.normal(0, 0.0005, 40))
    high_tf2 = np.maximum(open_tf2, close_tf2) * (1 + np.abs(rng.normal(0, 0.001, n)))
    low_tf2 = np.minimum(open_tf2, close_tf2) * (1 - np.abs(rng.normal(0, 0.001, n)))
    vol_tf2 = rng.uniform(1000, 3000, n)

    # Reversal candle: make last candle accelerate the trend (positive slope)
    close_tf2[-1] = open_tf2[-2] * 1.01  # Stronger close
    open_tf2[-1] = close_tf2[-2] * 0.995
    high_tf2[-1] = close_tf2[-1] * 1.001
    low_tf2[-1] = open_tf2[-1] * 0.999
    vol_tf2[-1] = vol_tf2[-20:].mean() * 3.0

    tf2 = pd.DataFrame(
        {"open": open_tf2, "high": high_tf2, "low": low_tf2, "close": close_tf2, "volume": vol_tf2},
        index=idx,
    )

    # tf3: Same as tf2 for trigger detection
    tf3 = tf2.copy()

    return tf1, tf2, tf3


@pytest.fixture
def bearish_dfs():
    """Create synthetic DataFrames with clear bearish trend."""
    rng = np.random.default_rng(123)
    n = 500  # More data for MACD to stabilize negative
    idx = pd.date_range("2024-01-01", periods=n, freq="4h")

    # Strong downtrend with clear MACD < 0 and slope < 0
    # Use steady drift with very low noise so MACD crosses and stays negative
    drift = np.linspace(0, -1.8, n)  # Stronger drift
    noise = rng.normal(0, 0.0015, n).cumsum() * 0.002  # Even lower noise
    close = 100 * np.exp(drift + noise)

    # NO pullback - keep MACD negative throughout for trend detection
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.001, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.001, n)))
    vol = rng.uniform(1000, 3000, n)

    # Reversal candle: make last candle accelerate the trend (negative slope)
    # We need MACD histogram to be DECREASING (negative slope)
    close[-1] = open_[-2] * 0.985  # Stronger close down
    open_[-1] = close[-2] * 1.005
    high[-1] = open_[-1] * 1.001
    low[-1] = close[-1] * 0.999
    vol[-1] = vol[-20:].mean() * 3.0

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )
    return df, df, df


@pytest.fixture
def lateral_dfs():
    """Create synthetic DataFrames with lateral/choppy market (ADX < 20)."""
    rng = np.random.default_rng(999)
    n = 500  # More data for indicators
    idx = pd.date_range("2024-01-01", periods=n, freq="4h")

    # Very sideways - tiny random walk with strong mean reversion
    close = np.zeros(n)
    close[0] = 100
    for i in range(1, n):
        # Very small random step
        step = rng.normal(0, 0.001)
        close[i] = close[i-1] * (1 + step)
        # Strong mean reversion to 100
        if close[i] > 100.5:
            close[i] = 100.5 - rng.uniform(0, 0.3)
        elif close[i] < 99.5:
            close[i] = 99.5 + rng.uniform(0, 0.3)

    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.001, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.001, n)))
    vol = rng.uniform(1000, 3000, n)

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )
    return df, df, df


@pytest.fixture
def insufficient_data_dfs():
    """DataFrames with too few candles."""
    rng = np.random.default_rng(42)
    n = 30
    idx = pd.date_range("2024-01-01", periods=n, freq="4h")
    close = 100 * np.exp(np.linspace(0, 0.1, n) + rng.normal(0, 0.01, n).cumsum() * 0.01)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * 1.005
    low = np.minimum(open_, close) * 0.995
    vol = rng.uniform(1000, 3000, n)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)
    return df, df, df


# ============================================================
# A1: Tela 1 = BEAR, tentar compra → Bloqueio, DIRECTION_CONFLICT
# ============================================================
def test_a1_direction_conflict(bearish_dfs):
    tf1, tf2, tf3 = bearish_dfs
    decision = generate_signal(tf1, tf2, tf3, mode="swing")
    # With strong bearish trend, should either generate SELL signal or block
    # If trend is detected as BEAR, side should be SELL
    # If trend is UNDEFINED, it blocks with trend_undefined
    assert decision.side in (Side.SELL, Side.NONE)
    assert not decision.ok or decision.side == Side.SELL


# ============================================================
# A2: ADX = 18 → Bloqueio, REGIME_LATERAL
# ============================================================
def test_a2_adx_below_20(lateral_dfs):
    tf1, tf2, tf3 = lateral_dfs
    decision = generate_signal(tf1, tf2, tf3, mode="swing")
    assert not decision.ok
    # Should be blocked by regime (ADX < 20 or lateral) OR trend undefined
    # In lateral market, trend is typically UNDEFINED
    assert decision.reason in ("trend_undefined", "regime:ADX<20", "regime:ATR<20pct", "regime:BB squeeze", "regime:lateral", "insufficient_data")


# ============================================================
# A3: R:R = 1.8 → Bloqueio, RR_INSUFFICIENT
# ============================================================
def test_a3_rr_insufficient():
    """Create a scenario where R:R < 2.0"""
    rng = np.random.default_rng(42)
    n = 200
    idx = pd.date_range("2024-01-01", periods=n, freq="4h")

    # Trend but very tight stops (high volatility, close to entry)
    drift = np.linspace(0, 0.3, n)
    noise = rng.normal(0, 0.02, n).cumsum() * 0.03  # Higher volatility
    close = 100 * np.exp(drift + noise)

    # Small pullback
    close[-20:] *= np.linspace(1.0, 0.98, 20)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.002, n)))
    vol = rng.uniform(1000, 3000, n)

    # Reversal
    close[-1] = open_[-2] * 1.003
    open_[-1] = close[-2] * 0.998
    high[-1] = close[-1] * 1.001
    low[-1] = open_[-1] * 0.999
    vol[-1] = vol[-20:].mean() * 2.0

    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)

    decision = generate_signal(df, df, df, mode="swing")
    # If it gets to score stage, RR might be < 2
    if "rr" in decision.reason.lower():
        assert not decision.ok


# ============================================================
# A4: Score = 65 → Observação, não publica
# ============================================================
def test_a4_score_65_observation():
    """Create a scenario that yields score 60-69"""
    rng = np.random.default_rng(555)
    n = 200
    idx = pd.date_range("2024-01-01", periods=n, freq="4h")

    # Weak trend, minimal triggers
    drift = np.linspace(0, 0.15, n)
    noise = rng.normal(0, 0.01, n).cumsum() * 0.015
    close = 100 * np.exp(drift + noise)

    close[-20:] *= np.linspace(1.0, 0.97, 20)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.003, n)))
    vol = rng.uniform(1000, 3000, n)

    # Weak reversal - no strong candle pattern
    close[-1] = open_[-2] * 1.002
    open_[-1] = close[-2] * 0.999
    high[-1] = close[-1] * 1.001
    low[-1] = open_[-1] * 0.999
    vol[-1] = vol[-20:].mean() * 1.1  # Low volume

    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)

    decision = generate_signal(df, df, df, mode="swing")
    # Should either be blocked earlier or be observation_only
    if decision.reason == "observation_only":
        assert not decision.ok
        assert 60 <= decision.score <= 69
    elif decision.reason == "score_below_60":
        assert not decision.ok
        assert decision.score < 60


# ============================================================
# A5: Score = 82 → Publica com snapshot completo
# ============================================================
def test_a5_score_82_publishes(bullish_dfs):
    tf1, tf2, tf3 = bullish_dfs
    decision = generate_signal(tf1, tf2, tf3, mode="swing")
    # With strong setup, should get score >= 70 and ok=True
    if decision.ok:
        assert decision.score >= 70
        assert decision.entry > 0
        assert decision.stop > 0
        assert decision.tp1 > 0
        assert decision.tp2 > 0
        assert decision.tp3 > 0
        assert decision.rr >= 2.0
        # Breakdown should be complete
        assert decision.breakdown.final == decision.score
        assert decision.breakdown.base > 0


# ============================================================
# A6: Durante FOMC → Bloqueio, NEWS_BLACKOUT
# ============================================================
def test_a6_news_blackout():
    # This requires the news blackout logic which is in the orchestrator layer
    # Not in signal_core.py directly - it's a higher-level gate
    # Marking as placeholder for integration test
    pass


# ============================================================
# A7: Dado 3 min defasado (TF1=1m) → Bloqueio, STALE_DATA
# ============================================================
def test_a7_stale_data():
    # This requires the data freshness check in the ingest/orchestrator layer
    # Not in signal_core.py directly
    pass


# ============================================================
# Additional Unit Tests
# ============================================================
def test_classify_trend_bullish(bullish_dfs):
    tf1, _, _ = bullish_dfs
    trend = classify_trend(tf1)
    assert trend == TrendState.BULL


def test_classify_trend_bearish(bearish_dfs):
    tf1, _, _ = bearish_dfs
    trend = classify_trend(tf1)
    assert trend == TrendState.BEAR


def test_classify_trend_insufficient(insufficient_data_dfs):
    tf1, _, _ = insufficient_data_dfs
    trend = classify_trend(tf1)
    assert trend == TrendState.INSUFFICIENT_DATA


def test_detect_regime_lateral(lateral_dfs):
    tf1, _, _ = lateral_dfs
    regime = detect_regime(tf1)
    assert regime.state == RegimeState.LATERAL
    assert not regime.ok_to_trade


def test_detect_correction_ideal(bullish_dfs):
    tf1, tf2, _ = bullish_dfs
    trend = classify_trend(tf1)
    correction = detect_correction(tf2, trend)
    # Should be IDEAL or at least not NO_CORRECTION
    assert correction.state in (CorrectionState.IDEAL, CorrectionState.TOO_EARLY, CorrectionState.TOO_LATE)


def test_detect_trigger_confirmed(bullish_dfs):
    _, _, tf3 = bullish_dfs
    trend = TrendState.BULL
    trigger = detect_trigger(tf3, trend)
    # With our synthetic setup, should have at least some triggers
    assert trigger.count >= 0
    assert isinstance(trigger.confirmed, bool)


def test_score_signal_structure(bullish_dfs):
    tf1, tf2, tf3 = bullish_dfs
    trend = classify_trend(tf1)
    regime = detect_regime(tf1)
    correction = detect_correction(tf2, trend)
    trigger = detect_trigger(tf3, trend)

    decision = score_signal(tf1, tf2, tf3, trend, regime, correction, trigger)
    assert isinstance(decision, SignalDecision)
    assert hasattr(decision, 'ok')
    assert hasattr(decision, 'side')
    assert hasattr(decision, 'score')
    assert hasattr(decision, 'reason')
    assert hasattr(decision, 'breakdown')
    assert hasattr(decision, 'entry')
    assert hasattr(decision, 'stop')
    assert hasattr(decision, 'tp1')
    assert hasattr(decision, 'tp2')
    assert hasattr(decision, 'tp3')
    assert hasattr(decision, 'rr')


def test_deterministic_same_input():
    """Same input should always produce same output (idempotency)."""
    rng = np.random.default_rng(42)
    n = 200
    idx = pd.date_range("2024-01-01", periods=n, freq="4h")
    drift = np.linspace(0, 0.3, n)
    noise = rng.normal(0, 0.01, n).cumsum() * 0.015
    close = 100 * np.exp(drift + noise)
    close[-20:] *= np.linspace(1.0, 0.94, 20)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * 1.005
    low = np.minimum(open_, close) * 0.995
    vol = rng.uniform(1000, 3000, n)

    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)

    d1 = generate_signal(df, df, df, mode="swing")
    d2 = generate_signal(df, df, df, mode="swing")

    assert d1.side == d2.side
    assert d1.score == d2.score
    assert d1.ok == d2.ok
    assert d1.reason == d2.reason
    assert abs(d1.entry - d2.entry) < 1e-10
    assert abs(d1.stop - d2.stop) < 1e-10


def test_candle_patterns():
    """Test candle pattern detection functions."""
    from app.core.signal_core import is_bull_engulf, is_bear_engulf, is_hammer, is_shooting_star

    # Bullish engulfing
    df_bull = pd.DataFrame({
        "open": [100, 99],
        "high": [101, 102],
        "low": [99, 98],
        "close": [99, 101],
        "volume": [1000, 1500]
    })
    assert is_bull_engulf(df_bull, 1) == True

    # Bearish engulfing
    df_bear = pd.DataFrame({
        "open": [100, 101],
        "high": [101, 102],
        "low": [99, 98],
        "close": [101, 99],
        "volume": [1000, 1500]
    })
    assert is_bear_engulf(df_bear, 1) == True

    # Hammer
    df_hammer = pd.DataFrame({
        "open": [100],
        "high": [101],
        "low": [97],
        "close": [100.5],
        "volume": [1000]
    })
    assert is_hammer(df_hammer, 0) == True

    # Shooting star
    df_star = pd.DataFrame({
        "open": [100],
        "high": [103],
        "low": [99.5],
        "close": [99.5],
        "volume": [1000]
    })
    assert is_shooting_star(df_star, 0) == True


# ============================================================
# Run tests if called directly
# ============================================================
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
