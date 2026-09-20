import type { StructureAnalysis } from './structure';
export interface Decision { ok: boolean; side: 'BUY' | 'SELL' | 'NONE'; score: number; reason: string; entry: number; stop: number; tp1: number; tp2: number; tp3: number; rr: number; breakdown: Record<string, number> }
export interface Analysis {
  structure?: StructureAnalysis;
  id: string; candle_time: number; created_at: string; engine_version: string; source: string; trend: string;
  decision: Decision; regime: { state: string; adx: number | null; bbw_pct: number | null; atr_pct: number | null; reason: string; ok_to_trade: boolean };
  correction: { state: string; rsi: number | null; stoch_k: number | null; near_ema13: boolean; in_fib_zone: boolean };
  trigger: { count: number; confirmed: boolean; macd_cross: boolean; rsi_exit: boolean; stoch_cross: boolean; candle_pattern: boolean; breakout_volume: boolean; cvd_confirm: boolean };
  indicators: Record<string, { close: number; ema13: number; macd_hist: number; rsi: number; atr: number; candle_time: number }>;
}
export interface PaperTrade { id: string; status: string; side: string; requested_at: number; opened_at?: number; entry?: number; quantity?: number; stop: number; target: number; pnl: number | null; unrealized_pnl?: number; exit?: number; exit_reason?: string; cancel_reason?: string }
export interface EngineStatus {
  ready: boolean; last_success: number | null; error: string | null; analysis: Analysis | null; actionable: boolean; block_reasons: string[];
  macro: { available: boolean; blocked: boolean; checked_at: number | null; source: string; events: { title: string; country: string; impact: string; time: number }[] };
  portfolio: { initial_capital: number; equity: number; realized_pnl: number; consecutive_losses: number; blocked: boolean; trades: PaperTrade[] };
  backtest_running: boolean;
}
export interface BacktestResult { id: string; days: number; initial_capital: number; final_equity: number; return_pct: number; max_drawdown_pct: number; trade_count: number; win_rate: number | null; start_time: number; end_time: number; assumptions: string[]; curve: { time: number; equity: number }[]; trades: { side: string; opened_at: number; entry: number; exit: number; pnl: number; costs: number; exit_reason: string }[] }
export async function engineRequest<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/engine/${path}`, { cache: 'no-store', ...(body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}) });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Não foi possível concluir a operação.');
  return data;
}
const reasons: Record<string,string> = {
  DADOS_INDISPONIVEIS: 'Dados ausentes, antigos ou coleta indisponível.',
  CALENDARIO_INDISPONIVEL: 'Não foi possível validar o calendário econômico desta semana.',
  JANELA_MACRO: 'Evento de alto impacto em USD dentro da janela de 15 minutos.',
  LIMITE_DE_RISCO: 'Limite de perdas da carteira simulada atingido.',
  trend_undefined: 'A tendência diária ainda não confirmou uma direção.',
  insufficient_data: 'Histórico insuficiente para calcular os indicadores.',
  'regime:ADX<20': 'ADX abaixo de 20: mercado sem tendência suficiente.',
  'regime:ATR<20pct': 'Volatilidade abaixo da faixa exigida pelo motor.',
  'regime:ATR>80pct': 'Volatilidade acima da faixa permitida pelo motor.',
  'regime:BB squeeze': 'Compressão das bandas de Bollinger: aguardar expansão.',
  'correction:TOO_EARLY': 'A correção de 4h ainda está longe da zona de entrada.',
  'correction:TOO_LATE': 'O preço já se afastou da zona de correção.',
  'correction:NO_CORRECTION': 'Ainda não há correção válida na direção da tendência.',
  observation_only: 'Score entre 60 e 69: observar, sem liberar entrada.',
  score_below_60: 'Score abaixo do mínimo para observação.',
  ok: 'As três telas confirmaram o cenário técnico.',
};
export function reasonText(reason: string) {
  if (reason.startsWith('trigger_count:')) return `Somente ${reason.split(':')[1]} de 6 confirmações no período de 1h; são necessárias pelo menos 3.`;
  return reasons[reason] || reason;
}
