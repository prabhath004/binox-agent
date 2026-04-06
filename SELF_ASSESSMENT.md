# Self-Assessment

This is my honest review of the submission against the rubric.

## Overall View

This project is stronger on clear thinking, structure, and documentation than on full production hardening. It is a solid working prototype with good guardrails.

## 1. Technical Execution

### What went well

- The project is a real working system, not just a prompt wrapper.
- The main parts are separated clearly: routing, planning, search, memory, and final answer writing.
- The app has clear limits for cost, chunk count, prompt size, and extra research rounds.
- Important edge cases are handled better now:
  - bad input fails early
  - no-evidence research does not fake a grounded answer
  - early budget cutoffs still keep the planned sub-questions
- There are tests for the risky behavior that a reviewer is likely to try.

### What is still weaker

- Search is still basic and does not use a reranker.
- OpenAI calls are still sync under the hood.
- There is no full benchmark set for answer quality.
- The setup is still local/demo-friendly more than production-ready.

### My score

`8.3/10`

## 2. Documentation and Reproducibility

### What went well

- The README is now simple and direct.
- The repo includes setup steps, architecture docs, a runbook, trade-off notes, and this self-review.
- The commands to verify the system are easy to copy and run.
- The document set is fixed, which makes the system easier to reproduce.

### What is still weaker

- A one-command setup script would make local setup even easier.

### My score

`9.0/10`

## 3. Creativity and Constraint Handling

### What went well

- I did not solve this with one large prompt.
- The memory plan is part of the design, not an afterthought.
- The app routes off-topic questions away from the research flow.
- The app prefers a safe answer over a fake grounded answer.

### What is still weaker

- There is room for a more advanced memory or ranking approach.

### My score

`8.5/10`

## 4. Business Impact Reasoning

### What went well

- The design keeps cost and time predictable.
- The split between n8n and FastAPI is based on reliability, not just tool hype.
- Routing exists for a practical reason: do not waste time and money on the wrong path.

### What is still weaker

- I did not include a deeper ROI model with expected traffic and cost ranges.

### My score

`8.3/10`

## Weighted Overall Score

Approximate overall score:

`8.5/10`

## What I Would Improve Next

1. Add a reranker on top of search.
2. Add a small answer-quality benchmark set.
3. Move model calls to a truly async path.
4. Add stronger deployment notes for a shared environment.
5. Expand the routing test set.

## Final Honest Claim

This is not a finished production product, but it is strong enough to defend in review because the design is clear, the limits are explicit, the failure cases are safer, and the docs are easy to follow.
