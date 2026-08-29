"""Export als NDJSON nach FHIR Bulk Data (Phase 2).

Ein Bundle ist zum Ansehen gut und zum Laden schlecht. Wer 200 Patienten in
ein System bringen will, braucht das Format, das die Import-Werkzeuge
erwarten: **eine Ressource je Zeile, eine Datei je Ressourcentyp.** Genau
das schreibt der FHIR-Bulk-Data-Access-Leitfaden vor (v3.0.0 STU 3,
<https://hl7.org/fhir/uv/bulkdata/en/export.html>): *jede Ausgabedatei
enthält Ressourcen nur eines Typs*, im MIME-Typ
`application/fhir+ndjson`.

Dateinamen schreibt der Leitfaden ausdrücklich **nicht** vor. Der
Ressourcentyp steht normativ im Manifestfeld `type`, nicht im Dateinamen —
ein Empfänger darf ihn nicht aus dem Namen ableiten. `Patient.ndjson` ist
also Konvention (die Endung ein SHOULD der NDJSON-Spezifikation), und
deshalb trägt das Manifest den Typ ausdrücklich.

===========================================================================
WAS BEIM SCHREIBEN SCHIEFGEHT
===========================================================================

**Zeilenenden — und ein Widerspruch im Standard.** Python übersetzt im
Textmodus jedes Zeilenende unter Windows still zu CRLF. Nachgemessen:
``Path.write_text`` — womit der Rest des Projekts Bundles schreibt —
erzeugt hier CRLF.

Welches Zeilenende richtig ist, sagen die Quellen verschieden. Die
FHIR-Kernseite zum Format (<https://hl7.org/fhir/R4/nd-json.html>) schreibt
wörtlich, Ressourcen seien *"separated by a newline pair (characters 13 and
10)"* — also CRLF. Der Bulk-Data-Leitfaden verweist dagegen auf die
NDJSON-Spezifikation, und die kennt den Zeilenvorschub als **Abschluss**
jeder Zeile, nicht als Trenner dazwischen.

Dieses Modul schreibt LF, aus drei Gründen in dieser Reihenfolge: Für
diesen Anwendungsfall ist der Bulk-Data-Leitfaden die einschlägige und
veröffentlichte Spezifikation (v3.0.0 STU 3), während die Kernseite auf
*Maturity Level 2, Standards Status: Draft* steht. Und die Werkzeuge, die
NDJSON tatsächlich einlesen, erwarten LF. Erzwungen wird es über den
``newline``-Parameter beim Öffnen.

Beim **Lesen** ist `lies_ndjson` dagegen nachsichtig und verkraftet auch
CRLF. Die Strenge gehört an die Stelle, an der wir etwas erzeugen, nicht an
die, an der wir etwas Fremdes prüfen.

**Der abschließende Zeilenvorschub gehört dazu.** Die NDJSON-Spezifikation
behandelt ihn als Abschluss jeder Zeile, auch der letzten. Ohne ihn klebte
die letzte Ressource an dem, was ein Werkzeug beim Aneinanderhängen
mehrerer Dateien dahinterschreibt. Eine zusätzliche Leerzeile dagegen
nicht — sie erzeugt bei manchen Lesern einen leeren Datensatz.

**Kein BOM.** ``utf-8-sig`` setzt drei Bytes an den Dateianfang. Sie landen
vor der ersten öffnenden Klammer, und der Parser der ersten Zeile — nur der
ersten — scheitert. Ein Fehler, der aussieht, als sei genau ein Datensatz
kaputt.

**Eingerückte Ausgabe.** ``json.dumps(..., indent=2)`` verteilt eine
Ressource über viele Zeilen. In NDJSON ist damit jede Zeile ein
Bruchstück. Hier gilt das Gegenteil: so kompakt wie möglich, garantiert
ohne eingebetteten Zeilenumbruch.

**Ladereihenfolge.** Die Dateien heißen nach ihrem Ressourcentyp, und
wer sie alphabetisch abarbeitet, lädt ``Condition.ndjson`` vor
``Patient.ndjson`` — also Diagnosen, deren Patienten es noch nicht gibt.
HAPI nimmt das hin (nachgeprüft: HTTP 201), Server mit
``enforceReferentialIntegrityOnWrite`` nicht. Der Leitfaden schreibt keine
Reihenfolge vor, deshalb kostet es nichts, im Manifest die referenzierten
Typen zuerst zu nennen. Abgeleitet wird sie aus den tatsächlichen
Verweisen, nicht fest verdrahtet — sonst stimmte sie beim nächsten
Ressourcentyp nicht mehr.

Eine Garantie ist das ausdrücklich nicht: Große Import-Werkzeuge
verarbeiten die Dateien parallel und sichern keine Reihenfolge zu (Microsoft
Bulk Import: *„this order is not guaranteed by distributed parallel
import"*). Sie prüfen dafür meist auch keine referentielle Integrität. Die
Sortierung hilft dem sequentiellen Lader und schadet dem parallelen nicht.

**Reste im Zielverzeichnis.** Schriebe ein Lauf über zwei Ressourcentypen
in ein Verzeichnis, in dem noch ``Encounter.ndjson`` eines früheren Laufs
liegt, lüde der Empfänger beides — die neue Kohorte und Reste einer alten.
Deshalb weigert sich `schreibe_ndjson` gegen ein belegtes Verzeichnis,
solange nicht ausdrücklich überschrieben werden soll.

===========================================================================
WAS DIESES MODUL NICHT IST
===========================================================================

Kein Bulk-Data-**Server**. Es gibt keine `$export`-Operation, keinen
Kick-off, kein Polling und keine Zugriffsverwaltung. Geschrieben werden
Dateien auf Platte, dazu ein Manifest in der Form, die der Leitfaden für
die Abschlussantwort vorsieht — als Beipackzettel, nicht als
Protokollzusage.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Der Leitfaden schreibt diesen MIME-Typ für die Dateien vor.
MIME_TYP = "application/fhir+ndjson"

ENDUNG = ".ndjson"
MANIFEST_NAME = "manifest.json"

# FHIR-Ressourcentypen bestehen ausschließlich aus Buchstaben. Die Prüfung
# ist keine Formsache: Der Typ wird zum Dateinamen, und ein `resourceType`
# von "../woanders" schrieb die Datei nachweislich außerhalb des
# Zielverzeichnisses.
TYP_MUSTER = re.compile(r"^[A-Za-z]+$")


@dataclass(frozen=True)
class Datei:
    """Eine geschriebene Datei, so wie das Manifest sie ausweist."""

    typ: str
    pfad: Path
    anzahl: int
    bytes: int

    def zum_manifest(self) -> dict:
        """Genau die Felder, die der Leitfaden für ein `output`-Element kennt.

        Getrennt von `to_dict`, weil hier eine **fremde Norm** bedient wird
        und dort unsere eigene Anzeige. Hier stand einmal `fileSize` —
        ein Feld, das erst der Continuous Build definiert, die
        veröffentlichte v3.0.0 aber nicht. Ein erfundenes Feld an
        normativer Stelle sieht aus wie Norm und stört nirgends; genau
        deshalb fällt es niemandem auf. Die Größe steht jetzt unter
        `extension`, wo Eigenes hingehört.
        """
        return {
            "type": self.typ,
            "url": self.pfad.resolve().as_uri(),
            "count": self.anzahl,
        }

    def to_dict(self) -> dict:
        """Für unsere eigene Anzeige — deutsche Schlüssel, keine Fremdnorm."""
        return {
            "typ": self.typ,
            "pfad": str(self.pfad),
            "anzahl": self.anzahl,
            "bytes": self.bytes,
        }


@dataclass
class Exportergebnis:
    """Was der Export geschrieben hat."""

    verzeichnis: Path
    dateien: list[Datei] = field(default_factory=list)
    manifest: Path | None = None
    entfernt: list[str] = field(default_factory=list)

    @property
    def ressourcen(self) -> int:
        return sum(d.anzahl for d in self.dateien)

    @property
    def bytes(self) -> int:
        return sum(d.bytes for d in self.dateien)

    def to_dict(self) -> dict:
        return {
            "verzeichnis": str(self.verzeichnis),
            "dateien": [d.to_dict() for d in self.dateien],
            "ressourcen": self.ressourcen,
            "bytes": self.bytes,
            "entfernt": self.entfernt,
        }


class ExportFehler(RuntimeError):
    """Der Export konnte nicht ausgeführt werden."""


def schreibe_ndjson(
    ressourcen: list[dict],
    verzeichnis: Path | str,
    *,
    manifest: bool = True,
    ueberschreiben: bool = False,
    anfrage: str | None = None,
    zeitpunkt: datetime | None = None,
) -> Exportergebnis:
    """Schreibt die Ressourcen als NDJSON, eine Datei je Ressourcentyp.

    `ueberschreiben` ist absichtlich nicht der Normalfall: Reste eines
    früheren Laufs im selben Verzeichnis würden vom Empfänger mitgeladen,
    ohne dass irgendwo steht, dass sie nicht dazugehören.

    `zeitpunkt` ist nur eingezogen, damit Tests ein festes
    `transactionTime` prüfen können.
    """
    ziel = Path(verzeichnis)
    nach_typ = _gruppiere(ressourcen)
    if not nach_typ:
        raise ExportFehler("Keine Ressourcen zum Schreiben.")

    if ziel.exists() and not ziel.is_dir():
        raise ExportFehler(f"{ziel} ist kein Verzeichnis.")

    vorhanden = _belegt(ziel)
    if vorhanden and not ueberschreiben:
        raise ExportFehler(
            f"{ziel} enthält bereits {', '.join(sorted(vorhanden))}. "
            "Ein Empfänger lüde diese Reste mit. Erst leeren oder "
            "ausdrücklich überschreiben."
        )

    ziel.mkdir(parents=True, exist_ok=True)
    ergebnis = Exportergebnis(verzeichnis=ziel)

    # Reste, die dieser Lauf NICHT selbst überschreibt, müssen weg — sonst
    # bliebe von einem früheren, größeren Lauf ein Ressourcentyp liegen.
    if vorhanden:
        behalten = {f"{typ}{ENDUNG}" for typ in nach_typ}
        # Das Manifest darf nur stehenbleiben, wenn dieser Lauf es gleich
        # überschreibt. Sonst bliebe das des Vorlaufs liegen und behauptete
        # Dateien und Zahlen, die es nicht mehr gibt — nachgestellt: Lauf 1
        # schrieb Patient und Condition, Lauf 2 nur Patient, und das alte
        # Manifest wies weiter beide aus.
        if manifest:
            behalten.add(MANIFEST_NAME)
        for name in sorted(vorhanden - behalten):
            (ziel / name).unlink()
            ergebnis.entfernt.append(f"{name} (Rest eines früheren Laufs, entfernt)")

    # Bricht eine Datei ab, wird das Angefangene zurückgenommen. Ein halber
    # Export ohne Manifest sieht aus wie ein ganzer: Der Empfänger sieht
    # NDJSON-Dateien und lädt sie. Lieber gar nichts als die Hälfte.
    try:
        for typ in _ladereihenfolge(nach_typ):
            pfad = ziel / f"{typ}{ENDUNG}"
            geschrieben = _schreibe_datei(pfad, nach_typ[typ])
            ergebnis.dateien.append(
                Datei(typ=typ, pfad=pfad, anzahl=len(nach_typ[typ]),
                      bytes=geschrieben)
            )
    except (OSError, ValueError, ExportFehler) as exc:
        for d in ergebnis.dateien:
            d.pfad.unlink(missing_ok=True)
        (ziel / f"{typ}{ENDUNG}").unlink(missing_ok=True)
        raise ExportFehler(
            f"Export abgebrochen bei {typ}: {exc}. Angefangene Dateien wurden "
            "entfernt, damit kein halber Export zurückbleibt."
        ) from exc

    if manifest:
        ergebnis.manifest = _schreibe_manifest(ziel, ergebnis, anfrage, zeitpunkt)

    return ergebnis


# --- Einzelschritte --------------------------------------------------------


def _gruppiere(ressourcen: list[dict]) -> dict[str, list[dict]]:
    """Nach Ressourcentyp, Reihenfolge innerhalb des Typs bleibt erhalten.

    Der Leitfaden verlangt, dass eine Datei nur Ressourcen eines Typs
    enthält. Eine Ressource ohne `resourceType` ist kein FHIR und wird
    nicht stillschweigend irgendwo einsortiert.
    """
    nach_typ: dict[str, list[dict]] = {}
    for i, r in enumerate(ressourcen):
        typ = r.get("resourceType") if isinstance(r, dict) else None
        if not isinstance(typ, str) or not typ:
            raise ExportFehler(
                f"Ressource {i} hat kein resourceType — das ist kein FHIR."
            )
        if not TYP_MUSTER.match(typ):
            raise ExportFehler(
                f"Ressource {i}: {typ!r} ist kein Ressourcentyp. Der Typ wird "
                "zum Dateinamen — ohne diese Prüfung schriebe ein Wert wie "
                "'../woanders' außerhalb des Zielverzeichnisses."
            )
        nach_typ.setdefault(typ, []).append(r)
    return nach_typ


def _verweis_ziele(wert, ziele: set[str]) -> None:
    """Sammelt die Ressourcentypen, auf die irgendwo verwiesen wird."""
    if isinstance(wert, dict):
        verweis = wert.get("reference")
        if isinstance(verweis, str) and "/" in verweis:
            ziele.add(verweis.split("/", 1)[0])
        for v in wert.values():
            _verweis_ziele(v, ziele)
    elif isinstance(wert, list):
        for v in wert:
            _verweis_ziele(v, ziele)


def _ladereihenfolge(nach_typ: dict[str, list[dict]]) -> list[str]:
    """Referenzierte Typen zuerst, danach alphabetisch.

    Abgeleitet aus den Verweisen in den Daten: Wer auf niemanden zeigt,
    kann zuerst geladen werden. Bei einem Ring — zwei Typen, die
    aufeinander zeigen — greift die alphabetische Reihenfolge, denn eine
    richtige Reihenfolge gibt es dann nicht.
    """
    kanten: dict[str, set[str]] = {}
    for typ, ressourcen in nach_typ.items():
        ziele: set[str] = set()
        for r in ressourcen:
            _verweis_ziele(r, ziele)
        # Nur Verweise auf Typen, die in diesem Export auch vorkommen.
        kanten[typ] = (ziele & set(nach_typ)) - {typ}

    reihenfolge: list[str] = []
    offen = set(nach_typ)
    while offen:
        frei = sorted(t for t in offen if not (kanten[t] - set(reihenfolge)))
        if not frei:                       # Ring: alphabetisch auflösen
            frei = [min(offen)]
        reihenfolge.extend(frei)
        offen -= set(frei)
    return reihenfolge


def _belegt(verzeichnis: Path) -> set[str]:
    """Namen im Zielverzeichnis, die ein Empfänger mitlesen würde.

    Groß- und Kleinschreibung wird ignoriert: Unter Windows ist
    `Encounter.NDJSON` dieselbe Datei wie `Encounter.ndjson`, und ein
    Empfänger unterscheidet sie ohnehin nicht. Ohne das rutschte ein Rest
    mit abweichender Schreibweise durch die Sperre — nachgestellt.
    """
    if not verzeichnis.is_dir():
        return set()
    return {
        p.name
        for p in verzeichnis.iterdir()
        if p.is_file()
        and (p.suffix.lower() == ENDUNG or p.name.lower() == MANIFEST_NAME)
    }


def _schreibe_datei(pfad: Path, ressourcen: list[dict]) -> int:
    """Eine NDJSON-Datei. Gibt die geschriebene Bytezahl zurück.

    `newline="\\n"` verhindert die Übersetzung zu CRLF unter Windows,
    `separators` erzwingt die kompakteste Form, und `ensure_ascii=False`
    hält die Umlaute lesbar — UTF-8 ist zulässig, und der Rest des Projekts
    schreibt ebenso.
    """
    with open(pfad, "w", encoding="utf-8", newline="\n") as datei:
        for r in ressourcen:
            # allow_nan=False ist der Punkt: Voreingestellt schriebe
            # json.dumps für einen Fließkomma-NaN das Wort NaN — das RFC 8259
            # nicht kennt. Die Zeile sähe aus wie JSON, wäre aber keines, und
            # der Empfänger stolperte über genau eine Zeile.
            zeile = json.dumps(
                r, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            )
            # Rückversicherung, kein aktiver Schutz: json.dumps maskiert
            # Steuerzeichen, dieser Zweig kann also nicht feuern. Er bleibt,
            # weil die Zusage „eine Ressource je Zeile" an einer fremden
            # Funktion hängt, die ein Wechsel der Serialisierung
            # stillschweigend brechen könnte.
            if "\n" in zeile or "\r" in zeile:
                raise ExportFehler(
                    f"{r.get('resourceType')}/{r.get('id')} enthält einen "
                    "Zeilenumbruch in der Ausgabe."
                )
            datei.write(zeile + "\n")
    return pfad.stat().st_size


def _schreibe_manifest(
    ziel: Path,
    ergebnis: Exportergebnis,
    anfrage: str | None,
    zeitpunkt: datetime | None,
) -> Path:
    """Das Manifest in der Form der Bulk-Data-Abschlussantwort.

    Gebaut wird gegen die **veröffentlichte v3.0.0**, nicht gegen den
    Continuous Build: Auf Wurzelebene stehen nur `transactionTime`,
    `request`, `requiresAccessToken`, `output`, `error` und `extension`.
    (Der Build kennt darüber hinaus `outputFormat`, `outputOrganizedBy`,
    `link` und benennt `error` in `outcome` um — nichts davon gehört in ein
    Dokument, das sich auf die veröffentlichte Fassung beruft.)

    `requiresAccessToken` ist falsch, weil hier nichts zu autorisieren ist:
    Die Dateien liegen auf derselben Platte. Der Leitfaden verlangt das Feld
    trotzdem.
    """
    jetzt = zeitpunkt or datetime.now(timezone.utc)
    if jetzt.tzinfo is None:
        # Ohne Zeitzone deutete astimezone den Wert als Ortszeit und
        # verschöbe ihn still: 12:00 wurde in der Sommerzeit zu 10:00Z.
        # `transactionTime` ist ein `instant` — ein Zeitpunkt ohne Zone ist
        # keiner.
        raise ExportFehler(
            "zeitpunkt braucht eine Zeitzone (z. B. timezone.utc); "
            "ohne sie verschöbe sich transactionTime um den lokalen Versatz."
        )
    inhalt = {
        "transactionTime": jetzt.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "request": anfrage or "synthfhir",
        "requiresAccessToken": False,
        "output": [d.zum_manifest() for d in ergebnis.dateien],
        # Pflicht trotz des Namens: Gibt es nichts zu melden, gehört ein
        # leeres Feld hierher, kein fehlendes.
        "error": [],
        # Alles, was der Leitfaden NICHT kennt, steht hier — nicht auf
        # Wurzelebene. `outputFormat` und `fileSize` standen einmal dort;
        # beide definiert erst der Continuous Build, nicht die
        # veröffentlichte v3.0.0.
        "extension": {
            "hinweis": (
                "Synthetische Testdaten aus SynthFHIR. Nicht für klinische "
                "Nutzung, keine echten Patientendaten."
            ),
            "dateiformat": MIME_TYP,
            "dateigroessen": {d.pfad.name: d.bytes for d in ergebnis.dateien},
        },
    }
    pfad = ziel / MANIFEST_NAME
    with open(pfad, "w", encoding="utf-8", newline="\n") as datei:
        json.dump(inhalt, datei, ensure_ascii=False, indent=2)
        datei.write("\n")
    return pfad


def lies_ndjson(pfad: Path | str) -> list[dict]:
    """Liest eine NDJSON-Datei zurück. Für Tests und zum Nachprüfen.

    Leere Zeilen werden übersprungen — der abschließende Zeilenvorschub der
    letzten Zeile erzeugt sonst einen leeren Datensatz.
    """
    ressourcen: list[dict] = []
    with open(pfad, "r", encoding="utf-8", newline="") as datei:
        for nummer, zeile in enumerate(datei, start=1):
            roh = zeile.strip()
            if not roh:
                continue
            try:
                ressourcen.append(json.loads(roh))
            except json.JSONDecodeError as exc:
                raise ExportFehler(f"{pfad}, Zeile {nummer}: {exc}") from exc
    return ressourcen
