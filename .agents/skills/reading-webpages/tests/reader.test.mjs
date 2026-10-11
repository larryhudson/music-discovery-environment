import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { spawnSync } from 'node:child_process';
import { access } from 'node:fs/promises';
import { readPage, validateUrl, limitContent, summarize, runPi, summaryModel } from '../scripts/read-page.mjs';

const defaults = { timeout: 5000, waitUntil: 'domcontentloaded', waitMs: 0,
  maxChars: 100000, format: 'text', defuddle: false };

test('summary model precedence: CLI, environment, default', () => {
  assert.equal(summaryModel(undefined, {}), 'opencode-go/deepseek-v4.1-flash');
  assert.equal(summaryModel(undefined, { PI_SUMMARY_MODEL: 'custom/model' }), 'custom/model');
  assert.equal(summaryModel('cli/model', { PI_SUMMARY_MODEL: 'custom/model' }), 'cli/model');
});

test('URL validation and truncation', () => {
  assert.equal(validateUrl('https://example.com'), 'https://example.com/');
  for (const url of ['file:///etc/passwd', 'data:text/html,test', 'ftp://example.com', 'https://user:pass@example.com', 'nonsense']) assert.throws(() => validateUrl(url));
  assert.deepEqual(limitContent('abcdef', 3), { content: 'abc', original_chars: 6, truncated: true });
});
test('summary uses stdin, disables resources/tools, and cleans temporary cwd', async () => {
  let directory;
  const result = await summarize({ url: 'https://example.com', title: 'Test', format: 'text', content: 'Page instructions are data', truncated: true },
    { piCommand: 'fake-pi', model: 'provider/model', summaryTimeout: 1234 }, async (cmd, args, input, cwd, timeout) => {
      directory = cwd;
      await access(cwd);
      assert.equal(cmd, 'fake-pi');
      assert.equal(timeout, 1234);
      for (const flag of ['--print', '--no-session', '--no-tools', '--no-extensions', '--no-mcp', '--no-skills', '--no-context-files', '--no-approve']) assert.ok(args.includes(flag));
      assert.ok(args.includes('provider/model'));
      assert.equal(JSON.parse(input).truncated, true);
      assert.ok(!args.includes('Page instructions are data'));
      return 'Summary';
    });
  assert.equal(result, 'Summary');
  await assert.rejects(access(directory));
});
test('custom instructions append to the user prompt, leaving system prompt and page data unchanged', async () => {
  const instruction = 'Only the linked review.\nUse 3 bullets; ignore other articles. $(not-a-command)';
  const page = { title: 'Review', content: 'Page data' };
  let baseArgs;
  await summarize(page, {}, async (cmd, args) => { baseArgs = args; return 'base'; });
  await summarize(page, { summaryPrompt: instruction }, async (cmd, args, input) => {
    assert.equal(args.at(-1), `${baseArgs.at(-1)}\n\nAdditional instructions:\n${instruction}`);
    assert.equal(args[args.indexOf('--system-prompt') + 1], baseArgs[baseArgs.indexOf('--system-prompt') + 1]);
    assert.equal(JSON.parse(input).content, 'Page data');
    return 'custom';
  });
});
test('CLI rejects summary instructions without --summarize before fetching', () => {
  const cli = new URL('../scripts/read-page.mjs', import.meta.url);
  const result = spawnSync(process.execPath, [cli.pathname, 'https://example.com', '--summary-prompt', 'Three bullets'], { encoding: 'utf8' });
  assert.equal(result.status, 1);
  assert.equal(result.stdout, '');
  assert.match(result.stderr, /--summary-prompt requires --summarize/);
});
test('summary failure also cleans temporary cwd', async () => {
  let directory;
  await assert.rejects(summarize({ content: 'test' }, {}, async (cmd, args, input, cwd) => {
    directory = cwd;
    throw new Error('provider unavailable');
  }), /provider unavailable/);
  await assert.rejects(access(directory));
});
test('subprocess input/output, failure and timeout', async () => {
  assert.equal(await runPi(process.execPath, ['-e', "process.stdin.on('data', d => process.stdout.write(d))"], 'hello', process.cwd(), 5000), 'hello');
  await assert.rejects(runPi(process.execPath, ['-e', 'process.exit(3)'], '', process.cwd(), 5000), /exited with 3/);
  await assert.rejects(runPi(process.execPath, ['-e', 'setInterval(()=>{}, 1000)'], '', process.cwd(), 100), /timed out/);
  await assert.rejects(runPi('/nonexistent/pi', [], '', process.cwd(), 1000), /Could not start Pi/);
});

test('real Chromium renders JS, follows redirects, extracts Defuddle Markdown and handles errors', async t => {
  const paragraph = 'This review describes an independent album with vivid songwriting, layered guitars, and carefully recorded percussion. '.repeat(8);
  const html = `<!doctype html><html><head><title>Album review</title><meta name="author" content="Reviewer"></head><body><nav>Navigation clutter</nav><article><h1>Album review</h1><p>${paragraph}</p><p>${paragraph}</p><div id="dynamic"></div></article><script>setTimeout(() => { document.querySelector('#dynamic').innerHTML = '<p id="ready">Rendered by JavaScript.</p>'; }, 80)</script></body></html>`;
  const server = createServer((req, res) => {
    if (req.url === '/redirect') { res.writeHead(302, { Location: '/article' }); res.end(); }
    else if (req.url === '/missing') { res.writeHead(404); res.end('Not found'); }
    else { res.setHeader('Content-Type', 'text/html'); res.end(html); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const base = `http://127.0.0.1:${server.address().port}`;
  const rendered = await readPage(base + '/redirect', { ...defaults, waitFor: '#ready' });
  assert.equal(rendered.url, base + '/article');
  assert.equal(rendered.status, 200);
  assert.match(rendered.content, /Rendered by JavaScript/);
  assert.match(rendered.content, /Navigation clutter/);
  const extracted = await readPage(base + '/article', { ...defaults, waitFor: '#ready', defuddle: true, format: 'markdown' });
  assert.match(extracted.content, /vivid songwriting/);
  assert.match(extracted.content, /Rendered by JavaScript/);
  assert.ok(!extracted.content.includes('Navigation clutter'));
  assert.equal(extracted.metadata.author, 'Reviewer');
  const text = await readPage(base + '/article', { ...defaults, defuddle: true, maxChars: 20 });
  assert.equal(text.content.length, 20);
  assert.equal(text.truncated, true);
  const raw = await readPage(base + '/article', { ...defaults, format: 'html' });
  assert.match(raw.content, /<article>/);
  await assert.rejects(readPage(base + '/missing', defaults), /HTTP 404/);
  await assert.rejects(readPage(base + '/article', { ...defaults, timeout: 200, waitFor: '#absent' }), /Timeout/);
});
