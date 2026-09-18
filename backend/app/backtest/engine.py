# Backtest Engine Core
# Runs signal generation over historical data with costs, slippage, funding

import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict
import logging
import json
from pathlib import Path
from sqlalchemy import select

from app.core.signal_core import generate_signal, SignalDecision, Side, TrendState
from app.backtest.config import backtest_settings
from app.backtest.metrics import (
    calculate_metrics, deflated_sharpe_ratio, probability_of_backtest_overfitting,
    combinatorial_purged_kfold, monte_carlo_simulation, walk_forward_splits
)
from app.database import async_session_maker
from app.models import Candle, Signal

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """Simulated trade from backtest"""
    entry_time: datetime
    exit_time: Optional[datetime]
    symbol: str
    side: Side
    entry_price: float
    exit_price: Optional[float]
    stop_price: float
    tp1: float
    tp2: float
    tp3: float
    size_usd: float
    leverage: int
    pnl_r: Optional[float] = None
    exit_reason: Optional[str] = None  # 'tp1', 'tp2', 'tp3', 'stop', 'time', 'signal_reverse'
    fees_paid: float = 0.0
    funding_paid: float = 0.0
    slippage_paid: float = 0.0


@dataclass
class BacktestResult:
    """Complete backtest result"""
    symbol: str
    timeframe: str
    start_date: datetime
    end_date: datetime

    # Equity curve
    equity_curve: pd.Series

    # Trades
    trades: List[Trade]

    # Metrics
    metrics: Any  # BacktestMetrics

    # Config used
    config: Dict

    # Metadata
    engine_version: str = "triple-screen-v1"
    score_version: str = "v1"
    risk_version: str = "v1"
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BacktestEngine:
    """
    Institutional-grade backtest engine
    Runs signal generation with realistic costs, slippage, funding
    """

    def __init__(self, config: Dict = None):
        self.config = {**backtest_settings.model_dump(), **(config or {})}
        self.trades: List[Trade] = []
        self.equity = 1.0  # Start with 1 unit of capital
        self.equity_curve: List[float] = [1.0]
        self.open_trades: Dict[str, Trade] = {}  # symbol -> trade
        self.position_sizes: Dict[str, float] = {}  # symbol -> size in USD

    async def run_backtest(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        source: str = 'binance',
        mode: str = 'swing',
        initial_capital: float = 10000,
        risk_per_trade_pct: float = 0.01  # 1% per trade
    ) -> BacktestResult:
        """
        Run backtest on historical data
        """
        logger.info(f"Starting backtest: {symbol} {timeframe} {start_date} to {end_date}")

        # Fetch data
        tf1_df, tf2_df, tf3_df = await self._fetch_multi_tf_data(
            symbol, start_date, end_date, source
        )

        if tf1_df is None or len(tf1_df) < 120:
            raise ValueError(f"Insufficient data for {symbol}")

        # Initialize
        self.equity = initial_capital
        self.equity_curve = [initial_capital]
        self.trades = []
        self.open_trades = {}
        equity_timestamps = [start_date]

        # Get unique timestamps from TF3 (trigger timeframe)
        timestamps = tf3_df.index.unique().sort_values()
        timestamps = timestamps[(timestamps >= start_date) & (timestamps <= end_date)]

        logger.info(f"Processing {len(timestamps)} candles")

        for i, ts in enumerate(timestamps):
            # Get data up to this timestamp (no lookahead)
            tf1_slice = tf1_df[tf1_df.index <= ts].tail(200)
            tf2_slice = tf2_df[tf2_df.index <= ts].tail(200)
            tf3_slice = tf3_df[tf3_df.index <= ts].tail(200)

            if len(tf1_slice) < 40 or len(tf2_slice) < 40 or len(tf3_slice) < 40:
                self.equity_curve.append(self.equity)
                equity_timestamps.append(ts)
                continue

            # Check open trades for exits
            await self._check_exits(ts, tf3_slice, symbol)

            # Generate signal
            decision = generate_signal(tf1_slice, tf2_slice, tf3_slice, mode=mode)

            # Execute if signal OK and no open position
            if decision.ok and symbol not in self.open_trades:
                await self._execute_signal(decision, ts, symbol, risk_per_trade_pct)

            # Record equity
            self.equity_curve.append(self.equity)
            equity_timestamps.append(ts)

            # Progress
            if i % 1000 == 0:
                logger.info(f"Progress: {i}/{len(timestamps)} equity={self.equity:.2f}")

        # Close any remaining open trades
        await self._close_all_trades(timestamps[-1], tf3_df, symbol)

        # Build equity series
        equity_series = pd.Series(self.equity_curve[1:], index=equity_timestamps[1:])

        # Calculate metrics
        trades_df = pd.DataFrame([{
            'entry_time': t.entry_time,
            'exit_time': t.exit_time,
            'symbol': t.symbol,
            'side': t.side.value,
            'pnl_r': t.pnl_r,
            'exit_reason': t.exit_reason,
            'fees_paid': t.fees_paid,
            'funding_paid': t.funding_paid,
            'slippage_paid': t.slippage_paid,
        } for t in self.trades])

        metrics = calculate_metrics(equity_series, trades_df)

        # Monte Carlo
        returns = equity_series.pct_change().dropna()
        mc_results = monte_carlo_simulation(
            returns,
            n_paths=self.config['mc_paths'],
            t_nu=self.config['t_distribution_nu']
        )
        metrics.mc_p5_equity = mc_results['p5_equity']
        metrics.mc_p50_equity = mc_results['p50_equity']
        metrics.mc_p95_equity = mc_results['p95_equity']
        metrics.mc_p5_max_dd = mc_results['p5_max_dd']

        # Segment analysis
        metrics.segments = self._analyze_segments(trades_df, timestamps)

        result = BacktestResult(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            equity_curve=equity_series,
            trades=self.trades,
            metrics=metrics,
            config=self.config
        )

        logger.info(f"Backtest complete: {symbol} equity={self.equity:.2f} trades={len(self.trades)}")
        return result

    async def _fetch_multi_tf_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        source: str
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Fetch multi-timeframe data from DB"""
        async with async_session_maker() as session:
            # TF1: Daily (trend)
            tf1_result = await session.execute(
                select(Candle)
                .where(Candle.symbol == symbol)
                .where(Candle.timeframe == '1d')
                .where(Candle.source == source)
                .where(Candle.is_final == True)
                .where(Candle.timestamp >= start_date - timedelta(days=400))  # Extra for indicators
                .where(Candle.timestamp <= end_date)
                .order_by(Candle.timestamp)
            )
            tf1_rows = tf1_result.scalars().all()

            # TF2: 4h (correction)
            tf2_result = await session.execute(
                select(Candle)
                .where(Candle.symbol == symbol)
                .where(Candle.timeframe == '4h')
                .where(Candle.source == source)
                .where(Candle.is_final == True)
                .where(Candle.timestamp >= start_date - timedelta(days=100))
                .where(Candle.timestamp <= end_date)
                .order_by(Candle.timestamp)
            )
            tf2_rows = tf2_result.scalars().all()

            # TF3: 1h (trigger)
            tf3_result = await session.execute(
                select(Candle)
                .where(Candle.symbol == symbol)
                .where(Candle.timeframe == '1h')
                .where(Candle.source == source)
                .where(Candle.is_final == True)
                .where(Candle.timestamp >= start_date - timedelta(days=30))
                .where(Candle.timestamp <= end_date)
                .order_by(Candle.timestamp)
            )
            tf3_rows = tf3_result.scalars().all()

        def rows_to_df(rows):
            if not rows:
                return pd.DataFrame()
            df = pd.DataFrame([{
                'timestamp': r.timestamp,
                'open': r.open,
                'high': r.high,
                'low': r.low,
                'close': r.close,
                'volume': r.volume,
            } for r in rows])
            df.set_index('timestamp', inplace=True)
            return df

        return rows_to_df(tf1_rows), rows_to_df(tf2_rows), rows_to_df(tf3_rows)

    async def _execute_signal(
        self,
        decision: SignalDecision,
        timestamp: datetime,
        symbol: str,
        risk_per_trade_pct: float
    ):
        """Execute a new trade from signal"""
        # Calculate position size
        risk_amount = self.equity * risk_per_trade_pct
        risk_per_unit = abs(decision.entry - decision.stop)
        if risk_per_unit <= 0:
            return

        size_usd = risk_amount / risk_per_unit * decision.entry

        # Apply costs at entry
        slippage_cost = size_usd * self.config['slippage_swing_bps'] / 10000
        fee_cost = size_usd * self.config['taker_fee_bps'] / 10000  # Market order
        total_entry_cost = slippage_cost + fee_cost

        trade = Trade(
            entry_time=timestamp,
            exit_time=None,
            symbol=symbol,
            side=decision.side,
            entry_price=decision.entry,
            exit_price=None,
            stop_price=decision.stop,
            tp1=decision.tp1,
            tp2=decision.tp2,
            tp3=decision.tp3,
            size_usd=size_usd,
            leverage=1,
            fees_paid=fee_cost,
            slippage_paid=slippage_cost,
        )

        self.open_trades[symbol] = trade
        self.equity -= total_entry_cost
        logger.debug(f"Opened {decision.side.value} {symbol} @ {decision.entry:.2f} size=${size_usd:.0f}")

    async def _check_exits(self, timestamp: datetime, tf3_df: pd.DataFrame, symbol: str):
        """Check if any open trade should be exited"""
        if symbol not in self.open_trades:
            return

        trade = self.open_trades[symbol]
        current_price = tf3_df.iloc[-1].close if len(tf3_df) > 0 else None
        if current_price is None:
            return

        # Check stop loss
        if trade.side == Side.BUY and current_price <= trade.stop_price:
            await self._close_trade(trade, timestamp, trade.stop_price, 'stop')
            return
        elif trade.side == Side.SELL and current_price >= trade.stop_price:
            await self._close_trade(trade, timestamp, trade.stop_price, 'stop')
            return

        # Check take profits
        if trade.side == Side.BUY:
            if current_price >= trade.tp3:
                await self._close_trade(trade, timestamp, trade.tp3, 'tp3')
            elif current_price >= trade.tp2:
                await self._close_trade(trade, timestamp, trade.tp2, 'tp2')
            elif current_price >= trade.tp1:
                await self._close_trade(trade, timestamp, trade.tp1, 'tp1')
        else:
            if current_price <= trade.tp3:
                await self._close_trade(trade, timestamp, trade.tp3, 'tp3')
            elif current_price <= trade.tp2:
                await self._close_trade(trade, timestamp, trade.tp2, 'tp2')
            elif current_price <= trade.tp1:
                await self._close_trade(trade, timestamp, trade.tp1, 'tp1')

    async def _close_trade(self, trade: Trade, timestamp: datetime, exit_price: float, reason: str):
        """Close a trade and calculate PnL"""
        # PnL in R multiples
        if trade.side == Side.BUY:
            pnl = (exit_price - trade.entry_price) / (trade.entry_price - trade.stop_price)
        else:
            pnl = (trade.entry_price - exit_price) / (trade.stop_price - trade.entry_price)

        # Exit costs
        slippage_cost = trade.size_usd * self.config['slippage_swing_bps'] / 10000
        fee_cost = trade.size_usd * self.config['taker_fee_bps'] / 10000

        trade.exit_time = timestamp
        trade.exit_price = exit_price
        trade.pnl_r = pnl
        trade.exit_reason = reason
        trade.fees_paid += fee_cost
        trade.slippage_paid += slippage_cost

        # Update equity
        pnl_usd = trade.size_usd * pnl
        self.equity += pnl_usd - fee_cost - slippage_cost

        # Move to closed trades
        self.trades.append(trade)
        del self.open_trades[trade.symbol]

        logger.debug(f"Closed {trade.side.value} {trade.symbol} @ {exit_price:.2f} pnl_r={pnl:.2f} reason={reason}")

    async def _close_all_trades(self, timestamp: datetime, tf3_df: pd.DataFrame, symbol: str):
        """Force close all open trades at end of backtest"""
        for sym, trade in list(self.open_trades.items()):
            current_price = tf3_df.iloc[-1].close if len(tf3_df) > 0 else trade.entry_price
            await self._close_trade(trade, timestamp, current_price, 'time')

    def _analyze_segments(self, trades_df: pd.DataFrame, timestamps: pd.DatetimeIndex) -> Dict:
        """Analyze performance by segment"""
        segments = {}

        if len(trades_df) == 0:
            return segments

        # By session (UTC hour)
        trades_df['hour'] = trades_df['entry_time'].dt.hour
        session_map = {
            'Asia': range(0, 8),
            'London': range(8, 16),
            'NY': range(13, 21),
        }

        for session, hours in session_map.items():
            mask = trades_df['hour'].isin(hours)
            if mask.any():
                seg_trades = trades_df[mask]
                segments[f'session_{session}'] = {
                    'trades': int(mask.sum()),
                    'win_rate': float((seg_trades['pnl_r'] > 0).mean()),
                    'expectancy': float(seg_trades['pnl_r'].mean()),
                }

        # By day of week
        trades_df['day'] = trades_df['entry_time'].dt.dayofweek
        for day in range(7):
            mask = trades_df['day'] == day
            if mask.any():
                seg_trades = trades_df[mask]
                segments[f'day_{day}'] = {
                    'trades': int(mask.sum()),
                    'win_rate': float((seg_trades['pnl_r'] > 0).mean()),
                    'expectancy': float(seg_trades['pnl_r'].mean()),
                }

        return segments


async def run_walk_forward_backtest(
    symbol: str,
    timeframe: str,
    start_date: datetime,
    end_date: datetime,
    config: Dict = None
) -> Dict:
    """
    Run walk-forward backtest with multiple train/test windows
    Returns aggregated results
    """
    engine = BacktestEngine(config)
    results = []

    # Get walk-forward splits
    # For simplicity, use monthly splits
    n_months = (end_date.year - start_date.year) * 12 + end_date.month - start_date.month

    for i in range(0, n_months, backtest_settings.test_months):
        train_start = start_date + timedelta(days=30 * i)
        train_end = train_start + timedelta(days=30 * backtest_settings.train_months)
        test_start = train_end
        test_end = min(test_start + timedelta(days=30 * backtest_settings.test_months), end_date)

        if train_end > end_date or test_start > end_date:
            break

        logger.info(f"Walk-forward window: train {train_start} to {train_end}, test {test_start} to {test_end}")

        try:
            result = await engine.run_backtest(
                symbol=symbol,
                timeframe=timeframe,
                start_date=train_start,
                end_date=test_end,
                mode='swing'
            )
            results.append({
                'train_start': train_start,
                'train_end': train_end,
                'test_start': test_start,
                'test_end': test_end,
                'result': result
            })
        except Exception as e:
            logger.error(f"Walk-forward window failed: {e}")
            results.append({
                'train_start': train_start,
                'train_end': train_end,
                'test_start': test_start,
                'test_end': test_end,
                'error': str(e)
            })

    return {'windows': results}


async def run_purged_kfold_backtest(
    symbol: str,
    timeframe: str,
    start_date: datetime,
    end_date: datetime,
    n_splits: int = 5,
    embargo_pct: float = 0.01,
    config: Dict = None
) -> Dict:
    """
    Run Purged K-Fold cross-validation backtest
    """
    # Fetch all data first
    engine = BacktestEngine(config)
    tf1_df, tf2_df, tf3_df = await engine._fetch_multi_tf_data(
        symbol, start_date, end_date, 'binance'
    )

    if tf1_df is None or len(tf1_df) < 120:
        raise ValueError("Insufficient data")

    # Use TF3 timestamps for splitting
    timestamps = tf3_df.index.unique().sort_values()
    n_samples = len(timestamps)

    # Generate splits
    splits = combinatorial_purged_kfold(n_samples, n_splits, embargo_pct)

    fold_results = []

    for fold, (train_idx, test_idx) in enumerate(splits):
        train_start = timestamps[train_idx[0]]
        train_end = timestamps[train_idx[-1]]
        test_start = timestamps[test_idx[0]]
        test_end = timestamps[test_idx[-1]]

        logger.info(f"Fold {fold+1}/{n_splits}: train {len(train_idx)}, test {len(test_idx)}")

        # Create engine for this fold
        fold_engine = BacktestEngine(config)

        try:
            result = await fold_engine.run_backtest(
                symbol=symbol,
                timeframe=timeframe,
                start_date=train_start,
                end_date=test_end,
                mode='swing'
            )
            fold_results.append({
                'fold': fold,
                'train_start': train_start,
                'train_end': train_end,
                'test_start': test_start,
                'test_end': test_end,
                'metrics': result.metrics,
                'n_trades': len(result.trades)
            })
        except Exception as e:
            logger.error(f"Fold {fold} failed: {e}")
            fold_results.append({
                'fold': fold,
                'error': str(e)
            })

    # Calculate PBO
    oos_sharpes = [r['metrics'].sharpe_ratio for r in fold_results if 'metrics' in r]
    pbo = probability_of_backtest_overfitting(np.array(oos_sharpes), n_splits) if oos_sharpes else 1.0

    return {
        'folds': fold_results,
        'pbo': pbo,
        'mean_oos_sharpe': np.mean(oos_sharpes) if oos_sharpes else 0,
        'std_oos_sharpe': np.std(oos_sharpes) if oos_sharpes else 0
    }


def save_backtest_result(result: BacktestResult, output_dir: str = "backtest_results"):
    """Save backtest result to disk"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    filename = f"{result.symbol}_{result.timeframe}_{result.start_date.strftime('%Y%m%d')}_{result.end_date.strftime('%Y%m%d')}.json"
    filepath = Path(output_dir) / filename

    # Convert to serializable dict
    data = {
        'symbol': result.symbol,
        'timeframe': result.timeframe,
        'start_date': result.start_date.isoformat(),
        'end_date': result.end_date.isoformat(),
        'equity_curve': result.equity_curve.to_json(),
        'trades': [{
            'entry_time': t.entry_time.isoformat(),
            'exit_time': t.exit_time.isoformat() if t.exit_time else None,
            'symbol': t.symbol,
            'side': t.side.value,
            'entry_price': t.entry_price,
            'exit_price': t.exit_price,
            'stop_price': t.stop_price,
            'tp1': t.tp1,
            'tp2': t.tp2,
            'tp3': t.tp3,
            'size_usd': t.size_usd,
            'leverage': t.leverage,
            'pnl_r': t.pnl_r,
            'exit_reason': t.exit_reason,
            'fees_paid': t.fees_paid,
            'funding_paid': t.funding_paid,
            'slippage_paid': t.slippage_paid,
        } for t in result.trades],
        'metrics': {
            'total_return': result.metrics.total_return,
            'annualized_return': result.metrics.annualized_return,
            'volatility': result.metrics.volatility,
            'sharpe_ratio': result.metrics.sharpe_ratio,
            'sortino_ratio': result.metrics.sortino_ratio,
            'calmar_ratio': result.metrics.calmar_ratio,
            'max_drawdown': result.metrics.max_drawdown,
            'max_drawdown_duration': result.metrics.max_drawdown_duration,
            'total_trades': result.metrics.total_trades,
            'win_rate': result.metrics.win_rate,
            'profit_factor': result.metrics.profit_factor,
            'expectancy': result.metrics.expectancy,
            'expectancy_per_trade': result.metrics.expectancy_per_trade,
            'r_multiple_mean': result.metrics.r_multiple_mean,
            'r_multiple_std': result.metrics.r_multiple_std,
            'r_multiple_median': result.metrics.r_multiple_median,
            'deflated_sharpe': result.metrics.deflated_sharpe,
            'pbo': result.metrics.pbo,
            'mc_p5_equity': result.metrics.mc_p5_equity,
            'mc_p50_equity': result.metrics.mc_p50_equity,
            'mc_p95_equity': result.metrics.mc_p95_equity,
            'mc_p5_max_dd': result.metrics.mc_p5_max_dd,
            'segments': result.metrics.segments,
        },
        'config': result.config,
        'engine_version': result.engine_version,
        'score_version': result.score_version,
        'risk_version': result.risk_version,
        'completed_at': result.completed_at.isoformat(),
    }

    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

    logger.info(f"Saved backtest result to {filepath}")
    return filepath
