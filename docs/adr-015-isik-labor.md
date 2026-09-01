# ADR-015: ISiK Labor — was geht, und warum Konformität nicht geht

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-09-01 |
| **Phase** | 3 (Vision) |
| **Betrifft** | `domain/codes.py`, `domain/templates.py`, `tools/erzeuge_snomed_labor_pruefliste.py` (neu) |
| **Baut auf** | ADR-003, ADR-009, ADR-013, ADR-014 |

---

## 1. Kontext

ADR-014 ließ die 20 Laborwerte des Katalogs unprofiliert und nannte den
Grund: Zuständig wäre `ISiK Labor`, ein drittes Modul.

Beim Nachsehen stellte sich zuerst etwas anderes heraus als erwartet.

### Das Modul ist ein Entwurf

Im Paketregister gibt es **eine einzige** Fassung: `4.0.0-rc`, beschrieben
als *„Release Candidate zur Kommentierung"*. Das Quellrepository
`gematik/spec-ISiK-Labor` hat **keine** Freigaben, nur Arbeitszweige. Die
Profile tragen `status: draft`.

Das berührt eine stehende Regel dieses Projekts (ADR-005): nie den
unveröffentlichten Stand zitieren, bei mehrstufigen Standards die
maßgebliche Stufe prüfen.

### Der Entwurf ist nicht erfüllbar

Gemessen mit dem Referenzvalidator gegen `ISiKLaboruntersuchung`, ergab
eine Laborwert-Observation **drei** Fehler. Zwei davon sind echte
Anforderungen (dazu unten). Der dritte ist ein Defekt:

Das **veröffentlichte Paket** verlangt für `Observation.category` das
Muster

    {"code": "laboratory", "system": "http://hl7.org/fhir/secondary-finding"}

Die **Quelle** auf GitHub verlangt an derselben Stelle

    {"code": "laboratory", "system": ".../CodeSystem/observation-category"}

Nachgemessen gegen tx.fhir.org enthält `http://hl7.org/fhir/secondary-finding`
den Code `laboratory` **nicht** — und auch `vital-signs`, `survey` und
`exam` nicht.

Damit ist die Anforderung unerfüllbar, und beide Wege wurden gemessen:

| unsere `category.system` | Ergebnis |
|---|---|
| `…/observation-category` (richtig) | Fehler: Muster nicht erfüllt |
| `…/secondary-finding` (wie gefordert) | Fehler: *Unbekannter Code `laboratory`* |

**Es gibt keine gültige FHIR-Ressource, die dieses Profil erfüllt.**

---

## 2. Entscheidung

**Der Teil, der unabhängig vom Modul richtig ist, wird gebaut. Die
Konformität wird nicht behauptet, und ISiK Labor wird nicht in die
Standardmessung aufgenommen.**

1. `Observation.code` trägt bei Laborwerten eine zweite Kodierung in
   SNOMED — dieselbe Doppelkodierung, die ADR-003 für Diagnosen
   entschieden hat.
2. Gefüllt sind **nur die sechs Codes, die die Spezifikation selbst
   nennt**. Die übrigen 14 wären eine eigene klinische Wahl und stehen als
   Prüfliste (`docs/snomed-labor-pruefliste.md`).
3. `ISiK Labor` kommt **nicht** in `profil.py`. Die Laborwerte bleiben im
   Bericht als unprofiliert ausgewiesen, mit dem Grund.

---

## 3. Begründung

### Warum die Doppelkodierung trotzdem gebaut wird

Zwei der drei Fehler waren echte Anforderungen: `Observation.code.coding`
braucht **zwei** Kodierungen, davon eine in SNOMED. Das ist keine Marotte
des Entwurfs, sondern dieselbe Entscheidung, die ADR-003 für Diagnosen
getroffen hat — SNOMED neben ICD-10-GM, „für beide Zielgruppen".

Gemessen: Mit ergänzter SNOMED-Kodierung bleibt von den drei Fehlern
**genau einer** übrig, und das ist der Defekt des Entwurfs. Die
Doppelkodierung ist also nicht nur richtig, sie ist auch alles, was von
unserer Seite fehlte.

Sie ist außerdem unabhängig vom Modul wertvoll: Ein Empfänger, der SNOMED
spricht, kann unsere Laborwerte damit einordnen.

### Warum nur sechs Codes

`ISiKLaboruntersuchungHb`, `-CRP`, `-TSH`, `-Thrombozyten`,
`-Serumkreatinin` und `-GFR` führen den SNOMED-Code als `patternCoding`.
Diese sechs sind **übernommen, nicht gewählt**.

Für die anderen 14 gibt es keine Quelle. Der SNOMED-Slice des allgemeinen
Profils ist an **kein ValueSet** gebunden — jeder gültige Code erfüllt die
Struktur. Die klinische Richtigkeit prüft also niemand außer einem
Menschen.

Der Katalog ist in diesem Projekt sicherheitskritisch: Die
Laufzeitprüfung sieht Codes nicht, und ein falscher Code erzeugt unbemerkt
inhaltlich falsche Testdaten. Deshalb wird hier nichts eingetragen, was
nicht belegt ist — genau wie bei den ICD-Schlüsseln.

**Was die Maschine beitragen kann, tut sie.**
`tools/erzeuge_snomed_labor_pruefliste.py` holt Kandidaten aus SNOMED
selbst: eine Expansion über `is-a 122869004` (Measurement procedure) mit
Textfilter. Damit ist belegt, dass jeder Vorschlag existiert und ein
Messverfahren ist. Ob er den richtigen Analyten im richtigen Material
meint, entscheidet die Maschine nicht — „Glucose measurement, serum" und
„Glucose measurement, urine" sind beide gültig, und nur einer ist gemeint.

### Warum ISiK Labor nicht in die Standardmessung kommt

Nähme man das Modul auf, zeigte jeder Bericht ab sofort rund zwanzig
Fehler — alle aus einem Defekt eines unveröffentlichten Entwurfs. Das
wäre kein ehrlicherer Bericht, sondern ein lauterer: Rauschen, in dem ein
echter Fehler unterginge.

Die Laborwerte bleiben deshalb als unprofiliert ausgewiesen. Der Bericht
sagt weiterhin in jeder Ausgabe, wie viele es sind und warum.

Wenn das Modul freigegeben ist und der Defekt behoben, ist die Aufnahme
zwei Zeilen: ein Eintrag in `MODULE` und einer in einer
`LABORPROFILE`-Zuordnung, analog zu `VITALPROFILE`.

### Ein Nebenbefund mit klinischem Gewicht

Die Spezifikation bindet `ISiKLaboruntersuchungGFR` an ein ValueSet mit
sechs LOINC-Codes: `98980-6`, `98979-8`, `94677-2`, `62238-1`, `77147-7`,
`50384-7`. Unser `33914-3` ist **nicht** darunter — es ist die
MDRD-Formel, die Liste führt CKD-EPI-Varianten.

Fünf unserer sechs LOINC-Codes sind Mitglied der jeweiligen ValueSets;
nur die GFR nicht. Das ist unabhängig von ISiK ein Hinweis: MDRD gilt als
überholt. Der Wechsel ist eine inhaltliche Entscheidung über den Katalog
und steht unter *Offen*.

---

## 3a. Nachweis (2026-09-01)

**Der Defekt**, gemessen an beiden Wegen — siehe Tabelle in Abschnitt 1.

**Die Doppelkodierung**, Hämoglobin mit ergänztem SNOMED `416125006`
gegen `ISiKLaboruntersuchungHb`:

    vorher:  3 Fehler (Kategorie, zwei Kodierungen, SNOMED-Slice)
    nachher: 1 Fehler (nur noch die Kategorie — der Defekt)

**Die LOINC-Codes gegen die ValueSets der Spezifikation:**

| Profil | unser LOINC | Mitglied |
|---|---|---|
| Hb | 718-7 | ja |
| Serumkreatinin | 2160-0 | ja |
| CRP | 1988-5 | ja |
| TSH | 3016-3 | ja |
| Thrombozyten | 777-3 | ja |
| GFR | 33914-3 | **nein** (Liste führt CKD-EPI) |

**Testreihe: 588 grün** (11 übersprungen ohne Server).

---

## 4. Konsequenzen

### Positiv

- Sechs Laborwerte tragen jetzt eine SNOMED-Kodierung aus der
  Spezifikation — richtig unabhängig davon, ob das Modul je erscheint.
- Der Abstand zu ISiK Labor ist gemessen und beziffert: Es fehlt nur die
  Doppelkodierung, sonst nichts.
- Die 14 offenen Codes sind nicht erfunden, sondern als Prüfliste mit
  belegten Kandidaten aufbereitet.
- Ein Defekt im veröffentlichten Release Candidate ist dokumentiert.

### Negativ, bewusst in Kauf genommen

- **Keine Konformität zu ISiK Labor.** Sie ist derzeit für niemanden
  erreichbar; das ist keine Eigenschaft unserer Daten.
- **14 von 20 Laborwerten haben keine SNOMED-Kodierung.** Sichtbar in der
  Prüfliste, und der Bericht weist die Laborwerte weiterhin als
  unprofiliert aus.
- **Jede Observation der sechs versorgten Codes ändert sich**, weil eine
  Kodierung dazukommt. Bestehende Aufzeichnungen melden ABWEICHUNG.
- **Zwei neue Katalogfelder**, die gepflegt werden müssen.

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| `category.system` auf `secondary-finding` ändern | Erzeugte falsches FHIR — der Code `laboratory` existiert dort nicht — um einen Entwurfsfehler zu bedienen. Gemessen: derselbe eine Fehler, nur an anderer Stelle. |
| ISiK Labor in die Standardmessung aufnehmen | Jeder Bericht zeigte zwanzig Fehler aus einem unerfüllbaren Entwurf. Rauschen, in dem ein echter Fehler unterginge. |
| Die 14 SNOMED-Codes selbst wählen und eintragen | Der Katalog ist sicherheitskritisch, und der Slice ist an kein ValueSet gebunden — es gäbe keine maschinelle Gegenprobe. Dieselbe Haltung wie bei den ICD-Schlüsseln. |
| Auf die Doppelkodierung ganz verzichten, bis das Modul erscheint | Sie ist unabhängig vom Modul richtig, und ADR-003 hat dieselbe Entscheidung für Diagnosen schon getroffen. |
| Die GFR sofort auf einen CKD-EPI-Code umstellen | Eine inhaltliche Katalogänderung mit klinischer Bedeutung. Sie gehört vorgelegt, nicht nebenbei getan. |

---

## 6. Offen

- **Die 14 SNOMED-Codes** aus `docs/snomed-labor-pruefliste.md`.
- **Der GFR-Code.** `33914-3` (MDRD) gegen einen CKD-EPI-Code tauschen —
  fachlich naheliegend, aber eine Entscheidung über den Katalog.
- **ISiK Labor aufnehmen**, sobald es freigegeben und der Kategoriedefekt
  behoben ist. Zwei Zeilen.
- **Den Defekt melden.** Der Release Candidate ist ausdrücklich *zur
  Kommentierung* veröffentlicht; ein Hinweis an die gematik wäre der
  vorgesehene Weg.
