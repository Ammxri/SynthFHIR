"""Erzeugt die Prüfliste der ICD-10-GM-Schlüssel aus dem Katalog.

Bewusst generiert statt handgeschrieben: So kann sie nach jeder
Katalogänderung neu erzeugt werden und läuft nicht aus dem Takt.
"""
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from synthfhir.domain.codes import CONDITION_CODES, icd_abdeckung

mit, gesamt = icd_abdeckung()
zeilen = [
    "# ICD-10-GM-Schlüssel: Nachweis der Prüfung",
    "",
    "> **Geprüft am 2026-08-28** gegen den amtlichen Katalog des BfArM,",
    "> ICD-10-GM Version 2026.",
    "",
    f"Der Katalog führt **{gesamt} Diagnosen**, alle **{mit} mit ICD-10-GM-Schlüssel**.",
    "",
    "## Ergebnis der Prüfung",
    "",
    "| | |",
    "|---|---|",
    "| Schlüssel korrekt | 19 |",
    "| **nicht kodierbar, korrigiert** | **2** |",
    "| zuvor leer, jetzt gefüllt | 4 |",
    "",
    "Die beiden Fehler waren `J45.9` (Asthma) und `B18.1` (Hepatitis B). Beide",
    "sind in ICD-10-GM nur Kategorieüberschriften: Ohne fünfte Stelle sind sie",
    "kein gültiger Schlüssel. Korrigiert zu `J45.99` und `B18.19`.",
    "",
    "Bemerkenswert daran: **Keine Prüfung im Projekt hätte sie gefunden.** Der",
    "Formattest akzeptiert `J45.9` als wohlgeformt, und HAPI kennt das",
    "CodeSystem nicht. Nur der Abgleich mit der Primärquelle deckt so etwas auf.",
    "",
    "## Warum das von Hand geschehen muss",
    "",
    "Der CI-Test validiert jeden Katalogeintrag gegen HAPI FHIR. Das sichert",
    "**UCUM-Einheiten, Struktur und Invarianten** ab — dort hat es in Phase 0",
    "auch tatsächlich Fehler gefunden. Es sichert **Codes nicht** ab: Dem",
    "Container fehlen die Terminologiepakete, ein unbekanntes CodeSystem ergibt",
    "höchstens eine Warnung. Ein falsch abgetippter ICD-Schlüssel sieht für ihn",
    "genauso aus wie ein richtiger.",
    "",
    "Ein Formattest in `tests/test_domaene.py` fängt Tippfehler der Bauart",
    "`E1190` statt `E11.90`. Mehr kann Automatik hier nicht leisten.",
    "",
    "## Quelle",
    "",
    "Amtlicher ICD-10-GM-Katalog des BfArM, frei einsehbar:",
    "<https://klassifikationen.bfarm.de/icd-10-gm/kode-suche/htmlgm2026/>",
    "",
    "Besonders zu prüfen ist die **fünfte Stelle**. ICD-10-GM verlangt sie an",
    "vielen Stellen, wo ICD-10-WHO mit vier Zeichen auskommt — bei Diabetes",
    "(E10–E14) und der Hypertonie (I10) etwa. Ein vierstelliger Schlüssel ist",
    "dort nicht kodierbar.",
    "",
    "## Geprüfte Schlüssel",
    "",
    "| ICD-10-GM | Bezeichnung laut Katalog | SNOMED CT | deutscher Anzeigetext |",
    "|---|---|---|---|",
]
for c in CONDITION_CODES.values():
    if c.hat_icd:
        zeilen.append(f"| `{c.icd10gm}` | {c.icd10gm_display} | `{c.code}` | {c.display_de} |")

zeilen += [
    "",
    "## Wenn eine Diagnose hinzukommt",
    "",
    "Ihr ICD-Schlüssel ist an der Primärquelle zu prüfen, bevor er in",
    "`src/synthfhir/domain/codes.py` landet — besonders auf die fünfte Stelle.",
    "Ist sie nicht zweifelsfrei bestimmbar, bleibt `icd10gm=None`: Die Vorlage",
    "baut dann gültiges FHIR mit SNOMED allein. Danach:",
    "",
    "```bash",
    ".venv/Scripts/python.exe -m pytest tests -q",
    "```",
    "",
    "Und diese Liste neu erzeugen, damit sie zum Katalog passt.",
    "",
]
Path("docs/icd-pruefliste.md").write_text("\n".join(zeilen) + "\n", encoding="utf-8")
print(f"docs/icd-pruefliste.md erzeugt: {mit} zu prüfen, {gesamt - mit} bewusst offen")
