import { AnalysisDashboard } from '@/components/AnalysisDashboard';
export default function HomePage() {
  return <div className="min-h-screen bg-background">
    <header className="border-b border-border sticky top-0 z-40 bg-background/95 backdrop-blur">
      <div className="container mx-auto flex flex-wrap items-center justify-between gap-3 px-4 py-4">
        <div><h1 className="text-xl font-bold">BTC Ultra <span className="ml-2 text-xs font-normal text-muted-foreground">Triple Screen</span></h1><p className="text-xs text-muted-foreground">Mercado real · decisões explicadas · simulação local</p></div>
        <nav className="flex gap-4 text-sm"><a href="#analysis">Análise</a><a href="#history">Histórico</a><a href="#paper">Simulação</a><a href="#backtest">Backtest</a></nav>
      </div>
    </header>
    <main className="container mx-auto space-y-8 px-4 py-6">
      <AnalysisDashboard />
      <footer className="rounded-xl border border-border bg-muted/30 p-4 text-xs text-muted-foreground">Ferramenta de análise e simulação. Sinais algorítmicos não garantem resultados e não são recomendação personalizada. Nenhuma ordem é enviada à corretora. A carteira é virtual e usa USDT como unidade. As decisões utilizam candles fechados de 1 dia, 4 horas e 1 hora.</footer>
    </main>
  </div>;
}
