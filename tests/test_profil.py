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

from synthfhir.domain.codes import ENCOUNTER_CLASSES
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


def test_summe_und_je_typ_fuehren_dieselben_spalten():
    """Eine Spalte, die nur an einer Stelle auftaucht, fällt beim Lesen des
    Berichts stillschweigend unter den Tisch.

    Genau so fehlte `informationen` zuerst in der Summe, während `je_typ`
    sie schon führte — der Bericht hätte 15 Warnungen ausgewiesen und die
    4 Hinweise nur in der Aufschlüsselung gehabt.
    """
    from synthfhir.profil import Profilbericht

    b = Profilbericht(
        erzeugt="2026-01-01T00:00:00Z",
        server="x",
        fhir_version="4.0.1",
        paket="p",
        paketversion="1",
        terminologieserver="keiner",
        ergebnisse=[
            Profilergebnis("Patient", "pat-001", "x", bewerte([
                issue("error", "Falsch"),
                issue("warning", "Unüblich"),
                issue("information", "Hinweis"),
                issue("error", "Unable to expand ValueSet 'X'"),
            ])),
            Profilergebnis("Condition", "cond-001", "y", bewerte([
                issue("warning", "Unüblich"),
            ])),
        ],
    )
    d = b.to_dict()
    spalten = set(d["summe"]) - {"geprueft"}
    for typ, z in d["je_typ"].items():
        fehlend = spalten - set(z)
        assert not fehlend, f"{typ} führt {fehlend} nicht"
    for spalte in spalten:
        assert d["summe"][spalte] == sum(z[spalte] for z in d["je_typ"].values()), (
            f"Summe und Aufschlüsselung sind sich über '{spalte}' nicht einig"
        )


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
    Regressionsschutz.

    Dieser Test allein sagt wenig: Er prüft eine **Abwesenheit**, und eine
    Abwesenheit stellt sich auch ein, wenn gar nicht mehr richtig geprüft
    wird. Er bliebe grün, wenn der Validator den Verstoss überhaupt nicht
    mehr fände. Seine Aussage bekommt er erst durch den Test darunter.
    """
    b = pruefe_gegen_profile(baue(), profilserver)
    alle = " ".join(
        f.meldung for e in b.ergebnisse for f in e.fehler + e.ungeprueft
    )
    assert "isik-con1" not in alle


def test_isik_con1_wird_ueberhaupt_noch_gefunden(profilserver):
    """Die Negativkontrolle. Sie hat gefehlt.

    Seit ADR-009 ergänzt der Bauweg für jeden Patienten mit Diagnose
    selbsttätig einen Kontakt (`templates.py`). Das ist richtig so — es war
    der Fix. Die Folge ist aber, dass der Messaufbau **keine**
    Konstellation mehr enthält, aus der `isik-con1` entstehen könnte: Der
    dritte Patient der Referenzkohorte liefert in den Parametern keine
    Begegnung, bekommt aber eine.

    Damit misst der Aufbau nur noch Fälle, die ohnehin durchgehen — genau
    das, wovor `docs/sondierung-isik.md` warnt. Ein Ausbleiben des Befundes
    belegt dann nichts, solange niemand zeigt, dass der Befund überhaupt
    noch auftreten **kann**.

    Dieser Test zeigt es. Er nimmt eine gebaute Diagnose, entfernt genau
    ein Feld und prüft dieselbe Ressource noch einmal. Der Unterschied ist
    das Feld, sonst nichts.
    """
    res = baue()
    diagnose = next(r for r in res if r["resourceType"] == "Condition")
    assert "encounter" in diagnose, (
        "der Bauweg setzt den Kontakt nicht mehr — dann prüft dieser Test "
        "nicht das, wofür er da ist"
    )

    ohne_kontakt = {k: v for k, v in diagnose.items() if k != "encounter"}
    b = pruefe_gegen_profile([ohne_kontakt], profilserver)
    e = b.ergebnisse[0]

    meldungen = " ".join(f.meldung for f in e.fehler)
    assert "isik-con1" in meldungen, (
        "der Validator meldet den Verstoss nicht mehr. Dann sagt auch sein "
        "Ausbleiben in test_isik_con1_greift_nicht_mehr nichts aus — und "
        "die ganze Profilmessung belegt weniger, als sie zu belegen scheint"
    )
    assert not e.konform

    # Die Gegenprobe zur Gegenprobe: dieselbe Ressource, nur mit dem Feld.
    # Ohne sie könnte der Befund auch an etwas anderem hängen.
    mit = pruefe_gegen_profile([diagnose], profilserver).ergebnisse[0]
    assert mit.konform, "dann liegt der Fehler nicht am fehlenden Kontakt"


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


# --- Die Kontaktarten gegen ISiK -------------------------------------------
#
# Hier stand bis zum 2026-09-01 ein Befundtest: EMER genuege ISiK nicht.
# Er war so gebaut, dass er ROT wird, sobald der Befund behoben ist - und
# genau das ist beim Umbau passiert. Er hat seine Aufgabe getan und ist
# durch die Tests unten ersetzt (ADR-018).


def _encounter_mit(art: str) -> list[dict]:
    from synthfhir.generation import Ergebnis, baue_und_pruefe

    e = baue_und_pruefe({"patienten": [{
        "vorname": "A", "nachname": "B", "geschlecht": "male",
        "geburtsdatum": "1980-01-01",
        "begegnungen": [{"art": art, "datum": "2024-01-01"}],
        "diagnosen": [{"code": "44054006", "beginn": "2020-01-01"}]}]},
        Ergebnis(beschreibung="x"))
    return [r for r in e.ressourcen if r["resourceType"] == "Encounter"]


def _encounterclass_de(server: str) -> set[str]:
    """Die erlaubten Codes, GEHOLT statt abgeschrieben.

    Eine Liste im Test waere eine zweite Handaufzaehlung neben der im
    Katalog - und die zweite veraltet immer zuerst. Aendert
    de.basisprofil.r4 das ValueSet, soll dieser Test das merken, nicht
    dieselbe alte Annahme bestaetigen.
    """
    import requests

    s = requests.Session()
    s.trust_env = False
    a = s.get(f"{server}/ValueSet/$expand",
              params={"url": "http://fhir.de/ValueSet/EncounterClassDE",
                      "count": 200},
              headers={"Accept": "application/fhir+json"}, timeout=120)
    d = a.json()
    assert d.get("resourceType") == "ValueSet", d
    return {c["code"] for c in d.get("expansion", {}).get("contains", [])}


# Gemessen am 2026-09-01 aus dem Paket de.basisprofil.r4 (identisch in
# 1.5.3, 1.5.4 und 1.6.0). Festgeschrieben, weil der Servertest darunter
# OHNE Profilserver uebersprungen wird - und ohne Server ist auf diesem
# Rechner der Normalfall, und in der CI laeuft er nie.
#
# Eine festgeschriebene Liste ist sonst genau das, wovor dieses Projekt
# sich huetet. Sie ist hier vertretbar, weil der Servertest darunter sie
# gegen die Quelle haelt, sobald ein Server da ist: Die Liste kann nicht
# still veralten, sie kann nur unbemerkt RICHTIG bleiben.
ENCOUNTERCLASSDE = {"AMB", "HH", "SS", "VR", "IMP", "PRENC"}


def test_jeder_katalogcode_liegt_in_encounterclassde_auch_ohne_server():
    """Die Wache, die IMMER laeuft.

    `test_jeder_katalogcode_liegt_in_encounterclassde` misst gegen den
    Server und ist damit genau dann still, wenn keiner da ist. Gemessen:
    Ohne Profilserver kam ein Katalogeintrag mit `code = "FLD"` - ein Code,
    den EncounterClassDE bewusst auslaesst - durch die ganze Testreihe.

    `test_begegnungsarten_stammen_aus_dem_valueset` faengt das nicht: Es
    prueft gegen `v3-ActEncounterCode`, und dort sind FLD und EMER
    enthalten. Die ISiK-Bindung ist enger als der Standard.
    """
    from synthfhir.domain.codes import ENCOUNTER_CLASSES

    fremd = {e.schluessel: e.code for e in ENCOUNTER_CLASSES.values()
             if e.code not in ENCOUNTERCLASSDE}
    assert not fremd, f"{fremd} nicht in EncounterClassDE"


def test_die_festgeschriebene_liste_stimmt_noch(profilserver):
    """Die Gegenprobe zur Festschreibung: Sobald ein Server da ist, muss
    die Liste oben genau seiner Expansion entsprechen. Ohne diesen Test
    waere sie eine Behauptung."""
    assert _encounterclass_de(profilserver) == ENCOUNTERCLASSDE


def test_jeder_katalogcode_liegt_in_encounterclassde(profilserver):
    """Der Test, der EMER haette verhindern muessen.

    Die Bindung von `Encounter.class` ist **required**. Ein Katalogeintrag
    mit einem Code ausserhalb erzeugt Daten, die niemals ISiK-konform sein
    koennen - und die Laufzeitpruefung sieht das nicht.
    """
    from synthfhir.domain.codes import ENCOUNTER_CLASSES

    erlaubt = _encounterclass_de(profilserver)
    assert erlaubt, "leere Expansion - dann prueft dieser Test nichts"
    fremd = {e.schluessel: e.code for e in ENCOUNTER_CLASSES.values()
             if e.code not in erlaubt}
    assert not fremd, f"{fremd} nicht in EncounterClassDE ({sorted(erlaubt)})"


def test_emer_ist_kein_class_code_mehr(profilserver):
    """Die Gegenprobe: EMER liegt weiterhin NICHT im ValueSet.

    Ohne sie koennte der Test darueber gruen sein, weil das ValueSet
    inzwischen alles enthaelt - und dann bewiese er nichts.
    """
    assert "EMER" not in _encounterclass_de(profilserver)


# Aus dem Katalog, nicht von Hand: Eine Liste hier waere eine zweite
# Aufzaehlung neben ENCOUNTER_CLASSES, und ein fuenfter Eintrag fiele an
# der einzigen profilkritischen Stelle lautlos hinten runter.
@pytest.mark.parametrize("art", sorted(ENCOUNTER_CLASSES))
def test_jede_kontaktart_genuegt_isik(art, profilserver):
    b = pruefe_gegen_profile(_encounter_mit(art), profilserver)
    fehler = [f.meldung for e in b.ergebnisse for f in e.fehler]
    assert fehler == [], fehler


def test_der_notfall_steht_im_aufnahmeanlass(profilserver):
    """Was aus EMER wird, und dass es nicht verschwindet.

    `class` sagt WIE der Kontakt stattfand, `admitSource` WARUM er
    zustande kam. Ohne diesen Test koennte der Notfall stillschweigend zu
    einer gewoehnlichen stationaeren Aufnahme werden - gueltiges FHIR mit
    falschem Inhalt, die schlimmste Sorte Fehler in diesem Projekt.
    """
    from synthfhir.domain.codes import AUFNAHMEANLASS_SYSTEM

    enc = _encounter_mit("EMER")[0]
    assert enc["class"]["code"] == "IMP"
    kodierung = enc["hospitalization"]["admitSource"]["coding"][0]
    assert kodierung["system"] == AUFNAHMEANLASS_SYSTEM
    assert kodierung["code"] == "N"

    b = pruefe_gegen_profile([enc], profilserver)
    assert [f.meldung for e in b.ergebnisse for f in e.fehler] == []


def test_nur_der_notfall_traegt_einen_aufnahmeanlass():
    """Ein `hospitalization` an jedem Kontakt waere gueltiges FHIR und
    trotzdem Unsinn - eine Videosprechstunde hat keinen Aufnahmeanlass."""
    for art in ("AMB", "IMP", "VR"):
        assert "hospitalization" not in _encounter_mit(art)[0], art
    assert "hospitalization" in _encounter_mit("EMER")[0]


def test_der_aufnahmeanlass_ist_ein_echter_code(profilserver):
    """Gegen den Server, nicht gegen eine Annahme. Der Katalog ist
    sicherheitskritisch: Ein erfundener Code erzeugt unbemerkt inhaltlich
    falsche Testdaten, und die Laufzeitpruefung sieht Codes nicht.
    """
    import requests

    from synthfhir.domain.codes import ENCOUNTER_CLASSES

    s = requests.Session()
    s.trust_env = False
    a = s.get(f"{profilserver}/ValueSet/$expand",
              params={"url": "http://fhir.de/ValueSet/dgkev/Aufnahmeanlass",
                      "count": 100},
              headers={"Accept": "application/fhir+json"}, timeout=120)
    d = a.json()
    assert d.get("resourceType") == "ValueSet", d
    vorhanden = {c["code"]: c.get("display", "")
                 for c in d.get("expansion", {}).get("contains", [])}

    for e in ENCOUNTER_CLASSES.values():
        if not e.aufnahmeanlass:
            continue
        assert e.aufnahmeanlass in vorhanden, (
            f"{e.schluessel}: Aufnahmeanlass {e.aufnahmeanlass!r} gibt es nicht"
        )
        # Auch die Bezeichnung, nicht nur der Code: Ein richtiger Code mit
        # falschem Text ist genau die Sorte Fehler, die niemand bemerkt.
        assert e.aufnahmeanlass_display == vorhanden[e.aufnahmeanlass]


def test_kein_szenario_liefert_einen_profilfehler(profilserver):
    """Eine kuratierte Vorlage mit bekanntem Profilfehler waere ein
    Pflegefehler. Gefunden genau so: `mehrere-kontakte` benutzte EMER."""
    from synthfhir.szenarien import alle, baue

    for s in alle():
        b = pruefe_gegen_profile(baue(s).ressourcen, profilserver)
        fehler = [(s.name, e.ressourcentyp, f.meldung)
                  for e in b.ergebnisse for f in e.fehler]
        assert fehler == [], fehler
