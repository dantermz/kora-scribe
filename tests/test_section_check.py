"""Section check for verify_note: flags lines written in the wrong SOAP section.

Usage:
    python tests/test_section_check.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from verify_note import check_section


def issues(section: str, text: str):
    return check_section({"section": section, "text": text})


def main() -> None:
    # A line with plan language -> flagged
    got = issues("A", "Lo siento, el sábado no")
    assert len(got) == 1 and got[0][0] == "yellow", got
    assert got[0][1] == "Parece una indicación del plan: ¿va en P?", got

    # A line stating a diagnosis -> not flagged
    assert issues("A", "Esguince de tobillo derecho") == []

    # P line with an instruction -> not flagged
    assert issues("P", "Paracetamol 500 mg cada 8 horas si hay dolor") == []

    # P line that only states a diagnosis -> flagged
    got = issues("P", "Es un esguince")
    assert len(got) == 1 and got[0][0] == "yellow", got
    assert got[0][1] == "Parece una impresión diagnóstica: ¿va en A?", got

    # P lines with instruction verbs from the broadened vocabulary -> not flagged
    assert issues("P", "Solicitar química sanguínea con creatinina y potasio") == []
    assert issues("P", "Disminuir sal y evitar consumo diario de cabrito") == []
    assert issues("P", "Control en un mes") == []

    # Narrowed P rule: bare diagnosis phrase -> flagged ...
    got = issues("P", "Esguince de tobillo derecho")
    assert len(got) == 1 and got[0][0] == "yellow", got
    assert got[0][1] == "Parece una impresión diagnóstica: ¿va en A?", got
    # ... but a line that merely lacks plan words is not flagged
    assert issues("P", "Se explica el pronóstico y se resuelven dudas") == []

    print("9/9 section checks ok")


if __name__ == "__main__":
    main()
