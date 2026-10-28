"""Transcribe an audio file with Muse Voice Transcribe (speaker diarization).

Usage:
    python scripts/transcribe_file.py audio/caso4.wav

The file must be 16 kHz, mono, 16-bit PCM WAV. On a Mac, convert any recording with:
    afconvert -f WAVE -d LEI16@16000 -c 1 input.m4a audio/caso4.wav

Writes three files next to the audio:
    <name>.events.jsonl     every raw event from the server
    <name>.transcript.json  one object per turn: id, speaker, start_ms, end_ms, text
    <name>.transcript.txt   the readable transcript, one turn per line
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
import wave
from pathlib import Path

import websockets

URL = "wss://api.meta.ai/v1/asr/realtime"
MODEL = "muse-voice-transcribe-1.0"
CHUNK_MS = 100
SPEED = 2.0  # send audio 2x faster than real time

# Clinical terms to bias recognition. Add more as you find mistakes.
KEYWORDS = [
    "metformina", "glibenclamida", "losartán", "paracetamol", "sulfato ferroso",
    "ácido fólico", "Tdpa", "hemoglobina glucosilada", "monofilamento",
    "hidrocoloide", "fibrina", "desbridamiento", "rinorrea", "sibilancias",
    "estertores", "fóvea", "fondo uterino", "torcí", "esguince", "pulso pedio",
    "maléolo", "equimosis", "peroneoastragalino", "ibuprofeno", "radiografía",
]


def load_key() -> str:
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("MODEL_API_KEY="):
                os.environ.setdefault("MODEL_API_KEY", line.split("=", 1)[1].strip())
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        sys.exit("Missing MODEL_API_KEY in .env")
    return key


def fmt(ms: int | None) -> str:
    if ms is None:
        return "[--:--]"
    return f"[{ms // 60000:02d}:{ms // 1000 % 60:02d}]"


def read_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
            sys.exit(
                f"{path.name} must be 16 kHz mono 16-bit. Convert it with:\n"
                f"  afconvert -f WAVE -d LEI16@16000 -c 1 {path.name} {path.stem}-16k.wav"
            )
        return w.readframes(w.getnframes())


async def transcribe(path: Path) -> None:
    pcm = read_pcm(path)
    events_path = path.with_suffix(".events.jsonl")
    text_path = path.with_suffix(".transcript.txt")
    json_path = path.with_suffix(".transcript.json")
    turns: list[dict] = []
    starts: dict[int, int] = {}
    speaker = "?"

    async with websockets.connect(f"{URL}?sessionId=kora-{uuid.uuid4()}") as ws:
        await ws.send(json.dumps({
            "authorization": {"accessToken": f"Bearer {load_key()}"},
            "audioEncoding": "PCM_16KHZ",
            "model": MODEL,
            "mode": "DIARIZATION",
            "partialMode": "CUMULATIVE",
            "emitAudioProgress": False,
            "languageBias": ["Spanish"],
            "keywords": KEYWORDS,
        }))
        ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if "sessionId" not in ack:
            sys.exit(f"Handshake rejected: {ack}")
        print(f"Connected · session {ack['sessionId']} · {len(pcm) / 32000:.0f} s of audio")

        async def send_audio() -> None:
            step = 16000 * 2 * CHUNK_MS // 1000
            for i in range(0, len(pcm), step):
                await ws.send(pcm[i:i + step])
                await asyncio.sleep(CHUNK_MS / 1000 / SPEED)
            await ws.send(json.dumps({"type": "endStream"}))

        sender = asyncio.create_task(send_audio())
        with events_path.open("w") as log:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                msg = json.loads(raw)
                log.write(json.dumps(msg, ensure_ascii=False) + "\n")
                kind = msg.get("type")
                if kind == "speechStart":
                    starts[msg["turnId"]] = msg.get("audioProcessedMs", 0)
                elif kind == "speaker":
                    speaker = msg.get("label", "?")
                elif kind == "speechComplete":
                    text = msg.get("transcript", "").strip()
                    if not text:
                        continue
                    turn_id = msg.get("turnId", len(turns))
                    turn = {
                        "id": f"T{turn_id}",
                        "speaker": speaker,
                        "start_ms": starts.get(turn_id),
                        "end_ms": msg.get("audioProcessedMs"),
                        "text": text,
                    }
                    turns.append(turn)
                    print(f"{turn['id']:>4} [{speaker}] {fmt(turn['start_ms'])} {text}")
                elif kind == "error":
                    print(f"ERROR: {msg.get('message', msg)}")
        await sender

    json_path.write_text(json.dumps(turns, ensure_ascii=False, indent=2), encoding="utf-8")
    text_path.write_text(
        "".join(f"{t['id']} [{t['speaker']}] {fmt(t['start_ms'])} {t['text']}\n" for t in turns),
        encoding="utf-8",
    )
    print(f"\n{len(turns)} turns · saved {json_path.name}, {text_path.name}, {events_path.name}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    asyncio.run(transcribe(Path(sys.argv[1])))
