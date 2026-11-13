"""Score a real model run against the planted answer key (data/golden.json).

    python -m eval.run_eval            # run once, print the scorecard
    python -m eval.run_eval --runs 3   # average over several runs (LLMs are not deterministic)
    python -m eval.run_eval --save     # also save the result as the frontend's example result

Matching is deliberately simple and transparent: a planted pain point counts as found when a kept
insight cites a verified quote from the same participant answer (utterance) as the answer key.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from backend.analyze import analyze
from backend.models import AnalyzeRequest, AnalyzeResponse, TranscriptIn
from backend.pseudonymize import prepare_transcript
from backend.verify import locate

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
GOLDEN = json.loads((DATA / "golden.json").read_text())
TITLES = {"P1": "Interview 1, daily commuter", "P2": "Interview 2, groceries and family", "P3": "Interview 3, student"}


def utterance_of(pid: str, start: int, transcripts) -> int | None:
    for i, (s, e) in enumerate(transcripts[pid].utterance_spans):
        if s <= start < e:
            return i
    return None


def score(res: AnalyzeResponse) -> dict:
    transcripts = {
        pid: prepare_transcript((DATA / p["file"]).read_text(), pid, p["file"])
        for pid, p in GOLDEN["participants"].items()
    }

    def golden_utt(pid: str, quote: str):
        m = locate(quote, pid, transcripts)
        return utterance_of(pid, m.start, transcripts)

    cited = []  # (kind, pid, utterance) for verified/near evidence of kept insights
    for ins in res.insights:
        if ins.status == "dropped":
            continue
        for ev in ins.evidence:
            if ev.status in ("verified", "near") and ev.start is not None:
                cited.append((ins.kind, ev.participant, utterance_of(ev.participant, ev.start, transcripts)))

    found, coverage = [], {}
    for pp in GOLDEN["pain_points"]:
        hits = [pid for pid, q in pp["evidence"].items()
                if any(k in ("pain_point", "need") and p == pid and u == golden_utt(pid, q) for k, p, u in cited)]
        coverage[pp["id"]] = (len(hits), len(pp["evidence"]))
        if hits:
            found.append(pp["id"])

    traps = []
    for t in GOLDEN["should_not_appear"]:
        for pid in transcripts:
            m = locate(t["trap"], pid, transcripts)
            if m.status == "verified":
                u = utterance_of(pid, m.start, transcripts)
                if any(k == "pain_point" and p == pid and uu == u for k, p, uu in cited):
                    traps.append(t["id"])

    s = res.stats
    return {
        "recall": len(found) / len(GOLDEN["pain_points"]),
        "found": found,
        "missed": [pp["id"] for pp in GOLDEN["pain_points"] if pp["id"] not in found],
        "coverage": coverage,
        "traps_hit": traps,
        "verified_rate": s.quotes_verified / s.quotes_total if s.quotes_total else 0.0,
        "retried": s.retried,
        "seconds": s.seconds,
    }


async def main():
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--save", action="store_true", help="save the last run as frontend/src/example-result.json")
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    req = AnalyzeRequest(transcripts=[
        TranscriptIn(title=TITLES[pid], text=(DATA / p["file"]).read_text())
        for pid, p in GOLDEN["participants"].items()
    ])

    results = []
    for i in range(args.runs):
        try:
            res = await analyze(req, model=args.model)
        except Exception as e:  # overloaded free tier etc.: report and continue
            print(f"\nRun {i + 1} failed: {type(e).__name__}: {str(e)[:160]}")
            continue
        sc = score(res)
        results.append(sc)
        print(f"\nRun {i + 1} ({res.stats.model}, {sc['seconds']}s, retried={sc['retried']})")
        print(f"  pain points found : {len(sc['found'])}/{len(GOLDEN['pain_points'])}  missed: {sc['missed'] or 'none'}")
        print(f"  participant cover : {', '.join(f'{k} {a}/{b}' for k, (a, b) in sc['coverage'].items())}")
        print(f"  traps fallen for  : {sc['traps_hit'] or 'none'}")
        print(f"  quotes verified   : {sc['verified_rate']:.0%}")

    if not results:
        return
    if args.runs > 1:
        n = len(results)
        print(f"\nAverage over {n} runs: recall {sum(r['recall'] for r in results) / n:.0%}, "
              f"verified {sum(r['verified_rate'] for r in results) / n:.0%}, "
              f"trap hits {sum(len(r['traps_hit']) for r in results)}")

    if args.save and results:
        out = ROOT / "frontend" / "src" / "example-result.json"
        out.write_text(res.model_dump_json(indent=1))
        print(f"\nSaved example result to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
