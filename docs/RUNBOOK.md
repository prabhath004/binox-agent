# Runbook

This file shows how to run the project and what to check.

## 1. What You Need

- Python `3.11+`
- OpenAI API key
- Docker only if you want to run n8n

## 2. Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Then put your key in `.env`:

```bash
OPENAI_API_KEY=your-key
```

## 3. Build The Local Search Store

```bash
python ingest.py
```

This creates the local Chroma store in `./chroma_store`.

## 4. Run The Tests

```bash
pytest -q
```

Expected:

- all tests pass

## 5. Start The API

```bash
uvicorn app.main:app --reload --port 8000
```

Useful endpoints:

- `GET /health`
- `POST /classify`
- `POST /route`
- `POST /research`
- `GET /docs`

## 6. Quick Checks

### Health

```bash
curl -s http://localhost:8000/health | jq
```

You should see:

- `status: "ok"`
- `openai_configured: true`
- `corpus_chunks` more than `0`

### General question

```bash
curl -s -X POST http://localhost:8000/route \
  -H "Content-Type: application/json" \
  -d '{"query":"what is ramayana"}' | jq
```

Expected:

- `routed_to: "direct_gpt"`

### In-scope research question

```bash
curl -s -X POST http://localhost:8000/route \
  -H "Content-Type: application/json" \
  -d '{"query":"what is cursor vs replit"}' | jq
```

Expected:

- `router_label: "research"`
- `routed_to` is either:
  - `research_pipeline`
  - `direct_gpt_fallback` if the local docs do not contain enough useful evidence

### Run research directly

```bash
curl -s -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"query":"Compare Cursor vs Copilot pricing and risks"}' | jq
```

Expected:

- sub-questions in the response
- budget report in the response
- memory state in the response

## 7. n8n Setup

Start n8n:

```bash
docker-compose up
```

Then:

1. open `http://localhost:5678`
2. import `n8n/workflow.json`
3. turn the workflow on

### Real webhook

Use this for repeated testing:

```bash
curl -s -X POST http://localhost:5678/webhook/research \
  -H "Content-Type: application/json" \
  -d '{"query":"what is cursor vs replit"}' | jq
```

### Test webhook

If you use `/webhook-test/research`, you need to click `Execute workflow` in the n8n UI before each call. That is normal n8n behavior.

## 8. Common Problems

### `/health` says `degraded`

Check:

- `OPENAI_API_KEY` is set
- `python ingest.py` was run
- the Chroma files exist

### A question was routed the wrong way

Check:

- `POST /classify` first
- whether the question is really inside the scope of the local docs
- whether n8n has the latest imported workflow

### n8n test webhook returns `404`

That usually means the test webhook is not armed.

Fix:

- click `Execute workflow` in n8n
- or use `/webhook/research` instead

### Research falls back to direct GPT

That means:

- the router thought the question should use research
- but the local docs did not return enough useful evidence

This is expected safer behavior.

## 9. Reset Local State

To rebuild the local search store:

```bash
rm -rf chroma_store
python ingest.py
```

If the n8n editor looks stale:

1. refresh the page
2. reopen the workflow
3. discard unsaved changes if asked
4. re-import `n8n/workflow.json` if needed

## 10. Final Note

This setup is meant for local testing and assessment review. It is not a locked-down production deployment.
