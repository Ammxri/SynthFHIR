# Product Requirements Document (PRD) — Version 2
## SynthFHIR — KI-gestützter, deutsch-lokalisierter Generator für synthetische FHIR-Testdaten

**Version:** 2.1 (nach Phase 0, Spike-Ergebnisse eingearbeitet) · **Datum:** 28. August 2026
**Status:** Phase 0 abgeschlossen, MVP-Umsetzung beginnt · **Primärzweck:** Portfolio-Nachweis (Medizininformatik + KI + Lokalisierung)
**Ersetzt:** PRD v2.0 · **Begleitdokumente:** `BUILD-SPEC_SynthFHIR_Phase0_Spike.md`, `docs/architekturentscheidung.md` (ADR-001)

---

## Statuslegende

| Markierung | Bedeutung |
|---|---|
| **[GESICHERT]** | Durch Recherche oder Entscheidung belegt |
| **[ENTSCHIEDEN]** | Festgelegt, nicht mehr zur Diskussion |
| **[ANNAHME]** | Plausibel, aber unvalidiert |
| **[OFFEN]** | Noch zu klären |
| **[SPIKE →]** | ~~Wird durch Phase 0 beantwortet~~ — in v2.1 vollständig aufgelöst |
| **[GEMESSEN]** | Wert aus der Messreihe der Phase 0, Beleg unter `spike/output/messreihe-02/` |
| **[GEKLÄRT]** | Frühere Annahme, durch Phase 0 beantwortet |

> **Änderungen gegenüber v2.0:** Phase 0 ist abgeschlossen. Die zentrale Architekturfrage ist entschieden (**Variante B**), alle mit `[SPIKE →]` markierten Felder sind durch Messwerte ersetzt, die Annahmen 2, 4 und 5 aus Block 10 sind bestätigt, Annahme 3 bleibt ungeprüft. Grundlage: 42 Messläufe, dokumentiert in `docs/architekturentscheidung.md`.
>
> **Änderungen gegenüber v1:** Tech-Stack entschieden (Python, HAPI FHIR via Docker, FHIR R4). Die zentrale Architekturfrage ist als Zwei-Varianten-Entscheidung ausformuliert statt als vage Annahme. MVP-Scope auf drei Ressourcentypen geschärft. Lern-/Skill-Ebene explizit verankert. Spike-abhängige Felder klar markiert.

---

## BLOCK 1 — EXECUTIVE SUMMARY

> **Fazit:** SynthFHIR erzeugt aus einer natürlichsprachlichen Beschreibung validierte, referenziell konsistente, deutsch-lokalisierte FHIR-Testdaten — die Kombination, die weder Synthea noch ein roher LLM-Chat liefert.

**Produktvision:**
SynthFHIR ist ein Web-Tool, in dem Entwickler und Medizininformatiker in natürlicher Sprache beschreiben, welche Patientenkohorte sie zum Testen brauchen, und daraus strukturell gültige, referenziell konsistente FHIR-Bundles erhalten. Es unterscheidet sich von Synthea durch Szenariospezifik, deutsche Lokalisierung und fehlendes Setup — und von rohem ChatGPT/Claude durch garantierte Validität, Referenzintegrität und echte Codes. Es verarbeitet ausschließlich synthetische Daten.

**Primäres Problem [GESICHERT]:**
Echte Gesundheitsdaten sind rechtlich und praktisch schwer zugänglich. Der freie Standard für synthetische Daten (Synthea) ist probabilistisch — man kann keine *spezifische* Kohorte anfordern —, US-zentriert und erfordert Java-Setup. Rohe LLMs erzeugen dagegen ungültige Strukturen, halluzinierte Codes und brechen bei Volumen die Referenzintegrität.

**Kernwertversprechen:**
„Beschreib in einem Satz die Testkohorte, die du brauchst — bekomme validierte, deutsch-lokalisierte FHIR-Bundles, ohne Setup, ohne echte Patientendaten."

**Strategische Einordnung [GESICHERT]:**
Portfolio-first. Umsatzpotenzial bewusst als bescheiden eingestuft (Synthea ist kostenlos). Der Wert liegt im Nachweis von FHIR-Kompetenz, KI-Implementierung und Lokalisierung — sowie darin, dass das Werkzeug ein selbst erlebtes Problem löst (fehlende Testdaten).

---

## BLOCK 2 — PROBLEM STATEMENT

> **Fazit:** Zwischen „Synthea: gültig, aber probabilistisch und US-lastig" und „roher LLM: flexibel, aber unzuverlässig" liegt eine präzise Lücke — genau die besetzt SynthFHIR.

**Belegte Schwächen des Marktstandards [GESICHERT]:**

| Schwäche von Synthea | Konsequenz |
|---|---|
| Probabilistische Generierung | Gezielte Szenarien und Edge Cases nicht anforderbar; man generiert Masse und filtert |
| US-Zentrierung | US-Demografie, US-Versicherung, US Core Profile; deutsche Strukturen nur über Community-Konfiguration |
| Java-CLI mit Build-Setup | Hohe Einstiegshürde für schnelles, gelegentliches Testen |

**Warum ein roher LLM das Problem nicht löst [GESICHERT als Argumentation]:**

| Anforderung | Roher LLM-Chat | SynthFHIR |
|---|---|---|
| Strukturelle Validität | unzuverlässig | garantiert durch Validierungsschleife |
| Referenzintegrität bei Masse | bricht | deterministisch durch Code gesetzt |
| Bulk-Export | nicht praktikabel | Kernfunktion (Phase 2) |
| Reproduzierbarkeit | nein | über Seed (Phase 2) |
| Echte Codes (LOINC/SNOMED/ICD) | plausibel, aber oft falsch | gegen erlaubte Liste geprüft |

**Kernaussage:** Das LLM erzeugt den *Inhalt*, das Tool liefert die *Garantien*. Die Garantien sind das Produkt.

---

## BLOCK 3 — USER PERSONAS & JOURNEY

> **Fazit:** Primär sind es Health-IT-Entwickler und Medizininformatiker, die schnell spezifische Testdaten brauchen — ohne Setup und ohne echte Daten anzufassen.

**Primär-Persona — Health-IT-Entwickler / Medizininformatiker:**
Baut oder testet eine FHIR-verarbeitende Anwendung. Will gezielte Testkohorten inklusive Edge Cases, direkt ladbar in einen FHIR-Server. Leidet unter Synthea-Setup und probabilistischer Streuung. Hohe technische Affinität, will Rohdaten und Export.

**Sekundär-Persona — Studierende/Lehrende der Medizininformatik:**
Lernt FHIR, braucht korrekte, nachvollziehbare Beispiele on demand. Wert liegt in der Lesbarkeit und der sichtbaren Validität.

**Tertiär — Portfolio-Betrachter (Recruiter/Fachgutachter, DE und China):**
Bewertet Kompetenz anhand des Projekts. Überzeugt durch sichtbare FHIR-Tiefe, saubere Validierungsarchitektur, Lokalisierung und ehrliche Dokumentation.

**Journey Ist → Soll:**

| Schritt | Heute (Synthea) | Mit SynthFHIR |
|---|---|---|
| 1 | Java installieren, Projekt bauen, Konfiguration anpassen | Web öffnen |
| 2 | Population probabilistisch generieren | Kohorte in natürlicher Sprache beschreiben |
| 3 | Auf gewünschtes Szenario filtern | Direkt passende Ressourcen erhalten |
| 4 | US-Daten für deutschen Kontext nacharbeiten | Deutsch lokalisiert erhalten |
| 5 | In FHIR-Server laden | Validierungsstatus sehen, exportieren, laden |

---

## BLOCK 4 — PRODUCT SCOPE & FEATURE-SET

> **Fazit:** Das MVP macht genau eines vollständig: aus natürlicher Sprache garantiert valide, deutsch-lokalisierte FHIR-Bundles für drei Ressourcentypen erzeugen und exportieren.

### Phase 0 — Validierungs-Spike (**abgeschlossen 2026-08-28**)

| Feature | Beschreibung | Nutzen | Priorität | Komplexität |
|---|---|---|---|---|
| Variante A | LLM erzeugt FHIR direkt, Fehler werden zur Korrektur zurückgegeben | Prüft, ob Direktgenerierung tragfähig ist | Must | M |
| Variante B | LLM erzeugt nur Parameter, Code baut FHIR aus Vorlagen | Prüft die robustere Alternative | Must | M |
| Validierungsanbindung | HAPI FHIR `$validate`, Auswertung des OperationOutcome | Die zentrale Garantie | Must | M |
| Referenzintegritätsprüfung | Eigener Code, unabhängig von der Strukturvalidierung | Deckt auf, was Validatoren nicht sehen | Must | S |
| Metrik- und Vergleichsbericht | Messreihe A gegen B über drei Szenarien | Grundlage der Architekturentscheidung | Must | S |

### Phase 1 — MVP

| Feature | Beschreibung | Nutzen | Priorität | Komplexität |
|---|---|---|---|---|
| Natürlichsprachliche Eingabe | Freitextbeschreibung der Kohorte (DE/EN) | Der Differenzierer gegenüber Synthea | Must | M |
| Generierung (Architektur laut Spike) | Erzeugung von Patient, Condition, Observation | Kernfunktion | Must | M |
| Validierung mit Garantie | Nur validierte Bundles werden als fertig ausgegeben | Der eigentliche Produktwert | Must | L |
| Referenzintegrität | Konsistente IDs und Verweise im Bundle | Verhindert unbrauchbare Ausgaben | Must | M |
| Deutsche Lokalisierung (Basis) | Deutsche Namen und Demografie, ICD-10-GM wo anwendbar | Zweiter Differenzierer | Must | M |
| Validierungsstatus sichtbar | Klare Kennzeichnung valide/invalide | Vertrauen und Lernwert | Should | S |
| Export als FHIR-JSON | Download des Bundles | Grundnutzen | Must | S |
| Kleine Kohorten | 1–25 Patienten | Beweist den Kern ohne Skalierungslast | Should | S |
| Lesbare Vorschau | Strukturierte Darstellung statt roher JSON-Wand | Lernwert, Portfolio-Wirkung | Should | S |

### Phase 2 — Version 1.x

| Feature | Beschreibung | Nutzen | Priorität | Komplexität |
|---|---|---|---|---|
| Weitere Ressourcentypen | Encounter, MedicationStatement u. a. | Realistischere Datensätze | Should | M |
| Bulk-Export (NDJSON) | Bulk-FHIR-Format | Praxistauglichkeit | Should | M |
| Direkter Server-Push | Laden in einen FHIR-Server | Workflow-Einbettung | Could | M |
| Seed/Reproduzierbarkeit | Gleicher Seed, gleiches Ergebnis | Wiederholbare Tests | Should | M |
| Größere Kohorten | Hunderte Patienten bei stabiler Integrität | Ernsthafte Testszenarien | Should | L |
| Profil-Konformität | Prüfung gegen wählbares Zielprofil | Höherer Nutzwert | Could | L |

### Phase 3 — Vision

| Feature | Beschreibung | Nutzen | Priorität | Komplexität |
|---|---|---|---|---|
| Deutsche Spezialprofile | KBV-/ISiK-konforme Ausgabe | Tiefe Nische, starkes Alleinstellungsmerkmal | Could | L |
| API-Zugang | Programmatische Generierung für CI/CD | Automatisierung, möglicher Umsatzhebel | Could | L |
| Weitere Standards | HL7v2 / C-CDA | Breiterer Nutzen | Could | L |
| Szenario-Bibliothek | Teilbare Kohorten-Vorlagen | Community und Bindung | Could | M |

---

## BLOCK 5 — USER STORIES & ACCEPTANCE CRITERIA

> **Fazit:** Die Kriterien prüfen vor allem, dass die Ausgabe garantiert valide und referenziell konsistent ist — das ist der Daseinsgrund gegenüber einem LLM-Chat.

**US-1 — Natürlichsprachliche Generierung**
*Als Entwickler möchte ich eine Kohorte in einem Satz beschreiben, um ohne Setup passende Testdaten zu erhalten.*
- AC1: Freitext in Deutsch oder Englisch wird angenommen.
- AC2: Ausgegeben wird mindestens ein Patient mit verknüpfter Condition und Observation.
- AC3: Genannte Kernkriterien (Alter, Diagnose) sind in der Ausgabe nachvollziehbar abgebildet.

**US-2 — Garantierte Validität (kritisch)**
*Als Entwickler möchte ich, dass jede Ausgabe valides FHIR ist, um sie ohne Nacharbeit laden zu können.*
- AC1: Jede Ressource wird gegen FHIR R4 validiert.
- AC2: Ressourcen mit Fehlern der Stufe `error` oder `fatal` werden nie als fertig ausgegeben.
- AC3: Der Validierungsstatus ist für den Nutzer sichtbar.

**US-3 — Referenzintegrität**
*Als Entwickler möchte ich konsistente Verweise, damit keine ins Leere zeigenden Referenzen entstehen.*
- AC1: Jede Condition und Observation verweist auf einen im selben Bundle vorhandenen Patienten.
- AC2: Alle IDs im Bundle sind eindeutig.
- AC3: Die Prüfung erfolgt unabhängig von der Strukturvalidierung.

**US-4 — Deutsche Lokalisierung**
*Als deutscher Entwickler möchte ich lokalisierte Daten, damit sie zu meinem Testkontext passen.*
- AC1: Namen und Demografie sind deutsch plausibel.
- AC2: Wo anwendbar werden ICD-10-GM-Codes verwendet.

**US-5 — Export**
*Als Entwickler möchte ich das Ergebnis exportieren, um es weiterzuverwenden.*
- AC1: Download als FHIR-JSON-Bundle.
- AC2: Die Datei lädt ohne Nacharbeit in einen FHIR-Server (manuell verifiziert).

**US-6 — Lesbarkeit**
*Als Studierende:r möchte ich die Ressource verständlich dargestellt sehen, um FHIR-Struktur zu lernen.*
- AC1: Strukturierte, lesbare Darstellung zusätzlich zum Roh-JSON.

---

## BLOCK 6 — TECHNISCHE ANFORDERUNGEN

> **Fazit:** Der Stack ist entschieden; die einzige verbleibende Architekturfrage ist, ob das LLM FHIR direkt erzeugt oder nur Parameter liefert — genau das beantwortet der Spike.

### Entschiedener Stack [ENTSCHIEDEN]

| Bereich | Entscheidung | Begründung |
|---|---|---|
| Validierung (Laufzeit) | `fhir.resources`, Pydantic-Modelle | ADR-002: kein Java-Server im Betrieb, Gate-Kriterium Veröffentlichung erreichbar |
| Validierung (CI) | HAPI FHIR via Docker über Katalog und Vorlagen | ADR-002: löst die Produktzusage tatsächlich ein |
| Kodierung Condition | SNOMED CT **und** ICD-10-GM nebeneinander | ADR-003: erfüllt US-4 AC2 ohne Verlust internationaler Anschlussfähigkeit |
| Sprache | Python | FHIR-/Health-Ökosystem ist Python-lastig; passt zum Medizininformatik-Kontext und zu späterer Signalverarbeitung |
| FHIR-Version | R4 | Verbreitetste Version, beste Werkzeugunterstützung |
| Validierung (Phase 0) | HAPI FHIR lokal via Docker, `$validate` | Kostenlos, liefert echtes OperationOutcome mit Fehlerorten, realitätsnah — im MVP ersetzt durch die zweistufige Lösung oben |
| LLM-Anbindung | Anbieterunabhängige Abstraktionsschicht, Modell konfigurierbar | Kostenkontrolle, kein Lock-in |
| Schlüssel | Ausschließlich Umgebungsvariablen | Sicherheit, Budgetkontrolle |
| Persistenz (MVP) | Keine Datenbank; Ergebnis wird erzeugt und exportiert | Minimale Datenschutzfläche, minimale Komplexität |
| Hosting (MVP) | Kostenloser oder sehr günstiger Tier | Budget 50–80 €/Monat |

### Architektur — die zentrale Entscheidung

**Variante A:** LLM erzeugt FHIR direkt → Validierung → bei Fehlern Rückgabe der Fehlermeldungen an das LLM (max. 3 Korrekturrunden).

**Variante B:** LLM erzeugt ausschließlich flache Parameter (Alter, Geschlecht, Diagnose, Laborwerte) → deterministischer Code baut daraus FHIR über feste Vorlagen. Codes stammen aus einer erlaubten Liste; erfundene Codes werden verworfen.

**Gewählte Architektur: Variante B** [ENTSCHIEDEN, 2026-08-28]

Gemessen an 42 Durchläufen (21 je Variante) über drei Szenarien gegen HAPI FHIR 4.0.1.
Ampel nach Abschnitt 10 der Build-Spezifikation: **A gelb, B grün**.

Ausschlaggebend war nicht die Validitätsquote — beide erreichen nach Korrektur 100 % —,
sondern die **Mengentreue**: Variante A lieferte nur 150 der 189 geforderten Ressourcen
(79,4 %), und der Einbruch skaliert mit der Komplexität (100 % / 88 % / 73 % über die drei
Szenarien). Variante B lieferte 189 von 189. Was nie erzeugt wird, kann auch keine
Korrekturschleife reparieren.

Hinzu kommen zwei modellunabhängige Argumente: Variante B braucht **21 statt 32
LLM-Aufrufe** und **die Hälfte der Kosten je Patient**. Die vollständige Begründung samt
Konsequenzen, Gültigkeitsgrenzen und Revisionsbedingungen steht in
`docs/architekturentscheidung.md` (ADR-001).

**Folge für den MVP:** Die Korrekturschleife entfällt. Struktur, Pflichtfelder,
Datentypen, Codes und Einheiten kommen aus Vorlagen und Katalog; das LLM liefert
ausschließlich klinische Inhalte.

**Designprinzip [ENTSCHIEDEN]:** Alles deterministisch Lösbare (IDs, Referenzen, Strukturgerüst) gehört in Code. Das LLM ist ausschließlich für klinisch plausible Inhalte zuständig — nie für IDs oder Referenzen.

### Komponenten

| Komponente | Aufgabe |
|---|---|
| Eingabe | Freitextbeschreibung entgegennehmen (DE/EN) |
| Generierung | Erzeugung laut gewählter Architektur |
| ID- und Referenzverwaltung | Deterministische Vergabe, konsistente Verweise, ohne LLM |
| Validierung | Prüfung gegen FHIR R4, Auswertung des OperationOutcome nach Schweregrad |
| Korrekturschleife | Nur bei Variante A; begrenzte Runden |
| Referenzintegritätsprüfung | Eigenständig, unabhängig von der Strukturvalidierung |
| Lokalisierung | Deutsche Namen/Demografie, ICD-10-GM wo anwendbar |
| Ausgabe | Lesbare Vorschau, Validierungsstatus, JSON-Export |

### Nicht-funktionale Anforderungen

| Anforderung | Zielwert | Status |
|---|---|---|
| Validitätsrate der ausgegebenen Bundles | 100 % der als fertig gekennzeichneten | [ENTSCHIEDEN als Kernziel] |
| Kaputte Referenzen | 0 | [ENTSCHIEDEN als Kernziel] |
| Generierungszeit kleine Kohorte | wenige Sekunden bis ca. 1 Minute | [ANNAHME] |
| Ø Korrekturrunden bis valide | **0** — entfällt, Variante B hat keine Korrekturschleife (Variante A: 0,07 über alle Ressourcen) | [GEMESSEN] |
| Kosten pro Patient | **0,0036 €** bei Variante B (Variante A: 0,0072 €) | [GEMESSEN, Referenztarif] |
| Datenschutzfläche | keine Verarbeitung echter Patientendaten | [GESICHERT] |

### Sicherheit und Datenschutz [GESICHERT]
- Ausschließlich synthetische Ausgaben; keine Verarbeitung echter Patientendaten
- Ausgaben sind Testdaten, nicht für klinische Nutzung — im Produkt sichtbar kennzeichnen
- Keine Schlüssel im Code oder in eingecheckten Dateien

---

## BLOCK 7 — RAHMENBEDINGUNGEN & ABHÄNGIGKEITEN

> **Fazit:** Regulatorisch unkritisch (kein MDR, keine Echtdaten); die realen Faktoren sind die Validierungsschleife und die kostenlose Konkurrenz.

**Regulatorisch [GESICHERT]:**
- Kein MDR — kein Diagnose- oder Therapiezweck, reines Entwickler- und Testwerkzeug
- Keine sensiblen Daten — DSGVO-Fläche minimal
- Kennzeichnungspflicht im Produkt: synthetisch, nicht klinisch nutzbar

**Technische Abhängigkeiten:**
- LLM-Anbieter (Kosten steuerbar über Modellwahl)
- HAPI FHIR als Validierungsinstanz
- Docker auf dem Entwicklungsrechner

**Kommerziell [GESICHERT]:**
- Synthea ist kostenlos und dominant → niedrige Zahlungsbereitschaft für die generische Funktion
- Umsatz allenfalls aus der spezifischen Nische (Szenariospezifik, deutsche Lokalisierung, API)

**Organisatorisch [GESICHERT]:**
- Solo, Student, Budget 50–80 €/Monat, Entwicklung mit KI-Unterstützung
- Nur ein Projekt zur Zeit; C+N1 ist wegen fehlender Hardware pausiert

**Risikotabelle:**

| Risiko | Ampel | Mitigation |
|---|---|---|
| LLM erzeugt zu häufig invalides FHIR (Variante A scheitert) | 🟡 | Spike vor MVP; Variante B als vollwertige Alternative bereits spezifiziert |
| Validierungsschleife wird teuer oder langsam | 🟡 | Kohortengröße begrenzen; Variante B ist deutlich sparsamer |
| Synthea-Gratis-Konkurrenz drückt Zahlungsbereitschaft | 🟡 | Portfolio-Zweck ist primär; Umsatz nur als Bonus bewertet |
| LLM-Kosten übersteigen das Budget | 🟡 | Günstiges Modell, kleine Kohorten, optional eigener API-Schlüssel des Nutzers |
| Wahrnehmung als bloßer LLM-Wrapper | 🟢 | Validität, Referenzintegrität und Lokalisierung sichtbar demonstrieren |
| Terminologie-Prüfung (existieren die Codes wirklich?) aufwendiger als gedacht | 🟡 | Im MVP feste erlaubte Codeliste; echte Terminologieprüfung erst Phase 2 |

---

## BLOCK 8 — SUCCESS METRICS & KPIs

> **Fazit:** Weil das Projekt Portfolio-first ist, misst Erfolg zuerst technische Qualität und Sichtbarkeit, nicht Umsatz.

**North Star Metric:**
**Validitätsrate der Ausgabe** — Anteil der ausgegebenen Bundles, die gegen FHIR R4 valide sind. Zielwert: 100 % der als fertig gekennzeichneten Bundles. Dies ist der Beweis, dass das Tool mehr ist als ein LLM-Wrapper.

**Ausgangswerte aus Phase 0 (Variante B, 21 Läufe, 189 Ressourcen):**

| Metrik | Gemessen | Zielwert MVP |
|---|---|---|
| Validitätsrate beim ersten Versuch | 100 % | 100 % der als fertig gekennzeichneten |
| Kaputte Referenzen | 0 | 0 |
| Codes außerhalb der erlaubten Liste | 0 | 0 |
| Mengentreue (geliefert / gefordert) | 100 % | 100 % |

Diese Werte gelten für Kohorten bis 3 Patienten und drei Ressourcentypen. Für die im
MVP vorgesehenen 1–25 Patienten sind sie **nicht** validiert — siehe Block 10.

**Qualitätsmetriken:**
- Trefferquote: Anteil der Generierungen, die die genannten Kohortenkriterien korrekt abbilden
- Referenzfehlerrate (Ziel: 0)
- Anteil erfolgreicher Server-Importe der Exporte
- Anteil ungültiger oder erfundener Codes (Ziel: 0)

**Portfolio-/Sichtbarkeitsmetriken:**
- Veröffentlicht mit erreichbarer URL und öffentlichem Repository mit belastbarer Dokumentation
- Nutzung durch Dritte (auch wenige echte Nutzer sind ein starkes Signal)
- Erwähnungen in FHIR-/Health-IT-Communities [ANNAHME: optional]

**Technische Metriken:**
- Generierungszeit pro Kohorte
- Kosten pro erzeugtem Patienten: **0,0036 €** [GEMESSEN in Phase 0, Referenztarif 1/5 USD je Mio. Token]
- Ø Korrekturrunden bis valide: **0** — entfällt bei Variante B [GEMESSEN]

---

## BLOCK 9 — EXPLIZIT NICHT IM SCOPE (MVP)

> **Fazit:** Alles, was Synthea bereits kostenlos kann oder was Skalierung betrifft, bleibt bewusst draußen.

| Ausgeschlossen | Begründung |
|---|---|
| Große Populationen (hunderte/tausende) | Skalierung und Kosten; Kern zuerst auf kleiner Kohorte beweisen |
| Weitere Ressourcentypen über die drei hinaus | Erst Kern beweisen; drei decken alle Risikoarten ab |
| Bulk-NDJSON, direkter Server-Push | Phase-2-Praxisfeatures |
| Profil-Konformität (US Core, IPS, KBV, ISiK) | Wertvoll, aber komplex; setzt validen Kern voraus |
| Echte Terminologieprüfung gegen LOINC/SNOMED-Server | Aufwendig; im MVP genügt eine feste erlaubte Codeliste |
| HL7v2 / C-CDA | FHIR zuerst |
| Nachbau vollständiger longitudinaler Lebensläufe | Genau das macht Synthea kostenlos — bewusst nicht nachbauen |
| API, CI/CD-Integration | Phase 3; potenzieller Umsatzhebel |
| Nutzerkonten, Persistenz | Für den Portfolio-MVP unnötig, erhöht nur Datenschutzfläche |
| Jeder klinische Nutzungsanspruch | Dauerhaft ausgeschlossen |

---

## BLOCK 10 — ANNAHMEN, RISIKEN & OFFENE FRAGEN

> **Fazit:** Die entscheidende technische Annahme wird durch Phase 0 direkt geprüft — danach ist die größte Unsicherheit des Projekts beseitigt.

**Kritische Annahmen, nach Relevanz:**

1. **[GEKLÄRT]** LLM-erzeugtes FHIR lässt sich zuverlässig auf valide Ausgaben bringen — **oder** Variante B liefert dies deterministisch. → **Variante B liefert es deterministisch.** Direktgenerierung erreicht zwar nach Korrektur 100 % Validität, verfehlt aber die geforderte Menge um 21 %. Architektur entschieden.
2. **[BESTÄTIGT]** Referenzintegrität bleibt bei kleinen Kohorten beherrschbar. → 0 kaputte Referenzen, 0 doppelte IDs, 0 fehlende Patientenverknüpfungen über 189 Ressourcen. **Einschränkung:** gemessen bis 3 Patienten, nicht bis 25.
3. **[WEITERHIN ANNAHME]** Deutsche Lokalisierung inklusive ICD-10-GM ist mit vertretbarem Aufwand umsetzbar. → **Im Spike nicht geprüft**, war ausdrücklich außerhalb des Scopes. Der Katalog nutzt bislang SNOMED CT und LOINC. Bleibt das größte ungeprüfte Risiko des MVP.
4. **[BESTÄTIGT]** LLM-Kosten bleiben im Budget. → 0,0036 € je Patient. Eine Kohorte von 25 Patienten kostet rund **0,09 €**; das Monatsbudget von 50–80 € ist selbst bei intensiver Nutzung nicht gefährdet.
5. **[BESTÄTIGT]** Drei Ressourcentypen sind für die Architekturentscheidung repräsentativ. → Sie haben alle vier Risikoarten sichtbar gemacht: fehlende Pflichtfelder, falsche Datentypen, ungültige Einheiten und verletzte Invarianten.

**Gemessene Fehlerarten aus Phase 0 und ihre Konsequenz für den MVP:**

Erhoben im ersten Validierungsdurchgang der Variante A. Variante B erzeugte **keine**
blockierenden Fehler — jede der folgenden Fehlerarten ist in der gewählten Architektur
strukturell ausgeschlossen, weil sie in Code oder Katalog liegt statt im Modell.

| Anzahl | Fehlerart | Warum Variante B sie nicht machen kann |
|---:|---|---|
| 5 | Fehlendes Pflichtfeld `Observation.status` | Die Vorlage setzt es immer |
| 5 | Ungültige UCUM-Einheit (`IU/mL`, `cells/µL`, `mL/min/1.73m2`) | Die Einheit kommt aus dem Katalog; das Modell liefert nur die Zahl |
| 1 | Falscher CodeSystem-URL (`condition-verification` statt `condition-ver-status`) | Steht fest im Code |
| 1 | Statuscode nicht im geforderten ValueSet | Fest gesetzt, Invarianten con-3/con-5 immer erfüllt |

**Konsequenz für den MVP-Scope:** Die Fehlerarten bestätigen die Scope-Entscheidung aus
Block 9, im MVP mit einer festen erlaubten Codeliste zu arbeiten statt mit echter
Terminologieprüfung. Zugleich zeigen sie deren Grenze — siehe die Einschränkung zur
Terminologie weiter unten.

**Grenze der Messung, die in den MVP hineinwirkt:** Der HAPI-Container hatte keine
LOINC-/SNOMED-Pakete geladen und meldete unbekannte Codes als **Warnung**, nicht als
Fehler. Die sieben beanstandeten Codes sind ausschließlich solche, die HAPI nativ prüfen
kann (UCUM-Einheiten, HL7-ValueSets). Wie viele LOINC- oder SNOMED-Codes Variante A frei
erfunden hat, ist unbekannt. Für Variante B ist das folgenlos, weil der Katalog die
Codes garantiert — es ist aber der Beleg dafür, dass die Zielmetrik „Anteil ungültiger
oder erfundener Codes = 0" **nur** über den Katalog erreichbar ist, nicht über die
Validierung.

**Risiko-Register:**

| Risiko | Typ | Wahrscheinlichkeit | Auswirkung | Ampel | Mitigation |
|---|---|---|---|---|---|
| Variante A unzuverlässig | Technik | M | H | 🟡 | Variante B vollwertig spezifiziert; Spike entscheidet |
| Referenzinkonsistenz bei Masse | Technik | M | M | 🟡 | Deterministische ID-Vergabe; kleine Kohorten im MVP |
| Kosten sprengen Budget | Ressource | M | M | 🟡 | Günstiges Modell, Kohortenbegrenzung, optional Nutzerschlüssel |
| Wahrnehmung als LLM-Wrapper | Wahrnehmung | M | M | 🟢 | Validierungsarchitektur sichtbar machen |
| Kein zahlender Markt | Markt | H | L (Portfolio-Zweck) | 🟢 | Umsatz war nie das Primärziel |
| Projekt bleibt unveröffentlicht | Umsetzung | M | H | 🔴 | Veröffentlichung ist Gate-Kriterium für Phase 1, nicht optional |
| ~~HAPI FHIR im kostenlosen Hosting-Tier nicht betreibbar~~ | Technik | H | H | 🟢 | **Gelöst durch ADR-002:** zweistufige Validierung, HAPI läuft nur noch in der CI. Neues Restrisiko siehe nächste Zeile. |
| **Katalog wird sicherheitskritisch** | Technik | M | H | 🟡 | Folge aus ADR-002: Die Laufzeitprüfung sieht Einheiten und Codes nicht. Ein falscher UCUM-Code im Katalog erzeugt unbemerkt invalide Ausgaben. Mitigation: CI-Test über den **vollständigen** Katalog gegen HAPI, verbindlich bei jedem Commit. |
| **Kohorten bis 25 Patienten ungetestet** | Technik | M | M | 🟡 | Der Spike maß bis 3 Patienten (18 Ressourcen). 25 Patienten bedeuten etwa das Achtfache an Ausgabemenge; ob ein einzelner LLM-Aufruf das trägt, ist offen. Mitigation: stückweise Erzeugung. |
| **Freitext → Parameter ist eine ungemessene Stufe** | Technik | M | M | 🟡 | Der Spike gab die Stückzahlen fest vor. Im MVP muss das Modell sie aus einem Satz ableiten. Neue Fehlerquelle, die direkt auf die Metrik „Trefferquote" wirkt. |

**Top-3 offene Fragen:**

| Frage | Klärungsmethode | Zeitrahmen | Status |
|---|---|---|---|
| ~~Architektur A oder B?~~ | Phase-0-Spike, 21 Läufe je Variante | erledigt | **Variante B** |
| ~~Welche Fehlerarten dominieren?~~ | Fehlerauswertung im Spike | erledigt | **siehe oben** |
| **Wo läuft die Validierung im veröffentlichten MVP?** | Architekturentscheidung vor Baubeginn | **blockierend** | offen |
| Umfang der deutschen Lokalisierung im MVP | Entscheidung anhand des Restaufwands | vor Baubeginn | offen |
| Tragen 25 Patienten einen einzelnen LLM-Aufruf? | Messung mit der vorhandenen Kette | früh im MVP | offen |

---

## BLOCK 11 — ROADMAP & MEILENSTEINE

> **Fazit:** Ein kurzer Spike entscheidet die Architektur, danach ein kleiner, veröffentlichter MVP — Skalierung erst danach.

| Phase | Inhalt | Zeitschätzung | Team | Gate-Kriterium |
|---|---|---|---|---|
| **Phase 0 — Spike** ✅ | Beide Varianten, Validierung, Referenzprüfung, Messreihe, Vergleichsbericht | abgeschlossen 2026-08-28 | Solo | **Erfüllt:** Architekturentscheidung mit Messdaten liegt vor (ADR-001) |
| **Phase 1 — MVP** | Eingabe, Generierung, Validierung, Referenzintegrität, DE-Lokalisierung, Vorschau, Export | 4–8 Wochen | Solo | **Veröffentlicht** (erreichbare URL + Repository + Dokumentation); Exporte laden fehlerfrei in einen FHIR-Server |
| **Phase 2 — v1.x** | Weitere Ressourcentypen, Bulk, Seed, Server-Push, größere Kohorten | nach MVP | Solo | Stabile Validität bei größeren Kohorten |
| **Phase 3 — Vision** | Deutsche Profile, API, weitere Standards, Szenario-Bibliothek | langfristig | wächst | Nachweisbare Nachfrage aus der Nische |

**Verzahnung mit dem Kompetenzaufbau [ENTSCHIEDEN]:**

| Ebene | Umgang |
|---|---|
| FHIR-Ressourcenstruktur, Validierung, OperationOutcome, Referenzlogik | **Tief verstehen** — der Portfolio-Kern; hier nicht durch KI-Generierung durchrutschen |
| Vorlagenaufbau in Variante B (Pflichtfelder, Datentypen) | **Tief verstehen** |
| Eingabe-UI, Dateiausgabe, Konfiguration, Hosting | KI-gestützt umsetzen |

**Kritischer Hinweis zur Umsetzung:** Das Gate-Kriterium für Phase 1 ist ausdrücklich **Veröffentlichung**, nicht Fertigstellung. Ein nicht veröffentlichtes Projekt hat keinen Portfolio-Wert.

---

## Anhang A — Nach dem Spike auszufüllen

Nach Abschluss von Phase 0 sind folgende Felder zu ergänzen und dieses Dokument zu v2.1 fortzuschreiben:

- [x] Gewählte Architektur (A oder B) mit Begründung → Block 6 — **Variante B**
- [x] Gemessene Validitätsrate je Variante → Block 8 — A 100 % nach Korrektur / 92,7 % beim ersten Versuch, B 100 % / 100 %
- [x] Ø Korrekturrunden bis valide → Block 6, Block 8 — entfällt bei B; A: 0,07
- [x] Kosten pro erzeugtem Patienten → Block 6, Block 8 — B 0,0036 €, A 0,0072 €
- [x] Liste der häufigsten Fehlerarten → Block 10, mit Konsequenzen für den MVP-Scope
- [x] Bestätigung oder Korrektur der Annahmen 2–5 aus Block 10 — 2, 4, 5 bestätigt; **3 bleibt ungeprüft**
- [x] **Entscheidung zum Lokalisierungsumfang im MVP → Block 4** — ICD-10-GM **zusätzlich** zu SNOMED CT in derselben CodeableConcept, deutsche Namen und Demografie; Observation bleibt bei LOINC. Begründung: `docs/adr-003-lokalisierung.md`

**Zusätzlich vor Baubeginn zu entscheiden (in Phase 0 neu aufgetaucht):**

- [x] **Wo läuft die Validierung im veröffentlichten MVP?** Zweistufig: Struktur zur
      Laufzeit über `fhir.resources`, HAPI in der CI über Katalog und Vorlagen.
      Gemessen an 339 gelabelten Ressourcen: 0 falsche Alarme, alle 5 Strukturfehler
      erkannt; die 7 übersehenen Befunde liegen ausnahmslos in Einheiten und Codes,
      also in dem Teil, den Variante B dem Modell entzieht. Begründung und die daraus
      folgende CI-Auflage: `docs/adr-002-validierungsarchitektur.md`
- [ ] **Wie werden Kohorten bis 25 Patienten erzeugt?** In einem Aufruf oder stückweise.
      Gemessen wurde bis 3 Patienten.

---

## Anhang B — Quellen- und Statusübersicht

**[GESICHERT]** beruht auf der Recherche vom Mai 2026: Synthea-Dominanz und dessen Eigenschaften (probabilistisch, US-zentriert, Java-CLI), die dokumentierte Szenarioschwäche, die Grenzen roher LLM-Generierung, die regulatorische Einordnung (kein MDR, keine Echtdaten, kein DiGA).

**[ENTSCHIEDEN]** umfasst die in der Build-Spezifikation festgelegten technischen Entscheidungen sowie das Designprinzip zur Trennung von deterministischem Code und LLM-Zuständigkeit.

**[GEMESSEN]** ist neu in v2.1 und bezeichnet Werte aus der Messreihe der Phase 0:
42 Durchläufe, 21 je Variante, drei Szenarien, Modell `openai/gpt-oss-120b`, Validator
HAPI FHIR 4.0.1, durchgeführt am 2026-08-28. Rohdaten und Bericht liegen versioniert
unter `spike/output/messreihe-02/`, die Herleitung in `docs/architekturentscheidung.md`.
Kostenangaben sind Hochrechnungen aus Token-Zahlen zu einem Referenztarif von
1 USD / 5 USD je 1 Mio. Ein- bzw. Ausgabe-Token, keine Abrechnung.

**Disclaimer:** Regulatorische Aussagen sind keine Rechtsberatung. Markt- und Umsatzeinschätzungen sind Schätzungen und ersetzen keine Primärvalidierung. Ausgaben des Werkzeugs sind synthetisch und nicht für klinische Nutzung bestimmt. Das Projekt ist Portfolio-first eingestuft; ein tragfähiges Umsatzmodell ist ausdrücklich nicht nachgewiesen.
