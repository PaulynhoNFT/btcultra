import pytest
import pandas as pd
import numpy as np
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from app.orchestrator import (
    SignalOrchestrator,
    CircuitBreakerState,
    NewsBlackoutManager,
    BlockReason,
)
from app.core.signal_core import SignalDecision, Side, TrendState, RegimeState
from app.models import Signal


class TestCircuitBreaker:
    """Test circuit breaker logic (§8)"""

    def test_no_breakers_initially(self):
        cb = CircuitBreakerState()
        blocks = cb.check_breakers()
        assert len(blocks) == 0

    def test_daily_limit_triggered(self):
        cb = CircuitBreakerState()
        cb.daily_pnl_pct = -3.5
        blocks = cb.check_breakers()
        assert BlockReason.CIRCUIT_BREAKER in blocks
        assert cb.paused_until is not None

    def test_weekly_limit_triggered(self):
        cb = CircuitBreakerState()
        cb.weekly_pnl_pct = -7.5
        blocks = cb.check_breakers()
        assert BlockReason.CIRCUIT_BREAKER in blocks

    def test_monthly_limit_triggered(self):
        cb = CircuitBreakerState()
        cb.monthly_pnl_pct = -16.0
        blocks = cb.check_breakers()
        assert BlockReason.CIRCUIT_BREAKER in blocks

    def test_consecutive_losses_pause(self):
        cb = CircuitBreakerState()
        cb.consecutive_losses = 5
        blocks = cb.check_breakers()
        assert BlockReason.CIRCUIT_BREAKER in blocks
        assert cb.paused_until is not None

    def test_record_win_resets_losses(self):
        cb = CircuitBreakerState()
        cb.consecutive_losses = 3
        cb.record_trade_result(1.5)  # win
        assert cb.consecutive_losses == 0
        assert cb.consecutive_wins == 1

    def test_record_loss_increments(self):
        cb = CircuitBreakerState()
        cb.record_trade_result(-1.0)
        assert cb.consecutive_losses == 1
        assert cb.consecutive_wins == 0


class TestNewsBlackout:
    """Test news blackout logic (N9)"""

    @pytest.mark.asyncio
    async def test_no_events_no_blackout(self):
        nb = NewsBlackoutManager()
        nb.events_cache = []
        assert not nb.is_blackout_active()

    @pytest.mark.asyncio
    async def test_event_within_window(self):
        nb = NewsBlackoutManager()
        now = datetime.now(timezone.utc)
        from app.models import EconomicEvent
        event = EconomicEvent(
            event_name="FOMC",
            country="US",
            currency="USD",
            impact="high",
            event_time=now + timedelta(minutes=10),
            source="test"
        )
        nb.events_cache = [event]
        assert nb.is_blackout_active(window_min=15)

    @pytest.mark.asyncio
    async def test_event_outside_window(self):
        nb = NewsBlackoutManager()
        now = datetime.now(timezone.utc)
        from app.models import EconomicEvent
        event = EconomicEvent(
            event_name="FOMC",
            country="US",
            currency="USD",
            impact="high",
            event_time=now + timedelta(hours=1),
            source="test"
        )
        nb.events_cache = [event]
        assert not nb.is_blackout_active(window_min=15)

    @pytest.mark.asyncio
    async def test_irrelevant_currency(self):
        nb = NewsBlackoutManager()
        now = datetime.now(timezone.utc)
        from app.models import EconomicEvent
        event = EconomicEvent(
            event_name="JPY CPI",
            country="JP",
            currency="JPY",
            impact="high",
            event_time=now + timedelta(minutes=5),
            source="test"
        )
        nb.events_cache = [event]
        # BTC/USDT should not care about JPY
        assert not nb.is_blackout_active(symbol="BTC/USDT", window_min=15)


class TestSignalOrchestrator:
    """Test signal orchestrator gates"""

    @pytest.fixture
    def orchestrator(self):
        return SignalOrchestrator()

    @pytest.fixture
    def sample_decision(self):
        from app.core.signal_core import ScoreBreakdown
        return SignalDecision(
            ok=True,
            side=Side.BUY,
            score=82,
            reason="ok",
            entry=50000,
            stop=49000,
            tp1=51000,
            tp2=52000,
            tp3=53000,
            rr=2.0,
            breakdown=ScoreBreakdown()
        )

    def test_run_gates_direction_conflict(self, orchestrator):
        from app.core.signal_core import ScoreBreakdown
        decision = SignalDecision(
            ok=False, side=Side.NONE, score=0, reason="trend_undefined",
            entry=0, stop=0, tp1=0, tp2=0, tp3=0, rr=0,
            breakdown=ScoreBreakdown()
        )
        import asyncio
        result = asyncio.run(orchestrator._run_gates("BTC/USDT", decision, None, None, None))
        assert result == BlockReason.DIRECTION_CONFLICT

    def test_run_gates_regime_lateral(self, orchestrator):
        from app.core.signal_core import ScoreBreakdown
        decision = SignalDecision(
            ok=False, side=Side.BUY, score=0, reason="regime:ADX<20",
            entry=0, stop=0, tp1=0, tp2=0, tp3=0, rr=0,
            breakdown=ScoreBreakdown()
        )
        import asyncio
        result = asyncio.run(orchestrator._run_gates("BTC/USDT", decision, None, None, None))
        assert result == BlockReason.REGIME_LATERAL

    def test_run_gates_rr_insufficient(self, orchestrator):
        from app.core.signal_core import ScoreBreakdown
        decision = SignalDecision(
            ok=False, side=Side.BUY, score=0, reason="rr:1.50",
            entry=0, stop=0, tp1=0, tp2=0, tp3=0, rr=0,
            breakdown=ScoreBreakdown()
        )
        import asyncio
        result = asyncio.run(orchestrator._run_gates("BTC/USDT", decision, None, None, None))
        assert result == BlockReason.RR_INSUFFICIENT

    def test_run_gates_score_below_60(self, orchestrator):
        from app.core.signal_core import ScoreBreakdown
        decision = SignalDecision(
            ok=False, side=Side.BUY, score=55, reason="score_below_60",
            entry=0, stop=0, tp1=0, tp2=0, tp3=0, rr=0,
            breakdown=ScoreBreakdown()
        )
        import asyncio
        result = asyncio.run(orchestrator._run_gates("BTC/USDT", decision, None, None, None))
        assert result == BlockReason.SCORE_BELOW_60

    def test_run_gates_observation_only(self, orchestrator):
        from app.core.signal_core import ScoreBreakdown
        decision = SignalDecision(
            ok=False, side=Side.BUY, score=65, reason="observation_only",
            entry=0, stop=0, tp1=0, tp2=0, tp3=0, rr=0,
            breakdown=ScoreBreakdown()
        )
        import asyncio
        result = asyncio.run(orchestrator._run_gates("BTC/USDT", decision, None, None, None))
        assert result == BlockReason.SCORE_BELOW_70

    def test_run_gates_ok_passes(self, orchestrator, sample_decision):
        import asyncio
        result = asyncio.run(orchestrator._run_gates("BTC/USDT", sample_decision, None, None, None))
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
