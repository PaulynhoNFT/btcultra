import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from app.ingest.validators import (
    validate_ohlc_structure,
    validate_price_deviation,
    validate_gap_anomaly,
    validate_flash_crash,
    validate_cross_exchange_divergence,
    validate_rsi_anomaly,
    validate_stale_data,
    run_all_validations,
    ValidationResult,
    ValidationReport,
)


class TestValidators:
    """Test all §4.2 validation functions"""

    def test_validate_ohlc_structure_valid(self):
        row = pd.Series({'open': 100, 'high': 102, 'low': 99, 'close': 101, 'volume': 1000})
        report = validate_ohlc_structure(row)
        assert report.is_ok
        assert report.result == ValidationResult.OK

    def test_validate_ohlc_structure_invalid_high(self):
        row = pd.Series({'open': 100, 'high': 99, 'low': 98, 'close': 101, 'volume': 1000})  # high < close
        report = validate_ohlc_structure(row)
        assert not report.is_ok
        assert report.result == ValidationResult.INVALID_OHLC

    def test_validate_ohlc_structure_invalid_low(self):
        row = pd.Series({'open': 100, 'high': 102, 'low': 101, 'close': 99, 'volume': 1000})  # low > open
        report = validate_ohlc_structure(row)
        assert not report.is_ok
        assert report.result == ValidationResult.INVALID_OHLC

    def test_validate_ohlc_structure_negative_volume(self):
        row = pd.Series({'open': 100, 'high': 102, 'low': 99, 'close': 101, 'volume': -100})
        report = validate_ohlc_structure(row)
        assert not report.is_ok
        assert report.result == ValidationResult.NEGATIVE_VOLUME

    def test_validate_price_deviation_ok(self):
        recent = pd.Series([100, 101, 99, 100, 101, 100, 99, 100] * 3)  # 24 points
        report = validate_price_deviation(100.5, recent, sigma_threshold=5.0)
        assert report.is_ok

    def test_validate_price_deviation_anomaly(self):
        recent = pd.Series([100, 101, 99, 100, 101] * 4)  # 20 points with some variance
        report = validate_price_deviation(150, recent, sigma_threshold=5.0)  # 50 sigma!
        assert not report.is_ok
        assert report.result == ValidationResult.INVALID_OHLC

    def test_validate_gap_anomaly_ok(self):
        report = validate_gap_anomaly(100.5, 100.0, atr=1.0, multiplier=2.0)  # gap=0.5 < 2.0
        assert report.is_ok

    def test_validate_gap_anomaly_detected(self):
        report = validate_gap_anomaly(105.0, 100.0, atr=1.0, multiplier=2.0)  # gap=5.0 > 2.0
        assert not report.is_ok
        assert report.result == ValidationResult.GAP_ANOMALY

    def test_validate_flash_crash_ok(self):
        recent = pd.Series([100, 101, 99, 100, 101])  # ~1% moves
        report = validate_flash_crash(100, recent, threshold_pct=8.0, window_min=5)
        assert report.is_ok

    def test_validate_flash_crash_detected(self):
        recent = pd.Series([100, 95, 90, 85, 80])  # 20% drop in 5 min
        report = validate_flash_crash(80, recent, threshold_pct=8.0, window_min=5)
        assert not report.is_ok
        assert report.result == ValidationResult.FLASH_CRASH

    def test_validate_cross_exchange_divergence_ok(self):
        prices = {'binance': 50000, 'bybit': 50020, 'okx': 49990}  # < 0.5%
        report = validate_cross_exchange_divergence(prices, threshold_pct=0.5)
        assert report.is_ok

    def test_validate_cross_exchange_divergence_detected(self):
        prices = {'binance': 50000, 'bybit': 50500}  # 1% divergence
        report = validate_cross_exchange_divergence(prices, threshold_pct=0.5)
        assert not report.is_ok
        assert report.result == ValidationResult.CROSS_EXCHANGE_DIVERGENCE

    def test_validate_rsi_anomaly_ok(self):
        recent_rsi = pd.Series([50] * 100)
        report = validate_rsi_anomaly(55, recent_rsi, sigma_threshold=4.0, lookback=100)
        assert report.is_ok

    def test_validate_rsi_anomaly_detected(self):
        recent_rsi = pd.Series([50 + i * 0.1 for i in range(100)])  # slight trend
        report = validate_rsi_anomaly(95, recent_rsi, sigma_threshold=4.0, lookback=100)  # extreme
        assert not report.is_ok
        assert report.result == ValidationResult.RSI_ANOMALY

    def test_validate_stale_data_ok(self):
        now = pd.Timestamp.now(tz='UTC')
        recent = now - pd.Timedelta(minutes=30)
        report = validate_stale_data(recent, '1h', max_age_multiplier=1.0, now=now)
        assert report.is_ok

    def test_validate_stale_data_detected(self):
        now = pd.Timestamp.now(tz='UTC')
        old = now - pd.Timedelta(hours=2)
        report = validate_stale_data(old, '1h', max_age_multiplier=1.0, now=now)
        assert not report.is_ok
        assert report.result == ValidationResult.STALE_DATA

    def test_run_all_validations(self):
        """Integration test for full validation pipeline"""
        row = pd.Series({
            'open': 100, 'high': 102, 'low': 99, 'close': 101, 'volume': 1000
        }, name=pd.Timestamp.now(tz='UTC'))

        recent_data = pd.DataFrame({
            'open': np.random.uniform(99, 101, 100),
            'high': np.random.uniform(101, 103, 100),
            'low': np.random.uniform(98, 100, 100),
            'close': np.random.uniform(99, 101, 100),
            'volume': np.random.uniform(1000, 5000, 100),
        }, index=pd.date_range('2024-01-01', periods=100, freq='1min', tz='UTC'))

        cross_prices = {'binance': 101, 'bybit': 101.2}

        reports = run_all_validations(
            row=row,
            recent_data=recent_data,
            cross_exchange_prices=cross_prices,
            current_rsi=55,
            recent_rsi=pd.Series(np.random.normal(50, 5, 100)),
            atr=1.5,
            timeframe='1m',
            config={
                'max_price_deviation_sigma': 5.0,
                'gap_atr_multiplier': 2.0,
                'flash_crash_threshold_pct': 8.0,
                'flash_crash_window_min': 5,
                'cross_exchange_divergence_pct': 0.5,
                'rsi_anomaly_sigma': 4.0,
                'rsi_lookback': 100,
                'stale_threshold_multiplier': 1.0,
            }
        )

        # Should have 7 validation reports
        assert len(reports) == 7
        # All should pass with this clean data
        for r in reports:
            assert r.is_ok, f"Validation failed: {r.result} - {r.message}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
