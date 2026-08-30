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
    """
    validator = HapiValidator(PROFIL_BASIS_URL)
    if validator.bereit(wartezeit_s=10.0) is None:
        if PROFIL_PFLICHT:
            pytest.fail(_PROFIL_HINWEIS, pytrace=False)
        pytest.skip(_PROFIL_HINWEIS, allow_module_level=True)
    return PROFIL_BASIS_URL
