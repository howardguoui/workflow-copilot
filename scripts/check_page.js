// Drive the built demo (docs/) in headless Chromium with a stand-in WebLLM model to check the browser agent loop.
// Usage: (cd docs && python -m http.server 8000) & node scripts/check_page.js http://localhost:8000/   (needs: npm i playwright; PW_CHROMIUM=path to use an installed Chromium)
const { chromium } = require('playwright');
const FAKE = `
let n = 0;
export async function CreateMLCEngine(model, opts) {
  opts.initProgressCallback({ progress: 1, text: 'fake model ready' });
  return { chat: { completions: { create: async (req) => {
    n++;
    if (req.stream) { const words = 'It fits: 143,040 tokens of KV cache, 17 requests at 8,192 tokens. This is an estimate.'.split(' ');
      return (async function* () { for (const w of words) yield { choices: [{ delta: { content: w + ' ' } }] }; })(); }
    const schema = JSON.parse(req.response_format.schema);
    let out;
    if (schema.properties.action) out = { action: n === 1 ? 'plan_vllm' : 'answer' };
    else out = { model: 'qwen2.5-7b', gpu_gib: 15.92, weights_gib: 5.19, max_model_len: 8192, kv_cache_dtype: 'auto' };
    globalThis.__reqs = (globalThis.__reqs || []).concat([req]);
    return { choices: [{ message: { content: JSON.stringify(out) } }] };
  } } } };
}`;
(async () => {
  const b = await chromium.launch({ executablePath: process.env.PW_CHROMIUM || undefined });
  const p = await b.newPage({ viewport: { width: 1280, height: 900 } });
  const errs = []; p.on('pageerror', e => errs.push(e.message));
  await p.addInitScript(() => { Object.defineProperty(navigator, 'gpu', { value: {} }); });
  await p.route('https://esm.run/**', r => r.fulfill({ status: 200, contentType: 'application/javascript', body: FAKE }));
  await p.goto(process.argv[2] || 'http://localhost:8000/'); await p.waitForSelector('#compiled h3');
  // edit the note: add a rule and check the compiled agent updates
  await p.fill('#note-text', (await p.inputValue('#note-text')).replace('## Rules\n', '## Rules\n- Always answer in English.\n'));
  const hasRule = await p.$eval('#compiled pre', e => e.textContent.includes('- Always answer in English.'));
  await p.click('#load'); await p.waitForSelector('#q:not([disabled])');
  await p.click('#ex button'); await p.waitForFunction(() => document.querySelectorAll('.msg.bot').length && !document.querySelector('.msg.bot').textContent.includes('…'));
  await p.waitForTimeout(300);
  const log = await p.$eval('#log', e => e.innerText);
  
  await p.click('[data-mode=recorded]');
  const rec = await p.$eval('#recorded', e => e.innerText.slice(0, 600));
  console.log(JSON.stringify({ errs, hasRule, log, rec }, null, 1));
  await b.close();
})();
