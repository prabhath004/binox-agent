# Evaluation

## Short Version

I built this project to be careful, not flashy.

The goal was to answer harder questions using a small local document set, while staying inside clear limits for cost, tokens, and retrieved context. I chose a step-by-step flow because it is easier to control and explain than one large prompt.

## 1. Why I Used Steps Instead of One Big Prompt

The app works like this:

1. break the question into smaller parts
2. search the local docs
3. shorten the notes if they get too long
4. ask a few extra follow-up questions if needed
5. write the final answer

I chose this because it gives me:

- better control
- clearer failure points
- easier testing
- easier budget handling

The downside is that it takes more model calls and can be slower than a single prompt.

## 2. Why I Used Search Instead of Sending All Docs at Once

I could have put the whole document set into one long prompt, but that would miss the point of the task.

I used local search because:

- the task is about working under limits
- it scales better if the document set grows
- it keeps prompts smaller
- it makes cost easier to predict

The downside is that search is not perfect. If the search step misses something, the final answer can miss it too.

## 3. Why I Used This Memory Plan

I used a simple three-part memory plan:

- current step notes
- saved evidence chunks
- shorter summary notes when the evidence gets too large

I chose this over simple truncation because truncation throws away earlier facts too easily. For research questions, that is risky because the first useful pricing or risk detail might disappear before the final answer is written.

The downside is that shortening notes can still lose detail.

## 4. How The Limits Work

The app has four clear limits:

| Limit | Default |
|---|---|
| Max context per step | `800` tokens |
| Max retrieved chunks | `20` |
| Max run cost | `$0.05` |
| Max extra planning rounds | `2` |

When limits are hit:

- large notes are shortened
- lower-priority chunks are skipped
- the run can stop early if cost is reached
- the app stops adding more follow-up questions

I added a few safety fixes after the first version:

- bad inputs now fail early
- if the run stops early on cost, the planned sub-questions are still kept
- if no useful evidence is found, the app does not fake a grounded answer

## 5. Why FastAPI Owns The Routing

The task mentioned `n8n/Dify` for routing and memory work. I still used n8n, but I did not leave the core routing logic there.

Final split:

- `n8n`: receives the webhook call and forwards it
- `FastAPI /route`: decides if the question should use research or a normal GPT answer
- `LangGraph`: runs the research flow

I made this choice because putting routing logic in both code and n8n made the system harder to trust. Keeping the real logic in Python gave me one source of truth and made the behavior easier to test.

This is slightly less literal to the prompt wording, but it is a stronger engineering choice.

## 6. Why I Added A Zero-Evidence Guard

One of the worst failure modes in this kind of project is a polished answer that sounds grounded but is not actually based on the local docs.

To avoid that:

- if research finds no useful evidence, the app does not pretend the docs answered the question
- the app can return a clear fallback answer with a note saying the research docs did not contain enough evidence

I would rather have a safer answer with a limitation note than a confident answer built on nothing.

## 7. Business Reasoning

Even though this is a small assessment project, I still made choices with real product trade-offs in mind.

Why route questions at all:

- saves money
- saves time
- avoids searching the docs for clearly off-topic questions

Why keep clear limits:

- easier to predict cost
- easier to debug
- easier to explain to a client or reviewer

Why use a small curated document set:

- easier to reproduce
- easier to inspect
- easier to evaluate fairly

## 8. What Is Still Missing

This project is solid, but not perfect.

Main gaps:

- no reranker on top of the search step
- no large answer-quality benchmark set
- the OpenAI client is still sync under the hood
- local n8n setup is demo-friendly, not production-hardened
- the document set is small and hand-picked

## 9. Final View

The best thing about this project is not that it tries to do everything.

The best thing is that it is:

- bounded
- understandable
- testable
- honest about what it knows and does not know

That is the kind of shape I wanted for this task.
