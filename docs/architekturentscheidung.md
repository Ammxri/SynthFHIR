# ADR-001: FHIR-Erzeugung über Parameter und Vorlagen

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-08-28 |
| **Phase** | 0 (Spike abgeschlossen) |
| **Betrifft** | Grundarchitektur der Datenerzeugung für das MVP |
| **Grundlage** | Build-Spezifikation SynthFHIR Phase 0, Abschnitt 10 und 14 |
| **Messdaten** | `output/messreihe-02/` (Bericht, Metriken, Artefakte je Lauf) |

> Alle im Spike erzeugten Daten sind rein synthetisch und **nicht für die
> klinische Nutzung** bestimmt. Es wurden zu keinem Zeitpunkt echte
> Patientendaten verarbeitet.

---

## 1. Kontext

Das Produkt soll synthetische FHIR-R4-Testdaten erzeugen. Die offene
Grundsatzfrage der Phase 0 war, **wer die FHIR-Struktur baut**:

- **Variante A** — Das LLM erzeugt unmittelbar FHIR-JSON. Bei
  Validierungsfehlern gehen die Fehlermeldungen an das Modell zurück, das
  korrigieren soll (maximal drei Runden je Ressource).
- **Variante B** — Das LLM erzeugt ausschließlich ein flaches
  Parameterobjekt (Alter, Geschlecht, Diagnosecode, Messwert, Datum).
  Deterministischer Code setzt daraus über feste Vorlagen die FHIR-
  Ressourcen zusammen. Codes stammen aus einem fest hinterlegten Katalog.

Beide Varianten teilen sich dieselbe nachgelagerte Kette: deterministische
ID- und Referenzvergabe, Validierung gegen `$validate`, eigene Referenz-
Integritätsprüfung, Metrikerfassung.

---

## 2. Entscheidung

**Variante B wird die Architektur des MVP.**

Die Erzeugung der FHIR-Struktur bleibt vollständig in deterministischem
Code. Das LLM ist ausschließlich für klinisch plausible **Inhalte**
zuständig — welcher Wert, welche Diagnose, welches Datum. Struktur,
Pflichtfelder, Datentypen, Codes und Einheiten kommen aus Vorlagen und
Katalog.

Die Korrekturschleife aus Variante A entfällt im Produkt.

---

## 3. Messgrundlage

| | |
|---|---|
| Durchläufe | 42 (21 je Variante, 0 Fehlschläge) |
| Szenarien | 3, mit steigender Komplexität, identische Fingerabdrücke in beiden Varianten |
| Modell | `openai/gpt-oss-120b` über Groq (`https://api.groq.com/openai/v1`) |
| Temperatur | 0.8 (Streuung zwischen Wiederholungen erwünscht) |
| Validator | HAPI FHIR, lokal via Docker, FHIR-Version 4.0.1 |
| Maximale Korrekturrunden | 3 |
| Messzeitpunkt | 2026-08-28 |

Abschnitt 10 der Spezifikation verlangt mindestens 20 Durchläufe je
Variante; mit 21 ist das erfüllt. Die Szenario-Fingerabdrücke sind je
Szenario über beide Varianten identisch — die Ergebnisse sind vergleichbar.

---

## 4. Ergebnisse

### 4.1 Ampelbewertung nach Abschnitt 10

| Kriterium | Variante A | Variante B |
|---|---|---|
| Anteil valider Ressourcen (nach max. 3 Runden) | 100,0 % · **grün** | 100,0 % · **grün** |
| Kaputte Referenzen | 0 · **grün** | 0 · **grün** |
| Ø Korrekturrunden je Ressource | 0,07 · **grün** | 0,00 · **grün** |
| Erfundene / beanstandete Codes | 7 (4,7 %) · **gelb** | 0 · **grün** |
| Kosten pro Patient | 0,0072 € · **grün** | 0,0036 € · **grün** |
| **Gesamt** | **gelb** | **grün** |

Entscheidungsregel aus Abschnitt 10: *A gelb/rot, B grün → Variante B.*

### 4.2 Vollständige Metriken

| Metrik | Variante A | Variante B |
|---|---|---|
| Ressourcen gefordert | 189 | 189 |
| Ressourcen geliefert | 150 | 189 |
| **Mengentreue** | **79,4 %** | **100 %** |
| davon Patient / Condition / Observation | 31 / 43 / 76 | 35 / 56 / 98 |
| Soll Patient / Condition / Observation | 35 / 56 / 98 | 35 / 56 / 98 |
| Valide beim ersten Versuch | 139 (92,7 %) | 189 (100 %) |
| Valide nach Korrekturschleife | 150 (100 %) | 189 (100 %) |
| Endgültig invalide | 0 | 0 |
| Reparierte Ressourcen | 11 | 0 |
| Runden ohne Verbesserung (Stagnation) | 0 | 0 |
| Kaputte Referenzen | 0 | 0 |
| Doppelte IDs | 0 | 0 |
| Codes außerhalb des Katalogs | 0 | 0 |
| Vom Validator beanstandete Codes | 7 | 0 |
| Terminologie-Warnungen (nicht wertend) | 84 | 98 |
| Antworten ohne gültiges JSON | 0 | 0 |
| LLM-Aufrufe | 32 | 21 |
| Eingabe-Token | 11 468 | 39 151 |
| Ausgabe-Token | 46 022 | 19 783 |
| Kosten (Referenztarif) | 0,2223 € | 0,1270 € |
| Laufzeit je Durchlauf | 21,1 s | 21,3 s |

Kosten sind eine Schätzung aus Token-Zahlen zu einem Referenztarif von
1 USD / 5 USD je 1 Mio. Ein- bzw. Ausgabe-Token. Der Messlauf selbst war
kostenlos (Gratiskontingent); der Referenztarif dient nur dem Vergleich der
Varianten untereinander.

### 4.3 Häufigste Fehlerarten der Variante A

Gezählt im **ersten** Validierungsdurchgang. Variante B produzierte keine
blockierenden Fehler.

| Anzahl | Fehlerart | Fehlerklasse |
|---:|---|---|
| 5 | `Observation.status: minimum required = 1, but only found 0` | Pflichtfeld |
| 5 | Ungültige UCUM-Einheit (`IU/mL`, `cells/µL`, `mL/min/1.73m2`) | Einheit |
| 1 | Falscher CodeSystem-URL: `condition-verification` statt `condition-ver-status` | Terminologie |
| 1 | `verificationStatus` nicht im geforderten ValueSet | Terminologie |

---

## 5. Begründung

### 5.1 „100 % valide" ist bei Variante A irreführend

Die Validitätsquote ist über die **erzeugten** Ressourcen gerechnet, nicht
über die **bestellten**. Variante A hat 39 der 189 geforderten Ressourcen
nie erzeugt; was nie entsteht, kann die Korrekturschleife nicht reparieren.
Gegen die Bestellung gerechnet:

| | Variante A | Variante B |
|---|---|---|
| Von 189 geforderten am Ende valide vorhanden | **150 (79,4 %)** | **189 (100 %)** |
| davon ohne Korrekturschleife | 139 (73,5 %) | 189 (100 %) |

Der Einbruch skaliert mit der Komplexität:

| Szenario | Variante A | Variante B |
|---|---|---|
| einfach (3 Ressourcen) | 100 % | 100 % |
| mittel (6 Ressourcen) | 88,1 % | 100 % |
| anspruchsvoll (18 Ressourcen) | **73,0 %** — 17 statt 21 Patienten | 100 % |

Ein Generator, der bei „drei Patienten" zwei liefert, ist unabhängig von
seiner Validitätsquote unbrauchbar.

### 5.2 Die Korrekturschleife ist nicht das Problem

Sie hat einwandfrei gearbeitet: Alle 11 fehlerhaften Ressourcen wurden in
je genau einer Runde valide, keine einzige Stagnationsrunde. Variante A
scheitert nicht an der **Korrektheit**, sondern an der **Vollständigkeit** —
und dagegen hilft eine Korrekturschleife prinzipbedingt nicht.

### 5.3 Die Fehlerarten liegen genau dort, wo B dem Modell die Verantwortung abnimmt

| Verantwortung | Variante A | Variante B |
|---|---|---|
| Klinischer Inhalt | Modell | Modell |
| Struktur, Pflichtfelder, Datentypen, Invarianten | Modell | **Vorlage im Code** |
| Codes und Einheiten | Modell | **fester Katalog** |
| IDs und Referenzen | Code | Code |

Jede gemessene Fehlerart der Variante A fällt in eine Spalte, die Variante B
dem Modell entzogen hat:

- fehlendes `Observation.status` → die Vorlage setzt es immer
- erfundene UCUM-Einheiten → die Einheit kommt aus dem Katalog, das Modell
  liefert nur die Zahl
- falscher CodeSystem-URL → steht fest im Code

Variante B hat nicht *weniger* dieser Fehler. Sie kann sie **nicht machen**.

### 5.4 Kürzere Ausgabe ist stabiler

Die Mengentreue der Variante B ist **nicht** durch Code garantiert — der
Vorlagen-Code iteriert über das, was das Modell liefert, und protokolliert
eine Abweichung als `count_mismatch`. In 21 Läufen ist das kein einziges Mal
aufgetreten. Der Grund ist die Aufgabengröße:

| Szenario „anspruchsvoll", Ausgabe-Token | Median | Maximum |
|---|---:|---:|
| Variante A (27 vollständige FHIR-Ressourcen) | 3 815 | 5 115 |
| Variante B (kompaktes Parameterobjekt) | **1 317** | 1 933 |

Variante A muss knapp die dreifache Textmenge fehlerfrei durchhalten. Über
diese Länge verliert das Modell den Faden.

### 5.5 Kostenstruktur

Variante B verbraucht **mehr** Eingabe-Token (39 151 gegen 11 468), weil der
Code-Katalog im Prompt mitläuft, aber deutlich **weniger** Ausgabe-Token
(19 783 gegen 46 022). Da Ausgabe-Token typischerweise das Fünffache kosten,
liegt B trotzdem bei der Hälfte der Kosten je Patient.

Dieser Vorteil wird im Produkt noch größer: Der Katalog ist über alle
Anfragen identisch und damit ein idealer Kandidat für Prompt-Caching,
während die Ausgabemenge der Variante A nicht komprimierbar ist.

---

## 6. Konsequenzen

### Positiv

- Strukturelle Validität ist eine Eigenschaft des Codes und damit testbar,
  nicht eine Eigenschaft eines Modelllaufs.
- Keine Korrekturschleife: weniger Code, weniger Latenz, halb so viele
  LLM-Aufrufe, keine Stagnationsrisiken.
- Die Datenqualität hängt nicht an der Modellstärke. Das entkoppelt das
  Produkt von Preis und Verfügbarkeit eines bestimmten Anbieters.
- Ein Modellwechsel erfordert keine erneute Validierung der Struktur.

### Negativ, bewusst in Kauf genommen

- **Jeder neue Ressourcentyp braucht eine Vorlage.** Der Aufwand wächst
  linear mit dem Umfang des Datenmodells, während Variante A neue Typen
  theoretisch ohne Codeänderung erzeugen könnte.
- **Der Code-Katalog muss gepflegt werden.** Er begrenzt die inhaltliche
  Vielfalt auf das, was hinterlegt ist.
- **Weniger inhaltliche Bandbreite.** Das Modell kann nur ausfüllen, wofür
  Parameter vorgesehen sind. Ungewöhnliche klinische Konstellationen
  brauchen eine Erweiterung des Parameterschemas.

### Beizubehalten

Die deterministische ID- und Referenzvergabe bleibt unverändert Bestandteil
der Architektur, ebenso die eigenständige Referenz-Integritätsprüfung. Die
Strukturvalidierung erkennt eine ins Leere zeigende Referenz prinzipbedingt
nicht (Begründung in `docs/konzepte.md`).

---

## 7. Verworfene Alternative

**Variante A (LLM erzeugt FHIR direkt)** wird verworfen — nicht wegen
mangelnder Validität, sondern wegen mangelnder Mengentreue, doppelter
Kosten und der Kopplung der Datenqualität an die Modellstärke.

Die Entscheidung ist **neu zu prüfen**, wenn eine dieser Bedingungen
eintritt:

1. Ein Modell erreicht über alle drei Szenarien reproduzierbar ≥ 99 %
   Mengentreue bei Variante A.
2. Das Datenmodell wächst so weit, dass der Vorlagenaufwand den Nutzen
   übersteigt (Richtwert: mehr als 15–20 Ressourcentypen).
3. Ausgabe-Token werden so billig, dass der Kostenvorteil von B entfällt.

Für die Neuprüfung genügt es, die vorhandene Messkette mit einem anderen
Modell laufen zu lassen: `python -m synthfhir compare --repeats 7`.

---

## 8. Gültigkeitsgrenzen der Messung

1. **Modellabhängigkeit.** Gemessen wurde mit `openai/gpt-oss-120b`. Für
   Variante A ist das Ergebnis eine **untere Schranke** — ein Spitzenmodell
   könnte besser abschneiden. Für Variante B ist das Ergebnis belastbar, da
   die Struktur aus dem Code kommt. Die Argumente aus 5.4 und 5.5 (kürzere
   Ausgabe, halbe Kosten) sind modellunabhängig.
2. **Terminologie ist ein blinder Fleck — zuungunsten von A.** Der HAPI-
   Container hat keine LOINC-/SNOMED-Pakete geladen und meldete 84 bzw. 98
   Codes als nicht prüfbare **Warnung**. Die 7 beanstandeten Codes der
   Variante A sind ausschließlich solche, die HAPI nativ prüfen kann
   (UCUM-Einheiten, HL7-ValueSets). **Wie viele LOINC- oder SNOMED-Codes
   Variante A frei erfunden hat, ist unbekannt.** Die gemessene Zahl ist
   eine Untergrenze; das Problem ist eher größer als ausgewiesen.
3. **Kosten** sind eine Hochrechnung aus Token-Zahlen zu einem
   Referenztarif, keine Abrechnung.
4. **Prompt-Asymmetrie.** Nur Variante B erhält den Code-Katalog. Das ist
   kein Messfehler, sondern der Unterschied, den der Spike misst.

---

## 9. Offene Punkte für die MVP-Phase

Aus Abschnitt 13 der Spezifikation, ergänzt um Erkenntnisse der Messung:

- **Terminologie-Validierung als eigene Komponente.** Punkt 8.2 zeigt, dass
  der Strukturvalidator Codes nicht prüfen kann. Für Variante B löst der
  Katalog das; sobald der Katalog wächst oder Codes aus anderer Quelle
  kommen, braucht es eine eigene Prüfung.
- **Umfang der deutschen Lokalisierung** (ICD-10-GM, deutsche Demografie).
- **Unterstützung von Profilen** (KBV/ISiK, US Core) — verändert die
  Vorlagen erheblich und sollte vor deren Ausbau entschieden werden.
- **Endgültige Modell- und Anbieterwahl.** Durch die Entscheidung für
  Variante B ist sie unkritischer geworden, aber nicht gegenstandslos: Die
  klinische Plausibilität der Inhalte hängt weiterhin am Modell.
- **Prompt-Caching für den Katalog**, siehe 5.5.

---

## 10. Nachweise

| Artefakt | Ort |
|---|---|
| Vergleichsbericht | `output/messreihe-02/bericht.md` |
| Metriken je Lauf | `output/messreihe-02/variante-*/…/metriken.json` |
| Prompts und Rohantworten | `output/messreihe-02/variante-*/…/prompt.txt`, `llm-roh-*.txt` |
| Erzeugte Bundles | `output/messreihe-02/variante-*/…/bundle.json` |
| OperationOutcomes je Ressource | `output/messreihe-02/variante-*/…/validierung/` |
| Zwischenstände der Korrekturrunden | `output/messreihe-02/variante-A/…/korrektur/` |
| Konzepterklärungen | `docs/konzepte.md` |

Eine frühere Messreihe (`output/messreihe-01/`) ist **nicht** Grundlage
dieser Entscheidung: Ein zu großzügiges `max_tokens` überschritt das
Minutenkontingent des Anbieters, wodurch 17 von 42 Läufen mit HTTP 413
abbrachen. Der Fehler ist behoben und durch einen Test abgesichert; die
Reihe bleibt nur zur Nachvollziehbarkeit erhalten.

---

**Damit endet Phase 0.** Alle Abschlusskriterien aus Abschnitt 14 sind
erfüllt: beide Varianten lauffähig, mindestens 20 Messläufe je Variante,
Vergleichsbericht mit allen Metriken aus Abschnitt 6.8, diese begründete
Architekturentscheidung und die Liste der häufigsten Fehlerarten.
