"""Dünne Abstraktionsschicht über einen LLM-Anbieter (Abschnitt 3).

Der Spike bindet genau einen echten Anbieter an (Anthropic). Modell und
Anbieter sind über Umgebungsvariablen austauschbar; ein weiterer Anbieter
wäre eine zusätzliche Klasse, die `LLMClient` implementiert, plus ein Eintrag
in `factory.build_client`. Bewusst kein Lock-in, aber auch kein Vorrat an
ungenutzten Integrationen.
"""

from .base import BudgetExceededError, LLMCall, LLMClient, LLMError, LLMResponse
from .factory import build_client

__all__ = [
    "BudgetExceededError",
    "LLMCall",
    "LLMClient",
    "LLMError",
    "LLMResponse",
    "build_client",
]
