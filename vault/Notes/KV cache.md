---
type: note
source: https://github.com/howardguoui/local-inference-lab/blob/main/results/latest.md
---
# KV cache

The KV cache holds every active request's context. vLLM turns the GPU memory left after the weights into KV cache blocks of 16 tokens.

Measured on an RTX 5070 Ti (16 GB) with Qwen2.5-7B AWQ at 90% GPU memory, 2026-10-07:
- FP16 KV cache: vLLM allocated 158,048 tokens.
- FP8 KV cache: vLLM allocated 272,304 tokens, 1.7 times as many.
- With 48 users sending 4k-token prompts, FP16 hit 100% KV cache use and preempted 6 requests; FP8 peaked at 65% with no preemptions and ran at 359 tokens/s against 297.

The planner predicted 143,040 FP16 and 286,096 FP8 tokens for this setup, within 10% of what vLLM allocated.
