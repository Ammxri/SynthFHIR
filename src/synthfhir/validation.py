"""Strukturvalidierung zur Laufzeit (ADR-002, Stufe 1).

Prüft Pflichtfelder, Kardinalitäten und Datentypen über die Pydantic-Modelle
von `fhir.resources`. Kein Netzwerk, kein Server, Laufzeit im
Millisekundenbereich.

===========================================================================
WAS DIESE PRÜFUNG LEISTET — UND WAS AUSDRÜCKLICH NICHT
===========================================================================

Gemessen an 339 Ressourcen aus der Phase 0, für die HAPIs Urteil vorlag
(ADR-002, Abschnitt 3):

    Pflichtfeld / Kardinalität     5 von 5 erkannt
    Terminologie und Einheiten     0 von 7 erkannt
    Falsche Alarme                 0 von 339

Sie erkennt also zuverlässig, was variabel ist — die Struktur der aus
Modellparametern gebauten Ressourcen. Sie erkennt **nicht**:

  * ob eine UCUM-Einheit existiert (`IU/mL` geht durch)
  * ob ein Code gültig ist (`99999-9` geht durch)
  * ob ein `code`-Feld seine **required binding** einhält — `gender:
    "weiblich"` und `status: "fertig"` gehen durch, obwohl HAPI beide
    zurückweist. Nachgeprüft am 2026-08-28; siehe die Tests in
    `tests/test_validierung.py`, Abschnitt „Was die Prüfung bewusst nicht
    sieht".

Das ist kein Versehen, sondern die bewusste Arbeitsteilung der Architektur:
Einheiten, Codes und gebundene Statuswerte kommen aus Katalog und Vorlage,
nicht aus dem Modell. Was diese
Prüfung nicht sieht, kann die Architektur nicht erzeugen — solange der
Katalog stimmt. Genau dafür gibt es die CI-Prüfung gegen HAPI
(`tests/test_katalog_gegen_hapi.py`).

===========================================================================
VERSIONSHINWEIS
===========================================================================

`fhir.resources` 8.x liefert R4B (4.3.0) und R5, aber kein R4 (4.0.1) — die
Zielversion des Projekts. Für die drei Ressourcentypen des MVP hat die
Messung an echten R4-Daten keine Abweichung gezeigt (0 falsche Alarme über
339 Ressourcen). Die verbleibende Differenz deckt die HAPI-Prüfung in der
CI ab, die gegen echtes R4 4.0.1 läuft.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fhir.resources.R4B.condition import Condition
from fhir.resources.R4B.observation import Observation
from fhir.resources.R4B.patient import Patient

MODELLE: dict[str, Any] = {
    "Patient": Patient,
    "Condition": Condition,
    "Observation": Observation,
}

# Ressourcentypen, die der MVP erzeugt. Alles andere ist ein Fehler und kein
# stillschweigend durchgereichter Sonderfall (PRD Block 9: keine weiteren
# Ressourcentypen im MVP).
UNTERSTUETZTE_TYPEN = tuple(MODELLE)


@dataclass(frozen=True)
class Befund:
    """Eine einzelne Beanstandung an einer Ressource."""

    pfad: str
    meldung: str

    def to_dict(self) -> dict:
        return {"pfad": self.pfad, "meldung": self.meldung}

    def __str__(self) -> str:
        return f"{self.pfad}: {self.meldung}"


@dataclass
class Pruefergebnis:
    """Urteil über genau eine Ressource."""

    ressourcentyp: str
    ressourcen_id: str
    befunde: list[Befund] = field(default_factory=list)

    @property
    def valide(self) -> bool:
        return not self.befunde

    def to_dict(self) -> dict:
        return {
            "ressourcentyp": self.ressourcentyp,
            "ressourcen_id": self.ressourcen_id,
            "valide": self.valide,
            "befunde": [b.to_dict() for b in self.befunde],
        }


def pruefe_ressource(ressource: dict) -> Pruefergebnis:
    """Validiert eine einzelne Ressource strukturell."""
    typ = ressource.get("resourceType")
    ressourcen_id = str(ressource.get("id") or "(ohne id)")

    if not isinstance(typ, str) or not typ:
        return Pruefergebnis(
            "(fehlt)",
            ressourcen_id,
            [Befund("resourceType", "Die Ressource hat kein Feld 'resourceType'.")],
        )

    modell = MODELLE.get(typ)
    if modell is None:
        return Pruefergebnis(
            typ,
            ressourcen_id,
            [
                Befund(
                    "resourceType",
                    f"Ressourcentyp {typ!r} wird nicht unterstützt. Erlaubt: "
                    + ", ".join(UNTERSTUETZTE_TYPEN),
                )
            ],
        )

    try:
        modell.model_validate(ressource)
    except Exception as exc:  # pydantic.ValidationError und Randfälle
        return Pruefergebnis(typ, ressourcen_id, _befunde_aus_fehler(exc))

    return Pruefergebnis(typ, ressourcen_id)


def pruefe_alle(ressourcen: list[dict]) -> list[Pruefergebnis]:
    """Validiert einen ganzen Ressourcensatz."""
    return [pruefe_ressource(r) for r in ressourcen]


def alle_valide(ergebnisse: list[Pruefergebnis]) -> bool:
    """True, wenn kein einziger Befund vorliegt.

    US-2 AC2 des PRD: Ressourcen mit Fehlern werden nie als fertig
    ausgegeben. Diese Funktion ist die Bedingung dafür.
    """
    return all(e.valide for e in ergebnisse)


def _befunde_aus_fehler(exc: Exception) -> list[Befund]:
    """Übersetzt einen Pydantic-Validierungsfehler in lesbare Befunde.

    Pydantic liefert `loc` als Tupel; daraus wird ein FHIRPath-ähnlicher
    Pfad. Der Fehlerort ist genau der Teil, der eine Meldung brauchbar
    macht — dieselbe Erkenntnis wie beim `expression`-Feld des
    OperationOutcome (siehe docs/konzepte.md, Abschnitt 1).
    """
    fehlerliste = getattr(exc, "errors", None)
    if not callable(fehlerliste):
        return [Befund("(unbekannt)", str(exc)[:200])]

    befunde: list[Befund] = []
    for fehler in fehlerliste():
        pfad = ".".join(str(teil) for teil in fehler.get("loc", ()) if teil != "__root__")
        befunde.append(Befund(pfad or "(Wurzel)", str(fehler.get("msg", "unbekannter Fehler"))))
    return befunde or [Befund("(unbekannt)", str(exc)[:200])]
