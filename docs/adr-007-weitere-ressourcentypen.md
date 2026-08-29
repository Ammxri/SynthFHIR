# ADR-007: Encounter und MedicationStatement — und was sie kosten

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-08-30 |
| **Phase** | 2 (v1.x), PRD-Punkt „Weitere Ressourcentypen" |
| **Betrifft** | Umfang des Katalogs und die Teilgröße aus ADR-004 |
| **Baut auf** | ADR-001 (Katalogprinzip), ADR-002 (Prüfschichten), ADR-003 (Lokalisierung), ADR-004 (Teilkohorten) |

---

## 1. Kontext

Das PRD führt „Weitere Ressourcentypen — Encounter, MedicationStatement
u. a." unter Phase 2 als *Should*. Drei Typen decken laut PRD Block 10 alle
vier Risikoarten ab; weitere bringen also keine neue **Architektur**-Frage,
sondern mehr Inhalt.

Sie bringen aber zwei andere Fragen mit, und beide sind für dieses Projekt
heikel:

1. **Medikamente brauchen Codes.** Der Katalog ist die sicherheitskritische
   Komponente: Weder die Laufzeitprüfung noch HAPI prüfen Codes — HAPI
   meldet ausdrücklich `CodeSystem is unknown and can't be validated`.
   Jeder neue Code ist nur so gut wie seine Prüfung an der Primärquelle.
2. **Mehr Ressourcen je Patient heißt mehr Token.** ADR-004 hatte das als
   offenen Punkt vermerkt: *„Ob die Teilgröße von 15 auch bei
   Ressourcentypen jenseits der heutigen drei trägt."*

---

## 2. Entscheidung

**Encounter und MedicationStatement kommen hinzu. Die Codes stammen aus
ATC (WHO) und dem ValueSet v3-ActEncounterCode, jeder einzeln an der
Primärquelle geprüft. Die Teilgröße sinkt von 15 auf 8.**

Sechs Festlegungen:

1. **19 Wirkstoffe**, ATC-kodiert, je mit den Diagnosen verknüpft, zu
   denen sie passen.
2. **4 Begegnungsarten** (AMB, IMP, EMER, VR) aus v3-ActEncounterCode.
3. **`status` setzt der Code**, nicht das Modell — bei beiden neuen Typen.
4. **`Encounter.type` bleibt leer.**
5. **Diagnosen und Messwerte verweisen auf die Begegnung**, aber nur wenn
   es eine gibt.
6. **Teilgröße 8 statt 15**, hergeleitet aus einer Messung.

---

## 3. Begründung

### Warum ATC und nicht PZN oder SNOMED

ATC ist das System, das die deutschen FHIR-Basisprofile für Wirkstoffe
vorsehen, und — entscheidend — es ist **öffentlich und einzeln prüfbar**.
Der ATC/DDD-Index des WHO Collaborating Centre for Drug Statistics
Methodology beantwortet eine Abfrage je Code:
`https://atcddd.fhi.no/atc_ddd_index/?code=A10BA02` → „metformin".

Genau diese Prüfbarkeit ist das Auswahlkriterium. Eine PZN bezeichnet ein
konkretes Handelspräparat und wechselt mit dem Markt; SNOMED-Arzneimittel
wären ohne Lizenz mühsamer zu belegen. Ein Codesystem, dessen Einträge sich
nicht von Hand nachschlagen lassen, ist für diesen Katalog untauglich —
nicht weil es schlechter wäre, sondern weil hier die Handprüfung die
**einzige** Prüfung ist.

Die System-URI lautet `http://www.whocc.no/atc` — die von HL7
kanonisierte URI der WHO-Fassung. Hier stand zuerst die deutsche amtliche
Fassung `http://fhir.de/CodeSystem/bfarm/atc`; warum das falsch war, steht
in Abschnitt 3b.

Nebenbei geprüft und für das Projekt wichtig: Träte die deutsche Fassung
je hinzu, hieße sie `bfarm/atc` und nicht `dimdi/atc` — DIMDI ist im BfArM
aufgegangen, und die Basisprofile haben beide URLs umbenannt. Viele
Anleitungen im Netz nennen noch `dimdi`. Nachgeprüft an Leitfaden Basis DE
1.3.1, wo ATC und ICD-10-GM beide `bfarm` tragen; damit ist zugleich
bestätigt, dass die bereits verwendete ICD-URI die aktuelle ist.

### Warum die englische Kleinschreibung im `display` bleibt

`display` steht wörtlich so da, wie der WHOCC-Index es schreibt:
`metformin`, `acetylsalicylic acid`, `levothyroxine sodium`. Eine geglättete
Schreibweise sähe besser aus und ließe sich nicht mehr gegen die Quelle
abgleichen — und dieser Abgleich ist die einzige Prüfung, die es für Codes
gibt.

Genau deshalb muss die System-URI die der WHO sein: Der Anzeigetext gehört
zum genannten System. Der deutsche Name steht in `text`, nicht in einem
zweiten Coding, weil er aus keiner geprüften Quelle stammt.

### Warum die Wirkstoffe ihre Indikationen kennen

Ohne diese Verknüpfung müsste das Modell entscheiden, welches Mittel zu
welcher Krankheit gehört. Das ist eine **fachliche** Aussage, und nach
ADR-001 gehören die ins Katalogsystem, nicht ins Modell. Mit der
Verknüpfung nennt der Prompt zu jedem Wirkstoff seine Indikation, und die
Zuordnung wird prüfbar.

Fünf Diagnosen haben bewusst **keinen** Wirkstoff — Adipositas, Multiple
Sklerose, Hepatitis B, bösartige Neubildung, Schlafapnoe. Ersatzweise
irgendetwas zu wählen wäre ein fachlicher Fehler, den keine Prüfschicht
bemerkt: Weder die Laufzeitprüfung noch HAPI wissen, wogegen Metformin
hilft.

### `Encounter.class` ist ein `Coding`

Nicht ein CodeableConcept. Der Unterschied ist im JSON fast unsichtbar, und
er ist gemessen: HAPI antwortet auf ein `{"coding": [...]}` an dieser Stelle
mit *„Unrecognized property 'coding'"*. Die Laufzeitprüfung fängt es
ebenfalls (`class.coding: Extra inputs are not permitted`) — hier greifen
also ausnahmsweise beide Schichten.

### Warum `status` aus dem Code kommt

Weil nur **eine** Schicht ihn prüft. Gemessen:

| Fall | Laufzeitprüfung | HAPI 4.0.1 |
|---|---|---|
| `class` als `CodeableConcept` | erkannt | erkannt |
| `class` fehlt | erkannt | erkannt |
| **`status: "abgeschlossen"`** | **geht durch** | erkannt |
| `medication[x]` fehlt | erkannt | — |

Das ist genau die Lücke, die ADR-002 benennt: `fhir.resources` erzwingt
required bindings nicht. Ein Statuswert vom Modell käme also im Betrieb
durch und fiele erst beim Empfänger auf. Deshalb setzt ihn die Vorlage,
wie sie schon Einheiten und Codes setzt.

### Warum `Encounter.type` leer bleibt

Es wäre schmückend und verlangte SNOMED-Codes für Begegnungsarten — jeder
davon einzeln an der Primärquelle zu prüfen. Ein ungeprüfter Code ist
teurer als ein fehlendes optionales Feld. Die Begegnung trägt ihre
Aussagekraft in `class`.

### Warum die Teilgröße auf 8 sinkt

Nicht vorausgeplant, sondern erzwungen. Der erste Lauf nach der Erweiterung
scheiterte an **HTTP 413**:

```
Kontingent: 8000 Token/Minute, angefragt: 8616
(davon 5600 als max_tokens reserviert)
-> max_tokens auf höchstens 4584 setzen
```

Die beiden neuen Kataloge haben den Prompt auf 3016 Token getrieben. Mit
5600 reservierten Ausgabe-Token passt keine Anfrage mehr unter das
Kontingent. Die Rechnung danach:

| Größe | Wert |
|---|---|
| Prompt mit fünf Katalogen | 3016 Token |
| verbleibt für `max_tokens` | 4984 → gewählt **4800** |
| Ausgabe je Patient | **504 Token** (vorher rund 276) |
| ergibt rechnerisch | 9,5 Patienten je Teil |
| gewählt mit Reserve | **8** |

Die Ausgabe je Patient hat sich fast verdoppelt — Begegnung, Medikation und
die Verweise darauf kosten. Ein Test hält die Rechnung fest, damit sie beim
nächsten Katalogwachstum nicht wieder still reißt.

---

## 3a. Nachweis (2026-08-30)

Echter Lauf: *„8 Patientinnen und Patienten mit Typ-2-Diabetes und
Bluthochdruck, mit Medikation und je einem ambulanten Termin"*.

| Prüfung | Ergebnis |
|---|---|
| Ressourcen | 8 Patient, 8 Encounter, 16 Condition, 32 Observation, 16 MedicationStatement |
| Mengentreue | 8 von 8 — 100 % |
| **Gültig gegen HAPI 4.0.1** | **80/80 — 100 %** |
| Referenzintegrität | 0 kaputte Verweise |
| Wirkstoff passt zur Diagnose desselben Patienten | **16 von 16** |
| Vergebene Wirkstoffe | Metformin (Diabetes), Ramipril (Hypertonie) |
| Wiedergabe der Aufzeichnung | byteweise identisch, 0 Token |
| NDJSON-Ladereihenfolge | Patient → Encounter → MedicationStatement → Condition → Observation |

Die Ladereihenfolge stimmte **ohne Codeänderung**: Sie wird aus den
tatsächlichen Verweisen abgeleitet (ADR-005), nicht aus einer Liste. Das
war der Zweck der Entscheidung, und hier zahlt sie sich zum ersten Mal aus.

Zusätzlich prüft die Pflichtprüfkette aus ADR-002 jeden neuen Katalogeintrag
einzeln gegen HAPI — 4 Begegnungsarten und 19 Wirkstoffe, je ein Test.

---

## 3b. Nachträglich gefundene Fehler (2026-08-30)

Eine gegnerische Durchsicht fand vier Fehler. Der erste bringt eine ganze
Kohorte zu Fall.

### Teilübergreifende Kennungskollision

`baue_aus_parametern` ließ **alle** Typzähler beim `index_versatz`
beginnen. Der Versatz wächst aber nur um die Zahl der **Patienten**. Hat
ein Patient mehr als eine Ressource eines Typs, überholt der Zähler den
Versatz — und im nächsten Teil kollidieren die vorläufigen Kennungen.

Nachgestellt mit zwei Teilen zu je drei Patienten mit je zwei Begegnungen:

```
Doppelte Kennungen: tmp-cond-3..5, tmp-enc-3..5
Integrität ok: False
kaputte Verweise: 9
  Condition/cond-005  encounter.reference -> Encounter/tmp-enc-4
```

**Der Fehler steckte seit ADR-004 im Code.** Er war folgenlos, solange
keine erzeugte Ressource auf eine andere erzeugte Nicht-Patient-Ressource
zeigte — und genau das tut seit dieser Änderung `Condition.encounter`. Der
200-Patienten-Nachweis aus ADR-004 war davon nicht betroffen: Dort
verwiesen Diagnosen und Messwerte ausschließlich auf Patienten, und deren
Nummerierung war korrekt.

Behoben, indem die Typzähler teil-lokal bei null beginnen und der Versatz
als Teilkenner in die Kennung wandert (`tmp-enc-{versatz}-{n}`). Das
schließt die Kollision baulich aus, statt sie diesmal zu beheben.

**Der vorhandene Test deckte den Fall nicht ab.** Er benutzte einen
Patienten mit einer Begegnung — die einzige Konstellation, in der die
Kollision nicht auftritt. Er war grün und wertlos.

### Die übrigen drei

| Befund | Was passierte | Behebung |
|---|---|---|
| **`erfundene_codes` zählte nur zwei Arten** | Eine Aufzählung von Hand; mit Phase 2 kamen zwei Arten hinzu, und die PRD-Metrik meldete 2 von 4 | Präfixprüfung `art.startswith("erfunden")` an allen drei Stellen |
| **`FESTE_WERTE` war deklariert und unbenutzt** | Eine Konstante, die aussieht, als täte sie etwas | im Fingerabdruck verdrahtet |
| **Englischer Anzeigetext unter deutscher System-URI** | `display: "metformin"` unter `bfarm/atc` — dort heißt der Eintrag „Metformin" | System auf `http://www.whocc.no/atc` umgestellt, die von HL7 kanonisierte WHO-URI |

Der dritte ist mehr als eine Formalie. `Coding.display` soll die
Bezeichnung **aus dem genannten System** sein. Geprüft habe ich Code *und*
englische Bezeichnung bei der WHO — also gehört die WHO-URI dazu. Die
deutschen Namen stammen aus keiner geprüften Quelle und stehen deshalb in
`text`, nicht in einem zweiten Coding. Das ist derselbe Grundsatz, den
ADR-003 für ICD-10-GM festgelegt hat: lieber keine zweite Kodierung als
eine geratene.

### Nachweis nach den Korrekturen

Fünf Teile, 40 Patienten, je zwei Ressourcen pro Typ — die Form, die brach:

| Prüfung | Ergebnis |
|---|---|
| Ressourcen | 40 Patient, je 80 Encounter, Condition, Observation, MedicationStatement |
| Mengentreue | 100 % |
| Doppelte Kennungen | keine |
| Kaputte Verweise | 0 |
| Verweise auf eine fremde Begegnung | keine |
| **Gültig gegen HAPI 4.0.1** | **360/360** |

---

## 4. Konsequenzen

### Positiv

- Realistischere Datensätze: Wer eine Kohorte mit Medikation braucht,
  bekommt sie.
- Die abgeleitete Ladereihenfolge und der Katalog-Fingerabdruck haben die
  Erweiterung ohne Änderung überstanden.
- Der Prompt nennt zu jedem Wirkstoff die Indikation — das Modell wählt
  aus, es entscheidet nicht.

### Negativ, bewusst in Kauf genommen

- **Kleinere Teile, längere Läufe.** 200 Patienten brauchen nun 25 Aufrufe
  statt 13. Mit `--pause 60` also über 25 Minuten. Das ist der Preis des
  Gratistarifs, nicht der Erweiterung.
- **19 Wirkstoffe sind wenig.** Sie decken 20 der 25 Diagnosen ab. Mehr
  hieße mehr Handprüfung — jeder Code einzeln.
- **Keine Dosierung als strukturierte Menge.** `dosage[0].text` ist
  Freitext. Eine `doseAndRate`-Angabe verlangte wieder UCUM-Einheiten, und
  die sind eine eigene Fehlerklasse (Phase 0).
- **`Encounter.type` und `serviceType` fehlen.** Siehe oben.
- **Bestehende Aufzeichnungen liefern jetzt andere Bundles**, weil
  Diagnosen und Messwerte nun auf die Begegnung verweisen. Die Wiedergabe
  meldet das als `ABWEICHUNG` — richtig so, das ist der Selbsttest aus
  ADR-006 bei der Arbeit.

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| Deutsche ATC-URI (`bfarm/atc`) mit englischem `display` | Stand zuerst da und ist falsch: Der Anzeigetext gehört zum genannten System. |
| Zweites Coding mit der deutschen ATC-URI und deutschem Namen | Die deutschen Namen sind nicht an der Primärquelle geprüft. ADR-003-Grundsatz: lieber eine geprüfte Kodierung als zwei, von denen eine geraten ist. Offen, sobald sie geprüft sind. |
| PZN statt ATC | Bezeichnet ein Handelspräparat, wechselt mit dem Markt, und ein einzelner Schlüssel ist nicht so einfach öffentlich zu belegen. |
| SNOMED CT für Wirkstoffe | Ohne Lizenz mühsamer nachzuschlagen. Für einen Katalog, dessen einzige Prüfung die Handprüfung ist, ist das ausschlaggebend. |
| `medicationReference` auf eine Medication-Ressource | Verlangte einen sechsten Ressourcentyp, ohne dass die Testdaten etwas gewönnen. |
| `Encounter.type` mit SNOMED füllen | Jeder Code einzeln zu prüfen, für ein optionales Feld. Ungeprüfte Codes sind teurer als fehlende. |
| Teilgröße bei 15 lassen und `max_tokens` senken | Rechnerisch unmöglich: 15 × 504 = 7560 Ausgabe-Token, verfügbar sind 4984. |
| Den Prompt kürzen, um die Kataloge unterzubringen | Die Katalogtexte SIND der Prompt — sie zu kürzen hieße, dem Modell Codes vorzuenthalten. |

---

## 6. Offen

- Ein zweites Coding mit der deutschen ATC-Fassung
  (`http://fhir.de/CodeSystem/bfarm/atc`), sobald die deutschen
  Wirkstoffnamen an der amtlichen Quelle geprüft sind. Dann trüge die
  Medikation zwei Kodierungen desselben Konzepts, genau wie die Diagnose.
- Wirkstoffe für die fünf Diagnosen ohne Eintrag, falls sie gebraucht
  werden.
- Strukturierte Dosierung (`doseAndRate`) samt UCUM-Prüfung.
- `Encounter.type`, falls jemand ihn braucht — dann mit geprüften Codes.
- Ob sich die Teilgröße bei einem bezahlten Tarif wieder anheben lässt. Die
  Grenze ist der Tarif, nicht das Modell.
