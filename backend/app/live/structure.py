"""Causal, explicitly parameterized interpretation of the supplied Fornes research.
No brokerage actions. All timestamps in milliseconds, events at confirmation close.
"""
import math

VERSION = 'fornes-structure-v1'
PERIODS = {'1d': 86400000, '4h': 14400000, '1h': 3600000}


def scan(rows, width=2):
    pivots, events, gaps, blocks = [], [], [], []
    latest = {}; broken = set(); swept = set()
    direction = 'RANGE'; protected = None
    for i, c in enumerate(rows):
        now = c['close_time']
        changed = False
        # A pivot becomes available only after width right-hand CLOSED bars.
        j = i - width
        if j >= width:
            for kind, key, compare in [('high', 'high', max), ('low', 'low', min)]:
                neighbours = rows[j-width:j] + rows[j+1:i+1]
                value = rows[j][key]
                edge = compare(r[key] for r in neighbours)
                if (value > edge if kind == 'high' else value < edge):
                    p = dict(kind=kind, price=value, time=rows[j]['time'], confirmed_at=now, index=j)
                    pivots.append(p); latest[kind] = p
        # Invalidate a protected extreme only by a CLOSE; retain wick sweeps separately.
        if protected and ((direction == 'BULL' and c['close'] < protected['price']) or
                          (direction == 'BEAR' and c['close'] > protected['price'])):
            side = 'BEAR' if direction == 'BULL' else 'BULL'
            events.append(dict(kind='change', side=side, time=now, price=protected['price'],
                               label='Possível mudança de direção'))
            direction = 'RANGE'; protected = None; changed = True
        for kind, side in [('high', 'BULL'), ('low', 'BEAR')]:
            p = latest.get(kind)
            if not p or p['confirmed_at'] >= now: continue
            ident = (kind, p['time'])
            crossed = c['close'] > p['price'] if side == 'BULL' else c['close'] < p['price']
            wick = c['high'] > p['price'] >= c['close'] if side == 'BULL' else c['low'] < p['price'] <= c['close']
            if crossed and ident not in broken and not changed:
                broken.add(ident)
                opposite = latest.get('low' if side == 'BULL' else 'high')
                continuation = direction == side
                # A contrary close without a protected break is internal, not a new major trend.
                internal = direction not in ('RANGE', side)
                event = dict(kind='internal' if internal else 'continuation' if continuation else 'break',
                    side=side, time=now, price=p['price'],
                    label='Movimento interno' if internal else 'Rompeu o último topo' if side == 'BULL' else 'Rompeu o último fundo',
                    origin=opposite)
                events.append(event)
                if not internal and opposite:
                    direction=side; protected=opposite
                # Last opposite candle in 10 bars before strong displacement. Proxy only.
                avg = sum(r['high']-r['low'] for r in rows[max(0,i-14):i]) / min(i,14) if i else 0
                if not internal and abs(c['close']-c['open']) >= 1.5*avg and avg > 0:
                    prior = next((r for r in reversed(rows[max(0,i-10):i])
                        if (r['close'] < r['open'] if side == 'BULL' else r['close'] > r['open'])), None)
                    if prior:
                        blocks.append(dict(kind='block', side=side, low=prior['low'], high=prior['high'],
                            time=prior['time'], confirmed_at=now, status='open', ended_at=None))
            elif wick and ident not in broken and ident not in swept:
                swept.add(ident)
                events.append(dict(kind='sweep', side='BEAR' if side=='BULL' else 'BULL', time=now,
                    price=p['price'], label='Preço passou do topo e voltou' if side=='BULL' else 'Preço passou do fundo e voltou'))
        if i >= 2:
            a = rows[i-2]
            side = 'BULL' if c['low'] > a['high'] else 'BEAR' if c['high'] < a['low'] else None
            if side:
                gaps.append(dict(kind='gap', side=side, low=a['high'] if side=='BULL' else c['high'],
                    high=c['low'] if side=='BULL' else a['low'], time=a['time'], confirmed_at=now,
                    status='open', ended_at=None))
        for zone in gaps + blocks:
            if zone['confirmed_at'] >= now or zone['status'] in ('filled','invalid'): continue
            invalid = c['close'] < zone['low'] if zone['side']=='BULL' else c['close'] > zone['high']
            filled = c['low'] <= zone['low'] if zone['side']=='BULL' else c['high'] >= zone['high']
            touched = c['low'] <= zone['high'] and c['high'] >= zone['low']
            if zone['kind']=='block' and invalid:
                zone.update(status='invalid', ended_at=now)
            elif zone['kind']=='gap' and filled:
                zone.update(status='filled', ended_at=now)
            elif touched: zone['status']='partial'
    groups = []
    for kind in ('high','low'):
        ps = [p for p in pivots if p['kind']==kind]
        for a,b in zip(ps,ps[1:]):
            if abs(a['price']-b['price']) / a['price'] <= .0015:
                groups.append(dict(kind=kind, price=(a['price']+b['price'])/2, time=b['confirmed_at']))
    return dict(direction=direction, protected=protected, pivots=pivots, events=events,
                zones=gaps+blocks, clusters=groups)


def candidate_plan(side, entry, stop, levels):
    risk = entry-stop if side=='BULL' else stop-entry
    candidates = [x for x in levels if (x>entry if side=='BULL' else x<entry)]
    if risk <= 0 or not candidates: return None
    target = min(candidates) if side=='BULL' else max(candidates)
    reward = abs(target-entry)
    costs = (entry+target)*.0015
    net_rr = (reward-costs)/(risk+(entry+stop)*.0015)
    if net_rr < 3: return None
    return dict(side=side, entry=entry, stop=stop, target=target, rr=reward/risk, net_rr=net_rr,
                conditional=True, execution_enabled=False)


def setup(screens):
    daily, middle, lower = (screens[t] for t in ('1d','4h','1h'))
    side=daily['direction']; buy=side=='BULL'
    checks=[dict(key=key,ok=False,text=text) for key,text in [
        ('direction','Direção principal confirmada por rompimento e extremo protegido'),
        ('impulse','Continuação anterior nas 4 horas, na direção do diário'),
        ('coverage','Histórico de 1 hora cobre toda a hipótese desde a criação da região'),
        ('zone','Preço chegou à região sem atravessá-la por fechamento'),
        ('sweep','Preço passou por um extremo na região e voltou'),
        ('confirmation','Fechamento de 1 hora rompeu a estrutura após a passagem e o retorno'),
        ('displacement','O rompimento deixou uma faixa de três velas ainda não preenchida'),
        ('retest','Retorno ao nível rompido com fechamento a favor na última vela de 1 hora'),
        ('target','Alvo real anterior permite retorno líquido estimado de pelo menos 3 vezes o risco')]]
    def check(key, ok, text):
        next(c for c in checks if c['key']==key).update(ok=bool(ok),text=text)
    check('direction', side in ('BULL','BEAR'), 'Direção principal confirmada por rompimento e extremo protegido')
    impulses=[e for e in middle['events'] if e['kind']=='continuation' and e['side']==side and e.get('origin')]
    impulse=impulses[-1] if impulses else None
    check('impulse', impulse is not None and middle['direction']==side, 'Continuação anterior nas 4 horas, na direção do diário')
    result=dict(state='waiting', side=side, zone=None, plan=None, checks=checks,
                waiting='Aguardar direção e continuação nas 4 horas.', invalidation='Sem hipótese definida para invalidar.')
    if not impulse or side=='RANGE' or middle['direction']!=side: return result
    # Freeze the impulse at the breakout bar; never use a subsequently discovered extreme.
    bar=next(c for c in middle['candles'] if c['close_time']==impulse['time'])
    origin=impulse['origin']['price']; end=bar['high'] if buy else bar['low']
    distance=abs(end-origin)
    if distance<=0: return result
    lo,hi=sorted([end+(-1 if buy else 1)*distance*r for r in (.618,.786)])
    zone=dict(kind='retracement',side=side,low=lo,high=hi,midpoint=(origin+end)/2,
              origin=origin,end=end,confirmed_at=impulse['time'],time=impulse['time'],status='open',ended_at=None)
    result['zone']=zone
    result['invalidation']=f"Um fechamento de 1 hora {'abaixo' if buy else 'acima'} de {(lo if buy else hi):.2f} USDT atravessa a região e cancela esta hipótese."
    available=[c for c in lower['candles'] if c['time']>impulse['time']]
    # Require uninterrupted lower-timeframe history since zone creation.
    covered=bool(available and available[0]['time']==impulse['time']+1)
    check('coverage',covered,'Histórico de 1 hora cobre toda a hipótese desde a criação da região')
    invalid=next((c for c in available if (c['close']<lo if buy else c['close']>hi)),None)
    if invalid:
        zone.update(status='invalid',ended_at=invalid['close_time']);result['state']='invalid'
    touches=[c for c in available if c['low']<=hi and c['high']>=lo]
    touch=touches[0] if touches else None
    check('zone', touch is not None and not invalid, 'Preço chegou à região sem atravessá-la por fechamento')
    sweeps=[e for e in lower['events'] if e['kind']=='sweep' and e['side']==side and touch and e['time']>=touch['close_time'] and lo<=e['price']<=hi]
    sweep=sweeps[0] if sweeps else None
    check('sweep',sweep is not None,'Preço passou por um extremo na região e voltou')
    breaks=[e for e in lower['events'] if e['kind'] in ('break','continuation') and e['side']==side and sweep and e['time']>sweep['time']]
    event=breaks[0] if breaks else None
    check('confirmation',event is not None,'Fechamento de 1 hora rompeu a estrutura após a passagem e o retorno')
    gaps=[z for z in lower['zones'] if z['kind']=='gap' and z['side']==side and event and z['confirmed_at']>=event['time'] and z['confirmed_at']<=event['time']+PERIODS['1h'] and z['status']!='filled']
    gap=gaps[0] if gaps else None
    check('displacement',gap is not None,'O rompimento deixou uma faixa de três velas ainda não preenchida')
    retests=[c for c in available if event and gap and c['time']>max(event['time'],gap['confirmed_at']) and
        c['low']<=event['price']<=c['high'] and (c['close']>event['price'] if buy else c['close']<event['price'])]
    retest=retests[0] if retests else None
    current=bool(retest and retest['close_time']==lower['candles'][-1]['close_time'])
    check('retest',current,'Retorno ao nível rompido com fechamento a favor na última vela de 1 hora')
    if invalid:
        result['waiting']='Esta região foi atravessada. Aguardar um novo impulso e uma nova região.'
    else:
        result['waiting']=next((c['text'] for c in checks if not c['ok']), 'Verificar alvo estrutural e relação entre retorno e risco.')
    levels=[p['price'] for screen in (daily,middle) for p in screen['pivots']
            if p['kind']==('high' if buy else 'low') and not any(
                (c['high']>=p['price'] if buy else c['low']<=p['price'])
                for c in screen['candles'] if c['close_time']>p['confirmed_at'])]
    plan=candidate_plan(side,lower['candles'][-1]['close'],origin,levels) if all(c['ok'] for c in checks if c['key']!='target') and not invalid else None
    check('target',plan is not None,'Alvo real anterior permite retorno líquido estimado de pelo menos 3 vezes o risco')
    if plan:
        result.update(state='conditional',plan=plan,waiting='Condições técnicas presentes no último fechamento. Plano de referência, sem execução automática.')
    return result


def analyze_structure(frames):
    screens={}
    for tf,period in PERIODS.items():
        rows=frames.get(tf,[])
        if len(rows)<30: return dict(version=VERSION,state='unavailable',reason='Histórico insuficiente: pelo menos 30 velas fechadas por período.',screens={},setup=None)
        for i,c in enumerate(rows):
            if (not all(math.isfinite(c[k]) for k in ('open','high','low','close')) or
                c['low']>min(c['open'],c['close']) or c['high']<max(c['open'],c['close']) or
                c['close_time']!=c['time']+period-1 or (i and c['time']!=rows[i-1]['time']+period)):
                return dict(version=VERSION,state='unavailable',reason='Histórico inválido ou com lacunas.',screens={},setup=None)
        major=scan(rows,2)
        minor=scan(rows,1)
        direction=major['direction']
        text={'BULL':'O preço rompeu um topo por fechamento e mantém o fundo protegido.',
              'BEAR':'O preço rompeu um fundo por fechamento e mantém o topo protegido.',
              'RANGE':'Sem direção principal confirmada. Os movimentos podem continuar dentro de uma faixa.'}[direction]
        screens[tf]=major | dict(candles=rows, internal_direction=minor['direction'], description=text,
                                close_time=rows[-1]['close_time'], close=rows[-1]['close'])
    return dict(version=VERSION,state='available',reason=None,screens=screens,setup=setup(screens),
                timeframe_note='Adaptação: diário / 4 horas / 1 hora. Não reproduz todas as combinações das aulas.')
