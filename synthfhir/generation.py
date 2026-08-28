"""Die beiden Generatoren (Abschnitt 6.2 und 6.3).

Beide enden an derselben Stelle: einer Liste FHIR-Ressourcen mit vom Code
vergebenen IDs und Referenzen. Ab da ist die weitere Kette identisch.

Der Unterschied liegt allein davor:

  Variante A   Prompt -> LLM -> FHIR-JSON -> Parsen
  Variante B   Prompt -> LLM -> Parameter-JSON -> Parsen -> Vorlagen -> FHIR

In Variante B kann das Modell strukturell nichts kaputtmachen: Selbst wenn
es Unsinn liefert, baut die Vorlage eine strukturell korrekte Ressource –
nur eben mit ersetztem Inhalt, was protokolliert wird.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .identity import NormalisationResult, assign_ids
from .jsonx import JsonExtractionError, as_resource_list, extract_json
from .llm import LLMClient, LLMError
from .prompts import build_variant_a_prompt, build_variant_b_prompt
from .scenarios import Scenario
from .templates import TemplateIssue, build_from_parameters


@dataclass
class GenerationResult:
    """Ergebnis eines Generierungsschritts, vor der Validierung."""

    variant: str
    system_prompt: str = ""
    user_prompt: str = ""
    resources: list[dict] = field(default_factory=list)
    raw_responses: list[str] = field(default_factory=list)
    parameters: dict | None = None
    attempts: int = 0
    json_failures: int = 0
    truncations: int = 0
    llm_calls: int = 0
    llm_failures: int = 0
    template_issues: list[TemplateIssue] = field(default_factory=list)
    normalisation: NormalisationResult | None = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None and bool(self.resources)

    @property
    def invented_codes(self) -> int:
        """Nur Variante B: Codes außerhalb des erlaubten Katalogs."""
        return sum(
            1
            for issue in self.template_issues
            if issue.kind in ("invented_condition_code", "invented_observation_code")
        )

    def to_dict(self) -> dict:
        return {
            "variant": self.variant,
            "attempts": self.attempts,
            "llm_calls": self.llm_calls,
            "llm_failures": self.llm_failures,
            "json_failures": self.json_failures,
            "truncations": self.truncations,
            "resource_count": len(self.resources),
            "invented_codes": self.invented_codes,
            "template_issues": [issue.to_dict() for issue in self.template_issues],
            "normalisation": self.normalisation.to_dict() if self.normalisation else None,
            "error": self.error,
        }


def _call_with_retries(
    llm: LLMClient,
    system: str,
    user: str,
    purpose: str,
    max_attempts: int,
    result: GenerationResult,
):
    """Ruft das Modell auf, bis eine parsbare JSON-Antwort kommt.

    Abschnitt 8: begrenzte Wiederholung, danach als Fehlversuch
    protokollieren und den Lauf fortsetzen. Eine nicht parsbare Antwort ist
    dabei eine eigene Fehlerkategorie und kein Infrastrukturproblem.
    """
    last_error = "unbekannt"
    for _ in range(max_attempts):
        result.attempts += 1
        try:
            response = llm.complete(system=system, user=user, purpose=purpose)
            result.llm_calls += 1
        except LLMError as exc:
            result.llm_failures += 1
            last_error = f"LLM-Aufruf fehlgeschlagen: {exc}"
            continue

        result.raw_responses.append(response.text)
        if response.stop_reason == "max_tokens":
            # Abgeschnittene Antwort: fast immer unparsbar. Getrennt gezählt,
            # weil die Ursache bei max_tokens liegt und NICHT beim Modell –
            # sonst zählte eine zu knappe Konfiguration als Architekturfehler.
            result.truncations += 1
            last_error = "Antwort war abgeschnitten (stop_reason=max_tokens)"

        try:
            return extract_json(response.text)
        except JsonExtractionError as exc:
            result.json_failures += 1
            last_error = f"Antwort war kein gültiges JSON: {exc}"

    result.error = last_error
    return None


# ---------------------------------------------------------------------------
# Variante A: LLM erzeugt FHIR direkt (Abschnitt 6.2)
# ---------------------------------------------------------------------------


def generate_variant_a(
    llm: LLMClient, scenario: Scenario, max_attempts: int = 3
) -> GenerationResult:
    """Lässt das Modell unmittelbar FHIR-R4-JSON erzeugen."""
    system, user = build_variant_a_prompt(scenario)
    result = GenerationResult(variant="A", system_prompt=system, user_prompt=user)

    payload = _call_with_retries(llm, system, user, "generate_a", max_attempts, result)
    if payload is None:
        return result

    try:
        resources = as_resource_list(payload)
    except JsonExtractionError as exc:
        result.json_failures += 1
        result.error = f"JSON enthielt keine verwertbaren Ressourcen: {exc}"
        return result

    # Der Antwort wird nicht vertraut: IDs und Referenzen macht der Code.
    normalisation = assign_ids(resources)
    result.normalisation = normalisation
    result.resources = normalisation.resources
    return result


# ---------------------------------------------------------------------------
# Variante B: LLM erzeugt Parameter, Vorlagen bauen FHIR (Abschnitt 6.3)
# ---------------------------------------------------------------------------


def generate_variant_b(
    llm: LLMClient, scenario: Scenario, max_attempts: int = 3
) -> GenerationResult:
    """Lässt das Modell nur ein flaches Parameterobjekt erzeugen."""
    system, user = build_variant_b_prompt(scenario)
    result = GenerationResult(variant="B", system_prompt=system, user_prompt=user)

    payload = _call_with_retries(llm, system, user, "generate_b", max_attempts, result)
    if payload is None:
        return result

    if not isinstance(payload, dict):
        result.json_failures += 1
        result.error = (
            f"Erwartet wurde ein Parameterobjekt, geliefert wurde {type(payload).__name__}."
        )
        return result

    result.parameters = payload
    template_result = build_from_parameters(
        payload,
        {
            "patients": scenario.patients,
            "conditions_per_patient": scenario.conditions_per_patient,
            "observations_per_patient": scenario.observations_per_patient,
        },
    )
    result.template_issues = template_result.issues

    if not template_result.resources:
        result.error = "Aus den Parametern ließ sich keine einzige Ressource bauen."
        return result

    # Dieselbe deterministische ID-Vergabe wie in Variante A (Abschnitt 6.4).
    normalisation = assign_ids(template_result.resources)
    result.normalisation = normalisation
    result.resources = normalisation.resources
    return result
