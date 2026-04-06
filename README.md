# Deep Research Agent — Budget-Constrained Pipeline

An AI research agent that answers complex questions by decomposing them into sub-questions, retrieving evidence from a vector database, compressing memory under strict token/cost constraints, and producing a structured report with sources and trade-offs.

Built with LangGraph (orchestration), ChromaDB (retrieval), OpenAI gpt-4o-mini (planning + synthesis), and FastAPI (API layer).

## Architecture

```
User Question
     │
     ▼
┌──────────┐     ┌───────────┐     ┌────────────┐     ┌──────────┐     ┌─────────────┐
│  PLANNER │────▶│ RETRIEVER │────▶│ COMPRESSOR │────▶│ REPLANNER│────▶│ SYNTHESIZER │
│          │     │           │     │            │     │          │     │             │
│ Break    │     │ Search    │     │ If evidence│     │ Gaps in  │     │ Write final │
│ question │     │ ChromaDB  │     │ > 800 tok  │     │ evidence?│     │ report from │
│ into 3-6 │     │ per sub-q │     │ → LLM      │     │ → add    │     │ compressed  │
│ sub-q's  │     │ dedup +   │     │ summarize  │     │ sub-q's  │     │ evidence    │
│          │     │ filter    │     │ to ~400 tok│     │ (max 2x) │     │             │
└──────────┘     └───────────┘     └────────────┘     └─────┬────┘     └─────────────┘
                                                            │
                                                     ┌──────┴──────┐
                                                     │  New sub-q? │
                                                     │  Budget ok? │
                                                     └──────┬──────┘
                                                       YES  │  NO
                                                       ▼    ▼
                                                  RETRIEVER  SYNTHESIZER
                                                  (loop)     (finish)
```

**Orchestration:** LangGraph `StateGraph` with 5 nodes and a conditional loop edge.
**Retrieval:** ChromaDB with cosine similarity, cross-query deduplication, and relevance filtering (threshold 0.75).
**Memory:** Three-tier system (working → evidence → compressed) using LLM-powered summarization cascade.
**Budget:** 4 hard limits enforced at every pipeline node, with automatic cutoff on violation.

## Quick Start

```bash
# 1. Setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. API key
cp .env.example .env
# Edit .env → paste your OpenAI API key

# 3. Ingest the corpus into ChromaDB (one-time)
python ingest.py

# 4. Run a research query
python -m app.main "Analyze top AI developer tooling startups, compare pricing, risks, and differentiation."

# 5. Or start the API server
uvicorn app.main:app --reload --port 8000
```

## Pipeline Stages

### 1. Planner (`app/planner.py`)
Takes the user question and outputs a JSON plan with 3-6 focused sub-questions. Each sub-question is designed to be independently searchable against the corpus.

**Input:** "Compare Cursor, Devin, Windsurf pricing and risks"
**Output:**
```json
{
  "objective": "Compare pricing and risks of Cursor, Devin, and Windsurf",
  "sub_questions": [
    "What are the pricing structures for Cursor, Devin, and Windsurf?",
    "What are the key risks for each tool?",
    "How do they differentiate in the market?"
  ]
}
```

### 2. Retriever (`app/retriever.py`)
For each sub-question: embeds the query (locally via Chroma's MiniLM model), searches the vector DB, filters by relevance, and deduplicates across sub-questions.

- **Relevance filter:** Cosine distance > 0.75 → dropped
- **Deduplication:** Same chunk appearing for multiple sub-questions is only counted once
- **Budget enforcement:** Stops when chunk limit (20) is hit

### 3. Compressor (`app/memory.py`)
If combined evidence exceeds 800 tokens, the compressor calls the LLM to summarize it into ~400 tokens of structured notes.

**What it keeps:** Company names, prices, risks, differentiators, source citations.
**What it removes:** Marketing language, filler paragraphs, redundant descriptions.

This is a **summarization cascade** — evidence flows through compression at every loop iteration, keeping the context window small and focused.

### 4. Replanner (`app/planner.py`)
After retrieval + compression, the replanner examines the evidence and decides if critical gaps exist. If yes, it adds up to 2 new sub-questions and loops back to the retriever. Limited to 2 replans to prevent infinite loops.

### 5. Synthesizer (`app/synthesizer.py`)
Produces the final structured report using only the compressed evidence (never the raw corpus). The output includes:
- 3-paragraph answer with inline source citations
- Per-sub-question findings with confidence levels
- Key insights and limitations
- Full budget report

## Memory Strategy

Three-tier memory with summarization cascade:

```
Tier 1 — Working Memory (per step)
  Current sub-question context. Rebuilt each step. Small.

Tier 2 — Evidence Memory (across steps)
  Retrieved chunks from ChromaDB. Accumulates during retrieval.
  When it exceeds 800 tokens → compressed into Tier 3.

Tier 3 — Compressed Summaries (persistent)
  LLM-generated bullet-point notes. Replaces raw evidence after compression.
  Preserves facts and sources, removes filler. ~400 tokens.
  This is what the synthesizer reads.
```

**Why not just keep everything?** Two reasons:
1. **Cost** — sending 2,600 tokens to the LLM costs more than sending 400
2. **Quality** — LLMs lose focus on long inputs. Shorter, cleaner evidence produces better answers

**Trade-off accepted:** Compression loses detail (exact quotes, edge cases). We mitigate this by instructing the compressor to preserve company names, specific prices, and source citations. The final report's limitations field flags what evidence was insufficient.

## Budget System

Four hard limits, all self-defined and configurable per request:

| Constraint | Default | Enforcement | What happens when hit |
|---|---|---|---|
| Context tokens/step | 800 | Before each LLM call | Evidence compressed to ~400 tokens |
| Retrieved chunks | 20 | During retrieval | Low-relevance chunks dropped, retrieval stops |
| Cost per run | $0.05 | After every LLM call | **Hard cutoff** — agent stops, synthesizes immediately |
| Replans | 2 | Before replan | No more loop-backs, straight to synthesis |

**Hard cutoff:** If cost exceeds $0.05 at ANY pipeline node, a `BudgetExceeded` exception fires, the agent stops all processing, and immediately synthesizes a report from whatever evidence it has. The report documents the cutoff.

**Cost tracking:** Uses OpenAI's actual `usage` field from API responses — real token counts, not estimates. Calculated at gpt-4o-mini rates ($0.15/M input, $0.60/M output).

**Budget is overridable via API:**
```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"query": "...", "max_context_tokens": 500, "max_chunks": 10, "max_cost_usd": 0.01, "max_replans": 1}'
```

## Chunking Strategy

Heading-based splitting with small-section merging and title prefixing.

1. **Split on `##` headings** — each markdown section becomes a candidate chunk
2. **Drop title-only chunks** — headings under 150 chars with no content are removed
3. **Merge small sections** — consecutive sections under 200 chars are merged until they're meaningful
4. **Prepend company name** — every chunk starts with `[CompanyName]` so embeddings associate facts with the correct entity
5. **Split oversized chunks** — anything over 1200 chars is split with 20-word overlap

**Result:** 30 high-quality chunks (avg 715 chars) from 13 docs. Zero useless chunks.

## Corpus

13 curated markdown documents about AI developer tooling startups:

| Doc | Topic |
|---|---|
| `01_cursor.md` – `10_bolt.md` | Individual startup profiles (overview, product, pricing, risks, differentiation) |
| `11_market_overview.md` | Market size, trends, competitive landscape |
| `12_pricing_comparison.md` | Side-by-side pricing for all 10 startups |
| `13_tool_comparison.md` | Direct comparison: cheapest to most expensive, trade-offs, risk by price tier |

To use a different corpus, replace the files in `data/` and re-run `python ingest.py`.

## Example Output

```
Query: "What are the cheapest AI coding tools and what do you lose by going cheap?"

SUB-QUESTIONS: 5 initial → 9 after 2 replans

ANSWER:
The cheapest AI coding tools include Continue (free), Cody ($9/mo),
and GitHub Copilot ($10/mo). While low-cost tools like Cody offer
unlimited autocomplete and chat, they come with trade-offs: Cody has
limited IDE integration, Copilot limits control as a plugin, and
Tabnine's local models are less capable than cloud alternatives...

BUDGET: $0.0024 spent | 20/20 chunks | 3 compressions | 2 replans
```

## API Reference

**`POST /research`** — Run a research query

Request:
```json
{"query": "your research question", "max_cost_usd": 0.05, "max_chunks": 20, "max_context_tokens": 800, "max_replans": 2}
```

Response:
```json
{"answer": "...", "sub_questions": [...], "sections": [...], "key_insights": [...], "limitations": [...], "sources_used": [...], "budget_report": {...}, "memory_state": {...}, "elapsed_seconds": 35.2}
```

**`POST /route`** — Smart query router (classifies query, routes to RAG pipeline or direct GPT)

```bash
# AI dev tools query → routes to research pipeline
curl -X POST http://localhost:8000/route \
  -H "Content-Type: application/json" \
  -d '{"query": "Compare Cursor vs Copilot pricing"}'
# Response includes: "routed_to": "research_pipeline"

# General query → routes to direct GPT
curl -X POST http://localhost:8000/route \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the capital of France?"}'
# Response includes: "routed_to": "direct_gpt"
```

**`GET /health`** — Health check

**`GET /docs`** — Interactive Swagger documentation

## n8n Integration (Query Routing + Memory Management)

n8n serves as the external workflow layer for query routing and trigger management, as specified in the reference stack.

### What n8n does

1. **Query routing** — Classifies incoming queries via OpenAI. Routes AI dev tools questions to the `/research` RAG pipeline. Routes general questions to direct GPT. Prevents wasting budget on queries the corpus can't answer.
2. **Trigger layer** — The webhook endpoint can be called from Slack, cron jobs, or any external system.
3. **Input validation** — Rejects malformed requests before they hit the pipeline.

### Setup

```bash
# Terminal 1: Start FastAPI
uvicorn app.main:app --port 8000

# Terminal 2: Start n8n (requires Docker)
docker-compose up

# Open n8n at http://localhost:5678
# Import n8n/workflow.json via Settings → Import Workflow
# Activate the workflow
```

### Test via n8n

```bash
# AI dev tools query → routed to research pipeline
curl -X POST http://localhost:5678/webhook/research \
  -H "Content-Type: application/json" \
  -d '{"query": "Compare Cursor vs Copilot pricing"}'

# General query → routed to direct GPT
curl -X POST http://localhost:5678/webhook/research \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the capital of France?"}'
```

### Without Docker

The same routing logic is available directly via the FastAPI `/route` endpoint — no n8n or Docker required. The n8n workflow and the `/route` endpoint implement identical logic.

## Project Structure

```
├── app/
│   ├── main.py          # FastAPI + LangGraph pipeline (5 nodes, conditional loop)
│   ├── planner.py        # Query decomposition + replanning
│   ├── retriever.py      # ChromaDB search + dedup + relevance filtering
│   ├── memory.py         # Three-tier memory + LLM compression
│   ├── budget.py         # Token/cost/chunk tracker + hard cutoff
│   ├── synthesizer.py    # Evidence-grounded report generation
│   ├── router.py         # Query classification + routing (RAG vs direct GPT)
│   └── utils.py          # OpenAI wrapper + JSON parsing
├── n8n/
│   └── workflow.json     # Importable n8n workflow (query router)
├── data/                 # 13 markdown docs (AI dev tooling corpus)
├── docker-compose.yml    # n8n container setup
├── ingest.py             # Heading-based chunking + ChromaDB ingestion
├── evaluation.md         # Architecture trade-offs
├── requirements.txt      # Pinned dependencies
└── .env.example          # API key placeholder
```

## Tech Stack

| Component | Choice | Why |
|---|---|---|
| Orchestration | LangGraph | Conditional loop (replan → retrieve), shared state graph |
| Query Routing | n8n + FastAPI /route | Classifies queries, routes to RAG or direct GPT |
| Vector DB | ChromaDB | Free, local, zero-config, built-in MiniLM embeddings |
| LLM | gpt-4o-mini | Cheapest OpenAI model with JSON mode — ~$0.002/run |
| Embeddings | Chroma default (MiniLM-L6-v2) | Free, local, no API key needed |
| API | FastAPI | Auto-generated docs, async, Pydantic validation |
| Workflow | n8n | Webhook triggers, query classification, external integrations |
