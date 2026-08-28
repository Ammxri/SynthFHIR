# SynthFHIR – Vergleichsbericht Phase-0-Spike

> **Hinweis:** Alle in diesem Spike erzeugten Daten sind rein synthetisch und ausdrücklich **nicht für die klinische Nutzung** bestimmt. Es wurden zu keinem Zeitpunkt echte Patientendaten verarbeitet.

Erstellt: 2026-08-28T18:27:07+00:00  
Anbieter/Modell: `openai_compatible` / `openai/gpt-oss-120b`  
Validierungsserver: `http://localhost:8080/fhir` (FHIR-Version laut Server: 4.0.1)  
Maximale Korrekturrunden: 3

> ℹ️ **Gemessen mit einem frei verfügbaren Modell** (`openai/gpt-oss-120b` über `https://api.groq.com/openai/v1`).
>
> Was das für die Aussagekraft bedeutet, hängt an der Richtung des Ergebnisses und ist für die beiden Varianten unterschiedlich:
>
> - **Variante A:** Ein schlechtes Ergebnis ist immer nur eine **untere Schranke** – es zeigt, dass A mit *diesem* Modell nicht trägt. Wie belastbar das ist, hängt davon ab, wie stark das Modell ist. Bei einem kleinen Modell (7B-Klasse) sagt ein Durchfall wenig über starke Modelle aus; bei einem großen offenen Modell ist der Abstand zur Spitzenklasse gering und der Befund entsprechend aussagekräftiger.
> - **Variante B:** Ein gutes Ergebnis ist unabhängig vom Modell belastbar. Die Struktur kommt aus dem Code, nicht aus dem Modell – was hier ein schwächeres Modell schafft, schafft ein stärkeres erst recht.
>
> Genau diese Modellabhängigkeit nennt Abschnitt 3 als eigenständiges Messergebnis: Wenn Variante A nur mit einem Spitzenmodell funktioniert, ist das ein Kostenrisiko und ein Argument für Variante B.

## 1. Messgrundlage

- Durchläufe Variante A: **21**, Variante B: **21** (Abschnitt 10 verlangt mindestens 20 je Variante)
- Szenarien A: {'anspruchsvoll': 7, 'einfach': 7, 'mittel': 7}
- Szenarien B: {'anspruchsvoll': 7, 'einfach': 7, 'mittel': 7}
- Szenario-Fingerabdrücke: ['9274e321fbb97442', 'c2da4f612cac58e5', 'e8a7fec0c1ec650e']


## 2. Metrikvergleich

| Metrik | Variante A | Variante B |
|---|---|---|
| Durchläufe | 21 | 21 |
| davon abgebrochen/fehlgeschlagen | 0 | 0 |
| Ressourcen gesamt | 150 | 189 |
| Sollmenge laut Szenario | 189 | 189 |
| **Mengentreue** (geliefert / gefordert) | 79.4 % | 100.0 % |
| davon Patient / Condition / Observation | 31 / 43 / 76 | 35 / 56 / 98 |
| Soll Patient / Condition / Observation | 35 / 56 / 98 | 35 / 56 / 98 |
| valide beim ERSTEN Versuch | 139 (92.7 %) | 189 (100.0 %) |
| valide NACH Korrekturschleife | 150 (100.0 %) | 189 (100.0 %) |
| endgültig invalide | 0 | 0 |
| reparierte Ressourcen | 11 | 0 |
| Ø Korrekturrunden je Ressource | 0.073 | 0 |
| Ø Korrekturrunden je reparierter Ressource | 1 | 0 |
| Runden ohne Verbesserung (Stagnation) | 0 | 0 |
| kaputte Referenzen | 0 | 0 |
| fehlende Patientenverknüpfungen | 0 | 0 |
| doppelte IDs im Bundle | 0 | 0 |
| erfundene Codes (außerhalb Katalog) | 0 | 0 |
| vom Validator beanstandete Codes (Fehler) | 7 | 0 |
| Terminologie-Warnungen (nicht wertend) | 84 | 98 |
| Antworten ohne gültiges JSON | 0 | 0 |
| davon durch max_tokens abgeschnitten (Konfigurationsartefakt) | 0 | 0 |
| fehlgeschlagene LLM-Aufrufe | 0 | 0 |
| LLM-Aufrufe gesamt | 32 | 21 |
| Eingabe-Token | 11468 | 39151 |
| Ausgabe-Token | 46022 | 19783 |
| geschätzte Kosten (EUR) | 0.2223 | 0.127 |
| geschätzte Kosten je Patient (EUR) | 0.0072 | 0.0036 |
| Laufzeit gesamt (s) | 443.62 | 447.6 |
| Laufzeit je Durchlauf (s) | 21.125 | 21.314 |


## 3. Bewertung nach Abschnitt 10

### Variante A – Gesamtampel: **gelb**

| Kriterium | Wert | Ampel | Anmerkung |
|---|---|---|---|
| Anteil valider Ressourcen (nach max. 3 Runden) | 100.0 % | **grün** | 150 von 150 |
| Kaputte Referenzen | 0 | **grün** | zusätzlich 0 fehlende Patientenverknüpfungen |
| Ø Korrekturrunden je Ressource | 0.07 | **grün** | über die 11 reparierten Ressourcen: 1.0 |
| Erfundene / beanstandete Codes | 7 (4.7 % der Ressourcen) | **gelb** | davon 0 außerhalb des Katalogs (nur Variante B), 7 vom Validator beanstandet |
| Kosten pro Patient | 0.0072 EUR | **grün** | Gesamtkosten der Messreihe: 0.2223 EUR |


### Variante B – Gesamtampel: **grün**

| Kriterium | Wert | Ampel | Anmerkung |
|---|---|---|---|
| Anteil valider Ressourcen (nach max. 3 Runden) | 100.0 % | **grün** | 189 von 189 |
| Kaputte Referenzen | 0 | **grün** | zusätzlich 0 fehlende Patientenverknüpfungen |
| Ø Korrekturrunden je Ressource | 0.00 | **grün** | über die 0 reparierten Ressourcen: 0.0 |
| Erfundene / beanstandete Codes | 0 (0.0 % der Ressourcen) | **grün** | davon 0 außerhalb des Katalogs (nur Variante B), 0 vom Validator beanstandet |
| Kosten pro Patient | 0.0036 EUR | **grün** | Gesamtkosten der Messreihe: 0.127 EUR |


Operationalisierte Schwellen für die beiden qualitativ formulierten Kriterien: „vereinzelt“ = bis 5 % der Ressourcen mit Codebeanstandung; „wenige Cent“ = unter 0,05 EUR je Patient, „budgetsprengend“ = ab 0,25 EUR je Patient.


## 4. Architekturentscheidung

Variante A ist nicht grün, Variante B ist grün: Variante B (Parameter + Vorlagen) wird die Architektur. Das ist ausdrücklich ein Erfolg des Spikes und kein Scheitern – es ist die zentrale Erkenntnis.


### Ergänzender Befund: Mengentreue

- **Variante A hat die geforderte Menge nicht geliefert:** 150 von 189 Ressourcen (79.4 %). Die Szenarien geben die Stückzahlen exakt vor (Abschnitt 6.1); wer sie unterschreitet, erzeugt zwar valide, aber unvollständige Testdaten.

Dieses Kriterium steht nicht in der Tabelle aus Abschnitt 10 und bekommt deshalb keine eigene Ampel. Für die Produktentscheidung ist es trotzdem erheblich – ein Generator, der die bestellte Menge nicht liefert, ist unabhängig von seiner Validitätsquote unbrauchbar.


## 5. Häufigste Fehlerarten (Grundlage für die Produktentwicklung)

Gezählt wird der **erste** Validierungsdurchgang – er zeigt, was die jeweilige Architektur produziert, bevor irgendetwas repariert wurde.

**Variante A**

| Anzahl | Fehlerart (normalisiert) |
|---:|---|
| 5 | `[error] Observation.status · Validation_VAL_Profile_Minimum: Observation.status: minimum required = #, but only found #` |
| 3 | `[error] Observation.value.ofType(Quantity) · Terminology_PassThrough_TX_Message: Error processing unit '…': The unit '…' is unknown'…'http://unitsofmeasure.org#IU/mL')` |
| 1 | `[error] Observation.value.ofType(Quantity) · Terminology_PassThrough_TX_Message: Error processing unit '…': The unit '…' is unknown'…'http://unitsofmeasure.org#cells/µL')` |
| 1 | `[error] Observation.value.ofType(Quantity) · Terminology_PassThrough_TX_Message: Error processing unit '…': The unit '…' is unknown'…'http://unitsofmeasure.org#mL/min/#.#m#')` |
| 1 | `[error] Condition.verificationStatus · Terminology_PassThrough_TX_Message: CodeSystem is unknown and can'…'http://terminology.hl#.org/CodeSystem/condition-verification#confirmed'` |
| 1 | `[error] Condition.verificationStatus · Terminology_TX_NoValid_1_CC: None of the codings provided are in the value set '…' (http://hl#.org/fhir/ValueSet/condition-ver-status|#.#.#` |

Nach Fehlerklasse: terminologie/code: 7, pflichtfeld/kardinalität: 5


**Variante B:** keine blockierenden Fehler im ersten Validierungsdurchgang.



## 6. Einschränkungen dieser Messung

- **Terminologie.** Der HAPI-Container hat keine LOINC-/SNOMED-Pakete geladen und meldet jede kodierte Ressource mit `Terminology_PassThrough_TX_Message` als **Warnung**, nicht als Fehler („CodeSystem is unknown and can't be validated“). Ein erfundener Code fällt in Variante A damit gar nicht auf. Das Kriterium „erfundene / beanstandete Codes“ ist für Variante A deshalb nur so aussagekräftig wie die Zeile „Terminologie-Warnungen“ klein ist; Variante B misst es über den eigenen Katalog unabhängig vom Server. Direkter Beleg für den offenen Punkt aus Abschnitt 13 (eigene Terminologie-Validierung).
- **Referenzen.** Der Code vergibt IDs neu und zieht bestehende Verweise über eine Abbildungstabelle mit, erfindet aber kein Ziel für einen Verweis ins Leere. Nur deshalb ist die Metrik „kaputte Referenzen“ überhaupt aussagekräftig.
- **Asymmetrie der Prompts.** Nur Variante B bekommt den Code-Katalog. Das ist kein Messfehler, sondern der Unterschied, den der Spike misst.
- **Kosten** sind eine Schätzung aus Token-Zahlen und einer hinterlegten Preistabelle, keine Abrechnung.


## 7. Offene Punkte (Abschnitt 13)

- Endgültige Modell- und Anbieterwahl für das Produkt
- Braucht es eine eigene Terminologie-Validierung? Siehe Abschnitt 6 dieses Berichts.
- Umfang der deutschen Lokalisierung (ICD-10-GM, deutsche Demografie)
- Unterstützung von Profilen (KBV/ISiK, US Core)
