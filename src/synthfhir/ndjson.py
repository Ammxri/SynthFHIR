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
NDJSON tatsächlich einlesen, erwarten LF. Erzwungen wird es dadurch, dass
die Dateien als **Bytes** geschrieben werden: Was der Textmodus nicht zu
sehen bekommt, kann er auch nicht übersetzen.

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

import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Die Ladereihenfolge wohnt seit Phase 2 in der Domänenschicht: Sie wird
# aus den Verweisen abgeleitet und dient jetzt zwei Ausgabewegen — dem
# NDJSON-Manifest und dem Server-Push. Zwei Abschriften liefen auseinander.
from .domain.integrity import ladereihenfolge

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
class Rohdatei:
    """Eine NDJSON-Datei, bevor sie irgendwo liegt.

    Der Export auf Platte und der Download über die Weboberfläche brauchen
    denselben Inhalt an zwei Ausgängen. Zwei Abschriften der Regeln — LF,
    kein BOM, kompakt, abschließender Zeilenvorschub — liefen auseinander,
    und zwar unbemerkt: Ein CRLF im Download sieht in keiner Anzeige anders
    aus als ein LF.
    """

    typ: str
    inhalt: bytes
    anzahl: int

    @property
    def name(self) -> str:
        """Auch die Namenskonvention gehört an genau eine Stelle."""
        return f"{self.typ}{ENDUNG}"


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
    angefangen: Path | None = None
    try:
        # Erst vollständig bauen, dann schreiben. Ein Fehler beim Bauen
        # erreicht die Platte damit gar nicht erst — vorher schrieb ein
        # NaN in der letzten Ressource erst alle vorherigen Dateien und
        # nahm sie danach wieder zurück.
        for roh in baue_dateien(ressourcen):
            angefangen = ziel / roh.name
            # `write_bytes` statt Textmodus: Die Zeilenenden stehen schon im
            # Inhalt, und was als Bytes hineingeht, kommt als Bytes heraus.
            angefangen.write_bytes(roh.inhalt)
            ergebnis.dateien.append(
                Datei(typ=roh.typ, pfad=angefangen, anzahl=roh.anzahl,
                      bytes=len(roh.inhalt))
            )
            angefangen = None
    except (OSError, ValueError, ExportFehler) as exc:
        for d in ergebnis.dateien:
            d.pfad.unlink(missing_ok=True)
        if angefangen is not None:
            angefangen.unlink(missing_ok=True)
        raise ExportFehler(
            f"Export abgebrochen: {exc}. Angefangene Dateien wurden "
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


def baue_dateien(ressourcen: list[dict]) -> list[Rohdatei]:
    """Die NDJSON-Dateien als Bytes, ohne Dateisystem.

    Der geteilte Kern beider Ausgabewege. `_gruppiere` prüft dabei die
    Ressourcentypen gegen `TYP_MUSTER` — was auf Platte einen Pfadausbruch
    verhinderte, verhindert im Archiv einen Eintragsnamen wie
    ``../entwischt.ndjson``. Dieselbe Gefahr, dieselbe Sperre.

    `allow_nan=False` ist der zweite Punkt: Voreingestellt schriebe
    json.dumps für einen Fließkomma-NaN das Wort NaN — das RFC 8259 nicht
    kennt. Die Zeile sähe aus wie JSON und wäre keines.
    """
    nach_typ = _gruppiere(ressourcen)
    aus: list[Rohdatei] = []
    for typ in ladereihenfolge(nach_typ):
        zeilen = []
        for r in nach_typ[typ]:
            try:
                zeile = json.dumps(
                    r, ensure_ascii=False, separators=(",", ":"),
                    allow_nan=False,
                )
            except ValueError as exc:
                # Ohne diesen Zweig lautete die Meldung "Out of range float
                # values are not JSON compliant" — wahr, aber bei 1020
                # Ressourcen keine Auskunft, sondern eine Suchaufgabe.
                raise ExportFehler(
                    f"{typ}/{r.get('id')} lässt sich nicht als JSON "
                    f"schreiben: {exc}"
                ) from exc
            if "\n" in zeile or "\r" in zeile:  # pragma: no cover
                raise ExportFehler(
                    f"{r.get('resourceType')}/{r.get('id')} enthält einen "
                    "Zeilenumbruch in der Ausgabe."
                )
            zeilen.append(zeile)
        # Der abschließende Zeilenvorschub gehört zur letzten Zeile — hier
        # wie beim Schreiben auf Platte.
        aus.append(
            Rohdatei(
                typ=typ,
                inhalt=("\n".join(zeilen) + "\n").encode("utf-8"),
                anzahl=len(zeilen),
            )
        )
    return aus


ARCHIV_HINWEIS = """SynthFHIR — synthetische Testdaten

Dieses Archiv enthaelt AUSSCHLIESSLICH synthetisch erzeugte Daten.
Es sind keine echten Patientendaten, und sie sind NICHT fuer die
klinische Nutzung bestimmt.

Je Ressourcentyp eine Datei im Format application/fhir+ndjson: eine
Ressource je Zeile. manifest.json nennt Typ und Anzahl je Datei; laden
Sie die Dateien in der dort angegebenen Reihenfolge, dann sind die
Verweise beim Einlesen aufloesbar.
"""

ARCHIV_HINWEIS_NAME = "LIESMICH.txt"


def baue_archiv(
    ressourcen: list[dict],
    *,
    anfrage: str | None = None,
    zeitpunkt: datetime | None = None,
) -> bytes:
    """Alle NDJSON-Dateien plus Manifest als ZIP-Archiv im Speicher.

    Für den Download über die Weboberfläche. Eine einzelne
    zusammengehängte Datei wäre der bequemere Weg gewesen und hätte
    ADR-005 widersprochen: **eine Datei je Ressourcentyp** ist keine
    Formsache, sondern die Vorgabe des Bulk-Data-Leitfadens. Ein Browser
    lädt aber nur eine Datei, also braucht es eine Hülle, und das Archiv
    ist die Hülle, die die Aufteilung erhält.

    **Zwei bewusste Abweichungen**, beide dokumentiert in ADR-010:

    `output[].url` trägt den Eintragsnamen im Archiv, nicht den absoluten
    Pfad, den der Leitfaden vorsieht. Ein absoluter Pfad wäre hier der
    Pfad *auf dem Server* — für den Empfänger nutzlos und obendrein eine
    Auskunft über fremde Verzeichnisse, die ihn nichts angeht.

    Die Zeitstempel der Einträge sind fest auf `zeitpunkt` gesetzt statt
    auf die Uhr. Sonst unterschieden sich zwei Archive aus denselben
    Daten in jedem Byte des Zeitfelds — und ADR-006 verspricht, dass
    gleiche Eingaben gleiche Ausgaben ergeben.
    """
    jetzt = zeitpunkt or datetime.now(timezone.utc)
    if jetzt.tzinfo is None:
        raise ExportFehler(
            "zeitpunkt braucht eine Zeitzone (z. B. timezone.utc); "
            "ohne sie verschöbe sich transactionTime um den lokalen Versatz."
        )
    dateien = baue_dateien(ressourcen)
    if not dateien:
        raise ExportFehler("Keine Ressourcen zum Schreiben.")

    manifest = _manifest_inhalt(
        eintraege=[
            {"type": d.typ, "url": d.name, "count": d.anzahl} for d in dateien
        ],
        groessen={d.name: len(d.inhalt) for d in dateien},
        anfrage=anfrage,
        jetzt=jetzt,
    )
    utc = jetzt.astimezone(timezone.utc)
    stempel = (utc.year, utc.month, utc.day, utc.hour, utc.minute, utc.second)

    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as archiv:
        inhalte = [(d.name, d.inhalt) for d in dateien]
        inhalte.append((
            MANIFEST_NAME,
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        ))
        inhalte.append((ARCHIV_HINWEIS_NAME, ARCHIV_HINWEIS.encode("utf-8")))
        for name, roh in inhalte:
            eintrag = zipfile.ZipInfo(name, date_time=stempel)
            # Ohne dieses Attribut trägt der Eintrag Rechte 0000; manche
            # Entpacker unter Linux legen die Datei dann unlesbar an.
            eintrag.external_attr = 0o644 << 16
            eintrag.compress_type = zipfile.ZIP_DEFLATED
            archiv.writestr(eintrag, roh)
    return puffer.getvalue()


def _manifest_inhalt(
    *,
    eintraege: list[dict],
    groessen: dict[str, int],
    anfrage: str | None,
    jetzt: datetime,
) -> dict:
    """Der Rumpf des Manifests — für die Platte wie für das Archiv.

    Diese Funktion gibt es, weil genau hier schon einmal etwas eingesickert
    ist: `outputFormat` und `fileSize` standen auf Wurzelebene, obwohl sie
    erst der Continuous Build definiert und die veröffentlichte v3.0.0
    nicht. Eine zweite Abschrift für den Download-Weg wäre die Einladung,
    denselben Fehler ein zweites Mal zu machen — an einer Stelle, die dann
    niemand mehr mit der ersten vergleicht.

    Auf Wurzelebene stehen daher ausschließlich `transactionTime`,
    `request`, `requiresAccessToken`, `output`, `error` und `extension`.
    """
    return {
        "transactionTime": jetzt.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "request": anfrage or "synthfhir",
        # Falsch, weil hier nichts zu autorisieren ist. Der Leitfaden
        # verlangt das Feld trotzdem.
        "requiresAccessToken": False,
        "output": eintraege,
        # Pflicht trotz des Namens: Gibt es nichts zu melden, gehört ein
        # leeres Feld hierher, kein fehlendes.
        "error": [],
        # Alles Eigene steht hier — nicht auf Wurzelebene.
        "extension": {
            "hinweis": (
                "Synthetische Testdaten aus SynthFHIR. Nicht für klinische "
                "Nutzung, keine echten Patientendaten."
            ),
            "dateiformat": MIME_TYP,
            "dateigroessen": groessen,
        },
    }


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
    inhalt = _manifest_inhalt(
        eintraege=[d.zum_manifest() for d in ergebnis.dateien],
        groessen={d.pfad.name: d.bytes for d in ergebnis.dateien},
        anfrage=anfrage,
        jetzt=jetzt,
    )
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
