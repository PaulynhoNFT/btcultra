import { test } from 'node:test';
import assert from 'node:assert/strict';
import { allowedOrigin } from '../src/lib/proxy';
test('accepts the actual Host for both local addresses, regardless of Next URL normalization', () => {
  assert.equal(allowedOrigin('http://127.0.0.1:3000', '127.0.0.1:3000'), true);
  assert.equal(allowedOrigin('http://localhost:3000', 'localhost:3000'), true);
});
test('rejects missing, cross-origin, external and lookalike origins', () => {
  for (const origin of [null, 'https://example.com', 'http://localhost:4000', 'http://127.0.0.1:3000.evil.com']) {
    assert.equal(allowedOrigin(origin, '127.0.0.1:3000'), false);
  }
  assert.equal(allowedOrigin('http://localhost:3000', '127.0.0.1:3000'), false);
});
