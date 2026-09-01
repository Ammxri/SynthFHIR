# ADR-009: ISiK-Basismodul erfüllen — und was daran nicht additiv war

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-08-30 |
| **Phase** | 3 (Vision), PRD-Punkt „Deutsche Spezialprofile (KBV/ISiK)" |
| **Betrifft** | Vorlagen, Katalog, und erstmals die Erzeugung selbst |
| **Baut auf** | [Sondierung ISiK](sondierung-isik.md), ADR-001, ADR-002, ADR-007 |

---

## 1. Kontext

Die [Sondierung](sondierung-isik.md) hatte den Abstand zum ISiK-Basismodul
gemessen: **25 Fehler** über eine Referenzkohorte von zehn profilierten
Ressourcen. Diese Entscheidung schließt sie.

Die Sondierung hatte zugleich einen Irrtum von mir korrigiert. Meine erste
Einschätzung lautete, die Lücke bestehe aus fünf additiven Feldern. Das war
zu optimistisch: `isik-con1` verlangt, dass eine kodierte Diagnose nennt,
in welchem Kontakt sie gestellt wurde — und das ist eine Aussage über die
**Erzeugung**, nicht über eine Vorlage.

---

## 2. Entscheidung

**Die erzeugten Ressourcen erfüllen das ISiK-Basismodul.** Nicht in einem
Profilmodus, sondern immer.

Fünf Ergänzungen an den Vorlagen:

1. `Patient.identifier.type` = `MR` aus `v2-0203`
2. `Encounter.identifier` mit `type` = `VN` aus `v2-0203`
3. `Encounter.type` mit der Kontaktebene
4. `Condition.recordedDate`
5. `version` in der ICD-10-GM-Kodierung

Und eine Zusage über die Erzeugung:

6. **Hat ein Patient eine kodierte Diagnose, bekommt er einen Kontakt** —
   auch wenn das Modell keinen geliefert hat.

---

## 3. Begründung

### Warum immer und nicht in einem Modus

Ein Profilmodus wäre die vorsichtige Form gewesen: Die heutige Ausgabe
bliebe unangetastet, die Felder kämen nur auf Wunsch dazu. Dagegen sprach
zweierlei.

Erstens **schadet keine der Ergänzungen außerhalb von ISiK.** Eine
Patientennummer mit Typkodierung, eine Fallnummer, ein Aufzeichnungsdatum
und eine ICD-Jahresfassung sind schlicht bessere FHIR-Daten. Die
Jahresfassung ist sogar unabhängig von ISiK richtig: ICD-10-GM ändert sich
jährlich, und ein Schlüssel ohne Jahr ist nur ungefähr bestimmt.

Zweitens kostet ein zweiter Ausgabepfad in einem Solo-Projekt dauerhaft
Pflege — und er hätte die Zusage aufgeteilt in „konform, wenn man daran
denkt".

### Der Punkt, der nicht additiv war

`isik-con1` lautet wörtlich:

> Falls eine kodierte Diagnose vorliegt muss angegeben werden durch welchen
> Kontakt diese Dokumentation erfolgte.

Das Modell liefert Begegnungen aber nur, wenn danach gefragt wurde — im
Parameterobjekt sind sie optional. Eine Diagnose ohne Kontakt ist damit
kein unvollständiger Datensatz, sondern ein **unzulässiger**.

Deshalb stellt der Code den Kontakt her, so wie er auch Pflichtfelder,
Einheiten und Statuswerte herstellt. Das ist dieselbe Arbeitsteilung, die
ADR-001 entschieden hat: Das Modell liefert Inhalt, der Code stellt die
Struktur her.

**Nur wo ISiK ihn verlangt.** Ein Patient mit ausschließlich Messwerten
bekommt keinen Kontakt — `isik-con1` gilt für kodierte Diagnosen. Ressourcen
zu erfinden, die niemand fordert, wäre das Gegenteil dessen, was ADR-001
will.

Das Datum des ergänzten Kontakts ist der Beginn der ersten Diagnose. Ein
erfundenes Datum wäre schlechter als ein bekanntes.

### Ein Code, den ich falsch hergeleitet hatte

`Encounter.type` braucht eine Kontaktebene. Das CodeSystem der
Basisprofile kennt drei: `einrichtungskontakt`, `abteilungskontakt`,
`versorgungsstellenkontakt`. Ich wählte `einrichtungskontakt` — aus der
Bedeutung heraus, denn unsere Begegnung bildet den Kontakt mit der
Einrichtung als Ganzes ab. Das ValueSet erlaubt alle drei.

Der Validator wies es ab. Der Slice `Encounter.type:Kontaktebene` trägt ein
`patternCodeableConcept` mit genau `abteilungskontakt`, und der
Diskriminator vergleicht auf dieses Muster. **Das Profil entscheidet nicht
über die Bedeutung, sondern über ein Muster.**

Die Lehre ist dieselbe wie an mehreren Stellen dieses Projekts: messen,
nicht herleiten.

### Warum die ICD-Jahresfassung an den Katalog gebunden ist

`ICD10GM_VERSION = "2026"` steht neben den Codes und nicht irgendwo sonst,
weil der Wert eine Aussage über die **Prüfung** ist: Am 2026-08-28 wurden
alle 25 Schlüssel gegen den amtlichen Katalog der Version 2026 abgeglichen.
Wer die Zahl hochsetzt, ohne die Schlüssel neu zu prüfen, behauptet eine
Prüfung, die nicht stattgefunden hat.

---

## 3a. Nachweis (2026-08-30)

Gegen `de.gematik.isik-basismodul` 4.0.3, HAPI FHIR 4.0.1, **ohne**
Terminologieserver, gemessen mit `synthfhir-profil` über die feste
Referenzkohorte:

| Typ | geprüft | Fehler | ungeprüft | Warnungen |
|---|---|---|---|---|
| Patient | 3 | **0** | 0 | 3 |
| Encounter | 4 | **0** | 0 | 8 |
| Condition | 4 | **0** | 8 | 8 |
| **Summe** | **11** | **0** | **8** | **19** |

Vorher: 25 Fehler. Die Referenzkohorte ist um einen Encounter gewachsen —
den, den der Code für den Patienten ohne Begegnung ergänzt.

> **Nachtrag vom 2026-09-01.** Die Spalte „Warnungen" war als „alles, was
> nicht Fehler und nicht ungeprüft ist" definiert und enthielt damit auch
> Befunde vom Schweregrad `information`. Von den 19 waren **4** solche
> Hinweise — die Slice-Hinweise zu `Condition.onset`. Die Messung ist
> unverändert, die Zählung berichtigt:
>
> | Typ | geprüft | Fehler | ungeprüft | Warnungen | Hinweise |
> |---|---|---|---|---|---|
> | Patient | 3 | **0** | 0 | 3 | 0 |
> | Encounter | 4 | **0** | 0 | 8 | 0 |
> | Condition | 4 | **0** | 8 | 4 | 4 |
> | **Summe** | **11** | **0** | **8** | **15** | **4** |

Zusätzlich: **17 von 17** Ressourcen weiterhin gültig gegen normales
FHIR R4 ohne Profile. Die Ergänzungen brechen also nichts.

### Was „0 Fehler" nicht heißt

**Nicht „ISiK-konform".** Acht Befunde bleiben ungeprüft: Das Profil bindet
`Condition.code` an ein SNOMED-ValueSet mit `is-a`-Filtern, und ohne
Terminologieserver lässt sich die Zugehörigkeit weder bestätigen noch
widerlegen. Der Validator sagt das selbst.

**Und nicht „der Messcode ist über jeden Zweifel erhaben".** *(Nachtrag vom
2026-09-01.)* „0 Fehler" heißt genauer: `bewerte()` hat aus dem, was
`pruefe_gegen_profile` als Befunde erkannt hat, keinen der Fehlerspalte
zugeordnet. Das ist eine Aussage über die Daten **und** über den Messcode.

Am 2026-09-01 wurden drei Wege gefunden, auf denen dieser Code zu niedrig
zählen konnte: ein Platzhalter, der eine einzige unbenannte
Auflösungsklage genügen liess, um jede Bindungsverletzung des Laufs zu
entschuldigen; eine Namenserkennung, die statt des ValueSet-Namens das
Wort `cannot` fing und deshalb nie zutraf; und eine Antwort ohne
`OperationOutcome`, die als „geprüft, fehlerfrei, konform" durchging, ohne
dass der HTTP-Status je angesehen wurde. Die Zahl oben war davon nicht
betroffen — nachgemessen, nicht angenommen —, aber sie hing daran.
Einzelheiten im Nachtrag von [docs/sondierung-isik.md](sondierung-isik.md).

**Und nicht „der Messaufbau würde einen Verstoß noch bemerken".** Seit
dieser Entscheidung ergänzt der Bauweg den Kontakt selbst; die
Referenzkohorte enthält damit keinen Fall mehr, an dem `isik-con1` greifen
könnte. Dass der Validator den Verstoß findet, belegt seit dem 2026-09-01
eine eigene Negativkontrolle — nicht mehr die Kohorte.

Die belastbare Aussage lautet daher:

> Gegen `de.gematik.isik-basismodul 4.0.3`, HAPI FHIR 4.0.1, ohne
> Terminologieserver, Stand 2026-08-30: **0 Fehler und 8 ungeprüfte
> Befunde** über 11 profilierte Ressourcen. Observation und
> MedicationStatement sind im Basismodul nicht profiliert.

---

## 4. Konsequenzen

### Positiv

- Die deutsche Lokalisierung — laut PRD der zweite Differenzierer — ist
  erstmals gegen einen deutschen Standard gemessen und nicht nur behauptet.
- Alle Ergänzungen sind auch außerhalb von ISiK bessere Daten.
- Der Messbericht bleibt und schützt das Ergebnis als Regression.

### Negativ, bewusst in Kauf genommen

- **Jedes Bundle ändert sich.** Bestehende Aufzeichnungen melden bei der
  Wiedergabe `ABWEICHUNG` — der Selbsttest aus ADR-006 bei der Arbeit.
- **Jede Kohorte enthält jetzt Encounter.** Wer nur Patienten und Diagnosen
  wollte, bekommt mehr Ressourcen als zuvor. Das ist eine sichtbare
  Änderung am Produkt.
- **Kein `meta.profile`.** Die Ressourcen erfüllen das Profil, behaupten es
  aber nicht. Solange acht Befunde ungeprüft sind, wäre eine
  Konformitätserklärung in den Daten größer als der Nachweis — und sie
  legte zugleich eine ISiK-Stufe fest, weil die kanonischen URLs sich
  zwischen den Stufen unterscheiden.
- **Nur das Basismodul, nur drei Typen.** Observation und
  MedicationStatement brauchen eigene Module.
- **Die Messung hängt an einem zweiten Server**, der die ISiK-Pakete lädt.
  In den Tests bleibt sie ein Übersprung, keine Auflage.

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| Profilmodus `--profil isik` | Ein zweiter Ausgabepfad kostet dauerhaft Pflege, und keine der Ergänzungen schadet außerhalb von ISiK. |
| `einrichtungskontakt` als Kontaktebene | Aus der Bedeutung hergeleitet und vom Validator abgewiesen: Der Slice verlangt per Muster `abteilungskontakt`. |
| Für **jeden** Patienten einen Kontakt erzeugen | `isik-con1` gilt für kodierte Diagnosen. Ressourcen zu erfinden, die niemand fordert, widerspricht ADR-001. |
| Je Diagnose einen eigenen Kontakt | Ein Kontakt je Patient genügt der Vorgabe und bleibt plausibel. |
| `meta.profile` setzen | Eine Behauptung in den Daten, die acht ungeprüfte Befunde nicht decken. |
| Ein erfundenes Kontaktdatum | Der Beginn der ersten Diagnose ist bekannt und plausibel. |

---

## 6. Offen

- Ein Terminologieserver, der die SNOMED-Bindung entscheidbar macht. Erst
  damit wird aus „0 Fehler" ein Konformitätsnachweis.
- Die ISiK-Module für Vitalparameter und Medikation, damit auch Observation
  und MedicationStatement profiliert sind.
- `meta.profile`, sobald beides steht — und dann mit einer bewussten
  Entscheidung über die ISiK-Stufe.
