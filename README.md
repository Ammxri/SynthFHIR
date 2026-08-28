# SynthFHIR

> **Alle erzeugten Daten sind rein synthetisch und ausdrücklich nicht für die
> klinische Nutzung bestimmt.** Es werden zu keinem Zeitpunkt echte
> Patientendaten verarbeitet.

Beschreib in einem Satz die Testkohorte, die du brauchst — bekomme validierte,
deutsch lokalisierte FHIR-R4-Bundles, ohne Setup und ohne echte Patientendaten.

SynthFHIR schließt die Lücke zwischen **Synthea** (gültig, aber probabilistisch,
US-zentriert, Java-Setup) und einem **rohen LLM-Chat** (flexibel, aber
unzuverlässig in Struktur, Referenzen und Codes). Das Sprachmodell erzeugt den
*Inhalt*, das Werkzeug liefert die *Garantien* — und die Garantien sind das
Produkt.

---

## Status

| Phase | Inhalt | Status |
|---|---|---|
| **0 — Spike** | Architekturentscheidung mit Messdaten | ✅ abgeschlossen 2026-08-28 |
| **1 — MVP** | Eingabe, Generierung, Validierung, Lokalisierung, Export, Veröffentlichung | 🔨 in Arbeit |
| 2 — v1.x | Weitere Ressourcentypen, Bulk-Export, Seed, größere Kohorten | geplant |
| 3 — Vision | Deutsche Profile (KBV/ISiK), API, weitere Standards | langfristig |

---

## Aufbau des Repositorys

```
docs/     Produktdokumentation und Architekturentscheidungen
src/      das Produkt (Phase 1)
  synthfhir/
    domain/       Katalog, Vorlagen, Identität, Referenzintegrität
    validation.py Strukturprüfung zur Laufzeit
    llm.py        Anbindung an OpenAI-kompatible Endpunkte
    prompts.py    Freitext → Parameter
    generation.py die Kette bis zum Bundle
    web/          Oberfläche (FastAPI, serverseitig gerendert)
tests/    Tests des Produkts
spike/    Phase 0 — eingefrorener Wegwerf-Code samt Messbelegen
```

## Starten

```bash
.venv/Scripts/python.exe -m uvicorn synthfhir.web:app --reload
```

Danach auf <http://127.0.0.1:8000>. Die App liest ihre Konfiguration selbst
aus der `.env`; im Betrieb gewinnen die Umgebungsvariablen des Anbieters.

Der Spike ist **nicht** das Produkt. Er hat eine Frage beantwortet und bleibt
nur als Nachweis und als Messkette für eine mögliche Neuprüfung erhalten.

---

## Entscheidungen

Wer verstehen will, warum das Projekt so gebaut ist, liest diese vier Dokumente
in dieser Reihenfolge:

| Dokument | Beantwortet |
|---|---|
| [PRD v2.1](docs/PRD_SynthFHIR_v2.1.md) | Was das Produkt ist und für wen |
| [ADR-001](docs/architekturentscheidung.md) | Wer die FHIR-Struktur baut — Modell oder Code? |
| [ADR-002](docs/adr-002-validierungsarchitektur.md) | Wo und womit die Validitätsgarantie eingelöst wird |
| [ADR-003](docs/adr-003-lokalisierung.md) | Wie weit die deutsche Lokalisierung geht |
| [Konzepte](docs/konzepte.md) | Die FHIR-Grundlagen dahinter, ausführlich erklärt |

### Die tragenden Entscheidungen in drei Sätzen

**Der Code baut die FHIR-Struktur, nicht das Sprachmodell** (ADR-001). Gemessen
an 42 Durchläufen: Direktgenerierung durch das Modell lieferte nur 79,4 % der
geforderten Ressourcen, und der Einbruch verschärfte sich mit der Komplexität.
Das Modell liefert deshalb nur noch klinische Inhalte — Diagnose, Wert, Datum.

**Die Validierung ist zweistufig** (ADR-002). Zur Laufzeit prüft
`fhir.resources` die Struktur; HAPI FHIR prüft in der CI Katalog und Vorlagen.
Gemessen an 339 gelabelten Ressourcen: null falsche Alarme, alle Strukturfehler
erkannt. Was die Laufzeitprüfung nicht sieht — Einheiten und Codes —, kann die
Architektur nicht erzeugen, weil es aus dem Katalog kommt.

**Diagnosen tragen SNOMED CT und ICD-10-GM nebeneinander** (ADR-003). Eine
FHIR-`CodeableConcept` ist genau dafür gemacht.

---

## Die kritische Regel

> Jeder Eintrag des Codekatalogs und jede Vorlage muss durch einen CI-Test
> gedeckt sein, der daraus eine Ressource baut und gegen HAPI validiert — über
> den **vollständigen** Katalog, nicht über eine Stichprobe.

Das ist keine Stilfrage. Die Laufzeitprüfung sieht Einheiten und Codes nicht;
ein falscher UCUM-Code im Katalog erzeugt ab sofort invalide Ausgaben, ohne dass
irgendetwas anschlägt. Dieser Test ist der Ort, an dem die Produktzusage
tatsächlich eingelöst wird. Begründung: [ADR-002](docs/adr-002-validierungsarchitektur.md),
Abschnitt 5.

---

## Voraussetzungen

- Python 3.11 oder neuer (entwickelt mit 3.13)
- Docker — nur für die CI-Validierung und den Spike, nicht im Betrieb
- Zugang zu einem LLM; ein kostenloser Weg genügt (lokales Ollama oder ein
  Gratiskontingent, siehe `.env.example`)

## Einrichtung

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python.exe -m pip install -e ".[dev]"
```

Konfiguration anlegen — `.env.example` nach `.env` kopieren und ausfüllen.
`.env` ist per `.gitignore` ausgeschlossen und darf niemals eingecheckt werden.

HAPI FHIR für die Validierungstests starten:

```bash
docker compose up -d
```

## Tests

```bash
.venv/Scripts/python.exe -m pytest tests -q
```

Den eingefrorenen Spike separat prüfen:

```bash
.venv/Scripts/python.exe -m pytest spike/tests -q
```
