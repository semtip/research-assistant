"""Check that every quote the model returns really exists in the source.

The model is treated as an untrusted narrator. A quote is:
- verified:      found verbatim (after normalizing whitespace, quote marks and case)
                 in the claimed participant's own speech
- near:          a close but not exact match (fuzzy score >= NEAR_THRESHOLD); shown, never counted as verified
- misattributed: found verbatim, but said by a different participant
- not_found:     not in the source at all (or only in the interviewer's lines)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz

from .pseudonymize import PreparedTranscript

NEAR_THRESHOLD = 90
Status = Literal["verified", "near", "misattributed", "not_found"]

_CHAR_MAP = str.maketrans({
    "‘": "'", "’": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "‟": '"', "″": '"',
    "–": "-", "—": "-", " ": " ",
})
_ELLIPSIS_RE = re.compile(r"\s*(?:\.\.\.|…|\[\.\.\.\])\s*")
_EDGE_CHARS = " \t\n\"'.,;:!?"


@dataclass
class Match:
    status: Status
    participant: str | None = None  # where it was actually found
    start: int | None = None        # offsets in the pseudonymized transcript
    end: int | None = None
    score: float = 0.0


def normalize_with_map(s: str) -> tuple[str, list[int]]:
    """Lowercase, unify quote marks, collapse whitespace. Keep a map back to original indices."""
    out: list[str] = []
    idx: list[int] = []
    prev_space = False
    for i, ch in enumerate(s.translate(_CHAR_MAP)):
        if ch.isspace():
            if prev_space or not out:
                continue
            out.append(" ")
            idx.append(i)
            prev_space = True
        else:
            out.append(ch.lower())
            idx.append(i)
            prev_space = False
    return "".join(out), idx


def _clean_fragment(q: str) -> str:
    q = q.translate(_CHAR_MAP).strip(_EDGE_CHARS)
    return normalize_with_map(q)[0]


def _find_exact(fragments: list[str], text: str, span: tuple[int, int]) -> tuple[int, int] | None:
    """All fragments must appear in order inside the span. Returns original offsets."""
    seg = text[span[0]: span[1]]
    norm, imap = normalize_with_map(seg)
    pos, first, last = 0, None, None
    for frag in fragments:
        if not frag:
            continue
        i = norm.find(frag, pos)
        if i == -1:
            return None
        first = i if first is None else first
        last = i + len(frag) - 1
        pos = i + len(frag)
    if first is None:
        return None
    return span[0] + imap[first], span[0] + imap[last] + 1


def _find_near(quote: str, text: str, span: tuple[int, int]) -> tuple[float, int, int] | None:
    seg = text[span[0]: span[1]]
    norm, imap = normalize_with_map(seg)
    if not norm or not quote:
        return None
    al = fuzz.partial_ratio_alignment(quote, norm)
    if al is None or al.dest_end <= al.dest_start:
        return None
    return al.score, span[0] + imap[al.dest_start], span[0] + imap[al.dest_end - 1] + 1


def locate(quote: str, participant: str, transcripts: dict[str, PreparedTranscript]) -> Match:
    fragments = [_clean_fragment(f) for f in _ELLIPSIS_RE.split(quote)]
    fragments = [f for f in fragments if f]
    if not fragments:
        return Match("not_found")

    own = transcripts.get(participant)
    if own:
        for span in own.utterance_spans:
            hit = _find_exact(fragments, own.text, span)
            if hit:
                return Match("verified", participant, hit[0], hit[1], 100.0)

    # Said by someone else?
    for pid, t in transcripts.items():
        if pid == participant:
            continue
        for span in t.utterance_spans:
            hit = _find_exact(fragments, t.text, span)
            if hit:
                return Match("misattributed", pid, hit[0], hit[1], 100.0)

    # Close but not exact (paraphrased or slightly altered)?
    if own:
        joined = " ".join(fragments)
        best: tuple[float, int, int] | None = None
        for span in own.utterance_spans:
            r = _find_near(joined, own.text, span)
            if r and (best is None or r[0] > best[0]):
                best = r
        if best and best[0] >= NEAR_THRESHOLD:
            return Match("near", participant, best[1], best[2], round(best[0], 1))
        if best:
            return Match("not_found", None, None, None, round(best[0], 1))
    return Match("not_found")
