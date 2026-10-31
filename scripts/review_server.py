"""Open the review-and-sign page for one processed consultation.

Usage:
    python scripts/review_server.py audio/lentes5

Reads <name>.transcript.json, <name>.verification.json (and <name>.wav if present),
serves review/index.html at http://localhost:8770, and saves the signed note as
<name>.signed.json when the clinician signs. Everything runs on this machine.
"""

from __future__ import annotations

import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "review" / "index.html"
PORT = 8770
SUFFIXES = (".verification.json", ".transcript.json", ".note.json", ".signed.json", ".wav")


def case_base(arg: str) -> Path:
    path = Path(arg)
    name = path.name
    for suffix in SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return path.with_name(name)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def find_audio(base: Path) -> Path | None:
    for candidate in (base.with_name(base.name + ".wav"), base.with_name(base.name + "-16k.wav")):
        if candidate.exists():
            return candidate
    return None


def make_handler(base: Path):
    transcript = read_json(base.with_name(base.name + ".transcript.json"))
    verification = read_json(base.with_name(base.name + ".verification.json"))
    if transcript is None or verification is None:
        sys.exit(f"Missing {base.name}.transcript.json or {base.name}.verification.json. "
                 f"Run: python scripts/run_pipeline.py {base}.wav")
    audio = find_audio(base)
    case = {
        "case": base.name,
        "transcript": transcript,
        "verification": verification,
        "note": read_json(base.with_name(base.name + ".note.json")),
        "has_audio": audio is not None,
    }
    signed_path = base.with_name(base.name + ".signed.json")

    class Handler(BaseHTTPRequestHandler):
        def send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            route = self.path.split("?")[0]
            if route in ("/", "/index.html"):
                self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif route == "/case.json":
                self.send(200, json.dumps(case, ensure_ascii=False).encode(), "application/json")
            elif route == "/audio.wav" and audio:
                self.send(200, audio.read_bytes(), "audio/wav")
            else:
                self.send(404, b"Not found", "text/plain")

        def do_POST(self) -> None:
            if self.path != "/sign":
                self.send(404, b"Not found", "text/plain")
                return
            length = int(self.headers.get("Content-Length", 0))
            signed = json.loads(self.rfile.read(length) or b"{}")
            signed_path.write_text(json.dumps(signed, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Signed note saved: {signed_path}")
            self.send(200, json.dumps({"saved": signed_path.name}).encode(), "application/json")

        def log_message(self, *args) -> None:
            pass

    return Handler


def main(arg: str) -> None:
    base = case_base(arg)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), make_handler(base))
    url = f"http://localhost:{PORT}"
    print(f"Reviewing {base.name} at {url}  (Ctrl+C to stop)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
