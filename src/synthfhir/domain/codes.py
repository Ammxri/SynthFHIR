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
# ATC in der Fassung der WHO. Das ist die von HL7 kanonisierte URI
# (terminology.hl7.org, CodeSystem v3-WC).
#
# Es gäbe auch die deutsche amtliche Fassung unter
# `http://fhir.de/CodeSystem/bfarm/atc` — und die stand hier zuerst. Sie ist
# aber falsch, solange der Anzeigetext englisch bleibt: `display` soll die
# Bezeichnung AUS DEM GENANNTEN SYSTEM sein, und im deutschen Katalog heißt
# der Eintrag „Metformin", nicht „metformin".
#
# Geprüft wurden Code UND englische Bezeichnung am ATC/DDD-Index der WHO.
# Die deutschen Namen stammen dagegen nicht aus einer geprüften Quelle,
# deshalb stehen sie in `text` und nicht in einem zweiten Coding. Das ist
# derselbe Grundsatz wie in ADR-003 bei ICD-10-GM: lieber keine zweite
# Kodierung als eine geratene.
ATC_SYSTEM = "http://www.whocc.no/atc"
# Begegnungsart. Kein deutsches System: `Encounter.class` ist an dieses
# ValueSet gebunden, und die Bindung ist verpflichtend.
ACT_CODE_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-ActCode"


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


# ---------------------------------------------------------------------------
# Medikamente (Phase 2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MedicationCode:
    """Ein zulässiger Wirkstoff.

    `display` ist die Bezeichnung **wörtlich** aus dem ATC/DDD-Index der
    WHO — kleingeschrieben und englisch, so wie sie dort steht. Das ist
    Absicht: Eine geglättete Schreibweise ließe sich nicht mehr gegen die
    Quelle abgleichen, und genau dieser Abgleich ist die einzige Prüfung,
    die es für Codes gibt. Sie gehört zu `ATC_SYSTEM`, das deshalb auf die
    WHO-Fassung zeigt und nicht auf die deutsche.

    `display_de` ist der deutsche Name für die Anzeige. Er landet in
    `CodeableConcept.text`, nicht in einem Coding: Er stammt nicht aus einer
    geprüften Quelle, und ein ungeprüfter Anzeigetext unter einer
    Systemangabe wäre eine Behauptung über diesen Katalog.

    `indikationen` nennt die SNOMED-Codes der Diagnosen, zu denen der
    Wirkstoff passt. Ohne diese Verknüpfung müsste das Modell entscheiden,
    welches Mittel zu welcher Krankheit gehört — und damit läge eine
    fachliche Aussage beim Modell statt im Katalog, entgegen ADR-001.
    """

    code: str                       # ATC
    display: str                    # wörtlich aus dem WHOCC-Index
    display_de: str                 # deutscher Wirkstoffname
    indikationen: tuple[str, ...]   # SNOMED-Codes aus CONDITION_CODES
    dosierung: str                  # Freitext für Dosage.text

    @property
    def system(self) -> str:
        return ATC_SYSTEM


# Alle Codes am 2026-08-30 einzeln gegen den ATC/DDD-Index des WHO
# Collaborating Centre for Drug Statistics Methodology geprüft
# (<https://atcddd.fhi.no/atc_ddd_index/>), Abfrage je Code über
# `?code=<ATC>`. Die englische Bezeichnung ist von dort übernommen.
#
# Wer hier etwas ergänzt: derselbe Weg, Code für Code. Weder die
# Laufzeitprüfung noch HAPI merken einen falschen ATC-Code — HAPI meldet
# ausdrücklich `CodeSystem is unknown and can't be validated`.
MEDICATION_CODES: dict[str, MedicationCode] = {
    m.code: m
    for m in [
        MedicationCode("A10BA02", "metformin", "Metformin",
                       ("44054006",), "1000 mg, 2-mal täglich"),
        MedicationCode("A10AB01", "insulin (human)", "Humaninsulin",
                       ("46635009",), "nach Blutzucker, subkutan"),
        MedicationCode("C09AA05", "ramipril", "Ramipril",
                       ("38341003", "84114007", "709044004"),
                       "5 mg, 1-mal täglich"),
        MedicationCode("C08CA01", "amlodipine", "Amlodipin",
                       ("38341003",), "5 mg, 1-mal täglich"),
        MedicationCode("C07AB07", "bisoprolol", "Bisoprolol",
                       ("38341003", "84114007", "49436004", "53741008"),
                       "5 mg, 1-mal täglich"),
        MedicationCode("C03CA01", "furosemide", "Furosemid",
                       ("84114007",), "40 mg, 1-mal täglich"),
        MedicationCode("C10AA01", "simvastatin", "Simvastatin",
                       ("13644009", "53741008", "22298006"),
                       "20 mg, abends"),
        MedicationCode("B01AC06", "acetylsalicylic acid", "Acetylsalicylsäure",
                       ("53741008", "22298006", "230690007"),
                       "100 mg, 1-mal täglich"),
        MedicationCode("B01AF01", "rivaroxaban", "Rivaroxaban",
                       ("49436004",), "20 mg, 1-mal täglich"),
        MedicationCode("R03AC02", "salbutamol", "Salbutamol",
                       ("195967001", "13645005"),
                       "100 µg, bei Bedarf inhalativ"),
        MedicationCode("R03BB04", "tiotropium bromide", "Tiotropiumbromid",
                       ("13645005",), "18 µg, 1-mal täglich inhalativ"),
        MedicationCode("M05BA04", "alendronic acid", "Alendronsäure",
                       ("64859006",), "70 mg, 1-mal wöchentlich"),
        MedicationCode("M01AE01", "ibuprofen", "Ibuprofen",
                       ("396275006", "69896004"), "400 mg, bei Bedarf"),
        MedicationCode("L04AX03", "methotrexate", "Methotrexat",
                       ("69896004",), "15 mg, 1-mal wöchentlich"),
        MedicationCode("N06AB06", "sertraline", "Sertralin",
                       ("35489007", "197480006"), "50 mg, 1-mal täglich"),
        MedicationCode("N06AB10", "escitalopram", "Escitalopram",
                       ("35489007", "197480006"), "10 mg, 1-mal täglich"),
        MedicationCode("A02BC01", "omeprazole", "Omeprazol",
                       ("235595009",), "20 mg, 1-mal täglich"),
        MedicationCode("H03AA01", "levothyroxine sodium", "Levothyroxin-Natrium",
                       ("40930008",), "75 µg, morgens nüchtern"),
        MedicationCode("H03BB02", "thiamazole", "Thiamazol",
                       ("34486009",), "10 mg, 1-mal täglich"),
    ]
}


# ---------------------------------------------------------------------------
# Begegnungsarten (Phase 2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EncounterClass:
    """Eine zulässige Begegnungsart.

    `Encounter.class` ist in FHIR R4 ein **Coding**, kein
    CodeableConcept — nachgeprüft: HAPI weist ein `{"coding": [...]}` mit
    „Unrecognized property 'coding'" ab. Die Bindung an dieses ValueSet ist
    verpflichtend, ein erfundener Code also kein Kavaliersdelikt.

    `display` ist wörtlich aus dem ValueSet v3-ActEncounterCode übernommen.
    """

    code: str
    display: str        # wörtlich aus dem ValueSet
    display_de: str

    @property
    def system(self) -> str:
        return ACT_CODE_SYSTEM


# Geprüft am 2026-08-30 gegen
# <https://terminology.hl7.org/6.0.2/ValueSet-v3-ActEncounterCode.html>.
# Bewusst nur die vier Arten, die in Testdaten tatsächlich vorkommen — ein
# ValueSet vollständig abzuschreiben, ohne dass die Einträge gebraucht
# werden, vergrößert nur die Fläche, die von Hand zu pflegen ist.
ENCOUNTER_CLASSES: dict[str, EncounterClass] = {
    e.code: e
    for e in [
        EncounterClass("AMB", "ambulatory", "ambulant"),
        EncounterClass("IMP", "inpatient encounter", "stationär"),
        EncounterClass("EMER", "emergency", "Notfall"),
        EncounterClass("VR", "virtual", "Videosprechstunde"),
    ]
}

# Pflichtfeld mit verpflichtender Bindung (EncounterStatus). Die
# Laufzeitprüfung sieht das NICHT — nachgemessen: `status: "abgeschlossen"`
# kommt dort durch und wird erst von HAPI abgewiesen. Deshalb setzt die
# Vorlage den Wert, statt ihn vom Modell zu übernehmen.
ENCOUNTER_STATUS = "finished"

# Dasselbe für MedicationStatement (MedicationStatementStatusCodes).
MEDICATION_STATUS = "active"


# ---------------------------------------------------------------------------
# Verzeichnis aller Kataloge
# ---------------------------------------------------------------------------

# Wer den Katalog als Ganzes braucht — etwa für den Fingerabdruck in
# `aufzeichnung.py` —, holt ihn hier und nicht über eine eigene Aufzählung.
#
# Der Grund ist ein bereits gemachter Fehler: Der Fingerabdruck lief über
# eine Aufzählung von Hand und übersah ein Feld. Eine Ebene höher wiederholte
# sich das mit einer ganzen Sammlung — käme ein Katalog hinzu und stünde er
# nicht in jeder Aufzählung, bliebe seine Änderung unbemerkt. Ein Verzeichnis
# an einer Stelle kann man vergessen zu erweitern; drei verstreute
# Aufzählungen vergisst man sicher.
KATALOGE: dict[str, dict] = {
    "observations": OBSERVATION_CODES,
    "conditions": CONDITION_CODES,
    "medications": MEDICATION_CODES,
    "encounter_classes": ENCOUNTER_CLASSES,
}

# Die System-URIs gehören zum Katalog: Sie landen ebenso im Bundle wie die
# Codes selbst.
SYSTEME: tuple[str, ...] = (
    LOINC_SYSTEM,
    SNOMED_SYSTEM,
    UCUM_SYSTEM,
    ICD10GM_SYSTEM,
    ATC_SYSTEM,
    ACT_CODE_SYSTEM,
)

# Auch die festen Statuswerte gehören zum Fingerabdruck: Sie stehen im
# Bundle und ändern sich, wenn jemand sie hier ändert.
FESTE_WERTE: tuple[str, ...] = (ENCOUNTER_STATUS, MEDICATION_STATUS)


def medication_catalog_text() -> str:
    """Kompakte Katalogdarstellung für den Prompt.

    Die Indikationen stehen dabei, damit das Modell ein passendes Mittel
    wählen kann, ohne selbst über die Zuordnung zu entscheiden — die wäre
    eine fachliche Aussage und gehört nach ADR-001 in den Katalog.
    """
    zeilen = []
    for m in MEDICATION_CODES.values():
        bei = ", ".join(CONDITION_CODES[i].display_de for i in m.indikationen
                        if i in CONDITION_CODES)
        zeilen.append(f"  {m.code} | {m.display_de} | bei: {bei}")
    return "\n".join(zeilen)


def encounter_catalog_text() -> str:
    """Kompakte Katalogdarstellung für den Prompt."""
    return "\n".join(
        f"  {e.code} | {e.display_de} ({e.display})"
        for e in ENCOUNTER_CLASSES.values()
    )


def medikamente_fuer(diagnose_code: str) -> list[MedicationCode]:
    """Die Wirkstoffe, die zu einer Diagnose passen — womöglich keiner.

    Fünf Diagnosen im Katalog haben bewusst keinen Wirkstoff, etwa
    Adipositas und Schlafapnoe. Die Vorlage muss das vertragen, statt
    ersatzweise irgendetwas zu wählen: Ein unpassendes Medikament wäre ein
    fachlicher Fehler, den keine Prüfschicht bemerkt — weder die
    Laufzeitprüfung noch HAPI wissen, wogegen Metformin hilft.
    """
    return [m for m in MEDICATION_CODES.values() if diagnose_code in m.indikationen]
