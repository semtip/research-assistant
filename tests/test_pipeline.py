"""Full pipeline with a fake model (no API key): first answer has bad quotes, the retry fixes them."""

import json
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.profiles import ModelProfile

from backend.analyze import analyze
from backend.models import AnalyzeRequest, TranscriptIn

DATA = Path(__file__).resolve().parent.parent / "data"
FILES = ["interview-1-sanne.txt", "interview-2-daan.txt", "interview-3-yara.txt"]

FIRST = {"insights": [
    {"title": "Repairs take too long", "kind": "pain_point", "summary": "3 of 3 participants waited long for repairs.",
     "evidence": [
         {"participant": "P1", "quote": "It took nine whole days."},           # paraphrased
         {"participant": "P2", "quote": "There's only the chat."},             # wrong participant? no, P2 said it, but wrong insight
         {"participant": "P3", "quote": "the slot they gave me was a week later"},
     ]},
    {"title": "Lock is unreliable", "kind": "pain_point", "summary": "1 participant had lock problems.",
     "evidence": [{"participant": "P2", "quote": "The lock broke on the first day"}]},  # invented
]}

SECOND = {"insights": [
    {"title": "Repairs take too long", "kind": "pain_point", "summary": "3 of 3 participants waited long for repairs.",
     "evidence": [
         {"participant": "P1", "quote": "It took nine days."},
         {"participant": "P2", "quote": "it was more than a week before the replacement bike came"},
         {"participant": "P3", "quote": "the slot they gave me was a week later"},
     ]},
    {"title": "Chat-only support", "kind": "pain_point", "summary": "2 of 3 participants could not reach a human.",
     "evidence": [
         {"participant": "P1", "quote": "There's only the chat."},             # misattributed: Daan said it
         {"participant": "P2", "quote": "There's only the chat."},
     ],
     "counter_evidence": [{"participant": "P3", "quote": "Through the chat, and to be fair it's fast."}]},
    {"title": "Lock is unreliable", "kind": "pain_point", "summary": "1 participant had lock problems.",
     "evidence": [{"participant": "P2", "quote": "The lock broke on the first day"}]},  # still invented
]}


def fake_model(messages, info: AgentInfo) -> ModelResponse:
    retried = len(messages) > 1  # the retry feedback arrives as a follow-up message
    return ModelResponse(parts=[TextPart(json.dumps(SECOND if retried else FIRST))])


@pytest.mark.anyio
async def test_retry_and_verification():
    model = FunctionModel(fake_model, profile=ModelProfile(supports_json_schema_output=True))
    req = AnalyzeRequest(transcripts=[TranscriptIn(title=f, text=(DATA / f).read_text()) for f in FILES])
    res = await analyze(req, model=model)

    assert res.stats.retried
    assert any("nine whole days" in p for p in res.stats.retry_feedback)
    assert any("lock broke" in p for p in res.stats.retry_feedback)

    by_title = {i.title: i for i in res.insights}
    repairs = by_title["Repairs take too long"]
    assert repairs.status == "verified" and repairs.participants == ["P1", "P2", "P3"]

    chat = by_title["Chat-only support"]
    assert [e.status for e in chat.evidence] == ["misattributed", "verified"]
    assert chat.participants == ["P2"]
    assert chat.counter_evidence[0].status == "verified"

    assert by_title["Lock is unreliable"].status == "dropped"
    assert res.insights[-1].title == "Lock is unreliable"  # dropped insights sort last

    for t in res.transcripts:  # what was sent is pseudonymized
        assert "Sanne" not in t.text and "Daan" not in t.text and "Yara" not in t.text


@pytest.fixture
def anyio_backend():
    return "asyncio"
