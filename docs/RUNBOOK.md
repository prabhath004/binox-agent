# Runbook

This runbook is intended for evaluators and maintainers who want to reproduce the system quickly and understand the expected runtime behavior.

## 1. Prerequisites

- Python `3.11+`
- OpenAI API key
- Optional: Docker if you want to run n8n locally

## 2. Local Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`.

## 3. Ingest the Corpus

```bash
python ingest.py
```

This builds the local Chroma store under `./chroma_store`.

## 4. Run Tests

```bash
pytest -q
```

Expected result:

- all tests pass

## 5. Start the API

```bash
uvicorn app.main:app --reload --port 8000
```

Useful endpoints:

- `GET /health`
- `POST /classify`
- `POST /route`
- `POST /research`
- `GET /docs`

## 6. Verification Checklist

### Health

```bash
curl -s http://localhost:8000/health | jq
```

Expected:

- `status: "ok"`
- `openai_configured: true`
- `corpus_chunks` greater than `0`

### Route a general query

```bash
curl -s -X POST http://localhost:8000/route \
  -H "Content-Type: application/json" \
  -d '{"query":"what is ramayana"}' | jq
```

Expected:

- `routed_to: "direct_gpt"`

### Route an in-scope product query

```bash
curl -s -X POST http://localhost:8000/route \
  -H "Content-Type: application/json" \
  -d '{"query":"what is cursor vs replit"}' | jq
```

Expected:

- `router_label: "research"`
- `routed_to` is either:
  - `research_pipeline`
  - `direct_gpt_fallback` if no evidence was found

### Run the research endpoint directly

```bash
curl -s -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"query":"Compare Cursor vs Copilot pricing and risks"}' | jq
```

Expected:

- sub-questions present
- budget report present
- memory state present

## 7. n8n Setup

Start n8n:

```bash
docker-compose up
```

Then:

1. open `http://localhost:5678`
2. import `n8n/workflow.json`
3. activate the workflow

### Real webhook

For repeatable requests, use:

```bash
curl -s -X POST http://localhost:5678/webhook/research \
  -H "Content-Type: application/json" \
  -d '{"query":"what is cursor vs replit"}' | jq
```

### Test webhook

If using `/webhook-test/research`, you must click `Execute workflow` in the n8n editor before each call. This is normal n8n behavior.

## 8. Troubleshooting

### `status: degraded` on `/health`

Check:

- `OPENAI_API_KEY` is set
- `python ingest.py` has been run
- Chroma store exists and is readable

### Query unexpectedly routed to general

Check:

- whether the query is truly in scope of the corpus
- `POST /classify` output directly
- whether the n8n workflow was refreshed after importing changes

### n8n returns `404` for `/webhook-test/research`

This happens when the test webhook is not currently armed. Use one of:

- click `Execute workflow` and retry
- use the real `/webhook/research` endpoint instead

### Research returns fallback direct answer

This means:

- the router considered the query in-scope
- but Chroma retrieval returned no usable evidence

That is safer than fabricating a grounded answer and is expected behavior.

## 9. Resetting Local State

If you want to rebuild the vector store from scratch:

```bash
rm -rf chroma_store
python ingest.py
```

If n8n editor state appears stale:

1. refresh the page
2. reopen the workflow
3. discard unsaved changes if prompted
4. re-import `n8n/workflow.json` if needed

## 10. Operational Notes

- `docker-compose.yml` is for local development/demo use
- n8n basic auth is disabled there for convenience and should be enabled in any shared environment
- the current setup is optimized for reproducibility of the assessment, not hardened production deployment
