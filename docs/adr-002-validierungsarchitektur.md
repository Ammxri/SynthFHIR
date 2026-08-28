# ADR-002: Zweistufige Validierung — Struktur zur Laufzeit, HAPI in der CI

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-08-28 |
| **Phase** | 1 (MVP), vor Baubeginn |
| **Betrifft** | Wo und womit die Validitätsgarantie eingelöst wird |
| **Baut auf** | ADR-001 (Variante B), PRD v2.1 Block 6 und 8 |

---

## 1. Kontext

Die Validitätsgarantie ist laut PRD das Produkt: *„Das LLM erzeugt den Inhalt,
das Tool liefert die Garantien. Die Garantien sind das Produkt."* Die North
Star Metric ist die Validitätsrate gegen FHIR R4.

Im Spike lief die Validierung über einen lokalen HAPI-FHIR-Server. Für ein
**veröffentlichtes** Web-Tool trägt das nicht: HAPI ist ein Java-Server mit
1–2 GB Speicherbedarf, während Block 6 des PRD einen kostenlosen oder sehr
günstigen Hosting-Tier vorsieht. Das Gate-Kriterium der Phase 1 ist
Veröffentlichung — die Frage blockiert also unmittelbar.

---

## 2. Entscheidung

Die Validierung wird **zweistufig**:

| Stufe | Läuft | Prüft | Werkzeug |
|---|---|---|---|
| **Laufzeit** | bei jeder Generierung | Struktur: Pflichtfelder, Kardinalitäten, Datentypen | `fhir.resources` (Pydantic-Modelle) |
| **Bauzeit** | in der CI, bei jedem Commit | dieselben Ressourcen **plus** Einheiten, Codes, Invarianten | HAPI FHIR via Docker |

Dazu kommt unverändert die eigenständige Referenz-Integritätsprüfung aus dem
Spike, die auf beiden Stufen läuft und weder von HAPI noch von den
Pydantic-Modellen abgedeckt wird (Begründung in `docs/konzepte.md`).

---

## 3. Messgrundlage

Beide Validierungen wurden auf demselben Datensatz gegeneinander gehalten:
**339 Ressourcen** aus der Messreihe der Phase 0, für die HAPIs Urteil als
`OperationOutcome` vorliegt. HAPI ist dabei die Wahrheit.

| Ergebnis | Anzahl |
|---|---:|
| Beide valide | 328 |
| Beide invalide | 5 |
| **Falscher Alarm** (Python meldet, HAPI nicht) | **0** |
| **Übersehen** (HAPI meldet, Python nicht) | **7** |
| Übereinstimmungsquote | **98,2 %** |

Aufgeschlüsselt nach Fehlerklasse:

| Fehlerklasse | von Python erkannt |
|---|---|
| Pflichtfeld / Kardinalität | **5 von 5** |
| Terminologie und Einheiten | **0 von 7** |

Die sieben übersehenen Befunde im Einzelnen:

| Anzahl | Übersehener Fehler | Wer besitzt dieses Feld in Variante B |
|---:|---|---|
| 3 | UCUM-Einheit `IU/mL` unbekannt | Katalog (`codes.py`) |
| 1 | UCUM-Einheit `cells/µL` unbekannt | Katalog (`codes.py`) |
| 1 | UCUM-Einheit `mL/min/1.73m2` fehlerhaft | Katalog (`codes.py`) |
| 1 | Falscher CodeSystem-URL bei `verificationStatus` | Vorlage (`templates.py`) |
| 1 | `verificationStatus` nicht im ValueSet | Vorlage (`templates.py`) |

---

## 4. Begründung

**Die Lücke der Laufzeitprüfung deckt sich exakt mit dem, was die Architektur
nicht erzeugen kann.** Alle sieben übersehenen Fehler liegen in Einheiten und
Codes. Genau diese Felder nimmt Variante B dem Sprachmodell ab: Einheiten und
UCUM-Codes kommen aus dem Katalog, die Statuscodes stehen fest in der Vorlage.
Das Modell liefert nur Code-Auswahl aus einer erlaubten Liste, Zahl und Datum.

Die beiden Stufen sind daher komplementär und nicht redundant:

- Die **Laufzeitprüfung** fängt ab, was variabel ist — die Struktur der aus
  Modellparametern gebauten Ressourcen. Dort war sie in der Messung
  vollständig (5 von 5) und ohne falschen Alarm (0 von 339).
- Die **CI-Prüfung** sichert ab, was fest ist — Katalog und Vorlagen. Diese
  Teile ändern sich nur durch Commits, also genau dann, wenn die CI läuft.

**Null falsche Alarme sind das zweite tragende Ergebnis.** Eine Laufzeitprüfung,
die valide Ressourcen fälschlich ablehnt, würde die Ausgabe unbrauchbar machen,
ohne dass es jemand merkt. Über 339 Ressourcen ist das nicht aufgetreten.

---

## 5. Auflage — der Katalog wird sicherheitskritisch

Die Garantie steht auf zwei Beinen. Fällt das CI-Bein weg, bricht sie
unbemerkt: Ein falscher UCUM-Code im Katalog erzeugt ab sofort invalide
Ausgaben, und die Laufzeitprüfung sagt nichts.

Daraus folgt eine **verbindliche Regel**:

> Jeder Eintrag des Codekatalogs und jede Vorlage muss durch einen CI-Test
> gedeckt sein, der aus ihm eine Ressource baut und diese gegen HAPI
> validiert. Der Test läuft über den **vollständigen** Katalog, nicht über
> eine Stichprobe.

Bei derzeit rund 25 Beobachtungs- und 25 Diagnosecodes sind das etwa 50
Ressourcen je Lauf — schnell genug für jeden Commit. Diese Testsuite ist
nicht Beiwerk, sondern der Ort, an dem die Produktzusage tatsächlich
eingelöst wird.

---

## 6. Konsequenzen

### Positiv

- Kein HAPI im Betrieb: Der MVP läuft in einem kostenlosen oder sehr
  günstigen Tier, das Gate-Kriterium Veröffentlichung ist erreichbar.
- Laufzeit im Millisekundenbereich statt HTTP-Aufruf gegen einen Java-Server.
- Keine zusätzliche Infrastruktur, kein Betriebsrisiko durch einen zweiten
  Dienst.
- Der Validierungsstatus bleibt für den Nutzer sichtbar (US-2 AC3) — er
  bezieht sich auf die Strukturprüfung, was im Produkt so zu benennen ist.

### Negativ, bewusst in Kauf genommen

- **Zwei Validatoren statt einem.** Ihre Gleichwertigkeit gilt nur, solange
  die CI-Regel aus Abschnitt 5 eingehalten wird.
- **`fhir.resources` bietet kein R4.** Version 8.3 liefert R4B (4.3.0) und
  R5; Zielversion des Projekts ist R4 (4.0.1). Für die drei Ressourcentypen
  des MVP hat die Messung an echten R4-Daten keine Abweichung gezeigt — 0
  falsche Alarme über 339 Ressourcen. Die verbleibende Differenz deckt die
  HAPI-Prüfung in der CI ab, die gegen echtes R4 4.0.1 läuft.
- **Terminologie wird zur Laufzeit gar nicht geprüft.** Das ist kein
  Rückschritt: Auch HAPI konnte es im Spike nicht, weil ihm die
  LOINC-/SNOMED-Pakete fehlten. Der Katalog ist der Ersatz, und das PRD sieht
  echte Terminologieprüfung ohnehin erst für Phase 2 vor.

---

## 7. Verworfene Alternativen

**HAPI mitdeployen (5–10 €/Monat).** Bliebe exakt bei der gemessenen
Validierung und hielte die Zusage wörtlich. Verworfen, weil es dauerhafte
Betriebskosten und einen zweiten Dienst für einen Portfolio-MVP bedeutet,
dessen Kernrisiko laut Risiko-Register ohnehin die Nichtveröffentlichung ist.
Bleibt die Rückfallebene, falls sich die CI-Regel als nicht haltbar erweist.

**Nur Validität durch Konstruktion, ohne Laufzeitprüfung.** Verworfen: Die
Messung zeigt, dass die Laufzeitprüfung 5 von 5 Strukturfehlern fängt. Diese
Fehler entstehen dort, wo Modelldaten in die Vorlage fließen — sie ganz
wegzulassen hieße, den einzigen variablen Teil ungeprüft zu lassen.

---

## 8. Nachweise

| Was | Wo |
|---|---|
| Gelabelte Vergleichsdaten (339 Ressourcen mit HAPI-Urteil) | `spike/output/messreihe-02/**/ressourcen.json`, `**/validierung/` |
| Architekturentscheidung Variante B | `docs/architekturentscheidung.md` |
| Warum Referenzintegrität eigenständig geprüft wird | `docs/konzepte.md`, Abschnitt 2 |
