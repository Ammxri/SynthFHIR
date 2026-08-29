"""Aufzeichnen und Wiedergeben eines Laufs (Phase 2).

===========================================================================
WARUM ES KEIN `--seed` GIBT
===========================================================================

Ein Seed verspricht: derselbe Auftrag, dasselbe Ergebnis. Bei Synthea löst
`-s` genau das ein. Hier kann er es nicht, und das ist gemessen, nicht
vermutet.

Gemessen am 2026-08-29 gegen `openai/gpt-oss-120b` über Groq, je drei
identische Anfragen:

| Einstellung | verschiedene Antworten |
|---|---|
| `temperature 0.8`, kein Seed (Voreinstellung) | 3 von 3 |
| `temperature 0`, kein Seed | 2 von 3 |
| `temperature 0`, **Seed 42** | 2 von 3 |
| `temperature 0.8`, Seed 42 | 2 von 3 |

Der Seed verbessert **nichts** gegenüber `temperature 0`. Auch der
`system_fingerprint`, mit dem sich sonst erkennen ließe, ob das Backend
gewechselt hat, wechselte bei fast jedem Aufruf — als Signal taugt er hier
nicht.

Ein Schalter namens `--seed` wäre also ein gebrochenes Versprechen schon im
Namen. Wer von Synthea kommt, erwartet exakte Wiederholbarkeit und bekäme
sie messbar nicht. Dieses Projekt hat Variante A in ADR-001 gerade deshalb
verworfen, weil sie 79,4 % lieferte und Erfolg meldete.

===========================================================================
WAS STATTDESSEN GEHT
===========================================================================

Die tragende Einsicht aus ADR-001, eine Ebene weiter gedacht: **Das Modell
liefert Inhalt, der Code stellt die Struktur her.** Gemessen ist der Weg
nach dem Modellaufruf byteweise stabil — dasselbe Parameterobjekt ergab
über 20 Läufe und über vier Prozesse mit verschiedenem `PYTHONHASHSEED`
denselben SHA-256.

Der gesamte Nichtdeterminismus steckt also in genau einem Schritt. Wird der
Beitrag des Modells **aufgezeichnet**, lässt sich der Rest beliebig oft
exakt wiederholen — garantiert vom eigenen Code, nicht von einer Zusage des
Anbieters.

Die Aufzeichnung ist klein: Sie enthält nicht das Bundle, sondern die
Parameterobjekte, aus denen es entsteht.

===========================================================================
DIE AUFZEICHNUNG PRÜFT SICH SELBST
===========================================================================

Jede Aufzeichnung führt die Prüfsumme des Bundles mit, das der
ursprüngliche Lauf erzeugt hat. Die Wiedergabe rechnet sie neu und
vergleicht. Damit *behauptet* dieses Modul die Reproduzierbarkeit nicht,
sondern **weist sie bei jedem Abspielen nach**.

Das ist mehr als Buchführung. Ändert sich der Katalog in `codes.py`, eine
Vorlage in `templates.py` oder die Kennungsvergabe, liefert dieselbe
Aufzeichnung ein anderes Bundle — und ohne diesen Vergleich fiele es
niemandem auf. Genau diese Klasse von Fehler zieht sich durch das Projekt:
Das Ergebnis sieht richtig aus.

Eine abweichende Prüfsumme ist deshalb **kein Fehler der Aufzeichnung**,
sondern ein Befund: Zwischen Aufnahme und Wiedergabe hat sich am
deterministischen Weg etwas geändert. Die Wiedergabe liefert das Ergebnis
trotzdem — sie sagt nur dazu, dass es nicht dasselbe ist.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .domain.codes import FESTE_WERTE, KATALOGE, SYSTEME
from .kohorte import Kohortenergebnis, TeilParameter, baue_aus_aufzeichnung

# Erhöhen, wenn sich das Dateiformat so ändert, dass alte Dateien nicht mehr
# gelesen werden können. Eine Aufzeichnung mit unbekannter Version wird
# abgewiesen statt halb verstanden.
FORMAT_VERSION = 1


class AufzeichnungFehler(RuntimeError):
    """Die Aufzeichnung ließ sich nicht schreiben, lesen oder abspielen."""


def pruefsumme(daten) -> str:
    """SHA-256 über eine stabile JSON-Darstellung.

    `sort_keys` ist der Punkt: Ohne sie hinge die Prüfsumme an der
    Einfügereihenfolge der Schlüssel, und zwei inhaltsgleiche Bundles
    ergäben verschiedene Summen.
    """
    text = json.dumps(daten, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def katalog_pruefsumme() -> str:
    """Fingerabdruck des Katalogs — der häufigsten Ursache für Abweichung.

    Nicht über die Datei, sondern über die Codes selbst: Ein geänderter
    Kommentar in `codes.py` ändert nichts am Ergebnis und darf keine
    Abweichung melden. Ein korrigierter ICD-Schlüssel sehr wohl.

    **Über alle Felder, nicht über eine Auswahl.** Hier stand einmal eine
    Aufzählung von Hand, und sie übersah `vital_sign` — das Feld, das über
    `Observation.category` entscheidet (`vital-signs` gegen `laboratory`).
    Nachgestellt: Das Bundle änderte sich, der Fingerabdruck nicht, und der
    Befund sagte „Der Katalog ist unverändert" und schickte die Suche in
    die falsche Richtung. `asdict` kann kein Feld vergessen, eine
    Aufzählung schon — beim nächsten neuen Katalogfeld wiederholte sich der
    Fehler sonst.

    Aus demselben Grund kommen die Sammlungen aus `KATALOGE` und nicht aus
    einer Aufzählung hier: Käme ein Katalog hinzu und stünde er nicht in
    dieser Datei, bliebe seine Änderung unbemerkt — derselbe Fehler eine
    Ebene höher.

    Eine Nebenwirkung, die man kennen muss: Ändert sich dieses **Verfahren**,
    passen die Fingerabdrücke älterer Aufzeichnungen nicht mehr, und die
    Wiedergabe meldet eine Katalogänderung, die keine ist. Die
    Bundle-Prüfsumme bleibt davon unberührt und behält recht — sie ist das
    Urteil, der Fingerabdruck nur die Ursachenzuordnung.
    """
    daten = {
        name: sorted(json.dumps(asdict(e), sort_keys=True) for e in katalog.values())
        for name, katalog in KATALOGE.items()
    }
    # Die System-URIs gehören dazu: Sie landen ebenso im Bundle wie die Codes.
    daten["systeme"] = sorted(SYSTEME)
    # Ebenso die festen Statuswerte. `FESTE_WERTE` war eine Weile deklariert
    # und dokumentiert, aber nirgends benutzt — eine Konstante, die aussieht,
    # als täte sie etwas.
    daten["feste_werte"] = sorted(FESTE_WERTE)
    return pruefsumme(daten)


@dataclass
class Aufzeichnung:
    """Der Beitrag des Modells zu einem Lauf, samt Herkunft und Prüfsumme."""

    beschreibung: str
    angefragt: int
    teile: list[TeilParameter]
    modell: str = "unbekannt"
    erzeugt: str = ""
    bundle_pruefsumme: str = ""
    katalog_pruefsumme: str = ""
    format_version: int = FORMAT_VERSION
    hinweis: str = (
        "Synthetische Testdaten aus SynthFHIR. Nicht für klinische Nutzung, "
        "keine echten Patientendaten."
    )

    @property
    def patienten(self) -> int:
        return sum(len(t.parameter.get("patienten", [])) for t in self.teile)

    def to_dict(self) -> dict:
        return {
            "format_version": self.format_version,
            "hinweis": self.hinweis,
            "beschreibung": self.beschreibung,
            "angefragt": self.angefragt,
            "modell": self.modell,
            "erzeugt": self.erzeugt,
            "bundle_pruefsumme": self.bundle_pruefsumme,
            "katalog_pruefsumme": self.katalog_pruefsumme,
            "teile": [t.to_dict() for t in self.teile],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Aufzeichnung":
        version = d.get("format_version")
        if version != FORMAT_VERSION:
            raise AufzeichnungFehler(
                f"Aufzeichnung hat Format {version!r}, dieses Programm liest "
                f"Format {FORMAT_VERSION}. Halb verstehen wäre schlimmer als "
                "abweisen."
            )
        try:
            teile = [TeilParameter.from_dict(t) for t in d["teile"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise AufzeichnungFehler(f"Aufzeichnung ist unvollständig: {exc}") from exc
        if not teile:
            raise AufzeichnungFehler("Aufzeichnung enthält keine Teile.")
        return cls(
            beschreibung=str(d.get("beschreibung", "")),
            angefragt=int(d.get("angefragt", 0)),
            teile=teile,
            modell=str(d.get("modell", "unbekannt")),
            erzeugt=str(d.get("erzeugt", "")),
            bundle_pruefsumme=str(d.get("bundle_pruefsumme", "")),
            katalog_pruefsumme=str(d.get("katalog_pruefsumme", "")),
            format_version=FORMAT_VERSION,
        )


@dataclass
class Wiedergabe:
    """Ergebnis eines Abspielens, samt Urteil über die Übereinstimmung."""

    ergebnis: Kohortenergebnis
    erwartet: str
    erhalten: str
    katalog_erwartet: str = ""
    katalog_erhalten: str = ""

    @property
    def identisch(self) -> bool:
        """Ist wirklich dasselbe herausgekommen?"""
        return bool(self.erwartet) and self.erwartet == self.erhalten

    @property
    def katalog_geaendert(self) -> bool:
        return bool(self.katalog_erwartet) and self.katalog_erwartet != self.katalog_erhalten

    def befund(self) -> str:
        """Was die Prüfsumme sagt — im Klartext, nicht als Zahlenpaar."""
        if self.identisch:
            if self.katalog_geaendert:
                # Kein Widerspruch: Der Katalog kann sich an Stellen geändert
                # haben, die diese Kohorte nicht benutzt. Erwähnenswert
                # bleibt es — die Aufzeichnung stammt aus anderen
                # Verhältnissen, und der nächste Lauf könnte betroffen sein.
                return ("identisch zum aufgezeichneten Lauf (Prüfsumme stimmt) "
                        "— der Katalog hat sich allerdings geändert, nur an "
                        "Stellen, die diese Kohorte nicht berührt")
            return "identisch zum aufgezeichneten Lauf (Prüfsumme stimmt)"
        if not self.erwartet:
            return ("die Aufzeichnung trägt keine Prüfsumme — die Wiedergabe "
                    "lässt sich nicht gegenprüfen")
        zeilen = [
            "ABWEICHUNG: Das Ergebnis ist nicht dasselbe wie beim "
            "aufgezeichneten Lauf.",
            f"  aufgezeichnet: {self.erwartet[:16]}…",
            f"  jetzt:         {self.erhalten[:16]}…",
        ]
        if self.katalog_geaendert:
            zeilen.append(
                "  Der Katalog hat sich geändert — das ist die wahrscheinliche "
                "Ursache."
            )
        elif not self.katalog_erwartet:
            # Die Aufzeichnung trägt keinen Fingerabdruck. „Unverändert" zu
            # sagen wäre eine Behauptung über etwas, das nie geprüft wurde.
            zeilen.append(
                "  Die Aufzeichnung trägt keinen Katalog-Fingerabdruck — ob "
                "der Katalog die Ursache ist, lässt sich nicht sagen."
            )
        else:
            zeilen.append(
                "  Der Katalog ist unverändert. Dann liegt es an den Vorlagen, "
                "der Kennungsvergabe oder dem Bundle-Bau."
            )
        return "\n".join(zeilen)


def aus_ergebnis(
    ergebnis: Kohortenergebnis,
    *,
    modell: str = "unbekannt",
    zeitpunkt: datetime | None = None,
) -> Aufzeichnung:
    """Macht aus einem gelaufenen Ergebnis eine Aufzeichnung."""
    if not ergebnis.parameter:
        raise AufzeichnungFehler(
            "Der Lauf hat keine Parameterobjekte hinterlassen — es gibt "
            "nichts aufzuzeichnen."
        )
    jetzt = zeitpunkt or datetime.now(timezone.utc)
    if jetzt.tzinfo is None:
        raise AufzeichnungFehler("zeitpunkt braucht eine Zeitzone.")
    return Aufzeichnung(
        beschreibung=ergebnis.beschreibung,
        angefragt=ergebnis.angefragt,
        teile=list(ergebnis.parameter),
        modell=modell,
        erzeugt=jetzt.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        bundle_pruefsumme=pruefsumme(ergebnis.bundle) if ergebnis.bundle else "",
        katalog_pruefsumme=katalog_pruefsumme(),
    )


def schreibe(aufzeichnung: Aufzeichnung, pfad: Path | str) -> Path:
    """Schreibt die Aufzeichnung als JSON."""
    ziel = Path(pfad)
    if ziel.exists() and ziel.is_dir():
        raise AufzeichnungFehler(f"{ziel} ist ein Verzeichnis.")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(
        json.dumps(aufzeichnung.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return ziel


def lies(pfad: Path | str) -> Aufzeichnung:
    """Liest eine Aufzeichnung."""
    quelle = Path(pfad)
    try:
        roh = json.loads(quelle.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AufzeichnungFehler(f"{quelle} gibt es nicht.") from exc
    except json.JSONDecodeError as exc:
        raise AufzeichnungFehler(f"{quelle} ist kein gültiges JSON: {exc}") from exc
    if not isinstance(roh, dict):
        raise AufzeichnungFehler(f"{quelle} enthält kein Aufzeichnungsobjekt.")
    return Aufzeichnung.from_dict(roh)


def gib_wieder(aufzeichnung: Aufzeichnung) -> Wiedergabe:
    """Spielt eine Aufzeichnung ab — ohne jeden Modellaufruf.

    Das Urteil über die Übereinstimmung fällt hier, nicht beim Aufrufer:
    Wer eine Wiedergabe bekommt, bekommt zugleich die Antwort auf die
    Frage, ob es wirklich dasselbe ist.
    """
    ergebnis = baue_aus_aufzeichnung(
        aufzeichnung.beschreibung, aufzeichnung.angefragt, aufzeichnung.teile
    )
    return Wiedergabe(
        ergebnis=ergebnis,
        erwartet=aufzeichnung.bundle_pruefsumme,
        erhalten=pruefsumme(ergebnis.bundle) if ergebnis.bundle else "",
        katalog_erwartet=aufzeichnung.katalog_pruefsumme,
        katalog_erhalten=katalog_pruefsumme(),
    )
