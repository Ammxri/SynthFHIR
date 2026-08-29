# ADR-006: Aufzeichnen statt Seed

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-08-29 |
| **Phase** | 2 (v1.x), PRD-Punkt „Seed / Reproduzierbarkeit" |
| **Betrifft** | Wie sich ein Lauf wiederholen lässt |
| **Baut auf** | ADR-001 (Variante B), ADR-004 (Teilkohorten) |

---

## 1. Kontext

Das PRD führt „Seed / Reproduzierbarkeit" unter Phase 2. Die naheliegende
Umsetzung wäre ein `--seed`, der an den Anbieter durchgereicht wird — so
wie Synthea es mit `-s` löst.

Bevor das gebaut wurde, war zu klären, ob es überhaupt trägt. Zwei
Messungen, beide am 2026-08-29.

### Der Code ist deterministisch

Derselbe Parametersatz durch `baue_aus_parametern`, `assign_ids` und
`baue_bundle`:

- 20 Läufe im selben Prozess → **ein** SHA-256
- 4 Prozesse mit verschiedenem `PYTHONHASHSEED` → **derselbe** SHA-256

Der zweite Teil ist der wichtigere: Er schließt aus, dass irgendwo die
Iterationsreihenfolge einer Menge oder eines Wörterbuchs ins Ergebnis
einfließt. Im Produktcode gibt es zudem keinen Zufall — kein `random`,
kein `uuid4`; `datetime.now` steht nur im NDJSON-Manifest, wo der
Zeitpunkt injizierbar ist.

### Das Modell ist es nicht

Je drei identische Anfragen an `openai/gpt-oss-120b` über Groq:

| Einstellung | verschiedene Antworten |
|---|---|
| `temperature 0.8`, kein Seed (Voreinstellung) | **3 von 3** |
| `temperature 0`, kein Seed | 2 von 3 |
| `temperature 0`, **Seed 42** | 2 von 3 |
| `temperature 0.8`, Seed 42 | 2 von 3 |

**Der Seed verbessert nichts** gegenüber `temperature 0`. Auch der
`system_fingerprint` — das Feld, an dem sich sonst ablesen ließe, ob das
Backend gewechselt hat — wechselte bei fast jedem Aufruf
(`fp_5781dfb07c`, `fp_803c0ba83d`, `fp_e1a78f200e` …) und taugt hier nicht
als Signal.

Damit steht der gesamte Nichtdeterminismus in **einem** Schritt, und
`--seed` kann ihn nicht beseitigen.

---

## 2. Entscheidung

**Es gibt kein `--seed`. Stattdessen wird der Beitrag des Modells
aufgezeichnet und wiedergegeben.**

```bash
synthfhir "200 Patientinnen mit Typ-2-Diabetes" -n 200 --aufzeichnen lauf.aufz.json
synthfhir --wiedergeben lauf.aufz.json -o kohorte.json
```

Die Zusage in einem Satz: **Eine Wiedergabe liefert dasselbe Bundle wie der
aufgezeichnete Lauf — byteweise —, und sie rechnet das bei jedem Abspielen
nach.**

Vier Festlegungen:

1. **Aufgezeichnet werden die Parameterobjekte**, nicht das Ergebnis. Sie
   sind der Beitrag des Modells; alles Weitere stellt der Code her.
2. **Die Aufzeichnung trägt die Prüfsumme des Bundles**, das der
   ursprüngliche Lauf erzeugt hat.
3. **Erzeugung und Wiedergabe laufen durch denselben Code**
   (`_verarbeite_teil`, `_schliesse_ab`).
4. **Eine Abweichung ist ein Befund, kein Abbruch.** Das Ergebnis wird
   geliefert, mit dem Hinweis, dass es nicht dasselbe ist.

---

## 3. Begründung

### Warum kein `--seed`

Weil er nicht hält, was sein Name verspricht — und das ist gemessen. Wer
von Synthea kommt, erwartet bei einem Seed exakte Wiederholbarkeit. Ein
Schalter, der stattdessen „meistens ähnlich" liefert, ist genau die Art
von Zusage, die dieses Projekt in **ADR-001** verworfen hat: Variante A
scheiterte nicht daran, dass sie schlecht war, sondern daran, dass sie
79,4 % lieferte und Erfolg meldete.

Ein `--seed` mit dem Kleingedruckten „garantiert nichts" wäre keine
Lösung, sondern eine Falle mit Fußnote. Der Name ist die Zusage.

### Warum Aufzeichnen trägt

Das ist die Einsicht aus ADR-001, eine Ebene weitergedacht: *Das Modell
liefert Inhalt, der Code stellt die Struktur her.* Wenn der Code
deterministisch ist — und das ist er, gemessen —, dann genügt es, den
Beitrag des Modells festzuhalten. Die Reproduzierbarkeit garantiert dann
**der eigene Code**, nicht die Zusage eines Anbieters.

Nebenwirkungen, die den Ausschlag mitgeben:

- Die Wiedergabe braucht **kein Netz und kein Kontingent**. Bei einem
  200er-Lauf, der getaktet dreizehn Minuten dauert, ist das kein
  Nebeneffekt, sondern der praktische Hauptgewinn.
- Die Aufzeichnung ist klein: gemessen **5,4 KB gegenüber 27 KB** Bundle,
  weil sie die Parameter enthält und nicht das Ergebnis.
- Sie ist lesbar. Wer wissen will, was das Modell beigetragen hat, sieht
  es dort — ohne die FHIR-Hülle drumherum.

### Warum die Aufzeichnung sich selbst prüft

Weil die Zusage sonst genau so lange hielte, bis jemand den Katalog
anfasst. Ändert sich ein ICD-Schlüssel in `codes.py` — und **das ist in
diesem Projekt bereits vorgekommen**, zwei Schlüssel waren falsch —, dann
liefert dieselbe Aufzeichnung ein anderes Bundle. Ohne Vergleich fiele das
niemandem auf.

Die mitgeführte Prüfsumme macht daraus einen Selbsttest: Die Wiedergabe
*behauptet* die Reproduzierbarkeit nicht, sie **weist sie nach**.
Nachgestellt: Ein geänderter ICD-Schlüssel einer benutzten Diagnose
erzeugt sofort `ABWEICHUNG`, samt Hinweis auf den Katalog als
wahrscheinliche Ursache.

Umgekehrt gilt: Ändert sich der Katalog an einer Stelle, die diese Kohorte
nicht benutzt, bleibt das Bundle identisch. Der Befund sagt beides — dass
es stimmt, und dass der Katalog sich trotzdem geändert hat.

### Warum ein gemeinsamer Bauweg

Zwei getrennte Wege liefen mit der Zeit auseinander, und die Wiedergabe
lieferte stillschweigend etwas anderes als der aufgezeichnete Lauf — ohne
dass ein Test es bemerkte. Deshalb wurde der Bauweg aus
`generiere_kohorte` herausgezogen; `baue_aus_aufzeichnung` benutzt exakt
dieselben Funktionen, nur ohne den einen nichtdeterministischen Schritt.

---

## 3a. Nachweis (2026-08-29)

Echter Lauf über die Kommandozeile, 8 Patienten mit Osteoporose:

| Prüfung | Ergebnis |
|---|---|
| Aufzeichnung | 5 427 Bytes (Bundle: 27 128 Bytes) |
| Wiedergabe | 0 Ein- und 0 Ausgabe-Token, kein Netzaufruf |
| **Bundles** | **byteweise identisch** (`db4027c7d91b47a7…`) |
| Selbstprüfung | „identisch zum aufgezeichneten Lauf (Prüfsumme stimmt)" |
| Kennungen | unverändert, `pat-001` … |
| Nicht abbildbare Kriterien | mitgeführt (DXA, Frakturrisiko) |

Nachgestellte Abweichungen:

| Änderung | Erkannt? |
|---|---|
| ICD-Schlüssel einer **benutzten** Diagnose | ja — `ABWEICHUNG`, Katalog als Ursache benannt |
| Deutscher Anzeigetext einer benutzten Diagnose | ja (er landet in `CodeableConcept.text`) |
| Code, den die Kohorte **nicht** benutzt | Bundle identisch, Katalogänderung trotzdem benannt |
| Aufzeichnung ohne Prüfsumme | „lässt sich nicht gegenprüfen" statt stillem Erfolg |

---

## 4. Konsequenzen

### Positiv

- Exakte Reproduzierbarkeit, garantiert vom eigenen Code.
- Wiedergabe ohne Netz und ohne Kontingent — bei getakteten Läufen der
  praktische Hauptgewinn.
- Eine Änderung am deterministischen Weg wird sichtbar, statt still zu
  wirken.
- Aufzeichnungen sind klein genug, um sie neben einen Test zu legen.

### Negativ, bewusst in Kauf genommen

- **Eine Aufzeichnung ist keine Beschreibung.** Sie wiederholt genau den
  einen Lauf. Wer eine *ähnliche* Kohorte will, muss neu erzeugen — es gibt
  keinen Schalter für „so wie damals, aber andere Leute".
- **Kein `--seed`**, obwohl das PRD den Begriff nennt und Nutzer ihn
  erwarten. Der Name wäre eine Zusage ohne Deckung. Die Entscheidung steht
  und fällt mit der Messung oben; ein Anbieter mit echtem Determinismus
  könnte sie umstoßen.
- **Die Aufzeichnung hängt am Katalog.** Sie speichert Codes, keine
  ausformulierten Ressourcen. Ändert sich der Katalog, ändert sich das
  Ergebnis — sichtbar, aber es ändert sich.
- **Kein Schutz gegen Manipulation.** Die Prüfsumme deckt Versehen auf,
  nicht Absicht: Wer die Datei ändert, kann die Prüfsumme mitändern. Für
  Testdaten ist das angemessen.

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| `--seed` an den Anbieter durchreichen | Gemessen wirkungslos: 2 von 3 Antworten verschieden, ebenso wie ohne Seed. Der Name verspricht, was der Anbieter nicht zusichert. |
| `--seed` mit dem Zusatz „ohne Garantie" | Der Name ist die Zusage. Eine Fußnote hebt sie nicht auf. |
| `temperature 0` als Voreinstellung | Verbessert die Wiederholbarkeit nicht ausreichend (2 von 3) und kostet Vielfalt — die bei Testdaten der Zweck ist. Bleibt über `SYNTHFHIR_LLM_TEMPERATURE` einstellbar. |
| `system_fingerprint` als Signal für Backend-Wechsel | Wechselte bei fast jedem Aufruf. Ein Signal, das immer anschlägt, ist keines. |
| Das fertige Bundle speichern statt der Parameter | Wäre kein Aufzeichnen, sondern Kopieren. Änderungen am Katalog oder an den Vorlagen blieben unsichtbar, statt aufzufallen. |
| Prüfsumme weglassen | Dann wäre die Zusage eine Behauptung. Der Selbsttest ist der Grund, warum man ihr trauen kann. |
| Aufzeichnung erzwingen, wenn die Prüfsumme abweicht | Ein Befund ist kein Fehler. Das Ergebnis ist gültiges FHIR; wer damit arbeiten will, soll es können — er muss es nur wissen. |

---

## 6. Offen

- Aufzeichnungen in der Weboberfläche (zustimmungspflichtig, weil UI).
- Ein Weg, aus einer Aufzeichnung heraus *ähnliche* statt gleicher Daten
  zu erzeugen — etwa durch Neuwürfeln der Namen bei gleichen Codes.
- Die Messung gegen ein lokales Ollama wiederholen. Dort könnte ein Seed
  tatsächlich tragen, weil kein geteiltes Batching dazwischenliegt.
