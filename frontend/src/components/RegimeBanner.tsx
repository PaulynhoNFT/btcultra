'use client';

import type { RegimeData } from '@/lib/api';
import { getRegimeColor, getRegimeDescription } from '@/hooks/useRegime';
import { TrendingUp, TrendingDown, Minus, AlertTriangle, Info } from 'lucide-react';

interface RegimeBannerProps {
  regime: RegimeData | undefined;
  loading: boolean;
}

export function RegimeBanner({ regime, loading }: RegimeBannerProps) {
  if (!loading && !regime) {
    return <p className="container mx-auto px-4 py-3 text-sm text-muted-foreground">Regime indisponível — aguardando candles reais validados.</p>;
  }
  if (loading || !regime) {
    return (
      <div className="border-b border-border bg-card/50">
        <div className="container mx-auto px-4 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-muted animate-pulse flex items-center justify-center">
                <Minus className="w-5 h-5 text-muted-foreground" />
              </div>
              <div className="space-y-1">
                <div className="h-4 w-32 bg-muted rounded animate-pulse"></div>
                <div className="h-3 w-48 bg-muted rounded animate-pulse"></div>
              </div>
            </div>
            <div className="flex items-center gap-4 text-sm text-muted-foreground">
              <div className="h-4 w-24 bg-muted rounded animate-pulse"></div>
              <div className="h-4 w-24 bg-muted rounded animate-pulse"></div>
              <div className="h-4 w-24 bg-muted rounded animate-pulse"></div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const { bg, text, label } = getRegimeColor(regime.state);
  const description = getRegimeDescription(regime.state, regime.reason);

  const iconMap: Record<string, React.ReactNode> = {
    TREND_STRONG: <TrendingUp className="w-5 h-5" />,
    TREND_WEAK: <TrendingUp className="w-5 h-5 opacity-70" />,
    LATERAL: <Minus className="w-5 h-5" />,
    INSUFFICIENT: <AlertTriangle className="w-5 h-5" />,
  };

  return (
    <div className={`border-b border-border ${regime.ok_to_trade ? 'bg-bull/5' : 'bg-bear/5'}`}>
      <div className="container mx-auto px-4 py-3">
        <div className="flex items-center justify-between flex-wrap gap-4">
          {/* Regime Status */}
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${bg} ${text}`}>
              {iconMap[regime.state] || <Info className="w-5 h-5" />}
            </div>
            <div>
              <p className={`font-semibold ${text}`}>{label}</p>
              <p className="text-xs text-muted-foreground">{regime.symbol} • {regime.timeframe.toUpperCase()}</p>
            </div>
          </div>

          {/* Key Metrics */}
          <div className="flex items-center gap-6 text-sm">
            <div className="flex items-center gap-1.5">
              <span className="text-muted-foreground">ADX</span>
              <span className="font-mono font-medium text-foreground">{regime.adx.toFixed(1)}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-muted-foreground">BBW %</span>
              <span className="font-mono font-medium text-foreground">{(regime.bbw_pct * 100).toFixed(0)}%</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-muted-foreground">ATR %</span>
              <span className="font-mono font-medium text-foreground">{(regime.atr_pct * 100).toFixed(0)}%</span>
            </div>
            {regime.hmm_bull_prob !== undefined && regime.hmm_bear_prob !== undefined && (
              <>
                <div className="flex items-center gap-1.5">
                  <span className="text-muted-foreground">HMM Bull</span>
                  <span className="font-mono font-medium text-bull">{(regime.hmm_bull_prob * 100).toFixed(0)}%</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="text-muted-foreground">HMM Bear</span>
                  <span className="font-mono font-medium text-bear">{(regime.hmm_bear_prob * 100).toFixed(0)}%</span>
                </div>
              </>
            )}
          </div>

          {/* Trade Permission */}
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg ${regime.ok_to_trade ? 'bg-bull/10 text-bull' : 'bg-bear/10 text-bear'}`}>
            {regime.ok_to_trade ? (
              <>
                <TrendingUp className="w-4 h-4" />
                <span className="font-medium">Operar permitido</span>
              </>
            ) : (
              <>
                <AlertTriangle className="w-4 h-4" />
                <span className="font-medium">Sem sinal — {regime.reason}</span>
              </>
            )}
          </div>
        </div>

        {/* Description */}
        <div className="mt-2 pt-2 border-t border-border/50">
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
      </div>
    </div>
  );
}
