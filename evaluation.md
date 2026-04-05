# Evaluation — Architecture Trade-offs

## 1. Why Planner + Retriever + Synthesizer?

The pipeline decomposition (plan → retrieve → compress → synthesize) was chosen over a single-prompt approach for three reasons:

**Modularity.** Each stage has a single responsibility and can be tested, tuned, and swapped independently. The planner can be improved without touching retrieval logic. The compressor can be replaced with a different strategy without affecting synthesis.

**Budget control.** A monolithic prompt that stuffs all context into one call makes it impossible to enforce per-step token limits. The pipeline model lets us measure and compress at each boundary. If evidence exceeds 2,000 tokens after retrieval, we compress before synthesis — the synthesizer never sees an oversized context.

**Observability.** Each stage produces inspectable output: the plan is a JSON object, the retriever returns scored chunks, the compressor logs what it dropped, and the synthesizer reports confidence per section. This makes debugging straightforward and demos convincing.

**Trade-off accepted:** More LLM calls (3–5 per run) means slightly higher latency and cost than a single-shot approach. We mitigate this by using `gpt-4o-mini` (cheap, fast) and keeping `max_tokens` tight at each stage.

## 2. Why Vector Retrieval Instead of Full Context?

Dumping all 12 documents (~8,000 tokens) into a single prompt would technically fit within GPT-4o-mini's 128K context window. We chose vector retrieval anyway because:

**The constraint is the point.** The assignment asks for memory-constrained operation. Retrieval with a top-k limit (8 chunks max) proves we can scale to a corpus 100x larger without changing architecture. Full-context dumping breaks at corpus sizes beyond the context window.

**Relevance filtering improves quality.** Not all documents are relevant to every sub-question. Vector similarity + a cosine distance threshold (0.35) means the synthesizer sees only high-signal evidence, reducing hallucination and improving answer precision.

**Cost scales linearly with retrieval, not corpus size.** With full context, cost grows as O(corpus_size × num_calls). With retrieval, embedding is a one-time cost, and each LLM call receives only the k most relevant chunks.

**Trade-off accepted:** Chroma's default embedding model (all-MiniLM-L6-v2) is fast but not state-of-the-art. For a production system, we'd use a stronger embedding model (e.g., text-embedding-3-large) or add a cross-encoder reranker. The current setup prioritizes simplicity and zero API cost for embedding.

## 3. How the Token/Cost Limit Works

The budget system tracks four dimensions:

| Metric | Limit | Enforcement Point |
|--------|-------|-------------------|
| Context tokens per step | 2,000 | Before each LLM call — compress if exceeded |
| Total retrieved chunks | 8 | During retrieval — stop fetching when limit hit |
| Total cost (USD) | $0.05 | After each LLM call — skip remaining steps if over |
| Replan attempts | 2 | After compression — limit recursive expansion |

**How compression works:**
1. After retrieval, `memory.compress_if_needed()` checks if the combined evidence exceeds 2,000 tokens.
2. If yes, it calls the LLM with a compression prompt: "Summarize these evidence chunks into concise notes under {target} tokens."
3. The compressed summary replaces the raw chunks in evidence memory.
4. The budget tracker logs a `compression_event` so the final report shows it happened.

**How cost is estimated:**
We use OpenAI's actual `usage` field from each API response (`prompt_tokens` and `completion_tokens`). Cost is calculated at gpt-4o-mini rates ($0.15/M input, $0.60/M output). This is not an estimate — it's the real token count from the API.

**Failure modes:**
- If cost limit is hit mid-retrieval: remaining sub-questions are skipped, and the synthesizer works with partial evidence. The report's `limitations` field notes what was missed.
- If all chunks are used: retrieval stops, and the report notes "chunk budget exhausted."
- If compression fails: raw chunks are truncated by character count as a fallback.

## 4. Trade-off: Lower Cost vs. Lower Completeness

This is the central tension of a budget-constrained research agent.

**What we lose with tight budgets:**
- Fewer sub-questions explored (some aspects of the query may be under-covered)
- Compressed evidence loses nuance (specific numbers, quotes, edge cases)
- No reranking step (we use embedding similarity only, no cross-encoder)
- Single-pass synthesis (no iterative refinement of the answer)

**What we gain:**
- Predictable cost: every run stays under $0.05
- Predictable latency: 3–5 LLM calls × ~1s each = under 10 seconds
- Reproducible: same query + same corpus = same plan + same chunks
- Scalable: this architecture works for 12 docs or 12,000 docs without code changes

**The right framing:** A budget-constrained agent is not "worse" — it's honest about its limitations. The final report explicitly states what was skipped, what had low confidence, and what the budget consumed. This is more useful than an unconstrained agent that silently hallucinates to fill gaps.

**Production extension path:**
1. Increase chunk budget to 20–30 for broader coverage
2. Add a reranker (cross-encoder) between retrieval and compression
3. Use `gpt-4o` for synthesis (higher quality, ~10x more expensive)
4. Add iterative refinement: synthesize → evaluate → retrieve more → re-synthesize
5. Implement long-term memory across sessions (persist compressed notes to vector DB)

## 5. Design Decisions Summary

| Decision | Choice | Alternative Considered | Why |
|----------|--------|----------------------|-----|
| Orchestration | LangGraph | Raw Python functions | Explicit state graph, conditional edges, built-in persistence |
| Vector DB | ChromaDB | FAISS, Pinecone | Zero config, local, free, good enough for bounded corpus |
| LLM | gpt-4o-mini | gpt-4o, Claude | Cheapest option that supports JSON mode and function calling |
| Embedding | Chroma default (MiniLM) | OpenAI text-embedding-3 | Free, local, no API key needed for embedding |
| Memory strategy | Summarization cascade | Sliding window, token pruning | Preserves factual claims while reducing size |
| API framework | FastAPI | Flask, no API | Auto-docs, async support, Pydantic validation |
| Corpus | 12 curated markdown files | Web crawling, PDF parsing | Reproducible, bounded, easy to explain in demo |
