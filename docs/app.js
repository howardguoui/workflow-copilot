// Workflow Copilot demo: compile the note in the page, chat with it through WebLLM, show recorded runs.
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const { compileNote, splitFrontmatter } = window.NoteCompiler;
const Tools = window.CopilotTools;
const WEBLLM = 'https://esm.run/@mlc-ai/web-llm@0.2.85';

const state = { manifest: null, filings: null, transcripts: { chats: [] }, files: {}, toolNotes: {}, bodies: {},
  workflowPath: null, compiled: null, error: null, engine: null, busy: false, history: [] };

async function getText(path) { const r = await fetch(path); if (!r.ok) throw new Error(`${path}: ${r.status}`); return r.text(); }

async function init() {
  state.manifest = await (await fetch('manifest.json')).json();
  state.filings = await (await fetch('filings_answers.json')).json();
  state.transcripts = await (await fetch('transcripts.json')).json().catch(() => ({ chats: [] }));
  await Promise.all(state.manifest.notes.map(async (p) => { state.files[p] = await getText('vault/' + encodeURI(p)); }));
  for (const [p, text] of Object.entries(state.files)) {
    const title = p.split('/').pop().replace(/\.md$/, '');
    if (p.startsWith('Tools/')) state.toolNotes[title] = text;
    state.bodies[title] = splitFrontmatter(text)[1];
  }
  $('#wf-tabs').innerHTML = state.manifest.workflows.map((p, i) =>
    `<button type="button" data-wf="${esc(p)}" aria-pressed="${i === 0}">${esc(p.replace(/\.md$/, ''))}</button>`).join('');
  document.querySelectorAll('[data-wf]').forEach((b) => b.addEventListener('click', () => selectWorkflow(b.dataset.wf)));
  $('#note-text').addEventListener('input', () => { recompile(); });
  selectWorkflow(state.manifest.workflows[0]);
  setupModes();
  setupLive();
}

function selectWorkflow(path) {
  state.workflowPath = path;
  document.querySelectorAll('[data-wf]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.wf === path)));
  $('#note-text').value = state.files[path];
  state.history = [];
  $('#log').innerHTML = '';
  recompile();
  renderRecorded();
}

function recompile() {
  try {
    state.compiled = compileNote($('#note-text').value, state.toolNotes);
    state.error = null;
  } catch (e) { state.error = e.message; }
  const box = $('#compiled');
  if (state.error) { box.innerHTML = `<p class="err">${esc(state.error)}</p>`; return; }
  const c = state.compiled, wf = c.workflow;
  const known = ['plan_vllm', 'read_note', 'search_filings'];
  const unknown = wf.tools.filter((t) => !known.includes(t));
  box.innerHTML = `<h3>${esc(wf.name)}</h3><div class="chips">${wf.tools.map((t) => `<span class="chip tool">tool: ${esc(t)}</span>`).join('')}
      ${wf.notes.map((n) => `<span class="chip">note: ${esc(n)}</span>`).join('')}</div>
    ${unknown.length ? `<p class="err">No such tool in this runtime: ${unknown.map(esc).join(', ')}</p>` : ''}
    <span class="muted">System instructions</span><pre>${esc(c.instructions)}</pre>`;
  $('#ex').innerHTML = wf.examples.map((e) => `<button type="button">${esc(e)}</button>`).join('') || '<span class="muted">Add an ## Examples list to the note.</span>';
  $('#ex').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    $('#q').value = b.textContent;
    if (state.engine && !state.busy) $('#ask').requestSubmit();
  }));
}

function setupModes() {
  document.querySelectorAll('[data-mode]').forEach((b) => b.addEventListener('click', () => {
    document.querySelectorAll('[data-mode]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    $('#live').hidden = b.dataset.mode !== 'live';
    $('#recorded').hidden = b.dataset.mode !== 'recorded';
  }));
}

function fmtResult(r) {
  if (r.error) return `error: ${r.error}`;
  if ('kv_tokens' in r) return `${r.kv_tokens.toLocaleString()} tokens of KV cache, ${r.max_concurrent_at_max_len} requests at ${r.max_model_len.toLocaleString()} tokens, fits: ${r.fits}`;
  if ('found' in r) return r.found ? `matched "${r.matched_question}" (${(r.sources || []).length} sources)` : 'no recorded answer matches';
  if ('text' in r) return `read "${r.title}" (${r.text.length} chars)`;
  return JSON.stringify(r).slice(0, 160);
}

function renderRecorded() {
  const t = state.transcripts, name = state.compiled ? state.compiled.workflow.name : '';
  const chats = (t.chats || []).filter((c) => c.workflow === name);
  if (!chats.length) { $('#recorded').innerHTML = '<p class="muted">No recorded runs for this workflow yet.</p>'; return; }
  $('#recorded').innerHTML = `<p class="lead">Recorded ${esc(t.recorded_at)} with ${esc(t.runtime)} and ${esc(t.model)} (Ollama, RTX 5070 Ti):
    the full Python runtime answering the note's examples. Real runs, unedited.</p>` + chats.map((c) => `<article>
      <div class="msg user">${esc(c.question)}</div>
      ${c.calls.map((k) => `<div class="call">${esc(k.tool)}(${esc(JSON.stringify(k.arguments))})\n→ ${esc(fmtResult(k.result))}</div>`).join('')}
      <div class="msg bot">${esc(c.answer)}</div></article>`).join('');
}

// ---- live bot ----
function setupLive() {
  if (!navigator.gpu) {
    $('#live-note').innerHTML = 'This browser has no WebGPU, so the live bot cannot run here (most phones, Safari before 26, Firefox). ' +
      'The <b>Recorded</b> tab shows the full runtime answering the same examples.';
    $('#load').disabled = true;
  }
  $('#load').addEventListener('click', loadModel);
  $('#ask').addEventListener('submit', (e) => { e.preventDefault(); const q = $('#q').value.trim(); if (q) { $('#q').value = ''; turn(q); } });
}

async function loadModel() {
  $('#load').disabled = true;
  $('#prog').hidden = false;
  try {
    const webllm = await import(WEBLLM);
    state.engine = await webllm.CreateMLCEngine($('#model').value, {
      initProgressCallback: (p) => { $('#prog span').style.width = `${Math.round((p.progress || 0) * 100)}%`; $('#load-status').textContent = p.text; },
    });
    $('#load-status').textContent = `Loaded ${$('#model').selectedOptions[0].text.split(' (')[0]}. Ask away.`;
    $('#prog').hidden = true;
    $('#q').disabled = false; $('#send').disabled = false; $('#q').focus();
  } catch (e) {
    $('#load-status').innerHTML = `<span class="err">Could not load the model: ${esc(e.message)}</span>`;
    $('#load').disabled = false;
  }
}

function add(cls, html) { const d = document.createElement('div'); d.className = cls; d.innerHTML = html; $('#log').appendChild(d); $('#log').scrollTop = 1e9; return d; }

function toolSchema(name, wf) {
  if (name === 'plan_vllm') return { type: 'object', properties: {
    model: { type: 'string', enum: state.manifest.models }, gpu_gib: { type: 'number' }, weights_gib: { type: 'number' },
    max_model_len: { type: 'integer' }, kv_cache_dtype: { type: 'string', enum: ['auto', 'fp8'] } },
    required: ['model', 'gpu_gib', 'weights_gib', 'max_model_len', 'kv_cache_dtype'] };
  if (name === 'read_note') return { type: 'object', properties: { title: { type: 'string', enum: wf.notes.length ? wf.notes : [''] } }, required: ['title'] };
  return { type: 'object', properties: { question: { type: 'string' } }, required: ['question'] };
}

function runTool(name, args) {
  const wf = state.compiled.workflow;
  if (name === 'plan_vllm') return Tools.planVllm(state.manifest.planner, args);
  if (name === 'read_note') return Tools.readNote(state.bodies, wf.notes, args.title);
  if (name === 'search_filings') return Tools.searchFilings(state.filings, args.question);
  return { error: `unknown tool ${name}` };
}

async function json(messages, schema) {
  // Constrained decoding can run into whitespace until max_tokens and leave the JSON unfinished; retry once.
  let last;
  for (let attempt = 0; attempt < 2; attempt++) {
    const r = await state.engine.chat.completions.create({ temperature: attempt ? 0.3 : 0, max_tokens: 300,
      messages: attempt ? [...messages, { role: 'user', content: 'Reply with compact JSON on one line.' }] : messages,
      response_format: { type: 'json_object', schema: JSON.stringify(schema) } });
    try { return JSON.parse(r.choices[0].message.content); } catch (e) { last = e; }
  }
  throw new Error(`The model did not return valid JSON (${last.message}). Try again or pick a larger model.`);
}

async function turn(question) {
  if (state.busy || state.error) return;
  state.busy = true; $('#send').disabled = true;
  const c = state.compiled, wf = c.workflow, tools = wf.tools.filter((t) => ['plan_vllm', 'read_note', 'search_filings'].includes(t));
  add('msg user', esc(question));
  const convo = [...state.history, { role: 'user', content: question }];
  const calls = [];
  // Tool results go into the system prompt, not into the chat as fake assistant turns: small models copy such
  // turns into their answers ("Calling plan_vllm again...") instead of acting on them.
  const results = () => calls.length ? '\n\nTool results so far for the latest message:\n' +
    calls.map((k) => `- ${k.tool}(${JSON.stringify(k.arguments)}) returned ${JSON.stringify(k.result)}`).join('\n') : '';
  try {
    for (let i = 0; i < 3 && tools.length; i++) {
      // Small models tend to answer from memory, so the first action is always one of the note's tools;
      // "answer" becomes an option once there is a tool result to answer from.
      const options = i === 0 ? tools : [...tools, 'answer'];
      const ask = i === 0 ? 'Which of the tools do the steps say to use for the latest user message?'
        : 'Read the steps again and the tool results above. If a step calls for another tool call given those results ' +
          '(for example a different argument), choose that tool; otherwise choose "answer".';
      const decide = await json([{ role: 'system', content: `${c.instructions}${results()}\n\n${ask}` }, ...convo],
        { type: 'object', properties: { action: { type: 'string', enum: options } }, required: ['action'] });
      if (decide.action === 'answer' || !tools.includes(decide.action)) break;
      const args = await json([{ role: 'system', content: `${c.instructions}${results()}\n\nWrite the arguments for ${decide.action}: ${c.tool_docs[decide.action] || ''} ` +
        'Take the values from the conversation; use the defaults the steps give for anything missing.' }, ...convo], toolSchema(decide.action, wf));
      if (calls.some((k) => k.tool === decide.action && JSON.stringify(k.arguments) === JSON.stringify(args))) break;
      const result = runTool(decide.action, args);
      calls.push({ tool: decide.action, arguments: args, result });
      add('call', `${esc(decide.action)}(${esc(JSON.stringify(args))})\n→ ${esc(fmtResult(result))}`);
    }
    const bubble = add('msg bot', '…');
    const stream = await state.engine.chat.completions.create({ stream: true, temperature: 0.2, max_tokens: 400, messages: [
      { role: 'system', content: `${c.instructions}${results()}\n\nNow answer the user's latest question in plain sentences. ` +
        'Follow the steps and rules, and use only these tool results for numbers and facts. Do not mention calling tools.' },
      ...convo] });
    let text = '';
    for await (const chunk of stream) { text += chunk.choices[0]?.delta?.content || ''; bubble.textContent = text; $('#log').scrollTop = 1e9; }
    state.history.push({ role: 'user', content: question }, { role: 'assistant', content: text });
  } catch (e) {
    add('msg bot', `<span class="err">${esc(e.message)}</span>`);
  } finally { state.busy = false; $('#send').disabled = false; }
}

init().catch((e) => { $('#compiled').innerHTML = `<p class="err">Could not load the demo files: ${esc(e.message)}</p>`; });
