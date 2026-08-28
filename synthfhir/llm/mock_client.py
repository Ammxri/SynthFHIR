"""Nachgebauter LLM-Anbieter – ausschließlich für den Selbsttest.

Zweck: Die komplette Kette (Erzeugung, JSON-Extraktion, ID-Vergabe,
Validierung, Korrekturschleife, Integritätsprüfung, Metriken, Artefakte)
ohne API-Schlüssel und ohne Kosten durchlaufen zu können.

WICHTIG: Dieser Anbieter erzeugt absichtlich typische Modellfehler
(fehlendes Pflichtfeld, Referenz ins Leere, erfundener Code, Markdown-
Rahmen). Er ist ein Prüfstand für den Code, KEINE Messgrundlage. Ergebnisse
aus einem Mock-Lauf dürfen niemals in den Vergleichsbericht der Architektur-
entscheidung eingehen – die Metrikdateien halten deshalb den Anbieter fest.
"""

from __future__ import annotations

import json
import re
import time

from ..config import LLMSettings
from .base import LLMClient, LLMResponse

_COUNTS_RE = re.compile(
    r"COUNTS: patients=(\d+), conditions_per_patient=(\d+), observations_per_patient=(\d+)"
)

_GIVEN = ["Anna", "Bernd", "Clara", "David", "Elif", "Farid"]
_FAMILY = ["Meier", "Schulz", "Kowalski", "Yilmaz", "Bauer", "Hofmann"]
_BIRTH = ["1992-03-14", "1968-07-02", "1941-11-25", "1985-01-09", "1977-05-30", "1954-09-18"]
_GENDER = ["female", "male", "female", "male", "female", "male"]


class MockClient(LLMClient):
    """Liefert deterministische Antworten anhand von Markern im Prompt."""

    def __init__(self, settings: LLMSettings, budget_limit_eur: float | None = None) -> None:
        super().__init__(settings, budget_limit_eur)
        self._invocation = 0

    def _complete_once(self, system: str, user: str) -> LLMResponse:
        started = time.perf_counter()
        self._invocation += 1

        if "You fix invalid FHIR R4 resources" in system:
            text = self._repair(user)
        elif "OUTPUT FORMAT: PARAMETERS" in user:
            text = self._parameters(user)
        else:
            text = self._fhir(user)

        return LLMResponse(
            text=text,
            model="mock",
            input_tokens=len(system + user) // 4,
            output_tokens=len(text) // 4,
            latency_s=time.perf_counter() - started,
            stop_reason="end_turn",
        )

    # -- Hilfen -------------------------------------------------------------
    @staticmethod
    def _counts(user: str) -> tuple[int, int, int]:
        match = _COUNTS_RE.search(user)
        if not match:
            return (1, 1, 1)
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))

    # -- Variante A ---------------------------------------------------------
    def _fhir(self, user: str) -> str:
        """Baut FHIR mit absichtlich eingebauten, typischen Modellfehlern."""
        patients, per_condition, per_observation = self._counts(user)
        resources: list[dict] = []

        for p in range(patients):
            resources.append(
                {
                    "resourceType": "Patient",
                    "id": f"patient-{p + 1}",
                    "name": [{"family": _FAMILY[p % 6], "given": [_GIVEN[p % 6]]}],
                    "gender": _GENDER[p % 6],
                    "birthDate": _BIRTH[p % 6],
                }
            )

        for p in range(patients):
            for c in range(per_condition):
                # Fehler 1: die letzte Diagnose zeigt auf einen Patienten,
                # den es nicht gibt.
                broken = p == patients - 1 and c == per_condition - 1
                target = "patient-999" if broken else f"patient-{p + 1}"
                resources.append(
                    {
                        "resourceType": "Condition",
                        "id": f"condition-{p + 1}-{c + 1}",
                        "clinicalStatus": {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                                    "code": "active",
                                }
                            ]
                        },
                        "verificationStatus": {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                                    "code": "confirmed",
                                }
                            ]
                        },
                        "code": {
                            "coding": [
                                {
                                    "system": "http://snomed.info/sct",
                                    "code": "44054006",
                                    "display": "Diabetes mellitus type 2",
                                }
                            ]
                        },
                        "subject": {"reference": f"Patient/{target}"},
                        "onsetDateTime": "2019-04-01",
                    }
                )

        for p in range(patients):
            for o in range(per_observation):
                observation = {
                    "resourceType": "Observation",
                    "id": f"observation-{p + 1}-{o + 1}",
                    "status": "final",
                    "code": {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": "4548-4",
                                "display": "Hemoglobin A1c",
                            }
                        ]
                    },
                    "subject": {"reference": f"Patient/patient-{p + 1}"},
                    "effectiveDateTime": f"2024-0{(o % 9) + 1}-15",
                    "valueQuantity": {
                        "value": 7.1 + o * 0.3,
                        "unit": "%",
                        "system": "http://unitsofmeasure.org",
                        "code": "%",
                    },
                }
                # Fehler 2: beim ersten Messwert fehlt das Pflichtfeld status.
                if p == 0 and o == 0:
                    observation.pop("status")
                # Fehler 3: erfundener LOINC-Code beim zweiten Messwert.
                if p == 0 and o == 1:
                    observation["code"]["coding"][0]["code"] = "99999-9"
                resources.append(observation)

        body = json.dumps(resources, indent=2, ensure_ascii=False)
        # Fehler 4: jeder dritte Aufruf kommt in Markdown-Rahmen mit Fließtext.
        if self._invocation % 3 == 0:
            return f"Gerne! Hier sind die Ressourcen:\n\n```json\n{body}\n```\n"
        return body

    # -- Variante B ---------------------------------------------------------
    def _parameters(self, user: str) -> str:
        patients, per_condition, per_observation = self._counts(user)
        condition_codes = ["44054006", "38341003", "13644009", "709044004"]
        observation_codes = ["4548-4", "2345-7", "2160-0", "8480-6", "718-7"]

        payload = {"patients": []}
        for p in range(patients):
            entry = {
                "given_name": _GIVEN[p % 6],
                "family_name": _FAMILY[p % 6],
                "gender": _GENDER[p % 6],
                "birth_date": _BIRTH[p % 6],
                "conditions": [
                    {
                        "code": condition_codes[(p + c) % len(condition_codes)],
                        "onset_date": f"201{(p + c) % 9}-06-01",
                    }
                    for c in range(per_condition)
                ],
                "observations": [
                    {
                        "code": observation_codes[(p + o) % len(observation_codes)],
                        "value": 7.2 + o * 0.4,
                        "effective_date": f"2024-0{(o % 9) + 1}-12",
                    }
                    for o in range(per_observation)
                ],
            }
            # Fehler: beim letzten Patienten ein Code außerhalb des Katalogs.
            if p == patients - 1 and entry["observations"]:
                entry["observations"][-1]["code"] = "00000-0"
            payload["patients"].append(entry)

        return json.dumps(payload, indent=2, ensure_ascii=False)

    # -- Korrekturschleife --------------------------------------------------
    def _repair(self, user: str) -> str:
        """Behebt genau die Fehler, die der Mock selbst eingebaut hat."""
        marker = "CURRENT RESOURCE:\n"
        start = user.find(marker)
        if start < 0:
            return "Ich kann die Ressource nicht finden."
        chunk = user[start + len(marker) :]
        end = chunk.rfind("}")
        try:
            resource = json.loads(chunk[: end + 1])
        except (json.JSONDecodeError, ValueError):
            return "Die Ressource ließ sich nicht lesen."

        errors = user[: start].lower()
        if "status" in errors and resource.get("resourceType") == "Observation":
            resource["status"] = "final"
        if "code" in errors:
            coding = resource.get("code", {}).get("coding")
            if isinstance(coding, list) and coding and coding[0].get("code") == "99999-9":
                coding[0]["code"] = "4548-4"

        return json.dumps(resource, indent=2, ensure_ascii=False)
