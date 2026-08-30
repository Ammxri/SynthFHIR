# Sondierung: Wie weit ist SynthFHIR von ISiK entfernt?

| | |
|---|---|
| **Art** | Messung, keine Entscheidung |
| **Datum** | 2026-08-30 |
| **Anlass** | Phase 3 des PRD, Punkt „Deutsche Spezialprofile (KBV/ISiK)" |
| **Ergebnis** | Die Lücke ist klein und benannt. Ob sie geschlossen wird, ist offen. |

---

## Warum überhaupt messen

Das PRD führt deutsche Spezialprofile unter Phase 3 als *Could* mit
Komplexität **L**, und das Gate der Phase lautet wörtlich *„Nachweisbare
Nachfrage aus der Nische"*. Beides sind Gründe, nicht einfach loszubauen.

Nach der Methode dieses Projekts steht am Anfang deshalb eine Messung: Wie
weit ist die heutige Ausgabe von ISiK entfernt? Eine Schätzung wäre hier
wertlos — genau wie in Phase 0, wo die Architekturentscheidung erst durch
42 gemessene Läufe entschieden war.

## Aufbau

Ein **zweiter** HAPI-Container auf Port 8090, getrennt vom
Validierungsserver der CI. Der Messaufbau darf die bestehende Prüfkette
nicht anfassen, solange nicht entschieden ist, ob überhaupt gebaut wird.

Geladene Pakete (geprüft am 2026-08-30 auf simplifier.net):

* `de.gematik.isik-basismodul` **4.0.3** — herausgegeben von der gematik,
  FHIR R4
* `de.basisprofil.r4` **1.5.3** — Abhängigkeit des ISiK-Pakets

> **Nachtrag zur Version.** 4.0.3 ist die `latest` des Paketregisters, aber
> **nicht** die maßgebliche Stufe. Die gematik führt ISiK in Stufen; die
> tragende Bestätigungsstufe ist derzeit **Stufe 3** (`3.1.1`), und für
> **Stufe 5** wird die Verbindlichkeit gerade festgelegt — Hersteller mit
> gültiger Stufe-3-Bestätigung erhalten dafür eine Verlängerung. „Aktuelle
> Fassung" war für 4.0.3 also die falsche Beschreibung.
>
> Technisch folgt daraus mehr als eine Fußnote: **Die kanonischen
> Profil-URLs unterscheiden sich zwischen den Stufen.**
>
> | Stufe | URL von ISiKPatient |
> |---|---|
> | 3.1.1 | `https://gematik.de/fhir/isik/v3/Basismodul/StructureDefinition/ISiKPatient` |
> | 4.0.3 | `https://gematik.de/fhir/isik/StructureDefinition/ISiKPatient` |
>
> Wer je `meta.profile` setzt, entscheidet damit eine Stufe. Die
> Lückenklassen unten sind davon unberührt — `isik-con1` etwa existiert in
> beiden Fassungen —, die Wahl der Stufe wäre aber eine eigene
> Entscheidung.

Beide Pakete laden über die Umgebungsvariablen
`hapi.fhir.implementationguides.<name>.name` und `.version` und werden im
Protokoll des Containers bestätigt.

> **Merkposten:** Paketinhalte landen im Paketspeicher, **nicht** als
> durchsuchbare Ressourcen. `GET /StructureDefinition?url=…` liefert null,
> obwohl das Profil geladen ist. Der Validator benutzt es trotzdem.

Validiert wurde mit `$validate?profile=<kanonische URL>` gegen eine
Kohorte, wie sie das Produkt heute erzeugt.

## Befund vor jeder Änderung

| Ressource | Profil | Fehler |
|---|---|---|
| Patient | ISiKPatient | 1 |
| Encounter | ISiKKontaktGesundheitseinrichtung | 3 |
| Condition | ISiKDiagnose | 5 |

(Gemessen an einer Kohorte **mit** Begegnung. Ohne Begegnung kommt ein
sechster Fehler dazu — siehe unten.)

Im Einzelnen:

* **Patient** — der Slice `identifier:Patientennummer` fehlt. Vorhanden ist
  ein Identifier, aber ohne `type`-Kodierung, an der die Zuordnung hängt.
* **Encounter** — `identifier` fehlt, `type` fehlt, und damit auch der
  Slice `type:Kontaktebene`.
* **Condition** — `recordedDate` fehlt, der ICD-10-GM-Kodierung fehlt
  `version`, und die SNOMED-Kodierung wird im ValueSet nicht gefunden.

## Befund nach fünf Ergänzungen

Versuchsweise ergänzt wurden:

1. `Patient.identifier.type` = `MR` aus `v2-0203`
2. `Encounter.identifier` mit `type` = `VN` aus `v2-0203`
3. `Encounter.type` mit einer Kodierung aus
   `http://fhir.de/CodeSystem/Kontaktebene`
4. `Condition.recordedDate`
5. `version` in der ICD-10-GM-Kodierung (die ICD-Jahresfassung)

| Profil | vorher | nachher |
|---|---|---|
| ISiKPatient | 1 | **0** |
| ISiKKontaktGesundheitseinrichtung | 3 | **0** |
| ISiKDiagnose | 5 | **2** |

### Und ein Fehler, den diese Messung zuerst übersehen hat

Die Messkohorte hatte eine Begegnung. Damit lief sie an einer
Zwangsbedingung vorbei, die ISiK stellt:

```
Constraint failed: isik-con1: 'Falls eine kodierte Diagnose vorliegt muss
angegeben werden durch welchen Kontakt diese Dokumentation erfolgte.'
```

Nachgestellt mit einem Patienten **ohne** Begegnung: Die Diagnose ist dann
nicht konform. Und genau diesen Fall erzeugt das Produkt heute regelmäßig —
`begegnungen` ist im Parameterobjekt optional, und die Vorlage setzt
`Condition.encounter` nur, wenn eine Begegnung vorliegt.

**Das ändert den Zuschnitt.** ISiK-Konformität ist nicht nur eine Frage von
fünf additiven Feldern, sondern verlangt eine **strukturelle Zusage**: Jeder
Patient mit kodierter Diagnose braucht einen Kontakt. Das ist eine Änderung
an der Erzeugung, nicht an einer Vorlage.

Der Prüffehler dahinter ist in diesem Projekt nicht neu: Gemessen wurde der
Fall, der ohnehin durchgeht. Dieselbe Sorte Irrtum wie zweimal zuvor beim
Nachstellen von Katalogfehlern.

**Die verbleibenden zwei sind kein Datenfehler.** Der Validator kann das
ValueSet `DiagnosesSCT` nicht auflösen, weil dem Server keine
SNOMED-Terminologie vorliegt — er sagt es selbst:

```
Unable to expand ValueSet: cannot apply filters […] because
CodeSystem 'http://snomed.info/sct' […]
The Coding provided (http://snomed.info/sct#44054006) was not found
in the value set 'DiagnosesSCT'
```

Das ist dieselbe Grenze, die ADR-002 seit Phase 0 benennt: Der Server
prüft, was er kennt. Ohne Terminologieserver lässt sich die Zugehörigkeit
eines SNOMED-Codes zu einem ValueSet weder bestätigen noch widerlegen.

## Was die Messung sonst noch ergeben hat

**Das Basismodul deckt drei unserer fünf Ressourcentypen ab** — Patient,
Encounter und Condition. Für Observation und MedicationStatement gibt es
im Basismodul keine Profile; sie gehören zu eigenen Modulen (Vitalparameter
beziehungsweise Medikation), also weiteren Paketen und weiterem Aufwand.

**Viele Pflichtangaben der Profile sind bedingt.** Die Profildefinition
listet Dutzende Elemente mit `min: 1`, etwa `Patient.address.city`. Sie
greifen aber nur, *wenn* das übergeordnete Element vorhanden ist — eine
Adresse braucht eine Stadt, ein Patient braucht keine Adresse. Die
tatsächlich bindende Menge ist erheblich kleiner als die Liste vermuten
lässt, und nur die Messung zeigt das.

## Was das für eine Entscheidung bedeutet

**Dafür:**

* Die Lücke ist klein: fünf additive Felder für drei Ressourcentypen.
* Alle fünf sind Angaben, die der **Code** setzt — kein Modellwissen, keine
  neuen Codes an unsicherer Quelle. Das passt zu ADR-001.
* Deutsche Lokalisierung ist laut PRD der zweite Differenzierer des
  Produkts. ISiK ist die Stelle, an der aus „deutsch lokalisiert" ein
  belegbarer Anspruch würde.

**Dagegen:**

* **Die Nachfrage ist nicht belegt.** Das Gate der Phase 3 verlangt sie
  ausdrücklich, und diese Sondierung hat sie nicht gemessen.
* **Es verlangt mehr als Felder.** `isik-con1` erzwingt, dass jeder
  Patient mit kodierter Diagnose einen Kontakt hat — eine Zusage über die
  Erzeugung, nicht über eine Vorlage.
* **Es ändert wieder jedes Bundle.** Wie schon beim HTEST-Label melden
  bestehende Aufzeichnungen danach `ABWEICHUNG`.
* **Vollständige Konformität ist ohne Terminologieserver nicht
  nachweisbar** — die zwei verbleibenden Befunde bleiben offen, solange
  keine SNOMED-Terminologie vorliegt. Ein Versprechen „ISiK-konform" wäre
  damit größer als der Nachweis.
* Die CI müsste zwei Pakete laden (rund 300 KB, wenige Sekunden) und einen
  zweiten Profilserver betreiben.
* Observation und MedicationStatement blieben zunächst außen vor.

## Offene Frage an die Entscheidung

Ein **Profilmodus** (`--profil isik`) wäre die vorsichtige Form: Er ließe
die heutige Ausgabe unangetastet und ergänzte die fünf Felder nur auf
Wunsch. Das vermeidet die erneute Änderung aller Bundles, kostet aber einen
zweiten Ausgabepfad, der mitgepflegt werden muss.

Die Alternative — die Felder immer zu setzen — wäre einfacher und
konsequenter, denn keines davon schadet außerhalb von ISiK. Sie ändert
dafür wieder jedes Bundle.

Beides ist vertretbar. Entschieden ist nichts.
