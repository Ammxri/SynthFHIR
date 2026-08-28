"""Der Codekatalog — die sicherheitskritische Komponente des Produkts.

===========================================================================
WARUM DIESE DATEI BESONDERS SORGFÄLTIG ZU BEHANDELN IST
===========================================================================

Die Architektur (ADR-001) nimmt dem Sprachmodell die Codes ab: Es darf nur
aus diesem Katalog wählen, alles andere wird verworfen. Damit ist die
Zusage „keine erfundenen Codes" genau so gut wie dieser Katalog.

Die Laufzeitvalidierung (ADR-002) prüft Codes **nicht**. Sie prüft Struktur.
Ein falscher Code hier erzeugt also ab sofort fehlerhafte Ausgaben, ohne
dass irgendetwas anschlägt. Deshalb gilt die Auflage aus ADR-002:

    Jeder Eintrag muss durch den CI-Test gedeckt sein, der aus ihm eine
    Ressource baut und gegen HAPI validiert.

===========================================================================
WAS DIESER TEST LEISTET — UND WAS NICHT
===========================================================================

Der HAPI-Test prüft **UCUM-Einheiten** zuverlässig: Er hat im Spike genau
diese Fehlerklasse gefunden (`IU/mL`, `cells/µL`, `mL/min/1.73m2` waren
allesamt ungültig). Er prüft ebenso Struktur und Invarianten.

Er prüft **LOINC-, SNOMED- und ICD-10-GM-Codes nicht**. Dem HAPI-Container
fehlen die Terminologiepakete; unbekannte CodeSystems ergeben höchstens eine
Warnung. Ein falsch abgetippter ICD-Schlüssel sieht für ihn genauso aus wie
ein richtiger.

Daraus folgt für die Pflege dieses Katalogs:

  * Einheiten sind maschinell abgesichert.
  * Codes sind es nicht. Sie brauchen einen menschlichen Abgleich gegen die
    Primärquelle — LOINC bei Regenstrief, SNOMED CT bei SNOMED
    International, ICD-10-GM beim BfArM.

===========================================================================
STAND DER ICD-10-GM-EINTRÄGE
===========================================================================

Alle 25 Schlüssel wurden am **2026-08-28 gegen den amtlichen Katalog des
BfArM geprüft** (ICD-10-GM Version 2026, klassifikationen.bfarm.de, ergänzt
über icd-code.de). Ergebnis:

  * 19 Schlüssel waren korrekt.
  * **2 waren nicht kodierbar** und wurden korrigiert: `J45.9` -> `J45.99`
    und `B18.1` -> `B18.19`. Beide sind in ICD-10-GM nur Kategorie-
    überschriften; ohne fünfte Stelle sind sie kein gültiger Schlüssel.
  * 4 Einträge hatten bis dahin gar keinen Schlüssel, weil die geforderte
    fünfte Stelle unklar war. Alle vier haben eine "nicht näher
    bezeichnet"-Variante und sind jetzt gefüllt: E66.99, M19.99, M06.99,
    M81.99.

Die Abdeckung liegt damit bei 25 von 25.

Die eigentliche Lehre steckt in den beiden Fehlern: ICD-10-GM verlangt an
vielen Stellen eine fünfte Stelle, wo ICD-10-WHO mit vier Zeichen auskommt.
Der Formattest in `tests/test_domaene.py` hätte sie nicht gefunden — `J45.9`
ist formal einwandfrei und trotzdem nicht kodierbar. HAPI findet sie
ebenfalls nicht, weil ihm das CodeSystem fehlt. Beide Fehler waren nur durch
den Abgleich mit der Primärquelle zu finden.

Das Feld bleibt trotzdem `optional`: Kommt eine Diagnose hinzu, deren
Schlüssel nicht zweifelsfrei bestimmbar ist, trägt sie lieber keine zweite
Kodierung als eine geratene (ADR-003, US-4 AC2: „wo anwendbar").
"""

from __future__ import annotations

from dataclasses import dataclass

LOINC_SYSTEM = "http://loinc.org"
SNOMED_SYSTEM = "http://snomed.info/sct"
UCUM_SYSTEM = "http://unitsofmeasure.org"
# Kanonischer URL des deutschen ICD-10-GM-CodeSystems, wie ihn die
# deutschen FHIR-Basisprofile (fhir.de) festlegen.
ICD10GM_SYSTEM = "http://fhir.de/CodeSystem/bfarm/icd-10-gm"


@dataclass(frozen=True)
class ObservationCode:
    """Ein zulässiger Laborwert oder Vitalparameter.

    `unit` ist die menschenlesbare Anzeige, `unit_code` der UCUM-Code. Die
    beiden sind nicht dasselbe: „mmHg" gegen „mm[Hg]". Genau hier hat das
    Sprachmodell im Spike die meisten Einheitenfehler produziert, weshalb
    beide Werte aus dem Katalog kommen und nicht aus dem Modell.
    """

    code: str
    display: str          # englischer LOINC-Anzeigetext
    display_de: str       # deutscher Anzeigetext für die Vorschau
    unit: str
    unit_code: str        # UCUM — maschinell durch den HAPI-Test gedeckt
    low: float
    high: float
    vital_sign: bool = False

    @property
    def system(self) -> str:
        return LOINC_SYSTEM


@dataclass(frozen=True)
class ConditionCode:
    """Eine zulässige Diagnose.

    Trägt bis zu zwei Kodierungen desselben Konzepts (ADR-003): SNOMED CT
    für internationale Anschlussfähigkeit, ICD-10-GM für den deutschen
    Kontext. `icd10gm = None` bedeutet: kein geprüfter Schlüssel vorhanden,
    die Ressource trägt dann nur SNOMED.
    """

    code: str             # SNOMED CT
    display: str          # englischer SNOMED-Anzeigetext
    display_de: str       # deutscher Anzeigetext — auch für CodeableConcept.text
    icd10gm: str | None = None
    icd10gm_display: str | None = None

    @property
    def system(self) -> str:
        return SNOMED_SYSTEM

    @property
    def hat_icd(self) -> bool:
        return self.icd10gm is not None


# ---------------------------------------------------------------------------
# Laborwerte und Vitalparameter (LOINC)
#
# Unverändert aus der Phase 0 übernommen: Alle 25 Einträge haben dort über
# 189 Ressourcen hinweg HAPI-valide Ausgaben erzeugt. Neu sind nur die
# deutschen Anzeigetexte.
# ---------------------------------------------------------------------------

OBSERVATION_CODES: dict[str, ObservationCode] = {
    o.code: o
    for o in [
        ObservationCode("718-7", "Hemoglobin [Mass/volume] in Blood", "Hämoglobin", "g/dL", "g/dL", 8.0, 17.5),
        ObservationCode("789-8", "Erythrocytes [#/volume] in Blood", "Erythrozyten", "10*6/uL", "10*6/uL", 3.5, 6.0),
        ObservationCode("6690-2", "Leukocytes [#/volume] in Blood", "Leukozyten", "10*3/uL", "10*3/uL", 3.0, 15.0),
        ObservationCode("777-3", "Platelets [#/volume] in Blood", "Thrombozyten", "10*3/uL", "10*3/uL", 120.0, 420.0),
        ObservationCode("2345-7", "Glucose [Mass/volume] in Serum or Plasma", "Glukose im Serum", "mg/dL", "mg/dL", 60.0, 300.0),
        ObservationCode("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood", "HbA1c", "%", "%", 4.5, 14.0),
        ObservationCode("2160-0", "Creatinine [Mass/volume] in Serum or Plasma", "Kreatinin im Serum", "mg/dL", "mg/dL", 0.5, 4.0),
        ObservationCode("3094-0", "Urea nitrogen [Mass/volume] in Serum or Plasma", "Harnstoff-Stickstoff", "mg/dL", "mg/dL", 6.0, 60.0),
        ObservationCode("33914-3", "Glomerular filtration rate/1.73 sq M.predicted", "geschätzte GFR", "mL/min/{1.73_m2}", "mL/min/{1.73_m2}", 10.0, 120.0),
        ObservationCode("2951-2", "Sodium [Moles/volume] in Serum or Plasma", "Natrium", "mmol/L", "mmol/L", 128.0, 148.0),
        ObservationCode("2823-3", "Potassium [Moles/volume] in Serum or Plasma", "Kalium", "mmol/L", "mmol/L", 3.0, 6.0),
        ObservationCode("2075-0", "Chloride [Moles/volume] in Serum or Plasma", "Chlorid", "mmol/L", "mmol/L", 95.0, 112.0),
        ObservationCode("2093-3", "Cholesterol [Mass/volume] in Serum or Plasma", "Gesamtcholesterin", "mg/dL", "mg/dL", 110.0, 320.0),
        ObservationCode("2085-9", "Cholesterol in HDL [Mass/volume] in Serum or Plasma", "HDL-Cholesterin", "mg/dL", "mg/dL", 25.0, 95.0),
        ObservationCode("2571-8", "Triglyceride [Mass/volume] in Serum or Plasma", "Triglyzeride", "mg/dL", "mg/dL", 50.0, 500.0),
        ObservationCode("1742-6", "Alanine aminotransferase [Enzymatic activity/volume] in Serum or Plasma", "ALAT (GPT)", "U/L", "U/L", 5.0, 150.0),
        ObservationCode("1920-8", "Aspartate aminotransferase [Enzymatic activity/volume] in Serum or Plasma", "ASAT (GOT)", "U/L", "U/L", 5.0, 150.0),
        ObservationCode("1975-2", "Bilirubin.total [Mass/volume] in Serum or Plasma", "Bilirubin gesamt", "mg/dL", "mg/dL", 0.2, 4.0),
        ObservationCode("1988-5", "C reactive protein [Mass/volume] in Serum or Plasma", "C-reaktives Protein", "mg/L", "mg/L", 0.1, 120.0),
        ObservationCode("3016-3", "Thyrotropin [Units/volume] in Serum or Plasma", "TSH", "mIU/L", "m[IU]/L", 0.2, 12.0),
        ObservationCode("8867-4", "Heart rate", "Herzfrequenz", "beats/minute", "/min", 45.0, 130.0, vital_sign=True),
        ObservationCode("8480-6", "Systolic blood pressure", "Blutdruck systolisch", "mmHg", "mm[Hg]", 90.0, 190.0, vital_sign=True),
        ObservationCode("8462-4", "Diastolic blood pressure", "Blutdruck diastolisch", "mmHg", "mm[Hg]", 50.0, 110.0, vital_sign=True),
        ObservationCode("29463-7", "Body weight", "Körpergewicht", "kg", "kg", 40.0, 140.0, vital_sign=True),
        ObservationCode("8302-2", "Body height", "Körpergröße", "cm", "cm", 145.0, 200.0, vital_sign=True),
    ]
}


# ---------------------------------------------------------------------------
# Diagnosen (SNOMED CT + ICD-10-GM)
#
# Die ICD-10-GM-Schlüssel sind am 2026-08-28 gegen den amtlichen
# BfArM-Katalog (Version 2026) geprüft; Einzelheiten im Modulkopf und in
# docs/icd-pruefliste.md. Wer hier eine Diagnose ergänzt, prüft den
# Schlüssel bitte ebenso an der Primärquelle: Weder der Formattest noch
# HAPI können ihn verifizieren.
# ---------------------------------------------------------------------------

CONDITION_CODES: dict[str, ConditionCode] = {
    c.code: c
    for c in [
        ConditionCode("44054006", "Diabetes mellitus type 2", "Diabetes mellitus Typ 2",
                      "E11.90", "Diabetes mellitus, Typ 2, ohne Komplikationen, nicht als entgleist bezeichnet"),
        ConditionCode("46635009", "Diabetes mellitus type 1", "Diabetes mellitus Typ 1",
                      "E10.90", "Diabetes mellitus, Typ 1, ohne Komplikationen, nicht als entgleist bezeichnet"),
        ConditionCode("38341003", "Hypertensive disorder, systemic arterial", "Arterielle Hypertonie",
                      "I10.90", "Essentielle Hypertonie, nicht näher bezeichnet, ohne Angabe einer hypertensiven Krise"),
        ConditionCode("13644009", "Hypercholesterolemia", "Hypercholesterinämie",
                      "E78.0", "Reine Hypercholesterinämie"),
        ConditionCode("414916001", "Obesity", "Adipositas",
                      "E66.99", "Adipositas, nicht näher bezeichnet: Grad oder Ausmaß "
                                "der Adipositas nicht näher bezeichnet"),
        ConditionCode("195967001", "Asthma", "Asthma bronchiale",
                      "J45.99", "Asthma bronchiale, nicht näher bezeichnet: "
                                "Ohne Angabe zu Kontrollstatus und Schweregrad"),
        ConditionCode("13645005", "Chronic obstructive lung disease", "COPD",
                      "J44.99", "Chronische obstruktive Lungenkrankheit, nicht näher "
                                "bezeichnet: FEV1 nicht näher bezeichnet"),
        ConditionCode("84114007", "Heart failure", "Herzinsuffizienz",
                      "I50.9", "Herzinsuffizienz, nicht näher bezeichnet"),
        ConditionCode("49436004", "Atrial fibrillation", "Vorhofflimmern",
                      "I48.9", "Vorhofflimmern und Vorhofflattern, nicht näher bezeichnet"),
        ConditionCode("22298006", "Myocardial infarction", "Myokardinfarkt",
                      "I21.9", "Akuter Myokardinfarkt, nicht näher bezeichnet"),
        ConditionCode("53741008", "Coronary arteriosclerosis", "Koronare Herzkrankheit",
                      "I25.9", "Chronische ischämische Herzkrankheit, nicht näher bezeichnet"),
        ConditionCode("230690007", "Cerebrovascular accident", "Schlaganfall",
                      "I64", "Schlaganfall, nicht als Blutung oder Infarkt bezeichnet"),
        ConditionCode("709044004", "Chronic kidney disease", "Chronische Nierenkrankheit",
                      "N18.9", "Chronische Nierenkrankheit, nicht näher bezeichnet"),
        ConditionCode("40930008", "Hypothyroidism", "Hypothyreose",
                      "E03.9", "Hypothyreose, nicht näher bezeichnet"),
        ConditionCode("34486009", "Hyperthyroidism", "Hyperthyreose",
                      "E05.9", "Hyperthyreose, nicht näher bezeichnet"),
        ConditionCode("396275006", "Osteoarthritis", "Arthrose",
                      "M19.99", "Arthrose, nicht näher bezeichnet: Nicht näher "
                                "bezeichnete Lokalisation"),
        ConditionCode("69896004", "Rheumatoid arthritis", "Rheumatoide Arthritis",
                      "M06.99", "Chronische Polyarthritis, nicht näher bezeichnet: "
                                "Nicht näher bezeichnete Lokalisation"),
        ConditionCode("64859006", "Osteoporosis", "Osteoporose",
                      "M81.99", "Osteoporose, nicht näher bezeichnet: Nicht näher "
                                "bezeichnete Lokalisation"),
        ConditionCode("35489007", "Depressive disorder", "Depressive Episode",
                      "F32.9", "Depressive Episode, nicht näher bezeichnet"),
        ConditionCode("197480006", "Anxiety disorder", "Angststörung",
                      "F41.9", "Angststörung, nicht näher bezeichnet"),
        ConditionCode("24700007", "Multiple sclerosis", "Multiple Sklerose",
                      "G35.9", "Multiple Sklerose, nicht näher bezeichnet"),
        ConditionCode("66071002", "Viral hepatitis type B", "Chronische Hepatitis B",
                      "B18.19", "Chronische Virushepatitis B ohne Delta-Virus, "
                                "Phase nicht näher bezeichnet"),
        ConditionCode("235595009", "Gastroesophageal reflux disease", "Refluxkrankheit",
                      "K21.9", "Gastroösophageale Refluxkrankheit ohne Ösophagitis"),
        ConditionCode("363346000", "Malignant neoplastic disease", "Bösartige Neubildung",
                      "C80.9", "Bösartige Neubildung, nicht näher bezeichnet"),
        ConditionCode("73430006", "Sleep apnea", "Schlafapnoe-Syndrom",
                      "G47.31", "Obstruktives Schlafapnoe-Syndrom"),
    ]
}


# ---------------------------------------------------------------------------
# Zugriff
# ---------------------------------------------------------------------------


def observation_catalog_text() -> str:
    """Kompakte Katalogdarstellung für den Prompt."""
    return "\n".join(
        f"  {o.code} | {o.display_de} ({o.display}) | Einheit {o.unit} "
        f"| plausibler Bereich {o.low}-{o.high}"
        for o in OBSERVATION_CODES.values()
    )


def condition_catalog_text() -> str:
    """Kompakte Katalogdarstellung für den Prompt."""
    return "\n".join(
        f"  {c.code} | {c.display_de} ({c.display})" for c in CONDITION_CODES.values()
    )


def icd_abdeckung() -> tuple[int, int]:
    """(Diagnosen mit ICD-10-GM, Diagnosen gesamt).

    Wird im Test und in der Projektdokumentation ausgewiesen, damit der
    Pflegestand des Katalogs sichtbar bleibt statt stillschweigend zu
    verwahrlosen.
    """
    mit = sum(1 for c in CONDITION_CODES.values() if c.hat_icd)
    return mit, len(CONDITION_CODES)
