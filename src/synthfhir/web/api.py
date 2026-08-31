"""Der programmatische Zugang.

Ein einziger Endpunkt, der ein Modell aufruft, und er läuft
**ausschließlich auf Rechnung des Aufrufers**. Das ist keine Preisfrage,
sondern die Auflage, unter der dieser Zugang überhaupt entstanden ist:
Das Gratiskontingent des Betreibers bleibt der Weboberfläche vorbehalten,
wo eine Ratenbremse es schützt. Ein Endpunkt ohne Schlüsselpflicht wäre
dieselbe Bremse, nur ohne Bremse.

===========================================================================
WIE DIE ZUSAGE DURCHGESETZT WIRD
===========================================================================

An vier Stellen, und keine davon genügt allein:

1. **Am Router**, nicht an der Route. Die Schlüsselprüfung hängt als
   `dependencies` am `APIRouter`. Eine später hinzugefügte Route kann sie
   damit nicht vergessen — und genau das wäre die Lücke, die das ganze
   Vorhaben aushebelte.
2. **In der Route**, vor jedem Client: fehlt, leer, nur Leerraum, doppelt
   gesendet oder mit unzulässigen Zeichen wird abgewiesen, bevor
   irgendetwas gebaut wird.
3. **In `llm.client_mit_fremdschluessel`**, also an der Quelle. Der
   Konstruktor fiel bei `None` und `""` nachgemessen still auf
   `SYNTHFHIR_LLM_API_KEY` zurück. Die Fabrik baut mit
   `umgebung_erlaubt=False`; der Riegel überlebt damit einen Umbau, der
   die Prüfung in dieser Datei entfernt.
4. **Dieses Modul importiert `client_aus_umgebung` nicht.** Was nicht
   importiert ist, kann nicht versehentlich aufgerufen werden.

Und als von außen prüfbare Form: Jede erfolgreiche Antwort trägt
`lauf.schluessel_herkunft`. Ohne dieses Feld könnte keine Schicht
oberhalb des Clients die Zusage nachträglich prüfen — der gesetzte
`Authorization`-Kopf sieht in beiden Fällen gleich aus.

===========================================================================
DER SCHLÜSSEL GEHÖRT IN EINE KOPFZEILE
===========================================================================

Nicht in den Rumpf. Nachgemessen mit FastAPI 0.141.1: Ein Rumpffeld mit
einer Pydantic-Bedingung steht bei einem Validierungsfehler **wörtlich**
in der 422-Antwort (`"input": "gsk_KURZ"`). Aus demselben Grund trägt der
Kopf hier keine Pydantic-Bedingung, sondern wird von Hand geprüft.

Nicht als Query-Parameter: uvicorn schreibt den Pfad samt Query-String in
jede Zugriffslogzeile, Kopfzeilen nicht.

Nicht als `Authorization: Bearer`. SynthFHIR authentifiziert niemanden —
es reicht eine fremde Zugangsdate an einen Dritten weiter. Ein eigener
Name sagt das, und der übliche Platz bleibt frei.

===========================================================================
KEIN FREMDER TEXT IM ANTWORTKÖRPER
===========================================================================

Keine Meldung, die eine Fremdbibliothek oder ein Anbieter geschrieben
hat, erreicht den Aufrufer. Der Grund ist nachgemessen und nicht
vorsorglich: Ein Schlüssel mit einem Zeilenumbruch erzeugt in `requests`
eine `InvalidHeader`, deren Text den **Wert** enthält; `llm.frage` bettet
`{exc}` ein, und der Satz landete so in `Ergebnis.fehler`. Ausgeliefert
werden ausschließlich kuratierte Sätze, ausgewählt über `LLMFehler.art`.

Dasselbe gilt in die andere Richtung: `antwort.text[:300]` des Anbieters
kann alles Mögliche enthalten, bis hin zu wiederholten Zugangsdaten.

===========================================================================
WAS DIESER ZUGANG NICHT IST
===========================================================================

Kein Auftragsmodell, kein Streaming, keine Wiederaufnahme: Der Aufruf
blockiert, bis das Ergebnis steht. Kein Push (`push.py` schriebe in eine
frei wählbare Ziel-URL — als Endpunkt wäre das eine SSRF-Maschine). Keine
vom Aufrufer wählbare Anbieter-URL, aus demselben Grund. Keine Kohorten
über `MAX_PATIENTEN`; wer mehr braucht, installiert das Paket.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time

from fastapi import APIRouter, Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..generation import Ergebnis, generiere
from ..llm import (
    SCHLUESSEL_HOECHSTLAENGE,
    LLMFehler,
    client_mit_fremdschluessel,
)
from ..ndjson import ExportFehler, baue_dateien
from ..prompts import MAX_PATIENTEN

SCHLUESSEL_KOPF = "X-SynthFHIR-LLM-Key"
MODELL_KOPF = "X-SynthFHIR-LLM-Model"

# Dieselbe Prüfung wie in der Fabrik, hier nur früher: So bekommt der
# Aufrufer 400 statt 401 und weiß, dass es an der Form lag.
_DRUCKBAR = re.compile(r"^[!-~]+$")

# Eine Beschreibung ist ein Satz, kein Dokument. Von Hand geprüft und
# nicht über Pydantic, damit der Wert nicht in einer 422 zurückkommt.
BESCHREIBUNG_HOECHSTLAENGE = 2000

# Der Rumpf trägt nur Text — kein Bundle, keine Aufzeichnung. 64 KB sind
# das Dreißigfache dessen, was die längste zulässige Beschreibung braucht.
# Starlette selbst begrenzt nichts: Es sammelt sämtliche Teile mit
# `b"".join(chunks)`, ohne je die Größe zu prüfen.
KOERPER_HOECHSTGROESSE = 64 * 1024

# „Unbegrenzt mit eigenem Schlüssel" heißt: keine Anzahlgrenze über die
# Zeit. Es heißt nicht, dass ein Aufrufer die Maschine allein bekommt.
#
# Alle Routen dieser App sind synchron definiert, FastAPI führt sie also
# im Threadpool aus (Vorgabe 40 Plätze) — geteilt mit der Weboberfläche.
# Ein Aufruf kann rechnerisch Minuten belegen. Ohne diesen Deckel könnte
# ein Aufrufer mit gültigem eigenem Schlüssel die Seite für alle anderen
# unbenutzbar machen, ohne das Kontingent des Betreibers auch nur zu
# berühren. Das ist kein Ratenlimit: Wer wartet, kommt dran.
GLEICHZEITIG = int(os.environ.get("SYNTHFHIR_API_GLEICHZEITIG", "4"))
_plaetze = threading.BoundedSemaphore(GLEICHZEITIG)

class Anfrage(BaseModel):
    """Der Anfragekörper. Der Schlüssel steht bewusst nicht darin."""

    beschreibung: str = Field(
        description="Die gewünschte Kohorte in einem Satz, deutsch oder englisch."
    )
    hoechstzahl: int | None = Field(
        default=None,
        description=(
            f"Obergrenze für die Patientenzahl, höchstens {MAX_PATIENTEN}. "
            "Das Feld heißt nicht 'anzahl', weil der Code kappt und meldet, "
            "aber nichts nachfordert."
        ),
    )
    ndjson: bool = Field(
        default=False,
        description="Zusätzlich je Ressourcentyp eine NDJSON-Datei als Klartext.",
    )


def _fehler(status: int, art: str, satz: str, quelle: str, **kopf) -> JSONResponse:
    """Immer dieselbe Form, nie ein fremder Text.

    `quelle` sagt, wem der Fehler gehört — dem Aufrufer, dem Anbieter oder
    diesem Dienst. Bei einem Zugang, der auf fremde Rechnung läuft, ist das
    keine Höflichkeit: Der Aufrufer muss erkennen können, ob die Bremse
    seine eigene ist.
    """
    return JSONResponse(
        status_code=status,
        content={"fehlerart": art, "fehler": satz, "quelle": quelle},
        headers=kopf or None,
    )


def pflicht_schluessel(
    request: Request,
    x_synthfhir_llm_key: str | None = Header(default=None, include_in_schema=False),
) -> str:
    """Die Schlüsselprüfung, als Abhängigkeit des **Routers**.

    Sie hängt am Router und nicht an der einzelnen Route, damit eine
    später hinzugefügte Route sie nicht vergessen kann.

    Der Kopf wird über `request.headers.getlist` erneut gelesen: Wird er
    doppelt gesendet, gewinnt bei einem als `str` deklarierten Parameter
    still der erste Wert. Bei einer Frage, die über fremde Abrechnung
    entscheidet, ist „still den ersten nehmen" die falsche Vorgabe.
    """
    werte = request.headers.getlist(SCHLUESSEL_KOPF)
    if not werte:
        raise _Abbruch(
            401,
            "schluessel_fehlt",
            f"Dieser Zugang verlangt einen eigenen LLM-Schlüssel im Kopf "
            f"{SCHLUESSEL_KOPF}.",
            "aufrufer",
            # RFC 9110 verlangt bei 401 eine Herausforderung. `Bearer` wäre
            # eine Falschauskunft und lockte Clients in einen Ablauf, den es
            # hier nicht gibt; ein unbekanntes Schema wird schlicht
            # übergangen, und genau das ist gewollt.
            kopf={"WWW-Authenticate": "SynthFHIR-LLM-Key"},
        )
    if len(werte) > 1:
        raise _Abbruch(
            400,
            "schluessel_mehrdeutig",
            f"{SCHLUESSEL_KOPF} wurde mehrfach gesendet.",
            "aufrufer",
        )

    roh = werte[0].strip()
    if not roh:
        raise _Abbruch(
            400, "schluessel_leer", f"{SCHLUESSEL_KOPF} ist leer.", "aufrufer"
        )
    if len(roh) > SCHLUESSEL_HOECHSTLAENGE:
        raise _Abbruch(
            400, "schluessel_unbrauchbar", "Der Schlüssel ist zu lang.", "aufrufer"
        )
    if not _DRUCKBAR.match(roh):
        # Ohne den Wert, mit Absicht: Diese Meldung wird ausgeliefert.
        raise _Abbruch(
            400,
            "schluessel_unbrauchbar",
            "Der Schlüssel enthält Zeichen, die in einer HTTP-Kopfzeile "
            "nicht zulässig sind.",
            "aufrufer",
        )
    return roh


class _Abbruch(Exception):
    """Trägt eine fertige Antwort nach oben.

    Eine eigene Ausnahme statt `HTTPException`, weil deren Körper
    `{"detail": ...}` heißt — der Zugang soll aber eine einzige
    Fehlerform haben, und die trägt `fehlerart`, `fehler` und `quelle`.
    """

    def __init__(self, status, art, satz, quelle, kopf=None):
        super().__init__(satz)
        self.antwort = _fehler(status, art, satz, quelle, **(kopf or {}))


# Welcher Statuscode zu welcher Fehlerart gehört, und welcher Satz
# ausgeliefert wird. Die Sätze sind kuratiert: Kein Text von `requests`,
# vom Anbieter oder aus einem Traceback erreicht den Aufrufer.
_ZUORDNUNG: dict[str, tuple[int, str, str]] = {
    "abgelehnt": (
        401,
        "schluessel_abgelehnt",
        "Der übermittelte Schlüssel wurde vom Anbieter abgelehnt.",
        # `quelle` steht als vierter Wert unten; hier reicht das Trio.
    ),
    "kein_zugriff": (
        403,
        "kein_zugriff",
        "Der Schlüssel ist gültig, hat aber keinen Zugriff auf dieses Modell.",
    ),
    "kontingent": (
        429,
        "kontingent",
        "Der Anbieter hat die Anfrage wegen seiner Ratengrenze abgewiesen. "
        "Das ist die Grenze des übermittelten Schlüssels, nicht die dieses "
        "Dienstes.",
    ),
    "verbindung": (
        502,
        "anbieter_nicht_erreichbar",
        "Der Modellanbieter war nicht erreichbar.",
    ),
    "unbrauchbar": (
        502,
        "anbieter_unbrauchbar",
        "Der Modellanbieter lieferte keine verwertbare Antwort.",
    ),
    "nicht_konfiguriert": (
        503,
        "nicht_einsatzbereit",
        "Der Dienst ist nicht einsatzbereit.",
    ),
}
# Wem der Fehler gehört. `nicht_konfiguriert` ist der einzige, der auf den
# Betreiber zeigt — und der einzige, den der Aufrufer nicht beheben kann.
_QUELLE = {
    "abgelehnt": "aufrufer",
    "kein_zugriff": "aufrufer",
    "kontingent": "anbieter",
    "verbindung": "anbieter",
    "unbrauchbar": "anbieter",
    "nicht_konfiguriert": "betreiber",
}


def _aus_art(art: str | None) -> JSONResponse:
    status, kennung, satz = _ZUORDNUNG.get(
        art or "", (502, "anbieter_unbrauchbar", "Der Lauf ist gescheitert.")
    )
    return _fehler(status, kennung, satz, _QUELLE.get(art or "", "anbieter"))


# Erst hier, weil die Prüfung vorher stehen muss: Sie hängt am ROUTER und
# nicht an der Route, damit eine später hinzugefügte Route sie erbt statt
# sie vergessen zu können.
router = APIRouter(
    prefix="/api/v1", tags=["api"], dependencies=[Depends(pflicht_schluessel)]
)


@router.post(
    "/erzeugen",
    summary="Eine synthetische FHIR-R4-Kohorte erzeugen",
    # Der Rumpf wird von Hand gelesen (siehe unten), FastAPI kann ihn also
    # nicht selbst beschreiben. Das Schema kommt deshalb aus demselben
    # Modell, das die Felder benennt — beschrieben wird damit genau das,
    # was auch gelesen wird, ohne dass eine 422 den Körper zurückspiegelt.
    openapi_extra={
        # Ohne diesen Eintrag zeigte die Beschreibung keinen Weg, den
        # Schlüssel überhaupt mitzugeben. Der KOPFNAME steht hier, nie
        # ein Wert und nie ein Beispiel.
        "security": [{"SynthFHIR-LLM-Key": []}],
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": Anfrage.model_json_schema()}
            },
        }
    },
)
async def erzeugen(
    request: Request,
    schluessel: str = Depends(pflicht_schluessel),
    x_synthfhir_llm_model: str | None = Header(
        default=None, include_in_schema=False
    ),
) -> JSONResponse:
    """Erzeugt eine Kohorte auf Rechnung des übermittelten Schlüssels.

    **Pflichtkopf `X-SynthFHIR-LLM-Key`** — der eigene Schlüssel beim
    Modellanbieter. Ohne ihn antwortet dieser Endpunkt mit 401 und ruft
    kein Modell auf; der Schlüssel des Betreibers wird hier nie benutzt.
    Der Name des Kopfes gehört ausdrücklich in diese Beschreibung: Er ist
    kein Geheimnis, nur sein Wert ist eines, und eine Dokumentation, die
    ihn verschweigt, ist unbrauchbar.

    Optional `X-SynthFHIR-LLM-Model` — sonst gilt das Modell, das der
    Dienst konfiguriert hat; welches es war, steht in `lauf.modell`.

    Die Anbieter-URL ist fest die des Dienstes. Ein Schlüssel eines
    anderen Anbieters funktioniert daher nicht.

    Antwortet mit **200 auch dann, wenn die Prüfung nicht durchgeht** —
    die Anfrage wurde vollständig verarbeitet, Token wurden verbraucht,
    und der erkannte Mangel ist das Produkt und kein Serverfehler. Das
    Urteil steht in `fertig`; bei `false` heißt das Feld mit dem Bundle
    `bundle_zurueckgehalten`, damit ein Client, der stumpf `bundle` liest,
    einen `KeyError` bekommt statt still ungeprüfte Daten auszuliefern.
    """
    # Der Rumpf wird von Hand gelesen, nicht über ein Pydantic-Argument:
    # Eine 422 aus FastAPI spiegelte den empfangenen Körper zurück, und
    # dieser Zugang gibt grundsätzlich nichts zurück, was hereinkam.
    roh = await _lies_koerper(request)

    beschreibung = str(roh.get("beschreibung") or "").strip()
    if not beschreibung:
        # Vor dem Modellaufruf, damit kein Kontingent verbrennt.
        return _fehler(
            400, "beschreibung_fehlt", "Die Beschreibung ist leer.", "aufrufer"
        )
    if len(beschreibung) > BESCHREIBUNG_HOECHSTLAENGE:
        return _fehler(
            400,
            "beschreibung_zu_lang",
            f"Die Beschreibung ist länger als {BESCHREIBUNG_HOECHSTLAENGE} Zeichen.",
            "aufrufer",
        )

    hoechstzahl = roh.get("hoechstzahl")
    if hoechstzahl is not None:
        if not isinstance(hoechstzahl, int) or isinstance(hoechstzahl, bool):
            return _fehler(
                400, "hoechstzahl_ungueltig", "hoechstzahl muss eine Zahl sein.",
                "aufrufer",
            )
        if hoechstzahl < 1:
            return _fehler(
                400, "hoechstzahl_ungueltig", "hoechstzahl muss mindestens 1 sein.",
                "aufrufer",
            )
    grenzen: list[str] = []
    gewuenscht = min(hoechstzahl or MAX_PATIENTEN, MAX_PATIENTEN)
    if hoechstzahl and hoechstzahl > MAX_PATIENTEN:
        grenzen.append(
            f"hoechstzahl auf {MAX_PATIENTEN} gekappt (Grenze dieses Zugangs)"
        )

    modell = (x_synthfhir_llm_model or "").strip() or None
    try:
        client = client_mit_fremdschluessel(schluessel, modell=modell)
    except LLMFehler as exc:
        return _aus_art(exc.art)

    # Nicht blockierend: Wer keinen Platz bekommt, erfährt es sofort statt
    # stumm in einer Warteschlange zu hängen, deren Länge niemand kennt.
    if not _plaetze.acquire(blocking=False):
        return _fehler(
            429,
            "ausgelastet",
            f"Es laufen bereits {GLEICHZEITIG} Erzeugungen. Diese Grenze "
            "schützt die Weboberfläche und gilt unabhängig vom Schlüssel.",
            "synthfhir",
            **{"Retry-After": "30"},
        )
    beginn = time.monotonic()
    try:
        # Ausdrücklich ausgelagert. Die Route ist `async def`, damit das
        # Lesen des Rumpfs und die Prüfungen die Ereignisschleife nicht
        # verlassen — `generiere` blockiert aber minutenlang und gehörte
        # niemals dorthin. Ohne dieses `run_in_threadpool` hielte ein
        # einziger Aufruf den gesamten Prozess an, Weboberfläche und
        # Startprüfung eingeschlossen.
        ergebnis = await run_in_threadpool(
            generiere, client, beschreibung, max_patienten=gewuenscht
        )
    finally:
        _plaetze.release()

    if ergebnis.fehler is not None:
        return _aus_art(ergebnis.fehlerart)

    return JSONResponse(
        content=_antwort(ergebnis, client, roh, grenzen, time.monotonic() - beginn)
    )


async def _lies_koerper(request: Request) -> dict:
    """Liest den Rumpf mit Größengrenze und ohne Rückspiegelung."""
    laenge = request.headers.get("content-length")
    if laenge and laenge.isdigit() and int(laenge) > KOERPER_HOECHSTGROESSE:
        raise _Abbruch(
            413,
            "koerper_zu_gross",
            f"Der Anfragekörper überschreitet {KOERPER_HOECHSTGROESSE} Bytes.",
            "aufrufer",
        )
    # Auch ohne Content-Length messen: Bei `Transfer-Encoding: chunked`
    # fehlt die Kopfzeile, und dann wäre die Prüfung oben wirkungslos.
    rumpf = await request.body()
    if len(rumpf) > KOERPER_HOECHSTGROESSE:
        raise _Abbruch(
            413,
            "koerper_zu_gross",
            f"Der Anfragekörper überschreitet {KOERPER_HOECHSTGROESSE} Bytes.",
            "aufrufer",
        )
    try:
        geparst = json.loads(rumpf or b"{}")
    except ValueError:
        raise _Abbruch(
            400, "koerper_unlesbar", "Der Anfragekörper ist kein gültiges JSON.",
            "aufrufer",
        ) from None
    if not isinstance(geparst, dict):
        raise _Abbruch(
            400, "koerper_unlesbar", "Erwartet wird ein JSON-Objekt.", "aufrufer"
        )
    return geparst


def registriere(app: FastAPI) -> None:
    """Hängt den Zugang in die App und macht `_Abbruch` zu einer Antwort.

    Ohne den Behandler entkäme `_Abbruch` aus der Abhängigkeit als
    500 — und ein fehlender Schlüssel sähe aus wie ein Serverfehler.
    """

    @app.exception_handler(_Abbruch)
    async def _behandle(_request: Request, abbruch: _Abbruch) -> JSONResponse:
        return abbruch.antwort

    app.include_router(router)


def _antwort(
    ergebnis: Ergebnis, client, roh: dict, grenzen: list[str], dauer_s: float
) -> dict:
    """Die Erfolgsantwort. Deutsche Schlüssel wie im übrigen Projekt.

    `Ergebnis.to_dict()` wird ausdrücklich **nicht** benutzt: Es gibt
    `fehler` heraus, und dorthin kopiert `_hole_parameter` den Text
    fremder Ausnahmen. Diese Form ist eigens gewählt und enthält nur
    Felder, deren Herkunft bekannt ist.
    """
    aus: dict = {
        "fertig": ergebnis.fertig,
        "hinweis": (
            "Synthetische Testdaten. Nicht für klinische Nutzung, keine "
            "echten Patientendaten."
        ),
        "verstanden": ergebnis.verstanden.to_dict() if ergebnis.verstanden else None,
        "ressourcen": ergebnis.anzahl_je_typ,
        "beanstandungen": [
            {"art": b.art, "detail": b.detail} for b in ergebnis.beanstandungen
        ],
        "validierung": [e.to_dict() for e in ergebnis.validierung],
        "integritaet": (
            ergebnis.integritaet.to_dict() if ergebnis.integritaet else None
        ),
        "befunde": ergebnis.befunde_als_text(),
        "grenzen_gegriffen": grenzen,
        "lauf": {
            "versuche": ergebnis.versuche,
            "eingabe_token": ergebnis.eingabe_token,
            "ausgabe_token": ergebnis.ausgabe_token,
            "modell": getattr(client, "modell", None),
            "dauer_s": round(dauer_s, 2),
            # Die von aussen prüfbare Form der Zusage.
            "schluessel_herkunft": getattr(client, "schluessel_herkunft", None),
        },
    }
    # Nicht `bundle`, wenn es nicht ausgeliefert werden darf. Ein Client,
    # der stumpf `daten["bundle"]` schreibt, bekommt dann einen KeyError
    # statt still ungeprüfte Daten weiterzureichen.
    aus["bundle" if ergebnis.fertig else "bundle_zurueckgehalten"] = ergebnis.bundle

    if ergebnis.parameter is not None:
        from ..aufzeichnung import AufzeichnungFehler, aus_einzellauf

        try:
            aus["aufzeichnung"] = aus_einzellauf(
                ergebnis, modell=getattr(client, "modell", "unbekannt")
            ).to_dict()
        except AufzeichnungFehler:
            # Eine fehlende Aufzeichnung ist kein Grund, ein gültiges
            # Ergebnis zurückzuhalten.
            pass

    if roh.get("ndjson"):
        try:
            aus["ndjson"] = {
                "dateien": [
                    {
                        "typ": d.typ,
                        "name": d.name,
                        "anzahl": d.anzahl,
                        "inhalt": d.inhalt.decode("utf-8"),
                    }
                    for d in baue_dateien(ergebnis.ressourcen)
                ]
            }
        except ExportFehler:
            # Kann bei gültigen Ressourcen nicht eintreten; ein gescheiterter
            # Zusatz darf das Ergebnis trotzdem nicht mitreissen.
            pass
    return aus
