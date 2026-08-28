"""Schlanker HAPI-Client — nur für Tests.

Bewusst nicht in `src/`: Das Produkt spricht im Betrieb nicht mit HAPI
(ADR-002). HAPI ist reine Prüfinfrastruktur der Bauzeit.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import requests

FHIR_JSON = "application/fhir+json"
BLOCKIEREND = ("fatal", "error")


class HapiNichtErreichbar(RuntimeError):
    """Der Validierungsserver antwortet nicht."""


@dataclass(frozen=True)
class Befund:
    schweregrad: str
    meldung: str
    fundstelle: str | None

    @property
    def blockierend(self) -> bool:
        return self.schweregrad in BLOCKIEREND

    def __str__(self) -> str:
        return f"[{self.schweregrad}] {self.fundstelle or '?'}: {self.meldung}"


class HapiValidator:
    """Ruft `$validate` auf und wertet das OperationOutcome aus."""

    def __init__(self, basis_url: str, timeout_s: float = 120.0) -> None:
        self.basis_url = basis_url.rstrip("/")
        self.timeout_s = timeout_s
        self.session = requests.Session()
        self.session.headers.update({"Accept": FHIR_JSON, "Content-Type": FHIR_JSON})

    def bereit(self, wartezeit_s: float = 5.0) -> str | None:
        """FHIR-Version des Servers, oder None wenn er nicht antwortet."""
        ende = time.monotonic() + wartezeit_s
        while time.monotonic() < ende:
            try:
                antwort = self.session.get(f"{self.basis_url}/metadata", timeout=5.0)
                if antwort.status_code == 200:
                    koerper = antwort.json()
                    if koerper.get("resourceType") == "CapabilityStatement":
                        return str(koerper.get("fhirVersion", "unbekannt"))
            except (requests.exceptions.RequestException, ValueError):
                pass
            time.sleep(1.0)
        return None

    def validiere(self, ressource: dict) -> list[Befund]:
        """Alle Befunde zu einer Ressource. Leere Liste heißt: einwandfrei."""
        typ = ressource.get("resourceType")
        if not isinstance(typ, str) or not typ:
            return [Befund("error", "Ressource ohne resourceType", None)]

        url = f"{self.basis_url}/{typ}/$validate"
        try:
            antwort = self.session.post(
                url,
                data=json.dumps(ressource, ensure_ascii=False).encode("utf-8"),
                timeout=self.timeout_s,
            )
        except requests.exceptions.RequestException as exc:
            raise HapiNichtErreichbar(f"{url}: {exc}") from exc

        # Nicht am Statuscode entscheiden: HAPI antwortet je nach Version mit
        # 200, 412 oder 422 — und auf besonders kaputte Eingaben mit 500,
        # dann aber ebenfalls mit verwertbarem OperationOutcome.
        try:
            koerper = antwort.json()
        except ValueError as exc:
            raise HapiNichtErreichbar(
                f"{url}: Antwort war kein JSON (HTTP {antwort.status_code})"
            ) from exc

        if koerper.get("resourceType") != "OperationOutcome":
            raise HapiNichtErreichbar(
                f"{url}: erwartet wurde ein OperationOutcome, bekommen "
                f"{koerper.get('resourceType')!r} (HTTP {antwort.status_code})"
            )

        return [
            Befund(
                schweregrad=str(eintrag.get("severity") or "error").lower(),
                meldung=_klartext(eintrag),
                fundstelle=_fundstelle(eintrag),
            )
            for eintrag in koerper.get("issue", []) or []
            if isinstance(eintrag, dict)
        ]

    def fehler(self, ressource: dict) -> list[Befund]:
        """Nur die blockierenden Befunde."""
        return [b for b in self.validiere(ressource) if b.blockierend]


def _klartext(eintrag: dict) -> str:
    text = eintrag.get("diagnostics")
    if isinstance(text, str) and text.strip():
        return text.strip()
    details = eintrag.get("details")
    if isinstance(details, dict) and isinstance(details.get("text"), str):
        return details["text"].strip()
    return str(eintrag.get("code") or "kein Klartext im OperationOutcome")


def _fundstelle(eintrag: dict) -> str | None:
    for schluessel in ("expression", "location"):
        wert = eintrag.get(schluessel)
        if isinstance(wert, list) and wert:
            return str(wert[0])
        if isinstance(wert, str) and wert:
            return wert
    return None
