"""Korrekturschleife der Variante A (Abschnitt 6.6) – Lernmodus-Komponente.

===========================================================================
KONZEPT: Warum funktioniert das Zurückgeben der Fehlermeldung überhaupt?
===========================================================================

Die Schleife verwandelt eine schwere Aufgabe in eine leichte.

Beim ersten Aufruf muss das Modell aus einer Prosabeschreibung eine
komplette, spezifikationskonforme Ressource erzeugen. Es muss dabei alles
gleichzeitig richtig machen: Pflichtfelder, Datentypen, Bindings,
Invarianten, Referenzen, klinischen Inhalt.

In der Korrekturrunde bekommt es etwas völlig anderes: einen konkreten
Gegenstand, einen benannten Ort und eine benannte Abweichung.

    [error] at Observation.valueQuantity.code
    Unable to validate code "mg/dl" - code is case-sensitive

Das ist eine lokale Bearbeitungsaufgabe, keine Erzeugungsaufgabe. Der
`expression`-Pfad aus dem OperationOutcome ist dabei der wertvollste Teil:
Er sagt, WO. Ohne ihn müsste das Modell die Fundstelle erst suchen.

===========================================================================
KONZEPT: Wo stößt das Verfahren an seine Grenzen?
===========================================================================

1. FEHLERMELDUNGEN BESCHREIBEN DAS SYMPTOM, NICHT DIE LÖSUNG.
   "minimum required = 1, but only found 0" sagt, dass `status` fehlt –
   nicht, welcher der acht erlaubten Statuswerte hier richtig ist. Bei
   required bindings muss das Modell die zulässige Werteliste kennen oder
   raten. Weiß es sie nicht, hilft auch die zehnte Runde nicht.

2. FLICKEN ERZEUGT NEUE LÖCHER.
   Ein Modell, das ein fehlendes `valueQuantity` ergänzt, ohne das
   vorhandene `valueString` zu entfernen, verletzt danach die Regel, dass
   von einer Auswahl `value[x]` nur EINE Ausprägung gesetzt sein darf. Die
   Fehlerzahl kann von Runde zu Runde steigen.

3. FEHLER VERDECKEN EINANDER.
   Manche Validierungsschritte laufen erst, wenn der vorherige durchkommt.
   Nach dem Beheben eines Strukturfehlers taucht plötzlich ein bis dahin
   unsichtbarer Terminologiefehler auf. Die Fehlerzahl fällt deshalb nicht
   monoton – und "0 Fehler nach 3 Runden" ist nicht dasselbe wie
   "3-mal je ein Drittel der Fehler behoben".

4. STAGNATION IST DAS EIGENTLICHE RISIKO.
   Wenn eine Runde die Fehlerzahl nicht senkt, formuliert das Modell in der
   Regel nur um. Das kostet Geld und Zeit, ohne dem Ziel näher zu kommen.
   Deshalb zählt diese Komponente `non_improving_rounds` gesondert – das
   ist der direkte Hinweis auf Endlosschleifenverhalten aus Abschnitt 6.6
   und einer der wichtigsten Werte des ganzen Spikes.

5. DIE KORREKTUR KANN INHALT ZERSTÖREN.
   Beim Reparieren der Struktur ändert ein Modell gern nebenbei Werte,
   Datumsangaben oder Referenzen. Deshalb wird nach jeder Runde die
   Identität wieder festgenagelt (`repin_identity`) und jeder Zwischenstand
   als Artefakt gespeichert (Abschnitt 9) – nur so ist nachvollziehbar,
   was das Modell tatsächlich verändert hat.

6. KOSTEN WACHSEN LINEAR MIT DEN RUNDEN.
   Jede Runde schickt die vollständige Ressource erneut hin und zurück.
   Drei Runden auf einer schlechten Ressource können teurer sein als die
   ursprüngliche Erzeugung des ganzen Szenarios.

Bewusste Festlegung: Dem Modell werden nur BLOCKIERENDE Befunde
(fatal/error) zurückgegeben. Warnungen mitzuschicken würde es zu Änderungen
verleiten, die nichts verbessern, aber neue Fehler einbauen können.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .identity import repin_identity
from .jsonx import JsonExtractionError, extract_json
from .llm import LLMClient, LLMError
from .prompts import build_repair_prompt
from .validator import HapiValidator, ValidationResult


@dataclass
class RepairRound:
    """Protokoll einer einzelnen Korrekturrunde."""

    round_no: int
    errors_before: int
    errors_after: int | None
    improved: bool
    note: str | None = None

    def to_dict(self) -> dict:
        return {
            "round_no": self.round_no,
            "errors_before": self.errors_before,
            "errors_after": self.errors_after,
            "improved": self.improved,
            "note": self.note,
        }


@dataclass
class RepairOutcome:
    """Ergebnis der Korrekturschleife für genau eine Ressource."""

    resource: dict
    resource_type: str
    resource_id: str
    initial_valid: bool
    final_valid: bool
    final_result: ValidationResult
    rounds: list[RepairRound] = field(default_factory=list)
    snapshots: list[dict] = field(default_factory=list)
    identity_corrections: list[str] = field(default_factory=list)
    llm_calls: int = 0
    json_failures: int = 0

    @property
    def rounds_used(self) -> int:
        return len(self.rounds)

    @property
    def non_improving_rounds(self) -> int:
        return sum(1 for r in self.rounds if not r.improved)

    def to_dict(self) -> dict:
        return {
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "initial_valid": self.initial_valid,
            "final_valid": self.final_valid,
            "rounds_used": self.rounds_used,
            "non_improving_rounds": self.non_improving_rounds,
            "llm_calls": self.llm_calls,
            "json_failures": self.json_failures,
            "identity_corrections": self.identity_corrections,
            "rounds": [r.to_dict() for r in self.rounds],
        }


class RepairLoop:
    """Führt bis zu `max_rounds` Korrekturrunden je Ressource aus."""

    def __init__(self, llm: LLMClient, validator: HapiValidator, max_rounds: int = 3) -> None:
        self.llm = llm
        self.validator = validator
        self.max_rounds = max_rounds

    def repair(self, resource: dict, initial_result: ValidationResult) -> RepairOutcome:
        """Korrigiert eine Ressource, bis sie valide ist oder die Runden aus sind."""
        expected_id = str(resource.get("id"))
        expected_type = str(resource.get("resourceType"))

        outcome = RepairOutcome(
            resource=resource,
            resource_type=expected_type,
            resource_id=expected_id,
            initial_valid=initial_result.is_valid,
            final_valid=initial_result.is_valid,
            final_result=initial_result,
        )
        if initial_result.is_valid:
            return outcome

        current = resource
        current_result = initial_result

        for round_no in range(1, self.max_rounds + 1):
            errors_before = current_result.error_count
            system, user = build_repair_prompt(
                resource_json=json.dumps(current, indent=2, ensure_ascii=False),
                errors=current_result.format_for_llm(),
            )

            try:
                response = self.llm.complete(system=system, user=user, purpose="repair")
                outcome.llm_calls += 1
            except LLMError as exc:
                outcome.rounds.append(
                    RepairRound(
                        round_no=round_no,
                        errors_before=errors_before,
                        errors_after=None,
                        improved=False,
                        note=f"LLM-Aufruf fehlgeschlagen: {exc}",
                    )
                )
                break

            try:
                payload = extract_json(response.text)
            except JsonExtractionError as exc:
                outcome.json_failures += 1
                outcome.rounds.append(
                    RepairRound(
                        round_no=round_no,
                        errors_before=errors_before,
                        errors_after=errors_before,
                        improved=False,
                        note=f"Antwort war kein gültiges JSON: {exc}",
                    )
                )
                # Mit unverändertem Stand in die nächste Runde – die Zahl der
                # Runden bleibt gedeckelt, also droht keine Endlosschleife.
                continue

            if not isinstance(payload, dict):
                outcome.json_failures += 1
                outcome.rounds.append(
                    RepairRound(
                        round_no=round_no,
                        errors_before=errors_before,
                        errors_after=errors_before,
                        improved=False,
                        note=(
                            "Erwartet wurde ein einzelnes Objekt, geliefert wurde "
                            f"{type(payload).__name__}."
                        ),
                    )
                )
                continue

            # Der Code besitzt den ID-Raum – auch nach einer Korrekturrunde.
            outcome.identity_corrections.extend(
                repin_identity(payload, expected_id, expected_type)
            )
            outcome.snapshots.append(payload)

            current = payload
            current_result = self.validator.validate(current)
            errors_after = current_result.error_count
            improved = errors_after < errors_before

            note = None
            if not improved:
                note = (
                    "Runde hat die Fehlerzahl nicht verringert "
                    f"({errors_before} -> {errors_after}) – Hinweis auf Stagnation."
                )
            outcome.rounds.append(
                RepairRound(
                    round_no=round_no,
                    errors_before=errors_before,
                    errors_after=errors_after,
                    improved=improved,
                    note=note,
                )
            )

            outcome.resource = current
            outcome.final_result = current_result
            outcome.final_valid = current_result.is_valid
            if outcome.final_valid:
                break

        return outcome
