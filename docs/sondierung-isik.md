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

## Aus der Sondierung ist eine Messung geworden

Die Zahlen oben waren einmalig und von Hand erhoben. Seit dem 2026-08-30
sind sie wiederholbar:

```bash
docker compose -f docs/belege/docker-compose.isik.yml up -d
synthfhir-profil -o docs/belege/isik-profilbericht.json
```

Gemessen wird eine **feste Referenzkohorte** (`referenzkohorte.py`) — drei
Patienten, ohne Modellaufruf, deterministisch. Das ist die Voraussetzung
für einen Vergleich: Eine vom Modell erzeugte Kohorte ändert sich bei jedem
Lauf, und dann misst man das Modell statt der Profilkonformität.

Der dritte Patient liefert **keine Begegnung** — absichtlich. Er ist der
Fall, den die erste Messung übersehen hat. Ein Messaufbau, der nur den Fall
enthält, der ohnehin durchgeht, misst nichts.

> **Nachtrag vom 2026-09-01.** Hier stand weiter: „…und der einzige, an dem
> `isik-con1` greift." Das trifft seit ADR-009 nicht mehr zu. Der Bauweg
> ergänzt den Kontakt inzwischen selbst, und damit enthält der Messaufbau
> **keinen** Fall mehr, an dem die Zwangsbedingung greifen könnte — also
> genau den Zustand, vor dem der Satz davor warnt. Dieses Dokument
> beschrieb sich selbst.
>
> Der Patient bleibt, aber in anderer Rolle: An ihm zeigt sich, dass der
> Code die strukturelle Zusage herstellt. Dass der Validator den Verstoss
> überhaupt noch **fände**, beweist er nicht — eine Kohorte, in der jeder
> Fall durchgeht, kann das grundsätzlich nicht.
>
> Diesen Beweis führt seit dem 2026-09-01 eine Negativkontrolle
> (`test_isik_con1_wird_ueberhaupt_noch_gefunden`): Sie entfernt den
> Kontakt aus einer gebauten Diagnose und prüft, dass der Befund dann
> auftritt — 1 Fehler statt 0, bei einem Feld Unterschied. Gemessen gegen
> einen Server ohne die ISiK-Pakete wird sie rot, während der blosse
> Abwesenheitstest daneben grün bliebe: Dort meldeten 11 Fehler, dass gar
> nichts geprüft wurde, und „`isik-con1` kommt nicht vor" traf trotzdem zu.

### Stand am 2026-08-30, vor ADR-009

`de.gematik.isik-basismodul` 4.0.3, HAPI FHIR 4.0.1, **kein**
Terminologieserver:

| Typ | geprüft | Fehler | ungeprüft | Warnungen |
|---|---|---|---|---|
| Patient | 3 | 3 | 0 | 15 |
| Encounter | 3 | 9 | 0 | 3 |
| Condition | 4 | 13 | 8 | 8 |
| **Summe** | **10** | **25** | **8** | **26** |

Observation und MedicationStatement sind nicht geprüft — das Basismodul
kennt für sie kein Profil. Der Bericht weist das aus, statt sie
stillschweigend zu überspringen.

### Stand am 2026-09-01

Die Überschrift darüber lautete bis zum 2026-09-01 schlicht „Stand am
2026-08-30" — und meinte damit den älteren von **zwei Ständen desselben
Tages**, ohne es zu sagen. ADR-009 hat die 25 Fehler noch am selben Tag
geschlossen, und der Beleg `docs/belege/isik-profilbericht.json` vom
2026-08-30, 21:37 Uhr wies bereits 0 aus. Dieses Dokument hat es nicht
mitgeteilt, und das README schickte die Leser für die Einordnung hierher.
Sechs von acht Zahlen der Tabelle waren zu diesem Zeitpunkt überholt.

Gemessen gegen denselben Aufbau, mit dem am 2026-09-01 berichtigten
Messcode:

| Typ | geprüft | Fehler | ungeprüft | Warnungen | Hinweise |
|---|---|---|---|---|---|
| Patient | 3 | 0 | 0 | 3 | 0 |
| Encounter | 4 | 0 | 0 | 8 | 0 |
| Condition | 4 | 0 | 8 | 4 | 4 |
| **Summe** | **11** | **0** | **8** | **15** | **4** |

Drei Unterschiede, und sie gehören auseinandergehalten — **einer betrifft
die Ausgabe, zwei die Messung**:

* **Encounter 3 → 4** *(Ausgabe)*. Der vierte ist der Kontakt, den der
  Code seit ADR-009 für den Patienten ohne Begegnung ergänzt. Hier hat
  sich wirklich etwas an den erzeugten Daten geändert.
* **Warnungen 26 → 15 + 4 Hinweise** *(Messung)*. Die Spalte „Warnungen"
  war als „alles, was nicht Fehler und nicht ungeprüft ist" definiert und
  enthielt damit auch Befunde vom Schweregrad `information`. An der
  Ausgabe hat sich nichts geändert, nur an der Zählung.
* **Die Fehlerspalte ist belastbarer geworden** *(Messung)*. Siehe den
  Nachtrag im nächsten Abschnitt: Der Zähler dahinter konnte zu niedrig
  zählen. Dass er es hier nicht tat, war Zufall.

> **Zum Zuschnitt dieser Tabelle.** Sie misst gegen **ein** Paket, das
> ISiK-Basismodul, und deckt damit drei der fünf Ressourcentypen ab —
> Observation und MedicationStatement waren zu diesem Zeitpunkt
> unprofiliert, so wie es der Abschnitt „Was die Messung sonst noch
> ergeben hat" beschreibt.
>
> Seit ADR-014 lädt der Messaufbau drei Module (Basismodul,
> Vitalparameter, Medikation), und derselbe Befehl misst dann 14 statt 11
> Ressourcen: **0 Fehler, 13 ungeprüft, 19 Warnungen, 14 Hinweise.** Die
> Zahl der ungeprüften Befunde steigt, weil mehr geprüft wird — nicht,
> weil etwas schlechter geworden wäre. Und sie ist seit ADR-013 auflösbar:
> Der Referenzvalidator gegen einen Terminologieserver meldet für dieselbe
> Kohorte 14 geprüft, 0 Fehler und **nichts ungeprüft**.
>
> Diese Tabelle bleibt trotzdem stehen. Sie ist der Stand, auf den sich
> die Abwägung dieses Dokuments bezieht, und ein Stand ohne sein Datum und
> seinen Zuschnitt ist keiner — das war der Fehler, den der Abschnitt
> darüber beschreibt.

### Warum vier Spalten und nicht zwei

`ungeprüft` heißt: **Der Validator konnte es nicht entscheiden.** Nicht,
dass es richtig ist.

Die acht ungeprüften Befunde sind allesamt dieselbe Sache: Das ISiK-Profil
bindet `Condition.code` an ein SNOMED-ValueSet mit `is-a`-Filtern, und ohne
SNOMED-Terminologie lässt sich die Zugehörigkeit weder bestätigen noch
widerlegen. Der Validator sagt das selbst — trägt den Befund aber als
`error`.

Solche Befunde als Fehler zu zählen macht das Ergebnis schlechter, als es
ist. Sie zu verschweigen macht es besser. Beides wäre Schönfärberei mit
Zahlen. Die Einstufungsregel ist deshalb scharf: Ein „nicht im ValueSet
enthalten" gilt nur dann als ungeprüft, wenn der Validator **in demselben
Lauf** erklärt hat, dass er genau dieses ValueSet nicht auflösen kann.
Ohne diese Klage bleibt es ein Fehler — sonst liesse sich jede
Bindungsverletzung wegdeuten.

> **Nachtrag vom 2026-09-01.** Die Regel stand hier scharf. Der Code hielt
> sie nicht.
>
> Fand er zu einer Auflösungsklage keinen ValueSet-Namen, trug er einen
> Platzhalter `"*"` ein — und danach galt **jeder** Befund des Laufs mit
> den Worten „value set" als ungeprüft, auch eine echte
> Bindungsverletzung gegen ein ValueSet, das der Server mühelos auflöst.
> Ausgelöst hätte das schon eine Meldung wie „Unknown code system …", und
> genau die ist für ICD-10-GM und ATC der dokumentierte Normalfall. Dazu
> fing die Namenserkennung bei der kanonischen Klage „Unable to expand
> ValueSet: cannot apply filters …" nicht den Namen, sondern das Wort
> `cannot`: Der Abgleich „genau dieses ValueSet" verglich einen Mülltoken
> und konnte per Namen nie zutreffen.
>
> **Die Zahlen dieser Seite waren davon nicht betroffen** — und das ist
> Zufall, kein Verdienst. HAPI wiederholt die Expansionsklage wörtlich im
> angehängten `error message = …`, sodass die acht Befunde schon an der
> ersten Regel hängenbleiben und den Platzhalter nie brauchten. Hätte HAPI
> diese Verschachtelung geändert, wäre der Bericht mitgewandert, ohne dass
> es jemand bemerkt hätte.
>
> Ein dritter Fall stand hier nie: Antwortete der Server auf `$validate`
> mit etwas anderem als einem `OperationOutcome`, zählte der Code null
> Befunde, und die Ressource galt als geprüft, fehlerfrei und konform —
> der HTTP-Status wurde nie angesehen. Und kannte der Server das Profil
> nicht, meldete er das als gewöhnlichen `error`, ununterscheidbar von
> einem Datenfehler; eine Messung gegen den falschen Server las sich als
> Bericht über schlechte Daten.
>
> Alles drei ist am 2026-09-01 berichtigt. Wer nicht sagen kann,
> **welches** ValueSet unauflösbar war, kann nicht behaupten, es sei genau
> dieses gewesen; und wo nichts validiert wurde, wird jetzt abgebrochen
> statt gezählt.

### Der Satz, der daraus folgt

Der Stand **vor** ADR-009:

> Gegen `de.gematik.isik-basismodul 4.0.3`, HAPI FHIR 4.0.1, ohne
> Terminologieserver, Stand 2026-08-30: Patient 3 Fehler, Encounter 9,
> Condition 13 Fehler und 8 ungeprüfte Befunde, über eine Referenzkohorte
> von 10 profilierten Ressourcen. Observation und MedicationStatement sind
> im Basismodul nicht profiliert.

Das ist ein Satz, den man nicht zurücknehmen muss — er trägt sein Datum.
Zurückzunehmen war nur, ihn ohne dieses Datum stehen zu lassen, während er
längst überholt war. Ein Satz, den man nicht zurücknehmen muss, wird
dadurch nicht zu einem, den man nicht fortschreiben muss.

Der Stand seit dem 2026-09-01:

> Gegen `de.gematik.isik-basismodul 4.0.3`, HAPI FHIR 4.0.1, ohne
> Terminologieserver, Stand 2026-09-01: 0 Fehler und 8 ungeprüfte Befunde
> über eine Referenzkohorte von 11 profilierten Ressourcen, dazu 15
> Warnungen und 4 Hinweise. Observation und MedicationStatement sind im
> Basismodul nicht profiliert.

Und die Fussnote, die dazugehört, weil sie sonst niemand mitliest: „0
Fehler" heisst genauer, dass `bewerte()` aus dem, was
`pruefe_gegen_profile` als Befunde erkannt hat, keinen der Fehlerspalte
zugeordnet hat. Das ist eine Aussage über die Daten **und** über den
Messcode. Seit dem 2026-09-01 bricht dieser Code ab, statt zu zählen, wenn
der Server nichts validiert hat oder das Profil nicht kennt — vorher hätte
er in beiden Fällen eine Zahl geliefert.

## Offene Frage an die Entscheidung

Ein **Profilmodus** (`--profil isik`) wäre die vorsichtige Form: Er ließe
die heutige Ausgabe unangetastet und ergänzte die fünf Felder nur auf
Wunsch. Das vermeidet die erneute Änderung aller Bundles, kostet aber einen
zweiten Ausgabepfad, der mitgepflegt werden muss.

Die Alternative — die Felder immer zu setzen — wäre einfacher und
konsequenter, denn keines davon schadet außerhalb von ISiK. Sie ändert
dafür wieder jedes Bundle.

Beides ist vertretbar. Entschieden ist nichts.
