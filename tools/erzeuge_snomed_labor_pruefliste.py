"""Erzeugt die Prüfliste der SNOMED-Codes für Laborwerte.

    python tools/erzeuge_snomed_labor_pruefliste.py

ISiK Labor verlangt neben der LOINC-Kodierung eine zweite in SNOMED. Für
sechs Messwerte nennt die Spezifikation den Code selbst; sie stehen im
Katalog. Für die übrigen wäre er eine **eigene klinische Wahl**.

Der Katalog ist in diesem Projekt sicherheitskritisch: Die
Laufzeitprüfung sieht Codes nicht, und ein falscher Code erzeugt
unbemerkt inhaltlich falsche Testdaten. Deshalb wird hier nichts
eingetragen, sondern eine Liste erzeugt, die ein Mensch durchgeht —
genau wie bei den ICD-Schlüsseln (`docs/icd-pruefliste.md`).

**Was die Maschine beiträgt und was nicht.** Die Kandidaten kommen aus
SNOMED selbst: eine Expansion über `is-a 122869004` (Measurement
procedure) mit Textfilter gegen tx.fhir.org. Damit ist sicher, dass jeder
Vorschlag existiert und ein Messverfahren ist. Ob er **den richtigen
Analyten im richtigen Material** meint, entscheidet die Maschine nicht —
'Glucose measurement, serum' und 'Glucose measurement, urine' sind beide
gültig und nur einer ist gemeint.
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from synthfhir.domain.codes import KATALOGE  # noqa: E402
from synthfhir.terminologie import SERVER  # noqa: E402

TX = SERVER["org"]
MESSVERFAHREN = "122869004"   # SNOMED: Measurement procedure

# Suchbegriffe je Messwert. Sie stehen hier und nicht im Katalog, weil sie
# nur der Suche dienen und keine Aussage über die Daten sind. Abgeleitet
# aus dem englischen LOINC-Namen, gekürzt auf das, was SNOMED findet.
BEGRIFFE = {
    "789-8": "red blood cell count",
    "6690-2": "white blood cell count",
    "2345-7": "glucose measurement serum",
    "4548-4": "hemoglobin A1c",
    "3094-0": "urea nitrogen",
    "2951-2": "sodium measurement",
    "2823-3": "potassium measurement",
    "2075-0": "chloride measurement",
    "2093-3": "cholesterol measurement",
    "2085-9": "high density lipoprotein",
    "2571-8": "triglyceride measurement",
    "1742-6": "alanine aminotransferase",
    "1920-8": "aspartate aminotransferase",
    "1975-2": "bilirubin total",
}


def kandidaten(begriff: str, anzahl: int = 5) -> list[tuple[str, str]]:
    vs = {
        "resourceType": "ValueSet", "status": "active",
        "url": "http://example.org/vs/labor-suche",
        "compose": {"include": [{
            "system": "http://snomed.info/sct",
            "filter": [{"property": "concept", "op": "is-a", "value": MESSVERFAHREN}],
        }]},
    }
    antwort = requests.post(
        f"{TX}/ValueSet/$expand",
        json={"resourceType": "Parameters", "parameter": [
            {"name": "valueSet", "resource": vs},
            {"name": "filter", "valueString": begriff},
            {"name": "count", "valueInteger": anzahl},
        ]},
        headers={"Accept": "application/fhir+json"}, timeout=180,
    )
    d = antwort.json()
    if d.get("resourceType") != "ValueSet":
        return []
    return [(c["code"], c.get("display", ""))
            for c in d.get("expansion", {}).get("contains", [])]


def main() -> int:
    o = KATALOGE["observations"]
    labor = [e for e in o.values() if not e.vital_sign]
    fertig = [e for e in labor if e.snomed]
    offen = [e for e in labor if not e.snomed]

    zeilen = [
        "# Prüfliste: SNOMED-Codes für Laborwerte",
        "",
        "**Erzeugt von `tools/erzeuge_snomed_labor_pruefliste.py`.** Nicht von",
        "Hand pflegen — neu erzeugen.",
        "",
        "ISiK Labor verlangt neben LOINC eine zweite Kodierung in SNOMED",
        "(`Observation.code.coding:snomed`, `min=1`). Der Slice ist an **kein**",
        "ValueSet gebunden: Jeder gültige SNOMED-Code erfüllt die Struktur.",
        "Die klinische Richtigkeit prüft also niemand ausser einem Menschen.",
        "",
        f"Von {len(labor)} Laborwerten sind **{len(fertig)}** versorgt und",
        f"**{len(offen)}** offen.",
        "",
        "---",
        "",
        "## Versorgt: aus der Spezifikation selbst",
        "",
        "Diese Codes stehen als `patternCoding` in den Profilen von",
        "ISiK Labor. Sie sind nicht gewählt, sondern übernommen.",
        "",
        "| LOINC | Messwert | SNOMED | Bezeichnung | Profil |",
        "|---|---|---|---|---|",
    ]
    profil = {"718-7": "Hb", "777-3": "Thrombozyten", "2160-0": "Serumkreatinin",
              "33914-3": "GFR", "1988-5": "CRP", "3016-3": "TSH"}
    for e in sorted(fertig, key=lambda x: x.code):
        zeilen.append(
            f"| `{e.code}` | {e.display_de} | `{e.snomed}` | {e.snomed_display} "
            f"| ISiKLaboruntersuchung{profil.get(e.code, '?')} |"
        )

    zeilen += [
        "",
        "---",
        "",
        "## Offen: Kandidaten aus SNOMED, noch nicht gewählt",
        "",
        "Die Kandidaten stammen aus einer Expansion über `is-a 122869004`",
        "(Measurement procedure) mit Textfilter, gegen tx.fhir.org. Damit ist",
        "belegt: Jeder existiert und ist ein Messverfahren.",
        "",
        "**Was damit nicht belegt ist:** ob er den richtigen Analyten im",
        "richtigen Material meint. 'Glucose measurement, serum' und",
        "'Glucose measurement, urine' sind beide gueltige Messverfahren,",
        "und nur eines ist gemeint. Das entscheidet ein Mensch.",
        "",
        "Zum Eintragen: `snomed=` und `snomed_display=` beim jeweiligen",
        "`ObservationCode` in `src/synthfhir/domain/codes.py`.",
        "",
    ]
    for e in sorted(offen, key=lambda x: x.code):
        begriff = BEGRIFFE.get(e.code)
        zeilen.append(f"### `{e.code}` — {e.display_de}")
        zeilen.append("")
        zeilen.append(f"LOINC: {e.display_loinc_de or e.display}")
        zeilen.append("")
        if not begriff:
            zeilen.append("_Kein Suchbegriff hinterlegt._")
            zeilen.append("")
            continue
        treffer = kandidaten(begriff)
        print(f"  {e.code:<9} {len(treffer)} Kandidat(en)", flush=True)
        if not treffer:
            zeilen.append(f"_Suche nach '{begriff}' ergab nichts._")
        else:
            zeilen.append("| SNOMED | Bezeichnung |")
            zeilen.append("|---|---|")
            for code, disp in treffer:
                zeilen.append(f"| `{code}` | {disp} |")
        zeilen.append("")

    ziel = Path(__file__).resolve().parent.parent / "docs" / "snomed-labor-pruefliste.md"
    ziel.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    print(f"\nGeschrieben: {ziel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
