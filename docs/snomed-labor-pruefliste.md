# Prüfliste: SNOMED-Codes für Laborwerte

**Erzeugt von `tools/erzeuge_snomed_labor_pruefliste.py`.** Nicht von
Hand pflegen — neu erzeugen.

ISiK Labor verlangt neben LOINC eine zweite Kodierung in SNOMED
(`Observation.code.coding:snomed`, `min=1`). Der Slice ist an **kein**
ValueSet gebunden: Jeder gültige SNOMED-Code erfüllt die Struktur.
Die klinische Richtigkeit prüft also niemand ausser einem Menschen.

Von 20 Laborwerten sind **6** aus der
Spezifikation übernommen, **14** gewählt und belegt
(ADR-021) und **0** offen.

---

## Aus der Spezifikation selbst

Diese Codes stehen als `patternCoding` in den Profilen von
ISiK Labor. Sie sind nicht gewählt, sondern übernommen.

| LOINC | Messwert | SNOMED | Bezeichnung | Profil |
|---|---|---|---|---|
| `1988-5` | C-reaktives Protein | `55235003` | C-reactive protein measurement | ISiKLaboruntersuchungCRP |
| `2160-0` | Kreatinin im Serum | `70901006` | Creatinine measurement, serum | ISiKLaboruntersuchungSerumkreatinin |
| `3016-3` | TSH | `61167004` | Thyroid stimulating hormone measurement | ISiKLaboruntersuchungTSH |
| `718-7` | Hämoglobin | `416125006` | Hemoglobin measurement | ISiKLaboruntersuchungHb |
| `777-3` | Thrombozyten | `365632008` | Finding of platelet count | ISiKLaboruntersuchungThrombozyten |
| `98979-8` | geschätzte GFR | `80274001` | Glomerular filtration rate measurement | ISiKLaboruntersuchungGFR |

---

## Gewählt und am Terminologieserver belegt (ADR-021)

Für diese 14 nennt die Spezifikation keinen Code. Je Wert wurde ein
SNOMED-Messverfahren gewählt, das den Analyten im vom LOINC genannten
Material trifft, am Terminologieserver bestätigt (existiert, aktiv,
`is-a 122869004`) und vom Menschen freigegeben. Sie tragen das
allgemeine Profil ISiKLaboruntersuchung.

| LOINC | Messwert | SNOMED | Bezeichnung |
|---|---|---|---|
| `1742-6` | ALAT (GPT) | `34608000` | Alanine aminotransferase measurement |
| `1920-8` | ASAT (GOT) | `45896001` | Aspartate aminotransferase measurement |
| `1975-2` | Bilirubin gesamt | `359986008` | Bilirubin, total measurement |
| `2075-0` | Chlorid | `46511006` | Chloride measurement |
| `2085-9` | HDL-Cholesterin | `28036006` | High density lipoprotein cholesterol measurement |
| `2093-3` | Gesamtcholesterin | `77068002` | Cholesterol measurement |
| `2345-7` | Glukose im Serum | `22569008` | Glucose measurement, serum |
| `2571-8` | Triglyzeride | `14740000` | Triglycerides measurement |
| `2823-3` | Kalium | `59573005` | Potassium measurement |
| `2951-2` | Natrium | `104934005` | Sodium measurement, serum |
| `3094-0` | Harnstoff-Stickstoff | `24509005` | Urea nitrogen measurement |
| `4548-4` | HbA1c | `43396009` | Hemoglobin A1c measurement |
| `6690-2` | Leukozyten | `767002` | White blood cell count |
| `789-8` | Erythrozyten | `14089001` | Red blood cell count |

---

## Offen

Keine — alle Laborwerte des Katalogs führen einen SNOMED-Code.
Kommt ein neuer Wert ohne Code hinzu, listet dieses Werkzeug
wieder Kandidaten für ihn.

