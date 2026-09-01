# ADR-012: Eine Mengengrenze — und die Wiedergabe über das Netz

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-09-01 |
| **Phase** | 3 |
| **Betrifft** | `domain/templates.py`, `kohorte.py`, `web/api.py`, Weboberfläche, CLI |
| **Ergänzt** | 2026-09-01: Die Wiedergabe verlangt keinen Schlüssel mehr (Abschnitt 3) |
| **Baut auf** | ADR-004, ADR-006, ADR-009, ADR-011 |

---

## 1. Kontext

ADR-011 hat den programmatischen Zugang gebaut und dabei zwei Punkte
ausdrücklich offen gelassen:

> Keine Obergrenze für Ressourcen je Patient. … Über die API nicht
> erreichbar, weil die Parameter vom Modell kommen und `max_tokens` sie
> deckelt — über Kommandozeile und Wiedergabe schon.

> `/api/v1/wiedergeben` … Nicht gebaut, weil er Scope über die Auflage
> hinaus wäre — **und** weil eine Prüfung zeigte, dass er der stärkste
> Verstärker wäre.

Diese Entscheidung schließt beide, in dieser Reihenfolge. Sie ist zwingend:
Der Endpunkt ist genau der Weg, auf dem ein Aufrufer die Parameterobjekte
**selbst** schreibt, statt sie vom Modell erzeugen zu lassen.

### Drei Achsen, nicht zwei

Nachgemessen am echten Bauweg:

| Angriff | Eingabe | Ergebnis |
|---|---|---|
| **A** ein Patient, 20 000 Messwerte | 1,1 MB | 20 001 Ressourcen, **0 Beanstandungen** |
| **B** 2000 winzige Teile à 2 Ressourcen | 414 KB | 4000 Ressourcen; jedes Teil für sich harmlos |
| **C** unförmige Einträge `[0, 0, 0, …]` | **64 KB** | **21 810 Ressourcen, 20,9 s, 120 MB Spitze** |

C ist der eigentliche Befund und war mir nicht bewusst. Ein Listeneintrag
muss nicht wohlgeformt sein: `templates.py` baut auch aus einer `0` eine
vollständige Observation. Zwei Bytes kaufen eine Ressource — und damit ist
der bestehende Körperdeckel von 64 KB die falsche Achse. Er begrenzt
**Bytes**, nicht **Arbeit**. Vier gleichzeitige Aufrufe dieser Art beenden
einen 512-MB-Tarif.

Ebenso wichtig: Gegen A hilft keine Grenze je Aufruf über die Gesamtzahl,
gegen B keine Grenze je Patient, gegen C keine von beiden. **Es braucht
drei Zahlen, nicht eine.**

### Und drei Abstürze

Beim Nachmessen fielen drei Wege auf, die HTTP 500 ergaben — zwei davon in
Code, der mit ADR-011 bereits ausgeliefert war:

1. **`RecursionError`.** `json.loads` wirft ihn ab rund 5000 Ebenen, und er
   ist kein `ValueError`. `_lies_koerper` fing nur `ValueError`. 60 KB
   Klammern ergaben **HTTP 500** auf `/api/v1/erzeugen`.
2. **`OverflowError`.** Eine Ganzzahl mit 400 Stellen ist ein `int`, kommt
   also durch die Typprüfung von `_messwert` — und `float()` wirft darauf.
   Der Fehler flog durch den ganzen Bauweg nach oben.
3. **`Infinity` / `NaN`.** `json.loads` liest beide Literale
   voreingestellt; `_messwert` liess sie durch; Starlettes Renderer lehnt
   sie mit `allow_nan=False` ab. Die Ressource entstand, und erst das
   **Ausliefern** scheiterte.

---

## 2. Entscheidung

**In der Domäne wird gekappt und gemeldet. Am Netzrand wird abgelehnt.**

| Ort | Grenze | Wert |
|---|---|---|
| `baue_aus_parametern` | Ressourcen je Patienteneintrag | `GRENZE_JE_PATIENT = 80` |
| `baue_aus_parametern` | Notaus je Bauaufruf | `NOTAUS_JE_BAUAUFRUF = 50 000` |
| `/api/v1/wiedergeben` | Anfragekörper | 512 KB |
| `/api/v1/wiedergeben` | Teile | 200 |
| `/api/v1/wiedergeben` | Ressourcen gesamt | 5000 |
| `/api/v1/wiedergeben` | gleichzeitige Läufe | 2 |

Dazu `POST /api/v1/wiedergeben` — **ohne Schlüsselpflicht**, an einem
zweiten, ausdrücklich benannten Router — und die drei Absturzpfade
behoben.

---

## 3. Begründung

### Warum die Grenze in die Domäne gehört

`baue_aus_parametern` ist der Engpass, durch den **alle** Wege laufen:
`generiere`, `_verarbeite_teil` und die Referenzkohorte. Dasselbe Argument
trägt schon `kennzeichne_als_testdaten` am Ende derselben Funktion. Eine
Grenze in `web/api.py` wäre eine Eigenschaft des Aufrufers — und
`synthfhir --wiedergeben fremde_datei.json` hätte gar keine.

### Warum die 80 hergeleitet ist und nicht gesetzt

**Nach oben** begrenzt sie der Katalog selbst: 25 Messwerte, 25 Diagnosen,
19 Medikamente und 4 Kontaktarten sind 73 verschiedene klinische Inhalte
plus den Patienten. Mehr Verschiedenes kann dieses Produkt nicht
ausdrücken.

**Nach unten** die Belege: Der 200-Patienten-Lauf aus ADR-004 erreichte 5,1
Ressourcen je Patient; die Referenzkohorte höchstens 8. Der nächstliegende
legitime Fall darüber ist eine Quartalsmessreihe über zehn Jahre — 40
Messwerte, gemessen 43 Ressourcen, geht durch.

Kein Umgebungsschalter für diese beiden Zahlen. Sie beschreiben den
Bauweg, nicht den Betrieb, und ein Schalter lüde zum Anheben ein. Genau
das ist mit `SYNTHFHIR_LLM_MAX_TOKENS` schon geschehen: Wer den anhebt,
hebt unbemerkt die einzige wirksame Ressourcengrenze von `/erzeugen` mit
an.

### Gekappt wird **nach** dem Sollvergleich

Die naheliegende Reihenfolge wäre gewesen, die Liste zuerst zu beschneiden
und dann wie gehabt weiterzumachen. Gemessen ergäbe das bei einem Patienten
mit 200 Messwerten und einer Erwartung von 200 die Beanstandung:

> Patient 0: 79 Messwerte geliefert, 200 erwartet

Das behauptet etwas Falsches über das Modell. Geliefert hat es 200 —
gekappt hat der eigene Code. Die Mengentreue ist die Kennzahl aus Phase 0,
mit der Variante A verworfen wurde; sie darf nicht die eigene Grenze
messen. Also: erst zählen und melden, dann für den Bau beschneiden.

### In Baureihenfolge, und das Parameterobjekt bleibt unberührt

Verbraucht wird das Budget in der Reihenfolge, in der gebaut wird:
Patient, Begegnungen, Diagnosen, Messwerte, Medikamente. Die Begegnungen
zuerst ist keine Geschmacksfrage — ein gekappter Patient darf nie den
Kontakt verlieren, auf den seine Diagnosen zeigen (`isik-con1`, ADR-009).
Nachgemessen über drei Formen: Integrität `ok`, 0 kaputte Verweise,
0 ungültige Ressourcen.

Gekappt wird **nur die lokale Liste im Bau**, nie das übergebene
Parameterobjekt. Sonst trüge die Aufzeichnung die gekappte Liste, die
Wiedergabe kappte nichts mehr, und die Beanstandung verschwände — der Lauf
sähe rückblickend sauber aus.

**`_setze_obergrenze_durch` bleibt dagegen unangetastet**, obwohl sie
genau das tut. Der Versuch, sie umzustellen, wurde gemessen: Ein Test fiel,
und `MAX_PATIENTEN` überlebte die Wiedergabe nicht mehr. Die In-Place-
Änderung ist dort die einzige Konstruktion, die die Obergrenze über eine
Aufzeichnung hinweg hält. Was an einer Stelle ein Fehler wäre, ist an der
anderen der Mechanismus.

### Eine Meldung je Bauaufruf, nicht je Vorfall

Der Reflex wäre eine Beanstandung je gekapptem Eintrag. Gemessen erzeugen
21 839 unförmige Einträge heute **43 678** Beanstandungen — die Meldung
wäre selbst der Verstärker. Die Sammelmeldung nennt die vollständigen
Zahlen und ist deshalb kein stilles Abschneiden:

> 1 Patienteneintrag überschritt die Grenze von 80 Ressourcen je Eintrag
> (erstmals Eintrag 0 mit 20001 angefragten Ressourcen). 19921 Ressourcen
> wurden verworfen.

### Ohne Sichtbarkeit wäre die Grenze still

`mengentreue` zählt nur Patienten, `teil.geliefert` ebenso, und `fertig`
sieht Beanstandungen gar nicht an. Ein Lauf, der 19 921 Messwerte
verwirft, meldete sonst „Mengentreue 100,0 %" und Rückgabewert 0.

Deshalb gehört zur Grenze:

- `mengengrenze_gegriffen` auf `Ergebnis` und `Kohortenergebnis`, gebildet
  über das **Präfix** `mengengrenze` — nicht über eine Aufzählung, denn
  mit dem Notaus kam eine zweite Art dazu.
- Der Rückgabewert der Kommandozeile wird 1, und die Zusammenfassung nennt
  die Grenze.
- In der Weboberfläche eine vierte Zeile in der Prüfliste, die Überschrift
  **„Valide, aber gekürzt"** statt „Valide gegen FHIR R4", und **beide
  Datenausgaben gesperrt**.

Der letzte Punkt ist der wichtigste, und er wurde nachgestellt: Ohne ihn
lieferte die Seite eine auf 80 Messwerte gekürzte Zehnjahresreihe als
„Valide gegen FHIR R4" mit freigeschaltetem Download aus. Beides wäre
wahr gewesen und zusammen irreführend. Die **Aufzeichnung** bleibt
herunterladbar — sie trägt gerade die *ungekappten* Parameter und ist das,
womit der Nutzer es anders versuchen kann.

### Am Netzrand wird abgelehnt, nicht gekappt

Zwei Gründe, und der zweite wiegt schwerer als die Kosten.

**Erstens** kostet Kappen dort schon zu viel: Die Zählung braucht gemessen
24 ms für 21 839 Einträge, der Bau derselben Eingabe 20,9 Sekunden. Eine
Ablehnung vor dem Bau ist um drei Größenordnungen billiger.

**Zweitens** träfe eine gekappte Wiedergabe auf die Prüfsumme des
Originals, meldete `ABWEICHUNG` und schickte die Ursachensuche in die
Irre. **Kappung und Prüfsummenurteil dürfen sich nie begegnen.** Auf dem
einzigen Weg, wo geteilte Betriebsmittel auf dem Spiel stehen, ist das
konstruktiv ausgeschlossen statt wegargumentiert.

Die exakte Vorzählung (`zaehle_je_patient`, `zaehle_ressourcen`) ist eine
**Abschrift** der Zählweise des Bauwegs — die Sorte Duplizierung, gegen die
dieses Projekt sonst argumentiert. Sie ist nur zu verantworten, weil ein
Zufallstest über 500 verunstaltete Parameterobjekte beide gegeneinander
hält. Der Test wurde gegen zwei absichtliche Fehler geprüft und wird bei
beiden rot.

### Drei Zahlen, weil es drei Achsen sind

- `GRENZE_JE_PATIENT` stoppt **A**. Gegen B blind (jedes Teil harmlos),
  gegen C blind (jeder Eintrag kostet genau eins).
- `WIEDERGABE_TEILE = 200` stoppt **B**. Gemessen ergeben 200 Patienten
  25 Teile, 500 Patienten 63 — 200 ist das Dreifache davon.
- `WIEDERGABE_RESSOURCEN = 5000` stoppt **C**. Das Vierfache des belegten
  200-Patienten-Laufs (1200 Ressourcen).

Die Anhebung des Körperdeckels auf 512 KB und die Ressourcengrenze sind
**eine** Entscheidung: 512 KB unförmiger Einträge ergäben sonst rund
175 000 Ressourcen. Der Deckel muss steigen, weil eine echte
500-Patienten-Aufzeichnung mit `indent=2` gemessen 448 KB misst — bei
64 KB nähme der Endpunkt ausgerechnet die Aufzeichnungen nicht an, für die
er da ist.

### Die Wiedergabe verlangt keinen Schlüssel

Zunächst tat sie es, und der erste Entwurf begründete das damit, dass die
Prüfung am Router verhindert, dass eine später hinzugefügte,
**modellaufrufende** Route sie vergisst.

Der Betreiber hat anders entschieden, und die Entscheidung ist die
bessere. Der Grund steht schon im ersten Entwurf, nur wurde er dort nicht
zu Ende gedacht: Der Schlüssel wurde auf dieser Route **nie auf
Gültigkeit geprüft** — die Route baut keinen Client, jede Zeichenkette
aus druckbarem ASCII genügte. Er zu verlangen schützte also nichts und
sammelte dafür fremde Zugangsdaten ein, die niemand braucht. Eine
Fassade, die man für Schutz hält, ist schlechter als keine.

Geschützt wird die Route durch die Grenzen, die tatsächlich greifen:
Anfragekörper, Teile, Ressourcen, gleichzeitige Läufe. Die Öffnung ist
damit **schutzneutral**; sie ändert nur, wer anklopfen darf.

Die berechtigte Sorge des ersten Entwurfs bleibt trotzdem gültig, und sie
wird jetzt anders beantwortet — **konstruktiv statt durch Verzicht**:

* Es gibt **zwei Router**. `router` trägt die Schlüsselprüfung, jede
  modellaufrufende Route gehört dorthin. `router_offen` trägt sie nicht
  und ist so benannt, dass eine Route dort nur landet, wenn jemand sie
  hinschreibt. Eine Ausnahme direkt an einer Route wäre die gefährlichere
  Form gewesen — sie liesse sich beim nächsten Mal mitkopieren.
* Ein Test geht über **alle veröffentlichten Routen** und verlangt 401
  ohne Schlüssel, mit genau einer namentlich genannten Ausnahme. Eine
  neue, ungeschützte Route färbt ihn rot.

Gegengeprüft: Eine neu hinzugefügte Route am offenen Router lässt den
Test fallen. `/erzeugen` versehentlich dorthin zu hängen dagegen nicht —
diese Route trägt die Prüfung auch in ihrer Signatur, die Sperre hielt
also weiter. Der Test misst „verlangt einen Schlüssel", nicht „hängt am
richtigen Router", und die erste Eigenschaft ist die, auf die es
ankommt.

---

## 3a. Nachweis (2026-09-01)

**Die Grenze, am echten Bauweg:**

| Eingabe | gewünscht | gebaut | Integrität | ungültig |
|---|---|---|---|---|
| 1 Patient, 20 000 Messwerte | 20 001 | **80** | ok, 0 kaputt | 0 |
| 0 Begegnungen, 200 Diag., 200 Mess. | 402 | **80** | ok, 0 kaputt | 0 |
| 200 Begegnungen, 200 Diagnosen | 401 | **80** | ok, 0 kaputt | 0 |
| legitim: 40 Quartalsmesswerte | 43 | **43** | ok | 0 |

Bauzeit im ersten Fall: von 0,20 s auf 0,001 s.

**Der Endpunkt, gegen alle drei Angriffe:**

| Angriff | Antwort |
|---|---|
| 5000 Messwerte bei einem Patienten | 413 `patient_zu_umfangreich` |
| 2000 Teile | 413 `zu_viele_teile` |
| 20 000 leere Einträge | 413 `zu_viele_ressourcen` |
| echte Aufzeichnung | 200, `identisch`, **0 Modellaufrufe** |

**Der teuerste *erlaubte* Aufruf**, nachgemessen: 276 KB Körper → 4975
Ressourcen, 7,95 s, 39,5 MB Spitze, 3,74 MB Antwort. Bei zwei
gleichzeitigen also rund 80 MB — auf einem 512-MB-Tarif tragbar. Diese
Zahl ist der Preis der Grenze 5000 und über
`SYNTHFHIR_API_WIEDERGABE_RESSOURCEN` zu senken.

**Die Weboberfläche**, mit 120 Messwerten für einen Patienten: Überschrift
„Valide, aber gekürzt", Zeile `Mengengrenze` sichtbar, beide
Datenausgaben gesperrt, Aufzeichnung weiterhin verfügbar.

**Testreihe: 570 grün** gegen beide Server (vorher 542), ISiK weiterhin
0 Fehler. Der Zufallstest der Vorzählung wurde gegen zwei absichtliche
Fehler geprüft und wird bei beiden rot.

---

## 4. Konsequenzen

### Positiv

- Die drei gemessenen Verstärkungen sind geschlossen, jede an der Achse,
  auf der sie wirkt.
- Drei Abstürze weniger, zwei davon in bereits ausgeliefertem Code.
- Eine Wiedergabe über das Netz kostet **kein Kontingent** — weder das des
  Betreibers noch das des Aufrufers. Für eine Prüfkette ist das der
  eigentliche Wert des ganzen Zugangs.
- `synthfhir --wiedergeben fremde_datei.json` ist erstmals gegen
  unförmige Dateien abgesichert.

### Negativ, bewusst in Kauf genommen

- **Ein Patient mit mehr als 79 Untereinträgen ist nicht mehr vollständig
  baubar.** Eine monatliche Messreihe über zehn Jahre (120 Werte) wird
  gekappt; eine quartalsweise (40) nicht. Der Nutzer sieht es, bekommt die
  verworfene Zahl genannt und kann die Reihe auf mehrere Patienten
  verteilen.
- **Der Rückgabewert der Kommandozeile kann 1 werden, wo er 0 war** — wenn
  gekappt wurde, ohne dass Patienten fehlen.
- **Die Zahl der Teile ist lokal weiterhin unbegrenzt.** `--anzahl` hat
  keine Obergrenze und soll keine bekommen; jede feste Teilegrenze träfe
  irgendwann einen legitimen grossen Lauf. Wer eine fremde Aufzeichnung
  lokal abspielt, führt ohnehin fremde Daten auf der eigenen Maschine aus.
  **Die Grenze als Schutzwall existiert nur dort, wo die Maschine geteilt
  wird — im Netz.**
- **Eine alte Aufzeichnung, deren Einträge die 80 reissen, meldet jetzt
  `ABWEICHUNG`.** Der Befund „es liegt an den Vorlagen" ist dann richtig.
  Keine solche Aufzeichnung ist nachweisbar; der höchste je gemessene Wert
  ist 8.
- **Ein Aufrufer kann mit zwei Plätzen dauerhaft rund 8 s Rechenzeit je
  Aufruf binden.** Das folgt aus „unbegrenzt mit eigenem Schlüssel" und
  ist über die Umgebung zu senken.

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| Nur eine Zahl statt dreien | Es sind drei Achsen. Gegen B ist jede Grenze je Aufruf blind, gegen C jede Grenze je Patient. |
| Grenze nur in `web/api.py` | Dann hängt der Riegel am Aufrufer, und `--wiedergeben` mit fremder Datei hat gar keinen. |
| Grenze nur in der Domäne, Rand ohne | Kappen kostet dort gemessen 20,9 s statt 24 ms — und eine gekappte Wiedergabe träfe auf die Prüfsumme des Originals. |
| Nach dem Bau abschneiden (`gebaute[:n]`) | Nähme einem Patienten seine Diagnosen nicht mit: Integrität kaputt, Befund läse sich wie ein Datenfehler. Ausserdem lägen alle Kosten schon hinter uns — 60 % entfallen auf die Validierung. |
| Kappen **vor** dem Sollvergleich | Die Mengenabweichung behauptete dann etwas Falsches über das Modell. |
| `_setze_obergrenze_durch` auf nicht-mutierend umstellen | Gemessen: ein Test fällt, und `MAX_PATIENTEN` überlebt die Wiedergabe nicht mehr. |
| Eine Beanstandung je gekapptem Eintrag | 43 678 Beanstandungen für einen Aufruf — die Meldung wäre der Verstärker. |
| Umgebungsschalter für `GRENZE_JE_PATIENT` | Lüde zum Anheben ein. Dieselbe Falle wie `SYNTHFHIR_LLM_MAX_TOKENS`. |
| Körperdeckel 512 KB ohne Ressourcengrenze | Ergäbe rund 175 000 Ressourcen aus unförmigen Einträgen. Beide Zahlen sind eine Entscheidung. |
| `/wiedergeben` mit Schlüsselpflicht | Der Schlüssel wurde dort nie geprüft — eine Fassade, die man für Schutz hält, ist schlechter als keine. Die Sorge um vergessene Prüfungen wird durch zwei Router und einen Test über alle Routen beantwortet. |
| Die Ausnahme direkt an der Route statt an einem zweiten Router | Liesse sich beim nächsten Mal mitkopieren, ohne dass es auffällt. |
| Eine Ratenbremse auf `/wiedergeben` | Widerspräche „mit eigenem Schlüssel unbegrenzt" ausdrücklich. Statt dessen ein Gleichzeitigkeitsdeckel — und die Restgefahr steht oben. |
| Abweichung als HTTP 409 melden | Deutete einen Befund in einen Fehler um. Dieselbe Linie wie `/erzeugen`: Das Urteil ist das Produkt. |

---

## 6. Offen

- **`dauer_s` fehlt der Wiedergabeantwort mit Absicht** (Auslastungssonde).
  Wer die eigene Antwortzeit braucht, misst sie selbst.
- **Kein Gesamtzeitbudget je Anfrage.** Ein Aufruf an der Ressourcengrenze
  dauert gemessen rund 8 s; abgebrochen wird er nicht.
- **Die Zahl der Teile ist lokal unbegrenzt** (siehe Konsequenzen).
- **Namen aus einer Wiedergabe stehen unverändert im Bundle.** Sie kommen
  hier vom Aufrufer, nicht vom Modell. Wer die Antwort weiterverarbeitet,
  behandelt sie als Fremdeingabe; das steht in der Routenbeschreibung.
