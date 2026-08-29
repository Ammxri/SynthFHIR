"""Kommandozeile für große Kohorten (Phase 2).

Warum nicht über die Weboberfläche: Ein Lauf über 200 Patienten dauert im
kostenlosen Kontingent mehrere Minuten und belegt so lange einen
Arbeitsprozess. Die Demo behält deshalb ihre Grenze von 25 Patienten; alles
darüber läuft hier, wo eine lange Laufzeit niemanden stört und der
Fortschritt sichtbar ist.

    synthfhir "80 Patientinnen mit Typ-2-Diabetes" --anzahl 80 -o kohorte.json

Der Rückgabewert ist Teil der Schnittstelle: 0 nur, wenn die Kohorte
vollständig und valide ist, 1 bei Lücken, 2 bei Abbruch. So lässt sich der
Befehl in einer Prüfkette verwenden, ohne die Ausgabe zu lesen.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .kohorte import TEILGROESSE, Kohortenergebnis, generiere_kohorte
from .llm import LLMFehler, client_aus_umgebung

HINWEIS = (
    "Synthetische Testdaten. Nicht für klinische Nutzung, "
    "keine echten Patientendaten."
)


def baue_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="synthfhir",
        description="Erzeugt validierte, deutsch lokalisierte FHIR-R4-Testdaten. " + HINWEIS,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Beispiele:\n"
            '  synthfhir "40 Patientinnen mit Asthma" -n 40 -o asthma.json\n'
            '  synthfhir "200 Diabetiker über 60" -n 200 --teilgroesse 20 --bericht b.json\n'
        ),
    )
    p.add_argument("beschreibung", help="Was erzeugt werden soll, in Alltagssprache.")
    p.add_argument("-n", "--anzahl", type=int, required=True,
                   help="Anzahl der Patienten.")
    p.add_argument("-o", "--ausgabe", type=Path,
                   help="Zieldatei für das Bundle (Standard: Ausgabe auf stdout).")
    p.add_argument("--teilgroesse", type=int, default=TEILGROESSE,
                   help=f"Patienten je LLM-Aufruf (Standard: {TEILGROESSE}).")
    p.add_argument("--versuche", type=int, default=2,
                   help="Versuche je Teil, bevor er als ausgefallen gilt (Standard: 2).")
    p.add_argument("--pause", type=float, default=0.0, metavar="SEKUNDEN",
                   help="Wartezeit zwischen den Teilen. Nötig bei knappem "
                        "Kontingent: Anbieter rechnen max_tokens in die "
                        "Anfragegröße ein, bei 8000 Token/Minute trägt das "
                        "etwa einen Teil pro Minute (--pause 60).")
    p.add_argument("--bericht", type=Path,
                   help="Zieldatei für die Messwerte des Laufs als JSON.")
    p.add_argument("--still", action="store_true",
                   help="Keinen Fortschritt auf stderr ausgeben.")
    return p


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = baue_parser().parse_args(argv)

    if args.anzahl < 1:
        print("Fehler: --anzahl muss mindestens 1 sein.", file=sys.stderr)
        return 2

    try:
        client = client_aus_umgebung()
    except LLMFehler as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2

    # Der Fortschritt geht auf stderr, damit `synthfhir ... > datei.json`
    # weiterhin eine saubere JSON-Datei ergibt.
    def melde(nummer: int, gesamt: int, stand: str) -> None:
        print(f"  Teil {nummer}/{gesamt}: {stand}", file=sys.stderr, flush=True)

    if not args.still:
        print(f"Erzeuge {args.anzahl} Patienten …", file=sys.stderr)

    try:
        ergebnis = generiere_kohorte(
            client,
            args.beschreibung,
            args.anzahl,
            teilgroesse=args.teilgroesse,
            versuche_je_teil=args.versuche,
            pause_s=args.pause,
            fortschritt=None if args.still else melde,
        )
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr)
        return 2

    if not args.still:
        print(_zusammenfassung(ergebnis), file=sys.stderr)

    if ergebnis.bundle is not None:
        text = json.dumps(ergebnis.bundle, ensure_ascii=False, indent=2)
        if args.ausgabe:
            args.ausgabe.write_text(text + "\n", encoding="utf-8")
            if not args.still:
                print(f"\nBundle: {args.ausgabe}", file=sys.stderr)
        else:
            print(text)

    if args.bericht:
        args.bericht.write_text(
            json.dumps(ergebnis.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if not args.still:
            print(f"Bericht: {args.bericht}", file=sys.stderr)

    if not ergebnis.ressourcen:
        return 2
    return 0 if ergebnis.fertig and ergebnis.mengentreue == 1.0 else 1


def _zusammenfassung(e: Kohortenergebnis) -> str:
    """Sagt auch, was fehlt — eine Lücke darf sich nicht verstecken."""
    zeilen = [
        "",
        f"  Patienten:      {e.patienten} von {e.angefragt} "
        f"(Mengentreue {e.mengentreue:.1%})",
        f"  Ressourcen:     {e.anzahl_je_typ}",
        f"  Namensvielfalt: {e.namensvielfalt:.1%}",
        f"  Token:          {e.eingabe_token} ein / {e.ausgabe_token} aus",
    ]
    if e.integritaet:
        zeilen.append(
            f"  Integrität:     {'ok' if e.integritaet.ok else 'FEHLER'} "
            f"({e.integritaet.broken_reference_count} kaputte Referenzen)"
        )
    ungueltig = [p for p in e.validierung if not p.valide]
    if ungueltig:
        zeilen.append(f"  UNGÜLTIG:       {len(ungueltig)} Ressourcen")
    for teil in e.teile:
        if not teil.erfolgreich:
            zeilen.append(f"  Teil {teil.nummer} ausgefallen: {teil.fehler}")
    if e.erfundene_codes:
        zeilen.append(
            f"  Verworfen:      {e.erfundene_codes} erfundene Codes "
            "(nicht im Katalog)"
        )
    for luecke in e.nicht_abbildbar:
        zeilen.append(f"  Nicht abbildbar: {luecke}")
    zeilen.append(f"\n  {HINWEIS}")
    return "\n".join(zeilen)


if __name__ == "__main__":
    raise SystemExit(main())
