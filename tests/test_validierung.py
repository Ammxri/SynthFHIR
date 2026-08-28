"""Tests der Laufzeitvalidierung (ADR-002, Stufe 1).

Prüft beide Richtungen: Sie muss echte Strukturfehler finden **und** darf
gültige Ressourcen nicht fälschlich ablehnen. Der zweite Teil ist der
wichtigere — ein falscher Alarm im Betrieb würde brauchbare Ausgaben
verwerfen, ohne dass es jemand bemerkt. In der Messung aus ADR-002 lag er
bei 0 von 339.
"""

from __future__ import annotations

import pytest

from synthfhir.domain.codes import CONDITION_CODES, OBSERVATION_CODES
from synthfhir.domain.identity import assign_ids
from synthfhir.domain.templates import baue_aus_parametern
from synthfhir.validation import alle_valide, pruefe_alle, pruefe_ressource


def _beispielsatz() -> list[dict]:
    ergebnis = baue_aus_parametern(
        {"patienten": [{"vorname": "Anna", "nachname": "Meier", "geschlecht": "female",
                        "geburtsdatum": "1968-04-12",
                        "diagnosen": [{"code": "44054006", "beginn": "2015-06-01"}],
                        "messwerte": [{"code": "4548-4", "wert": 7.9, "datum": "2024-03-11"}]}]}
    )
    return assign_ids(ergebnis.ressourcen).resources


# --- Was gültig ist, muss gültig bleiben -----------------------------------


def test_erzeugte_ressourcen_sind_valide():
    ergebnisse = pruefe_alle(_beispielsatz())
    assert alle_valide(ergebnisse), [b for e in ergebnisse for b in e.befunde]


@pytest.mark.parametrize("code", sorted(CONDITION_CODES))
def test_kein_falscher_alarm_bei_diagnosen(code):
    """Der ganze Katalog darf keine falschen Alarme auslösen — auch nicht
    durch die zweite ICD-10-GM-Kodierung aus ADR-003."""
    ergebnis = baue_aus_parametern(
        {"patienten": [{"vorname": "A", "nachname": "B", "geschlecht": "male",
                        "geburtsdatum": "1980-01-01",
                        "diagnosen": [{"code": code, "beginn": "2020-01-01"}],
                        "messwerte": []}]}
    )
    ergebnisse = pruefe_alle(assign_ids(ergebnis.ressourcen).resources)
    assert alle_valide(ergebnisse), [str(b) for e in ergebnisse for b in e.befunde]


@pytest.mark.parametrize("code", sorted(OBSERVATION_CODES))
def test_kein_falscher_alarm_bei_messwerten(code):
    spec = OBSERVATION_CODES[code]
    ergebnis = baue_aus_parametern(
        {"patienten": [{"vorname": "A", "nachname": "B", "geschlecht": "male",
                        "geburtsdatum": "1980-01-01", "diagnosen": [],
                        "messwerte": [{"code": code, "wert": round((spec.low + spec.high) / 2, 2),
                                       "datum": "2024-01-01"}]}]}
    )
    ergebnisse = pruefe_alle(assign_ids(ergebnis.ressourcen).resources)
    assert alle_valide(ergebnisse), [str(b) for e in ergebnisse for b in e.befunde]


# --- Was ungültig ist, muss auffallen --------------------------------------


def test_fehlendes_pflichtfeld_wird_erkannt():
    """`Observation.status` ist 1..1 — der Klassiker aus Phase 0, fünfmal
    von Variante A produziert."""
    kaputt = {
        "resourceType": "Observation",
        "id": "obs-001",
        "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4"}]},
    }
    ergebnis = pruefe_ressource(kaputt)
    assert not ergebnis.valide
    assert any("status" in b.pfad for b in ergebnis.befunde), ergebnis.befunde


def test_falscher_datentyp_wird_erkannt():
    """`valueQuantity.value` ist decimal, kein String."""
    kaputt = {
        "resourceType": "Observation",
        "id": "obs-001",
        "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4"}]},
        "valueQuantity": {"value": "sieben", "unit": "%"},
    }
    assert not pruefe_ressource(kaputt).valide


def test_deutsches_datumsformat_wird_erkannt():
    kaputt = {"resourceType": "Patient", "id": "pat-001", "birthDate": "12.05.1980"}
    assert not pruefe_ressource(kaputt).valide


def test_fehlender_ressourcentyp_wird_erkannt():
    ergebnis = pruefe_ressource({"id": "x"})
    assert not ergebnis.valide
    assert "resourceType" in ergebnis.befunde[0].pfad


def test_nicht_unterstuetzter_typ_wird_abgelehnt():
    """PRD Block 9: keine weiteren Ressourcentypen im MVP. Ein Encounter
    darf nicht stillschweigend durchgereicht werden."""
    ergebnis = pruefe_ressource({"resourceType": "Encounter", "id": "enc-1", "status": "finished"})
    assert not ergebnis.valide
    assert "Encounter" in ergebnis.befunde[0].meldung


# --- Was die Prüfung bewusst NICHT sieht -----------------------------------


def test_ungueltige_einheit_faellt_hier_nicht_auf():
    """Dokumentiert die bekannte Lücke aus ADR-002, statt sie zu verschweigen.

    Schlüge dieser Test eines Tages fehl, wäre das eine gute Nachricht —
    dann prüfte die Bibliothek plötzlich UCUM. Bis dahin ist der
    HAPI-Katalogtest die einzige Absicherung dieser Fehlerklasse, und
    dieser Test hält fest, warum es ihn geben muss.
    """
    mit_falscher_einheit = {
        "resourceType": "Observation",
        "id": "obs-001",
        "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4"}]},
        "valueQuantity": {
            "value": 7.9,
            "unit": "Prozent",
            "system": "http://unitsofmeasure.org",
            "code": "IU/mL",  # von HAPI in Phase 0 als ungültig gemeldet
        },
    }
    assert pruefe_ressource(mit_falscher_einheit).valide, (
        "Die Laufzeitprüfung erkennt UCUM jetzt doch — ADR-002 und der Kommentar "
        "in validation.py wären dann zu aktualisieren."
    )


@pytest.mark.parametrize(
    "ressource, feld",
    [
        ({"resourceType": "Patient", "id": "p1", "gender": "weiblich"}, "gender"),
        (
            {"resourceType": "Observation", "id": "o1", "status": "fertig",
             "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4"}]}},
            "status",
        ),
        (
            {"resourceType": "Condition", "id": "c1", "subject": {"reference": "Patient/p1"},
             "clinicalStatus": {"coding": [{
                 "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                 "code": "aktiv"}]}},
            "clinicalStatus",
        ),
    ],
)
def test_required_binding_faellt_hier_nicht_auf(ressource, feld):
    """Dritte bekannte Lücke: required bindings werden nicht erzwungen.

    `fhir.resources` prüft bei `code`-Feldern nur den Datentyp, nicht die
    gebundene Werteliste. HAPI weist alle drei Fälle zurück - nachgeprüft
    am 2026-08-28.

    Tragbar ist das, weil genau diese drei Felder von der Vorlage gesetzt
    werden und nie vom Modell kommen: `gender` normalisiert `_geschlecht`,
    `status` steht fest auf "final", die beiden Condition-Statusfelder
    stehen fest im Code. Abgesichert wird das durch
    `test_vorlage_setzt_gebundene_codes_fest` unten und durch den
    HAPI-Katalogtest.
    """
    assert pruefe_ressource(ressource).valide, (
        f"Die Laufzeitprüfung erkennt das required binding auf {feld} jetzt doch - "
        "dann sind ADR-002 und validation.py zu aktualisieren."
    )


def test_vorlage_setzt_gebundene_codes_fest():
    """Die eigentliche Absicherung gegen die Lücke oben.

    Was die Laufzeitprüfung nicht erzwingt, muss die Vorlage garantieren.
    Dieser Test ist deshalb nicht redundant zu den Vorlagentests, sondern
    das Gegenstück zum Test darüber.
    """
    from synthfhir.domain.templates import ALLOWED_GENDERS

    ergebnis = baue_aus_parametern(
        {"patienten": [{"geschlecht": "weiblich", "geburtsdatum": "quatsch",
                        "diagnosen": [{"code": "44054006"}],
                        "messwerte": [{"code": "4548-4", "wert": 7.0}]}]}
    )
    nach_typ = {r["resourceType"]: r for r in ergebnis.ressourcen}
    assert nach_typ["Patient"]["gender"] in ALLOWED_GENDERS
    assert nach_typ["Observation"]["status"] == "final"
    assert nach_typ["Condition"]["clinicalStatus"]["coding"][0]["code"] == "active"
    assert nach_typ["Condition"]["verificationStatus"]["coding"][0]["code"] == "confirmed"


def test_erfundener_code_faellt_hier_nicht_auf():
    """Ebenfalls bekannte Lücke: Codes werden nicht nachgeschlagen. Dagegen
    hilft nur der Katalog, nicht die Validierung."""
    mit_erfundenem_code = {
        "resourceType": "Observation",
        "id": "obs-001",
        "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": "99999-9"}]},
    }
    assert pruefe_ressource(mit_erfundenem_code).valide
