'use client';

import { Signal } from '@/lib/api';
import { format, formatDistanceToNow } from 'date-fns';
import { ptBR } from 'date-fns/locale';
import { TrendingUp, TrendingDown, Target, Shield, AlertCircle, Info } from 'lucide-react';

interface SignalCardProps {
  signal: Signal;
}

export function SignalCard({ signal }: SignalCardProps) {
  const isBuy = signal.side === 'BUY';
  const isObservation = !signal.ok && signal.score >= 60;
  const isBlocked = !signal.ok && signal.score < 60;

  const badgeClass = isBuy
    ? 'signal-badge-buy'
    : isObservation
    ? 'signal-badge-observation'
    : 'signal-badge-blocked';

  const badgeLabel = signal.ok
    ? isBuy
      ? 'COMPRA'
      : 'VENDA'
    : isObservation
    ? 'OBSERVAÇÃO'
    : 'BLOQUEADO';

  const scoreColor = signal.score >= 80 ? 'text-bull' : signal.score >= 70 ? 'text-yellow-500' : 'text-muted-foreground';
  const scoreBg = signal.score >= 80 ? 'bg-bull/10' : signal.score >= 70 ? 'bg-yellow-500/10' : 'bg-muted';

  const timeAgo = formatDistanceToNow(new Date(signal.timestamp), { addSuffix: true, locale: ptBR });
  const timeFormatted = format(new Date(signal.timestamp), 'dd/MM HH:mm', { locale: ptBR });

  return (
    <article className="bg-card border border-border rounded-xl p-5 transition-all hover:border-primary/30 hover:shadow-lg">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-medium text-foreground">{signal.symbol}</span>
          <span className="px-1.5 py-0.5 text-xs font-medium bg-muted rounded text-muted-foreground">{signal.timeframe}</span>
          <span className={`signal-badge ${badgeClass}`}>{badgeLabel}</span>
        </div>
        <div className="text-right">
          <p className="text-xs text-muted-foreground">{timeAgo}</p>
          <p className="text-xs text-muted-foreground font-mono">{timeFormatted}</p>
        </div>
      </div>

      {/* Score & Reason */}
      <div className="mb-3">
        <div className="flex items-center justify-between mb-1">
          <span className="text-sm font-medium text-foreground">Score</span>
          <span className={`text-sm font-bold ${scoreColor}`}>{signal.score}/100</span>
        </div>
        <div className="score-bar">
          <div
            className={`score-bar-fill ${isBuy ? 'score-bar-fill-bull' : 'score-bar-fill-bear'} rounded-full`}
            style={{ width: `${Math.min(signal.score, 100)}%` }}
          />
        </div>
        <p className="text-xs text-muted-foreground mt-1 line-clamp-1">{signal.reason}</p>
      </div>

      {/* Price Levels */}
      <div className="space-y-1.5 mb-4 text-sm font-mono">
        <div className="flex items-center justify-between text-foreground">
          <span className="flex items-center gap-1.5">
            <Target className="w-3.5 h-3.5 text-muted-foreground" />
            <span>Entrada</span>
          </span>
          <span className="font-medium">{signal.entry_price.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        </div>
        <div className="flex items-center justify-between text-bear">
          <span className="flex items-center gap-1.5">
            <Shield className="w-3.5 h-3.5" />
            <span>Stop</span>
          </span>
          <span className="font-medium">{signal.stop_price.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        </div>
        <div className="flex items-center justify-between text-bull">
          <span className="flex items-center gap-1.5">
            <TrendingUp className="w-3.5 h-3.5" />
            <span>TP1</span>
          </span>
          <span className="font-medium">{signal.tp1.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        </div>
        <div className="flex items-center justify-between text-bull/80">
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <TrendingUp className="w-3.5 h-3.5" />
            <span>TP2</span>
          </span>
          <span className="font-medium">{signal.tp2.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        </div>
        <div className="flex items-center justify-between text-bull/60">
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <TrendingUp className="w-3.5 h-3.5" />
            <span>TP3</span>
          </span>
          <span className="font-medium">{signal.tp3.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        </div>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-3 gap-2 pt-3 border-t border-border">
        <div className="text-center p-2 bg-muted/50 rounded-lg">
          <p className="text-xs text-muted-foreground">R:R</p>
          <p className="font-bold font-mono text-foreground">{signal.rr.toFixed(1)}:1</p>
        </div>
        <div className="text-center p-2 bg-muted/50 rounded-lg">
          <p className="text-xs text-muted-foreground">Modo</p>
          <p className="font-medium text-foreground capitalize">{signal.mode}</p>
        </div>
        <div className="text-center p-2 bg-muted/50 rounded-lg">
          <p className="text-xs text-muted-foreground">Versão</p>
          <p className="font-mono text-xs text-muted-foreground">{signal.engine_version}</p>
        </div>
      </div>

      {/* Expandable details (placeholder for click) */}
      <button
        className="w-full mt-3 px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground rounded-lg bg-muted/50 transition-colors flex items-center justify-center gap-1.5"
        onClick={() => window.open(`/signal/${signal.id}`, '_blank')}
      >
        <Info className="w-3.5 h-3.5" />
        Ver detalhes e explicação completa
      </button>
    </article>
  );
}
