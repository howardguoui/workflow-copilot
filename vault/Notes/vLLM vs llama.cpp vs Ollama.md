---
type: note
source: https://github.com/howardguoui/local-inference-lab/blob/main/results/latest.md
---
# vLLM vs llama.cpp vs Ollama

Measured with Local Inference Lab on an RTX 5070 Ti (16 GB), all serving Qwen2.5-7B at 4-bit, chat requests of about 480 prompt tokens and 256 output tokens, 2026-10-07.

At 16 concurrent users:
- vLLM with FP8 KV cache: 1,209.9 tokens/s, median time to first token 0.87 s.
- vLLM with FP16 KV cache: 1,092.4 tokens/s, median time to first token 0.89 s.
- llama.cpp with F16 KV cache: 527.4 tokens/s, median time to first token 4.36 s.
- Ollama: 99.1 tokens/s, median time to first token 37.13 s.

With one user all four are close (115 to 128 tokens/s). vLLM batches up to 64 requests; llama.cpp and Ollama ran 8 parallel slots, so extra requests waited in a queue.
