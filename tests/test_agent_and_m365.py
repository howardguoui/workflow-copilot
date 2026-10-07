"""The Agent Framework runtime and the Microsoft 365 channel against a scripted OpenAI-compatible server."""

import json
from pathlib import Path

from openai import AsyncOpenAI, _base_client

from workflow_copilot.agent import WorkflowCopilot, make_client
from workflow_copilot.m365 import create_web_app
from workflow_copilot.note import compile_note

VAULT = Path(__file__).resolve().parents[1] / "vault"
hx = getattr(_base_client, "httpx2", None) or _base_client.httpx  # openai's own HTTP library


def scripted_client(sent: list):
    """First reply calls plan_vllm; the next one answers in text."""

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        if not any(m.get("role") == "tool" for m in body["messages"]):
            msg = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "plan_vllm",
                            "arguments": json.dumps(
                                {"model": "qwen2.5-7b", "gpu_gib": 15.92, "weights_gib": 5.188, "max_model_len": 8192}
                            ),
                        },
                    }
                ],
            }
            finish = "tool_calls"
        else:
            msg, finish = {"role": "assistant", "content": "It fits: 143,040 tokens, 17 requests at 8k."}, "stop"
        return hx.Response(
            200,
            json={
                "id": "c",
                "object": "chat.completion",
                "created": 0,
                "model": "qwen3:8b",
                "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    async_client = AsyncOpenAI(
        base_url="http://x/v1",
        api_key="k",
        max_retries=0,
        http_client=hx.AsyncClient(transport=hx.MockTransport(handler)),
    )
    return make_client("http://x/v1", "qwen3:8b", async_client=async_client)


async def test_agent_follows_the_note_and_calls_its_tool():
    sent = []
    compiled = compile_note(VAULT / "GPU Sizing Assistant.md")
    bot = WorkflowCopilot(compiled, VAULT, scripted_client(sent))
    answer = await bot.ask("Will Qwen2.5-7B fit on 16 GB with 8k context?")
    assert answer == "It fits: 143,040 tokens, 17 requests at 8k."
    assert sent[0]["messages"][0]["content"] == compiled["instructions"]  # the note became the system prompt
    assert {t["function"]["name"] for t in sent[0]["tools"]} == {"plan_vllm", "read_note"}  # only linked tools
    assert bot.calls[0]["tool"] == "plan_vllm" and bot.calls[0]["result"]["kv_tokens"] == 143_040
    tool_msg = next(m for m in sent[1]["messages"] if m.get("role") == "tool")
    assert json.loads(tool_msg["content"])["max_concurrent_at_max_len"] == 17


def test_unknown_tool_in_note_is_rejected(tmp_path):
    note = tmp_path / "w.md"
    note.write_text("---\ntype: workflow\nname: W\n---\n## Tools\n- [[send_email]]\n", encoding="utf-8")
    try:
        WorkflowCopilot(compile_note(note), tmp_path, scripted_client([]))
    except ValueError as e:
        assert "send_email" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_web_app_exposes_the_agents_sdk_endpoint():
    app = create_web_app(compile_note(VAULT / "GPU Sizing Assistant.md"), VAULT, lambda: scripted_client([]))
    assert any(r.resource.canonical == "/api/messages" and r.method == "POST" for r in app.router.routes())


async def test_agents_sdk_endpoint_answers_an_activity_end_to_end():
    """POST a Bot Framework activity with deliveryMode=expectReplies and read the agent's reply from the response."""
    from aiohttp.test_utils import TestClient, TestServer

    app = create_web_app(compile_note(VAULT / "GPU Sizing Assistant.md"), VAULT, lambda: scripted_client([]))
    activity = {
        "type": "message",
        "id": "1",
        "text": "Will Qwen2.5-7B fit on 16 GB?",
        "channelId": "emulator",
        "serviceUrl": "http://localhost:56150",
        "deliveryMode": "expectReplies",
        "from": {"id": "user1", "name": "Howard"},
        "recipient": {"id": "bot", "name": "bot"},
        "conversation": {"id": "conv1"},
    }
    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/api/messages", json=activity)
        assert resp.status == 200, await resp.text()
        body = await resp.json()
    texts = [a.get("text") for a in body["activities"] if a.get("type") == "message"]
    assert texts == ["It fits: 143,040 tokens, 17 requests at 8k."]
