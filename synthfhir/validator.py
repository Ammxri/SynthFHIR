"""Anbindung an den HAPI-FHIR-Validator (Abschnitt 6.5) – Lernmodus-Komponente.

===========================================================================
KONZEPT 1: Was ist `$validate` überhaupt?
===========================================================================

FHIR kennt neben den normalen REST-Operationen (GET/POST/PUT auf Ressourcen)
sogenannte *Operations*. Sie werden mit einem Dollarzeichen adressiert. Der
Aufruf sieht aus wie ein Anlegen, hat aber keine Nebenwirkung:

    POST http://localhost:8080/fhir/Observation/$validate
    Content-Type: application/fhir+json

    { "resourceType": "Observation", ... }

Der Server legt nichts an. Er prüft die Ressource gegen die
StructureDefinition ihres Typs und antwortet mit genau einer Ressource:
einem `OperationOutcome`.

Wichtig: Der Endpunkt liegt unter dem RESSOURCENTYP. `Observation/$validate`
prüft gegen die Observation-Definition. Deshalb muss der Code den Typ aus
der Ressource lesen und die URL daraus bauen – schickt man eine Observation
an `Patient/$validate`, prüft der Server gegen das falsche Profil.

Was der Server prüft:
  * Kardinalitäten (Pflichtfelder vorhanden, Obergrenzen eingehalten)
  * Datentypen und deren Formate (date, dateTime, decimal, code …)
  * unbekannte Elemente (Feld, das es in FHIR gar nicht gibt)
  * Invarianten (die con-*/obs-*-Regeln aus der Spezifikation)
  * Bindings, soweit die Terminologie dem Server bekannt ist

Was der Server NICHT prüft:
  * ob eine Referenz auf eine existierende Ressource zeigt (dazu müsste er
    die Zielressource kennen – siehe integrity.py)
  * ob der Inhalt klinisch plausibel ist

===========================================================================
KONZEPT 2: Wie ist ein `OperationOutcome` aufgebaut?
===========================================================================

    {
      "resourceType": "OperationOutcome",
      "issue": [
        {
          "severity":    "error",
          "code":        "structure",
          "diagnostics": "Observation.status: minimum required = 1, but only found 0",
          "expression":  ["Observation.status"]
        }
      ]
    }

`issue` ist eine Liste. Jeder Eintrag ist ein Befund, kein Ergebnis: Der
OperationOutcome sagt nirgends "valide" oder "invalide". Diese Entscheidung
trifft der aufrufende Code anhand der Schweregrade.

  severity     fatal | error | warning | information
  code         grobe Fehlerklasse (structure, required, value, invariant,
               code-invalid, processing …)
  diagnostics  Klartext – das ist der Teil, der in der Korrekturschleife an
               das LLM zurückgeht
  expression   FHIRPath-Ausdruck auf die Fundstelle, z. B.
               "Observation.valueQuantity.code". Der wertvollste Teil,
               weil er den FEHLERORT nennt und nicht nur die Beschreibung.

===========================================================================
KONZEPT 3: Wie sind die Schweregrade zu interpretieren?
===========================================================================

Die Festlegung dieses Spikes (Abschnitt 6.5):

  fatal, error        -> Ressource gilt als INVALIDE
  warning, information-> wird protokolliert, ist aber kein Fehlschlag

Das ist keine Willkür, sondern folgt der FHIR-Semantik: `error` heißt "das
verletzt die Spezifikation", `warning` heißt "das ist erlaubt, aber
verdächtig". Der wichtigste Praxisfall dafür ist Terminologie: Ein HAPI-
Server ohne geladene LOINC-/SNOMED-Pakete kann Codes nicht nachschlagen und
meldet "unable to validate code" als WARNUNG. Ein erfundener LOINC-Code
fällt damit nicht als Fehler auf. Das ist eine echte Grenze der Messung –
und genau deshalb hält der Bericht codebezogene Befunde getrennt fest.

Zwei praktische Eigenheiten von HAPI, die der Code abfangen muss:

  * Der HTTP-Status ist nicht verlässlich. Je nach Version antwortet HAPI
    mit 200 (auch bei Fehlern) oder mit 412/422. Maßgeblich ist immer der
    Inhalt des OperationOutcome, nicht der Statuscode.
  * Ist gar keine Beanstandung enthalten oder nur eine mit
    severity=information ("No issues detected"), ist die Ressource valide.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests

FHIR_JSON = "application/fhir+json"

BLOCKING_SEVERITIES = ("fatal", "error")

# Einordnung eines Befundes für die Fehlergruppierung im Bericht.
#
# Die Reihenfolge ist entscheidend und vom SPEZIFISCHEN zum ALLGEMEINEN
# sortiert. Grund: HAPI-Meldungen enthalten das Wort "code" auch dann, wenn
# es gar nicht um Terminologie geht – "Observation.code: minimum required =
# 1, but only found 0" ist ein Kardinalitätsfehler. Würde man zuerst auf
# "code" prüfen, landete er in der Terminologie-Kategorie und verfälschte
# das Ampelkriterium "erfundene/beanstandete Codes".
CATEGORY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        # Härtester Fall: der Server konnte die Ressource nicht einmal als
        # FHIR einlesen. Eigene Klasse, weil dann gar keine inhaltliche
        # Prüfung stattgefunden hat – ein qualitativ anderer Fehler als ein
        # fehlendes Pflichtfeld.
        "nicht als FHIR parsbar",
        re.compile(r"failed to parse|cannot be parsed as|not a valid json|parse request body", re.I),
    ),
    (
        "pflichtfeld/kardinalität",
        re.compile(r"minimum required|maximum allowed|cardinalit|is required but", re.I),
    ),
    (
        "invariante",
        re.compile(r"constraint failed|invariant|\b(?:dom|con|obs|bdl|ref|ele|ext)-\d+\b", re.I),
    ),
    (
        "unbekanntes element",
        re.compile(
            r"unrecognised|unrecognized|unknown (?:element|property|attribute)"
            r"|not a valid property|is not allowed here",
            re.I,
        ),
    ),
    (
        "terminologie/code",
        re.compile(
            r"codesystem|value ?set|terminolog|unknown code|code is unknown"
            r"|unable to validate code|not in the value|binding|display|coding",
            re.I,
        ),
    ),
    (
        "datentyp/format",
        re.compile(
            r"not a valid|does not match|type mismatch|expected .* but|regex|primitive"
            r"|cannot be parsed|wrong type",
            re.I,
        ),
    ),
    ("referenz", re.compile(r"reference|cannot resolve|target of the reference", re.I)),
]

# HAPI schickt die eigentliche Fehlerkennung nicht in `issue.code` (dort steht
# meist nur das generische "processing"), sondern als Coding aus diesem System.
MESSAGE_ID_SYSTEM = "http://hl7.org/fhir/java-core-messageId"

# Kennung -> Kategorie. Zuverlässiger als jede Textsuche, deshalb zuerst.
MESSAGE_ID_CATEGORIES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Profile_Minimum|Profile_Maximum|_MIN_|_MAX_", re.I), "pflichtfeld/kardinalität"),
    (re.compile(r"Terminology|_TX_|CodeSystem|ValueSet", re.I), "terminologie/code"),
    (re.compile(r"#(?:dom|con|obs|bdl|ref|ele|ext)-\d+", re.I), "invariante"),
    (re.compile(r"Unknown_?Element|Unrecogni[sz]ed", re.I), "unbekanntes element"),
    (re.compile(r"Reference", re.I), "referenz"),
]

_QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")
_NUMBER_RE = re.compile(r"\d+")
# Viele HAPI-Meldungen beginnen mit dem genauen FHIRPath, obwohl `expression`
# nur den Ressourcentyp nennt. Der Pfad aus dem Text ist die bessere Fundstelle.
_PATH_PREFIX_RE = re.compile(r"^([A-Z][A-Za-z]+(?:\.[A-Za-z][A-Za-z0-9\[\]]*)+)\s*:")
# HAPI hängt an viele Meldungen "(from http://hl7.org/fhir/…|4.0.1)" an. Für die
# Gruppierung ist das Rauschen und würde die lesbare Kurzform auffressen.
_PROFILE_SUFFIX_RE = re.compile(r"\s*\(from https?://\S+?\)\s*$")


class ValidatorUnavailableError(RuntimeError):
    """Der Validierungsserver ist nicht erreichbar oder antwortet unbrauchbar.

    Führt laut Abschnitt 8 zum Abbruch des Laufs – keine stillen Fehlschläge.
    """


@dataclass(frozen=True)
class Issue:
    """Ein einzelner Befund aus dem OperationOutcome."""

    severity: str
    code: str | None
    diagnostics: str
    expression: str | None
    message_id: str | None = None

    @property
    def blocking(self) -> bool:
        return self.severity in BLOCKING_SEVERITIES

    def location(self) -> str:
        """Beste verfügbare Fundstelle.

        `expression` nennt bei HAPI oft nur den Ressourcentyp, während der
        Klartext mit dem genauen Pfad beginnt ("Observation.status: …").
        Der genauere Pfad gewinnt.
        """
        match = _PATH_PREFIX_RE.match(self.diagnostics.strip())
        if match:
            return match.group(1)
        return self.expression or "?"

    def category(self) -> str:
        """Fehlerklasse für die Gruppierung im Bericht."""
        if self.message_id:
            for pattern, name in MESSAGE_ID_CATEGORIES:
                if pattern.search(self.message_id):
                    return name
        haystack = f"{self.code or ''} {self.diagnostics}"
        for name, pattern in CATEGORY_PATTERNS:
            if pattern.search(haystack):
                return name
        return "sonstiges"

    def signature(self) -> str:
        """Normalisierte Kurzform, damit gleichartige Fehler zusammenfallen.

        Konkrete Werte und Zahlen werden entfernt: "Unknown code 'X'" und
        "Unknown code 'Y'" sollen als ein Fehlertyp gezählt werden. Liegt eine
        HAPI-Fehlerkennung vor, ist sie der verlässlichere Gruppierungs-
        schlüssel und steht deshalb vorn.
        """
        text = _PROFILE_SUFFIX_RE.sub("", self.diagnostics)
        text = _QUOTED_RE.sub("'…'", text)
        text = _NUMBER_RE.sub("#", text)
        text = " ".join(text.split())
        head = f"[{self.severity}] {self.location()}"
        if self.message_id:
            return f"{head} · {self.message_id}: {text[:110]}"
        return f"{head}: {text[:140]}"

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "message_id": self.message_id,
            "diagnostics": self.diagnostics,
            "expression": self.expression,
            "location": self.location(),
            "category": self.category(),
        }


@dataclass
class ValidationResult:
    """Auswertung einer einzelnen Validierung."""

    resource_type: str
    resource_id: str
    issues: list[Issue] = field(default_factory=list)
    outcome: dict = field(default_factory=dict)
    http_status: int = 0
    duration_s: float = 0.0

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.blocking]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def error_count(self) -> int:
        return len(self.errors)

    def to_dict(self) -> dict:
        return {
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "is_valid": self.is_valid,
            "error_count": self.error_count,
            "warning_count": len(self.warnings),
            "http_status": self.http_status,
            "duration_s": round(self.duration_s, 3),
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def format_for_llm(self) -> str:
        """Fehlermeldungen in der Form, in der sie ans Modell zurückgehen.

        Bewusst nur die blockierenden Befunde: Warnungen würden das Modell
        zu Änderungen verleiten, die nichts verbessern, aber neue Fehler
        einbauen können.
        """
        lines = []
        for index, issue in enumerate(self.errors, start=1):
            location = issue.expression or "(keine Fundstelle angegeben)"
            lines.append(f"{index}. [{issue.severity}] at {location}\n   {issue.diagnostics}")
        return "\n".join(lines) if lines else "(keine Fehler)"


class HapiValidator:
    """HTTP-Anbindung an den lokalen HAPI-FHIR-Server."""

    def __init__(self, base_url: str, timeout_s: float = 60.0, readiness_timeout_s: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.readiness_timeout_s = readiness_timeout_s
        self.session = requests.Session()
        self.session.headers.update({"Accept": FHIR_JSON, "Content-Type": FHIR_JSON})

    # -- Bereitschaftsprüfung (Abschnitt 6.5) ------------------------------
    def wait_until_ready(self, poll_interval_s: float = 3.0, verbose: bool = True) -> str:
        """Wartet, bis der Server eine CapabilityStatement liefert.

        Gibt die FHIR-Version des Servers zurück. Wirft
        `ValidatorUnavailableError`, wenn der Server nicht rechtzeitig
        antwortet – der Lauf darf dann gar nicht erst beginnen.
        """
        deadline = time.monotonic() + self.readiness_timeout_s
        last_error = "keine Antwort"
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            try:
                response = self.session.get(f"{self.base_url}/metadata", timeout=self.timeout_s)
                if response.status_code == 200:
                    body = response.json()
                    if body.get("resourceType") == "CapabilityStatement":
                        return str(body.get("fhirVersion", "unbekannt"))
                    last_error = f"unerwartete Antwort: {body.get('resourceType')!r}"
                else:
                    last_error = f"HTTP {response.status_code}"
            except requests.exceptions.RequestException as exc:
                last_error = type(exc).__name__
            except json.JSONDecodeError:
                last_error = "Antwort war kein JSON"
            if verbose and attempt == 1:
                print(f"  Warte auf HAPI unter {self.base_url} …")
            time.sleep(poll_interval_s)

        raise ValidatorUnavailableError(
            f"Validierungsserver unter {self.base_url} nicht erreichbar "
            f"({last_error}).\n"
            "  -> Läuft Docker Desktop?\n"
            "  -> Server starten mit:  docker compose up -d\n"
            "  -> Startfortschritt:    docker compose logs -f hapi"
        )

    # -- Validierung --------------------------------------------------------
    def validate(self, resource: dict) -> ValidationResult:
        """Schickt eine Ressource an `$validate` und wertet das Ergebnis aus."""
        resource_type = resource.get("resourceType")
        resource_id = str(resource.get("id") or "(ohne id)")

        if not isinstance(resource_type, str) or not resource_type:
            # Ohne Typ lässt sich der Endpunkt nicht bilden. Das ist ein
            # Befund über die Ressource, kein Infrastrukturproblem.
            return ValidationResult(
                resource_type="(fehlt)",
                resource_id=resource_id,
                issues=[
                    Issue(
                        severity="error",
                        code="structure",
                        diagnostics="Die Ressource hat kein Feld 'resourceType'.",
                        expression=None,
                    )
                ],
            )

        url = f"{self.base_url}/{resource_type}/$validate"
        started = time.perf_counter()
        try:
            response = self.session.post(
                url,
                data=json.dumps(resource, ensure_ascii=False).encode("utf-8"),
                timeout=self.timeout_s,
            )
        except requests.exceptions.RequestException as exc:
            raise ValidatorUnavailableError(
                f"Validierung von {resource_type}/{resource_id} fehlgeschlagen: {exc}"
            ) from exc
        duration = time.perf_counter() - started

        # Wichtig: NICHT am Statuscode entscheiden. HAPI antwortet je nach
        # Version mit 200, 400, 412 oder 422 – und auf besonders kaputte
        # Eingaben auch mit 500, dann aber ebenfalls mit einem verwertbaren
        # OperationOutcome. Wer solche Fälle als Serverproblem behandelt,
        # verliert wegen einer einzigen Ressource die ganze Messreihe
        # (Abschnitt 8). Maßgeblich ist deshalb der Antwortinhalt.
        try:
            body = response.json()
        except ValueError:
            raise ValidatorUnavailableError(
                f"Antwort von {url} war kein JSON (HTTP {response.status_code}, "
                f"Anfang: {response.text[:200]!r})."
            ) from None

        if body.get("resourceType") != "OperationOutcome":
            if response.status_code >= 500:
                raise ValidatorUnavailableError(
                    f"Der Validierungsserver antwortete mit HTTP {response.status_code} "
                    f"auf {url} und ohne OperationOutcome. Serverproblem, kein "
                    "Ressourcenfehler."
                )
            if response.status_code == 404:
                # Unbekannter Ressourcentyp: der Server kennt den Endpunkt
                # nicht. Das ist ein Befund über die Ressource.
                return ValidationResult(
                    resource_type=resource_type,
                    resource_id=resource_id,
                    issues=[
                        Issue(
                            severity="error",
                            code="not-supported",
                            diagnostics=(
                                f"Der Server kennt den Ressourcentyp {resource_type!r} nicht."
                            ),
                            expression=resource_type,
                        )
                    ],
                    outcome=body,
                    http_status=response.status_code,
                    duration_s=duration,
                )
            raise ValidatorUnavailableError(
                f"Erwartet wurde ein OperationOutcome von {url}, bekommen: "
                f"{body.get('resourceType')!r} (HTTP {response.status_code})."
            )

        return ValidationResult(
            resource_type=resource_type,
            resource_id=resource_id,
            issues=parse_outcome(body),
            outcome=body,
            http_status=response.status_code,
            duration_s=duration,
        )


def parse_outcome(outcome: dict) -> list[Issue]:
    """Liest die Befundliste aus einem OperationOutcome."""
    issues: list[Issue] = []
    for raw in outcome.get("issue", []) or []:
        if not isinstance(raw, dict):
            continue
        issues.append(
            Issue(
                severity=str(raw.get("severity") or "error").lower(),
                code=str(raw.get("code")) if raw.get("code") else None,
                diagnostics=_diagnostics_text(raw),
                expression=_first_expression(raw),
                message_id=_message_id(raw),
            )
        )
    return issues


def _message_id(raw: dict) -> str | None:
    """Liest die HAPI-Fehlerkennung aus `details.coding`.

    Beispiele: "Validation_VAL_Profile_Minimum",
    "Terminology_PassThrough_TX_Message",
    "http://hl7.org/fhir/StructureDefinition/DomainResource#dom-6".
    Sie ist ein weit verlässlicherer Gruppierungs- und Klassifikations-
    schlüssel als der Klartext.
    """
    details = raw.get("details")
    if not isinstance(details, dict):
        return None
    for coding in details.get("coding", []) or []:
        if not isinstance(coding, dict):
            continue
        code = coding.get("code")
        if coding.get("system") == MESSAGE_ID_SYSTEM and code:
            return str(code)
    # Manche Server lassen das System weg – dann das erste Coding nehmen.
    for coding in details.get("coding", []) or []:
        if isinstance(coding, dict) and coding.get("code"):
            return str(coding["code"])
    return None


def _first_expression(raw: dict) -> str | None:
    """`expression` ist neu, `location` ist die ältere Schreibweise."""
    for key in ("expression", "location"):
        value = raw.get(key)
        if isinstance(value, list) and value:
            return str(value[0])
        if isinstance(value, str) and value:
            return value
    return None


def _diagnostics_text(raw: dict) -> str:
    """Klartext des Befundes – mit Rückfallebenen für knappe Outcomes."""
    diagnostics = raw.get("diagnostics")
    if isinstance(diagnostics, str) and diagnostics.strip():
        return diagnostics.strip()
    details: Any = raw.get("details")
    if isinstance(details, dict):
        text = details.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    return str(raw.get("code") or "Kein Klartext im OperationOutcome.")
