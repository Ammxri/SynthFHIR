"""Referenz-Integritätsprüfung — eigenständig, nicht vom Validator abgedeckt.

===========================================================================
KONZEPT: Warum findet die Strukturvalidierung eine Referenz ins Leere nicht?
===========================================================================

Eine FHIR-Referenz ist im Datenmodell nur ein String:

    "subject": { "reference": "Patient/pat-042" }

`Reference.reference` hat den Datentyp `string`. Die StructureDefinition
sagt: Dieses Feld ist eine Zeichenkette, es soll die Form "Typ/ID" haben,
und der Zieltyp muss zu den erlaubten Zieltypen des Feldes gehören. Mehr
weiß sie nicht. Ob unter dieser Adresse etwas liegt, ist keine Frage der
STRUKTUR, sondern eine Frage des DATENBESTANDS.

Daraus folgt: Ein Strukturvalidator, der eine Ressource einzeln prüft, KANN
das gar nicht wissen. Er hat nur diese eine Ressource vor sich. "Patient/
pat-042" ist für ihn syntaktisch einwandfrei – auch wenn es pat-042 nirgends
gibt. Und genau so wird validiert: Ressource für Ressource, im Produkt sogar
ganz ohne Server (ADR-002).

Drei weitere Gründe, warum man sich hier nicht auf den Server verlassen darf:

1. Ein `$validate`-Aufruf legt nichts an. Selbst wenn der Server referen-
   zielle Integrität erzwingen könnte, hätte er beim Prüfen einer einzelnen
   Ressource keinen Bezug zu den anderen Ressourcen desselben Durchlaufs –
   die liegen ja nicht auf dem Server.
2. Bundle-Typ `collection` hat bewusst keine Transaktionssemantik. Anders
   als bei `transaction` löst der Server hier keine Verweise auf.
3. Referentielle Integrität ist in HAPI ohnehin eine abschaltbare Server-
   einstellung, keine Eigenschaft von FHIR.

Deshalb ist diese Prüfung eine eigenständige, zwingende Komponente. Sie
erfüllt US-3 AC3 des PRD: "Die Prüfung erfolgt unabhängig von der
Strukturvalidierung."

Geprüft wird:
  (a) Zeigt jede Condition und jede Observation auf einen Patienten, der im
      selben Bundle existiert?
  (b) Sind alle IDs innerhalb des Bundles eindeutig?
  (c) Gibt es irgendwo im Baum Verweise auf nicht existierende Ressourcen?

Punkt (c) ist bewusst weiter gefasst als (a): Verweise stecken nicht nur in
`subject`, sondern können überall auftauchen (encounter, performer,
hasMember, derivedFrom …). Deshalb wird der komplette Baum durchlaufen und
nicht nur ein bekanntes Feld abgefragt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Ressourcen, die laut Scope zwingend auf einen Patienten verweisen müssen.
PATIENT_LINKED_TYPES = ("Condition", "Observation")

_TYPE_ID_RE = re.compile(r"^([A-Z][A-Za-z]+)/([A-Za-z0-9\-.]{1,64})$")
_URL_TAIL_RE = re.compile(r"(?:^|/)([A-Z][A-Za-z]+)/([A-Za-z0-9\-.]{1,64})$")


@dataclass(frozen=True)
class ReferenceFinding:
    """Eine beanstandete Referenz."""

    source: str      # z. B. "Observation/obs-003"
    path: str        # z. B. "subject.reference"
    reference: str   # der beanstandete Wert
    reason: str

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "path": self.path,
            "reference": self.reference,
            "reason": self.reason,
        }


@dataclass
class IntegrityReport:
    """Ergebnis der Referenz-Integritätsprüfung über ein ganzes Bundle."""

    total_references: int = 0
    broken_references: list[ReferenceFinding] = field(default_factory=list)
    duplicate_ids: list[str] = field(default_factory=list)
    missing_patient_link: list[str] = field(default_factory=list)
    resources_checked: int = 0

    @property
    def ok(self) -> bool:
        return not (self.broken_references or self.duplicate_ids or self.missing_patient_link)

    @property
    def broken_reference_count(self) -> int:
        return len(self.broken_references)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "resources_checked": self.resources_checked,
            "total_references": self.total_references,
            "broken_reference_count": self.broken_reference_count,
            "broken_references": [f.to_dict() for f in self.broken_references],
            "duplicate_ids": self.duplicate_ids,
            "missing_patient_link": self.missing_patient_link,
        }


def check_resources(resources: list[dict]) -> IntegrityReport:
    """Prüft einen kompletten Ressourcensatz auf Referenzintegrität."""
    report = IntegrityReport(resources_checked=len(resources))

    # --- (b) IDs eindeutig? ------------------------------------------------
    known: set[str] = set()
    seen_counts: dict[str, int] = {}
    for resource in resources:
        resource_type = str(resource.get("resourceType") or "?")
        resource_id = resource.get("id")
        if not resource_id:
            continue
        key = f"{resource_type}/{resource_id}"
        seen_counts[key] = seen_counts.get(key, 0) + 1
        known.add(key)
    report.duplicate_ids = sorted(key for key, count in seen_counts.items() if count > 1)

    # --- (a) + (c) Verweise prüfen ----------------------------------------
    for resource in resources:
        resource_type = str(resource.get("resourceType") or "?")
        source = f"{resource_type}/{resource.get('id') or '(ohne id)'}"

        found: list[tuple[str, str]] = []
        _collect_references(resource, "", found)
        report.total_references += len(found)

        for path, reference in found:
            reason = _classify_reference(reference, known)
            if reason is not None:
                report.broken_references.append(
                    ReferenceFinding(
                        source=source, path=path, reference=reference, reason=reason
                    )
                )

        # (a) Pflichtverknüpfung zum Patienten
        if resource_type in PATIENT_LINKED_TYPES:
            subject = resource.get("subject")
            reference = subject.get("reference") if isinstance(subject, dict) else None
            if not isinstance(reference, str) or not reference.strip():
                report.missing_patient_link.append(f"{source}: kein subject.reference")
            else:
                target = _normalise(reference)
                if target is None:
                    report.missing_patient_link.append(
                        f"{source}: subject.reference {reference!r} ist keine Typ/ID-Referenz"
                    )
                elif not target.startswith("Patient/"):
                    report.missing_patient_link.append(
                        f"{source}: subject verweist auf {target}, nicht auf einen Patient"
                    )
                elif target not in known:
                    report.missing_patient_link.append(
                        f"{source}: subject verweist auf {target}, das es im Bundle nicht gibt"
                    )

    return report


def check_bundle(bundle: dict) -> IntegrityReport:
    """Bequemlichkeitsfunktion: prüft die Ressourcen eines Bundles."""
    resources = [
        entry.get("resource")
        for entry in bundle.get("entry", []) or []
        if isinstance(entry, dict) and isinstance(entry.get("resource"), dict)
    ]
    return check_resources([r for r in resources if r])


# --- Hilfsfunktionen -------------------------------------------------------


def _collect_references(node: Any, path: str, out: list[tuple[str, str]]) -> None:
    """Sammelt jeden `reference`-String im Baum samt seinem Pfad."""
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else key
            if key == "reference" and isinstance(value, str) and value.strip():
                out.append((child_path, value.strip()))
            else:
                _collect_references(value, child_path, out)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _collect_references(item, f"{path}[{index}]", out)


def _normalise(reference: str) -> str | None:
    """Bringt eine Referenz auf die Form "Typ/ID" – oder None, wenn unmöglich."""
    match = _TYPE_ID_RE.match(reference)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    match = _URL_TAIL_RE.search(reference)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    return None


def _classify_reference(reference: str, known: set[str]) -> str | None:
    """Gibt den Beanstandungsgrund zurück – oder None, wenn alles in Ordnung."""
    # Interne Verweise auf contained-Ressourcen prüft diese Komponente nicht;
    # sie verlassen die Ressource nicht und liegen außerhalb des Scopes.
    if reference.startswith("#"):
        return None
    target = _normalise(reference)
    if target is None:
        return "Referenz hat nicht die Form 'Typ/ID'"
    if target not in known:
        return f"Ziel {target} existiert nicht im selben Bundle"
    return None
