# ADR-021: Die 14 offenen SNOMED-Laborcodes gewählt, und die GFR modernisiert

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-09-08 |
| **Phase** | 3 (Vision) |
| **Betrifft** | `domain/codes.py`, `domain/templates.py`, `tools/erzeuge_snomed_labor_pruefliste.py` |
| **Baut auf** | ADR-003, ADR-015, ADR-020 |
| **Löst ab** | ADR-015 §6 (die 14 SNOMED-Codes, der GFR-Code) — beide erledigt |

---

## 1. Kontext

ADR-015 hat für sechs Laborwerte die SNOMED-Kodierung aus der Spezifikation
übernommen und die übrigen **14** bewusst offen gelassen: Der SNOMED-Slice
ist an kein ValueSet gebunden, die Wahl ist eine **klinische** und gehört
einem Menschen, nicht der Maschine. Als Zwischenschritt entstand
`docs/snomed-labor-pruefliste.md` — Kandidaten aus SNOMED selbst, aber
ausdrücklich ungewählt.

ADR-020 hat mit dem Umstieg auf Stufe 5 alle Laborwerte gegen das
**allgemeine** `ISiKLaboruntersuchung` konform gemacht — ganz ohne
erzwungenes SNOMED. Die Doppelkodierung ist damit von der Konformität
**entkoppelt**, aber nicht wertlos: Sie ist unabhängig vom Profil richtig
(ADR-003 — SNOMED neben LOINC „für beide Zielgruppen"), und ein Empfänger,
der SNOMED spricht, ordnet die Werte damit ein.

Zwei offene Punkte aus ADR-015 §6 sind damit reif zur Entscheidung: die
**14 Codes** und der **GFR-Code** (`33914-3` ist die überholte
MDRD-Formel; die aktuelle Empfehlung ist CKD-EPI).

---

## 2. Entscheidung

**1. Alle 14 offenen Laborwerte bekommen einen SNOMED-Code**, je ein
Messverfahren, das den Analyten im vom LOINC genannten Material trifft.

**2. Der GFR-Wert wechselt von `33914-3` (MDRD) auf `98979-8`**
(CKD-EPI 2021, kreatininbasiert).

Kein Code wurde maschinell eingetragen. Der Weg — genau die Haltung aus
ADR-015:

- **Vorschlag durch die Maschine, verifiziert am Terminologieserver.** Ein
  eigener Rechercheschritt (ein Agent je Wert) prüfte die Kandidaten der
  Prüfliste gegen tx.fhir.org: existiert der Code, ist er aktiv, ist es ein
  Messverfahren (`is-a 122869004`)? Jeder Vorschlag trägt den Fully
  Specified Name des Servers und ein Konfidenz-Flag.
- **Material vor Bequemlichkeit.** Gewählt wurde generisch oder
  materialpassend zum LOINC (meist Serum/Plasma bzw. Blut), nie eine
  Urin-, Liquor- oder Methoden-Sondervariante — der Fall, vor dem ADR-015
  ausdrücklich warnt („Glucose measurement, serum" vs. „…, urine").
- **Freigabe durch den Menschen.** Die vollständige Tabelle wurde
  vorgelegt und Wert für Wert bestätigt, bevor irgendetwas eingetragen
  wurde.

### Die 14 gewählten Codes

| LOINC | Messwert | SNOMED | Bezeichnung |
|---|---|---|---|
| `789-8` | Erythrozyten | `14089001` | Red blood cell count |
| `6690-2` | Leukozyten | `767002` | White blood cell count |
| `2345-7` | Glukose im Serum | `22569008` | Glucose measurement, serum |
| `4548-4` | HbA1c | `43396009` | Hemoglobin A1c measurement |
| `3094-0` | Harnstoff-Stickstoff | `24509005` | Urea nitrogen measurement |
| `2951-2` | Natrium | `104934005` | Sodium measurement, serum |
| `2823-3` | Kalium | `59573005` | Potassium measurement |
| `2075-0` | Chlorid | `46511006` | Chloride measurement |
| `2093-3` | Gesamtcholesterin | `77068002` | Cholesterol measurement |
| `2085-9` | HDL-Cholesterin | `28036006` | High density lipoprotein cholesterol measurement |
| `2571-8` | Triglyzeride | `14740000` | Triglycerides measurement |
| `1742-6` | ALAT (GPT) | `34608000` | Alanine aminotransferase measurement |
| `1920-8` | ASAT (GOT) | `45896001` | Aspartate aminotransferase measurement |
| `1975-2` | Bilirubin gesamt | `359986008` | Bilirubin, total measurement |

---

## 3. Begründung

### Warum diese Codes

Der Stil folgt der Spezifikation selbst: generische Messverfahren, das
Material zum LOINC passend. Wo der LOINC „Serum oder Plasma" sagt, wurde
kein Urin-/Blut-Sondercode und keine Methodenvariante (mit/ohne
Pyridoxal-Phosphat o.ä.) genommen. Zwei Werte tragen bewusst eine
serumspezifische Variante — **Glukose** (`22569008`) und **Natrium**
(`104934005`) —, konsistent mit dem schon vorhandenen serumspezifischen
Kreatinin (`70901006`); Präzision, wo die Terminologie sie hergibt.

### Warum die GFR wechselt

`33914-3` ist die **MDRD**-Formel — klinisch überholt. `98979-8` ist die
**CKD-EPI-2021**-Formel, kreatininbasiert: der aktuelle KDIGO/NKF-ASN-
Standard, **rasse-frei** seit der 2021er Neufassung. Der Tausch ist ein
direktes Like-for-like — kreatininbasiert, pro 1,73 m², kein zusätzlicher
Analyt nötig (anders als die Cystatin-C-Varianten `98980-6`/`94677-2`, die
einen zweiten Messwert bräuchten, den der Katalog nicht führt).

Nebeneffekt: `98979-8` steht — anders als unser MDRD-Code — **im
ValueSet der Spezifikation** für `ISiKLaboruntersuchungGFR`. Der Wert wäre
also auch gegen das *spezifische* GFR-Profil konform, nicht nur gegen das
allgemeine. Der SNOMED-Code `80274001` („Glomerular filtration rate
measurement") ist formelunabhängig und bleibt. Englische und deutsche
Anzeigetexte wurden am Terminologieserver geholt (tx.fhir.de und
tx.fhir.org, byteweise gleich), nicht erfunden.

---

## 3a. Nachweis (2026-09-08)

- **Jeder der 14 Codes am Terminologieserver bestätigt** (tx.fhir.org,
  SNOMED International 20250201): existiert, aktiv, `is-a 122869004`
  (Measurement procedure), korrekter Analyt. Konfidenz durchweg hoch.
- **Referenzvalidator** (offizieller HL7-Validator gegen
  `de.gematik.isik#5.1.3`): Die Laborwerte der Referenzkohorte tragen
  jetzt die zweite Kodierung; gemessen **0 Fehler**
  (`docs/belege/isik-referenzvalidator.json`).
- **Deutsche LOINC-Bezeichnungen** aller Katalogwerte gegen tx.fhir.org
  bestätigt (Live-Terminologietests grün, inkl. der neuen GFR-Bezeichnung).
- **Testreihe grün.**

---

## 4. Konsequenzen

### Positiv

- **Alle 20 Laborwerte tragen jetzt die Doppelkodierung LOINC + SNOMED.**
  Die Prüfliste hat keinen offenen Eintrag mehr.
- **Die GFR ist auf dem Stand der Leitlinie** (CKD-EPI 2021, rasse-frei)
  und zusätzlich gegen das spezifische GFR-Profil konform.
- **Jeder Vorschlag ist belegt**, nicht geraten — dieselbe Sorgfalt wie
  bei den ICD- und Diagnose-Codes.

### Negativ, bewusst in Kauf genommen

- **Jede Observation der 14 Codes ändert sich** (eine Kodierung kommt
  dazu). Bestehende **Aufzeichnungen** dieser Werte melden bei der
  Wiedergabe `ABWEICHUNG` — dieselbe Eigenschaft wie bei den sechs Codes
  aus ADR-015, jetzt für 14 weitere.
- **Der GFR-Wert wechselt die Bedeutung** (MDRD → CKD-EPI 2021) und den
  LOINC-Schlüssel (`33914-3` → `98979-8`). Wer den alten Code extern
  referenziert, muss nachziehen.
- **28 neue Katalogfelder** (`snomed` + `snomed_display` je Wert), die
  gepflegt werden müssen.

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| Elektrolyte durchgängig generisch (Natrium `25197003` statt `104934005`) | Vorgelegt und verworfen: Präzision, wo die Terminologie sie hergibt, konsistent mit dem serumspezifischen Kreatinin. Kalium/Chlorid bleiben generisch, weil es dort kein serumspezifisches Verfahren gibt. |
| GFR auf die Cystatin-C-Variante (`98980-6`, CKD-EPI 2021 Krea+Cys) | Bräuchte einen zweiten Analyten (Cystatin C) im Katalog, den es nicht gibt. Die kreatininbasierte Variante ist das direkte Like-for-like. |
| MDRD (`33914-3`) behalten | Gegen das allgemeine Profil zwar konform, aber klinisch überholt und nicht im spezifischen GFR-ValueSet. |
| Codes maschinell eintragen | Der Katalog ist sicherheitskritisch; der SNOMED-Slice ist an kein ValueSet gebunden, es gäbe keine maschinelle Gegenprobe auf Analyt/Material. Der Mensch entscheidet (ADR-015). |

---

## 6. Offen

- Keiner aus diesem ADR. Die Prüfliste ist leer; ein künftig neuer
  Laborwert ohne SNOMED-Code öffnet sie wieder.
