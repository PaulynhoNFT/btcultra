from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, and_
from pydantic import BaseModel, Field
from app.database import get_db
from app.models import Signal, SignalSnapshot, ShadowPortfolio
from app.routes.auth import get_current_user

router = APIRouter(prefix="/signals", tags=["signals"])


# ============================================================
# Schemas
# ============================================================
class ScoreBreakdown(BaseModel):
    base: int = 0
    trend: int = 0
    correction: int = 0
    confluences: int = 0
    volume: int = 0
    candle: int = 0
    sr_prox: int = 0
    rr_bonus: int = 0
    derivatives_mult: float = 1.0
    freshness_mult: float = 1.0
    final: int = 0


class SignalResponse(BaseModel):
    id: UUID
    timestamp: datetime
    symbol: str
    timeframe: str
    side: str
    score: int
    reason: str
    ok: bool
    entry_price: float
    stop_price: float
    tp1: float
    tp2: float
    tp3: float
    rr: float
    mode: str
    engine_version: str
    score_version: str
    risk_version: str
    snapshot_hash: str
    created_at: datetime
    breakdown: Optional[ScoreBreakdown] = None


class SignalDetailResponse(SignalResponse):
    snapshot: dict


class SignalsListResponse(BaseModel):
    signals: List[SignalResponse]
    total: int
    page: int
    page_size: int


# ============================================================
# Routes
# ============================================================
@router.get("", response_model=SignalsListResponse)
async def list_signals(
    symbol: Optional[str] = Query(None),
    ok: Optional[bool] = Query(None),
    side: Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),  # Require auth
):
    query = select(Signal)

    conditions = []
    if symbol:
        conditions.append(Signal.symbol == symbol.upper())
    if ok is not None:
        conditions.append(Signal.ok == ok)
    if side:
        conditions.append(Signal.side == side.upper())
    if from_date:
        conditions.append(Signal.timestamp >= from_date)
    if to_date:
        conditions.append(Signal.timestamp <= to_date)

    if conditions:
        query = query.where(and_(*conditions))

    # Total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Paginated results
    query = query.order_by(desc(Signal.timestamp)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    signals = result.scalars().all()

    return SignalsListResponse(
        signals=[SignalResponse.model_validate(s, from_attributes=True) for s in signals],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/latest", response_model=List[SignalResponse])
async def latest_signals(
    symbol: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    query = select(Signal).where(Signal.ok == True).order_by(desc(Signal.timestamp)).limit(limit)
    if symbol:
        query = query.where(Signal.symbol == symbol.upper())
    result = await db.execute(query)
    signals = result.scalars().all()
    return [SignalResponse.model_validate(s, from_attributes=True) for s in signals]


@router.get("/{signal_id}", response_model=SignalDetailResponse)
async def get_signal(
    signal_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await db.execute(select(Signal).where(Signal.id == signal_id))
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signal not found")

    # Load snapshot
    snap_result = await db.execute(select(SignalSnapshot).where(SignalSnapshot.signal_id == signal_id))
    snapshot = snap_result.scalar_one_or_none()

    breakdown = None
    if snapshot and snapshot.score_breakdown:
        breakdown = ScoreBreakdown(**snapshot.score_breakdown)

    return SignalDetailResponse(
        **SignalResponse.model_validate(signal, from_attributes=True).model_dump(),
        breakdown=breakdown,
        snapshot=snapshot.model_dump() if snapshot else {},
    )


@router.get("/{signal_id}/snapshot", response_model=dict)
async def get_signal_snapshot(
    signal_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await db.execute(select(SignalSnapshot).where(SignalSnapshot.signal_id == signal_id))
    snapshot = result.scalar_one_or_none()
    if not snapshot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
    return snapshot.model_dump()


# ============================================================
# Shadow Portfolio (blocked signals)
# ============================================================
class ShadowEntry(BaseModel):
    id: UUID
    signal_id: UUID
    block_reason: str
    entry_price: float
    stop_price: float
    tp1: float
    tp2: float
    tp3: float
    rr: float
    score: int
    outcome: Optional[str]
    pnl_r: Optional[float]
    closed_at: Optional[datetime]
    created_at: datetime


@router.get("/shadow/portfolio", response_model=List[ShadowEntry])
async def shadow_portfolio(
    symbol: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    query = select(ShadowPortfolio).join(Signal).order_by(desc(ShadowPortfolio.created_at)).limit(limit)
    if symbol:
        query = query.where(Signal.symbol == symbol.upper())
    if outcome:
        query = query.where(ShadowPortfolio.outcome == outcome)
    result = await db.execute(query)
    entries = result.scalars().all()
    return [ShadowEntry.model_validate(e, from_attributes=True) for e in entries]


@router.get("/shadow/stats")
async def shadow_stats(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from_date = datetime.now(timezone.utc) - __import__('datetime').timedelta(days=days)
    query = select(ShadowPortfolio).join(Signal).where(ShadowPortfolio.created_at >= from_date)
    result = await db.execute(query)
    entries = result.scalars().all()

    total = len(entries)
    if total == 0:
        return {"total": 0, "filter_value": 0, "message": "No shadow data"}

    closed = [e for e in entries if e.outcome in ("win", "loss")]
    wins = [e for e in closed if e.outcome == "win"]
    losses = [e for e in closed if e.outcome == "loss"]

    real_query = select(Signal).where(Signal.ok == True).where(Signal.created_at >= from_date)
    real_result = await db.execute(real_query)
    real_signals = real_result.scalars().all()

    real_closed = [s for s in real_signals if s.reason == "ok"]  # simplified
    # In production, track actual outcomes

    expectancy_shadow = sum(e.pnl_r or 0 for e in closed) / len(closed) if closed else 0
    expectancy_real = 0  # Would need actual trade outcomes

    return {
        "period_days": days,
        "shadow_total": total,
        "shadow_closed": len(closed),
        "shadow_wins": len(wins),
        "shadow_losses": len(losses),
        "shadow_win_rate": len(wins) / len(closed) if closed else 0,
        "shadow_expectancy_r": expectancy_shadow,
        "real_signals_emitted": len(real_signals),
        "filter_value": expectancy_real - expectancy_shadow,
    }
