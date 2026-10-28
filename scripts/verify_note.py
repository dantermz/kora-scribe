"""Verify a drafted SOAP note against its transcript with four checks.

Usage:
    python scripts/verify_note.py audio/caso6.note.json

Reads <name>.note.json and <name>.transcript.json, writes <name>.verification.json.

Checks (the first two and the fourth are plain code; the third asks a model):
  1. Citation  every cited turn exists, and every number in the line appears in those turns.
  2. Source    O, A and P lines must cite the clinician; S lines that cite only the
               patient are kept but labelled as patient-reported.
  3. Scope     Muse Spark Open checks that no line says more than its turns, and flags
               non-clinical lines and doubtful medical terms.
  4. Coverage  the note has the minimum sections a general consultation needs.

Each line ends up green (supported), yellow (needs a look) or red (unsupported).
Lines that cite only the patient are tagged as patient-reported. The note is never final until the clinician signs it.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

from draft_note import extract_json, load_env, make_client

SECTIONS = ("S", "O", "A", "P")
RANK = {"green": 0, "yellow": 1, "red": 2}
ICON = {"green": "✅", "yellow": "🟡", "red": "🔴"}

# ---------------------------------------------------------------- numbers

UNITS = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
    "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17,
    "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiun": 21, "veintiuno": 21,
    "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25,
    "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
}
TENS = {
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
    "setenta": 70, "ochenta": 80, "noventa": 90,
}
HUNDREDS = {
    "cien": 100, "ciento": 100, "doscientos": 200, "trescientos": 300,
    "cuatrocientos": 400, "quinientos": 500, "seiscientos": 600,
    "setecientos": 700, "ochocientos": 800, "novecientos": 900,
}


def plain(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def spoken_numbers(text: str) -> set[str]:
    """Numbers in a transcript, whether written as digits or spoken as Spanish words.

    "tres treinta y seis punto ocho" gives {"3", "36.8"}; "quinientos" gives {"500"}.
    """
    found = {n.replace(",", ".") for n in re.findall(r"\d+(?:[.,]\d+)?", text)}
    tokens = re.findall(r"[a-z]+|\d+", plain(text))

    value, slot, i = None, None, 0  # slot: the smallest place already filled

    def flush() -> None:
        nonlocal value, slot
        if value is not None:
            found.add(str(value))
        value, slot = None, None

    while i < len(tokens):
        word = tokens[i]
        if word in HUNDREDS:
            if slot is not None:
                flush()
            value, slot = HUNDREDS[word], "hundreds"
        elif word in TENS:
            if slot in ("tens", "units"):
                flush()
            value, slot = (value or 0) + TENS[word], "tens"
        elif word in UNITS:
            if slot == "units" or (slot == "tens" and i > 0 and tokens[i - 1] != "y"):
                flush()
            value, slot = (value or 0) + UNITS[word], "units"
        elif word == "y" and slot == "tens":
            pass
        elif word == "punto" and value is not None and i + 1 < len(tokens) and tokens[i + 1] in UNITS:
            whole = value
            flush()
            found.discard(str(whole))
            found.add(f"{whole}.{UNITS[tokens[i + 1]]}")
            i += 1
        else:
            flush()
        i += 1
    flush()
    return found


def line_numbers(text: str) -> set[str]:
    text = re.sub(r"/10\b", "", text)  # pain scale "6/10": the 10 is the scale, not a fact
    return {n.replace(",", ".") for n in re.findall(r"\d+(?:[.,]\d+)?", text)}


# ---------------------------------------------------------------- checks


def check_citation(line: dict, turns: dict[str, dict]) -> list[tuple[str, str]]:
    cites = line.get("cites", [])
    if not cites:
        return [("red", "Sin cita: ninguna parte de la transcripción la sustenta.")]
    missing = [c for c in cites if c not in turns]
    if missing:
        return [("red", f"Cita turnos que no existen: {', '.join(missing)}.")]
    said = set().union(*(spoken_numbers(turns[c]["text"]) for c in cites))
    unsupported = sorted(line_numbers(line.get("text", "")) - said)
    if unsupported:
        return [("red", f"Cifras que no aparecen en los turnos citados: {', '.join(unsupported)}.")]
    return []


def check_source(section: str, line: dict, turns: dict[str, dict], clinician: str) -> list[tuple[str, str]]:
    speakers = {turns[c]["speaker"] for c in line.get("cites", []) if c in turns}
    if not speakers:
        return []
    if section == "S":
        return []  # S is what the patient reports; the label is set in main()
    if clinician not in speakers:
        return [("red", f"En {section} solo puede ir lo que dijo el médico, y esta línea cita al paciente.")]
    if len(speakers) > 1:
        return [("yellow", f"En {section} mezcla lo que dijo el médico con lo que dijo el paciente.")]
    return []


SCOPE_PROMPT = """Eres un revisor de notas clínicas. Para cada línea recibes su texto y los turnos de la transcripción que cita. No juzgas si la medicina es correcta: solo si la línea es fiel a lo que se dijo.

Marca cada línea con uno de estos veredictos:
- "ok": dice lo mismo que sus turnos, sin agregar nada.
- "adds": agrega algo que los turnos no dicen (un diagnóstico, grado, dosis, unidad, fecha, causa o interpretación).
- "not_clinical": no aporta información clínica: plática personal o social, planes o eventos del paciente, o preguntas del paciente que no describen un síntoma ni un antecedente (por ejemplo "¿podré ir a mi fiesta?" o "¿puedo jugar el torneo?"). Lo que el médico respondió a esa pregunta sí puede ir en el plan.
- "doubtful_term": usa un término médico que no existe o que parece un error, ya sea al dictar o al transcribir (por ejemplo, una palabra parecida a un término real).

Además, revisa TODAS las líneas solo buscando términos médicos que no existan o que parezcan mal transcritos, y lístalos en "doubtful_terms" aunque ya hayas dado otro veredicto a esa línea.

Responde SOLO con JSON válido:
{"lines": [{"id": "S1", "verdict": "ok", "reason": "frase breve en español, vacía si es ok"}],
 "doubtful_terms": [{"id": "O5", "term": "...", "probably": "..."}]}"""

SCOPE_LEVEL = {"ok": None, "adds": "red", "not_clinical": "yellow", "doubtful_term": "yellow"}
SCOPE_LABEL = {
    "adds": "Dice más que sus turnos",
    "not_clinical": "No es información clínica",
    "doubtful_term": "Término dudoso (error al dictar o al transcribir)",
}


def check_scope(lines: list[dict], turns: dict[str, dict]) -> tuple[dict[str, list[tuple[str, str]]], dict]:
    payload = [
        {
            "id": line["id"],
            "section": line["section"],
            "text": line["text"],
            "turns": [{"id": c, "text": turns[c]["text"]} for c in line["cites"] if c in turns],
        }
        for line in lines
    ]
    client, model = make_client(load_env())
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": SCOPE_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )
    raw = response.choices[0].message.content or ""
    meta = {"model": model}
    if response.usage:
        meta["tokens"] = {"in": response.usage.prompt_tokens, "out": response.usage.completion_tokens}
    try:
        answer = extract_json(raw)
        verdicts = answer.get("lines", [])
        terms = answer.get("doubtful_terms", [])
    except (ValueError, json.JSONDecodeError):
        meta["error"] = "Scope check answer could not be parsed; every line needs a manual look."
        return {line["id"]: [("yellow", "El revisor de alcance no respondió; revisar a mano.")] for line in lines}, meta

    issues: dict[str, list[tuple[str, str]]] = {}
    for item in verdicts:
        level = SCOPE_LEVEL.get(item.get("verdict"))
        if level:
            reason = item.get("reason", "").strip()
            label = SCOPE_LABEL[item["verdict"]]
            issues.setdefault(item.get("id"), []).append((level, f"{label}: {reason}" if reason else label))
    for term in terms:
        found = issues.setdefault(term.get("id"), [])
        if not any("Término dudoso" in reason for _, reason in found):
            hint = f", ¿quiso decir «{term['probably']}»?" if term.get("probably") else ""
            found.append(("yellow", f"Término dudoso: «{term.get('term', '?')}»{hint}"))
    return issues, meta


# Known slips: (written, probably meant). They can come from the speech-to-text model or
# from the clinician misspeaking; either way the clinician must confirm. Code, not a model,
# so a phrase already seen is never missed. Add a pair every time a test finds a new one.
TERM_WATCHLIST = [
    ("pulso medio", "pulso pedio"),
    ("pulso pedido", "pulso pedio"),
    ("me siento bien jugando", "me torcí jugando"),
]


def check_terms(line: dict) -> list[tuple[str, str]]:
    text = plain(line.get("text", ""))
    issues = []
    for heard, meant in TERM_WATCHLIST:
        if meant and plain(heard) in text:
            issues.append(("yellow", f"Término dudoso conocido: «{heard}», ¿quiso decir «{meant}»? (error al dictar o al transcribir)"))
    return issues


COVERAGE = {
    "Motivo de consulta": lambda note: bool(note["S"]),
    "Alergias": lambda note: any("alerg" in plain(l["text"]) for s in SECTIONS for l in note[s]),
    "Signos vitales": lambda note: any(
        re.search(r"temperatura|presion|\bta\b|frecuencia|\bfc\b|\bfr\b|saturacion|spo2|peso|glucosa", plain(l["text"]))
        for l in note["O"]
    ),
    "Exploración física": lambda note: len(note["O"]) > 0,
    "Plan": lambda note: bool(note["P"]),
}


def check_coverage(note: dict) -> list[str]:
    return [item for item, present in COVERAGE.items() if not present(note)]


# ---------------------------------------------------------------- main


def main(note_path: Path) -> None:
    note = json.loads(note_path.read_text(encoding="utf-8"))
    transcript_path = note_path.with_name(note_path.name.replace(".note.json", ".transcript.json"))
    turns = {t["id"]: t for t in json.loads(transcript_path.read_text(encoding="utf-8"))}
    clinician = note.get("clinician_speaker", "A")
    for section in SECTIONS:
        note.setdefault(section, [])

    lines = []
    for section in SECTIONS:
        for n, line in enumerate(note[section], start=1):
            lines.append({"id": f"{section}{n}", "section": section,
                          "text": line.get("text", ""), "cites": line.get("cites", [])})

    print(f"Verifying {len(lines)} lines · clinician is speaker {clinician}")
    scope_issues, scope_meta = check_scope(lines, turns)

    for line in lines:
        issues = (
            check_citation(line, turns)
            + check_source(line["section"], line, turns, clinician)
            + scope_issues.get(line["id"], [])
        )
        if not any("Término dudoso" in r for _, r in issues):
            issues += check_terms(line)
        line["issues"] = [{"level": level, "reason": reason} for level, reason in issues]
        speakers = {turns[c]["speaker"] for c in line["cites"] if c in turns}
        line["patient_reported"] = bool(speakers) and clinician not in speakers
        line["status"] = max((level for level, _ in issues), key=RANK.get, default="green")

    missing = check_coverage(note)
    red = sum(line["status"] == "red" for line in lines)
    yellow = sum(line["status"] == "yellow" for line in lines)
    result = {
        "source": note_path.name,
        "clinician_speaker": clinician,
        "status": "needs_revision" if red else "ready_for_signoff",
        "summary": {"green": len(lines) - red - yellow, "yellow": yellow, "red": red},
        "coverage_missing": missing,
        "scope_check": scope_meta,
        "lines": lines,
    }
    out = note_path.with_name(note_path.name.replace(".note.json", ".verification.json"))
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    current = None
    for line in lines:
        if line["section"] != current:
            current = line["section"]
            print(f"\n{current}")
        tag = " 💬 referido" if line["patient_reported"] else ""
        print(f"  {ICON[line['status']]} {line['text']}  {line['cites']}{tag}")
        for issue in line["issues"]:
            print(f"       {ICON[issue['level']]} {issue['reason']}")

    print(f"\nCoverage: {'complete' if not missing else 'missing ' + ', '.join(missing)}")
    print(f"Lines: {result['summary']['green']} ✅  {yellow} 🟡  {red} 🔴")
    print(f"Status: {result['status']} · the clinician must review and sign before the note is final")
    if "tokens" in scope_meta:
        print(f"Scope check tokens: {scope_meta['tokens']['in']} in · {scope_meta['tokens']['out']} out")
    print(f"Saved {out.name}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
