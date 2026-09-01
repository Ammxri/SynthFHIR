# Prüfliste: SNOMED-Codes für Laborwerte

**Erzeugt von `tools/erzeuge_snomed_labor_pruefliste.py`.** Nicht von
Hand pflegen — neu erzeugen.

ISiK Labor verlangt neben LOINC eine zweite Kodierung in SNOMED
(`Observation.code.coding:snomed`, `min=1`). Der Slice ist an **kein**
ValueSet gebunden: Jeder gültige SNOMED-Code erfüllt die Struktur.
Die klinische Richtigkeit prüft also niemand ausser einem Menschen.

Von 20 Laborwerten sind **6** versorgt und
**14** offen.

---

## Versorgt: aus der Spezifikation selbst

Diese Codes stehen als `patternCoding` in den Profilen von
ISiK Labor. Sie sind nicht gewählt, sondern übernommen.

| LOINC | Messwert | SNOMED | Bezeichnung | Profil |
|---|---|---|---|---|
| `1988-5` | C-reaktives Protein | `55235003` | C-reactive protein measurement | ISiKLaboruntersuchungCRP |
| `2160-0` | Kreatinin im Serum | `70901006` | Creatinine measurement, serum | ISiKLaboruntersuchungSerumkreatinin |
| `3016-3` | TSH | `61167004` | Thyroid stimulating hormone measurement | ISiKLaboruntersuchungTSH |
| `33914-3` | geschätzte GFR | `80274001` | Glomerular filtration rate measurement | ISiKLaboruntersuchungGFR |
| `718-7` | Hämoglobin | `416125006` | Hemoglobin measurement | ISiKLaboruntersuchungHb |
| `777-3` | Thrombozyten | `365632008` | Finding of platelet count | ISiKLaboruntersuchungThrombozyten |

---

## Offen: Kandidaten aus SNOMED, noch nicht gewählt

Die Kandidaten stammen aus einer Expansion über `is-a 122869004`
(Measurement procedure) mit Textfilter, gegen tx.fhir.org. Damit ist
belegt: Jeder existiert und ist ein Messverfahren.

**Was damit nicht belegt ist:** ob er den richtigen Analyten im
richtigen Material meint. 'Glucose measurement, serum' und
'Glucose measurement, urine' sind beide gueltige Messverfahren,
und nur eines ist gemeint. Das entscheidet ein Mensch.

Zum Eintragen: `snomed=` und `snomed_display=` beim jeweiligen
`ObservationCode` in `src/synthfhir/domain/codes.py`.

### `1742-6` — ALAT (GPT)

LOINC: Alanin-Aminotransferase [Enzymaktivität/Volumen] in Serum oder Plasma

| SNOMED | Bezeichnung |
|---|---|
| `34608000` | Alanine aminotransferase measurement |
| `104481004` | ALT measurement, method with pyridoxal-5'-phosphate |
| `104482006` | ALT measurement, method without pyridoxal-5'-phosphate |
| `250637003` | ALT - blood measurement |
| `390961000` | Plasma alanine aminotransferase level |

### `1920-8` — ASAT (GOT)

LOINC: Aspartat-Aminotransferase [Enzymaktivität/Volumen] in Serum oder Plasma

| SNOMED | Bezeichnung |
|---|---|
| `45896001` | Aspartate aminotransferase measurement |
| `250641004` | AST serum measurement |

### `1975-2` — Bilirubin gesamt

LOINC: Bilirubin.gesamt [Masse/Volumen] in Serum oder Plasma

| SNOMED | Bezeichnung |
|---|---|
| `271051006` | Serum conjugated/total bilirubin ratio measurement |
| `313840000` | Serum total bilirubin measurement |
| `313951004` | Plasma total bilirubin measurement |
| `359986008` | Bilirubin, total measurement |
| `417572006` | Total bilirubin, neonatal measurement |

### `2075-0` — Chlorid

LOINC: Chlorid [Mol/Volumen] in Serum oder Plasma

| SNOMED | Bezeichnung |
|---|---|
| `46511006` | Chloride measurement |
| `14663000` | Chloride measurement, urine |
| `86964003` | Cystic fibrosis sweat test |
| `104589004` | Chloride measurement, blood |
| `104590008` | Chloride measurement, body fluid |

### `2085-9` — HDL-Cholesterin

LOINC: Cholesterol in HDL [Masse/Volumen] in Serum oder Plasma

| SNOMED | Bezeichnung |
|---|---|
| `17888004` | High density lipoprotein measurement |
| `28036006` | High density lipoprotein cholesterol measurement |
| `104583003` | HDL/total cholesterol ratio measurement |
| `121791001` | High density lipoprotein 2 measurement |
| `121792008` | High density lipoprotein 3 measurement |

### `2093-3` — Gesamtcholesterin

LOINC: Cholesterol [Masse/Volumen] in Serum oder Plasma

| SNOMED | Bezeichnung |
|---|---|
| `77068002` | Cholesterol measurement |
| `13067005` | Cholesteryl esters measurement |
| `28036006` | High density lipoprotein cholesterol measurement |
| `104583003` | HDL/total cholesterol ratio measurement |
| `104584009` | IDL cholesterol measurement |

### `2345-7` — Glukose im Serum

LOINC: Glucose [Masse/Volumen] in Serum oder Plasma

| SNOMED | Bezeichnung |
|---|---|
| `22569008` | Glucose measurement, serum |
| `167086002` | Serum random glucose measurement |
| `167087006` | Serum fasting glucose measurement |
| `167088001` | Serum 2-hr post-prandial glucose measurement |
| `313629005` | 30 minute serum glucose measurement |

### `2571-8` — Triglyzeride

LOINC: Triglycerid [Masse/Volumen] in Serum oder Plasma

| SNOMED | Bezeichnung |
|---|---|
| `14740000` | Triglycerides measurement |
| `104586006` | Cholesterol/triglyceride ratio measurement |
| `104784006` | Lipids, triglycerides measurement |
| `104990004` | Triglyceride and ester in HDL measurement |
| `104991000` | Triglyceride and ester in IDL measurement |

### `2823-3` — Kalium

LOINC: Kalium [Mol/Volumen] in Serum oder Plasma

| SNOMED | Bezeichnung |
|---|---|
| `59573005` | Potassium measurement |
| `49833001` | Potassium measurement, urine |
| `85056003` | Chlorazepate dipotassium measurement |
| `241417005` | Total exchangeable potassium measurement |
| `250734001` | Potassium/sodium ratio measurement |

### `2951-2` — Natrium

LOINC: Natrium [Mol/Volumen] in Serum oder Plasma

| SNOMED | Bezeichnung |
|---|---|
| `25197003` | Sodium measurement |
| `104934005` | Sodium measurement, serum |
| `104935006` | Sodium measurement, urine |
| `241416001` | Total exchangeable sodium measurement |
| `250607007` | Sodium valproate blood measurement |

### `3094-0` — Harnstoff-Stickstoff

LOINC: Harnstoff-Stickstoff [Masse/Volumen] in Serum oder Plasma

| SNOMED | Bezeichnung |
|---|---|
| `18207002` | BUN/Creatinine ratio |
| `24509005` | Urea nitrogen measurement |
| `105012004` | Urea nitrogen measurement, semi-quantitative |
| `105013009` | Urea nitrogen measurement, urine |
| `105014003` | Urea nitrogen renal clearance measurement |

### `4548-4` — HbA1c

LOINC: Hämoglobin A1c/Hämoglobin.gesamt in Blut

| SNOMED | Bezeichnung |
|---|---|
| `43396009` | Hemoglobin A1c measurement |
| `313835008` | HbA1c measurement (DCCT aligned) |
| `117346004` | Glucose measurement estimated from glycated hemoglobin |

### `6690-2` — Leukozyten

LOINC: Leukozyten [#/Volumen] in Blut mittels automatisierter Zählung

| SNOMED | Bezeichnung |
|---|---|
| `767002` | White blood cell count |
| `104112007` | White blood cell count, automated, cerebrospinal fluid |
| `104115009` | White blood cell count, automated, peritoneal fluid |
| `104119003` | White blood cell count, automated, pleural fluid |
| `104124000` | White blood cell count, automated, semen |

### `789-8` — Erythrozyten

LOINC: Erythrozyten [#/Volumen] in Blut mittels automatisierter Zählung

| SNOMED | Bezeichnung |
|---|---|
| `14089001` | Red blood cell count |
| `104111000` | Red blood cell count, automated, cerebrospinal fluid |
| `104114008` | Red blood cell count, manual, peritoneal fluid |
| `104118006` | Red blood cell count, automated, pleural fluid |
| `104122001` | Red blood cell count, automated, urine |

