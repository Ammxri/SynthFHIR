"""Auswahl des LLM-Anbieters über die Konfiguration (Abschnitt 3)."""

from __future__ import annotations

from ..config import LLMSettings
from .base import LLMClient

# Alias -> kanonischer Anbietername. `ollama` ist nur eine bequeme
# Schreibweise für den OpenAI-kompatiblen Adapter mit lokaler Basis-URL.
PROVIDER_ALIASES = {
    "ollama": "openai_compatible",
    "openai-compatible": "openai_compatible",
    "local": "openai_compatible",
}

PROVIDERS = ("anthropic", "openai_compatible", "mock")


def build_client(settings: LLMSettings, budget_limit_eur: float | None = None) -> LLMClient:
    """Erzeugt den konfigurierten Anbieter.

    Ein weiterer Anbieter wäre eine zusätzliche Klasse, die `LLMClient`
    implementiert, plus ein Zweig hier. Mehr braucht die Austauschbarkeit
    im Spike nicht.
    """
    provider = PROVIDER_ALIASES.get(settings.provider.lower(), settings.provider.lower())

    if provider == "anthropic":
        from .anthropic_client import AnthropicClient

        return AnthropicClient(settings, budget_limit_eur)
    if provider == "openai_compatible":
        from .openai_compatible import OpenAICompatibleClient

        return OpenAICompatibleClient(settings, budget_limit_eur)
    if provider == "mock":
        from .mock_client import MockClient

        return MockClient(settings, budget_limit_eur)

    raise ValueError(
        f"Unbekannter LLM-Anbieter {settings.provider!r}. "
        f"Erlaubt: {', '.join(PROVIDERS)} (Aliasse: {', '.join(PROVIDER_ALIASES)}). "
        "'mock' ist nur der Selbsttest."
    )
