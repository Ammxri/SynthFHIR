"""Tests der Aufzeichnung und Wiedergabe.

Der gefährlichste Fehler wäre eine Wiedergabe, die *fast* dasselbe liefert
und Erfolg meldet. Genau daran scheiterte Variante A in Phase 0. Die Tests
hier prüfen deshalb weniger, dass die Wiedergabe funktioniert, als dass sie
**merkt**, wenn sie es nicht tut.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from synthfhir import aufzeichnung as aufz
from synthfhir.domain.codes import CONDITION_CODES
from synthfhir.kohorte import TeilParameter, generiere_kohorte
from tests.test_kohorte import TeilClient


@pytest.fixture(autouse=True)
def keine_wartezeit(monkeypatch):
    """Ohne das schlafen die Ausfall-Tests hier echte 15 Sekunden je
    Wiederholung — gemessen: 61 s für diese Datei."""
    monkeypatch.setattr("synthfhir.kohorte._warte", lambda _: None)


@pytest.fixture
def lauf():
    """Ein gelaufenes Ergebnis über zwei Teile — Aufzeichnungen müssen
    Teilkohorten nach ADR-004 tragen, nicht nur Einzelaufrufe."""
    return generiere_kohorte(TeilClient(), "30 Diabetikerinnen", 30, teilgroesse=15)


@pytest.fixture
def gespeichert(lauf, tmp_path):
    a = aufz.aus_ergebnis(lauf, modell="testmodell")
    return aufz.schreibe(a, tmp_path / "lauf.aufz.json")


# --- Der Kern: gibt die Wiedergabe wirklich dasselbe? ----------------------


def test_wiedergabe_liefert_dasselbe_bundle(lauf, gespeichert):
    """Die eine Zusage dieses Moduls."""
    w = aufz.gib_wieder(aufz.lies(gespeichert))
    assert w.identisch
    assert w.ergebnis.bundle == lauf.bundle


def test_wiedergabe_braucht_kein_modell(gespeichert):
    """Kein Netz, kein Kontingent — das ist der halbe Zweck."""
    w = aufz.gib_wieder(aufz.lies(gespeichert))
    assert w.ergebnis.llm_antworten == []
    assert w.ergebnis.ausgabe_token == 0


def test_wiedergabe_haelt_die_kennungen(lauf, gespeichert):
    """Über die Teilgrenze hinweg — sonst wäre die Wiedergabe eine andere
    Kohorte mit denselben Personen."""
    w = aufz.gib_wieder(aufz.lies(gespeichert))
    alt = [r["id"] for r in lauf.ressourcen]
    neu = [r["id"] for r in w.ergebnis.ressourcen]
    assert neu == alt
    assert neu[0] == "pat-001"


def test_wiedergabe_ist_beliebig_oft_gleich(gespeichert):
    a = aufz.lies(gespeichert)
    summen = {aufz.gib_wieder(a).erhalten for _ in range(5)}
    assert len(summen) == 1


def test_wiedergabe_traegt_die_teilstruktur(lauf, gespeichert):
    a = aufz.lies(gespeichert)
    assert len(a.teile) == 2
    assert [t.angefragt for t in a.teile] == [15, 15]
    assert aufz.gib_wieder(a).ergebnis.patienten == lauf.patienten


def test_nicht_abbildbares_ueberlebt(gespeichert):
    """Was das Modell als nicht abbildbar gemeldet hat, gehört zum
    Ergebnis — eine Wiedergabe ohne diesen Hinweis wäre unvollständig."""
    w = aufz.gib_wieder(aufz.lies(gespeichert))
    assert isinstance(w.ergebnis.nicht_abbildbar, list)


# --- Der Selbsttest: merkt die Wiedergabe eine Abweichung? -----------------


def test_geaenderter_katalog_wird_als_abweichung_gemeldet(gespeichert):
    """Der eigentliche Grund für die Prüfsumme.

    Wird ein ICD-Schlüssel korrigiert — und das ist bei diesem Projekt
    schon vorgekommen —, liefert dieselbe Aufzeichnung ein anderes Bundle.
    Ohne den Vergleich fiele das niemandem auf.
    """
    a = aufz.lies(gespeichert)
    benutzt = sorted({d["code"] for t in a.teile
                      for p in t.parameter["patienten"]
                      for d in p.get("diagnosen", [])})
    schluessel = benutzt[0]
    alt = CONDITION_CODES[schluessel]
    try:
        CONDITION_CODES[schluessel] = replace(alt, icd10gm="Z99.9")
        w = aufz.gib_wieder(a)
    finally:
        CONDITION_CODES[schluessel] = alt

    assert not w.identisch
    assert w.katalog_geaendert
    assert "ABWEICHUNG" in w.befund()
    assert "Katalog hat sich geändert" in w.befund()


def test_abweichung_liefert_das_ergebnis_trotzdem(gespeichert):
    """Eine Abweichung ist ein Befund, kein Abbruch. Was entsteht, ist
    weiterhin gültiges FHIR — es ist nur nicht dasselbe."""
    a = aufz.lies(gespeichert)
    schluessel = next(iter(a.teile[0].parameter["patienten"][0]["diagnosen"]))["code"]
    alt = CONDITION_CODES[schluessel]
    try:
        CONDITION_CODES[schluessel] = replace(alt, display_de="Anders benannt")
        w = aufz.gib_wieder(a)
    finally:
        CONDITION_CODES[schluessel] = alt

    assert not w.identisch
    assert w.ergebnis.fertig, "gültig bleibt es"
    assert w.ergebnis.patienten == 30


def test_katalogaenderung_ohne_wirkung_wird_benannt_aber_nicht_als_fehler(gespeichert):
    """Ändert sich der Katalog an einer Stelle, die diese Kohorte nicht
    benutzt, ist das Bundle identisch — erwähnenswert bleibt es."""
    a = aufz.lies(gespeichert)
    benutzt = {d["code"] for t in a.teile for p in t.parameter["patienten"]
               for d in p.get("diagnosen", [])}
    unbenutzt = next(k for k in CONDITION_CODES if k not in benutzt)
    alt = CONDITION_CODES[unbenutzt]
    try:
        CONDITION_CODES[unbenutzt] = replace(alt, display_de="Egal")
        w = aufz.gib_wieder(a)
    finally:
        CONDITION_CODES[unbenutzt] = alt

    assert w.identisch
    assert w.katalog_geaendert
    assert "Katalog hat sich allerdings geändert" in w.befund()


def test_aufzeichnung_ohne_pruefsumme_sagt_das(lauf):
    """Schweigen wäre hier das Schlimmste: Der Nutzer hielte eine
    ungeprüfte Wiedergabe für eine geprüfte."""
    ohne = aufz.Aufzeichnung(beschreibung="x", angefragt=30,
                             teile=list(lauf.parameter))
    w = aufz.gib_wieder(ohne)
    assert not w.identisch
    assert "keine Prüfsumme" in w.befund()


# --- Das Dateiformat -------------------------------------------------------


def test_datei_enthaelt_die_parameter_nicht_das_bundle(lauf, gespeichert):
    """Die Aufzeichnung ist der Beitrag des Modells, nicht das Ergebnis."""
    d = json.loads(gespeichert.read_text(encoding="utf-8"))
    assert "teile" in d and "bundle" not in d
    assert d["teile"][0]["parameter"]["patienten"]
    roh = gespeichert.read_text(encoding="utf-8")
    assert "resourceType" not in roh


def test_datei_ist_deutlich_kleiner_als_das_bundle(lauf, gespeichert):
    bundle = json.dumps(lauf.bundle, ensure_ascii=False)
    assert gespeichert.stat().st_size < len(bundle.encode("utf-8"))


def test_datei_nennt_die_daten_als_testdaten(gespeichert):
    d = json.loads(gespeichert.read_text(encoding="utf-8"))
    assert "Nicht für klinische Nutzung" in d["hinweis"]


def test_datei_traegt_herkunft(gespeichert):
    d = json.loads(gespeichert.read_text(encoding="utf-8"))
    assert d["modell"] == "testmodell"
    assert d["erzeugt"].endswith("Z")
    assert len(d["bundle_pruefsumme"]) == 64
    assert len(d["katalog_pruefsumme"]) == 64


def test_zeitpunkt_braucht_eine_zeitzone(lauf):
    with pytest.raises(aufz.AufzeichnungFehler, match="Zeitzone"):
        aufz.aus_ergebnis(lauf, zeitpunkt=datetime(2026, 8, 29, 12, 0))


def test_zeitpunkt_wird_nach_utc_umgerechnet(lauf):
    a = aufz.aus_ergebnis(
        lauf, zeitpunkt=datetime(2026, 8, 29, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    )
    assert a.erzeugt == "2026-08-29T12:00:00Z"


# --- Fehlerhafte Eingaben --------------------------------------------------


def test_unbekannte_formatversion_wird_abgewiesen(gespeichert):
    """Halb verstehen wäre schlimmer als abweisen: Ein neueres Format
    könnte Felder tragen, deren Fehlen das Ergebnis stillschweigend
    verändert."""
    d = json.loads(gespeichert.read_text(encoding="utf-8"))
    d["format_version"] = 99
    gespeichert.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(aufz.AufzeichnungFehler, match="Format"):
        aufz.lies(gespeichert)


def test_fehlende_datei(tmp_path):
    with pytest.raises(aufz.AufzeichnungFehler, match="gibt es nicht"):
        aufz.lies(tmp_path / "nichts.json")


def test_kaputtes_json(tmp_path):
    pfad = tmp_path / "kaputt.json"
    pfad.write_text("{kein json", encoding="utf-8")
    with pytest.raises(aufz.AufzeichnungFehler, match="kein gültiges JSON"):
        aufz.lies(pfad)


def test_aufzeichnung_ohne_teile(tmp_path):
    pfad = tmp_path / "leer.json"
    pfad.write_text(json.dumps({"format_version": 1, "teile": []}), encoding="utf-8")
    with pytest.raises(aufz.AufzeichnungFehler, match="keine Teile"):
        aufz.lies(pfad)


def test_lauf_ohne_parameter_laesst_sich_nicht_aufzeichnen():
    """Ein vollständig gescheiterter Lauf hat nichts, was sich wiederholen
    ließe."""
    leer = generiere_kohorte(TeilClient(faellt_aus={1, 2, 3}), "45 Patientinnen",
                             45, teilgroesse=15)
    with pytest.raises(aufz.AufzeichnungFehler, match="nichts aufzuzeichnen"):
        aufz.aus_ergebnis(leer)


def test_unvollstaendiger_lauf_laesst_sich_aufzeichnen(tmp_path):
    """Was geliefert wurde, ist wiederholbar — die Lücke wandert mit."""
    teil = generiere_kohorte(TeilClient(faellt_aus={2}), "45 Patientinnen", 45,
                             teilgroesse=15)
    a = aufz.aus_ergebnis(teil)
    w = aufz.gib_wieder(a)
    assert w.identisch
    assert w.ergebnis.patienten == 30
    assert w.ergebnis.angefragt == 45
    assert w.ergebnis.mengentreue == pytest.approx(30 / 45), "die Lücke bleibt sichtbar"


# --- Die Prüfsumme selbst --------------------------------------------------


def test_pruefsumme_haengt_nicht_an_der_schluesselreihenfolge(lauf):
    """Ohne `sort_keys` ergäben zwei inhaltsgleiche Bundles verschiedene
    Summen, und jede Wiedergabe meldete grundlos eine Abweichung."""
    a = {"x": 1, "y": [{"p": 1, "q": 2}]}
    b = {"y": [{"q": 2, "p": 1}], "x": 1}
    assert aufz.pruefsumme(a) == aufz.pruefsumme(b)


def test_pruefsumme_merkt_einen_unterschied(lauf):
    geaendert = json.loads(json.dumps(lauf.bundle))
    geaendert["entry"][0]["resource"]["id"] = "pat-999"
    assert aufz.pruefsumme(lauf.bundle) != aufz.pruefsumme(geaendert)


def test_katalogpruefsumme_ist_stabil():
    assert aufz.katalog_pruefsumme() == aufz.katalog_pruefsumme()


def test_katalogpruefsumme_reagiert_auf_einen_geaenderten_code():
    schluessel = next(iter(CONDITION_CODES))
    alt = CONDITION_CODES[schluessel]
    vorher = aufz.katalog_pruefsumme()
    try:
        CONDITION_CODES[schluessel] = replace(alt, icd10gm="Z99.9")
        assert aufz.katalog_pruefsumme() != vorher
    finally:
        CONDITION_CODES[schluessel] = alt
    assert aufz.katalog_pruefsumme() == vorher


def test_teilparameter_ueberlebt_den_umweg_ueber_json():
    tp = TeilParameter(angefragt=15, parameter={"patienten": [{"vorname": "Käthe"}]})
    zurueck = TeilParameter.from_dict(json.loads(json.dumps(tp.to_dict())))
    assert zurueck == tp


# --- Nachgestellte Befunde -------------------------------------------------


def test_katalogsumme_erfasst_vital_sign(gespeichert):
    """Nachgestellt: `vital_sign` steuert Observation.category
    (`vital-signs` gegen `laboratory`) und wirkt damit aufs Bundle. Eine
    Aufzählung von Hand hatte es übersehen — das Bundle änderte sich, der
    Fingerabdruck nicht, und der Befund schickte die Suche zu den
    Vorlagen."""
    from synthfhir.domain.codes import OBSERVATION_CODES

    code = "4548-4"
    alt = OBSERVATION_CODES[code]
    vorher = aufz.katalog_pruefsumme()
    try:
        OBSERVATION_CODES[code] = replace(alt, vital_sign=not alt.vital_sign)
        assert aufz.katalog_pruefsumme() != vorher
        w = aufz.gib_wieder(aufz.lies(gespeichert))
    finally:
        OBSERVATION_CODES[code] = alt

    assert not w.identisch
    assert w.katalog_geaendert, "sonst zeigt der Befund in die falsche Richtung"


@pytest.mark.parametrize("feld,wert", [
    ("vital_sign", True), ("low", 0.1), ("high", 99.9),
    ("unit", "andere"), ("unit_code", "xyz"), ("display", "Other"),
])
def test_jedes_feld_des_katalogs_zaehlt(feld, wert):
    """Der Fingerabdruck läuft über alle Felder, nicht über eine Auswahl.
    Beim nächsten neuen Katalogfeld wiederholte sich der Fehler sonst."""
    from synthfhir.domain.codes import OBSERVATION_CODES

    code = "4548-4"
    alt = OBSERVATION_CODES[code]
    vorher = aufz.katalog_pruefsumme()
    try:
        OBSERVATION_CODES[code] = replace(alt, **{feld: wert})
        assert aufz.katalog_pruefsumme() != vorher, f"{feld} wird übersehen"
    finally:
        OBSERVATION_CODES[code] = alt


def test_ohne_katalogsumme_wird_nichts_ueber_den_katalog_behauptet(lauf):
    """Nachgestellt: Der Befund sagte „Der Katalog ist unverändert" —
    über etwas, das nie geprüft wurde."""
    ohne = aufz.Aufzeichnung(beschreibung="x", angefragt=30,
                             teile=list(lauf.parameter),
                             bundle_pruefsumme="0" * 64)
    befund = aufz.gib_wieder(ohne).befund()
    assert "keinen Katalog-Fingerabdruck" in befund
    assert "Katalog ist unverändert" not in befund


def test_kein_katalog_fehlt_im_verzeichnis():
    """Der Fingerabdruck läuft über `KATALOGE`. Käme eine Sammlung hinzu
    und stünde sie nicht dort, bliebe ihre Änderung unbemerkt — derselbe
    Fehler wie beim übersehenen `vital_sign`, nur eine Ebene höher.

    Deshalb sucht dieser Test die Sammlungen selbst und vergleicht.
    """
    from synthfhir.domain import codes as k

    gefunden = {
        name for name, wert in vars(k).items()
        if name.isupper() and isinstance(wert, dict) and wert
        and all(hasattr(e, "code") for e in wert.values())
    }
    verzeichnet = {id(v) for v in k.KATALOGE.values()}
    fehlend = {n for n in gefunden if id(getattr(k, n)) not in verzeichnet}
    assert not fehlend, f"nicht in KATALOGE: {sorted(fehlend)}"


def test_jeder_katalog_faellt_im_fingerabdruck_auf():
    """Nicht nur verzeichnet, sondern auch wirksam."""
    from dataclasses import replace

    from synthfhir.domain import codes as k

    for name, katalog in k.KATALOGE.items():
        schluessel = next(iter(katalog))
        alt = katalog[schluessel]
        vorher = aufz.katalog_pruefsumme()
        try:
            katalog[schluessel] = replace(alt, display="Geändert für den Test")
            assert aufz.katalog_pruefsumme() != vorher, f"{name} wird übersehen"
        finally:
            katalog[schluessel] = alt
