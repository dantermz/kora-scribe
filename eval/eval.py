"""Compare drafting models on the synthetic consultations, with the same verifier for all.

Usage:
    python eval/eval.py                              # Spark Open only
    python eval/eval.py spark glimmer-low            # several drafters
    python eval/eval.py spark glimmer-low --runs 3   # repeat to see run-to-run variation
    python eval/eval.py spark --score-only           # re-score notes already drafted

For each recording listed in eval/cases.json and each drafter, the saved transcript is copied
to audio/<recording>.<drafter>.transcript.json, drafted, and verified (the verifier is always
Muse Spark Open, so every drafter is judged by the same checks). The note is then scored in
code against the expected facts and traps of its case:

  facts    a fact counts when one line of the right section matches all its patterns
  traps    a trap counts when any line of its sections matches one of its patterns
  verifier how many lines the verifier marked red or yellow

Drafters:
  spark          Muse Spark Open on Baseten (BASETEN_* in .env)
  glimmer-low    Muse Glimmer on Modal (GLIMMER_BASE_URL / GLIMMER_API_KEY in .env), reasoning low
  glimmer-medium the same at reasoning medium

Writes eval/results.md and eval/results.json. No audio and no API is used for --score-only.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import draft_note  # noqa: E402
import verify_note  # noqa: E402

AUDIO = ROOT / "audio"
CASES = Path(__file__).with_name("cases.json")


def drafters(env: dict[str, str]) -> dict[str, dict[str, str]]:
    glimmer = {
        "DRAFT_BASE_URL": env.get("GLIMMER_BASE_URL", ""),
        "DRAFT_API_KEY": env.get("GLIMMER_API_KEY", ""),
        "DRAFT_MODEL": "muse-glimmer",
    }
    spark = {  # explicit, so a DRAFT_* default in .env (e.g. Glimmer) does not leak into the baseline
        "DRAFT_BASE_URL": "https://inference.baseten.co/v1",
        "DRAFT_API_KEY": env.get("BASETEN_API_KEY", ""),
        "DRAFT_MODEL": env.get("BASETEN_MODEL", ""),
        "DRAFT_REASONING": "",
    }
    return {
        "spark": spark,
        "glimmer-low": {**glimmer, "DRAFT_REASONING": "low"},
        "glimmer-medium": {**glimmer, "DRAFT_REASONING": "medium"},
    }


def plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


@contextlib.contextmanager
def drafter_env(settings: dict[str, str]):
    """Point draft_note at one drafter; the verifier keeps its own VERIFY_/BASETEN_ settings."""
    saved = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith("DRAFT_")}
    os.environ.update(settings)
    try:
        yield
    finally:
        for k in settings:
            os.environ.pop(k, None)
        os.environ.update(saved)


def lines_by_section(verification: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {s: [] for s in "SOAP"}
    for line in verification["lines"]:
        out[line["section"]].append(plain(line["text"]))
    return out


def score(case: dict, verification: dict) -> dict:
    sections = lines_by_section(verification)
    found, missing, traps = [], [], []
    for fact in case["facts"]:
        pool = [l for s in fact["sections"] for l in sections[s]]
        if any(all(re.search(p, l) for p in fact["all"]) for l in pool):
            found.append(fact["id"])
        else:
            missing.append(fact["id"])
    for trap in case["traps"]:
        pool = [l for s in trap["sections"] for l in sections[s]]
        if any(re.search(p, l) for p in trap["any"] for l in pool):
            traps.append(trap["id"])
    summary = verification["summary"]
    return {
        "facts_found": len(found), "facts_total": len(case["facts"]), "missing": missing,
        "traps_hit": traps, "traps_total": len(case["traps"]),
        "red": summary["red"], "yellow": summary["yellow"], "lines": len(verification["lines"]),
        "coverage_missing": verification.get("coverage_missing", []),
    }


def run_one(recording: str, label: str, settings: dict[str, str], score_only: bool) -> dict:
    base = AUDIO / f"{recording}.{label}"
    transcript = base.with_name(base.name + ".transcript.json")
    note = base.with_name(base.name + ".note.json")
    verification = base.with_name(base.name + ".verification.json")
    meta: dict = {}
    if not score_only:
        shutil.copyfile(AUDIO / f"{recording}.transcript.json", transcript)
        quiet = io.StringIO()
        start = time.time()
        with drafter_env(settings), contextlib.redirect_stdout(quiet):
            draft_note.main(transcript)
        meta["draft_seconds"] = round(time.time() - start, 1)
        tokens = re.search(r"Tokens: (\d+) in · (\d+) out", quiet.getvalue())
        if tokens:
            meta["draft_tokens_out"] = int(tokens.group(2))
        with contextlib.redirect_stdout(io.StringIO()):
            verify_note.main(note)
    if not verification.exists():
        sys.exit(f"Missing {verification.name}: run without --score-only first.")
    return {"verification": json.loads(verification.read_text(encoding="utf-8")), **meta}


def main(args: list[str]) -> None:
    runs = 1
    if "--runs" in args:
        runs = int(args[args.index("--runs") + 1])
        del args[args.index("--runs"):args.index("--runs") + 2]
    score_only = "--score-only" in args
    names = [a for a in args if not a.startswith("--")] or ["spark"]
    if score_only:
        runs = 1

    env = draft_note.load_env()
    available = drafters(env)
    for name in names:
        if name not in available:
            sys.exit(f"Unknown drafter {name!r}. Choose from: {', '.join(available)}")
        if name.startswith("glimmer") and not available[name]["DRAFT_API_KEY"] and not score_only:
            sys.exit("GLIMMER_BASE_URL / GLIMMER_API_KEY are missing from .env")

    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    results = []
    for case in cases:
        for recording in case["recordings"]:
            if not (AUDIO / f"{recording}.transcript.json").exists():
                print(f"skip {recording}: no transcript in audio/")
                continue
            for name in names:
                for run in range(1, runs + 1):
                    print(f"{case['id']} · {recording} · {name} · run {run}/{runs} ...", flush=True)
                    out = run_one(recording, name, available[name], score_only)
                    row = {"case": case["id"], "recording": recording, "drafter": name, "run": run,
                           **score(case, out["verification"]),
                           **{k: v for k, v in out.items() if k != "verification"}}
                    results.append(row)
                    print(f"   facts {row['facts_found']}/{row['facts_total']} · traps hit "
                          f"{len(row['traps_hit'])}/{row['traps_total']} · verifier "
                          f"{row['red']} red, {row['yellow']} yellow", flush=True)

    report = ["# Drafter evaluation", "",
              "Same transcripts, same prompt, same verifier (Muse Spark Open). Facts and traps from "
              "`eval/cases.json`, matched in code.", "",
              "| Case | Recording | Drafter | Run | Facts found | Traps hit | Verifier 🔴 | Verifier 🟡 | Draft s | Output tokens |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        report.append(f"| {r['case']} | {r['recording']} | {r['drafter']} | {r['run']} | "
                      f"{r['facts_found']}/{r['facts_total']} | {len(r['traps_hit'])}/{r['traps_total']} | "
                      f"{r['red']} | {r['yellow']} | {r.get('draft_seconds', '')} | {r.get('draft_tokens_out', '')} |")
    report += ["", "## Details", ""]
    for r in results:
        report.append(f"**{r['case']} · {r['drafter']} · run {r['run']}**")
        report.append(f"- Missing facts: {', '.join(r['missing']) or 'none'}")
        report.append(f"- Traps hit: {', '.join(r['traps_hit']) or 'none'}")
        report.append("")
    (Path(__file__).with_name("results.md")).write_text("\n".join(report), encoding="utf-8")
    (Path(__file__).with_name("results.json")).write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                                          encoding="utf-8")
    print("\n" + "\n".join(report[4:4 + 2 + len(results)]))
    print("\nSaved eval/results.md and eval/results.json")


if __name__ == "__main__":
    main(sys.argv[1:])
