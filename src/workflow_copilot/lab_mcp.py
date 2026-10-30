"""Get `plan_vllm` from Local Inference Lab's MCP server instead of the in-process copy in tools.py.

    workflow-copilot chat "vault/GPU Sizing Assistant.md" --mcp-lab "inference-lab mcp"
    workflow-copilot chat "vault/GPU Sizing Assistant.md" --mcp-lab http://127.0.0.1:8765/mcp

A command starts the lab's server as a subprocess and talks to it over stdio (Agent Framework's MCPStdioTool); a
URL connects to `inference-lab mcp --http` over streamable HTTP (MCPStreamableHTTPTool). Only the server's
`plan_vllm_deployment` tool is given to the agent. The agent still sees it under the name the workflow note links to,
`plan_vllm`, with the tool note's description, but with the server's own input schema, and every call goes to the
server. Needs the `mcp` package (`pip install -e ".[mcp]"`).
"""

from __future__ import annotations

import json
import os
import shlex
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from agent_framework import FunctionTool, MCPStdioTool, MCPStreamableHTTPTool
from agent_framework.exceptions import ToolException

LAB_SERVER = "local-inference-lab"
LAB_TOOL = "plan_vllm_deployment"  # local-inference-lab src/inference_lab/mcp_server.py
NOTE_TOOL = "plan_vllm"  # the name workflow notes link to
LabServer = MCPStdioTool | MCPStreamableHTTPTool


def split_command(command: str) -> list[str]:
    """Split a server command line; on Windows keep backslashes in paths and drop the quotes around arguments."""
    if os.name != "nt":
        return shlex.split(command)
    parts = shlex.split(command, posix=False)
    return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]


def lab_server(spec: str, request_timeout: int = 60) -> LabServer:
    """An unconnected Agent Framework MCP tool for the lab server: an http(s) URL, or a command to run over stdio."""
    options = dict(load_prompts=False, request_timeout=request_timeout)
    if spec.startswith(("http://", "https://")):
        return MCPStreamableHTTPTool(name=LAB_SERVER, url=spec, **options)
    parts = split_command(spec)
    if not parts:
        raise ValueError("--mcp-lab needs a command (e.g. 'inference-lab mcp') or a URL")
    return MCPStdioTool(name=LAB_SERVER, command=parts[0], args=parts[1:], **options)


def remote_function(server: LabServer) -> FunctionTool:
    """The connected server's plan_vllm_deployment tool, or a clear error naming what it offers instead."""
    for f in server.functions:
        if f.name == LAB_TOOL:
            return f
    offered = ", ".join(f.name for f in server.functions) or "no tools"
    raise ValueError(f"The MCP server has no {LAB_TOOL} tool (it offers: {offered}). Is it Local Inference Lab?")


@asynccontextmanager
async def connect(spec: str | None) -> AsyncIterator[LabServer | None]:
    """Connect to the lab server for the duration of the block; yields None when no server is configured."""
    if not spec:
        yield None
        return
    server = lab_server(spec)
    async with server:
        remote_function(server)  # fail at startup, not at the first question
        yield server


def _result(contents) -> dict:
    """The MCP tool result as a dict (the lab returns its plan as structured content / JSON text)."""
    text = contents if isinstance(contents, str) else "".join(c.text or "" for c in contents if c.type == "text")
    try:
        value = json.loads(text)
    except ValueError:
        return {"text": text}
    return value if isinstance(value, dict) else {"result": value}


def plan_vllm_tool(
    server: LabServer, description: str | None, record: Callable[[str, dict, dict], str]
) -> FunctionTool:
    """`plan_vllm` for the agent, backed by the server's plan_vllm_deployment.

    The parameters are the server's input schema exactly as tools/list reported it. Server errors (unknown model,
    bad kv_cache_dtype) come back to the model as {"error": ...}, like the in-process tool's errors.
    """
    remote = remote_function(server)

    async def call(**arguments) -> str:
        try:
            result = _result(await server.call_tool(LAB_TOOL, **arguments))
        except ToolException as e:
            result = {"error": str(e)}
        return record(NOTE_TOOL, arguments, result)

    return FunctionTool(
        name=NOTE_TOOL,
        description=description or remote.description,
        input_model=remote.parameters(),
        func=call,
        additional_properties={"mcp_server": LAB_SERVER, "mcp_tool": LAB_TOOL},
    )
