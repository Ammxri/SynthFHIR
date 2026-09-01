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
    ConditionCode,
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
    von ICD-Fehlern, die automatisch auffällt.

    Wie eng diese Grenze ist, hat die Prüfung vom 2026-08-28 gezeigt: `J45.9`
    und `B18.1` bestehen diesen Test mühelos und sind trotzdem nicht
    kodierbar, weil ICD-10-GM dort eine fünfte Stelle verlangt. Inhaltliche
    Richtigkeit braucht den Abgleich mit der Primärquelle.
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


def test_icd_abdeckung_faellt_nicht_still_zurueck():
    """Hält den Pflegestand sichtbar.

    Nach der BfArM-Prüfung vom 2026-08-28 tragen alle 25 Diagnosen einen
    Schlüssel. Ein einzelner bewusst leer gelassener Eintrag ist erlaubt -
    das ist die Entscheidung aus ADR-003 -, ein Einbruch darüber hinaus
    wäre dagegen ein Versehen und soll auffallen.
    """
    mit, gesamt = icd_abdeckung()
    assert gesamt == len(CONDITION_CODES)
    assert mit >= gesamt - 2, (
        f"Nur {mit} von {gesamt} Diagnosen haben einen ICD-10-GM-Schlüssel. "
        "Absicht? Dann diesen Test anpassen und die Begründung notieren."
    )


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


def test_condition_ohne_icd_traegt_nur_snomed(monkeypatch):
    """Fehlt ein geprüfter Schlüssel, bleibt es bei SNOMED — weiterhin
    gültiges FHIR, statt einen Code zu raten.

    Der Fall wird mit einem eigens eingesetzten Eintrag geprüft, nicht mit
    einem echten aus dem Katalog: Nach der BfArM-Prüfung vom 2026-08-28
    haben alle 25 Diagnosen einen Schlüssel. Ein Test, der sich auf eine
    zufällig leere Zeile stützt, bricht bei der nächsten Ergänzung — genau
    das ist hier passiert, als Arthrose ihren Schlüssel M19.99 bekam.
    """
    ohne_icd = ConditionCode("000000000", "Test condition", "Testdiagnose")
    assert not ohne_icd.hat_icd
    monkeypatch.setitem(CONDITION_CODES, ohne_icd.code, ohne_icd)

    b: list[Beanstandung] = []
    condition = baue_condition({"code": ohne_icd.code, "beginn": "2020-01-01"}, 0, 0, b)
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
    # Vier statt drei: Der Encounter kommt vom Code, weil eine kodierte
    # Diagnose ihren Kontakt nennen muss (ADR-009). Auch aus kaputten
    # Parametern entsteht eine strukturell vollständige Ressourcenmenge —
    # das ist die Aussage dieses Tests.
    assert len(ergebnis.ressourcen) == 4
    # Nach Typ statt nach Position: Kommt ein Ressourcentyp hinzu,
    # verschieben sich sonst die Indizes und der Test prüft etwas anderes,
    # ohne rot zu werden.
    nach_typ = {r["resourceType"]: r for r in ergebnis.ressourcen}
    patient = nach_typ["Patient"]
    observation = nach_typ["Observation"]
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
    # Der Encounter steht dazwischen, seit der Code ihn garantiert:
    # ISiK verlangt, dass eine kodierte Diagnose ihren Kontakt nennt
    # (ADR-009). Er wird VOR den Diagnosen gebaut, damit die Verweise
    # nach hinten zeigen.
    assert ids == ["pat-001", "enc-001", "cond-001", "obs-001"]
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


# --- Fachliche Identifier über Teilgrenzen ---------------------------------
#
# Die technische `id` und der fachliche Identifier sind zwei verschiedene
# Dinge und können unabhängig voneinander kaputtgehen. Genau das war der
# Fall: `assign_ids` machte die `id` über den Teilkenner eindeutig, die
# Fallnummer hing am teil-lokalen Zähler und begann in jedem Teil neu.
#
# Kein Test der Suite sah den fachlichen Identifier je an — `grep` über
# `tests/` fand weder `FALL-` noch `SYN-`. Gemessen wurde die technische
# Kennung, also die Nachbarschaft des Fehlers.


def _patient_mit_begegnungen(n: int, begegnungen: int = 2) -> dict:
    return {
        "vorname": f"Vorname{n}",
        "nachname": f"Nachname{n}",
        "geschlecht": "female",
        "geburtsdatum": "1970-01-01",
        "begegnungen": [
            {"art": "AMB", "datum": f"2024-0{i + 1}-01"} for i in range(begegnungen)
        ],
        "diagnosen": [{"code": "44054006", "beginn": "2015-01-01"}],
    }


def _baue_in_teilen(teile: list[list]) -> list[dict]:
    """Setzt mehrere Teile so zusammen, wie `kohorte.py` es tut."""
    alle: list[dict] = []
    versatz = 0
    for patienten in teile:
        bau = baue_aus_parametern({"patienten": patienten}, index_versatz=versatz)
        alle.extend(bau.ressourcen)
        versatz += max(bau.plaetze_belegt, 1)
    return assign_ids(alle).resources


def _identifier(res: list[dict], typ: str) -> list[str]:
    return [
        e["value"]
        for r in res
        if r["resourceType"] == typ
        for e in r.get("identifier", [])
    ]


def test_fallnummern_sind_ueber_teile_hinweg_eindeutig():
    """Bei 200 Patienten und TEILGROESSE 8 war jede Fallnummer 25-fach
    vergeben — und `integritaet.ok` stand auf `True`.

    Die Fallnummer erfüllt seit ADR-009 den ISiK-Slice
    `Encounter.identifier:Aufnahmenummer`. Eine Aufnahmenummer, die es
    25-mal gibt, erfüllt ihn dem Buchstaben nach und dem Sinn nach nicht.
    """
    res = _baue_in_teilen([[_patient_mit_begegnungen(i)] * 1 for i in range(6)])
    fall = _identifier(res, "Encounter")
    assert len(fall) == 12, "sechs Patienten mit je zwei Begegnungen"
    assert len(set(fall)) == len(fall), f"doppelte Fallnummern: {sorted(fall)}"


def test_integritaet_meldet_doppelte_fachliche_identifier():
    """Die Prüfung sah bisher nur `resourceType/id` an.

    Deshalb ging die doppelte Fallnummer durch jede Prüfschicht bis ins
    Bundle und in den Push: Die technischen Kennungen waren ja korrekt.
    """
    res = [
        {"resourceType": "Encounter", "id": "enc-001",
         "identifier": [{"system": "urn:beispiel:fall", "value": "FALL-0001"}]},
        {"resourceType": "Encounter", "id": "enc-002",
         "identifier": [{"system": "urn:beispiel:fall", "value": "FALL-0001"}]},
    ]
    bericht = check_resources(res)
    assert bericht.duplicate_ids == [], "die technischen ids sind in Ordnung"
    assert bericht.duplicate_identifiers == ["urn:beispiel:fall|FALL-0001"]
    assert not bericht.ok, "eine doppelte Aufnahmenummer ist kein sauberer Satz"


def test_identifier_ohne_system_oder_wert_behaupten_nichts():
    """Ein unvollständiger Identifier ist keine Zusage, die sich verletzen
    liesse — sonst meldete die Prüfung zwei leere Werte als Dublette."""
    res = [
        {"resourceType": "Encounter", "id": "enc-001", "identifier": [{"value": "X"}]},
        {"resourceType": "Encounter", "id": "enc-002", "identifier": [{"value": "X"}]},
        {"resourceType": "Encounter", "id": "enc-003",
         "identifier": [{"system": "urn:beispiel:fall"}]},
    ]
    assert check_resources(res).duplicate_identifiers == []


def test_uebersprungener_eintrag_verbraucht_seinen_kennungsplatz():
    """Ein einziges `null` in der Modellantwort liess die Kennungen zweier
    Teile überlappen.

    Der Versatz wuchs um die Zahl der GEBAUTEN Patienten, `p_index` zählt
    aber über `enumerate(patienten)`. Nachgestellt mit sechs Patienten und
    Teilgrösse drei: sechs kaputte Verweise, ein doppelter Identifier, und
    die gesamte Kohorte fiel wegen eines Ausreissers durch.
    """
    res = _baue_in_teilen([
        [None, _patient_mit_begegnungen(1, 0), _patient_mit_begegnungen(2, 0)],
        [_patient_mit_begegnungen(i, 0) for i in range(3, 6)],
    ])
    bericht = check_resources(res)
    assert bericht.ok, (
        f"doppelte ids: {bericht.duplicate_ids}, "
        f"doppelte Identifier: {bericht.duplicate_identifiers}, "
        f"kaputte Verweise: {bericht.broken_reference_count}"
    )
    syn = _identifier(res, "Patient")
    assert len(syn) == 5, "fünf gebaute Patienten aus sechs Einträgen"
    assert len(set(syn)) == 5, f"doppelte Patientennummern: {sorted(syn)}"
