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
from .push import TOKEN_VARIABLE, pushe

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
    p.add_argument("--push", metavar="FHIR-BASIS-URL",
                   help="Die Kohorte in einen FHIR-Server laden. Schreibt "
                        "NICHTS, solange nicht zusätzlich --push-ausfuehren "
                        "gesetzt ist: Ein Tippfehler in der URL soll sichtbar "
                        "werden, bevor er wirkt.")
    p.add_argument("--push-ausfuehren", action="store_true",
                   help="Den Push wirklich ausführen statt nur zu berichten.")
    p.add_argument("--fremde-daten-ok", action="store_true",
                   help="Auch dann pushen, wenn auf dem Ziel Daten ohne "
                        "Testkennzeichen liegen. Wer das setzt, sagt: Ich "
                        "weiß, was dort liegt.")
    p.add_argument("--bericht", type=Path,
                   help="Zieldatei für die Messwerte des Laufs als JSON.")
    p.add_argument("--still", action="store_true",
                   help="Keinen Fortschritt auf stderr ausgeben.")
    return p


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = baue_parser().parse_args(argv)

    if args.wiedergeben:
        ergebnis, vorbefund = _wiedergeben(args)
    else:
        ergebnis, vorbefund = _erzeugen(args)
    if ergebnis is None:
        return vorbefund

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
        elif not args.ndjson and not args.push:
            # Nur wenn gar kein Ziel genannt ist, geht das Bundle auf stdout.
            # Sonst schriebe `--ndjson ./export` oder `--push <url>` nebenbei
            # ein Megabyte in die Konsole.
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

    # Aufgezeichnet wird VOR dem NDJSON-Export, aus demselben Grund wie der
    # Bericht: Ein Dateisystemfehler dort nähme sonst den teuersten Teil des
    # Laufs mit — den Beitrag des Modells, der Minuten und Kontingent
    # gekostet hat und ohne den sich nichts wiederholen lässt.
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

    if args.push:
        push_rc = _pushen(args, ergebnis)
        if push_rc:
            return push_rc

    if not ergebnis.ressourcen:
        return 2
    schluss = 0 if ergebnis.fertig and ergebnis.mengentreue == 1.0 else 1
    # Eine Wiedergabe, die nicht dasselbe ergab, ist kein Erfolg — auch wenn
    # die Kohorte für sich vollständig und gültig ist. Sonst meldete der
    # Rückgabewert 0, während auf stderr ABWEICHUNG steht, und eine Prüfkette
    # liefe darüber hinweg.
    return max(schluss, vorbefund)


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
    # Der Rückgabewert trägt das Urteil mit: Genau dafür gibt es die
    # Wiedergabe. 1 heisst „geliefert, aber nicht dasselbe".
    return w.ergebnis, 0 if w.identisch else 1


def _pushen(args, ergebnis) -> int:
    """Führt den Push aus und meldet, was geschah. 0 heißt: kein Abbruch.

    Der Push kommt NACH Bundle, Bericht, Aufzeichnung und NDJSON. Wenn er
    scheitert, sind die lokalen Artefakte längst geschrieben — sie sind das
    Teure am Lauf, der Push ist wiederholbar.
    """
    if not ergebnis.fertig:
        print("Push abgebrochen: Die Kohorte ist nicht vollständig gültig. "
              "In ein fremdes System gehört nur, was die Prüfung besteht.",
              file=sys.stderr)
        return 2

    # Eine Lücke ist kein Grund, den Push zu verweigern: Was geliefert wurde,
    # ist gültig und in sich geschlossen, und 190 von 200 Patienten sind
    # brauchbar. Sie muss aber genau hier stehen, wo geschrieben wird — nicht
    # nur weiter oben in der Zusammenfassung.
    if ergebnis.mengentreue < 1.0 and not args.still:
        print(
            f"\nACHTUNG: Die Kohorte ist unvollständig — {ergebnis.patienten} "
            f"von {ergebnis.angefragt} Patienten ({ergebnis.mengentreue:.0%}). "
            "Was gepusht wird, ist gültig, aber es ist nicht alles.",
            file=sys.stderr,
        )

    e = pushe(
        ergebnis.ressourcen,
        args.push,
        ausfuehren=args.push_ausfuehren,
        fremde_daten_ok=args.fremde_daten_ok,
    )
    if not args.still:
        print(_push_zeilen(e, args), file=sys.stderr)

    if not e.fehler:
        return 0
    # 2 hieße „nichts passiert". Wenn aber schon Pakete durchgingen, liegen
    # Daten auf einem fremden Server, und der Rückgabewert darf das nicht
    # verschweigen. 1 heißt hier wie überall: geliefert, aber unvollständig.
    if e.geschrieben:
        print(
            f"  ACHTUNG: {e.geschrieben} Ressourcen sind bereits auf "
            f"{e.ziel} geschrieben. Der Push ist idempotent — ein zweiter "
            "Versuch ergänzt sie, statt sie zu verdoppeln.",
            file=sys.stderr,
        )
        return 1
    return 2


def _push_zeilen(e, args) -> str:
    zeilen = [f"\nPush: {e.ziel}"]
    b = e.befund
    if b and b.erreichbar:
        zeilen.append(f"  Server:       FHIR {b.fhir_version}")
        zeilen.append(
            f"  Bestand dort: {b.ressourcen_gesamt} Patienten, davon "
            f"{b.ressourcen_mit_testlabel} als Testdaten gekennzeichnet"
        )
    for f in e.fehler:
        zeilen.append(f"  ABGEBROCHEN:  {f}")
    if not e.fehler:
        zeilen.append(f"  Reihenfolge:  {' -> '.join(e.reihenfolge)}")
        if e.trockenlauf:
            zeilen.append(
                f"  TROCKENLAUF:  {e.pakete} Transaktionen würden geschrieben. "
                "Es wurde nichts verändert."
            )
            zeilen.append("  Wirklich ausführen mit:  --push-ausfuehren")
        else:
            zeilen.append(
                f"  Geschrieben:  {e.geschrieben} Ressourcen in {e.pakete} "
                "Transaktionen"
            )
    return "\n".join(zeilen)


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
