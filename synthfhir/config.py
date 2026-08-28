"""Konfiguration des Spikes.

Alle Einstellungen kommen aus Umgebungsvariablen (bei lokaler Entwicklung aus
einer nicht eingecheckten `.env`-Datei). Es liegen keinerlei Geheimnisse im
Code – Abschnitt 3 und 11 der Spezifikation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Preise je 1 Mio. Token in USD (Stand der API-Referenz vom 2026-06-24).
# Nur für die grobe Kostenschätzung im Bericht (Abschnitt 6.8). Über
# SYNTHFHIR_PRICE_IN_USD / SYNTHFHIR_PRICE_OUT_USD überschreibbar.
MODEL_PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-fable-5": (10.00, 50.00),
}

DEFAULT_MODEL = "claude-haiku-4-5"


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def _env_opt(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else None


def _env_float(name: str, default: float) -> float:
    raw = _env_opt(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:  # pragma: no cover – Konfigurationsfehler
        raise ConfigError(f"{name} ist keine Zahl: {raw!r}") from exc


def _env_int(name: str, default: int) -> int:
    raw = _env_opt(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:  # pragma: no cover – Konfigurationsfehler
        raise ConfigError(f"{name} ist keine ganze Zahl: {raw!r}") from exc


class ConfigError(RuntimeError):
    """Fehlerhafte oder fehlende Konfiguration."""


@dataclass(frozen=True)
class LLMSettings:
    """Einstellungen der LLM-Anbindung."""

    provider: str
    model: str
    temperature: float
    max_tokens: int
    effort: str | None
    thinking: str | None
    timeout_s: float
    max_retries: int
    price_in_usd_per_mtok: float | None
    price_out_usd_per_mtok: float | None
    eur_per_usd: float
    # Endpunkt des Anbieters. Für openai_compatible die Basis-URL des
    # Dienstes, für anthropic nur nötig, wenn ein Proxy übersteuert wird.
    base_url: str | None = None

    def prices(self) -> tuple[float, float] | None:
        """Preise (Eingabe, Ausgabe) je 1 Mio. Token in USD – oder None."""
        if self.price_in_usd_per_mtok is not None and self.price_out_usd_per_mtok is not None:
            return (self.price_in_usd_per_mtok, self.price_out_usd_per_mtok)
        if self.is_local:
            # Ein Modell auf dem eigenen Rechner kostet keine API-Gebühren.
            # Ohne diese Regel meldete der Bericht "Kosten unbekannt" und das
            # Ampelkriterium aus Abschnitt 10 fiele grundlos auf gelb.
            return (0.0, 0.0)
        return MODEL_PRICES_USD_PER_MTOK.get(self.model)

    @property
    def is_local(self) -> bool:
        """Läuft das Modell auf diesem Rechner?"""
        if not self.base_url:
            # Der OpenAI-kompatible Adapter zeigt ohne Angabe auf Ollama.
            return self.provider.lower() in ("openai_compatible", "ollama", "local")
        host = self.base_url.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        return host in ("localhost", "127.0.0.1", "::1", "host.docker.internal")


@dataclass(frozen=True)
class ValidatorSettings:
    """Einstellungen der HAPI-FHIR-Anbindung."""

    base_url: str
    timeout_s: float
    readiness_timeout_s: float


@dataclass(frozen=True)
class Settings:
    """Gesamtkonfiguration eines Messlaufs."""

    llm: LLMSettings
    validator: ValidatorSettings
    output_dir: Path
    scenarios_file: Path
    max_repair_rounds: int
    max_generation_attempts: int
    budget_limit_eur: float | None
    bundle_base_url: str


def load_settings(project_root: Path | None = None) -> Settings:
    """Liest die Konfiguration aus `.env` und Umgebungsvariablen."""
    root = project_root or Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")

    # Ein leer gelassener Schlüssel in der .env würde sonst einen echten
    # Schlüssel aus der Shell-Umgebung überschatten.
    if os.environ.get("ANTHROPIC_API_KEY", "").strip() == "":
        os.environ.pop("ANTHROPIC_API_KEY", None)

    provider = _env_str("SYNTHFHIR_LLM_PROVIDER", "anthropic").lower()
    # Die Modell-Vorgabe ist anbieterabhängig: Ein Claude-Modellname wäre bei
    # einem OpenAI-kompatiblen Dienst schlicht falsch. Dort muss das Modell
    # bewusst gewählt werden; `check` weist auf ein leeres Feld hin.
    llm = LLMSettings(
        provider=provider,
        model=_env_str("SYNTHFHIR_LLM_MODEL", DEFAULT_MODEL if provider == "anthropic" else ""),
        temperature=_env_float("SYNTHFHIR_LLM_TEMPERATURE", 0.8),
        max_tokens=_env_int("SYNTHFHIR_LLM_MAX_TOKENS", 16000),
        effort=_env_opt("SYNTHFHIR_LLM_EFFORT"),
        thinking=_env_opt("SYNTHFHIR_LLM_THINKING"),
        timeout_s=_env_float("SYNTHFHIR_LLM_TIMEOUT_S", 300.0),
        max_retries=_env_int("SYNTHFHIR_LLM_MAX_RETRIES", 3),
        price_in_usd_per_mtok=(
            float(v) if (v := _env_opt("SYNTHFHIR_PRICE_IN_USD")) else None
        ),
        price_out_usd_per_mtok=(
            float(v) if (v := _env_opt("SYNTHFHIR_PRICE_OUT_USD")) else None
        ),
        eur_per_usd=_env_float("SYNTHFHIR_EUR_PER_USD", 0.92),
        # Generisch für alle Anbieter; der alte anthropic-spezifische Name
        # bleibt als Rückfallebene gültig.
        base_url=_env_opt("SYNTHFHIR_LLM_BASE_URL")
        or _env_opt("SYNTHFHIR_ANTHROPIC_BASE_URL"),
    )

    validator = ValidatorSettings(
        base_url=_env_str("SYNTHFHIR_FHIR_BASE_URL", "http://localhost:8080/fhir").rstrip("/"),
        timeout_s=_env_float("SYNTHFHIR_FHIR_TIMEOUT_S", 120.0),
        readiness_timeout_s=_env_float("SYNTHFHIR_FHIR_READINESS_TIMEOUT_S", 300.0),
    )

    # Voreinstellung 5 EUR: der in Abschnitt 3 genannte Kostenrahmen gilt
    # auch dann, wenn niemand die Variable gesetzt hat.
    budget_raw = _env_opt("SYNTHFHIR_BUDGET_LIMIT_EUR") or "5.0"
    output_dir = Path(_env_str("SYNTHFHIR_OUTPUT_DIR", "output"))
    scenarios_file = Path(_env_str("SYNTHFHIR_SCENARIOS_FILE", "scenarios.yaml"))

    return Settings(
        llm=llm,
        validator=validator,
        output_dir=output_dir if output_dir.is_absolute() else root / output_dir,
        scenarios_file=(
            scenarios_file if scenarios_file.is_absolute() else root / scenarios_file
        ),
        max_repair_rounds=_env_int("SYNTHFHIR_MAX_REPAIR_ROUNDS", 3),
        max_generation_attempts=_env_int("SYNTHFHIR_MAX_GENERATION_ATTEMPTS", 3),
        budget_limit_eur=None if budget_raw.lower() in ("0", "aus", "none") else float(budget_raw),
        # Basis-URL für Bundle-Einträge. Rein synthetisch, wird nie aufgerufen.
        bundle_base_url=_env_str("SYNTHFHIR_BUNDLE_BASE_URL", "http://synthfhir.local/fhir"),
    )
