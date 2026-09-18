import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';

export const api = axios.create({
  baseURL: API_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 10000,
});

// Token management
let accessToken: string | null = null;
let refreshToken: string | null = null;

export function setTokens(access: string, refresh: string) {
  accessToken = access;
  refreshToken = refresh;
  if (typeof window !== 'undefined') {
    localStorage.setItem('access_token', access);
    localStorage.setItem('refresh_token', refresh);
  }
}

export function getAccessToken(): string | null {
  if (accessToken) return accessToken;
  if (typeof window !== 'undefined') {
    return localStorage.getItem('access_token');
  }
  return null;
}

export function getRefreshToken(): string | null {
  if (refreshToken) return refreshToken;
  if (typeof window !== 'undefined') {
    return localStorage.getItem('refresh_token');
  }
  return null;
}

export function clearTokens() {
  accessToken = null;
  refreshToken = null;
  if (typeof window !== 'undefined') {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
  }
}

// Request interceptor - add auth header
api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = getAccessToken();
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor - handle 401 with token refresh
let isRefreshing = false;
let failedQueue: Array<{ resolve: (value: any) => void; reject: (reason: any) => void }> = [];

const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach(prom => {
    if (error) prom.reject(error);
    else prom.resolve(token);
  });
  failedQueue = [];
};

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        }).then(token => {
          if (originalRequest.headers) {
            originalRequest.headers.Authorization = `Bearer ${token}`;
          }
          return api(originalRequest);
        }).catch(err => Promise.reject(err));
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        const refresh = getRefreshToken();
        if (!refresh) throw new Error('No refresh token');

        const response = await axios.post(`${API_URL}/auth/refresh`, { refresh_token: refresh });
        const { access_token, refresh_token } = response.data;
        setTokens(access_token, refresh_token);
        processQueue(null, access_token);

        if (originalRequest.headers) {
          originalRequest.headers.Authorization = `Bearer ${access_token}`;
        }
        return api(originalRequest);
      } catch (err) {
        processQueue(err, null);
        clearTokens();
        if (typeof window !== 'undefined') {
          window.location.href = '/login';
        }
        return Promise.reject(err);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  }
);

// ============================================================
// API Functions
// ============================================================
export interface Signal {
  id: string;
  timestamp: string;
  symbol: string;
  timeframe: string;
  side: 'BUY' | 'SELL';
  score: number;
  reason: string;
  ok: boolean;
  entry_price: number;
  stop_price: number;
  tp1: number;
  tp2: number;
  tp3: number;
  rr: number;
  mode: 'swing' | 'scalp';
  engine_version: string;
  score_version: string;
  risk_version: string;
  snapshot_hash: string;
  created_at: string;
}

export interface SignalsResponse {
  signals: Signal[];
  total: number;
  page: number;
  page_size: number;
}

export interface RegimeData {
  symbol: string;
  timeframe: string;
  state: string;
  adx: number;
  bbw_pct: number;
  atr_pct: number;
  hmm_bull_prob?: number;
  hmm_bear_prob?: number;
  hmm_chop_prob?: number;
  ok_to_trade: boolean;
  reason: string;
  timestamp: string;
}

export async function fetchSignals(params?: {
  symbol?: string;
  ok?: boolean | null;
  side?: string;
  from_date?: string;
  to_date?: string;
  page?: number;
  page_size?: number;
}): Promise<SignalsResponse> {
  const response = await api.get('/signals', { params });
  return response.data;
}

export async function fetchLatestSignals(symbol?: string, limit = 20): Promise<Signal[]> {
  const response = await api.get('/signals/latest', { params: { symbol, limit } });
  return response.data;
}

export async function fetchSignalDetail(id: string): Promise<Signal & { snapshot: any; breakdown: any }> {
  const response = await api.get(`/signals/${id}`);
  return response.data;
}

export async function fetchRegime(symbol = 'BTC/USDT', timeframe = '4h'): Promise<RegimeData> {
  const response = await api.get('/regime', { params: { symbol, timeframe } });
  return response.data;
}

export async function fetchShadowPortfolio(params?: {
  symbol?: string;
  outcome?: string;
  limit?: number;
}): Promise<any[]> {
  const response = await api.get('/signals/shadow/portfolio', { params });
  return response.data;
}

export async function fetchShadowStats(days = 30): Promise<any> {
  const response = await api.get('/signals/shadow/stats', { params: { days } });
  return response.data;
}

// Auth
export async function login(email: string, password: string, totp_code?: string) {
  const response = await api.post('/auth/login', { email, password, totp_code });
  setTokens(response.data.access_token, response.data.refresh_token);
  return response.data;
}

export async function register(email: string, password: string) {
  const response = await api.post('/auth/register', { email, password });
  setTokens(response.data.access_token, response.data.refresh_token);
  return response.data;
}

export async function logout() {
  const refresh = getRefreshToken();
  if (refresh) {
    await api.post('/auth/logout', { refresh_token: refresh }).catch(() => {});
  }
  clearTokens();
}

export async function getCurrentUser() {
  const response = await api.get('/auth/me');
  return response.data;
}

// WebSocket
export function createSignalWS(onMessage: (data: any) => void, onError?: (err: Event) => void) {
  const token = getAccessToken();
  const ws = new WebSocket(`${WS_URL}/ws/signals?token=${token}`);

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onMessage(data);
    } catch (e) {
      console.error('WS parse error', e);
    }
  };

  ws.onerror = (err) => {
    console.error('WS error', err);
    onError?.(err);
  };

  ws.onclose = () => {
    // Reconnect after 5s
    setTimeout(() => createSignalWS(onMessage, onError), 5000);
  };

  return ws;
}
