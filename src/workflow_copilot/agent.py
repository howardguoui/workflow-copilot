"""Turn a compiled workflow note into a Microsoft Agent Framework agent.

The model is any OpenAI-compatible chat endpoint: Ollama locally (http://localhost:11434/v1), vLLM, or Azure
OpenAI. Only the tools the note links to are given to the agent, with the descriptions written in the tool notes.
"""

import json
from pathlib import Path
from typing import Annotated

from agent_framework import Agent, tool
from agent_framework.openai import OpenAIChatCompletionClient

from . import tools as T


def make_client(base_url: str, model: str, api_key: str = "ollama", async_client=None) -> OpenAIChatCompletionClient:
    return OpenAIChatCompletionClient(model=model, base_url=base_url, api_key=api_key, async_client=async_client)


class WorkflowCopilot:
    """One chat session with the agent a workflow note defines. `calls` records every tool call."""

    def __init__(self, compiled: dict, vault: str | Path, client):
        self.compiled = compiled
        self.vault = Path(vault)
        self.calls: list[dict] = []
        wf = compiled["workflow"]
        available = self._tools(wf["notes"])
        unknown = [t for t in wf["tools"] if t not in available]
        if unknown:
            raise ValueError(f"The note links to tools this runtime does not have: {', '.join(unknown)}")
        chosen = [available[t] for t in wf["tools"]]
        self.agent = Agent(
            client,
            instructions=compiled["instructions"],
            name=wf["name"],
            tools=chosen,
            default_options={"temperature": 0},  # tool calling follows the note more reliably without sampling
        )
        self.session = self.agent.create_session()

    def _record(self, name: str, args: dict, result: dict) -> str:
        self.calls.append({"tool": name, "arguments": args, "result": result})
        return json.dumps(result)

    def _tools(self, notes: list[str]) -> dict:
        docs = self.compiled["tool_docs"]

        @tool(name="plan_vllm", description=docs.get("plan_vllm") or T.plan_vllm.__doc__)
        def plan_vllm(
            model: Annotated[str, f"model preset: {', '.join(T.MODELS)}"],
            gpu_gib: Annotated[float, "GPU memory in GiB, e.g. 15.92 for a 16 GB card"],
            weights_gib: Annotated[float, "size of the model's weight files in GiB"],
            max_model_len: Annotated[int, "max context length per request, in tokens"] = 8192,
            kv_cache_dtype: Annotated[str, "auto (FP16) or fp8"] = "auto",
            gpu_memory_utilization: Annotated[float, "fraction of GPU memory vLLM may use"] = 0.9,
        ) -> str:
            args = dict(
                model=model,
                gpu_gib=gpu_gib,
                weights_gib=weights_gib,
                max_model_len=max_model_len,
                kv_cache_dtype=kv_cache_dtype,
                gpu_memory_utilization=gpu_memory_utilization,
            )
            return self._record("plan_vllm", args, T.plan_vllm(**args))

        @tool(name="search_filings", description=docs.get("search_filings") or T.search_filings.__doc__)
        def search_filings(question: Annotated[str, "the user's question"]) -> str:
            return self._record("search_filings", {"question": question}, T.search_filings(question))

        @tool(name="read_note", description=docs.get("read_note") or T.read_note.__doc__)
        def read_note(title: Annotated[str, f"note title, one of: {', '.join(notes) or 'none'}"]) -> str:
            return self._record("read_note", {"title": title}, T.read_note(title, self.vault, notes))

        return {"plan_vllm": plan_vllm, "search_filings": search_filings, "read_note": read_note}

    async def ask(self, text: str) -> str:
        response = await self.agent.run(text, session=self.session)
        return response.text
