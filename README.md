# Research Assistant

Turns user-interview transcripts into insights you can trust. Every insight links to the exact quote it is based on, and every quote is checked against the source before anyone sees it.

**Prototype.** Built in a day to learn a production-style AI stack. Use synthetic data only. The short, non-technical story of how and why I built it is in [HOW-I-BUILT-IT.md](HOW-I-BUILT-IT.md).

Live demo: [semtip.nl/koos](https://semtip.nl/koos) · Example result without an AI call: [semtip.nl/koos#example](https://semtip.nl/koos#example)

## Why

AI is good at summarizing interviews, but designers rightly don't trust a summary they can't trace back. If one quote is invented, the whole synthesis is suspect. So this tool treats the model as an **untrusted narrator**:

- **Who said what is decided by code, not by the model.** Each transcript gets a participant ID (P1, P2, ...) before the model sees it.
- **Every quote must literally exist** in that participant's own lines, or it is rejected.
- **When quotes fail, the model is told exactly which ones and why**, and gets one retry. Whatever is still wrong after that is shown, not hidden.

## How it works

```
React + TypeScript  ──POST /api/analyze──▶  FastAPI
                                              │
                    1. Pseudonymize           │  names → P1 / Interviewer, emails → [EMAIL], phones → [PHONE]
                    2. LLM, structured output │  PydanticAI + Pydantic schema (Gemini by default)
                    3. Verify every quote     │  normalized exact match, inside the participant's own lines
                       ├─ failures? ──▶ tell the model which quotes failed, retry once
                    4. Label and sort         │  verified / near match / wrong person / not in source
                                              ▼
                    Insights + quotes + the exact text the model saw (with highlights)
```

| Piece | Choice | Why |
|---|---|---|
| API | FastAPI | Typed request/response contracts, async, the same app runs on Vercel, in Docker and locally |
| LLM layer | PydanticAI with a Pydantic output schema | Schema-validated output plus an output validator that can send precise feedback to the model. Model-agnostic: `LLM_MODEL` is a fallback chain, and switching to Groq or a local Ollama model is a config change, not a rewrite |
| Quote check | Normalized substring match, RapidFuzz for near matches | Exact match is "verified". A close paraphrase (90%+) is shown in amber as a near match and never counted as verified |
| Frontend | React + TypeScript (Vite) | Click any quote to see it highlighted in the transcript the model actually saw |
| Progress | `POST /api/analyze/stream`, newline-delimited JSON events | The UI shows real steps as they happen (privacy, which model is reading, a model being busy and the next one taking over, the quote check), not a fake timer. Cancel closes the stream and stops the run, so no quota is wasted |
| Packaging | Dockerfile (frontend build + API in one image) | Runs anywhere. The public demo runs as a Vercel Python function |

### Quote statuses

| Status | Meaning |
|---|---|
| Verified | Found verbatim (ignoring case, whitespace and quote-mark style) in the claimed participant's own lines |
| Near match | 90%+ similar but not exact. Shown, not counted as verified |
| Wrong person | Found verbatim, but said by a different participant |
| Not in source | Not in the transcript, or only in the interviewer's lines |

An insight with no verified or near-match quote is **dropped**, and shown greyed out at the bottom instead of disappearing.

## Data handling

- Speaker names (from labels and header lines), email addresses and phone numbers are replaced **before** the LLM call. Quotes are verified against that pseudonymized text, so what you see is exactly what the model saw.
- Nothing is stored. No database, no logs of transcript content.
- This is **pseudonymization, not anonymization**: names mentioned in free text that are not speakers (a colleague, a street) are not caught. For real client research I would add NER-based detection, a paid model tier with zero data retention or a local model, and a human review step.
- Input is capped (5 transcripts, 30,000 characters) because the public demo spends a free API quota.

## Evaluation

`data/` contains three synthetic interviews about a fictional e-bike subscription with **7 planted pain points** (some mentioned by all three participants, some by one), counter-examples, and **3 traps**: things a careless summary would report but the participants explicitly say are fine. `data/golden.json` is the answer key.

```bash
python -m eval.run_eval --runs 3
```

Reports per run: planted pain points found, per-participant coverage, traps fallen for, and the share of quotes verified.

Latest results (3 runs, November 2026, Gemini free tier):

| Run | Model that answered | Pain points found | Traps fallen for | Quotes verified | Time |
|---|---|---|---|---|---|
| 1 | gemini-3.5-flash-lite | 7/7 | 0/3 | 100% | 8.9s |
| 2 | gemini-3.1-flash-lite | 7/7 | 0/3 | 100% | 8.5s |
| 3 | gemini-3.1-flash-lite | 7/7 | 0/3 | 100% | 9.7s |

Read these with care: three short synthetic interviews are an easy test, so this shows the pipeline works, not that it is ready for messy real research. The primary model (gemini-3.8-flash) was overloaded during these runs, so the fallback chain answered: each model gets one attempt, so falling back takes seconds instead of the SDK's long retry backoff. The feedback-retry path did not trigger here because every quote verified first time; it is covered by `tests/test_pipeline.py`, where a fake model returns invented, paraphrased and misattributed quotes.

Unit tests (no API key needed) cover pseudonymization, quote matching, misattribution, interviewer lines, and the full retry loop with a fake model:

```bash
pytest
```

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env          # add a free Gemini key from https://aistudio.google.com/apikey
.venv/bin/uvicorn backend.app:app --reload --port 8000

cd frontend && npm install && npm run dev   # http://localhost:5173/koos/
```

Or with Docker:

```bash
docker build -t research-assistant .
docker run -p 8080:8080 --env-file .env research-assistant   # http://localhost:8080/koos/
```

## Limits and next steps

- One LLM call plus at most one retry. Next: split into a small graph (extract per transcript, then cluster across transcripts) so longer studies fit and each step can be evaluated on its own.
- Clustering quality is judged by the model. The evaluation measures recall on planted pain points, not how well themes are grouped.
- English transcripts with `Name:` speaker labels. Other formats need a parsing step.
- No auth or rate limiting beyond input caps. Fine for a demo, not for a client.

Built by [Sem Tip](https://semtip.nl).
