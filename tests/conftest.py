"""Gemeinsame Testfixtures.

Der wichtigste Teil hier ist die Handhabung des HAPI-Servers. ADR-002 macht
die Prüfung von Katalog und Vorlagen gegen HAPI zur **Auflage** — sie ist
der Ort, an dem die Produktzusage eingelöst wird. Eine Auflage, die
stillschweigend übersprungen wird, ist keine.

Deshalb:

  * Lokal ohne laufenden HAPI werden die betroffenen Tests übersprungen,
    mit einer Meldung, die sagt, wie man ihn startet. Entwickeln soll ohne
    Docker möglich bleiben.
  * Ist ``SYNTHFHIR_REQUIRE_HAPI=1`` gesetzt, ist ein fehlender Server ein
    **Fehlschlag**, kein Übersprung. Die CI setzt diese Variable. Damit kann
    die Auflage nicht unbemerkt verfallen.
"""

from __future__ import annotations

import os

import pytest

from .hapi import HapiValidator

# Erkennbar als Platzhalter. Er steht in `os.environ` statt des echten
# Schlüssels, sobald die autouse-Fixture unten greift.
BETREIBER_PLATZHALTER = "BETREIBERSCHLUESSEL-NUR-FUER-TESTS"

HAPI_BASIS_URL = os.environ.get("SYNTHFHIR_FHIR_BASE_URL", "http://localhost:8080/fhir")
HAPI_PFLICHT = os.environ.get("SYNTHFHIR_REQUIRE_HAPI", "").strip() in ("1", "true", "yes")

_HINWEIS = (
    f"HAPI FHIR ist unter {HAPI_BASIS_URL} nicht erreichbar.\n"
    "  Start:  docker compose up -d\n"
    "  Warten: docker compose logs -f hapi   (bis 'Started Application')\n"
    "Diese Prüfung ist laut ADR-002 verbindlich und darf in der CI nicht fehlen."
)


@pytest.fixture(scope="session")
def hapi() -> HapiValidator:
    """Ein bereiter HAPI-Validator, oder Übersprung/Fehlschlag."""
    validator = HapiValidator(HAPI_BASIS_URL)
    version = validator.bereit(wartezeit_s=10.0)
    if version is None:
        if HAPI_PFLICHT:
            pytest.fail(_HINWEIS, pytrace=False)
        pytest.skip(_HINWEIS, allow_module_level=True)
    return validator


PROFIL_BASIS_URL = os.environ.get("SYNTHFHIR_PROFIL_URL", "http://localhost:8090/fhir")
PROFIL_PFLICHT = os.environ.get("SYNTHFHIR_REQUIRE_PROFIL", "").strip() in ("1", "true", "yes")

_PROFIL_HINWEIS = (
    f"Der Profilserver ist unter {PROFIL_BASIS_URL} nicht erreichbar.\n"
    "  Start:  docker compose -f docs/belege/docker-compose.isik.yml up -d\n"
    "Er lädt die ISiK-Pakete und ist NICHT derselbe Server wie der\n"
    "Validierungsserver der CI — die Profilmessung darf die bestehende\n"
    "Prüfkette nicht anfassen."
)


@pytest.fixture(scope="session")
def profilserver() -> str:
    """Die Basis-URL eines FHIR-Servers mit geladenen ISiK-Profilen.

    Anders als bei `hapi` ist ein fehlender Server hier standardmäßig ein
    Übersprung und **kein** Fehlschlag, auch nicht in der CI: Die
    Profilmessung ist nach ADR-002 keine Produktzusage, sondern eine
    Sondierung. Sie zur Auflage zu machen hieße, ein Versprechen zu geben,
    über das noch gar nicht entschieden ist. `SYNTHFHIR_REQUIRE_PROFIL=1`
    kehrt das für einen gezielten Lauf um.

    **Diese Begründung deckt zwei verschiedene Dinge zu**, und ADR-012
    trennt sie: Unentschieden ist, ob SynthFHIR ISiK-Konformität *bewirbt*.
    Entschieden ist dagegen ADR-009 — die fünf Felder und die strukturelle
    Zusage sind gebaut und ausgeliefert, und nichts in der CI schützt sie.
    Solange dieser Übersprung gilt, läuft dort **weder die Messung noch
    ihre Negativkontrolle**.

    ADR-012 entscheidet, den Schalter zu setzen — nach dem Festnageln des
    HAPI-Images, weil die Einstufung am Wortlaut der Validatormeldungen
    hängt. Bis dahin bleibt es beim Übersprung.
    """
    validator = HapiValidator(PROFIL_BASIS_URL)
    if validator.bereit(wartezeit_s=10.0) is None:
        if PROFIL_PFLICHT:
            pytest.fail(_PROFIL_HINWEIS, pytrace=False)
        pytest.skip(_PROFIL_HINWEIS, allow_module_level=True)
    return PROFIL_BASIS_URL


# --- Vorbedingung, kein Test -----------------------------------------------


@pytest.fixture(autouse=True)
def kein_echter_schluessel(monkeypatch):
    """Ersetzt den Betreiberschlüssel für die Dauer der Suite.

    Ohne diese Fixture beweisen die Zusagen des programmatischen Zugangs
    nichts. `oberflaeche.py` ruft beim Import `load_dotenv()`, und die
    `.env` dieses Projekts setzt `SYNTHFHIR_LLM_API_KEY` — nachgemessen
    steht der echte Groq-Schlüssel danach in `os.environ`. Ein Test, der
    prüft „der Schlüssel des Betreibers wurde nicht benutzt", vergliche
    dann gegen den echten Wert, und ein Test, der versehentlich einen
    echten Client baut, telefonierte nach draußen.

    Der Platzhalter ist absichtlich als solcher erkennbar: Taucht er in
    einer Antwort auf, ist sofort klar, woher er stammt.
    """
    monkeypatch.setenv("SYNTHFHIR_LLM_API_KEY", BETREIBER_PLATZHALTER)
    monkeypatch.setenv("SYNTHFHIR_LLM_BASE_URL", "https://anbieter.invalid/v1")
    monkeypatch.setenv("SYNTHFHIR_LLM_MODEL", "test-modell")
