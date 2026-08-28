"""Deterministische ID- und Referenzvergabe.

Designprinzip des Produkts (PRD Block 6, ADR-001): Alles, was
deterministisch lösbar ist, gehört in Code. IDs sind deterministisch lösbar, also vergibt sie ausschließlich der
Code – niemals das Sprachmodell.

Eine bewusste Entscheidung, die aus der Phase 0 stammt und im Produkt gilt:

  Der Code vergibt die IDs neu und zieht bestehende Verweise über eine
  Abbildungstabelle mit. Er erfindet aber KEIN Ziel für einen Verweis, der
  ins Leere zeigt.

Warum? Würde der Code jede Referenz einfach auf "den ersten Patienten"
umbiegen, wäre die Zusage "0 kaputte Referenzen" trivial erfüllt und
zugleich wertlos: Sie würde eine falsche Verknüpfung verdecken statt sie zu
melden. Der Code besitzt den ID-Raum (Syntax), das Modell besitzt die
Verknüpfung (Semantik). Was ins Leere zeigt, findet die
Referenz-Integritätsprüfung in `integrity.py`.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

# Kurzpräfixe für die neuen IDs.
ID_PREFIXES = {"Patient": "pat", "Condition": "cond", "Observation": "obs"}

EXPECTED_TYPES = ("Patient", "Condition", "Observation")

_URL_TAIL_RE = re.compile(r"(?:^|/)([A-Z][A-Za-z]+)/([A-Za-z0-9\-.]{1,64})$")


@dataclass
class NormalisationResult:
    """Ergebnis der ID-Normalisierung eines Ressourcensatzes."""

    resources: list[dict]
    id_map: dict[str, str] = field(default_factory=dict)
    duplicate_ids_from_llm: list[str] = field(default_factory=list)
    unresolved_references: list[str] = field(default_factory=list)
    ambiguous_references: list[str] = field(default_factory=list)
    rewritten_references: int = 0
    unexpected_resource_types: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id_map": self.id_map,
            "duplicate_ids_from_llm": self.duplicate_ids_from_llm,
            "unresolved_references": self.unresolved_references,
            "ambiguous_references": self.ambiguous_references,
            "rewritten_references": self.rewritten_references,
            "unexpected_resource_types": self.unexpected_resource_types,
        }


def _alias_keys(resource_type: str, old_id: str) -> list[str]:
    """Alle Schreibweisen, unter denen ein Modell diese Ressource referenziert."""
    return [
        f"{resource_type}/{old_id}",
        old_id,
        f"urn:uuid:{old_id}",
    ]


def assign_ids(resources: list[dict]) -> NormalisationResult:
    """Vergibt neue IDs und zieht alle Verweise konsistent mit.

    Die Ressourcen werden dabei kopiert; die Eingabe bleibt unverändert,
    damit der Rohstand des Modells als Artefakt erhalten bleibt.
    """
    working = [copy.deepcopy(r) for r in resources]
    result = NormalisationResult(resources=working)

    counters: dict[str, int] = {}
    alias_to_new: dict[str, str] = {}
    ambiguous_aliases: set[str] = set()
    seen_old: set[tuple[str, str]] = set()

    # --- Schritt 1: neue IDs vergeben, Abbildungstabelle aufbauen ----------
    for resource in working:
        resource_type = str(resource.get("resourceType") or "Unknown")
        if resource_type not in EXPECTED_TYPES:
            result.unexpected_resource_types.append(resource_type)

        prefix = ID_PREFIXES.get(resource_type, resource_type.lower())
        counters[resource_type] = counters.get(resource_type, 0) + 1
        new_id = f"{prefix}-{counters[resource_type]:03d}"

        raw_id = resource.get("id")
        old_id = str(raw_id) if isinstance(raw_id, (str, int)) and str(raw_id).strip() else None

        if old_id:
            key = (resource_type, old_id)
            if key in seen_old:
                # Das Modell hat dieselbe ID zweimal vergeben. Innerhalb des
                # Bündels ist damit nicht mehr entscheidbar, welche Ressource
                # ein Verweis meint.
                result.duplicate_ids_from_llm.append(f"{resource_type}/{old_id}")
                for alias in _alias_keys(resource_type, old_id):
                    ambiguous_aliases.add(alias)
            else:
                seen_old.add(key)
                target = f"{resource_type}/{new_id}"
                for alias in _alias_keys(resource_type, old_id):
                    if alias in alias_to_new and alias_to_new[alias] != target:
                        # Gleiche ID in zwei verschiedenen Ressourcentypen:
                        # der kurze Alias ist mehrdeutig, der qualifizierte
                        # Alias "Typ/ID" bleibt eindeutig.
                        ambiguous_aliases.add(alias)
                    else:
                        alias_to_new[alias] = target
                alias_to_new[f"{resource_type}/{old_id}"] = target
                # Nur die erste Vergabe wandert in die Abbildungstabelle;
                # bei Dubletten bleibt sie damit nachvollziehbar.
                result.id_map[f"{resource_type}/{old_id}"] = target

        resource["id"] = new_id

    # --- Schritt 2: alle Verweise im gesamten Baum umschreiben -------------
    def rewrite(node: Any) -> None:
        if isinstance(node, dict):
            reference = node.get("reference")
            if isinstance(reference, str) and reference:
                resolved = _resolve(reference, alias_to_new, ambiguous_aliases, result)
                if resolved is not None and resolved != reference:
                    node["reference"] = resolved
                    result.rewritten_references += 1
            for value in node.values():
                rewrite(value)
        elif isinstance(node, list):
            for item in node:
                rewrite(item)

    for resource in working:
        rewrite(resource)

    return result


def _resolve(
    reference: str,
    alias_to_new: dict[str, str],
    ambiguous_aliases: set[str],
    result: NormalisationResult,
) -> str | None:
    """Bildet eine Referenz auf die neue ID ab. None = unverändert lassen."""
    # Interne Verweise auf "contained"-Ressourcen betreffen den ID-Raum des
    # Codes nicht und bleiben unangetastet.
    if reference.startswith("#"):
        return None

    if reference in ambiguous_aliases:
        result.ambiguous_references.append(reference)
        return None

    if reference in alias_to_new:
        return alias_to_new[reference]

    # Absolute URL wie "http://server/fhir/Patient/abc"
    match = _URL_TAIL_RE.search(reference)
    if match:
        candidate = f"{match.group(1)}/{match.group(2)}"
        if candidate in ambiguous_aliases:
            result.ambiguous_references.append(reference)
            return None
        if candidate in alias_to_new:
            return alias_to_new[candidate]

    # Nicht auflösbar: Der Verweis zeigt ins Leere. Bewusst NICHT reparieren –
    # die Referenz-Integritätsprüfung soll ihn finden und zählen.
    result.unresolved_references.append(reference)
    return None


def repin_identity(resource: dict, expected_id: str, expected_type: str) -> list[str]:
    """Setzt ID und Typ einer Ressource zwangsweise auf den Code-Stand.

    Im Produkt (Variante B) baut der Code die Ressourcen selbst, sodass die
    Funktion selten gebraucht wird. Sie bleibt als Absicherung erhalten,
    falls je eine Ressource aus fremder Quelle einfließt.
    """
    notes: list[str] = []
    if resource.get("resourceType") != expected_type:
        notes.append(
            f"resourceType wurde von {resource.get('resourceType')!r} "
            f"auf {expected_type!r} zurückgesetzt"
        )
        resource["resourceType"] = expected_type
    if resource.get("id") != expected_id:
        notes.append(f"id wurde von {resource.get('id')!r} auf {expected_id!r} zurückgesetzt")
        resource["id"] = expected_id
    return notes
