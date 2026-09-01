"""Tests der Szenario-Bibliothek.

Ein Szenario ist eingecheckter Inhalt, der gegen einen sich ändernden
Katalog läuft. Die Gefahr ist deshalb nicht, dass es heute kaputt ist —
sondern dass es in einem Jahr **still** falsch wird.

Genau das kann passieren: Nennt ein Szenario einen Code, den der Katalog
nicht mehr führt, ersetzt `baue_aus_parametern` ihn durch einen anderen
und hinterlässt nur eine Beanstandung. Das Ergebnis wäre gültiges FHIR mit
falschem Inhalt, ausgeliefert unter einem Namen, der etwas anderes
verspricht.

Die Tests hier sind deshalb vor allem **Haltbarkeitstests**.
"""

from __future__ import annotations

import json

import pytest

from synthfhir.domain.codes import (
    CONDITION_CODES,
    ENCOUNTER_CLASSES,
    MEDICATION_CODES,
    OBSERVATION_CODES,
)
from synthfhir.prompts import MAX_PATIENTEN
from synthfhir.szenarien import (
    SZENARIEN,
    baue_kohorte,
    Szenario,
    SzenarioFehler,
    alle,
    baue,
    hole,
    lies,
    unbekannte_codes,
)


# --- Haltbarkeit -----------------------------------------------------------


@pytest.mark.parametrize("szenario", alle(), ids=lambda s: s.name)
def test_jedes_szenario_benutzt_nur_katalogcodes(szenario):
    """Der wichtigste Test dieser Datei.

    Ohne ihn ersetzte ein veralteter Code sich still, und das Szenario
    lieferte weiter „eine Diabetes-Kohorte" — nur mit einer anderen
    Diagnose darin.
    """
    assert unbekannte_codes(szenario) == []


@pytest.mark.parametrize("szenario", alle(), ids=lambda s: s.name)
def test_jedes_szenario_ist_ausliefbar(szenario):
    """`fertig` heisst: valide, referenziell heil, ausliefbar. Ein
    Szenario, das das nicht erreicht, gehört nicht in die Bibliothek."""
    e = baue(szenario)
    assert e.fehler is None, e.fehler
    assert e.fertig, [str(b) for b in e.befunde_als_text()[:5]]
    assert e.integritaet and e.integritaet.broken_reference_count == 0


@pytest.mark.parametrize("szenario", alle(), ids=lambda s: s.name)
def test_kein_szenario_erfindet_codes_oder_reisst_grenzen(szenario):
    """Zwei Beanstandungsarten, die in einer kuratierten Vorlage nichts zu
    suchen haben: ein ersetzter Code und eine gegriffene Mengengrenze.

    Beide wären für sich harmlos gemeldet — in einem Szenario sind sie
    ein Pflegefehler.
    """
    e = baue(szenario)
    schlimm = [b for b in e.beanstandungen
               if b.art.startswith(("erfunden", "mengengrenze", "ungueltig",
                                 "obergrenze", "fehlendes_feld"))]
    assert not schlimm, [f"{b.art}: {b.detail}" for b in schlimm]


@pytest.mark.parametrize("szenario", alle(), ids=lambda s: s.name)
def test_jedes_szenario_liefert_die_versprochene_patientenzahl(szenario):
    """Gebaute Patienten gegen angekuendigte.

    Das ist keine Tautologie: `baue_aus_parametern` ueberspringt
    Eintraege, die es nicht lesen kann, und baut dann still weniger.
    Der Test unten stellt genau das nach.
    """
    e = baue(szenario)
    assert e.anzahl_je_typ.get("Patient") == szenario.patienten
    assert e.angefragt == szenario.patienten


def test_ein_uebersprungener_eintrag_faellt_auf():
    """Die Gegenprobe zum Test darueber — sonst hinge er in der Luft."""
    s = Szenario(
        name="kaputt", titel="x", beschreibung="x", zeigt="x",
        parameter={"patienten": [
            {"vorname": "A", "nachname": "B", "geschlecht": "female",
             "geburtsdatum": "1970-01-01",
             "diagnosen": [{"code": "44054006", "beginn": "2020-01-01"}]},
            "kein Objekt",
        ]},
    )
    e = baue(s)
    assert s.patienten == 2
    assert e.anzahl_je_typ.get("Patient") == 1
    assert any(b.art == "fehlendes_feld" for b in e.beanstandungen)


@pytest.mark.parametrize("szenario", alle(), ids=lambda s: s.name)
def test_kein_eingebautes_szenario_sprengt_die_patientengrenze(szenario):
    """`lies()` prueft das fuer geladene Dateien. Die eingebauten gehen
    daran vorbei — also hier."""
    assert szenario.patienten <= MAX_PATIENTEN


def test_ein_szenario_ist_deterministisch():
    """Ohne das wäre eine Vorlage keine Vorlage."""
    s = hole("diabetes-ambulanz")
    erst = json.dumps(baue(s).bundle, sort_keys=True, ensure_ascii=False)
    zweit = json.dumps(baue(s).bundle, sort_keys=True, ensure_ascii=False)
    assert erst == zweit


# --- Was die Bibliothek abdecken soll --------------------------------------


def test_die_bibliothek_zeigt_alle_fuenf_ressourcentypen():
    """Eine Bibliothek, die nur den glatten Fall zeigt, verkauft das
    Werkzeug unter Wert."""
    gesehen: set[str] = set()
    for s in alle():
        gesehen |= set(baue(s).anzahl_je_typ)
    assert gesehen == {"Patient", "Encounter", "Condition", "Observation",
                       "MedicationStatement"}


def test_die_bibliothek_enthaelt_den_fall_ohne_begegnung():
    """Der unbequeme Fall, an dem `isik-con1` einmal unsichtbar blieb
    (ADR-009). Er gehoert gezeigt, nicht versteckt."""
    ohne = [s for s in alle()
            if any(not p.get("begegnungen")
                   for p in s.parameter["patienten"])]
    assert ohne, "kein Szenario mit einem Patienten ohne Begegnung"

    e = baue(ohne[0])
    # Der Code ergaenzt den Kontakt — und genau das soll man sehen.
    assert e.anzahl_je_typ.get("Encounter")
    for r in e.ressourcen:
        if r["resourceType"] == "Condition":
            assert "encounter" in r


def test_die_bibliothek_enthaelt_ein_blutdruckpanel():
    """Seit ADR-014 ist der Blutdruck eine Observation mit zwei
    Komponenten. Ein Szenario, das das zeigt, ist die beste Erklaerung."""
    panels = [r for s in alle() for r in baue(s).ressourcen
              if r["resourceType"] == "Observation" and r.get("component")]
    assert panels
    assert panels[0]["code"]["coding"][0]["code"] == "85354-9"


def test_jedes_szenario_hat_eine_eigene_begruendung():
    """`zeigt` sagt, warum es diese Vorlage gibt. Zwei Szenarien mit
    demselben Satz waeren eines zu viel."""
    saetze = [s.zeigt for s in alle()]
    assert len(set(saetze)) == len(saetze)
    for s in alle():
        assert len(s.zeigt) > 20, f"{s.name}: zu duenn"


def test_die_namen_sind_eindeutig_und_urltauglich():
    """Sie werden zu Kennungen in der Oberflaeche und in der API."""
    import re

    namen = [s.name for s in alle()]
    assert len(set(namen)) == len(namen)
    for n in namen:
        assert re.fullmatch(r"[a-z0-9-]+", n), n


# --- Geladene Szenarien sind Fremdeingabe ----------------------------------


def test_ein_geladenes_szenario_wird_auf_form_geprueft(tmp_path):
    proben = [
        ("kein Objekt", '"text"'),
        ("Feld fehlt", '{"name": "x"}'),
        ("parameter kein Objekt", '{"name":"x","titel":"x","beschreibung":"x",'
                                  '"zeigt":"x","parameter":"nein"}'),
        ("keine Patienten", '{"name":"x","titel":"x","beschreibung":"x",'
                            '"zeigt":"x","parameter":{"patienten":[]}}'),
    ]
    for was, inhalt in proben:
        p = tmp_path / "s.json"
        p.write_text(inhalt, encoding="utf-8")
        with pytest.raises(SzenarioFehler):
            lies(p)


def test_ein_geladenes_szenario_sprengt_die_patientengrenze_nicht(tmp_path):
    """Sonst waere eine geteilte Vorlage der Weg an MAX_PATIENTEN vorbei."""
    p = tmp_path / "gross.json"
    p.write_text(json.dumps({
        "name": "gross", "titel": "x", "beschreibung": "x", "zeigt": "x",
        "parameter": {"patienten": [{"vorname": "A"}] * (MAX_PATIENTEN + 1)},
    }), encoding="utf-8")
    with pytest.raises(SzenarioFehler, match="höchstens"):
        lies(p)


def test_die_fehlermeldung_gibt_den_inhalt_nicht_wieder(tmp_path):
    """Ein geladenes Szenario ist Fremdeingabe. Sein Inhalt hat in einer
    Meldung nichts verloren — dieselbe Regel wie bei der Aufzeichnung."""
    p = tmp_path / "s.json"
    p.write_text(json.dumps({
        "name": "x", "titel": "x", "beschreibung": "x", "zeigt": "x",
        "parameter": "GEHEIMER-INHALT",
    }), encoding="utf-8")
    with pytest.raises(SzenarioFehler) as fehler:
        lies(p)
    assert "GEHEIM" not in str(fehler.value)


@pytest.mark.parametrize("feld,eintrag,code", [
    ("diagnosen", {"code": "999999999", "beginn": "2020-01-01"}, "999999999"),
    ("messwerte", {"code": "000-0", "wert": 5.0, "datum": "2024-01-01"}, "000-0"),
    ("medikamente", {"code": "Z99ZZ99", "beginn": "2020-01-01"}, "Z99ZZ99"),
    ("begegnungen", {"art": "XXXX", "datum": "2024-01-01"}, "XXXX"),
])
def test_ein_geladenes_szenario_mit_unbekanntem_code_faellt_auf(
    tmp_path, feld, eintrag, code
):
    """Ueber ALLE vier Kataloge, nicht nur ueber Diagnosen.

    Nachgemessen: Mit nur einem Fall blieb das Weglassen dreier Kataloge
    aus `unbekannte_codes` unbemerkt.

    Abgewiesen wird nichts — der Katalog des Empfaengers kann ein anderer
    sein —, aber `unbekannte_codes` zeigt es, und der Lauf beanstandet es.
    """
    p = tmp_path / "s.json"
    p.write_text(json.dumps({
        "name": "fremd", "titel": "x", "beschreibung": "x", "zeigt": "x",
        "parameter": {"patienten": [{
            "vorname": "A", "nachname": "B", "geschlecht": "female",
            "geburtsdatum": "1970-01-01",
            "diagnosen": [{"code": "44054006", "beginn": "2020-01-01"}],
            feld: [eintrag]}]},
    }, ensure_ascii=False), encoding="utf-8")
    s = lies(p)
    assert (feld, code) in unbekannte_codes(s)
    assert any(b.art.startswith("erfunden") for b in baue(s).beanstandungen)


# --- Ehrlichkeit -----------------------------------------------------------


def test_ein_szenariolauf_nennt_sich_als_solcher():
    """Sonst saehe eine Vorlage aus wie ein Modelllauf, und niemand
    koennte beides auseinanderhalten."""
    e = baue(hole("diabetes-ambulanz"))
    assert e.szenario == "diabetes-ambulanz"
    assert e.llm_antworten == []
    assert e.versuche == 0
    assert e.eingabe_token == 0 and e.ausgabe_token == 0


@pytest.mark.parametrize("szenario", alle(), ids=lambda s: s.name)
def test_beide_berichte_nennen_das_szenario(szenario):
    """Der maschinenlesbare Kanal muss es auch sagen, nicht nur stderr.

    Nachgemessen ohne diesen Test: `--szenario ... --bericht b.json`
    beschrieb einen Modelllauf, den es nie gab — `teile` mit einem
    Eintrag, `dauer_s: 0.0`, null Token. Wer den Bericht las, konnte
    Vorlage und Modelllauf nicht unterscheiden.
    """
    for e in (baue(szenario), baue_kohorte(szenario)):
        d = e.to_dict()
        assert d["szenario"] == szenario.name, type(e).__name__


def test_ein_modelllauf_nennt_kein_szenario():
    """Die Gegenprobe — sonst pruefte der Test oben nur eine Konstante."""
    from synthfhir.generation import Ergebnis
    from synthfhir.kohorte import Kohortenergebnis

    assert Ergebnis(beschreibung="x").szenario is None
    assert Kohortenergebnis(beschreibung="x", angefragt=1).szenario is None
    # Und zwar AUSGEWIESEN als null, nicht weggelassen: Ein fehlendes Feld
    # liesse offen, ob der Lauf keins hatte oder ob die Fassung es nicht
    # kennt.
    assert Ergebnis(beschreibung="x").to_dict()["szenario"] is None
    assert Kohortenergebnis(
        beschreibung="x", angefragt=1).to_dict()["szenario"] is None


def test_jede_ressource_traegt_das_testdatenlabel():
    """PRD Block 6 gilt auch hier. Ein Szenario nimmt keine Abkuerzung
    durch die Kennzeichnungspflicht."""
    from synthfhir.domain.codes import TESTDATEN_LABEL

    for s in alle():
        for r in baue(s).ressourcen:
            sicherheit = (r.get("meta") or {}).get("security") or []
            assert any(c.get("code") == TESTDATEN_LABEL["code"]
                       for c in sicherheit), f"{s.name}: {r['id']}"


def test_hole_weist_unbekannte_namen_ab():
    with pytest.raises(SzenarioFehler, match="Bekannt sind"):
        hole("gibtsnicht")
    assert set(SZENARIEN) == {s.name for s in alle()}


def test_szenarien_decken_die_kataloge_breit_ab():
    """Eine Bibliothek, die nur drei Codes benutzt, zeigt den Katalog
    nicht. Kein hoher Anspruch — aber einer, der auffaellt, wenn jemand
    alle Szenarien auf dieselbe Diagnose umstellt."""
    benutzt = {"diagnosen": set(), "messwerte": set(), "medikamente": set(),
               "begegnungen": set()}
    for s in alle():
        for p in s.parameter["patienten"]:
            for feld, schluessel in (("diagnosen", "code"), ("messwerte", "code"),
                                     ("medikamente", "code"), ("begegnungen", "art")):
                for e in p.get(feld) or []:
                    benutzt[feld].add(e[schluessel])
    assert len(benutzt["diagnosen"]) >= 4
    assert len(benutzt["messwerte"]) >= 8
    assert len(benutzt["begegnungen"]) >= 3
    # Und alles Benutzte muss es geben — die Gegenprobe zum Zaehlen.
    assert benutzt["diagnosen"] <= set(CONDITION_CODES)
    assert benutzt["messwerte"] <= set(OBSERVATION_CODES)
    assert benutzt["medikamente"] <= set(MEDICATION_CODES)
    assert benutzt["begegnungen"] <= set(ENCOUNTER_CLASSES)


def test_szenario_und_aufzeichnung_sind_verschiedene_dinge():
    """Ein Szenario traegt bewusst KEINE Pruefsumme.

    Eine Aufzeichnung verspricht „dasselbe wie damals" und meldet
    ABWEICHUNG, sobald sich der Katalog aendert. Eine Vorlage verspricht
    „eine Diabetes-Kohorte" — sie soll nach einer Katalogverbesserung die
    NEUE Ausgabe liefern, nicht die alte melden.
    """
    felder = set(Szenario.__dataclass_fields__)
    assert not felder & {"bundle_pruefsumme", "katalog_pruefsumme"}
    assert felder == {"name", "titel", "beschreibung", "zeigt", "parameter"}


# --- Die zwei Huellen ------------------------------------------------------


@pytest.mark.parametrize("szenario", alle(), ids=lambda s: s.name)
def test_beide_wege_liefern_dasselbe(szenario):
    """`baue` (Weboberflaeche) und `baue_kohorte` (Kommandozeile) muessen
    Ressource fuer Ressource uebereinstimmen.

    Es gibt sie beide, weil die CLI mit `Kohortenergebnis` rechnet und das
    Web mit `Ergebnis` — zwei Huellen um denselben Kern. Ohne diesen Test
    koennte eine davon abdriften, und dasselbe Szenario lieferte je nach
    Aufrufweg etwas anderes.
    """
    a, b = baue(szenario), baue_kohorte(szenario)
    assert a.bundle is not None and b.bundle is not None
    assert json.dumps(a.bundle, sort_keys=True) == json.dumps(b.bundle, sort_keys=True)
    assert a.fertig == b.fertig


def test_ein_szenario_fuehrt_den_notfall_vor():
    """Der Notfall ist der einzige Katalogeintrag, bei dem Schluessel und
    Code auseinandergehen (ADR-018). Ein Szenario, das ihn zeigt, ist die
    beste Erklaerung - und faellt auf, wenn die Umsetzung zurueckgedreht
    wird."""
    from synthfhir.domain.codes import AUFNAHMEANLASS_SYSTEM

    notfaelle = [
        r for s in alle() for r in baue(s).ressourcen
        if r["resourceType"] == "Encounter" and r.get("hospitalization")
    ]
    assert notfaelle, "kein Szenario zeigt den Aufnahmeanlass"
    e = notfaelle[0]
    assert e["class"]["code"] == "IMP", "der Notfall steht nicht in class"
    k = e["hospitalization"]["admitSource"]["coding"][0]
    assert k["system"] == AUFNAHMEANLASS_SYSTEM and k["code"] == "N"
