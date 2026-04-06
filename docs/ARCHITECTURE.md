# Architecture

This document describes the system beyond the high-level README. It focuses on component responsibilities, request flow, memory behavior, and failure handling.

## 1. Component Map

```mermaid
flowchart TD
    U[External Caller] --> N[n8n Webhook]
    N --> F[FastAPI]

    subgraph API[FastAPI Layer]
        F --> R[/route]
        F --> C[/classify]
        F --> Q[/research]
        F --> H[/health]
    end

    R --> ROUTER[Router]
    ROUTER -->|general| GPT[Direct GPT Answer]
    ROUTER -->|research| GRAPH[LangGraph Pipeline]

    subgraph PIPE[LangGraph Pipeline]
        GRAPH --> P[Planner]
        P --> RET[Retriever]
        RET --> MEM[Memory Store]
        MEM --> COMP[Compressor]
        COMP --> REP[Replanner]
        REP -->|new questions| RET
        REP -->|done| SYN[Synthesizer]
    end

    RET --> CHROMA[ChromaDB]
    SYN --> OUT[Response]
    GPT --> OUT
```

## 2. Request Flows

### General query

1. Request enters through FastAPI `/route` directly or through the n8n webhook.
2. Router classifies the query as `general`.
3. The system calls direct GPT answer generation.
4. Response is returned with `routed_to: "direct_gpt"`.

### In-scope research query

1. Request enters `/route`.
2. Router classifies the query as `research`.
3. LangGraph research pipeline runs:
   - plan
   - retrieve
   - compress if needed
   - replan if needed
   - synthesize
4. Response is returned with `routed_to: "research_pipeline"`.

### Research query with zero evidence

1. Request enters `/route`.
2. Router classifies the query as `research`.
3. Research pipeline runs but retrieval finds no usable evidence.
4. Synthesizer refuses to fabricate a grounded answer.
5. `/route` can return a safe fallback direct answer with explicit limitations and preserved research budget state.

## 3. Why the System Uses Two Front Doors

### FastAPI

FastAPI is the authoritative runtime surface. It owns:

- validation
- routing behavior
- research execution
- health reporting
- API docs

### n8n

n8n exists as the integration shell. It is intentionally thin and does not duplicate business logic. That keeps routing behavior consistent whether the query comes from:

- curl
- Swagger
- n8n
- future Slack or automation hooks

## 4. Research Pipeline Stages

### Planner

Turns one user question into a small set of searchable sub-questions plus an objective. This reduces the chance that retrieval misses important aspects of a compound question.

### Retriever

Queries ChromaDB for each pending sub-question. Applies:

- top-k retrieval
- relevance threshold
- duplicate suppression

Duplicate suppression now covers both:

- duplicates across multiple sub-questions
- duplicates across later replan loops

### Memory Store

The memory store tracks:

- raw evidence chunks
- compressed summaries
- skipped chunks due to budget pressure
- working notes

### Compressor

If accumulated evidence exceeds the configured context budget, evidence is compressed into dense research notes. This makes later prompts smaller and cheaper.

### Replanner

Examines coverage gaps after retrieval and compression. Adds new sub-questions only when necessary, and only up to the configured replan limit.

### Synthesizer

Builds the final structured answer from the current memory state. It now has a strict zero-evidence safeguard: no evidence means no claim of grounded research.

## 5. Memory Model

```text
Tier 1: Working Context
  Short-lived per-step prompt state

Tier 2: Evidence Chunks
  Raw retrieved facts across steps

Tier 3: Compressed Summaries
  Durable, condensed research notes used when token pressure increases
```

Why this design:

- better than truncation
- cheaper than re-sending all raw evidence
- still keeps the answer grounded in retrieved material

## 6. Constraint Enforcement

The project is intentionally explicit about constraints.

| Dimension | Mechanism |
|---|---|
| Tokens | `needs_compression()` and prompt trimming |
| Cost | `BudgetTracker` with post-call accounting |
| Retrieved chunks | bounded through `remaining_chunks()` |
| Replans | bounded through `can_replan()` |

If the cost limit is breached, the graph stops and the current best-known state is used for early synthesis.

## 7. Reliability Decisions

Several implementation choices were made specifically to reduce evaluator-facing failure modes.

### Strict request validation

Blank queries and invalid numeric settings are rejected early.

### Plan snapshot preservation

If budget is exceeded immediately after planning, the final response still contains the planned objective and sub-questions.

### Zero-evidence behavior

If retrieval returns nothing relevant:

- synthesis does not invent grounded claims
- the router can fall back to a clearly labeled general-knowledge answer instead

### Threadpool boundary

The app keeps synchronous OpenAI calls out of the main FastAPI event loop by using `run_in_threadpool()` at the API boundary.

## 8. Why This Architecture Fits the Assessment

The assessment asks for:

- complex query handling
- memory strategy under constraints
- workflow/orchestration tooling
- documented trade-offs

This architecture satisfies those goals while keeping the core behavior testable and bounded. It is intentionally stronger on clarity and reliability than on maximal agent autonomy.
