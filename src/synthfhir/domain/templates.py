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

Neu gegenüber der Phase 0 (ADR-003): `Condition.code` trägt SNOMED CT und
ICD-10-GM nebeneinander, und die Anzeigetexte sind deutsch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .codes import (
    CONDITION_CODES,
    ICD10GM_SYSTEM,
    LOINC_SYSTEM,
    OBSERVATION_CODES,
    SNOMED_SYSTEM,
    UCUM_SYSTEM,
    ConditionCode,
    ObservationCode,
)

CONDITION_CLINICAL_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-clinical"
CONDITION_VER_STATUS_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-ver-status"
OBSERVATION_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/observation-category"
PATIENT_IDENTIFIER_SYSTEM = "http://synthfhir.local/identifier/patient"

ALLOWED_GENDERS = ("male", "female", "other", "unknown")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Rückfallwerte, wenn das Modell keinen brauchbaren Namen liefert. Deutsch,
# weil die Lokalisierung der zweite Differenzierer des Produkts ist und ein
# englischer Platzhalter das sichtbar unterlaufen würde.
FALLBACK_VORNAME = "Unbekannt"
FALLBACK_NACHNAME = "Testperson"


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

    @property
    def erfundene_codes(self) -> int:
        return sum(
            1
            for b in self.beanstandungen
            if b.art in ("erfundener_diagnosecode", "erfundener_messwertcode")
        )


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
            {"system": PATIENT_IDENTIFIER_SYSTEM, "value": f"SYN-{index + 1:04d}"}
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
    params: dict, patient_index: int, index: int, beanstandungen: list[Beanstandung]
) -> dict:
    """Condition. `subject` ist 1..1; clinicalStatus und verificationStatus
    werden fest gesetzt, damit die Invarianten con-3 und con-5 unabhängig
    vom Modell immer erfüllt sind.

    `code` trägt beide Kodierungen desselben Konzepts (ADR-003). Fehlt ein
    geprüfter ICD-10-GM-Schlüssel, bleibt es bei SNOMED allein — das ist
    weiterhin gültiges FHIR.
    """
    spec = _diagnosecode(params.get("code"), index, beanstandungen)

    codings = [{"system": SNOMED_SYSTEM, "code": spec.code, "display": spec.display}]
    if spec.hat_icd:
        codings.append(
            {
                "system": ICD10GM_SYSTEM,
                "code": spec.icd10gm,
                "display": spec.icd10gm_display or spec.display_de,
            }
        )

    return {
        "resourceType": "Condition",
        "id": f"tmp-cond-{index}",
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
        "onsetDateTime": _datum(params.get("beginn"), "2020-01-01", beanstandungen, "beginn"),
    }


def baue_observation(
    params: dict, patient_index: int, index: int, beanstandungen: list[Beanstandung]
) -> dict:
    """Observation. `status` und `code` sind 1..1; `valueQuantity` braucht
    Wert, Anzeigeeinheit, System und UCUM-Code."""
    spec = _messwertcode(params.get("code"), index, beanstandungen)
    wert = _messwert(params.get("wert"), spec, beanstandungen)
    kategorie = "vital-signs" if spec.vital_sign else "laboratory"

    return {
        "resourceType": "Observation",
        "id": f"tmp-obs-{index}",
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
        "effectiveDateTime": _datum(params.get("datum"), "2024-01-01", beanstandungen, "datum"),
        "valueQuantity": {
            "value": wert,
            "unit": spec.unit,       # menschenlesbar
            "system": UCUM_SYSTEM,
            "code": spec.unit_code,  # UCUM — nicht identisch mit `unit`
        },
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

    soll_p = erwartet.get("patienten")
    if soll_p is not None and len(patienten) != soll_p:
        b.append(
            Beanstandung("mengenabweichung", f"{len(patienten)} Patienten geliefert, {soll_p} erwartet")
        )

    cond_index = obs_index = index_versatz
    for roh_index, roh in enumerate(patienten):
        p_index = index_versatz + roh_index
        if not isinstance(roh, dict):
            b.append(Beanstandung("fehlendes_feld", f"Patienteneintrag {p_index} ist kein Objekt."))
            continue

        ergebnis.ressourcen.append(baue_patient(roh, p_index, b))

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
            ergebnis.ressourcen.append(
                baue_condition(eintrag if isinstance(eintrag, dict) else {}, p_index, cond_index, b)
            )
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
            ergebnis.ressourcen.append(
                baue_observation(eintrag if isinstance(eintrag, dict) else {}, p_index, obs_index, b)
            )
            obs_index += 1

    return ergebnis


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
