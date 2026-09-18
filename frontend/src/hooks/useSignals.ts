import { useQuery, useQueryClient } from '@tanstack/react-query';
import { fetchSignals, fetchLatestSignals, type Signal, type SignalsResponse } from '@/lib/api';

export function useSignals(params?: {
  symbol?: string;
  ok?: boolean | null;
  side?: string;
  from_date?: string;
  to_date?: string;
  page?: number;
  page_size?: number;
}, enabled = true) {
  return useQuery<SignalsResponse, Error>({
    enabled,
    queryKey: ['signals', params],
    queryFn: () => fetchSignals(params),
    staleTime: 30_000, // 30 seconds
    refetchInterval: 60_000, // Refetch every minute
    retry: 2,
  });
}

export function useLatestSignals(symbol?: string, limit = 20) {
  return useQuery<Signal[], Error>({
    queryKey: ['signals', 'latest', symbol, limit],
    queryFn: () => fetchLatestSignals(symbol, limit),
    staleTime: 15_000,
    refetchInterval: 30_000,
    retry: 2,
  });
}

export function useSignalDetail(id: string) {
  return useQuery({
    queryKey: ['signals', 'detail', id],
    queryFn: () => import('@/lib/api').then(m => m.fetchSignalDetail(id)),
    enabled: !!id,
    staleTime: 60_000,
    retry: 1,
  });
}

export function useShadowPortfolio(params?: { symbol?: string; outcome?: string; limit?: number }) {
  return useQuery({
    queryKey: ['signals', 'shadow', params],
    queryFn: () => import('@/lib/api').then(m => m.fetchShadowPortfolio(params)),
    staleTime: 60_000,
    refetchInterval: 120_000,
  });
}

export function useShadowStats(days = 30) {
  return useQuery({
    queryKey: ['signals', 'shadow', 'stats', days],
    queryFn: () => import('@/lib/api').then(m => m.fetchShadowStats(days)),
    staleTime: 300_000, // 5 minutes
  });
}

// Prefetch helpers
export function prefetchSignals(queryClient: ReturnType<typeof useQueryClient>, params?: Parameters<typeof fetchSignals>[0]) {
  queryClient.prefetchQuery({
    queryKey: ['signals', params],
    queryFn: () => fetchSignals(params),
    staleTime: 30_000,
  });
}
