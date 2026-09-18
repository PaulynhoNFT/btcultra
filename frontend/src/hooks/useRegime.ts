import { useQuery } from '@tanstack/react-query';
import { fetchRegime, type RegimeData } from '@/lib/api';

export function useRegime(symbol = 'BTC/USDT', timeframe = '4h') {
  return useQuery<RegimeData, Error>({
    queryKey: ['regime', symbol, timeframe],
    queryFn: () => fetchRegime(symbol, timeframe),
    staleTime: 60_000,
    refetchInterval: 300_000, // 5 minutes
    retry: 2,
  });
}

export function getRegimeColor(state: string): { bg: string; text: string; label: string } {
  switch (state) {
    case 'TREND_STRONG':
      return { bg: 'bg-bull/10', text: 'text-bull', label: 'Tendência Forte 🟢' };
    case 'TREND_WEAK':
      return { bg: 'bg-bull/10', text: 'text-bull', label: 'Tendência Fraca 🟡' };
    case 'LATERAL':
      return { bg: 'bg-yellow-500/10', text: 'text-yellow-500', label: 'Lateral 🟡' };
    case 'INSUFFICIENT':
      return { bg: 'bg-muted', text: 'text-muted-foreground', label: 'Dados Insuficientes ⚪' };
    default:
      return { bg: 'bg-muted', text: 'text-muted-foreground', label: state };
  }
}

export function getRegimeDescription(state: string, reason: string): string {
  const descriptions: Record<string, string> = {
    TREND_STRONG: 'ADX ≥ 25, volatilidade normal, regime favorável a tendência.',
    TREND_WEAK: '20 ≤ ADX < 25, tendência presente mas fraca.',
    LATERAL: 'ADX < 20 ou squeeze de Bollinger ou ATR extremo — mercado sem direção clara.',
    INSUFFICIENT: 'Histórico insuficiente para classificar regime.',
  };
  return descriptions[state] || reason;
}
