import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { search, integer, publishedDate } from '../scripts/exa-search.mjs';
const defaults = { count: 10, type: 'auto', timeout: 1000 };
const cli = new URL('../scripts/exa-search.mjs', import.meta.url).pathname;
const run = (args, env = process.env) => spawnSync(process.execPath, [cli, ...args], { encoding: 'utf8', env });

test('fixed endpoint, POST JSON, header auth, filters and normalized results', async () => {
  const result = await search('music & reviews', { ...defaults, includeDomains: ['post-trash.com', 'pitchfork.com'],
    excludeDomains: ['example.org'], startPublishedDate: '2026-01-01T00:00:00Z', endPublishedDate: '2026-02-01T00:00:00Z', moderation: true }, 'test-secret', async (url, options) => {
    assert.equal(url, 'https://api.exa.ai/search');
    assert.equal(options.method, 'POST');
    assert.equal(options.headers['x-api-key'], 'test-secret');
    assert.equal(options.headers['Content-Type'], 'application/json');
    assert.ok(!url.includes('test-secret'));
    assert.ok(options.signal instanceof AbortSignal);
    assert.deepEqual(JSON.parse(options.body), { query: 'music & reviews', numResults: 10, type: 'auto',
      moderation: true, contents: { highlights: true }, includeDomains: ['post-trash.com', 'pitchfork.com'],
      excludeDomains: ['example.org'], startPublishedDate: '2026-01-01T00:00:00Z', endPublishedDate: '2026-02-01T00:00:00Z' });
    return Response.json({ requestId: 'req', costDollars: { total: 0.01 }, results: [{ title: 'Review', url: 'https://example.com', highlights: ['Snippet'] }] });
  });
  assert.deepEqual(result, { query: 'music & reviews', requestId: 'req', costDollars: { total: 0.01 },
    results: [{ title: 'Review', url: 'https://example.com', publishedDate: null, author: null, highlights: ['Snippet'] }] });
});
test('text cap, fast mode, raw and empty results', async () => {
  const data = { results: [{ url: 'https://example.com', text: 'Page', author: 'Author', publishedDate: '2026-01-01' }], extra: true };
  const fetcher = async (_, opts) => {
    assert.deepEqual(JSON.parse(opts.body).contents, { highlights: true, text: { maxCharacters: 5000 } });
    assert.equal(JSON.parse(opts.body).type, 'fast');
    return Response.json(data);
  };
  const opts = { ...defaults, type: 'fast', text: true, textMaxChars: 5000 };
  assert.deepEqual(await search('q', { ...opts, raw: true }, 'key', fetcher), data);
  const result = await search('q', opts, 'key', fetcher);
  assert.equal(result.results[0].text, 'Page');
  assert.deepEqual(result.results[0].highlights, []);
  assert.deepEqual((await search('q', defaults, 'key', async () => Response.json({ results: [] }))).results, []);
});
test('missing key, invalid query/date order, HTTP errors, invalid responses, and network errors', async () => {
  await assert.rejects(search('q', defaults, ''), /EXA_SEARCH_API_KEY/);
  await assert.rejects(search('  ', defaults, 'key'), /empty/);
  await assert.rejects(search('q', { ...defaults, startPublishedDate: '2026-02-01T00:00:00Z', endPublishedDate: '2026-01-01T00:00:00Z' }, 'key'), /must not be after/);
  for (const status of [401, 403, 429, 500]) {
    await assert.rejects(search('q', defaults, 'secret', async () => new Response('secret', { status, headers: { 'retry-after': '10' } })), new RegExp(`${status}; retry after 10 seconds`));
  }
  await assert.rejects(search('q', defaults, 'key', async () => new Response('invalid')), /invalid JSON/);
  await assert.rejects(search('q', defaults, 'key', async () => Response.json({})), /missing results array/);
  await assert.rejects(search('q', defaults, 'secret', async () => { throw new Error('secret'); }), /^Error: Exa request failed \(network error or timeout\)\.$/);
});
test('integer/date validation and CLI usage errors (including removed Brave flags)', () => {
  assert.equal(integer(1, 100)('100'), 100);
  for (const value of ['0', '-1', '101', '1.5', 'abc']) assert.throws(() => integer(1, 100)(value));
  assert.equal(publishedDate('2026-01-01T00:00:00Z'), '2026-01-01T00:00:00Z');
  for (const value of ['yesterday', '2026-01-01', '2026-13-01T00:00:00Z']) assert.throws(() => publishedDate(value));
  for (const args of [['--count', '101'], ['--offset', '1'], ['--type', 'neural'], ['--start-published-date', 'bad'], ['--text-max-chars', '500']]) {
    const result = run(['search', 'q', ...args]);
    assert.equal(result.status, 1);
    assert.equal(result.stdout, '');
  }
  assert.equal(run(['--help']).status, 0);
  assert.equal(run(['search', '--help']).status, 0);
});
test('auth status only reports presence; dotenv loaded and environment wins', () => {
  const dir = mkdtempSync(join(tmpdir(), 'exa-search-test-'));
  try {
    const file = join(dir, '.env');
    writeFileSync(file, 'EXA_SEARCH_API_KEY=file-secret\n');
    const env = { ...process.env };
    delete env.EXA_SEARCH_API_KEY;
    const configured = run(['--env-file', file, 'auth', 'status'], env);
    assert.equal(configured.status, 0);
    assert.deepEqual(JSON.parse(configured.stdout), { configured: true });
    assert.equal(configured.stderr, '');
    const emptyOverride = run(['--env-file', file, 'auth', 'status'], { ...env, EXA_SEARCH_API_KEY: '' });
    assert.deepEqual(JSON.parse(emptyOverride.stdout), { configured: false });
    const emptyFile = join(dir, 'empty.env');
    writeFileSync(emptyFile, '');
    const missing = run(['--env-file', emptyFile, 'search', 'q'], env);
    assert.equal(missing.status, 1);
    assert.equal(missing.stdout, '');
    assert.match(missing.stderr, /EXA_SEARCH_API_KEY is required/);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
