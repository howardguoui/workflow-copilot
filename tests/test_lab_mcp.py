"""plan_vllm from Local Inference Lab's MCP server (--mcp-lab), against tests/fake_lab_mcp.py.

The fake server runs as a real subprocess (stdio) or a real local HTTP server, and Agent Framework's own
MCPStdioTool / MCPStreamableHTTPTool talk to it. The chat model is the scripted OpenAI-compatible server from
test_agent_and_m365.py. No network, GPU or Ollama.
"""

import json
import os
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from agent_framework import FunctionTool  # noqa: E402

from tests.test_agent_and_m365 import scripted_client  # noqa: E402
from workflow_copilot import cli  # noqa: E402
from workflow_copilot.agent import WorkflowCopilot  # noqa: E402
from workflow_copilot.lab_mcp import LAB_TOOL, connect, remote_function  # noqa: E402
from workflow_copilot.m365 import create_web_app  # noqa: E402
from workflow_copilot.note import compile_note  # noqa: E402

VAULT = Path(__file__).resolve().parents[1] / "vault"
FAKE = Path(__file__).with_name("fake_lab_mcp.py")
STDIO = shlex.join([sys.executable, str(FAKE)])
QUESTION = "Will Qwen2.5-7B fit on 16 GB with 8k context?"

# plan_vllm_deployment's inputSchema as Local Inference Lab's real server (fastmcp) reported it over tools/list,
# from `inference-lab mcp` at local-inference-lab commit 49044a8.
LAB_SCHEMA = {
    "properties": {
        "model": {"type": "string"},
        "weights_gib": {"type": "number"},
        "max_model_len": {"default": 8192, "type": "integer"},
        "gpu_gib": {"anyOf": [{"type": "number"}, {"type": "null"}], "default": None},
        "gpu_memory_utilization": {"default": 0.9, "type": "number"},
        "kv_cache_dtype": {"default": "auto", "type": "string"},
        "overhead_gib": {"default": 1.5, "type": "number"},
    },
    "required": ["model", "weights_gib"],
    "type": "object",
    "additionalProperties": False,
}


def shape(schema: dict) -> dict:
    """A schema without the cosmetic keys the two MCP server libraries disagree on (titles, additionalProperties)."""
    props = {k: {a: b for a, b in v.items() if a != "title"} for k, v in schema["properties"].items()}
    return {"type": schema["type"], "required": sorted(schema.get("required", [])), "properties": props}


def offered(body: dict) -> dict:
    return {t["function"]["name"]: t["function"] for t in body["tools"]}


async def test_fake_server_matches_the_labs_tool():
    """Guard the stand-in: same tool name and the same parameters, types, defaults and required list."""
    async with connect(STDIO) as lab:
        remote = remote_function(lab)
    assert remote.name == LAB_TOOL == "plan_vllm_deployment"
    assert shape(remote.parameters()) == shape(LAB_SCHEMA)


async def test_agent_gets_plan_vllm_from_the_mcp_server_over_stdio():
    sent = []
    compiled = compile_note(VAULT / "GPU Sizing Assistant.md")
    async with connect(STDIO) as lab:
        bot = WorkflowCopilot(compiled, VAULT, scripted_client(sent), lab=lab)
        answer = await bot.ask(QUESTION)
        schema = remote_function(lab).parameters()
    assert answer == "It fits: 143,040 tokens, 17 requests at 8k."
    tools = offered(sent[0])
    assert set(tools) == {"plan_vllm", "read_note"}  # still only the note's tools, under the note's names
    assert tools["plan_vllm"]["description"] == compiled["tool_docs"]["plan_vllm"]  # the tool note's text
    assert tools["plan_vllm"]["parameters"] == schema  # the server's own schema, not the in-process one
    assert "overhead_gib" in tools["plan_vllm"]["parameters"]["properties"]
    call = bot.calls[0]
    assert call["tool"] == "plan_vllm"
    assert call["arguments"] == {"model": "qwen2.5-7b", "gpu_gib": 15.92, "weights_gib": 5.188, "max_model_len": 8192}
    # kv_blocks and advice exist only in the lab's result: the answer came from the server, not tools.py
    assert call["result"]["kv_blocks"] == 8940 and call["result"]["advice"] == "fake lab server"
    assert call["result"]["kv_tokens"] == 143_040 and call["result"]["max_concurrent_at_max_len"] == 17
    tool_msg = next(m for m in sent[1]["messages"] if m.get("role") == "tool")
    assert json.loads(tool_msg["content"])["kv_blocks"] == 8940  # and the server's result reached the model


async def test_server_errors_reach_the_model_as_error_results():
    calls = []

    def record(name, args, result):
        calls.append((name, args, result))
        return json.dumps(result)

    from workflow_copilot.lab_mcp import plan_vllm_tool

    async with connect(STDIO) as lab:
        tool = plan_vllm_tool(lab, None, record)
        assert tool.description.startswith("Predict how many tokens")  # server's description without a tool note
        await tool.invoke(arguments={"model": "gpt-9", "weights_gib": 5.0, "gpu_gib": 15.92})
    assert calls[0][0] == "plan_vllm" and "Unknown model 'gpt-9'" in calls[0][2]["error"]


async def test_agent_gets_plan_vllm_over_streamable_http():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, str(FAKE), "--http", str(port)], stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                if time.monotonic() > deadline or proc.poll() is not None:
                    raise AssertionError("fake MCP HTTP server did not start") from None
                time.sleep(0.1)
        sent = []
        async with connect(f"http://127.0.0.1:{port}/mcp") as lab:
            compiled = compile_note(VAULT / "GPU Sizing Assistant.md")
            bot = WorkflowCopilot(compiled, VAULT, scripted_client(sent), lab=lab)
            await bot.ask(QUESTION)
        assert bot.calls[0]["result"]["kv_blocks"] == 8940
    finally:
        proc.terminate()
        proc.wait(timeout=10)


async def test_agents_sdk_endpoint_uses_the_mcp_server():
    from aiohttp.test_utils import TestClient, TestServer

    compiled = compile_note(VAULT / "GPU Sizing Assistant.md")
    app = create_web_app(compiled, VAULT, lambda: scripted_client([]), mcp_lab=STDIO)
    activity = {
        "type": "message",
        "id": "1",
        "text": QUESTION,
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
        calls = app["sessions"]["conv1"].calls
    assert calls[0]["result"]["kv_blocks"] == 8940
    assert "server" not in app["lab"]  # connection closed with the app


def test_a_server_without_the_lab_tool_is_rejected():
    class Server:
        functions = [FunctionTool(name="gpu_status", description="", func=lambda: {})]

    with pytest.raises(ValueError, match="no plan_vllm_deployment tool .*gpu_status"):
        remote_function(Server())


async def test_default_path_is_unchanged_in_process():
    """Without a lab server: the in-process plan_vllm, with its own schema and result."""
    sent = []
    bot = WorkflowCopilot(compile_note(VAULT / "GPU Sizing Assistant.md"), VAULT, scripted_client(sent))
    await bot.ask(QUESTION)
    assert bot.lab is None
    params = offered(sent[0])["plan_vllm"]["parameters"]
    assert "gpu_gib" in params["required"] and "overhead_gib" not in params["properties"]
    assert bot.calls[0]["result"]["kv_tokens"] == 143_040 and "kv_blocks" not in bot.calls[0]["result"]


def test_default_cli_does_not_use_or_import_mcp():
    """--mcp-lab is off unless given (or COPILOT_MCP_LAB is set), and the default path never imports mcp."""
    script = (
        "import sys; from workflow_copilot import cli, m365; from workflow_copilot.agent import WorkflowCopilot;"
        "from workflow_copilot.note import compile_note; from workflow_copilot.agent import make_client;"
        f"WorkflowCopilot(compile_note({str(VAULT / 'GPU Sizing Assistant.md')!r}), {str(VAULT)!r},"
        "make_client('http://x/v1', 'm'));"
        "print(cli.DEFAULT_MCP_LAB, any(m == 'mcp' or m.startswith('mcp.') for m in sys.modules))"
    )
    env = {k: v for k, v in os.environ.items() if k != "COPILOT_MCP_LAB"}
    out = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["None", "False"]
    env["COPILOT_MCP_LAB"] = "inference-lab mcp"
    out = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=True)
    assert out.stdout.split()[:3] == ["inference-lab", "mcp", "False"]


def test_mcp_lab_flag_is_parsed(monkeypatch):
    seen = {}

    def run(coro):
        seen["args"] = coro.cr_frame.f_locals["args"]  # the namespace _chat was called with
        coro.close()

    monkeypatch.setattr(cli.asyncio, "run", run)
    cli.main(["chat", "vault/GPU Sizing Assistant.md", "--mcp-lab", "inference-lab mcp"])
    assert seen["args"].mcp_lab == "inference-lab mcp"
