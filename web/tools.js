// The in-browser versions of the tools in src/workflow_copilot/tools.py (parity-tested in tests/test_web_parity.py).
(function (root) {
  const Planner = root.Planner || (typeof require !== 'undefined' ? require('./planner.js') : null);
  const STOPWORDS = new Set(('the a an and or of to in on for with what how does do did is are was were its it their about describe ' +
    'says say say face faces from by at as be this that which who whom any all').split(' '));
  const round2 = (x) => Math.round(x * 100) / 100;

  function planVllm(spec, args) {
    const model = String(args.model || '').trim().toLowerCase();
    if (!spec.models[model]) return { error: `unknown model '${args.model}'; choose one of: ${Object.keys(spec.models).join(', ')}` };
    const dtype = String(args.kv_cache_dtype || 'auto').toLowerCase().startsWith('fp8') ? 'fp8' : 'auto';
    const maxLen = Number(args.max_model_len ?? 8192);
    const p = Planner.planVllm(spec, {
      model, gpu_gib: Number(args.gpu_gib), weights_gib: Number(args.weights_gib), max_model_len: maxLen,
      gpu_memory_utilization: Number(args.gpu_memory_utilization ?? 0.9), kv_cache_dtype: dtype,
    });
    return {
      model, kv_cache_dtype: dtype === 'fp8' ? 'fp8' : 'fp16', kv_budget_gib: p.kv_budget_gib, kv_tokens: p.kv_tokens,
      max_model_len: maxLen, max_concurrent_at_max_len: p.max_concurrent_at_max_len, fits: p.fits,
      gib_per_request: round2(p.gib_per_sequence),
    };
  }

  const words = (text) => new Set((String(text).toLowerCase().match(/[a-z0-9]+/g) || []).filter((w) => w.length > 2 && !STOPWORDS.has(w)));

  function searchFilings(data, question) {
    const q = words(question);
    let best = null, bestScore = 0;
    for (const a of data.answers) {
      const w = words(a.question);
      let score = 0;
      for (const x of q) if (w.has(x)) score++;
      if (score > bestScore) { best = a; bestScore = score; }
    }
    if (!best || bestScore < 2) return { found: false, covered_questions: data.answers.map((a) => a.question) };
    return { found: true, matched_question: best.question, answer: best.answer, abstained: best.abstained,
      sources: best.citations, recorded: data.source };
  }

  function readNote(notesByTitle, allowed, title) {
    title = String(title || '').trim().replace(/^"|"$/g, '').replace(/^\[+|\]+$/g, '');
    if (!allowed.includes(title)) return { error: `'${title}' is not linked from this workflow; readable notes: ${allowed.join(', ')}` };
    const text = notesByTitle[title];
    if (text == null) return { error: `note '${title}' not found in the vault` };
    return { title, text: text.trim() };
  }

  const api = { planVllm, searchFilings, readNote, words };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.CopilotTools = api;
})(typeof window !== 'undefined' ? window : globalThis);
