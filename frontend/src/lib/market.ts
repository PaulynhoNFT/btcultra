import { z } from 'zod';

export const SOURCE_URL = 'https://data-api.binance.vision';
const positive = z.coerce.number().finite().positive();
const nonnegative = z.coerce.number().finite().nonnegative();
const timestamp = z.number().int().positive();
const tickerSchema = z.object({
  symbol: z.literal('BTCUSDT'), lastPrice: positive,
  priceChangePercent: z.coerce.number().finite(), highPrice: positive,
  lowPrice: positive, volume: nonnegative, quoteVolume: nonnegative,
  closeTime: timestamp,
});
const candleSchema = z.tuple([
  timestamp, positive, positive, positive, positive, nonnegative,
  timestamp, z.unknown(), z.unknown(), z.unknown(), z.unknown(), z.unknown(),
]);

export function parseMarket(tickerInput: unknown, candlesInput: unknown, timeInput: unknown, now = Date.now()) {
  const ticker = tickerSchema.parse(tickerInput);
  const { serverTime } = z.object({ serverTime: timestamp }).parse(timeInput);
  const rows = z.array(candleSchema).min(2).max(200).parse(candlesInput);
  if (Math.abs(serverTime - now) > 90_000 || serverTime - ticker.closeTime > 90_000 || ticker.closeTime > serverTime + 5_000) {
    throw new Error('Cotação desatualizada ou relógio da fonte inconsistente.');
  }
  if (ticker.highPrice < ticker.lowPrice || ticker.lastPrice > ticker.highPrice || ticker.lastPrice < ticker.lowPrice) {
    throw new Error('Cotação inconsistente.');
  }
  const candles = rows.map((row, i) => {
    const [openTime, open, high, low, close, volume, closeTime] = row;
    if (high < Math.max(open, close) || low > Math.min(open, close) || high < low ||
        closeTime !== openTime + 3_600_000 - 1 || openTime > serverTime ||
        (i > 0 && openTime !== rows[i - 1][0] + 3_600_000)) {
      throw new Error('Candles inconsistentes ou com lacunas.');
    }
    return { time: openTime / 1000, open, high, low, close, volume, closed: closeTime < serverTime };
  });
  if (serverTime - rows[rows.length - 1][0] > 3_600_000) {
    throw new Error('Candles desatualizados.');
  }
  return {
    symbol: 'BTC/USDT', source: 'Binance Spot', sourceUrl: SOURCE_URL,
    interval: '1h', price: ticker.lastPrice, change24h: ticker.priceChangePercent,
    high24h: ticker.highPrice, low24h: ticker.lowPrice,
    volumeBtc24h: ticker.volume, volumeUsdt24h: ticker.quoteVolume,
    sourceTime: new Date(ticker.closeTime).toISOString(),
    fetchedAt: new Date(now).toISOString(), candles,
  };
}
export type BitcoinSnapshot = ReturnType<typeof parseMarket>;

export async function fetchMarket(fetcher: typeof fetch = fetch): Promise<BitcoinSnapshot> {
  const paths = ['/api/v3/ticker/24hr?symbol=BTCUSDT', '/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=120', '/api/v3/time'];
  const payloads = await Promise.all(paths.map(async path => {
    const response = await fetcher(`${SOURCE_URL}${path}`, { cache: 'no-store', signal: AbortSignal.timeout(10_000) });
    if (!response.ok) throw new Error(`Fonte de mercado indisponível (HTTP ${response.status}).`);
    return response.json();
  }));
  return parseMarket(payloads[0], payloads[1], payloads[2]);
}
