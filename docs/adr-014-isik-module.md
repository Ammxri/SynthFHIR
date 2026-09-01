# ADR-014: Die ISiK-Module für Observation und MedicationStatement

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-09-01 |
| **Phase** | 3 (Vision) |
| **Betrifft** | `domain/codes.py`, `domain/templates.py`, `profil.py`, `tools/isik_referenzvalidator.py`, Compose |
| **Baut auf** | ADR-001, ADR-003, ADR-007, ADR-009, ADR-013 |

---

## 1. Kontext

ADR-009 hatte Observation und MedicationStatement ausdrücklich offen
gelassen:

> Nur das Basismodul, nur drei Typen. Observation und MedicationStatement
> brauchen eigene Module.

Die Module heißen `de.gematik.isik-vitalparameter` (4.0.2) und
`de.gematik.isik-medikation` (4.0.3). Der Abstand wurde gemessen, nicht
geschätzt — mit dem Referenzvalidator aus ADR-013, gegen einen
Terminologieserver.

### Was die Module wirklich profilieren

**Vitalparameter profiliert nicht „Observation".** Es profiliert **je
Vitalparameter einzeln**: `ISiKHerzfrequenz`, `ISiKKoerpergewicht`,
`ISiKKoerpergroesse`, `ISiKBlutdruckSystemischArteriell` und weitere,
dazu 47 MII-ICU-Profile. Welches Profil gilt, entscheidet der LOINC-Code
der einzelnen Ressource — nicht ihr Typ.

Von den 25 Messwertcodes des Katalogs sind **fünf** Vitalparameter. Die
anderen 20 sind Laborwerte; für sie wäre `ISiK Labor` zuständig, ein
**drittes** Modul.

### Vier Messungen, die den Zuschnitt bestimmen

**(1) MedicationStatement ist bereits konform.** Unsere Ausgabe gegen
`ISiKMedikationsInformation|4.0.3`: **0 Fehler**, ohne jede Änderung.

Das korrigiert eine eigene Fehlannahme. Aus dem Differential hatte ich
`MedicationStatement.medication[x].reference` mit `min=1` gelesen und
daraus geschlossen, eine sechste Ressource (`Medication`) sei Pflicht.
Falsch: Die Bedingung gilt, *falls* eine Referenz benutzt wird — nicht,
*dass* eine benutzt werden muss. `medicationCodeableConcept` genügt.

Gegenprobe, damit das nicht bloß so aussieht: `status` und
`subject.reference` entfernt → **3 Fehler**. Das Profil wird also
angewandt.

**(2) Drei Vitalparameter fehlt genau ein Feld.** Körpergewicht,
Körpergröße und Herzfrequenz ergaben **je einen** Fehler:

> Wrong Display Name 'Body weight' for `http://loinc.org#29463-7`.
> Valid display is 'Körpergewicht' (de-DE)

Wir setzen den englischen LOINC-Text in `Coding.display`; das deutsche
Profil verlangt den deutschen.

**(3) Es ist keine Fehlerbehebung, sondern eine Entscheidung.** Mit
`-language en` sind es **0 Fehler**. Der Befund entsteht, weil das
ISiK-Paket Zuständigkeit DE erklärt und der Validator deshalb deutsch
prüft. Unsere Daten sind als englisches LOINC korrekt — nur nicht im
Zusammenhang, für den dieses Werkzeug gemacht ist.

**(4) Der Blutdruck ist strukturell unvereinbar.** `obs-002` gegen
`ISiKBlutdruckSystemischArteriell` ergab **12 Fehler**:

    BPCode: magic LOINC code 85354-9 required, but not found
    Observation.component: mindestens erforderlich = 2, aber gefunden 0
    Observation.value[x]: maximal erlaubt = 0, aber gefunden 1

Verlangt wird **eine** Observation mit Panel-Code und zwei Komponenten,
ohne eigenen Wert. Wir erzeugen **zwei** Observations mit je einem Wert.

---

## 2. Entscheidung

**Beide beauftragten Module werden erfüllt. Das Labor-Modul nicht — es
war nicht beauftragt, und sein Fehlen wird ausgewiesen statt verschwiegen.**

1. `Coding.display` trägt bei LOINC die **amtliche deutsche** Bezeichnung.
   Neues Katalogfeld `display_loinc_de`, für alle 25 Codes gefüllt und
   gegen tx.fhir.org geprüft.
2. **Blutdruck wird ein Panel**: eine Observation, Code 85354-9, zwei
   Komponenten, kein eigener Wert. Das ist eine Änderung an der
   **Erzeugung**.
3. `profil.py` ordnet Profile **je Ressource** zu, nicht je Typ.
4. Der Messaufbau lädt alle drei Module; der Bericht nennt sie alle.
5. Unprofilierte Ressourcen werden **je Ressource gezählt** und benannt.

---

## 3. Begründung

### Warum der deutsche Anzeigetext, obwohl es kein Fehler ist

`-language en` macht den Befund verschwinden — die Daten sind also nicht
falsch. Die Frage ist, für welchen Zusammenhang dieses Werkzeug Daten
erzeugt, und die ist beantwortet: für den deutschen. Ein Krankenhaus, das
unsere Testdaten gegen ISiK prüft, prüft sie deutsch.

ADR-003 hatte das bereits entschieden, nur nicht bis hierher gedacht:
„Namen, Geburtsdaten und Anzeigetexte werden deutsch. `Observation.code`
bleibt bei LOINC." Der **Code** bleibt LOINC — das ändert sich nicht. Der
**Anzeigetext** wird deutsch, und genau das steht dort.

**Drei Felder, drei Aufgaben**, und sie dürfen nicht vermischt werden:

| Feld | Inhalt | wohin |
|---|---|---|
| `display` | LOINCs englischer Text | Rückfall, wenn kein deutscher da ist |
| `display_loinc_de` | LOINCs **amtlicher** deutscher Text | `Coding.display` |
| `display_de` | unsere Kurzform | `CodeableConcept.text` |

Die dritte Zeile ist der Punkt: „HbA1c" ist keine LOINC-Bezeichnung.
LOINCs deutscher Text lautet „Hämoglobin A1c/Hämoglobin.gesamt in Blut".
Nachgemessen stimmen nur **3 von 25** unserer Kurzformen mit LOINCs
amtlicher Fassung überein — `display_de` einfach in `Coding.display` zu
schreiben hätte 22 neue Fehler erzeugt.

Lizenzrechtlich ist der Weg frei: Anders als bei SNOMED, wo Übersetzen
beschränkt ist (`NOTICE.md`), veröffentlicht LOINC seine deutschen
Fassungen selbst.

**Die Werte hängen am Server, von dem sie stammen.** Nachgemessen führt
tx.fhir.de für `33914-3` (geschätzte GFR) **keine** deutsche Bezeichnung
und antwortet mit dem englischen Text; tx.fhir.org hat eine. Der Test
fragt deshalb ausdrücklich tx.fhir.org — gegen den Vorgabeserver zu
prüfen hiesse, eine Lücke jenes Servers als Katalogfehler zu melden.
Praktische Folge hat die Abweichung keine: `33914-3` ist ein Laborwert,
für den es kein Profil gibt, das den Anzeigenamen prüfte.

### Warum der Blutdruck die Erzeugung betrifft

Das ist der zweite Fall nach `isik-con1` (ADR-009), in dem
Profilkonformität nicht durch ein zusätzliches Feld zu haben ist. Zwei
Messwerte werden zu **einer** Ressource — die Zahl der Ressourcen ändert
sich, nicht nur ihr Inhalt.

Dieselbe Arbeitsteilung wie in ADR-001: Das Modell nennt weiterhin
`8480-6` und `8462-4`, der Code baut daraus die Struktur. Der Katalog
behält beide Einzelcodes.

**Gepaart wird am selben Datum.** Das ist die einzige Zuordnung, die aus
den Parametern hervorgeht; alles andere wäre geraten. Was sich nicht
paaren lässt — ein systolischer Wert ohne Gegenstück — bleibt eine eigene
Observation. Sie ist dann gültiges FHIR, nur nicht profilkonform; sie zu
verwerfen wäre schlimmer, als sie stehenzulassen.

### Warum die Zuordnung je Ressource gehen muss

`PROFILE` bildete bisher Typ → Profil ab, `OHNE_PROFIL` nannte Typen ganz
ohne Profil. Diese Zweiteilung trägt die neue Lage nicht: Ein
Observation-Satz ist zur Hälfte profiliert (Vitalparameter) und zur
Hälfte nicht (Laborwerte). Die alte Meldung „für Observation gibt es kein
Profil" wäre schlicht falsch geworden — und hätte den Bericht
vollständiger aussehen lassen, als er ist.

`profil_fuer(ressource)` entscheidet deshalb je Ressource, und der
Bericht zählt Unprofiliertes je Ressource:

> 2 Observation-Ressource(n) ohne Profil in den geladenen Modulen. Für
> Laborwerte wäre das Modul ISiK Labor zuständig; es ist nicht geladen.

### Warum ISiK Labor nicht gebaut wird

Der Auftrag lautete „die ISiK-Module für Observation und
MedicationStatement". Labor ist ein drittes Modul mit eigenem Umfang, und
es zu bauen wäre eine Ausweitung, die niemand bestellt hat. Es wird
benannt, nicht verschwiegen — 20 der 25 Messwertcodes bleiben
unprofiliert, und der Bericht sagt das in jeder Ausgabe.

---

## 3a. Nachweis (2026-09-01)

**Gegen HAPI 8.10.0 mit allen drei Modulen**, ohne Terminologieserver:

| Typ | geprüft | Fehler | ungeprüft | Warnungen |
|---|---|---|---|---|
| Condition | 4 | **0** | 8 | 8 |
| Encounter | 4 | **0** | 0 | 8 |
| MedicationStatement | 2 | **0** | 2 | 8 |
| Observation | 1 | **0** | 3 | 6 |
| Patient | 3 | **0** | 0 | 3 |
| **Summe** | **14** | **0** | 13 | 33 |

Vorher waren es 11 geprüfte Ressourcen. Die 13 ungeprüften sind mehr als
die 8 aus ADR-009 — die neuen Profile bringen neue Terminologiebindungen
mit, die HAPI ohne Terminologieserver nicht auflösen kann. Das ist keine
Verschlechterung, sondern mehr Messfläche.

**Gegen den HL7-Referenzvalidator** mit Terminologie:

| Profil | geprüft | Fehler | Warnungen |
|---|---|---|---|
| ISiKBlutdruckSystemischArteriell | 1 | **0** | 2 |
| ISiKDiagnose | 4 | **0** | 12 |
| ISiKKontaktGesundheitseinrichtung | 4 | **0** | 8 |
| ISiKMedikationsInformation | 2 | **0** | 2 |
| ISiKPatient | 3 | **0** | 3 |
| **Summe** | **14** | **0** | 27 |

Und ausdrücklich gesucht: **keine ungeprüften Befunde**.

**Testreihe: 590 grün** (vorher 583).

### Die Zielgestalt war belegt, bevor gebaut wurde

Ein von Hand geschriebenes Blutdruck-Panel — Code 85354-9 mit LOINCs
amtlicher deutscher Bezeichnung, zwei Komponenten, kein Wert — ergab
gegen `ISiKBlutdruckSystemischArteriell` **0 Fehler**. Erst danach wurde
der Generator umgebaut.

---

## 4. Konsequenzen

### Positiv

- Alle fünf erzeugten Ressourcentypen sind jetzt profilgeprüft, soweit
  ISiK sie kennt.
- Der Blutdruck ist erstmals FHIR-richtig modelliert. Zwei getrennte
  Observations waren auch ohne ISiK die schlechtere Form — das
  Kernprofil `hl7.org/fhir/StructureDefinition/bp` verlangt dasselbe.
- Die Anzeigetexte stimmen mit LOINCs amtlicher deutscher Fassung
  überein, statt englisch in einem deutschen Zusammenhang zu stehen.
- Der Bericht kann jetzt sagen, welche Ressourcen **nicht** geprüft
  wurden — vorher konnte er das nur je Typ.

### Negativ, bewusst in Kauf genommen

- **Jedes Bundle mit Blutdruck ändert sich**, und die Ressourcenzahl sinkt
  (zwei werden eins). Die Referenzkohorte fiel von 17 auf 16 Ressourcen.
  Bestehende Aufzeichnungen melden bei der Wiedergabe `ABWEICHUNG` — der
  Selbsttest aus ADR-006 bei der Arbeit, und der Befund ist richtig: Es
  liegt an den Vorlagen.
- **Jede Observation ändert sich**, weil `Coding.display` jetzt deutsch
  ist. Dasselbe gilt.
- **20 von 25 Messwertcodes bleiben unprofiliert.** Sichtbar in jedem
  Bericht.
- **Der Messaufbau lädt drei Pakete statt einem.** Der Server braucht
  länger zum Starten.
- **Ein unpaariger Blutdruckwert bleibt profilfremd.** Er ist gültiges
  FHIR und wird nicht verworfen, erfüllt aber kein Vitalparameter-Profil.
- **Ein viertes Katalogfeld je Messwert**, das gepflegt werden muss.
  `tests/test_terminologie.py` hält es gegen tx.fhir.org.

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| `display_de` in `Coding.display` schreiben | Nachgemessen stimmen nur 3 von 25 mit LOINCs amtlicher deutscher Fassung überein — 22 neue Fehler. „HbA1c" ist keine LOINC-Bezeichnung. |
| Beim englischen `display` bleiben | Technisch richtig, aber falsch für den Zusammenhang, für den dieses Werkzeug Daten erzeugt. ADR-003 hat „Anzeigetexte werden deutsch" schon entschieden. |
| Eine `Medication`-Ressource bauen | Gemessen nicht nötig: `medicationCodeableConcept` erfüllt `ISiKMedikationsInformation` bereits. Meine erste Lesart des Differentials war falsch. |
| Blutdruck als zwei Observations lassen | 12 Fehler, und das Kernprofil `bp` verlangt dasselbe wie ISiK. Es war auch vorher die schlechtere Modellierung. |
| Blutdruck nach Reihenfolge paaren statt nach Datum | Das Datum steht in den Parametern; die Reihenfolge wäre geraten. |
| Unpaarige Blutdruckwerte verwerfen | Stilles Wegwerfen von Modellausgabe. Sie bleiben als eigene Observation stehen. |
| ISiK Labor mitbauen | Ein drittes Modul, nicht beauftragt. Es wird benannt statt verschwiegen. |
| `meta.profile` setzen | Unverändert die Haltung aus ADR-009: Die Ressourcen erfüllen die Profile, behaupten es aber nicht. |
| `OHNE_PROFIL` je Typ beibehalten | Wäre nach dieser Änderung eine falsche Aussage: Observation ist zur Hälfte profiliert. |

---

## 6. Offen

- **ISiK Labor** für die 20 Laborwerte. Das ist der nächste Brocken, und
  er ist größer als dieser.
- **Weitere Vitalparameter.** Der Katalog führt fünf; das Modul kennt
  Körpertemperatur, Atemfrequenz, Sauerstoffsättigung, Kopfumfang und
  mehr. Neue Katalogeinträge wären damit sofort profilgeprüft.
- **Die vier SNOMED-Anzeigetexte** in `Condition.code` bleiben englisch.
  Anders als bei LOINC ist Übersetzen dort lizenzrechtlich beschränkt
  (`NOTICE.md`); der Validator meldet es als Warnung, nicht als Fehler.
- **`Observation.performer`** fehlt — eine Warnung, kein Fehler. Ein
  erfundener Behandler wäre eine erfundene Person.
