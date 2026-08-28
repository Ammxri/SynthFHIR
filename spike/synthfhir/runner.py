"""Ablauf eines Messlaufs (Abschnitt 7).

    1. Prüfen, ob der Validierungsserver erreichbar ist   -> CLI
    2. Szenario laden                                     -> CLI
    3. Generierung starten (Variante A oder B)
    4. Antwort in JSON überführen, begrenzt wiederholen
    5. IDs und Referenzen deterministisch setzen
    6. Jede Ressource validieren
    7. Bei Fehlern in Variante A: Korrekturschleife
    8. Referenz-Integritätsprüfung über das ganze Bundle
    9. Alle Artefakte und Metriken schreiben
   10. Wiederholen

Fehlerbehandlung (Abschnitt 8): Ein einzelner Fehlschlag darf die Messreihe
nie abbrechen. Nur zwei Dinge brechen ab – ein nicht erreichbarer
Validierungsserver und eine gerissene Kostengrenze. Beide sind keine
Messergebnisse, sondern Umgebungsprobleme.
"""

from __future__ import annotations

import time
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .artifacts import RunArtifacts
from .config import Settings
from .generation import GenerationResult, generate_variant_a, generate_variant_b
from .integrity import check_resources
from .llm import BudgetExceededError, LLMClient
from .metrics import RunMetrics
from .repair import RepairLoop
from .scenarios import Scenario
from .templates import build_bundle
from .validator import HapiValidator, ValidationResult, ValidatorUnavailableError

Echo = Callable[[str], None]


class SpikeRunner:
    """Führt einzelne Durchläufe und ganze Messreihen aus."""

    def __init__(
        self,
        settings: Settings,
        llm: LLMClient,
        validator: HapiValidator,
        session_dir: Path,
        echo: Echo = print,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.validator = validator
        self.session_dir = session_dir
        self.echo = echo
        self.repair_loop = RepairLoop(llm, validator, settings.max_repair_rounds)

    # -- ein Durchlauf ------------------------------------------------------
    def run_once(self, variant: str, scenario: Scenario, run_index: int) -> RunMetrics:
        """Führt genau einen Durchlauf aus und schreibt alle Artefakte."""
        started = datetime.now(timezone.utc)
        started_perf = _now()
        artifacts = RunArtifacts(self.session_dir, variant, scenario.key, run_index)

        metrics = RunMetrics(
            run_id=f"{variant}-{scenario.key}-{run_index:02d}",
            variant=variant,
            scenario_key=scenario.key,
            scenario_name=scenario.name,
            scenario_fingerprint=scenario.fingerprint(),
            started_at=started.isoformat(timespec="seconds"),
            provider=self.settings.llm.provider,
            model=self.settings.llm.model,
        )
        metrics.expected_by_type = {
            "Patient": scenario.patients,
            "Condition": scenario.expected_conditions,
            "Observation": scenario.expected_observations,
        }
        tokens_before = (self.llm.total_input_tokens, self.llm.total_output_tokens)
        calls_before = len(self.llm.calls)

        try:
            self._execute(variant, scenario, artifacts, metrics)
        except (ValidatorUnavailableError, BudgetExceededError):
            # Umgebungsproblem: nach oben durchreichen, Messreihe endet.
            metrics.status = "aborted"
            metrics.duration_s = _now() - started_perf
            self._finish_llm_metrics(metrics, tokens_before, calls_before)
            artifacts.metrics(metrics.to_dict())
            raise
        except Exception as exc:  # noqa: BLE001 – Abschnitt 8: Lauf fortsetzen
            metrics.status = "aborted"
            metrics.notes.append(f"Unerwartete Ausnahme: {exc}")
            metrics.notes.append(traceback.format_exc(limit=6))
            self.echo(f"    ! Unerwartete Ausnahme, Lauf übersprungen: {exc}")

        metrics.duration_s = _now() - started_perf
        self._finish_llm_metrics(metrics, tokens_before, calls_before)
        artifacts.metrics(metrics.to_dict())
        return metrics

    # -- Kern des Durchlaufs ------------------------------------------------
    def _execute(
        self,
        variant: str,
        scenario: Scenario,
        artifacts: RunArtifacts,
        metrics: RunMetrics,
    ) -> None:
        # Schritt 3 + 4 + 5: Generierung, Parsen, ID-Vergabe
        generator = generate_variant_a if variant == "A" else generate_variant_b
        generation: GenerationResult = generator(
            self.llm, scenario, self.settings.max_generation_attempts
        )

        artifacts.prompt(generation.system_prompt, generation.user_prompt)
        artifacts.raw_responses(generation.raw_responses)
        artifacts.parameters(generation.parameters)
        metrics.generation = generation.to_dict()
        metrics.invented_codes = generation.invented_codes

        if not generation.succeeded:
            metrics.status = "generation_failed"
            metrics.notes.append(generation.error or "Generierung ohne Ergebnis")
            self.echo(f"    ! Generierung fehlgeschlagen: {generation.error}")
            return

        resources = generation.resources
        artifacts.resources(resources)
        metrics.resources_by_type = dict(
            Counter(str(r.get("resourceType") or "?") for r in resources)
        )

        # Schritt 6: jede Ressource einzeln validieren
        first_results: list[ValidationResult] = []
        for resource in resources:
            result = self.validator.validate(resource)
            first_results.append(result)
            artifacts.validation(result.resource_type, result.resource_id, result.outcome)

        metrics.valid_first_attempt = sum(1 for r in first_results if r.is_valid)
        self._count_issues(metrics, first_results)

        # Schritt 7: Korrekturschleife – laut Abschnitt 6.6 nur Variante A
        final_resources = list(resources)
        final_results = list(first_results)

        if variant == "A":
            for index, (resource, result) in enumerate(zip(resources, first_results)):
                if result.is_valid:
                    continue
                outcome = self.repair_loop.repair(resource, result)
                for round_no, snapshot in enumerate(outcome.snapshots, start=1):
                    artifacts.repair_snapshot(
                        outcome.resource_type, outcome.resource_id, round_no, snapshot
                    )
                artifacts.validation(
                    outcome.resource_type,
                    f"{outcome.resource_id}-final",
                    outcome.final_result.outcome,
                )
                final_resources[index] = outcome.resource
                final_results[index] = outcome.final_result

                metrics.repaired_resources += 1
                metrics.repair_rounds_total += outcome.rounds_used
                metrics.non_improving_rounds += outcome.non_improving_rounds
                metrics.repair_json_failures += outcome.json_failures
                metrics.identity_corrections.extend(outcome.identity_corrections)

        metrics.valid_final = sum(1 for r in final_results if r.is_valid)
        metrics.invalid_final = len(final_results) - metrics.valid_final

        # Schritt 8: Referenz-Integritätsprüfung über das ganze Bundle
        bundle = build_bundle(final_resources, self.settings.bundle_base_url)
        artifacts.bundle(bundle)
        integrity = check_resources(final_resources)
        artifacts.integrity(integrity.to_dict())
        metrics.integrity = integrity.to_dict()

        self.echo(
            f"    {metrics.valid_first_attempt}/{len(resources)} beim ersten Versuch valide, "
            f"{metrics.valid_final}/{len(resources)} am Ende, "
            f"{integrity.broken_reference_count} kaputte Referenzen"
        )

    # -- Hilfen -------------------------------------------------------------
    @staticmethod
    def _count_issues(metrics: RunMetrics, results: list[ValidationResult]) -> None:
        """Zählt die Befunde des ERSTEN Validierungsdurchgangs.

        Bewusst der erste Durchgang: Er zeigt, was die jeweilige Architektur
        produziert. Was die Korrekturschleife daraus macht, steht in den
        Reparaturmetriken.
        """
        for result in results:
            metrics.warning_count += len(result.warnings)
            for issue in result.issues:
                category = issue.category()
                if issue.blocking:
                    metrics.error_signatures[issue.signature()] += 1
                    metrics.error_categories[category] += 1
                    if category == "terminologie/code":
                        metrics.code_related_issues += 1
                elif category == "terminologie/code":
                    metrics.code_related_warnings += 1

    def _finish_llm_metrics(
        self, metrics: RunMetrics, tokens_before: tuple[int, int], calls_before: int
    ) -> None:
        """Rechnet den Verbrauch dieses Laufs aus den Gesamtsummen heraus."""
        metrics.input_tokens = self.llm.total_input_tokens - tokens_before[0]
        metrics.output_tokens = self.llm.total_output_tokens - tokens_before[1]
        metrics.llm_calls = len(self.llm.calls) - calls_before

        prices = self.settings.llm.prices()
        if prices is None:
            metrics.cost_usd = None
            metrics.cost_eur = None
            return
        price_in, price_out = prices
        usd = (
            metrics.input_tokens / 1_000_000 * price_in
            + metrics.output_tokens / 1_000_000 * price_out
        )
        metrics.cost_usd = usd
        metrics.cost_eur = usd * self.settings.llm.eur_per_usd

    # -- ganze Messreihe ----------------------------------------------------
    def run_series(
        self, variants: list[str], scenarios: list[Scenario], repeats: int
    ) -> list[RunMetrics]:
        """Führt alle Kombinationen aus Varianten, Szenarien und Wiederholungen aus."""
        collected: list[RunMetrics] = []
        for variant in variants:
            self.echo(f"\n=== Variante {variant} ===")
            for scenario in scenarios:
                self.echo(f"  Szenario '{scenario.key}' ({scenario.name})")
                for index in range(1, repeats + 1):
                    self.echo(f"  Lauf {index}/{repeats}")
                    collected.append(self.run_once(variant, scenario, index))
        return collected


def _now() -> float:
    return time.perf_counter()
