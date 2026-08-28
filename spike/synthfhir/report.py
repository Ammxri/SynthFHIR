"""Vergleichsbericht Variante A gegen Variante B (Abschnitt 9, 10 und 14).

Erzeugt Markdown. Der Bericht enthält alles, was Abschnitt 14 für den
Abschluss des Spikes verlangt: die Metriken aus 6.8, die Ampelbewertung aus
10, die daraus folgende Architekturentscheidung und die Liste der häufigsten
Fehlerarten.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .metrics import Criterion, aggregate, decision, evaluate, overall_rating

DISCLAIMER = (
    "> **Hinweis:** Alle in diesem Spike erzeugten Daten sind rein synthetisch "
    "und ausdrücklich **nicht für die klinische Nutzung** bestimmt. Es wurden zu "
    "keinem Zeitpunkt echte Patientendaten verarbeitet."
)


def _fmt(value: object, suffix: str = "") -> str:
    if value is None:
        return "–"
    if isinstance(value, float):
        return f"{value:.4f}{suffix}".rstrip("0").rstrip(".") + ("" if suffix else "")
    return f"{value}{suffix}"


def _percent(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.1f} %"


def _criteria_table(criteria: list[Criterion]) -> str:
    lines = ["| Kriterium | Wert | Ampel | Anmerkung |", "|---|---|---|---|"]
    for c in criteria:
        lines.append(f"| {c.name} | {c.value} | **{c.rating}** | {c.note} |")
    return "\n".join(lines)


def _comparison_table(a: dict, b: dict) -> str:
    rows: list[tuple[str, object, object]] = [
        ("Durchläufe", a.get("runs"), b.get("runs")),
        ("davon abgebrochen/fehlgeschlagen", a.get("runs_failed"), b.get("runs_failed")),
        ("Ressourcen gesamt", a.get("resources_total"), b.get("resources_total")),
        (
            "Sollmenge laut Szenario",
            a.get("expected_resources_total"),
            b.get("expected_resources_total"),
        ),
        (
            "**Mengentreue** (geliefert / gefordert)",
            _percent(a.get("count_compliance")),
            _percent(b.get("count_compliance")),
        ),
        (
            "davon Patient / Condition / Observation",
            _by_type(a.get("resources_by_type") or {}),
            _by_type(b.get("resources_by_type") or {}),
        ),
        (
            "Soll Patient / Condition / Observation",
            _by_type(a.get("expected_resources_by_type") or {}),
            _by_type(b.get("expected_resources_by_type") or {}),
        ),
        (
            "valide beim ERSTEN Versuch",
            f"{a.get('valid_first_attempt')} ({_percent(a.get('valid_first_rate'))})",
            f"{b.get('valid_first_attempt')} ({_percent(b.get('valid_first_rate'))})",
        ),
        (
            "valide NACH Korrekturschleife",
            f"{a.get('valid_final')} ({_percent(a.get('valid_final_rate'))})",
            f"{b.get('valid_final')} ({_percent(b.get('valid_final_rate'))})",
        ),
        ("endgültig invalide", a.get("invalid_final"), b.get("invalid_final")),
        ("reparierte Ressourcen", a.get("repaired_resources"), b.get("repaired_resources")),
        (
            "Ø Korrekturrunden je Ressource",
            a.get("repair_rounds_avg_over_all"),
            b.get("repair_rounds_avg_over_all"),
        ),
        (
            "Ø Korrekturrunden je reparierter Ressource",
            a.get("repair_rounds_avg_over_repaired"),
            b.get("repair_rounds_avg_over_repaired"),
        ),
        (
            "Runden ohne Verbesserung (Stagnation)",
            a.get("non_improving_rounds"),
            b.get("non_improving_rounds"),
        ),
        ("kaputte Referenzen", a.get("broken_references"), b.get("broken_references")),
        ("fehlende Patientenverknüpfungen", a.get("missing_patient_link"), b.get("missing_patient_link")),
        ("doppelte IDs im Bundle", a.get("duplicate_ids"), b.get("duplicate_ids")),
        ("erfundene Codes (außerhalb Katalog)", a.get("invented_codes"), b.get("invented_codes")),
        (
            "vom Validator beanstandete Codes (Fehler)",
            a.get("code_related_issues"),
            b.get("code_related_issues"),
        ),
        (
            "Terminologie-Warnungen (nicht wertend)",
            a.get("code_related_warnings"),
            b.get("code_related_warnings"),
        ),
        ("Antworten ohne gültiges JSON", a.get("json_failures"), b.get("json_failures")),
        (
            "davon durch max_tokens abgeschnitten (Konfigurationsartefakt)",
            a.get("truncations"),
            b.get("truncations"),
        ),
        ("fehlgeschlagene LLM-Aufrufe", a.get("llm_failures"), b.get("llm_failures")),
        ("LLM-Aufrufe gesamt", a.get("llm_calls"), b.get("llm_calls")),
        ("Eingabe-Token", a.get("input_tokens"), b.get("input_tokens")),
        ("Ausgabe-Token", a.get("output_tokens"), b.get("output_tokens")),
        ("geschätzte Kosten (EUR)", a.get("cost_eur"), b.get("cost_eur")),
        ("geschätzte Kosten je Patient (EUR)", a.get("cost_eur_per_patient"), b.get("cost_eur_per_patient")),
        ("Laufzeit gesamt (s)", a.get("duration_s_total"), b.get("duration_s_total")),
        ("Laufzeit je Durchlauf (s)", a.get("duration_s_avg"), b.get("duration_s_avg")),
    ]
    lines = ["| Metrik | Variante A | Variante B |", "|---|---|---|"]
    for name, left, right in rows:
        lines.append(f"| {name} | {_fmt(left)} | {_fmt(right)} |")
    return "\n".join(lines)


def _by_type(by_type: dict) -> str:
    return (
        f"{by_type.get('Patient', 0)} / "
        f"{by_type.get('Condition', 0)} / "
        f"{by_type.get('Observation', 0)}"
    )


def _error_table(summary: dict, title: str) -> str:
    top = summary.get("top_errors") or []
    if not top:
        return f"**{title}:** keine blockierenden Fehler im ersten Validierungsdurchgang.\n"
    lines = [f"**{title}**\n", "| Anzahl | Fehlerart (normalisiert) |", "|---:|---|"]
    for signature, count in top:
        lines.append(f"| {count} | `{signature}` |")
    categories = summary.get("error_categories") or {}
    if categories:
        joined = ", ".join(f"{name}: {count}" for name, count in categories.items())
        lines.append(f"\nNach Fehlerklasse: {joined}\n")
    return "\n".join(lines)


def _count_compliance_note(a: dict, b: dict) -> str:
    """Weist auf fehlende Mengentreue hin.

    Abschnitt 10 kennt dieses Kriterium nicht, deshalb bekommt es keine
    eigene Ampel – die Entscheidungsregel bleibt unverändert. Es gehört aber
    zwingend in den Bericht: Eine Variante, die 100 % valide, aber nur 73 %
    der geforderten Ressourcen liefert, ist als Testdatengenerator unbrauchbar.
    Die Zahl allein ("150 Ressourcen") sagt das nicht.
    """
    lines: list[str] = []
    for name, summary in (("A", a), ("B", b)):
        rate = summary.get("count_compliance")
        if rate is None or rate >= 0.99:
            continue
        lines.append(
            f"- **Variante {name} hat die geforderte Menge nicht geliefert:** "
            f"{summary.get('resources_total')} von "
            f"{summary.get('expected_resources_total')} Ressourcen "
            f"({rate * 100:.1f} %). Die Szenarien geben die Stückzahlen exakt vor "
            "(Abschnitt 6.1); wer sie unterschreitet, erzeugt zwar valide, aber "
            "unvollständige Testdaten."
        )
    if not lines:
        return (
            "\n**Mengentreue:** Beide Varianten haben die in den Szenarien "
            "geforderten Stückzahlen vollständig geliefert.\n"
        )
    return (
        "\n### Ergänzender Befund: Mengentreue\n\n"
        + "\n".join(lines)
        + "\n\nDieses Kriterium steht nicht in der Tabelle aus Abschnitt 10 und "
        "bekommt deshalb keine eigene Ampel. Für die Produktentscheidung ist es "
        "trotzdem erheblich – ein Generator, der die bestellte Menge nicht "
        "liefert, ist unabhängig von seiner Validitätsquote unbrauchbar.\n"
    )


def build_report(runs: list[dict], settings_summary: dict) -> str:
    """Baut den vollständigen Vergleichsbericht als Markdown."""
    runs_a = [r for r in runs if r.get("variant") == "A"]
    runs_b = [r for r in runs if r.get("variant") == "B"]
    summary_a = aggregate(runs_a)
    summary_b = aggregate(runs_b)
    criteria_a = evaluate(summary_a)
    criteria_b = evaluate(summary_b)
    rating_a = overall_rating(criteria_a)
    rating_b = overall_rating(criteria_b)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    provider = settings_summary.get("provider")
    model = settings_summary.get("model")

    parts: list[str] = []
    parts.append("# SynthFHIR – Vergleichsbericht Phase-0-Spike\n")
    parts.append(DISCLAIMER + "\n")
    parts.append(
        f"Erstellt: {now}  \n"
        f"Anbieter/Modell: `{provider}` / `{model}`  \n"
        f"Validierungsserver: `{settings_summary.get('fhir_base_url')}` "
        f"(FHIR-Version laut Server: {settings_summary.get('fhir_version', 'unbekannt')})  \n"
        f"Maximale Korrekturrunden: {settings_summary.get('max_repair_rounds')}\n"
    )

    if provider == "mock":
        parts.append(
            "> ⚠️ **Dieser Bericht stammt aus einem Mock-Lauf.** Der Anbieter `mock` "
            "erzeugt fest verdrahtete Antworten und dient nur dem Selbsttest der "
            "Kette. Er ist **keine Grundlage für die Architekturentscheidung**.\n"
        )
    elif str(provider) in ("openai_compatible", "ollama", "local"):
        parts.append(
            "> ℹ️ **Gemessen mit einem frei verfügbaren Modell** "
            f"(`{model}` über `{settings_summary.get('llm_base_url')}`).\n"
            ">\n"
            "> Was das für die Aussagekraft bedeutet, hängt an der Richtung des "
            "Ergebnisses und ist für die beiden Varianten unterschiedlich:\n"
            ">\n"
            "> - **Variante A:** Ein schlechtes Ergebnis ist immer nur eine "
            "**untere Schranke** – es zeigt, dass A mit *diesem* Modell nicht "
            "trägt. Wie belastbar das ist, hängt davon ab, wie stark das Modell "
            "ist. Bei einem kleinen Modell (7B-Klasse) sagt ein Durchfall wenig "
            "über starke Modelle aus; bei einem großen offenen Modell ist der "
            "Abstand zur Spitzenklasse gering und der Befund entsprechend "
            "aussagekräftiger.\n"
            "> - **Variante B:** Ein gutes Ergebnis ist unabhängig vom Modell "
            "belastbar. Die Struktur kommt aus dem Code, nicht aus dem Modell – "
            "was hier ein schwächeres Modell schafft, schafft ein stärkeres erst "
            "recht.\n"
            ">\n"
            "> Genau diese Modellabhängigkeit nennt Abschnitt 3 als eigenständiges "
            "Messergebnis: Wenn Variante A nur mit einem Spitzenmodell "
            "funktioniert, ist das ein Kostenrisiko und ein Argument für "
            "Variante B.\n"
        )

    # Prüfung der Vergleichbarkeit
    fingerprints = set(summary_a.get("scenario_fingerprints") or []) | set(
        summary_b.get("scenario_fingerprints") or []
    )
    parts.append("## 1. Messgrundlage\n")
    parts.append(
        f"- Durchläufe Variante A: **{summary_a.get('runs', 0)}**, "
        f"Variante B: **{summary_b.get('runs', 0)}** "
        f"(Abschnitt 10 verlangt mindestens 20 je Variante)\n"
        f"- Szenarien A: {summary_a.get('scenarios')}\n"
        f"- Szenarien B: {summary_b.get('scenarios')}\n"
        f"- Szenario-Fingerabdrücke: {sorted(fingerprints)}\n"
    )
    if summary_a.get("runs", 0) < 20 or summary_b.get("runs", 0) < 20:
        parts.append(
            "> ⚠️ Weniger als 20 Durchläufe je Variante. Die Messreihe erfüllt die "
            "Mindestanforderung aus Abschnitt 10 noch nicht; die Zahlen sind "
            "vorläufig.\n"
        )

    parts.append("\n## 2. Metrikvergleich\n")
    parts.append(_comparison_table(summary_a, summary_b) + "\n")

    parts.append("\n## 3. Bewertung nach Abschnitt 10\n")
    parts.append(f"### Variante A – Gesamtampel: **{rating_a}**\n")
    parts.append(_criteria_table(criteria_a) + "\n")
    parts.append(f"\n### Variante B – Gesamtampel: **{rating_b}**\n")
    parts.append(_criteria_table(criteria_b) + "\n")
    parts.append(
        "\nOperationalisierte Schwellen für die beiden qualitativ formulierten "
        "Kriterien: „vereinzelt“ = bis 5 % der Ressourcen mit Codebeanstandung; "
        "„wenige Cent“ = unter 0,05 EUR je Patient, „budgetsprengend“ = ab "
        "0,25 EUR je Patient.\n"
    )

    parts.append("\n## 4. Architekturentscheidung\n")
    parts.append(decision(rating_a, rating_b) + "\n")
    parts.append(_count_compliance_note(summary_a, summary_b))

    parts.append("\n## 5. Häufigste Fehlerarten (Grundlage für die Produktentwicklung)\n")
    parts.append(
        "Gezählt wird der **erste** Validierungsdurchgang – er zeigt, was die "
        "jeweilige Architektur produziert, bevor irgendetwas repariert wurde.\n"
    )
    parts.append(_error_table(summary_a, "Variante A") + "\n")
    parts.append(_error_table(summary_b, "Variante B") + "\n")

    parts.append("\n## 6. Einschränkungen dieser Messung\n")
    parts.append(
        "- **Terminologie.** Der HAPI-Container hat keine LOINC-/SNOMED-Pakete "
        "geladen und meldet jede kodierte Ressource mit "
        "`Terminology_PassThrough_TX_Message` als **Warnung**, nicht als Fehler "
        "(„CodeSystem is unknown and can't be validated“). Ein erfundener Code "
        "fällt in Variante A damit gar nicht auf. Das Kriterium „erfundene / "
        "beanstandete Codes“ ist für Variante A deshalb nur so aussagekräftig "
        "wie die Zeile „Terminologie-Warnungen“ klein ist; Variante B misst es "
        "über den eigenen Katalog unabhängig vom Server. Direkter Beleg für den "
        "offenen Punkt aus Abschnitt 13 (eigene Terminologie-Validierung).\n"
        "- **Referenzen.** Der Code vergibt IDs neu und zieht bestehende Verweise "
        "über eine Abbildungstabelle mit, erfindet aber kein Ziel für einen "
        "Verweis ins Leere. Nur deshalb ist die Metrik „kaputte Referenzen“ "
        "überhaupt aussagekräftig.\n"
        "- **Asymmetrie der Prompts.** Nur Variante B bekommt den Code-Katalog. "
        "Das ist kein Messfehler, sondern der Unterschied, den der Spike misst.\n"
        "- **Kosten** sind eine Schätzung aus Token-Zahlen und einer hinterlegten "
        "Preistabelle, keine Abrechnung.\n"
    )

    parts.append("\n## 7. Offene Punkte (Abschnitt 13)\n")
    parts.append(
        "- Endgültige Modell- und Anbieterwahl für das Produkt\n"
        "- Braucht es eine eigene Terminologie-Validierung? Siehe Abschnitt 6 "
        "dieses Berichts.\n"
        "- Umfang der deutschen Lokalisierung (ICD-10-GM, deutsche Demografie)\n"
        "- Unterstützung von Profilen (KBV/ISiK, US Core)\n"
    )

    return "\n".join(parts)
