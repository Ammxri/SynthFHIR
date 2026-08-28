> ## ⚠️ Eingefroren — Phase 0 ist abgeschlossen
>
> Dieses Verzeichnis enthält den **Wegwerf-Spike**, mit dem am 2026-08-28 die
> Architekturentscheidung getroffen wurde. Es ist nicht das Produkt.
>
> - **Ergebnis:** Variante B — siehe [`../docs/architekturentscheidung.md`](../docs/architekturentscheidung.md)
> - **Das Produkt** entsteht unter [`../src/synthfhir/`](../src/)
> - **Belege** liegen unter `output/messreihe-02/`, davon der Beleg-Kern versioniert
>
> Der Spike bleibt bewusst lauffähig: ADR-001 nennt eine erneute Messreihe mit
> einem anderen Modell als Weg, die Entscheidung zu überprüfen. Alle Befehle
> unten sind aus **diesem** Verzeichnis auszuführen; die virtuelle Umgebung
> und die `.env` liegen in der Repository-Wurzel.

# SynthFHIR – Phase-0-Validierungs-Spike

> **Wichtiger Hinweis:** Dieses Projekt erzeugt **ausschließlich synthetische
> Testdaten**. Es werden zu keinem Zeitpunkt echte Patientendaten verarbeitet.
> Alle Ausgaben sind **nicht für die klinische Nutzung** bestimmt.

Der Spike beantwortet **eine einzige Frage**:

> Lässt sich LLM-erzeugtes FHIR über eine Validierungs- und Korrekturschleife
> zuverlässig auf valide FHIR-Ressourcen bringen — und welche von zwei
> Architekturvarianten ist dafür der richtige Weg?

Ergebnis des Spikes ist **eine begründete Architekturentscheidung mit
Messdaten**, kein lauffähiges Produkt. Der Code ist bewusst Wegwerf-Code mit
Erkenntniswert: optimiert auf Nachvollziehbarkeit und Messbarkeit.

---

## Die zwei Varianten

| | Variante A | Variante B |
|---|---|---|
| Das LLM liefert | fertiges FHIR-R4-JSON | ein flaches Parameterobjekt |
| FHIR baut | das LLM | deterministischer Code aus festen Vorlagen |
| Codes | erfindet das LLM frei | nur aus einem fest hinterlegten Katalog |
| Korrekturschleife | ja, bis 3 Runden | nein (nicht nötig) |

Alles danach ist identisch: ID-/Referenzvergabe, Validierung, Referenz-
Integritätsprüfung, Metriken, Artefakte.

```
Szenario (scenarios.yaml)
      ↓
 [Variante A oder B]          generation.py
      ↓
 JSON-Parsing                 jsonx.py
      ↓
 ID- und Referenzvergabe      identity.py     ← deterministisch, beide Varianten
      ↓
 FHIR-Validierung (HAPI)      validator.py
      ↓
 Korrekturschleife (nur A)    repair.py
      ↓
 Referenz-Integrität          integrity.py    ← eigener Code, nicht HAPI
      ↓
 Metriken + Dateiausgabe      metrics.py / artifacts.py / report.py
```

---

## Voraussetzungen

- Python 3.11 oder neuer (entwickelt und getestet mit 3.13)
- Docker Desktop (für den HAPI-FHIR-Server)
- Zugang zu einem LLM – **kostenpflichtig ist dafür nicht nötig**, siehe unten

## Den Spike ohne laufende Kosten messen

Der Spike misst die **Architektur**, nicht die maximale Modellqualität
(Abschnitt 3). Deshalb reicht ein frei verfügbares Modell. Der Adapter
`openai_compatible` spricht `/v1/chat/completions` und deckt damit mehrere
kostenlose Wege ab:

| Weg | Basis-URL | Schlüssel |
|---|---|---|
| **Ollama, lokal** | `http://localhost:11434/v1` | keiner nötig |
| Groq | `https://api.groq.com/openai/v1` | kostenlos |
| OpenRouter (`:free`-Modelle) | `https://openrouter.ai/api/v1` | kostenlos |
| Mistral | `https://api.mistral.ai/v1` | kostenlos |
| Google AI Studio | `https://generativelanguage.googleapis.com/v1beta/openai` | kostenlos |

Lokal, ohne jeden Schlüssel und ohne dass Daten den Rechner verlassen:

```bash
../.venv/Scripts/python.exe -m synthfhir --llm ollama --model mistral:latest compare --repeats 7
```

**Wie das Ergebnis zu lesen ist.** Ein kleines offenes Modell ist deutlich
schwächer als ein Spitzenmodell. Das macht die Messung nicht wertlos, aber
asymmetrisch:

- Ein schlechtes Ergebnis für **Variante A ist eine untere Schranke** – es
  zeigt, dass A mit *diesem* Modell nicht trägt, nicht dass A grundsätzlich
  nicht trägt.
- Ein gutes Ergebnis für **Variante B ist belastbar** – die Struktur kommt
  aus dem Code, nicht aus dem Modell. Was ein 7B-Modell schafft, schafft ein
  stärkeres erst recht.

Genau diesen Fall nennt Abschnitt 3 als eigenständiges Messergebnis: Wenn
Variante A nur mit einem Spitzenmodell funktioniert, ist das ein Kostenrisiko
und damit ein Argument für Variante B. Der Bericht weist Anbieter und Modell
bei jedem Lauf aus und blendet diesen Hinweis automatisch ein.

## Einrichtung

```bash
python -m venv ../.venv
```

```bash
../.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
```

Konfiguration anlegen – `.env.example` nach `.env` kopieren und den
API-Schlüssel eintragen. `.env` ist per `.gitignore` ausgeschlossen und darf
**niemals** eingecheckt werden.

```bash
copy .env.example .env
```

Validierungsserver starten (lädt beim ersten Mal das HAPI-Image herunter,
das dauert einige Minuten):

```bash
docker compose up -d
```

Der Serverstart selbst braucht danach nochmal 1–3 Minuten. Fortschritt:

```bash
docker compose logs -f hapi
```

## Bedienung

Konfiguration und Serverbereitschaft prüfen:

```bash
../.venv/Scripts/python.exe -m synthfhir check
```

Ein einzelner Block (eine Variante, ein Szenario):

```bash
../.venv/Scripts/python.exe -m synthfhir run --variant A --scenario einfach --repeats 3
```

Die vollständige Messreihe – beide Varianten, alle drei Szenarien, am Ende
der Vergleichsbericht. `--repeats 7` ergibt 7 × 3 = **21 Läufe je Variante**
und erfüllt damit die Mindestanforderung von 20 aus Abschnitt 10 der
Spezifikation:

```bash
../.venv/Scripts/python.exe -m synthfhir compare --repeats 7
```

Bericht aus einer bereits gemessenen Reihe neu erzeugen, ohne zu messen:

```bash
../.venv/Scripts/python.exe -m synthfhir report --session output/20260828-120000
```

Kostenloser Selbsttest der gesamten Kette ohne API-Schlüssel (`mock` liefert
fest verdrahtete Antworten mit absichtlich eingebauten Fehlern – **keine
Messgrundlage**, der Bericht weist das aus):

```bash
../.venv/Scripts/python.exe -m synthfhir compare --llm mock --repeats 1
```

Tests:

```bash
../.venv/Scripts/python.exe -m pytest tests -q
```

## Ausgabestruktur

```
output/<zeitstempel>/
    session.json                        Konfiguration der Messreihe
    bericht.md                          Vergleichsbericht A gegen B
    variante-A/<szenario>/lauf-01/
        prompt.txt                      System- und User-Prompt
        llm-roh-1.txt                   unveränderte Modellantwort
        parameter.json                  nur Variante B
        ressourcen.json                 nach ID-/Referenzvergabe
        bundle.json                     Bundle (collection)
        validierung/<Typ>-<id>.json     OperationOutcome je Ressource
        korrektur/<Typ>-<id>-runde-N.json   Zwischenstände (nur A)
        integritaet.json                Referenz-Integritätsprüfung
        metriken.json                   maschinenlesbare Metriken
```

---

## Auslegungsentscheidungen, die das Messergebnis beeinflussen

Diese Punkte legt die Spezifikation nicht bis ins Letzte fest. Sie sind hier
so entschieden – und das verändert, was die Zahlen bedeuten.

**1. Der Code besitzt den ID-Raum, das Modell die Verknüpfung.**
`identity.py` vergibt alle IDs neu und zieht bestehende Verweise über eine
Abbildungstabelle mit. Es erfindet aber **kein Ziel** für einen Verweis, der
ins Leere zeigt. Würde der Code jede Referenz einfach auf den ersten
Patienten umbiegen, wäre die Metrik „kaputte Referenzen“ in beiden Varianten
immer 0 und der ganze Vergleich wertlos.

**2. Kein erzwungenes JSON-Format.**
Beide Varianten fordern reinen Text an, ohne `output_config.format`. Ein
serverseitig erzwungenes JSON-Schema würde die Fehlerkategorie „Antwort ist
kein gültiges JSON“ künstlich auf null setzen – laut Abschnitt 8 ist genau
das eine Kernmetrik. `jsonx.py` entfernt nur Verpackung (Markdown-Rahmen,
Fließtext), repariert aber niemals kaputtes JSON.

**3. Nur Variante B bekommt den Code-Katalog.**
Das ist keine Benachteiligung von A, sondern der Unterschied, den der Spike
misst: A soll Codes selbst erzeugen, B darf nur aus einer festen Liste
wählen.

**4. Gezählt wird der erste Validierungsdurchgang.**
Die Liste der häufigsten Fehlerarten zeigt, was die jeweilige Architektur
produziert, bevor irgendetwas repariert wurde. Was die Korrekturschleife
daraus macht, steht getrennt in den Reparaturmetriken.

**5. Terminologie ist ein blinder Fleck – und zwar nachweislich.**
Der HAPI-Container aus `docker-compose.yml` hat keine LOINC-/SNOMED-Pakete
geladen. Gemessen am 28.08.2026 gegen HAPI 4.0.1 antwortet er auf jede
kodierte Ressource mit:

```
severity: warning
Terminology_PassThrough_TX_Message
CodeSystem is unknown and can't be validated: http://loinc.org
```

Also **Warnung, nicht Fehler**. Ein frei erfundener LOINC- oder SNOMED-Code
fällt in Variante A damit gar nicht auf. Genau deshalb zählt der Bericht
codebezogene Fehler und codebezogene Warnungen getrennt: Die Warnungszeile
ist das Maß für die Größe dieses blinden Flecks. Für Variante A ist das
Kriterium „erfundene Codes“ ohne geladene Terminologie also **nicht
aussagekräftig** – Variante B misst es über den eigenen Katalog dagegen
verlässlich. Das ist der direkte Beleg für den offenen Punkt „braucht es
eine eigene Terminologie-Validierung?“ aus Abschnitt 13.

**6. Operationalisierte Ampelschwellen.**
Abschnitt 10 formuliert zwei Kriterien qualitativ. Sie sind hier festgelegt
als: „vereinzelt“ = bis 5 % der Ressourcen mit Codebeanstandung; „wenige
Cent“ = unter 0,05 EUR je Patient, „budgetsprengend“ = ab 0,25 EUR je
Patient. Die Werte stehen in `metrics.py` und im Bericht.

**7. Temperatur > 0.**
Voreingestellt 0.8. Bei Temperatur 0 würden 21 Wiederholungen desselben
Szenarios 21-mal fast dasselbe messen. Für eine Fehlerquote braucht es
Streuung.

---

## Konfiguration

Alles über Umgebungsvariablen bzw. `.env`, siehe `.env.example`. Die
wichtigsten:

| Variable | Bedeutung |
|---|---|
| `ANTHROPIC_API_KEY` | Schlüssel für den Anbieter `anthropic`. Nur hier, nie im Code. |
| `SYNTHFHIR_LLM_API_KEY` | Schlüssel für `openai_compatible`. Bei lokalem Ollama leer lassen. |
| `SYNTHFHIR_LLM_PROVIDER` | `anthropic`, `openai_compatible` (Alias `ollama`) oder `mock` (Selbsttest) |
| `SYNTHFHIR_LLM_BASE_URL` | Endpunkt des Anbieters; ohne Angabe zeigt `openai_compatible` auf das lokale Ollama |
| `SYNTHFHIR_LLM_MODEL` | Voreinstellung `claude-haiku-4-5` – bewusst ein günstiges Modell |
| `SYNTHFHIR_LLM_TEMPERATURE` | Streuung zwischen Wiederholungen |
| `SYNTHFHIR_BUDGET_LIMIT_EUR` | Notbremse, Voreinstellung **5,00 EUR**; die Messreihe bricht ab, bevor mehr Kosten entstehen. Abschalten mit `0`. |
| `SYNTHFHIR_FHIR_BASE_URL` | Voreinstellung `http://localhost:8080/fhir` |
| `SYNTHFHIR_MAX_REPAIR_ROUNDS` | Voreinstellung 3 |

Zum Modell: Der Spike misst die **Architektur**, nicht die maximale
Modellqualität. Wenn Variante A nur mit einem Spitzenmodell funktioniert, ist
das selbst ein wichtiges Messergebnis (Kostenrisiko). Zum Gegentest genügt
`--model claude-sonnet-5` bzw. `--model claude-opus-5`.

Hinweis: Ist die Umgebungsvariable `ANTHROPIC_BASE_URL` gesetzt, benutzt das
Anthropic-SDK diesen Endpunkt. Für eigene Messungen ggf. entfernen.

Kostenrahmen: Eine vollständige Messreihe (`compare --repeats 7`, 42 Läufe)
liegt mit `claude-haiku-4-5` erfahrungsgemäß deutlich unter dem in der
Spezifikation genannten Rahmen von 5 EUR. Der genaue Wert steht nach dem Lauf
im Bericht; `SYNTHFHIR_BUDGET_LIMIT_EUR` deckelt ihn hart.

---

## Was bewusst NICHT enthalten ist

Keine Benutzeroberfläche, kein Hosting, keine Datenbank, keine
Authentifizierung, keine deutsche Lokalisierung (ICD-10-GM), keine weiteren
Ressourcentypen, keine Profile (US Core, KBV, ISiK), kein Bulk-Export, keine
großen Kohorten. Das ist die harte Scope-Grenze aus Abschnitt 2 der
Spezifikation.

## Ergebnis des Spikes

**Phase 0 ist abgeschlossen. Die Entscheidung fiel auf Variante B**
(Parameter + Vorlagen), gemessen an 42 Durchläufen gegen HAPI FHIR 4.0.1.

Ausschlaggebend war nicht die Validitätsquote – beide Varianten erreichen
nach der Korrekturschleife 100 % –, sondern die **Mengentreue**: Variante A
lieferte nur 150 der 189 geforderten Ressourcen (79,4 %), und der Einbruch
skaliert mit der Komplexität (100 % / 88 % / 73 %). Variante B: 100 %.

Die vollständige Begründung mit allen Metriken, Konsequenzen,
Gültigkeitsgrenzen und Revisionsbedingungen steht in
**[docs/architekturentscheidung.md](docs/architekturentscheidung.md)**.

## Weiterführend

- `docs/architekturentscheidung.md` – ADR-001, die begründete
  Architekturentscheidung am Ende der Phase 0.
- `docs/konzepte.md` – die vier Konzepte ausführlich: `$validate` und
  `OperationOutcome`, warum Strukturvalidierung Referenzen ins Leere nicht
  findet, welche Pflichtfelder die drei Ressourcen brauchen, und wo die
  Korrekturschleife an ihre Grenzen stößt.
- Die Module `validator.py`, `integrity.py`, `templates.py` und `repair.py`
  tragen dieselben Erklärungen als Docstring direkt am Code.
