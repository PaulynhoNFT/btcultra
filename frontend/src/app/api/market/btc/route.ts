import { NextResponse } from 'next/server';
import { fetchMarket, type BitcoinSnapshot } from '@/lib/market';
export const dynamic = 'force-dynamic';
let cached: BitcoinSnapshot | undefined;
let pending: Promise<BitcoinSnapshot> | undefined;
export async function GET() {
  try {
    if (!cached || Date.now() - Date.parse(cached.fetchedAt) > 15_000) {
      pending ??= fetchMarket();
      try { cached = await pending; } finally { pending = undefined; }
    }
    return NextResponse.json(cached, { headers: { 'Cache-Control': 'no-store' } });
  } catch {
    cached = undefined;
    return NextResponse.json({ error: 'Dados reais de BTC indisponíveis. Aguarde a próxima atualização.' }, { status: 503, headers: { 'Cache-Control': 'no-store' } });
  }
}
