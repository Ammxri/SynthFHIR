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
    # Die Gesamtbremse blieb zuvor über die ganze Datei stehen. Sie zählt
    # 30 je Zeitfenster, die Datei hat inzwischen genug erfolgreiche POSTs,
    # dass ein weiterer Test die Grenze hätte kippen können — und der
    # Fehlschlag träfe dann irgendeinen Test, nicht den verursachenden.
    app_modul.GESAMTBREMSE.zuruecksetzen()
    yield
    app_modul.BREMSE.zuruecksetzen()
    app_modul.GESAMTBREMSE.zuruecksetzen()


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


def _mit_eigenem_schluessel(monkeypatch, gebaute: list | None = None) -> None:
    """Ersetzt den Client, den die FABRIK baut — nicht die Fabrik selbst.

    Der frühere Aufbau ersetzte `OpenAIKompatiblerClient` im Modul der
    Oberfläche, und das war blind: Die Attrappe validierte in ihrem
    `__init__` nichts, der echte Konstruktor lief im Test also nie — und
    genau dort sitzen die Prüfungen, um die es geht.

    Ersetzt wird deshalb der Konstruktor im Modul `llm`. Die drei Riegel
    von `client_mit_fremdschluessel` laufen dann wirklich, und nur der
    Netzzugriff dahinter entfällt.
    """
    import synthfhir.llm as llm_modul

    class Attrappe(FesterClient):
        def __init__(self, *a, api_schluessel="", **kw):
            super().__init__(_antwort())
            if gebaute is not None:
                gebaute.append(api_schluessel)

    # Die Fabrik verlangt beides — ohne Basis-URL ginge ein fremder
    # Schlüssel an die Vorgabe, und die zeigt auf ein lokales Ollama.
    monkeypatch.setenv("SYNTHFHIR_LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("SYNTHFHIR_LLM_MODEL", "test-modell")
    monkeypatch.setattr(llm_modul, "OpenAIKompatiblerClient", Attrappe)


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
    _mit_eigenem_schluessel(monkeypatch, gebaute)
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
    _mit_eigenem_schluessel(monkeypatch)
    antwort = klient.post(
        "/erzeugen",
        data={"beschreibung": "Eine Patientin", "eigener_schluessel": "gsk_streng_geheim"},
    )
    assert "gsk_streng_geheim" not in antwort.text
    assert "Eine Patientin" in antwort.text, "Die Beschreibung soll dagegen stehen bleiben"


def test_unzulaessiger_schluessel_wird_abgewiesen_und_nicht_gezeigt(klient, monkeypatch):
    """Der Fall, an dem der Schlüssel tatsächlich in die Seite geriet.

    Die Oberfläche baute den Client direkt und umging damit die
    Musterprüfung der Fabrik. `requests` wirft bei einem Zeilenumbruch im
    Kopfwert eine `InvalidHeader`, **deren Meldung den Wert enthält**;
    `frage()` bettet sie mit `{exc}` in den `LLMFehler` ein, und von dort
    ging der fremde Schlüssel über `ergebnis.fehler` in die gerenderte
    Seite und in jede `--bericht`-Datei.

    Der Test daneben konnte das nicht bemerken: Sein Schlüssel ist rein
    alphanumerisch, also genau der, der ohnehin durchgeht.
    """
    _mit_eigenem_schluessel(monkeypatch)
    geheim = "gsk_streng_geheim"
    antwort = klient.post(
        "/erzeugen",
        data={
            "beschreibung": "Eine Patientin",
            "eigener_schluessel": f"{geheim}\nX-Boes: 1",
        },
    )
    assert antwort.status_code == 503
    assert geheim not in antwort.text, "der Schlüssel steht in der ausgelieferten Seite"


def test_zu_langer_schluessel_geht_nicht_hinaus(klient, monkeypatch):
    """Zweite Folge desselben Umgehens: 100 000 Zeichen gingen ungeprüft
    an den Anbieter hinaus."""
    gebaute: list[str] = []
    _mit_eigenem_schluessel(monkeypatch, gebaute)
    antwort = klient.post(
        "/erzeugen",
        data={"beschreibung": "Eine Patientin", "eigener_schluessel": "g" * 100_000},
    )
    assert antwort.status_code == 503
    assert gebaute == [], "es wurde trotzdem ein Client gebaut"


def test_schluesselfeld_ist_ein_passwortfeld(klient):
    text = klient.get("/").text
    assert 'type="password"' in text
    assert 'name="eigener_schluessel"' in text
    assert "nicht gespeichert" in text


# --- Grenzen, die bisher nur der API-Pfad hatte ----------------------------


def test_leere_beschreibung_verbraucht_keinen_platz_in_der_bremse(klient, monkeypatch):
    """Beide Bremsen verbuchten ihren Platz, bevor irgendetwas geprüft war.

    Damit konnte ein Aufrufer die Demo mit Anfragen sperren, die garantiert
    nichts kosten: `generiere` bricht bei leerer Beschreibung ab, ohne je
    ein Modell zu fragen. `api.py` prüft ausdrücklich vorher — „damit kein
    Kontingent verbrennt"; die Oberfläche hatte diese Prüfung nicht.
    """
    _mit_fester_antwort(monkeypatch, _antwort())
    for _ in range(app_modul.BREMSE.anfragen + 5):
        assert klient.post("/erzeugen", data={"beschreibung": "   "}).status_code == 400

    # Die entscheidende Zusicherung: Danach ist noch Platz für eine
    # richtige Anfrage. Zuvor war das Kontingent hier längst leer.
    assert klient.post("/erzeugen", data={"beschreibung": "Test"}).status_code == 200


def test_zu_lange_beschreibung_wird_abgewiesen(klient, monkeypatch):
    """Ohne Grenze ging die Beschreibung ungeprüft in den Prompt — auf
    Rechnung des Betreibers. Die Bremse zählt Anfragen, nicht Token."""
    from synthfhir.web.api import BESCHREIBUNG_HOECHSTLAENGE

    def _darf_nicht():
        raise AssertionError("Es wurde ein Client gebaut, obwohl die Eingabe zu lang ist")

    monkeypatch.setattr(app_modul, "client_aus_umgebung", _darf_nicht)
    antwort = klient.post(
        "/erzeugen", data={"beschreibung": "x" * (BESCHREIBUNG_HOECHSTLAENGE + 1)}
    )
    assert antwort.status_code == 400
    assert "länger als" in antwort.text


def test_zu_grosser_koerper_wird_abgewiesen(klient, monkeypatch):
    """`/export` nahm beliebig grosse Körper an, parste sie als JSON und
    baute bei `art=ndjson` zusätzlich ein ZIP im Speicher — ohne Grenze,
    ohne Bremse, ohne Authentifizierung. Starlette selbst begrenzt nichts.
    """
    monkeypatch.setattr(app_modul, "KOERPER_HOECHSTGROESSE", 1024)
    antwort = klient.post("/export", data={"bundle": "x" * 4096})
    assert antwort.status_code == 413


def test_eigener_schluessel_hat_jetzt_auch_einen_deckel(klient, monkeypatch):
    """ADR-011 begründet den Gleichzeitigkeitsdeckel wörtlich damit, dass
    ein Aufrufer mit gültigem eigenem Schlüssel „die Seite für alle anderen
    unbenutzbar machen" könnte — er stand aber nur an `/api/v1`. Über die
    Oberfläche kam derselbe Aufrufer mit demselben Schlüssel ohne Deckel
    und ohne Bremse durch.
    """
    import synthfhir.web.api as api_modul

    _mit_eigenem_schluessel(monkeypatch)
    monkeypatch.setattr(api_modul._plaetze, "acquire", lambda blocking=True: False)
    antwort = klient.post(
        "/erzeugen",
        data={"beschreibung": "Test", "eigener_schluessel": "gsk_geheim"},
    )
    assert antwort.status_code == 429
    assert antwort.headers["Retry-After"] == "30"


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


# --- Szenarien in der Oberflaeche (ADR-016) --------------------------------


def test_die_bibliothek_steht_auf_der_startseite(klient):
    """Sie ist der einzige Weg, der auch bei leerem Kontingent etwas
    zeigt — also gehoert sie auf die erste Ansicht, nicht hinter einen
    Klick."""
    text = klient.get("/").text
    for name in ("diabetes-ambulanz", "blutdruck-kontrolle",
                 "labor-grundprofil", "mehrere-kontakte", "ohne-kontakt"):
        assert f"/szenario/{name}" in text


def test_szenario_liefert_eine_vollstaendige_kohorte(klient):
    a = klient.get("/szenario/diabetes-ambulanz")
    assert a.status_code == 200
    assert "Valide gegen FHIR R4" in a.text
    assert "Vorschau" in a.text
    assert "synthfhir --szenario diabetes-ambulanz" in a.text
    assert "kein Sprachmodell" in a.text


def test_szenario_laeuft_ohne_jeden_modellaufruf(klient, monkeypatch):
    """Die Zusage von ADR-016. `--szenario` LAEUFT ohne Schluessel — das
    sieht man; ob dabei trotzdem ein Client gebaut wird, nicht."""
    def verboten(*a, **k):
        raise AssertionError("Ein Szenariolauf hat das Modell angefasst.")

    monkeypatch.setattr(app_modul, "client_aus_umgebung", verboten)
    # Zuvor stand hier `OpenAIKompatiblerClient`. Den Namen kennt dieses
    # Modul nicht mehr: Die Oberfläche baut den Client für einen eigenen
    # Schlüssel seit der Durchsicht über die Fabrik
    # `client_mit_fremdschluessel`, weil der direkte Konstruktor beide
    # Riegel aus `llm.py` umging und ein Schlüssel mit Zeilenumbruch so in
    # die gerenderte Seite geriet.
    #
    # Die Zusage dieses Tests ist unverändert — nur der Name, den man
    # verbieten muss, ist ein anderer. Beide Wege sind gesperrt, also kann
    # der Szenariopfad auf keinem davon einen Client bauen.
    monkeypatch.setattr(app_modul, "client_mit_fremdschluessel", verboten)
    for name in ("diabetes-ambulanz", "blutdruck-kontrolle",
                 "labor-grundprofil", "mehrere-kontakte", "ohne-kontakt"):
        assert klient.get(f"/szenario/{name}").status_code == 200


def test_szenario_verbraucht_keinen_platz_der_bremse(klient):
    """Die Bremsen schuetzen ein Kontingent beim Modellanbieter. Ein
    Szenario benutzt keinen — es darf dort nichts abbuchen, sonst naehme
    ausgerechnet der kostenlose Weg dem bezahlten die Plaetze weg."""
    vorher = len(app_modul.GESAMTBREMSE._verlauf[app_modul.GESAMT])
    for _ in range(8):
        assert klient.get("/szenario/ohne-kontakt").status_code == 200
    assert len(app_modul.GESAMTBREMSE._verlauf[app_modul.GESAMT]) == vorher


def test_unbekanntes_szenario_gibt_404_und_nennt_die_bekannten(klient):
    a = klient.get("/szenario/gibtsnicht")
    assert a.status_code == 404
    assert "diabetes-ambulanz" in a.text


def test_der_pfad_wird_nicht_in_die_seite_zurueckgeschrieben(klient):
    """Der Name kommt aus dem Pfad und ist damit Fremdeingabe. Jinja
    maskiert zwar — aber der sicherste Weg ist, ihn gar nicht erst
    aufzunehmen."""
    a = klient.get("/szenario/GEHEIMER-MARKER-XYZ")
    assert a.status_code == 404
    assert "GEHEIMER-MARKER-XYZ" not in a.text
    assert "MARKER" not in a.text


def test_szenario_bietet_keine_aufzeichnung_an(klient):
    """Eine Aufzeichnung haelt den Beitrag des Modells fest. Den gibt es
    hier nicht, und eine Datei unter diesem Namen waere eine Luege."""
    text = klient.get("/szenario/ohne-kontakt").text
    assert 'value="json"' in text and 'value="ndjson"' in text
    assert 'value="aufzeichnung"' not in text


def test_das_gewaehlte_szenario_ist_in_der_liste_markiert(klient):
    assert 'class="aktiv"' in klient.get("/szenario/labor-grundprofil").text


def test_das_blutdruckpanel_zeigt_seine_werte(klient):
    """Gefunden durch das Szenario selbst: Die Vorschau las nur
    `valueQuantity` und zeigte ausgerechnet beim Blutdruck einen
    Gedankenstrich — bei der einen Ressource, die ihn vorfuehren soll."""
    text = klient.get("/szenario/blutdruck-kontrolle").text
    assert "158.0 / 96.0 mmHg" in text
    assert "85354-9" in text


def test_ein_szenario_ohne_kontakt_zeigt_den_ergaenzten_kontakt(klient):
    text = klient.get("/szenario/ohne-kontakt").text
    assert "Kontakte" in text, "isik-con1 ergaenzt sie — das soll man sehen"


@pytest.mark.parametrize("r,erwartet", [
    ({"valueQuantity": {"value": 7.8, "unit": "%"}}, "7.8 %"),
    ({"component": [{"valueQuantity": {"value": 120, "unit": "mmHg"}},
                    {"valueQuantity": {"value": 80, "unit": "mmHg"}}]},
     "120 / 80 mmHg"),
    ({}, "—"),
    ({"component": []}, "—"),
    ({"component": ["kein Objekt", {"valueQuantity": {}}]}, "—"),
    ({"valueQuantity": {"unit": "%"}}, "—"),
])
def test_messwerttext_haelt_auch_das_unvollstaendige_aus(r, erwartet):
    """Die Vorschau darf an keiner Ressource abstuerzen — auch nicht an
    einer, die aus einem fremden Bundle kommt."""
    assert app_modul._messwerttext(r) == erwartet


def test_die_bibliothek_zaehlt_sich_selbst(klient):
    """„Diese fuenf" stand hier fest im Text. Eine sechste Vorlage haette
    den Satz zur Falschaussage gemacht — die Sorte Handzaehlung, die
    dieses Projekt schon fuenfmal eingeholt hat."""
    from synthfhir.szenarien import alle

    text = klient.get("/").text
    assert f"Diese {len(alle())} sind kuratiert" in text


def test_dateiname_mit_nicht_ascii_wird_gefiltert_statt_zu_scheitern(klient):
    """`c.isalnum()` ist unicode-bewusst und liess alles durch, was
    irgendwo ein Buchstabe ist.

    Nachgemessen: `dateiname=日本語` ergab `日本語.json`, und Starlette
    schreibt Kopfzeilenwerte als latin-1 — die Antwort endete als
    Serverfehler statt als Datei. Der Pfaddurchquerungsschutz war davon
    nicht betroffen und bleibt.
    """
    antwort = klient.post(
        "/export",
        data={"bundle": '{"resourceType":"Bundle","entry":[]}',
              "art": "json", "dateiname": "日本語"},
    )
    assert antwort.status_code == 200
    zuordnung = antwort.headers["content-disposition"]
    assert "日本語" not in zuordnung
    assert "synthfhir" in zuordnung, "ohne brauchbare Zeichen greift die Vorgabe"


def test_pfaddurchquerung_im_dateinamen_bleibt_wirkungslos(klient):
    antwort = klient.post(
        "/export",
        data={"bundle": '{"resourceType":"Bundle","entry":[]}',
              "art": "json", "dateiname": "../../etc/passwd"},
    )
    assert antwort.status_code == 200
    zuordnung = antwort.headers["content-disposition"]
    assert ".." not in zuordnung and "/" not in zuordnung.split("filename=")[1]


# --- Der Notfall in der Vorschau (ADR-018) ---------------------------------


def test_die_vorschau_zeigt_den_notfall(klient):
    """Seit ADR-018 steht der Notfall in `hospitalization.admitSource`,
    nicht in `class`. Wer nur `class` liest, zeigt bei einer Notaufnahme
    "stationaer" — richtig und trotzdem irrefuehrend, weil genau die
    Information fehlt, nach der gefragt wurde."""
    text = klient.get("/szenario/mehrere-kontakte").text
    assert "Notfall" in text
    assert "stationär · Notfall" in text


@pytest.mark.parametrize("encounter,erwartet", [
    ({"class": {"code": "AMB"}}, "ambulant"),
    ({"class": {"code": "VR"}}, "Videosprechstunde"),
    ({"class": {"code": "IMP"}}, "stationär"),
    ({"class": {"code": "IMP"}, "hospitalization": {"admitSource": {"coding": [
        {"system": "http://fhir.de/CodeSystem/dgkev/Aufnahmeanlass",
         "code": "N"}]}}}, "stationär · Notfall"),
    # Fremdes System an derselben Stelle: nicht uebersetzen, nicht anzeigen.
    ({"class": {"code": "IMP"}, "hospitalization": {"admitSource": {"coding": [
        {"system": "http://example.org/fremd", "code": "N"}]}}}, "stationär"),
    # Unbekannter Anlass aus unserem System: roh zeigen, sichtbar fremd.
    ({"class": {"code": "IMP"}, "hospitalization": {"admitSource": {"coding": [
        {"system": "http://fhir.de/CodeSystem/dgkev/Aufnahmeanlass",
         "code": "G"}]}}}, "stationär · G"),
    # Alte Aufzeichnung, aelter als ADR-018.
    ({"class": {"code": "EMER", "display": "emergency"}},
     "Notfall, stationäre Aufnahme"),
    # Kaputtes: darf nicht abstuerzen.
    ({}, "—"),
    ({"class": {"code": "IMP"}, "hospitalization": {}}, "stationär"),
    ({"class": {"code": "IMP"}, "hospitalization": {"admitSource": {}}}, "stationär"),
    ({"class": {"code": "IMP"}, "hospitalization": {"admitSource": {
        "coding": ["kein Objekt"]}}}, "stationär"),
])
def test_kontaktart_haelt_auch_das_unvollstaendige_aus(encounter, erwartet):
    assert app_modul._kontaktart(encounter) == erwartet


def test_die_bezeichnung_kommt_aus_dem_katalog_nicht_aus_der_ressource():
    """Bei einer geladenen Fremddatei stammt `display` vom Aufrufer. Der
    gehoert nicht ungeprueft in die Seite."""
    e = {"class": {"code": "IMP"}, "hospitalization": {"admitSource": {"coding": [
        {"system": "http://fhir.de/CodeSystem/dgkev/Aufnahmeanlass",
         "code": "N", "display": "<script>boese</script>"}]}}}
    assert app_modul._kontaktart(e) == "stationär · Notfall"


# --- /export gegen die JSON-Verstaerkungsbombe (Befund 7) ------------------


def _tief(n):
    x = 0
    for _ in range(n):
        x = [x]
    return x


def test_export_weist_die_json_bombe_ab(klient):
    """EINE anonyme Anfrage unter 1 MB darf keine GB-Ausgabe erzeugen.

    `json.dumps(indent=2)` blaeht tief verschachtelte Eingabe linear mit
    der Tiefe auf - gemessen 1,6 KB rein, 1,3 MB raus. Auf der 512-MB-
    Instanz ist das ein OOM aus einer einzigen Anfrage. Der Schutz sitzt
    auf der Ausgabe, weil der Verstaerkungsfaktor jede Eingabegrenze
    aushebelt.
    """
    import json as _json

    ein = _json.dumps(_tief(2000))
    a = klient.post("/export", data={"bundle": ein, "art": "json"})
    assert a.status_code == 413
    assert len(a.content) < 2000, "die Bombe darf keine grosse Antwort erzeugen"


def test_export_grenze_greift_ohne_recursionerror(klient):
    """Die Gegenprobe zur Tiefe, die WIRKLICH die Ausgabegrenze trifft.

    Nachgemessen: `[tief(800)]*N` laeuft in Wahrheit in den
    RecursionError des Encoders (Tiefe 801) und beweist die Ausgabegrenze
    NICHT. Hier ist die Tiefe klein (51, weit unter der Encoder-Grenze),
    aber die Breite gross: 704 KiB Eingabe, 36 MiB Ausgabe. Nur die
    Ausgabegrenze kann das fangen — der Test wird gruen, wenn man sie
    aufweicht, ist also die richtige Wache.
    """
    import json as _json
    import urllib.parse as _up

    # Tiefe 200: weit unter der Encoder-Rekursionsgrenze, also KEIN
    # RecursionError — nachgemessen: mit aufgeweichter Grenze liefert
    # genau diese Eingabe 200 mit 40 MB Ausgabe. Nur die Ausgabegrenze
    # fangt es. 500 Kopien treiben die eingerueckte Ausgabe auf ~38 MB.
    breit = [_tief(200)] * 500
    ein = _json.dumps(breit)
    # Der Wert wird urlencoded uebertragen; die vielen Klammern verdreifachen
    # ihn. Er muss auch dann unter Starlettes 1-MB-Feldgrenze bleiben, sonst
    # misst der Test die Feldgrenze statt der Ausgabegrenze.
    assert len(_up.quote_plus(ein)) < 1024 * 1024
    a = klient.post("/export", data={"bundle": ein, "art": "json"})
    assert a.status_code == 413


def test_export_sehr_tiefe_eingabe_ist_400_kein_500(klient):
    """Ab rund 5000 Ebenen wirft schon der Parser RecursionError. Das ist
    ein Eingabefehler (400), kein Serverfehler (500)."""
    tief = "[" * 9000 + "0" + "]" * 9000
    a = klient.post("/export", data={"bundle": tief, "art": "json"})
    assert a.status_code == 400


def test_export_meldung_zeigt_die_eingabe_nicht(klient):
    """Der Koerper ist Fremdeingabe. Die 413-Meldung nennt die Grenze,
    nicht den Inhalt."""
    import json as _json

    marke = "GEHEIM-MARKER-9998"
    obj = {"resourceType": marke, "tief": _tief(2000)}
    a = klient.post("/export", data={"bundle": _json.dumps(obj), "art": "json"})
    assert a.status_code == 413
    assert marke not in a.text


def test_export_ein_echtes_bundle_geht_weiterhin_durch(klient):
    """Die Grenze darf den rechtmaessigen Fall nicht treffen: 200
    Patienten sind rund 3 MB, die Grenze liegt bei 16."""
    import json as _json

    bundle = {"resourceType": "Bundle", "entry": [
        {"resource": {"resourceType": "Patient", "id": f"pat-{i}",
                      "name": [{"family": "Mustermann", "given": ["Erika"]}]}}
        for i in range(200)]}
    a = klient.post("/export", data={"bundle": _json.dumps(bundle), "art": "json"})
    assert a.status_code == 200
    assert _json.loads(a.content)["entry"][0]["resource"]["resourceType"] == "Patient"


# --- Der Betreiberschluessel darf nicht in die Seite (Fix 2) ---------------


def test_betreiberschluessel_leckt_nicht_ueber_anbietertext(klient, monkeypatch):
    """Auf dem Demopfad benutzt die Seite den Betreiberschluessel. Wenn der
    Anbieter ihn in seiner Fehlermeldung wiederholt, darf er trotzdem nicht
    in der gerenderten Seite stehen — ein anonymer Besucher saehe ihn sonst.
    """
    from synthfhir import llm

    GEHEIM = "sk-BETREIBER-GEHEIM-4711"

    class FakeAntwort:
        status_code = 500
        text = f'{{"error":{{"message":"rejected (Bearer {GEHEIM})"}}}}'
        headers: dict = {}

        def json(self):
            raise ValueError("kein JSON")

    def bau():
        c = llm.OpenAIKompatiblerClient(
            modell="m", basis_url="https://anbieter.invalid/v1",
            api_schluessel=GEHEIM)
        c._post_mit_wartepausen = lambda url, rumpf: FakeAntwort()
        return c

    monkeypatch.setattr(app_modul, "client_aus_umgebung", bau)
    a = klient.post("/erzeugen", data={"beschreibung": "Ein Patient mit Diabetes"})
    assert GEHEIM not in a.text, "der Betreiberschluessel steht in der Seite"
    assert "Bearer" not in a.text
