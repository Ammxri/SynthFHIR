"""Die Auflage aus ADR-002: der vollständige Katalog gegen echtes HAPI.

Hier wird die Produktzusage „garantiert valide" tatsächlich eingelöst.

Die Laufzeitvalidierung prüft Struktur, aber weder Einheiten noch Codes
(gemessen: 0 von 7 Terminologie- und Einheitenfehlern erkannt). Ein falscher
UCUM-Code im Katalog erzeugt darum ab sofort invalide Ausgaben, ohne dass im
Betrieb irgendetwas anschlägt. Dieser Test ist die einzige Stelle, an der so
etwas auffällt.

Er läuft deshalb über den **vollständigen** Katalog, nicht über eine
Stichprobe: Jeder Beobachtungscode und jeder Diagnosecode wird zu einer
echten Ressource gebaut und einzeln validiert.

Grenze, die man kennen muss: HAPI hat keine LOINC-, SNOMED- oder
ICD-10-GM-Pakete geladen. Der Test sichert damit **Einheiten, Struktur und
Invarianten** ab — nicht die inhaltliche Richtigkeit der Codes. Die braucht
einen menschlichen Abgleich gegen die Primärquellen; siehe den Kopf von
`synthfhir/domain/codes.py`.
"""

from __future__ import annotations

import pytest

from synthfhir.domain.codes import CONDITION_CODES, OBSERVATION_CODES
from synthfhir.domain.identity import assign_ids
from synthfhir.domain.templates import (
    Beanstandung,
    baue_bundle,
    baue_condition,
    baue_observation,
    baue_patient,
)


def _satz_fuer_diagnose(code: str) -> list[dict]:
    """Ein minimaler, vollständiger Satz für genau einen Diagnosecode."""
    b: list[Beanstandung] = []
    ressourcen = [
        baue_patient(
            {
                "vorname": "Anna",
                "nachname": "Meier",
                "geschlecht": "female",
                "geburtsdatum": "1968-04-12",
            },
            0,
            b,
        ),
        baue_condition({"code": code, "beginn": "2015-06-01"}, 0, 0, b),
    ]
    assert not b, f"Vorlage hat den Katalogeintrag {code} beanstandet: {b}"
    return assign_ids(ressourcen).resources


def _satz_fuer_messwert(code: str) -> list[dict]:
    """Ein minimaler, vollständiger Satz für genau einen Messwertcode."""
    spec = OBSERVATION_CODES[code]
    b: list[Beanstandung] = []
    ressourcen = [
        baue_patient(
            {
                "vorname": "Bernd",
                "nachname": "Schulz",
                "geschlecht": "male",
                "geburtsdatum": "1975-09-30",
            },
            0,
            b,
        ),
        baue_observation(
            {"code": code, "wert": round((spec.low + spec.high) / 2, 2), "datum": "2024-03-11"},
            0,
            0,
            b,
        ),
    ]
    assert not b, f"Vorlage hat den Katalogeintrag {code} beanstandet: {b}"
    return assign_ids(ressourcen).resources


@pytest.mark.parametrize("code", sorted(OBSERVATION_CODES), ids=lambda c: f"loinc-{c}")
def test_jeder_messwertcode_ist_hapi_valide(hapi, code):
    """Deckt vor allem die UCUM-Einheiten ab — die Fehlerklasse, die die
    Laufzeitprüfung nicht sieht und die in Phase 0 fünfmal auftrat."""
    for ressource in _satz_fuer_messwert(code):
        fehler = hapi.fehler(ressource)
        assert not fehler, (
            f"Katalogeintrag {code} ({OBSERVATION_CODES[code].display_de}) erzeugt eine "
            f"invalide {ressource['resourceType']}:\n  "
            + "\n  ".join(str(f) for f in fehler)
        )


@pytest.mark.parametrize("code", sorted(CONDITION_CODES), ids=lambda c: f"snomed-{c}")
def test_jeder_diagnosecode_ist_hapi_valide(hapi, code):
    """Deckt Struktur und die Invarianten con-3/con-5 ab, außerdem die
    Doppelkodierung SNOMED + ICD-10-GM aus ADR-003."""
    for ressource in _satz_fuer_diagnose(code):
        fehler = hapi.fehler(ressource)
        assert not fehler, (
            f"Katalogeintrag {code} ({CONDITION_CODES[code].display_de}) erzeugt eine "
            f"invalide {ressource['resourceType']}:\n  "
            + "\n  ".join(str(f) for f in fehler)
        )


def test_bundle_mit_dem_gesamten_katalog_ist_valide(hapi):
    """Ein Bundle, das jeden Katalogeintrag genau einmal verwendet.

    Fängt Fehler, die erst im Zusammenspiel auftreten — etwa doppelte
    `fullUrl` (bdl-7) oder ein Bundle-Typ, der `entry.request` verlangt.
    """
    b: list[Beanstandung] = []
    ressourcen = [baue_patient({"vorname": "Clara", "nachname": "Kowalski",
                                "geschlecht": "female", "geburtsdatum": "1990-02-20"}, 0, b)]
    for i, code in enumerate(sorted(CONDITION_CODES)):
        ressourcen.append(baue_condition({"code": code, "beginn": "2019-01-01"}, 0, i, b))
    for i, code in enumerate(sorted(OBSERVATION_CODES)):
        spec = OBSERVATION_CODES[code]
        ressourcen.append(
            baue_observation(
                {"code": code, "wert": round((spec.low + spec.high) / 2, 2), "datum": "2024-05-05"},
                0, i, b,
            )
        )
    assert not b, f"Vorlagen haben Katalogeinträge beanstandet: {b}"

    normalisiert = assign_ids(ressourcen)
    bundle = baue_bundle(normalisiert.resources)

    urls = [e["fullUrl"] for e in bundle["entry"]]
    assert len(urls) == len(set(urls)), "fullUrl ist nicht eindeutig (bdl-7)"

    fehler = hapi.fehler(bundle)
    assert not fehler, "Das Katalog-Bundle ist invalide:\n  " + "\n  ".join(
        str(f) for f in fehler
    )


def test_hapi_spricht_r4(hapi):
    """Absicherung gegen eine stillschweigend gewechselte Serverversion.

    Die Zielversion des Projekts ist R4 (4.0.1). Liefe der Container gegen
    R5, prüfte dieser Test etwas anderes als das Produkt zusagt — und
    niemand würde es merken.
    """
    version = hapi.bereit(wartezeit_s=5.0)
    assert version is not None
    assert version.startswith("4.0"), (
        f"HAPI meldet FHIR-Version {version!r}, erwartet wird R4 (4.0.x). "
        "Die Zusage des Produkts bezieht sich auf R4."
    )
