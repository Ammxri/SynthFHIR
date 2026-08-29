"""Der Prompt der Freitext-Stufe.

Das ist die Stelle, die der Spike nie gemessen hat. Dort waren die
Stückzahlen fest vorgegeben; hier muss das Modell sie aus einem Satz
ableiten. Das ist eine neue Fehlerquelle, und sie wirkt direkt auf die
Metrik „Trefferquote" aus PRD Block 8.

Drei Entscheidungen prägen den Prompt:

**Das Modell liest die Anfrage zurück.** Es füllt einen Block `verstanden`
mit der erkannten Patientenzahl und den Kernkriterien. Das dient drei
Zwecken auf einmal: Der Nutzer sieht, was ankam (US-1 AC3), der Code kann
die Zahl gegen die tatsächlich gelieferten Patienten prüfen, und die
Trefferquote wird überhaupt erst messbar. Ohne diesen Block müsste man aus
den Ausgabedaten rückwärts raten, was gemeint war.

**Kein erzwungenes JSON-Schema.** Der Prompt fordert reinen Text. Ein
serverseitig erzwungenes Format würde die Fehlerkategorie „Antwort ist kein
gültiges JSON" verdecken — die Phase 0 hat sie als eigene Kategorie geführt,
und das bleibt so.

**Anweisungen auf Englisch, Inhalt auf Deutsch.** Die Prompt-Anweisungen
sind englisch, weil das im Spike verlässlich funktioniert hat. Die
Beschreibung des Nutzers geht wörtlich und unübersetzt hinein, und die
geforderten Inhalte sind ausdrücklich deutsch — Namen, Demografie,
Anzeigetexte.
"""

from __future__ import annotations

from .domain.codes import (
    condition_catalog_text,
    encounter_catalog_text,
    medication_catalog_text,
    observation_catalog_text,
)

# Obergrenze laut PRD Block 4: kleine Kohorten von 1 bis 25 Patienten.
MAX_PATIENTEN = 25

SYSTEM = """You plan SYNTHETIC clinical test data for software testing.
The data is fictional and must never describe a real person.

You do NOT produce FHIR. You produce a plain parameter object that a
downstream program turns into FHIR.

Hard output rules:
- Reply with ONE JSON object and nothing else.
- No prose, no explanation, no markdown code fences.
- Use only codes from the catalogues given to you. Never invent a code.
- Every numeric value must be a JSON number, every date a "YYYY-MM-DD" string.

Localisation (this matters, it is a core product requirement):
- Names must be plausible GERMAN names, both given and family names.
- Birth dates must fit the ages implied by the request.
"""

USER = """REQUEST FROM THE USER, verbatim — it may be German or English:
\"\"\"
{beschreibung}
\"\"\"

Read the request and decide yourself how many patients it asks for and
what the clinical picture should be. If the request does not say how many
patients, choose a small sensible number.
Never exceed {max_patienten} patients.

REQUIRED JSON SHAPE (exactly these keys, no extras):
{{
  "verstanden": {{
    "anzahl_patienten": <number>,
    "kernkriterien": ["short phrase", "short phrase"],
    "nicht_abbildbar": ["criterion the catalogues cannot express"]
  }},
  "patienten": [
    {{
      "vorname": "string",
      "nachname": "string",
      "geschlecht": "male" | "female" | "other" | "unknown",
      "geburtsdatum": "YYYY-MM-DD",
      "diagnosen": [
        {{ "code": "<code from the diagnosis catalogue>", "beginn": "YYYY-MM-DD" }}
      ],
      "messwerte": [
        {{ "code": "<code from the measurement catalogue>",
           "wert": <number>,
           "datum": "YYYY-MM-DD" }}
      ],
      "begegnungen": [
        {{ "art": "<code from the encounter catalogue>", "datum": "YYYY-MM-DD" }}
      ],
      "medikamente": [
        {{ "code": "<ATC code from the medication catalogue>",
           "beginn": "YYYY-MM-DD" }}
      ]
    }}
  ]
}}

"begegnungen" and "medikamente" are optional: include them when the request
asks for encounters or medication, or when they make the record plausible.
Zero, one or a few per patient are all fine. Only pick a medication whose
listed indication matches one of that patient's diagnoses — the catalogue
says which drug goes with which condition, and that judgement is not yours
to make.

"verstanden" is your read-back of the request: how many patients you took
from it, and the key criteria you recognised, each as a short phrase in the
language of the request. Be honest here — if the request was vague, say what
you assumed.

"nicht_abbildbar" is the most important field for the user's trust. List
every criterion you could NOT express with the catalogues below — a
measurement that has no LOINC code in the list, a diagnosis with no entry, a
detail the parameter shape cannot carry. Naming a gap is never a failure on
your part; silently substituting something else and saying nothing is. Leave
the list empty only if you really covered everything that was asked for.

Every patient needs at least one diagnosis and at least one measurement.

DIAGNOSIS CATALOGUE (SNOMED CT) — choose only from this list:
{diagnose_katalog}

MEASUREMENT CATALOGUE (LOINC) — choose only from this list:
{messwert_katalog}

MEDICATION CATALOGUE (ATC) — choose only from this list. The indication
after "bei:" tells you which diagnoses the drug fits; do not pair a drug
with a diagnosis that is not listed for it:
{medikament_katalog}

ENCOUNTER CATALOGUE — choose only from this list:
{begegnung_katalog}

Do not send units or display names: the downstream program takes them from
the catalogue. Send only the code, the numeric value and the date.
Values must sit inside the plausible range shown for the chosen code and
must fit the patient's age and diagnoses.

Return the JSON object now."""


def baue_prompt(beschreibung: str, max_patienten: int = MAX_PATIENTEN) -> tuple[str, str]:
    """(System-Prompt, Benutzer-Prompt) für eine Freitextbeschreibung."""
    return SYSTEM, USER.format(
        beschreibung=beschreibung.strip(),
        max_patienten=max_patienten,
        diagnose_katalog=condition_catalog_text(),
        messwert_katalog=observation_catalog_text(),
        medikament_katalog=medication_catalog_text(),
        begegnung_katalog=encounter_catalog_text(),
    )


# --- Stückweise Erzeugung großer Kohorten (Phase 2) ------------------------

TEIL_HINWEIS = """

DIESER AUFRUF IST TEIL {teil} VON {gesamt} EINER GRÖSSEREN KOHORTE.
Erzeuge genau {anzahl} Patienten für diesen Teil — nicht mehr, nicht weniger.
Die Patienten dieses Teils müssen sich von denen der übrigen Teile
unterscheiden: andere Namen, andere Geburtsjahre, andere Wertelagen. Wähle
Vor- und Nachnamen, die in den anderen Teilen unwahrscheinlich sind, und
verteile die Geburtsjahre über den vom Auftrag erlaubten Bereich."""


def baue_teil_prompt(
    beschreibung: str, anzahl: int, teil: int, gesamt: int
) -> tuple[str, str]:
    """Prompt für einen Teil einer großen Kohorte.

    Der Zusatz ist nötig, weil sonst jeder Teil dieselbe Handvoll Namen und
    Geburtsjahre liefert: Das Modell sieht die anderen Teile nicht und
    greift ohne Hinweis auf seine wahrscheinlichsten Vorschläge zurück. Für
    Testdaten wäre eine Kohorte aus 200-mal derselben Anna Müller wertlos.

    Echte Sperren gegen Wiederholung sind das nicht — der Hinweis kann nur
    streuen, nicht garantieren. Wie gut es wirkt, misst
    `Kohortenergebnis.namensvielfalt`.
    """
    system, benutzer = baue_prompt(beschreibung, max_patienten=anzahl)
    zusatz = TEIL_HINWEIS.format(teil=teil, gesamt=gesamt, anzahl=anzahl)
    return system, benutzer.replace(
        "Return the JSON object now.", zusatz.strip() + "\n\nReturn the JSON object now."
    )
