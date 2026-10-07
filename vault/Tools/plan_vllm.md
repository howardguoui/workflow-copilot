---
type: tool
name: plan_vllm
---
Predicts how much KV cache vLLM will allocate on one GPU and how many full-length requests fit. Inputs: model (one of the presets), GPU memory in GiB, weights size in GiB, max context length in tokens, KV cache type (auto = FP16, or fp8) and GPU memory utilization (default 0.9). When a result says `fits: false` with the FP16 cache, call it again with `kv_cache_dtype: fp8`: FP8 halves the cache per token.

Same formula as `inference-lab plan vllm` in Local Inference Lab.
