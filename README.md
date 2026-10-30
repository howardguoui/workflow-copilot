# Workflow Copilot

Write an agent's workflow as an Obsidian note; get a chatbot. The note holds the agent's goal, steps, tools and
rules in plain markdown. Workflow Copilot compiles it into an agent and runs it two ways:

- **Microsoft stack:** a [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) agent served
  through the **Microsoft 365 Agents SDK** (the endpoint Microsoft 365 Agents Playground, Teams and Copilot talk to),
  on any OpenAI-compatible model: Ollama locally, vLLM, or Azure OpenAI.
- **In the browser:** the same note compiled by `web/compile.js` and run with a small open model on the visitor's
  GPU through [WebLLM](https://github.com/mlc-ai/web-llm). No server, no API key.

**Demo:** [howardguoui.github.io/workflow-copilot](https://howardguoui.github.io/workflow-copilot/): edit a workflow
note and watch the agent recompile, chat with it in the browser, and read transcripts recorded with the full Python
runtime and Qwen3 8B.

**Stack:** Python, Microsoft Agent Framework, Microsoft 365 Agents SDK (aiohttp), Model Context Protocol (MCP), Ollama,
WebLLM (WebGPU), JavaScript, pytest, GitHub Actions

```mermaid
flowchart LR
    N["Obsidian workflow note<br/>Steps · [[tool]] links · Rules"] --> C1[note.py] & C2[compile.js]
    T["Tool notes<br/>(descriptions)"] --> C1 & C2
    C1 --> A["Microsoft Agent Framework agent<br/>OpenAI-compatible model (Ollama)"]
    A --> S["Microsoft 365 Agents SDK<br/>/api/messages"] --> P["Agents Playground · Teams · Copilot"]
    C2 --> W["WebLLM in the browser<br/>Qwen2.5 0.5B to 3B"]
    A & W --> TL["tools: plan_vllm · read_note · search_filings"]
    A -. "--mcp-lab (optional)" .-> M["Local Inference Lab MCP server<br/>plan_vllm_deployment"]
```

## A workflow note

```markdown
---
type: workflow
name: GPU Sizing Assistant
description: Answers "will this model fit on my GPU, and for how many users?" for vLLM deployments.
---
## Steps
1. Find the model, GPU memory, weights size and context length in the question. Assume FP16 KV cache.
2. Call [[plan_vllm]] with those values.
3. If the result says `fits: false`, call [[plan_vllm]] again with `kv_cache_dtype: fp8` before answering.
   Never work out FP8 numbers yourself.
4. If the user asks which server to run, read [[vLLM vs llama.cpp vs Ollama]] and quote its numbers.

## Tools
- [[plan_vllm]]
- [[read_note]]

## Rules
- Never invent benchmark numbers: only quote tool results and the notes you read.
```

Compiling it gives the agent its system instructions, exactly the tools linked under `## Tools` (described by the
tool notes in `vault/Tools/`), and read access to the other notes it links to, nothing else.
`workflow-copilot compile "vault/GPU Sizing Assistant.md"` prints the result.

The tools use real data: `plan_vllm` is the vLLM planner from
[Local Inference Lab](https://github.com/howardguoui/local-inference-lab) (its benchmark notes quote measured
results), and `search_filings` returns answers recorded from [Filings RAG](https://github.com/howardguoui/filings-rag).
By default all three run in-process: `plan_vllm` is a copy of the lab's planner formula (`tools.py`, parity-tested
against the lab's numbers) and `search_filings` replays recorded answers. With `--mcp-lab`, the Python agent gets
`plan_vllm` from Local Inference Lab's own MCP server instead (below). `search_filings` and `read_note` are always
in-process, and the browser bot always uses its JavaScript copies (`web/tools.js`).

## Run it

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
ollama pull qwen3:8b
workflow-copilot chat  "vault/GPU Sizing Assistant.md"      # terminal chat; tool calls are printed
workflow-copilot serve "vault/GPU Sizing Assistant.md"      # Microsoft 365 Agents SDK endpoint on :3978
workflow-copilot record vault                                # answer every note's examples -> docs/transcripts.json
workflow-copilot site                                        # build the static demo into docs/
```

`--base-url` and `--model` (or `COPILOT_BASE_URL`, `COPILOT_MODEL`) point it at any OpenAI-compatible server.

### plan_vllm over MCP

`chat`, `serve` and `record` take `--mcp-lab` (or `COPILOT_MCP_LAB`) to call Local Inference Lab's MCP server for
`plan_vllm` instead of the in-process copy. Give it the command that starts the lab's server (stdio) or the URL of
`inference-lab mcp --http` (streamable HTTP):

```bash
.venv/bin/pip install -e ".[mcp]"        # mcp 2 + Agent Framework 1.23 or later (also in the dev extras)
workflow-copilot chat "vault/GPU Sizing Assistant.md" --mcp-lab "inference-lab mcp"
workflow-copilot chat "vault/GPU Sizing Assistant.md" --mcp-lab "/path/to/local-inference-lab/.venv/bin/inference-lab mcp"
workflow-copilot serve "vault/GPU Sizing Assistant.md" --mcp-lab http://127.0.0.1:8765/mcp   # lab: inference-lab mcp --http
```

`src/workflow_copilot/lab_mcp.py` uses Agent Framework's own MCP clients (`MCPStdioTool` for a command,
`MCPStreamableHTTPTool` for a URL), connects once (per chat, per `record` run, or for the life of the `serve` app)
and takes the server's `plan_vllm_deployment` tool. The agent still sees it as `plan_vllm`, the name the note links
to, with the tool note's description, but with the server's input schema (so it also takes `overhead_gib`, and
`gpu_gib` is optional: the lab reads the GPU's memory over NVML when it is left out). Every call goes to the server
and returns the lab's full plan, including `kv_blocks` and `advice`. Server errors, such as an unknown model name (the
lab matches preset names exactly, where the in-process copy ignores case), go back to the model as `{"error": ...}`.
If the server has no `plan_vllm_deployment` tool, the copilot stops at startup. `record --mcp-lab` notes the MCP
source in the transcript's `runtime`. Without the flag nothing changes and `mcp` is not imported.

**Microsoft 365:** `serve` runs anonymously for local use, which is what Microsoft 365 Agents Playground expects;
point Playground at `http://localhost:3978/api/messages`. To reach Teams or Microsoft 365 Copilot, register an Azure
Bot and swap the anonymous connection in `m365.py` for an MSAL connection manager
(`microsoft-agents-authentication-msal`); that part needs an Azure subscription and is not exercised here.

## The browser bot

`docs/` is a static page (GitHub Pages). It loads the vault's markdown, compiles the selected note with `compile.js`
and runs a Qwen2.5 model with WebLLM. Small models are unreliable at free-form tool calling, so each turn is split:
the model picks the next tool from the note's list (output constrained to a JSON schema; the first pick must be a tool, because small models otherwise answer from memory), fills that tool's arguments
(also schema-constrained), the tool runs in the page, and the model writes the answer from the result. Browsers
without WebGPU (most phones) get the recorded transcripts instead.

## Tests

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -q
```

- the parser and compiler on the vault notes; the tools against Local Inference Lab's numbers;
- the Agent Framework agent against a scripted OpenAI-compatible server: the note becomes the system prompt, only
  linked tools are offered, the tool call runs and its result reaches the model;
- `--mcp-lab` end to end against `tests/fake_lab_mcp.py`, a stand-in MCP server with the lab's `plan_vllm_deployment`
  name and schema (the test checks the schema against one captured from the real server): over stdio and streamable
  HTTP, through the Agents SDK endpoint, server errors, and the default path staying in-process;
- the Microsoft 365 Agents SDK endpoint end to end: a Bot Framework activity in, the agent's reply out
  (`deliveryMode: expectReplies`);
- `web/compile.js` and `web/tools.js` under Node against the Python versions (same JSON for every note, same tool
  results on a grid of inputs).

`scripts/check_page.js` drives the built page in headless Chromium with a stand-in model to check the browser agent
loop (needs Playwright).

## Layout

```
vault/                     Obsidian vault: workflow notes, Tools/, Notes/
src/workflow_copilot/      note.py (compiler), tools.py, agent.py (Agent Framework), m365.py (Agents SDK),
                           lab_mcp.py (plan_vllm over MCP), cli.py, site.py
web/                       index.html, app.js (WebLLM), compile.js, tools.js, planner.js
docs/                      built demo for GitHub Pages
tests/                     pytest
```
