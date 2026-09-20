export type Direction = 'BULL' | 'BEAR' | 'RANGE';
export interface StructureCandle { time: number; close_time: number; open: number; high: number; low: number; close: number }
export interface Pivot { kind: 'high' | 'low'; price: number; time: number; confirmed_at: number }
export interface StructureEvent { kind: string; side: Direction; time: number; price: number; label: string }
export interface Zone { kind: string; side: Direction; low: number; high: number; time: number; confirmed_at: number; status: string; ended_at: number | null; midpoint?: number; origin?: number; end?: number }
export interface StructureScreen { direction: Direction; internal_direction: Direction; protected: Pivot | null; pivots: Pivot[]; events: StructureEvent[]; zones: Zone[]; clusters: {kind: string; price: number; time: number}[]; candles: StructureCandle[]; description: string; close_time: number; close: number }
export interface StructureAnalysis { version: string; state: string; reason: string | null; timeframe_note?: string; screens: Record<string, StructureScreen>; setup: null | {state: string; side: Direction; waiting: string; invalidation: string; zone: Zone | null; checks: {key: string; ok: boolean; text: string}[]; plan: null | {side: Direction; entry: number; stop: number; target: number; rr: number; net_rr: number; conditional: boolean; execution_enabled: boolean}} }
export const directionText = (d: Direction) => ({BULL: 'Alta', BEAR: 'Baixa', RANGE: 'Sem direção confirmada'}[d]);
export const numberText = (n: number) => new Intl.NumberFormat('pt-BR', {maximumFractionDigits: 2}).format(n);
export const zoneText = (z: Zone) => z.kind === 'retracement' ? 'Região para observar' : z.kind === 'block' ? 'Região de reação do preço' : z.status === 'filled' ? 'Faixa já preenchida' : z.status === 'partial' ? 'Faixa parcialmente preenchida' : 'Faixa ainda não preenchida';
// Keep a visible margin even for a perfectly flat fixture or a single price.
export function chartBounds(candles: StructureCandle[], zones: Zone[]) {
  const values = [...candles.flatMap(c => [c.low,c.high]), ...zones.flatMap(z => [z.low,z.high])];
  const low=Math.min(...values), high=Math.max(...values), pad=Math.max((high-low)*.08,high*.001);
  return {low:low-pad, high:high+pad};
}
