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
from . import aufzeichnung as aufz
from .llm import LLMFehler, client_aus_umgebung
from .ndjson import MIME_TYP, Exportergebnis, ExportFehler, schreibe_ndjson

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
            '  synthfhir "50 Patienten mit COPD" -n 50 --ndjson ./export --pause 60\n'
        ),
    )
    p.add_argument("beschreibung", nargs="?", default="",
                   help="Was erzeugt werden soll, in Alltagssprache. "
                        "Bei --wiedergeben nicht nötig.")
    p.add_argument("-n", "--anzahl", type=int,
                   help="Anzahl der Patienten. Bei --wiedergeben nicht nötig: "
                        "Die Menge steht in der Aufzeichnung.")
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
    p.add_argument("--aufzeichnen", type=Path, metavar="DATEI",
                   help="Den Beitrag des Modells mitschreiben, damit sich der "
                        "Lauf später exakt wiederholen lässt.")
    p.add_argument("--wiedergeben", type=Path, metavar="DATEI",
                   help="Eine Aufzeichnung abspielen statt das Modell zu "
                        "fragen. Ohne Netz, ohne Kontingent, exakt "
                        "reproduzierbar — und die Prüfsumme wird nachgerechnet.")
    p.add_argument("--ndjson", type=Path, metavar="VERZEICHNIS",
                   help="Zusätzlich als NDJSON nach FHIR Bulk Data ausgeben: "
                        "eine Datei je Ressourcentyp plus manifest.json. Das "
                        "Format, das Import-Werkzeuge erwarten.")
    p.add_argument("--ueberschreiben", action="store_true",
                   help="Vorhandene NDJSON-Dateien im Zielverzeichnis ersetzen. "
                        "Ohne diesen Schalter bricht der Export ab, damit Reste "
                        "eines früheren Laufs nicht mitgeladen werden.")
    p.add_argument("--bericht", type=Path,
                   help="Zieldatei für die Messwerte des Laufs als JSON.")
    p.add_argument("--still", action="store_true",
                   help="Keinen Fortschritt auf stderr ausgeben.")
    return p


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = baue_parser().parse_args(argv)

    if args.wiedergeben:
        ergebnis, rc = _wiedergeben(args)
        if ergebnis is None:
            return rc
    else:
        ergebnis, rc = _erzeugen(args)
        if ergebnis is None:
            return rc

    if not args.still:
        print(_zusammenfassung(ergebnis), file=sys.stderr)

    if ergebnis.bundle is not None:
        if args.ausgabe:
            args.ausgabe.write_text(
                json.dumps(ergebnis.bundle, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if not args.still:
                print(f"\nBundle: {args.ausgabe}", file=sys.stderr)
        elif not args.ndjson:
            # Nur wenn gar kein Ziel genannt ist, geht das Bundle auf stdout.
            # Sonst schriebe `--ndjson ./export` nebenbei ein Megabyte in die
            # Konsole.
            print(json.dumps(ergebnis.bundle, ensure_ascii=False, indent=2))

    # Der Bericht wird VOR dem NDJSON-Export geschrieben. Sonst ginge er
    # bei einem Dateisystemfehler verloren — und mit ihm die Messwerte
    # eines Laufs, der Minuten gedauert und Kontingent gekostet hat.
    if args.bericht:
        args.bericht.write_text(
            json.dumps(ergebnis.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if not args.still:
            print(f"Bericht: {args.bericht}", file=sys.stderr)

    if args.ndjson:
        try:
            export = schreibe_ndjson(
                ergebnis.ressourcen,
                args.ndjson,
                ueberschreiben=args.ueberschreiben,
                anfrage=(f"synthfhir --wiedergeben {args.wiedergeben}"
                         if args.wiedergeben
                         else f"synthfhir {ergebnis.beschreibung!r} "
                              f"-n {ergebnis.angefragt}"),
            )
        except ExportFehler as exc:
            print(f"NDJSON-Export fehlgeschlagen: {exc}", file=sys.stderr)
            return 2
        if not args.still:
            print(_export_zeilen(export), file=sys.stderr)

    if args.aufzeichnen and not args.wiedergeben:
        try:
            a = aufz.aus_ergebnis(ergebnis, modell=_modellname())
            pfad = aufz.schreibe(a, args.aufzeichnen)
        except aufz.AufzeichnungFehler as exc:
            print(f"Aufzeichnen fehlgeschlagen: {exc}", file=sys.stderr)
            return 2
        if not args.still:
            print(f"Aufzeichnung: {pfad}  ({len(a.teile)} Teile, "
                  f"Prüfsumme {a.bundle_pruefsumme[:12]}…)", file=sys.stderr)
            print(f"  Wiederholen mit:  synthfhir --wiedergeben {pfad}",
                  file=sys.stderr)

    if not ergebnis.ressourcen:
        return 2
    return 0 if ergebnis.fertig and ergebnis.mengentreue == 1.0 else 1


def _modellname() -> str:
    return os.environ.get("SYNTHFHIR_LLM_MODEL", "unbekannt").strip() or "unbekannt"


def _erzeugen(args) -> "tuple[Kohortenergebnis | None, int]":
    """Der übliche Weg: das Modell fragen."""
    if not args.beschreibung:
        print("Fehler: Ohne --wiedergeben braucht es eine Beschreibung.",
              file=sys.stderr)
        return None, 2
    if args.anzahl is None or args.anzahl < 1:
        print("Fehler: --anzahl muss mindestens 1 sein.", file=sys.stderr)
        return None, 2

    try:
        client = client_aus_umgebung()
    except LLMFehler as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return None, 2

    # Der Fortschritt geht auf stderr, damit `synthfhir ... > datei.json`
    # weiterhin eine saubere JSON-Datei ergibt.
    def melde(nummer: int, gesamt: int, stand: str) -> None:
        print(f"  Teil {nummer}/{gesamt}: {stand}", file=sys.stderr, flush=True)

    if not args.still:
        print(f"Erzeuge {args.anzahl} Patienten …", file=sys.stderr)

    try:
        return generiere_kohorte(
            client,
            args.beschreibung,
            args.anzahl,
            teilgroesse=args.teilgroesse,
            versuche_je_teil=args.versuche,
            pause_s=args.pause,
            fortschritt=None if args.still else melde,
        ), 0
    except KeyboardInterrupt:
        print(chr(10) + "Abgebrochen.", file=sys.stderr)
        return None, 2


def _wiedergeben(args) -> "tuple[Kohortenergebnis | None, int]":
    """Abspielen statt fragen — ohne Netz, ohne Kontingent.

    Der Befund über die Übereinstimmung geht auf stderr, und zwar immer:
    Eine Wiedergabe, die stillschweigend etwas anderes liefert als der
    aufgezeichnete Lauf, wäre schlimmer als gar keine.
    """
    try:
        a = aufz.lies(args.wiedergeben)
    except aufz.AufzeichnungFehler as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return None, 2

    if not args.still:
        print(f"Gebe wieder: {args.wiedergeben}", file=sys.stderr)
        print(f"  aufgezeichnet {a.erzeugt or 'ohne Datum'} mit {a.modell}",
              file=sys.stderr)
        print(f"  {len(a.teile)} Teile, {a.patienten} Patienten, "
              "kein Modellaufruf", file=sys.stderr)

    w = aufz.gib_wieder(a)
    if not args.still:
        print(f"  {w.befund()}", file=sys.stderr)
    elif not w.identisch:
        # Auch im stillen Betrieb: Eine Abweichung ist kein Rauschen.
        print(w.befund(), file=sys.stderr)
    return w.ergebnis, 0


def _export_zeilen(export: Exportergebnis) -> str:
    zeilen = [f"\nNDJSON: {export.verzeichnis}"]
    for d in export.dateien:
        zeilen.append(
            f"  {d.pfad.name:<22} {d.anzahl:>6} Ressourcen  {d.bytes:>10,} Bytes"
        )
    if export.manifest:
        zeilen.append(f"  {export.manifest.name:<22} {MIME_TYP}")
    for hinweis in export.entfernt:
        zeilen.append(f"  entfernt: {hinweis}")
    return "\n".join(zeilen)


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
