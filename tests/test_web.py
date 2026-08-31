"""Tests der Weboberfläche.

Kein Netz: Der LLM-Client wird durch eine feste Antwort ersetzt. Geprüft
wird, was der Nutzer tatsächlich zu sehen bekommt — vor allem, dass die
Zusage nicht nur intern stimmt, sondern auch auf der Seite ankommt.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from synthfhir.web import app
from synthfhir.web import oberflaeche as app_modul
from synthfhir.llm import FesterClient, LLMFehler


@pytest.fixture(autouse=True)
def bremse_zuruecksetzen():
    """Jeder Test beginnt mit leerer Ratenbremse.

    Ohne das teilen sich alle Tests dieselbe Kennung ("testclient") und
    laufen ab dem sechsten POST in die Bremse - was beim ersten Lauf auch
    prompt passiert ist.
    """
    app_modul.BREMSE.zuruecksetzen()
    yield
    app_modul.BREMSE.zuruecksetzen()


@pytest.fixture
def klient() -> TestClient:
    return TestClient(app)


def _antwort(patienten: list[dict] | None = None, luecken: list[str] | None = None) -> str:
    return json.dumps(
        {
            "verstanden": {
                "anzahl_patienten": 1,
                "kernkriterien": ["Diabetes mellitus Typ 2"],
                "nicht_abbildbar": luecken or [],
            },
            "patienten": patienten
            or [
                {
                    "vorname": "Ingrid",
                    "nachname": "Baumgartner",
                    "geschlecht": "female",
                    "geburtsdatum": "1958-03-14",
                    "diagnosen": [{"code": "44054006", "beginn": "2012-05-01"}],
                    "messwerte": [{"code": "4548-4", "wert": 7.8, "datum": "2024-01-15"}],
                }
            ],
        },
        ensure_ascii=False,
    )


def _mit_fester_antwort(monkeypatch, text: str) -> None:
    monkeypatch.setattr(app_modul, "client_aus_umgebung", lambda: FesterClient(text))


# --- Startseite ------------------------------------------------------------


def test_startseite_zeigt_das_formular(klient):
    antwort = klient.get("/")
    assert antwort.status_code == 200
    assert 'name="beschreibung"' in antwort.text


def test_hinweis_auf_synthetische_daten_ist_immer_sichtbar(klient):
    """Auflage aus PRD Block 6 und 7: Kennzeichnungspflicht im Produkt.

    Der Hinweis steht im Grundgerüst der Seite, nicht nur im Ergebnis — er
    muss auch dann dastehen, wenn noch gar nichts erzeugt wurde.
    """
    text = klient.get("/").text
    assert "nicht für die klinische Nutzung" in text
    assert "Synthetische Testdaten" in text


def test_gesundheitsendpunkt(klient):
    assert klient.get("/health").text == "ok"


# --- Erzeugung -------------------------------------------------------------


def test_erfolgreiche_erzeugung_zeigt_vorschau_und_status(klient, monkeypatch):
    _mit_fester_antwort(monkeypatch, _antwort())
    antwort = klient.post("/erzeugen", data={"beschreibung": "Eine Diabetikerin über 60"})

    assert antwort.status_code == 200
    text = antwort.text
    assert "Valide gegen FHIR R4" in text
    assert "Ingrid Baumgartner" in text          # lesbare Vorschau, US-6
    assert "Diabetes mellitus Typ 2" in text
    assert "HbA1c" in text                        # deutscher Anzeigetext
    assert "So wurde deine Anfrage gelesen" in text


def test_beide_kodierungen_erscheinen_in_der_vorschau(klient, monkeypatch):
    """ADR-003 soll für den Nutzer sichtbar sein, nicht nur im JSON."""
    _mit_fester_antwort(monkeypatch, _antwort())
    text = klient.post("/erzeugen", data={"beschreibung": "Diabetes"}).text
    assert "SNOMED 44054006" in text
    assert "ICD-10-GM E11.90" in text


def test_nicht_abbildbare_kriterien_werden_angezeigt(klient, monkeypatch):
    """Der Befund aus der ersten Messung: Der Nutzer muss erfahren, wenn
    seine Anfrage nicht vollständig abgedeckt werden konnte."""
    _mit_fester_antwort(monkeypatch, _antwort(luecken=["Vitamin-D-Wert — kein Code im Katalog"]))
    text = klient.post("/erzeugen", data={"beschreibung": "Vitamin D"}).text
    assert "Nicht abbildbar" in text
    assert "Vitamin-D-Wert" in text


def test_die_beschreibung_bleibt_im_formular_stehen(klient, monkeypatch):
    _mit_fester_antwort(monkeypatch, _antwort())
    text = klient.post("/erzeugen", data={"beschreibung": "Drei Patienten mit Asthma"}).text
    assert "Drei Patienten mit Asthma" in text


def test_fehlgeschlagene_erzeugung_erklaert_sich(klient, monkeypatch):
    _mit_fester_antwort(monkeypatch, "Das kann ich nicht liefern.")
    antwort = klient.post("/erzeugen", data={"beschreibung": "Irgendwas"})
    assert antwort.status_code == 200
    assert "Das hat nicht geklappt" in antwort.text
    assert "kein gültiges JSON" in antwort.text


def test_konfigurationsfehler_wird_vom_nutzerfehler_getrennt(klient, monkeypatch):
    """Ein fehlender Modellname ist ein Problem des Betreibers. Der Nutzer
    soll das als solches erkennen und nicht seine Anfrage umformulieren."""

    def kaputt():
        raise LLMFehler("SYNTHFHIR_LLM_MODEL ist nicht gesetzt.")

    monkeypatch.setattr(app_modul, "client_aus_umgebung", kaputt)
    antwort = klient.post("/erzeugen", data={"beschreibung": "Egal"})
    assert antwort.status_code == 503
    assert "nicht einsatzbereit" in antwort.text
    assert "SYNTHFHIR_LLM_MODEL" in antwort.text


# --- Export ----------------------------------------------------------------


def test_download_liefert_eine_fhir_datei(klient):
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": []}
    antwort = klient.post(
        "/export", data={"bundle": json.dumps(bundle), "dateiname": "test.json"}
    )
    assert antwort.status_code == 200
    assert antwort.headers["content-type"].startswith("application/fhir+json")
    assert 'filename="test.json"' in antwort.headers["content-disposition"]
    assert json.loads(antwort.text)["resourceType"] == "Bundle"


def test_download_weist_unbrauchbaren_inhalt_ab(klient):
    antwort = klient.post("/export", data={"bundle": "kein json"})
    assert antwort.status_code == 400


def test_dateiname_wird_entschaerft(klient):
    """Der Name kommt aus dem Formular und darf nicht in den Pfad wirken."""
    antwort = klient.post(
        "/export",
        data={"bundle": json.dumps({"resourceType": "Bundle"}),
              "dateiname": "../../etc/passwd"},
    )
    assert antwort.status_code == 200
    kopf = antwort.headers["content-disposition"]
    assert ".." not in kopf and "/" not in kopf.split("filename=")[1]
    assert kopf.endswith('.json"'), "Die Endung setzt der Server, nicht der Nutzer"


def test_download_ist_gesperrt_solange_die_pruefung_nicht_durchgeht(klient, monkeypatch):
    """US-2 AC2: Was die Prüfung nicht besteht, wird nicht als fertig
    ausgegeben — und darf folglich auch nicht anklickbar sein."""
    from synthfhir.generation import Ergebnis
    from synthfhir.validation import Befund

    echtes_generiere = app_modul.generiere

    def mit_befund(client, beschreibung, **kw) -> Ergebnis:
        e = echtes_generiere(client, beschreibung, **kw)
        e.validierung[0].befunde.append(Befund("test", "künstlich"))
        return e

    _mit_fester_antwort(monkeypatch, _antwort())
    monkeypatch.setattr(app_modul, "generiere", mit_befund)
    text = klient.post("/erzeugen", data={"beschreibung": "Eine Patientin"}).text

    assert "Nicht ausgelieferbar" in text
    assert "disabled" in text
    assert "Die Datenausgabe ist gesperrt" in text

    # Beide Datenausgaben sind gesperrt, nicht nur die erste. Der zweite
    # Knopf kam später dazu, und ein Knopf, an den beim Sperren niemand
    # gedacht hat, ist genau die Lücke, die diese Zusage aushöhlt.
    for wert in ('value="json"', 'value="ndjson"'):
        stelle = text.index(wert)
        assert "disabled" in text[stelle:stelle + 120], f"{wert} nicht gesperrt"

    # Die Aufzeichnung dagegen bleibt: Sie ist die EINGABE des Laufs, und
    # gerade ein misslungener Lauf soll ohne neuen Modellaufruf
    # wiederholbar sein.
    stelle = text.index('value="aufzeichnung"')
    assert "disabled" not in text[stelle:stelle + 120]


def test_head_wird_beantwortet(klient):
    """Hosting-Anbieter prüfen die Erreichbarkeit oft mit HEAD. Ein 405
    liest sich für sie wie ein Ausfall - beim ersten lokalen Start stand
    genau das im Log.
    """
    assert klient.head("/").status_code == 200
    assert klient.head("/health").status_code == 200


def test_favicon_erzeugt_keinen_zweiten_request(klient):
    """Inline als Data-URI, damit weder ein Request noch ein 404 anfällt."""
    text = klient.get("/").text
    assert 'rel="icon"' in text
    assert "data:image/svg+xml" in text


# --- Demo-Betrieb: Ratenbremse und eigener Schlüssel ------------------------


def test_bremse_greift_nach_dem_kontingent(klient, monkeypatch):
    """Beim Gratiskontingent reicht es für rund eine Anfrage pro Minute -
    weltweit. Ohne Bremse leert ein einzelner Besucher es für alle."""
    _mit_fester_antwort(monkeypatch, _antwort())
    for _ in range(app_modul.BREMSE.anfragen):
        assert klient.post("/erzeugen", data={"beschreibung": "Test"}).status_code == 200

    antwort = klient.post("/erzeugen", data={"beschreibung": "Test"})
    assert antwort.status_code == 429
    assert "Demo-Kontingent" in antwort.text
    assert "eigenen Schlüssel" in antwort.text


def test_eigener_schluessel_umgeht_die_bremse(klient, monkeypatch):
    """Der vorgesehene Weg für alle, die mehr brauchen - genau die
    Mitigation aus dem Risikoregister des PRD."""
    gebaute: list[str] = []

    class Attrappe(FesterClient):
        def __init__(self, *a, api_schluessel="", **kw):
            super().__init__(_antwort())
            gebaute.append(api_schluessel)

    monkeypatch.setattr(app_modul, "OpenAIKompatiblerClient", Attrappe)
    app_modul.BREMSE.zuruecksetzen()
    for _ in range(app_modul.BREMSE.anfragen + 3):
        antwort = klient.post(
            "/erzeugen", data={"beschreibung": "Test", "eigener_schluessel": "gsk_geheim"}
        )
        assert antwort.status_code == 200

    assert gebaute == ["gsk_geheim"] * (app_modul.BREMSE.anfragen + 3)


def test_eigener_schluessel_erscheint_nirgends_in_der_antwort(klient, monkeypatch):
    """Er wird nicht gespeichert, nicht protokolliert und nicht in die Seite
    zurückgeschrieben - anders als die Beschreibung, die absichtlich stehen
    bleibt."""

    class Attrappe(FesterClient):
        def __init__(self, *a, api_schluessel="", **kw):
            super().__init__(_antwort())

    monkeypatch.setattr(app_modul, "OpenAIKompatiblerClient", Attrappe)
    antwort = klient.post(
        "/erzeugen",
        data={"beschreibung": "Eine Patientin", "eigener_schluessel": "gsk_streng_geheim"},
    )
    assert "gsk_streng_geheim" not in antwort.text
    assert "Eine Patientin" in antwort.text, "Die Beschreibung soll dagegen stehen bleiben"


def test_schluesselfeld_ist_ein_passwortfeld(klient):
    text = klient.get("/").text
    assert 'type="password"' in text
    assert 'name="eigener_schluessel"' in text
    assert "nicht gespeichert" in text


# --- Die drei Ausgabewege --------------------------------------------------
#
# Alle drei waren bis Phase 3 nur auf der Kommandozeile zu haben. Wer über
# die Weboberfläche erzeugte, bekam ein Bundle und sonst nichts — obwohl
# NDJSON (ADR-005) und Aufzeichnung (ADR-006) längst gebaut waren.


def _erzeuge(klient, monkeypatch, antwort: str | None = None):
    """Ein Lauf über die Seite, mit fester Modellantwort."""
    _mit_fester_antwort(monkeypatch, antwort or _antwort())
    return klient.post("/erzeugen", data={"beschreibung": "Eine Patientin"})


def _feld(text: str, name: str) -> str:
    """Den Wert eines versteckten Formularfelds aus der Seite lesen."""
    import html
    import re

    treffer = re.search(
        rf'<input type="hidden" name="{name}" value="(.*?)">', text, re.S
    )
    assert treffer, f"Feld {name} steht nicht in der Seite"
    return html.unescape(treffer.group(1))


def test_ndjson_archiv_kommt_als_gueltiges_zip(klient, monkeypatch):
    """ADR-005 verlangt eine Datei je Ressourcentyp. Ein Browser lädt aber
    nur eine Datei — also ein Archiv, das die Aufteilung erhält."""
    import io
    import zipfile

    seite = _erzeuge(klient, monkeypatch).text
    antwort = klient.post(
        "/export", data={"bundle": _feld(seite, "bundle"), "art": "ndjson"}
    )
    assert antwort.status_code == 200
    assert antwort.headers["content-type"] == "application/zip"
    assert antwort.headers["content-disposition"].endswith('.zip"')

    archiv = zipfile.ZipFile(io.BytesIO(antwort.content))
    assert archiv.testzip() is None
    namen = archiv.namelist()
    assert "manifest.json" in namen
    assert "Patient.ndjson" in namen

    # Der Punkt des Formats: eine Ressource je Zeile, ein Typ je Datei.
    for name in namen:
        if not name.endswith(".ndjson"):
            continue
        roh = archiv.read(name)
        assert roh.endswith(b"\n") and b"\r" not in roh
        typen = {
            json.loads(z)["resourceType"] for z in roh.decode("utf-8").splitlines()
        }
        assert typen == {name[: -len(".ndjson")]}, f"{name} mischt Typen"


def test_archiv_traegt_den_testdatenhinweis(klient, monkeypatch):
    """Auflage aus PRD Block 6: Die Kennzeichnung darf nicht am Rand der
    Weboberfläche hängenbleiben. Wer das Archiv entpackt, sieht die Seite
    nicht mehr — und manifest.json liest kaum jemand."""
    import io
    import zipfile

    seite = _erzeuge(klient, monkeypatch).text
    antwort = klient.post(
        "/export", data={"bundle": _feld(seite, "bundle"), "art": "ndjson"}
    )
    archiv = zipfile.ZipFile(io.BytesIO(antwort.content))
    hinweis = archiv.read("LIESMICH.txt").decode("utf-8")
    assert "synthetisch" in hinweis.lower()
    assert "NICHT fuer die" in hinweis or "nicht für die" in hinweis.lower()


def test_gefaelschtes_bundle_bricht_das_archiv_ab(klient):
    """Der Bundle-Inhalt kommt aus dem Formular zurück — er ist damit
    Eingabe des Nutzers, nicht Ausgabe des Servers.

    Ein `resourceType` von "../entwischt" schrieb beim Dateiexport
    nachweislich ausserhalb des Zielverzeichnisses. Im Archiv wäre es ein
    Eintragsname, den manche Entpacker genauso behandeln.
    """
    bosheit = json.dumps(
        {
            "resourceType": "Bundle",
            "entry": [{"resource": {"resourceType": "../entwischt", "id": "x"}}],
        }
    )
    antwort = klient.post("/export", data={"bundle": bosheit, "art": "ndjson"})
    assert antwort.status_code == 400
    assert b"PK" not in antwort.content, "kein Archiv trotz Fehler"


def test_aufzeichnung_laesst_sich_herunterladen_und_wiedergeben(klient, monkeypatch):
    """ADR-006 im Web: Der Knopf taugt nur etwas, wenn das Heruntergeladene
    auch wirklich denselben Lauf zurückgibt."""
    from synthfhir import aufzeichnung as aufz

    seite = _erzeuge(klient, monkeypatch).text
    antwort = klient.post(
        "/export",
        data={
            "bundle": _feld(seite, "bundle"),
            "aufzeichnung": _feld(seite, "aufzeichnung"),
            "art": "aufzeichnung",
        },
    )
    assert antwort.status_code == 200

    gelesen = aufz.Aufzeichnung.from_dict(json.loads(antwort.text))
    assert gelesen.teile, "eine Aufzeichnung ohne Teile gibt nichts wieder"
    wieder = aufz.gib_wieder(gelesen)
    assert wieder.identisch, wieder.befund()
    assert not wieder.katalog_geaendert


def test_unbrauchbare_aufzeichnung_wird_nicht_ausgeliefert(klient, monkeypatch):
    """Sonst bekäme der Nutzer eine Datei, die ihren Namen nicht verdient
    und erst beim Abspielen scheitert — weit weg von hier."""
    seite = _erzeuge(klient, monkeypatch).text
    antwort = klient.post(
        "/export",
        data={
            "bundle": _feld(seite, "bundle"),
            "aufzeichnung": '{"beschreibung": "ohne alles"}',
            "art": "aufzeichnung",
        },
    )
    assert antwort.status_code == 400


def test_unbekannte_ausgabeart_wird_abgewiesen(klient, monkeypatch):
    seite = _erzeuge(klient, monkeypatch).text
    antwort = klient.post(
        "/export", data={"bundle": _feld(seite, "bundle"), "art": "exe"}
    )
    assert antwort.status_code == 400


def test_dateiname_aus_dem_formular_bestimmt_die_endung_nicht(klient, monkeypatch):
    """Die Endung setzt der Server. Sonst erklärte ein Feld aus der Seite
    ein ZIP zu einer .json — oder zu etwas Schlimmerem."""
    seite = _erzeuge(klient, monkeypatch).text
    antwort = klient.post(
        "/export",
        data={
            "bundle": _feld(seite, "bundle"),
            "art": "ndjson",
            "dateiname": "../../etc/passwd.json",
        },
    )
    verfuegung = antwort.headers["content-disposition"]
    assert verfuegung == 'attachment; filename="etcpasswd.zip"'


# --- Die Vorschau zeigt, was erzeugt wurde ---------------------------------


def test_vorschau_zeigt_alle_fuenf_ressourcentypen(klient, monkeypatch):
    """Seit ADR-007 entstehen fünf Typen, die Vorschau zeigte zwei.

    Begegnungen und Medikation standen im Bundle und waren unsichtbar —
    wer nur auf die Seite sah, hielt das Erzeugte für kleiner, als es ist.
    """
    patient = {
        "vorname": "Ingrid",
        "nachname": "Baumgartner",
        "geschlecht": "female",
        "geburtsdatum": "1958-03-14",
        "begegnungen": [{"art": "IMP", "datum": "2024-02-14"}],
        "diagnosen": [{"code": "44054006", "beginn": "2012-05-01"}],
        "messwerte": [{"code": "4548-4", "wert": 7.8, "datum": "2024-01-15"}],
        "medikamente": [{"code": "A10BA02", "beginn": "2012-06-01"}],
    }
    text = _erzeuge(klient, monkeypatch, _antwort([patient])).text

    assert "Kontakte" in text
    assert "stationär" in text, "die Kontaktart auf Deutsch, aus dem Katalog"
    assert "Medikation" in text
    assert "Metformin" in text
    assert "A10BA02" in text


def test_vorschau_nennt_den_kontakt_der_diagnose(klient, monkeypatch):
    """Die sichtbare Seite von isik-con1 (ADR-009): Eine kodierte Diagnose
    muss sagen, in welchem Kontakt sie gestellt wurde. Diese Zusage soll
    man sehen, nicht nur im Validator nachlesen."""
    text = _erzeuge(klient, monkeypatch).text
    assert "<th>Kontakt</th>" in text
    assert "enc-001" in text


def test_fusstext_nennt_alle_erzeugten_ressourcentypen(klient):
    """Der Fusstext hatte seit ADR-007 drei von fünf Typen genannt.

    Er steht dort als Beschreibung des Produkts — wer ihn liest, glaubt zu
    wissen, was herauskommt. Diese Prüfung zählt gegen die Vorlagen, damit
    ein sechster Typ nicht wieder still danebensteht.
    """
    from synthfhir.domain.templates import baue_aus_parametern
    from synthfhir.referenzkohorte import PARAMETER

    erzeugte = {
        r["resourceType"]
        for r in baue_aus_parametern(PARAMETER, {}).ressourcen
    }
    text = klient.get("/").text
    fehlend = [t for t in erzeugte if t not in text]
    assert not fehlend, f"im Fusstext nicht genannt: {fehlend}"
