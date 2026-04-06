# Architecture

This file explains the system in simple terms.

## Main Idea

The app answers some questions by doing research over a local document set. It does not send every question through the full research flow. First it decides whether the question is:

- a normal general question
- or a question that should use the local research docs

## Big Picture

```mermaid
flowchart TD
    U[User] --> N[n8n Webhook]
    N --> F[FastAPI]
    F --> R[/route]
    R --> C{Research or General}
    C -->|General| G[Direct GPT Answer]
    C -->|Research| P[Research Flow]
    P --> O[Final Response]
    G --> O
```

## What Each Part Does

### n8n

n8n is the outside wrapper.

It:

- receives webhook calls
- does a small input check
- forwards the request to FastAPI

It does not run the real research logic.

### FastAPI

FastAPI is the main app.

It:

- checks the input
- decides which path the question should take
- runs the research flow when needed
- returns the final result

### LangGraph

LangGraph runs the step-by-step research flow:

1. plan
2. search
3. shorten notes if needed
4. ask follow-up questions if needed
5. write the final answer

### ChromaDB

ChromaDB stores the local document chunks and helps find the most relevant ones for each smaller question.

## Research Flow

### 1. Plan

The app turns one large question into a few smaller questions. This helps the search step focus on one thing at a time.

### 2. Search

The app searches the local docs for each smaller question.

It also:

- filters weak matches
- avoids re-adding the same chunk again

### 3. Shorten Notes

If the saved notes get too long, the app shortens them so later prompts stay inside the token limit.

### 4. Add More Questions

If the app still has a big gap, it can add a small number of extra questions and search again.

### 5. Write Final Answer

The app writes the final answer using the saved notes.

If no useful evidence was found, it does not pretend the answer came from the local docs.

## Memory Plan

The app keeps memory in three simple layers:

1. current step notes
2. saved evidence chunks
3. shorter summary notes

This is better than just cutting off old text because cutting off old text can remove useful facts too early.

## Limits

The app has clear built-in limits:

- max prompt size per step
- max number of retrieved chunks
- max dollar cost per run
- max number of extra planning rounds

These limits help keep the app:

- cheaper
- easier to predict
- easier to debug

## Safety Choices

I added a few simple safety choices to make the system more trustworthy:

- bad requests fail early
- no-evidence research does not fake grounded answers
- if the run stops early because of cost, the planned sub-questions are still kept

## Why This Fits The Task

The task asked for:

- a research agent
- a memory plan
- clear limits
- workflow tooling
- trade-off notes

This design hits those points while keeping the system understandable and testable.
