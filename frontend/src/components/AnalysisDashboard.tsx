'use client';
import { useEffect, useState } from 'react';
import { StructurePanel } from '@/components/StructurePanel';
import { BitcoinMarket } from '@/components/BitcoinMarket';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { engineRequest, reasonText, type Analysis, type BacktestResult, type EngineStatus } from '@/lib/engine';

const money = (v: number | null | undefined) => v == null ? '—' : new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 }).format(v);
const date = (v: number | null | undefined) => v ? new Date(v).toLocaleString('pt-BR') : '—';
const label = (v: string) => ({ BULL: 'Alta', BEAR: 'Baixa', UNDEFINED: 'Sem direção confirmada', INSUFFICIENT_DATA: 'Dados insuficientes', IDEAL: 'Correção confirmada', NO_CORRECTION: 'Sem correção', TOO_EARLY: 'Aguardar aproximação', TOO_LATE: 'Entrada tardia', TREND_STRONG: 'Tendência forte', TREND_WEAK: 'Tendência fraca', LATERAL: 'Lateral', BUY: 'Compra', SELL: 'Venda', NONE: 'Aguardar', pending: 'Entrada agendada', open: 'Aberta', closed: 'Encerrada', cancelled: 'Cancelada' }[v] || v);
const panel = 'rounded-xl border border-border bg-card p-5 scroll-mt-24';
const button = 'rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-40';
function Stat({ title, value }: { title: string; value: React.ReactNode }) { return <div><p className="text-xs text-muted-foreground">{title}</p><p className="mt-1 font-mono text-lg">{value}</p></div>; }

export function AnalysisDashboard() {
  const client = useQueryClient();
  const [clock, setClock] = useState(Date.now());
  const [risk, setRisk] = useState(1);
  const [confirmed, setConfirmed] = useState(false);
  const [days, setDays] = useState(7);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => { const id = setInterval(() => setClock(Date.now()), 1000); return () => clearInterval(id); }, []);
  const status = useQuery({ queryKey: ['engine-status'], queryFn: () => engineRequest<EngineStatus>('status'), refetchInterval: 15_000, retry: 1 });
  const history = useQuery({ queryKey: ['engine-history'], queryFn: () => engineRequest<Analysis[]>('history'), refetchInterval: 60_000, retry: 1 });
  const savedBacktest = useQuery({ queryKey: ['backtest'], queryFn: () => engineRequest<BacktestResult | null>('backtest'), retry: 1 });
  const detail = useQuery({ queryKey: ['snapshot', selected], queryFn: () => engineRequest<unknown>(`history/${selected}`), enabled: Boolean(selected) });
  const paper = useMutation({ mutationFn: () => engineRequest('paper', { analysis_id: status.data?.analysis?.id, risk_pct: risk, confirmed }), onSuccess: () => { setConfirmed(false); client.invalidateQueries({ queryKey: ['engine-status'] }); } });
  const finish = useMutation({ mutationFn: (id: string) => engineRequest(`paper/${id}/close`, { confirmed: true }), onSuccess: () => client.invalidateQueries({ queryKey: ['engine-status'] }) });
  const simulation = useMutation({ mutationFn: () => engineRequest<BacktestResult>('backtest', { days }), onSuccess: (data) => client.setQueryData(['backtest'], data) });
  const state = status.data;
  const a = state?.analysis;
  const directional = a?.trend === 'BULL' || a?.trend === 'BEAR';
  const fresh = Boolean(state?.ready && state.last_success && clock - state.last_success * 1000 < 120_000 && !status.error);
  const active = fresh && state?.actionable;
  const hasPosition = state?.portfolio.trades.some(t => ['pending', 'open'].includes(t.status));
  const d = a?.decision;
  const plan = d && d.entry > 0 && d.stop > 0;
  const qty = plan && state ? Math.min(state.portfolio.equity * risk / 100 / (Math.abs(d.entry - d.stop) + (d.entry + d.stop) * .0015), state.portfolio.equity / (d.entry * 1.0015)) : null;
  const bt = savedBacktest.data;
  useEffect(() => setConfirmed(false), [a?.id]);

  return <>
    <StructurePanel data={a?.structure} fresh={fresh} loading={status.isLoading} />
    <details className={panel}><summary className="cursor-pointer text-lg font-semibold">Filtros separados: Triple Screen por médias e MACD</summary>
    <section id="indicator-analysis" className="mt-5">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-xl font-semibold">Análise Triple Screen — BTC/USDT</h2><p className="text-sm text-muted-foreground">Recalculada a cada minuto com candles fechados; o histórico registra cada conjunto de dados.</p></div>
        <span className={`rounded-full px-4 py-2 font-semibold ${active ? 'bg-green-500/15 text-green-400' : 'bg-amber-500/10 text-amber-300'}`}>{!fresh ? 'Dados indisponíveis' : active ? `Sinal de ${label(d?.side || 'NONE').toLowerCase()}` : 'Aguardar'}</span></div>
      {status.isLoading && <p role="status" className="my-5">Carregando histórico real e indicadores…</p>}
      {status.error && <p role="alert" className="my-4 text-red-400">{status.error.message}</p>}
      {state && !fresh && <p role="alert" className="my-4 text-amber-300">{state.error || 'Aguardando uma coleta válida. Uma análise anterior não autoriza nova entrada.'}</p>}
      {a && <>
        <div className="my-6 grid gap-4 md:grid-cols-3">
          <div className="rounded-lg bg-muted/40 p-4"><p className="text-xs uppercase tracking-wide text-muted-foreground">Tela 1 · Tendência · 1D</p><h3 className="my-2 text-lg font-semibold">{label(a.trend)}</h3><p className="text-sm">{label(a.regime.state)} · ADX {money(a.regime.adx)}</p><p className="text-sm text-muted-foreground">EMA 13: {money(a.indicators['1d'].ema13)} · MACD: {money(a.indicators['1d'].macd_hist)}</p><p className="mt-3 text-xs text-muted-foreground">Candle: {date(a.indicators['1d'].candle_time)}</p></div>
          <div className="rounded-lg bg-muted/40 p-4"><p className="text-xs uppercase tracking-wide text-muted-foreground">Tela 2 · Correção · 4H</p><h3 className="my-2 text-lg font-semibold">{directional ? label(a.correction.state) : 'Aguardando a Tela 1'}</h3><p className="text-sm">RSI {money(a.correction.rsi ?? a.indicators['4h'].rsi)} · Estocástico {money(a.correction.stoch_k)}</p><p className="text-sm text-muted-foreground">Próxima à EMA: {!directional ? 'não avaliada' : a.correction.near_ema13 ? 'sim' : 'não'} · Zona Fibonacci: {!directional ? 'não avaliada' : a.correction.in_fib_zone ? 'sim' : 'não'}</p><p className="mt-3 text-xs text-muted-foreground">Candle: {date(a.indicators['4h'].candle_time)}</p></div>
          <div className="rounded-lg bg-muted/40 p-4"><p className="text-xs uppercase tracking-wide text-muted-foreground">Tela 3 · Gatilho · 1H</p><h3 className="my-2 text-lg font-semibold">{directional ? `${a.trigger.count} de 6 confirmações` : 'Aguardando a Tela 1'}</h3><p className="text-sm">{!directional ? 'Gatilhos direcionais ainda não avaliados' : a.trigger.confirmed ? 'Gatilho confirmado' : 'Mínimo necessário: 3'}</p><p className="text-sm text-muted-foreground">RSI {money(a.indicators['1h'].rsi)} · ATR {money(a.indicators['1h'].atr)}</p><p className="mt-3 text-xs text-muted-foreground">Candle: {date(a.indicators['1h'].candle_time)}</p></div>
        </div>
        {!directional && <p className="mb-4 rounded-lg bg-amber-500/10 p-4 text-sm text-amber-200">No diário, o fechamento está {a.indicators['1d'].close >= a.indicators['1d'].ema13 ? 'acima' : 'abaixo'} da EMA 13 ({money(a.indicators['1d'].ema13)} USDT), e o histograma MACD está em {money(a.indicators['1d'].macd_hist)}. O conjunto de critérios de direção ainda não foi confirmado. As telas 2 e 3 aguardam essa definição; isso é uma análise de espera, não um sinal de compra ou venda.</p>}
        <div className="rounded-lg border border-border p-4"><h3 className="font-semibold">Por que {active ? 'o sinal foi liberado' : 'aguardar'}?</h3><ul className="mt-2 list-inside list-disc space-y-1 text-sm text-muted-foreground">{(fresh ? state.block_reasons.length ? state.block_reasons : ['ok'] : ['DADOS_INDISPONIVEIS']).map(r => <li key={r}>{reasonText(r)}</li>)}</ul></div>
        <div className="mt-5 grid gap-5 lg:grid-cols-2"><div><h3 className="mb-2 font-semibold">Confirmações de 1h</h3><ul className="grid grid-cols-2 gap-2 text-sm">{([['macd_cross','Cruzamento MACD'],['rsi_exit','Saída do RSI'],['stoch_cross','Estocástico'],['candle_pattern','Padrão de candle'],['breakout_volume','Volume'],['cvd_confirm','Fluxo estimado por volume']] as const).map(([key,text]) => <li key={key} className={a.trigger[key] ? 'text-green-400' : 'text-muted-foreground'}>{!directional ? '—' : a.trigger[key] ? '✓' : '○'} {text}</li>)}</ul><p className="mt-2 text-xs text-muted-foreground">O fluxo é uma aproximação por preço e volume, não CVD de negócios individuais.</p></div>
          <div><h3 className="mb-2 font-semibold">Score {d?.score}/100</h3><p className="text-xs text-muted-foreground">O score só é calculado após os filtros de tendência, regime, correção e gatilho. Zero pode indicar bloqueio anterior.</p><div className="mt-3 flex flex-wrap gap-2">{Object.entries(d?.breakdown || {}).filter(([key]) => ['trend','correction','confluences','volume','candle','sr_prox','rr_bonus'].includes(key)).map(([key,value]) => <span key={key} className="rounded bg-muted px-2 py-1 text-xs">{{trend:'Tendência',correction:'Correção',confluences:'Confluências',volume:'Volume',candle:'Candle',sr_prox:'Proximidade',rr_bonus:'R:R'}[key]}: {value}</span>)}</div></div></div>
        {plan && <div className="mt-6 rounded-lg border border-border p-4"><h3 className="font-semibold">Plano técnico · {label(d.side)} {active ? '' : '· não liberado'}</h3><div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-6"><Stat title="Entrada de referência" value={money(d.entry)}/><Stat title="Stop" value={money(d.stop)}/><Stat title="TP1 · 1R" value={money(d.tp1)}/><Stat title="TP2 · 2R" value={money(d.tp2)}/><Stat title="TP3 · 3R" value={money(d.tp3)}/><Stat title="R:R até TP2" value={money(d.rr)}/></div><p className="mt-3 text-xs text-muted-foreground">Preços em USDT. Entrada de referência é o fechamento de 1h, não uma promessa de execução. A simulação usa a próxima abertura de 1 minuto e cancela se o R:R ficar abaixo de 2.</p></div>}
        <p className="mt-5 break-all text-xs text-muted-foreground">Fonte: {a.source} · última coleta: {date((state.last_success || 0) * 1000)} · versão: {a.engine_version} · snapshot: {a.id.slice(0,16)}…</p>
      </>}
    </section>

    </details>
    <BitcoinMarket />

    {state && <section className={panel}><h2 className="text-lg font-semibold">Calendário e bloqueios</h2><p className="mt-2 text-sm">{!state.macro.available ? 'Calendário indisponível: novas entradas bloqueadas.' : state.macro.blocked ? 'Janela macro ativa: novas entradas bloqueadas.' : 'Sem evento de alto impacto em USD na janela de ±15 minutos.'}</p><p className="mt-1 text-xs text-muted-foreground">Fonte: <a className="underline" href={state.macro.source} target="_blank" rel="noreferrer">Forex Factory / Fair Economy</a> · verificado: {date((state.macro.checked_at || 0) * 1000)}</p><ul className="mt-4 space-y-2 text-sm">{state.macro.events.map(e => <li key={`${e.title}-${e.time}`}><span className="text-muted-foreground">{date(e.time*1000)}</span> · {e.title}</li>)}</ul></section>}

    <section id="paper" className={panel}><h2 className="text-xl font-semibold">Carteira simulada · filtros de médias</h2><p className="text-sm text-muted-foreground">Saldo virtual inicial de 10.000 USDT. Nenhuma compra, venda ou transferência real.</p>
      {state && <><div className="my-5 grid grid-cols-2 gap-4 md:grid-cols-4"><Stat title="Saldo realizado · USDT" value={money(state.portfolio.equity)}/><Stat title="Resultado realizado · USDT" value={money(state.portfolio.realized_pnl)}/><Stat title="Perdas consecutivas" value={state.portfolio.consecutive_losses}/><Stat title="Proteção de perdas" value={state.portfolio.blocked ? 'Bloqueada' : 'Dentro dos limites'}/></div>
      <p className="text-xs text-muted-foreground">Limites: −300 USDT no dia, −700 em 7 dias, −1.500 em 30 dias. Após 3 perdas, risco reduzido pela metade; após 5, pausa de 24h.</p>
      <div className="mt-4 flex flex-wrap items-center gap-4"><label className="text-sm">Risco por operação <select value={risk} onChange={e => setRisk(Number(e.target.value))} className="ml-2 rounded border border-border bg-background p-2"><option value={0.5}>0,5%</option><option value={1}>1%</option></select></label>{qty != null && <p className="text-sm text-muted-foreground">Tamanho estimado: {qty.toFixed(6)} BTC · limitado ao saldo virtual.</p>}</div>
      <label className="my-4 flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} className="mt-1"/>Confirmo que desejo registrar uma operação simulada com entrada no próximo minuto, saída integral em TP2 ou stop e custos de 0,15% por lado.</label>
      <button className={button} disabled={!active || !confirmed || hasPosition || paper.isPending} onClick={() => paper.mutate()}>{paper.isPending ? 'Registrando…' : 'Confirmar simulação do sinal'}</button>
      {!active && <p className="mt-2 text-sm text-muted-foreground">Disponível quando o cenário técnico e todos os filtros estiverem aprovados.</p>}{hasPosition && <p className="mt-2 text-sm">Já existe uma operação aberta ou agendada.</p>}
      {finish.error && <p role="alert" className="mt-3 text-red-400">{finish.error.message}</p>}{paper.error && <p role="alert" className="mt-3 text-red-400">{paper.error.message}</p>}{paper.isSuccess && <p role="status" className="mt-3 text-green-400">Simulação registrada. A entrada será avaliada na próxima abertura de 1 minuto.</p>}
      <div className="mt-5 overflow-x-auto"><table className="w-full text-left text-sm"><thead className="text-muted-foreground"><tr><th className="p-2">Solicitação</th><th>Direção</th><th>Status</th><th>Entrada</th><th>Resultado · USDT</th><th>Ação</th></tr></thead><tbody>{state.portfolio.trades.map(t => <tr key={t.id} className="border-t border-border"><td className="p-2">{date(t.requested_at)}</td><td>{label(t.side)}</td><td>{label(t.status)}{t.cancel_reason && <p className="text-xs">{t.cancel_reason}</p>}</td><td>{money(t.entry)}</td><td>{money(t.pnl ?? t.unrealized_pnl)}{t.status==='open' ? ' (em aberto)' : ''}</td><td>{['pending','open'].includes(t.status) && <button className="text-primary underline disabled:opacity-40" disabled={finish.isPending} onClick={() => { if (window.confirm(t.status === 'pending' ? 'Cancelar a entrada simulada agendada?' : 'Encerrar a operação simulada pela cotação real atual, descontando os custos?')) finish.mutate(t.id); }}>{t.status === 'pending' ? 'Cancelar' : 'Encerrar'}</button>}</td></tr>)}</tbody></table>{!state.portfolio.trades.length && <p className="py-4 text-sm text-muted-foreground">Nenhuma operação simulada registrada.</p>}</div></>}
    </section>

    <section id="backtest" className={panel}><h2 className="text-xl font-semibold">Backtest dos filtros de médias</h2><p className="mt-1 text-sm text-muted-foreground">Teste retrospectivo do motor técnico. Os filtros macro históricos não estão incluídos; os resultados não representam o desempenho completo do fluxo ao vivo.</p>
      <div className="my-4 flex gap-3"><label><span className="sr-only">Período do backtest</span><select value={days} onChange={e => setDays(Number(e.target.value))} className="rounded border border-border bg-background p-2"><option value={7}>Últimos 7 dias</option><option value={30}>Últimos 30 dias</option></select></label><button className={button} disabled={!fresh || simulation.isPending || state?.backtest_running} onClick={() => simulation.mutate()}>{simulation.isPending || state?.backtest_running ? 'Calculando…' : 'Executar backtest'}</button></div>
      {simulation.error && <p role="alert" className="text-red-400">{simulation.error.message}</p>}
      {bt && <><p className="text-xs text-muted-foreground">{date(bt.start_time)} → {date(bt.end_time)} · {bt.days} dias</p><div className="my-5 grid grid-cols-2 gap-4 md:grid-cols-4"><Stat title="Saldo final · USDT" value={money(bt.final_equity)}/><Stat title="Retorno líquido" value={`${money(bt.return_pct)}%`}/><Stat title="Queda máxima" value={`${money(bt.max_drawdown_pct)}%`}/><Stat title="Operações / acerto" value={`${bt.trade_count} / ${bt.win_rate == null ? '—' : money(bt.win_rate)+'%'}`}/></div>
      {bt.trade_count===0 && <p className="my-3 text-sm text-amber-300">Nenhuma entrada passou pelos critérios no período. Não foram criadas operações para preencher o resultado.</p>}
      <ul className="list-inside list-disc space-y-1 text-xs text-muted-foreground">{bt.assumptions.map(s=><li key={s}>{s}</li>)}</ul>
      {bt.trades.length>0 && <div className="mt-4 overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>Entrada</th><th>Direção</th><th>Preço</th><th>Saída</th><th>Custos</th><th>Resultado</th></tr></thead><tbody>{bt.trades.map((t,i)=><tr key={i} className="border-t border-border"><td className="py-2">{date(t.opened_at)}</td><td>{label(t.side)}</td><td>{money(t.entry)}</td><td>{money(t.exit)}</td><td>{money(t.costs)}</td><td>{money(t.pnl)}</td></tr>)}</tbody></table></div>}</>}
    </section>

    <section id="history" className={panel}><h2 className="text-xl font-semibold">Histórico auditável</h2><p className="text-sm text-muted-foreground">Análises técnicas gravadas neste computador. Cada snapshot contém os 600 candles usados, indicadores e decisão. Um registro histórico não é um sinal ativo.</p>
      {history.error && <p className="mt-3 text-red-400">{history.error.message}</p>}
      <div className="mt-4 overflow-x-auto"><table className="w-full text-left text-sm"><thead className="text-muted-foreground"><tr><th className="p-2">Candle de 1h</th><th>Tendência</th><th>Decisão técnica</th><th>Score</th><th>Auditoria</th></tr></thead><tbody>{history.data?.map(row=><tr className="border-t border-border" key={row.id}><td className="p-2">{date(row.candle_time)}</td><td>{label(row.trend)}</td><td>{row.decision.ok ? label(row.decision.side) : 'Aguardar'}</td><td>{row.decision.score}</td><td><button className="text-primary underline" onClick={()=>setSelected(selected===row.id?null:row.id)}>Ver snapshot</button></td></tr>)}</tbody></table>{history.data?.length===0 && <p className="py-4 text-sm text-muted-foreground">Aguardando a primeira análise válida.</p>}</div>
      {selected && <div className="mt-4"><a className="text-sm text-primary underline" href={`/api/engine/history/${selected}`} target="_blank" rel="noreferrer">Abrir JSON completo</a>{detail.error && <p className="text-red-400">{detail.error.message}</p>}<pre className="mt-2 max-h-80 overflow-auto rounded bg-muted/50 p-3 text-xs">{detail.isLoading ? 'Carregando snapshot…' : JSON.stringify(detail.data,null,2)}</pre></div>}
    </section>
  </>;
}
