"""Laden und Prüfen der Szenario-Konfiguration (Abschnitt 6.1).

Die Szenarien liegen bewusst in einer Datei und nicht im Code, damit sie
zwischen Messläufen nachweislich unverändert bleiben. Zur Absicherung wird
je Szenario ein Hash gebildet; er landet in der Metrikdatei. Weichen zwei
Läufe im Hash ab, sind ihre Ergebnisse nicht vergleichbar.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml


class ScenarioError(RuntimeError):
    """Fehlerhafte Szenario-Konfiguration."""


@dataclass(frozen=True)
class Scenario:
    """Ein Testszenario, identisch für Variante A und Variante B."""

    key: str
    name: str
    description: str
    patients: int
    conditions_per_patient: int
    observations_per_patient: int

    @property
    def expected_conditions(self) -> int:
        return self.patients * self.conditions_per_patient

    @property
    def expected_observations(self) -> int:
        return self.patients * self.observations_per_patient

    @property
    def expected_total(self) -> int:
        return self.patients + self.expected_conditions + self.expected_observations

    def fingerprint(self) -> str:
        """Stabiler Hash über alle messrelevanten Felder."""
        payload = json.dumps(
            {
                "key": self.key,
                "description": " ".join(self.description.split()),
                "patients": self.patients,
                "conditions_per_patient": self.conditions_per_patient,
                "observations_per_patient": self.observations_per_patient,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _require_int(raw: dict, field: str, key: str) -> int:
    value = raw.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ScenarioError(
            f"Szenario {key!r}: Feld {field!r} muss eine ganze Zahl >= 1 sein (ist: {value!r})"
        )
    return value


def load_scenarios(path: Path) -> dict[str, Scenario]:
    """Liest die Szenariodatei und gibt die Szenarien nach Schlüssel zurück."""
    if not path.exists():
        raise ScenarioError(f"Szenariodatei nicht gefunden: {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("scenarios")
    if not isinstance(entries, list) or not entries:
        raise ScenarioError(f"{path}: Schlüssel 'scenarios' fehlt oder ist leer.")

    scenarios: dict[str, Scenario] = {}
    for raw in entries:
        if not isinstance(raw, dict):
            raise ScenarioError(f"{path}: Szenario-Eintrag ist kein Objekt: {raw!r}")
        key = str(raw.get("key", "")).strip()
        if not key:
            raise ScenarioError(f"{path}: Szenario ohne 'key'.")
        if key in scenarios:
            raise ScenarioError(f"{path}: Szenario-Schlüssel {key!r} kommt doppelt vor.")
        description = str(raw.get("description", "")).strip()
        if not description:
            raise ScenarioError(f"Szenario {key!r}: 'description' fehlt.")
        scenarios[key] = Scenario(
            key=key,
            name=str(raw.get("name") or key),
            description=" ".join(description.split()),
            patients=_require_int(raw, "patients", key),
            conditions_per_patient=_require_int(raw, "conditions_per_patient", key),
            observations_per_patient=_require_int(raw, "observations_per_patient", key),
        )

    if len(scenarios) < 3:
        raise ScenarioError(
            f"{path}: Die Spezifikation verlangt mindestens drei Szenarien "
            f"(gefunden: {len(scenarios)})."
        )
    return scenarios
