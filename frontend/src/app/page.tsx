'use client';

import { useEffect, useState } from 'react';
import { BitcoinMarket } from '@/components/BitcoinMarket';
import { getAccessToken } from '@/lib/api';
import { SignalCard } from '@/components/SignalCard';
import { RegimeBanner } from '@/components/RegimeBanner';
import { useSignals } from '@/hooks/useSignals';
import { useRegime } from '@/hooks/useRegime';

export default function HomePage() {
  const [activeTab, setActiveTab] = useState<'all' | 'active' | 'observation'>('active');
  const [authenticated, setAuthenticated] = useState(false);
  useEffect(() => setAuthenticated(Boolean(getAccessToken())), []);
  const { data, isLoading, error } = useSignals({ symbol: 'BTC/USDT', ok: activeTab === 'active' ? true : activeTab === 'observation' ? false : undefined }, authenticated);
  const signals = data?.signals;
  const { data: regime, isLoading: regimeLoading } = useRegime();

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-40">
        <div className="container mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
              <svg className="w-5 h-5 text-primary-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
            </div>
            <h1 className="text-xl font-bold text-foreground">Signal Platform</h1>
            <span className="px-2 py-0.5 text-xs font-medium bg-muted rounded-full text-muted-foreground">v1.0.0</span>
          </div>

          <nav className="flex items-center gap-1 bg-muted p-1 rounded-lg">
            {[
              { key: 'active', label: 'Ativos', count: signals?.filter(s => s.ok).length },
              { key: 'observation', label: 'Observação', count: signals?.filter(s => !s.ok && s.score >= 60).length },
              { key: 'all', label: 'Todos', count: signals?.length },
            ].map(tab => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key as any)}
                className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                  activeTab === tab.key
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {tab.label} {tab.count !== undefined && (
                  <span className="ml-1.5 px-1.5 py-0.5 text-xs bg-primary/10 text-primary rounded-full">
                    {tab.count}
                  </span>
                )}
              </button>
            ))}
          </nav>

          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground hidden sm:block">BTC/USDT • 4H</span>
            <span className="text-xs text-muted-foreground">Mercado público</span>
          </div>
        </div>
      </header>

      {/* Regime Banner */}
      <RegimeBanner regime={regime} loading={regimeLoading} />

      {/* Main Content */}
      <main className="container mx-auto px-4 py-6">
        <BitcoinMarket />
        {!authenticated && <p className="my-6 text-sm text-muted-foreground">O histórico privado de sinais exige autenticação na API. As cotações e os candles acima são públicos.</p>}
        {error && (
          <div className="mb-6 p-4 bg-destructive/10 border border-destructive/20 text-destructive rounded-lg">
            Erro ao carregar sinais: {error.message}
          </div>
        )}

        {!authenticated ? null : isLoading ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {[...Array(8)].map((_, i) => (
              <SignalCardSkeleton key={i} />
            ))}
          </div>
        ) : signals && signals.length > 0 ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {signals
              .filter(s => {
                if (activeTab === 'active') return s.ok;
                if (activeTab === 'observation') return !s.ok && s.score >= 60;
                return true;
              })
              .map(signal => (
                <SignalCard key={signal.id} signal={signal} />
              ))}
          </div>
        ) : (
          <div className="text-center py-12 text-muted-foreground">
            <svg className="w-12 h-12 mx-auto mb-4 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <p className="text-lg">Nenhum sinal {activeTab === 'active' ? 'ativo' : activeTab === 'observation' ? 'em observação' : ''}</p>
            <p className="text-sm mt-1">O motor é conservador por padrão — não operar é a decisão padrão.</p>
          </div>
        )}

        {/* Disclaimer */}
        <div className="mt-12 p-4 bg-muted/50 rounded-lg border border-border">
          <p className="text-xs text-muted-foreground text-center">
            <strong>Disclaimer:</strong> Este site não constitui recomendação de investimento. Sinais são gerados por algoritmo determinístico
            baseado no Triple Screen de Elder adaptado para cripto. Performance passada não garante resultados futuros.
            Motor: triple-screen-v1 • Score Engine v1 • Risk Engine v1
          </p>
        </div>
      </main>
    </div>
  );
}

function SignalCardSkeleton() {
  return (
    <div className="bg-card border border-border rounded-xl p-5 animate-pulse space-y-3">
      <div className="flex items-center justify-between">
        <div className="h-4 w-24 bg-muted rounded"></div>
        <div className="h-6 w-20 bg-muted rounded-full"></div>
      </div>
      <div className="h-6 w-32 bg-muted rounded"></div>
      <div className="h-4 w-full bg-muted rounded"></div>
      <div className="h-4 w-3/4 bg-muted rounded"></div>
      <div className="h-2 bg-muted rounded-full mt-2">
        <div className="h-full w-1/2 bg-primary rounded-full"></div>
      </div>
      <div className="grid grid-cols-3 gap-2 pt-2">
        <div className="h-10 bg-muted rounded"></div>
        <div className="h-10 bg-muted rounded"></div>
        <div className="h-10 bg-muted rounded"></div>
      </div>
    </div>
  );
}
