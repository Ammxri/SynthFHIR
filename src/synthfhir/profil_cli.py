"""Kommandozeile für die Profilmessung (Phase 3).

    synthfhir-profil --server http://localhost:8090/fhir -o bericht.json

Ein eigener Befehl und kein Schalter an `synthfhir`: Die Messung braucht
kein Sprachmodell, kein Kontingent und keine Beschreibung — sie braucht
einen Profilserver. Das ist eine andere Aufgabe mit anderen Voraussetzungen.

Der Rückgabewert sagt, ob **Fehler** gefunden wurden — nicht, ob
Konformität nachgewiesen ist. Diese beiden Aussagen sind nicht dasselbe,
solange Befunde ungeprüft bleiben, und der Bericht hält sie getrennt.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .profil import ProfilFehler, Profilbericht, pruefe_gegen_profile
from .referenzkohorte import baue

STANDARD_SERVER = "http://localhost:8090/fhir"


def baue_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="synthfhir-profil",
        description=(
            "Misst, wie weit die erzeugten Testdaten von den ISiK-Profilen "
            "entfernt sind. Ändert nichts an der Erzeugung."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Der Profilserver muss die ISiK-Pakete geladen haben:\n"
            "  docker compose -f docs/belege/docker-compose.isik.yml up -d\n"
        ),
    )
    p.add_argument("--server", default=STANDARD_SERVER,
                   help=f"FHIR-Server mit geladenen ISiK-Profilen "
                        f"(Standard: {STANDARD_SERVER}).")
    p.add_argument("-o", "--ausgabe", type=Path,
                   help="Zieldatei für den Bericht als JSON.")
    p.add_argument("--still", action="store_true",
                   help="Keine Tabelle auf stderr ausgeben.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = baue_parser().parse_args(argv)

    try:
        bericht = pruefe_gegen_profile(baue(), args.server)
    except ProfilFehler as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        print("  Läuft der Profilserver?  docker compose -f "
              "docs/belege/docker-compose.isik.yml up -d", file=sys.stderr)
        return 2

    if not args.still:
        print(_tabelle(bericht), file=sys.stderr)

    text = json.dumps(bericht.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if args.ausgabe:
        args.ausgabe.parent.mkdir(parents=True, exist_ok=True)
        args.ausgabe.write_text(text, encoding="utf-8")
        if not args.still:
            print(f"\nBericht: {args.ausgabe}", file=sys.stderr)
    else:
        print(text)

    return 1 if bericht.summe("fehler") else 0


def _tabelle(b: Profilbericht) -> str:
    zeilen = [
        "",
        f"Profilmessung gegen {b.paket} {b.paketversion}",
        f"  Server:            {b.server} (FHIR {b.fhir_version})",
        f"  Terminologieserver: {b.terminologieserver}",
        "",
        f"  {'Typ':<22}{'geprüft':>9}{'Fehler':>9}{'ungeprüft':>11}{'Warnungen':>11}",
        f"  {'-' * 62}",
    ]
    for typ, z in sorted(b.je_typ.items()):
        zeilen.append(
            f"  {typ:<22}{z['geprueft']:>9}{z['fehler']:>9}"
            f"{z['ungeprueft']:>11}{z['warnungen']:>11}"
        )
    zeilen.append(
        f"  {'SUMME':<22}{len(b.ergebnisse):>9}{b.summe('fehler'):>9}"
        f"{b.summe('ungeprueft'):>11}{b.summe('warnungen'):>11}"
    )
    for h in b.hinweise:
        zeilen.append(f"\n  Hinweis: {h}")
    zeilen.append(
        "\n  'ungeprüft' heißt: Der Validator konnte es nicht entscheiden —\n"
        "  nicht, dass es richtig ist. Ohne Terminologieserver bleibt jede\n"
        "  Bindung an SNOMED, LOINC, ICD-10-GM und ATC in dieser Spalte."
    )
    return "\n".join(zeilen)


if __name__ == "__main__":
    raise SystemExit(main())
