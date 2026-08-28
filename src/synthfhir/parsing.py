"""Robustes Herausschälen von JSON aus einer LLM-Antwort.

Der Prompt verlangt reines JSON. Modelle halten sich nicht immer daran:
sie rahmen die Antwort in ```json ... ``` ein, stellen einen Satz voran oder
hängen eine Erklärung an. Diese Funktion holt trotzdem heraus, was da ist.

Bewusst wird NICHT versucht, kaputtes JSON zu reparieren – keine Klammern
ergänzen, keine Anführungszeichen raten. Nur Verpackung wird entfernt. Ein
unreparierbar kaputtes JSON ist ein ehrlicher Fehlschlag: Der Nutzer bekommt
dann eine Fehlermeldung statt stillschweigend geratener Daten.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*\n(.*?)\n?\s*```\s*$", re.DOTALL)


class JsonExtractionError(ValueError):
    """Aus der Antwort ließ sich kein gültiges JSON gewinnen."""


def _strip_code_fence(text: str) -> str:
    match = _FENCE_RE.match(text)
    return match.group(1) if match else text


def _scan_balanced(text: str, start: int) -> str | None:
    """Liest ab `start` genau einen ausbalancierten JSON-Wert.

    Berücksichtigt Zeichenketten und Escapes, damit Klammern innerhalb von
    Strings nicht mitgezählt werden.
    """
    opener = text[start]
    closer = {"{": "}", "[": "]"}[opener]
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def extract_json(text: str) -> Any:
    """Gibt das erste vollständige JSON-Dokument der Antwort zurück.

    Wirft `JsonExtractionError`, wenn nichts Parsbares gefunden wird.
    """
    if not text or not text.strip():
        raise JsonExtractionError("Die Antwort war leer.")

    candidate = _strip_code_fence(text.strip()).strip()

    # 1. Glücksfall: Die Antwort ist bereits sauberes JSON.
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # 2. Erstes '{' oder '[' suchen und von dort ausbalanciert lesen.
    for index, char in enumerate(candidate):
        if char in "{[":
            chunk = _scan_balanced(candidate, index)
            if chunk is None:
                continue
            try:
                return json.loads(chunk)
            except json.JSONDecodeError:
                continue

    raise JsonExtractionError(
        "Kein gültiges JSON in der Antwort gefunden "
        f"(Antwortlänge {len(text)} Zeichen, Anfang: {text[:120]!r})."
    )
