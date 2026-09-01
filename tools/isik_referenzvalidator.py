"""Misst die Referenzkohorte mit dem offiziellen HL7-Validator.

    python tools/isik_referenzvalidator.py

Der Unterschied zu `synthfhir-profil` ist das **Messgerät**. Dort urteilt
ein HAPI-Server, hier der Validator, den HL7 selbst veröffentlicht und den
der Referenzvalidator der gematik als Maßstab nennt. Für die Frage „ist
das konform" ist das kein gradueller, sondern ein kategorialer
Unterschied.

===========================================================================
WARUM DAS EIN WERKZEUG IST UND KEIN TEST
===========================================================================

Der Validator ist eine 191-MiB-Datei, die HL7 verteilt. Sie gehört nicht
ins Repository (`werkzeuge/` ist ignoriert), und die Messung braucht drei
bis vier Minuten und einen fremden Terminologieserver ohne
Betriebszusage. Beides schließt den Commit-Pfad aus.

Eingecheckt wird deshalb nur der **Bericht** unter `docs/belege/`. Wer ihn
nachrechnen will, holt sich den Validator und ruft dieses Werkzeug auf.

===========================================================================
ZWEI EINSTELLUNGEN, DIE ÜBER DAS ERGEBNIS ENTSCHEIDEN
===========================================================================

**`-sct intl`.** Ohne sie fragt der Validator die SNOMED-Fassung `null` an,
und ein Server, der nur versionierte Editionen führt, antwortet „kenne ich
nicht". Gemessen war das der Unterschied zwischen *1 Fehler, 5 Warnungen*
und *0 Fehlern, 3 Warnungen* — bei identischer Eingabe.

**Ein eigener `-txCache` je Server.** Der Validator legt seinen
Terminologie-Zwischenspeicher sonst unter einem festen Pfad ab und benutzt
beim zweiten Lauf die Antworten des ersten. Nachgemessen lieferten zwei
Läufe gegen **verschiedene** Server byteweise dasselbe Ergebnis,
einschließlich der Editionsnummern des jeweils anderen — ein Vergleich,
der keiner war.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from synthfhir.profil import MODULE, profil_fuer  # noqa: E402
from synthfhir.referenzkohorte import baue  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
VALIDATOR = WURZEL / "werkzeuge" / "validator_cli.jar"
ARBEIT = WURZEL / "messlauf"
FHIR_VERSION = "4.0.1"
# Alle Module, die Profile beisteuern. Seit ADR-014 sind es drei: Das
# Basismodul kennt Observation und MedicationStatement nicht.
ISIK_PAKETE = [f"{name}#{fassung}" for name, fassung in MODULE.items()]
TX = "https://tx.fhir.org/r4"


def schreibe_kohorte(ziel: Path) -> dict[str, list[Path]]:
    """Legt die Referenzkohorte ab, gruppiert nach **Profil**.

    Nach Profil und nicht nach Typ: Seit ADR-014 tragen zwei Observations
    desselben Typs verschiedene Profile — ein Vitalparameter eines, ein
    Laborwert gar keines. Wer nach Typ gruppiert, misst das Panel gegen
    das falsche Profil oder gar nicht.
    """
    ziel.mkdir(parents=True, exist_ok=True)
    for alt in ziel.glob("*.json"):
        alt.unlink()
    nach_profil: dict[str, list[Path]] = {}
    for r in baue():
        profil = profil_fuer(r)
        if profil is None:
            continue
        pfad = ziel / f"{r['resourceType']}-{r['id']}.json"
        pfad.write_text(
            json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        nach_profil.setdefault(profil, []).append(pfad)
    return nach_profil


def _befunde(datei: Path) -> list[dict]:
    """Die Einzelbefunde, egal ob der Validator ein OperationOutcome oder
    ein Bundle daraus geschrieben hat."""
    d = json.loads(datei.read_text(encoding="utf-8"))
    if d.get("resourceType") == "OperationOutcome":
        return d.get("issue", [])
    return [i for e in d.get("entry", []) for i in e["resource"].get("issue", [])]


def _text(befund: dict) -> str:
    return (befund.get("details") or {}).get("text") or befund.get("diagnostics", "")


def messe(tx: str = TX, sct: str = "intl") -> dict:
    if not VALIDATOR.exists():
        raise SystemExit(
            f"Der Validator fehlt: {VALIDATOR}\n"
            "  Holen von https://github.com/hapifhir/org.hl7.fhir.core/releases\n"
            "  (validator_cli.jar, rund 191 MiB). Er gehört nicht ins Repository."
        )
    if not shutil.which("java"):
        raise SystemExit("Java fehlt im Pfad. Der Validator braucht Java 17 oder neuer.")

    nach_profil = schreibe_kohorte(ARBEIT)
    # Eigener Zwischenspeicher je Server — sonst antwortet beim zweiten
    # Lauf der erste Server.
    cache = ARBEIT / f"txcache-{tx.replace('://', '-').replace('/', '-')}"

    bericht: dict = {
        "werkzeug": "org.hl7.fhir.core validator_cli",
        "pakete": ISIK_PAKETE,
        "fhir_version": FHIR_VERSION,
        "terminologieserver": tx,
        "snomed_edition": sct,
        "je_typ": {},
        "warnungen_gezaehlt": {},
    }
    alle_texte: Counter = Counter()

    for profil, dateien in sorted(nach_profil.items()):
        kurz = profil.rsplit("/", 1)[-1]
        ausgabe = ARBEIT / f"ref-{kurz}.json"
        pakete = []
        for paket in ISIK_PAKETE:
            pakete += ["-ig", paket]
        befehl = [
            "java", "-jar", str(VALIDATOR),
            *[str(p) for p in dateien],
            "-version", FHIR_VERSION,
            *pakete,
            "-profile", profil,
            "-tx", tx,
            "-sct", sct,
            "-txCache", str(cache),
            "-output", str(ausgabe),
        ]
        print(f"  {kurz} ({len(dateien)}) …", flush=True)
        lauf = subprocess.run(befehl, capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
        if not ausgabe.exists():
            raise SystemExit(
                f"Der Validator hat für {kurz} nichts geschrieben.\n{lauf.stdout[-1500:]}"
            )
        befunde = _befunde(ausgabe)
        fehler = [b for b in befunde if b["severity"] == "error"]
        warnungen = [b for b in befunde if b["severity"] == "warning"]
        bericht["je_typ"][kurz] = {
            "geprueft": len(dateien),
            "profil": profil,
            "fehler": len(fehler),
            "warnungen": len(warnungen),
            "fehlertexte": [
                {"ort": (b.get("expression") or ["?"])[0], "meldung": _text(b)}
                for b in fehler
            ],
        }
        for b in warnungen:
            alle_texte[_text(b)[:120]] += 1

    bericht["warnungen_gezaehlt"] = dict(alle_texte.most_common())
    bericht["summe"] = {
        "geprueft": sum(z["geprueft"] for z in bericht["je_typ"].values()),
        "fehler": sum(z["fehler"] for z in bericht["je_typ"].values()),
        "warnungen": sum(z["warnungen"] for z in bericht["je_typ"].values()),
    }
    # Es gibt hier keine dritte Spalte mehr, und das ist der Punkt: Der
    # Validator konnte mit Terminologie entscheiden. Damit das nicht
    # stillschweigend behauptet wird, wird ausdrücklich gesucht.
    bericht["ungepruefte_meldungen"] = [
        t for t in alle_texte
        if "Unable to check whether the code is in the value set" in t
        or "cannot apply filters" in t
    ]
    return bericht


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--tx", default=TX, help=f"Terminologieserver (Standard: {TX}).")
    p.add_argument("--sct", default="intl", help="SNOMED-Edition (Standard: intl).")
    p.add_argument("-o", "--ausgabe", type=Path,
                   default=WURZEL / "docs" / "belege" / "isik-referenzvalidator.json")
    args = p.parse_args(argv)

    print("Referenzvalidator gegen " + ", ".join(ISIK_PAKETE))
    print(f"Terminologie {args.tx} ({args.sct})")
    bericht = messe(args.tx, args.sct)

    s = bericht["summe"]
    print(f"\n  {'Profil':<38}{'geprüft':>9}{'Fehler':>9}{'Warn.':>8}")
    print(f"  {'-' * 63}")
    for name, zeile in sorted(bericht["je_typ"].items()):
        print(f"  {name:<38}{zeile['geprueft']:>9}{zeile['fehler']:>9}{zeile['warnungen']:>8}")
    print(f"  {'SUMME':<38}{s['geprueft']:>9}{s['fehler']:>9}{s['warnungen']:>8}")

    if bericht["ungepruefte_meldungen"]:
        print("\n  ACHTUNG — Befunde blieben ungeprüft:")
        for t in bericht["ungepruefte_meldungen"]:
            print(f"    {t}")
    else:
        print("\n  Keine ungeprüften Befunde: Die Terminologie hat entschieden.")

    print("\n  Warnungen nach Art:")
    for t, n in bericht["warnungen_gezaehlt"].items():
        print(f"    {n:>2}x  {t}")

    args.ausgabe.parent.mkdir(parents=True, exist_ok=True)
    args.ausgabe.write_text(
        json.dumps(bericht, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n  Bericht: {args.ausgabe}")
    return 1 if s["fehler"] or bericht["ungepruefte_meldungen"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
