import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseMarket, fetchMarket } from '../src/lib/market';

// Synthetic inputs are isolated test fixtures; the application never imports them.
const now = 1_800_001_000_000;
const start = Math.floor(now / 3_600_000) * 3_600_000;
const ticker = { symbol: 'BTCUSDT', lastPrice: '60000', priceChangePercent: '1.5', highPrice: '61000', lowPrice: '59000', volume: '123', quoteVolume: '7380000', closeTime: now };
const candle = (time: number) => [time, '59900', '60100', '59800', '60000', '12', time + 3_600_000 - 1, '0', 10, '0', '0', '0'];
const rows = () => [candle(start - 3_600_000), candle(start)];
test('preserves source values and distinguishes closed and open candles', () => {
  const data = parseMarket(ticker, rows(), { serverTime: now }, now);
  assert.equal(data.price, 60000);
  assert.equal(data.source, 'Binance Spot');
  assert.deepEqual(data.candles.map(c => c.closed), [true, false]);
  assert.equal(data.candles[0].volume, 12);
});
test('rejects stale quotes', () => {
  assert.throws(() => parseMarket({ ...ticker, closeTime: now - 100_000 }, rows(), { serverTime: now }, now));
});
test('rejects stale or future server clocks', () => {
  for (const offset of [-100_000, 100_000]) assert.throws(() => parseMarket(ticker, rows(), { serverTime: now + offset }, now));
});
test('rejects invalid OHLC and missing intervals', () => {
  const invalid = rows(); invalid[1][2] = '1';
  assert.throws(() => parseMarket(ticker, invalid, { serverTime: now }, now));
  assert.throws(() => parseMarket(ticker, [candle(start - 7_200_000), candle(start)], { serverTime: now }, now));
});
test('rejects missing, non-finite and other-symbol data', () => {
  for (const lastPrice of [null, '', 'NaN', 'Infinity', '-1']) assert.throws(() => parseMarket({ ...ticker, lastPrice }, rows(), { serverTime: now }, now));
  assert.throws(() => parseMarket({ ...ticker, symbol: 'ETHUSDT' }, rows(), { serverTime: now }, now));
});
test('does not replace HTTP failure with demo prices', async () => {
  const failing = async () => new Response('{}', { status: 503 });
  await assert.rejects(fetchMarket(failing as typeof fetch));
});
