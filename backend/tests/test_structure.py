"""Synthetic fixtures are isolated tests; the application serves only exchange data."""
from copy import deepcopy
import pytest
from app.live.structure import scan, analyze_structure, candidate_plan, setup, PERIODS


def bars(values, period=3600000):
    return [dict(time=i*period, close_time=(i+1)*period-1, open=v-.1,
                 close=v, high=v+.4, low=v-.4, volume=1) for i,v in enumerate(values)]


SWING=[10,11,14,11,10,9,10,11,15,12,11,12,16,13,12,13,17]


def test_pivot_requires_right_closed_candles():
    rows=bars(SWING)
    assert not scan(rows[:4])['pivots']
    p=scan(rows[:5])['pivots'][0]
    assert p['time']==rows[2]['time'] and p['confirmed_at']==rows[4]['close_time']


def test_every_prefix_preserves_confirmed_events_no_lookahead():
    rows=bars(SWING+[14,13,14,18,12,11,10,9,8,10,11,7])
    complete=scan(rows)
    for count in range(5,len(rows)+1):
        partial=scan(rows[:count]); end=rows[count-1]['close_time']
        assert partial['events']==[e for e in complete['events'] if e['time']<=end]
        assert partial['pivots']==[p for p in complete['pivots'] if p['confirmed_at']<=end]
        assert [(z['low'],z['high'],z['confirmed_at']) for z in partial['zones']]==[(z['low'],z['high'],z['confirmed_at']) for z in complete['zones'] if z['confirmed_at']<=end]


def test_wick_return_is_not_close_break():
    rows=bars(SWING[:8]);rows+=bars([13])
    rows[-1].update(time=8*3600000,close_time=9*3600000-1,high=15)
    result=scan(rows)
    assert result['direction']=='RANGE'
    assert result['events'][-1]['kind']=='sweep'
    rows[-1]['close']=14.8
    result=scan(rows)
    assert result['direction']=='BULL' and result['events'][-1]['kind']=='break'


def test_up_down_and_flat_are_distinct():
    assert scan(bars(SWING))['direction']=='BULL'
    inverse=[dict(c,open=40-c['open'],close=40-c['close'],high=40-c['low'],low=40-c['high']) for c in bars(SWING)]
    assert scan(inverse)['direction']=='BEAR'
    assert scan(bars([10]*40))['direction']=='RANGE'


def test_protected_break_is_possible_change_not_instant_reversal():
    rows=bars(SWING+[7])
    result=scan(rows)
    assert result['direction']=='RANGE'
    assert result['events'][-1]['kind']=='change'


def test_gap_confirmation_partial_and_full_fill():
    rows=bars([10,12,14])
    assert scan(rows)['zones'][0]['confirmed_at']==rows[2]['close_time']
    rows=bars([10,12,14,12])
    assert scan(rows)['zones'][0]['status']=='partial'
    rows=bars([10,12,14,12,10])
    z=scan(rows)['zones'][0]
    assert z['status']=='filled' and z['ended_at']==rows[-1]['close_time']


def test_target_never_fabricated_or_skips_nearest_barrier():
    assert candidate_plan('BULL',100,90,[]) is None
    assert candidate_plan('BULL',100,90,[110,150]) is None
    plan=candidate_plan('BULL',100,90,[150,160])
    assert plan['target']==150 and plan['net_rr']>=3 and not plan['execution_enabled']
    assert candidate_plan('BEAR',100,110,[50])['target']==50
    assert candidate_plan('BULL',100,100,[150]) is None


def test_insufficient_and_gapped_history():
    frames={tf:bars([100]*40,p) for tf,p in PERIODS.items()}
    assert analyze_structure(frames)['state']=='available'
    frames['1h']=frames['1h'][:10]
    assert analyze_structure(frames)['setup'] is None
    frames['1h']=bars([100]*40);frames['1h'].pop(20)
    assert analyze_structure(frames)['state']=='unavailable'


def scenario():
    # Test the sequential decision independently of pivot discovery.
    hourly=bars([117]*20)
    middle=bars([150]*5,PERIODS['4h'])
    impulse=dict(kind='continuation',side='BULL',time=middle[0]['close_time'],origin={'price':100})
    def screen(candles): return dict(direction='BULL',candles=candles,events=[],zones=[],pivots=[])
    screens={'1d':screen(bars([140]*3,PERIODS['1d'])),'4h':screen(middle),'1h':screen(hourly)}
    screens['4h']['events']=[impulse]
    return screens


def test_zone_touch_alone_does_not_create_plan():
    screens=scenario();s=setup(screens)
    assert s['zone'] is not None and s['plan'] is None
    assert next(x['ok'] for x in s['checks'] if x['key']=='zone')
    assert not next(x['ok'] for x in s['checks'] if x['key']=='confirmation')


def test_close_through_zone_invalidates_hypothesis():
    screens=scenario();screens['1h']['candles'][-1].update(close=105,low=104)
    s=setup(screens)
    assert s['state']=='invalid' and s['zone']['status']=='invalid' and s['plan'] is None


def test_history_after_zone_creation_must_be_complete():
    screens=scenario();screens['1h']['candles']=screens['1h']['candles'][10:]
    s=setup(screens)
    assert not next(x['ok'] for x in s['checks'] if x['key']=='coverage')
    assert s['plan'] is None


def test_complete_sequence_can_form_conditional_plan_and_expire():
    screens=scenario(); lower=screens['1h']; rows=lower['candles']
    lower['events']=[dict(kind='sweep',side='BULL',time=rows[4]['close_time'],price=115),
                     dict(kind='break',side='BULL',time=rows[5]['close_time'],price=120)]
    lower['zones']=[dict(kind='gap',side='BULL',confirmed_at=rows[5]['close_time'],status='open')]
    rows[-1].update(open=120,low=119,high=121,close=120.5)
    screens['1d']['pivots']=[dict(kind='high',price=200,confirmed_at=0)]
    result=setup(screens)
    assert result['state']=='conditional' and result['plan']['target']==200
    assert all(c['ok'] for c in result['checks'])
    rows.append(dict(rows[-1],time=rows[-1]['time']+3600000,close_time=rows[-1]['close_time']+3600000))
    assert setup(screens)['plan'] is None  # last closed bar is no longer the first valid retest


def test_stale_service_hides_structural_plan_without_mutating_snapshot(tmp_path):
    import time
    from app.live.engine import analyze
    from app.live.store import Store
    from app.live.service import LiveService
    frames={tf:bars([100]*200,p) for tf,p in PERIODS.items()}
    service=LiveService(Store(tmp_path/'state.sqlite3'))
    service.latest=analyze(frames)
    service.latest['snapshot']['structure']['setup']['plan']={'entry':100}
    service.last_success=time.time()-121
    status=service.status()
    assert status['analysis']['structure']['state']=='unavailable'
    assert status['analysis']['structure']['setup'] is None
    assert service.latest['snapshot']['structure']['setup']['plan']=={'entry':100}
