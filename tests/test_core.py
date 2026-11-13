"""Deterministic tests: pseudonymization and quote verification. No API key needed."""

import json
from pathlib import Path

import pytest

from backend.pseudonymize import prepare_transcript
from backend.verify import locate

DATA = Path(__file__).resolve().parent.parent / "data"
GOLDEN = json.loads((DATA / "golden.json").read_text())


@pytest.fixture(scope="module")
def transcripts():
    out = {}
    for pid, p in GOLDEN["participants"].items():
        out[pid] = prepare_transcript((DATA / p["file"]).read_text(), pid, p["file"])
    return out


def test_all_pii_removed(transcripts):
    for t in transcripts.values():
        for pii in GOLDEN["pii_to_remove"]:
            assert pii not in t.text, f"{pii!r} still in {t.title}"


def test_speakers_become_ids(transcripts):
    for pid, t in transcripts.items():
        assert f"\n{pid}: " in t.text
        assert "\nInterviewer: " in t.text
        assert t.utterance_spans, f"no participant speech found for {pid}"


def test_placeholders_and_counts(transcripts):
    assert "[EMAIL]" in transcripts["P1"].text
    assert "[PHONE]" in transcripts["P2"].text
    assert transcripts["P3"].redactions["emails"] == 1
    assert transcripts["P2"].redactions["phones"] == 1


def test_golden_evidence_verifies(transcripts):
    items = GOLDEN["pain_points"] + GOLDEN["positives"]
    for item in items:
        for pid, quote in item["evidence"].items():
            m = locate(quote, pid, transcripts)
            assert m.status == "verified", (item["id"], pid, quote, m)
            span_text = transcripts[pid].text[m.start:m.end]
            assert quote.strip(".").lower() in span_text.lower()


def test_quote_normalization(transcripts):
    # Curly quotes, extra whitespace, missing final period, different case.
    m = locate("It took   nine DAYS", "P1", transcripts)
    assert m.status == "verified"
    m = locate("I really love the bike’", "P1", transcripts)
    assert m.status == "verified"


def test_ellipsis_quote(transcripts):
    m = locate("I tried to call... there's no phone number anywhere", "P1", transcripts)
    assert m.status == "verified"


def test_fabricated_quote_rejected(transcripts):
    m = locate("The lock broke on the first day", "P2", transcripts)
    assert m.status == "not_found"


def test_paraphrase_is_near_not_verified(transcripts):
    m = locate("It took nine whole days", "P1", transcripts)
    assert m.status in {"near", "not_found"}
    assert m.status != "verified"


def test_misattributed_quote(transcripts):
    # Daan said this, not Sanne.
    m = locate("There's only the chat.", "P1", transcripts)
    assert m.status == "misattributed"
    assert m.participant == "P2"


def test_interviewer_lines_never_count(transcripts):
    m = locate("What happens when something goes wrong with the bike?", "P1", transcripts)
    assert m.status != "verified"


def test_heuristic_without_headers():
    text = (
        "Anna: How do you use the app?\n\n"
        "Bram Jansen: Every day. I mostly use it to plan my week and it saves me a lot of time.\n\n"
        "Anna: What would you change?\n\n"
        "Bram Jansen: Call me on +31 6 12345678 and I'll tell you. Or mail bram@example.com.\n"
    )
    t = prepare_transcript(text, "P1")
    assert "Bram" not in t.text and "Anna" not in t.text
    assert "[PHONE]" in t.text and "[EMAIL]" in t.text
    assert locate("it saves me a lot of time", "P1", {"P1": t}).status == "verified"
