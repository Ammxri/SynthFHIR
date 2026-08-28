"""Tests des Domänenkerns — laufen ohne Server und ohne Sprachmodell.

Der Kern ist rein deterministisch: gleiche Parameter, gleiche Ressourcen.
Genau deshalb ist er vollständig testbar, und genau darauf beruht die
Zusage des Produkts.
"""

from __future__ import annotations

import re

import pytest

from synthfhir.domain.codes import (
    CONDITION_CODES,
    ICD10GM_SYSTEM,
    OBSERVATION_CODES,
    SNOMED_SYSTEM,
    icd_abdeckung,
)
from synthfhir.domain.identity import assign_ids
from synthfhir.domain.integrity import check_resources
from synthfhir.domain.templates import (
    Beanstandung,
    baue_aus_parametern,
    baue_bundle,
    baue_condition,
    baue_observation,
    baue_patient,
)

# ICD-10-GM: Buchstabe, zwei Ziffern, optional Punkt und ein bis zwei Stellen.
ICD10GM_FORMAT = re.compile(r"^[A-Z]\d{2}(\.\d{1,2})?$")


# --- Katalog ---------------------------------------------------------------


def test_katalog_ist_nicht_leer():
    assert len(OBSERVATION_CODES) >= 20
    assert len(CONDITION_CODES) >= 20


def test_katalogschluessel_stimmen_mit_den_codes_ueberein():
    """Ein Tippfehler im Schlüssel machte den Eintrag unauffindbar."""
    assert all(k == v.code for k, v in OBSERVATION_CODES.items())
    assert all(k == v.code for k, v in CONDITION_CODES.items())


def test_jeder_eintrag_hat_einen_deutschen_anzeigetext():
    """Die Lokalisierung ist der zweite Differenzierer des Produkts (US-4);
    ein leerer deutscher Text unterliefe sie still."""
    for eintrag in list(OBSERVATION_CODES.values()) + list(CONDITION_CODES.values()):
        assert eintrag.display_de.strip(), f"{eintrag.code} hat keinen deutschen Anzeigetext"


def test_icd_schluessel_haben_gueltiges_format():
    """Die einzige maschinelle Prüfung, die es für ICD-10-GM gibt.

    HAPI kennt das CodeSystem nicht und meldet einen falschen Schlüssel
    allenfalls als Warnung. Ein Formatfehler ist damit die einzige Klasse
    von ICD-Fehlern, die automatisch auffällt — inhaltliche Richtigkeit
    braucht den Abgleich gegen den BfArM-Katalog von Hand.
    """
    for eintrag in CONDITION_CODES.values():
        if eintrag.icd10gm is None:
            continue
        assert ICD10GM_FORMAT.match(eintrag.icd10gm), (
            f"{eintrag.code} ({eintrag.display_de}): {eintrag.icd10gm!r} ist kein "
            "gültiges ICD-10-GM-Format"
        )


def test_icd_eintrag_hat_immer_auch_einen_anzeigetext():
    for eintrag in CONDITION_CODES.values():
        if eintrag.icd10gm is not None:
            assert eintrag.icd10gm_display, f"{eintrag.code}: ICD-Code ohne Anzeigetext"


def test_icd_abdeckung_ist_dokumentiert():
    """Hält den Pflegestand sichtbar. Sinkt die Abdeckung, fällt es auf."""
    mit, gesamt = icd_abdeckung()
    assert gesamt == len(CONDITION_CODES)
    assert mit >= 20, f"Nur {mit} von {gesamt} Diagnosen haben einen ICD-10-GM-Schlüssel"


def test_ucum_und_anzeigeeinheit_sind_getrennt_gepflegt():
    """`mmHg` ist die Anzeige, `mm[Hg]` der UCUM-Code — die Verwechslung war
    in Phase 0 die häufigste Einheitenfehlerquelle."""
    blutdruck = OBSERVATION_CODES["8480-6"]
    assert blutdruck.unit == "mmHg"
    assert blutdruck.unit_code == "mm[Hg]"
    for eintrag in OBSERVATION_CODES.values():
        assert eintrag.unit_code.strip(), f"{eintrag.code} hat keinen UCUM-Code"
        assert eintrag.low < eintrag.high, f"{eintrag.code} hat einen leeren Wertebereich"


# --- Vorlagen --------------------------------------------------------------


def test_condition_traegt_beide_kodierungen():
    """ADR-003: SNOMED und ICD-10-GM nebeneinander in derselben CodeableConcept."""
    b: list[Beanstandung] = []
    condition = baue_condition({"code": "44054006", "beginn": "2015-06-01"}, 0, 0, b)
    systeme = [c["system"] for c in condition["code"]["coding"]]
    assert SNOMED_SYSTEM in systeme
    assert ICD10GM_SYSTEM in systeme
    icd = next(c for c in condition["code"]["coding"] if c["system"] == ICD10GM_SYSTEM)
    assert icd["code"] == "E11.90"
    assert condition["code"]["text"] == "Diabetes mellitus Typ 2"


def test_condition_ohne_icd_traegt_nur_snomed():
    """Fehlt ein geprüfter Schlüssel, bleibt es bei SNOMED — weiterhin
    gültiges FHIR, statt einen Code zu raten."""
    b: list[Beanstandung] = []
    condition = baue_condition({"code": "396275006", "beginn": "2020-01-01"}, 0, 0, b)  # Arthrose
    systeme = [c["system"] for c in condition["code"]["coding"]]
    assert systeme == [SNOMED_SYSTEM]
    assert not b


def test_vorlagen_setzen_die_pflichtfelder():
    b: list[Beanstandung] = []
    patient = baue_patient(
        {"vorname": "Anna", "nachname": "Meier", "geschlecht": "female",
         "geburtsdatum": "1968-04-12"}, 0, b)
    condition = baue_condition({"code": "44054006", "beginn": "2015-06-01"}, 0, 0, b)
    observation = baue_observation({"code": "4548-4", "wert": 7.9, "datum": "2024-03-11"}, 0, 0, b)
    assert not b

    assert patient["gender"] == "female"
    assert patient["birthDate"] == "1968-04-12"
    assert condition["subject"]["reference"]                       # 1..1
    assert condition["clinicalStatus"]["coding"][0]["code"] == "active"
    assert condition["verificationStatus"]["coding"][0]["code"] == "confirmed"
    assert observation["status"] == "final"                        # 1..1
    assert observation["code"]["coding"][0]["code"] == "4548-4"    # 1..1
    assert observation["valueQuantity"]["system"] == "http://unitsofmeasure.org"


def test_kaputte_parameter_ergeben_trotzdem_gueltige_struktur():
    """Der Kern der Architektur: Das Modell kann strukturell nichts zerstören."""
    ergebnis = baue_aus_parametern(
        {
            "patienten": [
                {
                    "geschlecht": "weiblich",
                    "geburtsdatum": "12.05.1980",
                    "diagnosen": [{"code": "gibt-es-nicht"}],
                    "messwerte": [{"code": "auch-nicht", "wert": "hoch"}],
                }
            ]
        }
    )
    assert len(ergebnis.ressourcen) == 3
    patient = ergebnis.ressourcen[0]
    observation = ergebnis.ressourcen[2]
    assert patient["gender"] == "unknown"
    assert patient["birthDate"] == "1970-01-01"
    assert observation["status"] == "final"
    assert isinstance(observation["valueQuantity"]["value"], float)
    assert ergebnis.erfundene_codes == 2


def test_mengenabweichung_wird_gemeldet_nicht_aufgefuellt():
    """Mengentreue war in Phase 0 das entscheidende Kriterium. Sie muss
    messbar bleiben — stilles Auffüllen würde genau das verdecken."""
    ergebnis = baue_aus_parametern(
        {"patienten": [{"vorname": "A", "nachname": "B", "geschlecht": "male",
                        "geburtsdatum": "1980-01-01", "diagnosen": [], "messwerte": []}]},
        erwartet={"patienten": 3, "diagnosen_je_patient": 1, "messwerte_je_patient": 1},
    )
    arten = [b.art for b in ergebnis.beanstandungen]
    assert arten.count("mengenabweichung") == 3      # Patienten, Diagnosen, Messwerte
    assert len([r for r in ergebnis.ressourcen if r["resourceType"] == "Patient"]) == 1


# --- Identität und Referenzintegrität --------------------------------------


def test_ids_kommen_vom_code_und_referenzen_ziehen_mit():
    ergebnis = baue_aus_parametern(
        {"patienten": [{"vorname": "Anna", "nachname": "Meier", "geschlecht": "female",
                        "geburtsdatum": "1968-04-12",
                        "diagnosen": [{"code": "44054006", "beginn": "2015-01-01"}],
                        "messwerte": [{"code": "4548-4", "wert": 7.9, "datum": "2024-01-01"}]}]}
    )
    normalisiert = assign_ids(ergebnis.ressourcen)
    ids = [r["id"] for r in normalisiert.resources]
    assert ids == ["pat-001", "cond-001", "obs-001"]
    for r in normalisiert.resources[1:]:
        assert r["subject"]["reference"] == "Patient/pat-001"


def test_referenzintegritaet_ist_sauber():
    ergebnis = baue_aus_parametern(
        {"patienten": [
            {"vorname": "A", "nachname": "B", "geschlecht": "male", "geburtsdatum": "1980-01-01",
             "diagnosen": [{"code": "44054006"}], "messwerte": [{"code": "718-7", "wert": 14.0}]},
            {"vorname": "C", "nachname": "D", "geschlecht": "female", "geburtsdatum": "1990-01-01",
             "diagnosen": [{"code": "38341003"}], "messwerte": [{"code": "8480-6", "wert": 130}]},
        ]}
    )
    normalisiert = assign_ids(ergebnis.ressourcen)
    bericht = check_resources(normalisiert.resources)
    assert bericht.ok
    assert bericht.broken_reference_count == 0
    assert bericht.duplicate_ids == []
    assert bericht.missing_patient_link == []


def test_jeder_patient_bekommt_seine_eigenen_verweise():
    """Bei mehreren Patienten darf nichts querverdrahtet werden."""
    ergebnis = baue_aus_parametern(
        {"patienten": [
            {"vorname": "A", "nachname": "B", "geschlecht": "male", "geburtsdatum": "1980-01-01",
             "diagnosen": [{"code": "44054006"}], "messwerte": []},
            {"vorname": "C", "nachname": "D", "geschlecht": "female", "geburtsdatum": "1990-01-01",
             "diagnosen": [{"code": "38341003"}], "messwerte": []},
        ]}
    )
    normalisiert = assign_ids(ergebnis.ressourcen)
    conditions = [r for r in normalisiert.resources if r["resourceType"] == "Condition"]
    ziele = {c["subject"]["reference"] for c in conditions}
    assert ziele == {"Patient/pat-001", "Patient/pat-002"}


def test_bundle_ist_eine_collection_mit_eindeutigen_urls():
    ergebnis = baue_aus_parametern(
        {"patienten": [{"vorname": "A", "nachname": "B", "geschlecht": "male",
                        "geburtsdatum": "1980-01-01",
                        "diagnosen": [{"code": "44054006"}],
                        "messwerte": [{"code": "718-7", "wert": 14.0}]}]}
    )
    bundle = baue_bundle(assign_ids(ergebnis.ressourcen).resources)
    assert bundle["type"] == "collection"
    urls = [e["fullUrl"] for e in bundle["entry"]]
    assert len(urls) == len(set(urls))
    assert all("request" not in e and "response" not in e for e in bundle["entry"])


@pytest.mark.parametrize("code", sorted(CONDITION_CODES))
def test_jeder_diagnosecode_baut_ohne_beanstandung(code):
    b: list[Beanstandung] = []
    baue_condition({"code": code, "beginn": "2020-01-01"}, 0, 0, b)
    assert not b


@pytest.mark.parametrize("code", sorted(OBSERVATION_CODES))
def test_jeder_messwertcode_baut_ohne_beanstandung(code):
    spec = OBSERVATION_CODES[code]
    b: list[Beanstandung] = []
    baue_observation(
        {"code": code, "wert": round((spec.low + spec.high) / 2, 2), "datum": "2024-01-01"}, 0, 0, b
    )
    assert not b
