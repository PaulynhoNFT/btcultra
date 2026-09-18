export function allowedOrigin(origin: string | null, host: string | null): boolean {
  return origin !== null && ['http://localhost:3000', 'http://127.0.0.1:3000'].includes(origin) && origin === `http://${host}`;
}
