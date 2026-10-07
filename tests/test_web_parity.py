"""The in-browser bot must compile notes and run tools exactly like the Python runtime."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from workflow_copilot import tools as T
from workflow_copilot.cli import workflow_notes
from workflow_copilot.note import compile_note, split_frontmatter

ROOT = Path(__file__).resolve().parents[1]
VAULT = ROOT / "vault"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")


def node(script: str, payload) -> object:
    out = subprocess.run(
        ["node", "-e", script, str(ROOT / "web")],
        input=json.dumps(payload),
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(out.stdout)


PRELUDE = (
    "const W=process.argv[1];globalThis.Planner=require(W+'/planner.js');const C=require(W+'/compile.js');"
    "const T=require(W+'/tools.js');let s='';process.stdin.on('data',d=>s+=d);process.stdin.on('end',()=>{"
    "const p=JSON.parse(s);console.log(JSON.stringify(run(p)))});"
)


def test_compile_js_matches_python_for_every_workflow_note():
    notes = workflow_notes(VAULT)
    assert len(notes) == 2
    payload = [
        {
            "note": n.read_text(encoding="utf-8"),
            "tools": {p.stem: p.read_text(encoding="utf-8") for p in (VAULT / "Tools").glob("*.md")},
        }
        for n in notes
    ]
    got = node(PRELUDE + "function run(p){return p.map(x=>C.compileNote(x.note,x.tools))}", payload)
    for n, js in zip(notes, got, strict=True):
        assert js == compile_note(n, VAULT), n.name


def test_tools_js_match_python():
    plans = [
        dict(model=m, gpu_gib=g, weights_gib=w, max_model_len=n, kv_cache_dtype=kv)
        for m in ("qwen2.5-7b", "Qwen2.5-14B", "qwen2.5-32b", "llama-3.1-8b", "nope")
        for g in (12.0, 15.92, 24.0)
        for w in (4.5, 5.188, 9.5, 18.5)
        for n in (4096, 8192, 32768)
        for kv in ("auto", "fp8")
    ]
    questions = [
        "What cyber security risks does JPMorgan describe?",
        "How do export controls affect NVIDIA in China?",
        "Where are Tesla's factories?",
        "What is the weather in Paris?",
        "How many cars did Microsoft sell last year?",
        "Goldman Sachs counterparty credit risk",
        "Amazon competition",
    ]
    data = T.filings_answers()
    got = node(
        PRELUDE + "function run(p){return {plans:p.plans.map(a=>T.planVllm(p.spec,a)),"
        "search:p.questions.map(q=>T.searchFilings(p.data,q))}}",
        {"spec": T.planner_spec(), "plans": plans, "questions": questions, "data": data},
    )
    for args, js in zip(plans, got["plans"], strict=True):
        py = T.plan_vllm(**args)
        if "error" in py:
            assert "error" in js
            continue
        for k in ("model", "kv_cache_dtype", "kv_tokens", "max_model_len", "max_concurrent_at_max_len", "fits"):
            assert js[k] == py[k], (args, k)
        assert js["kv_budget_gib"] == pytest.approx(py["kv_budget_gib"], abs=0.006)
        assert js["gib_per_request"] == pytest.approx(py["gib_per_request"], abs=0.006)
    for q, js in zip(questions, got["search"], strict=True):
        assert js == T.search_filings(q), q


def test_read_note_js_matches_python():
    allowed = ["KV cache", "vLLM vs llama.cpp vs Ollama"]
    bodies = {p.stem: split_frontmatter(p.read_text(encoding="utf-8"))[1] for p in (VAULT / "Notes").glob("*.md")}
    titles = ["KV cache", " vLLM vs llama.cpp vs Ollama ", "GPU Sizing Assistant"]
    got = node(
        PRELUDE + "function run(p){return p.titles.map(t=>T.readNote(p.bodies,p.allowed,t))}",
        {"bodies": bodies, "allowed": allowed, "titles": titles},
    )
    for t, js in zip(titles, got, strict=True):
        py = T.read_note(t, VAULT, allowed)
        assert js.keys() == py.keys() and js.get("text") == py.get("text"), t
