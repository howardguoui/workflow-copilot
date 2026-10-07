// Obsidian workflow note -> agent definition. A line-for-line port of src/workflow_copilot/note.py;
// tests/test_web_parity.py runs both on every note in the vault and requires identical output.
(function (root) {
  const WIKILINK = /\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]/g;
  const LIST_ITEM = /^\s*(?:[-*+]|\d+[.)])\s+(.*)$/;

  // Enough YAML for note properties: `key: value` and `key: [a, b]`.
  function parseYaml(text) {
    const out = {};
    for (const line of text.split('\n')) {
      const m = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
      if (!m) continue;
      let v = m[2].trim();
      if (v.startsWith('[') && v.endsWith(']')) {
        v = v.slice(1, -1).split(',').map((s) => s.trim().replace(/^["']|["']$/g, '')).filter(Boolean);
      } else {
        v = v.replace(/^["']|["']$/g, '');
      }
      out[m[1]] = v;
    }
    return out;
  }

  function splitFrontmatter(text) {
    text = text.replace(/\r\n/g, '\n');
    if (text.startsWith('---\n')) {
      const end = text.indexOf('\n---', 4);
      if (end !== -1) return [parseYaml(text.slice(4, end)), text.slice(end + 4).replace(/^\n+/, '')];
    }
    return [{}, text];
  }

  function sections(body) {
    const out = {};
    let current = null;
    for (const line of body.split('\n')) {
      if (line.startsWith('## ')) { current = line.slice(3).trim().toLowerCase(); out[current] = []; }
      else if (current !== null) out[current].push(line);
    }
    return out;
  }

  const listItems = (lines) => lines.map((l) => l.match(LIST_ITEM)).filter(Boolean).map((m) => m[1].trim());
  const paragraph = (lines) => lines.map((l) => l.trim()).filter(Boolean).join(' ');
  const linkTargets = (text) => [...text.matchAll(WIKILINK)].map((m) => m[1].trim());
  const plain = (text) => text.replace(WIKILINK, (_, target, alias) => (alias || target).trim());
  const rstripChars = (s, chars) => { let i = s.length; while (i > 0 && chars.includes(s[i - 1])) i--; return s.slice(0, i); };

  function parseWorkflow(text) {
    const [meta, body] = splitFrontmatter(text);
    if (meta.type !== 'workflow') throw new Error('Not a workflow note: add `type: workflow` to its properties.');
    const sec = sections(body);
    const tools = [];
    for (const item of listItems(sec.tools || [])) {
      const targets = linkTargets(item);
      for (const t of targets.length ? targets : [item]) if (!tools.includes(t)) tools.push(t);
    }
    const linked = [];
    for (const key of ['goal', 'steps', 'rules']) {
      for (const t of linkTargets((sec[key] || []).join('\n'))) if (!tools.includes(t) && !linked.includes(t)) linked.push(t);
    }
    return {
      name: String(meta.name || 'Workflow'),
      description: String(meta.description || ''),
      goal: plain(paragraph(sec.goal || [])),
      steps: listItems(sec.steps || []).map(plain),
      tools,
      rules: listItems(sec.rules || []).map(plain),
      examples: listItems(sec.examples || []).map(plain),
      notes: linked,
    };
  }

  function toolDescription(text) {
    const [, body] = splitFrontmatter(text);
    const paras = body.split('\n\n').map((p) => p.trim()).filter((p) => p && !p.startsWith('#'));
    return paras.length ? paras[0].split(/\s+/).join(' ') : '';
  }

  function instructions(wf, docs) {
    let lines = [rstripChars(`You are ${wf.name}: ${wf.description}`, ': ').replace(/\s+$/, ''), ''];
    if (wf.goal) lines.push(`Goal: ${wf.goal}`, '');
    if (wf.steps.length) lines.push('Follow these steps in order:', ...wf.steps.map((s, i) => `${i + 1}. ${s}`), '');
    if (wf.rules.length) lines.push('Rules:', ...wf.rules.map((r) => `- ${r}`), '');
    if (wf.tools.length) lines.push('Tools you can call:', ...wf.tools.map((t) => rstripChars(`- ${t}: ${docs[t] || ''}`, ': ')), '');
    if (wf.notes.length) lines.push('Notes you can read with read_note: ' + wf.notes.map((n) => `"${n}"`).join(', ') + '.');
    return lines.join('\n').trim();
  }

  // toolNotes: {tool name: text of vault/Tools/<name>.md} for the tools the note links to.
  function compileNote(noteText, toolNotes) {
    const wf = parseWorkflow(noteText);
    const docs = {};
    for (const t of wf.tools) docs[t] = toolNotes[t] != null ? toolDescription(toolNotes[t]) : '';
    return { workflow: wf, instructions: instructions(wf, docs), tool_docs: docs };
  }

  const api = { compileNote, parseWorkflow, splitFrontmatter, plain };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.NoteCompiler = api;
})(typeof window !== 'undefined' ? window : globalThis);
