# ADR-024: Das EKG — Kurven als SampledData

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-09-09 |
| **Phase** | 3 (Vision) |
| **Betrifft** | `domain/codes.py`, `domain/templates.py`, `profil.py`, `referenzkohorte.py`, `szenarien.py` |
| **Baut auf** | ADR-014, ADR-023 |

---

## 1. Kontext

ADR-023 hat den Glasgow Coma Score gebaut und das EKG als **letzten**
offenen Sonderfall benannt. Das EKG ist kein Messwert — es ist eine
**Kurve**.

`ISiKEKG` (über das fhir.de-EKG-Profil) verlangt:

- Kategorie `procedure`,
- den Code LOINC `11524-6` („EKG-Bericht"),
- Subjekt und Zeitpunkt,
- **mindestens eine Ableitungs-Komponente** (`ekgLeads`), deren Wert
  **`SampledData`** ist — die Kurve als Rohwerte
  (`origin`/`period`/`dimensions`/`data`).

Der Ableitungscode ist SNOMED und `required` an das ValueSet
`EkgAbleitungenVS` gebunden (die zwölf Standardableitungen). Damit ist das
EKG die dritte Observation-Sonderform neben dem Blutdruckpanel (Komponenten
mit `valueQuantity`) und dem GCS (Komponenten mit `valueCodeableConcept`).

---

## 2. Entscheidung

**Das EKG bekommt einen eigenen Bauweg (`baue_ekg`), analog zu GCS und
Blutdruck, und wird in Kohorte und Bibliothek gemessen.**

1. `codes.py` trägt den Code `11524-6`, die drei Extremitätenableitungen
   (I, II, III) mit ihren SNOMED-Codes aus `EkgAbleitungenVS` und eine
   **feste synthetische Kurve** (`SampledData.data`).
2. `baue_ekg` erzeugt die Observation: Kategorie `procedure`, Code
   (nur LOINC), je Ableitung eine Komponente mit `valueSampledData`.
3. Der Messwert-Bauweg erkennt `11524-6` und ruft `baue_ekg`; der Code
   steht in `SONDER_OBSERVATION_CODES` (eigener Bauweg, gültige
   Messwert-Eingabe, nicht in `OBSERVATION_CODES`).
4. `profil.py` ordnet `11524-6` → `ISiKEKG` zu. Gemessen am
   Herzinsuffizienz-Patienten der Kohorte und im Szenario `intensivkontakt`.

---

## 3. Begründung

### Warum SampledData und keine Media

Das ISiK-Profil ist eine **Observation** mit `SampledData`-Komponenten,
kein `Media`/`DocumentReference`. Die Ableitung ist die Kurve selbst
(Rohwerte um eine Nulllinie), nicht ein Verweis auf ein Bild.

### Warum eine feste synthetische Kurve

Testdaten brauchen keine klinisch echte Kurve, sondern ein **strukturell
gültiges** `SampledData`. Die Kurve ist fest verdrahtet (grob EKG-artiger
Schlag um die Nulllinie 2048), damit die Ausgabe **wiedergabestabil** ist —
eine zufällige Kurve machte jeden Aufzeichnungsvergleich wertlos.

### Warum drei Ableitungen und kein `display`

Drei Extremitätenableitungen (I, II, III) wie im Beispiel der
Spezifikation genügen, um das Profil vorzuführen; die vollen zwölf sind für
Testdaten kein Mehrwert. Der Ableitungscode trägt **kein `display`**: er
ist `required` gebunden, und ein englischer Anzeigename ohne deutsche
Entsprechung würde als Fehler gemeldet — dieselbe gemessene Falle wie bei
den GCS-Antwortcodes. Der lesbare Text steht in `code.text`.

### Warum in die Kohorte

Wie bei GCS, Kopfumfang und Gewicht/Größe (ADR-018 ff.): Ein Profil, das im
Katalog steht, aber von keiner gemessenen Ressource getroffen wird, sieht
konform aus, ohne es gemessen zu haben.

---

## 3a. Nachweis (2026-09-09)

- **Einzeln gegen `ISiKEKG`** (offizieller HL7-Validator, tx.fhir.org,
  `-sct intl`): ein EKG mit drei `SampledData`-Ableitungen → **0 Fehler**.
- **Referenzvalidator** gegen `de.gematik.isik#5.1.3`: `ISiKEKG 1 geprüft,
  0 Fehler`; Kohorte gesamt **0 Fehler**, nichts ungeprüft
  (`docs/belege/isik-referenzvalidator.json`).
- `intensivkontakt`: die Bibliothek zeigt `ISiKEKG`.
- **Testreihe grün.**

---

## 4. Konsequenzen

### Positiv

- **Das EKG ist kein offener Sonderfall mehr — und es war der letzte.**
  Der Bauweg beherrscht jetzt alle drei Observation-Sonderformen:
  Quantity-Panel (Blutdruck), Score-Panel mit kodierten Komponenten (GCS)
  und Kurve als `SampledData` (EKG).
- **Jedes ISiK-Observation-Profil, das der Katalog nennt, wird gebaut und
  gemessen.**

### Negativ, bewusst in Kauf genommen

- **Die Kurve ist synthetisch und fest.** Sie ist strukturell gültig, aber
  keine echte Ableitung; alle EKGs tragen dieselbe Kurve. Für Testdaten
  ausreichend, für eine EKG-Analyse nicht.
- **Nur drei Ableitungen**, nicht die vollen zwölf.
- **Ein Messwert mehr in Kohorte und Szenario** (`geprueft == 34`).

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| EKG als `Media`/`DocumentReference` | `ISiKEKG` ist eine Observation mit `SampledData`-Komponenten, keine Media-Ressource. |
| Eine zufällige/realistische Kurve je Ableitung | Testdaten brauchen strukturelle Gültigkeit und Wiedergabestabilität, keine echte Physiologie. |
| Alle zwölf Ableitungen | Kein Mehrwert für Testdaten; drei genügen zur Vorführung des Profils. |
| `display` auf den Ableitungscodes | Gemessen ein Fehler: keine deutsche Bezeichnung bei `required`-Bindung. Text statt Display. |

---

## 6. Offen

- Keiner aus diesem ADR. Damit sind die Sonderfälle aus ADR-019/022
  (GCS, EKG) beide geschlossen.
