# SynthFHIR

**Live: <https://synthfhir.onrender.com>**

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
| **1 — MVP** | Eingabe, Generierung, Validierung, Lokalisierung, Export, Veröffentlichung | ✅ veröffentlicht 2026-08-29 |
| **2 — v1.x** | Weitere Ressourcentypen, Bulk-Export, Seed, Server-Push, größere Kohorten | ✅ abgeschlossen 2026-08-30 |
| 3 — Vision | Deutsche Profile (KBV/ISiK), API, weitere Standards | ⏳ ISiK-Abstand gemessen und wiederholbar (2026-08-30) |

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
    kohorte.py    große Kohorten in Teilen (Phase 2)
    ndjson.py     Bulk-Export nach FHIR Bulk Data (Phase 2)
    push.py       Laden in einen FHIR-Server (Phase 2)
    profil.py     Messung gegen ISiK-Profile (Phase 3)
    referenzkohorte.py  feste Kohorte für wiederholbare Messungen
    aufzeichnung.py  Läufe aufzeichnen und wiedergeben (Phase 2)
    cli.py        Kommandozeile
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

### Große Kohorten von der Kommandozeile

Die Weboberfläche bleibt bei 25 Patienten je Anfrage: Ein Lauf über Hunderte
dauert im kostenlosen Kontingent Minuten und belegt so lange einen
Arbeitsprozess. Alles darüber läuft über die Kommandozeile.

```bash
synthfhir "Patientinnen mit Typ-2-Diabetes, 45 bis 80 Jahre" -n 200 -o kohorte.json
```

Der Lauf wird in Teile zu je 15 Patienten zerlegt, weil ein einzelner
LLM-Aufruf bei etwa 25 Patienten an die Token-Obergrenze stößt. Die Teile
werden erst am Ende zusammengeführt und **einmal** durchnummeriert — sonst
trüge jeder Teil wieder `pat-001` und die Verweise zeigten quer.

Fällt ein Teil aus, laufen die übrigen weiter und die Mengentreue weist die
Lücke aus. Der Rückgabewert sagt dasselbe ohne Lesen der Ausgabe: `0`
vollständig und valide, `1` Lücken, `2` Abbruch. Der Fortschritt geht auf
stderr, das Bundle auf stdout — `synthfhir … > datei.json` ergibt also eine
saubere Datei.

| Schalter | Wirkung |
|---|---|
| `-n`, `--anzahl` | Anzahl der Patienten |
| `-o`, `--ausgabe` | Zieldatei statt stdout |
| `--teilgroesse` | Patienten je LLM-Aufruf (Standard 15) |
| `--versuche` | Versuche je Teil, bevor er als ausgefallen gilt (Standard 2) |
| `--pause` | Wartezeit zwischen den Teilen, in Sekunden |
| `--aufzeichnen` | den Beitrag des Modells mitschreiben |
| `--wiedergeben` | eine Aufzeichnung abspielen statt das Modell zu fragen |
| `--ndjson` | zusätzlich als NDJSON in ein Verzeichnis schreiben |
| `--push` | in einen FHIR-Server laden — **schreibt nichts ohne `--push-ausfuehren`** |
| `--push-ausfuehren` | den Push wirklich ausführen |
| `--fremde-daten-ok` | auch pushen, wenn auf dem Ziel ungekennzeichnete Daten liegen |
| `--ueberschreiben` | vorhandene NDJSON-Dateien dort ersetzen |
| `--bericht` | Messwerte des Laufs als JSON |
| `--still` | kein Fortschritt auf stderr |

**`--pause` ist bei knappem Kontingent nötig.** Anbieter rechnen
`max_tokens` in die Anfragegröße ein: Bei 5600 reservierten Ausgabe-Token
und rund 2400 Token Prompt zählt ein Teil fast 8000 Token — bei einem
Kontingent von 8000 Token je Minute also etwa ein Teil pro Minute. Ein
ungetakteter Lauf über 200 Patienten lieferte am 2026-08-29 genau vier
Teile, dann stand die Ratengrenze. Mit `--pause 60` läuft derselbe Auftrag
durch, dauert aber entsprechend lange.

### Denselben Lauf wiederholen

**Es gibt kein `--seed`, und das hat einen gemessenen Grund.** Je drei
identische Anfragen an das Modell ergaben:

| Einstellung | verschiedene Antworten |
|---|---|
| `temperature 0.8` (Voreinstellung) | 3 von 3 |
| `temperature 0` | 2 von 3 |
| `temperature 0` **mit Seed** | 2 von 3 |

Der Seed verbessert nichts. Ein Schalter, der Wiederholbarkeit verspricht
und sie nicht liefert, wäre genau die Zusage ohne Deckung, wegen der
[ADR-001](docs/architekturentscheidung.md) Variante A verworfen hat.

Was stattdessen geht: Der Weg **nach** dem Modellaufruf ist byteweise
stabil — derselbe Parametersatz ergab über 20 Läufe und über vier Prozesse
mit verschiedenem `PYTHONHASHSEED` denselben SHA-256. Es genügt also, den
Beitrag des Modells aufzuzeichnen.

```bash
synthfhir "200 Patientinnen mit Typ-2-Diabetes" -n 200 --aufzeichnen lauf.aufz.json
synthfhir --wiedergeben lauf.aufz.json -o kohorte.json
```

Die Wiedergabe braucht **kein Netz und kein Kontingent** — bei einem
getakteten 200er-Lauf über dreizehn Minuten ist das der praktische Gewinn.
Die Aufzeichnung ist klein, weil sie die Parameter enthält und nicht das
Ergebnis: gemessen 5,4 KB gegenüber 27 KB Bundle.

**Die Aufzeichnung prüft sich selbst.** Sie führt die Prüfsumme des
ursprünglich erzeugten Bundles mit und rechnet sie bei jedem Abspielen
nach:

```
  identisch zum aufgezeichneten Lauf (Prüfsumme stimmt)
```

Ändert sich der Katalog in `codes.py` — ein korrigierter ICD-Schlüssel etwa,
und das ist hier schon vorgekommen —, liefert dieselbe Aufzeichnung ein
anderes Bundle. Dann sagt sie das:

```
  ABWEICHUNG: Das Ergebnis ist nicht dasselbe wie beim aufgezeichneten Lauf.
    aufgezeichnet: f7851380d151d127…
    jetzt:         2a598c336f01d233…
    Der Katalog hat sich geändert — das ist die wahrscheinliche Ursache.
```

Das Ergebnis wird trotzdem geliefert — eine Abweichung ist ein Befund, kein
Abbruch —, aber der **Rückgabewert ist dann 1**. Wofür die Wiedergabe da
ist, muss auch der maschinenlesbare Kanal sagen, nicht nur stderr.

Begründung und die Grenzen der Zusage in
[ADR-006](docs/adr-006-reproduzierbarkeit.md).

### Wie weit ist die Ausgabe von ISiK entfernt?

Das misst ein eigener Befehl. Er **ändert nichts** an der Erzeugung — er
hält die Ausgabe gegen die ISiK-Profile der gematik und berichtet:

```bash
docker compose -f docs/belege/docker-compose.isik.yml up -d
synthfhir-profil -o docs/belege/isik-profilbericht.json
```

```
Typ                     geprüft   Fehler  ungeprüft  Warnungen
Condition                     4       13          8          8
Encounter                     3        9          0          3
Patient                       3        3          0         15
SUMME                        10       25          8         26
```

**Drei Spalten, nicht zwei.** `ungeprüft` heißt: Der Validator konnte es
nicht entscheiden — nicht, dass es richtig ist. Ohne Terminologieserver
bleibt jede Bindung an SNOMED, LOINC, ICD-10-GM und ATC in dieser Spalte.
Solche Befunde als Fehler zu zählen machte das Ergebnis schlechter, als es
ist; sie zu verschweigen besser. Beides wäre Schönfärberei mit Zahlen.

Gemessen wird eine feste Referenzkohorte ohne Modellaufruf — sonst
verglichen zwei Läufe verschiedene Daten. Einer der drei Patienten hat
**keine** Begegnung: Er ist der Fall, an dem `isik-con1` greift, und er
gehört dazu, *weil* er scheitert.

Einordnung und offene Entscheidung in
[docs/sondierung-isik.md](docs/sondierung-isik.md).

### In einen FHIR-Server laden

Das ist der einzige Teil, der in ein **fremdes System** schreibt. Ein
Tippfehler in der Ziel-URL schriebe erfundene Patienten in etwas, das
vielleicht kein Testserver ist. Deshalb ist der Trockenlauf die
Voreinstellung:

```bash
synthfhir --wiedergeben lauf.aufz.json --push http://localhost:8080/fhir
```

```
Push: http://localhost:8080/fhir
  Server:       FHIR 4.0.1
  Bestand dort: 0 Patienten, davon 0 als Testdaten gekennzeichnet
  Reihenfolge:  Patient -> Encounter -> MedicationStatement -> Condition -> Observation
  TROCKENLAUF:  1 Transaktionen würden geschrieben. Es wurde nichts verändert.
  Wirklich ausführen mit:  --push-ausfuehren
```

Geschrieben wird in Transaktionen mit `PUT`: atomar je Paket und
idempotent — zweimal ausgeführt ergibt denselben Serverzustand statt
doppelter Patienten. Ein Zugangstoken kommt aus `SYNTHFHIR_PUSH_TOKEN`,
ausdrücklich nicht von der Kommandozeile: Argumente stehen in der
Shell-Historie.

**Der Push weigert sich**, wenn auf dem Ziel Patienten **ohne**
Testkennzeichen liegen — ein Hinweis darauf, dass es kein Testserver ist.
`--fremde-daten-ok` hebt das auf. Verlassen sollte man sich darauf nicht:
Der Wächter liest den Suchindex des Zielservers, und der hängt hinterher.

### Jede Ressource ist als Testdatum gekennzeichnet

```json
"meta": {"security": [{
  "system": "http://terminology.hl7.org/CodeSystem/v3-ActReason",
  "code": "HTEST", "display": "test health data"}]}
```

Das Versprechen „nur synthetische Daten" stand bisher im README, im
Manifest und in jeder Konsolenausgabe — also überall dort, wo ein *Mensch*
hinsieht. `HTEST` ist der Standardcode dafür, und er macht daraus eine
Angabe, nach der ein Server suchen kann (`_security=…|HTEST`).

Das Label sitzt an **jeder** erzeugten Ressource, nicht nur an gepushten:
Eine Datei, die heute exportiert wird, kann morgen jemand anderes irgendwo
hineinladen. Begründung in
[ADR-008](docs/adr-008-server-push.md).

### Bulk-Export als NDJSON

Ein Bundle ist zum Ansehen gut und zum Laden schlecht. Wer eine Kohorte in
ein System bringen will, braucht das Format, das Import-Werkzeuge erwarten:

```bash
synthfhir "200 Patientinnen mit Typ-2-Diabetes" -n 200 --pause 60 --ndjson ./export
```

Das ergibt eine Datei je Ressourcentyp plus ein `manifest.json` in der Form
der Bulk-Data-Abschlussantwort:

```
export/
  Patient.ndjson       200 Ressourcen
  Condition.ndjson     220 Ressourcen
  Observation.ndjson   600 Ressourcen
  manifest.json        transactionTime, output[] mit type, url, count
```

Zwei Dinge, die nicht offensichtlich sind:

**Das Manifest nennt die referenzierten Typen zuerst.** Wer die Dateien
alphabetisch abarbeitet, lädt `Condition.ndjson` vor `Patient.ndjson` —
also Diagnosen, deren Patienten es noch nicht gibt. HAPI nimmt das hin
(nachgeprüft), Server mit `enforceReferentialIntegrityOnWrite` nicht.

Verlassen darf man sich darauf allerdings nicht: Große Import-Werkzeuge
verarbeiten die Dateien parallel und sichern gar keine Reihenfolge zu. Die
Sortierung hilft dem, der sequentiell lädt, und kostet sonst nichts — eine
Garantie ist sie nicht.

**Ein belegtes Zielverzeichnis wird verweigert.** Läge dort noch ein
`Encounter.ndjson` eines früheren Laufs, lüde der Empfänger es mit.
`--ueberschreiben` hebt die Sperre auf und räumt dabei die Reste weg.

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
| [ADR-004](docs/adr-004-grosse-kohorten.md) | Wie große Kohorten in Teilen entstehen, ohne zu zerbrechen |
| [ADR-005](docs/adr-005-ndjson-export.md) | Warum der Bulk-Export ein Verzeichnis ist und kein Strom |
| [ADR-006](docs/adr-006-reproduzierbarkeit.md) | Warum es kein `--seed` gibt, sondern Aufzeichnungen |
| [ADR-007](docs/adr-007-weitere-ressourcentypen.md) | Encounter und MedicationStatement — und was sie an Token kosten |
| [ADR-008](docs/adr-008-server-push.md) | Server-Push, und warum jede Ressource als Testdatum gekennzeichnet ist |
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

## Veröffentlichen

Das Repository enthält ein `Dockerfile` und eine `render.yaml`. Für den
Betrieb genügt ein Anbieter, der ein Container-Abbild startet — HAPI FHIR
wird **nicht** mitbetrieben, es läuft nur in der CI (ADR-002). Deshalb reicht
eine kleine Instanz mit wenigen hundert Megabyte.

### Warum Render

| Anbieter | kostenlos | Kreditkarte | Anmerkung |
|---|---|---|---|
| **Render** | ja, 750 Instanzstunden/Monat | **nein** | schläft nach 15 Min ohne Zugriff ein |
| Fly.io | nein | ja | ~2–3 USD/Monat für die kleinste Maschine |
| Railway | nur Startguthaben | ja | danach kostenpflichtig |

Render ist der einzige der drei, der ohne Kreditkarte auskommt und dauerhaft
kostenlos bleibt.

### Vorgehen

1. Im Render-Dashboard **New → Blueprint**, dieses Repository auswählen.
2. Render liest `render.yaml` und fragt nach `SYNTHFHIR_LLM_API_KEY` —
   der Schlüssel wird dort verschlüsselt abgelegt und steht nie im Repo.
3. Fertig. Jeder Push auf `main` löst ein neues Deployment aus.

### Was der kostenlose Tier kostet

Der Dienst wird nach **15 Minuten ohne Zugriff schlafen gelegt** und braucht
beim nächsten Aufruf rund **eine Minute** zum Aufwachen. Für eine
Portfolio-Demo ist das hinnehmbar, für ernsthafte Nutzung nicht — dann ist
der kostenpflichtige Tier oder ein anderer Anbieter die Antwort.

Dazu kommt die Wartezeit des LLM-Kontingents: Ohne eigenen Schlüssel sind
fünf Anfragen je Stunde und Adresse erlaubt, und bei ausgelastetem
Gratiskontingent wartet eine Anfrage bis zu einer Minute. Beides ist in der
Oberfläche erklärt, statt den Nutzer raten zu lassen.

## Tests

```bash
.venv/Scripts/python.exe -m pytest tests -q
```

Den eingefrorenen Spike separat prüfen:

```bash
.venv/Scripts/python.exe -m pytest spike/tests -q
```
