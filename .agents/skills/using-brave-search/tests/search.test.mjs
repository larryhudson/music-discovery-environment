import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { search, integer } from '../scripts/brave-search.mjs';
const defaults = { count: 10, offset: 0, country: 'ALL', language: 'en', safesearch: 'moderate', timeout: 1000 };

test('request uses fixed Brave endpoint, header auth, and page offset; normalizes results', async () => {
  const result = await search('music & reviews', { ...defaults, offset: 1, freshness: 'pw' }, 'test-secret', async (url, options) => {
    assert.equal(url.origin, 'https://api.search.brave.com');
    assert.equal(url.pathname, '/res/v1/web/search');
    assert.equal(url.searchParams.get('q'), 'music & reviews');
    assert.equal(url.searchParams.get('offset'), '1');
    assert.equal(url.searchParams.get('freshness'), 'pw');
    assert.equal(options.headers['X-Subscription-Token'], 'test-secret');
    assert.ok(!url.href.includes('test-secret'));
    return new Response(JSON.stringify({ query: { more_results_available: true }, web: { results: [{ title: 'Review', url: 'https://example.com', description: 'Snippet' }] } }));
  });
  assert.equal(result.more_results_available, true);
  assert.equal(result.results[0].title, 'Review');
  assert.deepEqual(result.results[0].extra_snippets, []);
});
test('raw and empty results', async () => {
  const fetcher = async () => new Response('{"query":{}}');
  assert.deepEqual((await search('q', defaults, 'key', fetcher)).results, []);
  assert.deepEqual(await search('q', { ...defaults, raw: true }, 'key', fetcher), { query: {} });
});
test('missing key, rate limiting, invalid JSON, and network errors', async () => {
  await assert.rejects(search('q', defaults, ''), /BRAVE_SEARCH_API_KEY/);
  await assert.rejects(search('q', defaults, 'key', async () => new Response('', { status: 429, headers: { 'retry-after': '10' } })), /429; retry after 10/);
  await assert.rejects(search('q', defaults, 'key', async () => new Response('invalid')), /invalid JSON/);
  await assert.rejects(search('q', defaults, 'secret', async () => { throw new Error('secret'); }), /network error or timeout/);
});
test('integer validation and CLI usage errors', () => {
  assert.equal(integer(0, 9)('1'), 1);
  for (const value of ['-1', '10', '1.5', 'abc']) assert.throws(() => integer(0, 9)(value));
  const cli = new URL('../scripts/brave-search.mjs', import.meta.url);
  const result = spawnSync(process.execPath, [cli.pathname, 'search', 'q', '--offset', '10'], { encoding: 'utf8' });
  assert.equal(result.status, 1); // Commander defaults to exit 1 for usage errors.
  assert.equal(result.stdout, '');
});
