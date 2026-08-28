"""Anbindung an die Claude-API über das offizielle Anthropic-SDK.

Bewusst schlank gehalten: ein Aufruf, ein Text zurück, Token-Zahlen für die
Kostenmetrik. Der API-Schlüssel wird nie übergeben, sondern vom SDK aus der
Umgebungsvariablen ANTHROPIC_API_KEY gelesen (Abschnitt 11).
"""

from __future__ import annotations

import time

import anthropic

from ..config import LLMSettings
from .base import LLMClient, LLMError, LLMResponse

# Modelle, die keine Sampling-Parameter (temperature/top_p/top_k) mehr
# akzeptieren – ein Aufruf mit `temperature` endet dort in einem HTTP 400.
MODELS_WITHOUT_SAMPLING = frozenset(
    {
        "claude-fable-5",
        "claude-mythos-5",
        "claude-opus-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-5",
        "claude-sonnet-4-6",
    }
)


class AnthropicClient(LLMClient):
    """LLM-Anbindung für Claude-Modelle."""

    def __init__(self, settings: LLMSettings, budget_limit_eur: float | None = None) -> None:
        super().__init__(settings, budget_limit_eur)
        client_args: dict = {
            "timeout": settings.timeout_s,
            "max_retries": settings.max_retries,
        }
        # Ohne explizite Vorgabe löst das SDK den Endpunkt selbst auf – und
        # zieht dabei auch eine gesetzte Umgebungsvariable ANTHROPIC_BASE_URL
        # heran. Auf Entwicklungsrechnern mit Proxy ist das eine stille
        # Falle: die Messläufe gingen dann woanders hin.
        if settings.base_url:
            client_args["base_url"] = settings.base_url

        try:
            self._client = anthropic.Anthropic(**client_args)
        except Exception as exc:  # pragma: no cover – Konfigurationsfehler
            raise LLMError(f"Anthropic-Client konnte nicht erzeugt werden: {exc}") from exc
        self._max_tokens = settings.max_tokens
        self._max_tokens_clamped = False
        # Parameter, die das gewählte Modell abgelehnt hat und die deshalb
        # nicht erneut mitgeschickt werden.
        self._dropped_params: set[str] = set()

    # -- Aufbau der Anfrage -------------------------------------------------
    def _clamp_max_tokens(self) -> None:
        """Begrenzt max_tokens auf das, was das Modell tatsächlich kann.

        Verhindert, dass eine ganze Messreihe an einem HTTP 400 scheitert,
        weil das konfigurierte max_tokens über der Modellgrenze liegt.
        """
        if self._max_tokens_clamped:
            return
        self._max_tokens_clamped = True
        try:
            info = self._client.models.retrieve(self.settings.model)
            cap = getattr(info, "max_tokens", None)
            if isinstance(cap, int) and cap > 0 and cap < self._max_tokens:
                self._max_tokens = cap
        except Exception:
            # Modelle-Endpunkt nicht verfügbar: konfigurierten Wert behalten.
            pass

    def _build_params(self, system: str, user: str) -> dict:
        params: dict = {
            "model": self.settings.model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if (
            "temperature" not in self._dropped_params
            and self.settings.model not in MODELS_WITHOUT_SAMPLING
        ):
            params["temperature"] = self.settings.temperature
        if self.settings.thinking and "thinking" not in self._dropped_params:
            params["thinking"] = {"type": self.settings.thinking}
        if self.settings.effort and "output_config" not in self._dropped_params:
            params["output_config"] = {"effort": self.settings.effort}
        return params

    # -- Ausführung ---------------------------------------------------------
    def _complete_once(self, system: str, user: str) -> LLMResponse:
        self._clamp_max_tokens()
        started = time.perf_counter()
        try:
            message = self._client.messages.create(**self._build_params(system, user))
        except anthropic.BadRequestError as exc:
            # Ein Parameter passt nicht zum Modell (z. B. `temperature` auf
            # einem neueren Modell). Einmal ohne diesen Parameter erneut
            # versuchen, statt die ganze Messreihe zu verlieren.
            dropped = self._drop_offending_param(str(exc))
            if dropped is None:
                raise LLMError(f"Ungültige Anfrage an die Claude-API: {exc}") from exc
            started = time.perf_counter()
            try:
                message = self._client.messages.create(**self._build_params(system, user))
            except Exception as retry_exc:
                raise LLMError(
                    f"Anfrage auch ohne Parameter {dropped!r} fehlgeschlagen: {retry_exc}"
                ) from retry_exc
        except anthropic.AuthenticationError as exc:
            raise LLMError(
                "Authentifizierung fehlgeschlagen. Ist ANTHROPIC_API_KEY in der "
                f".env gesetzt? ({exc})"
            ) from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude-API antwortete mit HTTP {exc.status_code}: {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"Keine Verbindung zur Claude-API: {exc}") from exc
        except Exception as exc:  # pragma: no cover – unerwartet
            raise LLMError(f"Unerwarteter Fehler beim LLM-Aufruf: {exc}") from exc

        latency = time.perf_counter() - started
        stop_reason = getattr(message, "stop_reason", None)
        if stop_reason == "refusal":
            raise LLMError("Das Modell hat die Anfrage abgelehnt (stop_reason=refusal).")

        text = "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )
        if not text.strip():
            raise LLMError(f"Leere Antwort des Modells (stop_reason={stop_reason}).")

        return LLMResponse(
            text=text,
            model=getattr(message, "model", self.settings.model),
            input_tokens=int(getattr(message.usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(message.usage, "output_tokens", 0) or 0),
            latency_s=latency,
            stop_reason=str(stop_reason) if stop_reason else None,
        )

    def _drop_offending_param(self, error_text: str) -> str | None:
        """Erkennt am Fehlertext, welcher Parameter entfernt werden muss."""
        lowered = error_text.lower()
        for param in ("temperature", "thinking", "output_config"):
            if param in lowered and param not in self._dropped_params:
                self._dropped_params.add(param)
                return param
        return None
