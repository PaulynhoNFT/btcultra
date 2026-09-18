'use client';
import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ColorType, createChart, type UTCTimestamp } from 'lightweight-charts';
import type { BitcoinSnapshot } from '@/lib/market';

const price = (value: number) => new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2, minimumFractionDigits: 2 }).format(value);
function CandleChart({ candles }: { candles: BitcoinSnapshot['candles'] }) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!container.current) return;
    const chart = createChart(container.current, {
      autoSize: true, height: 330,
      layout: { background: { type: ColorType.Solid, color: '#101827' }, textColor: '#a9b7cd' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      timeScale: { timeVisible: true },
    });
    chart.addCandlestickSeries({ upColor: '#22c55e', downColor: '#ef4444', borderVisible: false, wickUpColor: '#22c55e', wickDownColor: '#ef4444' })
      .setData(candles.map(c => ({ ...c, time: c.time as UTCTimestamp })));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [candles]);
  return <div ref={container} className="h-[330px] w-full" role="img" aria-label="Candles reais de BTC/USDT, período de uma hora, horários em UTC" />;
}
export function BitcoinMarket() {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const { data, error, isLoading, isFetching, refetch } = useQuery<BitcoinSnapshot>({
    queryKey: ['bitcoin-market'],
    queryFn: async () => {
      const response = await fetch('/api/market/btc', { cache: 'no-store' });
      if (!response.ok) throw new Error('Dados reais de BTC indisponíveis.');
      return response.json();
    },
    refetchInterval: 30_000, staleTime: 15_000, retry: 1,
  });
  const stale = data ? now - Date.parse(data.sourceTime) > 90_000 : false;
  const unavailable = Boolean(error) || stale;
  return <section className="mb-8 rounded-xl border border-border bg-card p-5" aria-labelledby="btc-title">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 id="btc-title" className="text-xl font-bold">Bitcoin <span className="text-sm text-muted-foreground">BTC/USDT · Spot</span></h2>
        <p className="text-sm text-muted-foreground">Dados reais da Binance · atualização a cada 30 segundos</p></div>
      <button onClick={() => refetch()} disabled={isFetching} className="rounded border border-border px-3 py-2 text-sm disabled:opacity-50">{isFetching ? 'Atualizando…' : 'Atualizar'}</button>
    </div>
    {isLoading && <p className="py-12 text-muted-foreground" role="status">Consultando a fonte de mercado…</p>}
    {unavailable && <p role="alert" className="my-5 rounded bg-destructive/10 p-4 text-destructive">{stale ? 'Dados desatualizados. A cotação ficará oculta até uma nova consulta válida.' : 'Fonte indisponível. Nenhum preço estimado será exibido.'}</p>}
    {data && !unavailable && <>
      <div className="my-6 grid grid-cols-2 gap-5 md:grid-cols-4">
        <div><p className="text-xs text-muted-foreground">Preço · USDT</p><p className="text-2xl font-bold tabular-nums">{price(data.price)}</p></div>
        <div><p className="text-xs text-muted-foreground">Variação · 24h</p><p className={`text-xl font-bold ${data.change24h >= 0 ? 'text-green-500' : 'text-red-500'}`}>{data.change24h >= 0 ? '+' : ''}{price(data.change24h)}%</p></div>
        <div><p className="text-xs text-muted-foreground">Máxima / mínima · 24h · USDT</p><p className="tabular-nums">{price(data.high24h)} / {price(data.low24h)}</p></div>
        <div><p className="text-xs text-muted-foreground">Volume · 24h · BTC</p><p className="tabular-nums">{price(data.volumeBtc24h)}</p></div>
      </div>
      <CandleChart candles={data.candles} />
      <p className="mt-3 text-xs text-muted-foreground">120 candles de 1h · horários do gráfico em UTC · o último candle pode estar em formação.</p>
      <p className="mt-2 text-xs text-muted-foreground">Fonte: <a href="https://www.binance.com/en/trade/BTC_USDT" target="_blank" rel="noreferrer" className="underline">{data.source}</a> · horário da cotação: {new Date(data.sourceTime).toLocaleString('pt-BR')} · USDT não é cotação em reais.</p>
      <p className="mt-2 text-xs text-muted-foreground">Gráfico com <a className="underline" href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView Lightweight Charts</a>.</p>
    </>}
  </section>;
}
