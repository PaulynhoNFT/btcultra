# CCXT Pro WebSocket Ingestor
# Handles multi-exchange OHLCV streaming with validation and persistence

import asyncio
import ccxt.pro as ccxtpro
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from collections import defaultdict
import logging
import hashlib
import json

from app.ingest.config import ingest_settings
from app.ingest.validators import (
    run_all_validations, ValidationResult, ValidationReport
)
from app.core.signal_core import generate_signal, SignalDecision
from app.database import async_session_maker
from app.models import Candle, OrderbookL2, DerivativesData, EngineMetric
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert

logger = logging.getLogger(__name__)


@dataclass
class ExchangeState:
    name: str
    client: ccxtpro.Exchange
    connected: bool = False
    degraded: bool = False
    last_candle_time: Dict[str, Dict[str, datetime]] = field(default_factory=lambda: defaultdict(dict))
    error_count: int = 0
    symbols_subscribed: List[str] = field(default_factory=list)


@dataclass
class CandleBuffer:
    """In-memory buffer for building candles from trades/ticker"""
    symbol: str
    timeframe: str
    exchange: str
    opens: List[float] = field(default_factory=list)
    highs: List[float] = field(default_factory=list)
    lows: List[float] = field(default_factory=list)
    closes: List[float] = field(default_factory=list)
    volumes: List[float] = field(default_factory=list)
    timestamps: List[datetime] = field(default_factory=list)
    start_time: Optional[datetime] = None


class CCXTProIngestor:
    """
    Multi-exchange WebSocket ingestor using CCXT Pro.
    Handles: connection management, candle building, validation, persistence.
    """

    def __init__(self):
        self.exchanges: Dict[str, ExchangeState] = {}
        self.candle_buffers: Dict[str, CandleBuffer] = {}  # key: f"{exchange}:{symbol}:{tf}"
        self.running = False
        self.signal_callback: Optional[Callable] = None
        self.metrics_callback: Optional[Callable] = None

        # TF to milliseconds
        self.tf_ms = {
            '1m': 60_000, '5m': 300_000, '15m': 900_000, '30m': 1_800_000,
            '1h': 3_600_000, '2h': 7_200_000, '4h': 14_400_000,
            '6h': 21_600_000, '12h': 43_200_000, '1d': 86_400_000
        }

    async def initialize(self):
        """Initialize exchange connections"""
        exchange_configs = {
            'binance': {
                'class': ccxtpro.binance,
                'params': {'enableRateLimit': True, 'options': {'defaultType': 'spot'}}
            }
        }

        for name, config in exchange_configs.items():
            try:
                client = config['class'](config['params'])
                # Test connection
                await client.load_markets()
                self.exchanges[name] = ExchangeState(
                    name=name,
                    client=client,
                    connected=True
                )
                logger.info(f"Initialized {name} exchange")
            except Exception as e:
                logger.error(f"Failed to initialize {name}: {e}")
                self.exchanges[name] = ExchangeState(
                    name=name,
                    client=None,
                    connected=False,
                    degraded=True
                )

    async def subscribe_symbol(self, exchange_name: str, symbol: str, timeframes: List[str]):
        """Subscribe to OHLCV streams for a symbol across timeframes"""
        exchange = self.exchanges.get(exchange_name)
        if not exchange or not exchange.connected:
            logger.warning(f"Exchange {exchange_name} not connected")
            return

        for tf in timeframes:
            buffer_key = f"{exchange_name}:{symbol}:{tf}"
            self.candle_buffers[buffer_key] = CandleBuffer(
                symbol=symbol,
                timeframe=tf,
                exchange=exchange_name
            )
            exchange.symbols_subscribed.append(f"{symbol}:{tf}")

        logger.info(f"Subscribed {exchange_name} {symbol} to {timeframes}")

    async def start_streaming(self):
        """Start WebSocket streaming for all subscribed symbols"""
        self.running = True

        # Create tasks for each exchange
        tasks = []
        for name, exchange in self.exchanges.items():
            if exchange.connected and exchange.symbols_subscribed:
                tasks.append(self._stream_exchange(name))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _stream_exchange(self, exchange_name: str):
        exchange = self.exchanges[exchange_name]
        await asyncio.gather(*(
            self._stream_subscription(exchange_name, *subscription.rsplit(':', 1))
            for subscription in exchange.symbols_subscribed
        ))

    async def _stream_subscription(self, exchange_name: str, symbol: str, timeframe: str):
        exchange = self.exchanges[exchange_name]
        while self.running:
            try:
                # CCXT returns an awaitable list of cumulative OHLCV snapshots.
                candles = await exchange.client.watch_ohlcv(symbol, timeframe)
                for candle in candles:
                    await self._process_ohlcv(exchange_name, symbol, timeframe, candle)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Stream error %s %s %s: %s", exchange_name, symbol, timeframe, exc)
                exchange.error_count += 1
                if exchange.error_count >= ingest_settings.exchange_degraded_threshold:
                    exchange.degraded = True
                await asyncio.sleep(ingest_settings.ws_reconnect_delay)

    async def _process_ohlcv(self, exchange_name: str, symbol: str, timeframe: str, ohlcv: List):
        """Process incoming OHLCV from WebSocket"""
        # CCXT Pro returns: [timestamp, open, high, low, close, volume]
        ts, o, h, l, c, v = ohlcv
        timestamp = pd.Timestamp(ts, unit='ms', tz='UTC')

        buffer_key = f"{exchange_name}:{symbol}:{timeframe}"
        buffer = self.candle_buffers.get(buffer_key)

        if not buffer:
            buffer = CandleBuffer(symbol=symbol, timeframe=timeframe, exchange=exchange_name)
            self.candle_buffers[buffer_key] = buffer

        # Check if new candle
        tf_ms = self.tf_ms.get(timeframe, 60_000)
        candle_start = pd.Timestamp((ts // tf_ms) * tf_ms, unit='ms', tz='UTC')

        if buffer.start_time is None or candle_start > buffer.start_time:
            # Finalize previous candle if exists
            if buffer.start_time is not None and buffer.closes:
                await self._finalize_candle(buffer)

            # Start new candle
            buffer.start_time = candle_start
            buffer.opens = [o]
            buffer.highs = [h]
            buffer.lows = [l]
            buffer.closes = [c]
            buffer.volumes = [v]
            buffer.timestamps = [timestamp]
        elif candle_start == buffer.start_time:
            # Each update replaces the cumulative snapshot, including volume.
            buffer.opens = [o]
            buffer.highs = [h]
            buffer.lows = [l]
            buffer.closes = [c]
            buffer.volumes = [v]
        else:
            return  # Ignore older candles replayed by the exchange cache.

        # Update exchange last candle time
        exchange = self.exchanges.get(exchange_name)
        if exchange is not None:
            exchange.last_candle_time[symbol][timeframe] = timestamp

    async def _finalize_candle(self, buffer: CandleBuffer):
        """Finalize and persist a completed candle"""
        # Build candle row
        row = pd.Series({
            'open': buffer.opens[0],
            'high': max(buffer.highs),
            'low': min(buffer.lows),
            'close': buffer.closes[-1],
            'volume': sum(buffer.volumes),
        }, name=buffer.start_time)

        # Get recent data for validation
        recent_data = await self._get_recent_candles(buffer.symbol, buffer.timeframe, buffer.exchange, 100)

        # Calculate ATR for gap check
        atr = None
        if len(recent_data) >= 14:
            atr_series = self._calculate_atr(recent_data.high, recent_data.low, recent_data.close, 14)
            atr = atr_series.iloc[-1] if not atr_series.empty else None

        # Calculate RSI for anomaly check
        current_rsi = None
        recent_rsi = None
        if len(recent_data) >= 14:
            rsi_series = self._calculate_rsi(recent_data.close, 14)
            recent_rsi = rsi_series
            current_rsi = rsi_series.iloc[-1] if not rsi_series.empty else None

        # Cross-exchange prices (latest close from each exchange)
        cross_prices = await self._get_cross_exchange_prices(buffer.symbol, buffer.timeframe)

        # Run validations
        config = {
            'max_price_deviation_sigma': ingest_settings.max_price_deviation_sigma,
            'gap_atr_multiplier': ingest_settings.gap_atr_multiplier,
            'flash_crash_threshold_pct': ingest_settings.flash_crash_threshold_pct,
            'flash_crash_window_min': ingest_settings.flash_crash_window_min,
            'cross_exchange_divergence_pct': ingest_settings.cross_exchange_divergence_pct,
            'rsi_anomaly_sigma': ingest_settings.rsi_anomaly_sigma,
            'rsi_lookback': ingest_settings.rsi_lookback,
            'stale_threshold_multiplier': ingest_settings.stale_threshold_multiplier,
        }

        validations = run_all_validations(
            row=row,
            recent_data=recent_data,
            cross_exchange_prices=cross_prices,
            current_rsi=current_rsi,
            recent_rsi=recent_rsi,
            atr=atr,
            timeframe=buffer.timeframe,
            config=config
        )

        # Check for blocking validations
        blocked = any(not v.is_ok and v.result in (
            ValidationResult.GAP_ANOMALY,
            ValidationResult.FLASH_CRASH,
            ValidationResult.CROSS_EXCHANGE_DIVERGENCE,
            ValidationResult.RSI_ANOMALY,
            ValidationResult.STALE_DATA
        ) for v in validations)

        # Persist candle (even if validation warns, but mark is_final appropriately)
        await self._persist_candle(
            exchange=buffer.exchange,
            symbol=buffer.symbol,
            timeframe=buffer.timeframe,
            timestamp=buffer.start_time,
            ohlcv=row,
            is_final=not blocked,  # If validation fails, mark as provisional
            validation_reports=validations
        )

        # Emit metrics
        if self.metrics_callback:
            await self.metrics_callback({
                'exchange': buffer.exchange,
                'symbol': buffer.symbol,
                'timeframe': buffer.timeframe,
                'timestamp': buffer.start_time.isoformat(),
                'validations': [v.result.value for v in validations],
                'blocked': blocked
            })

        # Generate signal if we have enough data and validations pass
        if not blocked and len(recent_data) >= ingest_settings.min_candles_for_indicators:
            await self._maybe_generate_signal(buffer.symbol, buffer.timeframe)

    async def _persist_candle(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        timestamp: pd.Timestamp,
        ohlcv: pd.Series,
        is_final: bool,
        validation_reports: List[ValidationReport]
    ):
        """Persist candle to TimescaleDB"""
        async with async_session_maker() as session:
            stmt = insert(Candle).values(
                timestamp=timestamp.to_pydatetime(),
                symbol=symbol,
                timeframe=timeframe,
                open=float(ohlcv.open),
                high=float(ohlcv.high),
                low=float(ohlcv.low),
                close=float(ohlcv.close),
                volume=float(ohlcv.volume),
                source=exchange,
                is_final=is_final,
            ).on_conflict_do_update(
                index_elements=['symbol', 'timeframe', 'timestamp'],
                set_={
                    'open': float(ohlcv.open),
                    'high': float(ohlcv.high),
                    'low': float(ohlcv.low),
                    'close': float(ohlcv.close),
                    'volume': float(ohlcv.volume),
                    'source': exchange,
                    'is_final': is_final,
                    'ingested_at': func.now(),
                }
            )
            await session.execute(stmt)
            await session.commit()

    async def _get_recent_candles(
        self, symbol: str, timeframe: str, exchange: str, limit: int
    ) -> pd.DataFrame:
        """Fetch recent candles from DB for validation"""
        async with async_session_maker() as session:
            result = await session.execute(
                select(Candle)
                .where(Candle.symbol == symbol)
                .where(Candle.timeframe == timeframe)
                .where(Candle.source == exchange)
                .order_by(Candle.timestamp.desc())
                .limit(limit)
            )
            rows = result.scalars().all()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame([{
            'timestamp': r.timestamp,
            'open': r.open,
            'high': r.high,
            'low': r.low,
            'close': r.close,
            'volume': r.volume,
        } for r in reversed(rows)])
        df.set_index('timestamp', inplace=True)
        return df

    async def _get_cross_exchange_prices(
        self, symbol: str, timeframe: str
    ) -> Dict[str, float]:
        """Get latest close price from each exchange for divergence check"""
        async with async_session_maker() as session:
            result = await session.execute(
                select(Candle.source, Candle.close)
                .where(Candle.symbol == symbol)
                .where(Candle.timeframe == timeframe)
                .where(Candle.is_final == True)
                .order_by(Candle.timestamp.desc())
            )
            rows = result.all()

        # Get latest per exchange
        prices = {}
        for source, close in rows:
            if source not in prices:
                prices[source] = close
        return prices

    def _calculate_atr(self, high: pd.Series, low: pd.Series, close: pd.Series, n: int) -> pd.Series:
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1/n, adjust=False).mean()

    def _calculate_rsi(self, close: pd.Series, n: int) -> pd.Series:
        d = close.diff()
        g = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
        l = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
        rs = g / l.replace(0, np.nan)
        result = 100 - 100/(1+rs)
        result = result.mask((l == 0) & (g > 0), 100)
        result = result.mask((g == 0) & (l > 0), 0)
        return result.mask((g == 0) & (l == 0), 50)

    async def _maybe_generate_signal(self, symbol: str, timeframe: str):
        """Generate signal if conditions met"""
        # For now, generate on 4h timeframe using 1h/4h/1d as TF3/TF2/TF1
        if timeframe != '4h':
            return

        # Fetch multi-timeframe data
        tf1 = await self._get_recent_candles(symbol, '1d', 'binance', 200)  # Weekly trend
        tf2 = await self._get_recent_candles(symbol, '4h', 'binance', 200)  # Correction
        tf3 = await self._get_recent_candles(symbol, '1h', 'binance', 200)  # Trigger

        if len(tf1) < 40 or len(tf2) < 40 or len(tf3) < 40:
            return

        # Generate signal
        decision = generate_signal(tf1, tf2, tf3, mode='swing')

        if self.signal_callback:
            await self.signal_callback(symbol, decision)

    async def stop(self):
        """Stop all streams and close connections"""
        self.running = False
        for exchange in self.exchanges.values():
            if exchange.client:
                await exchange.client.close()
        logger.info("Ingestor stopped")


# Global ingestor instance
ingestor = CCXTProIngestor()


async def start_ingestor(
    signal_callback: Callable = None,
    metrics_callback: Callable = None
):
    """Start the global ingestor"""
    ingestor.signal_callback = signal_callback
    ingestor.metrics_callback = metrics_callback

    await ingestor.initialize()

    # Subscribe all symbols/timeframes
    for symbol in ingest_settings.symbols:
        for exchange_name in ['binance']:
            await ingestor.subscribe_symbol(exchange_name, symbol, ingest_settings.timeframes)

    await ingestor.start_streaming()


async def stop_ingestor():
    """Stop the global ingestor"""
    await ingestor.stop()
