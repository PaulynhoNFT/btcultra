import pytest
import asyncio
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from app.ingest.ccxt_ingestor import CCXTProIngestor, CandleBuffer


class TestCCXTProIngestor:
    """Test CCXT Pro ingestor logic"""

    @pytest.fixture
    def ingestor(self):
        return CCXTProIngestor()

    def test_tf_ms_mapping(self):
        i = CCXTProIngestor()
        assert i.tf_ms['1m'] == 60_000
        assert i.tf_ms['5m'] == 300_000
        assert i.tf_ms['1h'] == 3_600_000
        assert i.tf_ms['4h'] == 14_400_000
        assert i.tf_ms['1d'] == 86_400_000

    def test_candle_buffer_initialization(self):
        buffer = CandleBuffer(symbol="BTC/USDT", timeframe="1h", exchange="binance")
        assert buffer.symbol == "BTC/USDT"
        assert buffer.timeframe == "1h"
        assert buffer.exchange == "binance"
        assert buffer.start_time is None

    @pytest.mark.asyncio
    async def test_process_ohlcv_new_candle(self, ingestor):
        """Test processing OHLCV creates new candle buffer"""
        ingestor.running = True
        buffer_key = "binance:BTC/USDT:1h"

        # Mock the finalize method
        ingestor._finalize_candle = AsyncMock()

        # First OHLCV - should create new buffer
        ohlcv = [1704067200000, 50000, 50100, 49900, 50050, 100]  # ts, o, h, l, c, v

        await ingestor._process_ohlcv("binance", "BTC/USDT", "1h", ohlcv)

        buffer = ingestor.candle_buffers.get(buffer_key)
        assert buffer is not None
        assert buffer.opens == [50000]
        assert buffer.highs == [50100]
        assert buffer.lows == [49900]
        assert buffer.closes == [50050]
        assert buffer.volumes == [100]

    @pytest.mark.asyncio
    async def test_process_ohlcv_updates_current(self, ingestor):
        """Test processing OHLCV updates current candle"""
        ingestor.running = True
        buffer_key = "binance:BTC/USDT:1h"

        # First candle
        ohlcv1 = [1704067200000, 50000, 50100, 49900, 50050, 100]
        await ingestor._process_ohlcv("binance", "BTC/USDT", "1h", ohlcv1)

        # Second update same candle (same hour)
        ohlcv2 = [1704067260000, 50000, 50200, 49850, 50150, 50]  # 1 min later
        await ingestor._process_ohlcv("binance", "BTC/USDT", "1h", ohlcv2)

        buffer = ingestor.candle_buffers.get(buffer_key)
        assert buffer.highs == [50200]  # updated high
        assert buffer.lows == [49850]   # updated low
        assert buffer.closes == [50150] # updated close
        assert buffer.volumes == [50]  # latest cumulative OHLCV snapshot

    @pytest.mark.asyncio
    async def test_process_ohlcv_new_candle_finalizes_old(self, ingestor):
        """Test new candle triggers finalize of previous"""
        ingestor.running = True
        ingestor._finalize_candle = AsyncMock()
        buffer_key = "binance:BTC/USDT:1h"

        # First hour
        ohlcv1 = [1704067200000, 50000, 50100, 49900, 50050, 100]
        await ingestor._process_ohlcv("binance", "BTC/USDT", "1h", ohlcv1)

        # Next hour - should finalize previous
        ohlcv2 = [1704070800000, 50050, 50150, 49950, 50100, 120]
        await ingestor._process_ohlcv("binance", "BTC/USDT", "1h", ohlcv2)

        # Should have called finalize once
        ingestor._finalize_candle.assert_called_once()

    def test_calculate_atr(self):
        i = CCXTProIngestor()
        high = pd.Series([102, 103, 101, 104, 105])
        low = pd.Series([99, 100, 98, 101, 102])
        close = pd.Series([100, 101, 99, 102, 103])

        atr = i._calculate_atr(high, low, close, 3)
        assert len(atr) == 5
        assert not atr.isna().all()

    def test_calculate_rsi(self):
        i = CCXTProIngestor()
        close = pd.Series([100, 101, 102, 101, 100, 99, 98, 99, 100, 101])

        rsi = i._calculate_rsi(close, 5)
        assert len(rsi) == 10
        assert pd.isna(rsi.iloc[0])  # no preceding close exists
        assert rsi.iloc[1:].between(0, 100).all()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
