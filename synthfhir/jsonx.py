"""Robustes Herausschälen von JSON aus einer LLM-Antwort (Abschnitt 6.2).

Der Prompt verlangt reines JSON. Modelle halten sich nicht immer daran:
sie rahmen die Antwort in ```json ... ``` ein, stellen einen Satz voran oder
hängen eine Erklärung an. Diese Funktion holt trotzdem heraus, was da ist.

Wichtig für die Messung: Wenn hier nichts Verwertbares herauskommt, ist das
ein echtes Messergebnis (Fehlerkategorie "kein gültiges JSON", Abschnitt 8)
und kein Fehler, den man wegprogrammieren sollte. Deshalb wird bewusst NICHT
versucht, kaputtes JSON zu reparieren (keine Klammern ergänzen, keine
Anführungszeichen raten) – nur Verpackung wird entfernt.
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


def as_resource_list(payload: Any) -> list[dict]:
    """Normalisiert das Ergebnis der Variante A auf eine Ressourcenliste.

    Akzeptiert eine Liste von Ressourcen, ein Bundle oder eine einzelne
    Ressource – alles, was Modelle in der Praxis liefern.
    """
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and payload.get("resourceType") == "Bundle":
        items = [
            entry.get("resource")
            for entry in payload.get("entry", []) or []
            if isinstance(entry, dict)
        ]
    elif isinstance(payload, dict) and "resourceType" in payload:
        items = [payload]
    elif isinstance(payload, dict):
        # Häufige Ausweichform: {"resources": [...]} oder {"entry": [...]}
        for key in ("resources", "entry", "entries", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                items = value
                break
        else:
            raise JsonExtractionError(
                f"JSON enthält keine Ressourcenliste (Schlüssel: {sorted(payload)[:8]})."
            )
    else:
        raise JsonExtractionError(f"Unerwarteter JSON-Typ: {type(payload).__name__}")

    resources = [item for item in items if isinstance(item, dict) and item.get("resourceType")]
    if not resources:
        raise JsonExtractionError("JSON enthielt keine einzige Ressource mit 'resourceType'.")
    return resources
