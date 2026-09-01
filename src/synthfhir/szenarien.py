"""Die Szenario-Bibliothek: fertige Kohorten ohne Modellaufruf.

Ein Szenario ist ein **kuratierter Parametersatz** mit Beschreibung. Es
läuft durch denselben Weg wie ein Modelllauf — `baue_und_pruefe` —, nur
ohne den einzigen Schritt, der Geld kostet und nicht deterministisch ist.

===========================================================================
WARUM DAS MEHR IST ALS EIN VORAUSGEFÜLLTES TEXTFELD
===========================================================================

Die Weboberfläche bot bisher drei Beispieltexte an. Wer einen anklickt,
bekommt den Text ins Feld geschrieben — und zahlt danach trotzdem einen
Modellaufruf. Bei einem Gratiskontingent, das für rund **eine Anfrage je
Minute für alle Besucher zusammen** reicht, ist das der teuerste Weg,
jemandem zu zeigen, was das Werkzeug kann.

Ein Szenario kostet **nichts**. Es ist sofort da, immer dasselbe, und es
funktioniert auch dann, wenn das Kontingent erschöpft oder der Anbieter
ausgefallen ist. Für eine Portfolio-Demo ist das der Unterschied
zwischen „probier es aus" und „probier es aus, wenn gerade frei ist".

===========================================================================
EIN SZENARIO IST KEINE AUFZEICHNUNG
===========================================================================

Beide tragen Parameter, beide laufen ohne Modell. Der Unterschied ist die
**Zusage**.

Eine Aufzeichnung (ADR-006) verspricht: *dasselbe Ergebnis wie damals*.
Sie trägt dafür zwei Prüfsummen und meldet `ABWEICHUNG`, sobald sich
Katalog oder Vorlagen geändert haben. Das ist ihr Zweck.

Ein Szenario verspricht: *eine Diabetes-Kohorte*. Ändert sich der
Katalog — kommt etwa eine SNOMED-Kodierung dazu, wie in ADR-015 —, dann
soll das Szenario die **neue, bessere** Ausgabe liefern, nicht die alte
melden. Eine Prüfsumme wäre hier kein Schutz, sondern Dauerlärm.

Deshalb ein eigenes Format ohne Prüfsummen. Was ein Szenario dafür
braucht, ist eine andere Absicherung: Die Tests halten es gegen den
Katalog (jeder Code muss existieren) und gegen die Prüfkette (jedes
Szenario muss `fertig` ergeben). Ein veraltetes Szenario fällt damit auf,
bevor es jemand sieht — nicht erst beim Nutzer.

===========================================================================
WAS EIN SZENARIO NICHT DARF
===========================================================================

**Codes erfinden.** Nennt ein Szenario einen Code, den der Katalog nicht
führt, ersetzt `baue_aus_parametern` ihn still durch einen anderen und
hinterlässt eine Beanstandung `erfundener_…`. Das Ergebnis wäre gültiges
FHIR mit falschem Inhalt — die schlimmste Sorte Fehler in einem Werkzeug,
dessen Produkt die Verlässlichkeit ist. `tests/test_szenarien.py` prüft
jeden Code jedes Szenarios gegen den Katalog.

**So tun, als käme es vom Modell.** `Ergebnis.szenario` trägt den Namen.
Wer die Ausgabe weiterverarbeitet, kann Vorlage und Beschreibung
unterscheiden.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .domain.codes import (
    CONDITION_CODES,
    ENCOUNTER_CLASSES,
    MEDICATION_CODES,
    OBSERVATION_CODES,
)
from .generation import Ergebnis, baue_und_pruefe
from .kohorte import Kohortenergebnis, TeilParameter, baue_aus_aufzeichnung
from .prompts import MAX_PATIENTEN


class SzenarioFehler(RuntimeError):
    """Das Szenario ist unbrauchbar."""


@dataclass(frozen=True)
class Szenario:
    """Eine benannte Kohortenvorlage."""

    name: str
    titel: str
    beschreibung: str
    # Was das Szenario zeigt — für die Oberfläche und für den, der
    # auswählt. Keine Ableitung aus den Parametern: Es soll sagen, warum
    # es diese Vorlage gibt, nicht was zufällig darin vorkommt.
    zeigt: str
    parameter: dict = field(default_factory=dict)

    @property
    def patienten(self) -> int:
        p = self.parameter.get("patienten")
        return len(p) if isinstance(p, list) else 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "titel": self.titel,
            "beschreibung": self.beschreibung,
            "zeigt": self.zeigt,
            "patienten": self.patienten,
        }

    @classmethod
    def from_dict(cls, d: object) -> "Szenario":
        """Liest ein Szenario und prüft dabei die Form.

        Die Meldungen nennen den empfangenen **Typ**, nie den Wert: Ein
        geladenes Szenario ist Fremdeingabe, und sein Inhalt hat in einer
        Fehlermeldung nichts verloren.
        """
        if not isinstance(d, dict):
            raise SzenarioFehler(
                f"Szenario ist kein Objekt, sondern {type(d).__name__}."
            )
        for feld in ("name", "titel", "beschreibung", "zeigt"):
            if not isinstance(d.get(feld), str) or not d[feld].strip():
                raise SzenarioFehler(f"Feld {feld!r} fehlt oder ist kein Text.")
        parameter = d.get("parameter")
        if not isinstance(parameter, dict):
            raise SzenarioFehler(
                f"'parameter' ist kein Objekt, sondern {type(parameter).__name__}."
            )
        patienten = parameter.get("patienten")
        if not isinstance(patienten, list) or not patienten:
            raise SzenarioFehler("'parameter.patienten' ist keine nichtleere Liste.")
        if len(patienten) > MAX_PATIENTEN:
            raise SzenarioFehler(
                f"{len(patienten)} Patienten; höchstens {MAX_PATIENTEN} sind "
                "zulässig."
            )
        return cls(
            name=d["name"].strip(), titel=d["titel"].strip(),
            beschreibung=d["beschreibung"].strip(), zeigt=d["zeigt"].strip(),
            parameter=parameter,
        )


def _p(vorname, nachname, geschlecht, geburtsdatum, **rest) -> dict:
    """Kurzform für einen Patienteneintrag — die Vorlagen unten sind sonst
    kaum noch zu lesen."""
    return {"vorname": vorname, "nachname": nachname, "geschlecht": geschlecht,
            "geburtsdatum": geburtsdatum, **rest}


# ===========================================================================
# Die eingebauten Szenarien
# ===========================================================================
#
# Ausgewählt nach dem, was ein Tester wirklich braucht — nicht nach dem,
# was sich gut liest. Zwei der fünf zeigen ausdrücklich **unbequeme**
# Fälle: eine Kohorte ohne Begegnung und eine mit mehreren Kontakten je
# Patient. Glatte Kohorten findet man überall; an den schiefen scheitern
# Importwerkzeuge.

_EINGEBAUT: list[Szenario] = [
    Szenario(
        name="diabetes-ambulanz",
        titel="Diabetes-Ambulanz",
        beschreibung=(
            "Drei Patientinnen und Patienten mit Typ-2-Diabetes, je einem "
            "ambulanten Kontakt, HbA1c-Verlauf und Metformin."
        ),
        zeigt="Alle fünf Ressourcentypen im Zusammenspiel — der Normalfall.",
        parameter={"patienten": [
            _p("Ingrid", "Baumgartner", "female", "1958-03-14",
               begegnungen=[{"art": "AMB", "datum": "2024-02-05"}],
               diagnosen=[{"code": "44054006", "beginn": "2012-05-01"}],
               messwerte=[{"code": "4548-4", "wert": 7.8, "datum": "2024-02-05"},
                          {"code": "4548-4", "wert": 7.2, "datum": "2024-08-12"}],
               medikamente=[{"code": "A10BA02", "beginn": "2012-06-01"}]),
            _p("Hans-Jürgen", "Weiß", "male", "1949-11-02",
               begegnungen=[{"art": "AMB", "datum": "2024-03-11"}],
               diagnosen=[{"code": "44054006", "beginn": "2008-09-15"}],
               messwerte=[{"code": "4548-4", "wert": 8.9, "datum": "2024-03-11"},
                          {"code": "2345-7", "wert": 168.0, "datum": "2024-03-11"}],
               medikamente=[{"code": "A10BA02", "beginn": "2008-10-01"}]),
            _p("Ayşe", "Öztürk", "female", "1971-06-28",
               begegnungen=[{"art": "AMB", "datum": "2024-05-20"}],
               diagnosen=[{"code": "44054006", "beginn": "2019-01-20"}],
               messwerte=[{"code": "4548-4", "wert": 6.9, "datum": "2024-05-20"}],
               medikamente=[{"code": "A10BA02", "beginn": "2019-02-01"}]),
        ]},
    ),
    Szenario(
        name="blutdruck-kontrolle",
        titel="Blutdruck-Kontrolle",
        beschreibung=(
            "Zwei Patienten mit arterieller Hypertonie und je zwei "
            "Blutdruckmessungen an verschiedenen Tagen."
        ),
        zeigt=(
            "Blutdruck als Panel: eine Observation mit zwei Komponenten, "
            "wie ISiK Vitalparameter es verlangt (ADR-014)."
        ),
        parameter={"patienten": [
            _p("Reinhard", "Kowalski", "male", "1962-04-09",
               begegnungen=[{"art": "AMB", "datum": "2024-01-15"}],
               diagnosen=[{"code": "38341003", "beginn": "2015-03-01"}],
               messwerte=[{"code": "8480-6", "wert": 158.0, "datum": "2024-01-15"},
                          {"code": "8462-4", "wert": 96.0, "datum": "2024-01-15"},
                          {"code": "8480-6", "wert": 142.0, "datum": "2024-07-08"},
                          {"code": "8462-4", "wert": 88.0, "datum": "2024-07-08"}],
               medikamente=[{"code": "C09AA05", "beginn": "2015-04-01"}]),
            _p("Beate", "Schröder", "female", "1955-12-19",
               begegnungen=[{"art": "AMB", "datum": "2024-02-27"}],
               diagnosen=[{"code": "38341003", "beginn": "2011-08-14"}],
               messwerte=[{"code": "8480-6", "wert": 134.0, "datum": "2024-02-27"},
                          {"code": "8462-4", "wert": 82.0, "datum": "2024-02-27"}],
               medikamente=[{"code": "C09AA05", "beginn": "2011-09-01"}]),
        ]},
    ),
    Szenario(
        name="labor-grundprofil",
        titel="Labor-Grundprofil",
        beschreibung=(
            "Ein Patient mit einer Aufnahme und einem breiten Laborsatz: "
            "Blutbild, Elektrolyte, Leberwerte, Entzündungsparameter."
        ),
        zeigt=(
            "Viele Observations an einem Patienten, mit UCUM-Einheiten aus "
            "dem Katalog. Sechs davon tragen die SNOMED-Doppelkodierung."
        ),
        parameter={"patienten": [
            _p("Wolfgang", "Petersen", "male", "1968-07-23",
               begegnungen=[{"art": "IMP", "datum": "2024-04-02"}],
               diagnosen=[{"code": "13645005", "beginn": "2020-11-05"}],
               messwerte=[
                   {"code": "718-7", "wert": 13.2, "datum": "2024-04-02"},
                   {"code": "789-8", "wert": 4.6, "datum": "2024-04-02"},
                   {"code": "6690-2", "wert": 9.1, "datum": "2024-04-02"},
                   {"code": "777-3", "wert": 245.0, "datum": "2024-04-02"},
                   {"code": "2951-2", "wert": 139.0, "datum": "2024-04-02"},
                   {"code": "2823-3", "wert": 4.2, "datum": "2024-04-02"},
                   {"code": "2160-0", "wert": 1.1, "datum": "2024-04-02"},
                   {"code": "1742-6", "wert": 34.0, "datum": "2024-04-02"},
                   {"code": "1988-5", "wert": 8.4, "datum": "2024-04-02"},
               ]),
        ]},
    ),
    Szenario(
        name="mehrere-kontakte",
        titel="Mehrere Kontakte",
        beschreibung=(
            "Eine Patientin mit stationärer Aufnahme, Notaufnahme und "
            "ambulanter Nachsorge im selben Jahr."
        ),
        zeigt=(
            "Mehrere Encounter je Patient und die Kennungsvergabe darüber "
            "hinweg. Der Fall, an dem eine Kennungskollision einmal "
            "unbemerkt blieb (ADR-007)."
        ),
        parameter={"patienten": [
            _p("Christa", "Lindemann", "female", "1943-02-11",
               # Nicht EMER. Gemessen gegen ISiK: `Encounter.class` ist an
               # `EncounterClassDE` (de.basisprofil.r4 1.5.3) gebunden, und
               # diese Liste enthaelt genau AMB, HH, SS, VR, IMP, PRENC —
               # kein EMER. Ein kuratiertes Szenario liefert keinen
               # Profilfehler aus. Dass der Katalog EMER trotzdem fuehrt,
               # ist ein eigener Befund und steht in ADR-016 unter Offen.
               begegnungen=[{"art": "IMP", "datum": "2024-01-08"},
                            {"art": "VR", "datum": "2024-01-22"},
                            {"art": "AMB", "datum": "2024-02-19"}],
               diagnosen=[{"code": "84114007", "beginn": "2024-01-08"},
                          {"code": "38341003", "beginn": "2016-05-30"}],
               messwerte=[{"code": "8867-4", "wert": 96.0, "datum": "2024-01-08"},
                          {"code": "2160-0", "wert": 1.4, "datum": "2024-01-09"}],
               medikamente=[{"code": "C09AA05", "beginn": "2016-06-15"}]),
        ]},
    ),
    Szenario(
        name="ohne-kontakt",
        titel="Diagnose ohne Kontakt",
        beschreibung=(
            "Zwei Patienten mit Diagnosen, aber ohne angegebene Kontakte."
        ),
        zeigt=(
            "Der unbequeme Fall: ISiK verlangt über `isik-con1`, dass eine "
            "kodierte Diagnose ihren Kontakt nennt. Der Code ergänzt ihn "
            "(ADR-009) — hier sieht man, dass er es tut."
        ),
        parameter={"patienten": [
            _p("Miroslav", "Nowak", "male", "1979-09-30",
               diagnosen=[{"code": "195967001", "beginn": "2006-04-12"}],
               messwerte=[{"code": "8867-4", "wert": 74.0, "datum": "2024-06-14"}]),
            _p("Elfriede", "Hartmann", "female", "1936-05-07",
               diagnosen=[{"code": "13644009", "beginn": "2001-10-22"}],
               medikamente=[{"code": "C10AA01", "beginn": "2001-11-01"}]),
        ]},
    ),
]

SZENARIEN: dict[str, Szenario] = {s.name: s for s in _EINGEBAUT}


def alle() -> list[Szenario]:
    """Die eingebauten Szenarien, in fester Reihenfolge."""
    return list(_EINGEBAUT)


def hole(name: str) -> Szenario:
    szenario = SZENARIEN.get((name or "").strip())
    if szenario is None:
        bekannt = ", ".join(sorted(SZENARIEN))
        raise SzenarioFehler(f"Unbekanntes Szenario. Bekannt sind: {bekannt}")
    return szenario


def lies(pfad: Path | str) -> Szenario:
    """Lädt ein Szenario aus einer JSON-Datei.

    Für geteilte Vorlagen — das PRD nennt sie „teilbare
    Kohorten-Vorlagen". Geprüft wird die Form, nicht der Inhalt: Ob die
    Codes im Katalog stehen, zeigt erst der Lauf, und zwar als
    Beanstandung.
    """
    p = Path(pfad)
    try:
        roh = json.loads(p.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SzenarioFehler(f"{p} nicht lesbar: {exc}") from exc
    except ValueError as exc:
        raise SzenarioFehler(f"{p} ist kein gültiges JSON: {exc}") from exc
    return Szenario.from_dict(roh)


def baue(szenario: Szenario) -> Ergebnis:
    """Baut die Kohorte des Szenarios — ohne Modellaufruf.

    Derselbe Weg wie ein Modelllauf: `baue_und_pruefe` normalisiert die
    Kennungen, validiert jede Ressource und prüft die Referenzen. Ein
    Szenario bekommt keine Abkürzung; es überspringt nur den Schritt
    davor.
    """
    ergebnis = Ergebnis(beschreibung=szenario.beschreibung)
    ergebnis.szenario = szenario.name
    ergebnis.parameter = szenario.parameter
    ergebnis.angefragt = szenario.patienten
    # KEINE Sollmenge. Naheliegend wäre `{"patienten": szenario.patienten}` —
    # aber `Szenario.patienten` IST die Länge derselben Liste, gegen die
    # `baue_aus_parametern` vergleicht. Der Vergleich könnte nie ausschlagen;
    # er sähe nur nach Prüfung aus. Beim Modelllauf ist er sinnvoll, weil
    # die Sollzahl dort aus einer anderen Quelle stammt (der Rücklesung des
    # Modells) und deshalb abweichen KANN.
    #
    # Dass die gebauten Patienten zur Liste passen, prüft statt dessen
    # `tests/test_szenarien.py` — über den ganzen Bau hinweg, wo ein
    # übersprungener Eintrag tatsächlich sichtbar wird.
    return baue_und_pruefe(szenario.parameter, ergebnis)


def baue_kohorte(szenario: Szenario) -> Kohortenergebnis:
    """Dasselbe für die Kommandozeile.

    Die CLI rechnet durchgehend mit `Kohortenergebnis` (Teile, Mengentreue,
    Namensvielfalt), die Weboberfläche mit `Ergebnis`. Beide Hüllen gibt es
    seit Phase 2, und beide münden in `baue_aus_parametern`.

    Hier wird deshalb NICHT ein dritter Weg gebaut, sondern der vorhandene
    benutzt: `baue_aus_aufzeichnung` mit genau einem Teil. Ein Szenario ist
    aus Sicht des Baus dasselbe wie eine einteilige Aufzeichnung — nur ohne
    die Prüfsummen, die eine Aufzeichnung mitführt.
    """
    ergebnis = baue_aus_aufzeichnung(
        szenario.beschreibung,
        szenario.patienten,
        [TeilParameter(angefragt=szenario.patienten, parameter=szenario.parameter)],
    )
    ergebnis.szenario = szenario.name
    return ergebnis


def unbekannte_codes(szenario: Szenario) -> list[tuple[str, str]]:
    """Codes des Szenarios, die der Katalog nicht führt.

    Ohne diese Prüfung ersetzt `baue_aus_parametern` einen unbekannten
    Code still durch einen anderen und hinterlässt nur eine Beanstandung.
    Das Ergebnis wäre gültiges FHIR mit falschem Inhalt — in einem
    Werkzeug, dessen Produkt die Verlässlichkeit ist, die schlimmste
    Sorte Fehler.

    Die Kataloge werden aus einer Zuordnung geholt und nicht einzeln
    aufgezählt: Käme ein sechster Ressourcentyp hinzu, bliebe eine
    Aufzählung stumm — fünfmal in diesem Projekt geschehen.
    """
    kataloge = {
        "diagnosen": ("code", CONDITION_CODES),
        "messwerte": ("code", OBSERVATION_CODES),
        "medikamente": ("code", MEDICATION_CODES),
        "begegnungen": ("art", ENCOUNTER_CLASSES),
    }
    fehlend: list[tuple[str, str]] = []
    for eintrag in szenario.parameter.get("patienten", []):
        if not isinstance(eintrag, dict):
            continue
        for feld, (schluessel, katalog) in kataloge.items():
            for wert in eintrag.get(feld) or []:
                if not isinstance(wert, dict):
                    continue
                code = str(wert.get(schluessel) or "").strip()
                if code and code not in katalog:
                    fehlend.append((feld, code))
    return fehlend
