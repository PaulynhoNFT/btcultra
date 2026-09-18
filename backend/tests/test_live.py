"""Isolated fixtures: none of these prices are served by the application."""
import hashlib
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from app.live.engine import (PERIODS, validate_candles, analyze, canonical, sizing,
    resolve_exit, close_trade, backtest)
from app.live.store import Store
from app.live.service import LiveService
from app.core.signal_core import SignalDecision, ScoreBreakdown, Side

NOW=1800000000000

def source_rows(tf,count=400):
    p=PERIODS[tf];start=(NOW//p-count)*p
    return [[start+i*p,'100','102','98','101','20',start+(i+1)*p-1,0,0,0,0,0] for i in range(count)]

@pytest.fixture
def frames():
    return {tf:validate_candles(source_rows(tf,1000 if tf=='1h' else 400),tf,NOW) for tf in PERIODS}

@pytest.fixture
def service(tmp_path): return LiveService(Store(tmp_path/'real.sqlite3'))

def test_open_candle_excluded():
    rows=source_rows('1h');p=PERIODS['1h'];ts=NOW//p*p
    rows.append([ts,'100','102','98','101','20',ts+p-1])
    result=validate_candles(rows,'1h',NOW)
    assert result[-1]['close_time']<NOW and len(result)==400

@pytest.mark.parametrize('mutation', ['gap','duplicate','invalid_high','nan','negative_volume','stale'])
def test_bad_source_rejected(mutation):
    rows=source_rows('1h')
    if mutation=='gap': rows.pop(50)
    elif mutation=='duplicate': rows[50]=rows[49]
    elif mutation=='invalid_high': rows[-1][2]='50'
    elif mutation=='nan': rows[-1][4]='NaN'
    elif mutation=='negative_volume': rows[-1][5]='-1'
    elif mutation=='stale': rows=rows[:-3]
    with pytest.raises(ValueError): validate_candles(rows,'1h',NOW)

def test_snapshot_replay_and_persistence(frames,tmp_path):
    result=analyze(frames)
    assert result['id']==hashlib.sha256(canonical(result['snapshot']).encode()).hexdigest()
    assert analyze(result['snapshot']['inputs'])['id']==result['id']
    store=Store(tmp_path/'state.sqlite3');store.save_candles(frames);store.save_analysis(result);store.save_analysis(result)
    reopened=Store(tmp_path/'state.sqlite3')
    assert len(reopened.history())==1
    assert reopened.analysis(result['id'])==result
    assert len(reopened.candles('1h'))==1000

def test_calendar_unavailable_and_stale_blocks(service,frames):
    service.latest=analyze(frames);service.latest['snapshot']['decision']['ok']=True
    service.last_success=time.time()
    assert 'CALENDARIO_INDISPONIVEL' in service.status()['block_reasons']
    assert not service.status()['actionable']
    service.calendar=[];service.calendar_checked=time.time()
    service.last_success=time.time()-121
    assert 'DADOS_INDISPONIVEIS' in service.status()['block_reasons']

def test_macro_window_includes_past_event(service):
    service.calendar=[dict(title='CPI',country='USD',impact='High',time=time.time()-600)]
    service.calendar_checked=time.time()
    assert service.macro()['blocked']

@pytest.mark.asyncio
async def test_network_failure_never_reuses_ready_state(service,frames):
    service.latest=analyze(frames);service.last_success=time.time()
    service.json=AsyncMock(side_effect=ValueError('source failure'))
    await service.refresh()
    assert not service.status()['ready']
    assert service.status()['error']

@pytest.mark.asyncio
async def test_successful_refresh_saves_closed_candles(service,monkeypatch):
    import app.live.service as module
    monkeypatch.setattr(module.time,'time',lambda:NOW/1000)
    async def remote(client,url,params=None):
        if url.endswith('/time'): return {'serverTime':NOW}
        if url.endswith('/klines'): return source_rows(params['interval'],params['limit'])
        if 'ticker' in url: return {'symbol':'BTCUSDT','lastPrice':'101','closeTime':NOW}
        return [{'date':datetime.fromtimestamp(NOW/1000,timezone.utc).isoformat(),'title':'CPI','country':'USD','impact':'High'}]
    service.json=remote
    await service.refresh()
    assert service.status()['ready']
    assert service.macro()['blocked']
    assert len(service.store.history())==1
    assert len(service.store.candles('1h'))==1000

def test_sizing_includes_costs_and_caps_notional():
    result=sizing(100,99,10000,1)
    assert result['estimated_risk']<=100.0000001
    assert result['notional']<=10000
    with pytest.raises(ValueError): sizing(100,100)
    with pytest.raises(ValueError): sizing(100,99,risk_pct=2)
    with pytest.raises(ValueError): sizing(float('nan'),99)

def test_stop_priority_and_gap():
    trade=dict(side='BUY',entry=100,stop=98,target=104,quantity=1)
    assert resolve_exit(trade,dict(open=100,high=105,low=97))==(98,'stop')
    assert resolve_exit(trade,dict(open=96,high=101,low=95))==(96,'stop_gap')
    result=close_trade(trade,104,NOW,'target')
    assert result['pnl']==pytest.approx(4-204*.0015)

def test_single_pending_position_enforced(service):
    service.store.save_paper(dict(id='a',analysis_id='one',status='pending'),create=True)
    with pytest.raises(ValueError): service.store.save_paper(dict(id='b',analysis_id='two',status='pending'),create=True)

@pytest.mark.asyncio
async def test_paper_executes_next_minute_and_settles_once(service):
    service.calendar=[];service.calendar_checked=NOW/1000
    requested=NOW;start=(requested//60000+1)*60000
    trade=dict(id='a',analysis_id='one',status='pending',side='BUY',stop=98,target=104,risk_pct=1,capital=10000,requested_at=requested)
    service.store.save_paper(trade,create=True)
    service.json=AsyncMock(return_value=[[start,100,105,99,104,1,start+59999]])
    await service.settle_paper(None,start+60001)
    saved=service.store.paper()[0]
    assert saved['opened_at']==start and saved['status']=='closed'
    assert saved['exit']==104 and saved['costs']>0 and saved['pnl']>0
    await service.settle_paper(None,start+120001)
    assert service.store.paper()[0]==saved

@pytest.mark.asyncio
async def test_entry_gap_cancels_instead_of_rewriting_plan(service):
    service.calendar=[];service.calendar_checked=NOW/1000
    start=(NOW//60000+1)*60000
    service.store.save_paper(dict(id='a',analysis_id='one',status='pending',side='BUY',stop=98,target=104,risk_pct=1,capital=10000,requested_at=NOW),create=True)
    service.json=AsyncMock(return_value=[[start,103,105,102,104,1,start+59999]])
    await service.settle_paper(None,start+60001)
    assert service.store.paper()[0]['status']=='cancelled'

@pytest.mark.asyncio
async def test_new_paper_requires_current_approved_analysis(service,frames):
    service.latest=analyze(frames);service.last_success=time.time()
    with pytest.raises(ValueError): await service.open_paper(service.latest['id'],1)
    assert service.store.paper()==[]

def test_backtest_closed_multitimeframe_no_lookahead(frames,monkeypatch):
    import app.live.engine as module
    seen=[]
    def blocked(d,h4,h1):
        assert d.close_time.max()<=h1.close_time.max()
        assert h4.close_time.max()<=h1.close_time.max()
        seen.append(h1.close_time.max())
        return SignalDecision(False,Side.NONE,0,'trend_undefined',ScoreBreakdown())
    monkeypatch.setattr(module,'generate_signal',blocked)
    result=backtest(frames,7)
    assert len(seen)==168
    assert result['trade_count']==0 and result['win_rate'] is None
    assert result['final_equity']==10000
    assert all(t<row['time'] for t,row in zip(seen,result['curve']))

def test_backtest_next_open_and_costs(frames,monkeypatch):
    import app.live.engine as module
    monkeypatch.setattr(module,'generate_signal',lambda *args:SignalDecision(True,Side.BUY,80,'ok',ScoreBreakdown(),100,99,101,102,103,2))
    result=backtest(frames,7)
    assert result['trade_count']>0
    trade=result['trades'][0]
    assert trade['entry']==100 and trade['exit']==99  # both touched: stop first
    assert trade['costs']>0 and trade['pnl']<0

def test_api_history_detail_and_origin_guard(service,frames,monkeypatch):
    import app.main as module
    result=analyze(frames);service.store.save_analysis(result)
    monkeypatch.setattr(module,'service',service);monkeypatch.setattr(module,'store',service.store)
    client=TestClient(module.app)  # no lifespan/network collection in this test
    assert client.get('/live/history').json()[0]['id']==result['id']
    assert client.get('/live/history/'+result['id']).json()['snapshot']['inputs']
    assert client.get('/live/history/missing').status_code==404
    assert client.post('/live/paper',json={}).status_code==403
    assert client.post('/live/paper',headers={'Origin':'http://127.0.0.1:3000'},json={'analysis_id':result['id'],'confirmed':False}).status_code==422
    assert client.post('/live/backtest',headers={'Origin':'http://127.0.0.1:3000'},json={'days':365}).status_code==422

@pytest.mark.asyncio
async def test_pending_trade_expires_during_outage(service):
    service.store.save_paper(dict(id='a',analysis_id='one',status='pending',side='BUY',stop=98,target=104,risk_pct=1,capital=10000,requested_at=NOW),create=True)
    service.json=AsyncMock()
    await service.settle_paper(None,NOW+240000)
    assert service.store.paper()[0]['status']=='cancelled'
    service.json.assert_not_called()

@pytest.mark.asyncio
async def test_cancel_pending_is_idempotent(service):
    service.store.save_paper(dict(id='a',analysis_id='one',status='pending',requested_at=NOW),create=True)
    result=await service.finish_paper('a')
    assert result['status']=='cancelled'
    assert await service.finish_paper('a')==result

def test_realized_daily_loss_blocks_entries(service):
    service.store.save_paper(dict(id='a',analysis_id='one',status='closed',closed_at=time.time()*1000,pnl=-301),create=True)
    assert service.portfolio()['blocked']
    assert service.portfolio()['equity']==9699

@pytest.mark.asyncio
async def test_approved_signal_can_be_confirmed_once(service,frames):
    result=analyze(frames)
    result['snapshot']['decision'].update(ok=True,side='BUY',entry=100,stop=98,tp1=102,tp2=104,tp3=106,rr=2,score=80)
    service.latest=result;service.last_success=time.time();service.calendar=[];service.calendar_checked=time.time()
    trade=await service.open_paper(result['id'],1)
    assert trade['status']=='pending' and trade['gate_snapshot']['macro']['available']
    with pytest.raises(ValueError): await service.open_paper(result['id'],1)

@pytest.mark.asyncio
async def test_backtest_result_is_persistent(service,frames):
    service.store.save_candles(frames);service.latest=analyze(frames);service.last_success=time.time()
    result=await service.run_backtest(7)
    assert service.store.latest_backtest()['id']==result['id']
    assert not service.backtest_running

@pytest.mark.asyncio
async def test_manual_close_uses_fresh_price_and_costs(service,frames):
    service.store.save_paper(dict(id='a',analysis_id='one',status='open',side='BUY',entry=100,stop=98,target=104,quantity=1),create=True)
    service.latest=analyze(frames);service.last_success=time.time();service.quote=dict(price=103,time=int(time.time()*1000))
    service.refresh=AsyncMock()
    result=await service.finish_paper('a')
    assert result['status']=='closed' and result['exit_reason']=='manual'
    assert result['pnl']==pytest.approx(3-203*.0015)

@pytest.mark.asyncio
async def test_macro_rechecked_before_scheduled_fill(service):
    start=(NOW//60000+1)*60000
    service.calendar=[dict(title='CPI',country='USD',impact='High',time=start/1000)]
    service.calendar_checked=NOW/1000
    service.store.save_paper(dict(id='a',analysis_id='one',status='pending',side='BUY',stop=98,target=104,risk_pct=1,capital=10000,requested_at=NOW),create=True)
    service.json=AsyncMock(return_value=[[start,100,105,99,104,1,start+59999]])
    await service.settle_paper(None,start+60001)
    assert service.store.paper()[0]['status']=='cancelled'
