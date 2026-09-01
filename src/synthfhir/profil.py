"""Profilkonformität messen — wiederholbar statt einmalig (Phase 3).

Dieses Modul ändert **keine einzige erzeugte Ressource**. Es misst nur, wie
weit die heutige Ausgabe von den ISiK-Profilen der gematik entfernt ist,
und schreibt das Ergebnis so auf, dass man es wiederholen und vergleichen
kann.

===========================================================================
WARUM DREI SPALTEN UND NICHT ZWEI
===========================================================================

Die naheliegende Auswertung wäre „Fehler" gegen „keine Fehler". Sie wäre
hier irreführend.

Der Validator kann drei Dinge sagen, nicht zwei:

  **Fehler**      Das ist falsch.
  **Ungeprüft**   Das kann ich nicht entscheiden.
  **Warnung**     Das ist erlaubt, aber unüblich.

Die mittlere Antwort ist bei diesem Projekt keine Randerscheinung, sondern
der Regelfall. Das ISiK-Profil bindet `Condition.code` an ein
SNOMED-ValueSet mit `is-a`-Filtern. Ohne SNOMED-Terminologie kann der
Server dieses ValueSet nicht auflösen — er sagt das ausdrücklich und meldet
den Code danach als „nicht gefunden". Beides trägt `severity: error`, und
beides ist **kein Nachweis**, dass etwas falsch ist.

Ein Bericht, der solche Befunde als Fehler zählt, macht das Ergebnis
schlechter, als es ist. Ein Bericht, der sie stillschweigend verschweigt,
macht es besser. Beides wäre Schönfärberei mit Zahlen — die dritte Spalte
ist die einzige ehrliche Form.

===========================================================================
WANN GILT EIN BEFUND ALS UNGEPRÜFT
===========================================================================

Nicht nach Gefühl, sondern nach einer Regel, die der Validator selbst
liefert:

1. Sagt er in **diesem Lauf** zu einem ValueSet, dass er es nicht auflösen
   kann, gelten alle weiteren Befunde zu **genau diesem ValueSet** als
   ungeprüft.
2. Meldet er ein unbekanntes CodeSystem, gilt derselbe Befund als
   ungeprüft.

Ein „nicht im ValueSet enthalten" ohne vorangegangene Auflösungsklage
bleibt ein **Fehler**. Sonst ließe sich jede Bindungsverletzung wegdeuten.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

# ISiK-Basismodul der gematik. Die Stufe ist Teil des Berichts, nicht eine
# Nebensache: Die kanonischen Profil-URLs unterscheiden sich zwischen den
# Stufen (Stufe 3 trägt `/isik/v3/Basismodul/`, Stufe 4 nur `/isik/`), und
# tragend ist derzeit Stufe 3.
PAKET = "de.gematik.isik-basismodul"
PAKETVERSION = "4.0.3"

_SD = "https://gematik.de/fhir/isik/StructureDefinition/"

PROFILE = {
    "Patient": _SD + "ISiKPatient",
    "Encounter": _SD + "ISiKKontaktGesundheitseinrichtung",
    "Condition": _SD + "ISiKDiagnose",
    # Das Medikationsmodul profiliert MedicationStatement. Nachgemessen
    # erfüllt unsere Ausgabe es bereits ohne jede Änderung — anders als
    # zunächst aus dem Differential gelesen, verlangt
    # `medication[x].reference` keine Medication-Ressource, sondern gilt
    # nur, FALLS eine Referenz benutzt wird.
    "MedicationStatement": _SD + "ISiKMedikationsInformation",
}

# Die weiteren Module. Sie werden vom Messserver zusätzlich geladen.
MODULE = {
    "de.gematik.isik-basismodul": "4.0.3",
    "de.gematik.isik-vitalparameter": "4.0.2",
    "de.gematik.isik-medikation": "4.0.3",
}

# Observation ist der Sonderfall: Das Vitalparameter-Modul profiliert nicht
# „Observation", sondern **je Vitalparameter einzeln**. Welches Profil gilt,
# entscheidet also der LOINC-Code der einzelnen Ressource — nicht ihr Typ.
#
# Für die 20 Laborwerte des Katalogs gibt es hier nichts: Zuständig wäre
# das Modul ISiK Labor, und das ist nicht Teil dieses Auftrags. Sie bleiben
# unprofiliert, und der Bericht sagt das je Ressource.
VITALPROFILE = {
    "85354-9": _SD + "ISiKBlutdruckSystemischArteriell",
    "8867-4": _SD + "ISiKHerzfrequenz",
    "29463-7": _SD + "ISiKKoerpergewicht",
    "8302-2": _SD + "ISiKKoerpergroesse",
}

LOINC = "http://loinc.org"


def profil_fuer(ressource: dict) -> str | None:
    """Das Profil dieser einen Ressource, oder `None`.

    Je **Ressource**, nicht je Typ. Bis ADR-014 genügte eine Zuordnung
    nach Ressourcentyp; das Vitalparameter-Modul kennt aber für jeden
    Vitalparameter ein eigenes Profil, und für Laborwerte gar keines.
    Derselbe Typ trägt damit beides.
    """
    typ = ressource.get("resourceType")
    if typ in PROFILE:
        return PROFILE[typ]
    if typ != "Observation":
        return None
    for coding in (ressource.get("code") or {}).get("coding", []):
        if coding.get("system") == LOINC:
            treffer = VITALPROFILE.get(coding.get("code"))
            if treffer:
                return treffer
    return None

TIMEOUT_S = 180.0

# Der Validator kann ein ValueSet nicht auflösen.
_NICHT_AUFLOESBAR = re.compile(
    r"Unable to expand ValueSet|cannot apply filters|CodeSystem is unknown"
    r"|is ignored|not able to check|Unknown code system",
    re.IGNORECASE,
)
# Zu welchem ValueSet gehört ein Befund?
_VALUESET = re.compile(r"(?:value set|ValueSet)[ :'\"]*([A-Za-z0-9:/._|-]+)")


@dataclass
class Befund:
    """Ein einzelner Befund des Validators."""

    schweregrad: str
    meldung: str
    ort: str
    ungeprueft: bool = False

    def to_dict(self) -> dict:
        return {
            "schweregrad": self.schweregrad,
            "ort": self.ort,
            "ungeprueft": self.ungeprueft,
            "meldung": self.meldung,
        }


@dataclass
class Profilergebnis:
    """Was die Prüfung einer Ressource gegen ein Profil ergeben hat."""

    ressourcentyp: str
    kennung: str
    profil: str | None
    befunde: list[Befund] = field(default_factory=list)

    @property
    def fehler(self) -> list[Befund]:
        return [
            b for b in self.befunde
            if b.schweregrad in ("error", "fatal") and not b.ungeprueft
        ]

    @property
    def ungeprueft(self) -> list[Befund]:
        return [b for b in self.befunde if b.ungeprueft]

    @property
    def warnungen(self) -> list[Befund]:
        return [
            b for b in self.befunde
            if b.schweregrad not in ("error", "fatal") and not b.ungeprueft
        ]

    @property
    def konform(self) -> bool:
        """Kein Fehler — was nicht heißt: nachgewiesen konform.

        Solange Befunde ungeprüft sind, ist das Urteil unvollständig. Der
        Bericht weist beides getrennt aus, damit der Unterschied nicht
        verlorengeht.
        """
        return not self.fehler

    def to_dict(self) -> dict:
        return {
            "ressourcentyp": self.ressourcentyp,
            "kennung": self.kennung,
            "profil": self.profil,
            "fehler": len(self.fehler),
            "ungeprueft": len(self.ungeprueft),
            "warnungen": len(self.warnungen),
            "befunde": [b.to_dict() for b in self.befunde],
        }


@dataclass
class Profilbericht:
    """Ein vollständiger, wiederholbarer Messbericht."""

    erzeugt: str
    server: str
    fhir_version: str
    paket: str
    paketversion: str
    terminologieserver: str
    # Alle Module, die Profile beisteuern. Seit ADR-014 sind es drei; der
    # Kopf „gemessen gegen das Basismodul" wäre sonst eine unzutreffende
    # Angabe über den eigenen Messaufbau.
    module: dict[str, str] = field(default_factory=dict)
    ergebnisse: list[Profilergebnis] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)

    def summe(self, feld: str) -> int:
        return sum(len(getattr(e, feld)) for e in self.ergebnisse)

    @property
    def je_typ(self) -> dict[str, dict[str, int]]:
        aus: dict[str, dict[str, int]] = {}
        for e in self.ergebnisse:
            z = aus.setdefault(
                e.ressourcentyp,
                {"geprueft": 0, "fehler": 0, "ungeprueft": 0, "warnungen": 0},
            )
            z["geprueft"] += 1
            z["fehler"] += len(e.fehler)
            z["ungeprueft"] += len(e.ungeprueft)
            z["warnungen"] += len(e.warnungen)
        return aus

    def to_dict(self) -> dict:
        return {
            "erzeugt": self.erzeugt,
            "server": self.server,
            "fhir_version": self.fhir_version,
            "paket": self.paket,
            "paketversion": self.paketversion,
            "module": self.module,
            "terminologieserver": self.terminologieserver,
            "hinweis": (
                "Synthetische Testdaten. 'ungeprueft' heißt: Der Validator "
                "konnte es nicht entscheiden — nicht, dass es richtig ist."
            ),
            "summe": {
                "geprueft": len(self.ergebnisse),
                "fehler": self.summe("fehler"),
                "ungeprueft": self.summe("ungeprueft"),
                "warnungen": self.summe("warnungen"),
            },
            "je_typ": self.je_typ,
            "hinweise": self.hinweise,
            "ergebnisse": [e.to_dict() for e in self.ergebnisse],
        }


class ProfilFehler(RuntimeError):
    """Die Profilprüfung ließ sich nicht durchführen."""


def _valuesets_ohne_aufloesung(issues: list[dict]) -> set[str]:
    """Welche ValueSets konnte der Validator in DIESEM Lauf nicht auflösen?

    Nur wer hier steht, darf später als „ungeprüft" gelten. Ohne diese
    Einschränkung ließe sich jede Bindungsverletzung wegdeuten.
    """
    offen: set[str] = set()
    for i in issues:
        text = _text(i)
        if _NICHT_AUFLOESBAR.search(text):
            treffer = _VALUESET.search(text)
            offen.add(treffer.group(1) if treffer else "*")
    return offen


def _text(issue: dict) -> str:
    return (
        issue.get("diagnostics")
        or (issue.get("details") or {}).get("text")
        or ""
    )


def _ort(issue: dict) -> str:
    orte = issue.get("expression") or issue.get("location") or []
    return orte[0] if orte else "?"


def bewerte(issues: list[dict]) -> list[Befund]:
    """Ordnet die Befunde des Validators den drei Spalten zu."""
    offen = _valuesets_ohne_aufloesung(issues)
    befunde = []
    for i in issues:
        text = _text(i)
        ungeprueft = bool(_NICHT_AUFLOESBAR.search(text))
        if not ungeprueft and offen:
            # „nicht im ValueSet gefunden" zählt nur dann als ungeprüft,
            # wenn genau dieses ValueSet in diesem Lauf nicht auflösbar war.
            treffer = _VALUESET.search(text)
            if treffer and ("*" in offen or treffer.group(1) in offen):
                ungeprueft = True
        befunde.append(
            Befund(
                schweregrad=str(i.get("severity") or "error").lower(),
                meldung=text,
                ort=_ort(i),
                ungeprueft=ungeprueft,
            )
        )
    return befunde


def pruefe_gegen_profile(
    ressourcen: list[dict],
    server: str,
    *,
    zeitpunkt: datetime | None = None,
) -> Profilbericht:
    """Prüft jede Ressource gegen ihr ISiK-Profil und berichtet."""
    basis = server.rstrip("/")
    s = requests.Session()
    s.headers.update(
        {"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"}
    )

    try:
        antwort = s.get(f"{basis}/metadata", timeout=TIMEOUT_S)
        cap = antwort.json()
    except (requests.exceptions.RequestException, ValueError) as exc:
        raise ProfilFehler(f"Profilserver {basis} antwortet nicht: {exc}") from exc
    if cap.get("resourceType") != "CapabilityStatement":
        raise ProfilFehler(f"{basis} ist kein FHIR-Server.")

    jetzt = zeitpunkt or datetime.now(timezone.utc)
    if jetzt.tzinfo is None:
        raise ProfilFehler("zeitpunkt braucht eine Zeitzone.")

    bericht = Profilbericht(
        erzeugt=jetzt.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        server=basis,
        fhir_version=str(cap.get("fhirVersion") or "unbekannt"),
        paket=PAKET,
        paketversion=PAKETVERSION,
        module=dict(MODULE),
        # Ohne Terminologieserver bleibt jede Bindung an SNOMED, LOINC,
        # ICD-10-GM und ATC ungeprüft. Das gehört in den Bericht, nicht in
        # eine Fußnote.
        terminologieserver="keiner",
    )

    # Je RESSOURCE gezählt, nicht je Typ: Ein Observation-Satz kann zur
    # Hälfte profiliert sein (Vitalparameter) und zur Hälfte nicht
    # (Laborwerte). Die alte Meldung „für Observation gibt es kein Profil"
    # wäre jetzt schlicht falsch.
    unprofiliert: dict[str, int] = {}
    for r in ressourcen:
        if profil_fuer(r) is None:
            typ = str(r.get("resourceType"))
            unprofiliert[typ] = unprofiliert.get(typ, 0) + 1
    for typ, anzahl in sorted(unprofiliert.items()):
        bericht.hinweise.append(
            f"{anzahl} {typ}-Ressource(n) ohne Profil in den geladenen "
            "Modulen. Für Laborwerte wäre das Modul ISiK Labor zuständig; "
            "es ist nicht geladen."
        )

    for r in ressourcen:
        typ = r.get("resourceType")
        profil = profil_fuer(r)
        if not profil:
            continue
        antwort = s.post(
            f"{basis}/{typ}/$validate",
            params={"profile": profil},
            data=json.dumps(r, ensure_ascii=False).encode("utf-8"),
            timeout=TIMEOUT_S,
        )
        try:
            oo = antwort.json()
        except ValueError as exc:
            raise ProfilFehler(
                f"{typ}/$validate lieferte kein JSON (HTTP {antwort.status_code})"
            ) from exc
        issues = oo.get("issue", []) if oo.get("resourceType") == "OperationOutcome" else []
        bericht.ergebnisse.append(
            Profilergebnis(
                ressourcentyp=str(typ),
                kennung=str(r.get("id") or "?"),
                profil=profil,
                befunde=bewerte(issues),
            )
        )

    return bericht
