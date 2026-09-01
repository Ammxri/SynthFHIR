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


@pytest.mark.parametrize(
    "klage",
    [
        "Unknown code system http://fhir.de/CodeSystem/bfarm/icd-10-gm",
        "HAPI-2646: Unable to expand ValueSet: cannot apply filters "
        "'[org.hl7.fhir.r5.model.ValueSet$ConceptSetFilterComponent@7c7f5b47]' "
        "because CodeSystem 'http://snomed.info/sct' is ignored/not-present",
        "The CodeSystem is unknown, so the code cannot be validated",
        "The terminology server is not able to check the code",
        "The code system is ignored/not-present",
    ],
)
def test_aufloesungsklage_ohne_namen_entschuldigt_nichts(klage):
    """Die Lücke, durch die sich doch jede Bindungsverletzung wegdeuten liess.

    Fand der Code zu einer Auflösungsklage keinen ValueSet-Namen, trug er
    einen Platzhalter `"*"` ein — und danach galt JEDER Befund des Laufs
    mit den Worten „value set" als ungeprüft, auch eine Verletzung gegen
    ein ValueSet, das der Server mühelos auflöst.

    Die sechs Einstufungstests daneben konnten das nicht sehen: Jede ihrer
    Meldungen enthält einen Namen in Anführungszeichen, der `else`-Zweig
    wurde also nie betreten. Von den fünf Wendungen, die `_NICHT_AUFLOESBAR`
    kennt, war keine einzige geprüft — obwohl `codes.py` „Unknown code
    system" für ICD-10-GM und ATC ausdrücklich als Normalfall dokumentiert.
    """
    b = bewerte([
        issue("error", klage),
        issue(
            "error",
            "The Coding provided ('weiblich') was not found in the value set "
            "'AdministrativeGender', and a code is required from this value set",
        ),
    ])
    assert b[0].ungeprueft, "die Klage selbst bleibt ungeprüft"
    assert not b[1].ungeprueft, (
        "eine Auflösungsklage ohne ValueSet-Namen hat eine fremde "
        "Bindungsverletzung entschuldigt"
    )


def test_warnungen_zaehlen_getrennt():
    """Vier Schweregrade, vier Spalten — und `information` ist keine
    Warnung.

    Dieser Test stand einmal auf `len(e.warnungen) == 2` und zählte den
    `information`-Befund mit. Das war nicht bloss eine Zahl im Test: Im
    veröffentlichten Beleg waren 4 der 19 ausgewiesenen Warnungen vom
    Schweregrad `information`, und die 19 steht so in ADR-009 §3a und in
    der Sondierung.
    """
    e = Profilergebnis("Patient", "pat-001", "x", bewerte([
        issue("error", "Wirklich falsch"),
        issue("warning", "dom-6: narrative fehlt"),
        issue("error", "Unable to expand ValueSet 'X'"),
        issue("information", "Hinweis"),
    ]))
    assert len(e.fehler) == 1
    assert len(e.ungeprueft) == 1
    assert len(e.warnungen) == 1
    assert len(e.informationen) == 1
    assert not e.konform


def test_kein_befund_faellt_aus_allen_spalten():
    """Die Aufteilung muss vollständig sein.

    `informationen` ist als Rest definiert und nicht als Aufzählung von
    `information` und `success`: Ein Schweregrad, den niemand
    vorhergesehen hat, soll auftauchen statt lautlos zu verschwinden.
    """
    e = Profilergebnis("Patient", "pat-001", "x", bewerte([
        issue("fatal", "Abbruch"),
        issue("error", "Falsch"),
        issue("warning", "Unüblich"),
        issue("information", "Hinweis"),
        issue("success", "Alles gut"),
        issue("voellig-neu", "Was auch immer"),
        issue("error", "Unable to expand ValueSet 'X'"),
    ]))
    gezaehlt = (
        len(e.fehler) + len(e.ungeprueft) + len(e.warnungen) + len(e.informationen)
    )
    assert gezaehlt == len(e.befunde) == 7


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
    assert s["geprueft"] == 11
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


# --- Was der Server antwortet, wenn er nicht validiert ---------------------
#
# Dieser Abschnitt hat gefehlt. Jeder Test, der `$validate` wirklich
# anfasst, braucht den `profilserver` und wird ohne Container
# übersprungen — der Zweig „Antwort ist kein OperationOutcome" wurde also
# von null laufenden Tests je berührt. Hier steht er ohne Container, mit
# einer Attrappe der Sitzung.


class _FalscheAntwort:
    def __init__(self, koerper, status=200):
        self._koerper = koerper
        self.status_code = status

    def json(self):
        return self._koerper


class _FalscheSitzung:
    """Nachbau von `requests.Session`, so weit die Messung sie benutzt."""

    def __init__(self, validate_antwort, status=200):
        self.headers: dict = {}
        self._validate = validate_antwort
        self._status = status

    def get(self, url, timeout=None):
        return _FalscheAntwort(
            {"resourceType": "CapabilityStatement", "fhirVersion": "4.0.1"}
        )

    def post(self, url, params=None, data=None, timeout=None):
        return _FalscheAntwort(self._validate, self._status)


def test_antwort_ohne_operationoutcome_ist_keine_messung(monkeypatch):
    """Ein makelloser Bericht über einen Lauf, in dem nichts validiert wurde.

    Zuvor stand hier ein stilles `else []`: Was kein OperationOutcome war,
    ergab null Befunde, und die Ressource galt als **geprüft**, fehlerfrei
    und konform. Der HTTP-Status wurde nie angesehen. Ein Gateway, das
    `/metadata` durchlässt und `$validate` mit 401 und einem JSON-Körper
    beantwortet, hätte damit 11 geprüfte Ressourcen und 0 Fehler gemeldet.
    """
    import synthfhir.profil as profil_modul
    from synthfhir.profil import ProfilFehler

    monkeypatch.setattr(
        profil_modul.requests,
        "Session",
        lambda: _FalscheSitzung({"error": "unauthorized"}, status=401),
    )
    with pytest.raises(ProfilFehler, match="ungültige Messung"):
        pruefe_gegen_profile(baue(), "http://beispiel.invalid/fhir")


def test_unbekanntes_profil_ist_keine_messung(monkeypatch):
    """Eine Messung gegen den falschen Server ist keine Aussage über die Daten.

    Der Server meldet das als gewöhnlichen `error`, ununterscheidbar von
    einem Datenfehler — nachgemessen gegen einen HAPI ohne die
    ISiK-Pakete: „Invalid profile. Failed to retrieve profile with url=…",
    ein Fehler je Ressource. Der Bericht hätte das als schlechte Daten
    ausgewiesen, obwohl gar nichts gegen ISiK geprüft wurde.

    Damit hängt die Zusage „gemessen gegen `de.gematik.isik-basismodul
    4.0.3`" nicht mehr allein an zwei Konstanten im Quelltext.
    """
    import synthfhir.profil as profil_modul
    from synthfhir.profil import ProfilFehler

    oo = {
        "resourceType": "OperationOutcome",
        "issue": [
            {
                "severity": "error",
                "diagnostics": (
                    "Invalid profile. Failed to retrieve profile with url="
                    "https://gematik.de/fhir/isik/StructureDefinition/ISiKPatient"
                ),
            }
        ],
    }
    monkeypatch.setattr(
        profil_modul.requests, "Session", lambda: _FalscheSitzung(oo)
    )
    with pytest.raises(ProfilFehler, match="kennt das Profil"):
        pruefe_gegen_profile(baue(), "http://beispiel.invalid/fhir")
