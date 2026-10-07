"""The tools a workflow note can link to. web/tools.js implements the same three for the in-browser bot.

plan_vllm is the vLLM planner from Local Inference Lab (same presets and formula; the tests check it against
web/planner.js, which is that project's parity-tested browser port). search_filings looks up answers that
Filings RAG really produced (data/filings_answers.json). read_note returns a note linked from the workflow.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

from .note import find_note, split_frontmatter

GIB = 1024**3
KV_BYTES = {"auto": 2.0, "fp8": 1.0}
OVERHEAD_GIB = 1.5
BLOCK_SIZE = 16
# From local-inference-lab src/inference_lab/models.py (each model's Hugging Face config.json).
MODELS = {
    "qwen2.5-7b": {"n_layers": 28, "n_kv_heads": 4, "head_dim": 128, "params_b": 7.62},
    "qwen2.5-14b": {"n_layers": 48, "n_kv_heads": 8, "head_dim": 128, "params_b": 14.7},
    "qwen2.5-32b": {"n_layers": 64, "n_kv_heads": 8, "head_dim": 128, "params_b": 32.5},
    "qwen3-8b": {"n_layers": 36, "n_kv_heads": 8, "head_dim": 128, "params_b": 8.19},
    "qwen3-14b": {"n_layers": 40, "n_kv_heads": 8, "head_dim": 128, "params_b": 14.8},
    "llama-3.1-8b": {"n_layers": 32, "n_kv_heads": 8, "head_dim": 128, "params_b": 8.03},
    "mistral-7b": {"n_layers": 32, "n_kv_heads": 8, "head_dim": 128, "params_b": 7.25},
}
DATA = Path(__file__).parent / "data"


def planner_spec() -> dict:
    """The constants web/planner.js reads (same shape as Local Inference Lab's data.json `planner`)."""
    return {
        "gib": GIB,
        "kv_bytes": KV_BYTES,
        "gpu_memory_utilization": 0.9,
        "overhead_gib": OVERHEAD_GIB,
        "block_size": BLOCK_SIZE,
        "models": MODELS,
    }


def plan_vllm(
    model: str,
    gpu_gib: float,
    weights_gib: float,
    max_model_len: int = 8192,
    kv_cache_dtype: str = "auto",
    gpu_memory_utilization: float = 0.9,
) -> dict:
    """KV cache vLLM will allocate and how many full-length requests fit."""
    key = model.strip().lower()
    if key not in MODELS:
        return {"error": f"unknown model {model!r}; choose one of: {', '.join(MODELS)}"}
    dtype = "fp8" if kv_cache_dtype.lower().startswith("fp8") else "auto"
    m = MODELS[key]
    per_token = m["n_layers"] * m["n_kv_heads"] * m["head_dim"] * 2 * KV_BYTES[dtype]
    budget = gpu_gib * gpu_memory_utilization - weights_gib - OVERHEAD_GIB
    blocks = max(0, int(budget * GIB // (per_token * BLOCK_SIZE)))
    tokens = blocks * BLOCK_SIZE
    return {
        "model": key,
        "kv_cache_dtype": "fp8" if dtype == "fp8" else "fp16",
        "kv_budget_gib": round(max(budget, 0.0), 2),
        "kv_tokens": tokens,
        "max_model_len": max_model_len,
        "max_concurrent_at_max_len": tokens // max_model_len if max_model_len else 0,
        "fits": tokens >= max_model_len,
        "gib_per_request": round(max_model_len * per_token / GIB, 2),
    }


STOPWORDS = set(
    "the a an and or of to in on for with what how does do did is are was were its it their about describe "
    "says say say face faces from by at as be this that which who whom any all".split()
)


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOPWORDS}


@cache
def filings_answers() -> dict:
    return json.loads((DATA / "filings_answers.json").read_text(encoding="utf-8"))


def search_filings(question: str) -> dict:
    """The recorded Filings RAG answer whose question shares the most words with this one."""
    data = filings_answers()
    q = words(question)
    best, best_score = None, 0
    for a in data["answers"]:
        score = len(q & words(a["question"]))
        if score > best_score:
            best, best_score = a, score
    if best is None or best_score < 2:
        return {"found": False, "covered_questions": [a["question"] for a in data["answers"]]}
    return {
        "found": True,
        "matched_question": best["question"],
        "answer": best["answer"],
        "abstained": best["abstained"],
        "sources": best["citations"],
        "recorded": data["source"],
    }


def read_note(title: str, vault: str | Path, allowed: list[str]) -> dict:
    """A note's text, only if the workflow links to it."""
    title = title.strip().strip('"').strip("[]")
    if title not in allowed:
        return {"error": f"{title!r} is not linked from this workflow; readable notes: {', '.join(allowed)}"}
    path = find_note(vault, title)
    if path is None:
        return {"error": f"note {title!r} not found in the vault"}
    _, body = split_frontmatter(path.read_text(encoding="utf-8"))
    return {"title": title, "text": body.strip()}
