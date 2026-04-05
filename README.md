# Deep Research Agent — Budget-Constrained Pipeline

A research agent that decomposes complex questions into sub-questions, retrieves evidence from a vector database, compresses memory to stay within token/cost limits, and produces a structured report with sources.

## Architecture

```
POST /research
   │
   ▼
┌────────┐   ┌───────────┐   ┌────────────┐   ┌──────────┐   ┌─────────────┐
│ Planner│──▶│ Retriever │──▶│ Compressor │──▶│ Replanner│──▶│ Synthesizer │
│        │   │           │   │            │   │          │   │             │
│ 3-6    │   │ ChromaDB  │   │ LLM summary│   │ Add new  │   │ JSON report │
│ sub-q's│   │ top-k/q   │   │ if >800 tok│   │ if gaps  │   │ + budget    │
└────────┘   └───────────┘   └────────────┘   └──────────┘   └─────────────┘
```

**Orchestration:** LangGraph state graph with conditional edges
**Retrieval:** ChromaDB with cosine similarity + deduplication + relevance filtering
**Memory:** Three-tier (working → evidence → compressed) with LLM summarization
**Budget:** Hard limits on tokens, chunks, cost, and replans

## Quick Start

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Set API key
cp .env.example .env
# Edit .env with your OpenAI key

# Ingest corpus
python ingest.py

# Run CLI demo
python -m app.main "Analyze top AI developer tooling startups, compare pricing, risks, and differentiation."

# Or start API server
uvicorn app.main:app --reload --port 8000
```

## Budget Constraints

| Constraint | Default | Purpose |
|-----------|---------|---------|
| Context tokens per step | 800 | Triggers compression when exceeded |
| Retrieved chunks total | 20 | Bounds retrieval cost, drops low-relevance |
| Cost per run | $0.05 | Hard spending cap |
| Replans | 2 | Limits agent loops |

When limits are hit: chunks are dropped by relevance score, evidence is compressed via LLM summarization, retrieval stops early, and the report documents what was skipped.

## API

```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"query": "Compare AI coding assistants by pricing and enterprise readiness"}'
```

Swagger docs at `http://localhost:8000/docs`

## Project Structure

```
├── app/
│   ├── main.py          # FastAPI + LangGraph pipeline
│   ├── planner.py        # Query decomposition + replanning
│   ├── retriever.py      # ChromaDB search + dedup + filtering
│   ├── memory.py         # Three-tier memory + compression
│   ├── budget.py         # Token/cost/chunk budget tracker
│   ├── synthesizer.py    # Final report generation
│   └── utils.py          # LLM wrapper
├── data/                 # 13 markdown docs (AI dev tooling corpus)
├── ingest.py             # Corpus → ChromaDB loader
├── evaluation.md         # Architecture trade-offs
├── requirements.txt
└── .env.example
```
