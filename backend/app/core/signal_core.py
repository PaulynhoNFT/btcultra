# language: Python 3.10+, file: signal_core.py, target: any
# *Triple Screen de Elder — funções puras, apenas candles fechados, determinístico*
# *sem I/O, sem efeitos colaterais. alimenta com DataFrames: open,high,low,close,volume*

from __future__ import annotations
import math
from dataclasses import dataclass, field, asdict
from enum import Enum
import numpy as np
import pandas as pd


# ============================================================
# 1. STATES
# ============================================================
class TrendState(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    UNDEFINED = "UNDEFINED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class RegimeState(str, Enum):
    TREND_STRONG = "TREND_STRONG"   # ADX >= 25
    TREND_WEAK   = "TREND_WEAK"     # 20 <= ADX < 25
    LATERAL      = "LATERAL"        # ADX < 20
    INSUFFICIENT = "INSUFFICIENT"


class CorrectionState(str, Enum):
    IDEAL = "IDEAL"
    TOO_EARLY = "TOO_EARLY"
    TOO_LATE = "TOO_LATE"
    NO_CORRECTION = "NO_CORRECTION"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NONE = "NONE"


# ============================================================
# 2. INDICADORES — puros
# ============================================================
def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def macd(close: pd.Series, f: int = 12, s: int = 26, sig: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    line = ema(close, f) - ema(close, s)
    signal = ema(line, sig)
    return line, signal, line - signal


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    # Handle case where l == 0 (all gains) - RSI should be 100
    # Handle case where g == 0 (all losses) - RSI should be 0
    rs = g / l.replace(0, np.nan)
    rsi_val = 100 - 100/(1+rs)
    # Fill NaN: if l was 0 (no losses), RSI = 100; if g was 0 (no gains), RSI = 0
    rsi_val = rsi_val.fillna(100).where(l != 0, 100).where(g != 0, 0)
    return rsi_val


def stochastic(h: pd.Series, l: pd.Series, c: pd.Series, k: int = 14, ks: int = 3, ds: int = 3) -> tuple[pd.Series, pd.Series]:
    ll = l.rolling(k).min()
    hh = h.rolling(k).max()
    raw = 100 * (c - ll) / (hh - ll).replace(0, np.nan)
    K = raw.rolling(ks).mean()
    return K, K.rolling(ds).mean()


def atr(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> pd.Series:
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


def adx_wilder(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    up, dn = h.diff(), -l.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    a = tr.ewm(alpha=1/n, adjust=False).mean()
    pdi = 100 * pd.Series(pdm, index=h.index).ewm(alpha=1/n, adjust=False).mean() / a
    mdi = 100 * pd.Series(mdm, index=h.index).ewm(alpha=1/n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1/n, adjust=False).mean(), pdi, mdi


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    m = sma(close, n)
    sd = close.rolling(n).std(ddof=0)
    return m - k*sd, m, m + k*sd


def bb_width_pct(close: pd.Series, n: int = 20, k: float = 2.0, lb: int = 100) -> pd.Series:
    lo, mid, hi = bollinger(close, n, k)
    w = (hi - lo) / mid.replace(0, np.nan)
    return w.rolling(lb).rank(pct=True)


def atr_pct(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14, lb: int = 100) -> pd.Series:
    return atr(h, l, c, n).rolling(lb).rank(pct=True)


def elder_ray(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 13) -> tuple[pd.Series, pd.Series, pd.Series]:
    e = ema(c, n)
    return h - e, l - e, e


def cvd_proxy(close: pd.Series, volume: pd.Series, lb: int = 20) -> tuple[pd.Series, pd.Series]:
    sign = np.sign(close.diff()).fillna(0)
    cvd = (sign * volume).cumsum()
    return cvd, cvd.diff(lb)


# ============================================================
# 3. PADRÕES DE CANDLE
# ============================================================
def is_bull_engulf(df: pd.DataFrame, i: int) -> bool:
    if i < 1:
        return False
    o1, c1 = df.open.iloc[i-1], df.close.iloc[i-1]
    o2, c2 = df.open.iloc[i], df.close.iloc[i]
    return c1 < o1 and c2 > o2 and c2 >= o1 and o2 <= c1


def is_bear_engulf(df: pd.DataFrame, i: int) -> bool:
    if i < 1:
        return False
    o1, c1 = df.open.iloc[i-1], df.close.iloc[i-1]
    o2, c2 = df.open.iloc[i], df.close.iloc[i]
    return c1 > o1 and c2 < o2 and c2 <= o1 and o2 >= c1


def is_hammer(df: pd.DataFrame, i: int, br: float = 0.33) -> bool:
    o, h, l, c = df.open.iloc[i], df.high.iloc[i], df.low.iloc[i], df.close.iloc[i]
    rng = h - l
    if rng <= 0:
        return False
    body = abs(c - o)
    lo = min(o, c) - l
    hi = h - max(o, c)
    return body <= br*rng and lo >= 2*body and hi <= body


def is_shooting_star(df: pd.DataFrame, i: int, br: float = 0.33) -> bool:
    o, h, l, c = df.open.iloc[i], df.high.iloc[i], df.low.iloc[i], df.close.iloc[i]
    rng = h - l
    if rng <= 0:
        return False
    body = abs(c - o)
    hi = h - max(o, c)
    lo = min(o, c) - l
    return body <= br*rng and hi >= 2*body and lo <= body


# ============================================================
# 4. TELA 1 — TENDÊNCIA
# ============================================================
def classify_trend(tf1: pd.DataFrame) -> TrendState:
    if len(tf1) < 40:
        return TrendState.INSUFFICIENT_DATA
    c = tf1.close
    e13 = ema(c, 13).iloc[-1]
    _, _, hist = macd(c)
    h, hp = hist.iloc[-1], hist.iloc[-2]
    px = c.iloc[-1]
    if any(math.isnan(x) for x in (e13, h, hp)):
        return TrendState.INSUFFICIENT_DATA
    slope = h - hp
    if px > e13 and h > 0 and slope > 0:
        return TrendState.BULL
    if px < e13 and h < 0 and slope < 0:
        return TrendState.BEAR
    return TrendState.UNDEFINED


# ============================================================
# 5. REGIME — ADX + BBW + ATR pct
# ============================================================
@dataclass
class RegimeReport:
    state: RegimeState
    adx: float
    bbw_pct: float
    atr_pct: float
    ok_to_trade: bool
    reason: str = ""


def detect_regime(tf1: pd.DataFrame) -> RegimeReport:
    nan = float("nan")
    if len(tf1) < 120:
        return RegimeReport(RegimeState.INSUFFICIENT, nan, nan, nan, False, "insufficient")
    adx_v = adx_wilder(tf1.high, tf1.low, tf1.close)[0].iloc[-1]
    bbw = bb_width_pct(tf1.close).iloc[-1]
    atr_p = atr_pct(tf1.high, tf1.low, tf1.close).iloc[-1]
    if any(math.isnan(x) for x in (adx_v, bbw, atr_p)):
        return RegimeReport(RegimeState.INSUFFICIENT, nan, nan, nan, False, "nan")
    if adx_v < 20:
        return RegimeReport(RegimeState.LATERAL, adx_v, bbw, atr_p, False, "ADX<20")
    if atr_p < 0.20:
        return RegimeReport(RegimeState.LATERAL, adx_v, bbw, atr_p, False, "ATR<20pct")
    if atr_p > 0.80:
        st = RegimeState.TREND_STRONG if adx_v >= 25 else RegimeState.TREND_WEAK
        return RegimeReport(st, adx_v, bbw, atr_p, False, "ATR>80pct")
    if bbw < 0.20:
        return RegimeReport(RegimeState.LATERAL, adx_v, bbw, atr_p, False, "BB squeeze")
    st = RegimeState.TREND_STRONG if adx_v >= 25 else RegimeState.TREND_WEAK
    return RegimeReport(st, adx_v, bbw, atr_p, True, "")


# ============================================================
# 6. TELA 2 — CORREÇÃO
# ============================================================
@dataclass
class CorrectionReport:
    state: CorrectionState
    rsi: float
    stoch_k: float
    bear_power: float
    bull_power: float
    in_fib_zone: bool
    near_ema13: bool


def detect_correction(tf2: pd.DataFrame, trend: TrendState) -> CorrectionReport:
    nan = float("nan")
    if len(tf2) < 40 or trend not in (TrendState.BULL, TrendState.BEAR):
        return CorrectionReport(CorrectionState.NO_CORRECTION, nan, nan, nan, nan, False, False)
    r = rsi(tf2.close).iloc[-1]
    k = stochastic(tf2.high, tf2.low, tf2.close)[0].iloc[-1]
    bull, bear, e13 = elder_ray(tf2.high, tf2.low, tf2.close)

    bv, br = bull.iloc[-1], bear.iloc[-1]
    c = tf2.close.iloc[-1]

    sh = tf2.high.iloc[-40:].max()
    sl = tf2.low.iloc[-40:].min()
    rng = sh - sl
    in_fib = (sl + 0.382*rng) <= c <= (sl + 0.618*rng) if rng > 0 else False
    atr_v = atr(tf2.high, tf2.low, tf2.close).iloc[-1]
    near_ema = abs(c - e13.iloc[-1]) <= 0.5 * atr_v

    if trend == TrendState.BULL:
        in_zone = (r < 30) or (k < 20) or (br < 0)
    else:
        in_zone = (r > 70) or (k > 80) or (bv > 0)

    if not in_zone:
        return CorrectionReport(CorrectionState.NO_CORRECTION, r, k, br, bv, in_fib, near_ema)
    if not (in_fib or near_ema):
        return CorrectionReport(CorrectionState.TOO_EARLY, r, k, br, bv, in_fib, near_ema)
    if abs(c - e13.iloc[-1]) > 1.0 * atr_v:
        return CorrectionReport(CorrectionState.TOO_LATE, r, k, br, bv, in_fib, near_ema)
    return CorrectionReport(CorrectionState.IDEAL, r, k, br, bv, in_fib, near_ema)


# ============================================================
# 7. TELA 3 — GATILHO
# ============================================================
@dataclass
class TriggerReport:
    macd_cross: bool
    rsi_exit: bool
    stoch_cross: bool
    candle_pattern: bool
    breakout_volume: bool
    cvd_confirm: bool
    count: int
    confirmed: bool


def detect_trigger(tf3: pd.DataFrame, trend: TrendState) -> TriggerReport:
    F = (False,)*6
    if len(tf3) < 40 or trend not in (TrendState.BULL, TrendState.BEAR):
        return TriggerReport(*F, 0, False)
    c = tf3.close
    _, _, hist = macd(c)
    r = rsi(c)
    k, d = stochastic(tf3.high, tf3.low, tf3.close)
    vol_ma = tf3.volume.rolling(20).mean()
    i = -1

    if trend == TrendState.BULL:
        mc = hist.iloc[i] > 0 and hist.iloc[i-1] <= 0
        re = r.iloc[i-1] < 30 and r.iloc[i] >= 30
        sc = k.iloc[i] > d.iloc[i] and k.iloc[i-1] <= d.iloc[i-1] and k.iloc[i] < 50
        cp = is_bull_engulf(tf3, len(tf3)-1) or is_hammer(tf3, len(tf3)-1)
        bv = tf3.volume.iloc[i] > vol_ma.iloc[i]*1.2 and c.iloc[i] > c.iloc[i-1]
    else:
        mc = hist.iloc[i] < 0 and hist.iloc[i-1] >= 0
        re = r.iloc[i-1] > 70 and r.iloc[i] <= 70
        sc = k.iloc[i] < d.iloc[i] and k.iloc[i-1] >= d.iloc[i-1] and k.iloc[i] > 50
        cp = is_bear_engulf(tf3, len(tf3)-1) or is_shooting_star(tf3, len(tf3)-1)
        bv = tf3.volume.iloc[i] > vol_ma.iloc[i]*1.2 and c.iloc[i] < c.iloc[i-1]
    _, cvd_slope = cvd_proxy(c, tf3.volume)

    cvd_ok = cvd_slope.iloc[i] > 0 if trend == TrendState.BULL else cvd_slope.iloc[i] < 0
    flags = [mc, re, sc, cp, bv, cvd_ok]
    cnt = sum(bool(x) for x in flags)
    return TriggerReport(*flags, cnt, cnt >= 3)


# ============================================================
# 8. SCORE ENGINE
# ============================================================
@dataclass
class ScoreBreakdown:
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


@dataclass
class SignalDecision:
    ok: bool
    side: Side
    score: int
    reason: str
    breakdown: ScoreBreakdown
    entry: float = 0.0
    stop: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    tp3: float = 0.0
    rr: float = 0.0


def _stops(tf3: pd.DataFrame, side: Side, atr_v: float, mode: str) -> tuple[float, float, float, float, float, float]:
    c = tf3.close.iloc[-1]
    low20 = tf3.low.iloc[-20:].min()
    high20 = tf3.high.iloc[-20:].max()
    if side == Side.BUY:
        stop = min(low20, c - 1.5*atr_v) if mode == "swing" else min(tf3.low.iloc[-1], c - 0.75*atr_v)
        risk = c - stop
        return c, stop, c + 1*risk, c + 2*risk, c + 3*risk, risk
    else:
        stop = max(high20, c + 1.5*atr_v) if mode == "swing" else max(tf3.high.iloc[-1], c + 0.75*atr_v)
        risk = stop - c
        return c, stop, c - 1*risk, c - 2*risk, c - 3*risk, risk


def score_signal(
    tf1: pd.DataFrame,
    tf2: pd.DataFrame,
    tf3: pd.DataFrame,
    trend: TrendState,
    regime: RegimeReport,
    correction: CorrectionReport,
    trigger: TriggerReport,
    derivatives_ok: bool = True,
    derivatives_factor: float = 1.0,
    freshness_candles: int = 0,
    mode: str = "swing",
) -> SignalDecision:
    sb = ScoreBreakdown()
    if trend == TrendState.UNDEFINED:
        return SignalDecision(False, Side.NONE, 0, "trend_undefined", sb)
    if trend == TrendState.INSUFFICIENT_DATA:
        return SignalDecision(False, Side.NONE, 0, "insufficient_data", sb)
    if not regime.ok_to_trade:
        return SignalDecision(False, Side.NONE, 0, f"regime:{regime.reason}", sb)

    side = Side.BUY if trend == TrendState.BULL else Side.SELL

    if correction.state != CorrectionState.IDEAL:
        return SignalDecision(False, side, 0, f"correction:{correction.state.value}", sb)
    if not trigger.confirmed:
        return SignalDecision(False, side, 0, f"trigger_count:{trigger.count}", sb)

    sb.trend = 25 if regime.state == RegimeState.TREND_STRONG else 15
    sb.correction = 20
    sb.confluences = min(20, int(round(20 * trigger.count / 6)))
    sb.volume = 10 if trigger.breakout_volume else 0
    sb.candle = 10 if trigger.candle_pattern else 0
    sb.sr_prox = 10 if (correction.in_fib_zone or correction.near_ema13) else 0

    atr_v = atr(tf3.high, tf3.low, tf3.close).iloc[-1]
    entry, stop, tp1, tp2, tp3, risk = _stops(tf3, side, atr_v, mode)
    rr = abs(tp2 - entry) / risk if risk > 0 else 0.0
    if rr < 2.0 - 1e-9:
        return SignalDecision(False, side, 0, f"rr:{rr:.2f}", sb)

    sb.rr_bonus = 5 + (2 if rr >= 3.0 else 0)
    sb.base = sb.trend + sb.correction + sb.confluences + sb.volume + sb.candle + sb.sr_prox + sb.rr_bonus
    sb.derivatives_mult = 0.85 if not derivatives_ok else max(0.85, min(1.15, derivatives_factor))
    sb.freshness_mult = max(0.5, 1.0 - 0.05 * freshness_candles)
    sb.final = max(0, min(100, int(round(sb.base * sb.derivatives_mult * sb.freshness_mult))))

    if sb.final < 60:
        return SignalDecision(False, side, sb.final, "score_below_60", sb, entry, stop, tp1, tp2, tp3, rr)
    if sb.final < 70:
        return SignalDecision(False, side, sb.final, "observation_only", sb, entry, stop, tp1, tp2, tp3, rr)
    return SignalDecision(True, side, sb.final, "ok", sb, entry, stop, tp1, tp2, tp3, rr)


# ============================================================
# 9. ORQUESTRADOR
# ============================================================
def generate_signal(
    tf1: pd.DataFrame,
    tf2: pd.DataFrame,
    tf3: pd.DataFrame,
    mode: str = "swing",
    derivatives_ok: bool = True,
    derivatives_factor: float = 1.0,
    freshness_candles: int = 0,
) -> SignalDecision:
    trend = classify_trend(tf1)
    regime = detect_regime(tf1)
    correction = detect_correction(tf2, trend)
    trigger = detect_trigger(tf3, trend)
    return score_signal(
        tf1, tf2, tf3, trend, regime, correction, trigger,
        derivatives_ok, derivatives_factor, freshness_candles, mode
    )


# ============================================================
# 10. DEMO
# ============================================================
if __name__ == "__main__":
    print("Motor Triple Screen: use os candles reais da ingestão. Não há cotação demonstrativa.")
