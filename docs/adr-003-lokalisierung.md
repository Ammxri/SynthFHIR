# ADR-003: ICD-10-GM zusätzlich zu SNOMED CT, nicht anstelle

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-08-28 |
| **Phase** | 1 (MVP), vor Baubeginn |
| **Betrifft** | Umfang der deutschen Lokalisierung im MVP |
| **Baut auf** | PRD v2.1 Block 4 und US-4, ADR-001 (Katalogprinzip) |

---

## 1. Kontext

Die deutsche Lokalisierung ist laut PRD der **zweite Differenzierer** gegenüber
Synthea. US-4 verlangt: deutsch plausible Namen und Demografie, und
*„wo anwendbar werden ICD-10-GM-Codes verwendet"*.

Das PRD hatte den Umfang bewusst offen gelassen und die Entscheidung an den
Restaufwand nach Phase 0 geknüpft. Annahme 3 aus Block 10 — ICD-10-GM sei mit
vertretbarem Aufwand umsetzbar — blieb im Spike ungeprüft, weil Lokalisierung
ausdrücklich außerhalb des Spike-Scopes lag.

Der Spike-Katalog nutzt heute SNOMED CT für `Condition.code` und LOINC für
`Observation.code`. Da bei Variante B die gesamte Code-Garantie am Katalog
hängt (ADR-001), entscheidet diese Frage unmittelbar über `codes.py`.

---

## 2. Entscheidung

`Condition.code` trägt **beide Kodierungen nebeneinander** in derselben
`CodeableConcept`: SNOMED CT und ICD-10-GM.

```json
"code": {
  "coding": [
    { "system": "http://snomed.info/sct",       "code": "44054006", "display": "Diabetes mellitus type 2" },
    { "system": "http://fhir.de/CodeSystem/bfarm/icd-10-gm", "code": "E11.90", "display": "Diabetes mellitus, Typ 2, ohne Komplikationen, nicht als entgleist bezeichnet" }
  ],
  "text": "Diabetes mellitus Typ 2"
}
```

Namen, Geburtsdaten und Anzeigetexte werden deutsch. `Observation.code` bleibt
bei LOINC — LOINC ist international und in Deutschland der gebräuchliche
Standard für Laborwerte; ein deutsches Gegenstück wäre kein Gewinn.

---

## 3. Begründung

**FHIR sieht genau das vor.** Eine `CodeableConcept` ist als Liste von
`coding`-Einträgen definiert, die *dasselbe Konzept in verschiedenen
Terminologien* ausdrücken. Zwei Kodierungen sind hier kein Kompromiss, sondern
der spezifikationskonforme Normalfall — und exakt die Struktur, die deutsche
FHIR-Implementierungen in der Praxis verwenden.

**Es hält beide Zielgruppen.** Der deutsche Entwickler bekommt den ICD-10-GM-
Code, den seine Anwendung erwartet. Der internationale Betrachter — laut PRD
gehören Portfolio-Gutachter in Deutschland *und* China zur Zielgruppe — sieht
weiterhin SNOMED und damit Anschlussfähigkeit an internationale Profile.

**Der Aufwand ist begrenzt und bekannt.** Der Katalog umfasst rund 25
Diagnosen. Jede braucht einen zusätzlichen ICD-10-GM-Code und einen deutschen
Anzeigetext — eine überschaubare, einmalige Ergänzung an einer einzigen Stelle
im Code. `codes.py` wird erweitert, nicht ersetzt; die 189 in Phase 0
gemessenen validen Ressourcen bleiben als Regressionsgrundlage gültig.

**Es hält die Tür für Phase 3 offen.** Deutsche Spezialprofile (KBV, ISiK)
setzen ICD-10-GM voraus. Wer im MVP nur SNOMED führt, muss dort umbauen; wer
beides führt, ergänzt nur die Profil-Metadaten.

---

## 4. Konsequenzen

### Positiv

- US-4 AC2 ist vollständig erfüllt statt nur dem Buchstaben nach.
- Der zweite Differenzierer des Produkts wird sichtbar, ohne die
  internationale Anschlussfähigkeit aufzugeben.
- Vorarbeit für Phase 3 ist geleistet.

### Negativ, bewusst in Kauf genommen

- **Der Katalog wird doppelt pflegebedürftig.** Jede neue Diagnose braucht
  zwei Codes statt einem. Bei 25 Einträgen tragbar; bei Hunderten wäre eine
  echte Terminologieanbindung nötig — das ist ohnehin Phase 2.
- **Die fachliche Zuordnung ist nicht immer eindeutig.** SNOMED und ICD-10-GM
  sind unterschiedlich granular; ein SNOMED-Konzept kann mehreren
  ICD-Schlüsseln entsprechen. Für die 25 Katalogeinträge wird die Zuordnung
  einmal bewusst getroffen und im Code dokumentiert, statt sie zu automatisieren.
- **Lizenz- und Quellenfrage.** ICD-10-GM wird vom BfArM herausgegeben. Die
  im MVP verwendeten Codes werden als kleine, handverlesene Liste im Code
  geführt und mit Quellenangabe versehen. Eine vollständige Katalogeinbindung
  wäre gesondert zu klären und ist nicht Teil des MVP.
- **Kein Automatismus kann die Schlüssel prüfen.** Weder der Formattest noch
  HAPI erkennen einen falschen ICD-Schlüssel — siehe den Nachtrag unten.

### Auflage — und ihre Grenze

Die Regel aus ADR-002 gilt unverändert: Jeder Eintrag muss durch den CI-Test
gedeckt sein, der aus ihm eine Ressource baut und gegen HAPI validiert.

**Für ICD-10-GM leistet dieser Test allerdings weniger, als hier ursprünglich
stand.** HAPI kennt das CodeSystem nicht und meldet einen unbekannten Code
höchstens als Warnung. Der Test sichert damit auch bei Diagnosen nur
Struktur und Invarianten ab — nicht die Richtigkeit des Schlüssels. Die
ursprüngliche Formulierung, ein Tippfehler falle „sonst erst beim Nutzer
auf", war zu optimistisch: Er fällt auch mit dem Test nicht auf.

Was bleibt, ist der Abgleich mit der Primärquelle. Siehe den Nachtrag.

---

## 4a. Nachtrag: Prüfung gegen den BfArM-Katalog (2026-08-28)

Alle 25 Diagnosen wurden gegen den amtlichen Katalog des BfArM abgeglichen
(ICD-10-GM Version 2026). Ergebnis:

| | Anzahl |
|---|---:|
| Schlüssel korrekt | 19 |
| **nicht kodierbar, korrigiert** | **2** |
| zuvor leer, jetzt gefüllt | 4 |
| **Abdeckung danach** | **25 von 25** |

Die beiden Fehler:

| war | ist | Grund |
|---|---|---|
| `J45.9` | `J45.99` | In ICD-10-GM nur Kategorieüberschrift; die fünfte Stelle (Kontrollstatus und Schweregrad) ist zwingend. |
| `B18.1` | `B18.19` | Ebenso; die fünfte Stelle bezeichnet die Phase. |

Vier Einträge hatten bis dahin gar keinen Schlüssel, weil die geforderte
fünfte Stelle unklar schien. Alle vier haben eine „nicht näher bezeichnet"-
Variante: `E66.99` (Adipositas), `M19.99` (Arthrose), `M06.99` (Rheumatoide
Arthritis, amtlich „Chronische Polyarthritis"), `M81.99` (Osteoporose).

**Die Lehre daraus ist wichtiger als die zwei Korrekturen.** Beide falschen
Schlüssel hätten jede Prüfung im Projekt bestanden: Der Formattest
akzeptiert `J45.9` als wohlgeformt, und HAPI kennt das CodeSystem nicht.
Sie waren ausschließlich durch den Abgleich mit der Primärquelle zu finden.
Wer eine Diagnose ergänzt, muss diesen Abgleich also von Hand führen — die
Automatik trägt hier nicht.

---

## 5. Verworfene Alternativen

**ICD-10-GM anstelle von SNOMED CT.** Stärkster Lokalisierungsnachweis, aber
`codes.py` müsste neu gebaut werden, die internationale Lesbarkeit ginge
verloren, und die in Phase 0 gemessene Regressionsgrundlage wäre entwertet.
Der Zugewinn gegenüber der Doppelkodierung ist gering, der Verlust real.

**Nur Namen und Demografie, Codes unverändert.** Geringster Aufwand, aber die
schwächste Auslegung von US-4 AC2. Das PRD führt die Lokalisierung als
Differenzierer gegenüber Synthea — deutsche Namen allein sind keiner, denn
auch Synthea lässt sich lokalisieren. Die Codes sind der Teil, der zählt.

---

## 6. Offen

Die deutsche Demografie (Namensverteilung, Postleitzahlen, plausible
Geburtsjahrgänge) ist mit dieser Entscheidung noch nicht festgelegt. Sie
betrifft die Vorlage `build_patient`, nicht den Katalog, und wird beim Bau
entschieden.
