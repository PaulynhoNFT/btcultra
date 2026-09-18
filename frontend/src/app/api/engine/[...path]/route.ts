import { NextRequest, NextResponse } from 'next/server';
import { allowedOrigin } from '@/lib/proxy';
export const dynamic = 'force-dynamic';
const base = process.env.ENGINE_API_URL || 'http://127.0.0.1:8000';
async function proxy(request: NextRequest, { params }: { params: { path: string[] } }) {
  const path = params.path.join('/');
  const read = /^(status|history|history\/[a-f0-9]{64}|backtest)$/.test(path);
  const write = /^(paper|backtest|paper\/[a-f0-9-]{36}\/close)$/.test(path);
  if ((request.method === 'GET' && !read) || (request.method === 'POST' && !write)) {
    return NextResponse.json({ detail: 'Rota não encontrada' }, { status: 404 });
  }
  const origin = request.headers.get('origin');
  if (request.method === 'POST' && !allowedOrigin(origin, request.headers.get('host'))) {
    return NextResponse.json({ detail: 'Esta operação está disponível apenas no painel local.' }, { status: 403 });
  }
  try {
    const response = await fetch(`${base}/live/${path}`, {
      method: request.method, cache: 'no-store', signal: AbortSignal.timeout(path === 'backtest' ? 120_000 : 15_000),
      headers: { 'Content-Type': 'application/json', ...(origin ? { Origin: origin } : {}) },
      ...(request.method === 'POST' ? { body: await request.text() } : {}),
    });
    return new NextResponse(await response.text(), { status: response.status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });
  } catch {
    return NextResponse.json({ detail: 'Motor indisponível. Inicie a API local e aguarde a coleta dos dados reais.' }, { status: 503 });
  }
}
export const GET = proxy;
export const POST = proxy;
