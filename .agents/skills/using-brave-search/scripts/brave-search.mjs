#!/usr/bin/env node
import { Command, Option, InvalidArgumentError } from 'commander';
import { config } from 'dotenv';
import { pathToFileURL } from 'node:url';

export function integer(min, max) {
  return value => {
    const n = Number(value);
    if (!/^\d+$/.test(value) || !Number.isSafeInteger(n) || n < min || n > max)
      throw new InvalidArgumentError(`Expected an integer from ${min} to ${max}.`);
    return n;
  };
}

export async function search(query, options, key, fetcher = fetch) {
  if (!key) throw new Error('BRAVE_SEARCH_API_KEY is required. Set it in the environment or .env.');
  const url = new URL('https://api.search.brave.com/res/v1/web/search');
  const params = { q: query, count: options.count, offset: options.offset,
    country: options.country, search_lang: options.language, safesearch: options.safesearch,
    extra_snippets: 'true' };
  if (options.freshness) params.freshness = options.freshness;
  for (const [name, value] of Object.entries(params)) url.searchParams.set(name, String(value));
  let response;
  try {
    response = await fetcher(url, { headers: { Accept: 'application/json',
      'X-Subscription-Token': key }, signal: AbortSignal.timeout(options.timeout) });
  } catch {
    throw new Error('Brave request failed (network error or timeout).');
  }
  if (!response.ok) {
    const retry = response.headers.get('retry-after');
    throw new Error(`Brave HTTP ${response.status}${retry ? `; retry after ${retry}` : ''}.`);
  }
  let data;
  try { data = await response.json(); } catch { throw new Error('Brave returned invalid JSON.'); }
  if (options.raw) return data;
  return { query, offset: options.offset, more_results_available: data.query?.more_results_available ?? false,
    results: (data.web?.results ?? []).map(r => ({ title: r.title, url: r.url,
      description: r.description, extra_snippets: r.extra_snippets ?? [], age: r.age ?? null })) };
}

export async function main(argv = process.argv) {
  const program = new Command().name('brave-search').description('Search the web through Brave; JSON on stdout.')
    .option('--env-file <path>', 'dotenv file (environment takes precedence)', '.env')
    .option('--pretty', 'indent JSON');
  program.command('search').argument('<query>', 'search query')
    .option('--count <n>', 'results per page (1–20)', integer(1, 20), 10)
    .option('--offset <n>', 'page offset (0–9), not a result offset', integer(0, 9), 0)
    .option('--country <code>', 'country code or ALL', 'ALL')
    .option('--language <code>', 'Brave search language code', 'en')
    .addOption(new Option('--safesearch <level>', 'content filter').choices(['off', 'moderate', 'strict']).default('moderate'))
    .option('--freshness <range>', 'pd, pw, pm, py, or YYYY-MM-DDtoYYYY-MM-DD')
    .option('--timeout <ms>', 'HTTP timeout', integer(1, 300000), 30000)
    .option('--raw', 'return the complete Brave response')
    .action(async (query, opts) => {
      config({ path: program.opts().envFile, quiet: true });
      const result = await search(query, opts, process.env.BRAVE_SEARCH_API_KEY);
      console.log(JSON.stringify(result, null, program.opts().pretty ? 2 : undefined));
    });
  program.command('auth').command('status').description('Check configuration, not credential validity')
    .action(() => {
      config({ path: program.opts().envFile, quiet: true });
      console.log(JSON.stringify({ configured: Boolean(process.env.BRAVE_SEARCH_API_KEY) }));
    });
  await program.parseAsync(argv);
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => { console.error(`Error: ${error.message}`); process.exitCode = 1; });
}
