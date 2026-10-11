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

export function publishedDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value)))
    throw new InvalidArgumentError('Expected an ISO 8601 date-time with timezone, e.g. 2026-01-01T00:00:00Z.');
  return value;
}

export async function search(query, options, key, fetcher = fetch) {
  if (!key) throw new Error('EXA_SEARCH_API_KEY is required. Set it in the environment or .env.');
  if (!query.trim()) throw new Error('Search query must not be empty.');
  if (options.startPublishedDate && options.endPublishedDate && Date.parse(options.startPublishedDate) > Date.parse(options.endPublishedDate))
    throw new Error('Start published date must not be after end published date.');
  const body = { query, numResults: options.count ?? 10, type: options.type ?? 'auto',
    moderation: options.moderation ?? false, contents: { highlights: true } };
  if (options.text) body.contents.text = { maxCharacters: options.textMaxChars ?? 10000 };
  for (const name of ['includeDomains', 'excludeDomains', 'startPublishedDate', 'endPublishedDate']) {
    if (options[name] !== undefined) body[name] = options[name];
  }
  let response;
  try {
    response = await fetcher('https://api.exa.ai/search', { method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'x-api-key': key },
      body: JSON.stringify(body), signal: AbortSignal.timeout(options.timeout ?? 30000) });
  } catch {
    // Do not leak credentials from transport exceptions or response bodies.
    throw new Error('Exa request failed (network error or timeout).');
  }
  if (!response.ok) {
    const retry = response.headers.get('retry-after');
    const safeRetry = retry && /^\d+$/.test(retry) ? `; retry after ${retry} seconds` : '';
    throw new Error(`Exa HTTP ${response.status}${safeRetry}.`);
  }
  let data;
  try { data = await response.json(); } catch { throw new Error('Exa returned invalid JSON.'); }
  if (!Array.isArray(data?.results)) throw new Error('Exa returned an invalid search response (missing results array).');
  if (options.raw) return data;
  return { query, requestId: data.requestId ?? null, costDollars: data.costDollars ?? null,
    results: data.results.map(r => ({ title: r.title ?? null, url: r.url,
      publishedDate: r.publishedDate ?? null, author: r.author ?? null,
      highlights: r.highlights ?? [], ...(r.text !== undefined ? { text: r.text } : {}) })) };
}

const append = (value, previous = []) => [...previous, value];
export async function main(argv = process.argv) {
  const program = new Command().name('exa-search').description('Search the web through Exa; JSON on stdout.')
    .option('--env-file <path>', 'dotenv file (environment takes precedence)', '.env')
    .option('--pretty', 'indent JSON');
  program.command('search').argument('<query>', 'search query')
    .option('--count <n>', 'number of results (1–100; no offset pagination)', integer(1, 100), 10)
    .addOption(new Option('--type <mode>', 'search mode').choices(['auto', 'fast', 'instant']).default('auto'))
    .option('--include-domain <domain>', 'only this domain/path (repeatable)', append)
    .option('--exclude-domain <domain>', 'exclude this domain/path (repeatable)', append)
    .option('--start-published-date <date>', 'published after ISO 8601 date-time', publishedDate)
    .option('--end-published-date <date>', 'published before ISO 8601 date-time', publishedDate)
    .option('--moderation', 'filter unsafe content', false)
    .option('--text', 'also retrieve page text', false)
    .option('--text-max-chars <n>', 'text cap per result (requires --text)', integer(1, 1000000), 10000)
    .option('--timeout <ms>', 'HTTP timeout', integer(1, 300000), 30000)
    .option('--raw', 'return the complete Exa response')
    .action(async (query, opts, command) => {
      if (!opts.text && command.getOptionValueSource('textMaxChars') === 'cli')
        throw new Error('--text-max-chars requires --text.');
      config({ path: program.opts().envFile, quiet: true });
      const result = await search(query, { ...opts, includeDomains: opts.includeDomain,
        excludeDomains: opts.excludeDomain }, process.env.EXA_SEARCH_API_KEY);
      console.log(JSON.stringify(result, null, program.opts().pretty ? 2 : undefined));
    });
  program.command('auth').command('status').description('Check configuration, not credential validity')
    .action(() => {
      config({ path: program.opts().envFile, quiet: true });
      console.log(JSON.stringify({ configured: Boolean(process.env.EXA_SEARCH_API_KEY) }));
    });
  await program.parseAsync(argv);
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => { console.error(`Error: ${error.message}`); process.exitCode = 1; });
}
