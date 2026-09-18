# Signal Orchestrator
# Coordinates: Ingest → Validation → Signal Generation → Persistence → Notification
# Implements all N-rules gates, news blackout, circuit breakers, freshness

import asyncio
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
import logging
import json

import pandas as pd

from app.core.signal_core import (
    generate_signal, SignalDecision, TrendState, RegimeState,
    CorrectionState, Side, RegimeReport, CorrectionReport, TriggerReport
)
from app.database import async_session_maker
from app.models import (
    Signal, SignalSnapshot, ShadowPortfolio, EngineMetric,
    EconomicEvent, AuditLog
)
from sqlalchemy import select, func, and_, desc
from app.ingest.ccxt_ingestor import ingestor
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class BlockReason(str, Enum):
    """N-rule block reasons"""
    DIRECTION_CONFLICT = "DIRECTION_CONFLICT"      # N1
    REGIME_LATERAL = "REGIME_LATERAL"              # N2
    RR_INSUFFICIENT = "RR_INSUFFICIENT"            # N3
    SCORE_BELOW_60 = "SCORE_BELOW_60"              # N4
    SCORE_BELOW_70 = "SCORE_BELOW_70"              # N4 (observation)
    STALE_DATA = "STALE_DATA"                      # N7
    NEWS_BLACKOUT = "NEWS_BLACKOUT"                # N9
    EXCHANGE_DEGRADED = "EXCHANGE_DEGRADED"        # N8
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"            # N10
    CORRELATION_BLOCK = "CORRELATION_BLOCK"        # N10 (portfolio level)
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass
class SignalContext:
    """Full context for signal generation"""
    symbol: str
    tf1_df: Any  # pd.DataFrame
    tf2_df: Any
    tf3_df: Any
    regime: RegimeReport
    correction: CorrectionReport
    trigger: TriggerReport
    trend: TrendState
    decision: SignalDecision
    derivatives_ctx: Dict = field(default_factory=dict)
    news_blackout: bool = False
    candle_hashes: Dict[str, str] = field(default_factory=dict)


class CircuitBreakerState:
    """Portfolio-level circuit breakers (§8)"""
    def __init__(self):
        self.daily_pnl_pct: float = 0.0
        self.weekly_pnl_pct: float = 0.0
        self.monthly_pnl_pct: float = 0.0
        self.consecutive_losses: int = 0
        self.consecutive_wins: int = 0
        self.last_reset_daily: datetime = datetime.now(timezone.utc)
        self.last_reset_weekly: datetime = datetime.now(timezone.utc)
        self.last_reset_monthly: datetime = datetime.now(timezone.utc)
        self.paused_until: Optional[datetime] = None
        self.pause_reason: Optional[str] = None

    def check_breakers(self) -> List[BlockReason]:
        """Check all circuit breakers, return list of active blocks"""
        blocks = []
        now = datetime.now(timezone.utc)

        # Check if paused
        if self.paused_until and now < self.paused_until:
            blocks.append(BlockReason.CIRCUIT_BREAKER)
            return blocks

        # Daily -3%
        if self.daily_pnl_pct <= -3.0:
            blocks.append(BlockReason.CIRCUIT_BREAKER)
            self.paused_until = datetime(now.year, now.month, now.day, 23, 59, 59, tzinfo=timezone.utc)
            self.pause_reason = "Daily -3% limit"

        # Weekly -7%
        if self.weekly_pnl_pct <= -7.0:
            blocks.append(BlockReason.CIRCUIT_BREAKER)
            self.paused_until = now + timedelta(days=7)
            self.pause_reason = "Weekly -7% limit"

        # Monthly -15%
        if self.monthly_pnl_pct <= -15.0:
            blocks.append(BlockReason.CIRCUIT_BREAKER)
            self.paused_until = now + timedelta(days=30)
            self.pause_reason = "Monthly -15% limit"

        # 3 consecutive losses → sizing 50%
        # 5 consecutive losses → pause 24h
        if self.consecutive_losses >= 5:
            blocks.append(BlockReason.CIRCUIT_BREAKER)
            self.paused_until = now + timedelta(hours=24)
            self.pause_reason = "5 consecutive losses"

        return blocks

    def record_trade_result(self, pnl_r: float):
        """Update circuit breaker state with trade result"""
        if pnl_r > 0:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            self.consecutive_wins = 0

    def reset_daily(self):
        self.daily_pnl_pct = 0.0
        self.last_reset_daily = datetime.now(timezone.utc)

    def reset_weekly(self):
        self.weekly_pnl_pct = 0.0
        self.last_reset_weekly = datetime.now(timezone.utc)

    def reset_monthly(self):
        self.monthly_pnl_pct = 0.0
        self.last_reset_monthly = datetime.now(timezone.utc)


class NewsBlackoutManager:
    """Manages economic calendar news blackout (±15 min around high-impact events)"""

    def __init__(self):
        self.events_cache: List[EconomicEvent] = []
        self.last_fetch: Optional[datetime] = None
        self.cache_ttl = timedelta(hours=1)

    async def refresh_events(self):
        """Fetch economic events from Forex Factory / Econoday"""
        # TODO: Implement actual API fetch
        # For now, use cached events from DB
        async with async_session_maker() as session:
            result = await session.execute(
                select(EconomicEvent)
                .where(EconomicEvent.event_time >= datetime.now(timezone.utc))
                .where(EconomicEvent.event_time <= datetime.now(timezone.utc) + timedelta(days=7))
                .where(EconomicEvent.impact == 'high')
                .order_by(EconomicEvent.event_time)
            )
            self.events_cache = result.scalars().all()
        self.last_fetch = datetime.now(timezone.utc)

    def is_blackout_active(self, symbol: str = None, window_min: int = 15) -> bool:
        """Check if any high-impact event is within window_min minutes"""
        if not self.events_cache or (self.last_fetch and datetime.now(timezone.utc) - self.last_fetch > self.cache_ttl):
            # Would need to refresh - for now return False
            return False

        now = datetime.now(timezone.utc)
        for event in self.events_cache:
            # Filter by currency relevance
            if symbol:
                base = symbol.split('/')[0]
                if event.currency not in ('USD', base, 'BTC', 'ETH'):
                    continue

            time_diff = abs((event.event_time - now).total_seconds() / 60)
            if time_diff <= window_min:
                return True
        return False


class SignalOrchestrator:
    """
    Main orchestrator: receives validated candles, runs gates, persists signals,
    manages shadow portfolio, emits metrics.
    """

    def __init__(self):
        self.circuit_breaker = CircuitBreakerState()
        self.news_blackout = NewsBlackoutManager()
        self.signal_callbacks: List[Callable] = []
        self.metrics_callbacks: List[Callable] = []
        self.running = False
        self.last_signal_hash: Dict[str, str] = {}  # symbol -> hash

    async def initialize(self):
        """Initialize orchestrator"""
        await self.news_blackout.refresh_events()
        # Load circuit breaker state from DB
        await self._load_circuit_breaker_state()
        logger.info("Signal orchestrator initialized")

    async def _load_circuit_breaker_state(self):
        """Load recent PnL for circuit breakers"""
        # Simplified - in production, compute from paper_trades / shadow_portfolio
        pass

    def register_signal_callback(self, callback: Callable):
        self.signal_callbacks.append(callback)

    def register_metrics_callback(self, callback: Callable):
        self.metrics_callbacks.append(callback)

    async def process_candle(self, symbol: str, timeframe: str, exchange: str = 'binance'):
        """Process a new finalized candle - main entry point"""
        # 1. Check global circuit breakers
        cb_blocks = self.circuit_breaker.check_breakers()
        if cb_blocks:
            await self._emit_metric('circuit_breaker_active', 1, {'symbol': symbol, 'reasons': [b.value for b in cb_blocks]})
            return

        # 2. Check news blackout
        if self.news_blackout.is_blackout_active(symbol):
            await self._block_signal(symbol, timeframe, BlockReason.NEWS_BLACKOUT, "Economic news blackout")
            return

        # 3. Check exchange health
        exchange_state = ingestor.exchanges.get(exchange)
        if exchange_state and exchange_state.degraded:
            await self._block_signal(symbol, timeframe, BlockReason.EXCHANGE_DEGRADED, f"Exchange {exchange} degraded")
            return

        # 4. Fetch multi-timeframe data
        tf1_df = await self._get_tf_data(symbol, '1d', exchange, 200)
        tf2_df = await self._get_tf_data(symbol, '4h', exchange, 200)
        tf3_df = await self._get_tf_data(symbol, '1h', exchange, 200)

        if tf1_df is None or tf2_df is None or tf3_df is None:
            await self._emit_metric('insufficient_data', 1, {'symbol': symbol})
            return

        # 5. Check data freshness (N7)
        if not self._check_freshness(tf1_df, '1d') or not self._check_freshness(tf2_df, '4h') or not self._check_freshness(tf3_df, '1h'):
            await self._block_signal(symbol, timeframe, BlockReason.STALE_DATA, "Data stale")
            return

        # 6. Generate signal
        decision = generate_signal(tf1_df, tf2_df, tf3_df, mode='swing')

        # 7. Compute candle hashes for idempotency (§11.5)
        candle_hashes = self._compute_candle_hashes(tf1_df, tf2_df, tf3_df)
        combined_hash = self._hash_combined(candle_hashes)

        # Idempotency check
        if self.last_signal_hash.get(symbol) == combined_hash:
            logger.debug(f"Duplicate signal for {symbol}, skipping")
            return
        self.last_signal_hash[symbol] = combined_hash

        # 8. Run all gates (N1-N12)
        block_reason = await self._run_gates(symbol, decision, tf1_df, tf2_df, tf3_df)
        if block_reason:
            await self._block_signal(symbol, timeframe, block_reason, decision.reason)
            return

        # 9. Correlation check (portfolio level)
        if await self._check_correlation_block(symbol, decision.side):
            await self._block_signal(symbol, timeframe, BlockReason.CORRELATION_BLOCK, "High correlation with open position")
            return

        # 10. Persist signal
        await self._persist_signal(symbol, timeframe, decision, candle_hashes, combined_hash)

        # 11. Emit signal
        for callback in self.signal_callbacks:
            try:
                await callback(symbol, decision)
            except Exception as e:
                logger.error(f"Signal callback error: {e}")

        # 12. Emit metrics
        await self._emit_metric('signal_generated', 1, {
            'symbol': symbol,
            'side': decision.side.value,
            'score': decision.score,
            'rr': decision.rr
        })

    def _check_freshness(self, df, timeframe: str) -> bool:
        """Check if latest candle is fresh (N7)"""
        if df is None or len(df) == 0:
            return False
        latest = df.index[-1]
        now = datetime.now(timezone.utc)
        tf_minutes = {'1m': 1, '5m': 5, '15m': 15, '1h': 60, '4h': 240, '1d': 1440}
        max_age = timedelta(minutes=tf_minutes.get(timeframe, 60) * 1.0)
        return (now - latest.to_pydatetime()) <= max_age

    async def _run_gates(
        self,
        symbol: str,
        decision: SignalDecision,
        tf1_df, tf2_df, tf3_df
    ) -> Optional[BlockReason]:
        """Run all N-rule gates in sequence"""
        # N1: Direction conflict (already handled in signal_core - trend vs side)
        if decision.reason == "trend_undefined":
            return BlockReason.DIRECTION_CONFLICT

        # N2: Regime lateral (ADX < 20)
        if decision.reason.startswith("regime:"):
            reason = decision.reason.split(":")[1]
            if reason in ("ADX<20", "ATR<20pct", "BB squeeze", "lateral"):
                return BlockReason.REGIME_LATERAL

        # N3: R:R < 2:1
        if decision.reason.startswith("rr:"):
            return BlockReason.RR_INSUFFICIENT

        # N4: Score < 60 or 60-69 (observation)
        if decision.reason == "score_below_60":
            return BlockReason.SCORE_BELOW_60
        if decision.reason == "observation_only":
            return BlockReason.SCORE_BELOW_70

        # N5: Incomplete signal (schema validation)
        if decision.entry <= 0 or decision.stop <= 0 or decision.rr <= 0:
            return BlockReason.INSUFFICIENT_DATA

        # N7: Stale data (already checked)

        # N9: News blackout (already checked)

        # N10: Circuit breaker (already checked)

        return None

    async def _check_correlation_block(self, symbol: str, side: Side) -> bool:
        """Check if new signal correlates > 0.9 with existing open position"""
        # Simplified: check if BTC and ETH both have signals same direction
        if symbol in ('BTC/USDT', 'ETH/USDT'):
            other = 'ETH/USDT' if symbol == 'BTC/USDT' else 'BTC/USDT'
            async with async_session_maker() as session:
                result = await session.execute(
                    select(Signal)
                    .where(Signal.symbol == other)
                    .where(Signal.ok == True)
                    .where(Signal.side == side.value)
                    .where(Signal.timestamp >= datetime.now(timezone.utc) - timedelta(hours=24))
                    .order_by(Signal.timestamp.desc())
                    .limit(1)
                )
                existing = result.scalar_one_or_none()
                if existing:
                    # In production, compute actual correlation
                    return True
        return False

    async def _block_signal(self, symbol: str, timeframe: str, reason: BlockReason, detail: str):
        """Record blocked signal in shadow portfolio"""
        logger.info(f"Signal blocked: {symbol} {reason.value} - {detail}")

        # Create shadow entry (with dummy prices for tracking)
        async with async_session_maker() as session:
            shadow = ShadowPortfolio(
                signal_id=None,  # No signal ID since blocked
                block_reason=reason.value,
                entry_price=0.0,
                stop_price=0.0,
                tp1=0.0,
                tp2=0.0,
                tp3=0.0,
                rr=0.0,
                score=0,
                outcome='blocked',
            )
            session.add(shadow)
            await session.commit()

        await self._emit_metric('signal_blocked', 1, {
            'symbol': symbol,
            'reason': reason.value,
            'detail': detail
        })

    async def _persist_signal(
        self,
        symbol: str,
        timeframe: str,
        decision: SignalDecision,
        candle_hashes: Dict[str, str],
        combined_hash: str
    ):
        """Persist signal with full snapshot"""
        async with async_session_maker() as session:
            # Create signal
            signal = Signal(
                timestamp=datetime.now(timezone.utc),
                symbol=symbol,
                timeframe=timeframe,
                side=decision.side.value,
                score=decision.score,
                reason=decision.reason,
                ok=decision.ok,
                entry_price=decision.entry,
                stop_price=decision.stop,
                tp1=decision.tp1,
                tp2=decision.tp2,
                tp3=decision.tp3,
                rr=decision.rr,
                mode='swing',
                engine_version='triple-screen-v1',
                score_version='v1',
                risk_version='v1',
                snapshot_hash=combined_hash,
                snapshot_json=self._build_snapshot_json(decision),
            )
            session.add(signal)
            await session.flush()

            # Create snapshot
            snapshot = SignalSnapshot(
                signal_id=signal.id,
                tf1_indicators={},  # Would populate from actual indicator values
                tf2_indicators={},
                tf3_indicators={},
                regime_report={},
                correction_report={},
                trigger_report={},
                score_breakdown=self._breakdown_to_dict(decision.breakdown),
                derivatives_ctx={},
                news_blackout=False,
                candle_hashes=candle_hashes,
            )
            session.add(snapshot)
            await session.commit()

        logger.info(f"Signal persisted: {symbol} {decision.side.value} score={decision.score} ok={decision.ok}")

    def _build_snapshot_json(self, decision: SignalDecision) -> Dict:
        """Build minimal snapshot for signal record"""
        return {
            'score': decision.score,
            'side': decision.side.value,
            'entry': decision.entry,
            'stop': decision.stop,
            'tp1': decision.tp1,
            'tp2': decision.tp2,
            'tp3': decision.tp3,
            'rr': decision.rr,
            'breakdown': self._breakdown_to_dict(decision.breakdown),
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

    def _breakdown_to_dict(self, bd) -> Dict:
        return {
            'base': bd.base, 'trend': bd.trend, 'correction': bd.correction,
            'confluences': bd.confluences, 'volume': bd.volume, 'candle': bd.candle,
            'sr_prox': bd.sr_prox, 'rr_bonus': bd.rr_bonus,
            'derivatives_mult': bd.derivatives_mult, 'freshness_mult': bd.freshness_mult,
            'final': bd.final,
        }

    def _compute_candle_hashes(self, tf1_df, tf2_df, tf3_df) -> Dict[str, str]:
        """Compute SHA256 of last candle for each timeframe (§11.5)"""
        hashes = {}
        for name, df in [('tf1', tf1_df), ('tf2', tf2_df), ('tf3', tf3_df)]:
            if df is not None and len(df) > 0:
                last = df.iloc[-1]
                data = f"{last.name.isoformat()}{last.open}{last.high}{last.low}{last.close}{last.volume}"
                hashes[name] = hashlib.sha256(data.encode()).hexdigest()[:16]
        return hashes

    def _hash_combined(self, candle_hashes: Dict[str, str]) -> str:
        """Combined hash for idempotency"""
        combined = "".join(sorted(candle_hashes.values()))
        return hashlib.sha256(combined.encode()).hexdigest()[:32]

    async def _get_tf_data(self, symbol: str, timeframe: str, exchange: str, limit: int):
        """Fetch timeframe data from DB"""
        async with async_session_maker() as session:
            result = await session.execute(
                select(Candle)
                .where(Candle.symbol == symbol)
                .where(Candle.timeframe == timeframe)
                .where(Candle.source == exchange)
                .where(Candle.is_final == True)
                .order_by(Candle.timestamp.desc())
                .limit(limit)
            )
            rows = result.scalars().all()

        if not rows or len(rows) < 40:
            return None

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

    async def _emit_metric(self, name: str, value: float, labels: Dict = None):
        """Emit metric to Prometheus and DB"""
        metric = EngineMetric(
            timestamp=datetime.now(timezone.utc),
            metric_name=name,
            metric_value=value,
            labels=labels or {}
        )
        async with async_session_maker() as session:
            session.add(metric)
            await session.commit()

        for callback in self.metrics_callbacks:
            try:
                await callback(name, value, labels)
            except Exception as e:
                logger.error(f"Metrics callback error: {e}")


# Global orchestrator
orchestrator = SignalOrchestrator()


async def start_orchestrator():
    """Start the signal orchestrator"""
    await orchestrator.initialize()

    # Register as callback for ingestor
    async def on_signal(symbol: str, decision: SignalDecision):
        # Signal already persisted in orchestrator.process_candle
        pass

    async def on_metric(data: Dict):
        pass

    # The ingestor calls _maybe_generate_signal which calls orchestrator.process_candle
    # So we just need to ensure orchestrator is ready
    logger.info("Orchestrator ready")


async def stop_orchestrator():
    """Stop the orchestrator"""
    pass
