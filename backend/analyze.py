"""The analysis pipeline: pseudonymize -> LLM (structured output) -> verify quotes -> feedback retry."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from pydantic_ai import (
    Agent,
    ModelQuotaExceededError,
    ModelRateLimitError,
    ModelRetry,
    ModelUnavailableError,
    NativeOutput,
    RunContext,
)

from .models import (
    AnalyzeRequest,
    AnalyzeResponse,
    EvidenceOut,
    InsightOut,
    LLMAnalysis,
    LLMEvidence,
    Stats,
    TranscriptOut,
)
from .pseudonymize import PreparedTranscript, prepare_transcript
from .verify import locate

# Comma-separated: the first model is used, the next ones only if it is overloaded or out of quota.
DEFAULT_MODEL = "google:gemini-3.8-flash,google:gemini-3.5-flash-lite,google:gemini-3.1-flash-lite"
RUN_TIMEOUT_SECONDS = 50

INSTRUCTIONS = """\
You are a research assistant for service designers. You analyse user-interview transcripts.

The transcripts are pseudonymized. Each participant has an ID (P1, P2, ...). Lines starting with
"P1:" are what participant P1 said. Lines starting with "Interviewer:" are questions: never quote them.

Find the insights in these interviews:
- pain_point: a problem, frustration or obstacle a participant experienced
- positive: something that works well for a participant
- need: an unmet need or wish (for example a feature request)

Rules:
1. Every insight needs evidence: for each participant who supports it, one quote copied VERBATIM,
   character for character, from that participant's own lines. Keep quotes short (max ~25 words).
   Do not fix grammar, do not shorten words, do not merge sentences from different lines.
2. Only report what participants actually said. Do not infer, generalize or invent.
3. If a participant explicitly says the opposite (e.g. it worked fine for them), add their quote
   as counter_evidence instead of ignoring it.
4. Never report something as a pain point when the participant says it is fine.
5. Write summaries about the participants ("2 of 3 participants..."), never about "users" in general.
6. Merge duplicates. Put the insights mentioned by the most participants first.
7. Also report issues that only one participant mentions, including small or indirect ones
   (for example something that got worse over time or under certain conditions). In research,
   a single strong signal matters.
"""


Emit = Callable[[dict], None]


def _noop(_: dict) -> None:
    pass


@dataclass
class Deps:
    transcripts: dict[str, PreparedTranscript]
    retry_feedback: list[str] = field(default_factory=list)
    emit: Emit = _noop  # progress events for the streaming endpoint


agent = Agent(
    output_type=NativeOutput(LLMAnalysis),
    deps_type=Deps,
    instructions=INSTRUCTIONS,
    retries={"output": 1},
)


def _all_evidence(out: LLMAnalysis):
    for i, ins in enumerate(out.insights):
        for ev in ins.evidence:
            yield i, ins, ev
        for ev in ins.counter_evidence:
            yield i, ins, ev


@agent.output_validator
async def verify_quotes(ctx: RunContext[Deps], out: LLMAnalysis) -> LLMAnalysis:
    """First attempt: tell the model exactly which quotes failed and why. Second attempt: accept,
    and let the deterministic checks below mark what is still wrong."""
    n_quotes = sum(1 for _ in _all_evidence(out))
    ctx.deps.emit({"type": "step", "step": "read", "status": "done", "insights": len(out.insights)})
    ctx.deps.emit({"type": "step", "step": "verify", "status": "active", "quotes": n_quotes})
    if ctx.retry >= 1:
        return out
    problems = []
    for _, ins, ev in _all_evidence(out):
        if ev.participant not in ctx.deps.transcripts:
            problems.append(f'"{ins.title}": participant {ev.participant} does not exist')
            continue
        m = locate(ev.quote, ev.participant, ctx.deps.transcripts)
        if m.status == "misattributed":
            problems.append(f'"{ins.title}": "{ev.quote}" was said by {m.participant}, not {ev.participant}')
        elif m.status != "verified":
            problems.append(f'"{ins.title}": "{ev.quote}" does not appear verbatim in {ev.participant}\'s lines')
    if problems:
        ctx.deps.retry_feedback.extend(problems)
        ctx.deps.emit({"type": "retry", "problems": len(problems), "quotes": n_quotes})
        raise ModelRetry(
            "Some quotes could not be verified against the transcripts:\n- "
            + "\n- ".join(problems)
            + "\nCopy quotes exactly from the participant's own lines, fix the participant ID, "
            "or remove evidence you cannot support. Return the complete analysis again."
        )
    return out


def _check(ev: LLMEvidence, transcripts: dict[str, PreparedTranscript]) -> EvidenceOut:
    m = locate(ev.quote, ev.participant, transcripts) if ev.participant in transcripts else None
    if m is None:
        return EvidenceOut(participant=ev.participant, quote=ev.quote, status="not_found")
    return EvidenceOut(
        participant=ev.participant, quote=ev.quote, status=m.status,
        found_in=m.participant, start=m.start, end=m.end, score=m.score,
    )


def prepare(req: AnalyzeRequest) -> dict[str, PreparedTranscript]:
    out = {}
    for i, t in enumerate(req.transcripts, start=1):
        pid = f"P{i}"
        out[pid] = prepare_transcript(t.text, pid, t.title or f"Transcript {i}")
    return out


def build_response(
    output: LLMAnalysis, transcripts: dict[str, PreparedTranscript], deps: Deps, model: str, seconds: float
) -> AnalyzeResponse:
    insights: list[InsightOut] = []
    for ins in output.insights:
        ev = [_check(e, transcripts) for e in ins.evidence]
        counter = [_check(e, transcripts) for e in ins.counter_evidence]
        verified = [e for e in ev if e.status == "verified"]
        near = [e for e in ev if e.status == "near"]
        status = "verified" if verified else ("near" if near else "dropped")
        participants = sorted({e.participant for e in verified + near}, key=lambda p: int(p[1:]))
        insights.append(InsightOut(
            title=ins.title, kind=ins.kind, summary=ins.summary, status=status,
            participants=participants, evidence=ev, counter_evidence=counter,
        ))

    order = {"verified": 0, "near": 1, "dropped": 2}
    insights.sort(key=lambda i: (order[i.status], -len(i.participants)))

    all_ev = [e for i in insights for e in i.evidence + i.counter_evidence]
    stats = Stats(
        quotes_total=len(all_ev),
        quotes_verified=sum(e.status == "verified" for e in all_ev),
        quotes_near=sum(e.status == "near" for e in all_ev),
        quotes_rejected=sum(e.status in ("not_found", "misattributed") for e in all_ev),
        insights_kept=sum(i.status != "dropped" for i in insights),
        insights_dropped=sum(i.status == "dropped" for i in insights),
        retried=bool(deps.retry_feedback),
        retry_feedback=deps.retry_feedback,
        model=model,
        seconds=round(seconds, 1),
    )
    return AnalyzeResponse(
        transcripts=[TranscriptOut(pid=t.pid, title=t.title, text=t.text, redactions=t.redactions) for t in transcripts.values()],
        insights=insights,
        stats=stats,
    )


def _make_model(name: str):
    """Google models get a single attempt each: when a model is overloaded we want the fallback
    within seconds, not the SDK's long retry backoff."""
    if name.startswith("google:"):
        from google.genai.types import HttpRetryOptions
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider

        return GoogleModel(name.removeprefix("google:"), provider=GoogleProvider(retry_options=HttpRetryOptions(attempts=1)))
    return name


def model_chain(spec) -> list:
    """A "provider:model" string, a comma-separated fallback chain, or a pydantic-ai Model (tests)."""
    if not isinstance(spec, str):
        return [spec]
    return [n.strip() for n in spec.split(",") if n.strip()]


def model_label(m) -> str:
    return m if isinstance(m, str) else getattr(m, "model_name", type(m).__name__)


BUSY_ERRORS = (ModelUnavailableError, ModelRateLimitError, ModelQuotaExceededError)


async def analyze(req: AnalyzeRequest, model=None, emit: Emit = _noop) -> AnalyzeResponse:
    """Run the pipeline. `emit` receives progress events (used by the streaming endpoint).

    Models are tried in order; a model that is overloaded or out of quota gets one attempt, then the
    next one takes over within seconds. The whole run shares one deadline."""
    chain = model_chain(model or os.getenv("LLM_MODEL", DEFAULT_MODEL))
    transcripts = prepare(req)
    totals = {k: sum(t.redactions.get(k, 0) for t in transcripts.values()) for k in ("names", "emails", "phones")}
    emit({"type": "step", "step": "privacy", "status": "done", "transcripts": len(transcripts), **totals})

    prompt = "\n\n".join(f"=== Transcript {t.pid} ===\n{t.text}" for t in transcripts.values())
    t0 = time.perf_counter()
    last_error: Exception | None = None
    for i, spec in enumerate(chain):
        remaining = RUN_TIMEOUT_SECONDS - (time.perf_counter() - t0)
        if remaining <= 5:
            break
        label = model_label(spec)
        emit({"type": "step", "step": "read", "status": "active", "model": label})
        deps = Deps(transcripts=transcripts, emit=emit)
        try:
            m = _make_model(spec) if isinstance(spec, str) else spec
            result = await agent.run(prompt, deps=deps, model=m, timeout=remaining)
        except BUSY_ERRORS as e:
            last_error = e
            nxt = model_label(chain[i + 1]) if i + 1 < len(chain) else None
            emit({"type": "model_busy", "model": label, "next": nxt})
            continue
        response = build_response(result.output, transcripts, deps, label, time.perf_counter() - t0)
        s = response.stats
        emit({"type": "step", "step": "verify", "status": "done", "verified": s.quotes_verified, "quotes": s.quotes_total})
        return response
    if last_error:
        raise last_error
    raise ModelUnavailableError(model_name=model_label(chain[-1]), message="No time left to try another model")
