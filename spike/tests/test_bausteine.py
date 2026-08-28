"""Tests der deterministischen Bausteine.

Genau diese Teile dürfen nicht vom Modell abhängen. Wenn sie falsch
arbeiten, misst der Spike etwas anderes als er zu messen glaubt.
"""

from __future__ import annotations

import pytest

from synthfhir.codes import CONDITION_CODES, OBSERVATION_CODES
from synthfhir.identity import assign_ids, repin_identity
from synthfhir.integrity import check_resources
from synthfhir.jsonx import JsonExtractionError, as_resource_list, extract_json
from synthfhir.metrics import GREEN, RED, YELLOW, aggregate, decision, evaluate, overall_rating
from synthfhir.templates import build_bundle, build_from_parameters
from synthfhir.validator import parse_outcome


# --- JSON-Extraktion -------------------------------------------------------


def test_json_ohne_verpackung():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_json_in_markdown_rahmen():
    text = '```json\n[{"resourceType": "Patient"}]\n```'
    assert extract_json(text) == [{"resourceType": "Patient"}]


def test_json_mit_vor_und_nachtext():
    text = 'Gerne!\n[{"resourceType": "Patient"}]\nViel Erfolg.'
    assert extract_json(text) == [{"resourceType": "Patient"}]


def test_klammern_in_zeichenketten_verwirren_nicht():
    text = '{"note": "ein } mitten im String", "resourceType": "Patient"}'
    assert extract_json(text)["note"].endswith("String")


def test_unparsbare_antwort_wird_zum_fehler():
    with pytest.raises(JsonExtractionError):
        extract_json("Das kann ich leider nicht liefern.")


def test_bundle_wird_zur_ressourcenliste():
    payload = {
        "resourceType": "Bundle",
        "entry": [{"resource": {"resourceType": "Patient", "id": "x"}}],
    }
    assert len(as_resource_list(payload)) == 1


# --- ID- und Referenzvergabe ----------------------------------------------


def test_ids_werden_immer_neu_vergeben():
    result = assign_ids([{"resourceType": "Patient", "id": "vom-modell"}])
    assert result.resources[0]["id"] == "pat-001"


def test_referenzen_werden_konsistent_mitgezogen():
    result = assign_ids(
        [
            {"resourceType": "Patient", "id": "p1"},
            {"resourceType": "Condition", "id": "c1", "subject": {"reference": "Patient/p1"}},
        ]
    )
    assert result.resources[1]["subject"]["reference"] == "Patient/pat-001"
    assert result.rewritten_references == 1


def test_urn_uuid_referenz_wird_aufgeloest():
    result = assign_ids(
        [
            {"resourceType": "Patient", "id": "abc"},
            {"resourceType": "Observation", "id": "o", "subject": {"reference": "urn:uuid:abc"}},
        ]
    )
    assert result.resources[1]["subject"]["reference"] == "Patient/pat-001"


def test_referenz_ins_leere_wird_nicht_repariert():
    """Kernentscheidung: nur so bleibt die Metrik 'kaputte Referenzen' messbar."""
    result = assign_ids(
        [
            {"resourceType": "Patient", "id": "p1"},
            {"resourceType": "Observation", "id": "o", "subject": {"reference": "Patient/p9"}},
        ]
    )
    assert result.resources[1]["subject"]["reference"] == "Patient/p9"
    assert "Patient/p9" in result.unresolved_references


def test_doppelte_modell_ids_werden_erkannt():
    result = assign_ids(
        [
            {"resourceType": "Patient", "id": "p1"},
            {"resourceType": "Patient", "id": "p1"},
            {"resourceType": "Condition", "id": "c", "subject": {"reference": "Patient/p1"}},
        ]
    )
    assert result.duplicate_ids_from_llm == ["Patient/p1"]
    assert "Patient/p1" in result.ambiguous_references


def test_contained_referenzen_bleiben_unberuehrt():
    result = assign_ids(
        [{"resourceType": "Observation", "id": "o", "subject": {"reference": "#inline"}}]
    )
    assert result.resources[0]["subject"]["reference"] == "#inline"
    assert result.unresolved_references == []


def test_repin_setzt_identitaet_zurueck():
    resource = {"resourceType": "Patient", "id": "vom-modell-geaendert"}
    notes = repin_identity(resource, "obs-001", "Observation")
    assert resource["id"] == "obs-001"
    assert resource["resourceType"] == "Observation"
    assert len(notes) == 2


# --- Referenz-Integritätsprüfung ------------------------------------------


def test_integritaet_meldet_ziel_ausserhalb_des_bundles():
    report = check_resources(
        [
            {"resourceType": "Patient", "id": "pat-001"},
            {"resourceType": "Observation", "id": "obs-001", "subject": {"reference": "Patient/pat-9"}},
        ]
    )
    assert report.broken_reference_count == 1
    assert not report.ok


def test_integritaet_findet_referenzen_ausserhalb_von_subject():
    report = check_resources(
        [
            {"resourceType": "Patient", "id": "pat-001"},
            {
                "resourceType": "Observation",
                "id": "obs-001",
                "subject": {"reference": "Patient/pat-001"},
                "performer": [{"reference": "Practitioner/x"}],
            },
        ]
    )
    assert report.broken_reference_count == 1
    assert report.broken_references[0].path == "performer[0].reference"


def test_integritaet_meldet_doppelte_ids():
    report = check_resources(
        [
            {"resourceType": "Patient", "id": "pat-001"},
            {"resourceType": "Patient", "id": "pat-001"},
        ]
    )
    assert report.duplicate_ids == ["Patient/pat-001"]


def test_integritaet_meldet_fehlende_patientenverknuepfung():
    report = check_resources([{"resourceType": "Observation", "id": "obs-001"}])
    assert report.missing_patient_link


def test_integritaet_akzeptiert_sauberen_satz():
    report = check_resources(
        [
            {"resourceType": "Patient", "id": "pat-001"},
            {"resourceType": "Condition", "id": "cond-001", "subject": {"reference": "Patient/pat-001"}},
        ]
    )
    assert report.ok


# --- Vorlagen der Variante B ----------------------------------------------


def _parameter_beispiel() -> dict:
    return {
        "patients": [
            {
                "given_name": "Anna",
                "family_name": "Meier",
                "gender": "female",
                "birth_date": "1968-04-12",
                "conditions": [{"code": "44054006", "onset_date": "2015-06-01"}],
                "observations": [
                    {"code": "4548-4", "value": 7.9, "effective_date": "2024-03-11"}
                ],
            }
        ]
    }


def test_vorlage_setzt_pflichtfelder():
    result = build_from_parameters(
        _parameter_beispiel(),
        {"patients": 1, "conditions_per_patient": 1, "observations_per_patient": 1},
    )
    assert not result.issues
    kinds = {r["resourceType"]: r for r in result.resources}
    assert kinds["Observation"]["status"] == "final"          # 1..1
    assert kinds["Observation"]["code"]["coding"][0]["code"]  # 1..1
    assert kinds["Condition"]["subject"]["reference"]         # 1..1
    assert kinds["Condition"]["clinicalStatus"]["coding"][0]["code"] == "active"
    assert kinds["Patient"]["gender"] in ("male", "female", "other", "unknown")


def test_vorlage_setzt_ucum_getrennt_von_anzeigeeinheit():
    payload = _parameter_beispiel()
    payload["patients"][0]["observations"][0]["code"] = "8480-6"  # Blutdruck systolisch
    result = build_from_parameters(
        payload, {"patients": 1, "conditions_per_patient": 1, "observations_per_patient": 1}
    )
    quantity = [r for r in result.resources if r["resourceType"] == "Observation"][0][
        "valueQuantity"
    ]
    assert quantity["unit"] == "mmHg"
    assert quantity["code"] == "mm[Hg]"
    assert quantity["system"] == "http://unitsofmeasure.org"


def test_erfundener_code_wird_ersetzt_und_gezaehlt():
    payload = _parameter_beispiel()
    payload["patients"][0]["observations"][0]["code"] = "99999-9"
    result = build_from_parameters(
        payload, {"patients": 1, "conditions_per_patient": 1, "observations_per_patient": 1}
    )
    assert result.invented_codes == 1
    observation = [r for r in result.resources if r["resourceType"] == "Observation"][0]
    assert observation["code"]["coding"][0]["code"] in OBSERVATION_CODES


def test_kaputte_parameter_ergeben_trotzdem_strukturell_gueltige_ressourcen():
    """Der Kern der Variante B: strukturell kann nichts kaputtgehen."""
    payload = {
        "patients": [
            {
                "gender": "weiblich",
                "birth_date": "12.05.1980",
                "conditions": [{"code": "unbekannt"}],
                "observations": [{"code": "auch-unbekannt", "value": "hoch"}],
            }
        ]
    }
    result = build_from_parameters(
        payload, {"patients": 1, "conditions_per_patient": 1, "observations_per_patient": 1}
    )
    assert len(result.resources) == 3
    observation = [r for r in result.resources if r["resourceType"] == "Observation"][0]
    assert observation["status"] == "final"
    assert isinstance(observation["valueQuantity"]["value"], float)
    patient = [r for r in result.resources if r["resourceType"] == "Patient"][0]
    assert patient["gender"] == "unknown"
    assert patient["birthDate"] == "1970-01-01"


def test_katalog_ist_nicht_leer():
    assert len(OBSERVATION_CODES) >= 20
    assert len(CONDITION_CODES) >= 20


def test_bundle_hat_eindeutige_fullurls():
    result = build_from_parameters(
        _parameter_beispiel(),
        {"patients": 1, "conditions_per_patient": 1, "observations_per_patient": 1},
    )
    normalised = assign_ids(result.resources)
    bundle = build_bundle(normalised.resources, "http://synthfhir.local/fhir")
    urls = [entry["fullUrl"] for entry in bundle["entry"]]
    assert bundle["type"] == "collection"
    assert len(urls) == len(set(urls))
    assert all("request" not in entry for entry in bundle["entry"])


# --- OperationOutcome-Auswertung ------------------------------------------


def test_outcome_wird_nach_schweregrad_getrennt():
    issues = parse_outcome(
        {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "error",
                    "code": "structure",
                    "diagnostics": "Observation.status: minimum required = 1, but only found 0",
                    "expression": ["Observation.status"],
                },
                {"severity": "warning", "code": "code-invalid", "diagnostics": "Unknown code system"},
                {"severity": "information", "diagnostics": "No issues detected"},
            ],
        }
    )
    assert [i.severity for i in issues] == ["error", "warning", "information"]
    assert issues[0].blocking and not issues[1].blocking
    assert issues[0].category() == "pflichtfeld/kardinalität"
    assert issues[1].category() == "terminologie/code"


def test_fehlersignatur_fasst_gleichartige_fehler_zusammen():
    issues = parse_outcome(
        {
            "issue": [
                {"severity": "error", "diagnostics": "Unknown code 'abc'", "expression": ["Observation.code"]},
                {"severity": "error", "diagnostics": "Unknown code 'xyz'", "expression": ["Observation.code"]},
            ]
        }
    )
    assert issues[0].signature() == issues[1].signature()


def test_location_wird_als_rueckfallebene_gelesen():
    issues = parse_outcome({"issue": [{"severity": "error", "location": ["Patient.gender"]}]})
    assert issues[0].expression == "Patient.gender"


def _hapi_issue(diagnostics: str, message_id: str, severity: str = "error") -> dict:
    """Baut einen Befund in genau der Form, die HAPI tatsächlich liefert."""
    return {
        "severity": severity,
        "code": "processing",  # HAPI schickt hier fast immer nur "processing"
        "diagnostics": diagnostics,
        "expression": ["Observation"],  # oft nur der Ressourcentyp
        "details": {
            "coding": [
                {"system": "http://hl7.org/fhir/java-core-messageId", "code": message_id}
            ]
        },
    }


def test_hapi_fehlerkennung_wird_gelesen():
    issue = parse_outcome(
        {
            "issue": [
                _hapi_issue(
                    "Observation.status: minimum required = 1, but only found 0",
                    "Validation_VAL_Profile_Minimum",
                )
            ]
        }
    )[0]
    assert issue.message_id == "Validation_VAL_Profile_Minimum"
    assert issue.category() == "pflichtfeld/kardinalität"


def test_genauer_pfad_schlaegt_groben_expression_wert():
    """HAPI nennt in `expression` oft nur 'Observation'; der Klartext ist genauer."""
    issue = parse_outcome(
        {"issue": [_hapi_issue("Observation.status: minimum required = 1", "X")]}
    )[0]
    assert issue.expression == "Observation"
    assert issue.location() == "Observation.status"


def test_pflichtfeld_code_ist_kein_terminologiefehler():
    """Regression: 'Observation.code' enthält 'code', ist aber Kardinalität.

    Würde das als Terminologiefehler zählen, verfälschte es das
    Ampelkriterium 'erfundene/beanstandete Codes' aus Abschnitt 10.
    """
    with_id = parse_outcome(
        {
            "issue": [
                _hapi_issue(
                    "Observation.code: minimum required = 1, but only found 0",
                    "Validation_VAL_Profile_Minimum",
                )
            ]
        }
    )[0]
    without_id = parse_outcome(
        {
            "issue": [
                {
                    "severity": "error",
                    "diagnostics": "Observation.code: minimum required = 1, but only found 0",
                    "expression": ["Observation"],
                }
            ]
        }
    )[0]
    assert with_id.category() == "pflichtfeld/kardinalität"
    assert without_id.category() == "pflichtfeld/kardinalität"


def test_unbekanntes_codesystem_ist_terminologie_und_nur_warnung():
    """Der gemessene blinde Fleck: HAPI ohne LOINC meldet nur eine Warnung."""
    issue = parse_outcome(
        {
            "issue": [
                _hapi_issue(
                    "CodeSystem is unknown and can't be validated: http://loinc.org "
                    "for 'http://loinc.org#4548-4'",
                    "Terminology_PassThrough_TX_Message",
                    severity="warning",
                )
            ]
        }
    )[0]
    assert issue.category() == "terminologie/code"
    assert not issue.blocking


def test_invariante_wird_an_der_kennung_erkannt():
    issue = parse_outcome(
        {
            "issue": [
                _hapi_issue(
                    "Constraint failed: dom-6: 'A resource should have narrative'",
                    "http://hl7.org/fhir/StructureDefinition/DomainResource#dom-6",
                    severity="warning",
                )
            ]
        }
    )[0]
    assert issue.category() == "invariante"


# --- Bewertung und Entscheidungsregel -------------------------------------


def _lauf(variant: str, valide: int, gesamt: int, kaputte_referenzen: int = 0) -> dict:
    return {
        "variant": variant,
        "status": "ok",
        "scenario": {"key": "einfach", "fingerprint": "abc"},
        "duration_s": 1.0,
        "llm": {"calls": 1, "input_tokens": 100, "output_tokens": 200, "cost_eur": 0.001},
        "generation": {"json_failures": 0, "llm_failures": 0},
        "resources": {"total": gesamt, "by_type": {"Patient": 1, "Condition": 1, "Observation": gesamt - 2}},
        "validation": {
            "valid_first_attempt": valide,
            "valid_final": valide,
            "invalid_final": gesamt - valide,
            "warning_count": 0,
            "code_related_issues": 0,
            "code_related_warnings": 3,
            "error_signatures": {"[error] Observation: fehlt": gesamt - valide},
            "error_categories": {"pflichtfeld/kardinalität": gesamt - valide},
        },
        "repair": {"repaired_resources": 0, "rounds_total": 0, "non_improving_rounds": 0, "json_failures": 0},
        "integrity": {"broken_reference_count": kaputte_referenzen, "duplicate_ids": [], "missing_patient_link": []},
        "codes": {"invented": 0},
    }


def test_aggregation_summiert_ueber_laeufe():
    summary = aggregate([_lauf("B", 3, 3), _lauf("B", 3, 3)])
    assert summary["runs"] == 2
    assert summary["resources_total"] == 6
    assert summary["valid_final_rate"] == 1.0
    assert summary["cost_eur_per_patient"] == pytest.approx(0.001, abs=1e-6)


def test_ampel_gruen_bei_sauberem_ergebnis():
    summary = aggregate([_lauf("B", 3, 3) for _ in range(5)])
    assert overall_rating(evaluate(summary)) == GREEN


def test_ampel_rot_bei_niedriger_validitaetsquote():
    summary = aggregate([_lauf("A", 1, 3) for _ in range(5)])
    kriterien = {c.name: c.rating for c in evaluate(summary)}
    assert kriterien["Anteil valider Ressourcen (nach max. 3 Runden)"] == RED


def test_ampel_gelb_bei_wenigen_kaputten_referenzen():
    summary = aggregate([_lauf("A", 3, 3, kaputte_referenzen=1)])
    kriterien = {c.name: c.rating for c in evaluate(summary)}
    assert kriterien["Kaputte Referenzen"] == YELLOW


def test_entscheidungsregel_folgt_abschnitt_10():
    assert "Direktgenerierung" in decision(GREEN, GREEN)
    assert "Variante B" in decision(YELLOW, GREEN)
    assert "Projektannahmen" in decision(RED, RED)


def test_nicht_parsbare_ressource_ist_eigene_fehlerklasse():
    """Echter Befund aus dem Lauf mit einem lokalen 7B-Modell.

    Wenn HAPI die Ressource nicht einmal einlesen kann, hat gar keine
    inhaltliche Prüfung stattgefunden – qualitativ etwas anderes als ein
    fehlendes Pflichtfeld, deshalb eigene Klasse.
    """
    issue = parse_outcome(
        {
            "issue": [
                {
                    "severity": "error",
                    "code": "processing",
                    "diagnostics": (
                        "HAPI-0450: Failed to parse request body as JSON resource. "
                        "Error was: HAPI-1821: [element='status'] Invalid attribute "
                        "value 'Final': Case discrepancy detected"
                    ),
                }
            ]
        }
    )[0]
    assert issue.category() == "nicht als FHIR parsbar"


def _lauf_mit_sollmenge(variant: str, ist: int, soll: int) -> dict:
    run = _lauf(variant, ist, ist)
    run["resources"]["expected_total"] = soll
    run["resources"]["expected_by_type"] = {"Patient": 1, "Condition": 1, "Observation": soll - 2}
    return run


def test_mengentreue_wird_berechnet():
    summary = aggregate([_lauf_mit_sollmenge("A", 3, 4), _lauf_mit_sollmenge("A", 3, 4)])
    assert summary["expected_resources_total"] == 8
    assert summary["count_compliance"] == 0.75


def test_fehlende_mengentreue_wird_im_bericht_benannt():
    """Eine Variante kann 100 % valide sein und trotzdem unbrauchbar."""
    from synthfhir.report import build_report

    runs = [_lauf_mit_sollmenge("A", 3, 5) for _ in range(3)]
    runs += [_lauf_mit_sollmenge("B", 5, 5) for _ in range(3)]
    report = build_report(runs, {"provider": "x", "model": "y", "fhir_base_url": "z"})
    assert "Mengentreue" in report
    assert "Variante A hat die geforderte Menge nicht geliefert" in report
    assert "Variante B hat die geforderte Menge nicht geliefert" not in report


def test_vollstaendige_mengentreue_wird_ebenfalls_festgehalten():
    from synthfhir.report import build_report

    runs = [_lauf_mit_sollmenge(v, 5, 5) for v in ("A", "B") for _ in range(3)]
    report = build_report(runs, {"provider": "x", "model": "y", "fhir_base_url": "z"})
    assert "vollständig geliefert" in report
