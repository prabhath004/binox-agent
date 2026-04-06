# Evaluation — Architecture Trade-offs

## 1. Why Planner + Retriever + Synthesizer?

The pipeline decomposition (plan → retrieve → compress → synthesize) was chosen over a single-prompt approach for three reasons:

**Modularity.** Each stage has a single responsibility and can be tested, tuned, and swapped independently.

**Budget control.** A monolithic prompt makes it impossible to enforce per-step token limits. The pipeline lets us measure and compress at each boundary. If evidence exceeds 800 tokens after retrieval, we compress before synthesis — the synthesizer never sees an oversized context.

**Observability.** Each stage produces inspectable output: the plan is a JSON object, the retriever returns scored chunks, the compressor logs what it dropped, and the synthesizer reports confidence per section.

**Trade-off accepted:** More LLM calls (3–5 per run) means slightly higher latency than a single-shot approach. We mitigate this by using gpt-4o-mini and keeping max_tokens tight at each stage.

## 2. Why Vector Retrieval Instead of Full Context?

Dumping all 12 documents (~8,000 tokens) into a single prompt would fit within GPT-4o-mini's 128K context window. We chose vector retrieval because:

**The constraint is the point.** Retrieval with a top-k limit (20 chunks max) proves we can scale to a corpus 100x larger without changing architecture. Full-context dumping breaks at scale.

**Relevance filtering improves quality.** Vector similarity + a cosine distance threshold (0.75) means the synthesizer sees only high-signal evidence, reducing hallucination. Deduplication across sub-questions and later replan loops prevents the same chunk consuming multiple budget slots.

**Cost scales with retrieval, not corpus size.** Embedding is a one-time cost (using Chroma's local MiniLM model — zero API cost). Each LLM call receives only the most relevant chunks.

**Trade-off accepted:** Chroma's default MiniLM embedding is fast but not state-of-the-art. For production, we'd add a cross-encoder reranker or use text-embedding-3-large.

## 3. How the Token/Cost Limit Works

The budget system tracks four dimensions:

| Metric | Limit | Enforcement Point |
|--------|-------|-------------------|
| Context tokens per step | 800 | Before each LLM call — compress if exceeded |
| Total retrieved chunks | 20 | During retrieval — stop fetching when limit hit |
| Total cost (USD) | $0.05 | After each LLM call — skip remaining steps if over |
| Replan attempts | 2 | After compression — limit recursive expansion |

**Compression flow:** After retrieval, `compress_if_needed()` checks if combined evidence exceeds 800 tokens. If yes, the LLM summarizes it to ~400 tokens. The compressed summary replaces raw chunks. The budget tracker logs a `compression_event`.

**Cost tracking:** We use OpenAI's actual `usage` field from each API response. Cost is calculated at gpt-4o-mini rates ($0.15/M input, $0.60/M output). This is the real token count from the API, not an estimate.

**When limits are hit:**
- Cost limit mid-retrieval → remaining sub-questions skipped, report notes what was missed
- All chunks used → retrieval stops, report notes "chunk budget exhausted"
- Low-relevance chunks → dropped before entering memory, sorted by relevance score
- Zero retrieved evidence → synthesis returns an explicit "no relevant corpus evidence found" result instead of fabricating a grounded answer

## 4. Trade-off: Lower Cost vs. Lower Completeness

**What we lose with tight budgets:**
- Fewer sub-questions explored (some aspects under-covered)
- Compressed evidence loses nuance (specific numbers, edge cases)
- No reranking step (embedding similarity only)
- Single-pass synthesis (no iterative refinement)

**What we gain:**
- Predictable cost: every run stays under $0.05 (typically under $0.002)
- Predictable latency: 3–7 LLM calls at under 60 seconds total
- Reproducible: same query + same corpus = consistent output
- Scalable: architecture works for 12 docs or 12,000 docs

**The right framing:** A budget-constrained agent is not "worse" — it's honest about its limitations. The final report explicitly states what was skipped, what had low confidence, and what the budget consumed.

## 5. How n8n and LangGraph Split Responsibilities

The reference stack suggests "n8n/Dify for query routing + memory management." We use both n8n and LangGraph, but for different jobs:

**n8n handles external concerns:** webhook triggers and integration with external systems (Slack, cron, email). The imported workflow is intentionally thin: validate request, normalize payload, forward to FastAPI `/route`, return the response. This keeps the visual workflow reproducible without duplicating business logic.

**FastAPI handles routing and validation:** query classification, route selection, request validation, zero-evidence fallback, and health reporting. Keeping this in Python gives one source of truth for behavior, which proved more robust than splitting routing logic between code and the visual workflow.

**LangGraph handles internal orchestration:** the 5-node research pipeline with conditional looping, shared state, and budget enforcement. These require code-level control (checking token counts, deciding whether to replan, compressing evidence) that a visual workflow tool cannot express cleanly.

**The split is deliberate.** n8n is the external trigger/proxy. FastAPI is the router. LangGraph is the researcher. Each layer has a clear ownership boundary.

**Fallback without Docker:** The same routing logic is available directly through FastAPI's `/route` endpoint. This ensures the evaluator can test classification and routing without running n8n/Docker.

## 6. Chunking Strategy

We use heading-based splitting with merging and title-prefixing, not recursive text splitting or fixed-size windows.

**Why heading-based?** The corpus is structured markdown with clear `##` sections (Overview, Pricing, Risks, Differentiation). These headings are natural semantic boundaries — splitting at them preserves complete thoughts. Recursive text splitters cut blindly at character limits, breaking mid-paragraph.

**Title prefixing.** Every chunk is prefixed with the company name: `[Cursor]\n## Pricing\n- Pro: $20/month...`. This ensures the embedding vector associates the pricing data with the correct company. Without it, a generic "## Pricing" chunk embeds identically regardless of which company it belongs to, causing the compressor to crosswire attributes between companies.

**Small section merging.** A `## Pricing` section with 3 bullet points (133 chars) is too small to embed well and wastes a retrieval slot. We merge consecutive sections until each chunk exceeds 200 characters. This cut chunks from 77 (21 useless) to 30 (0 useless), raising average chunk size from 279 to 715 characters.

**Result:** Retrieval quality improved dramatically — for "cheapest AI tools", the comparison doc now ranks #1 (distance 0.31) instead of an irrelevant Devin chunk. Company-specific queries now consistently return the correct company's data.

## 7. Reliability Improvements Added After Initial Prototype

The biggest risk in an agentic prototype is not architecture, it is false confidence. Several hardening steps were added to improve evaluator trust:

- **Strict request validation:** blank queries, invalid chunk counts, or nonsensical budget settings are rejected up front by Pydantic instead of producing confusing runtime behavior.
- **Plan-state preservation on hard cutoff:** if the run exceeds cost budget immediately after planning, the final response still retains the objective and sub-questions already produced instead of collapsing back to the raw input query.
- **Zero-evidence safeguard:** if retrieval returns nothing relevant, the research path refuses to synthesize a source-grounded answer. `/route` can then fall back to direct GPT with explicit limitations instead of pretending the corpus answered the question.
- **Automated regression tests:** routing heuristics, zero-evidence handling, duplicate-chunk skipping, validation, and hard-cutoff recovery now have lightweight tests to reduce demo risk.

## 8. Design Decisions Summary

| Decision | Choice | Alternative | Why |
|----------|--------|-------------|-----|
| Orchestration | LangGraph | n8n, Dify, raw Python | Conditional loops, shared state, extensible graph |
| Vector DB | ChromaDB | FAISS, Pinecone | Zero config, local, free, sufficient for bounded corpus |
| LLM | gpt-4o-mini | gpt-4o, Claude | Cheapest option with JSON mode support |
| Embedding | Chroma default (MiniLM) | OpenAI text-embedding-3 | Free, local, no API key needed |
| Memory | Summarization cascade | Sliding window, token pruning | Preserves factual claims while reducing size |
| API | FastAPI | Flask, n8n webhook | Auto-docs, async, Pydantic validation |
| Corpus | 13 curated markdown files | Web crawling, PDF parsing | Reproducible, bounded, verifiable results |
| Query routing | FastAPI `/route` + thin n8n proxy | Hardcoded rules, no routing | Classifies queries, avoids wasting budget on off-topic questions |
