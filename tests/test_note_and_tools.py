from pathlib import Path

import pytest

from workflow_copilot import tools as T
from workflow_copilot.note import compile_note, parse_workflow, plain

VAULT = Path(__file__).resolve().parents[1] / "vault"


def test_workflow_note_compiles_to_steps_tools_and_linked_notes():
    c = compile_note(VAULT / "GPU Sizing Assistant.md")
    wf = c["workflow"]
    assert wf["name"] == "GPU Sizing Assistant"
    assert wf["tools"] == ["plan_vllm", "read_note"]
    assert wf["notes"] == ["vLLM vs llama.cpp vs Ollama", "KV cache"]
    assert len(wf["steps"]) == 6 and "[[" not in " ".join(wf["steps"])
    assert wf["steps"][1] == "Call plan_vllm with those values."
    assert c["tool_docs"]["plan_vllm"].startswith("Predicts how much KV cache vLLM will allocate")
    ins = c["instructions"]
    assert ins.startswith("You are GPU Sizing Assistant: Answers")
    assert "1. Find the model" in ins and "- plan_vllm: Predicts" in ins
    assert ins.endswith('Notes you can read with read_note: "vLLM vs llama.cpp vs Ollama", "KV cache".')


def test_parser_rules():
    assert plain("see [[KV cache|the KV note]] and [[plan_vllm]]") == "see the KV note and plan_vllm"
    with pytest.raises(ValueError):
        parse_workflow("---\ntype: note\n---\n# x")
    wf = parse_workflow("---\ntype: workflow\nname: X\n---\n## Steps\n1) one\n- two\n## Tools\n- read_note\n")
    assert wf.steps == ["one", "two"] and wf.tools == ["read_note"] and wf.description == ""


def test_plan_vllm_matches_the_lab_planner_for_the_benchmarked_setup():
    # Local Inference Lab predicted 143,040 FP16 / 286,096 FP8 tokens for Qwen2.5-7B AWQ on the 15.92 GiB card.
    w = 5_570_829_760 / 1024**3
    assert T.plan_vllm("qwen2.5-7b", 15.92, w)["kv_tokens"] == 143_040
    fp8 = T.plan_vllm("Qwen2.5-7B", 15.92, w, 8192, "fp8")
    assert fp8["kv_tokens"] == 286_096 and fp8["max_concurrent_at_max_len"] == 34 and fp8["fits"]
    assert not T.plan_vllm("qwen2.5-32b", 15.92, 18.5)["fits"]
    assert "error" in T.plan_vllm("gpt-9", 16, 4)


def test_search_filings_returns_recorded_answers_or_says_not_covered():
    hit = T.search_filings("What cyber security risks does JPMorgan describe?")
    assert hit["found"] and hit["matched_question"] == "What cybersecurity risks does JPMorgan describe?"
    assert hit["sources"] and hit["sources"][0]["company"]
    miss = T.search_filings("What is the weather in Paris?")
    assert not miss["found"] and len(miss["covered_questions"]) == 10


def test_read_note_only_reads_linked_notes():
    ok = T.read_note("KV cache", VAULT, ["KV cache"])
    assert "272,304" in ok["text"]
    assert "error" in T.read_note("GPU Sizing Assistant", VAULT, ["KV cache"])
