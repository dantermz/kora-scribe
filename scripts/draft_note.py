"""Draft a SOAP note from a diarized transcript, citing the turn behind every line.

Usage:
    python scripts/draft_note.py audio/caso6.transcript.json

Reads the transcript written by transcribe_file.py and writes <name>.note.json next to it.
Uses Muse Spark Open on Baseten by default. To use Muse Glimmer (or any other
OpenAI-compatible endpoint), set DRAFT_BASE_URL, DRAFT_API_KEY and DRAFT_MODEL in .env.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent

SYSTEM_PROMPT = """Eres un asistente de documentación clínica. Tu único trabajo es ESTRUCTURAR en formato SOAP lo que se dijo en una consulta. No diagnosticas, no recomiendas y no agregas nada.

Recibes la transcripción como una lista de turnos. Cada turno tiene un id (T0, T1, ...), un hablante (A, B, ...) y un texto. Los turnos largos vienen partidos en frases (T13a, T13b, ...): cita la frase exacta de donde sale cada dato, no todas las frases del turno. No sabes de antemano qué hablante es el médico: dedúcelo por el contenido (quien explora, mide signos e indica el plan).

Reglas obligatorias:
1. Cada línea de la nota debe citar en "cites" los ids de los turnos que la sustentan. Sin cita, no hay línea.
2. Escribe solo lo que se dijo. No agregues diagnósticos, grados, clasificaciones, dosis, estudios ni resultados que nadie mencionó.
3. Si alguien se corrige ("no, perdón"), usa el valor corregido.
4. Lo que el paciente refiere (síntomas, medicamentos que tomó por su cuenta) va en S y nunca en P. P contiene solo lo que el médico indicó.
5. A contiene solo la impresión que el médico expresó en voz alta. Si no expresó ninguna, deja A vacía.
6. Omite la plática que no es clínica (saludos, despedidas, temas personales).
7. Si una línea se basa en una respuesta corta del paciente ("sí", "no", "catorce"), cita también el turno de la pregunta del médico, porque la respuesta sola no se entiende.
8. Si el médico resume en voz alta lo que le contó el paciente ("Entonces, ..."), cita también esa frase del resumen en las líneas de S que correspondan: la voz del médico suele transcribirse mejor que la del paciente. Si el resumen y lo que se transcribió del paciente no coinciden en un dato, no juntes las dos versiones en una línea: escribe la del resumen y cita los dos turnos (el médico confirmará).
9. Redacta en español, en estilo de nota médica breve y en tercera persona. NO copies las frases de la transcripción: reescríbelas como las escribiría un médico en el expediente. Escribe las cifras con números y unidades ("temperatura treinta y seis punto ocho" → "Temperatura 36.8 °C"). Una respuesta corta se redacta junto con su pregunta ("¿Eres alérgica a algún medicamento?" / "No, a ninguno" → "Niega alergia a medicamentos").
10. Si una palabra de la transcripción no tiene sentido (probable error de transcripción), no la interpretes ni la adivines: escribe [ininteligible] en su lugar para que el médico lo revise.

Ejemplo de estilo (de otra consulta, no lo copies):
Transcripción: T3 [B] "Tengo tos desde el lunes, como con flemas", T4 [A] "¿Fiebre?", T5 [B] "No, nada", T6 [A] "Saturación noventa y siete, pulmones con estertores en base derecha".
Nota: S: "Tos con flemas desde el lunes" (T3) · "Niega fiebre" (T4, T5) — O: "SpO2 97 %" (T6) · "Estertores en base pulmonar derecha" (T6).

Responde SOLO con un objeto JSON válido, sin texto antes ni después, con esta forma:
{
  "clinician_speaker": "A",
  "S": [{"text": "...", "cites": ["T1"]}],
  "O": [{"text": "...", "cites": ["T12"]}],
  "A": [{"text": "...", "cites": ["T13"]}],
  "P": [{"text": "...", "cites": ["T13"]}]
}"""


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    env.update({k: v for k, v in os.environ.items() if k.startswith(("DRAFT_", "BASETEN_", "VERIFY_"))})
    return env


def make_client(env: dict[str, str], role: str = "DRAFT") -> tuple[OpenAI, str]:
    """Client for the drafter (DRAFT_*) or the verifier (VERIFY_*); both default to Spark Open on Baseten.

    Keeping them separate lets the drafter be swapped (e.g. Muse Glimmer on Modal) while the
    verifier stays the same, so two drafters are judged by the same checks."""
    base_url = env.get(f"{role}_BASE_URL", "https://inference.baseten.co/v1")
    api_key = env.get(f"{role}_API_KEY") or env.get("BASETEN_API_KEY")
    model = env.get(f"{role}_MODEL") or env.get("BASETEN_MODEL")
    if not api_key or not model:
        sys.exit(f"Missing BASETEN_API_KEY / BASETEN_MODEL (or {role}_*) in .env")
    return OpenAI(base_url=base_url, api_key=api_key, timeout=600), model


def model_options(env: dict[str, str], role: str = "DRAFT") -> dict:
    """Optional reasoning effort, e.g. DRAFT_REASONING=low for Muse Glimmer."""
    effort = env.get(f"{role}_REASONING")
    return {"reasoning_effort": effort} if effort else {}


def extract_json(text: str) -> dict:
    """The model may reason before answering; keep the last JSON object it wrote."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object in the model's answer")
    return json.loads(text[start:end + 1])


def main(transcript_path: Path) -> None:
    turns = json.loads(transcript_path.read_text(encoding="utf-8"))
    compact = [{"id": t["id"], "speaker": t["speaker"], "text": t["text"]} for t in turns]

    env = load_env()
    client, model = make_client(env, "DRAFT")
    options = model_options(env, "DRAFT")
    print(f"Drafting with {model} · {len(turns)} turns" + (f" · reasoning {options['reasoning_effort']}" if options else ""))
    # The model occasionally answers with no JSON (an empty or cut-off reply); ask again, up to 3 times.
    for attempt in range(1, 4):
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(compact, ensure_ascii=False)},
            ],
            **options,
        )
        raw = response.choices[0].message.content or ""
        try:
            note = extract_json(raw)
            break
        except (ValueError, json.JSONDecodeError) as error:
            debug = transcript_path.with_name(transcript_path.name.replace(".transcript.json", ".note.raw.txt"))
            debug.write_text(raw, encoding="utf-8")
            if attempt == 3:
                sys.exit(f"Could not parse the note after 3 tries ({error}). Last answer saved to {debug.name}")
            print(f"  attempt {attempt}: no valid JSON in the answer ({error}); asking again")

    note["model"] = model
    note["source"] = transcript_path.name
    out = transcript_path.with_name(transcript_path.name.replace(".transcript.json", ".note.json"))
    out.write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Clinician: speaker {note.get('clinician_speaker', '?')}\n")
    for section in ("S", "O", "A", "P"):
        print(section)
        for line in note.get(section, []):
            print(f"  - {line.get('text', '')}  {line.get('cites', [])}")
    usage = response.usage
    if usage:
        print(f"\nTokens: {usage.prompt_tokens} in · {usage.completion_tokens} out")
    print(f"Saved {out.name}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
