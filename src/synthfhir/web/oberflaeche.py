"""Die Weboberfläche.

Bewusst serverseitig gerendert: kein Build-Schritt, kein JavaScript-Bundle,
keine Datenbank. Das PRD schließt Persistenz und Nutzerkonten für den MVP
aus (Block 9) und verlangt einen kostenlosen oder sehr günstigen
Hosting-Tier (Block 6) — beides spricht für die einfachste Bauform, die
funktioniert.

Ohne Persistenz braucht der Export einen Umweg: Das erzeugte Bundle wandert
als verstecktes Formularfeld zurück zum Server und wird von dort als Datei
ausgeliefert. Das kostet etwas Bandbreite, funktioniert aber ohne
JavaScript, ohne Sitzung und ohne Zwischenspeicher.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..aufzeichnung import Aufzeichnung, AufzeichnungFehler, aus_einzellauf
from ..domain.codes import KATALOGE
from ..ndjson import ExportFehler, baue_archiv
from ..generation import Ergebnis, generiere
from ..llm import (
    LLMClient,
    LLMFehler,
    client_aus_umgebung,
    client_mit_fremdschluessel,
)
from ..prompts import MAX_PATIENTEN
from .. import szenarien as szen
from .ratenbremse import Ratenbremse, kennung_aus_anfrage

# Die App liest ihre Konfiguration selbst ein, statt sich auf den
# Startbefehl zu verlassen. Jeder Hosting-Anbieter startet uvicorn direkt
# auf `synthfhir.web:app`; ohne diese Zeile fände die App dort ihren
# Modellnamen nicht und meldete sich als nicht einsatzbereit.
# `load_dotenv` überschreibt bereits gesetzte Variablen nicht — im Betrieb
# gewinnen also die echten Umgebungsvariablen des Anbieters.
load_dotenv()

HIER = Path(__file__).resolve().parent

app = FastAPI(
    title="SynthFHIR",
    description="Validierte, deutsch lokalisierte synthetische FHIR-R4-Testdaten",
    # Eine feste Kennung statt der Paketversion. FastAPI setzt hier sonst
    # "0.1.0" ein, und das Schema ist schlüsselfrei abrufbar — die
    # Zusage dieses Feldes gilt der Schnittstelle, nicht dem Build.
    version="v1",
    # Beides lag zuvor auf None, in der Absicht, nichts auszuliefern. Die
    # Absicht war richtig, die Umsetzung unvollständig: `docs_url=None`
    # schaltet nur die Swagger-Oberfläche ab, nicht das Schema.
    # Nachgemessen antwortete `/openapi.json` mit 200 und listete unter
    # anderem das Formularfeld `eigener_schluessel`. Jetzt liegt das
    # Schema unter dem API-Präfix, und die Oberflächenrouten stehen mit
    # `include_in_schema=False` nicht darin.
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url=None,
)
app.mount("/static", StaticFiles(directory=HIER / "static"), name="static")
vorlagen = Jinja2Templates(directory=str(HIER / "templates"))

# Demo-Betrieb: Der Schlüssel des Betreibers bedient anonyme Besucher, aber
# nur begrenzt. Wer mehr braucht, bringt seinen eigenen mit - genau die
# Mitigation, die das PRD im Risikoregister vorsieht.
BREMSE = Ratenbremse(
    anfragen=int(os.environ.get("SYNTHFHIR_DEMO_ANFRAGEN", "5")),
    zeitfenster_s=float(os.environ.get("SYNTHFHIR_DEMO_FENSTER_S", "3600")),
)

# Die zweite Bremse, ohne Kennung. Sie zählt schlicht, wie oft der
# Schlüssel des Betreibers im Zeitfenster benutzt wurde — und ist damit
# das einzige Versprechen, das nicht an einer fälschbaren Kopfzeile hängt.
# Nachgemessen: 30 Anfragen mit rotierendem X-Forwarded-For ergaben vorher
# 30 Aufrufe und kein einziges 429.
#
# 30 je Stunde ist bewusst knapp gewählt. Eine Erzeugung kostet rund 2100
# Eingabe- und bis zu 4500 Ausgabe-Token bei einem Minutenkontingent von
# 8000; mehr als etwa eine Anfrage je Minute trägt der Gratistarif ohnehin
# nicht.
GESAMTBREMSE = Ratenbremse(
    anfragen=int(os.environ.get("SYNTHFHIR_DEMO_GESAMT", "30")),
    zeitfenster_s=float(os.environ.get("SYNTHFHIR_DEMO_FENSTER_S", "3600")),
)
# Ein fester Name: Diese Bremse unterscheidet keine Aufrufer.
GESAMT = "betreiberschluessel"

# Zeitgrenzen des Oberflächenpfads. Sie sind bewusst weiter als die des
# programmatischen Zugangs — hier wartet ein Mensch, der zusieht, dort ein
# Programm. Sie stehen als benannte Werte hier, weil die Fabrik
# `client_mit_fremdschluessel` die knapperen API-Werte vorgibt und diese
# Seite sie ausdrücklich überschreibt, statt sie stillschweigend zu erben.
EIGENER_TIMEOUT_S = 180.0
EIGENER_VERSUCHE = 3

# Grösse des Anfragekörpers. Starlette begrenzt nichts: Es sammelt
# sämtliche Teile mit `b"".join(chunks)`, ohne je die Grösse zu prüfen.
# `/export` nahm damit beliebig grosse Körper an, parste sie als JSON und
# baute bei `art=ndjson` zusätzlich ein ZIP im Speicher — wenige
# gleichzeitige Anfragen zu je 100 MB genügten, um die kostenlose Instanz
# umzubringen. Keine Modellkosten, aber Ausfall.
#
# Die Grenze ist grosszügig, weil `/export` rechtmässig ein ganzes Bundle
# trägt: 200 Patienten ergeben rund 1000 Ressourcen. 8 MB sind ein
# Vielfaches davon und immer noch eine Grenze.
#
# Sie sitzt in einer Middleware und nicht in der Route, und das ist keine
# Stilfrage: FastAPI liest den Körper vollständig ein, BEVOR es die
# Abhängigkeiten einer Route auflöst. Eine Prüfung in der Route käme zu
# spät — der Speicher wäre schon belegt.
KOERPER_HOECHSTGROESSE = 8 * 1024 * 1024

@app.middleware("http")
async def begrenze_koerper(request: Request, call_next):
    """Weist zu grosse Anfragekörper ab, bevor sie im Speicher landen.

    Geprüft wird `Content-Length`, nicht der gelesene Körper — der Sinn
    der Grenze ist ja gerade, ihn nicht zu lesen. Fehlt der Kopf, wird
    nichts abgewiesen: Browser senden ihn bei Formularen immer, und ein
    Abweisen ohne Kopf träfe nur redliche Sonderfälle.

    Der programmatische Zugang hat seine eigene, viel engere Grenze von
    64 KB. Diese hier ersetzt sie nicht, sie liegt darüber.
    """
    laenge = request.headers.get("content-length")
    if laenge is not None:
        try:
            zu_gross = int(laenge) > KOERPER_HOECHSTGROESSE
        except ValueError:
            # Ein unlesbares Content-Length ist selbst schon ein Grund.
            zu_gross = True
        if zu_gross:
            return PlainTextResponse(
                f"Der Anfragekörper ist grösser als "
                f"{KOERPER_HOECHSTGROESSE // (1024 * 1024)} MB.",
                status_code=413,
            )
    return await call_next(request)


BEISPIELE = [
    "Eine 68-jährige Patientin mit Diabetes Typ 2 und HbA1c-Verlauf über ein Jahr",
    "Drei Patienten mit chronischer Nierenkrankheit, je Kreatinin und eGFR",
    "Fünf Patienten unterschiedlichen Alters mit Herz-Kreislauf-Erkrankungen",
]


# HEAD zusätzlich zu GET: Hosting-Anbieter prüfen die Erreichbarkeit oft
# mit HEAD, und ein 405 an dieser Stelle liest sich für sie wie ein Ausfall.
@app.api_route(
    "/", methods=["GET", "HEAD"], response_class=HTMLResponse,
    include_in_schema=False,
)
def startseite(request: Request):
    BREMSE.aufraeumen()
    return vorlagen.TemplateResponse(
        request,
        "index.html",
        {
            "beispiele": BEISPIELE,
            "szenarien": szen.alle(),
            "max_patienten": MAX_PATIENTEN,
            "demo_anfragen": BREMSE.anfragen,
        },
    )


@app.post("/erzeugen", response_class=HTMLResponse, include_in_schema=False)
def erzeugen(
    request: Request,
    beschreibung: str = Form(""),
    eigener_schluessel: str = Form(""),
):
    # Die Grenzen des programmatischen Zugangs. Lokal importiert, weil
    # `api.py` nichts aus dieser Datei kennt und diese Richtung so bleiben
    # soll — siehe `_haenge_api_ein` am Dateiende. Der lokale Import hat
    # nebenbei den Vorzug, dass ein zur Laufzeit ersetzter Deckel auch
    # hier gilt.
    from .api import BESCHREIBUNG_HOECHSTLAENGE, GLEICHZEITIG, _plaetze

    kontext: dict = {
        "beispiele": BEISPIELE,
        "szenarien": szen.alle(),
        "max_patienten": MAX_PATIENTEN,
        "beschreibung": beschreibung,
        "demo_anfragen": BREMSE.anfragen,
    }

    # Die Eingabe zuerst, und zwar VOR jeder Bremse.
    #
    # Zuvor verbuchten beide Bremsen ihren Platz, bevor irgendetwas geprüft
    # war. 30 Anfragen mit leerer Beschreibung sperrten die Demo für den
    # Rest des Zeitfensters für jeden anonymen Besucher — ohne dass ein
    # einziger Token entstanden wäre, denn `generiere` bricht bei leerer
    # Beschreibung ab, ohne je ein Modell zu fragen. `api.py` macht es
    # ausdrücklich umgekehrt („Vor dem Modellaufruf, damit kein Kontingent
    # verbrennt"); die Oberfläche hatte diese Prüfung nicht.
    if not beschreibung.strip():
        kontext["eingabefehler"] = "Die Beschreibung ist leer."
        return vorlagen.TemplateResponse(
            request, "index.html", kontext, status_code=400
        )
    if len(beschreibung) > BESCHREIBUNG_HOECHSTLAENGE:
        # Ohne Grenze ging die Beschreibung ungeprüft in den Prompt — auf
        # Rechnung des Betreibers. Die Bremse zählt Anfragen, nicht Token:
        # Fünf erlaubte Anfragen einer Adresse konnten damit ein
        # Vielfaches des angenommenen Verbrauchs auslösen. Der API-Pfad
        # begrenzt seit ADR-011 auf denselben Wert, die Oberfläche nicht.
        kontext["eingabefehler"] = (
            f"Die Beschreibung ist länger als "
            f"{BESCHREIBUNG_HOECHSTLAENGE} Zeichen."
        )
        # Nicht ungekürzt zurückschreiben: Sonst trüge die Antwort die
        # ganze überlange Eingabe noch einmal aus.
        kontext["beschreibung"] = beschreibung[:BESCHREIBUNG_HOECHSTLAENGE]
        return vorlagen.TemplateResponse(
            request, "index.html", kontext, status_code=400
        )

    schluessel = eigener_schluessel.strip()
    # Der eigene Schlüssel wird ausschließlich für diesen einen Aufruf
    # benutzt: nicht gespeichert, nicht protokolliert und nicht in die Seite
    # zurückgeschrieben. Deshalb steht er auch nirgends im Kontext.
    platz_belegt = False
    if schluessel:
        try:
            # Über die Fabrik, nicht am Konstruktor vorbei.
            #
            # Zuvor stand hier `OpenAIKompatiblerClient(...)` direkt, und
            # das umging beide Riegel aus `llm.py`: die Musterprüfung auf
            # druckbares ASCII und die Längengrenze. Die Folge war
            # nachgemessen: `requests` wirft bei einem Zeilenumbruch im
            # Kopfwert eine `InvalidHeader`, DEREN MELDUNG DEN WERT
            # ENTHÄLT — `frage()` bettet sie mit `{exc}` in den `LLMFehler`
            # ein, und von dort ging der fremde Schlüssel über
            # `ergebnis.fehler` in genau die Seite, die der Kommentar
            # darüber ausschliesst. Zweite Folge: 100 000 Zeichen gingen
            # ungeprüft an den Anbieter hinaus.
            #
            # Die Fabrik verlangt zusätzlich eine gesetzte Basis-URL. Das
            # ist kein Beiwerk, sondern ihr dritter Riegel: Ohne
            # `SYNTHFHIR_LLM_BASE_URL` griff hier die Vorgabe, und die
            # zeigt auf ein lokales Ollama — der Schlüssel eines Fremden
            # wäre an einen Dienst gegangen, den niemand gemeint hat.
            client = client_mit_fremdschluessel(
                schluessel,
                modell=os.environ.get("SYNTHFHIR_LLM_MODEL", "").strip()
                or "openai/gpt-oss-120b",
                timeout_s=EIGENER_TIMEOUT_S,
                versuche=EIGENER_VERSUCHE,
            )
        except LLMFehler as exc:
            kontext["konfigurationsfehler"] = str(exc)
            return vorlagen.TemplateResponse(request, "index.html", kontext, status_code=503)

        # Der Gleichzeitigkeitsdeckel, den bisher nur `/api/v1` hatte.
        #
        # Alle Routen dieser App sind synchron definiert, FastAPI führt sie
        # also im Threadpool aus (Vorgabe 40 Plätze) — geteilt mit dem
        # API-Pfad. Ein Lauf kann Minuten belegen. Die Begründung des
        # Deckels in ADR-011 lautet wörtlich: „Ohne diesen Deckel könnte
        # ein Aufrufer mit gültigem eigenem Schlüssel die Seite für alle
        # anderen unbenutzbar machen." Das trifft auf diese Stelle genauso
        # zu — nur stand der Deckel bisher nicht hier.
        #
        # Der Betreiberpfad braucht ihn nicht: Dort deckeln die Bremsen.
        if not _plaetze.acquire(blocking=False):
            kontext["ausgelastet"] = True
            kontext["gleichzeitig"] = GLEICHZEITIG
            return vorlagen.TemplateResponse(
                request, "index.html", kontext, status_code=429,
                headers={"Retry-After": "30"},
            )
        platz_belegt = True
    else:
        # Reihenfolge mit Absicht: Die Bremse je Adresse zuerst, denn nur
        # eine erlaubte Anfrage verbraucht dort einen Platz. Andersherum
        # verbrauchte ein bereits gesperrter Aufrufer noch Plätze der
        # Gesamtbremse und könnte sie leerlaufen lassen, ohne je bedient
        # zu werden.
        erlaubt, wartezeit = BREMSE.pruefe(kennung_aus_anfrage(request))
        if erlaubt:
            erlaubt, wartezeit = GESAMTBREMSE.pruefe(GESAMT)
            kontext["gesamtbremse_greift"] = not erlaubt
        if not erlaubt:
            kontext["bremse_greift"] = True
            kontext["wartezeit_min"] = max(1, round(wartezeit / 60))
            return vorlagen.TemplateResponse(request, "index.html", kontext, status_code=429)
        try:
            client = client_aus_umgebung()
        except LLMFehler as exc:
            # Konfigurationsfehler klar von Erzeugungsfehlern trennen: Der
            # eine betrifft den Betreiber, der andere den Nutzer.
            kontext["konfigurationsfehler"] = str(exc)
            return vorlagen.TemplateResponse(request, "index.html", kontext, status_code=503)

    try:
        ergebnis = generiere(client, beschreibung)
    finally:
        # In jedem Fall zurückgeben, auch wenn `generiere` scheitert: Ein
        # nicht freigegebener Platz wäre für die Laufzeit des Prozesses
        # verloren, und vier davon legten den eigenen Schlüsselpfad still.
        if platz_belegt:
            _plaetze.release()

    kontext["ergebnis"] = ergebnis
    kontext["ansicht"] = _ansicht(ergebnis)
    kontext["bundle_json"] = (
        json.dumps(ergebnis.bundle, indent=2, ensure_ascii=False) if ergebnis.bundle else ""
    )
    kontext["aufzeichnung_json"] = _aufzeichnung_json(ergebnis, client)
    return vorlagen.TemplateResponse(request, "index.html", kontext)


# GET und nicht POST, mit dem Namen im Pfad: Das Ergebnis haengt an
# nichts als dem Namen, ist beliebig oft wiederholbar und aendert nichts.
# Damit ist es verlinkbar — /szenario/diabetes-ambulanz laesst sich in eine
# Bewerbung schreiben, ein POST-Ergebnis nicht.
#
# KEINE Bremse. Die Bremsen dieser Seite schuetzen ein Gratiskontingent
# beim Modellanbieter; hier gibt es keinen Anbieter. Was bleibt, ist etwas
# Rechenzeit fuer hoechstens 17 Ressourcen aus einer festen Liste von
# fuenf — gemessen 3,1 ms je Bau. Eine Bremse davor kostete den Zweck (die
# Seite soll auch dann etwas zeigen, wenn das Kontingent leer ist) und
# braechte nichts.
@app.get("/szenario/{name}", response_class=HTMLResponse, include_in_schema=False)
def szenario(request: Request, name: str):
    kontext: dict = {
        "beispiele": BEISPIELE,
        "szenarien": szen.alle(),
        "max_patienten": MAX_PATIENTEN,
        "demo_anfragen": BREMSE.anfragen,
    }
    try:
        s = szen.hole(name)
    except szen.SzenarioFehler as exc:
        # `hole` gibt den empfangenen Namen NICHT zurueck: Er kaeme aus dem
        # Pfad und stuende sonst in der Seite. Die Meldung nennt nur die
        # bekannten Namen.
        kontext["szenario_fehler"] = str(exc)
        return vorlagen.TemplateResponse(request, "index.html", kontext,
                                         status_code=404)

    ergebnis = szen.baue(s)
    kontext["szenario"] = s
    kontext["ergebnis"] = ergebnis
    kontext["ansicht"] = _ansicht(ergebnis)
    kontext["bundle_json"] = (
        json.dumps(ergebnis.bundle, indent=2, ensure_ascii=False)
        if ergebnis.bundle else ""
    )
    # Kein `aufzeichnung_json`: Eine Aufzeichnung haelt den Beitrag des
    # Modells fest, und den gibt es hier nicht. Die Vorlage blendet den
    # Knopf dann von selbst aus.
    return vorlagen.TemplateResponse(request, "index.html", kontext)


def _aufzeichnung_json(ergebnis: Ergebnis, client: LLMClient) -> str:
    """Die Aufzeichnung dieses Laufs als JSON — oder leer.

    Leer statt einer Fehlermeldung: Eine fehlende Aufzeichnung ist kein
    Grund, ein gültiges Ergebnis zurückzuhalten. Der Knopf erscheint dann
    schlicht nicht.

    Das Modell wird mitgeschrieben, weil eine Wiedergabe zwar ohne Modell
    auskommt, die Frage „womit ist das entstanden?" aber später niemand
    mehr beantworten kann.
    """
    if ergebnis.parameter is None:
        return ""
    try:
        aufz = aus_einzellauf(
            ergebnis, modell=getattr(client, "modell", "unbekannt")
        )
    except AufzeichnungFehler:
        return ""
    return json.dumps(aufz.to_dict(), ensure_ascii=False)


# Was heruntergeladen werden kann: Endung und MIME-Typ setzt der Server,
# nicht das Formular. So kann kein Feld aus der Seite eine Datei zu etwas
# anderem erklären, als sie ist.
AUSGABEARTEN = {
    "json": (".json", "application/fhir+json", "synthfhir-bundle"),
    "ndjson": (".zip", "application/zip", "synthfhir-ndjson"),
    "aufzeichnung": (".json", "application/json", "synthfhir-aufzeichnung"),
}


def _sicherer_name(dateiname: str, endung: str) -> str:
    """Der Name kommt aus dem Formular.

    Er landet zwar nur im Content-Disposition-Kopf und nicht in einem Pfad,
    aber ein Filter, der "../../etc/passwd" zu "....etcpasswd" macht, ist
    kein Filter. Deshalb bleibt nur Alphanumerisches plus Bindestrich und
    Unterstrich stehen, und die Endung setzt der Server.
    """
    roh = dateiname.strip()
    for bekannt in (".json", ".zip", ".ndjson"):
        if roh.lower().endswith(bekannt):
            roh = roh[: -len(bekannt)]
            break
    # `isalnum()` allein ist unicode-bewusst und liess damit alles durch,
    # was irgendwo auf der Welt ein Buchstabe oder eine Ziffer ist.
    # Nachgemessen: `_sicherer_name("日本語", ".json")` ergab `日本語.json`,
    # und Starlette schreibt Kopfzeilenwerte als latin-1 — die Antwort
    # endete als Serverfehler statt als Datei oder als 400. Gleiches für
    # arabisch-indische Ziffern (`٠١`) und `Ⅸ`.
    #
    # Der Schutz gegen Pfaddurchquerung war davon nicht betroffen und
    # bleibt: Kein Steuerzeichen ist alphanumerisch, `../../etc/passwd`
    # wird zu `etcpasswd`.
    basis = "".join(
        c for c in roh if (c.isascii() and c.isalnum()) or c in "-_"
    )[:60]
    return f"{basis or 'synthfhir'}{endung}"





@app.post("/export", include_in_schema=False)
def export(
    bundle: str = Form(...),
    art: str = Form("json"),
    aufzeichnung: str = Form(""),
    dateiname: str = Form(""),
):
    """Liefert das Erzeugte als Datei aus — in einer von drei Formen.

    Der Inhalt kommt aus dem Formular zurück, weil der MVP nichts speichert.
    Er wird vor der Auslieferung erneut geparst: Was nicht als JSON lesbar
    ist, wird nicht ausgeliefert.
    """
    if art not in AUSGABEARTEN:
        return PlainTextResponse(f"Unbekannte Ausgabeart: {art}", status_code=400)
    endung, mime, vorgabe = AUSGABEARTEN[art]

    try:
        geparst = json.loads(bundle)
    except json.JSONDecodeError:
        return PlainTextResponse("Kein gültiges JSON erhalten.", status_code=400)

    if art == "aufzeichnung":
        try:
            # Nicht bloss als JSON lesbar, sondern als Aufzeichnung
            # gültig — sonst lieferte die Seite eine Datei aus, die ihren
            # Namen nicht verdient und beim Abspielen scheitert.
            geprueft = Aufzeichnung.from_dict(json.loads(aufzeichnung))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError,
                AufzeichnungFehler) as exc:
            return PlainTextResponse(
                f"Keine gültige Aufzeichnung erhalten: {exc}", status_code=400
            )
        inhalt: bytes | str = json.dumps(
            geprueft.to_dict(), indent=2, ensure_ascii=False
        )
    elif art == "ndjson":
        ressourcen = [
            e["resource"]
            for e in (geparst.get("entry") or [])
            if isinstance(e, dict) and isinstance(e.get("resource"), dict)
        ]
        try:
            # `baue_archiv` prüft die Ressourcentypen gegen TYP_MUSTER.
            # Das ist hier keine Formsache: Der Typ wird zum Eintragsnamen
            # im Archiv, und ein Bundle aus einem gefälschten Formular
            # könnte sonst einen Eintrag "../entwischt.ndjson" enthalten.
            inhalt = baue_archiv(ressourcen, anfrage="synthfhir-web")
        except ExportFehler as exc:
            return PlainTextResponse(
                f"Archiv nicht erzeugbar: {exc}", status_code=400
            )
    else:
        inhalt = json.dumps(geparst, indent=2, ensure_ascii=False)

    return Response(
        content=inhalt,
        media_type=mime,
        headers={
            "Content-Disposition":
                f'attachment; filename='
                f'"{_sicherer_name(dateiname or vorgabe, endung)}"'
        },
    )


# Der programmatische Zugang. Ganz am Ende eingehängt, damit dieses Modul
# fertig geladen ist — `api.py` importiert aus `generation` und `llm`,
# aber nichts aus dieser Datei, und diese Reihenfolge soll auch so
# bleiben.
def _haenge_api_ein() -> None:
    from .api import SCHLUESSEL_KOPF, registriere

    registriere(app)

    # Das Sicherheitsschema, auf das die Route verweist. FastAPI baut es
    # nicht selbst, weil der Kopf mit `include_in_schema=False` deklariert
    # ist — und das ist Absicht: Als Parameter mit Bedingung stünde sein
    # Wert bei einem Validierungsfehler in der Antwort.
    urspruenglich = app.openapi

    def mit_schluesselschema():
        dokument = urspruenglich()
        dokument.setdefault("components", {})["securitySchemes"] = {
            "SynthFHIR-LLM-Key": {
                "type": "apiKey",
                "in": "header",
                "name": SCHLUESSEL_KOPF,
                "description": (
                    "Der eigene Schlüssel beim Modellanbieter. Dieser "
                    "Zugang läuft ausschliesslich auf seine Rechnung."
                ),
            }
        }
        return dokument

    app.openapi = mit_schluesselschema


_haenge_api_ein()


@app.api_route(
    "/health", methods=["GET", "HEAD"], response_class=PlainTextResponse,
    include_in_schema=False,
)
async def health():
    """Für die Startprüfung des Hosting-Anbieters."""
    return "ok"


# --- Aufbereitung für die Anzeige ------------------------------------------


def _ansicht(ergebnis: Ergebnis) -> list[dict]:
    """Gruppiert die Ressourcen patientenweise für die lesbare Vorschau.

    US-6: Studierende sollen die Struktur verstehen können. Eine rohe
    JSON-Wand leistet das nicht — die Verknüpfung Patient → Diagnose →
    Messwert ist genau das, was FHIR ausmacht und was man sehen muss.

    Seit ADR-007 erzeugt SynthFHIR fünf Ressourcentypen, die Vorschau zeigte
    aber weiter nur zwei. Begegnungen und Medikation standen im Bundle und
    waren in der Oberfläche unsichtbar — wer nur hierher sah, hielt das
    Erzeugte für kleiner, als es ist.

    Die Diagnosezeile nennt deshalb auch ihren Kontakt. Das ist die
    sichtbare Seite von `isik-con1` (ADR-009): Eine kodierte Diagnose muss
    sagen, in welchem Kontakt sie gestellt wurde — und diese Zusage soll
    man sehen können, nicht nur im Validator nachlesen.
    """
    if not ergebnis.ressourcen:
        return []

    patienten: dict[str, dict] = {}
    for r in ergebnis.ressourcen:
        if r.get("resourceType") != "Patient":
            continue
        name = (r.get("name") or [{}])[0]
        vorname = " ".join(name.get("given") or [])
        patienten[f"Patient/{r['id']}"] = {
            "id": r["id"],
            "name": f"{vorname} {name.get('family', '')}".strip() or "(ohne Namen)",
            "geschlecht": {"male": "männlich", "female": "weiblich",
                           "other": "divers", "unknown": "unbekannt"}.get(r.get("gender"), "—"),
            "geburtsdatum": r.get("birthDate", "—"),
            "begegnungen": [],
            "diagnosen": [],
            "messwerte": [],
            "medikamente": [],
        }

    for r in ergebnis.ressourcen:
        typ = r.get("resourceType")
        if typ not in ("Condition", "Observation", "Encounter",
                       "MedicationStatement"):
            continue
        verweis = (r.get("subject") or {}).get("reference")
        eintrag = patienten.get(verweis)
        if eintrag is None:
            continue
        if typ == "Encounter":
            eintrag["begegnungen"].append(
                {
                    "id": r["id"],
                    "art": _kontaktart(r.get("class") or {}),
                    "zeitraum": _zeitraum(r.get("period") or {}),
                    "fallnummer": next(
                        (k.get("value", "—") for k in r.get("identifier", [])),
                        "—",
                    ),
                }
            )
        elif typ == "MedicationStatement":
            mittel = r.get("medicationCodeableConcept") or {}
            eintrag["medikamente"].append(
                {
                    "text": mittel.get("text", "—"),
                    "codes": [
                        f"{_systemkuerzel(c.get('system'))} {c.get('code')}"
                        for c in mittel.get("coding", [])
                    ],
                    "dosierung": next(
                        (d.get("text", "") for d in r.get("dosage", [])), ""
                    ),
                    "seit": r.get("effectiveDateTime")
                    or _zeitraum(r.get("effectivePeriod") or {}),
                }
            )
        elif typ == "Condition":
            eintrag["diagnosen"].append(
                {
                    "text": (r.get("code") or {}).get("text", "—"),
                    "codes": [
                        f"{_systemkuerzel(c.get('system'))} {c.get('code')}"
                        for c in (r.get("code") or {}).get("coding", [])
                    ],
                    "beginn": r.get("onsetDateTime", "—"),
                    # Der Verweis, den isik-con1 verlangt — hier als
                    # blosse Kennung, damit die Zeile lesbar bleibt.
                    "kontakt": ((r.get("encounter") or {}).get("reference", "")
                                .split("/")[-1]),
                }
            )
        else:
            eintrag["messwerte"].append(
                {
                    "text": (r.get("code") or {}).get("text", "—"),
                    "wert": _messwerttext(r),
                    "datum": r.get("effectiveDateTime", "—"),
                    "code": (r.get("code") or {}).get("coding", [{}])[0].get("code", ""),
                }
            )

    return list(patienten.values())


def _messwerttext(r: dict) -> str:
    """Der Messwert als Text — auch wenn er in Komponenten steckt.

    Seit ADR-014 ist der Blutdruck EINE Observation mit zwei Komponenten
    und **ohne** `valueQuantity`. Die Vorschau las nur `valueQuantity` und
    zeigte deshalb ausgerechnet beim Blutdruck einen Gedankenstrich —
    aufgefallen an dem Szenario, das den Blutdruck vorführen soll.

    Kein Sonderfall für 85354-9: Gelesen wird, was da ist. Käme ein
    zweites Panel hinzu, zeigte es sich von selbst.
    """
    menge = r.get("valueQuantity")
    if isinstance(menge, dict) and menge.get("value") is not None:
        return f"{menge['value']} {menge.get('unit', '')}".strip()

    # Ohne Beschriftung der Komponenten: „158 / 96 mmHg" ist die uebliche
    # Schreibweise des Blutdrucks und braucht keine. Die Reihenfolge kommt
    # aus `_teile_blutdruck` und ist dort systolisch zuerst — dieselbe
    # Reihenfolge, die jeder Leser erwartet. Die Einheit steht einmal am
    # Ende, weil beide Komponenten dieselbe tragen.
    werte, einheit = [], ""
    for k in r.get("component") or []:
        if not isinstance(k, dict):
            continue
        m = k.get("valueQuantity") or {}
        if m.get("value") is None:
            continue
        werte.append(str(m["value"]))
        einheit = einheit or str(m.get("unit") or "")
    if werte:
        return " / ".join(werte) + (f" {einheit}" if einheit else "")
    return "—"


def _kontaktart(klasse: dict) -> str:
    """Die Kontaktart auf Deutsch — aus dem Katalog, nicht aus einer
    zweiten Liste.

    Eine hier abgeschriebene Zuordnung ginge genau so lange gut, bis dem
    Katalog eine fünfte Kontaktart zuwüchse. Das ist in diesem Projekt
    schon viermal passiert, jedes Mal mit einer Handaufzählung.
    """
    code = klasse.get("code", "")
    eintrag = KATALOGE["encounter_classes"].get(code)
    if eintrag is not None:
        return eintrag.display_de
    # Unbekannter Code: lieber den rohen Code zeigen als nichts. Er
    # stammte dann aus einer Aufzeichnung, die älter ist als der Katalog.
    return klasse.get("display") or code or "—"


def _zeitraum(zeitraum: dict) -> str:
    """`period` als eine lesbare Angabe. Gleicher Beginn und Schluss
    ergeben einen Tag, keine Spanne von einem Tag auf denselben."""
    beginn, schluss = zeitraum.get("start"), zeitraum.get("end")
    if beginn and schluss and beginn != schluss:
        return f"{beginn} bis {schluss}"
    return beginn or schluss or "—"


def _systemkuerzel(system: str | None) -> str:
    """Macht aus einer CodeSystem-URL ein lesbares Kürzel."""
    if not system:
        return "?"
    if "snomed" in system:
        return "SNOMED"
    if "loinc" in system:
        return "LOINC"
    if "icd-10-gm" in system:
        return "ICD-10-GM"
    if system.endswith("/atc"):
        return "ATC"
    return system.rsplit("/", 1)[-1]
