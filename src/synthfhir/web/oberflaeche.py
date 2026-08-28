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

from ..generation import Ergebnis, generiere
from ..llm import LLMFehler, OpenAIKompatiblerClient, client_aus_umgebung
from ..prompts import MAX_PATIENTEN
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
    docs_url=None,
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

BEISPIELE = [
    "Eine 68-jährige Patientin mit Diabetes Typ 2 und HbA1c-Verlauf über ein Jahr",
    "Drei Patienten mit chronischer Nierenkrankheit, je Kreatinin und eGFR",
    "Fünf Patienten unterschiedlichen Alters mit Herz-Kreislauf-Erkrankungen",
]


# HEAD zusätzlich zu GET: Hosting-Anbieter prüfen die Erreichbarkeit oft
# mit HEAD, und ein 405 an dieser Stelle liest sich für sie wie ein Ausfall.
@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def startseite(request: Request):
    BREMSE.aufraeumen()
    return vorlagen.TemplateResponse(
        request,
        "index.html",
        {
            "beispiele": BEISPIELE,
            "max_patienten": MAX_PATIENTEN,
            "demo_anfragen": BREMSE.anfragen,
        },
    )


@app.post("/erzeugen", response_class=HTMLResponse)
def erzeugen(
    request: Request,
    beschreibung: str = Form(""),
    eigener_schluessel: str = Form(""),
):
    kontext: dict = {
        "beispiele": BEISPIELE,
        "max_patienten": MAX_PATIENTEN,
        "beschreibung": beschreibung,
        "demo_anfragen": BREMSE.anfragen,
    }

    schluessel = eigener_schluessel.strip()
    # Der eigene Schlüssel wird ausschließlich für diesen einen Aufruf
    # benutzt: nicht gespeichert, nicht protokolliert und nicht in die Seite
    # zurückgeschrieben. Deshalb steht er auch nirgends im Kontext.
    if schluessel:
        try:
            client = OpenAIKompatiblerClient(
                modell=os.environ.get("SYNTHFHIR_LLM_MODEL", "").strip()
                or "openai/gpt-oss-120b",
                basis_url=os.environ.get("SYNTHFHIR_LLM_BASE_URL") or None,
                api_schluessel=schluessel,
            )
        except LLMFehler as exc:
            kontext["konfigurationsfehler"] = str(exc)
            return vorlagen.TemplateResponse(request, "index.html", kontext, status_code=503)
    else:
        erlaubt, wartezeit = BREMSE.pruefe(kennung_aus_anfrage(request))
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

    ergebnis = generiere(client, beschreibung)
    kontext["ergebnis"] = ergebnis
    kontext["ansicht"] = _ansicht(ergebnis)
    kontext["bundle_json"] = (
        json.dumps(ergebnis.bundle, indent=2, ensure_ascii=False) if ergebnis.bundle else ""
    )
    return vorlagen.TemplateResponse(request, "index.html", kontext)


@app.post("/export")
def export(bundle: str = Form(...), dateiname: str = Form("synthfhir-bundle.json")):
    """Liefert das Bundle als Datei aus.

    Der Inhalt kommt aus dem Formular zurück, weil der MVP nichts speichert.
    Er wird vor der Auslieferung erneut geparst — was nicht als JSON lesbar
    ist, wird nicht ausgeliefert.
    """
    try:
        geparst = json.loads(bundle)
    except json.JSONDecodeError:
        return PlainTextResponse("Kein gültiges JSON erhalten.", status_code=400)

    # Der Name kommt aus dem Formular. Er landet zwar nur im
    # Content-Disposition-Kopf und nicht in einem Pfad, aber ein Filter, der
    # "../../etc/passwd" zu "....etcpasswd" macht, ist kein Filter. Deshalb
    # bleibt nur Alphanumerisches plus Bindestrich und Unterstrich stehen,
    # und die Endung setzt der Server.
    roh = dateiname.strip()
    if roh.lower().endswith(".json"):
        roh = roh[:-5]
    basis = "".join(c for c in roh if c.isalnum() or c in "-_")[:60]
    sicherer_name = f"{basis or 'synthfhir-bundle'}.json"
    return Response(
        content=json.dumps(geparst, indent=2, ensure_ascii=False),
        media_type="application/fhir+json",
        headers={"Content-Disposition": f'attachment; filename="{sicherer_name}"'},
    )


@app.api_route("/health", methods=["GET", "HEAD"], response_class=PlainTextResponse)
def health():
    """Für die Startprüfung des Hosting-Anbieters."""
    return "ok"


# --- Aufbereitung für die Anzeige ------------------------------------------


def _ansicht(ergebnis: Ergebnis) -> list[dict]:
    """Gruppiert die Ressourcen patientenweise für die lesbare Vorschau.

    US-6: Studierende sollen die Struktur verstehen können. Eine rohe
    JSON-Wand leistet das nicht — die Verknüpfung Patient → Diagnose →
    Messwert ist genau das, was FHIR ausmacht und was man sehen muss.
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
            "diagnosen": [],
            "messwerte": [],
        }

    for r in ergebnis.ressourcen:
        typ = r.get("resourceType")
        if typ not in ("Condition", "Observation"):
            continue
        verweis = (r.get("subject") or {}).get("reference")
        eintrag = patienten.get(verweis)
        if eintrag is None:
            continue
        if typ == "Condition":
            eintrag["diagnosen"].append(
                {
                    "text": (r.get("code") or {}).get("text", "—"),
                    "codes": [
                        f"{_systemkuerzel(c.get('system'))} {c.get('code')}"
                        for c in (r.get("code") or {}).get("coding", [])
                    ],
                    "beginn": r.get("onsetDateTime", "—"),
                }
            )
        else:
            menge = r.get("valueQuantity") or {}
            eintrag["messwerte"].append(
                {
                    "text": (r.get("code") or {}).get("text", "—"),
                    "wert": f"{menge.get('value', '—')} {menge.get('unit', '')}".strip(),
                    "datum": r.get("effectiveDateTime", "—"),
                    "code": (r.get("code") or {}).get("coding", [{}])[0].get("code", ""),
                }
            )

    return list(patienten.values())


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
    return system.rsplit("/", 1)[-1]
