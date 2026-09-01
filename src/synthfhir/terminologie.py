"""Die SNOMED-Bindung entscheiden, die ohne Terminologie offen bleibt.

ADR-009 hatte die ISiK-Messung bei **0 Fehlern und 8 ungeprüften Befunden**
abgeschlossen. „Ungeprüft" heißt dort: Der Validator konnte es nicht
entscheiden. Die Ursache ist eine einzige, benannte Bindung —
`ISiKDiagnose` verlangt für `Condition.code.coding:SNOMED-CT` einen Code
aus dem ValueSet `DiagnosesSCT`, und dieses ValueSet ist über drei
`is-a`-Filter definiert. Ein `is-a`-Filter braucht die
SNOMED-Hierarchie; ohne sie meldet HAPI wörtlich:

    Unable to expand ValueSet: cannot apply filters ... because
    CodeSystem 'http://snomed.info/sct' is ignored/not-present

Dieses Modul beantwortet genau diese Frage — und **nur** diese. Es fragt
einen öffentlichen Terminologieserver, ob jeder Diagnosecode des Katalogs
Mitglied des gebundenen ValueSets ist.

===========================================================================
WARUM DAS EIN EIGENES MODUL IST UND NICHT EINE VALIDATOR-EINSTELLUNG
===========================================================================

Der naheliegende Weg wäre, dem messenden HAPI einen entfernten
Terminologieserver mitzugeben. Der wurde versucht und ist eine **Falle**:

| Aufbau | geprüft | Fehler | ungeprüft | Warnungen |
|---|---|---|---|---|
| ohne Terminologie | 11 | 0 | **8** | 19 |
| mit `remote_terminology_service` | 11 | **11** | **0** | **0** |

Die zweite Zeile sieht nach dem Ziel aus — null ungeprüft. Sie ist das
Gegenteil: Jeder der elf Fehler war eine `NullPointerException`, die
Validierung war vollständig abgestürzt. Es wurde **nichts** geprüft, nicht
alles. Das einzige sichtbare Zeichen war, dass auch die 19 Warnungen
verschwanden.

**Ein kaputter Terminologieaufbau erzeugt die schönste Zahl, die dieser
Bericht kennt.** Deshalb misst dieses Modul nicht nur, sondern **weist
nach, dass es gemessen hat** — siehe die Kanarienvögel unten.

===========================================================================
DIE DREI PROBENARTEN
===========================================================================

Eine Messung, die nur „ja" sagen kann, sagt nichts. Geprüft wird deshalb
in drei Richtungen:

1. **Mitglied** — jeder Diagnosecode des Katalogs. Das ist die Frage.
2. **Kein Mitglied** — ein Code, den es in SNOMED wirklich gibt, der aber
   kein Befund ist (`27113001`, *Body weight*). Antwortet der Server hier
   mit „ja", dann entscheidet er nicht, sondern winkt durch.
3. **Erfunden** — `999999999`. Fängt den Fall ab, dass ein Server jeden
   Code kennt, den man ihm zeigt.

Nur wenn **beide** Kanarienvögel richtig verneinen, gilt die Messung als
gültig. Sonst ist `Terminologienachweis.gueltig` falsch, und der Bericht
sagt das, statt eine schöne Zahl zu melden.

===========================================================================
DIE VALUESET-DEFINITION WIRD GEHOLT, NICHT MITGELIEFERT
===========================================================================

Gegen ein selbstgeschriebenes ValueSet zu messen wäre ein Zirkelschluss:
Man bekäme genau die Antwort, die man hineingeschrieben hat. Die
Definition kommt deshalb aus dem Quellrepository der gematik, am Tag der
gemessenen Fassung, und ihre **SHA-256-Summe wird geprüft**. Stimmt sie
nicht, bricht die Messung ab.

Sie wird auch nicht ins Repository gelegt. Das erspart die Frage, unter
welchen Bedingungen fremde Profilinhalte weiterverbreitet werden dürfen —
und es hält die Messung ehrlich: Gemessen wird gegen das, was die gematik
veröffentlicht, nicht gegen eine Kopie davon.

===========================================================================
WAS DIESES MODUL NICHT IST
===========================================================================

**Keine Konformitätsbescheinigung.** Es beantwortet eine Teilfrage — die
Mitgliedschaft im gebundenen ValueSet. Ob eine erzeugte Ressource das
ISiK-Profil insgesamt erfüllt, misst weiterhin `profil.py` gegen einen
Validator.

**Kein Ersatz für die dritte Spalte.** Andere ungeprüfte Befunde können
bestehen bleiben; dieses Modul deckt die SNOMED-Bindung ab und sagt das.

**Nicht für ICD-10-GM.** Nachgemessen führt weder tx.fhir.de noch
tx.fhir.org ein CodeSystem unter `fhir.de` oder `bfarm` — ein `$lookup`
auf `http://fhir.de/CodeSystem/bfarm/icd-10-gm` antwortet mit HTTP 422.
Für die ICD-Kodierung ändert sich also nichts. Das ist kein Mangel dieses
Moduls, sondern der Zustand der öffentlichen Terminologieserver, und es
gehört in den Bericht statt in eine Fußnote.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from .domain.codes import KATALOGE, SNOMED_SYSTEM

# --- Die gemessene ValueSet-Fassung ----------------------------------------
#
# Die Version ist an das Paket gebunden, das `docs/belege/docker-compose.isik.yml`
# lädt (de.gematik.isik-basismodul 4.0.3). Wer das Paket hochzieht, muss
# auch hier hochziehen — sonst misst der Nachweis eine andere Fassung als
# der Validator.
DIAGNOSES_SCT = "https://gematik.de/fhir/isik/ValueSet/DiagnosesSCT"
ISIK_VERSION = "4.0.3"
DIAGNOSES_SCT_QUELLE = (
    "https://raw.githubusercontent.com/gematik/spec-ISiK-Basismodul/"
    "v.4.0.3/Resources/fsh-generated/resources/ValueSet-DiagnosesSCT.json"
)
# Nachgemessen am 2026-09-01. Ändert sich die Datei, bricht die Messung ab,
# statt still gegen etwas anderes zu messen.
DIAGNOSES_SCT_SHA256 = (
    "fee9b527c982a2eec48f64e724200667a4a8722486419e36dddbe3394c92b63b"
)

# --- Die Server ------------------------------------------------------------
#
# tx.fhir.de ist die Vorgabe: Der Terminologieserver von HL7 Deutschland
# führt die **deutsche** SNOMED-Edition (Modul 11000274103), die den
# internationalen Kern enthält und aktueller ist als die internationale
# Fassung auf tx.fhir.org. Für ein deutsch lokalisiertes Werkzeug ist das
# der passende Bezug, und gemessen antwortet er rund viermal schneller.
#
# Beide sind ausdrücklich **ohne Betriebszusage**. HL7 sagt zu tx.fhir.org
# selbst, er sei kein Produktivserver. Deshalb ist der zweite Server
# eingebaut und nicht nur erwähnt: Fällt einer aus, gibt es einen Weg.
SERVER = {
    "de": "https://tx.fhir.de/fhir",
    "org": "https://tx.fhir.org/r4",
}
STANDARD_SERVER = SERVER["de"]

# --- Die Kanarienvögel -----------------------------------------------------
#
# `27113001` (Body weight) ist der wichtigere von beiden: Er existiert in
# SNOMED, ist aber weder Clinical finding noch Event noch Situation — also
# kein Mitglied. Ein Server, der ihn bejaht, entscheidet nicht, sondern
# winkt durch, und genau das muss auffallen.
NICHT_MITGLIED = "27113001"
ERFUNDEN = "999999999"


class TerminologieFehler(RuntimeError):
    """Die Messung konnte nicht stattfinden."""


@dataclass(frozen=True)
class Probe:
    """Eine Frage an den Terminologieserver und ihre Antwort."""

    code: str
    bezeichnung: str
    erwartet: bool
    erhalten: bool | None
    meldung: str = ""

    @property
    def wie_erwartet(self) -> bool:
        return self.erhalten is self.erwartet

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "bezeichnung": self.bezeichnung,
            "erwartet": self.erwartet,
            "erhalten": self.erhalten,
            "wie_erwartet": self.wie_erwartet,
            "meldung": self.meldung,
        }


@dataclass
class Terminologienachweis:
    """Das Ergebnis, samt Beleg, dass tatsächlich gemessen wurde."""

    server: str
    valueset: str
    valueset_version: str
    valueset_sha256: str
    snomed_version: str = ""
    erzeugt: str = ""
    mitglieder: list[Probe] = field(default_factory=list)
    kanarienvoegel: list[Probe] = field(default_factory=list)

    @property
    def gueltig(self) -> bool:
        """Hat die Messung tatsächlich entschieden?

        Nur wahr, wenn **beide** Kanarienvögel richtig verneint haben. Ein
        Server, der alles bejaht, oder eine Verbindung, die still ins Leere
        lief, fällt hier durch — und der Bericht meldet dann keine schöne
        Zahl, sondern dass er nichts gemessen hat.
        """
        return bool(self.kanarienvoegel) and all(
            p.wie_erwartet for p in self.kanarienvoegel
        )

    @property
    def alle_mitglied(self) -> bool:
        return bool(self.mitglieder) and all(p.erhalten is True for p in self.mitglieder)

    @property
    def abweichler(self) -> list[Probe]:
        return [p for p in self.mitglieder if p.erhalten is not True]

    def to_dict(self) -> dict:
        return {
            "server": self.server,
            "valueset": self.valueset,
            "valueset_version": self.valueset_version,
            "valueset_sha256": self.valueset_sha256,
            "snomed_version": self.snomed_version,
            "erzeugt": self.erzeugt,
            "gueltig": self.gueltig,
            "alle_mitglied": self.alle_mitglied,
            "geprueft": len(self.mitglieder),
            "mitglied": sum(1 for p in self.mitglieder if p.erhalten is True),
            "abweichler": [p.to_dict() for p in self.abweichler],
            "kanarienvoegel": [p.to_dict() for p in self.kanarienvoegel],
        }

    def befund(self) -> str:
        """Das Urteil im Klartext — für einen Bericht, den ein Mensch liest."""
        if not self.gueltig:
            schlecht = [p.code for p in self.kanarienvoegel if not p.wie_erwartet]
            return (
                "UNGÜLTIG: Der Terminologieserver hat nicht entschieden. "
                f"Gegenprobe fehlgeschlagen für {', '.join(schlecht)}. "
                "Die Mitgliedschaftszahlen unten bedeuten nichts."
            )
        if self.alle_mitglied:
            return (
                f"Alle {len(self.mitglieder)} Diagnosecodes sind Mitglied von "
                f"{self.valueset}|{self.valueset_version}."
            )
        namen = ", ".join(f"{p.code}" for p in self.abweichler)
        return (
            f"{len(self.abweichler)} von {len(self.mitglieder)} Diagnosecodes "
            f"sind KEIN Mitglied: {namen}"
        )


def hole_valueset(quelle: str = DIAGNOSES_SCT_QUELLE, *, zeitgrenze: float = 60.0) -> dict:
    """Holt die ValueSet-Definition und prüft ihre Prüfsumme.

    Nicht aus dem Repository, sondern von der gematik — gegen eine Kopie
    zu messen wäre ein Zirkelschluss, und mitzuliefern wäre
    Weiterverbreitung fremder Profilinhalte.
    """
    try:
        antwort = requests.get(quelle, timeout=zeitgrenze)
    except requests.exceptions.RequestException as exc:
        raise TerminologieFehler(f"ValueSet nicht abrufbar: {exc}") from exc
    if antwort.status_code != 200:
        raise TerminologieFehler(
            f"ValueSet nicht abrufbar (HTTP {antwort.status_code})."
        )
    gefunden = hashlib.sha256(antwort.content).hexdigest()
    if gefunden != DIAGNOSES_SCT_SHA256:
        raise TerminologieFehler(
            "Die ValueSet-Definition hat sich geändert.\n"
            f"  erwartet: {DIAGNOSES_SCT_SHA256}\n"
            f"  erhalten: {gefunden}\n"
            "Gemessen wird gegen eine bekannte Fassung. Wer die Fassung "
            "hochzieht, prüft die Codes neu und setzt die Summe hier nach."
        )
    return json.loads(antwort.content)


def _frage(server: str, valueset: dict, code: str, zeitgrenze: float) -> tuple[bool | None, str]:
    """Eine Mitgliedschaftsfrage. Gibt (Antwort, Meldung) zurück."""
    rumpf = {
        "resourceType": "Parameters",
        "parameter": [
            {"name": "coding", "valueCoding": {"system": SNOMED_SYSTEM, "code": code}},
            {"name": "valueSet", "resource": valueset},
        ],
    }
    try:
        antwort = requests.post(
            f"{server}/ValueSet/$validate-code",
            json=rumpf,
            headers={"Accept": "application/fhir+json"},
            timeout=zeitgrenze,
        )
    except requests.exceptions.RequestException as exc:
        raise TerminologieFehler(f"{server} nicht erreichbar: {exc}") from exc
    if antwort.status_code != 200:
        raise TerminologieFehler(
            f"{server} antwortete mit HTTP {antwort.status_code} für {code}."
        )
    try:
        werte = {
            p["name"]: p.get("valueBoolean", p.get("valueString", ""))
            for p in antwort.json().get("parameter", [])
        }
    except ValueError as exc:
        raise TerminologieFehler(f"{server} antwortete nicht mit JSON.") from exc
    # `result` fehlt, wenn der Server die Frage gar nicht beantwortet hat.
    # Das als False zu lesen wäre der stille Fehler: Es sähe aus wie „kein
    # Mitglied" und wäre „nicht gefragt".
    return werte.get("result"), str(werte.get("message", ""))


def weise_nach(
    *,
    server: str = STANDARD_SERVER,
    zeitgrenze: float = 60.0,
    zeitpunkt: datetime | None = None,
) -> Terminologienachweis:
    """Prüft jeden Diagnosecode des Katalogs gegen die ISiK-Bindung.

    Die Proben sind an den **Katalog** gekoppelt, nicht an eine feste
    Liste. Kommt ein Code hinzu, wird er mitgeprüft — eine Handaufzählung
    hätte ihn übersehen, und genau das ist in diesem Projekt schon
    fünfmal passiert.
    """
    valueset = hole_valueset(zeitgrenze=zeitgrenze)
    jetzt = zeitpunkt or datetime.now(timezone.utc)

    nachweis = Terminologienachweis(
        server=server,
        valueset=DIAGNOSES_SCT,
        valueset_version=ISIK_VERSION,
        valueset_sha256=DIAGNOSES_SCT_SHA256,
        erzeugt=jetzt.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
    )

    # Zuerst die Kanarienvögel. Scheitern sie, ist alles Weitere wertlos —
    # aber es wird trotzdem gemessen, damit der Bericht zeigt, was der
    # Server geantwortet hat.
    for code, bezeichnung, erwartet in (
        (NICHT_MITGLIED, "Body weight (existiert, kein Befund)", False),
        (ERFUNDEN, "erfundener Code", False),
    ):
        ergebnis, meldung = _frage(server, valueset, code, zeitgrenze)
        nachweis.kanarienvoegel.append(
            Probe(code, bezeichnung, erwartet, ergebnis, meldung)
        )

    for eintrag in KATALOGE["conditions"].values():
        ergebnis, meldung = _frage(server, valueset, eintrag.code, zeitgrenze)
        if not nachweis.snomed_version:
            nachweis.snomed_version = _version(server, valueset, eintrag.code, zeitgrenze)
        nachweis.mitglieder.append(
            Probe(eintrag.code, eintrag.display_de, True, ergebnis, meldung)
        )
    return nachweis


def _version(server: str, valueset: dict, code: str, zeitgrenze: float) -> str:
    """Welche SNOMED-Fassung der Server benutzt hat.

    Gehört in den Bericht: „Mitglied" ist eine Aussage über eine Edition,
    nicht über SNOMED an sich. tx.fhir.de antwortet mit der deutschen
    Edition, tx.fhir.org mit der internationalen.
    """
    rumpf = {
        "resourceType": "Parameters",
        "parameter": [
            {"name": "coding", "valueCoding": {"system": SNOMED_SYSTEM, "code": code}},
            {"name": "valueSet", "resource": valueset},
        ],
    }
    try:
        antwort = requests.post(
            f"{server}/ValueSet/$validate-code", json=rumpf, timeout=zeitgrenze
        )
        for p in antwort.json().get("parameter", []):
            if p["name"] == "version":
                return str(p.get("valueString", ""))
    except (requests.exceptions.RequestException, ValueError):
        pass
    return ""
