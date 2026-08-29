# ADR-004: Große Kohorten in Teilen, zusammengeführt am Ende

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-08-29 |
| **Phase** | 2 (v1.x), Gate „stabile Validität bei größeren Kohorten" |
| **Betrifft** | Erzeugung von Kohorten oberhalb eines LLM-Aufrufs |
| **Baut auf** | ADR-001 (Variante B), ADR-002 (zweistufige Validierung) |

---

## 1. Kontext

Phase 1 liefert bis zu 25 Patienten je Anfrage. Diese Grenze ist nicht
willkürlich: Gemessen am 2026-08-28 schöpften 25 Patienten mit je zwei
Messwerten **84,9 %** der Token-Obergrenze von 5600 aus. Bei drei Messwerten
je Patient reißt es.

Das Gate der Phase 2 verlangt Kohorten in dreistelliger Größe. Ein einzelner
Aufruf trägt das nicht — die Frage ist also nicht *ob* gestückelt wird,
sondern **wie die Teile zusammenfinden, ohne dass die Kohorte dabei
zerbricht.**

Das ist keine bloße Fleißarbeit. Die Vorlagen vergeben vorläufige Kennungen
ab `tmp-pat-0`; jeder Teil beginnt für sich wieder bei null. Zwei
aneinandergehängte Teile tragen damit dieselben Kennungen, und die Verweise
des zweiten Teils zeigen auf Patienten des ersten. Nachgestellt: **drei
doppelte Kennungen und vier kaputte Referenzen** bei zwei Teilen zu je zwei
Patienten. Bei dreizehn Teilen wäre das Ergebnis unbrauchbar — und zwar
lautlos, denn strukturell ist jede einzelne Ressource weiterhin gültig
(ADR-002, Abschnitt Referenzintegrität).

---

## 2. Entscheidung

**Der Auftrag wird in Teile zu je 15 Patienten zerlegt. Jeder Teil bekommt
einen Index-Versatz. Die endgültigen Kennungen werden erst am Ende vergeben,
einmal über die gesamte Kohorte.**

Vier Festlegungen im Einzelnen:

1. **Teilgröße 15**, bewusst unter den gemessenen 25. Das lässt Luft für
   Patienten mit mehreren Diagnosen und Messwerten, ohne die Zahl der
   Aufrufe unnötig zu treiben.

2. **`index_versatz` je Teil.** `baue_aus_parametern` beginnt nicht bei
   `tmp-pat-0`, sondern beim Versatz. Der Versatz wächst um das, was ein
   Teil **tatsächlich geliefert** hat, nicht um das, was angefragt war —
   sonst klaffte in der Nummerierung eine Lücke, wo nie ein Patient war.

3. **`assign_ids` läuft einmal über die gesamte Kohorte**, nicht je Teil.
   Liefe es je Teil, trüge jeder Teil wieder `pat-001` — dasselbe Problem
   eine Ebene höher, nur nach der Normalisierung und damit noch schwerer zu
   sehen.

4. **Ein ausgefallener Teil bricht die Kohorte nicht ab.** Er wird
   protokolliert, die übrigen laufen weiter, und die Mengentreue weist die
   Lücke aus.

---

## 3. Begründung

### Warum nicht ein Aufruf mit höherem `max_tokens`?

Weil die Obergrenze nicht am Modell hängt, sondern am Kontingent. Anbieter
rechnen `max_tokens` in die **Anfragegröße** ein: Ein `max_tokens` von 16000
ließ in Messreihe 01 jede Anfrage mit HTTP 413 scheitern, obwohl kein
einziges Token erzeugt wurde. Ein höherer Wert verschiebt das Problem nicht,
er verschärft es.

### Warum die IDs erst am Ende?

Das ist dieselbe Trennung, die ADR-001 zugunsten der Variante B entschieden
hat, eine Ebene höher angewandt: **Das Modell liefert Inhalt, der Code
stellt die Struktur her.** Ein Teil weiß nichts von den anderen und kann
nichts über die Gesamtkohorte garantieren. Also garantiert er auch nichts —
die Kennungen entstehen dort, wo die vollständige Sicht existiert.

### Warum ein halbes Ergebnis statt Abbruch?

Das ist der Grundsatz aus Phase 0, der schon die Messreihe gerettet hat: Ein
HTTP 500 durfte nicht die ganze Reihe beenden. Hier gilt er doppelt, weil ein
Lauf über 200 Patienten Minuten dauert — 60 brauchbare Patienten sind mehr
wert als eine Fehlermeldung nach zwölf Minuten.

**Entscheidend ist, dass die Lücke sichtbar bleibt.** Genau daran scheiterte
Variante A in Phase 0: Sie lieferte 79,4 % der geforderten Ressourcen und
meldete Erfolg. Deshalb weist `Kohortenergebnis.mengentreue` das Verhältnis
aus, die Zusammenfassung benennt jeden ausgefallenen Teil, und der
Rückgabewert der Kommandozeile sagt dasselbe ohne Lesen der Ausgabe: `0`
vollständig, `1` Lücken, `2` Abbruch.

### Warum der Takt zwischen den Teilen

Nicht vorausgeplant, sondern gemessen. Der erste Gate-Lauf über 200 Patienten
lief ungetaktet und lieferte **60**. Bei rund 2400 Token Prompt plus 5600
reservierten Ausgabe-Token zählt ein Teil fast 8000 Token — bei einem
Kontingent von 8000 Token je Minute trägt das etwa einen Teil pro Minute.
Vier Teile gingen durch, dann stand die Ratengrenze.

Derselbe Lauf legte einen zweiten Fehler offen: Der Wiederholversuch startete
sofort. Bei den beiden häufigsten Ursachen ist das nutzlos — eine
Ratengrenze steht noch, und ein Namensauflösungsfehler kommt binnen
Millisekunden zurück. Ein Teil verbrannte so beide Versuche in unter einer
Sekunde. Seither wartet der Wiederholversuch.

---

## 3a. Nachweis: 200 Patienten (2026-08-29)

Auftrag: *„Patientinnen und Patienten mit Typ-2-Diabetes, 45 bis 80 Jahre,
mit HbA1c-Werten und Blutdruckmessungen"*, `-n 200 --pause 60`.
Modell `openai/gpt-oss-120b` über Groq, kostenloses Kontingent.

| Kriterium | Ergebnis |
|---|---|
| Teile | 13/13 erfolgreich (12 × 15 + 1 × 20) |
| **Mengentreue** | **200 von 200 — 100 %** |
| Ressourcen | 1020 (200 Patient, 220 Condition, 600 Observation) |
| **Gültig gegen HAPI FHIR 4.0.1** | **1020/1020 — 100 %**, kein blockierender Befund |
| Kennungen | `pat-001` … `pat-200`, lückenlos und eindeutig |
| Referenzintegrität | 0 kaputte Verweise, 0 verwaiste Patienten |
| Erfundene Codes verworfen | 0 |
| Nicht abbildbare Kriterien | keine |
| Namensvielfalt | 188 von 200 eindeutig — 94,0 % |
| Token | 32 998 ein / 55 206 aus |
| Dauer | rund 13 Minuten, davon 12 Minuten Takt |

**Das Gate der Phase 2 — „stabile Validität bei größeren Kohorten" — ist
damit belegt**, und zwar gegen den echten Server, nicht nur gegen die
Laufzeitprüfung.

Der Inhalt trifft den Auftrag: Geburtsjahre 1943–1981 (34 verschiedene),
Geschlecht 100/100, alle 220 Diagnosen mit ICD-10-GM neben SNOMED, die drei
angeforderten LOINC-Codes (HbA1c 4548-4, Blutdruck 8480-6 und 8462-4) mit
den UCUM-Einheiten `%` und `mm[Hg]`.

### Was die Warnungen sagen

HAPI meldet zu jeder Ressource `dom-6` (Narrative fehlt) und zu jeder
Observation eine Empfehlung, einen `performer` zu setzen — beides
Empfehlungen, keine Verstöße.

Aufschlussreicher ist die dritte Warnung: **`CodeSystem is unknown and
can't be validated`** für LOINC *und* ICD-10-GM. Der echte Server prüft
diese Codes also nicht — er kennt die Terminologien nicht. Das bestätigt
unmittelbar, was ADR-003 als Grenze der Absicherung benannt hat: Ein
falscher ICD-Schlüssel im Katalog fällt weder der Laufzeitprüfung noch
HAPI auf. Nur die Prüfung von Hand gegen den BfArM-Katalog fängt ihn.

### Zur Namensvielfalt

94,0 % bei 13 Teilen gegenüber 96,7 % bei 2 Teilen. Zwölf Namen sind
doppelt vergeben, jeder genau zweimal; 73 verschiedene Nachnamen. Der
Prompt-Hinweis streut also noch ausreichend. Der Wert ist zu beobachten:
Fällt er bei mehr Teilen deutlich, greift die Auflage in Abschnitt 4.

---

## 4. Konsequenzen

### Positiv

- Kohorten sind nach oben nicht mehr durch einen Aufruf begrenzt.
- Ein Ausfall kostet einen Teil, nicht den Lauf.
- Die Zerlegung ist für den Aufrufer unsichtbar: Er bekommt ein Bundle mit
  durchgehender Nummerierung.

### Negativ, bewusst in Kauf genommen

- **Die Dauer wächst linear und ist im Gratiskontingent taktgebunden.**
  200 Patienten brauchen 13 Aufrufe, mit `--pause 60` also über zwölf
  Minuten. Das ist der Preis dafür, keinen bezahlten Zugang zu verlangen.
- **Kein Wiederaufsetzen.** Ein Lauf, der bei Teil 9 abbricht, liefert die
  ersten acht Teile — aber es gibt keinen Weg, ihn aufzufüllen. Bei einem
  Zwölf-Minuten-Lauf ist das spürbar. Bewusst nicht gebaut, weil es Ablage
  von Zwischenständen verlangt und damit Scope, der nicht beauftragt ist.
- **Die Vielfalt über Teilgrenzen ist nicht garantiert, nur gestreut.** Ein
  Teil sieht die anderen nicht. Der Prompt bittet um abweichende Namen,
  Geburtsjahre und Wertelagen; erzwingen kann er es nicht.

### Auflage

`Kohortenergebnis.namensvielfalt` misst den Anteil eindeutiger Namen und ist
in jedem Bericht enthalten. Sinkt der Wert bei wachsender Teilzahl deutlich,
ist der Prompt-Hinweis nicht mehr ausreichend und der Entwurf zu überdenken —
etwa durch Mitgeben bereits vergebener Nachnamen oder durch deterministische
Namensvergabe im Code.

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| Ein Aufruf mit hohem `max_tokens` | Zählt in die Anfragegröße; scheitert am Kontingent, bevor ein Token entsteht (HTTP 413, gemessen). |
| IDs je Teil vergeben, danach umnummerieren | Zwei Nummerierungsschritte statt einem, und der zweite müsste alle Verweise nachziehen — mehr Angriffsfläche für genau den Fehler, den die Entscheidung vermeiden soll. |
| Teile parallel abrufen | Vervielfacht den Token-Durchsatz je Minute und läuft im Gratiskontingent sofort in die Ratengrenze. Der Engpass ist das Kontingent, nicht die Latenz. |
| Bei erstem Ausfall abbrechen | Widerspricht dem Grundsatz aus Phase 0 und verschenkt bereits erzeugte, gültige Patienten. |
| Große Kohorten in der Weboberfläche | Ein Lauf über Minuten belegte einen Arbeitsprozess der Demo, die sich einen Anbieterzugang teilt. Die Oberfläche bleibt bei 25. |

---

## 6. Offen

- Wiederaufsetzen abgebrochener Läufe (siehe Konsequenzen).
- Ob die Teilgröße von 15 auch bei Ressourcentypen jenseits der heutigen
  drei trägt. Encounter und MedicationStatement stehen in Phase 2 noch aus
  und erhöhen die Ausgabelänge je Patient.
