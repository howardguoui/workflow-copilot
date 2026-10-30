"""A stand-in for Local Inference Lab's MCP server (`inference-lab mcp`), for tests: no GPU, no NVML, no network.

It exposes `plan_vllm_deployment` with the same name, parameters, defaults and docstring as
local-inference-lab src/inference_lab/mcp_server.py, and returns the same keys as that project's
`VllmPlan.as_dict()` (including `kv_blocks` and `advice`, which the in-process plan_vllm does not return, so a test
can tell where a result came from). The formula is the lab's planner; `gpu_gib` must be given because there is no
GPU to read.

    python tests/fake_lab_mcp.py                 # stdio
    python tests/fake_lab_mcp.py --http PORT     # streamable HTTP on http://127.0.0.1:PORT/mcp
"""

from __future__ import annotations

import sys

try:  # mcp 2 (what Agent Framework >= 1.23 uses)
    from mcp.server.mcpserver import MCPServer as Server
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1 (Agent Framework 1.20 to 1.22)
    from mcp.server.fastmcp import FastMCP as Server
    from mcp.server.fastmcp.exceptions import ToolError

GIB = 1024**3
VLLM_KV_BYTES = {"auto": 2.0, "float16": 2.0, "bfloat16": 2.0, "fp8": 1.0, "fp8_e4m3": 1.0, "fp8_e5m2": 1.0}
# name: (layers, kv heads, head dim), from local-inference-lab src/inference_lab/models.py
PRESETS = {
    "qwen2.5-7b": (28, 4, 128),
    "qwen2.5-14b": (48, 8, 128),
    "qwen2.5-32b": (64, 8, 128),
    "qwen3-8b": (36, 8, 128),
    "qwen3-14b": (40, 8, 128),
    "llama-3.1-8b": (32, 8, 128),
    "mistral-7b": (32, 8, 128),
}

mcp = Server("local-inference-lab", log_level="WARNING")


@mcp.tool()
def plan_vllm_deployment(
    model: str,
    weights_gib: float,
    max_model_len: int = 8192,
    gpu_gib: float | None = None,
    gpu_memory_utilization: float = 0.90,
    kv_cache_dtype: str = "auto",
    overhead_gib: float = 1.5,
) -> dict:
    """Predict how many tokens of KV cache vLLM will allocate and how many full-length sequences fit.
    weights_gib: size of the checkpoint on disk. kv_cache_dtype: one of auto, float16, bfloat16, fp8.
    gpu_gib defaults to the GPU's total memory (NVML)."""
    # The lab's server (fastmcp) sends any exception's message to the client; mcp 2 only does that for ToolError.
    if kv_cache_dtype not in VLLM_KV_BYTES:
        raise ToolError(f"kv_cache_dtype must be one of {sorted(VLLM_KV_BYTES)}")
    if model not in PRESETS:
        raise ToolError(f"Unknown model {model!r}. Presets: {', '.join(PRESETS)}")
    if gpu_gib is None:
        raise ToolError("No NVIDIA GPU or driver found (NVML unavailable).")
    layers, kv_heads, head_dim = PRESETS[model]
    per_token = layers * kv_heads * head_dim * 2 * VLLM_KV_BYTES[kv_cache_dtype]
    budget = gpu_gib * gpu_memory_utilization - weights_gib - overhead_gib
    blocks = max(0, int(budget * GIB // (per_token * 16)))
    tokens = blocks * 16
    fits = tokens >= max_model_len
    concurrent = tokens // max_model_len if max_model_len else 0
    return {
        "model": model,
        "kv_cache_dtype": kv_cache_dtype,
        "kv_bytes_per_token": per_token,
        "gpu_gib": gpu_gib,
        "gpu_memory_utilization": gpu_memory_utilization,
        "weights_gib": round(weights_gib, 2),
        "overhead_gib": overhead_gib,
        "kv_budget_gib": round(max(budget, 0.0), 2),
        "kv_tokens": tokens,
        "kv_blocks": blocks,
        "max_model_len": max_model_len,
        "max_concurrent_at_max_len": concurrent,
        "fits": fits,
        "advice": "fake lab server",
    }


@mcp.tool()
def gpu_status() -> dict:
    """Current GPU name, VRAM used and free, utilization, temperature and power."""
    return {"error": "No NVIDIA GPU or driver found (NVML unavailable)."}


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--http":
        host, port = "127.0.0.1", int(sys.argv[2])
        if hasattr(mcp.settings, "port"):  # mcp 1 reads host and port from settings
            mcp.settings.host, mcp.settings.port = host, port
            mcp.run(transport="streamable-http")
        else:
            mcp.run(transport="streamable-http", host=host, port=port)
    else:
        mcp.run()
