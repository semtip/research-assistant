"""Streaming endpoint: progress events arrive in order, including a model fallback."""

import json
from functools import partial
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic_ai import ModelUnavailableError
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.profiles import ModelProfile

import backend.app as app_module
from backend.analyze import analyze
from tests.test_pipeline import FILES, FIRST, SECOND

DATA = Path(__file__).resolve().parent.parent / "data"
PROFILE = ModelProfile(supports_json_schema_output=True)


def busy(messages, info):
    raise ModelUnavailableError(model_name="busy-model", message="high demand")


def works(messages, info):
    return ModelResponse(parts=[TextPart(json.dumps(SECOND if len(messages) > 1 else FIRST))])


def test_stream_events_with_fallback(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    chain = [FunctionModel(busy, model_name="busy-model", profile=PROFILE),
             FunctionModel(works, model_name="backup-model", profile=PROFILE)]
    monkeypatch.setattr(app_module, "analyze", partial(analyze, model=chain))
    monkeypatch.setattr("backend.analyze.model_chain", lambda spec: spec if isinstance(spec, list) else [spec])

    body = {"transcripts": [{"title": f, "text": (DATA / f).read_text()} for f in FILES]}
    with TestClient(app_module.app) as client:
        res = client.post("/koos/api/analyze/stream", json=body)
    assert res.status_code == 200
    events = [json.loads(line) for line in res.text.splitlines() if line]
    kinds = [(e["type"], e.get("step"), e.get("status")) for e in events]

    assert kinds[0] == ("step", "privacy", "done")
    assert events[0]["names"] > 0 and events[0]["emails"] == 2 and events[0]["phones"] == 1
    assert ("model_busy", None, None) in kinds
    busy_ev = next(e for e in events if e["type"] == "model_busy")
    assert busy_ev["model"] == "busy-model" and busy_ev["next"] == "backup-model"
    assert ("retry", None, None) in kinds
    assert ("step", "verify", "done") in kinds
    assert events[-1]["type"] == "result"
    assert events[-1]["data"]["stats"]["model"] == "backup-model"


def test_stream_all_models_busy(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    chain = [FunctionModel(busy, model_name="a", profile=PROFILE), FunctionModel(busy, model_name="b", profile=PROFILE)]
    monkeypatch.setattr(app_module, "analyze", partial(analyze, model=chain))
    monkeypatch.setattr("backend.analyze.model_chain", lambda spec: spec if isinstance(spec, list) else [spec])
    body = {"transcripts": [{"text": (DATA / FILES[0]).read_text()}]}
    with TestClient(app_module.app) as client:
        res = client.post("/api/analyze/stream", json=body)
    last = json.loads(res.text.splitlines()[-1])
    assert last == {"type": "error", "status": 503, "message": last["message"]}
    assert "busy" in last["message"]
