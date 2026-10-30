"""Run the whole KORA Scribe pipeline on one recording.

Usage:
    python scripts/run_pipeline.py audio/lentes3.wav

Steps: transcribe (Muse Voice Transcribe) -> draft the SOAP note -> verify it.
Writes <name>.transcript.json, <name>.note.json and <name>.verification.json next to the audio.
Accepts .wav at 16 kHz mono; any other file (.m4a, other rates) is converted first with afconvert.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
import wave
from pathlib import Path

import draft_note
import transcribe_file
import verify_note


def ensure_wav(path: Path) -> Path:
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as w:
                if (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2):
                    return path
        except wave.Error:
            pass
    out = path.with_name(path.stem + "-16k.wav")
    print(f"Converting {path.name} -> {out.name}")
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(path), str(out)], check=True)
    return out


def step(title: str) -> float:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")
    return time.time()


def main(audio: Path) -> None:
    audio = ensure_wav(audio)
    base = audio.with_suffix("")

    t = step("1/3  Transcribe (Muse Voice Transcribe)")
    asyncio.run(transcribe_file.transcribe(audio))
    print(f"({time.time() - t:.0f} s)")

    t = step("2/3  Draft SOAP note")
    draft_note.main(Path(f"{base}.transcript.json"))
    print(f"({time.time() - t:.0f} s)")

    t = step("3/3  Verify note")
    verify_note.main(Path(f"{base}.note.json"))
    print(f"({time.time() - t:.0f} s)")

    print(f"\nDone. Files: {base.name}.transcript.json · {base.name}.note.json · {base.name}.verification.json")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
