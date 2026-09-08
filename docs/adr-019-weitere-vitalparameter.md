# ADR-019: Drei weitere Vitalparameter — Atemfrequenz, Temperatur, Sauerstoffsättigung

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-09-01 |
| **Phase** | 3 (Vision) |
| **Betrifft** | `domain/codes.py`, `profil.py`, `referenzkohorte.py` |
| **Baut auf** | ADR-003, ADR-014, ADR-018 |

---

## 1. Kontext

Das ISiK-Vitalparameter-Modul (`de.gematik.isik-vitalparameter` 4.0.2) ist
seit ADR-014 geladen und profiliert jeden Vitalparameter einzeln. Der
Katalog nutzte davon vier: Herzfrequenz, Blutdruck (als Panel),
Körpergewicht, Körpergröße.

Drei der klassischen Vitalparameter fehlten — **Atemfrequenz,
Körpertemperatur, Sauerstoffsättigung**. Sie sind nicht schmückend: Ein
Testdatensatz „Patient auf der Intensivstation" ohne Atemfrequenz und
Sauerstoffsättigung ist unvollständig, und das Modul, das sie prüft, war
längst da. Der Zuwachs war also sofort profilgeprüft, nicht bloß behauptet.

---

## 2. Entscheidung

**Die drei Vitalparameter werden in den Katalog aufgenommen, jeder mit dem
LOINC-Code und der Einheit aus der Primärquelle, und in
`profil.py` ihrem ISiK-Profil zugeordnet.**

| Vitalparameter | LOINC | UCUM | ISiK-Profil |
|---|---|---|---|
| Atemfrequenz | `9279-1` | `/min` | `ISiKAtemfrequenz` |
| Körpertemperatur | `8310-5` | `Cel` | `ISiKKoerpertemperatur` |
| Sauerstoffsättigung (arteriell) | `2708-6` | `%` | `ISiKSauerstoffsaettigungArteriell` |

Aufgenommen in die Referenzkohorte an einem stationären Patienten, damit
sie **gemessen** werden und nicht nur im Katalog stehen.

---

## 3. Begründung

### Woher die Codes stammen

Der Katalog ist sicherheitskritisch (die Laufzeitprüfung sieht Codes
nicht), also wird auch hier nichts geraten. Jeder Wert kommt aus der
Primärquelle, geprüft am 2026-09-01:

- **Der LOINC-Code** aus dem **primären `loinc`-Slice** des jeweiligen
  fhir.de-Vitalparameter-Profils (`observation-de-vitalsign-*` in
  de.basisprofil.r4 1.5.3), das ISiK verfeinert. Das ist eine Falle mit
  Ansage: Dieselben Profile führen einen zweiten Slice `loinc-zusatzcode`
  (bei Körpergewicht `8339-4`), und ein erster, grober Auszug hatte den
  **Zusatzcode** für den primären gehalten. Erst der Blick auf die
  `sliceName` trennte beide. Für die Sauerstoffsättigung ist der Effekt
  handfest: primär ist `2708-6`, der Zusatzcode `59408-5` — wer den
  Zusatzcode nimmt, kodiert etwas anderes.
- **Die amtliche deutsche Bezeichnung** (`display_loinc_de`) von
  tx.fhir.org, LOINC 2.82 — dieselbe Quelle und dasselbe Verfahren wie
  für die 25 bestehenden Codes. `tests/test_terminologie.py` hält sie
  gegen den Server; der Lauf über **alle** Observation-Codes ist grün.
- **Die UCUM-Einheit** ist die fachlich eindeutige des jeweiligen
  Vitalparameters und durch die Profilmessung gedeckt (siehe Nachweis).

### Warum kein SNOMED

Die Vitalparameter-Profile verlangen keinen SNOMED-Code (der Slice ist
`min=0`), anders als die Laborwerte in ADR-015. `test_domaene.py` hält
ausdrücklich fest, dass **kein** Vitalparameter einen SNOMED-Code trägt —
die drei neuen fügen sich ein.

### Warum in die Referenzkohorte

`EMER` blieb unbemerkt nicht konform, weil die feste Testkohorte es nicht
benutzte (ADR-018). Damit sich das nicht wiederholt, stehen die drei neuen
Vitalparameter an einem stationären Patienten der Referenzkohorte. Sie
werden damit bei jeder Profilmessung geprüft, nicht nur beim Bau.

---

## 3a. Nachweis (2026-09-01)

Gemessen mit dem **offiziellen HL7-Validator** (`validator_cli`, derselbe
Maßstab wie ADR-013/018) gegen tx.fhir.org, SNOMED international:

    ISiKAtemfrequenz                    1 geprüft   0 Fehler   2 Warnungen
    ISiKKoerpertemperatur               1 geprüft   0 Fehler   2 Warnungen
    ISiKSauerstoffsaettigungArteriell   1 geprüft   0 Fehler   2 Warnungen
    SUMME (ganze Kohorte)              17 geprüft   0 Fehler  33 Warnungen

    Keine ungeprüften Befunde: Die Terminologie hat entschieden.

Beleg: `docs/belege/isik-referenzvalidator.json` (17 statt zuvor 14).

**Keine neue Warnungsart.** Die 33 Warnungen sind dieselben wie in
ADR-013/014: dom-6 (fehlendes Narrative, je Ressource eine), fehlender
`performer`, das nicht auflösbare ICD-10-GM-CodeSystem 2026 und die
fehlenden deutschen SNOMED-Anzeigenamen. Jeder der drei neuen
Vitalparameter trägt genau zwei davon (dom-6 und Performer) — nichts, was
mit den Vitalparametern selbst zu tun hätte.

**Terminologie:** `test_die_deutschen_loinc_bezeichnungen_stimmen` läuft
über alle Observation-Codes gegen tx.fhir.org und ist grün — die
amtlichen Bezeichnungen der drei neuen stimmen.

---

## 4. Konsequenzen

### Positiv

- Die drei klassischen fehlenden Vitalparameter sind da und **nachweislich
  ISiK-konform** — der Zuwachs war sofort profilgeprüft, wie beim Vorschlag
  versprochen.
- Ein Intensiv- oder Notfallpatient lässt sich jetzt vollständiger
  abbilden.
- Die Referenzmessung deckt sie ab; sie können nicht still nicht-konform
  werden.

### Negativ, bewusst in Kauf genommen

- **Drei Katalogeinträge mehr**, die gepflegt werden wollen — abgefedert
  durch die Terminologie- und Profilmessung, die bei jeder Änderung
  anschlägt.
- **Bestehende Aufzeichnungen ändern sich nicht**, aber der
  Katalog-Fingerabdruck bleibt gleich (die neuen Codes sind zusätzliche
  Katalogeinträge, keine geänderten) — eine Aufzeichnung, die keinen der
  neuen Codes benutzt, spielt unverändert ab.

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| Den `loinc-zusatzcode` als primären LOINC nehmen | Kodierte etwas anderes — bei der Sauerstoffsättigung `59408-5` statt `2708-6`. Der primäre Slice ist der maßgebliche. |
| SNOMED-Doppelkodierung wie bei Laborwerten (ADR-015) | Die Vitalparameter-Profile verlangen keinen SNOMED-Code. Einen zu erfinden wäre dieselbe ungeprüfte Wahl, die ADR-015 für die 14 offenen Laborwerte ablehnt. |
| Die weiteren ISiK-Vitalparameter (GCS, EKG, Kopfumfang) gleich mit | GCS und EKG sind Sonderfälle (Score bzw. mehrkomponentig), Kopfumfang eine Nische. Drei klassische Vitalparameter sind der klare Gewinn; die übrigen bleiben *Offen*. |
| Nur in den Katalog, nicht in die Referenzkohorte | Dann bliebe die Konformität ungemessen — genau der blinde Fleck, an dem `EMER` scheiterte (ADR-018). |

---

## 6. Offen

- **Die übrigen ISiK-Vitalparameter:** GCS (Glasgow Coma Scale, ein
  Score), EKG, Kopfumfang. Jeweils eigener Aufwand, kein klarer Bedarf.
- **Ein SNOMED-Slice für Vitalparameter** wäre möglich (das Profil erlaubt
  ihn), aber optional und ungeprüft — dieselbe Zurückhaltung wie bei den
  Laborwerten.
