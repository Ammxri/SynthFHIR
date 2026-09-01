"""FHIR-R4-Vorlagen — hier entsteht die strukturelle Garantie.

Die Vorlagen sind der Kern der Architektur aus ADR-001: Sie setzen
Pflichtfelder, Datentypen, Invarianten, Codes und Einheiten von sich aus
richtig. Das Sprachmodell liefert nur Code-Auswahl, Zahl und Datum — es kann
strukturell nichts kaputtmachen.

Welche Pflichtfelder FHIR R4 für die drei Ressourcentypen wirklich verlangt
und warum, ist ausführlich in `docs/konzepte.md`, Abschnitt 3, erklärt. Die
Kurzfassung als Erinnerung beim Lesen des Codes:

  Patient      kein Pflichtfeld außer resourceType. Fehlerquellen sind
               Datentyp und Binding: `gender` ist required bound,
               `birthDate` ist ein `date`, `name` ist ein Objekt.
  Condition    `subject` ist 1..1. Die Invarianten con-3/con-5 koppeln
               clinicalStatus und verificationStatus; beide werden fest
               gesetzt, damit sie immer erfüllt sind.
  Observation  `status` und `code` sind 1..1. `valueQuantity` braucht vier
               Teile, darunter `unit` (Anzeige) und `code` (UCUM) — die
               sind nicht dasselbe.

Dazu die beiden Typen der Phase 2 (ADR-007):

  Encounter    `status` und `class` sind 1..1. **`class` ist ein `Coding`,
               kein CodeableConcept** — der Unterschied ist im JSON fast
               unsichtbar und von HAPI nachgeprüft.
  Medication-  `status`, `medication[x]` und `subject` sind Pflicht.
  Statement    `medication[x]` ist ein choice type; hier immer die
               CodeableConcept-Ausprägung.

Bei beiden neuen Typen setzt der Code den `status`. Gemessen: Ein
erfundener Wert kommt durch die Laufzeitprüfung und wird erst von HAPI
abgewiesen — `fhir.resources` erzwingt required bindings nicht (ADR-002).

Neu gegenüber der Phase 0 (ADR-003): `Condition.code` trägt SNOMED CT und
ICD-10-GM nebeneinander, und die Anzeigetexte sind deutsch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .codes import (
    CONDITION_CODES,
    ENCOUNTER_CLASSES,
    ENCOUNTER_STATUS,
    ICD10GM_SYSTEM,
    ICD10GM_VERSION,
    KONTAKTEBENE_CODE,
    KONTAKTEBENE_SYSTEM,
    LOINC_SYSTEM,
    MEDICATION_CODES,
    MEDICATION_STATUS,
    OBSERVATION_CODES,
    SNOMED_SYSTEM,
    TESTDATEN_LABEL,
    UCUM_SYSTEM,
    V2_0203_SYSTEM,
    ConditionCode,
    EncounterClass,
    MedicationCode,
    ObservationCode,
)

CONDITION_CLINICAL_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-clinical"
CONDITION_VER_STATUS_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-ver-status"
OBSERVATION_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/observation-category"
PATIENT_IDENTIFIER_SYSTEM = "http://synthfhir.local/identifier/patient"
FALL_IDENTIFIER_SYSTEM = "http://synthfhir.local/identifier/fall"

ALLOWED_GENDERS = ("male", "female", "other", "unknown")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Rückfallwerte, wenn das Modell keinen brauchbaren Namen liefert. Deutsch,
# weil die Lokalisierung der zweite Differenzierer des Produkts ist und ein
# englischer Platzhalter das sichtbar unterlaufen würde.
FALLBACK_VORNAME = "Unbekannt"
FALLBACK_NACHNAME = "Testperson"

# Das Rückfalldatum, wenn das Modell keines oder ein unlesbares liefert.
#
# EINE Konstante für das ganze Modul, und das ist keine Aufräumarbeit:
# `baue_condition` fiel auf 2020-01-01 zurück, `_kontaktdatum` auf
# 2024-01-01. Lieferte das Modell ein unbrauchbares Diagnosedatum — etwa
# „01.03.2021" im deutschen Format —, entstand eine Diagnose von 2020 und
# ein vom Code ergänzter Kontakt von 2024: vier Jahre nach der Diagnose,
# die er dokumentieren soll. Kein Validierungsfehler, aber ein
# unplausibler Datensatz, den keine Prüfschicht meldet.
RUECKFALLDATUM = "2020-01-01"


@dataclass
class Beanstandung:
    """Eine Abweichung in den vom Modell gelieferten Parametern.

    Wird protokolliert statt verschwiegen: Die Metrik „Anteil erfundener
    Codes" aus dem PRD speist sich genau hieraus.
    """

    art: str
    detail: str

    def to_dict(self) -> dict:
        return {"art": self.art, "detail": self.detail}


@dataclass
class Bauergebnis:
    """Ergebnis des Zusammenbaus aus Parametern."""

    ressourcen: list[dict] = field(default_factory=list)
    beanstandungen: list[Beanstandung] = field(default_factory=list)

    # Wie viele Kennungsplätze dieser Aufruf verbraucht hat.
    #
    # Nicht dasselbe wie die Zahl der gebauten Patienten: Ein Eintrag, der
    # kein Objekt ist, wird übersprungen, verbraucht aber seinen Platz —
    # `p_index` zählt über `enumerate(patienten)`. Wer den Versatz des
    # nächsten Teils aus der Zahl der GEBAUTEN Patienten fortschreibt,
    # lässt beide Zähler auseinanderlaufen und vergibt Kennungen doppelt.
    plaetze_belegt: int = 0

    @property
    def erfundene_codes(self) -> int:
        """Zählt jede erfundene Angabe, nicht eine Aufzählung davon.

        Hier standen zwei Arten von Hand aufgezählt. Mit den Katalogen der
        Phase 2 kamen zwei weitere hinzu — `erfundener_medikamentencode`
        und `erfundene_begegnungsart` —, und die Metrik aus dem PRD meldete
        weiter nur zwei von vier. Ein Präfix kann keine neue Art vergessen.
        """
        return sum(1 for b in self.beanstandungen if b.art.startswith("erfunden"))


# --- Prüfung der Modellparameter -------------------------------------------


def _datum(wert: object, ersatz: str, beanstandungen: list[Beanstandung], feld: str) -> str:
    if isinstance(wert, str) and _DATE_RE.match(wert.strip()):
        return wert.strip()
    beanstandungen.append(
        Beanstandung("ungueltiges_datum", f"{feld}: {wert!r} ist kein Datum YYYY-MM-DD -> {ersatz}")
    )
    return ersatz


def _geschlecht(wert: object, beanstandungen: list[Beanstandung]) -> str:
    if isinstance(wert, str) and wert.strip().lower() in ALLOWED_GENDERS:
        return wert.strip().lower()
    beanstandungen.append(
        Beanstandung("ungueltiges_geschlecht", f"Geschlecht {wert!r} nicht zulässig -> unknown")
    )
    return "unknown"


def _text(wert: object, ersatz: str) -> str:
    return wert.strip() if isinstance(wert, str) and wert.strip() else ersatz


def _diagnosecode(wert: object, index: int, beanstandungen: list[Beanstandung]) -> ConditionCode:
    code = str(wert).strip() if wert is not None else ""
    if code in CONDITION_CODES:
        return CONDITION_CODES[code]
    ersatz = list(CONDITION_CODES.values())[index % len(CONDITION_CODES)]
    beanstandungen.append(
        Beanstandung(
            "erfundener_diagnosecode",
            f"Diagnosecode {code!r} nicht im Katalog -> ersetzt durch {ersatz.code}",
        )
    )
    return ersatz


def _messwertcode(wert: object, index: int, beanstandungen: list[Beanstandung]) -> ObservationCode:
    code = str(wert).strip() if wert is not None else ""
    if code in OBSERVATION_CODES:
        return OBSERVATION_CODES[code]
    ersatz = list(OBSERVATION_CODES.values())[index % len(OBSERVATION_CODES)]
    beanstandungen.append(
        Beanstandung(
            "erfundener_messwertcode",
            f"Messwertcode {code!r} nicht im Katalog -> ersetzt durch {ersatz.code}",
        )
    )
    return ersatz


def _messwert(wert: object, spec: ObservationCode, beanstandungen: list[Beanstandung]) -> float:
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        mitte = round((spec.low + spec.high) / 2, 2)
        beanstandungen.append(
            Beanstandung(
                "ungueltiger_messwert",
                f"Messwert {wert!r} für {spec.code} ist keine Zahl -> {mitte}",
            )
        )
        return mitte
    return round(float(wert), 2)


# --- Vorlagen --------------------------------------------------------------


def baue_patient(params: dict, index: int, beanstandungen: list[Beanstandung]) -> dict:
    """Patient. Kein Pflichtfeld außer resourceType — die Risiken sind
    Datentyp (`birthDate`) und required binding (`gender`)."""
    return {
        "resourceType": "Patient",
        "id": f"tmp-pat-{index}",
        "identifier": [
            {
                # `type` ist der Schlüssel zum ISiK-Slice
                # `identifier:Patientennummer`: Das Profil erkennt die
                # Patientennummer am Muster `MR`, nicht am System. Ohne diese
                # Kodierung greift der Slice nicht, und die Ressource ist
                # nicht konform — obwohl ein Identifier dasteht.
                "type": {"coding": [{"system": V2_0203_SYSTEM, "code": "MR"}]},
                "system": PATIENT_IDENTIFIER_SYSTEM,
                "value": f"SYN-{index + 1:04d}",
            }
        ],
        "name": [
            {
                "use": "official",
                "family": _text(params.get("nachname"), f"{FALLBACK_NACHNAME}{index + 1}"),
                "given": [_text(params.get("vorname"), FALLBACK_VORNAME)],
            }
        ],
        "gender": _geschlecht(params.get("geschlecht"), beanstandungen),
        "birthDate": _datum(params.get("geburtsdatum"), "1970-01-01", beanstandungen, "geburtsdatum"),
    }


def baue_condition(
    params: dict, patient_index: int, index: int,
    beanstandungen: list[Beanstandung], teil: int = 0
) -> dict:
    """Condition. `subject` ist 1..1; clinicalStatus und verificationStatus
    werden fest gesetzt, damit die Invarianten con-3 und con-5 unabhängig
    vom Modell immer erfüllt sind.

    `code` trägt beide Kodierungen desselben Konzepts (ADR-003). Fehlt ein
    geprüfter ICD-10-GM-Schlüssel, bleibt es bei SNOMED allein — das ist
    weiterhin gültiges FHIR.
    """
    spec = _diagnosecode(params.get("code"), index, beanstandungen)
    beginn = _datum(params.get("beginn"), RUECKFALLDATUM, beanstandungen, "beginn")

    codings = [{"system": SNOMED_SYSTEM, "code": spec.code, "display": spec.display}]
    if spec.hat_icd:
        codings.append(
            {
                "system": ICD10GM_SYSTEM,
                # Die Jahresfassung gehört zur Kodierung: ICD-10-GM ändert
                # sich jährlich, ein Schlüssel ohne Jahr ist nur ungefähr
                # bestimmt. ISiK macht sie zur Pflicht.
                "version": ICD10GM_VERSION,
                "code": spec.icd10gm,
                "display": spec.icd10gm_display or spec.display_de,
            }
        )

    return {
        "resourceType": "Condition",
        "id": f"tmp-cond-{teil}-{index}",
        "clinicalStatus": {
            "coding": [
                {"system": CONDITION_CLINICAL_SYSTEM, "code": "active", "display": "Active"}
            ]
        },
        "verificationStatus": {
            "coding": [
                {"system": CONDITION_VER_STATUS_SYSTEM, "code": "confirmed", "display": "Confirmed"}
            ]
        },
        "code": {"coding": codings, "text": spec.display_de},
        "subject": {"reference": f"Patient/tmp-pat-{patient_index}"},
        "onsetDateTime": beginn,
        # Wann die Diagnose dokumentiert wurde. ISiK verlangt das Feld;
        # ein besseres Datum als den Beginn haben wir nicht, und eines zu
        # erfinden wäre schlechter, als das bekannte zu nehmen.
        "recordedDate": beginn,
    }


def baue_observation(
    params: dict, patient_index: int, index: int,
    beanstandungen: list[Beanstandung], teil: int = 0
) -> dict:
    """Observation. `status` und `code` sind 1..1; `valueQuantity` braucht
    Wert, Anzeigeeinheit, System und UCUM-Code."""
    spec = _messwertcode(params.get("code"), index, beanstandungen)
    wert = _messwert(params.get("wert"), spec, beanstandungen)
    kategorie = "vital-signs" if spec.vital_sign else "laboratory"

    return {
        "resourceType": "Observation",
        "id": f"tmp-obs-{teil}-{index}",
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": OBSERVATION_CATEGORY_SYSTEM,
                        "code": kategorie,
                        "display": "Vital Signs" if spec.vital_sign else "Laboratory",
                    }
                ]
            }
        ],
        "code": {
            "coding": [{"system": LOINC_SYSTEM, "code": spec.code, "display": spec.display}],
            "text": spec.display_de,
        },
        "subject": {"reference": f"Patient/tmp-pat-{patient_index}"},
        "effectiveDateTime": _datum(params.get("datum"), RUECKFALLDATUM, beanstandungen, "datum"),
        "valueQuantity": {
            "value": wert,
            "unit": spec.unit,       # menschenlesbar
            "system": UCUM_SYSTEM,
            "code": spec.unit_code,  # UCUM — nicht identisch mit `unit`
        },
    }


def _medikamentencode(
    wert: object, index: int, beanstandungen: list[Beanstandung]
) -> MedicationCode:
    code = str(wert).strip() if wert is not None else ""
    if code in MEDICATION_CODES:
        return MEDICATION_CODES[code]
    ersatz = list(MEDICATION_CODES.values())[index % len(MEDICATION_CODES)]
    beanstandungen.append(
        Beanstandung(
            "erfundener_medikamentencode",
            f"Wirkstoffcode {code!r} nicht im Katalog -> ersetzt durch {ersatz.code}",
        )
    )
    return ersatz


def _begegnungsart(
    wert: object, beanstandungen: list[Beanstandung]
) -> EncounterClass:
    code = str(wert).strip().upper() if wert is not None else ""
    if code in ENCOUNTER_CLASSES:
        return ENCOUNTER_CLASSES[code]
    ersatz = ENCOUNTER_CLASSES["AMB"]
    if code:
        beanstandungen.append(
            Beanstandung(
                "erfundene_begegnungsart",
                f"Begegnungsart {code!r} nicht im Katalog -> ersetzt durch {ersatz.code}",
            )
        )
    return ersatz


def _kontaktdatum(patient: dict) -> str:
    """Ein plausibles Datum für einen vom Code ergänzten Kontakt.

    Der Beginn der ersten Diagnose passt am besten: Der Kontakt, in dem
    eine Diagnose gestellt wird, liegt zu ihrem Beginn. Ein erfundenes
    Datum wäre schlechter als ein bekanntes.
    """
    for feld, schluessel in (("diagnosen", "beginn"), ("messwerte", "datum")):
        eintraege = patient.get(feld)
        if isinstance(eintraege, list):
            for e in eintraege:
                wert = e.get(schluessel) if isinstance(e, dict) else None
                if isinstance(wert, str) and _DATE_RE.match(wert.strip()):
                    return wert.strip()
    return RUECKFALLDATUM


def baue_encounter(
    params: dict, patient_index: int, index: int,
    beanstandungen: list[Beanstandung], teil: int = 0,
    nummer_beim_patienten: int = 0,
) -> dict:
    """Encounter. Nur `status` und `class` sind Pflicht (je 1..1).

    Beide setzt der Code, nicht das Modell, und das ist keine Vorsicht,
    sondern gemessen: Ein `status` von „abgeschlossen" kommt durch die
    Laufzeitprüfung und wird erst von HAPI abgewiesen — die Bindung ist
    verpflichtend, aber `fhir.resources` erzwingt required bindings nicht
    (ADR-002).

    **`class` ist ein `Coding`, kein `CodeableConcept`.** Nachgeprüft:
    HAPI antwortet auf ein `{"coding": [...]}` mit „Unrecognized property
    'coding'". Der Unterschied ist im JSON unsichtbar und im Editor
    unauffällig.

    `type` blieb bis ADR-009 leer: Es wäre schmückend gewesen, verlangte
    aber Codes für Begegnungsarten, und jeder davon müsste einzeln an der
    Primärquelle geprüft werden. Ein ungeprüfter Code ist teurer als ein
    fehlendes optionales Feld. Seit ADR-009 steht es doch da — nicht als
    Schmuck, sondern weil ISiK den Slice `type:Kontaktebene` verlangt, und
    mit **einem** Code aus `http://fhir.de/CodeSystem/Kontaktebene`, der an
    der Quelle geprüft ist. Der Absatz stand hier noch unverändert und sagte
    das Gegenteil dessen, was sechs Zeilen weiter unten geschieht.
    """
    art = _begegnungsart(params.get("art"), beanstandungen)
    datum = _datum(params.get("datum"), RUECKFALLDATUM, beanstandungen, "datum")
    return {
        "resourceType": "Encounter",
        "id": f"tmp-enc-{teil}-{index}",
        "status": ENCOUNTER_STATUS,
        "class": {"system": art.system, "code": art.code, "display": art.display},
        # Die Fallnummer. ISiK verlangt mindestens einen Identifier, und die
        # Typkodierung `VN` ist dort ein 1..1-Slice — ein Identifier ohne sie
        # erfüllt die Vorgabe nicht.
        #
        # Hier stand `FALL-{index + 1:04d}`, und `index` ist der
        # TEIL-LOKALE Zähler: Er beginnt in jedem Teil wieder bei null.
        # Damit vergab jeder Teil erneut FALL-0001, FALL-0002, … Bei 200
        # Patienten und `TEILGROESSE = 8` war jede Fallnummer 25-fach
        # vergeben. Die Patientennummer daneben war korrekt, weil sie am
        # globalen `patient_index` hängt — der Unterschied war
        # unauffällig, weil beide Zeilen gleich aussehen.
        #
        # Keine Prüfschicht schlug an: `assign_ids` macht die technische
        # `id` über den Teilkenner eindeutig, und `check_resources` prüft
        # `resourceType/id` — den fachlichen Identifier sah niemand an.
        #
        # Jetzt aus dem globalen Patientenzähler und der Nummer des
        # Kontakts BEI DIESEM PATIENTEN. Das ist zugleich die Bedeutung,
        # die eine Fallnummer im Haus hat: der wievielte Fall dieses
        # Patienten. Ein teilübergreifend fortlaufender Zähler stünde hier
        # nicht zur Verfügung — der Versatz wächst nur um die Zahl der
        # Patienten, nicht der Kontakte.
        "identifier": [
            {
                "type": {"coding": [{"system": V2_0203_SYSTEM, "code": "VN"}]},
                "system": FALL_IDENTIFIER_SYSTEM,
                "value": f"FALL-{patient_index + 1:04d}-{nummer_beim_patienten + 1}",
            }
        ],
        # Die Kontaktebene. Nicht zu verwechseln mit `class`: `class` sagt,
        # WIE der Kontakt stattfand (ambulant, stationär), `type` mit der
        # Kontaktebene sagt, auf welcher Ebene er verbucht ist.
        "type": [
            {"coding": [{"system": KONTAKTEBENE_SYSTEM, "code": KONTAKTEBENE_CODE}]}
        ],
        "subject": {"reference": f"Patient/tmp-pat-{patient_index}"},
        "period": {"start": datum, "end": datum},
    }


def baue_medicationstatement(
    params: dict, patient_index: int, index: int,
    beanstandungen: list[Beanstandung], teil: int = 0
) -> dict:
    """MedicationStatement. Pflicht sind `status`, `medication[x]` und
    `subject`.

    `medication[x]` ist ein choice type: Entweder ein CodeableConcept oder
    ein Verweis auf eine Medication-Ressource. Hier das CodeableConcept —
    ein Verweis verlangte einen sechsten Ressourcentyp, ohne dass die
    Testdaten dadurch etwas gewönnen.

    Der ATC-Code kommt aus dem Katalog, nie vom Modell. Weder die
    Laufzeitprüfung noch HAPI merken einen falschen: HAPI meldet
    ausdrücklich `CodeSystem is unknown and can't be validated`.
    """
    spec = _medikamentencode(params.get("code"), index, beanstandungen)
    return {
        "resourceType": "MedicationStatement",
        "id": f"tmp-med-{teil}-{index}",
        "status": MEDICATION_STATUS,
        "medicationCodeableConcept": {
            "coding": [
                {"system": spec.system, "code": spec.code, "display": spec.display}
            ],
            "text": spec.display_de,
        },
        "subject": {"reference": f"Patient/tmp-pat-{patient_index}"},
        "effectiveDateTime": _datum(
            params.get("beginn"), "2023-01-01", beanstandungen, "beginn"
        ),
        "dosage": [{"text": spec.dosierung}],
    }


def baue_aus_parametern(
    parameter: dict,
    erwartet: dict[str, int] | None = None,
    *,
    index_versatz: int = 0,
) -> Bauergebnis:
    """Setzt den kompletten Ressourcensatz aus dem Parameterobjekt zusammen.

    `erwartet` ist optional: Wenn Sollzahlen bekannt sind, werden
    Abweichungen protokolliert, aber **nicht** aufgefüllt. Die Mengentreue
    war in Phase 0 das entscheidende Kriterium — sie muss messbar bleiben,
    nicht stillschweigend korrigiert werden.

    `index_versatz` verschiebt die vorläufigen Kennungen (`tmp-pat-0`,
    `tmp-cond-0` …). Für die stückweise Erzeugung großer Kohorten ist das
    zwingend: Ohne Versatz begänne jeder Teil wieder bei null, zwei
    aneinandergehängte Teile trügen kollidierende Kennungen, und die
    Verweise des zweiten Teils zeigten auf Patienten des ersten. Die
    Integritätsprüfung meldete das zwar — aber erst, nachdem der Schaden
    entstanden ist.
    """
    ergebnis = Bauergebnis()
    b = ergebnis.beanstandungen
    erwartet = erwartet or {}

    patienten = parameter.get("patienten")
    if not isinstance(patienten, list) or not patienten:
        b.append(Beanstandung("fehlendes_feld", "Parameterobjekt enthält keine Liste 'patienten'."))
        return ergebnis

    # Jeder Eintrag verbraucht seinen Kennungsplatz, auch ein übersprungener.
    ergebnis.plaetze_belegt = len(patienten)

    soll_p = erwartet.get("patienten")
    if soll_p is not None and len(patienten) != soll_p:
        b.append(
            Beanstandung("mengenabweichung", f"{len(patienten)} Patienten geliefert, {soll_p} erwartet")
        )

    # Teil-LOKALE Zähler ab null. Der Versatz wandert stattdessen als
    # Teilkenner in die vorläufige Kennung (`tmp-enc-{versatz}-{n}`).
    #
    # Vorher starteten diese Zähler beim Versatz — und weil der Versatz nur
    # um die Zahl der PATIENTEN wächst, überholten sie ihn, sobald ein
    # Patient mehr als eine Ressource eines Typs hatte. Nachgestellt mit
    # zwei Teilen zu je drei Patienten mit je zwei Begegnungen: sechs
    # doppelte Kennungen, neun kaputte Verweise, `integritaet.ok = False`.
    #
    # Der Fehler steckte seit ADR-004 drin und war folgenlos, solange nichts
    # auf eine Nicht-Patient-Ressource zeigte. Mit Encounter wurde er scharf.
    # Diese Form schließt ihn baulich aus statt ihn nur diesmal zu beheben.
    cond_index = obs_index = enc_index = med_index = 0
    for roh_index, roh in enumerate(patienten):
        p_index = index_versatz + roh_index
        if not isinstance(roh, dict):
            b.append(Beanstandung("fehlendes_feld", f"Patienteneintrag {p_index} ist kein Objekt."))
            continue

        ergebnis.ressourcen.append(baue_patient(roh, p_index, b))

        # Begegnungen zuerst: Diagnosen und Messwerte dürfen auf sie
        # verweisen, und ein Verweis nach vorn ist leichter zu prüfen als
        # einer nach hinten — auch wenn `assign_ids` beide auflöst.
        begegnungen = roh.get("begegnungen") if isinstance(roh.get("begegnungen"), list) else []
        diagnosen_roh = roh.get("diagnosen") if isinstance(roh.get("diagnosen"), list) else []
        if not begegnungen and diagnosen_roh:
            # ISiK verlangt über `isik-con1`, dass eine kodierte Diagnose
            # nennt, in welchem Kontakt sie gestellt wurde. Das Modell
            # liefert Begegnungen aber nur, wenn danach gefragt wurde —
            # also stellt der Code den Kontakt her, so wie er auch
            # Pflichtfelder und Einheiten herstellt (ADR-001).
            #
            # Das ist der eine Punkt, an dem Profilkonformität nicht durch
            # ein zusätzliches Feld zu haben war, sondern die Erzeugung
            # selbst betrifft: Eine Diagnose ohne Kontakt ist kein
            # unvollständiger Datensatz, sondern ein unzulässiger.
            begegnungen = [{"art": "AMB", "datum": _kontaktdatum(roh)}]
        erste_begegnung: str | None = None
        for k, eintrag in enumerate(begegnungen):
            ergebnis.ressourcen.append(
                baue_encounter(eintrag if isinstance(eintrag, dict) else {},
                               p_index, enc_index, b, index_versatz,
                               nummer_beim_patienten=k)
            )
            if erste_begegnung is None:
                erste_begegnung = f"Encounter/tmp-enc-{index_versatz}-{enc_index}"
            enc_index += 1

        diagnosen = roh.get("diagnosen") if isinstance(roh.get("diagnosen"), list) else []
        soll_d = erwartet.get("diagnosen_je_patient")
        if soll_d is not None and len(diagnosen) != soll_d:
            b.append(
                Beanstandung(
                    "mengenabweichung",
                    f"Patient {p_index}: {len(diagnosen)} Diagnosen geliefert, {soll_d} erwartet",
                )
            )
        for eintrag in diagnosen:
            cond = baue_condition(
                eintrag if isinstance(eintrag, dict) else {}, p_index, cond_index,
                b, index_versatz
            )
            # Nur setzen, wenn es die Begegnung wirklich gibt. Ein Verweis
            # ins Leere wäre strukturell einwandfrei und trotzdem falsch —
            # genau die Fehlerklasse, gegen die die Integritätsprüfung
            # existiert.
            if erste_begegnung:
                cond["encounter"] = {"reference": erste_begegnung}
            ergebnis.ressourcen.append(cond)
            cond_index += 1

        messwerte = roh.get("messwerte") if isinstance(roh.get("messwerte"), list) else []
        soll_m = erwartet.get("messwerte_je_patient")
        if soll_m is not None and len(messwerte) != soll_m:
            b.append(
                Beanstandung(
                    "mengenabweichung",
                    f"Patient {p_index}: {len(messwerte)} Messwerte geliefert, {soll_m} erwartet",
                )
            )
        for eintrag in messwerte:
            obs = baue_observation(
                eintrag if isinstance(eintrag, dict) else {}, p_index, obs_index,
                b, index_versatz
            )
            if erste_begegnung:
                obs["encounter"] = {"reference": erste_begegnung}
            ergebnis.ressourcen.append(obs)
            obs_index += 1

        medikamente = roh.get("medikamente") if isinstance(roh.get("medikamente"), list) else []
        for eintrag in medikamente:
            ergebnis.ressourcen.append(
                baue_medicationstatement(
                    eintrag if isinstance(eintrag, dict) else {}, p_index, med_index,
                    b, index_versatz
                )
            )
            med_index += 1

    for r in ergebnis.ressourcen:
        kennzeichne_als_testdaten(r)
    return ergebnis


def kennzeichne_als_testdaten(ressource: dict) -> dict:
    """Setzt `meta.security` auf HTEST — auf jede erzeugte Ressource.

    Das Projekt verspricht an vielen Stellen, ausschließlich synthetische
    Daten zu erzeugen. Bisher stand dieses Versprechen im README, im
    Manifest und in der Konsolenausgabe — also überall dort, wo ein Mensch
    hinsieht, und nirgends dort, wo eine Maschine hinsieht.

    `HTEST` macht daraus eine prüfbare Aussage. Ein Empfänger kann danach
    suchen (`_security=HTEST` — an HAPI nachgeprüft), und ein Server kann
    solche Daten von echten trennen. Die Definition des Codes trifft
    diesen Fall wörtlich: *„simulated or synthetic health data used for
    testing system capabilities outside of a production or operational
    system environment."*

    Das Label sitzt bewusst an **jeder** Ressource und nicht erst am
    Server-Push. Eine Datei, die heute exportiert wird, kann morgen jemand
    anderes irgendwohin laden — dann ist die Kennzeichnung schon drin.

    Angewandt wird es an genau einer Stelle, am Ende von
    `baue_aus_parametern`. Jede erzeugte Ressource läuft dort hindurch; ein
    neuer Ressourcentyp bekommt es also, ohne dass jemand daran denken
    muss.
    """
    meta = ressource.setdefault("meta", {})
    vorhanden = meta.setdefault("security", [])
    if not any(
        s.get("system") == TESTDATEN_LABEL["system"]
        and s.get("code") == TESTDATEN_LABEL["code"]
        for s in vorhanden
        if isinstance(s, dict)
    ):
        vorhanden.append(dict(TESTDATEN_LABEL))
    return ressource


def baue_bundle(ressourcen: list[dict], basis_url: str = "http://synthfhir.local/fhir") -> dict:
    """Fasst die Ressourcen als Bundle vom Typ `collection` zusammen.

    `collection` hat keine Transaktionssemantik, deshalb dürfen
    `entry.request` und `entry.response` nicht gesetzt sein (Invariante
    bdl-3). `fullUrl` muss im Bundle eindeutig sein (bdl-7) — das ist
    garantiert, weil der Code die IDs vergibt.
    """
    basis = basis_url.rstrip("/")
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "fullUrl": f"{basis}/{r.get('resourceType')}/{r.get('id')}",
                "resource": r,
            }
            for r in ressourcen
        ],
    }
