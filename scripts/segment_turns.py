"""Split long transcript turns into phrases, using the word timing in the raw events.

Usage:
    python scripts/segment_turns.py audio/lentes5

Muse Voice Transcribe sends cumulative partial transcripts while a turn is being spoken.
Each partial adds a few words and says how much audio had been processed at that moment,
so the first partial that contains a word tells us roughly when that word ended. That is
enough to cut a long turn into phrases with their own start and end times, without
transcribing again.

A turn longer than MAX_WORDS is cut at sentence punctuation, or at a pause of PAUSE_MS
or more where there is no punctuation nearby (dictated recaps often come without any).
Phrases keep the turn they came from: T13 becomes T13a, T13b, ... with "turn": "T13".
Short turns are left as they are.

Rewrites <name>.transcript.json and <name>.transcript.txt from <name>.events.jsonl.
After segmenting, draft and verify again so the note cites the phrases.
"""

from __future__ import annotations

import json
import re
import string
import sys
from pathlib import Path

MAX_WORDS = 15     # turns up to this length stay whole
PAUSE_MS = 900     # silence between words that counts as a phrase break
LAG_MS = 500       # a word shows up in the partials about this long after it is spoken
LOOKAHEAD = 6      # do not cut at a pause if a sentence ends within this many words
SENTENCE_END = re.compile(r"[.?!]$")


def fmt(ms: int | None) -> str:
    if ms is None:
        return "[--:--]"
    return f"[{ms // 60000:02d}:{ms // 1000 % 60:02d}]"


def read_turns(events: list[dict]) -> list[dict]:
    """Rebuild the turns from the raw events, with each word's approximate end time."""
    turns: list[dict] = []
    current: dict | None = None
    speaker = "?"
    for e in events:
        kind = e.get("type")
        if kind == "speechStart":
            current = {"turn_id": e["turnId"], "start_ms": e.get("audioProcessedMs", 0), "words": []}
        elif kind == "transcript" and current is not None and not e.get("final"):
            words = e.get("transcript", "").split()
            have = current["words"]
            keep = 0
            while keep < min(len(have), len(words)) and have[keep][0] == words[keep]:
                keep += 1
            del have[keep:]  # the server may revise the tail of a partial
            at = e.get("audioProcessedMs", 0) - LAG_MS
            have.extend([w, at] for w in words[keep:])
        elif kind == "speaker":
            speaker = e.get("label", "?")
        elif kind == "speechComplete" and current is not None:
            text = e.get("transcript", "").strip()
            if text:
                turns.append({
                    "id": f"T{e.get('turnId', current['turn_id'])}",
                    "speaker": speaker,
                    "start_ms": current["start_ms"],
                    "end_ms": e.get("audioProcessedMs"),
                    "text": text,
                    "words": current["words"],
                })
            current = None
    return turns


def word_times(turn: dict) -> list[tuple[str, int]]:
    """Final words of the turn with their end times; proportional when partials disagree."""
    final = turn["text"].split()
    partial = turn["words"]
    if [w for w, _ in partial] == final:
        return [(w, min(max(t, turn["start_ms"]), turn["end_ms"])) for w, t in partial]
    total = sum(len(w) + 1 for w in final)
    span = turn["end_ms"] - turn["start_ms"]
    out, done = [], 0
    for w in final:
        done += len(w) + 1
        out.append((w, turn["start_ms"] + span * done // total))
    return out


def split_turn(turn: dict) -> list[dict]:
    words = word_times(turn)
    base = {k: turn[k] for k in ("id", "speaker", "start_ms", "end_ms", "text")}
    if len(words) <= MAX_WORDS or turn["start_ms"] is None or turn["end_ms"] is None:
        return [base]

    phrases: list[list[tuple[str, int]]] = [[]]
    for i, (word, at) in enumerate(words):
        phrases[-1].append((word, at))
        if i + 1 == len(words):
            break
        sentence_end = SENTENCE_END.search(word) and len(phrases[-1]) >= 2
        ahead = words[i + 1:i + 1 + LOOKAHEAD]
        pause = (words[i + 1][1] - at >= PAUSE_MS and len(phrases[-1]) >= 3
                 and not any(SENTENCE_END.search(w) for w, _ in ahead))
        if sentence_end or pause:
            phrases.append([])

    if len(phrases) == 1:
        return [base]
    segments, start = [], turn["start_ms"]
    letters = string.ascii_lowercase
    for n, phrase in enumerate(phrases):
        last = n + 1 == len(phrases)
        end = turn["end_ms"] if last else min(phrase[-1][1] + 300, turn["end_ms"])
        segments.append({
            "id": f"{turn['id']}{letters[n] if n < 26 else n}",
            "turn": turn["id"],
            "speaker": turn["speaker"],
            "start_ms": start,
            "end_ms": end,
            "text": " ".join(w for w, _ in phrase),
        })
        start = end
    return segments


def segment(events: list[dict]) -> list[dict]:
    return [seg for turn in read_turns(events) for seg in split_turn(turn)]


def write(base: Path, segments: list[dict]) -> None:
    base.with_name(base.name + ".transcript.json").write_text(
        json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
    base.with_name(base.name + ".transcript.txt").write_text(
        "".join(f"{s['id']} [{s['speaker']}] {fmt(s['start_ms'])} {s['text']}\n" for s in segments),
        encoding="utf-8")


def main(arg: str) -> list[dict]:
    path = Path(arg)
    base = path.with_name(path.name.split(".")[0])
    events_path = base.with_name(base.name + ".events.jsonl")
    if not events_path.exists():
        sys.exit(f"Missing {events_path}")
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    segments = segment(events)
    write(base, segments)
    split = sorted({s["turn"] for s in segments if "turn" in s}, key=lambda t: int(t[1:]))
    print(f"{len(segments)} segments · split {', '.join(split) or 'nothing'} · saved {base.name}.transcript.json")
    for s in segments:
        if "turn" in s:
            print(f"  {s['id']:>5} {fmt(s['start_ms'])} {s['text']}")
    return segments


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
