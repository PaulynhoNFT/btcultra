import asyncio
import hashlib
import logging
import math
import time
import uuid
from datetime import datetime, timezone, timedelta
import httpx
from app.live.engine import (PERIODS, analyze, summary, canonical, sizing, resolve_exit,
    close_trade, backtest, validate_candles)

BASE = 'https://data-api.binance.vision'
CALENDAR = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'
log=logging.getLogger(__name__)

class LiveService:
    def __init__(self, store):
        self.store=store; self.lock=asyncio.Lock(); self.last_success=0.; self.error=None
        self.latest=None; self.calendar=None; self.calendar_checked=0.; self.quote=None
        self.backtest_running=False

    async def json(self, client, url, params=None):
        response=await client.get(url,params=params)
        response.raise_for_status()
        return response.json()

    async def refresh_calendar(self, client, now):
        if self.calendar and now-self.calendar_checked<1800: return
        try:
            raw=await self.json(client,CALENDAR)
            if not isinstance(raw,list) or not raw: raise ValueError('Calendário vazio')
            parsed=[]
            for e in raw:
                date=datetime.fromisoformat(e['date'])
                if date.tzinfo is None: raise ValueError('Calendário sem fuso horário')
                parsed.append(dict(title=str(e['title']),country=str(e['country']),
                    impact=str(e['impact']),time=date.timestamp()))
            day=datetime.fromtimestamp(now,timezone.utc)
            sunday=(day-timedelta(days=(day.weekday()+1)%7)).replace(hour=0,minute=0,second=0,microsecond=0)
            if not any(sunday.timestamp() <= e['time'] < (sunday+timedelta(days=7)).timestamp() for e in parsed):
                raise ValueError('Calendário não corresponde à semana atual')
            self.calendar=parsed; self.calendar_checked=now
        except Exception as exc:
            log.warning('Calendário indisponível: %s',exc)

    def macro(self, now=None):
        now=time.time() if now is None else now
        available=self.calendar is not None and now-self.calendar_checked<3600
        events=[e for e in (self.calendar or []) if e['country']=='USD' and e['impact']=='High']
        blocked=available and any(abs(e['time']-now)<=900 for e in events)
        return dict(available=available,blocked=bool(blocked),source=CALENDAR,
            checked_at=self.calendar_checked or None,
            events=[e for e in events if e['time']>=now-900][:8])

    async def refresh(self):
        async with self.lock:
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    clock=await self.json(client,BASE+'/api/v3/time')
                    server=int(clock['serverTime'])
                    if abs(server-time.time()*1000)>90000: raise ValueError('Relógio da fonte inconsistente')
                    async def fetch_tf(tf,limit):
                        raw=await self.json(client,BASE+'/api/v3/klines',{'symbol':'BTCUSDT','interval':tf,'limit':limit})
                        return tf,validate_candles(raw,tf,server)
                    frames=dict(await asyncio.gather(fetch_tf('1d',400),fetch_tf('4h',400),fetch_tf('1h',1000)))
                    quote=await self.json(client,BASE+'/api/v3/ticker/24hr',{'symbol':'BTCUSDT'})
                    price=float(quote['lastPrice']);stamp=int(quote['closeTime'])
                    if quote['symbol']!='BTCUSDT' or not math.isfinite(price) or price<=0 or not -5000<=server-stamp<=90000:
                        raise ValueError('Cotação inválida ou desatualizada')
                    self.quote=dict(price=price,time=stamp)
                    self.store.save_candles(frames)
                    result=await asyncio.to_thread(analyze,frames)
                    self.store.save_analysis(result)
                    self.latest=self.store.analysis(result['id'])
                    await self.refresh_calendar(client,server/1000)
                    await self.settle_paper(client,server)
                    self.last_success=time.time();self.error=None
            except asyncio.CancelledError: raise
            except Exception as exc:
                self.error='Não foi possível validar os dados reais. Novos sinais estão bloqueados.'
                log.exception('Coleta de BTC falhou: %s',exc)

    async def run(self):
        while True:
            await self.refresh()
            await asyncio.sleep(60)

    def portfolio(self):
        trades=self.store.paper();closed=[t for t in trades if t['status']=='closed']
        equity=10000+sum(t['pnl'] for t in closed)
        now=datetime.now(timezone.utc)
        def pnl_since(days):
            boundary=(now-timedelta(days=days)).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()*1000
            return sum(t['pnl'] for t in closed if t['closed_at']>=boundary)
        losses=0
        for t in sorted(closed,key=lambda x:x['closed_at'],reverse=True):
            if t['pnl']>=0: break
            losses+=1
        breaker=pnl_since(0)<=-300 or pnl_since(6)<=-700 or pnl_since(29)<=-1500
        if losses>=5 and closed:
            breaker=breaker or time.time()*1000-max(t['closed_at'] for t in closed)<86400000
        return dict(initial_capital=10000,equity=equity,realized_pnl=equity-10000,
            consecutive_losses=losses,blocked=breaker,trades=trades,
            mode='Simulação em USDT; nenhum dinheiro ou ordem real')

    def status(self):
        now=time.time();fresh=self.latest is not None and now-self.last_success<120 and self.error is None
        macro=self.macro(now);portfolio=self.portfolio();reasons=[]
        if not fresh: reasons.append('DADOS_INDISPONIVEIS')
        if not macro['available']: reasons.append('CALENDARIO_INDISPONIVEL')
        if macro['blocked']: reasons.append('JANELA_MACRO')
        if portfolio['blocked']: reasons.append('LIMITE_DE_RISCO')
        current=summary(self.latest) if self.latest else None
        if current and not fresh and current.get('structure'):
            # Do not expose an old conditional plan as a current API signal.
            current['structure'] = dict(current['structure'], state='unavailable',
                reason='Dados antigos ou coleta indisponível. Hipótese sem autorização atual.', setup=None)
        if current and not current['decision']['ok']: reasons.append(current['decision']['reason'])
        actionable=bool(current and current['decision']['ok'] and not reasons)
        return dict(ready=fresh,last_success=self.last_success or None,error=self.error,
            analysis=current,macro=macro,block_reasons=reasons,actionable=actionable,
            portfolio=portfolio,backtest_running=self.backtest_running,
            storage='SQLite persistente',source='Binance Spot')

    async def open_paper(self, analysis_id, risk_pct):
        async with self.lock:
            status=self.status()
            if not status['actionable'] or self.latest['id']!=analysis_id:
                raise ValueError('O sinal não está ativo ou mudou. Atualize a análise.')
            if any(t['status'] in ('open','pending') for t in self.store.paper()):
                raise ValueError('Já existe uma simulação aberta ou aguardando entrada.')
            d=status['analysis']['decision'];effective=risk_pct*(0.5 if status['portfolio']['consecutive_losses']>=3 else 1)
            trade=dict(id=str(uuid.uuid4()),analysis_id=analysis_id,status='pending',side=d['side'],
                stop=d['stop'],target=d['tp2'],tp1=d['tp1'],tp3=d['tp3'],
                risk_pct=effective,capital=status['portfolio']['equity'],
                requested_at=int(time.time()*1000),source='Binance Spot',pnl=None,
                gate_snapshot=dict(macro=status['macro'],equity=status['portfolio']['equity'],consecutive_losses=status['portfolio']['consecutive_losses'],checked_at=time.time()),
                policy='Entrada na próxima abertura de 1 minuto; TP2 integral; stop prioritário; custos 0,15% por lado.')
            self.store.save_paper(trade,create=True)
            return trade

    async def settle_paper(self,client,server):
        for trade in self.store.paper():
            if trade['status'] not in ('pending','open'): continue
            if trade['status']=='pending' and server-trade['requested_at']>180000:
                trade|=dict(status='cancelled',cancel_reason='Coleta atrasada: a entrada agendada expirou.')
                self.store.save_paper(trade)
                continue
            start=trade.get('processed_until',((trade['requested_at']//60000)+1)*60000)
            # Paginate after downtime, stopping at the first unresolved/open minute.
            while start+60000<=server:
                rows=await self.json(client,BASE+'/api/v3/klines',{'symbol':'BTCUSDT','interval':'1m','startTime':start,'limit':1000})
                if not rows: raise ValueError('Candles de execução ausentes')
                progressed=False
                for row in rows:
                    ts=int(row[0])
                    if int(row[6])>=server: break
                    if ts!=start or int(row[6])!=ts+59999: raise ValueError('Lacuna na simulação')
                    o,h,l,c,v=map(float,row[1:6])
                    if not all(math.isfinite(x) for x in (o,h,l,c,v)) or min(o,h,l,c)<=0 or l>min(o,c) or h<max(o,c):
                        raise ValueError('Candle de execução inválido')
                    candle=dict(time=ts,open=o,high=h,low=l,close=c)
                    if trade['status']=='pending':
                        context=self.macro(ts/1000)
                        changed=self.latest is not None and self.latest['id']!=trade['analysis_id']
                        if not context['available'] or context['blocked'] or self.portfolio()['blocked'] or changed:
                            trade|=dict(status='cancelled',cancel_reason='Filtros de mercado, calendário ou risco mudaram antes da entrada.')
                            self.store.save_paper(trade)
                            break
                        buy=trade['side']=='BUY';risk=o-trade['stop'] if buy else trade['stop']-o
                        reward=trade['target']-o if buy else o-trade['target']
                        if risk<=0 or reward/risk<2-1e-9:
                            trade|=dict(status='cancelled',cancel_reason='A abertura invalidou o stop ou R:R mínimo.');self.store.save_paper(trade);break
                        trade|=sizing(o,trade['stop'],trade['capital'],trade['risk_pct'])
                        trade|=dict(status='open',entry=o,opened_at=ts)
                    result=resolve_exit(trade,candle)
                    if result:
                        trade=close_trade(trade,result[0],ts+60000,result[1]);self.store.save_paper(trade);break
                    trade['processed_until']=ts+60000;trade['last_price']=c
                    trade['unrealized_pnl']=close_trade(trade,c,ts,'mark')['pnl']
                    self.store.save_paper(trade);start=ts+60000;progressed=True
                if trade['status'] not in ('pending','open') or not progressed: break

    async def finish_paper(self, ident):
        pending=next((t for t in self.store.paper() if t['id']==ident),None)
        if not pending: raise ValueError('Simulação não encontrada')
        if pending['status']=='open':
            # Settle intervening stops before permitting a manual close at a fresh quote.
            await self.refresh()
        async with self.lock:
            trade=next(t for t in self.store.paper() if t['id']==ident)
            if trade['status']=='pending':
                trade|=dict(status='cancelled',cancel_reason='Cancelada pelo usuário antes da entrada.')
            elif trade['status']=='open':
                if not self.status()['ready'] or not self.quote or time.time()*1000-self.quote['time']>90000:
                    raise ValueError('Sem cotação válida para encerrar a simulação')
                trade=close_trade(trade,self.quote['price'],self.quote['time'],'manual')
            else:
                return trade  # idempotent confirmation if the stop just settled
            self.store.save_paper(trade)
            return trade

    async def run_backtest(self,days):
        if self.backtest_running: raise ValueError('Já existe um backtest em andamento')
        if not self.status()['ready']: raise ValueError('Aguarde a atualização dos candles reais')
        self.backtest_running=True
        try:
            frames={tf:self.store.candles(tf) for tf in PERIODS}
            result=await asyncio.to_thread(backtest,frames,days)
            result['created_at']=datetime.now(timezone.utc).isoformat()
            result['id']=hashlib.sha256(canonical(result).encode()).hexdigest()
            self.store.save_backtest(result)
            return result
        finally: self.backtest_running=False
