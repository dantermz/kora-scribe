"""Verify a drafted SOAP note against its transcript with four checks.

Usage:
    python scripts/verify_note.py audio/caso6.note.json

Reads <name>.note.json and <name>.transcript.json, writes <name>.verification.json.

Checks (the first two and the fourth are plain code; the third asks a model):
  1. Citation  every cited turn exists, and every number in the line appears in those turns.
  2. Source    O, A and P lines must cite the clinician; S lines that cite only the
               patient are kept but labelled as patient-reported.
  3. Scope     Muse Spark Open (two passes, merged) checks that no line says more than its turns, and flags
               non-clinical lines and doubtful medical terms.
  4. Coverage  the note has the minimum sections a general consultation needs.
  5. Gaps      the transcript itself looks incomplete: a clinician question with no answer
               after it, or a long stretch of audio with no transcribed speech. The note can
               only be checked against what was transcribed, so lost speech must be flagged.
  6. Recap     when the clinician recaps the history aloud, a model compares that recap with
               what was transcribed from the patient. If they give a different value for the
               same fact (where, when, which side, how much), every S line citing either turn
               is flagged: one of the two was misheard, and the clinician decides which.

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

Algunos turnos traen "same_turn": las frases que la misma persona dijo justo antes o después, en el mismo turno. Úsalas para entender una frase cortada: si el turno citado es un fragmento o un titubeo (por ejemplo "si es una semana" justo antes de "si en una semana no mejora...") y la línea lo convierte en una indicación o un dato, es "adds".

Algunos turnos traen "before": el turno anterior de la otra persona, normalmente la pregunta a la que responde. Úsalo para interpretar respuestas cortas: si el médico preguntó "¿Eres alérgica a algún medicamento?" y la respuesta fue "No, ninguno", la línea "Niega alergia a medicamentos" es fiel ("ok").

Marca cada línea con uno de estos veredictos:
- "ok": dice lo mismo que sus turnos, sin agregar nada.
- "adds": agrega algo que los turnos no dicen (un diagnóstico, grado, dosis, fecha, causa o interpretación). También es "adds" cuando el turno tiene palabras que no tienen sentido (probable error de transcripción, por ejemplo "con gelada") y la línea las reemplaza por una interpretación (por ejemplo "con dificultad"): la línea debe dejar el hueco, no adivinar.

No cuentan como agregado: las unidades estándar implícitas en la práctica clínica (°C para temperatura, mmHg para presión arterial, lpm para frecuencia cardiaca, kg para peso, mg/dL para glucosa, mg para dosis de medicamentos que se expresan en miligramos), escribir con cifras lo que se dijo con palabras, y abreviaturas médicas comunes. Sí cuenta una unidad que cambia el valor o que no es la habitual para esa medición.
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


SCOPE_RUNS = 2  # the model check varies between runs; two passes, flags are merged


def check_scope(lines: list[dict], turns: dict[str, dict]) -> tuple[dict[str, list[tuple[str, str]]], dict]:
    ordered = sorted(turns.values(), key=lambda t: (t.get("start_ms") or 0))
    previous = {t["id"]: ordered[i - 1] for i, t in enumerate(ordered) if i > 0}
    following = {t["id"]: ordered[i + 1] for i, t in enumerate(ordered[:-1])}

    def with_context(turn_id: str) -> dict:
        turn = turns[turn_id]
        item = {"id": turn_id, "text": turn["text"]}
        before = previous.get(turn_id)
        if before and before["speaker"] != turn["speaker"]:
            item["before"] = {"id": before["id"], "text": before["text"]}
        # A phrase cut out of a longer turn: show what the speaker said right before and after,
        # so a false start ("si es una semana") is read as part of the full sentence.
        if "turn" in turn:
            same = [t for t in (previous.get(turn_id), following.get(turn_id))
                    if t and t.get("turn") == turn["turn"]]
            if same:
                item["same_turn"] = [{"id": t["id"], "text": t["text"]} for t in same]
        return item

    payload = [
        {
            "id": line["id"],
            "section": line["section"],
            "text": line["text"],
            "turns": [with_context(c) for c in line["cites"] if c in turns],
        }
        for line in lines
    ]
    client, model = make_client(load_env(), "VERIFY")
    meta: dict = {"model": model, "runs": 0, "tokens": {"in": 0, "out": 0}}
    issues: dict[str, list[tuple[str, str]]] = {}
    seen: set[tuple[str, str]] = set()

    def add(line_id: str, level: str, kind: str, reason: str) -> None:
        if (line_id, kind) in seen:
            return
        seen.add((line_id, kind))
        issues.setdefault(line_id, []).append((level, reason))

    for _ in range(SCOPE_RUNS):
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {"role": "system", "content": SCOPE_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        )
        if response.usage:
            meta["tokens"]["in"] += response.usage.prompt_tokens
            meta["tokens"]["out"] += response.usage.completion_tokens
        try:
            answer = extract_json(response.choices[0].message.content or "")
        except (ValueError, json.JSONDecodeError):
            continue
        meta["runs"] += 1
        for item in answer.get("lines", []):
            level = SCOPE_LEVEL.get(item.get("verdict"))
            if level:
                reason = item.get("reason", "").strip()
                label = SCOPE_LABEL[item["verdict"]]
                add(item.get("id"), level, item["verdict"], f"{label}: {reason}" if reason else label)
        for term in answer.get("doubtful_terms", []):
            hint = f", ¿quiso decir «{term['probably']}»?" if term.get("probably") else ""
            add(term.get("id"), "yellow", "doubtful_term", f"Término dudoso: «{term.get('term', '?')}»{hint}")

    if meta["runs"] == 0:
        meta["error"] = "Scope check answer could not be parsed; every line needs a manual look."
        return {line["id"]: [("yellow", "El revisor de alcance no respondió; revisar a mano.")] for line in lines}, meta
    return issues, meta


RECAP_PROMPT = """Eres un revisor de transcripciones clínicas. Recibes la transcripción de una consulta: cada frase con su id, quién habla y su texto.

Muchas veces el médico resume en voz alta lo que le contó el paciente (por ejemplo: "Entonces, dolor de cabeza en la nuca algunas mañanas, toma losartán de 50..."). La voz del paciente se oye más lejos y su transcripción puede tener errores; la del médico suele ser más clara.

Haz esto paso por paso:
1. Encuentra las frases del médico que resumen lo que refirió el paciente. Si no hay resumen, responde con listas vacías.
2. Divide el resumen en datos sueltos (cada síntoma, medicamento, cifra, lugar, momento...).
3. Para CADA dato del resumen, busca qué dijo el paciente sobre ese mismo dato y compáralos:
   - "same": dicen lo mismo, aunque con otras palabras.
   - "different": dan un valor distinto o contrario para el mismo dato (otro lugar, otro momento, otro lado, otra cifra, otra dosis, o uno afirma y el otro niega).
   - "absent": el paciente no habló de ese dato en la transcripción.

Responde SOLO con JSON válido:
{"recap_ids": ["T8a"],
 "facts": [{"fact": "dónde se midió la presión", "recap_id": "T8a", "recap_says": "cita textual breve",
            "patient_id": "T7", "patient_says": "cita textual breve", "verdict": "different"}]}"""

RECAP_RUNS = 2  # a model check is not deterministic; two independent passes, conflicts are merged


def ask_recap(payload: list[dict]) -> tuple[dict | None, dict]:
    client, model = make_client(load_env(), "VERIFY")
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": RECAP_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )
    usage = {"in": response.usage.prompt_tokens, "out": response.usage.completion_tokens} if response.usage else {}
    try:
        return extract_json(response.choices[0].message.content or ""), {"model": model, "tokens": usage}
    except (ValueError, json.JSONDecodeError):
        return None, {"model": model, "tokens": usage}


STOPWORDS = {"para", "como", "pero", "que", "una", "uno", "este", "esta", "tiene", "dijo", "refiere", "salio"}


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", plain(text)) if w not in STOPWORDS}


def check_recap(lines: list[dict], ordered: list[dict], clinician: str) -> tuple[dict, dict, dict]:
    """Compare the patient's transcribed words with the clinician's spoken recap.

    The comparison is between the two transcript turns, not between the note and the recap,
    so it holds whichever version the drafter chose. Returns (issues per line, turns to
    compare per line, meta)."""
    payload = [{"id": t["id"], "who": "médico" if t["speaker"] == clinician else "paciente", "text": t["text"]}
               for t in ordered]
    speaker = {t["id"]: t["speaker"] for t in ordered}
    meta: dict = {"runs": 0, "recap_ids": [], "conflicts": [], "tokens": {"in": 0, "out": 0}}
    seen = set()
    for _ in range(RECAP_RUNS):
        answer, run = ask_recap(payload)
        meta["model"] = run["model"]
        for k in ("in", "out"):
            meta["tokens"][k] += run["tokens"].get(k, 0)
        if answer is None:
            continue
        meta["runs"] += 1
        for r in answer.get("recap_ids", []):
            if speaker.get(r) == clinician and r not in meta["recap_ids"]:
                meta["recap_ids"].append(r)
        for f in answer.get("facts", []):
            if (f.get("verdict") == "different" and speaker.get(f.get("recap_id")) == clinician
                    and f.get("patient_id") in speaker and speaker[f["patient_id"]] != clinician
                    and (f["patient_id"], f["recap_id"]) not in seen):
                seen.add((f["patient_id"], f["recap_id"]))
                meta["conflicts"].append(f)
    if meta["runs"] == 0:
        meta["error"] = "Recap check answer could not be parsed."
    conflicts = meta["conflicts"]
    issues: dict[str, list[tuple[str, str]]] = {}
    related: dict[str, list[str]] = {}
    s_lines = [l for l in lines if l["section"] == "S"]
    for c in conflicts:
        # A recap often covers several facts in one phrase, so citing the recap alone is not
        # enough: flag the lines that cite the patient's turn, or, if none does, the lines that
        # cite the recap and share content words with what the patient said.
        targets = [l for l in s_lines if c["patient_id"] in l["cites"]]
        if not targets:
            said = content_words(c.get("patient_says", "")) | content_words(c.get("recap_says", ""))
            targets = [l for l in s_lines if c["recap_id"] in l["cites"] and content_words(l["text"]) & said]
        for line in targets:
            issues.setdefault(line["id"], []).append((
                "yellow",
                f"El paciente dijo «{c.get('patient_says', '?')}» ({c['patient_id']}) y tu resumen dice "
                f"«{c.get('recap_says', '?')}» ({c['recap_id']}). Escucha los dos y deja el dato correcto."))
            related.setdefault(line["id"], []).extend(t for t in (c["patient_id"], c["recap_id"])
                                                     if t not in line["cites"])
    return issues, related, meta


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


# Plan or instruction language: infinitives, nouns and phrases used in P.
# Compared against plain() text, so matching is accent-insensitive lower case.
PLAN_WORDS = re.compile(
    r"\b(usar|aplicar|tomar|reposo|regresar|venda|hielo|mg|disminuir|evitar|solicitar|"
    r"indicar|iniciar|suspender|continuar|aumentar|incrementar|cita|curacion|dieta)\b"
)
PLAN_ELEVADO = re.compile(r"\belevad[oa]s?\b")  # pie elevado / pierna elevada
PLAN_PHRASES = (
    re.compile(r"\bno\W+jugar\b"),
    re.compile(r"\bsabado\W+no\b"),
    re.compile(r"\bcontrol\W+en\b"),
    re.compile(r"\bcada\W+\w+\W+horas\b"),  # cada 8 horas / cada ocho horas
)


def has_plan_language(text: str) -> bool:
    text = plain(text)
    return bool(PLAN_WORDS.search(text) or PLAN_ELEVADO.search(text)
                or any(p.search(text) for p in PLAN_PHRASES))


# Diagnosis nouns (plain form, no accents) for the narrowed P rule: a P line is
# only flagged when it positively looks like a diagnosis, never for merely
# lacking words from the plan list.
ES_UN = re.compile(r"^\s*es\s+un[oa]s?\b")  # Es un esguince / Es una fractura
DIAGNOSIS = re.compile(
    r"\b(esguince|fractura|luxacion|desgarro|contusion|quemadura|herida|tendinitis|"
    r"lumbalgia|cervicalgia|dorsalgia|ciatica|artritis|artrosis|hipertension|hipotension|"
    r"diabetes|prediabetes|dislipidemia|hipercolesterolemia|obesidad|sobrepeso|anemia|"
    r"desnutricion|infeccion|faringitis|amigdalitis|otitis|sinusitis|bronquitis|neumonia|"
    r"tuberculosis|gripe|influenza|covid|resfriado|resfrio|gastritis|gastroenteritis|"
    r"colitis|apendicitis|colecistitis|hepatitis|pancreatitis|reflujo|ulcera|dermatitis|"
    r"eczema|eccema|psoriasis|celulitis|absceso|urticaria|micosis|impetigo|conjuntivitis|"
    r"blefaritis|glaucoma|catarata|cistitis|pielonefritis|prostatitis|vaginitis|"
    r"candidiasis|migrana|epilepsia|ansiedad|depresion|insomnio|asma|epoc|rinitis|"
    r"hernia|tumor|cancer|carcinoma|deshidratacion|insuficiencia|arritmia|infarto|"
    r"angina|hipotiroidismo|hipertiroidismo)\b"
)


def check_section(line: dict) -> list[tuple[str, str]]:
    """Flag a line written in the wrong SOAP section. Plain code, no model call."""
    section = line.get("section", "")
    text = line.get("text", "")
    if section == "A" and has_plan_language(text):
        return [("yellow", "Parece una indicación del plan: ¿va en P?")]
    if section == "P" and not has_plan_language(text):
        stated = plain(text)
        if ES_UN.match(stated) or DIAGNOSIS.search(stated):
            return [("yellow", "Parece una impresión diagnóstica: ¿va en A?")]
    return []


COVERAGE = {
    # Age and allergies alone are not a reason for the visit: S needs at least one other line.
    "Motivo de consulta": lambda note: any(
        not re.search(r"\banos\b|\bedad\b|alerg", plain(l["text"]))
        and plain(l["text"]).replace("[ininteligible]", "").strip(" .,;")  # a line that is only a gap says nothing
        for l in note["S"]
    ),
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


GAP_SECONDS = 5


def check_gaps(ordered: list[dict], clinician: str) -> list[dict]:
    """Signs that speech was lost before it reached the transcript."""
    gaps = []
    for i, turn in enumerate(ordered):
        nxt = ordered[i + 1] if i + 1 < len(ordered) else None
        text = turn["text"].strip()
        same_turn = nxt is not None and nxt.get("turn", nxt["id"]) == turn.get("turn", turn["id"])
        if (turn["speaker"] == clinician and text.endswith("?") and nxt and nxt["speaker"] == clinician
                and not same_turn):
            question = text[text.rfind("¿"):] if "¿" in text else text[-60:]
            gaps.append({
                "after": turn["id"],
                "kind": "unanswered_question",
                "reason": f"Pregunta sin respuesta registrada: «{question}» ({turn['id']}). "
                          "Posible respuesta del paciente perdida.",
            })
        if nxt and turn.get("end_ms") is not None and nxt.get("start_ms") is not None:
            silence = (nxt["start_ms"] - turn["end_ms"]) / 1000
            if silence >= GAP_SECONDS:
                gaps.append({
                    "after": turn["id"],
                    "kind": "silence",
                    "reason": f"{silence:.0f} s sin transcripción entre {turn['id']} y {nxt['id']}. "
                              "Puede ser una pausa o voz que no se captó.",
                })
    return gaps


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
    ordered = sorted(turns.values(), key=lambda t: (t.get("start_ms") or 0))
    recap_issues, recap_related, recap_meta = check_recap(lines, ordered, clinician)

    for line in lines:
        issues = (
            check_citation(line, turns)
            + check_source(line["section"], line, turns, clinician)
            + scope_issues.get(line["id"], [])
            + recap_issues.get(line["id"], [])
        )
        if recap_related.get(line["id"]):
            line["compare"] = recap_related[line["id"]]
        if not any("Término dudoso" in r for _, r in issues):
            issues += check_terms(line)
        issues += check_section(line)
        line["issues"] = [{"level": level, "reason": reason} for level, reason in issues]
        # Patient-reported: what the line states comes from the patient. Citing the clinician's
        # question next to the answer (drafting rule 7) does not make it the clinician's finding.
        # The clinician's spoken recap of the history is also the patient's account, not a finding.
        recap = set(recap_meta.get("recap_ids", []))
        content = [turns[c] for c in line["cites"] if c in turns and c not in recap
                   and not (turns[c]["speaker"] == clinician and turns[c]["text"].strip().endswith("?"))]
        from_recap = any(c in recap for c in line["cites"])
        line["patient_reported"] = (line["section"] == "S"
                                    and all(t["speaker"] != clinician for t in content)
                                    and bool(content or from_recap))
        line["status"] = max((level for level, _ in issues), key=RANK.get, default="green")

    # Small talk the scope check marked as non-clinical does not count toward coverage
    # (a question about a football tournament is not a reason for the visit).
    counted = {
        section: [l for l in lines if l["section"] == section
                  and not any(SCOPE_LABEL["not_clinical"] in i["reason"] for i in l["issues"])]
        for section in SECTIONS
    }
    missing = check_coverage(counted)
    gaps = check_gaps(ordered, clinician)
    if any(g["kind"] == "unanswered_question" for g in gaps):
        missing.append("Respuestas del paciente (hay preguntas sin respuesta registrada)")
    red = sum(line["status"] == "red" for line in lines)
    yellow = sum(line["status"] == "yellow" for line in lines)
    result = {
        "source": note_path.name,
        "clinician_speaker": clinician,
        "status": "needs_revision" if red else ("review_gaps" if gaps else "ready_for_signoff"),
        "summary": {"green": len(lines) - red - yellow, "yellow": yellow, "red": red},
        "coverage_missing": missing,
        "transcript_gaps": gaps,
        "scope_check": scope_meta,
        "recap_check": recap_meta,
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

    if gaps:
        print("\nPosible audio perdido")
        for gap in gaps:
            print(f"  🟡 {gap['reason']}")
    print(f"\nCoverage: {'complete' if not missing else 'missing ' + ', '.join(missing)}")
    print(f"Lines: {result['summary']['green']} ✅  {yellow} 🟡  {red} 🔴")
    print(f"Status: {result['status']} · the clinician must review and sign before the note is final")
    if "tokens" in scope_meta:
        print(f"Scope check tokens: {scope_meta['tokens']['in']} in · {scope_meta['tokens']['out']} out")
    if recap_meta.get("recap_ids") is not None:
        found = ", ".join(recap_meta["recap_ids"]) or "none"
        print(f"Clinician recap found in: {found}")
        for c in recap_meta.get("conflicts", []):
            print(f"  🟡 patient {c['patient_id']} «{c.get('patient_says')}» vs recap {c['recap_id']} «{c.get('recap_says')}»")
    print(f"Saved {out.name}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
