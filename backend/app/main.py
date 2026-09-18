"""Working single-user API; persistent local database, real public market data."""
import asyncio
import os
import sqlite3
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from app.live.store import Store
from app.live.service import LiveService
from app.live.engine import summary

DATA = Path(os.environ.get('BTC_DATA_DIR', Path(__file__).resolve().parents[1] / 'data'))
store=Store(DATA / 'btcultra.sqlite3')
service=LiveService(store)

@asynccontextmanager
async def lifespan(app):
    worker=asyncio.create_task(service.run())
    try: yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError): await worker

app=FastAPI(title='BTC Ultra — análise real e simulação',version='2.0.0',lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['localhost','127.0.0.1','backend','testserver'])

@app.middleware('http')
async def local_writes(request: Request,call_next):
    # Personal mode: bind to loopback and only accept mutations from the same-origin proxy.
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        if origin not in ('http://localhost:3000','http://127.0.0.1:3000'):
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail':'Origem não autorizada'},status_code=403)
    response=await call_next(request)
    response.headers['Cache-Control']='no-store'
    return response

@app.get('/health')
async def health():
    state=service.status()
    return {'status':'ok' if state['ready'] else 'warming_up','source':state['source'],'storage':state['storage']}

@app.get('/live/status')
async def status(): return service.status()

@app.get('/live/history')
async def history(): return [summary(s) for s in store.history()]

@app.get('/live/history/{ident}')
async def detail(ident: str):
    data=store.analysis(ident)
    if not data: raise HTTPException(404,'Análise não encontrada')
    return data

class PaperRequest(BaseModel):
    analysis_id: str = Field(min_length=64,max_length=64)
    risk_pct: float = Field(default=1,gt=0,le=1,allow_inf_nan=False)
    confirmed: Literal[True]

@app.post('/live/paper',status_code=201)
async def paper(body: PaperRequest):
    try: return await service.open_paper(body.analysis_id,body.risk_pct)
    except (ValueError,sqlite3.IntegrityError) as exc: raise HTTPException(409,str(exc)) from exc

class BacktestRequest(BaseModel):
    days: Literal[7,30] = 7

@app.post('/live/backtest')
async def run_backtest(body: BacktestRequest):
    try: return await service.run_backtest(body.days)
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc

@app.get('/live/backtest')
async def last_backtest(): return store.latest_backtest()

class FinishRequest(BaseModel):
    confirmed: Literal[True]

@app.post('/live/paper/{ident}/close')
async def finish_paper(ident: str, body: FinishRequest):
    try: return await service.finish_paper(ident)
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc
