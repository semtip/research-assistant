"""Pydantic contracts: what the LLM must return, and what the API returns."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

InsightKind = Literal["pain_point", "positive", "need"]


# ---------- LLM output contract ----------

class LLMEvidence(BaseModel):
    participant: str = Field(description="Participant ID exactly as in the transcript header, e.g. P1")
    quote: str = Field(description="Verbatim words copied character for character from that participant's own lines. Max ~25 words.")


class LLMInsight(BaseModel):
    title: str = Field(description="Short insight title, max 8 words, neutral language")
    kind: InsightKind
    summary: str = Field(description="One sentence. Say how many participants, never 'users' in general.")
    evidence: list[LLMEvidence] = Field(min_length=1, description="One supporting quote per participant who mentions it")
    counter_evidence: list[LLMEvidence] = Field(default_factory=list, description="Quotes from participants who say the opposite")


class LLMAnalysis(BaseModel):
    insights: list[LLMInsight]


# ---------- API contract ----------

class TranscriptIn(BaseModel):
    title: str = Field(default="", max_length=120)
    text: str = Field(min_length=20)


class AnalyzeRequest(BaseModel):
    transcripts: list[TranscriptIn] = Field(min_length=1, max_length=5)


QuoteStatus = Literal["verified", "near", "misattributed", "not_found"]


class EvidenceOut(BaseModel):
    participant: str
    quote: str
    status: QuoteStatus
    found_in: str | None = None
    start: int | None = None
    end: int | None = None
    score: float = 0.0


class InsightOut(BaseModel):
    title: str
    kind: InsightKind
    summary: str
    status: Literal["verified", "near", "dropped"]
    participants: list[str]
    evidence: list[EvidenceOut]
    counter_evidence: list[EvidenceOut]


class TranscriptOut(BaseModel):
    pid: str
    title: str
    text: str
    redactions: dict[str, int]


class Stats(BaseModel):
    quotes_total: int
    quotes_verified: int
    quotes_near: int
    quotes_rejected: int
    insights_kept: int
    insights_dropped: int
    retried: bool
    retry_feedback: list[str]
    model: str
    seconds: float


class AnalyzeResponse(BaseModel):
    transcripts: list[TranscriptOut]
    insights: list[InsightOut]
    stats: Stats
