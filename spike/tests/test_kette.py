"""End-to-End-Test der kompletten Kette.

Verwendet den Mock-Anbieter (kostenlos, deterministisch) und einen Stub-
Validator, der die für den Spike relevanten HAPI-Regeln nachbildet. Damit
lässt sich der Ablauf aus Abschnitt 7 vollständig prüfen, ohne Docker und
ohne API-Schlüssel.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from synthfhir.codes import CONDITION_CODES, OBSERVATION_CODES
from synthfhir.config import LLMSettings, Settings, ValidatorSettings
from synthfhir.llm.mock_client import MockClient
from synthfhir.report import build_report
from synthfhir.runner import SpikeRunner
from synthfhir.scenarios import Scenario
from synthfhir.validator import Issue, ValidationResult


class StubValidator:
    """Bildet die Regeln nach, die für den Spike zählen.

    Bewusst nur die harten Fälle: Pflichtfelder, unbekannte Codes,
    Geschlechts-Binding. Ersetzt HAPI nicht, prüft aber die Verdrahtung.
    """

    base_url = "stub://validator"

    def __init__(self) -> None:
        self.calls = 0

    def validate(self, resource: dict) -> ValidationResult:
        self.calls += 1
        resource_type = str(resource.get("resourceType") or "")
        issues: list[Issue] = []

        if resource_type == "Observation":
            if "status" not in resource:
                issues.append(
                    Issue(
                        "error",
                        "required",
                        "Observation.status: minimum required = 1, but only found 0",
                        "Observation.status",
                    )
                )
            code = _coding(resource.get("code"))
            if code is None:
                issues.append(
                    Issue("error", "required", "Observation.code is required", "Observation.code")
                )
            elif code not in OBSERVATION_CODES:
                issues.append(
                    Issue(
                        "warning",
                        "code-invalid",
                        f"Unable to validate code '{code}' - no terminology server",
                        "Observation.code.coding[0].code",
                    )
                )

        if resource_type == "Condition":
            if not resource.get("subject"):
                issues.append(
                    Issue(
                        "error",
                        "required",
                        "Condition.subject: minimum required = 1, but only found 0",
                        "Condition.subject",
                    )
                )
            code = _coding(resource.get("code"))
            if code is not None and code not in CONDITION_CODES:
                issues.append(
                    Issue(
                        "warning",
                        "code-invalid",
                        f"Unable to validate code '{code}'",
                        "Condition.code.coding[0].code",
                    )
                )

        if resource_type == "Patient":
            gender = resource.get("gender")
            if gender is not None and gender not in ("male", "female", "other", "unknown"):
                issues.append(
                    Issue(
                        "error",
                        "code-invalid",
                        f"Unknown code '{gender}' for 'administrative-gender'",
                        "Patient.gender",
                    )
                )

        return ValidationResult(
            resource_type=resource_type or "(fehlt)",
            resource_id=str(resource.get("id") or "?"),
            issues=issues,
            outcome={
                "resourceType": "OperationOutcome",
                "issue": [i.to_dict() for i in issues],
            },
            http_status=200,
        )


def _coding(concept: object) -> str | None:
    if not isinstance(concept, dict):
        return None
    coding = concept.get("coding")
    if isinstance(coding, list) and coding and isinstance(coding[0], dict):
        value = coding[0].get("code")
        return str(value) if value else None
    return None


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        llm=LLMSettings(
            provider="mock",
            model="mock",
            temperature=0.8,
            max_tokens=4000,
            effort=None,
            thinking=None,
            timeout_s=30.0,
            max_retries=1,
            price_in_usd_per_mtok=1.0,
            price_out_usd_per_mtok=5.0,
            eur_per_usd=0.92,
        ),
        validator=ValidatorSettings(base_url="stub://validator", timeout_s=5.0, readiness_timeout_s=5.0),
        output_dir=tmp_path / "output",
        scenarios_file=Path("scenarios.yaml"),
        max_repair_rounds=3,
        max_generation_attempts=3,
        budget_limit_eur=None,
        bundle_base_url="http://synthfhir.local/fhir",
    )


@pytest.fixture
def scenario() -> Scenario:
    return Scenario(
        key="test",
        name="Testszenario",
        description="Ein Patient mit einer Diagnose und zwei Messwerten.",
        patients=1,
        conditions_per_patient=1,
        observations_per_patient=2,
    )


def _runner(settings: Settings, tmp_path: Path) -> tuple[SpikeRunner, StubValidator, MockClient]:
    llm = MockClient(settings.llm)
    validator = StubValidator()
    session = tmp_path / "session"
    session.mkdir(parents=True, exist_ok=True)
    runner = SpikeRunner(settings, llm, validator, session, echo=lambda *_: None)
    return runner, validator, llm


def test_variante_b_erzeugt_durchgehend_valide_ressourcen(settings, scenario, tmp_path):
    runner, _, _ = _runner(settings, tmp_path)
    metrics = runner.run_once("B", scenario, 1)

    assert metrics.status == "ok"
    assert metrics.resources_total == 4  # 1 Patient + 1 Condition + 2 Observations
    assert metrics.valid_first_attempt == metrics.resources_total
    assert metrics.invalid_final == 0
    assert metrics.repair_rounds_total == 0        # Variante B hat keine Schleife
    assert metrics.integrity["broken_reference_count"] == 0
    assert metrics.invented_codes == 1             # der Mock baut genau einen ein


def test_variante_a_wird_durch_die_korrekturschleife_valide(settings, scenario, tmp_path):
    runner, _, _ = _runner(settings, tmp_path)
    metrics = runner.run_once("A", scenario, 1)

    assert metrics.status == "ok"
    # Der Mock lässt beim ersten Messwert `status` weg -> genau eine Ressource
    # ist zunächst invalide und wird von der Schleife repariert.
    assert metrics.valid_first_attempt == metrics.resources_total - 1
    assert metrics.repaired_resources == 1
    assert metrics.repair_rounds_total >= 1
    assert metrics.valid_final == metrics.resources_total


def test_variante_a_haelt_kaputte_referenz_fest(settings, scenario, tmp_path):
    """Der Mock verweist bei der letzten Diagnose auf einen fremden Patienten."""
    runner, _, _ = _runner(settings, tmp_path)
    metrics = runner.run_once("A", scenario, 1)
    assert metrics.integrity["broken_reference_count"] == 1
    assert metrics.integrity["missing_patient_link"]


def test_artefakte_werden_vollstaendig_geschrieben(settings, scenario, tmp_path):
    runner, _, _ = _runner(settings, tmp_path)
    runner.run_once("A", scenario, 1)
    run_dir = tmp_path / "session" / "variante-A" / "test" / "lauf-01"

    for name in ("prompt.txt", "ressourcen.json", "bundle.json", "integritaet.json", "metriken.json"):
        assert (run_dir / name).exists(), name
    assert list((run_dir / "validierung").glob("*.json"))
    assert list((run_dir / "korrektur").glob("*runde-1.json"))
    assert list(run_dir.glob("llm-roh-*.txt"))

    bundle = json.loads((run_dir / "bundle.json").read_text(encoding="utf-8"))
    assert bundle["resourceType"] == "Bundle" and bundle["type"] == "collection"


def test_ids_stammen_auch_nach_der_korrektur_vom_code(settings, scenario, tmp_path):
    runner, _, _ = _runner(settings, tmp_path)
    runner.run_once("A", scenario, 1)
    run_dir = tmp_path / "session" / "variante-A" / "test" / "lauf-01"
    bundle = json.loads((run_dir / "bundle.json").read_text(encoding="utf-8"))
    ids = [entry["resource"]["id"] for entry in bundle["entry"]]
    assert all(i.startswith(("pat-", "cond-", "obs-")) for i in ids), ids
    assert len(ids) == len(set(ids))


def test_messreihe_und_bericht(settings, scenario, tmp_path):
    runner, _, llm = _runner(settings, tmp_path)
    runs = runner.run_series(["A", "B"], [scenario], repeats=2)
    assert len(runs) == 4

    report = build_report(
        [m.to_dict() for m in runs],
        {"provider": "mock", "model": "mock", "fhir_base_url": "stub", "max_repair_rounds": 3},
    )
    assert "Vergleichsbericht" in report
    assert "Mock-Lauf" in report            # Warnhinweis muss drinstehen
    assert "Architekturentscheidung" in report
    assert "Häufigste Fehlerarten" in report
    assert "nicht für die klinische Nutzung" in report
    assert llm.estimated_cost_eur() is not None


def test_budgetgrenze_bricht_ab(settings, scenario, tmp_path):
    from synthfhir.llm import BudgetExceededError

    llm = MockClient(settings.llm, budget_limit_eur=0.0000001)
    runner = SpikeRunner(settings, llm, StubValidator(), tmp_path / "s", echo=lambda *_: None)
    runner.run_once("B", scenario, 1)  # erster Aufruf geht durch, Kosten entstehen
    with pytest.raises(BudgetExceededError):
        runner.run_once("B", scenario, 2)
