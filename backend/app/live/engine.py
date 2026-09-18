"""The existing Triple Screen engine fed exclusively with validated closed candles."""
import hashlib
import json
import math
from dataclasses import asdict
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from app.core.signal_core import (classify_trend, detect_regime, detect_correction,
    detect_trigger, generate_signal, ema, macd, rsi, atr)

PERIODS = {'1h': 3600000, '4h': 14400000, '1d': 86400000}
VERSION = 'triple-screen-live-v2'

def clean(value):
    if isinstance(value, dict): return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [clean(v) for v in value]
    if isinstance(value, np.generic): return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value): return None
    return value

def canonical(value):
    return json.dumps(clean(value), sort_keys=True, separators=(',', ':'), allow_nan=False)

def validate_candles(rows, tf, server_time, minimum=200):
    period = PERIODS[tf]
    parsed = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 7:
            raise ValueError('Formato de candle inválido')
        ts, end = int(row[0]), int(row[6])
        o, h, l, c, v = map(float, row[1:6])
        if (ts % period or end != ts + period - 1 or not all(math.isfinite(x) for x in (o,h,l,c,v))
            or min(o,h,l,c) <= 0 or v < 0 or l > min(o,c) or h < max(o,c) or l > h):
            raise ValueError('OHLCV inválido')
        if ts > server_time: raise ValueError('Candle no futuro')
        if end >= server_time: continue  # never analyze the open candle
        if parsed and ts != parsed[-1]['time'] + period:
            raise ValueError('Candles duplicados ou com lacunas')
        parsed.append(dict(time=ts, close_time=end, open=o, high=h, low=l, close=c, volume=v))
    if len(parsed) < minimum: raise ValueError('Histórico insuficiente')
    age = server_time - (parsed[-1]['time'] + period)
    if age < 0 or age > period: raise ValueError('Candles desatualizados')
    return parsed

def frame(rows):
    return pd.DataFrame(rows).set_index(pd.to_datetime([r['time'] for r in rows], unit='ms', utc=True))

def analyze(frames):
    inputs = {tf: rows[-200:] for tf, rows in frames.items()}
    d, h4, h1 = [frame(inputs[tf]) for tf in ('1d','4h','1h')]
    trend = classify_trend(d)
    regime = detect_regime(d)
    correction = detect_correction(h4, trend)
    trigger = detect_trigger(h1, trend)
    decision = generate_signal(d, h4, h1)
    indicators = {}
    for tf, f in [('1d',d),('4h',h4),('1h',h1)]:
        indicators[tf] = dict(close=f.close.iloc[-1], ema13=ema(f.close,13).iloc[-1],
            macd_hist=macd(f.close)[2].iloc[-1], rsi=rsi(f.close).iloc[-1],
            atr=atr(f.high,f.low,f.close).iloc[-1], candle_time=inputs[tf][-1]['time'])
    snapshot = clean(dict(engine_version=VERSION, source='Binance Spot', symbol='BTC/USDT',
        inputs=inputs, trend=trend.value, regime=asdict(regime), correction=asdict(correction),
        trigger=asdict(trigger), indicators=indicators, decision=asdict(decision)))
    ident = hashlib.sha256(canonical(snapshot).encode()).hexdigest()
    return dict(id=ident, candle_time=inputs['1h'][-1]['time'], snapshot=snapshot,
                created_at=datetime.now(timezone.utc).isoformat())

def summary(data):
    snap = data['snapshot']
    return {k:v for k,v in data.items() if k != 'snapshot'} | {k:v for k,v in snap.items() if k != 'inputs'}

def sizing(entry, stop, equity=10000., risk_pct=1.):
    if not all(math.isfinite(x) and x > 0 for x in (entry, stop, equity, risk_pct)) or risk_pct > 1:
        raise ValueError('Parâmetros de risco inválidos')
    distance = abs(entry-stop)
    if distance == 0: raise ValueError('Stop igual à entrada')
    # Include estimated fees and slippage in the budget; cap exposure at 1x cash.
    costs_per_unit = (entry + stop) * 0.0015
    quantity = min(equity * risk_pct / 100 / (distance + costs_per_unit), equity / (entry * 1.0015))
    return dict(quantity=quantity, notional=quantity*entry,
                estimated_risk=quantity*(distance+costs_per_unit), risk_pct=risk_pct)

def resolve_exit(trade, candle):
    buy = trade['side'] == 'BUY'
    stop, target = trade['stop'], trade['target']
    # Gaps fill at the first available open; stop wins if both levels occur in one bar.
    if buy:
        if candle['open'] <= stop: return candle['open'], 'stop_gap'
        if candle['open'] >= target: return target, 'target'
        if candle['low'] <= stop: return stop, 'stop'
        if candle['high'] >= target: return target, 'target'
    else:
        if candle['open'] >= stop: return candle['open'], 'stop_gap'
        if candle['open'] <= target: return target, 'target'
        if candle['high'] >= stop: return stop, 'stop'
        if candle['low'] <= target: return target, 'target'
    return None

def close_trade(trade, price, closed_at, reason):
    direction = 1 if trade['side'] == 'BUY' else -1
    costs = trade['quantity'] * (trade['entry'] + price) * 0.0015
    return trade | dict(status='closed', exit=price, closed_at=closed_at, exit_reason=reason,
        costs=costs, pnl=direction*(price-trade['entry'])*trade['quantity']-costs)

def backtest(frames, days=7):
    """No lookahead: closed multi-timeframe bars, entry at next hourly open."""
    hourly=frames['1h']; end=hourly[-1]['time']+PERIODS['1h']; start=end-days*86400000
    trades=[]; active=None; equity=10000.; curve=[]; peak=equity; max_dd=0.
    full = {tf: frame(rows) for tf,rows in frames.items()}
    for candle in hourly:
        ts=candle['time']
        if ts < start: continue
        if active is None:
            visible={tf: df[df.close_time < ts].tail(200) for tf,df in full.items()}
            if len(visible['1d']) < 200 or len(visible['4h']) < 200 or len(visible['1h']) < 200:
                continue
            decision=generate_signal(visible['1d'],visible['4h'],visible['1h'])
            if decision.ok and decision.side.value in ('BUY','SELL'):
                entry=candle['open']; buy=decision.side.value=='BUY'
                # Do not enter if opening gap has invalidated the planned levels or R:R.
                risk=entry-decision.stop if buy else decision.stop-entry
                reward=decision.tp2-entry if buy else entry-decision.tp2
                if risk>0 and reward/risk>=2-1e-9 and equity>0:
                    size=sizing(entry,decision.stop,equity)
                    active=dict(side=decision.side.value,entry=entry,stop=decision.stop,target=decision.tp2,
                        quantity=size['quantity'],opened_at=ts,status='open')
        if active:
            result=resolve_exit(active,candle)
            if result:
                active=close_trade(active,result[0],ts+PERIODS['1h'],result[1]);equity+=active['pnl'];trades.append(active);active=None
        marked=equity
        if active:
            marked+=close_trade(active,candle['close'],ts,'mark')['pnl']
        peak=max(peak,marked);max_dd=max(max_dd,(peak-marked)/peak)
        curve.append(dict(time=ts,equity=marked))
    if active:
        active=close_trade(active,hourly[-1]['close'],end,'end_of_period');equity+=active['pnl'];trades.append(active)
    if not curve: raise ValueError('Histórico insuficiente para o período e aquecimento')
    return dict(days=days,initial_capital=10000,final_equity=equity,return_pct=(equity/10000-1)*100,
        max_drawdown_pct=max_dd*100,trades=trades,trade_count=len(trades),
        win_rate=(sum(t['pnl']>0 for t in trades)/len(trades)*100) if trades else None,
        curve=curve,source='Binance Spot',start_time=curve[0]['time'],end_time=end,
        assumptions=['Simulação técnica; não inclui filtros macro históricos nem carteira ao vivo.',
            'Entrada na abertura seguinte; apenas candles fechados disponíveis naquele instante.',
            'Taxa de 0,10% e slippage de 0,05% por lado; risco de até 1%; exposição máxima 1x.',
            'Alvo TP2 integral; stop tem prioridade quando stop e alvo ocorrem no mesmo candle.',
            'Venda simula posição curta hipotética: não é uma ordem Spot nem inclui funding ou empréstimo.'],
        engine_version=VERSION)
