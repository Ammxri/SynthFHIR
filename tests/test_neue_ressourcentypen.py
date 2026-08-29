"""Tests für Encounter und MedicationStatement (Phase 2).

Der Schwerpunkt liegt auf zwei Dingen, die keine Prüfschicht von allein
fängt:

* **`Encounter.class` ist ein `Coding`, kein `CodeableConcept`.** Der
  Unterschied ist im JSON unsichtbar und im Editor unauffällig.
* **Codes.** Weder die Laufzeitprüfung noch HAPI wissen, ob ein ATC-Code
  existiert oder wogegen der Wirkstoff hilft. Was hier nicht geprüft wird,
  wird nirgends geprüft.
"""

from __future__ import annotations

import pytest

from synthfhir.domain import assign_ids, baue_aus_parametern
from synthfhir.domain.codes import (
    ACT_CODE_SYSTEM,
    ATC_SYSTEM,
    CONDITION_CODES,
    ENCOUNTER_CLASSES,
    MEDICATION_CODES,
    medikamente_fuer,
)
from synthfhir.domain.integrity import check_resources
from synthfhir.domain.templates import baue_encounter, baue_medicationstatement
from synthfhir.validation import pruefe_alle


def patient_mit_allem() -> dict:
    return {"patienten": [{
        "vorname": "Käthe", "nachname": "Müller", "geschlecht": "female",
        "geburtsdatum": "1955-03-17",
        "begegnungen": [{"art": "AMB", "datum": "2024-06-01"}],
        "diagnosen": [{"code": "44054006", "beginn": "2015-01-01"}],
        "messwerte": [{"code": "4548-4", "wert": 7.4, "datum": "2024-06-01"}],
        "medikamente": [{"code": "A10BA02", "beginn": "2015-02-01"}],
    }]}


def gebaut(parameter: dict) -> list[dict]:
    return assign_ids(baue_aus_parametern(parameter).ressourcen).resources


# --- Encounter.class: der unsichtbare Unterschied ---------------------------


def test_encounter_class_ist_ein_coding_kein_codeableconcept():
    """Nachgeprüft an HAPI: Ein `{"coding": [...]}` wird mit
    „Unrecognized property 'coding'" abgewiesen. Beides sieht im JSON fast
    gleich aus, und nur eines ist richtig."""
    enc = baue_encounter({"art": "AMB", "datum": "2024-06-01"}, 0, 0, [])
    assert set(enc["class"]) == {"system", "code", "display"}
    assert "coding" not in enc["class"], "class ist ein Coding, keine Hülle darum"
    assert enc["class"]["system"] == ACT_CODE_SYSTEM


def test_encounter_traegt_die_beiden_pflichtfelder():
    enc = baue_encounter({}, 0, 0, [])
    assert enc["status"], "status ist 1..1"
    assert enc["class"], "class ist 1..1"


def test_encounter_status_kommt_aus_dem_code_nicht_vom_modell():
    """Gemessen: `status: "abgeschlossen"` kommt durch die
    Laufzeitprüfung und wird erst von HAPI abgewiesen — die Bindung ist
    verpflichtend, aber fhir.resources erzwingt sie nicht (ADR-002).
    Deshalb darf das Modell den Wert gar nicht erst liefern."""
    enc = baue_encounter({"status": "abgeschlossen", "art": "AMB"}, 0, 0, [])
    assert enc["status"] == "finished"


def test_erfundene_begegnungsart_wird_ersetzt_und_protokolliert():
    b: list = []
    enc = baue_encounter({"art": "SPRECHSTUNDE", "datum": "2024-06-01"}, 0, 0, b)
    assert enc["class"]["code"] == "AMB"
    assert [x.art for x in b] == ["erfundene_begegnungsart"]


def test_fehlende_begegnungsart_ist_keine_beanstandung():
    """Nichts zu liefern ist kein Fehler — nur etwas Falsches zu liefern.

    Ein fehlendes Datum ist etwas anderes: Dort ersetzt der Code einen
    konkreten Wert, und das gehört protokolliert. Deshalb steht hier ein
    gültiges Datum, damit der Test genau eine Sache prüft.
    """
    b: list = []
    baue_encounter({"datum": "2024-06-01"}, 0, 0, b)
    assert b == []


# --- MedicationStatement ---------------------------------------------------


def test_medicationstatement_traegt_die_pflichtfelder():
    med = baue_medicationstatement({"code": "A10BA02"}, 0, 0, [])
    assert med["status"]
    assert med["medicationCodeableConcept"]["coding"][0]["system"] == ATC_SYSTEM
    assert med["subject"]["reference"].startswith("Patient/")


def test_erfundener_wirkstoffcode_wird_ersetzt_und_protokolliert():
    b: list = []
    med = baue_medicationstatement(
        {"code": "X99ZZ99", "beginn": "2023-01-01"}, 0, 0, b
    )
    assert med["medicationCodeableConcept"]["coding"][0]["code"] in MEDICATION_CODES
    assert [x.art for x in b] == ["erfundener_medikamentencode"]


def test_anzeigetext_ist_woertlich_aus_der_quelle():
    """`display` steht kleingeschrieben und englisch da, weil es wörtlich
    aus dem WHOCC-Index stammt. Eine geglättete Schreibweise ließe sich
    nicht mehr gegen die Quelle abgleichen — und dieser Abgleich ist die
    einzige Prüfung, die es für Codes gibt."""
    med = baue_medicationstatement({"code": "A10BA02"}, 0, 0, [])
    coding = med["medicationCodeableConcept"]["coding"][0]
    assert coding["display"] == "metformin"
    assert med["medicationCodeableConcept"]["text"] == "Metformin"


# --- Der Katalog: was hier nicht geprüft wird, wird nirgends geprüft -------


def test_jeder_wirkstoff_nennt_nur_bekannte_indikationen():
    """Eine Indikation, die es im Diagnosekatalog nicht gibt, wäre eine
    stille Sackgasse: Der Wirkstoff würde nie vorgeschlagen."""
    for m in MEDICATION_CODES.values():
        unbekannt = [i for i in m.indikationen if i not in CONDITION_CODES]
        assert not unbekannt, f"{m.code} nennt {unbekannt}"


def test_jeder_wirkstoff_hat_mindestens_eine_indikation():
    for m in MEDICATION_CODES.values():
        assert m.indikationen, f"{m.code} ohne Indikation ist unerreichbar"


def test_atc_codes_haben_die_richtige_form():
    """ATC ist siebenstellig: Buchstabe, zwei Ziffern, zwei Buchstaben,
    zwei Ziffern. Das ersetzt keine Prüfung an der Quelle, fängt aber
    Tippfehler."""
    import re

    for code in MEDICATION_CODES:
        assert re.fullmatch(r"[A-Z]\d{2}[A-Z]{2}\d{2}", code), code


def test_begegnungsarten_stammen_aus_dem_valueset():
    assert set(ENCOUNTER_CLASSES) <= {
        "AMB", "EMER", "FLD", "HH", "IMP", "ACUTE", "NONAC", "OBSENC",
        "PRENC", "SS", "VR",
    }


def test_medikamente_fuer_liefert_nichts_wo_es_nichts_gibt():
    """Fünf Diagnosen haben bewusst keinen Wirkstoff. Ersatzweise
    irgendetwas zu wählen wäre ein fachlicher Fehler, den keine
    Prüfschicht bemerkt."""
    assert medikamente_fuer("414916001") == []          # Adipositas
    assert [m.code for m in medikamente_fuer("44054006")] == ["A10BA02"]


# --- Zusammenspiel ---------------------------------------------------------


def test_alle_fuenf_typen_entstehen_und_sind_valide():
    res = gebaut(patient_mit_allem())
    assert [r["resourceType"] for r in res] == [
        "Patient", "Encounter", "Condition", "Observation", "MedicationStatement",
    ]
    assert all(e.valide for e in pruefe_alle(res))


def test_kennungen_bekommen_eigene_praefixe():
    res = gebaut(patient_mit_allem())
    ids = {r["resourceType"]: r["id"] for r in res}
    assert ids["Encounter"] == "enc-001"
    assert ids["MedicationStatement"] == "med-001"


def test_diagnose_und_messwert_verweisen_auf_die_begegnung():
    res = gebaut(patient_mit_allem())
    enc = next(r for r in res if r["resourceType"] == "Encounter")
    for typ in ("Condition", "Observation"):
        r = next(x for x in res if x["resourceType"] == typ)
        assert r["encounter"]["reference"] == f"Encounter/{enc['id']}"


def test_ohne_begegnung_kein_verweis_ins_leere():
    """Der gefährliche Fall: ein Verweis auf eine Begegnung, die es nicht
    gibt. Strukturell einwandfrei, inhaltlich falsch."""
    p = patient_mit_allem()
    p["patienten"][0].pop("begegnungen")
    res = gebaut(p)
    for r in res:
        assert "encounter" not in r, f"{r['resourceType']} verweist ins Leere"
    assert check_resources(res).ok


def test_neue_typen_brauchen_einen_patientenbezug():
    """Encounter und MedicationStatement ohne subject sind sinnlos — und
    in R4 ist das Feld ohnehin Pflicht."""
    ohne = [
        {"resourceType": "Encounter", "id": "enc-001", "status": "finished",
         "class": {"system": ACT_CODE_SYSTEM, "code": "AMB"}},
        {"resourceType": "MedicationStatement", "id": "med-001", "status": "active",
         "medicationCodeableConcept": {"text": "x"}},
    ]
    bericht = check_resources(ohne)
    assert not bericht.ok
    assert len(bericht.missing_patient_link) == 2


def test_integritaet_bleibt_ueber_mehrere_patienten():
    p = patient_mit_allem()
    p["patienten"] = p["patienten"] * 3
    res = gebaut(p)
    bericht = check_resources(res)
    assert bericht.ok
    assert bericht.broken_reference_count == 0
    encs = [r["id"] for r in res if r["resourceType"] == "Encounter"]
    assert encs == ["enc-001", "enc-002", "enc-003"]
    # Jede Diagnose zeigt auf die Begegnung IHRES Patienten, nicht auf
    # irgendeine.
    for cond in (r for r in res if r["resourceType"] == "Condition"):
        eigener = cond["subject"]["reference"].replace("Patient/pat-", "")
        assert cond["encounter"]["reference"] == f"Encounter/enc-{eigener}"


def test_teilkohorten_versetzen_auch_die_neuen_typen():
    """ADR-004: Ohne Versatz trügen zwei Teile dieselben Kennungen.

    Dieser Test stand hier zuerst mit EINEM Patienten und EINER Begegnung —
    also genau der Form, in der die Kollision nicht auftritt. Er war grün
    und wertlos. Jetzt mehrere Patienten mit je mehreren Ressourcen eines
    Typs: das ist der Fall, der wirklich brach.
    """
    def viele(start: int) -> dict:
        einer = patient_mit_allem()["patienten"][0]
        einer = dict(einer)
        einer["begegnungen"] = [{"art": "AMB", "datum": "2024-01-01"},
                                {"art": "IMP", "datum": "2024-02-01"}]
        einer["diagnosen"] = [{"code": "44054006", "beginn": "2015-01-01"},
                              {"code": "38341003", "beginn": "2016-01-01"}]
        return {"patienten": [dict(einer, vorname=f"V{start + i}") for i in range(3)]}

    erst = baue_aus_parametern(viele(0), index_versatz=0).ressourcen
    zweit = baue_aus_parametern(viele(3), index_versatz=3).ressourcen
    ids = [r["id"] for r in erst + zweit]
    assert len(ids) == len(set(ids)), "kollidierende vorläufige Kennungen"

    norm = assign_ids(erst + zweit)
    assert norm.duplicate_ids_from_llm == []
    bericht = check_resources(norm.resources)
    assert bericht.ok, bericht.broken_references[:3]
    assert bericht.broken_reference_count == 0


def test_verweise_bleiben_beim_eigenen_patienten_ueber_teilgrenzen():
    """Der eigentliche Schaden der Kollision war nicht die doppelte
    Kennung, sondern dass eine Diagnose auf die Begegnung eines FREMDEN
    Patienten zeigte — strukturell einwandfrei, inhaltlich falsch."""
    def zwei(start: int) -> dict:
        einer = dict(patient_mit_allem()["patienten"][0])
        einer["begegnungen"] = [{"art": "AMB", "datum": "2024-01-01"},
                                {"art": "IMP", "datum": "2024-02-01"}]
        return {"patienten": [dict(einer, vorname=f"V{start + i}") for i in range(3)]}

    res = assign_ids(
        baue_aus_parametern(zwei(0), index_versatz=0).ressourcen
        + baue_aus_parametern(zwei(3), index_versatz=3).ressourcen
    ).resources

    patient_von_begegnung = {
        r["id"]: r["subject"]["reference"]
        for r in res if r["resourceType"] == "Encounter"
    }
    for r in res:
        if r.get("encounter"):
            begegnung = r["encounter"]["reference"].split("/", 1)[1]
            assert patient_von_begegnung[begegnung] == r["subject"]["reference"], (
                f"{r['resourceType']}/{r['id']} zeigt auf eine fremde Begegnung"
            )


# --- Gegen den echten Server -----------------------------------------------


@pytest.mark.parametrize("art", sorted(ENCOUNTER_CLASSES))
def test_jede_begegnungsart_gegen_hapi(hapi, art):
    """Die Auflage aus ADR-002 gilt auch für die neuen Kataloge: Jeder
    Eintrag wird zu einer Ressource gebaut und dem echten Server
    vorgelegt."""
    enc = baue_encounter({"art": art, "datum": "2024-06-01"}, 0, 0, [])
    enc["subject"] = {"reference": "Patient/pat-001"}
    assert not hapi.fehler(enc)


@pytest.mark.parametrize("code", sorted(MEDICATION_CODES))
def test_jeder_wirkstoff_gegen_hapi(hapi, code):
    med = baue_medicationstatement({"code": code, "beginn": "2023-01-01"}, 0, 0, [])
    assert not hapi.fehler(med)


def test_der_ganze_satz_gegen_hapi(hapi):
    for r in gebaut(patient_mit_allem()):
        fehler = hapi.fehler(r)
        assert not fehler, f"{r['resourceType']}: {fehler}"


def test_erfundene_codes_zaehlt_auch_die_neuen_arten():
    """Die Metrik lief über eine Aufzählung von zwei Arten. Mit Phase 2
    kamen zwei weitere hinzu — und sie meldete weiter zwei von vier."""
    bau = baue_aus_parametern({"patienten": [{
        "vorname": "V", "nachname": "N", "geschlecht": "female",
        "geburtsdatum": "1960-01-01",
        "begegnungen": [{"art": "ERFUNDEN", "datum": "2024-01-01"}],
        "diagnosen": [{"code": "999", "beginn": "2015-01-01"}],
        "messwerte": [{"code": "888", "wert": 1.0, "datum": "2024-01-01"}],
        "medikamente": [{"code": "Z99ZZ99", "beginn": "2023-01-01"}],
    }]})
    arten = sorted({b.art for b in bau.beanstandungen if b.art.startswith("erfunden")})
    assert arten == [
        "erfundene_begegnungsart",
        "erfundener_diagnosecode",
        "erfundener_medikamentencode",
        "erfundener_messwertcode",
    ]
    assert bau.erfundene_codes == 4


def test_atc_system_passt_zum_anzeigetext():
    """`display` soll die Bezeichnung AUS DEM GENANNTEN SYSTEM sein. Hier
    stand die englische WHOCC-Bezeichnung unter der deutschen BfArM-URI —
    im deutschen Katalog heißt der Eintrag aber „Metformin"."""
    from synthfhir.domain.codes import ATC_SYSTEM

    assert ATC_SYSTEM == "http://www.whocc.no/atc"
    med = baue_medicationstatement({"code": "A10BA02"}, 0, 0, [])
    coding = med["medicationCodeableConcept"]["coding"][0]
    assert coding["system"] == ATC_SYSTEM
    assert coding["display"] == "metformin", "englisch, wie bei der WHO"
    assert med["medicationCodeableConcept"]["text"] == "Metformin"


def test_feste_werte_wirken_im_fingerabdruck(monkeypatch):
    """`FESTE_WERTE` war deklariert, dokumentiert — und nirgends benutzt.
    Eine Konstante, die aussieht, als täte sie etwas.

    Ersetzt wird der Name in `aufzeichnung`, nicht in `codes`: Der Import
    holt den Wert, nicht den Verweis, und ein Neubinden in der Quelle bliebe
    dort wirkungslos. Bei `KATALOGE` fällt das nicht auf, weil dessen Inhalt
    verändert wird und nicht die Bindung.
    """
    from synthfhir import aufzeichnung as aufz

    vorher = aufz.katalog_pruefsumme()
    monkeypatch.setattr(aufz, "FESTE_WERTE", ("geaendert",))
    assert aufz.katalog_pruefsumme() != vorher
