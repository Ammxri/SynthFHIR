"""Kommandozeilen-Einstiegspunkt (Abschnitt 6.9).

    python -m synthfhir check
        Prüft Konfiguration und Erreichbarkeit des Validierungsservers.

    python -m synthfhir run --variant A --scenario einfach --repeats 3
        Führt einen einzelnen Variante/Szenario-Block aus.

    python -m synthfhir compare --repeats 7
        Führt beide Varianten über alle Szenarien aus und schreibt am Ende
        den Vergleichsbericht. 7 Wiederholungen x 3 Szenarien = 21 Läufe je
        Variante und erfüllt damit die Mindestanforderung aus Abschnitt 10.

    python -m synthfhir report --session output/20260828-120000
        Erzeugt den Vergleichsbericht aus bereits vorhandenen Metrikdateien
        neu, ohne zu messen.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .artifacts import collect_run_metrics, session_dir, write_json, write_text
from .config import ConfigError, Settings, load_settings
from .llm import BudgetExceededError, LLMError, build_client
from .report import build_report
from .runner import SpikeRunner
from .scenarios import Scenario, ScenarioError, load_scenarios
from .validator import HapiValidator, ValidatorUnavailableError

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _echo(message: str = "") -> None:
    print(message, flush=True)


def _settings_summary(settings: Settings, fhir_version: str | None = None) -> dict:
    """Konfigurationsüberblick ohne jedes Geheimnis."""
    return {
        "provider": settings.llm.provider,
        "model": settings.llm.model,
        "temperature": settings.llm.temperature,
        "max_tokens": settings.llm.max_tokens,
        "max_repair_rounds": settings.max_repair_rounds,
        "max_generation_attempts": settings.max_generation_attempts,
        "llm_base_url": settings.llm.base_url or "(Vorgabe des Anbieters)",
        "fhir_base_url": settings.validator.base_url,
        "fhir_version": fhir_version or "unbekannt",
        "budget_limit_eur": settings.budget_limit_eur,
        "scenarios_file": str(settings.scenarios_file),
    }


def _pick_scenarios(all_scenarios: dict[str, Scenario], selection: str) -> list[Scenario]:
    if selection in ("alle", "all", "*"):
        return list(all_scenarios.values())
    if selection not in all_scenarios:
        raise ScenarioError(
            f"Unbekanntes Szenario {selection!r}. Verfügbar: {', '.join(all_scenarios)}"
        )
    return [all_scenarios[selection]]


def _apply_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    """Setzt die per Kommandozeile erlaubten Übersteuerungen um."""
    import dataclasses

    llm = settings.llm
    if getattr(args, "llm", None):
        llm = dataclasses.replace(llm, provider=args.llm)
    if getattr(args, "model", None):
        llm = dataclasses.replace(llm, model=args.model)
    return dataclasses.replace(settings, llm=llm)


# --- Befehle ---------------------------------------------------------------


def cmd_check(settings: Settings, args: argparse.Namespace) -> int:
    scenarios = load_scenarios(settings.scenarios_file)
    _echo("Konfiguration")
    for key, value in _settings_summary(settings).items():
        _echo(f"  {key:26s} {value}")
    _echo(f"\nSzenarien ({len(scenarios)}):")
    for scenario in scenarios.values():
        _echo(
            f"  {scenario.key:16s} {scenario.expected_total:3d} Ressourcen "
            f"(Fingerabdruck {scenario.fingerprint()})  {scenario.name}"
        )

    import os

    if settings.llm.provider in ("openai_compatible", "ollama", "local"):
        if not settings.llm.model:
            _echo(
                "\n! SYNTHFHIR_LLM_MODEL ist leer. Verfügbare Modelle des Anbieters:\n"
                f"  curl {settings.llm.base_url or 'http://localhost:11434/v1'}/models"
            )
        if not settings.llm.is_local and not os.environ.get("SYNTHFHIR_LLM_API_KEY", "").strip():
            _echo(
                "\n! SYNTHFHIR_LLM_API_KEY ist nicht gesetzt, der Endpunkt ist aber "
                f"nicht lokal ({settings.llm.base_url}).\n"
                "  Den kostenlosen Schlüssel des Anbieters in die .env eintragen."
            )

    if settings.llm.provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            _echo(
                "\n! ANTHROPIC_API_KEY ist nicht gesetzt. Für echte Messläufe den "
                "Schlüssel in die .env eintragen."
            )
        if os.environ.get("ANTHROPIC_BASE_URL") and not settings.llm.base_url:
            _echo(
                "\n! ANTHROPIC_BASE_URL ist in der Umgebung gesetzt. Das SDK schickt "
                "die Messläufe an diesen Endpunkt.\n"
                "  Falls das nicht gewollt ist, in der .env setzen:\n"
                "  SYNTHFHIR_ANTHROPIC_BASE_URL=https://api.anthropic.com"
            )

    _echo("\nValidierungsserver")
    validator = HapiValidator(
        settings.validator.base_url,
        settings.validator.timeout_s,
        min(settings.validator.readiness_timeout_s, 20.0),
    )
    try:
        version = validator.wait_until_ready(poll_interval_s=2.0)
    except ValidatorUnavailableError as exc:
        _echo(f"  NICHT BEREIT\n{exc}")
        return 1
    _echo(f"  bereit unter {settings.validator.base_url}, FHIR-Version {version}")
    return 0


def _execute_series(
    settings: Settings,
    variants: list[str],
    scenarios: list[Scenario],
    repeats: int,
    session_name: str | None,
) -> int:
    stamp = session_name or datetime.now().strftime("%Y%m%d-%H%M%S")
    session = session_dir(settings.output_dir, stamp)

    validator = HapiValidator(
        settings.validator.base_url,
        settings.validator.timeout_s,
        settings.validator.readiness_timeout_s,
    )
    # Schritt 1 aus Abschnitt 7: erst prüfen, dann messen.
    try:
        fhir_version = validator.wait_until_ready()
    except ValidatorUnavailableError as exc:
        _echo(f"ABBRUCH: {exc}")
        return 2
    _echo(f"Validierungsserver bereit (FHIR {fhir_version}).")

    try:
        llm = build_client(settings.llm, settings.budget_limit_eur)
    except (LLMError, ValueError) as exc:
        _echo(f"ABBRUCH: LLM-Anbindung nicht möglich: {exc}")
        return 2

    summary = _settings_summary(settings, fhir_version)
    write_json(
        session / "session.json",
        {
            "session": stamp,
            "settings": summary,
            "variants": variants,
            "scenarios": [s.key for s in scenarios],
            "repeats": repeats,
            "planned_runs": len(variants) * len(scenarios) * repeats,
        },
    )
    _echo(f"Messreihe: {len(variants) * len(scenarios) * repeats} Läufe -> {session}")

    runner = SpikeRunner(settings, llm, validator, session, echo=_echo)
    exit_code = 0
    try:
        runner.run_series(variants, scenarios, repeats)
    except ValidatorUnavailableError as exc:
        _echo(f"\nABBRUCH: Validierungsserver nicht mehr erreichbar.\n{exc}")
        exit_code = 2
    except BudgetExceededError as exc:
        _echo(f"\nABBRUCH: {exc}")
        exit_code = 3
    except KeyboardInterrupt:
        _echo("\nAbbruch durch Benutzer. Bereits geschriebene Artefakte bleiben erhalten.")
        exit_code = 130

    # Bericht immer aus dem schreiben, was tatsächlich gemessen wurde.
    runs = collect_run_metrics(session)
    report = build_report(runs, summary)
    report_path = session / "bericht.md"
    write_text(report_path, report)

    cost = llm.estimated_cost_eur()
    _echo(f"\n{len(runs)} Läufe erfasst.")
    if cost is not None:
        _echo(f"Geschätzte Kosten dieser Messreihe: {cost:.3f} EUR")
    _echo(f"Bericht: {report_path}")
    return exit_code


def cmd_run(settings: Settings, args: argparse.Namespace) -> int:
    scenarios = load_scenarios(settings.scenarios_file)
    selected = _pick_scenarios(scenarios, args.scenario)
    return _execute_series(
        settings, [args.variant], selected, args.repeats, args.session
    )


def cmd_compare(settings: Settings, args: argparse.Namespace) -> int:
    scenarios = load_scenarios(settings.scenarios_file)
    return _execute_series(
        settings, ["A", "B"], list(scenarios.values()), args.repeats, args.session
    )


def cmd_report(settings: Settings, args: argparse.Namespace) -> int:
    session = Path(args.session)
    if not session.is_absolute():
        session = PROJECT_ROOT / session
    if not session.exists():
        _echo(f"Messreihe nicht gefunden: {session}")
        return 1
    runs = collect_run_metrics(session)
    if not runs:
        _echo(f"Keine Metrikdateien unter {session} gefunden.")
        return 1

    summary = _settings_summary(settings)
    session_file = session / "session.json"
    if session_file.exists():
        import json

        try:
            stored = json.loads(session_file.read_text(encoding="utf-8")).get("settings")
            if isinstance(stored, dict):
                summary = stored
        except (OSError, ValueError):
            pass

    report_path = session / "bericht.md"
    write_text(report_path, build_report(runs, summary))
    _echo(f"{len(runs)} Läufe ausgewertet.\nBericht: {report_path}")
    return 0


# --- Argumente -------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m synthfhir",
        description=(
            "SynthFHIR Phase-0-Spike: Vergleich zweier Architekturvarianten für "
            "LLM-erzeugte FHIR-R4-Testdaten. Erzeugt ausschließlich synthetische "
            "Daten, nicht für die klinische Nutzung."
        ),
    )
    parser.add_argument(
        "--llm",
        choices=["anthropic", "openai_compatible", "ollama", "mock"],
        help=(
            "Anbieter übersteuern. 'ollama' ist der OpenAI-kompatible Adapter "
            "mit lokaler Basis-URL, 'mock' der kostenlose Selbsttest."
        ),
    )
    parser.add_argument("--model", help="Modell übersteuern.")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="Konfiguration und Serverbereitschaft prüfen")
    check.set_defaults(func=cmd_check)

    run = sub.add_parser("run", help="Einzelne Variante über ein Szenario messen")
    run.add_argument("--variant", choices=["A", "B"], required=True)
    run.add_argument(
        "--scenario", default="alle", help="Szenario-Schlüssel oder 'alle' (Standard)"
    )
    run.add_argument("--repeats", type=int, default=1, help="Anzahl Wiederholungen")
    run.add_argument("--session", help="Name des Ausgabeverzeichnisses")
    run.set_defaults(func=cmd_run)

    compare = sub.add_parser(
        "compare", help="Beide Varianten über alle Szenarien messen und Bericht erzeugen"
    )
    compare.add_argument(
        "--repeats",
        type=int,
        default=7,
        help="Wiederholungen je Szenario und Variante (Standard 7 -> 21 Läufe je Variante)",
    )
    compare.add_argument("--session", help="Name des Ausgabeverzeichnisses")
    compare.set_defaults(func=cmd_compare)

    report = sub.add_parser("report", help="Bericht aus vorhandenen Metrikdateien neu erzeugen")
    report.add_argument("--session", required=True, help="Pfad zum Messreihenverzeichnis")
    report.set_defaults(func=cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows-Konsolen verwenden nicht immer UTF-8; ohne das brechen Umlaute
    # die Ausgabe mit einem UnicodeEncodeError ab.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = _apply_overrides(load_settings(PROJECT_ROOT), args)
    except ConfigError as exc:
        _echo(f"Konfigurationsfehler: {exc}")
        return 1

    if getattr(args, "repeats", 1) is not None and getattr(args, "repeats", 1) < 1:
        _echo("--repeats muss mindestens 1 sein.")
        return 1

    try:
        return int(args.func(settings, args))
    except ScenarioError as exc:
        _echo(f"Szenariofehler: {exc}")
        return 1
    except KeyboardInterrupt:
        _echo("\nAbgebrochen.")
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
