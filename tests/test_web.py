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
    assert "Der Download ist gesperrt" in text


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
