"""Tests des Server-Pushs.

Dies ist der einzige Teil des Produkts, der in ein **fremdes System**
schreibt. Die Tests prüfen deshalb weniger, dass er schreibt, als dass er
es **unterlässt**, wenn etwas nicht stimmt: falsches Ziel, fremde Daten,
fehlendes Kennzeichen, unvollständige Kohorte.
"""

from __future__ import annotations

import json

import pytest
import requests

from synthfhir.domain import assign_ids, baue_aus_parametern
from synthfhir.domain.codes import TESTDATEN_LABEL
from synthfhir.push import (
    TOKEN_VARIABLE,
    UNSINNSLABEL,
    Zielbefund,
    baue_transaktion,
    befrage_ziel,
    pushe,
)


def kohorte(n: int = 3) -> list[dict]:
    p = {"patienten": [{
        "vorname": f"V{i}", "nachname": "Müller", "geschlecht": "female",
        "geburtsdatum": "1955-03-17",
        "begegnungen": [{"art": "AMB", "datum": "2024-06-01"}],
        "diagnosen": [{"code": "44054006", "beginn": "2015-01-01"}],
        "messwerte": [{"code": "4548-4", "wert": 7.4, "datum": "2024-06-01"}],
        "medikamente": [{"code": "A10BA02", "beginn": "2015-02-01"}],
    } for i in range(n)]}
    return assign_ids(baue_aus_parametern(p).ressourcen).resources


class StubAntwort:
    def __init__(self, status=200, koerper=None, text=""):
        self.status_code = status
        self._koerper = koerper
        self.text = text or json.dumps(koerper or {})

    def json(self):
        if self._koerper is None:
            raise ValueError("kein JSON")
        return self._koerper


class StubSitzung:
    """Ein Zielserver, der sich beliebig verhalten lässt — ohne Netz.

    Bildet ausdrücklich einen Server nach, der `_security` **beachtet**:
    Auf ein Label, das es nicht gibt, antwortet er mit null. Das ist keine
    Feinheit — der Wächter erkennt genau daran, ob die Auskunft des Servers
    überhaupt etwas wert ist.
    """

    def __init__(self, gesamt=0, mit_label=0, metadata=True, post_status=200):
        self.gesamt, self.mit_label = gesamt, mit_label
        self.metadata, self.post_status = metadata, post_status
        self.headers: dict = {}
        self.posts: list[dict] = []

    def get(self, url, params=None, timeout=None):
        if url.endswith("/metadata"):
            if not self.metadata:
                return StubAntwort(404, {"resourceType": "OperationOutcome"})
            return StubAntwort(200, {"resourceType": "CapabilityStatement",
                                     "fhirVersion": "4.0.1"})
        params = params or {}
        if "_security" not in params:
            n = self.gesamt
        elif params["_security"] == UNSINNSLABEL:
            n = 0                      # ein Server, der den Filter beachtet
        else:
            n = self.mit_label
        return StubAntwort(200, {"resourceType": "Bundle", "total": n})

    def post(self, url, data=None, timeout=None):
        self.posts.append(json.loads(data.decode("utf-8")))
        if self.post_status >= 400:
            return StubAntwort(self.post_status, None, text="Fehler vom Server")
        return StubAntwort(200, {"resourceType": "Bundle", "type": "transaction-response"})


@pytest.fixture
def ziel(monkeypatch):
    """Ein leerer, ansprechbarer Zielserver."""
    s = StubSitzung(gesamt=0, mit_label=0)
    monkeypatch.setattr("synthfhir.push._sitzung", lambda token: s)
    return s


# --- Der Trockenlauf ist die Voreinstellung --------------------------------


def test_ohne_ausfuehren_wird_nichts_geschrieben(ziel):
    """Die wichtigste Zusage dieses Moduls: Ein Tippfehler in der URL soll
    sichtbar werden, bevor er wirkt."""
    e = pushe(kohorte(), "http://ziel/fhir")
    assert e.trockenlauf
    assert e.geschrieben == 0
    assert ziel.posts == [], "es darf keine einzige Anfrage abgesetzt werden"
    assert e.pakete == 1, "berichtet trotzdem, was geschähe"


def test_mit_ausfuehren_wird_geschrieben(ziel):
    e = pushe(kohorte(), "http://ziel/fhir", ausfuehren=True)
    assert not e.trockenlauf
    assert e.geschrieben == 15
    assert len(ziel.posts) == 1


# --- Der Wächter gegen fremde Daten ----------------------------------------


def test_fremde_daten_verhindern_den_push(monkeypatch):
    """Liegen auf dem Ziel Patienten ohne Testkennzeichen, könnte es ein
    produktives System sein."""
    s = StubSitzung(gesamt=500, mit_label=0)
    monkeypatch.setattr("synthfhir.push._sitzung", lambda token: s)

    e = pushe(kohorte(), "http://ziel/fhir", ausfuehren=True)
    assert e.geschrieben == 0
    assert s.posts == []
    assert "könnte ein produktives System sein" in e.fehler[0]


def test_freigabe_hebt_die_sperre_auf(monkeypatch):
    s = StubSitzung(gesamt=500, mit_label=0)
    monkeypatch.setattr("synthfhir.push._sitzung", lambda token: s)
    e = pushe(kohorte(), "http://ziel/fhir", ausfuehren=True, fremde_daten_ok=True)
    assert e.geschrieben == 15


def test_nur_eigene_testdaten_sind_unverdaechtig(monkeypatch):
    s = StubSitzung(gesamt=42, mit_label=42)
    monkeypatch.setattr("synthfhir.push._sitzung", lambda token: s)
    e = pushe(kohorte(), "http://ziel/fhir", ausfuehren=True)
    assert e.fehler == []
    assert e.geschrieben == 15


def test_unbekannter_bestand_gilt_als_verdaechtig(monkeypatch):
    """Wer nicht sagen kann, was auf dem Ziel liegt, sollte nicht
    hineinschreiben. Schweigen ist keine Freigabe."""
    class Stumm(StubSitzung):
        def get(self, url, params=None, timeout=None):
            if url.endswith("/metadata"):
                return super().get(url, params, timeout)
            return StubAntwort(403, None, text="verboten")

    s = Stumm()
    monkeypatch.setattr("synthfhir.push._sitzung", lambda token: s)
    befund = befrage_ziel("http://ziel/fhir")
    assert befund.ressourcen_gesamt is None
    assert befund.fremde_daten, "unbekannt heißt verdächtig"

    e = pushe(kohorte(), "http://ziel/fhir", ausfuehren=True)
    assert e.geschrieben == 0
    assert "lässt sich der Bestand nicht ermitteln" in e.fehler[0]


# --- Das Ziel muss ein FHIR-Server sein ------------------------------------


def test_kein_fhir_server(monkeypatch):
    s = StubSitzung(metadata=False)
    monkeypatch.setattr("synthfhir.push._sitzung", lambda token: s)
    e = pushe(kohorte(), "http://irgendwas", ausfuehren=True)
    assert e.geschrieben == 0
    assert s.posts == []


def test_nicht_erreichbares_ziel(monkeypatch):
    class Tot(StubSitzung):
        def get(self, url, params=None, timeout=None):
            raise requests.exceptions.ConnectionError("Name nicht auflösbar")

    monkeypatch.setattr("synthfhir.push._sitzung", lambda token: Tot())
    e = pushe(kohorte(), "http://tippfehler/fhir", ausfuehren=True)
    assert e.geschrieben == 0
    assert "nicht erreichbar" in " ".join(e.fehler)


def test_metadata_ohne_capabilitystatement(monkeypatch):
    class Falsch(StubSitzung):
        def get(self, url, params=None, timeout=None):
            if url.endswith("/metadata"):
                return StubAntwort(200, {"resourceType": "Patient"})
            return super().get(url, params, timeout)

    monkeypatch.setattr("synthfhir.push._sitzung", lambda token: Falsch())
    e = pushe(kohorte(), "http://ziel/fhir", ausfuehren=True)
    assert e.geschrieben == 0


# --- Kennzeichnung ---------------------------------------------------------


def test_ressourcen_ohne_testkennzeichen_werden_abgewiesen(ziel):
    """Nicht nachrüsten, sondern abbrechen: Wenn hier etwas ohne
    Kennzeichen ankommt, stimmt weiter oben etwas nicht."""
    res = kohorte()
    res[0].pop("meta")
    e = pushe(res, "http://ziel/fhir", ausfuehren=True)
    assert e.geschrieben == 0
    assert ziel.posts == []
    assert "ohne Testdaten-Kennzeichen" in e.fehler[0]


def test_ein_fremdes_label_zaehlt_nicht_als_kennzeichen(ziel):
    """Der Code allein genügt nicht — das System gehört dazu. Ohne diese
    Strenge hielte der Push ein HTEST aus einem anderen System für das
    eigene."""
    res = kohorte()
    res[0]["meta"]["security"] = [
        {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
         "code": "HTEST"}
    ]
    e = pushe(res, "http://ziel/fhir", ausfuehren=True)
    assert e.geschrieben == 0


def test_jede_erzeugte_ressource_traegt_das_kennzeichen():
    for r in kohorte(2):
        security = r["meta"]["security"]
        assert TESTDATEN_LABEL in security, r["resourceType"]


# --- Form der Übertragung --------------------------------------------------


def test_transaktion_benutzt_put_und_ist_damit_idempotent():
    """POST legte bei jedem Lauf neue Ressourcen an. Die Kennungen kommen
    aus diesem Projekt, also ist PUT richtig."""
    tx = baue_transaktion(kohorte(1))
    assert tx["type"] == "transaction"
    for eintrag in tx["entry"]:
        assert eintrag["request"]["method"] == "PUT"
        r = eintrag["resource"]
        assert eintrag["request"]["url"] == f"{r['resourceType']}/{r['id']}"


def test_referenzierte_typen_kommen_zuerst(ziel):
    e = pushe(kohorte(), "http://ziel/fhir", ausfuehren=True)
    assert e.reihenfolge[0] == "Patient"
    assert e.reihenfolge.index("Encounter") < e.reihenfolge.index("Condition")


def test_grosse_kohorten_werden_paketiert(ziel):
    e = pushe(kohorte(20), "http://ziel/fhir", ausfuehren=True, paketgroesse=25)
    assert e.pakete == 4          # 100 Ressourcen zu je 25
    assert len(ziel.posts) == 4
    assert e.geschrieben == 100


def test_paketierung_zerreisst_die_reihenfolge_nicht(ziel):
    """Auch über Paketgrenzen hinweg müssen die Patienten vor allem
    kommen, was auf sie zeigt."""
    pushe(kohorte(20), "http://ziel/fhir", ausfuehren=True, paketgroesse=25)
    typen = [e["resource"]["resourceType"]
             for paket in ziel.posts for e in paket["entry"]]
    assert typen.index("Condition") > max(
        i for i, t in enumerate(typen) if t == "Patient"
    ), "alle Patienten vor der ersten Diagnose"


# --- Wenn es schiefgeht ----------------------------------------------------


def test_fehler_bricht_ab_statt_weiterzumachen(monkeypatch):
    """Transaktionen sind atomar — das fehlgeschlagene Paket ist
    zurückgerollt. Weiterzumachen hinterließe eine Lücke mitten in der
    Kohorte."""
    s = StubSitzung(post_status=400)
    monkeypatch.setattr("synthfhir.push._sitzung", lambda token: s)
    e = pushe(kohorte(20), "http://ziel/fhir", ausfuehren=True, paketgroesse=25)
    assert len(s.posts) == 1, "nach dem ersten Fehler ist Schluss"
    assert e.geschrieben == 0
    assert "HTTP 400" in e.fehler[0]


def test_leere_kohorte(ziel):
    e = pushe([], "http://ziel/fhir", ausfuehren=True)
    assert e.fehler
    assert ziel.posts == []


# --- Geheimnisse -----------------------------------------------------------


def test_token_kommt_aus_der_umgebung(monkeypatch):
    """Ausdrücklich kein Kommandozeilenargument: Argumente stehen in der
    Shell-Historie und in der Prozessliste."""
    monkeypatch.setenv(TOKEN_VARIABLE, "geheim-123")
    gesehen = {}

    def merken(token):
        gesehen["token"] = token
        return StubSitzung()

    monkeypatch.setattr("synthfhir.push._sitzung", merken)
    pushe(kohorte(1), "http://ziel/fhir", ausfuehren=True)
    assert gesehen["token"] == "geheim-123"


def test_token_landet_nicht_in_fehlermeldungen(monkeypatch):
    """Ein Token, das einmal in einem Bericht steht, ist nicht mehr
    geheim."""
    monkeypatch.setenv(TOKEN_VARIABLE, "geheim-123")

    class Petzt(StubSitzung):
        def post(self, url, data=None, timeout=None):
            raise requests.exceptions.ConnectionError(
                "Fehler bei Authorization: Bearer geheim-123"
            )

    monkeypatch.setattr("synthfhir.push._sitzung", lambda token: Petzt())
    e = pushe(kohorte(1), "http://ziel/fhir", ausfuehren=True)
    zusammen = json.dumps(e.to_dict(), ensure_ascii=False) + " ".join(e.fehler)
    assert "geheim-123" not in zusammen
    assert "<Token entfernt>" in " ".join(e.fehler)


def test_bericht_enthaelt_kein_token(monkeypatch):
    monkeypatch.setenv(TOKEN_VARIABLE, "geheim-123")
    s = StubSitzung()
    monkeypatch.setattr("synthfhir.push._sitzung", lambda token: s)
    e = pushe(kohorte(1), "http://ziel/fhir", ausfuehren=True)
    assert "geheim" not in json.dumps(e.to_dict(), ensure_ascii=False)


# --- Gegen den echten Server -----------------------------------------------


def test_push_gegen_echten_server(hapi, monkeypatch):
    """Der Nachweis, der zählt: Die Kohorte landet wirklich im Server, und
    die Verweise lösen sich dort auf."""
    import requests as r

    basis = "http://localhost:8080/fhir"
    res = kohorte(2)
    # Eigene Kennungen, damit der Test nicht mit anderen Läufen kollidiert.
    for x in res:
        x["id"] = f"pt-{x['id']}"
    for x in res:
        for feld in ("subject", "encounter"):
            if isinstance(x.get(feld), dict):
                typ, kennung = x[feld]["reference"].split("/")
                x[feld]["reference"] = f"{typ}/pt-{kennung}"

    e = pushe(res, basis, ausfuehren=True, fremde_daten_ok=True)
    assert e.fehler == [], e.fehler
    assert e.geschrieben == len(res)

    s = r.Session()
    s.headers["Accept"] = "application/fhir+json"
    gelesen = s.get(f"{basis}/Patient/pt-pat-001", timeout=60)
    assert gelesen.status_code == 200
    assert gelesen.json()["meta"]["security"][0]["code"] == "HTEST"


# --- Nachgestellte Befunde -------------------------------------------------


def test_server_der_security_ignoriert_gilt_als_verdaechtig(monkeypatch):
    """Der gefährlichste Fehler dieses Moduls, nachgestellt.

    Ein FHIR-Server darf einen unbekannten Suchparameter stillschweigend
    ignorieren — gemessen: Beide geprüften Server liefern auf einen
    erfundenen Parameter die volle Trefferzahl. Beachtet das Ziel
    `_security` nicht, sind beide Zahlen gleich groß, und der Wächter
    hielte einen Server voller echter Patienten für einen leeren
    Testserver. Er versagte nach der falschen Seite.
    """
    class Ignoriert(StubSitzung):
        def get(self, url, params=None, timeout=None):
            if url.endswith("/metadata"):
                return super().get(url, params, timeout)
            # Filter wird ignoriert: immer die volle Zahl.
            return StubAntwort(200, {"resourceType": "Bundle", "total": 8252})

    s = Ignoriert()
    monkeypatch.setattr("synthfhir.push._sitzung", lambda token: s)

    befund = befrage_ziel("http://produktiv/fhir")
    assert befund.security_filter_wirkt is False
    assert befund.fremde_daten, "gleich große Zahlen dürfen nicht beruhigen"

    e = pushe(kohorte(), "http://produktiv/fhir", ausfuehren=True)
    assert e.geschrieben == 0
    assert s.posts == []


def test_gegenprobe_erkennt_einen_wirksamen_filter(monkeypatch):
    """Ein Server, der auf ein erfundenes Label null liefert, beachtet den
    Filter — und erst dann sagt seine HTEST-Zahl etwas aus."""
    s = StubSitzung(gesamt=42, mit_label=42)
    monkeypatch.setattr("synthfhir.push._sitzung", lambda token: s)
    befund = befrage_ziel("http://ziel/fhir")
    assert befund.security_filter_wirkt is True
    assert not befund.fremde_daten


@pytest.mark.parametrize("ressource", [
    {"resourceType": "../Binary", "id": "x"},
    {"resourceType": "Patient/x", "id": "y"},
    {"resourceType": "Patient", "id": "../evil"},
    {"resourceType": "Patient", "id": ""},
    {"resourceType": "", "id": "x"},
])
def test_typ_und_kennung_kommen_nicht_ungeprueft_in_den_url_pfad(ressource, ziel):
    """Beide wandern in den URL-Pfad der Transaktion. Ein `resourceType`
    von "../Binary" schriebe an eine andere Stelle des Servers."""
    from synthfhir.push import PushFehler

    with pytest.raises(PushFehler):
        baue_transaktion([ressource])

    ressource = dict(ressource, meta={"security": [dict(TESTDATEN_LABEL)]})
    e = pushe([ressource], "http://ziel/fhir", ausfuehren=True)
    assert e.geschrieben == 0
    assert ziel.posts == [], "nichts gesendet, auch kein erstes Paket"


def test_pruefung_laeuft_vor_dem_ersten_paket(monkeypatch):
    """Eine kaputte Ressource im letzten Paket darf die ersten nicht schon
    auf den Server gebracht haben."""
    s = StubSitzung()
    monkeypatch.setattr("synthfhir.push._sitzung", lambda token: s)
    res = kohorte(20)
    res[-1]["resourceType"] = "../Binary"
    e = pushe(res, "http://ziel/fhir", ausfuehren=True, paketgroesse=10)
    assert s.posts == [], "kein einziges Paket unterwegs"
    assert e.geschrieben == 0


def test_testlabel_wirkt_im_katalog_fingerabdruck(monkeypatch):
    """Das Kennzeichen steht in jeder Ressource, ändert also jedes Bundle.
    Fehlte es im Fingerabdruck, meldete eine Wiedergabe zwar die
    Abweichung, benannte aber den Katalog als unverändert."""
    from synthfhir import aufzeichnung as aufz

    vorher = aufz.katalog_pruefsumme()
    monkeypatch.setattr(aufz, "FESTE_WERTE", ("anders",))
    assert aufz.katalog_pruefsumme() != vorher
