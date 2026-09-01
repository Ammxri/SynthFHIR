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
| 3 — Vision | Deutsche Profile (KBV/ISiK), API, weitere Standards | ⏳ ISiK-Basismodul: 0 Fehler, 8 ungeprüft (2026-08-30) |

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
    szenarien.py  fertige Kohortenvorlagen ohne Modellaufruf (Phase 3)
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

Die Oberfläche gibt dreierlei heraus ([ADR-010](docs/adr-010-ausgabewege-in-der-weboberflaeche.md)):
ein **FHIR-Bundle**, ein **ZIP-Archiv** mit je einer NDJSON-Datei pro
Ressourcentyp samt Manifest, und die **Aufzeichnung** des Laufs, die sich
mit `synthfhir --wiedergeben` ohne neuen Modellaufruf abspielen lässt.

### Fertige Kohorten ohne Modellaufruf

Fünf kuratierte Vorlagen stehen auf jeder Ansicht bereit und bauen
**sofort, kostenlos und immer gleich** — auch dann, wenn das Kontingent
leer oder der Anbieter ausgefallen ist
([ADR-016](docs/adr-016-szenario-bibliothek.md)).

| Szenario | zeigt |
|---|---|
| `diabetes-ambulanz` | alle fünf Ressourcentypen im Zusammenspiel |
| `blutdruck-kontrolle` | das Panel: eine Observation mit zwei Komponenten |
| `labor-grundprofil` | viele Observations mit UCUM-Einheiten |
| `mehrere-kontakte` | mehrere Encounter je Patient |
| `ohne-kontakt` | Diagnose ohne Kontakt — `isik-con1` ergänzt ihn |

Jede hat eine eigene Adresse und ist damit verlinkbar:
<https://synthfhir.onrender.com/szenario/blutdruck-kontrolle>

Ein Szenario ist **keine Aufzeichnung**: Es verspricht *eine
Diabetes-Kohorte*, nicht *dasselbe Ergebnis wie damals*. Ändert sich der
Katalog, liefert es die neue Ausgabe, statt eine Abweichung zu melden.
Deshalb trägt es keine Prüfsummen — dafür halten Tests jeden seiner Codes
gegen den Katalog.

### Programmatischer Zugang

`POST /api/v1/erzeugen` erzeugt eine Kohorte über HTTP. Der Zugang läuft
**ausschließlich auf den Schlüssel des Aufrufers** — der Schlüssel des
Betreibers ist der Weboberfläche vorbehalten, wo eine Ratenbremse ihn
schützt. Mit eigenem Schlüssel gibt es keine Anzahlgrenze über die Zeit.

```bash
curl -X POST https://synthfhir.onrender.com/api/v1/erzeugen \
  -H "X-SynthFHIR-LLM-Key: $GROQ_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"beschreibung": "Zwei Patienten mit Asthma und Peak-Flow-Werten"}'
```

Die Antwort trägt das Bundle **und** die Nachweise — Validierung,
Referenzintegrität, Beanstandungen und die Rücklesung der Anfrage. Laut
README sind die Garantien das Produkt; ein Zugang, der nur das Bundle
zurückgäbe, lieferte die falsche Hälfte.

| Feld | Inhalt |
|---|---|
| `fertig` | Darf das Ergebnis ausgeliefert werden? |
| `bundle` | Nur wenn `fertig` — sonst heißt es `bundle_zurueckgehalten` |
| `validierung`, `integritaet`, `beanstandungen` | Die Nachweise |
| `aufzeichnung` | Abspielbar mit `synthfhir --wiedergeben`, ohne neuen Modellaufruf |
| `lauf.schluessel_herkunft` | Immer `"aufrufer"` — die Zusage, von außen prüfbar |

Beschreibung der Schnittstelle: `/api/v1/docs`.

Grenzen, die trotz „unbegrenzt" gelten: höchstens `25` Patienten je
Anfrage, 2000 Zeichen Beschreibung, 64 KB Anfragekörper, **80 Ressourcen
je Patient** ([ADR-012](docs/adr-012-mengengrenze-und-wiedergabe.md)) und
vier gleichzeitige Läufe. Der Deckel für gleichzeitige Läufe ist kein
Ratenlimit, sondern der Schutz davor, dass ein Aufrufer alle
Arbeitsplätze des einen Prozesses belegt und die Weboberfläche mitreißt.

Und: Die Anbieter-URL ist die des Betreibers (Groq) — ein Schlüssel eines
anderen Anbieters funktioniert daher nicht.

### Wiedergabe: derselbe Lauf, ohne Modellaufruf

`POST /api/v1/wiedergeben` rechnet eine Aufzeichnung nach. **Ohne jeden
Modellaufruf** — der erste Lauf kostet Token, jede Wiederholung ist
umsonst. Für eine Prüfkette ist das der eigentliche Wert des Zugangs: Er
funktioniert auch dann, wenn beim Betreiber gar kein Anbieter erreichbar
ist.

**Ohne Schlüssel** — diese Route berührt kein Kontingent, weder Ihres
noch ein fremdes. Der Rumpf ist `{"aufzeichnung": …}` mit dem Objekt aus
dem Feld `aufzeichnung` einer `/erzeugen`-Antwort. Die Antwort trägt `identisch`,
`befund` und beide Prüfsummen. Sie antwortet mit **200 für jede
Prüfsummenlage** — eine Abweichung ist ein Befund, kein Fehler.

Grenzen: 512 KB Anfragekörper, höchstens 200 Teile, höchstens 5000
Ressourcen, zwei gleichzeitige Läufe. Anders als sonst wird hier
**abgelehnt und nicht gekürzt**: Eine gekürzte Wiedergabe träfe auf die
Prüfsumme des Originals und meldete eine Abweichung, die keine ist.

### Szenarien über HTTP

`GET /api/v1/szenarien` listet die Vorlagen, `GET /api/v1/szenarien/{name}`
baut eine. **Beides ohne Schlüssel und ohne Modellaufruf** — der Inhalt
kommt aus dem Katalog, nicht aus dem Anfragekörper.

```bash
curl https://synthfhir.onrender.com/api/v1/szenarien
curl https://synthfhir.onrender.com/api/v1/szenarien/diabetes-ambulanz
```

Die Antwort trägt `bundle`, `ressourcen`, `integritaet`, die
Beanstandungen und `lauf.modellaufrufe: 0`. Keine Prüfsummen: Ein Szenario
sagt zu, *was* für eine Kohorte kommt, nicht *welche Bytes*.

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
| `--szenario` | eine fertige Vorlage bauen — Name oder Pfad zu einer `.json` |
| `--szenarien` | die eingebauten Vorlagen auflisten |
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

### Ohne Modell und ohne Aufzeichnung: Szenarien

```bash
synthfhir --szenarien
synthfhir --szenario diabetes-ambulanz -o kohorte.json
synthfhir --szenario blutdruck-kontrolle --ndjson ./export
```

Kein Netz, kein Schlüssel, kein Kontingent — und bei gleichem Namen immer
dasselbe. Eine eigene Vorlage geht als Datei:

```bash
synthfhir --szenario meins.json -o kohorte.json
```

Nennt sie einen Code, den dieser Katalog nicht führt, wird sie **nicht
abgewiesen** — der Katalog des Empfängers darf ein anderer sein —, aber
die Ersetzung steht vorgezogen auf stderr:

```
  ACHTUNG: 1 Code(s) stehen nicht in diesem Katalog und werden ersetzt:
    diagnosen: 999999999
```

Unterschied zur Aufzeichnung: Ein Szenario verspricht *eine
Diabetes-Kohorte*, eine Aufzeichnung *dasselbe Ergebnis wie damals*.
Deshalb wird `--aufzeichnen` bei `--szenario` übergangen (mit Hinweis) und
`--wiedergeben` zusammen mit `--szenario` abgewiesen.

### Wie weit ist die Ausgabe von ISiK entfernt?

Das misst ein eigener Befehl. Er **ändert nichts** an der Erzeugung — er
hält die Ausgabe gegen die ISiK-Profile der gematik und berichtet:

```bash
docker compose -f docs/belege/docker-compose.isik.yml up -d
synthfhir-profil -o docs/belege/isik-profilbericht.json
```

```
Typ                     geprüft   Fehler  ungeprüft  Warnungen
Condition                     4        0          8          8
Encounter                     4        0          0          8
Patient                       3        0          0          3
SUMME                        11        0          8         19
```

Bei der ersten Messung waren es **25 Fehler**; [ADR-009](docs/adr-009-isik-konformitaet.md)
hat sie geschlossen. **„0 Fehler" heißt aber nicht „ISiK-konform"** — die
acht ungeprüften Befunde bleiben, solange kein Terminologieserver die
SNOMED-Bindung entscheiden kann.

**Drei Spalten, nicht zwei.** `ungeprüft` heißt: Der Validator konnte es
nicht entscheiden — nicht, dass es richtig ist. Ohne Terminologieserver
bleibt jede Bindung an SNOMED, LOINC, ICD-10-GM und ATC in dieser Spalte.

### Die SNOMED-Bindung entscheiden

```bash
synthfhir-profil --terminologie
```

Fragt einen öffentlichen Terminologieserver, ob jeder Diagnosecode des
Katalogs Mitglied des ValueSets ist, das ISiK für `Condition.code`
verlangt — genau die Frage, die dem Validator ohne SNOMED-Hierarchie
offenbleibt. Gemessen am 2026-09-01: **25 von 25**, auf tx.fhir.de und
tx.fhir.org.

Der Nachweis führt zwei **Gegenproben** mit: einen Code, den es gibt, der
aber kein Befund ist, und einen erfundenen. Beide müssen verneint werden,
sonst gilt die Messung als ungültig. Das ist kein Beiwerk — der Versuch,
stattdessen den Validator selbst auf einen Terminologieserver zu zeigen,
ergab „0 ungeprüft" aus einer abgestürzten Validierung.

### Gegen den offiziellen HL7-Validator

```bash
python tools/isik_referenzvalidator.py
```

Misst dieselbe Kohorte mit dem Validator, den HL7 selbst veröffentlicht,
gegen einen Terminologieserver. Gemessen am 2026-09-01:

    Profil                                  geprüft   Fehler   Warn.
    ISiKBlutdruckSystemischArteriell              1        0       2
    ISiKDiagnose                                  4        0      12
    ISiKKontaktGesundheitseinrichtung             4        0       8
    ISiKMedikationsInformation                    2        0       2
    ISiKPatient                                   3        0       3
    SUMME                                        14        0      27

    Keine ungeprüften Befunde: Die Terminologie hat entschieden.

Gemessen wird gegen drei Module: Basismodul, Vitalparameter und
Medikation ([ADR-014](docs/adr-014-isik-module.md)). Die 20 Laborwerte
des Katalogs bleiben unprofiliert, und der Bericht sagt das in jeder
Ausgabe.

Zuständig wäre **ISiK Labor** — das existiert aber nur als Release
Candidate, und das veröffentlichte Paket verlangt für
`Observation.category` ein CodeSystem, das den geforderten Code gar nicht
enthält. Konformität ist damit derzeit für niemanden erreichbar. Sechs
Laborwerte tragen trotzdem schon die SNOMED-Kodierung, die die
Spezifikation nennt; die übrigen 14 stehen als
[Prüfliste](docs/snomed-labor-pruefliste.md). Näheres in
[ADR-015](docs/adr-015-isik-labor.md).

Damit sind die acht ungeprüften Befunde aus ADR-009 **aufgelöst**, nicht
wegdefiniert — das Werkzeug sucht ausdrücklich nach den Meldungen, die
„ungeprüft" bedeuten, und meldet sie mit Rückgabewert 1.

Das Werkzeug braucht `werkzeuge/validator_cli.jar` (rund 191 MiB, von
[HL7](https://github.com/hapifhir/org.hl7.fhir.core/releases)) und Java.
Beides gehört nicht ins Repository; eingecheckt wird nur der Bericht
unter `docs/belege/`.

Näheres in [ADR-013](docs/adr-013-terminologienachweis.md).
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
| [ADR-009](docs/adr-009-isik-konformitaet.md) | ISiK-Basismodul erfüllen — und was daran nicht additiv war |
| [ADR-010](docs/adr-010-ausgabewege-in-der-weboberflaeche.md) | Warum der NDJSON-Download ein Archiv ist und die Aufzeichnung nicht gesperrt wird |
| [ADR-011](docs/adr-011-programmatischer-zugang.md) | Ein API-Zugang, der ausschließlich auf fremde Rechnung läuft |
| [ADR-012](docs/adr-012-mengengrenze-und-wiedergabe.md) | Eine Mengengrenze gegen Verstärkung — und die Wiedergabe über das Netz |
| [ADR-013](docs/adr-013-terminologienachweis.md) | Die SNOMED-Bindung entscheiden — und beweisen, dass entschieden wurde |
| [ADR-014](docs/adr-014-isik-module.md) | Die ISiK-Module für Observation und MedicationStatement |
| [ADR-015](docs/adr-015-isik-labor.md) | ISiK Labor — was geht, und warum Konformität nicht geht |
| [ADR-016](docs/adr-016-szenario-bibliothek.md) | Die Szenario-Bibliothek — Vorlagen statt Modellaufrufe |
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

Daneben steht eine **Gesamtgrenze über alle Besucher** (`30` je Stunde).
Sie kennt keine Kennung und lässt sich deshalb nicht umgehen — anders als
die Grenze je Adresse, die eine Zeit lang über eine gefälschte
`X-Forwarded-For`-Kopfzeile zu unterlaufen war. Gemessen ergaben 30
Anfragen mit rotierendem Kopf 30 Aufrufe und kein einziges 429; heute sind
es fünf. Näheres in [ADR-011](docs/adr-011-programmatischer-zugang.md).

## Tests

```bash
.venv/Scripts/python.exe -m pytest tests -q
```

Den eingefrorenen Spike separat prüfen:

```bash
.venv/Scripts/python.exe -m pytest spike/tests -q
```

---

## Lizenz

Der **Code** steht unter der MIT-Lizenz (`LICENSE`).

Der **Katalog** in `src/synthfhir/domain/codes.py` führt daneben Codes und
Bezeichnungen aus SNOMED CT, LOINC, ICD-10-GM und ATC. Für sie gilt die
MIT-Lizenz nicht — die Bedingungen ihrer Herausgeber stehen in
[NOTICE.md](NOTICE.md).

Kurz: Die **erzeugten Testdaten** sind eine Anwendung dieser
Terminologien und unproblematisch. Wer den **Katalog selbst** übernimmt
oder verändert, handelt mit kuratierter Terminologie und ist an die
Bedingungen in `NOTICE.md` gebunden.

> This material contains content from LOINC (<https://loinc.org>). LOINC is
> copyright © 1995-2026, Regenstrief Institute, Inc. and the LOINC
> Committee and is available at no cost under the license at
> <https://loinc.org/license/>. LOINC® is a registered United States
> trademark of Regenstrief Institute, Inc.
