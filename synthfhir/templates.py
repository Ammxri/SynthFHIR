"""FHIR-Vorlagen der Variante B (Abschnitt 6.3) – Lernmodus-Komponente.

===========================================================================
KONZEPT: Welche Pflichtfelder und Datentypen brauchen die drei Ressourcen?
===========================================================================

Die Vorlagen sind der ganze Trick der Variante B. Sie müssen die Struktur
von sich aus richtig setzen, damit strukturell nichts vom Modell abhängt.
Dafür muss man wissen, was FHIR R4 wirklich verlangt. "Wirklich verlangt"
heißt: was der Validator als *error* meldet, nicht was schön wäre.

Es gibt drei Klassen von Anforderungen:

1. KARDINALITÄT (1..1 = Pflicht). Fehlt so ein Feld, ist es ein Fehler.
2. DATENTYP. Ein `date` muss YYYY[-MM[-DD]] sein, ein `dateTime` zusätzlich
   mit Zeitzone, wenn eine Uhrzeit dransteht. "12.05.1980" ist kein `date`.
3. REQUIRED BINDING. Manche `code`-Felder dürfen nur Werte aus einer festen
   Liste tragen. Ein Tippfehler dort ist ein Fehler, keine Warnung.
   Zusätzlich gibt es INVARIANTEN (con-3, con-5, obs-6 …) – Regeln, die
   Beziehungen zwischen Feldern erzwingen.

--- Patient ---------------------------------------------------------------
Überraschung: Patient hat in R4 KEIN einziges Pflichtfeld außer
`resourceType`. `{"resourceType": "Patient"}` ist valide. Die Fehlerquellen
liegen deshalb ausschließlich bei Datentyp und Binding:

  gender     code, REQUIRED binding auf male | female | other | unknown.
             "Male", "m" oder "männlich" sind Fehler, keine Warnungen.
  birthDate  Datentyp `date`. Deutsche Schreibweise ist ein Fehler.
  name       0..* HumanName – ein OBJEKT im Array, nicht ein String.
             "name": "Anna Meier" ist ein Datentypfehler.
             `family` ist ein String, `given` ein Array von Strings.
  identifier 0..* Identifier mit `system` (uri) und `value` (string).

--- Condition -------------------------------------------------------------
  subject             1..1 Reference – PFLICHT. Fehlt sie, ist die Ressource
                      invalide. Das ist der einzige harte Kardinalitätsfehler
                      dieser Ressource.
  clinicalStatus      CodeableConcept, REQUIRED binding auf
                      condition-clinical (active, recurrence, relapse,
                      inactive, remission, resolved).
  verificationStatus  CodeableConcept, REQUIRED binding auf
                      condition-ver-status (unconfirmed, provisional,
                      differential, confirmed, refuted, entered-in-error).
  Die Invarianten con-3/con-5 koppeln beide: clinicalStatus muss da sein,
  wenn verificationStatus nicht "entered-in-error" ist – und darf dann
  nicht da sein, wenn er es doch ist. Die Vorlage setzt fest
  active + confirmed; damit sind beide Invarianten immer erfüllt.
  code                0..1 CodeableConcept, nur EXAMPLE binding. Ein
                      erfundener Code ist hier also strukturell erlaubt –
                      genau deshalb braucht Variante B den eigenen Katalog
                      und nicht bloß den Validator.
  onsetDateTime       Teil der Auswahl `onset[x]`. Es darf immer nur EINE
                      Ausprägung einer Auswahl gesetzt sein.

--- Observation -----------------------------------------------------------
Die fehleranfälligste der drei, weil sie zwei Pflichtfelder UND einen
zusammengesetzten Datentyp hat.

  status         1..1 code, REQUIRED binding (registered, preliminary,
                 final, amended, corrected, cancelled, entered-in-error,
                 unknown). Vergessenes `status` ist der Klassiker.
  code           1..1 CodeableConcept – PFLICHT.
  subject        0..1, formal optional. Semantisch unverzichtbar: eine
                 Messung ohne Patient ist wertlos. Der Strukturvalidator
                 beanstandet das NICHT – ein Grund mehr für die eigene
                 Referenz-Integritätsprüfung (siehe integrity.py).
  valueQuantity  Teil der Auswahl `value[x]`. Quantity braucht für eine
                 maschinell auswertbare Messung vier Teile:
                   value  – decimal, also eine JSON-Zahl, kein String
                   unit   – menschenlesbare Einheit
                   system – "http://unitsofmeasure.org"
                   code   – der UCUM-Code, z. B. "mg/dL", "mm[Hg]", "/min"
                 `unit` und `code` sind NICHT dasselbe: "mmHg" ist die
                 Anzeige, "mm[Hg]" der UCUM-Code. Genau hier vertun sich
                 Modelle regelmäßig.
  effectiveDateTime  Auswahl `effective[x]`, Datentyp dateTime.

Die Vorlage setzt all das aus dem Katalog (codes.py) – das Modell liefert
in Variante B nur Code, Zahl und Datum.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .codes import (
    CONDITION_CODES,
    OBSERVATION_CODES,
    SNOMED_SYSTEM,
    UCUM_SYSTEM,
    ConditionCode,
    ObservationCode,
    fallback_condition,
    fallback_observation,
)

CONDITION_CLINICAL_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-clinical"
CONDITION_VER_STATUS_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-ver-status"
OBSERVATION_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/observation-category"
PATIENT_IDENTIFIER_SYSTEM = "http://synthfhir.local/identifier/patient"

ALLOWED_GENDERS = ("male", "female", "other", "unknown")

# LOINC-Codes aus dem Katalog, die Vitalparameter sind und deshalb eine
# andere Observation.category tragen als Laborwerte.
VITAL_SIGN_CODES = frozenset({"8867-4", "8480-6", "8462-4", "29463-7", "8302-2"})

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class TemplateIssue:
    """Eine Beanstandung an den vom Modell gelieferten Parametern."""

    kind: str
    detail: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "detail": self.detail}


@dataclass
class TemplateResult:
    """Ergebnis des Zusammenbaus aus Parametern."""

    resources: list[dict] = field(default_factory=list)
    issues: list[TemplateIssue] = field(default_factory=list)

    @property
    def invented_codes(self) -> int:
        return sum(
            1
            for issue in self.issues
            if issue.kind in ("invented_condition_code", "invented_observation_code")
        )


# --- Hilfsfunktionen für die Prüfung der Parameter -------------------------


def _valid_date(value: object, fallback: str, issues: list[TemplateIssue], what: str) -> str:
    if isinstance(value, str) and _DATE_RE.match(value.strip()):
        return value.strip()
    issues.append(
        TemplateIssue("invalid_date", f"{what}: {value!r} ist kein Datum YYYY-MM-DD -> {fallback}")
    )
    return fallback


def _valid_gender(value: object, issues: list[TemplateIssue]) -> str:
    if isinstance(value, str) and value.strip().lower() in ALLOWED_GENDERS:
        return value.strip().lower()
    issues.append(
        TemplateIssue("invalid_gender", f"Geschlecht {value!r} nicht zulässig -> unknown")
    )
    return "unknown"


def _valid_text(value: object, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _resolve_condition_code(
    value: object, index: int, issues: list[TemplateIssue]
) -> ConditionCode:
    code = str(value).strip() if value is not None else ""
    if code in CONDITION_CODES:
        return CONDITION_CODES[code]
    replacement = fallback_condition(index)
    issues.append(
        TemplateIssue(
            "invented_condition_code",
            f"Diagnosecode {code!r} nicht im Katalog -> ersetzt durch {replacement.code}",
        )
    )
    return replacement


def _resolve_observation_code(
    value: object, index: int, issues: list[TemplateIssue]
) -> ObservationCode:
    code = str(value).strip() if value is not None else ""
    if code in OBSERVATION_CODES:
        return OBSERVATION_CODES[code]
    replacement = fallback_observation(index)
    issues.append(
        TemplateIssue(
            "invented_observation_code",
            f"Messwertcode {code!r} nicht im Katalog -> ersetzt durch {replacement.code}",
        )
    )
    return replacement


def _valid_value(value: object, spec: ObservationCode, issues: list[TemplateIssue]) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        midpoint = round((spec.low + spec.high) / 2, 2)
        issues.append(
            TemplateIssue(
                "invalid_value",
                f"Messwert {value!r} für {spec.code} ist keine Zahl -> {midpoint}",
            )
        )
        return midpoint
    return round(float(value), 2)


# --- Vorlagen --------------------------------------------------------------


def build_patient(params: dict, index: int, issues: list[TemplateIssue]) -> dict:
    """Baut eine Patient-Ressource aus flachen Parametern."""
    return {
        "resourceType": "Patient",
        "id": f"tmp-pat-{index}",
        "identifier": [
            {
                "system": PATIENT_IDENTIFIER_SYSTEM,
                "value": f"SYN-{index + 1:04d}",
            }
        ],
        "name": [
            {
                "use": "official",
                "family": _valid_text(params.get("family_name"), f"Testperson{index + 1}"),
                "given": [_valid_text(params.get("given_name"), "Anonym")],
            }
        ],
        "gender": _valid_gender(params.get("gender"), issues),
        "birthDate": _valid_date(params.get("birth_date"), "1970-01-01", issues, "birth_date"),
    }


def build_condition(
    params: dict, patient_index: int, index: int, issues: list[TemplateIssue]
) -> dict:
    """Baut eine Condition-Ressource aus flachen Parametern."""
    spec = _resolve_condition_code(params.get("code"), index, issues)
    return {
        "resourceType": "Condition",
        "id": f"tmp-cond-{index}",
        # con-3 / con-5: beide Statusfelder fest gesetzt, damit die
        # Invarianten unabhängig vom Modell immer erfüllt sind.
        "clinicalStatus": {
            "coding": [
                {"system": CONDITION_CLINICAL_SYSTEM, "code": "active", "display": "Active"}
            ]
        },
        "verificationStatus": {
            "coding": [
                {
                    "system": CONDITION_VER_STATUS_SYSTEM,
                    "code": "confirmed",
                    "display": "Confirmed",
                }
            ]
        },
        "code": {
            "coding": [{"system": SNOMED_SYSTEM, "code": spec.code, "display": spec.display}],
            "text": spec.display,
        },
        # Pflichtfeld 1..1 – wird von identity.assign_ids auf die endgültige
        # Patienten-ID umgeschrieben.
        "subject": {"reference": f"Patient/tmp-pat-{patient_index}"},
        "onsetDateTime": _valid_date(
            params.get("onset_date"), "2020-01-01", issues, "onset_date"
        ),
    }


def build_observation(
    params: dict, patient_index: int, index: int, issues: list[TemplateIssue]
) -> dict:
    """Baut eine Observation-Ressource aus flachen Parametern."""
    spec = _resolve_observation_code(params.get("code"), index, issues)
    value = _valid_value(params.get("value"), spec, issues)
    category = "vital-signs" if spec.code in VITAL_SIGN_CODES else "laboratory"
    return {
        "resourceType": "Observation",
        "id": f"tmp-obs-{index}",
        "status": "final",  # Pflichtfeld 1..1 mit required binding
        "category": [
            {
                "coding": [
                    {
                        "system": OBSERVATION_CATEGORY_SYSTEM,
                        "code": category,
                        "display": category.replace("-", " ").title(),
                    }
                ]
            }
        ],
        "code": {  # Pflichtfeld 1..1
            "coding": [{"system": spec.system, "code": spec.code, "display": spec.display}],
            "text": spec.display,
        },
        "subject": {"reference": f"Patient/tmp-pat-{patient_index}"},
        "effectiveDateTime": _valid_date(
            params.get("effective_date"), "2024-01-01", issues, "effective_date"
        ),
        "valueQuantity": {
            "value": value,
            "unit": spec.unit,  # menschenlesbar
            "system": UCUM_SYSTEM,
            "code": spec.unit_code,  # UCUM – nicht identisch mit `unit`
        },
    }


def build_from_parameters(payload: dict, expected: dict[str, int]) -> TemplateResult:
    """Setzt aus dem Parameterobjekt des Modells den kompletten Satz zusammen.

    `expected` enthält die Sollzahlen aus dem Szenario; Abweichungen werden
    protokolliert, aber NICHT aufgefüllt – die Metrik soll zeigen, ob das
    Modell die geforderten Mengen einhält.
    """
    result = TemplateResult()
    issues = result.issues

    patients = payload.get("patients")
    if not isinstance(patients, list) or not patients:
        issues.append(
            TemplateIssue("missing_field", "Parameterobjekt enthält keine Liste 'patients'.")
        )
        return result

    if len(patients) != expected.get("patients", len(patients)):
        issues.append(
            TemplateIssue(
                "count_mismatch",
                f"{len(patients)} Patienten geliefert, {expected.get('patients')} erwartet",
            )
        )

    condition_index = 0
    observation_index = 0

    for patient_index, raw_patient in enumerate(patients):
        if not isinstance(raw_patient, dict):
            issues.append(
                TemplateIssue(
                    "missing_field", f"Patienteneintrag {patient_index} ist kein Objekt."
                )
            )
            continue

        result.resources.append(build_patient(raw_patient, patient_index, issues))

        raw_conditions = raw_patient.get("conditions")
        conditions = raw_conditions if isinstance(raw_conditions, list) else []
        if len(conditions) != expected.get("conditions_per_patient", len(conditions)):
            issues.append(
                TemplateIssue(
                    "count_mismatch",
                    f"Patient {patient_index}: {len(conditions)} Diagnosen geliefert, "
                    f"{expected.get('conditions_per_patient')} erwartet",
                )
            )
        for raw_condition in conditions:
            entry = raw_condition if isinstance(raw_condition, dict) else {}
            result.resources.append(
                build_condition(entry, patient_index, condition_index, issues)
            )
            condition_index += 1

        raw_observations = raw_patient.get("observations")
        observations = raw_observations if isinstance(raw_observations, list) else []
        if len(observations) != expected.get("observations_per_patient", len(observations)):
            issues.append(
                TemplateIssue(
                    "count_mismatch",
                    f"Patient {patient_index}: {len(observations)} Messwerte geliefert, "
                    f"{expected.get('observations_per_patient')} erwartet",
                )
            )
        for raw_observation in observations:
            entry = raw_observation if isinstance(raw_observation, dict) else {}
            result.resources.append(
                build_observation(entry, patient_index, observation_index, issues)
            )
            observation_index += 1

    return result


def build_bundle(resources: list[dict], base_url: str) -> dict:
    """Fasst alle Ressourcen eines Durchlaufs zusammen (Abschnitt 5.4).

    Bundle-Typ `collection`: eine reine Sammlung ohne Transaktionssemantik.
    Deshalb dürfen `entry.request` und `entry.response` nicht gesetzt sein
    (Invariante bdl-3). `fullUrl` muss innerhalb des Bundles eindeutig sein
    (bdl-7); da der Code die IDs vergibt, ist das garantiert.
    """
    base = base_url.rstrip("/")
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "fullUrl": f"{base}/{resource.get('resourceType')}/{resource.get('id')}",
                "resource": resource,
            }
            for resource in resources
        ],
    }
