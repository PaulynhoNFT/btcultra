# Backtest Metrics & Statistics
# Institutional-grade performance metrics

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional, Dict, List
from scipy import stats
import warnings
warnings.filterwarnings('ignore')


@dataclass
class BacktestMetrics:
    """Complete backtest metrics"""
    # Basic
    total_return: float
    annualized_return: float
    volatility: float

    # Risk-adjusted
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float

    # Drawdown
    max_drawdown: float
    max_drawdown_duration: int  # days

    # Trade stats
    total_trades: int
    win_rate: float
    profit_factor: float
    expectancy: float
    expectancy_per_trade: float

    # R multiples
    r_multiples: List[float]
    r_multiple_mean: float
    r_multiple_std: float
    r_multiple_median: float

    # Advanced
    deflated_sharpe: Optional[float] = None
    pbo: Optional[float] = None  # Probability of Backtest Overfitting

    # Monte Carlo
    mc_p5_equity: Optional[float] = None
    mc_p50_equity: Optional[float] = None
    mc_p95_equity: Optional[float] = None
    mc_p5_max_dd: Optional[float] = None

    # Segment breakdown
    segments: Optional[Dict] = None


def calculate_metrics(
    equity_curve: pd.Series,
    trades: pd.DataFrame,
    risk_free_rate: float = 0.02,
    periods_per_year: int = 365 * 24  # 4h candles
) -> BacktestMetrics:
    """Calculate comprehensive backtest metrics"""

    if len(equity_curve) < 2:
        return BacktestMetrics(
            total_return=0, annualized_return=0, volatility=0,
            sharpe_ratio=0, sortino_ratio=0, calmar_ratio=0,
            max_drawdown=0, max_drawdown_duration=0,
            total_trades=0, win_rate=0, profit_factor=0, expectancy=0, expectancy_per_trade=0,
            r_multiples=[], r_multiple_mean=0, r_multiple_std=0, r_multiple_median=0
        )

    # Returns
    returns = equity_curve.pct_change().dropna()
    total_return = (equity_curve.iloc[-1] / equity_curve.iloc[0]) - 1
    n_years = len(returns) / periods_per_year
    annualized_return = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0
    volatility = returns.std() * np.sqrt(periods_per_year)

    # Sharpe
    excess_returns = returns - risk_free_rate / periods_per_year
    sharpe_ratio = excess_returns.mean() / returns.std() * np.sqrt(periods_per_year) if returns.std() > 0 else 0

    # Sortino (downside deviation)
    downside_returns = returns[returns < 0]
    downside_std = downside_returns.std() * np.sqrt(periods_per_year) if len(downside_returns) > 0 else 0
    sortino_ratio = excess_returns.mean() / downside_std * np.sqrt(periods_per_year) if downside_std > 0 else 0

    # Drawdown
    running_max = equity_curve.expanding().max()
    drawdown = (equity_curve - running_max) / running_max
    max_drawdown = drawdown.min()

    # Max drawdown duration
    dd_duration = 0
    max_dd_duration = 0
    for dd in drawdown:
        if dd < 0:
            dd_duration += 1
            max_dd_duration = max(max_dd_duration, dd_duration)
        else:
            dd_duration = 0

    # Calmar
    calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown < 0 else 0

    # Trade stats
    if len(trades) > 0:
        total_trades = len(trades)
        wins = trades[trades['pnl_r'] > 0]
        losses = trades[trades['pnl_r'] <= 0]
        win_rate = len(wins) / total_trades

        gross_profit = wins['pnl_r'].sum() if len(wins) > 0 else 0
        gross_loss = abs(losses['pnl_r'].sum()) if len(losses) > 0 else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.inf

        expectancy = trades['pnl_r'].mean()
        expectancy_per_trade = expectancy

        r_multiples = trades['pnl_r'].tolist()
        r_multiple_mean = np.mean(r_multiples)
        r_multiple_std = np.std(r_multiples, ddof=1)
        r_multiple_median = np.median(r_multiples)
    else:
        total_trades = 0
        win_rate = 0
        profit_factor = 0
        expectancy = 0
        expectancy_per_trade = 0
        r_multiples = []
        r_multiple_mean = 0
        r_multiple_std = 0
        r_multiple_median = 0

    return BacktestMetrics(
        total_return=total_return,
        annualized_return=annualized_return,
        volatility=volatility,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=sortino_ratio,
        calmar_ratio=calmar_ratio,
        max_drawdown=max_drawdown,
        max_drawdown_duration=max_dd_duration,
        total_trades=total_trades,
        win_rate=win_rate,
        profit_factor=profit_factor,
        expectancy=expectancy,
        expectancy_per_trade=expectancy_per_trade,
        r_multiples=r_multiples,
        r_multiple_mean=r_multiple_mean,
        r_multiple_std=r_multiple_std,
        r_multiple_median=r_multiple_median
    )


def deflated_sharpe_ratio(
    sharpe: float,
    n_trials: int,
    n_periods: int,
    skew: float = 0,
    kurtosis: float = 3
) -> float:
    """
    Deflated Sharpe Ratio (López de Prado)
    Adjusts Sharpe for multiple testing / selection bias
    """
    if n_trials <= 1 or n_periods <= 0:
        return sharpe

    # Expected maximum Sharpe under null
    emc = stats.norm.ppf(1 - 1/n_trials)  # Expected max of n_trials standard normals
    # Variance of Sharpe estimator
    var_sharpe = (1 + 0.5 * sharpe**2 - skew * sharpe + (kurtosis - 3) / 4 * sharpe**2) / n_periods

    # Deflated Sharpe
    dsr = (sharpe - emc * np.sqrt(var_sharpe)) / np.sqrt(var_sharpe)
    return dsr


def probability_of_backtest_overfitting(
    sharpe_ratios: np.ndarray,
    n_splits: int
) -> float:
    """
    Probability of Backtest Overfitting (PBO) - López de Prado
    Proportion of paths where out-of-sample SR < median(SR)
    """
    if len(sharpe_ratios) == 0:
        return 1.0

    median_sr = np.median(sharpe_ratios)

    # PBO = proportion where SR < median(SR)
    pbo = np.mean(sharpe_ratios < median_sr)
    return float(pbo)


def combinatorial_purged_kfold(
    n_samples: int,
    n_splits: int = 5,
    embargo_pct: float = 0.01
) -> List[tuple]:
    """
    Generate purged K-fold indices with embargo
    Returns list of (train_idx, test_idx) tuples
    """
    embargo = int(n_samples * embargo_pct)
    indices = np.arange(n_samples)
    fold_size = n_samples // n_splits

    splits = []
    for i in range(n_splits):
        test_start = i * fold_size
        test_end = min((i + 1) * fold_size, n_samples)
        test_idx = indices[test_start:test_end]

        # Purge: remove embargo samples around test set
        purge_start = max(0, test_start - embargo)
        purge_end = min(n_samples, test_end + embargo)

        train_idx = np.concatenate([
            indices[:purge_start],
            indices[purge_end:]
        ])

        splits.append((train_idx, test_idx))

    return splits


def monte_carlo_simulation(
    returns: pd.Series,
    n_paths: int = 10000,
    t_nu: float = 4.0,
    initial_capital: float = 1.0
) -> Dict:
    """
    Monte Carlo simulation with t-distribution (fat tails)
    Returns equity paths statistics
    """
    n_periods = len(returns)
    mean_ret = returns.mean()
    std_ret = returns.std()

    # Generate t-distributed returns
    np.random.seed(42)
    t_shocks = np.random.standard_t(t_nu, size=(n_paths, n_periods))
    # Scale to match return distribution
    simulated_returns = mean_ret + std_ret * t_shocks * np.sqrt((t_nu - 2) / t_nu)

    # Build equity curves
    equity_paths = np.zeros((n_paths, n_periods + 1))
    equity_paths[:, 0] = initial_capital

    for i in range(n_paths):
        equity_paths[i, 1:] = initial_capital * np.cumprod(1 + simulated_returns[i])

    # Statistics
    final_equity = equity_paths[:, -1]

    # Drawdowns per path
    max_dds = []
    for i in range(n_paths):
        eq = equity_paths[i]
        running_max = np.maximum.accumulate(eq)
        dd = (eq - running_max) / running_max
        max_dds.append(dd.min())

    return {
        'equity_paths': equity_paths,
        'final_equity': final_equity,
        'p5_equity': np.percentile(final_equity, 5),
        'p50_equity': np.percentile(final_equity, 50),
        'p95_equity': np.percentile(final_equity, 95),
        'p5_max_dd': np.percentile(max_dds, 5),
        'mean_final': final_equity.mean(),
        'std_final': final_equity.std()
    }


def walk_forward_splits(
    n_samples: int,
    train_months: int = 6,
    test_months: int = 2,
    period_per_sample: str = '4h'
) -> List[tuple]:
    """
    Generate walk-forward train/test splits
    Returns list of (train_start, train_end, test_start, test_end)
    """
    # Convert months to samples
    freq_map = {'1m': 43200, '5m': 8640, '15m': 2880, '1h': 720, '4h': 180, '1d': 30}
    samples_per_month = freq_map.get(period_per_sample, 180)

    train_samples = train_months * samples_per_month
    test_samples = test_months * samples_per_month

    splits = []
    for test_start in range(train_samples, n_samples - test_samples + 1, test_samples):
        train_start = max(0, test_start - train_samples)
        train_end = test_start
        test_end = min(n_samples, test_start + test_samples)

        splits.append((train_start, train_end, test_start, test_end))

    return splits
