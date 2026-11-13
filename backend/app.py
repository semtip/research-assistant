"""FastAPI app. Serves the API at /api and /koos/api, and (locally or in Docker) the built frontend at /koos."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic_ai import (
    ModelAPIError,
    ModelAuthenticationError,
    ModelQuotaExceededError,
    ModelRateLimitError,
    ModelUnavailableError,
    RunTimedOut,
    UnexpectedModelBehavior,
    UserError,
)

from .analyze import analyze
from .models import AnalyzeRequest, AnalyzeResponse

load_dotenv()
log = logging.getLogger("research-assistant")

MAX_CHARS_PER_TRANSCRIPT = 12_000
MAX_CHARS_TOTAL = 30_000

app = FastAPI(title="Research Assistant", description="Interview transcripts in, verified insights out.")
router = APIRouter()


@router.get("/health")
def health():
    configured = bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))
    return {"ok": True, "ai_configured": configured}


def check_request(req: AnalyzeRequest) -> None:
    lengths = [len(t.text) for t in req.transcripts]
    if max(lengths) > MAX_CHARS_PER_TRANSCRIPT or sum(lengths) > MAX_CHARS_TOTAL:
        raise HTTPException(413, f"Too much text for this demo: max {MAX_CHARS_PER_TRANSCRIPT:,} characters per transcript and {MAX_CHARS_TOTAL:,} in total.")
    if not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
        raise HTTPException(503, "The AI model is not configured on this server. Try the example result instead.")


def error_for(e: Exception) -> tuple[int, str]:
    """Map model errors to a status code and a message a person can act on."""
    if isinstance(e, ModelUnavailableError):
        return 503, "The free AI models are all busy right now. Try again in a minute, or view the example result."
    if isinstance(e, RunTimedOut):
        return 504, "The AI took too long to answer. Try again, or view the example result."
    if isinstance(e, (ModelRateLimitError, ModelQuotaExceededError)):
        return 429, "The free AI quota is used up for now. Try again in a minute, or view the example result."
    if isinstance(e, ModelAuthenticationError):
        return 503, "The AI model is not configured correctly on this server."
    if isinstance(e, UnexpectedModelBehavior):
        log.warning("model behaviour: %s", e)
        return 502, "The AI returned something we could not use. Please try again."
    log.warning("model error: %r", e)
    return 502, "The AI service had a problem. Please try again."


HANDLED = (ModelAPIError, RunTimedOut, UnexpectedModelBehavior, UserError)


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_endpoint(req: AnalyzeRequest):
    check_request(req)
    try:
        return await analyze(req)
    except HANDLED as e:
        status, message = error_for(e)
        raise HTTPException(status, message)


@router.post("/analyze/stream")
async def analyze_stream(req: AnalyzeRequest):
    """Same as /analyze, but streams progress as newline-delimited JSON events, ending with
    {"type": "result", ...} or {"type": "error", ...}."""
    check_request(req)
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def run():
        try:
            result = await analyze(req, emit=queue.put_nowait)
            queue.put_nowait({"type": "result", "data": result.model_dump()})
        except HANDLED as e:
            status, message = error_for(e)
            queue.put_nowait({"type": "error", "status": status, "message": message})
        except Exception:
            log.exception("unexpected error")
            queue.put_nowait({"type": "error", "status": 500, "message": "Something went wrong on our side. Please try again."})
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(run())

    async def events():
        try:
            while (event := await queue.get()) is not None:
                yield json.dumps(event) + "\n"
        finally:
            if not task.done():  # client went away (e.g. pressed Cancel): stop spending quota
                task.cancel()

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Same routes under both prefixes: /api (Vercel function, Docker) and /koos/api (behind semtip.nl/koos).
app.include_router(router, prefix="/api")
app.include_router(router, prefix="/koos/api")

DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist" / "koos"
if DIST.is_dir():
    app.mount("/koos", StaticFiles(directory=DIST, html=True), name="frontend")

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/koos/")
