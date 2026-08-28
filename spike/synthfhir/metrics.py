"""Metrikerfassung und Auswertung (Abschnitt 6.8 und 10).

Zwei Ebenen:

  RunMetrics    alles, was in einem einzelnen Durchlauf anfällt. Wird als
                JSON je Lauf geschrieben (Abschnitt 9).
  aggregate()   fasst beliebig viele Läufe einer Variante zusammen und
                wendet die Ampelbewertung aus Abschnitt 10 an.

`aggregate` arbeitet bewusst auf der JSON-Form und nicht auf den Objekten:
So lässt sich der Vergleichsbericht jederzeit aus den Dateien auf der Platte
neu erzeugen, ohne die Messung zu wiederholen.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# --- Schwellen der Ampelbewertung (Abschnitt 10) ---------------------------
# Die Spezifikation nennt für zwei Kriterien nur qualitative Bänder
# ("vereinzelt", "wenige Cent"). Sie werden hier operationalisiert, damit
# die Bewertung reproduzierbar ist. Die gewählten Grenzen stehen im Bericht.
CODE_ISSUE_RATE_YELLOW = 0.05   # bis 5 % der Ressourcen: "vereinzelt"
COST_PER_PATIENT_GREEN_EUR = 0.05
COST_PER_PATIENT_YELLOW_EUR = 0.25

GREEN, YELLOW, RED = "grün", "gelb", "rot"


@dataclass
class RunMetrics:
    """Alle Messwerte eines einzelnen Durchlaufs."""

    run_id: str
    variant: str
    scenario_key: str
    scenario_name: str
    scenario_fingerprint: str
    started_at: str
    provider: str
    model: str

    duration_s: float = 0.0
    status: str = "ok"  # ok | generation_failed | aborted
    notes: list[str] = field(default_factory=list)

    resources_by_type: dict[str, int] = field(default_factory=dict)
    # Sollmenge aus dem Szenario. Ohne sie ist die Ist-Zahl bedeutungslos:
    # "100 % valide" bei 73 % gelieferter Menge waere irrefuehrend.
    expected_by_type: dict[str, int] = field(default_factory=dict)
    valid_first_attempt: int = 0
    valid_final: int = 0
    invalid_final: int = 0

    repaired_resources: int = 0
    repair_rounds_total: int = 0
    non_improving_rounds: int = 0
    repair_json_failures: int = 0
    identity_corrections: list[str] = field(default_factory=list)

    error_signatures: Counter = field(default_factory=Counter)
    error_categories: Counter = field(default_factory=Counter)
    code_related_issues: int = 0
    code_related_warnings: int = 0
    warning_count: int = 0

    integrity: dict = field(default_factory=dict)
    generation: dict = field(default_factory=dict)
    invented_codes: int = 0

    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    cost_eur: float | None = None

    @property
    def resources_total(self) -> int:
        return sum(self.resources_by_type.values())

    def to_dict(self) -> dict:
        total = self.resources_total
        repaired = self.repaired_resources
        return {
            "run_id": self.run_id,
            "variant": self.variant,
            "status": self.status,
            "notes": self.notes,
            "scenario": {
                "key": self.scenario_key,
                "name": self.scenario_name,
                "fingerprint": self.scenario_fingerprint,
            },
            "started_at": self.started_at,
            "duration_s": round(self.duration_s, 3),
            "llm": {
                "provider": self.provider,
                "model": self.model,
                "calls": self.llm_calls,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cost_usd": None if self.cost_usd is None else round(self.cost_usd, 6),
                "cost_eur": None if self.cost_eur is None else round(self.cost_eur, 6),
            },
            "generation": self.generation,
            "resources": {
                "total": total,
                "by_type": dict(self.resources_by_type),
                "expected_total": sum(self.expected_by_type.values()),
                "expected_by_type": dict(self.expected_by_type),
            },
            "validation": {
                "valid_first_attempt": self.valid_first_attempt,
                "valid_final": self.valid_final,
                "invalid_final": self.invalid_final,
                "warning_count": self.warning_count,
                "code_related_issues": self.code_related_issues,
                "code_related_warnings": self.code_related_warnings,
                "error_signatures": dict(self.error_signatures),
                "error_categories": dict(self.error_categories),
            },
            "repair": {
                "repaired_resources": repaired,
                "rounds_total": self.repair_rounds_total,
                "rounds_avg_over_all": round(self.repair_rounds_total / total, 3) if total else 0.0,
                "rounds_avg_over_repaired": (
                    round(self.repair_rounds_total / repaired, 3) if repaired else 0.0
                ),
                "non_improving_rounds": self.non_improving_rounds,
                "json_failures": self.repair_json_failures,
                "identity_corrections": self.identity_corrections,
            },
            "integrity": self.integrity,
            "codes": {"invented": self.invented_codes},
        }


# ---------------------------------------------------------------------------
# Aggregation über viele Läufe
# ---------------------------------------------------------------------------


def _get(node: Any, *path: str, default: Any = 0) -> Any:
    for key in path:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
    return default if node is None else node


def aggregate(runs: list[dict]) -> dict:
    """Fasst die Läufe einer Variante zusammen."""
    if not runs:
        return {"variant": "?", "runs": 0}

    variant = runs[0].get("variant", "?")
    by_type: Counter = Counter()
    expected_by_type: Counter = Counter()
    signatures: Counter = Counter()
    categories: Counter = Counter()

    totals = {
        "resources": 0,
        "expected_resources": 0,
        "valid_first": 0,
        "valid_final": 0,
        "invalid_final": 0,
        "repair_rounds": 0,
        "repaired_resources": 0,
        "non_improving": 0,
        "broken_references": 0,
        "duplicate_ids": 0,
        "missing_patient_link": 0,
        "invented_codes": 0,
        "code_related_issues": 0,
        "code_related_warnings": 0,
        "warnings": 0,
        "llm_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "json_failures": 0,
        "truncations": 0,
        "llm_failures": 0,
        "patients": 0,
    }
    cost_eur = 0.0
    cost_known = False
    duration = 0.0
    runs_failed = 0
    scenario_keys: Counter = Counter()
    fingerprints: set[str] = set()

    for run in runs:
        scenario_keys[_get(run, "scenario", "key", default="?")] += 1
        fingerprints.add(str(_get(run, "scenario", "fingerprint", default="?")))
        if run.get("status") != "ok":
            runs_failed += 1

        duration += float(_get(run, "duration_s", default=0.0))
        for key, value in (_get(run, "resources", "by_type", default={}) or {}).items():
            by_type[key] += int(value)
        totals["resources"] += int(_get(run, "resources", "total", default=0))
        totals["expected_resources"] += int(
            _get(run, "resources", "expected_total", default=0)
        )
        for key, value in (_get(run, "resources", "expected_by_type", default={}) or {}).items():
            expected_by_type[key] += int(value)
        totals["patients"] += int((_get(run, "resources", "by_type", default={}) or {}).get("Patient", 0))

        totals["valid_first"] += int(_get(run, "validation", "valid_first_attempt", default=0))
        totals["valid_final"] += int(_get(run, "validation", "valid_final", default=0))
        totals["invalid_final"] += int(_get(run, "validation", "invalid_final", default=0))
        totals["warnings"] += int(_get(run, "validation", "warning_count", default=0))
        totals["code_related_issues"] += int(
            _get(run, "validation", "code_related_issues", default=0)
        )
        totals["code_related_warnings"] += int(
            _get(run, "validation", "code_related_warnings", default=0)
        )
        for signature, count in (_get(run, "validation", "error_signatures", default={}) or {}).items():
            signatures[signature] += int(count)
        for category, count in (_get(run, "validation", "error_categories", default={}) or {}).items():
            categories[category] += int(count)

        totals["repair_rounds"] += int(_get(run, "repair", "rounds_total", default=0))
        totals["repaired_resources"] += int(_get(run, "repair", "repaired_resources", default=0))
        totals["non_improving"] += int(_get(run, "repair", "non_improving_rounds", default=0))

        totals["broken_references"] += int(
            _get(run, "integrity", "broken_reference_count", default=0)
        )
        totals["duplicate_ids"] += len(_get(run, "integrity", "duplicate_ids", default=[]) or [])
        totals["missing_patient_link"] += len(
            _get(run, "integrity", "missing_patient_link", default=[]) or []
        )

        totals["invented_codes"] += int(_get(run, "codes", "invented", default=0))
        totals["llm_calls"] += int(_get(run, "llm", "calls", default=0))
        totals["input_tokens"] += int(_get(run, "llm", "input_tokens", default=0))
        totals["output_tokens"] += int(_get(run, "llm", "output_tokens", default=0))
        totals["json_failures"] += int(_get(run, "generation", "json_failures", default=0))
        totals["json_failures"] += int(_get(run, "repair", "json_failures", default=0))
        totals["truncations"] += int(_get(run, "generation", "truncations", default=0))
        totals["llm_failures"] += int(_get(run, "generation", "llm_failures", default=0))

        run_cost = _get(run, "llm", "cost_eur", default=None)
        if run_cost is not None:
            cost_eur += float(run_cost)
            cost_known = True

    resources = totals["resources"]
    patients = totals["patients"]

    return {
        "variant": variant,
        "runs": len(runs),
        "runs_failed": runs_failed,
        "scenarios": dict(scenario_keys),
        "scenario_fingerprints": sorted(fingerprints),
        "resources_total": resources,
        "resources_by_type": dict(by_type),
        "expected_resources_total": totals["expected_resources"],
        "expected_resources_by_type": dict(expected_by_type),
        "count_compliance": _rate(resources, totals["expected_resources"]),
        "valid_first_attempt": totals["valid_first"],
        "valid_final": totals["valid_final"],
        "invalid_final": totals["invalid_final"],
        "valid_first_rate": _rate(totals["valid_first"], resources),
        "valid_final_rate": _rate(totals["valid_final"], resources),
        "repaired_resources": totals["repaired_resources"],
        "repair_rounds_total": totals["repair_rounds"],
        "repair_rounds_avg_over_all": _ratio(totals["repair_rounds"], resources),
        "repair_rounds_avg_over_repaired": _ratio(
            totals["repair_rounds"], totals["repaired_resources"]
        ),
        "non_improving_rounds": totals["non_improving"],
        "broken_references": totals["broken_references"],
        "duplicate_ids": totals["duplicate_ids"],
        "missing_patient_link": totals["missing_patient_link"],
        "invented_codes": totals["invented_codes"],
        "code_related_issues": totals["code_related_issues"],
        "code_related_warnings": totals["code_related_warnings"],
        "warnings": totals["warnings"],
        "json_failures": totals["json_failures"],
        "truncations": totals["truncations"],
        "llm_failures": totals["llm_failures"],
        "llm_calls": totals["llm_calls"],
        "input_tokens": totals["input_tokens"],
        "output_tokens": totals["output_tokens"],
        "cost_eur": round(cost_eur, 4) if cost_known else None,
        "cost_eur_per_patient": (
            round(cost_eur / patients, 4) if cost_known and patients else None
        ),
        "duration_s_total": round(duration, 2),
        "duration_s_avg": _ratio(duration, len(runs)),
        "top_errors": signatures.most_common(15),
        "error_categories": dict(categories.most_common()),
    }


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _ratio(part: float, whole: float) -> float:
    return round(part / whole, 3) if whole else 0.0


# ---------------------------------------------------------------------------
# Ampelbewertung (Abschnitt 10)
# ---------------------------------------------------------------------------


@dataclass
class Criterion:
    """Ein bewertetes Kriterium der Entscheidungstabelle."""

    name: str
    value: str
    rating: str
    note: str = ""


def evaluate(summary: dict) -> list[Criterion]:
    """Wendet die Tabelle aus Abschnitt 10 auf eine Variantenzusammenfassung an."""
    criteria: list[Criterion] = []

    # 1. Anteil valider Ressourcen nach maximal drei Korrekturrunden
    rate = summary.get("valid_final_rate")
    if rate is None:
        criteria.append(Criterion("Anteil valider Ressourcen", "keine Daten", RED))
    else:
        percent = rate * 100
        rating = GREEN if percent >= 90 else (YELLOW if percent >= 60 else RED)
        criteria.append(
            Criterion(
                "Anteil valider Ressourcen (nach max. 3 Runden)",
                f"{percent:.1f} %",
                rating,
                f"{summary.get('valid_final')} von {summary.get('resources_total')}",
            )
        )

    # 2. Kaputte Referenzen
    broken = int(summary.get("broken_references") or 0)
    rating = GREEN if broken == 0 else (YELLOW if broken <= 2 else RED)
    criteria.append(
        Criterion(
            "Kaputte Referenzen",
            str(broken),
            rating,
            f"zusätzlich {summary.get('missing_patient_link')} fehlende Patientenverknüpfungen",
        )
    )

    # 3. Durchschnittliche Korrekturrunden
    avg = float(summary.get("repair_rounds_avg_over_all") or 0.0)
    rating = GREEN if avg <= 1 else (YELLOW if avg <= 2 else RED)
    criteria.append(
        Criterion(
            "Ø Korrekturrunden je Ressource",
            f"{avg:.2f}",
            rating,
            f"über die {summary.get('repaired_resources')} reparierten Ressourcen: "
            f"{summary.get('repair_rounds_avg_over_repaired')}",
        )
    )

    # 4. Erfundene bzw. beanstandete Codes
    resources = int(summary.get("resources_total") or 0)
    code_issues = int(summary.get("invented_codes") or 0) + int(
        summary.get("code_related_issues") or 0
    )
    if code_issues == 0:
        rating = GREEN
    elif resources and code_issues / resources <= CODE_ISSUE_RATE_YELLOW:
        rating = YELLOW
    else:
        rating = RED
    share = f" ({code_issues / resources * 100:.1f} % der Ressourcen)" if resources else ""
    criteria.append(
        Criterion(
            "Erfundene / beanstandete Codes",
            f"{code_issues}{share}",
            rating,
            f"davon {summary.get('invented_codes')} außerhalb des Katalogs (nur Variante B), "
            f"{summary.get('code_related_issues')} vom Validator beanstandet",
        )
    )

    # 5. Kosten pro Patient
    cost = summary.get("cost_eur_per_patient")
    if cost is None:
        criteria.append(
            Criterion("Kosten pro Patient", "unbekannt", YELLOW, "keine Preisdaten hinterlegt")
        )
    else:
        rating = (
            GREEN
            if cost < COST_PER_PATIENT_GREEN_EUR
            else (YELLOW if cost < COST_PER_PATIENT_YELLOW_EUR else RED)
        )
        criteria.append(
            Criterion(
                "Kosten pro Patient",
                f"{cost:.4f} EUR",
                rating,
                f"Gesamtkosten der Messreihe: {summary.get('cost_eur')} EUR",
            )
        )

    return criteria


def overall_rating(criteria: list[Criterion]) -> str:
    """Gesamtampel: das schlechteste Einzelkriterium entscheidet."""
    ratings = {c.rating for c in criteria}
    if RED in ratings:
        return RED
    if YELLOW in ratings:
        return YELLOW
    return GREEN


def decision(rating_a: str, rating_b: str) -> str:
    """Entscheidungsregel aus Abschnitt 10 als Klartext."""
    if rating_a == GREEN:
        return (
            "Variante A ist grün: Die LLM-Direktgenerierung wird die Architektur. "
            "Die Korrekturschleife bleibt Bestandteil des Produkts."
        )
    if rating_a in (YELLOW, RED) and rating_b == GREEN:
        return (
            "Variante A ist nicht grün, Variante B ist grün: Variante B "
            "(Parameter + Vorlagen) wird die Architektur. Das ist ausdrücklich ein "
            "Erfolg des Spikes und kein Scheitern – es ist die zentrale Erkenntnis."
        )
    if rating_a == RED and rating_b == RED:
        return (
            "Beide Varianten sind rot. Die Projektannahmen sind zu überdenken. "
            "Da Variante B strukturell kaum scheitern kann, deutet das eher auf ein "
            "Problem im Messaufbau als auf ein Problem der Architektur hin – "
            "zuerst Validatorkonfiguration und Katalog prüfen."
        )
    return (
        f"Variante A: {rating_a}, Variante B: {rating_b}. Keine der Regeln aus "
        "Abschnitt 10 greift eindeutig. Entscheidung anhand der Einzelkriterien "
        "und der häufigsten Fehlerarten treffen."
    )
