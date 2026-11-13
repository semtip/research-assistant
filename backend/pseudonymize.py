"""Pseudonymize interview transcripts before anything is sent to an LLM.

Who said what is decided here, in code, never by the model:
each transcript gets a participant ID (P1, P2, ...) and the interviewer
becomes "Interviewer". Emails and phone numbers are replaced with fixed
placeholders so quotes still match the text the model actually saw.

This is pseudonymization, not anonymization: it removes the obvious
identifiers (speaker names, emails, phone numbers) but cannot guarantee
that nothing identifying remains in free text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# "Name:" at the start of a line, 1 to 4 words.
LABEL_RE = re.compile(r"^([A-Z][\w'.-]*(?: [A-Za-z][\w'.-]*){0,3}):[ \t]", re.MULTILINE)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Dutch numbers (06 1234 5678, +31 6 12345678, 020-1234567) and other international numbers.
PHONE_RE = re.compile(
    r"(?<![\w+])(?:(?:\+31|0031|0)(?:[\s-]?\d){9}|\+\d{1,3}(?:[\s-]?\d){7,12})(?!\d)"
)

METADATA_LABELS = {"study", "participant", "interviewer", "date", "location", "note", "notes", "project"}
NAME_PARTICLES = {"de", "van", "der", "den", "het", "ter", "ten", "el", "al", "la", "le", "du", "da", "di", "von"}


@dataclass
class PreparedTranscript:
    pid: str                      # "P1"
    title: str                    # original file name or label
    text: str                     # pseudonymized text (what the model sees)
    utterance_spans: list[tuple[int, int]] = field(default_factory=list)  # participant speech only
    redactions: dict[str, int] = field(default_factory=dict)


def _speaker_labels(text: str) -> list[str]:
    return [m.group(1) for m in LABEL_RE.finditer(text) if m.group(1).lower() not in METADATA_LABELS]


def _metadata_value(text: str, key: str) -> str | None:
    m = re.search(rf"^{key}:[ \t]*([^\n,]+)", text, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else None


def _identify_speakers(text: str) -> tuple[str | None, set[str]]:
    """Return (participant_name, interviewer_names)."""
    labels = _speaker_labels(text)
    participant = _metadata_value(text, "participant")
    interviewer = _metadata_value(text, "interviewer")
    interviewers = {interviewer} if interviewer else set()
    interviewers.add("Interviewer")

    if participant is None:
        # Heuristic: the interviewer asks the questions, the participant talks the most.
        stats: dict[str, list[int]] = {}
        for m in LABEL_RE.finditer(text):
            name = m.group(1)
            if name.lower() in METADATA_LABELS:
                continue
            line_end = text.find("\n", m.end())
            line = text[m.end(): line_end if line_end != -1 else len(text)]
            s = stats.setdefault(name, [0, 0])
            s[0] += len(line.split())
            s[1] += line.rstrip().endswith("?")
        candidates = [n for n in stats if n not in interviewers]
        if candidates:
            participant = max(candidates, key=lambda n: stats[n][0])
            for n in candidates:
                if n != participant and stats[n][1] > 0:
                    interviewers.add(n)
    elif labels:
        # The header may say "Sanne de Vries" while the label says "Sanne": keep both.
        for lab in set(labels):
            if lab not in interviewers and lab.split()[0] == participant.split()[0]:
                participant = max(participant, lab, key=len)
    return participant, interviewers


def _name_variants(full_name: str) -> list[str]:
    parts = full_name.split()
    variants = {full_name}
    for p in parts:
        if len(p) > 2 and p.lower() not in NAME_PARTICLES:
            variants.add(p)
    # Longest first so "Sanne de Vries" is replaced before "Sanne".
    return sorted(variants, key=len, reverse=True)


def _replace_names(text: str, names: list[str], placeholder: str) -> tuple[str, int]:
    count = 0
    for name in names:
        pattern = re.compile(rf"(?<![\w@.]){re.escape(name)}(?![\w@])")
        text, n = pattern.subn(placeholder, text)
        count += n
    return text, count


def _participant_spans(text: str, pid: str) -> list[tuple[int, int]]:
    """Character spans of what the participant said (after the "P1:" label)."""
    spans = []
    labels = list(LABEL_RE.finditer(text))
    for i, m in enumerate(labels):
        if m.group(1) != pid:
            continue
        start = m.end()
        nxt = labels[i + 1].start() if i + 1 < len(labels) else len(text)
        para_end = text.find("\n\n", start)
        end = min(nxt, para_end) if para_end != -1 else nxt
        spans.append((start, end))
    return spans


def prepare_transcript(text: str, pid: str, title: str = "") -> PreparedTranscript:
    text = text.replace("\r\n", "\n")
    redactions = {"names": 0, "emails": 0, "phones": 0}

    participant, interviewers = _identify_speakers(text)

    text, redactions["emails"] = EMAIL_RE.subn("[EMAIL]", text)
    text, redactions["phones"] = PHONE_RE.subn("[PHONE]", text)

    if participant:
        text, n = _replace_names(text, _name_variants(participant), pid)
        redactions["names"] += n
    interviewer_names = [v for name in interviewers if name != "Interviewer" for v in _name_variants(name)]
    if interviewer_names:
        text, n = _replace_names(text, sorted(set(interviewer_names), key=len, reverse=True), "Interviewer")
        redactions["names"] += n

    return PreparedTranscript(
        pid=pid,
        title=title or pid,
        text=text,
        utterance_spans=_participant_spans(text, pid),
        redactions=redactions,
    )
