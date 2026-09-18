from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone, timedelta
import asyncio

from app.database import get_db
from app.routes.auth import get_current_user
from app.backtest import (
    BacktestEngine, run_walk_forward_backtest, run_purged_kfold_backtest,
    save_backtest_result
)
from app.models import User

router = APIRouter(prefix="/backtest", tags=["backtest"])


class BacktestRequest(BaseModel):
    symbol: str
    timeframe: str = "4h"
    start_date: datetime
    end_date: datetime
    source: str = "binance"
    mode: str = "swing"
    initial_capital: float = 10000
    risk_per_trade_pct: float = 0.01
    config: Optional[dict] = None


class WalkForwardRequest(BaseModel):
    symbol: str
    timeframe: str = "4h"
    start_date: datetime
    end_date: datetime
    config: Optional[dict] = None


class PurgedKFoldRequest(BaseModel):
    symbol: str
    timeframe: str = "4h"
    start_date: datetime
    end_date: datetime
    n_splits: int = 5
    embargo_pct: float = 0.01
    config: Optional[dict] = None


class BacktestResponse(BaseModel):
    symbol: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    total_return: float
    annualized_return: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    total_trades: int
    win_rate: float
    profit_factor: float
    expectancy: float
    mc_p5_equity: Optional[float]
    mc_p50_equity: Optional[float]
    mc_p95_equity: Optional[float]
    mc_p5_max_dd: Optional[float]
    completed_at: datetime


@router.post("/run", response_model=BacktestResponse)
async def run_backtest(
    request: BacktestRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """Run a single backtest"""
    engine = BacktestEngine(request.config)

    try:
        result = await engine.run_backtest(
            symbol=request.symbol.upper(),
            timeframe=request.timeframe,
            start_date=request.start_date,
            end_date=request.end_date,
            source=request.source,
            mode=request.mode,
            initial_capital=request.initial_capital,
            risk_per_trade_pct=request.risk_per_trade_pct
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backtest failed: {str(e)}")

    # Save in background
    background_tasks.add_task(save_backtest_result, result)

    m = result.metrics
    return BacktestResponse(
        symbol=result.symbol,
        timeframe=result.timeframe,
        start_date=result.start_date,
        end_date=result.end_date,
        total_return=m.total_return,
        annualized_return=m.annualized_return,
        sharpe_ratio=m.sharpe_ratio,
        sortino_ratio=m.sortino_ratio,
        calmar_ratio=m.calmar_ratio,
        max_drawdown=m.max_drawdown,
        total_trades=m.total_trades,
        win_rate=m.win_rate,
        profit_factor=m.profit_factor,
        expectancy=m.expectancy,
        mc_p5_equity=m.mc_p5_equity,
        mc_p50_equity=m.mc_p50_equity,
        mc_p95_equity=m.mc_p95_equity,
        mc_p5_max_dd=m.mc_p5_max_dd,
        completed_at=result.completed_at
    )


@router.post("/walk-forward")
async def run_walk_forward(
    request: WalkForwardRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """Run walk-forward backtest"""
    try:
        result = await run_walk_forward_backtest(
            symbol=request.symbol.upper(),
            timeframe=request.timeframe,
            start_date=request.start_date,
            end_date=request.end_date,
            config=request.config
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Walk-forward backtest failed: {str(e)}")

    return {"windows": len(result['windows']), "results": result}


@router.post("/purged-kfold")
async def run_purged_kfold(
    request: PurgedKFoldRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """Run Purged K-Fold cross-validation backtest"""
    try:
        result = await run_purged_kfold_backtest(
            symbol=request.symbol.upper(),
            timeframe=request.timeframe,
            start_date=request.start_date,
            end_date=request.end_date,
            n_splits=request.n_splits,
            embargo_pct=request.embargo_pct,
            config=request.config
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Purged K-Fold backtest failed: {str(e)}")

    return result


@router.get("/results")
async def list_backtest_results(
    symbol: Optional[str] = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user)
):
    """List saved backtest results"""
    import os
    from pathlib import Path

    results_dir = Path("backtest_results")
    if not results_dir.exists():
        return {"results": []}

    files = list(results_dir.glob("*.json"))
    if symbol:
        files = [f for f in files if f.name.startswith(symbol.upper() + "_")]

    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    files = files[:limit]

    results = []
    for f in files:
        try:
            import json
            with open(f) as fp:
                data = json.load(fp)
            results.append({
                "filename": f.name,
                "symbol": data.get("symbol"),
                "timeframe": data.get("timeframe"),
                "start_date": data.get("start_date"),
                "end_date": data.get("end_date"),
                "total_return": data.get("metrics", {}).get("total_return"),
                "sharpe_ratio": data.get("metrics", {}).get("sharpe_ratio"),
                "total_trades": data.get("metrics", {}).get("total_trades"),
                "completed_at": data.get("completed_at"),
            })
        except Exception:
            continue

    return {"results": results}


@router.get("/results/{filename}")
async def get_backtest_result(
    filename: str,
    current_user: User = Depends(get_current_user)
):
    """Get detailed backtest result"""
    from pathlib import Path
    import json

    filepath = Path("backtest_results") / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Result not found")

    with open(filepath) as f:
        data = json.load(f)

    return data
