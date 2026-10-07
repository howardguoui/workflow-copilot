---
type: tool
name: search_filings
---
Searches answers that Filings RAG produced from the companies' 10-K filings and returns the closest one with its source sections. Input: the question.

The answers were recorded from real runs of Filings RAG (hybrid pgvector search, reranking, Qwen3 8B on an RTX 5070 Ti).
