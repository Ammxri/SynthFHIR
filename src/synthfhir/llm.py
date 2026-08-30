"""LLM-Anbindung über OpenAI-kompatible Endpunkte.

Ein einziger Adapter erschließt alle Wege, die das Projekt braucht:

  * **Ollama, lokal** — kostet nichts, Daten verlassen den Rechner nicht.
    Ohne Angabe zeigt der Adapter dorthin.
  * **Groq, OpenRouter, Mistral, Google AI Studio** — kostenlose
    Kontingente, gleiche Schnittstelle, andere Basis-URL.

Die Robustheit stammt aus der Phase 0 und ist dort teuer gelernt worden:
Eine Messreihe war zu einem Drittel unbrauchbar, weil `max_tokens` das
Minutenkontingent des Anbieters überschritt und jede Anfrage mit HTTP 413
abgewiesen wurde. Beide Fälle — Ratengrenze und zu große Anfrage — werden
deshalb ausdrücklich behandelt und nicht als inhaltlicher Fehler verbucht.
"""

from __future__ import annotations

import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests

DEFAULT_BASE_URL = "http://localhost:11434/v1"  # Ollama

# OpenAI nennt den Abbruchgrund anders als Anthropic; vereinheitlicht, damit
# der aufrufende Code nur eine Schreibweise kennen muss.
FINISH_REASON = {"length": "max_tokens", "stop": "end_turn"}

# Voreinstellung für die Antwortlänge. Der Wert MUSS zu dem Prompt passen,
# den dieser Code ausliefert: Anbieter rechnen `max_tokens` in die
# Anfragegröße ein, und im Gratistarif (8000 Token/Minute) bleibt neben
# einem Prompt von rund 2900 Token nicht mehr Platz.
#
# Er stand auf 5600 und passte zum Prompt mit drei Katalogen. Mit den
# Katalogen der Phase 2 wuchs der Prompt, und die veröffentlichte Seite
# antwortete auf JEDE Anfrage mit HTTP 413 — die Voreinstellung wurde in
# `.env.example` gesenkt, aber nicht hier, und ein Deployment ohne gesetzte
# Umgebungsvariable landet genau hier.
#
# `tests/test_llm.py` hält den Wert gegen den tatsächlichen Prompt.
# Gewählt mit Spielraum: Der Teil-Prompt für Kohorten trägt einen Zusatz
# und ist der längste, den dieses Projekt sendet. Bei 4800 lag er pessimistisch
# gerechnet zwei Token über der Grenze — ein Spielraum von zwei Token ist
# keiner.
STANDARD_MAX_TOKENS = 4500

_LIMIT_RE = re.compile(r"Limit\s+(\d+)", re.I)
_REQUESTED_RE = re.compile(r"Requested\s+(\d+)", re.I)


class LLMFehler(RuntimeError):
    """Der Aufruf ist endgültig fehlgeschlagen."""


@dataclass(frozen=True)
class LLMAntwort:
    """Antwort eines Aufrufs samt Verbrauch."""

    text: str
    modell: str
    eingabe_token: int
    ausgabe_token: int
    dauer_s: float
    abbruchgrund: str | None = None

    @property
    def abgeschnitten(self) -> bool:
        """True, wenn die Antwort an `max_tokens` endete.

        Wichtig zu unterscheiden: Eine abgeschnittene Antwort ist fast immer
        unparsbar, aber die Ursache liegt in der Konfiguration, nicht beim
        Modell. Wer beides zusammenwirft, misst Konfigurationsfehler als
        Modellversagen.
        """
        return self.abbruchgrund == "max_tokens"


class LLMClient(ABC):
    """Schnittstelle, gegen die der Rest des Programms arbeitet."""

    @abstractmethod
    def frage(self, *, system: str, benutzer: str) -> LLMAntwort:
        """Ein Aufruf. Wirft `LLMFehler`, wenn er endgültig scheitert."""


class OpenAIKompatiblerClient(LLMClient):
    """Anbindung an `/v1/chat/completions`."""

    def __init__(
        self,
        modell: str,
        basis_url: str | None = None,
        api_schluessel: str | None = None,
        temperatur: float = 0.7,
        max_tokens: int = STANDARD_MAX_TOKENS,
        timeout_s: float = 180.0,
        versuche: int = 3,
    ) -> None:
        self.modell = modell
        self.basis_url = (basis_url or DEFAULT_BASE_URL).rstrip("/")
        self.temperatur = temperatur
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.versuche = max(1, versuche)

        self.session = requests.Session()
        self.session.headers["Content-Type"] = "application/json"
        # Ollama braucht keinen Schlüssel, verträgt aber auch keinen leeren
        # Header - deshalb nur setzen, wenn tatsächlich einer da ist.
        schluessel = (api_schluessel or os.environ.get("SYNTHFHIR_LLM_API_KEY", "")).strip()
        if schluessel:
            self.session.headers["Authorization"] = f"Bearer {schluessel}"

    def frage(self, *, system: str, benutzer: str) -> LLMAntwort:
        rumpf = {
            "model": self.modell,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": benutzer},
            ],
            "temperature": self.temperatur,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        url = f"{self.basis_url}/chat/completions"
        beginn = time.perf_counter()

        try:
            antwort = self._post_mit_wartepausen(url, rumpf)
        except requests.exceptions.RequestException as exc:
            raise LLMFehler(
                f"Keine Verbindung zu {url}: {exc}\n"
                "  Lokales Ollama: läuft der Dienst?  ollama list\n"
                "  Cloud-Dienst: stimmt SYNTHFHIR_LLM_BASE_URL?"
            ) from exc

        dauer = time.perf_counter() - beginn
        self._pruefe_status(antwort, url)

        try:
            koerper = antwort.json()
        except ValueError as exc:
            raise LLMFehler(f"Antwort von {url} war kein JSON: {antwort.text[:200]!r}") from exc

        auswahl = koerper.get("choices")
        if not isinstance(auswahl, list) or not auswahl:
            raise LLMFehler(f"Antwort ohne 'choices': {str(koerper)[:300]}")

        nachricht = auswahl[0].get("message") or {}
        text = nachricht.get("content")
        if not isinstance(text, str) or not text.strip():
            raise LLMFehler(f"Leere Antwort (finish_reason={auswahl[0].get('finish_reason')!r}).")

        verbrauch = koerper.get("usage") or {}
        grund = auswahl[0].get("finish_reason")
        return LLMAntwort(
            text=text,
            modell=str(koerper.get("model") or self.modell),
            eingabe_token=int(verbrauch.get("prompt_tokens") or 0),
            ausgabe_token=int(verbrauch.get("completion_tokens") or 0),
            dauer_s=dauer,
            abbruchgrund=FINISH_REASON.get(str(grund), str(grund) if grund else None),
        )

    # -- interne Hilfen -----------------------------------------------------

    def _post_mit_wartepausen(self, url: str, rumpf: dict) -> requests.Response:
        """Wartet bei Ratengrenzen ab, statt sie als Fehler zu verbuchen.

        Kostenlose Kontingente begrenzen Anfragen pro Minute. Ein HTTP 429
        ist eine Wartepause, kein Messergebnis.
        """
        letzte: requests.Response | None = None
        for versuch in range(self.versuche):
            antwort = self.session.post(url, json=rumpf, timeout=self.timeout_s)
            if antwort.status_code != 429 and antwort.status_code < 500:
                return antwort
            letzte = antwort
            if versuch == self.versuche - 1:
                break
            kopfzeile = antwort.headers.get("Retry-After", "")
            try:
                warten = float(kopfzeile)
            except ValueError:
                warten = 0.0
            time.sleep(min(max(warten, 2.0 * (2**versuch)), 60.0))
        assert letzte is not None
        return letzte

    def _pruefe_status(self, antwort: requests.Response, url: str) -> None:
        if antwort.status_code == 429:
            raise LLMFehler(
                f"Ratengrenze bei {url} auch nach Wartezeit aktiv (HTTP 429). "
                "Kontingent erschöpft — später erneut versuchen."
            )
        if antwort.status_code == 413:
            # Anbieter rechnen `max_tokens` in die Anfragegröße ein. Ein zu
            # großzügiger Wert lässt damit JEDE Anfrage scheitern, obwohl
            # inhaltlich nichts falsch ist.
            limit, angefragt = _grenzwerte(antwort.text)
            hinweis = ""
            if limit and angefragt:
                prompt_anteil = max(angefragt - self.max_tokens, 0)
                vorschlag = max(limit - prompt_anteil - 400, 512)
                hinweis = (
                    f"\n  Kontingent: {limit} Token/Minute, angefragt: {angefragt} "
                    f"(davon {self.max_tokens} als max_tokens reserviert)."
                    f"\n  -> max_tokens auf höchstens {vorschlag} setzen."
                )
            raise LLMFehler(f"Anfrage an {url} zu groß für das Kontingent (HTTP 413).{hinweis}")
        if antwort.status_code in (401, 403):
            raise LLMFehler(
                f"Zugriff auf {url} verweigert (HTTP {antwort.status_code}). "
                "Fehlt SYNTHFHIR_LLM_API_KEY?"
            )
        if antwort.status_code == 404:
            raise LLMFehler(
                f"{url} antwortete mit HTTP 404. Stimmt die Basis-URL, und gibt es "
                f"das Modell {self.modell!r}?"
            )
        if antwort.status_code >= 400:
            raise LLMFehler(
                f"{url} antwortete mit HTTP {antwort.status_code}: {antwort.text[:300]}"
            )


class FesterClient(LLMClient):
    """Liefert vorgegebene Antworten — für Tests, nie für den Betrieb."""

    def __init__(self, antworten: list[str] | str) -> None:
        self.antworten = [antworten] if isinstance(antworten, str) else list(antworten)
        self.aufrufe: list[tuple[str, str]] = []

    def frage(self, *, system: str, benutzer: str) -> LLMAntwort:
        self.aufrufe.append((system, benutzer))
        if not self.antworten:
            raise LLMFehler("Keine weitere vorgegebene Antwort vorhanden.")
        text = self.antworten.pop(0) if len(self.antworten) > 1 else self.antworten[0]
        return LLMAntwort(
            text=text,
            modell="fest",
            eingabe_token=len(system + benutzer) // 4,
            ausgabe_token=len(text) // 4,
            dauer_s=0.0,
            abbruchgrund="end_turn",
        )


def client_aus_umgebung() -> LLMClient:
    """Baut den Client aus den Umgebungsvariablen.

    Schlüssel kommen ausschließlich aus der Umgebung, niemals aus dem Code
    (PRD Block 6).
    """
    modell = os.environ.get("SYNTHFHIR_LLM_MODEL", "").strip()
    if not modell:
        raise LLMFehler(
            "SYNTHFHIR_LLM_MODEL ist nicht gesetzt. Verfügbare Modelle des Anbieters:\n"
            f"  curl {os.environ.get('SYNTHFHIR_LLM_BASE_URL', DEFAULT_BASE_URL)}/models"
        )
    return OpenAIKompatiblerClient(
        modell=modell,
        basis_url=os.environ.get("SYNTHFHIR_LLM_BASE_URL") or None,
        temperatur=float(os.environ.get("SYNTHFHIR_LLM_TEMPERATURE", "0.7")),
        max_tokens=int(
            os.environ.get("SYNTHFHIR_LLM_MAX_TOKENS", str(STANDARD_MAX_TOKENS))
        ),
    )


def _grenzwerte(text: str) -> tuple[int | None, int | None]:
    """Liest "Limit N ... Requested M" aus der Fehlermeldung des Anbieters."""
    limit = _LIMIT_RE.search(text)
    angefragt = _REQUESTED_RE.search(text)
    return (
        int(limit.group(1)) if limit else None,
        int(angefragt.group(1)) if angefragt else None,
    )
