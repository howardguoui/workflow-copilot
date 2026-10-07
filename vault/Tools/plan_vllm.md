---
type: tool
name: plan_vllm
---
Predicts how much KV cache vLLM will allocate on one GPU and how many full-length requests fit. Inputs: model (one of the presets), GPU memory in GiB, weights size in GiB, max context length in tokens, KV cache type (auto = FP16, or fp8) and GPU memory utilization (default 0.9).

Same formula as `inference-lab plan vllm` in Local Inference Lab.
