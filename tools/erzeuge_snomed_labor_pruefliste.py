"""Erzeugt die Prüfliste der SNOMED-Codes für Laborwerte.

    python tools/erzeuge_snomed_labor_pruefliste.py

ISiK Labor verlangt neben der LOINC-Kodierung eine zweite in SNOMED. Für
sechs Messwerte nennt die Spezifikation den Code selbst; die übrigen 14
waren eine **eigene klinische Wahl** und sind seit ADR-021 getroffen — je
Wert am Terminologieserver belegt (existiert, aktiv, Messverfahren) und
vom Menschen freigegeben. Dieses Werkzeug trennt im Bericht beide Gruppen
und findet weiterhin Kandidaten für jeden künftig hinzukommenden Wert, der
noch keinen SNOMED-Code führt.

Der Katalog ist in diesem Projekt sicherheitskritisch: Die
Laufzeitprüfung sieht Codes nicht, und ein falscher Code erzeugt
unbemerkt inhaltlich falsche Testdaten. Deshalb wird ein Code nie
maschinell eingetragen, sondern eine Liste erzeugt, die ein Mensch
durchgeht — genau wie bei den ICD-Schlüsseln (`docs/icd-pruefliste.md`).

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


# Die sechs Codes, die die Spezifikation selbst als `patternCoding` nennt,
# mit dem Suffix ihres spezifischen Profils. Alles Übrige ist gewählt.
SPEZIFIKATION = {"718-7": "Hb", "777-3": "Thrombozyten", "2160-0": "Serumkreatinin",
                 "98979-8": "GFR", "1988-5": "CRP", "3016-3": "TSH"}


def main() -> int:
    o = KATALOGE["observations"]
    labor = [e for e in o.values() if not e.vital_sign]
    aus_spec = sorted((e for e in labor if e.snomed and e.code in SPEZIFIKATION),
                      key=lambda x: x.code)
    gewaehlt = sorted((e for e in labor if e.snomed and e.code not in SPEZIFIKATION),
                      key=lambda x: x.code)
    offen = sorted((e for e in labor if not e.snomed), key=lambda x: x.code)

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
        f"Von {len(labor)} Laborwerten sind **{len(aus_spec)}** aus der",
        f"Spezifikation übernommen, **{len(gewaehlt)}** gewählt und belegt",
        f"(ADR-021) und **{len(offen)}** offen.",
        "",
        "---",
        "",
        "## Aus der Spezifikation selbst",
        "",
        "Diese Codes stehen als `patternCoding` in den Profilen von",
        "ISiK Labor. Sie sind nicht gewählt, sondern übernommen.",
        "",
        "| LOINC | Messwert | SNOMED | Bezeichnung | Profil |",
        "|---|---|---|---|---|",
    ]
    for e in aus_spec:
        zeilen.append(
            f"| `{e.code}` | {e.display_de} | `{e.snomed}` | {e.snomed_display} "
            f"| ISiKLaboruntersuchung{SPEZIFIKATION.get(e.code, '?')} |"
        )

    zeilen += [
        "",
        "---",
        "",
        "## Gewählt und am Terminologieserver belegt (ADR-021)",
        "",
        "Für diese 14 nennt die Spezifikation keinen Code. Je Wert wurde ein",
        "SNOMED-Messverfahren gewählt, das den Analyten im vom LOINC genannten",
        "Material trifft, am Terminologieserver bestätigt (existiert, aktiv,",
        "`is-a 122869004`) und vom Menschen freigegeben. Sie tragen das",
        "allgemeine Profil ISiKLaboruntersuchung.",
        "",
        "| LOINC | Messwert | SNOMED | Bezeichnung |",
        "|---|---|---|---|",
    ]
    for e in gewaehlt:
        zeilen.append(
            f"| `{e.code}` | {e.display_de} | `{e.snomed}` | {e.snomed_display} |"
        )

    if not offen:
        zeilen += [
            "",
            "---",
            "",
            "## Offen",
            "",
            "Keine — alle Laborwerte des Katalogs führen einen SNOMED-Code.",
            "Kommt ein neuer Wert ohne Code hinzu, listet dieses Werkzeug",
            "wieder Kandidaten für ihn.",
            "",
        ]
        ziel = Path(__file__).resolve().parent.parent / "docs" / "snomed-labor-pruefliste.md"
        ziel.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
        print(f"\nGeschrieben: {ziel}")
        return 0

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
    for e in offen:
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
