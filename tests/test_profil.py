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
    OHNE_PROFIL,
    PROFILE,
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
    """Der wichtigste Patient der Kohorte — und der einzige, der scheitert.

    Die erste Sondierung hat isik-con1 übersehen, weil jeder Patient eine
    Begegnung hatte. Ein Messaufbau, der nur den Fall enthält, der ohnehin
    durchgeht, misst nichts.
    """
    ohne = [p for p in PARAMETER["patienten"] if not p.get("begegnungen")]
    assert len(ohne) == 1, "genau ein Patient ohne Begegnung, absichtlich"

    res = baue()
    diagnosen_ohne = [
        r for r in res if r["resourceType"] == "Condition" and "encounter" not in r
    ]
    assert diagnosen_ohne, "sonst greift isik-con1 nie"


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


def test_nicht_profilierte_typen_werden_ausgewiesen_nicht_verschwiegen(profilserver):
    """Observation und MedicationStatement kennt das Basismodul nicht. Sie
    stillschweigend zu überspringen liesse den Bericht vollständiger
    aussehen, als er ist."""
    b = pruefe_gegen_profile(baue(), profilserver)
    assert any("kein Profil" in h for h in b.hinweise)
    geprueft = {e.ressourcentyp for e in b.ergebnisse}
    assert geprueft == set(PROFILE)
    assert not geprueft & set(OHNE_PROFIL)


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
    assert s["geprueft"] == 10
    assert s["fehler"] > 0, "die Lücke ist real und soll sichtbar sein"
    assert s["ungeprueft"] > 0, "die SNOMED-Bindung ist ohne Terminologie offen"


def test_isik_con1_wird_gefunden(profilserver):
    """Der Befund, für den es die Referenzkohorte gibt."""
    b = pruefe_gegen_profile(baue(), profilserver)
    meldungen = " ".join(f.meldung for e in b.ergebnisse for f in e.fehler)
    assert "isik-con1" in meldungen


def test_bericht_ueberlebt_den_umweg_ueber_json(profilserver):
    b = pruefe_gegen_profile(baue(), profilserver)
    zurueck = json.loads(json.dumps(b.to_dict(), ensure_ascii=False))
    assert zurueck["summe"]["fehler"] == b.summe("fehler")


def test_falscher_server_bricht_sauber_ab():
    from synthfhir.profil import ProfilFehler

    with pytest.raises(ProfilFehler, match="antwortet nicht"):
        pruefe_gegen_profile(baue(), "http://localhost:1/fhir")
