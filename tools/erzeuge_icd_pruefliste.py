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
    "# Prüfliste: ICD-10-GM-Schlüssel",
    "",
    "> **Diese Liste ist vor der Veröffentlichung abzuarbeiten.**",
    "",
    f"Der Katalog führt **{gesamt} Diagnosen**, davon **{mit} mit ICD-10-GM-Schlüssel**.",
    "Die Schlüssel sind ein Entwurf und **nicht gegen den amtlichen Katalog geprüft**.",
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
    "## Zu prüfen",
    "",
    "| ✓ | ICD-10-GM | Bezeichnung laut Katalog | SNOMED CT | deutscher Anzeigetext |",
    "|---|---|---|---|---|",
]
for c in CONDITION_CODES.values():
    if c.hat_icd:
        zeilen.append(f"| ☐ | `{c.icd10gm}` | {c.icd10gm_display} | `{c.code}` | {c.display_de} |")

ohne = [c for c in CONDITION_CODES.values() if not c.hat_icd]
zeilen += [
    "",
    "## Bewusst ohne Schlüssel",
    "",
    "Hier war die von ICD-10-GM geforderte fünfte Stelle nicht zweifelsfrei",
    "bestimmbar. Ein geratener Schlüssel wäre schlechter als gar keiner; die",
    "Vorlage baut ohne ihn weiterhin gültiges FHIR mit SNOMED allein.",
    "Ergänzen ist jederzeit möglich.",
    "",
    "| SNOMED CT | Anzeigetext | offene Frage |",
    "|---|---|---|",
]
offen = {
    "414916001": "E66.- verlangt eine BMI-Klasse an fünfter Stelle",
    "396275006": "M19.9- verlangt eine Lokalisationsangabe",
    "69896004": "M06.9- verlangt eine Lokalisationsangabe",
    "64859006": "M81.9- verlangt eine Lokalisationsangabe",
}
for c in ohne:
    zeilen.append(f"| `{c.code}` | {c.display_de} | {offen.get(c.code, 'noch zu klären')} |")

zeilen += [
    "",
    "## Nach der Prüfung",
    "",
    "Korrekturen gehören in `src/synthfhir/domain/codes.py`, Abschnitt",
    "`CONDITION_CODES`. Danach:",
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
