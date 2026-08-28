"""Prompts beider Varianten.

Bewusste Entscheidungen für die Vergleichbarkeit der Messung:

1. Beide Varianten bekommen dieselbe Szenariobeschreibung wörtlich.
2. Beide Varianten fordern reinen Text ohne erzwungenes JSON-Schema
   (kein `output_config.format`). Ein serverseitig erzwungenes JSON-Format
   würde die Fehlerkategorie "Antwort ist kein gültiges JSON" künstlich auf
   null setzen – laut Abschnitt 8 ist genau das aber eine Kernmetrik.
3. Nur Variante B bekommt den Code-Katalog. Das ist keine Benachteiligung
   von A, sondern der Unterschied, den der Spike misst: A soll Codes selbst
   erzeugen, B darf nur aus einer festen Liste wählen (Abschnitt 6.3).
"""

from __future__ import annotations

from .codes import condition_catalog_text, observation_catalog_text
from .scenarios import Scenario

# --- Variante A ------------------------------------------------------------

SYSTEM_VARIANT_A = """You generate SYNTHETIC test data as FHIR R4 resources.
The data is fictional and must never describe a real person.

Hard output rules:
- Reply with ONE JSON array and nothing else.
- No prose, no explanation, no markdown code fences.
- The array contains only resources with resourceType Patient, Condition or Observation.
- Every resource carries an "id" that you assign yourself.
- Every Condition and Observation links to its patient via
  "subject": {"reference": "Patient/<id of that patient>"}.
- Reference only patient ids that exist in the same array.
"""

USER_VARIANT_A = """SCENARIO (German, verbatim):
{description}

COUNTS: patients={patients}, conditions_per_patient={conditions}, observations_per_patient={observations}

Produce exactly {patients} Patient, {total_conditions} Condition and
{total_observations} Observation resources, in this order.
The clinical content must be internally consistent and plausible.

OUTPUT FORMAT: FHIR
Return the JSON array now."""

# --- Variante A: Korrekturschleife -----------------------------------------

SYSTEM_REPAIR = """You fix invalid FHIR R4 resources.

Hard output rules:
- Reply with ONE JSON object: the corrected resource.
- No prose, no explanation, no markdown code fences.
- Keep resourceType and id exactly as given.
- Keep all clinical content that is not part of the reported problem.
- Change only what is needed to remove the reported validation errors.
"""

USER_REPAIR = """This FHIR R4 resource failed validation.

VALIDATION ERRORS reported by the FHIR server:
{errors}

CURRENT RESOURCE:
{resource}

OUTPUT FORMAT: FHIR
Return the corrected resource as a single JSON object now."""

# --- Variante B ------------------------------------------------------------

SYSTEM_VARIANT_B = """You plan SYNTHETIC clinical test data.
The data is fictional and must never describe a real person.

You do NOT produce FHIR. You produce a plain parameter object that a
downstream program turns into FHIR.

Hard output rules:
- Reply with ONE JSON object and nothing else.
- No prose, no explanation, no markdown code fences.
- Use only codes from the catalogues given to you. Never invent a code.
- Every numeric value must be a JSON number, every date a "YYYY-MM-DD" string.
"""

USER_VARIANT_B = """SCENARIO (German, verbatim):
{description}

COUNTS: patients={patients}, conditions_per_patient={conditions}, observations_per_patient={observations}

REQUIRED JSON SHAPE (exactly these keys, no extras):
{{
  "patients": [
    {{
      "given_name": "string",
      "family_name": "string",
      "gender": "male" | "female" | "other" | "unknown",
      "birth_date": "YYYY-MM-DD",
      "conditions": [
        {{ "code": "<code from the diagnosis catalogue>", "onset_date": "YYYY-MM-DD" }}
      ],
      "observations": [
        {{ "code": "<code from the measurement catalogue>",
           "value": <number>,
           "effective_date": "YYYY-MM-DD" }}
      ]
    }}
  ]
}}

Produce exactly {patients} entries in "patients", each with exactly
{conditions} entries in "conditions" and {observations} entries in "observations".

DIAGNOSIS CATALOGUE (SNOMED CT) - choose only from this list:
{condition_catalog}

MEASUREMENT CATALOGUE (LOINC) - choose only from this list:
{observation_catalog}

Do not send units or display names: the downstream program takes them from
the catalogue. Send only the code, the numeric value and the date.
Values must sit inside the plausible range shown for the chosen code and
must fit the patient's age and diagnoses.

OUTPUT FORMAT: PARAMETERS
Return the JSON object now."""


def build_variant_a_prompt(scenario: Scenario) -> tuple[str, str]:
    """(System-Prompt, User-Prompt) für Variante A."""
    return SYSTEM_VARIANT_A, USER_VARIANT_A.format(
        description=scenario.description,
        patients=scenario.patients,
        conditions=scenario.conditions_per_patient,
        observations=scenario.observations_per_patient,
        total_conditions=scenario.expected_conditions,
        total_observations=scenario.expected_observations,
    )


def build_variant_b_prompt(scenario: Scenario) -> tuple[str, str]:
    """(System-Prompt, User-Prompt) für Variante B."""
    return SYSTEM_VARIANT_B, USER_VARIANT_B.format(
        description=scenario.description,
        patients=scenario.patients,
        conditions=scenario.conditions_per_patient,
        observations=scenario.observations_per_patient,
        condition_catalog=condition_catalog_text(),
        observation_catalog=observation_catalog_text(),
    )


def build_repair_prompt(resource_json: str, errors: str) -> tuple[str, str]:
    """(System-Prompt, User-Prompt) für eine Korrekturrunde."""
    return SYSTEM_REPAIR, USER_REPAIR.format(errors=errors, resource=resource_json)
