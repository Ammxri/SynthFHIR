"""Tests der Profilmessung.

Der Kern dieser Datei ist die **Einstufung**: Wann zählt ein Befund als
Fehler, wann als ungeprüft? Beide Richtungen sind gefährlich.

Zählt man ungeprüfte Befunde als Fehler, sieht das Ergebnis schlechter aus,
als es ist. Deutet man Fehler zu ungeprüft um, sieht es besser aus — und
das wäre Schönfärberei mit Zahlen, gegen die dieses Projekt seit ADR-001
antritt. Die Regel muss also scharf sein, und sie muss in beide Richtungen
prüfbar bleiben.
"""

from __future__ import annotations

import json

import pytest

from synthfhir.profil import (
    PROFILE,
    VITALPROFILE,
    profil_fuer,
    Profilergebnis,
    bewerte,
    pruefe_gegen_profile,
)
from synthfhir.referenzkohorte import PARAMETER, baue


def issue(schwere, text, ort="X"):
    return {"severity": schwere, "diagnostics": text, "expression": [ort]}


# --- Die Einstufung --------------------------------------------------------


def test_echter_fehler_bleibt_fehler():
    b = bewerte([issue("error", "Condition.recordedDate: minimum required = 1")])
    assert not b[0].ungeprueft


def test_nicht_aufloesbares_valueset_ist_ungeprueft():
    """Der Validator sagt selbst, dass er es nicht entscheiden kann."""
    b = bewerte([issue("error", "Unable to expand ValueSet: cannot apply filters")])
    assert b[0].ungeprueft


def test_nicht_gefunden_ist_ungeprueft_wenn_das_valueset_offen_war():
    """Die eigentliche Regel: Ein 'nicht im ValueSet' zählt nur dann als
    ungeprüft, wenn GENAU DIESES ValueSet in DIESEM Lauf nicht auflösbar
    war."""
    b = bewerte([
        issue("error", "Unable to expand ValueSet 'DiagnosesSCT' because CodeSystem"),
        issue("error", "The Coding provided was not found in the value set 'DiagnosesSCT'"),
    ])
    assert all(x.ungeprueft for x in b)


def test_nicht_gefunden_bleibt_fehler_ohne_aufloesungsklage():
    """Die Gegenrichtung, und die wichtigere: Ohne vorangegangene
    Auflösungsklage ist eine Bindungsverletzung ein Fehler. Sonst liesse
    sich jede wegdeuten."""
    b = bewerte([
        issue("error", "The Coding provided was not found in the value set 'Kontaktebene'")
    ])
    assert not b[0].ungeprueft, "sonst wäre jede Bindungsverletzung wegdeutbar"


def test_offenes_valueset_faerbt_nicht_auf_ein_anderes_ab():
    """Ein nicht auflösbares SNOMED-ValueSet darf eine Verletzung bei einem
    ANDEREN ValueSet nicht entschuldigen."""
    b = bewerte([
        issue("error", "Unable to expand ValueSet 'DiagnosesSCT'"),
        issue("error", "The Coding provided was not found in the value set 'Kontaktebene'"),
    ])
    assert b[0].ungeprueft
    assert not b[1].ungeprueft


def test_warnungen_zaehlen_getrennt():
    e = Profilergebnis("Patient", "pat-001", "x", bewerte([
        issue("error", "Wirklich falsch"),
        issue("warning", "dom-6: narrative fehlt"),
        issue("error", "Unable to expand ValueSet 'X'"),
        issue("information", "Hinweis"),
    ]))
    assert len(e.fehler) == 1
    assert len(e.ungeprueft) == 1
    assert len(e.warnungen) == 2
    assert not e.konform


def test_konform_heisst_kein_fehler_nicht_nachgewiesen():
    """`konform` sagt: kein Fehler. Es sagt NICHT: nachgewiesen konform —
    solange etwas ungeprüft ist, ist das Urteil unvollständig."""
    e = Profilergebnis("Condition", "cond-001", "x", bewerte([
        issue("error", "Unable to expand ValueSet 'DiagnosesSCT'"),
    ]))
    assert e.konform
    assert e.ungeprueft, "und genau deshalb weist der Bericht beides aus"


# --- Die Referenzkohorte ---------------------------------------------------


def test_referenzkohorte_ist_ohne_modell_und_stabil():
    """Ein Messbericht taugt nur zum Vergleich, wenn sich zwischen zwei
    Läufen ausschließlich das ändert, was gemessen werden soll."""
    erst = json.dumps(baue(), sort_keys=True, ensure_ascii=False)
    zweit = json.dumps(baue(), sort_keys=True, ensure_ascii=False)
    assert erst == zweit


def test_referenzkohorte_enthaelt_den_fall_ohne_begegnung():
    """Der Patient, für den es diese Kohorte gibt.

    In den **Parametern** liefert er keine Begegnung — das war der Fall,
    den die erste Sondierung übersah und an dem `isik-con1` scheiterte.
    Seit ADR-009 ergänzt der Code den Kontakt, und derselbe Patient belegt
    nun die Zusage statt der Lücke.

    Er bleibt deshalb in der Kohorte. Ihn zu entfernen, weil er jetzt
    durchgeht, hiesse die Messung genau um den Fall zu erleichtern, der sie
    einmal gerettet hat.
    """
    ohne = [p for p in PARAMETER["patienten"] if not p.get("begegnungen")]
    assert len(ohne) == 1, "genau ein Patient ohne Begegnung in den Parametern"

    res = baue()
    diagnosen_ohne = [
        r for r in res if r["resourceType"] == "Condition" and "encounter" not in r
    ]
    assert not diagnosen_ohne, "jede kodierte Diagnose nennt ihren Kontakt"


def test_referenzkohorte_deckt_mehrere_ressourcen_je_typ_ab():
    mehrfach = [p for p in PARAMETER["patienten"] if len(p.get("begegnungen", [])) > 1]
    assert mehrfach, "sonst bleibt die Kennungsvergabe ungetestet"


def test_referenzkohorte_traegt_deutsche_sonderzeichen():
    """Umlaute und Ligaturen gehören in eine Referenzkohorte eines Produkts,
    das deutsche Lokalisierung verspricht."""
    namen = " ".join(
        f"{p['vorname']} {p['nachname']}" for p in PARAMETER["patienten"]
    )
    assert any(c in namen for c in "äöüßÄÖÜşğ")


# --- Der Bericht -----------------------------------------------------------


def test_unprofilierte_ressourcen_werden_ausgewiesen_nicht_verschwiegen(profilserver):
    """Seit ADR-014 ist das je RESSOURCE zu zählen, nicht je Typ.

    Ein Observation-Satz kann zur Hälfte profiliert sein (Vitalparameter)
    und zur Hälfte nicht (Laborwerte). Die alte Meldung „für Observation
    gibt es kein Profil" wäre schlicht falsch geworden — und hätte den
    Bericht vollständiger aussehen lassen, als er ist.
    """
    res = baue()
    b = pruefe_gegen_profile(res, profilserver)
    assert any("ohne Profil" in h for h in b.hinweise)

    erwartet = sum(1 for r in res if profil_fuer(r) is not None)
    assert len(b.ergebnisse) == erwartet
    # Und die Gegenprobe: Es gibt tatsächlich beide Sorten Observation.
    obs = [r for r in res if r["resourceType"] == "Observation"]
    assert any(profil_fuer(r) for r in obs), "kein profilierter Vitalparameter"
    assert any(profil_fuer(r) is None for r in obs), "kein unprofilierter Laborwert"


def test_das_blutdruckpanel_bekommt_sein_vitalparameterprofil(profilserver):
    """Ohne die Zuordnung je Ressource fiele es unter „Observation" und
    bliebe ungeprüft."""
    res = baue()
    panel = next(r for r in res
                 if r["resourceType"] == "Observation" and r.get("component"))
    assert profil_fuer(panel) == VITALPROFILE["85354-9"]


def test_bericht_nennt_paket_und_terminologiestand(profilserver):
    """Ohne diese Angaben ist eine Messung nicht wiederholbar."""
    b = pruefe_gegen_profile(baue(), profilserver)
    d = b.to_dict()
    assert d["paket"] == "de.gematik.isik-basismodul"
    assert d["paketversion"]
    assert d["terminologieserver"] == "keiner"
    assert d["fhir_version"] == "4.0.1"
    assert d["erzeugt"].endswith("Z")


def test_bericht_zaehlt_drei_spalten_getrennt(profilserver):
    b = pruefe_gegen_profile(baue(), profilserver)
    s = b.to_dict()["summe"]
    # 14 statt 11 seit ADR-014: Das Blutdruckpanel und die beiden
    # MedicationStatements sind jetzt profiliert.
    assert s["geprueft"] == 14
    assert s["ungeprueft"] > 0, "die SNOMED-Bindung ist ohne Terminologie offen"


def test_keine_fehler_mehr(profilserver):
    """Die Zusage aus ADR-009, gemessen statt behauptet.

    25 Fehler waren es bei der Sondierung. Dass hier null steht, heisst
    **nicht** „ISiK-konform": Acht Befunde bleiben ungeprüft, weil ohne
    Terminologieserver niemand sagen kann, ob die SNOMED-Codes im
    geforderten ValueSet liegen. Genau dafür gibt es die dritte Spalte.
    """
    b = pruefe_gegen_profile(baue(), profilserver)
    fehler = [(e.ressourcentyp, f.meldung) for e in b.ergebnisse for f in e.fehler]
    assert fehler == [], fehler


def test_isik_con1_greift_nicht_mehr(profilserver):
    """Der Befund, der die Kohorte einmal gerettet hat — jetzt als
    Regressionsschutz."""
    b = pruefe_gegen_profile(baue(), profilserver)
    alle = " ".join(
        f.meldung for e in b.ergebnisse for f in e.fehler + e.ungeprueft
    )
    assert "isik-con1" not in alle


def test_bericht_ueberlebt_den_umweg_ueber_json(profilserver):
    b = pruefe_gegen_profile(baue(), profilserver)
    zurueck = json.loads(json.dumps(b.to_dict(), ensure_ascii=False))
    assert zurueck["summe"]["fehler"] == b.summe("fehler")


def test_falscher_server_bricht_sauber_ab():
    from synthfhir.profil import ProfilFehler

    with pytest.raises(ProfilFehler, match="antwortet nicht"):
        pruefe_gegen_profile(baue(), "http://localhost:1/fhir")


def test_der_bericht_nennt_alle_geladenen_module(profilserver):
    """Seit ADR-014 tragen drei Module Profile bei.

    Der Kopf „gemessen gegen das Basismodul" waere eine unzutreffende
    Angabe ueber den eigenen Messaufbau — und genau die Sorte Angabe, die
    einen Bericht wertlos macht. Der Test zaehlt gegen MODULE, nicht gegen
    eine Liste hier, damit ein viertes Modul nicht stillschweigend
    danebensteht.
    """
    from synthfhir.profil import MODULE

    d = pruefe_gegen_profile(baue(), profilserver).to_dict()
    assert d["module"] == MODULE
    assert len(d["module"]) >= 3


def test_jedes_profil_der_zuordnung_wird_auch_benutzt():
    """Ein Eintrag in VITALPROFILE, den keine Ressource je trifft, waere
    toter Code — und er liesse den Bericht breiter aussehen, als er misst.

    Rot, sobald ein Profil eingetragen wird, fuer das der Katalog keinen
    Code fuehrt.
    """
    from synthfhir.domain.codes import BLUTDRUCK_PANEL, OBSERVATION_CODES

    bekannt = set(OBSERVATION_CODES) | {BLUTDRUCK_PANEL}
    unbenutzbar = [c for c in VITALPROFILE if c not in bekannt]
    assert not unbenutzbar, f"Profil ohne passenden Katalogcode: {unbenutzbar}"


# --- Was der Katalog anbietet und ISiK nicht annimmt -----------------------


# Gemessen am 2026-09-01 gegen `EncounterClassDE` (de.basisprofil.r4 1.5.3),
# an das ISiK `Encounter.class` bindet. Die Liste enthaelt genau sechs
# Codes: AMB, HH, SS, VR, IMP, PRENC.
#
# Unser Katalog fuehrt vier, davon drei aus dieser Liste. EMER steht NICHT
# darin — obwohl es ein gueltiger v3-ActCode ist und unsere Daten damit
# gueltiges FHIR bleiben. Das ist eine offene Katalogfrage (ADR-016) und
# keine Eigenschaft, die dieser Test gutheisst.
ISIK_KONTAKTARTEN = {"AMB", "IMP", "VR"}
NICHT_IN_ENCOUNTERCLASSDE = {"EMER"}


def _encounter_mit(art: str) -> list[dict]:
    from synthfhir.generation import Ergebnis, baue_und_pruefe

    e = baue_und_pruefe({"patienten": [{
        "vorname": "A", "nachname": "B", "geschlecht": "male",
        "geburtsdatum": "1980-01-01",
        "begegnungen": [{"art": art, "datum": "2024-01-01"}],
        "diagnosen": [{"code": "44054006", "beginn": "2020-01-01"}]}]},
        Ergebnis(beschreibung="x"))
    return [r for r in e.ressourcen if r["resourceType"] == "Encounter"]


def test_der_katalog_der_kontaktarten_ist_vollstaendig_vermessen(profilserver):
    """Keine Kontaktart darf unvermessen bleiben.

    Ohne diesen Test wuchs der Katalog, und ob eine neue Art ISiK genuegt,
    stellte sich erst beim Nutzer heraus. Genau so blieb EMER unbemerkt:
    Die feste Testkohorte benutzt es nicht.
    """
    from synthfhir.domain.codes import ENCOUNTER_CLASSES

    assert set(ENCOUNTER_CLASSES) == ISIK_KONTAKTARTEN | NICHT_IN_ENCOUNTERCLASSDE


@pytest.mark.parametrize("art", sorted(ISIK_KONTAKTARTEN))
def test_diese_kontaktarten_genuegen_isik(art, profilserver):
    b = pruefe_gegen_profile(_encounter_mit(art), profilserver)
    fehler = [f.meldung for e in b.ergebnisse for f in e.fehler]
    assert fehler == [], fehler


@pytest.mark.parametrize("art", sorted(NICHT_IN_ENCOUNTERCLASSDE))
def test_diese_kontaktart_genuegt_isik_nicht(art, profilserver):
    """Ein Test, der einen BEFUND festhaelt, kein Sollverhalten.

    Er steht hier, damit zwei Dinge auffallen: dass der Befund noch gilt
    (dann bleibt er gruen) und dass er behoben ist (dann wird er rot und
    gehoert geloescht). Ohne ihn verschwaende die Messung.
    """
    b = pruefe_gegen_profile(_encounter_mit(art), profilserver)
    fehler = " ".join(f.meldung for e in b.ergebnisse for f in e.fehler)
    assert "EncounterClassDE" in fehler, (
        f"{art} genuegt ISiK jetzt — Befund behoben, diesen Test loeschen."
    )


def test_kein_szenario_liefert_einen_profilfehler(profilserver):
    """Eine kuratierte Vorlage mit bekanntem Profilfehler waere ein
    Pflegefehler. Gefunden genau so: `mehrere-kontakte` benutzte EMER."""
    from synthfhir.szenarien import alle, baue

    for s in alle():
        b = pruefe_gegen_profile(baue(s).ressourcen, profilserver)
        fehler = [(s.name, e.ressourcentyp, f.meldung)
                  for e in b.ergebnisse for f in e.fehler]
        assert fehler == [], fehler
