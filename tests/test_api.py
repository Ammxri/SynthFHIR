"""Tests des programmatischen Zugangs.

Der Kern dieser Datei ist **eine** Zusage: Ohne eigenen Schlüssel läuft
hier nichts, und der Schlüssel des Betreibers wird niemals benutzt.

Diese Zusage lässt sich leicht scheinbar prüfen. Das Projekt hat den
Fehler schon gemacht — `tests/test_web.py` ersetzte
`OpenAIKompatiblerClient` durch eine Attrappe und prüfte, *welcher Wert
übergeben wurde*. Der Rückfall auf den Betreiberschlüssel passierte aber
**innerhalb** der echten Klasse: Der Test wäre grün geblieben, während
die App im Betrieb den fremden Schlüssel verwarf.

Deshalb greifen die Tests hier so tief wie möglich — an `Session.send`,
also an der letzten Stelle vor dem Netz. Was dort im `Authorization`-Kopf
steht, ist das, was tatsächlich hinausgegangen wäre.
"""

from __future__ import annotations

import json

import pytest
import requests
from fastapi.testclient import TestClient

from synthfhir.llm import LLMFehler, client_mit_fremdschluessel
from synthfhir.web import app
from synthfhir.web import api as api_modul

from .conftest import BETREIBER_PLATZHALTER

KOPF = "X-SynthFHIR-LLM-Key"
AUFRUFER = "gsk_SCHLUESSEL-DES-AUFRUFERS"


@pytest.fixture
def klient() -> TestClient:
    return TestClient(app)


@pytest.fixture
def draht(monkeypatch):
    """Fängt jede ausgehende Anfrage ab und merkt sich ihre Kopfzeilen.

    Kein Netz, aber auch keine Attrappe der Klasse: `frage()`,
    `_post_mit_wartepausen`, `_pruefe_status` und der ganze Aufbau des
    Clients laufen echt. Abgeschnitten wird erst der letzte Schritt.
    """

    class Draht:
        def __init__(self):
            self.anfragen = []

        @property
        def autorisierungen(self):
            return [a.headers.get("Authorization") for a in self.anfragen]

    gefangen = Draht()
    antwort_text = json.dumps(
        {
            "verstanden": {"anzahl_patienten": 1, "kernkriterien": [],
                           "nicht_abbildbar": []},
            "patienten": [
                {
                    "vorname": "Ingrid", "nachname": "Baumgartner",
                    "geschlecht": "female", "geburtsdatum": "1958-03-14",
                    "diagnosen": [{"code": "44054006", "beginn": "2012-05-01"}],
                    "messwerte": [{"code": "4548-4", "wert": 7.8,
                                   "datum": "2024-01-15"}],
                }
            ],
        },
        ensure_ascii=False,
    )

    def falsches_send(self, vorbereitet, **_):
        gefangen.anfragen.append(vorbereitet)
        antwort = requests.Response()
        antwort.status_code = 200
        antwort._content = json.dumps(
            {
                "choices": [
                    {"message": {"content": antwort_text}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }
        ).encode("utf-8")
        antwort.headers["Content-Type"] = "application/json"
        return antwort

    monkeypatch.setattr(requests.Session, "send", falsches_send)
    return gefangen


def _erzeuge(klient, schluessel=AUFRUFER, **rumpf):
    kopf = {KOPF: schluessel} if schluessel is not None else {}
    return klient.post(
        "/api/v1/erzeugen", json={"beschreibung": "Eine Patientin", **rumpf},
        headers=kopf,
    )


# --- Die tragende Zusage ---------------------------------------------------


def test_ohne_kopf_geht_keine_einzige_anfrage_hinaus(klient, draht):
    """Die wichtigste Prüfung, und die, die ein Statuscode allein nicht
    leistet: 401 sagt nur, was zurückkam — nicht, ob vorher etwas
    hinausging."""
    antwort = _erzeuge(klient, schluessel=None)
    assert antwort.status_code == 401
    assert antwort.json()["fehlerart"] == "schluessel_fehlt"
    assert draht.anfragen == [], "es ging trotz 401 etwas hinaus"


@pytest.mark.parametrize(
    "wert",
    ["", "   ", chr(9), chr(11), "gsk" + chr(0) + "abc", "a" * 5000],
)
def test_unbrauchbare_schluessel_erreichen_das_netz_nicht(klient, draht, wert):
    """Die Fälle, die im Konstruktor drei verschiedene Ausgänge hatten.

    `""` fiel still auf den Betreiberschlüssel zurück, reiner Leerraum
    schickte die Anfrage ganz ohne Authorization hinaus. Beides
    nachgemessen, beides hier abgedeckt.
    """
    antwort = _erzeuge(klient, schluessel=wert)
    assert antwort.status_code == 400
    assert draht.anfragen == []


def test_nicht_ascii_schluessel_erreicht_das_netz_nicht(klient, draht):
    """Ein Wert wie U+00A0 laesst sich als `str` gar nicht senden - httpx
    verlangt ASCII. Ein roher Client kann die Bytes aber schicken, und der
    Server gibt sie als Latin-1 weiter. Der Fall wird deshalb als Bytes
    geprueft und nicht fuer unmoeglich erklaert."""
    antwort = klient.post(
        "/api/v1/erzeugen",
        json={"beschreibung": "x"},
        headers=[(KOPF.encode(), bytes([0xA0]))],
    )
    assert antwort.status_code == 400
    assert draht.anfragen == []


def test_der_betreiberschluessel_geht_nie_hinaus(klient, draht):
    """Die Zusage in ihrer schärfsten Form: Über ALLE Wege, auf denen ein
    Aufrufer es versuchen könnte, darf der Platzhalter nirgends im
    ausgehenden Verkehr auftauchen."""
    for versuch in (None, "", "   ", chr(9)):
        _erzeuge(klient, schluessel=versuch)
    assert draht.anfragen == []

    _erzeuge(klient)  # der ehrliche Weg
    hinaus = " ".join(a or "" for a in draht.autorisierungen)
    assert BETREIBER_PLATZHALTER not in hinaus
    assert hinaus.count(f"Bearer {AUFRUFER}") == len(draht.anfragen)


def test_der_eigene_schluessel_geht_tatsaechlich_hinaus(klient, draht):
    """Die Gegenprobe. Ohne sie könnte der Test oben auch dann bestehen,
    wenn gar nichts funktioniert."""
    antwort = _erzeuge(klient)
    assert antwort.status_code == 200, antwort.text
    assert draht.autorisierungen == [f"Bearer {AUFRUFER}"]
    assert antwort.json()["lauf"]["schluessel_herkunft"] == "aufrufer"


def test_die_fabrik_haelt_auch_ohne_route(monkeypatch):
    """Der Riegel sitzt an der Quelle, nicht nur an der Route.

    Entfernte ein späterer Umbau die Prüfung in `api.py`, bliebe dieser
    Test rot — genau das soll er leisten.
    """
    for wert in (None, "", "   "):
        with pytest.raises(LLMFehler) as fehler:
            client_mit_fremdschluessel(wert)
        assert fehler.value.art == "abgelehnt"

    client = client_mit_fremdschluessel(AUFRUFER)
    assert client.session.headers["Authorization"] == f"Bearer {AUFRUFER}"
    assert client.schluessel_herkunft == "aufrufer"


def test_netrc_kann_den_schluessel_nicht_ersetzen(tmp_path, monkeypatch, draht):
    """`requests` ersetzt einen Bearer-Kopf durch .netrc-Zugangsdaten,
    sobald `trust_env` gilt — der Schlüssel steht als Kopfzeile, nicht als
    `auth`, und wird dort nicht gesehen.

    Nachgemessen ging ein gesetzter `Bearer sk-...` als
    `Basic <netrc>` hinaus. Auf einem Rechner mit hinterlegter .netrc für
    den Anbieter hätte der Aufrufer damit auf fremde Rechnung gearbeitet.
    """
    netrc = tmp_path / "netrc"
    netrc.write_text(
        "machine anbieter.invalid login BETREIBER password NETRC-GEHEIM\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NETRC", str(netrc))

    client = client_mit_fremdschluessel(AUFRUFER)
    assert client.session.trust_env is False
    try:
        client.frage(system="s", benutzer="b")
    except LLMFehler:
        pass
    hinaus = " ".join(a or "" for a in draht.autorisierungen)
    assert "NETRC-GEHEIM" not in hinaus
    assert "Basic " not in hinaus
    assert f"Bearer {AUFRUFER}" in hinaus


# --- Kein fremder Text nach draußen ----------------------------------------


def test_kein_schluessel_in_der_fehlerantwort(klient, draht):
    """Ein Schlüssel mit Zeilenumbruch erzeugt in `requests` eine
    Ausnahme, deren Text den WERT enthält; `llm.frage` bettet sie ein.
    Nachgemessen landete er so wörtlich in `Ergebnis.fehler`."""
    antwort = _erzeuge(klient, schluessel="gsk_GEHEIM\nX-Boes: ja")
    assert antwort.status_code == 400
    assert "GEHEIM" not in antwort.text
    assert draht.anfragen == []


def test_kein_anbietertext_in_der_fehlerantwort(klient, monkeypatch):
    """Der Rumpf des Anbieters kann alles enthalten — bis hin zu
    wiederholten Zugangsdaten. Er darf den Aufrufer nie erreichen."""

    def antwortet_mit_geheimnis(self, vorbereitet, **_):
        antwort = requests.Response()
        antwort.status_code = 500
        antwort._content = b'{"error":"INTERNES-DETAIL-DES-ANBIETERS"}'
        return antwort

    monkeypatch.setattr(requests.Session, "send", antwortet_mit_geheimnis)
    antwort = _erzeuge(klient)
    assert antwort.status_code == 502
    assert "INTERNES-DETAIL" not in antwort.text
    assert antwort.json()["quelle"] == "anbieter"


def test_der_anfragekoerper_wird_nicht_zurueckgespiegelt(klient, draht):
    """Eine 422 aus FastAPI gäbe den empfangenen Körper wörtlich zurück
    (nachgemessen: `"input": "gsk_KURZ"`). Deshalb liest dieser Zugang
    den Rumpf von Hand."""
    antwort = klient.post(
        "/api/v1/erzeugen",
        content=b'{"beschreibung": "ERKENNBARER-INHALT", "hoechstzahl": "keine Zahl"}',
        headers={KOPF: AUFRUFER, "Content-Type": "application/json"},
    )
    assert antwort.status_code == 400
    assert "ERKENNBARER-INHALT" not in antwort.text


# --- Statuscodes und Grenzen -----------------------------------------------


def test_abgelehnter_schluessel_wird_als_solcher_gemeldet(klient, monkeypatch):
    def lehnt_ab(self, vorbereitet, **_):
        antwort = requests.Response()
        antwort.status_code = 401
        antwort._content = b"{}"
        return antwort

    monkeypatch.setattr(requests.Session, "send", lehnt_ab)
    antwort = _erzeuge(klient)
    assert antwort.status_code == 401
    assert antwort.json()["fehlerart"] == "schluessel_abgelehnt"


def test_ratengrenze_des_anbieters_ist_als_fremde_erkennbar(klient, monkeypatch):
    """„Unbegrenzt mit eigenem Schlüssel" heißt, der Aufrufer muss
    erkennen können, dass die Bremse seine eigene ist."""

    def bremst(self, vorbereitet, **_):
        antwort = requests.Response()
        antwort.status_code = 429
        antwort._content = b"{}"
        return antwort

    monkeypatch.setattr(requests.Session, "send", bremst)
    antwort = _erzeuge(klient)
    assert antwort.status_code == 429
    assert antwort.json()["quelle"] == "anbieter"


def test_doppelter_kopf_wird_abgewiesen_statt_still_gewaehlt(klient, draht):
    """Bei einem als `str` deklarierten Parameter gewinnt still der erste
    Wert. Wo über fremde Abrechnung entschieden wird, ist „still den
    ersten nehmen" die falsche Vorgabe."""
    antwort = klient.post(
        "/api/v1/erzeugen",
        json={"beschreibung": "x"},
        headers=[(KOPF, AUFRUFER), (KOPF, "gsk_ein_zweiter")],
    )
    assert antwort.status_code == 400
    assert antwort.json()["fehlerart"] == "schluessel_mehrdeutig"
    assert draht.anfragen == []


def test_leere_beschreibung_kostet_kein_kontingent(klient, draht):
    antwort = _erzeuge(klient, beschreibung="   ")
    assert antwort.status_code == 400
    assert draht.anfragen == [], "der Modellaufruf fand trotzdem statt"


def test_zu_langer_koerper_wird_abgewiesen(klient, draht):
    antwort = klient.post(
        "/api/v1/erzeugen",
        content=json.dumps({"beschreibung": "x" * 200_000}).encode(),
        headers={KOPF: AUFRUFER, "Content-Type": "application/json"},
    )
    assert antwort.status_code == 413
    assert draht.anfragen == []


def test_hoechstzahl_wird_gekappt_und_gemeldet(klient, draht):
    """Gekappt zu werden ist in Ordnung; still gekappt zu werden nicht."""
    antwort = _erzeuge(klient, hoechstzahl=500)
    assert antwort.status_code == 200
    assert any("gekappt" in g for g in antwort.json()["grenzen_gegriffen"])


def test_ausgelastet_meldet_die_eigene_grenze_als_eigene(klient, draht, monkeypatch):
    """Der Deckel für gleichzeitige Läufe ist kein Ratenlimit — aber der
    Aufrufer muss ihn von der Grenze seines Anbieters unterscheiden
    können."""
    monkeypatch.setattr(api_modul._plaetze, "acquire", lambda blocking=True: False)
    antwort = _erzeuge(klient)
    assert antwort.status_code == 429
    assert antwort.json()["quelle"] == "synthfhir"
    assert antwort.headers.get("Retry-After")


# --- Die Antwort ------------------------------------------------------------


def test_die_antwort_traegt_die_nachweise(klient, draht):
    """Laut README sind die Garantien das Produkt. Ein programmatischer
    Zugang, der nur das Bundle zurückgibt, liefert die falsche Hälfte."""
    daten = _erzeuge(klient).json()
    for feld in ("fertig", "bundle", "verstanden", "ressourcen", "validierung",
                 "integritaet", "beanstandungen", "befunde", "hinweis", "lauf"):
        assert feld in daten, feld
    assert daten["integritaet"]["ok"] is True
    assert "synthetisch" in daten["hinweis"].lower()


def test_die_aufzeichnung_laesst_sich_wiedergeben(klient, draht):
    """Der Zweck des Zugangs laut PRD ist CI/CD. Dort ist die Aufzeichnung
    der wertvollste Teil: Der erste Lauf kostet Token, jede Wiederholung
    ist umsonst."""
    from synthfhir import aufzeichnung as aufz

    daten = _erzeuge(klient).json()
    wieder = aufz.gib_wieder(aufz.Aufzeichnung.from_dict(daten["aufzeichnung"]))
    assert wieder.identisch, wieder.befund()


def test_ndjson_nur_auf_anforderung(klient, draht):
    ohne = _erzeuge(klient).json()
    assert "ndjson" not in ohne

    mit = _erzeuge(klient, ndjson=True).json()
    typen = {d["typ"] for d in mit["ndjson"]["dateien"]}
    assert "Patient" in typen
    for datei in mit["ndjson"]["dateien"]:
        assert datei["inhalt"].endswith("\n")


def test_ungeprueftes_bundle_heisst_nicht_bundle(klient, draht, monkeypatch):
    """US-2 AC2 auch hier: Ein Client, der stumpf `daten["bundle"]`
    schreibt, soll einen KeyError bekommen statt still ungeprüfte Daten
    weiterzureichen."""
    from synthfhir.validation import Befund

    echtes = api_modul.generiere

    def mit_befund(client, beschreibung, **kw):
        e = echtes(client, beschreibung, **kw)
        e.validierung[0].befunde.append(Befund("test", "künstlich"))
        return e

    monkeypatch.setattr(api_modul, "generiere", mit_befund)
    daten = _erzeuge(klient).json()
    assert daten["fertig"] is False
    assert "bundle" not in daten
    assert daten["bundle_zurueckgehalten"]["resourceType"] == "Bundle"


# --- Das Schema -------------------------------------------------------------


def test_das_schema_verraet_keine_formularfelder(klient):
    """`docs_url=None` schaltete nur die Oberfläche ab, nicht das Schema.
    Nachgemessen antwortete `/openapi.json` mit 200 und listete das
    Formularfeld `eigener_schluessel`."""
    assert klient.get("/openapi.json").status_code == 404
    schema = klient.get("/api/v1/openapi.json")
    assert schema.status_code == 200
    text = schema.text
    assert "eigener_schluessel" not in text
    # Die Eigenschaft, nicht die Liste: Hier stand einmal
    # `== ["/api/v1/erzeugen"]`, und der Test wurde rot, als eine zweite
    # API-Route dazukam — obwohl genau das erlaubt ist. Verboten ist,
    # dass eine Route der Weboberflaeche im Schema auftaucht.
    pfade = list(schema.json()["paths"])
    assert pfade, "das Schema ist leer"
    assert all(p.startswith("/api/v1/") for p in pfade), pfade
    for oberflaeche in ("/erzeugen", "/export", "/health", "/"):
        assert oberflaeche not in pfade


def test_das_schema_nennt_keine_paketversion(klient):
    """Eine unauthentifizierte GET beantwortete sonst „welche Version
    läuft"."""
    schema = klient.get("/api/v1/openapi.json").json()
    assert schema["info"]["version"] == "v1"


def test_der_schluesselwert_steht_nirgends_im_schema(klient):
    """Der NAME des Kopfes ist kein Geheimnis, nur sein Wert — und ein
    Schema, das Beispiele mitführte, wäre die Stelle, an der einer
    hineingerät."""
    text = klient.get("/api/v1/openapi.json").text
    assert BETREIBER_PLATZHALTER not in text
    assert AUFRUFER not in text


def test_der_gleichzeitigkeitsdeckel_greift_und_gibt_wieder_frei(
    klient, draht, monkeypatch
):
    """Ein Test gegen ein zurechtgelegtes `acquire` bewiese nur, dass die
    Abzweigung existiert. Hier laufen echte Threads gegen das echte
    Semaphor.

    Er faerbt sich rot bei zwei verschiedenen Fehlern: wenn der Deckel gar
    nicht greift (alle kommen durch), und wenn ein Platz nach dem Lauf
    nicht zurueckgegeben wird (spaetere Aufrufe bekommen 429, obwohl
    nichts mehr laeuft). Der zweite waere der stillere von beiden.
    """
    import threading
    import time

    monkeypatch.setattr(api_modul, "_plaetze", threading.BoundedSemaphore(2))
    losgelassen = threading.Event()
    echtes = api_modul.generiere

    def langsam(*args, **kw):
        losgelassen.wait(timeout=5)
        return echtes(*args, **kw)

    monkeypatch.setattr(api_modul, "generiere", langsam)

    codes: list[int] = []
    sperre = threading.Lock()

    def lauf():
        antwort = _erzeuge(klient)
        with sperre:
            codes.append(antwort.status_code)

    threads = [threading.Thread(target=lauf) for _ in range(5)]
    for t in threads:
        t.start()
    # Erst warten, bis die Abgewiesenen durch sind, dann die Blockierten
    # loslassen - sonst entscheidet der Zufall, wer welchen Platz bekommt.
    # Mit `sleep` und nicht als Leerlaufschleife: Eine solche Schleife
    # haelt den GIL und hungert genau die Threads aus, auf die sie wartet.
    # Der Test war damit gruen und trotzdem schlecht gebaut - beim
    # Gegenversuch mit entferntem Deckel lief er nicht mehr durch.
    frist = time.monotonic() + 10
    while len(codes) < 3 and time.monotonic() < frist:
        time.sleep(0.01)
    assert codes.count(429) == 3, f"der Deckel greift nicht: {codes}"
    losgelassen.set()
    for t in threads:
        t.join(timeout=10)
    assert codes.count(200) == 2, f"nicht beide Plaetze genutzt: {codes}"

    # Und jetzt der stille Fehler: Sind die Plaetze wieder frei?
    assert _erzeuge(klient).status_code == 200, "ein Platz wurde nicht freigegeben"


def test_das_schema_nennt_den_kopfnamen(klient):
    """Der NAME des Kopfes gehoert in die Dokumentation - nur sein WERT
    ist ein Geheimnis. Ohne ihn zeigte die Beschreibung keinen Weg, den
    Schluessel ueberhaupt mitzugeben, und waere damit unbrauchbar.

    Zusammen mit `test_der_schluesselwert_steht_nirgends_im_schema` haelt
    dieser Test beide Richtungen: Name ja, Wert nie.
    """
    dokument = klient.get("/api/v1/openapi.json").json()
    schema = dokument["components"]["securitySchemes"]["SynthFHIR-LLM-Key"]
    assert schema["in"] == "header"
    assert schema["name"] == KOPF
    assert dokument["paths"]["/api/v1/erzeugen"]["post"]["security"]


# --- Die Wiedergabe --------------------------------------------------------
#
# Der Endpunkt, der keinen Modellaufruf braucht — und genau deshalb der,
# ueber den ein Aufrufer die Parameterobjekte SELBST schreibt. Bei
# /erzeugen kommen sie vom Modell und sind durch max_tokens gedeckelt.


def _aufzeichnung(patienten, angefragt=1):
    """Eine Aufzeichnung mit EINEM Teil, ohne Pruefsumme."""
    return {
        "format_version": 1,
        "angefragt": angefragt,
        "beschreibung": "Testkohorte",
        "modell": "test",
        "erzeugt": "2026-09-01T00:00:00Z",
        "bundle_pruefsumme": "",
        "katalog_pruefsumme": "",
        "teile": [{"angefragt": angefragt, "parameter": {"patienten": patienten}}],
    }


def _wiedergabe(klient, aufzeichnung, schluessel=AUFRUFER):
    kopf = {KOPF: schluessel} if schluessel is not None else {}
    return klient.post(
        "/api/v1/wiedergeben", json={"aufzeichnung": aufzeichnung}, headers=kopf
    )


def test_wiedergabe_braucht_keinen_modellaufruf(klient, draht):
    """Der Grund, warum es diesen Endpunkt gibt: Der erste Lauf kostet
    Token, jede Wiederholung ist umsonst."""
    daten = _erzeuge(klient).json()
    assert len(draht.anfragen) == 1

    antwort = _wiedergabe(klient, daten["aufzeichnung"])
    assert antwort.status_code == 200, antwort.text
    ergebnis = antwort.json()
    assert ergebnis["identisch"] is True, ergebnis["befund"]
    assert ergebnis["lauf"]["modellaufrufe"] == 0
    assert len(draht.anfragen) == 1, "die Wiedergabe hat doch das Modell gefragt"


def test_wiedergabe_laeuft_ohne_schluessel(klient):
    """Diese Route ruft kein Modell auf und beruehrt kein Kontingent.

    Einen Schluessel zu verlangen haette hier nichts geschuetzt: Er wurde
    nie auf Gueltigkeit geprueft, jede druckbare Zeichenkette genuegte.
    Er einzusammeln haette also fremde Zugangsdaten aufgenommen, die
    niemand braucht.
    """
    antwort = _wiedergabe(klient, _aufzeichnung([{"vorname": "A"}]), schluessel=None)
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["lauf"]["modellaufrufe"] == 0


def test_jede_api_route_verlangt_einen_schluessel_ausser_der_wiedergabe(klient):
    """Die Regel, die den zweiten Router traegt.

    Sie geht ueber ALLE veroeffentlichten Routen, nicht ueber eine Liste,
    die jemand hier pflegen muesste. Kommt eine neue Route dazu und
    verlangt keinen Schluessel, faerbt sich dieser Test rot und zwingt zu
    einer bewussten Entscheidung.

    Gegengeprueft, mit zwei absichtlichen Fehlern:

    * Eine NEUE Route am offenen Router ohne jede Pruefung -> rot.
      Das ist der Fall, um den es geht.
    * `/erzeugen` an den offenen Router gehaengt -> **gruen**, und das ist
      richtig so: Diese Route traegt `Depends(pflicht_schluessel)` auch in
      ihrer Signatur, die Pruefung hielt also weiterhin. Der Test misst
      die Eigenschaft „verlangt einen Schluessel", nicht „haengt am
      richtigen Router" — und die erste ist die, auf die es ankommt.
    """
    OHNE_SCHLUESSEL = {"/api/v1/wiedergeben"}

    # Die Pfadliste kommt aus dem Schema, das die App selbst
    # veroeffentlicht — nicht aus FastAPI-Interna und nicht aus einer
    # Liste, die jemand hier pflegen muesste.
    pfade = klient.get("/api/v1/openapi.json").json()["paths"]
    gepruefte = 0
    for pfad, operationen in pfade.items():
        if "post" not in operationen:
            continue
        gepruefte += 1
        antwort = klient.post(pfad, json={})
        if pfad in OHNE_SCHLUESSEL:
            assert antwort.status_code != 401, f"{pfad} verlangt doch einen"
        else:
            assert antwort.status_code == 401, (
                f"{pfad} laesst ohne Schluessel durch (HTTP {antwort.status_code})"
            )
    assert gepruefte >= 2, f"nur {gepruefte} Routen gefunden"


def test_das_schema_sagt_die_wahrheit_ueber_den_schluessel(klient):
    """Ein Schema, das an der offenen Route eine Sicherheitsangabe
    behauptet, waere eine Falschauskunft — und umgekehrt."""
    pfade = klient.get("/api/v1/openapi.json").json()["paths"]
    assert pfade["/api/v1/erzeugen"]["post"]["security"]
    assert pfade["/api/v1/wiedergeben"]["post"]["security"] == []


def test_wiedergabe_braucht_keinen_erreichbaren_anbieter(klient, monkeypatch):
    """Das macht sie fuer eine Pruefkette wertvoll: Sie laeuft auch dann,
    wenn beim Betreiber gar kein Modell konfiguriert ist. Ein 503 kommt
    hier nie vor."""
    monkeypatch.delenv("SYNTHFHIR_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("SYNTHFHIR_LLM_MODEL", raising=False)
    antwort = _wiedergabe(klient, _aufzeichnung([{"vorname": "A", "nachname": "B"}]))
    assert antwort.status_code == 200


# --- Die drei gemessenen Verstaerkungen ------------------------------------


def test_ein_patient_mit_zwanzigtausend_messwerten_wird_abgelehnt(klient):
    """Gemessen ergab ein solcher Eintrag 20.001 Ressourcen. Abgelehnt,
    nicht gekappt: Eine gekappte Wiedergabe traefe auf die Pruefsumme des
    Originals und meldete ABWEICHUNG.

    5000 Messwerte und nicht 20.000, damit der Rumpf unter der
    Koerpergrenze bleibt — sonst pruefte dieser Test die Koerpergrenze
    und nicht die Grenze je Patient. Genau die Verwechslung, die einen
    Test gruen und wertlos macht.
    """
    viel = _aufzeichnung([{
        "vorname": "A", "nachname": "B",
        "messwerte": [{"code": "8867-4", "wert": 80}] * 5000,
    }])
    rumpf = len(json.dumps({"aufzeichnung": viel}))
    assert rumpf < api_modul.WIEDERGABE_KOERPER, f"Rumpf {rumpf} B ist zu gross"

    antwort = _wiedergabe(klient, viel)
    assert antwort.status_code == 413
    assert antwort.json()["fehlerart"] == "patient_zu_umfangreich"


def test_ein_zu_grosser_koerper_wird_vor_allem_anderen_abgewiesen(klient):
    """Und die andere Reihenfolge, damit beide Grenzen belegt sind."""
    riesig = _aufzeichnung([{
        "vorname": "A", "nachname": "B",
        "messwerte": [{"code": "8867-4", "wert": 80}] * 20000,
    }])
    antwort = _wiedergabe(klient, riesig)
    assert antwort.status_code == 413
    assert antwort.json()["fehlerart"] == "koerper_zu_gross"


def test_zweitausend_winzige_teile_werden_abgelehnt(klient):
    """Der Fall, gegen den jede Grenze JE AUFRUF blind ist: Jedes Teil
    fuer sich bleibt weit unter jeder Schranke. Deshalb gibt es eine
    eigene Zahl fuer die Teile."""
    teil = {"angefragt": 1, "parameter": {"patienten": [{"vorname": "A"}]}}
    viele = _aufzeichnung([{"vorname": "A"}])
    viele["teile"] = [teil] * 2000
    antwort = _wiedergabe(klient, viele)
    assert antwort.status_code == 413
    assert antwort.json()["fehlerart"] == "zu_viele_teile"


def test_zwanzigtausend_leere_eintraege_werden_abgelehnt(klient):
    """Vier Bytes JSON genuegen fuer einen vollstaendigen Patienten.
    Gegen diesen Fall hilft weder die Grenze je Patient (jeder Eintrag
    kostet genau eins) noch die Teilegrenze (ein Teil)."""
    antwort = _wiedergabe(klient, _aufzeichnung([{}] * 20000))
    assert antwort.status_code == 413
    assert antwort.json()["fehlerart"] == "zu_viele_ressourcen"


def test_abgelehnt_wird_bevor_gebaut_wird(klient):
    """Ein 413 nach getaner Arbeit waere wertlos. Gemessen kostet die
    Zaehlung 24 ms fuer 21.839 Eintraege, der Bau 20,9 Sekunden."""
    import time

    beginn = time.monotonic()
    antwort = _wiedergabe(klient, _aufzeichnung([{}] * 20000))
    gedauert = time.monotonic() - beginn
    assert antwort.status_code == 413
    assert gedauert < 2.0, f"die Ablehnung dauerte {gedauert:.1f}s — es wurde gebaut"


def test_eine_legitime_grosse_aufzeichnung_geht_durch(klient):
    """Die Gegenprobe. Ohne sie koennten die Grenzen beliebig scharf sein
    und jeder Ablehnungstest bliebe gruen."""
    patient = {
        "vorname": "Käthe", "nachname": "Schäfer", "geschlecht": "female",
        "geburtsdatum": "1970-01-01",
        "diagnosen": [{"code": "44054006", "beginn": "2020-01-01"}],
        "messwerte": [{"code": "8867-4", "wert": 80, "datum": "2023-01-01"}] * 3,
    }
    antwort = _wiedergabe(klient, _aufzeichnung([patient] * 25, angefragt=25))
    assert antwort.status_code == 200, antwort.text
    assert sum(antwort.json()["ressourcen"].values()) == 25 * 6


# --- Was nicht herauskommen darf -------------------------------------------


def test_die_wiedergabe_verraet_keine_rechenzeit(klient):
    """`dauer_s` waere hier eine Auslastungssonde: reine, vom Server
    gemessene Rechenzeit ueber eine vom Aufrufer frei gewaehlte,
    konstante Last — gratis und beliebig oft abfragbar."""
    daten = _wiedergabe(klient, _aufzeichnung([{"vorname": "A"}])).json()
    assert "dauer_s" not in json.dumps(daten)


def test_die_wiedergabe_behauptet_keine_schluesselherkunft(klient):
    """Das Feld ist die pruefbare Form der Zusage 'niemals auf Rechnung
    des Betreibers'. Hier entsteht kein Client — es auszugeben waere eine
    Aussage ueber einen Modellaufruf, den es nicht gab."""
    daten = _wiedergabe(klient, _aufzeichnung([{"vorname": "A"}])).json()
    assert "schluessel_herkunft" not in json.dumps(daten)
    assert daten["lauf"]["modellaufrufe"] == 0


def test_kein_aufruferwert_in_der_fehlermeldung(klient):
    """`int('GEHEIM-XY')` schrieb den Wert woertlich in die Ausnahme, und
    die wanderte ueber `AufzeichnungFehler` bis in den Antwortkoerper."""
    kaputt = _aufzeichnung([{"vorname": "A"}])
    kaputt["teile"] = [{"angefragt": "GEHEIM-XY", "parameter": {"patienten": []}}]
    antwort = _wiedergabe(klient, kaputt)
    assert antwort.status_code == 400
    assert "GEHEIM" not in antwort.text


def test_kein_fremdtext_der_validierungsbibliothek(klient):
    """`Befund.meldung` traegt den Text von pydantic beziehungsweise
    fhir.resources. Ausgeliefert wird nur der `pfad` — er stammt aus dem
    eigenen Modell."""
    daten = _wiedergabe(
        klient,
        _aufzeichnung([{"vorname": "A", "nachname": "B", "geburtsdatum": "kein Datum"}]),
    ).json()
    for eintrag in daten["validierung_ungueltig"]:
        assert set(eintrag) == {"ressourcentyp", "ressourcen_id", "pfade"}


def test_unfoermige_aufzeichnungen_ergeben_nie_einen_serverfehler(klient):
    """Vier Formen, die vorher abgestuerzt sind — davon zwei gemessen als
    HTTP 500."""
    proben = [
        {"aufzeichnung": "kein Objekt"},
        {"aufzeichnung": {"format_version": 99, "teile": [{}]}},
        {"aufzeichnung": {"format_version": 1, "teile": [42]}},
        {"aufzeichnung": {"format_version": 1,
                          "teile": [{"angefragt": 1, "parameter": "Text"}]}},
    ]
    for probe in proben:
        antwort = klient.post("/api/v1/wiedergeben", json=probe, headers={KOPF: AUFRUFER})
        assert 400 <= antwort.status_code < 500, (probe, antwort.status_code, antwort.text)


def test_tief_verschachtelter_koerper_ergibt_keinen_serverfehler(klient):
    """`json.loads` wirft ab rund 5000 Ebenen `RecursionError`, und der
    ist kein `ValueError`. Gemessen ergaben 60 KB Klammern HTTP 500 — auf
    beiden Routen, denn sie teilen sich `_lies_koerper`."""
    tief = (b"[" * 30000) + (b"]" * 30000)
    for pfad in ("/api/v1/erzeugen", "/api/v1/wiedergeben"):
        antwort = klient.post(
            pfad, content=tief,
            headers={KOPF: AUFRUFER, "Content-Type": "application/json"},
        )
        assert antwort.status_code == 400, (pfad, antwort.status_code)
        assert antwort.json()["fehlerart"] == "koerper_unlesbar"


def test_riesige_zahl_als_messwert_stuerzt_die_wiedergabe_nicht_ab(klient):
    """Eine Ganzzahl mit 400 Stellen ist ein `int` und kam durch die
    Typpruefung; `float()` warf darauf `OverflowError` mitten im Bauweg."""
    antwort = klient.post(
        "/api/v1/wiedergeben",
        content=json.dumps({"aufzeichnung": _aufzeichnung([{
            "vorname": "A", "nachname": "B",
            "messwerte": [{"code": "8867-4", "wert": int("9" * 400)}],
        }])}).encode(),
        headers={KOPF: AUFRUFER, "Content-Type": "application/json"},
    )
    assert antwort.status_code == 200, antwort.text
    assert any(
        b["art"] == "ungueltiger_messwert" for b in antwort.json()["beanstandungen"]
    )


def test_infinity_als_messwert_laesst_sich_ausliefern(klient):
    """`json.loads` liest `Infinity`, Starlettes Renderer lehnt es ab —
    die Ressource entstand, und erst das Ausliefern scheiterte mit 500."""
    antwort = klient.post(
        "/api/v1/wiedergeben",
        content=b'{"aufzeichnung": {"format_version": 1, "angefragt": 1, "teile": '
                b'[{"angefragt": 1, "parameter": {"patienten": [{"vorname": "A", '
                b'"messwerte": [{"code": "8867-4", "wert": Infinity}]}]}}]}}',
        headers={KOPF: AUFRUFER, "Content-Type": "application/json"},
    )
    assert antwort.status_code == 200, antwort.text


def test_der_gleichzeitigkeitsdeckel_der_wiedergabe_ist_ein_eigener(klient, monkeypatch):
    """Geteilt verdraengten die billigen Wiedergaben die teuren
    Erzeugungen, und die 429 sagte nicht mehr, welche Grenze griff."""
    monkeypatch.setattr(
        api_modul._wiedergabeplaetze, "acquire", lambda blocking=True: False
    )
    antwort = _wiedergabe(klient, _aufzeichnung([{"vorname": "A"}]))
    assert antwort.status_code == 429
    assert antwort.json()["quelle"] == "synthfhir"
    assert antwort.headers.get("Retry-After")


# --- Szenarien (ADR-016) ---------------------------------------------------
#
# Wie /wiedergeben ohne Schluessel, aber mit einem entscheidenden
# Unterschied: Der Inhalt kommt aus dem KATALOG, nicht aus dem
# Anfragekoerper. Deshalb fehlen hier die Grenzen, die dort noetig sind -
# und das gehoert belegt, nicht behauptet.


def test_szenarienliste_laeuft_ohne_schluessel(klient, draht):
    a = klient.get("/api/v1/szenarien")
    assert a.status_code == 200
    namen = [s["name"] for s in a.json()["szenarien"]]
    assert "diabetes-ambulanz" in namen
    assert draht.anfragen == [], "keine einzige Anfrage ging hinaus"


def test_szenarienliste_nennt_was_zur_auswahl_noetig_ist(klient):
    """Ohne `zeigt` und `patienten` muesste man jedes bauen, um zu
    erfahren, was drinsteht."""
    for s in klient.get("/api/v1/szenarien").json()["szenarien"]:
        assert set(s) == {"name", "titel", "beschreibung", "zeigt", "patienten"}
        assert s["zeigt"] and isinstance(s["patienten"], int)


def test_szenario_baut_ohne_schluessel_und_ohne_modell(klient, draht):
    """Der ganze Zweck: eine geprüfte Kohorte, die niemanden etwas kostet."""
    a = klient.get("/api/v1/szenarien/diabetes-ambulanz")
    assert a.status_code == 200
    d = a.json()
    assert d["fertig"] is True
    assert d["ressourcen"]["Patient"] == 3
    assert d["lauf"]["modellaufrufe"] == 0
    assert d["bundle"]["resourceType"] == "Bundle"
    assert draht.anfragen == []


def test_szenario_nennt_sich_in_der_antwort(klient):
    """Sonst saehe sie aus wie die eines Modelllaufs."""
    d = klient.get("/api/v1/szenarien/ohne-kontakt").json()
    assert d["szenario"]["name"] == "ohne-kontakt"
    assert d["szenario"]["zeigt"]


def test_szenarioantwort_traegt_keine_pruefsumme(klient):
    """Eine Prüfsumme ist die Zusage einer Aufzeichnung („dasselbe wie
    damals"). Ein Szenario sagt „eine Diabetes-Kohorte" — es soll nach
    einer Katalogverbesserung die NEUE Ausgabe liefern."""
    d = klient.get("/api/v1/szenarien/diabetes-ambulanz").json()
    assert "pruefsummen" not in d
    assert "identisch" not in d


def test_szenarioantwort_gibt_keine_fremdtexte_zurueck(klient):
    """Dieselbe Regel wie ueberall in diesem Modul: Meldungen von pydantic
    und `fhir.resources` erreichen den Antwortkoerper nie."""
    d = klient.get("/api/v1/szenarien/labor-grundprofil").json()
    for eintrag in d["validierung_ungueltig"]:
        assert set(eintrag) == {"ressourcentyp", "ressourcen_id", "pfade"}
    assert "dauer_s" not in d
    assert "schluessel_herkunft" not in d


def test_unbekanntes_szenario_gibt_404_ohne_den_namen(klient):
    a = klient.get("/api/v1/szenarien/GEHEIM-XYZ-MARKER")
    assert a.status_code == 404
    assert a.json()["fehlerart"] == "unbekanntes_szenario"
    assert a.json()["quelle"] == "aufrufer"
    assert "GEHEIM" not in a.text and "MARKER" not in a.text
    assert "diabetes-ambulanz" in a.text, "die bekannten Namen helfen weiter"


def test_szenario_gibt_bei_gleichem_namen_immer_dasselbe(klient):
    """Ohne das waere es keine Vorlage."""
    a = klient.get("/api/v1/szenarien/blutdruck-kontrolle").json()["bundle"]
    b = klient.get("/api/v1/szenarien/blutdruck-kontrolle").json()["bundle"]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_szenarien_stehen_im_schema_als_schluessellos(klient):
    """Ohne `security: []` erbten sie die Angabe der App und behaupteten
    einen Schluessel, den sie nicht verlangen."""
    pfade = klient.get("/api/v1/openapi.json").json()["paths"]
    for pfad in ("/api/v1/szenarien", "/api/v1/szenarien/{name}"):
        assert pfade[pfad]["get"]["security"] == [], pfad


def test_die_ui_route_bleibt_aus_dem_schema(klient):
    """`/szenario/{name}` gehoert der Weboberflaeche. Sie liefert HTML und
    hat im Schema des programmatischen Zugangs nichts zu suchen."""
    pfade = list(klient.get("/api/v1/openapi.json").json()["paths"])
    assert not [p for p in pfade if p.startswith("/szenario")]


def test_jedes_szenario_ist_ueber_die_api_baubar(klient):
    """Die Liste und der Bau duerfen nicht auseinanderlaufen: Ein Name in
    der Liste, der 404 gibt, waere schlimmer als ein fehlender."""
    for s in klient.get("/api/v1/szenarien").json()["szenarien"]:
        a = klient.get(f"/api/v1/szenarien/{s['name']}")
        assert a.status_code == 200, s["name"]
        assert a.json()["ressourcen"]["Patient"] == s["patienten"]
