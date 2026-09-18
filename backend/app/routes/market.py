"""Public regime computed from real, closed candles stored by ingestion."""
import math
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import Candle
from app.core.signal_core import detect_regime

router = APIRouter(tags=["market"])

@router.get("/regime")
async def regime(symbol: str = Query("BTC/USDT", pattern=r"^BTC/USDT$"),
                 timeframe: str = Query("4h", pattern=r"^(1h|4h|1d)$"),
                 db: AsyncSession = Depends(get_db)):
    period = timedelta(hours={"1h": 1, "4h": 4, "1d": 24}[timeframe])
    now = datetime.now(timezone.utc)
    result = await db.execute(select(Candle).where(
        Candle.symbol == symbol, Candle.timeframe == timeframe,
        Candle.source == "binance", Candle.is_final.is_(True),
        Candle.timestamp <= now - period,
    ).order_by(Candle.timestamp.desc()).limit(200))
    rows = list(reversed(result.scalars().all()))
    if len(rows) < 120 or now - (rows[-1].timestamp + period) > period:
        raise HTTPException(503, "Candles reais insuficientes ou desatualizados")
    if any(b.timestamp - a.timestamp != period for a, b in zip(rows, rows[1:])):
        raise HTTPException(503, "Histórico de candles com lacunas")
    frame = pd.DataFrame([{k: getattr(c, k) for k in ("open", "high", "low", "close", "volume")} for c in rows], index=pd.DatetimeIndex([c.timestamp for c in rows]))
    report = asdict(detect_regime(frame))
    if not all(math.isfinite(report[k]) for k in ("adx", "bbw_pct", "atr_pct")):
        raise HTTPException(503, "Indicadores indisponíveis")
    return {**report, "symbol": symbol, "timeframe": timeframe,
            "timestamp": rows[-1].timestamp, "source": "Binance Spot"}
