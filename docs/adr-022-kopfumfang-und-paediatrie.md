# ADR-022: Kopfumfang als Vitalparameter — und der erste pädiatrische Fall

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-09-08 |
| **Phase** | 3 (Vision) |
| **Betrifft** | `domain/codes.py`, `profil.py`, `referenzkohorte.py`, `szenarien.py` |
| **Baut auf** | ADR-014, ADR-018, ADR-019, ADR-020 |

---

## 1. Kontext

ADR-019 hat drei klassische Vitalparameter ergänzt und drei Fälle
ausdrücklich als **Sonderfälle** offen gelassen: GCS, EKG und Kopfumfang.

Beim Nachsehen ist der Kopfumfang **kein** Sonderfall. ISiK Stufe 5
profiliert ihn (`ISiKKopfumfang`), und er ist eine gewöhnliche
quantitative Observation wie die anderen Vitalparameter: LOINC `9843-4`
ist im fhir.de-Basisprofil `observation-de-vitalsign-kopfumfang` fest
(`min=1`), der SNOMED-Slice ist optional. Er fügt sich damit genau in den
Weg ein, den ADR-019 gebaut hat.

Die echten Sonderfälle bleiben GCS (ein **Summenscore** aus drei
Komponenten) und EKG (kein Messwert, sondern **Media/Dokument**) — beide
mit eigenem Datenmodell.

Ein Kopfumfang wird fast nur in der **Pädiatrie** gemessen. Die
Referenzkohorte bestand bisher nur aus Erwachsenen — ein Kopfumfang an
einem von ihnen wäre klinisch schief.

---

## 2. Entscheidung

**Kopfumfang (`9843-4`) wird als Vitalparameter-Profil aufgenommen, und
die Kohorte bekommt ihren ersten pädiatrischen Fall, damit er gemessen
wird — nicht nur katalogisiert.**

1. Neuer `ObservationCode` `9843-4` (Kopfumfang, cm, Bereich 30–60 cm),
   `vital_sign=True`, mit der amtlichen deutschen Bezeichnung von
   tx.fhir.org.
2. `VITALPROFILE` in `profil.py` ordnet `9843-4` → `ISiKKopfumfang` zu —
   wie die übrigen Vitalparameter je LOINC einzeln.
3. Die Referenzkohorte bekommt einen **Säugling** (U-Untersuchung, ein
   ambulanter Kontakt, Kopfumfang 43 cm). Er ist der einzige pädiatrische
   Fall und der einzige Träger des Kopfumfangs im eingecheckten Beleg.
4. Ein neues Szenario **`vorsorge-saeugling`** führt den Kopfumfang über
   zwei Früherkennungstermine (U4/U5) in der Bibliothek vor.

---

## 3. Begründung

### Warum ein pädiatrischer Fall und kein Kopfumfang am Erwachsenen

Der Kopfumfang gehört in die U-Untersuchungen des Säuglings. Ihn an einem
der erwachsenen Kohortenpatienten zu messen, wäre klinisch unstimmig — und
die Kohorte lebt von Stimmigkeit (jeder Fall ist plausibel). Der Säugling
ist der richtige Träger und bringt zugleich die erste **pädiatrische
Abdeckung** ins Projekt.

### Warum überhaupt in die Kohorte

Genau der blinde Fleck aus ADR-018/019: Ein Profil, das im Katalog steht,
aber von keiner gemessenen Ressource getroffen wird, sieht konform aus,
ohne es gemessen zu haben. `ISiKKoerpergewicht`/`-groesse` standen so lange
ungemessen im Katalog; ADR-019 hat sie in die Kohorte geholt. Der
Kopfumfang folgt demselben Weg — sofort mitgemessen, nicht später.

### Warum nur LOINC

Der SNOMED-Slice von `ISiKKopfumfang` ist `min=0`. Wie die übrigen
Vitalparameter trägt der Kopfumfang deshalb **nur LOINC** — anders als die
Laborwerte (ADR-021), deren Profil bzw. Spezifikation die zweite Kodierung
nahelegt.

### Warum GCS und EKG nicht

Sie sind echte Sonderfälle mit eigenem Datenmodell (Komponentenscore bzw.
Media) und gehören eigen entschieden, nicht in diesen additiven Schritt
gezogen.

---

## 3a. Nachweis (2026-09-08)

- **Referenzvalidator** (offizieller HL7-Validator gegen
  `de.gematik.isik#5.1.3`): Der Kopfumfang des Säuglings validiert gegen
  `ISiKKopfumfang`; Kohorte gesamt **0 Fehler**, nichts ungeprüft
  (`docs/belege/isik-referenzvalidator.json`).
- **Bibliothek:** `vorsorge-saeugling` ergibt `fertig` und zeigt
  `ISiKKopfumfang`; die Testzusage „jedes Vitalparameter-Profil wird von
  einem Szenario gezeigt" ist wieder erfüllt.
- **Testreihe grün.**

---

## 4. Konsequenzen

### Positiv

- **Acht Vitalparameter-Profile** im Katalog, alle profiliert und
  gemessen. Der Kopfumfang ist kein offener Sonderfall mehr.
- **Erste pädiatrische Abdeckung** — ein Säugling in Kohorte und
  Bibliothek.
- Der Katalogbereich 30–60 cm deckt Neugeborene bis Erwachsene ab.

### Negativ, bewusst in Kauf genommen

- **Ein fünfter Kohortenpatient** und ein siebtes Szenario, die mitgepflegt
  werden. Die Zählungen (`anzahl_patienten`, `geprueft == 32`) ziehen mit.
- **Nur ein pädiatrischer Messwert.** Wachstumsperzentilen, Säuglings-
  spezifische Referenzbereiche (Gewicht/Länge) sind nicht abgebildet — der
  Kopfumfang steht für sich.

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| Kopfumfang an einem erwachsenen Kohortenpatienten | Klinisch schief; die Kohorte lebt von plausiblen Fällen. |
| Kopfumfang nur in den Katalog, nicht in die Kohorte | Der blinde Fleck aus ADR-018/019: im Katalog, aber nie gemessen. |
| GCS und EKG gleich mitnehmen | Echte Sonderfälle mit eigenem Datenmodell (Score/Media); gehören eigen entschieden. |
| SNOMED-Doppelkodierung wie bei den Laborwerten | Der Slice ist `min=0`; die Vitalparameter sind durchweg LOINC-only. |

---

## 6. Offen

- **GCS** (Glasgow Coma Score) — Summenscore aus drei Komponenten-
  Observations. Eigenes Datenmodell.
- **EKG** — Media/Dokument statt einfachem Messwert.
- Säuglings-/Kinder-spezifische Referenzbereiche und weitere pädiatrische
  Messwerte, falls das Projekt die Pädiatrie ausbauen will.
