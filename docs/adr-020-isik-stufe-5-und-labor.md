# ADR-020: ISiK Stufe 5 — ein Paket, und Labor wird konform

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-09-08 |
| **Phase** | 3 (Vision) |
| **Betrifft** | `profil.py`, `referenzkohorte.py`, `tools/isik_referenzvalidator.py`, `docs/belege/docker-compose.isik.yml` |
| **Baut auf** | ADR-014, ADR-015, ADR-019 |
| **Löst ab** | ADR-015 in einem Punkt: „Keine Konformität zu ISiK Labor" |

---

## 1. Kontext

ADR-015 ließ die 20 Laborwerte des Katalogs unprofiliert und nannte zwei
Gründe: `ISiK Labor` existierte nur als Release Candidate `4.0.0-rc`, und
dieser Entwurf war **nicht erfüllbar** — er band `Observation.category` an
das CodeSystem `http://hl7.org/fhir/secondary-finding`, das den geforderten
Code `laboratory` gar nicht enthält. Es gab keine gültige FHIR-Ressource,
die das Profil erfüllte.

ADR-015 sagte auch, was die Aufnahme kostete, sobald der Defekt behoben
sei: **„zwei Zeilen: ein Eintrag in `MODULE` und einer in einer
`LABORPROFILE`-Zuordnung, analog zu `VITALPROFILE`."**

Beim erneuten Nachsehen (2026-09-08) stellte sich heraus: Der Defekt **ist
behoben** — nicht im eigenständigen Modul, sondern im vereinheitlichten
Paket der **Stufe 5**, `de.gematik.isik#5.1.3` (aktiv, freigegeben). Die
gematik hat mit Stufe 5 die vorher getrennten Module (Basismodul,
Vitalparameter, Medikation) und Labor in **ein** Paket zusammengeführt.
`ISiKLaboruntersuchung` bindet `category` dort korrekt an
`observation-category`.

Damit war die Voraussetzung erfüllt, die ADR-015 selbst genannt hatte.

---

## 2. Entscheidung

**Migration auf ISiK Stufe 5 (`de.gematik.isik#5.1.3`) als einziges Paket,
und Profilierung aller Laborwerte gegen das allgemeine
`ISiKLaboruntersuchung`.**

1. `MODULE` in `profil.py` führt statt der drei Stufe-4-Pakete das eine
   Paket `de.gematik.isik#5.1.3`. `PAKET`/`PAKETVERSION` entsprechend.
2. `profil_fuer` gibt für jede Observation mit LOINC, die kein
   Vitalparameter ist, `ISiKLaboruntersuchung` zurück (statt `None`).
   Nur eine Observation ganz ohne LOINC bleibt unprofiliert.
3. Die Referenzkohorte bekommt einen Patienten mit breitem Laborsatz
   (Kreatinin, CRP, Natrium, Kalium, Glukose), damit das neue Profil im
   eingecheckten Beleg an mehr als zwei Einzelwerten hängt.

---

## 3. Begründung

### Warum die ganze Migration und nicht nur „Labor dazu"

Stufe 4 und Stufe 5 teilen sich die **kanonischen URLs** der Profile, aber
unter **verschiedenen Versionen**. Ein Validator kann nicht das
Stufe-4-Basismodul und das Stufe-5-Labor gleichzeitig laden — er meldete
einen Versionskonflikt auf derselben URL. „ISiK Labor einbauen" heißt
deshalb zwangsläufig: **ganz auf Stufe 5**. Ein Nebeneinander gibt es
nicht.

Das ist kein Nachteil, sondern die Richtung der Spezifikation selbst:
Stufe 5 ist die aktuelle, aktive Stufe; die drei getrennten
Stufe-4-Module sind ihr Vorläufer. Gemessen wurde, dass **alle** bereits
konformen Ressourcen — Patient, Kontakt, Diagnose, die sieben
Vitalparameter, Medikation — gegen Stufe 5 unverändert **0 Fehler**
liefern. Die Migration verliert nichts.

### Warum das allgemeine Profil, nicht die spezifischen

ADR-015 hatte für die SNOMED-Doppelkodierung die **spezifischen** Profile
im Blick (`ISiKLaboruntersuchungHb`, `-CRP`, `-GFR` …). Diese Migration
wählt bewusst das **allgemeine** `ISiKLaboruntersuchung` für alle
Laborwerte. Der Unterschied entscheidet über die Erreichbarkeit:

- Das allgemeine Profil verlangt nur eine **LOINC-Kodierung** (`code.coding:loinc`
  min=1), `category`, `subject` und — wenn ein Wert da ist —
  `valueQuantity.value/system/code`. Es erzwingt **keine** SNOMED-Kodierung
  und bindet die Werte an **kein** analytspezifisches ValueSet.
- Damit sind **alle 20 Laborwerte** des Katalogs erfüllbar, so wie sie
  sind — auch die 14 ohne SNOMED-Code (ADR-015 §6), und auch die **GFR**.

Der GFR-Nebenbefund aus ADR-015 (unser `33914-3` ist MDRD, das ValueSet
des **spezifischen** Profils führt CKD-EPI) ist damit von der Konformität
**entkoppelt**: Gegen das allgemeine Profil ist `33914-3` konform. Die
Frage MDRD → CKD-EPI bleibt eine Frage der **Katalogqualität**, aber sie
blockiert keine Konformität mehr.

Die spezifischen Profile hätten das Gegenteil bewirkt: Sie hätten auf 14
Werten eine SNOMED-Kodierung erzwungen, die der Katalog aus gutem Grund
noch nicht hat (der Slice ist an kein ValueSet gebunden — niemand außer
einem Menschen prüft die klinische Richtigkeit, ADR-015 §3), und die GFR
wäre am CKD-EPI-ValueSet gescheitert.

### Was von ADR-015 bleibt

- Die **SNOMED-Doppelkodierung** der sechs spezifizierten Codes bleibt.
  Sie ist unabhängig vom Profil wertvoll (ein SNOMED-Empfänger ordnet die
  Werte ein) und schadet dem allgemeinen Profil nicht.
- Die **Prüfliste** der 14 offenen SNOMED-Codes
  (`docs/snomed-labor-pruefliste.md`) bleibt offen — jetzt ohne
  Konformitätsdruck.
- Die **GFR-Frage** bleibt offen, aber entschärft.

### Kein Ressourcen-Byte ändert sich

Anders als ADR-015 (das jeder versorgten Observation eine Kodierung
hinzufügte und damit ABWEICHUNG gegen bestehende Aufzeichnungen erzeugte)
ändert diese Migration **keine** Ressource. `profil_fuer` steuert allein
die Messung; die erzeugten Ressourcen tragen kein `meta.profile`. Ein
bestehender Datensatz sieht nach der Migration byteweise gleich aus — nur
der **Bericht** misst ihn jetzt gegen ein Profil mehr.

---

## 3a. Nachweis (2026-09-08)

Offizieller HL7-Validator (`validator_cli.jar`) gegen
`de.gematik.isik#5.1.3`, Terminologie tx.fhir.org (`-sct intl`),
Referenzkohorte:

    ISiKLaboruntersuchung                    7        0      16
    … (alle übrigen Profile)                          0
    SUMME                                   29        0      59

    Keine ungeprüften Befunde: Die Terminologie hat entschieden.

**29 geprüft, 0 Fehler, nichts ungeprüft.** Die sieben Laborwerte decken
beide Fälle ab: HbA1c (4548-4) und Natrium/Kalium/Glukose ohne SNOMED,
Hb (718-7)/Kreatinin (2160-0)/CRP (1988-5) mit SNOMED-Doppelkodierung.
Alle erfüllen das allgemeine Profil. Die 59 Warnungen sind sämtlich
bekannt und harmlos (dom-6-Narrative, fehlender Performer, ICD-10-GM-2026
kennt tx.fhir.org noch nicht, fehlende deutsche SNOMED-Displaynamen) —
keine ist ein Konformitätsmangel.

Der volle Beleg steht in `docs/belege/isik-referenzvalidator.json`.

**Testreihe grün.**

---

## 4. Konsequenzen

### Positiv

- **Jede Katalog-Observation ist jetzt profiliert und konform gemessen.**
  Der Bericht sagt nicht mehr „20 Laborwerte unprofiliert".
- **Ein Paket statt drei.** `de.gematik.isik#5.1.3` trägt Basismodul,
  Vitalparameter, Medikation und Labor. Die Messkonfiguration
  (`docker-compose.isik.yml`, `tools/isik_referenzvalidator.py`) wird
  einfacher.
- **Auf der aktuellen Stufe der Spezifikation.** Stufe 5 ist aktiv; die
  getrennten Stufe-4-Module waren der Vorläufer.
- **Keine ABWEICHUNG.** Bestehende Aufzeichnungen ändern sich nicht.

### Negativ, bewusst in Kauf genommen

- **Stufe 4 und Stufe 5 sind nicht mischbar.** Wer aus einem anderen Grund
  auf Stufe 4 bleiben müsste, kann das Labor nicht einzeln nachrüsten.
  Das ist eine Eigenschaft der Spezifikation, nicht dieser Wahl.
- **Die 14 SNOMED-Codes und die GFR-Frage bleiben offen** — jetzt aber
  ohne Konformitätsdruck (siehe Offen).
- **Ein Toleranztest weniger:** Es gibt keine unprofilierte Observation
  mehr im Normalfall, an der sich „der Bericht verschweigt nichts"
  zeigen ließe. Die Negativkontrolle dafür steht im Test.

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| Auf Stufe 4 bleiben, Labor separat nachrüsten | Technisch unmöglich: Stufe-4-Module und Stufe-5-Labor teilen kanonische URLs unter verschiedenen Versionen — Versionskonflikt beim Laden. |
| Die **spezifischen** Laborprofile verwenden | Hätten auf 14 Werten SNOMED erzwungen (Katalog hat es nicht, aus gutem Grund) und die GFR am CKD-EPI-ValueSet scheitern lassen. Das allgemeine Profil ist für den ganzen Katalog erfüllbar. |
| Weiter warten, bis das eigenständige `isik-labor` freigegeben ist | Der Defekt ist in Stufe 5 bereits behoben und freigegeben. Warten hieße, eine verfügbare Lösung auszuschlagen. |
| Die gematik zum `4.0.0-rc`-Defekt anschreiben | In Stufe 5 behoben — eine Rückmeldung zum Vorläufer wäre gegenstandslos. (Dieser Punkt aus ADR-015 §6 entfällt.) |

---

## 6. Offen

- **Die 14 SNOMED-Codes** aus `docs/snomed-labor-pruefliste.md` — jetzt
  ohne Konformitätsdruck, weiterhin eine klinische Entscheidung.
- **Der GFR-Code.** `33914-3` (MDRD) gegen CKD-EPI — von der Konformität
  entkoppelt, bleibt eine Frage der Katalogqualität.
- **Stufe 6 — geprüft am 2026-09-08, NICHT gesprungen.** Im Paketregister
  trägt zwar `de.gematik.isik#6.0.0` den `latest`-Tag, aber „latest" ist
  nicht „maßgeblich" (ADR-005). Belegt: Die gematik führt Stufe 6 in der
  Roadmap Q1 2026 in der **Konzeptionsphase**; der Implementierungsleitfaden
  erscheint als `6.0.0-rc`; im Mai 2026 lief ein **Kommentierungsverfahren**.
  Verbindlich ist laut fachportal.gematik.de aktuell **Stufe 3**, **Stufe 5**
  ist seit 01.07.2025 veröffentlicht und ihre Verbindlichkeit „in
  Herstellung", **Stufe 4** ist abgekündigt. SynthFHIR misst gegen die
  neueste **freigegebene** Stufe — das ist 5, nicht der Entwurf 6. Der
  Sprung wird erneut geprüft, wenn Stufe 6 freigegeben ist (kein `-rc`,
  keine Konzeptionsphase) — dann derselbe Weg wie hier. Genau die Haltung
  aus ADR-005 und ADR-015: nie den unveröffentlichten Stand zitieren.
- ~~**Der Diagnose-Terminologienachweis pinnt noch Stufe 4.**~~
  **Erledigt 2026-09-08:** `terminologie.py` zieht die `DiagnosesSCT`-Quelle
  jetzt auf den Tag `v.5.1.3`, mit neuem SHA-Pin. Die Definition war
  byteweise gleich (dieselben drei `is-a`-Wurzeln), die Mitgliedschaft der
  25 Codes gegen tx.fhir.de und tx.fhir.org neu gemessen: 25 von 25
  (ADR-013, Nachtrag).
- **Der HAPI-Beleg** (`docs/belege/isik-profilbericht.json`, vom
  `synthfhir-profil`-Werkzeug) ist noch vom Stand ADR-009; er braucht zum
  Erneuern den Docker-Profilserver. Der maßgebliche Beleg
  (`isik-referenzvalidator.json`) ist auf Stufe 5 aktuell.
