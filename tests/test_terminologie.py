"""Tests des Terminologie-Nachweises.

Der Kern dieser Datei ist **nicht** die Frage „sind unsere Codes
Mitglied". Die ist eine Tatsache über SNOMED und ändert sich nicht,
wenn dieser Code kaputtgeht.

Der Kern ist: **Merkt der Nachweis, wenn er nichts gemessen hat?**

Das ist keine erfundene Sorge. Beim Bau wurde der naheliegende Weg
versucht — dem messenden HAPI einen entfernten Terminologieserver
mitgeben — und er ergab:

    ohne Terminologie:  11 geprüft | 0 Fehler | 8 ungeprüft | 19 Warnungen
    mit der Einstellung: 11 geprüft | 11 Fehler | 0 ungeprüft | 0 Warnungen

„0 ungeprüft" ist die schönste Zahl, die dieser Bericht kennt, und sie kam
von einer NullPointerException, die jede Validierung abbrach. Ein
kaputter Terminologieaufbau sieht besser aus als ein funktionierender.
"""

from __future__ import annotations

import json

import pytest
import requests

from synthfhir.domain.codes import KATALOGE
from synthfhir.terminologie import (
    DIAGNOSES_SCT_SHA256,
    ERFUNDEN,
    NICHT_MITGLIED,
    Probe,
    TerminologieFehler,
    Terminologienachweis,
    hole_valueset,
    weise_nach,
)


def _antwort(inhalt: dict, status: int = 200) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r._content = json.dumps(inhalt).encode("utf-8")
    r.headers["Content-Type"] = "application/fhir+json"
    return r


def _parameters(result) -> dict:
    p = [{"name": "code", "valueCode": "x"}]
    if result is not None:
        p.insert(0, {"name": "result", "valueBoolean": result})
    return {"resourceType": "Parameters", "parameter": p}


@pytest.fixture
def echtes_valueset(monkeypatch):
    """Die echte Definition, ohne sie jedes Mal zu holen."""
    vs = {
        "resourceType": "ValueSet", "status": "active",
        "url": "https://gematik.de/fhir/isik/ValueSet/DiagnosesSCT",
        "version": "4.0.3",
        "compose": {"include": [
            {"system": "http://snomed.info/sct",
             "filter": [{"property": "concept", "op": "is-a", "value": v}]}
            for v in ("404684003", "272379006", "243796009")
        ]},
    }
    monkeypatch.setattr("synthfhir.terminologie.hole_valueset", lambda **kw: vs)
    return vs


# --- Merkt der Nachweis, wenn er nichts gemessen hat? ----------------------


def test_ein_server_der_alles_bejaht_macht_den_nachweis_ungueltig(
    monkeypatch, echtes_valueset
):
    """Der wichtigste Test dieser Datei.

    Ohne die Gegenproben meldete dieser Lauf „25 von 25 Mitglied" — die
    bestmögliche Zahl — obwohl der Server überhaupt nicht entscheidet.
    """
    monkeypatch.setattr(
        requests, "post", lambda *a, **kw: _antwort(_parameters(True))
    )
    n = weise_nach()
    assert n.alle_mitglied is True, "die Mitgliederzahl sieht perfekt aus"
    assert n.gueltig is False, "und genau deshalb muss der Nachweis fallen"
    assert "UNGÜLTIG" in n.befund()


def test_ein_server_der_nichts_entscheidet_macht_den_nachweis_ungueltig(
    monkeypatch, echtes_valueset
):
    """Die Antwort ohne `result`-Parameter. Sie als False zu lesen wäre der
    stille Fehler: Es sähe aus wie „kein Mitglied" und wäre „nicht
    gefragt"."""
    monkeypatch.setattr(
        requests, "post", lambda *a, **kw: _antwort(_parameters(None))
    )
    n = weise_nach()
    assert n.gueltig is False
    assert all(p.erhalten is None for p in n.kanarienvoegel)


def test_ein_entscheidender_server_macht_den_nachweis_gueltig(
    monkeypatch, echtes_valueset
):
    """Die Gegenprobe zur Gegenprobe. Ohne sie könnten die Tests oben auch
    dann bestehen, wenn `gueltig` immer falsch wäre."""
    diagnosen = {e.code for e in KATALOGE["conditions"].values()}

    def entscheidet(url, **kw):
        code = kw["json"]["parameter"][0]["valueCoding"]["code"]
        return _antwort(_parameters(code in diagnosen))

    monkeypatch.setattr(requests, "post", entscheidet)
    n = weise_nach()
    assert n.gueltig is True
    assert n.alle_mitglied is True
    assert "Alle 25" in n.befund()


def test_ein_einzelner_nichtmitglied_code_faellt_auf(monkeypatch, echtes_valueset):
    """Der Fall, für den es den Nachweis gibt: Ein Katalogeintrag, der
    nicht in die Bindung gehört."""
    diagnosen = {e.code for e in KATALOGE["conditions"].values()}
    schwarzes_schaf = sorted(diagnosen)[0]

    def entscheidet(url, **kw):
        code = kw["json"]["parameter"][0]["valueCoding"]["code"]
        return _antwort(_parameters(code in diagnosen and code != schwarzes_schaf))

    monkeypatch.setattr(requests, "post", entscheidet)
    n = weise_nach()
    assert n.gueltig is True, "die Messung selbst war in Ordnung"
    assert n.alle_mitglied is False
    assert [p.code for p in n.abweichler] == [schwarzes_schaf]
    assert schwarzes_schaf in n.befund()


# --- Gegen was gemessen wird ----------------------------------------------


def test_eine_geaenderte_valueset_definition_bricht_ab(monkeypatch):
    """Gemessen wird gegen eine bekannte Fassung. Ändert die gematik sie,
    darf der Nachweis nicht stillschweigend etwas anderes messen."""
    r = requests.Response()
    r.status_code = 200
    r._content = b'{"resourceType": "ValueSet", "compose": {"include": []}}'
    monkeypatch.setattr(requests, "get", lambda *a, **kw: r)

    with pytest.raises(TerminologieFehler, match="geändert"):
        hole_valueset()


def test_die_pruefsumme_gehoert_in_den_bericht():
    """Ohne sie liesse sich nicht unterscheiden, ob gegen die Definition
    der gematik gemessen wurde oder gegen eine selbstgeschriebene."""
    n = Terminologienachweis(
        server="x", valueset="y", valueset_version="4.0.3",
        valueset_sha256=DIAGNOSES_SCT_SHA256,
    )
    assert n.to_dict()["valueset_sha256"] == DIAGNOSES_SCT_SHA256
    assert len(DIAGNOSES_SCT_SHA256) == 64


def test_die_proben_haengen_am_katalog_nicht_an_einer_liste(
    monkeypatch, echtes_valueset
):
    """Kommt ein Diagnosecode hinzu, wird er mitgeprüft.

    Eine Handaufzählung hätte ihn übersehen — das ist in diesem Projekt
    fünfmal passiert, zuletzt beim Fusstext mit drei von fünf
    Ressourcentypen.
    """
    monkeypatch.setattr(
        requests, "post", lambda *a, **kw: _antwort(_parameters(False))
    )
    n = weise_nach()
    geprueft = {p.code for p in n.mitglieder}
    im_katalog = {e.code for e in KATALOGE["conditions"].values()}
    assert geprueft == im_katalog


def test_die_kanarienvoegel_sind_keine_diagnosecodes():
    """Wäre einer davon im Katalog, prüfte die Gegenprobe sich selbst."""
    im_katalog = {e.code for e in KATALOGE["conditions"].values()}
    assert NICHT_MITGLIED not in im_katalog
    assert ERFUNDEN not in im_katalog


def test_ein_unerreichbarer_server_bricht_ab_statt_zu_schweigen(
    monkeypatch, echtes_valueset
):
    def faellt_aus(*a, **kw):
        raise requests.exceptions.ConnectionError("kein Netz")

    monkeypatch.setattr(requests, "post", faellt_aus)
    with pytest.raises(TerminologieFehler, match="nicht erreichbar"):
        weise_nach()


def test_probe_urteilt_ueber_die_erwartung_nicht_ueber_das_ergebnis():
    assert Probe("x", "y", erwartet=False, erhalten=False).wie_erwartet
    assert Probe("x", "y", erwartet=True, erhalten=True).wie_erwartet
    assert not Probe("x", "y", erwartet=False, erhalten=True).wie_erwartet
    assert not Probe("x", "y", erwartet=False, erhalten=None).wie_erwartet


# --- Gegen die echten Server ----------------------------------------------


def test_die_bindung_haelt_gegen_den_echten_server(terminologieserver):
    """Die eigentliche Messung, gegen einen echten Terminologieserver.

    Übersprungen, solange keiner verlangt wird — wie beim HAPI-Server
    (ADR-002). Mit `SYNTHFHIR_REQUIRE_TERMINOLOGIE=1` ist ein Fehlschlag
    ein Fehler und kein Übersprung.
    """
    n = weise_nach(server=terminologieserver)
    assert n.gueltig, n.befund()
    assert n.alle_mitglied, n.befund()
    assert n.snomed_version, "der Bericht muss die SNOMED-Fassung nennen"
