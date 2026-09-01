# Hinweise zu fremden Inhalten

Der **Code** dieses Projekts steht unter der MIT-Lizenz (siehe `LICENSE`).

Der **Katalog** in `src/synthfhir/domain/codes.py` führt daneben Codes und
Bezeichnungen aus fremden Terminologien. Für sie gilt die MIT-Lizenz
nicht — sie gehören ihren jeweiligen Herausgebern und stehen unter deren
Bedingungen. Diese Datei nennt sie.

Warum das hier steht: Eine pauschale MIT-Angabe über das ganze
Repository erlaubte Dritten ausdrücklich, die Inhalte zu verändern und
weiterzulizenzieren. Das steht keinem der drei Herausgeber unten zu, und
es steht auch dem Betreiber dieses Projekts nicht zu, es zu gewähren.

---

## SNOMED CT

`src/synthfhir/domain/codes.py` führt 25 SNOMED-CT-Bezeichner mit ihren
englischen Bezeichnungen (`display`).

Diese Angaben stammen aus dem **SNOMED CT Global Patient Set** (GPS).
© SNOMED International, lizenziert unter
[Creative Commons Attribution-NoDerivatives 4.0 International](https://creativecommons.org/licenses/by-nd/4.0/)
(CC BY-ND 4.0). Das GPS umfasst seit dem 11.03.2026 den vollständigen
Inhalt der SNOMED-CT-International-Edition — Bezeichner, Fully Specified
Names, Preferred Terms und Aktiv-Kennzeichen — und ist weltweit
gebührenfrei nutzbar, ohne Affiliate-Lizenz.

<https://www.snomed.org/gps>

Die deutschen Texte im Feld `display_de` sind **keine** SNOMED-Inhalte,
sondern eigene Bezeichnungen dieses Projekts. Sie werden auch nicht als
`Coding.display` ausgegeben, sondern ausschließlich als
`CodeableConcept.text` — das Projekt behauptet also nirgends, eine
SNOMED-Description übersetzt zu haben.

**Für Anwender in Deutschland:** Wer SNOMED CT über das GPS hinaus nutzt
— etwa die vollständige Edition mit ihren Hierarchien —, braucht eine
Affiliate-Lizenz. Sie ist in Deutschland gebührenfrei und wird vom BfArM
als National Release Center vergeben, auch an Einzelpersonen.
<https://www.bfarm.de/DE/Kodiersysteme/Terminologien/SNOMED-CT/Lizenz/_node.html>

Dieses Projekt liefert **keine** SNOMED-Release-Dateien mit und lädt
keine in seine Container.

## LOINC

`src/synthfhir/domain/codes.py` führt 25 LOINC-Codes mit ihren
Bezeichnungen.

> This material contains content from LOINC (<https://loinc.org>). LOINC is
> copyright © 1995-2026, Regenstrief Institute, Inc. and the Logical
> Observation Identifiers Names and Codes (LOINC) Committee and is
> available at no cost under the license at
> <https://loinc.org/license/>. LOINC® is a registered United States
> trademark of Regenstrief Institute, Inc.

Die deutschen Texte (`display_de`) und die Einheitenangaben sind
Ergänzungen dieses Projekts; die LOINC-Felder selbst sind unverändert.

## ICD-10-GM

`src/synthfhir/domain/codes.py` führt ICD-10-GM-Schlüssel der Fassung
**2026** mit ihren Bezeichnungen.

Die amtlichen Ausgaben der ICD-10-GM sind ein *anderes amtliches Werk*
im Sinne des § 5 Abs. 2 UrhG. Die Nutzungsrechte bestehen unter
Beachtung des **Änderungsverbots** (§ 62 UrhG) und des **Gebots der
Quellenangabe** (§ 63 UrhG).

Quelle: Bundesinstitut für Arzneimittel und Medizinprodukte (BfArM),
ICD-10-GM Version 2026, Systematisches Verzeichnis.
<https://www.bfarm.de/DE/Kodiersysteme/Klassifikationen/ICD/ICD-10-GM/_node.html>

**Anmerkung zur Genauigkeit:** Einige Einträge führen als
`icd10gm_display` eine aus Kategorie- und Endstellentext zusammengezogene
Bezeichnung, etwa „Asthma bronchiale, nicht näher bezeichnet: Ohne Angabe
zu Kontrollstatus und Schweregrad". Die Textteile selbst sind unverändert;
zusammengeführt wurden sie zur besseren Lesbarkeit.

## ATC

`src/synthfhir/domain/codes.py` führt 19 ATC-Codes.

Quelle: WHO Collaborating Centre for Drug Statistics Methodology,
ATC/DDD Index. <https://atcddd.fhi.no/atc_ddd_index/>

## ISiK-Profile

Die Messung gegen das ISiK-Basismodul (`synthfhir-profil`) lädt die
Profile zur Laufzeit aus dem FHIR-Paketregister und holt die
ValueSet-Definition beim Messen aus dem Quellrepository der gematik.
Es wird **nichts** davon in diesem Repository mitgeliefert.

---

## Was das für Nutzer dieses Projekts heißt

Die **erzeugten Testdaten** sind Daten, keine Terminologie: Ein Bundle,
das SNOMED- oder LOINC-Codes trägt, ist eine Anwendung dieser
Terminologien und unproblematisch — so, wie ein Arztbrief mit einem
ICD-Schlüssel keine Weitergabe der ICD ist.

Wer den **Katalog selbst** übernimmt, weiterverbreitet oder verändert,
handelt dagegen mit kuratierter Terminologie und ist an die Bedingungen
oben gebunden — nicht an die MIT-Lizenz.
