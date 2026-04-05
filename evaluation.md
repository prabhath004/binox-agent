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

**Relevance filtering improves quality.** Vector similarity + a cosine distance threshold (0.75) means the synthesizer sees only high-signal evidence, reducing hallucination. Deduplication across sub-questions prevents the same chunk consuming multiple budget slots.

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

## 5. Why LangGraph over n8n/Dify

The reference stack suggests n8n or Dify for query routing and memory management. We chose LangGraph + FastAPI instead because:

**n8n is a trigger layer, not an orchestration engine.** n8n excels at "when X happens, call Y, send result to Z" — webhooks, cron jobs, Slack integration. Our pipeline needs conditional looping (replan → retrieve again if gaps exist), shared mutable state across nodes, and tight budget enforcement between steps. These are code-level concerns, not workflow routing concerns.

**LangGraph handles the conditional loop cleanly.** After the replan node, the graph decides at runtime whether to loop back to retrieval or proceed to synthesis. This conditional edge based on budget state is natural in LangGraph and awkward in a visual workflow tool.

**FastAPI serves the same trigger role.** The `POST /research` endpoint accepts a query and returns a structured report. Any external system (n8n, Slack bot, cron job, frontend) can call it. Adding n8n as a wrapper would add operational complexity (Docker, separate service) without improving the core pipeline.

**If we needed n8n:** It would sit outside the pipeline as a thin integration layer — receiving Slack messages, calling `/research`, and routing results to email/sheets. The research logic would remain unchanged in LangGraph. This separation is intentional: orchestration logic belongs in code, integration logic belongs in a workflow tool.

## 6. Chunking Strategy

We use heading-based splitting with merging and title-prefixing, not recursive text splitting or fixed-size windows.

**Why heading-based?** The corpus is structured markdown with clear `##` sections (Overview, Pricing, Risks, Differentiation). These headings are natural semantic boundaries — splitting at them preserves complete thoughts. Recursive text splitters cut blindly at character limits, breaking mid-paragraph.

**Title prefixing.** Every chunk is prefixed with the company name: `[Cursor]\n## Pricing\n- Pro: $20/month...`. This ensures the embedding vector associates the pricing data with the correct company. Without it, a generic "## Pricing" chunk embeds identically regardless of which company it belongs to, causing the compressor to crosswire attributes between companies.

**Small section merging.** A `## Pricing` section with 3 bullet points (133 chars) is too small to embed well and wastes a retrieval slot. We merge consecutive sections until each chunk exceeds 200 characters. This cut chunks from 77 (21 useless) to 30 (0 useless), raising average chunk size from 279 to 715 characters.

**Result:** Retrieval quality improved dramatically — for "cheapest AI tools", the comparison doc now ranks #1 (distance 0.31) instead of an irrelevant Devin chunk. Company-specific queries now consistently return the correct company's data.

## 7. Design Decisions Summary

| Decision | Choice | Alternative | Why |
|----------|--------|-------------|-----|
| Orchestration | LangGraph | n8n, Dify, raw Python | Conditional loops, shared state, extensible graph |
| Vector DB | ChromaDB | FAISS, Pinecone | Zero config, local, free, sufficient for bounded corpus |
| LLM | gpt-4o-mini | gpt-4o, Claude | Cheapest option with JSON mode support |
| Embedding | Chroma default (MiniLM) | OpenAI text-embedding-3 | Free, local, no API key needed |
| Memory | Summarization cascade | Sliding window, token pruning | Preserves factual claims while reducing size |
| API | FastAPI | Flask, n8n webhook | Auto-docs, async, Pydantic validation |
| Corpus | 12 curated markdown files | Web crawling, PDF parsing | Reproducible, bounded, verifiable results |
| Trigger layer | FastAPI endpoint | n8n/Dify | Simpler ops, same functionality for demo scope |
