"""Tests des Domänenkerns — laufen ohne Server und ohne Sprachmodell.

Der Kern ist rein deterministisch: gleiche Parameter, gleiche Ressourcen.
Genau deshalb ist er vollständig testbar, und genau darauf beruht die
Zusage des Produkts.
"""

from __future__ import annotations

import json
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
    GRENZE_JE_PATIENT,
    zaehle_ressourcen,
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


# --- Die Mengengrenze ------------------------------------------------------
#
# Ein Patienteneintrag durfte beliebig viele Untereinträge tragen. Gemessen
# ergab EIN Patient mit 20.000 Messwerten 20.001 Ressourcen, ohne eine
# einzige Beanstandung.


def _patient(**kw):
    return {"vorname": "Käthe", "nachname": "Schäfer", "geschlecht": "female",
            "geburtsdatum": "1970-01-01", **kw}


def _messwerte(n):
    return [{"code": "8867-4", "wert": 80, "datum": "2023-01-01"}] * n


def test_die_vorzaehlung_stimmt_mit_dem_bau_ueberein():
    """Der wichtigste Test dieser Datei.

    `zaehle_je_patient` ist eine **Abschrift** der Zählweise von
    `baue_aus_parametern` — die Sorte Duplizierung, gegen die dieses
    Projekt sonst argumentiert. Sie ist nur zu verantworten, solange
    dieser Test beide gegeneinander hält.

    Entscheidend ist, was der Zufall erzeugt: Ein Test, der nur
    **wohlgeformte** Einträge würfelt, bliebe grün und bewiese nichts.
    Genau diese Falle hat sich das Projekt bei `katalog_pruefsumme` schon
    einmal gestellt — dort übersah eine Handaufzählung `vital_sign`.
    Deshalb kommen hier ausdrücklich Nicht-Objekte, falsch typisierte
    Unterlisten und Diagnosen ohne Begegnung vor.
    """
    import random

    wuerfel = random.Random(20260901)
    muell = [0, "text", None, [], {}, 5, "kein array", True]
    # Blutdruckcodes gehören ausdrücklich hinein: Seit ADR-014 wird ein
    # Paar zu EINER Observation, die Zählung ist also nicht mehr eins zu
    # eins. Ein Zufallstest, der nur leere Objekte würfelt, träfe diesen
    # Pfad nie und bliebe grün, während die Vorzählung falsch zählt.
    messwertformen = [
        {}, {"code": "8480-6", "datum": "2024-01-01"},
        {"code": "8462-4", "datum": "2024-01-01"},
        {"code": "8480-6", "datum": "2024-06-01"},
        {"code": "4548-4", "datum": "2024-01-01"},
    ]

    for lauf in range(500):
        patienten = []
        for _ in range(wuerfel.randint(0, 6)):
            if wuerfel.random() < 0.15:
                patienten.append(wuerfel.choice(muell))
                continue
            eintrag = _patient()
            for feld in ("begegnungen", "diagnosen", "messwerte", "medikamente"):
                wahl = wuerfel.random()
                if wahl < 0.2:
                    continue                        # Feld fehlt
                if wahl < 0.35:
                    eintrag[feld] = wuerfel.choice(muell)   # falscher Typ
                    continue
                if feld == "messwerte":
                    eintrag[feld] = [
                        dict(wuerfel.choice(messwertformen))
                        for _ in range(wuerfel.randint(0, 5))
                    ]
                else:
                    eintrag[feld] = [{}] * wuerfel.randint(0, 4)
            patienten.append(eintrag)
        parameter = {"patienten": patienten}

        gezaehlt = zaehle_ressourcen(parameter)
        gebaut = len(baue_aus_parametern(parameter, {}).ressourcen)
        assert gezaehlt == gebaut, f"Lauf {lauf}: {gezaehlt} gezählt, {gebaut} gebaut"


def test_die_vorzaehlung_kennt_die_ersatzbegegnung():
    """Der Fall, den eine naive Zählung übersieht: Eine Diagnose ohne
    Begegnung erzeugt eine — das verlangt `isik-con1` (ADR-009)."""
    ohne = {"patienten": [_patient(diagnosen=[{"code": "44054006"}])]}
    assert zaehle_ressourcen(ohne) == 3        # Patient + Ersatzbegegnung + Diagnose
    assert len(baue_aus_parametern(ohne, {}).ressourcen) == 3


def test_die_grenze_je_patient_greift_und_meldet_sich():
    bau = baue_aus_parametern({"patienten": [_patient(messwerte=_messwerte(20000))]}, {})
    assert len(bau.ressourcen) == GRENZE_JE_PATIENT

    grenze = [b for b in bau.beanstandungen if b.art == "mengengrenze_je_patient"]
    assert len(grenze) == 1, "genau eine Sammelmeldung, nicht eine je Vorfall"
    # Beide Zahlen gehören hinein: Ohne sie wäre es stilles Abschneiden
    # mit einem Hinweis daneben.
    assert "20001" in grenze[0].detail
    assert str(GRENZE_JE_PATIENT) in grenze[0].detail
    assert "19921" in grenze[0].detail


def test_der_legitime_fall_bleibt_unberuehrt():
    """Eine Quartalsmessreihe über zehn Jahre. Der nächstliegende echte
    Anwendungsfall unterhalb der Grenze — geht er kaputt, ist die Zahl
    falsch gewählt."""
    reihe = {"patienten": [
        _patient(diagnosen=[{"code": "44054006"}], messwerte=_messwerte(40))
    ]}
    bau = baue_aus_parametern(reihe, {})
    assert len(bau.ressourcen) == 43
    assert not any(b.art.startswith("mengengrenze") for b in bau.beanstandungen)


def test_kappen_zerreisst_die_referenzintegritaet_nicht():
    """Die naheliegende falsche Umsetzung wäre, nach dem Bau
    abzuschneiden. Dann bliebe eine Diagnose ohne ihren Patienten stehen —
    oder die Begegnung fiele weg, auf die `Condition.encounter` zeigt."""
    from synthfhir.domain.identity import assign_ids
    from synthfhir.domain.integrity import check_resources
    from synthfhir.validation import pruefe_alle

    formen = [
        _patient(diagnosen=[{"code": "44054006"}] * 200, messwerte=_messwerte(200)),
        _patient(begegnungen=[{"art": "AMB", "datum": "2023-01-01"}] * 200,
                 diagnosen=[{"code": "44054006"}] * 200),
        _patient(begegnungen=[{"art": "AMB", "datum": "2023-01-01"}],
                 messwerte=_messwerte(20000)),
    ]
    for form in formen:
        bau = baue_aus_parametern({"patienten": [form]}, {})
        assert len(bau.ressourcen) == GRENZE_JE_PATIENT
        res = assign_ids(bau.ressourcen).resources
        bericht = check_resources(res)
        assert bericht.ok, bericht.to_dict()
        assert bericht.broken_reference_count == 0
        assert not [p for p in pruefe_alle(res) if not p.valide]


def test_die_kappung_faelscht_die_mengenabweichung_nicht():
    """Gekappt wird NACH dem Sollvergleich.

    Andersherum meldete die Beanstandung „79 Messwerte geliefert, 200
    erwartet" — und behauptete damit etwas Falsches über das Modell:
    Geliefert hat es 200, gekappt hat der eigene Code. Die Mengentreue
    ist die Kennzahl aus Phase 0; sie darf nicht die eigene Grenze messen.
    """
    bau = baue_aus_parametern(
        {"patienten": [_patient(messwerte=_messwerte(200))]},
        {"patienten": 1, "messwerte_je_patient": 200},
    )
    abweichung = [b for b in bau.beanstandungen if b.art == "mengenabweichung"]
    assert abweichung == [], [b.detail for b in abweichung]


def test_die_kappung_veraendert_das_parameterobjekt_nicht():
    """Sonst trüge die Aufzeichnung die gekappte Liste, und die
    Wiedergabe meldete die Beanstandung nicht mehr — der Lauf sähe
    rückblickend sauber aus."""
    parameter = {"patienten": [_patient(messwerte=_messwerte(500))]}
    baue_aus_parametern(parameter, {})
    assert len(parameter["patienten"][0]["messwerte"]) == 500


def test_die_kappung_ist_deterministisch():
    """Ohne das wäre eine gekappte Kohorte nicht wiedergebbar."""
    parameter = {"patienten": [_patient(messwerte=_messwerte(500))]}
    erst = baue_aus_parametern(parameter, {}).ressourcen
    zweit = baue_aus_parametern(parameter, {}).ressourcen
    assert json.dumps(erst, sort_keys=True) == json.dumps(zweit, sort_keys=True)


def test_unbrauchbare_messwerte_stuerzen_nicht_ab():
    """Drei Werte, die den Bau oder das Ausliefern zum Absturz brachten.

    Eine Ganzzahl mit 400 Stellen ist ein `int` und kam durch die
    Typprüfung — `float()` warf darauf `OverflowError`. `Infinity` und
    `NaN` wurden gebaut, und erst Starlettes Renderer (`allow_nan=False`)
    scheiterte. Beides ergab HTTP 500.
    """
    for wert in (int("9" * 400), float("inf"), float("nan"), "keine Zahl"):
        bau = baue_aus_parametern(
            {"patienten": [_patient(
                messwerte=[{"code": "8867-4", "wert": wert, "datum": "2023-01-01"}]
            )]},
            {},
        )
        assert len(bau.ressourcen) == 2
        assert any(b.art == "ungueltiger_messwert" for b in bau.beanstandungen)
        # Muss sich strikt serialisieren lassen — NaN und Infinity sind
        # kein JSON, und der Renderer der API lehnt sie ab.
        json.dumps(bau.ressourcen, allow_nan=False)


def test_die_meldung_gibt_keinen_langen_aufruferwert_wieder():
    """Der Wert stammt vom Aufrufer. Bei 400 Stellen stünden sonst 400
    Stellen in der Beanstandung — und die wandert in Berichte."""
    bau = baue_aus_parametern(
        {"patienten": [_patient(
            messwerte=[{"code": "8867-4", "wert": int("9" * 400)}]
        )]},
        {},
    )
    meldung = next(b for b in bau.beanstandungen if b.art == "ungueltiger_messwert")
    assert len(meldung.detail) < 200, meldung.detail


# --- Blutdruck als Panel (ADR-014) -----------------------------------------


def _blutdruck(datum="2024-01-15", syst=130, diast=85):
    return [{"code": "8480-6", "wert": syst, "datum": datum},
            {"code": "8462-4", "wert": diast, "datum": datum}]


def test_blutdruck_wird_eine_observation_mit_zwei_komponenten():
    """Das Vitalparameter-Profil laesst nichts anderes zu.

    Gemessen gegen ISiKBlutdruckSystemischArteriell ergaben zwei getrennte
    Observations 12 Fehler, darunter:
      BPCode: magic LOINC code 85354-9 required, but not found
      Observation.component: mindestens erforderlich = 2
      Observation.value[x]: maximal erlaubt = 0, aber gefunden 1
    """
    from synthfhir.domain.codes import BLUTDRUCK_PANEL

    bau = baue_aus_parametern({"patienten": [_patient(messwerte=_blutdruck())]}, {})
    obs = [r for r in bau.ressourcen if r["resourceType"] == "Observation"]
    assert len(obs) == 1, "aus zwei Messwerten wird EINE Observation"

    panel = obs[0]
    assert panel["code"]["coding"][0]["code"] == BLUTDRUCK_PANEL
    assert "valueQuantity" not in panel, "das Profil erlaubt hier maximal null"
    codes = [k["code"]["coding"][0]["code"] for k in panel["component"]]
    assert codes == ["8480-6", "8462-4"]
    for k in panel["component"]:
        assert k["valueQuantity"]["code"] == "mm[Hg]"


def test_ein_einzelner_blutdruckwert_bleibt_eine_eigene_observation():
    """Ein Panel braucht beide Komponenten. Einen unpaarigen Wert zu
    verwerfen waere schlimmer als ihn stehenzulassen: Er ist als schlichte
    Observation weiterhin gueltiges FHIR, nur nicht profilkonform."""
    bau = baue_aus_parametern(
        {"patienten": [_patient(messwerte=[{"code": "8480-6", "wert": 130,
                                            "datum": "2024-01-15"}])]}, {}
    )
    obs = [r for r in bau.ressourcen if r["resourceType"] == "Observation"]
    assert len(obs) == 1
    assert obs[0]["code"]["coding"][0]["code"] == "8480-6"
    assert "valueQuantity" in obs[0]
    assert "component" not in obs[0]


def test_gepaart_wird_nur_am_selben_datum():
    """Die einzige Zuordnung, die aus den Parametern hervorgeht. Alles
    andere waere geraten."""
    mw = _blutdruck("2024-01-15") + [{"code": "8480-6", "wert": 140,
                                      "datum": "2024-06-01"}]
    bau = baue_aus_parametern({"patienten": [_patient(messwerte=mw)]}, {})
    obs = [r for r in bau.ressourcen if r["resourceType"] == "Observation"]
    codes = sorted(o["code"]["coding"][0]["code"] for o in obs)
    assert codes == ["8480-6", "85354-9"], codes


def test_die_paarung_ist_deterministisch():
    """Ohne das waere eine Kohorte mit Blutdruck nicht wiedergebbar."""
    p = {"patienten": [_patient(messwerte=_blutdruck("2024-01-15")
                                + _blutdruck("2024-03-01", 128, 82))]}
    erst = json.dumps(baue_aus_parametern(p, {}).ressourcen, sort_keys=True)
    zweit = json.dumps(baue_aus_parametern(p, {}).ressourcen, sort_keys=True)
    assert erst == zweit


def test_loinc_display_ist_die_amtliche_deutsche_bezeichnung():
    """Die deutschen ISiK-Profile pruefen `Coding.display` gegen LOINCs
    de-DE-Fassung. Nachgemessen ergab 'Body weight' bei ISiKKoerpergewicht
    genau einen Fehler, und der verschwand mit 'Koerpergewicht'.

    `display_de` bleibt daneben unsere Kurzform und steht in `text` —
    'HbA1c' ist keine LOINC-Bezeichnung.
    """
    from synthfhir.domain.codes import OBSERVATION_CODES

    bau = baue_aus_parametern(
        {"patienten": [_patient(messwerte=[{"code": "4548-4", "wert": 7.2}])]}, {}
    )
    obs = next(r for r in bau.ressourcen if r["resourceType"] == "Observation")
    spec = OBSERVATION_CODES["4548-4"]
    assert obs["code"]["coding"][0]["display"] == spec.display_loinc_de
    assert obs["code"]["text"] == spec.display_de
    assert spec.display_loinc_de != spec.display_de, "sonst prueft dieser Test nichts"


def test_jeder_messwertcode_hat_eine_amtliche_deutsche_bezeichnung():
    """Eine Luecke hier hiesse: stiller Rueckfall auf den englischen Text
    und ein Fehler im deutschen Profil."""
    from synthfhir.domain.codes import OBSERVATION_CODES

    ohne = [e.code for e in OBSERVATION_CODES.values() if not e.display_loinc_de]
    assert not ohne, f"ohne deutsche LOINC-Bezeichnung: {ohne}"


def test_die_referenzkohorte_traegt_das_blutdruckpanel():
    """Sie ist die Messgrundlage. Faellt das Panel aus ihr heraus, misst
    der ISiK-Bericht den Fall nicht mehr, um den es geht."""
    from synthfhir.referenzkohorte import baue

    res = baue()
    panels = [r for r in res
              if r["resourceType"] == "Observation" and r.get("component")]
    assert len(panels) == 1
    assert panels[0]["code"]["coding"][0]["code"] == "85354-9"
