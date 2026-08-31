# ADR-011: Ein Zugang, der ausschließlich auf fremde Rechnung läuft

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-08-31 |
| **Phase** | 3 (Vision), PRD-Punkt „API-Zugang" (Priorität *Could*) |
| **Betrifft** | `web/api.py` (neu), `llm.py`, `web/ratenbremse.py`, `generation.py` |
| **Baut auf** | ADR-002, ADR-006, ADR-010 |

---

## 1. Kontext

Das PRD führt den API-Zugang als „Programmatische Generierung für CI/CD".
Die Auflage des Betreibers dazu ist wörtlich:

> Ohne eigenen Schlüssel nicht laufen lassen. Mein kostenloses Ratenlimit
> soll für mich aufrechterhalten bleiben. Mit eigenem Schlüssel kann die
> Person unbegrenzt handeln.

Beim Nachmessen zeigte sich, dass **beide Hälften dieser Auflage heute
nicht halten** — die zweite noch nicht, die erste schon nicht mehr.

### Was der Konstruktor tat

`llm.py` enthielt:

```python
schluessel = (api_schluessel or os.environ.get("SYNTHFHIR_LLM_API_KEY", "")).strip()
```

Nachgemessen, mit gesetztem Betreiberschlüssel:

| übergeben | gesetzter Authorization-Kopf |
|---|---|
| `None` | **Bearer BETREIBERSCHLUESSEL** |
| `""` | **Bearer BETREIBERSCHLUESSEL** |
| `"   "` | *keiner* — die Anfrage ging unauthentifiziert hinaus |
| `"gsk_fremd"` | Bearer gsk_fremd |

Drei Ausgänge, wo zwei gemeint waren. Jede Schicht, die ein leeres Feld
durchreicht, arbeitete auf Kosten des Betreibers — ohne Ausnahme, ohne
Meldung, ohne Spur.

### Was die Ratenbremse tat

Der schwerere Befund, und er betrifft die bestehende Weboberfläche, nicht
die neue API. `kennung_aus_anfrage` las `X-Forwarded-For.split(",")[0]`,
also das **linke** Glied. Die Kopfzeile wächst aber von links nach rechts:
Jeder Proxy hängt an, von wem er empfangen hat. Links steht damit, was der
Aufrufer selbst geschrieben hat.

Gemessen gegen die laufende App:

| | Aufrufe auf den Betreiberschlüssel | HTTP 429 |
|---|---|---|
| 9 Anfragen, feste Adresse | 5 | 4 |
| 30 Anfragen, rotierende Adresse | **30** | **0** |

Die Bremse wirkte ausschließlich gegen ehrliche Clients. Die Zusage „das
Gratiskontingent ist der Weboberfläche vorbehalten" war unbelegt, bevor
die erste Zeile des API-Zugangs geschrieben war.

### Was `requests` tat

`requests.Session()` steht voreingestellt auf `trust_env=True`. Der
Schlüssel wird hier als **Kopfzeile** gesetzt, nicht über den
`auth`-Parameter — requests sieht ihn in `prepare_request` also nicht,
hält die Anfrage für unauthentifiziert und zieht `.netrc` heran.
Nachgemessen ging ein gesetzter `Bearer sk-AUFRUFER` als
`Basic <netrc-Zugangsdaten>` hinaus. Beide Hälften der Auflage zugleich
verletzt: Der fremde Schlüssel verworfen, abgerechnet über den des
Betreibers.

---

## 2. Entscheidung

**Ein Endpunkt: `POST /api/v1/erzeugen`.** Er verlangt einen eigenen
LLM-Schlüssel im Kopf `X-SynthFHIR-LLM-Key` und benutzt niemals den des
Betreibers. Über die Zeit ist er unbegrenzt; begrenzt sind nur
Gleichzeitigkeit, Körpergröße und Kohortengröße.

Dazu vier Änderungen am Bestand, ohne die der Endpunkt seine Zusage nicht
halten könnte:

1. `OpenAIKompatiblerClient` normalisiert **erst** und entscheidet
   **dann**; neu ist `umgebung_erlaubt`, und `schluessel_herkunft` macht
   die Herkunft von außen prüfbar.
2. `session.trust_env = False`.
3. `LLMFehler` bekommt `art` — ein geschlossener Wortschatz statt Prosa.
4. Die Ratenbremse zählt von rechts, und daneben steht eine
   **Gesamtbremse ohne Kennung**.

---

## 3. Begründung

### Vier Riegel, keiner davon allein genügend

Die Zusage „niemals auf Kosten des Betreibers" wird an vier Stellen
durchgesetzt:

**Am Router.** Die Schlüsselprüfung hängt als `dependencies` am
`APIRouter`, nicht an der einzelnen Route. Eine später hinzugefügte Route
kann sie damit nicht vergessen.

**In der Route.** Fehlt, leer, nur Leerraum, doppelt gesendet, zu lang
oder mit unzulässigen Zeichen — abgewiesen, bevor irgendein Client
entsteht.

**In `client_mit_fremdschluessel`.** Der eigentliche Riegel, weil er einen
Umbau überlebt, der die Prüfung in `api.py` entfernt. Er baut mit
`umgebung_erlaubt=False`; der Konstruktor wirft dann, statt still
zurückzufallen.

**Durch Weglassen.** `api.py` importiert `client_aus_umgebung` nicht. Was
nicht importiert ist, kann nicht versehentlich aufgerufen werden.

Und als von außen prüfbare Form trägt jede Antwort
`lauf.schluessel_herkunft`. Ohne dieses Feld könnte keine Schicht oberhalb
des Clients die Zusage nachträglich prüfen — der gesetzte
`Authorization`-Kopf sieht in beiden Fällen gleich aus.

### Warum der Schlüssel in eine Kopfzeile gehört

**Nicht in den Rumpf.** Nachgemessen mit FastAPI 0.141.1: Ein Rumpffeld
mit Pydantic-Bedingung steht bei einem Validierungsfehler **wörtlich** in
der 422-Antwort:

```json
{"loc":["body","schluessel"], "input":"gsk_KURZ", "ctx":{"min_length":10}}
```

Aus demselben Grund trägt auch der Kopf keine Pydantic-Bedingung, sondern
wird von Hand geprüft — und aus demselben Grund liest die Route den
gesamten Rumpf selbst, statt ihn sich von FastAPI aushändigen zu lassen.

**Nicht als Query-Parameter.** uvicorn schreibt den Pfad samt
Query-String in jede Zugriffslogzeile; Kopfzeilen nicht.

**Nicht als `Authorization: Bearer`.** SynthFHIR authentifiziert
niemanden. Es reicht eine fremde Zugangsdate an einen Dritten weiter, und
ein eigener Name sagt das. Der übliche Platz bleibt frei.

Eine doppelt gesendete Kopfzeile wird **abgewiesen**, nicht stillschweigend
nach der ersten aufgelöst. Bei einer Frage, die über fremde Abrechnung
entscheidet, ist „nimm den ersten" die falsche Vorgabe.

### Kein fremder Text im Antwortkörper

Keine Meldung, die eine Fremdbibliothek oder ein Anbieter geschrieben hat,
erreicht den Aufrufer. Der Grund ist nachgemessen: Ein Schlüssel mit einem
Zeilenumbruch erzeugt in `requests` eine `InvalidHeader`, deren Text den
**Wert** enthält —

```
Invalid ... in header value: 'Bearer sk-GEHEIM-DES-AUFRUFERS\nX: y'
```

— und `llm.frage` bettet `{exc}` ein. Der Satz landete so in
`Ergebnis.fehler`, und von dort in die gerenderte Seite und in jede mit
`--bericht` geschriebene Datei. Derselbe Weg trägt `antwort.text[:300]`
des Anbieters.

Ausgeliefert werden deshalb ausschließlich kuratierte Sätze, ausgewählt
über `LLMFehler.art`. Das ist die eigentliche Aufgabe von `art`: Ohne ihn
müsste die Route deutsche Fehlerprosa zerlegen, um einen Statuscode zu
wählen, und eine Umformulierung änderte still das Verhalten.

### Warum 200 auch dann, wenn die Prüfung nicht durchgeht

Die Anfrage wurde verstanden, vollständig verarbeitet und beantwortet;
Token wurden verbraucht. Ein 4xx gäbe dem Aufrufer die Schuld, obwohl er
nur einen Satz Text geschickt hat. Ein 5xx behauptete, der Server sei
kaputt, obwohl er den Mangel im Gegenteil **erkannt** hat — und diese
Erkennung ist das Produkt. Präzedenzfall im eigenen Haus: `$validate`
antwortet 200 und legt das Urteil in den OperationOutcome.

Durchgesetzt wird die Zusage über die **Form** der Antwort: Bei
`fertig == false` heißt das Feld `bundle_zurueckgehalten` statt `bundle`.
Ein Client, der stumpf `daten["bundle"]` liest, bekommt einen `KeyError`
statt still ungeprüfte Daten weiterzureichen. Das ist ein Riegel gegen
Unachtsamkeit, keine Mauer — und genau so ist er gemeint.

### Warum „unbegrenzt" nicht „ohne Grenzen" heißt

Die Auflage lautet: keine Anzahlgrenze über die Zeit. Sie lautet nicht:
ein Aufrufer bekommt die Maschine allein.

Gemessen am Bestand: ein uvicorn-Prozess ohne `--workers`, alle Routen
synchron, also im AnyIO-Threadpool mit 40 Plätzen — geteilt mit der
Weboberfläche. Ein einzelner Lauf kann rechnerisch bis zu 22 Minuten
belegen (`versuche=3` × `timeout_s=180` plus Wartepausen, mal
`generiere(versuche=2)`). Ohne Deckel könnte ein Aufrufer mit **gültigem
eigenem** Schlüssel die Seite für alle anderen unbenutzbar machen, ohne
das Kontingent des Betreibers auch nur zu berühren.

Deshalb bleiben: höchstens vier gleichzeitige Läufe (nicht blockierend
erworben — wer keinen Platz bekommt, erfährt es sofort statt in einer
Warteschlange zu hängen), 64 KB Körpergröße, `MAX_PATIENTEN`, 2000 Zeichen
Beschreibung, und für den API-Pfad kürzere Zeitgrenzen als in der
Oberfläche: Dort wartet ein Mensch, der zusieht.

Ausdrücklich **keine** Anfragen-je-Minute-Bremse. Die Auflage ist als hart
formuliert, und diese Abweichung stünde nicht dem Entwickler zu.

### Zwei Bremsen für das Kontingent des Betreibers

Von rechts zu zählen behebt den gemessenen Fall, verlässt sich aber auf
eine richtig eingestellte Zahl vertrauenswürdiger Proxys — bei Render
genau einer. Steht sie falsch, ist die Lücke zurück.

Daneben steht deshalb eine **Gesamtbremse ohne Kennung**: Sie zählt
schlicht, wie oft der Betreiberschlüssel im Zeitfenster benutzt wurde. Sie
lässt sich nicht fälschen, weil es nichts zu fälschen gibt.

Der Preis ist ehrlich zu nennen: Wer sie ausschöpft, sperrt für den Rest
des Fensters auch alle anderen anonymen Besucher aus. Das ist gewollt. Die
Zusage lautet „das Kontingent des Betreibers bleibt seines", nicht „jeder
Besucher bekommt seinen Anteil" — und ein erschöpftes Gratiskontingent
sperrt ohnehin alle aus, nur ungewollt.

### Das Schema war schon offen

`docs_url=None` schaltet nur die Swagger-Oberfläche ab, **nicht** das
Schema. Nachgemessen antwortete `/openapi.json` mit 200 und listete unter
anderem das Formularfeld `eigener_schluessel`. Die Absicht hinter der
Abschaltung war richtig, die Umsetzung unvollständig. Das Schema liegt
jetzt unter `/api/v1/openapi.json`, die Oberflächenrouten stehen mit
`include_in_schema=False` nicht mehr darin, und `version` ist auf `"v1"`
festgelegt statt auf die Paketversion.

---

## 3a. Nachweis (2026-08-31)

Gegen den laufenden Dienst und einen **echten** Groq-Aufruf:

| Fall | Ergebnis |
|---|---|
| kein Kopf | 401 `schluessel_fehlt`, `WWW-Authenticate: SynthFHIR-LLM-Key` |
| leerer Kopf | 400 `schluessel_leer` |
| **falscher** Schlüssel | 401 `schluessel_abgelehnt` |
| eigener Schlüssel | 200, 10/10 valide, Integrität ok, 3,6 s |

Der dritte Fall ist der aussagekräftigste: Wäre der Betreiberschlüssel
eingesprungen, hätte ein *falscher* Schlüssel funktioniert.

In der Antwort des Erfolgsfalls: `lauf.schluessel_herkunft = "aufrufer"`,
kein Schlüssel, keine Anbieter-URL, kein Variablenname des Betreibers.

Die geschlossene Lücke der Ratenbremse, gemessen an derselben App:

| | vorher | nachher |
|---|---|---|
| 50 Anfragen, rotierender gefälschter Kopf | 30 Aufrufe / 0 × 429 | **5 Aufrufe / 45 × 429** |

Testreihe: **540 grün** gegen beide Server (vorher 508), davon 30 neue.

Zwei der neuen Tests wurden gegen absichtlich eingebaute Fehler geprüft.
Der Test des Gleichzeitigkeitsdeckels färbte sich rot, als die Freigabe
entfernt wurde, **und** als der Deckel entfernt wurde. Dabei fiel auf,
dass er zwar grün war, aber mit einer Leerlaufschleife wartete, die unter
dem GIL genau die Threads aushungert, auf die sie wartet — er lief beim
zweiten Gegenversuch gar nicht mehr durch und ist ersetzt.

---

## 4. Konsequenzen

### Positiv

- Das Kontingent des Betreibers ist erstmals tatsächlich geschützt, und
  zwar unabhängig von einer fälschbaren Kopfzeile.
- Der Rückfall auf den Betreiberschlüssel ist an der Quelle geschlossen,
  nicht bei einem Aufrufer.
- `LLMFehler.art` macht Fehlerbehandlung überall im Projekt entscheidbar,
  ohne Prosa zu zerlegen.
- Ein Weblauf und ein API-Lauf liefern dieselbe Aufzeichnung — für eine
  Prüfkette ist das der wertvollste Teil: Der erste Lauf kostet Token,
  jede Wiederholung ist umsonst.

### Negativ, bewusst in Kauf genommen

- **Wer keinen Groq-Schlüssel hat, kann die API nicht benutzen.** Die
  Anbieter-URL bleibt die des Betreibers; sie vom Aufrufer wählen zu
  lassen wäre eine SSRF-Maschine.
- **Die Gesamtbremse sperrt im Zweifel alle anonymen Besucher.** Siehe
  oben; es ist die gewollte Reihenfolge der Zusagen.
- **Ein API-Lauf kann die Weboberfläche verlangsamen.** Vier gleichzeitige
  Läufe belegen vier der 40 Threadplätze.
- **Die Weboberfläche zeigt weiterhin `str(exc)`** bei
  Konfigurationsfehlern. Anbieter-URL und Modellname stehen ohnehin im
  Klartext in `render.yaml` eines öffentlichen Repositories — der
  Verschleierungsaufwand wäre dort unehrlich. Die irreführende Meldung
  „Fehlt SYNTHFHIR_LLM_API_KEY?" ist trotzdem behoben.
- **Ein zusätzliches Feld auf `Ergebnis`** (`fehlerart`).

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| Schlüssel im Anfragekörper | Nachgemessen: Ein Pydantic-Fehler gibt den Wert wörtlich zurück. |
| Schlüssel als `Authorization: Bearer` | Eine Falschauskunft — hier wird niemand authentifiziert, sondern eine fremde Zugangsdate weitergereicht. |
| `fastapi.security.APIKeyHeader(auto_error=True)` | Prüft nur `if not api_key`: „fehlt" und „leer" fallen zusammen, und reiner Leerraum läuft durch. |
| Prüfung nur in der Route | Ein Umbau entfernt sie, und die Suite bliebe grün. Der Riegel gehört an die Quelle. |
| Anbieter-URL oder Positivliste vom Aufrufer | SSRF, und eine zweite dauerhaft zu pflegende Konfigurationsfläche. |
| `/api/v1/push` | `push.py` schreibt in eine frei wählbare Ziel-URL. Als Endpunkt wäre das eine SSRF-Maschine. |
| Ein FHIR-`$generate` mit `Parameters`/`OperationOutcome` | Drei Beschreibungen derselben Sache (OperationDefinition, CapabilityStatement, CodeSystem), die auseinanderlaufen, ohne dass ein Test es merkte. Der Inhalt ist ohnehin FHIR. |
| 4xx oder 5xx bei `fertig == false` | Weder der Aufrufer noch der Server hat einen Fehler gemacht; der erkannte Mangel ist das Produkt. |
| CORS | Schützt den Server nicht — eine einfache POST-Anfrage erreicht die Route ohnehin; CORS entscheidet nur, ob der Browser die *Antwort* lesen darf. Der Verbrauch entsteht beim Aufruf. |
| Anfragen-je-Minute-Bremse für die API | Widerspräche der ausdrücklichen Auflage. Gleichzeitigkeit und Zeitbudget binden die Maschine bereits. |
| Nur die Bremse von rechts zählen lassen | Verlässt sich auf eine richtig eingestellte Zahl. Die Gesamtbremse braucht keine Annahme. |

---

## 6. Offen

- **`/api/v1/wiedergeben`.** Für CI/CD der eigentlich wertvolle Endpunkt,
  weil eine Wiedergabe keinen Modellaufruf braucht. Nicht gebaut, weil er
  Scope über die Auflage hinaus wäre — **und** weil eine Prüfung zeigte,
  dass er der stärkste Verstärker wäre: Eine Aufzeichnung von 448 KB
  erzeugt über `baue_aus_aufzeichnung` mehrere tausend Ressourcen in
  Sekunden. Er braucht zuerst die nächste Zeile.
- **Keine Obergrenze für Ressourcen je Patient.** `MAX_PATIENTEN` gilt nur
  für die *Länge* der Patientenliste; die Listen *innerhalb* eines
  Patienten sind ungedeckelt. Über die API nicht erreichbar, weil die
  Parameter vom Modell kommen und `max_tokens` sie deckelt — über
  Kommandozeile und Wiedergabe schon.
- **Die Zahl vertrauenswürdiger Proxys ist gegen Render nicht
  nachgemessen**, nur hergeleitet. Die Gesamtbremse hält unabhängig davon.
- **Kein Gesamtzeitbudget je Anfrage**, nur kürzere Einzelzeitgrenzen. Ein
  Gegenüber, das langsam tropft, hält seinen Platz länger als gedacht.
