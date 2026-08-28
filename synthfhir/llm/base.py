"""Gemeinsame Schnittstelle und Buchhaltung aller LLM-Anbindungen."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..config import LLMSettings


class LLMError(RuntimeError):
    """Der LLM-Aufruf ist endgültig fehlgeschlagen."""


class BudgetExceededError(RuntimeError):
    """Die geschätzten Kosten haben die konfigurierte Obergrenze überschritten.

    Absicherung des Kostenrahmens aus Abschnitt 3 der Spezifikation. Wird
    geworfen, BEVOR ein weiterer Aufruf Geld kostet.
    """


@dataclass(frozen=True)
class LLMResponse:
    """Antwort eines LLM-Aufrufs inklusive Token-Verbrauch."""

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    # Warum das Modell aufgehört hat. "max_tokens" bedeutet abgeschnittene
    # Antwort und ist die häufigste Ursache für unparsbares JSON.
    stop_reason: str | None = None


@dataclass
class LLMCall:
    """Protokolleintrag eines einzelnen Aufrufs – Grundlage der Kostenmetrik."""

    purpose: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    ok: bool
    error: str | None = None
    stop_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "purpose": self.purpose,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_s": round(self.latency_s, 3),
            "ok": self.ok,
            "error": self.error,
            "stop_reason": self.stop_reason,
        }


class LLMClient(ABC):
    """Basisklasse: Buchhaltung, Kostenschätzung und Budgetgrenze.

    Unterklassen implementieren nur `_complete_once`. Alles rundherum
    (Zählung der Aufrufe, Token-Summen, Notbremse) ist anbieterunabhängig.
    """

    def __init__(self, settings: LLMSettings, budget_limit_eur: float | None = None) -> None:
        self.settings = settings
        self.budget_limit_eur = budget_limit_eur
        self.calls: list[LLMCall] = []

    # -- von Unterklassen zu implementieren --------------------------------
    @abstractmethod
    def _complete_once(self, system: str, user: str) -> LLMResponse:
        """Führt genau einen Aufruf aus oder wirft `LLMError`."""

    # -- gemeinsame Logik ---------------------------------------------------
    def complete(self, *, system: str, user: str, purpose: str) -> LLMResponse:
        """Ruft das Modell auf und protokolliert den Aufruf."""
        self._enforce_budget()
        started = time.perf_counter()
        try:
            response = self._complete_once(system, user)
        except LLMError as exc:
            self.calls.append(
                LLMCall(
                    purpose=purpose,
                    model=self.settings.model,
                    input_tokens=0,
                    output_tokens=0,
                    latency_s=time.perf_counter() - started,
                    ok=False,
                    error=str(exc)[:400],
                )
            )
            raise
        self.calls.append(
            LLMCall(
                purpose=purpose,
                model=response.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                latency_s=response.latency_s,
                ok=True,
                stop_reason=response.stop_reason,
            )
        )
        return response

    # -- Kosten -------------------------------------------------------------
    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    def estimated_cost_usd(self) -> float | None:
        """Grobe Kostenschätzung. None, wenn kein Preis hinterlegt ist."""
        prices = self.settings.prices()
        if prices is None:
            return None
        price_in, price_out = prices
        return (
            self.total_input_tokens / 1_000_000 * price_in
            + self.total_output_tokens / 1_000_000 * price_out
        )

    def estimated_cost_eur(self) -> float | None:
        usd = self.estimated_cost_usd()
        return None if usd is None else usd * self.settings.eur_per_usd

    def _enforce_budget(self) -> None:
        if self.budget_limit_eur is None:
            return
        spent = self.estimated_cost_eur()
        if spent is not None and spent >= self.budget_limit_eur:
            raise BudgetExceededError(
                f"Geschätzte Kosten {spent:.2f} EUR erreichen die Obergrenze "
                f"{self.budget_limit_eur:.2f} EUR (SYNTHFHIR_BUDGET_LIMIT_EUR). "
                "Messreihe wird abgebrochen."
            )
