"""Anbindung an jeden Dienst mit OpenAI-kompatibler Chat-API.

Warum dieser Adapter existiert: Abschnitt 3 der Spezifikation verlangt, dass
Modell und Anbieter über Konfiguration austauschbar sind, und setzt einen
Kostenrahmen. Ein einziger Adapter gegen `/v1/chat/completions` erschließt
mehrere kostenlose Wege, den Spike überhaupt messen zu können:

  * **Ollama, lokal** – kostet nichts, verlässt den Rechner nicht.
    SYNTHFHIR_LLM_BASE_URL=http://localhost:11434/v1
    Ein Schlüssel wird nicht gebraucht.
  * **Kostenlose Kontingente** (Groq, OpenRouter, Mistral, Google AI Studio) –
    alle sprechen dieselbe Schnittstelle, nur mit anderer Basis-URL und einem
    Schlüssel in SYNTHFHIR_LLM_API_KEY.

Bewusst über `requests` statt über ein zusätzliches SDK: Der Spike braucht
genau einen Endpunkt, und die Abhängigkeitsliste soll klein bleiben.

WICHTIG für die Auswertung: Ein kleines lokales Modell ist deutlich schwächer
als ein Spitzenmodell. Fällt Variante A damit durch, ist das eine UNTERE
Schranke ("A funktioniert nicht mit einem 7B-Modell"), kein Beweis, dass A
auch mit einem starken Modell scheitert. Genau diesen Fall nennt Abschnitt 3
als eigenständiges Messergebnis (Kostenrisiko). Der Bericht hält Anbieter und
Modell deshalb bei jedem Lauf fest.
"""

from __future__ import annotations

import os
import re
import time

import requests

_LIMIT_RE = re.compile(r"Limit\s+(\d+)", re.I)
_REQUESTED_RE = re.compile(r"Requested\s+(\d+)", re.I)


def _parse_token_limits(text: str) -> tuple[int | None, int | None]:
    """Liest "Limit N ... Requested M" aus der Fehlermeldung des Anbieters."""
    limit = _LIMIT_RE.search(text)
    requested = _REQUESTED_RE.search(text)
    return (
        int(limit.group(1)) if limit else None,
        int(requested.group(1)) if requested else None,
    )

from ..config import LLMSettings
from .base import LLMClient, LLMError, LLMResponse

DEFAULT_BASE_URL = "http://localhost:11434/v1"  # Ollama

# OpenAI nennt den Abbruchgrund anders als Anthropic; für die Metrik
# vereinheitlicht auf die Anthropic-Schreibweise.
FINISH_REASON_MAP = {"length": "max_tokens", "stop": "end_turn"}


class OpenAICompatibleClient(LLMClient):
    """LLM-Anbindung über `/v1/chat/completions`."""

    def __init__(self, settings: LLMSettings, budget_limit_eur: float | None = None) -> None:
        super().__init__(settings, budget_limit_eur)
        self.base_url = (settings.base_url or DEFAULT_BASE_URL).rstrip("/")
        self.session = requests.Session()
        # Ollama braucht keinen Schlüssel, verlangt aber auch keinen leeren
        # Header. Andere Dienste brauchen einen – deshalb nur setzen, wenn da.
        api_key = os.environ.get("SYNTHFHIR_LLM_API_KEY", "").strip()
        if api_key:
            self.session.headers["Authorization"] = f"Bearer {api_key}"
        self.session.headers["Content-Type"] = "application/json"

    def _post_with_backoff(self, url: str, payload: dict) -> requests.Response:
        """Schickt die Anfrage und wartet bei Ratengrenzen ab.

        Kostenlose Kontingente (Groq, OpenRouter, Mistral) begrenzen Anfragen
        pro Minute. Ohne Rücksicht darauf würde eine Messreihe reihenweise
        Läufe als "fehlgeschlagen" protokollieren, obwohl inhaltlich nichts
        kaputt ist – das verfälschte die Messung. Ein HTTP 429 ist deshalb
        kein Messergebnis, sondern eine Wartepause.
        """
        attempts = max(1, self.settings.max_retries) + 1
        last: requests.Response | None = None
        for attempt in range(attempts):
            response = self.session.post(url, json=payload, timeout=self.settings.timeout_s)
            if response.status_code != 429 and response.status_code < 500:
                return response
            last = response
            if attempt == attempts - 1:
                break
            # `Retry-After` beachten, sonst exponentiell (2, 4, 8 … Sekunden),
            # gedeckelt, damit eine Messreihe nicht stundenlang schläft.
            header = response.headers.get("Retry-After", "")
            try:
                wait = float(header)
            except ValueError:
                wait = 0.0
            wait = min(max(wait, 2.0 * (2**attempt)), 60.0)
            time.sleep(wait)
        assert last is not None
        return last

    def _complete_once(self, system: str, user: str) -> LLMResponse:
        payload = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
            "stream": False,
        }
        url = f"{self.base_url}/chat/completions"
        started = time.perf_counter()
        try:
            response = self._post_with_backoff(url, payload)
        except requests.exceptions.RequestException as exc:
            raise LLMError(
                f"Keine Verbindung zu {url}: {exc}\n"
                "  -> Bei lokalem Ollama: läuft der Dienst?  ollama list\n"
                "  -> Bei einem Cloud-Dienst: stimmt SYNTHFHIR_LLM_BASE_URL?"
            ) from exc
        latency = time.perf_counter() - started

        if response.status_code == 429:
            raise LLMError(
                f"Ratengrenze bei {url} auch nach Wartezeit noch aktiv (HTTP 429). "
                "Kontingent erschöpft – später erneut messen oder Anbieter wechseln."
            )
        if response.status_code == 413:
            # Die Anfrage ist für das Minutenkontingent zu groß. Anbieter
            # rechnen `max_tokens` in die Anfragegröße mit ein – ein zu
            # großzügiges max_tokens lässt also JEDE Anfrage scheitern,
            # obwohl inhaltlich nichts falsch ist. Das ist kein Messergebnis,
            # sondern ein Konfigurationsfehler, und muss als solcher benannt
            # werden, sonst entwertet es unbemerkt eine ganze Messreihe.
            limit, requested = _parse_token_limits(response.text)
            hint = ""
            if limit and requested:
                prompt_tokens = max(requested - self.settings.max_tokens, 0)
                suggestion = max(limit - prompt_tokens - 400, 512)
                hint = (
                    f"\n  Kontingent: {limit} Token/Minute, angefragt: {requested} "
                    f"(davon {self.settings.max_tokens} als max_tokens reserviert)."
                    f"\n  -> SYNTHFHIR_LLM_MAX_TOKENS auf höchstens {suggestion} setzen."
                )
            raise LLMError(
                f"Anfrage an {url} zu groß für das Kontingent (HTTP 413).{hint}"
            )
        if response.status_code == 401 or response.status_code == 403:
            raise LLMError(
                f"Zugriff auf {url} verweigert (HTTP {response.status_code}). "
                "Fehlt SYNTHFHIR_LLM_API_KEY?"
            )
        if response.status_code == 404:
            raise LLMError(
                f"{url} antwortete mit HTTP 404. Stimmt die Basis-URL, und ist das "
                f"Modell {self.settings.model!r} vorhanden?"
            )
        if response.status_code >= 400:
            raise LLMError(
                f"{url} antwortete mit HTTP {response.status_code}: {response.text[:300]}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise LLMError(f"Antwort von {url} war kein JSON: {response.text[:200]!r}") from exc

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMError(f"Antwort ohne 'choices': {str(body)[:300]}")

        message = choices[0].get("message") or {}
        text = message.get("content")
        if not isinstance(text, str) or not text.strip():
            raise LLMError(
                f"Leere Antwort (finish_reason={choices[0].get('finish_reason')!r})."
            )

        usage = body.get("usage") or {}
        finish = choices[0].get("finish_reason")
        return LLMResponse(
            text=text,
            model=str(body.get("model") or self.settings.model),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            latency_s=latency,
            stop_reason=FINISH_REASON_MAP.get(str(finish), str(finish) if finish else None),
        )
