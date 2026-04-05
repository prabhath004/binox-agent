# Deep Research Agent — Budget-Constrained Pipeline

A research agent that answers complex questions by decomposing them into sub-questions, retrieving evidence from a vector database, compressing memory to stay within token/cost limits, and producing a structured report with sources and trade-offs.

## Architecture

```
POST /research
   │
   ▼
┌──────────┐    ┌───────────┐    ┌────────────┐    ┌──────────┐    ┌─────────────┐
│  Planner │───▶│ Retriever │───▶│ Compressor │───▶│ Replanner│───▶│ Synthesizer │
│          │    │           │    │            │    │          │    │             │
│ Decompose│    │ Chroma DB │    │ Summarize  │    │ Add new  │    │ Final report│
│ query    │    │ top-k per │    │ if over    │    │ questions│    │ with budget │
│ into 3-6 │    │ sub-q     │    │ token limit│    │ if gaps  │    │ stats       │
│ sub-q's  │    │           │    │            │    │          │    │             │
└──────────┘    └───────────┘    └────────────┘    └──────────┘    └─────────────┘
```

**Orchestration:** LangGraph state graph with conditional edges  
**Retrieval:** ChromaDB with cosine similarity + relevance filtering  
**Memory:** Three-tier (working → evidence → compressed) with LLM summarization  
**Budget:** Hard limits on tokens, chunks, cost, and replans  

## Quick Start

### 1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Set your API key

```bash
cp .env.example .env
# Edit .env and add your OpenAI API key
export OPENAI_API_KEY=sk-your-key-here
```

### 3. Ingest the sample corpus

```bash
python ingest.py
```

This loads 12 markdown documents about AI developer tooling into ChromaDB (~50 chunks).

### 4. Run the CLI demo

```bash
python -m app.main "Analyze top AI developer tooling startups, compare pricing, risks, and differentiation."
```

### 5. Run the API server

```bash
uvicorn app.main:app --reload --port 8000
```

Then:

```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"query": "Compare AI coding assistants by pricing and enterprise readiness"}'
```

## Budget Constraints

Every run enforces:

| Constraint | Default | Purpose |
|-----------|---------|---------|
| Max context tokens per step | 2,000 | Keeps each LLM call small |
| Max retrieved chunks total | 8 | Bounds retrieval cost |
| Max cost per run | $0.05 | Hard spending cap |
| Max replans | 2 | Limits agent loops |

When limits are hit:
- Low-relevance chunks are **dropped** before entering memory
- Evidence is **compressed** via LLM summarization into concise notes
- Retrieval **stops early** if chunk or cost budget is exhausted
- The final report **documents** what was skipped and why

## Pipeline Stages

### 1. Planner (`app/planner.py`)
Decomposes the user question into a JSON plan:
```json
{
  "objective": "Compare AI coding assistants...",
  "sub_questions": [
    "Who are the top AI coding assistant startups?",
    "What does each product offer?",
    "How do their pricing models compare?",
    "What are the key risks for each?",
    "How do they differentiate from each other?"
  ],
  "success_criteria": "..."
}
```

### 2. Retriever (`app/retriever.py`)
For each sub-question: embed → query Chroma → filter by relevance threshold → return top-k chunks.

### 3. Memory + Compression (`app/memory.py`)
Three-tier memory:
- **Working memory:** current step context
- **Evidence memory:** chunks from retrieval
- **Compressed summaries:** LLM-generated notes when evidence exceeds token budget

### 4. Replanner (`app/planner.py:maybe_replan`)
After initial retrieval, checks if critical gaps exist. Can add up to 2 new sub-questions (bounded by `max_replans`).

### 5. Synthesizer (`app/synthesizer.py`)
Produces a structured JSON report with: answer, per-sub-question sections, key insights, limitations, sources used, and the full budget report.

## Project Structure

```
binox-research-agent/
├── app/
│   ├── main.py          # FastAPI + LangGraph pipeline
│   ├── planner.py        # Query decomposition + replanning
│   ├── retriever.py      # Chroma RAG with relevance filter
│   ├── memory.py         # Three-tier memory + compression
│   ├── budget.py         # Token/cost/chunk budget tracker
│   ├── synthesizer.py    # Final report generation
│   └── utils.py          # LLM wrapper, JSON parsing
├── data/                 # Sample corpus (12 markdown docs)
├── tests/
│   └── test_pipeline.py  # Unit + integration tests
├── ingest.py             # Corpus → ChromaDB loader
├── evaluation.md         # Architecture trade-offs
├── README.md
├── requirements.txt
└── .env.example
```

## API Docs

Start the server and visit: `http://localhost:8000/docs` (auto-generated Swagger UI)

## Running Tests

```bash
python -m pytest tests/ -v
```
# binox-agent
