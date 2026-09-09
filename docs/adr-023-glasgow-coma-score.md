# ADR-023: Der Glasgow Coma Score — ein Score-Panel mit kodierten Komponenten

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-09-09 |
| **Phase** | 3 (Vision) |
| **Betrifft** | `domain/codes.py`, `domain/templates.py`, `profil.py`, `referenzkohorte.py`, `szenarien.py` |
| **Baut auf** | ADR-014, ADR-019, ADR-022 |

---

## 1. Kontext

ADR-019 und ADR-022 haben GCS und EKG als **echte Sonderfälle** offen
gelassen — anders als der Kopfumfang, der sich als gewöhnlicher
Vitalparameter erwies (ADR-022).

Der Glasgow Coma Score ist wirklich ein Sonderfall. Er ist **kein
einfacher `valueQuantity`**, sondern ein Panel:

- ein **Gesamtwert** (LOINC `9269-2`, 3..15 Punkte) und
- **drei kodierte Komponenten** — Augen (`9267-6`), Motorik (`9268-4`),
  Verbal (`9270-0`) —, deren Wert je ein `CodeableConcept` aus einer
  **required** gebundenen LOINC-Antwortliste ist.

Das ISiK-Profil `ISiKGCS` verfeinert das fhir.de-Score-Profil. Unser
bisheriger Bauweg kannte nur zwei Observation-Formen: den einfachen
Messwert (`valueQuantity`) und das Blutdruck-Panel (Komponenten mit
`valueQuantity`, aber ohne Gesamtwert). Der GCS ist beides zugleich —
Gesamtwert **und** Komponenten — und die Komponenten sind **kodiert**,
nicht numerisch.

---

## 2. Entscheidung

**Der GCS bekommt einen eigenen Bauweg (`baue_gcs`), analog zum
Blutdruck-Panel, und wird in Kohorte und Bibliothek gemessen.**

1. `codes.py` trägt die drei Antwortlisten (Augen/Motorik/Verbal) mit
   ihren LOINC-`LA`-Codes und Punktwerten — **vollständig aus den
   gebundenen fhir.de-ValueSets** `glasgow-coma-score-{eye,motor,verbal}`
   übernommen, nicht gewählt.
2. Ein Gesamtwert wird kanonisch in (Augen, Motorik, Verbal) zerlegt
   (`GCS_DEKOMPOSITION`): eine plausible Aufteilung je Summe 3..15. Ein
   Wert außerhalb wird gekappt und beanstandet.
3. `baue_gcs` erzeugt die Observation: Kategorie `survey`, Gesamtcode
   (nur LOINC), `valueQuantity` (Punktwert), drei Komponenten mit
   `valueCodeableConcept`.
4. Der Messwert-Bauweg erkennt den GCS-Code (`9269-2`) und ruft `baue_gcs`
   statt `baue_observation` — wie das Blutdruckpaar seinen eigenen Weg hat.
5. `profil.py` ordnet `9269-2` → `ISiKGCS` zu. Gemessen wird der GCS an
   Hans-Jürgen (Referenzkohorte, stationäre Aufnahme) und im Szenario
   `intensivkontakt`.

---

## 3. Begründung

### Warum ein Gesamtwert zerlegt wird und nicht drei Werte gefordert werden

Klinisch ist der GCS als „E4 V5 M6" **die** Kurzform, und ein Szenario
oder Modell nennt am ehesten die Summe. Die Zerlegung ist nicht eindeutig,
aber für Testdaten genügt **eine** plausible Aufteilung je Summe. Sie ist
fest hinterlegt, damit die Ausgabe wiedergabestabil ist. Wer die drei
Komponenten einzeln braucht, hat mit der Tabelle die belegte Grundlage.

### Warum die Antwortcodes keinen `display` tragen

Gemessen: Die LOINC-`LA`-Codes haben **keine deutsche Bezeichnung**, und
das Profil bindet den Komponentenwert `required`. Ein englischer
Anzeigename wird dann vom Validator als **Fehler** gemeldet (nicht als
Warnung wie bei einer lockeren Bindung). Deshalb steht der lesbare Text in
`CodeableConcept.text`, der nicht gegen die Terminologie geprüft wird, und
das `coding` trägt nur System und Code. Das Minimalbeispiel der
Spezifikation macht es genauso strukturell.

### Warum Kategorie `survey` und nur LOINC am Gesamtcode

Der GCS ist ein Erhebungsinstrument (`survey`), kein Vitalparameter
(`vital-signs`). Der SNOMED-Slice des Gesamtcodes ist optional (`min=0`);
wie im Minimalbeispiel trägt der Gesamtcode deshalb nur LOINC.

### Warum in die Kohorte

Derselbe Grund wie bei Kopfumfang und Gewicht/Größe (ADR-018/019/022): Ein
Profil, das im Katalog steht, aber von keiner gemessenen Ressource
getroffen wird, sieht konform aus, ohne es gemessen zu haben. Der GCS wird
deshalb sofort mitgemessen.

---

## 3a. Nachweis (2026-09-09)

- **Einzeln gegen `ISiKGCS`** (offizieller HL7-Validator, tx.fhir.org,
  `-sct intl`): ein GCS mit Gesamtwert und drei kodierten Komponenten →
  **0 Fehler**.
- **Referenzvalidator** gegen `de.gematik.isik#5.1.3`: `ISiKGCS 1 geprüft,
  0 Fehler`; Kohorte gesamt **0 Fehler**, nichts ungeprüft
  (`docs/belege/isik-referenzvalidator.json`).
- `vorsorge`/`intensivkontakt`: die Bibliothek zeigt `ISiKGCS`.
- **Testreihe grün.**

---

## 4. Konsequenzen

### Positiv

- **Der GCS ist kein offener Sonderfall mehr.** Der Bauweg beherrscht jetzt
  ein Score-Panel mit Gesamtwert und kodierten Komponenten — die Grundlage,
  auf der das EKG (Kurven als `SampledData`) als nächster Schritt aufsetzt.
- **Belegt statt geraten:** die Antwortcodes und Punktwerte stammen
  vollständig aus den gebundenen ValueSets.

### Negativ, bewusst in Kauf genommen

- **Die Zerlegung ist eine von mehreren.** Der Gesamtwert bestimmt die
  Komponenten eindeutig (feste Tabelle), obwohl klinisch mehrere
  Aufteilungen zu derselben Summe führen. Für Testdaten ist das
  ausreichend; wer echte Komponenten braucht, wählt sie selbst.
- **Ein Messwert mehr in Kohorte und Szenario**, der mitgepflegt wird
  (`geprueft == 33`).

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| GCS als einfacher `valueQuantity` (nur Gesamtwert) | Verfehlt das Profil: `ISiKGCS` verlangt die drei kodierten Komponenten. |
| Die drei Sub-Scores als Parameter fordern statt Gesamtwert zerlegen | Klinisch/als Eingabe ist die Summe die übliche Kurzform; die feste Zerlegung hält die Ausgabe wiedergabestabil und einfach. |
| `display` auf den Antwortcodes behalten | Gemessen ein Fehler: keine deutsche Bezeichnung bei `required`-Bindung. Text statt Display. |
| Antwortcodes selbst wählen | Der Komponentenwert ist `required` an eine ValueSet gebunden — die Listen sind vollständig übernommen, nicht gewählt. |

---

## 6. Offen

- **EKG** — die zweite offene Sonderform: Kurven als `SampledData`
  (Ableitungen mit `origin`/`period`/`dimensions`/`data`). Eigener
  Bauweg, aufbauend auf dem Komponenten-Panel dieses ADR.
