"""Fest hinterlegter Katalog gültiger Codes (Abschnitt 6.3).

Variante B darf ausschließlich aus dieser Liste wählen. Liefert das Modell
einen Code außerhalb des Katalogs, wird das protokolliert und der Wert
ersetzt – das ist eine der Kernmetriken des Spikes ("erfundene Codes").

Warum SNOMED CT und LOINC und nicht ICD-10-GM? Der Spike arbeitet auf
Basis-FHIR ohne deutsche Lokalisierung (Abschnitt 2). Condition.code ist in
Basis-FHIR bevorzugt an SNOMED CT gebunden, Observation.code an LOINC.
Die deutsche Lokalisierung ist bewusst erst nach dem Spike dran.
"""

from __future__ import annotations

from dataclasses import dataclass

LOINC_SYSTEM = "http://loinc.org"
SNOMED_SYSTEM = "http://snomed.info/sct"
UCUM_SYSTEM = "http://unitsofmeasure.org"


@dataclass(frozen=True)
class ObservationCode:
    """Ein zulässiger Laborwert- bzw. Vitalparameter-Code."""

    code: str
    display: str
    unit: str        # menschenlesbare Einheit (Quantity.unit)
    unit_code: str   # UCUM-Code (Quantity.code)
    low: float       # plausibler Wertebereich – nur Rückfallebene
    high: float

    @property
    def system(self) -> str:
        return LOINC_SYSTEM


@dataclass(frozen=True)
class ConditionCode:
    """Ein zulässiger Diagnose-Code."""

    code: str
    display: str

    @property
    def system(self) -> str:
        return SNOMED_SYSTEM


OBSERVATION_CODES: dict[str, ObservationCode] = {
    o.code: o
    for o in [
        ObservationCode("718-7", "Hemoglobin [Mass/volume] in Blood", "g/dL", "g/dL", 8.0, 17.5),
        ObservationCode("789-8", "Erythrocytes [#/volume] in Blood", "10*6/uL", "10*6/uL", 3.5, 6.0),
        ObservationCode("6690-2", "Leukocytes [#/volume] in Blood", "10*3/uL", "10*3/uL", 3.0, 15.0),
        ObservationCode("777-3", "Platelets [#/volume] in Blood", "10*3/uL", "10*3/uL", 120.0, 420.0),
        ObservationCode("2345-7", "Glucose [Mass/volume] in Serum or Plasma", "mg/dL", "mg/dL", 60.0, 300.0),
        ObservationCode("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood", "%", "%", 4.5, 14.0),
        ObservationCode("2160-0", "Creatinine [Mass/volume] in Serum or Plasma", "mg/dL", "mg/dL", 0.5, 4.0),
        ObservationCode("3094-0", "Urea nitrogen [Mass/volume] in Serum or Plasma", "mg/dL", "mg/dL", 6.0, 60.0),
        ObservationCode("33914-3", "Glomerular filtration rate/1.73 sq M.predicted", "mL/min/{1.73_m2}", "mL/min/{1.73_m2}", 10.0, 120.0),
        ObservationCode("2951-2", "Sodium [Moles/volume] in Serum or Plasma", "mmol/L", "mmol/L", 128.0, 148.0),
        ObservationCode("2823-3", "Potassium [Moles/volume] in Serum or Plasma", "mmol/L", "mmol/L", 3.0, 6.0),
        ObservationCode("2075-0", "Chloride [Moles/volume] in Serum or Plasma", "mmol/L", "mmol/L", 95.0, 112.0),
        ObservationCode("2093-3", "Cholesterol [Mass/volume] in Serum or Plasma", "mg/dL", "mg/dL", 110.0, 320.0),
        ObservationCode("2085-9", "Cholesterol in HDL [Mass/volume] in Serum or Plasma", "mg/dL", "mg/dL", 25.0, 95.0),
        ObservationCode("2571-8", "Triglyceride [Mass/volume] in Serum or Plasma", "mg/dL", "mg/dL", 50.0, 500.0),
        ObservationCode("1742-6", "Alanine aminotransferase [Enzymatic activity/volume] in Serum or Plasma", "U/L", "U/L", 5.0, 150.0),
        ObservationCode("1920-8", "Aspartate aminotransferase [Enzymatic activity/volume] in Serum or Plasma", "U/L", "U/L", 5.0, 150.0),
        ObservationCode("1975-2", "Bilirubin.total [Mass/volume] in Serum or Plasma", "mg/dL", "mg/dL", 0.2, 4.0),
        ObservationCode("1988-5", "C reactive protein [Mass/volume] in Serum or Plasma", "mg/L", "mg/L", 0.1, 120.0),
        ObservationCode("3016-3", "Thyrotropin [Units/volume] in Serum or Plasma", "mIU/L", "m[IU]/L", 0.2, 12.0),
        ObservationCode("8867-4", "Heart rate", "beats/minute", "/min", 45.0, 130.0),
        ObservationCode("8480-6", "Systolic blood pressure", "mmHg", "mm[Hg]", 90.0, 190.0),
        ObservationCode("8462-4", "Diastolic blood pressure", "mmHg", "mm[Hg]", 50.0, 110.0),
        ObservationCode("29463-7", "Body weight", "kg", "kg", 40.0, 140.0),
        ObservationCode("8302-2", "Body height", "cm", "cm", 145.0, 200.0),
    ]
}

CONDITION_CODES: dict[str, ConditionCode] = {
    c.code: c
    for c in [
        ConditionCode("44054006", "Diabetes mellitus type 2"),
        ConditionCode("46635009", "Diabetes mellitus type 1"),
        ConditionCode("38341003", "Hypertensive disorder, systemic arterial"),
        ConditionCode("13644009", "Hypercholesterolemia"),
        ConditionCode("414916001", "Obesity"),
        ConditionCode("195967001", "Asthma"),
        ConditionCode("13645005", "Chronic obstructive lung disease"),
        ConditionCode("84114007", "Heart failure"),
        ConditionCode("49436004", "Atrial fibrillation"),
        ConditionCode("22298006", "Myocardial infarction"),
        ConditionCode("53741008", "Coronary arteriosclerosis"),
        ConditionCode("230690007", "Cerebrovascular accident"),
        ConditionCode("709044004", "Chronic kidney disease"),
        ConditionCode("40930008", "Hypothyroidism"),
        ConditionCode("34486009", "Hyperthyroidism"),
        ConditionCode("396275006", "Osteoarthritis"),
        ConditionCode("69896004", "Rheumatoid arthritis"),
        ConditionCode("64859006", "Osteoporosis"),
        ConditionCode("35489007", "Depressive disorder"),
        ConditionCode("197480006", "Anxiety disorder"),
        ConditionCode("24700007", "Multiple sclerosis"),
        ConditionCode("66071002", "Viral hepatitis type B"),
        ConditionCode("235595009", "Gastroesophageal reflux disease"),
        ConditionCode("363346000", "Malignant neoplastic disease"),
        ConditionCode("73430006", "Sleep apnea"),
    ]
}


def observation_catalog_text() -> str:
    """Kompakte Katalogdarstellung für den Prompt der Variante B."""
    return "\n".join(
        f"  {o.code} | {o.display} | unit={o.unit} | ucum={o.unit_code} "
        f"| plausible range {o.low}-{o.high}"
        for o in OBSERVATION_CODES.values()
    )


def condition_catalog_text() -> str:
    """Kompakte Katalogdarstellung für den Prompt der Variante B."""
    return "\n".join(f"  {c.code} | {c.display}" for c in CONDITION_CODES.values())


def fallback_observation(index: int) -> ObservationCode:
    """Ersatzwert, wenn das Modell einen unbekannten Laborwert-Code liefert."""
    codes = list(OBSERVATION_CODES.values())
    return codes[index % len(codes)]


def fallback_condition(index: int) -> ConditionCode:
    """Ersatzwert, wenn das Modell einen unbekannten Diagnose-Code liefert."""
    codes = list(CONDITION_CODES.values())
    return codes[index % len(codes)]
