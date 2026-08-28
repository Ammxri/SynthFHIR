# ICD-10-GM-Schlüssel: Nachweis der Prüfung

> **Geprüft am 2026-08-28** gegen den amtlichen Katalog des BfArM,
> ICD-10-GM Version 2026.

Der Katalog führt **25 Diagnosen**, alle **25 mit ICD-10-GM-Schlüssel**.

## Ergebnis der Prüfung

| | |
|---|---|
| Schlüssel korrekt | 19 |
| **nicht kodierbar, korrigiert** | **2** |
| zuvor leer, jetzt gefüllt | 4 |

Die beiden Fehler waren `J45.9` (Asthma) und `B18.1` (Hepatitis B). Beide
sind in ICD-10-GM nur Kategorieüberschriften: Ohne fünfte Stelle sind sie
kein gültiger Schlüssel. Korrigiert zu `J45.99` und `B18.19`.

Bemerkenswert daran: **Keine Prüfung im Projekt hätte sie gefunden.** Der
Formattest akzeptiert `J45.9` als wohlgeformt, und HAPI kennt das
CodeSystem nicht. Nur der Abgleich mit der Primärquelle deckt so etwas auf.

## Warum das von Hand geschehen muss

Der CI-Test validiert jeden Katalogeintrag gegen HAPI FHIR. Das sichert
**UCUM-Einheiten, Struktur und Invarianten** ab — dort hat es in Phase 0
auch tatsächlich Fehler gefunden. Es sichert **Codes nicht** ab: Dem
Container fehlen die Terminologiepakete, ein unbekanntes CodeSystem ergibt
höchstens eine Warnung. Ein falsch abgetippter ICD-Schlüssel sieht für ihn
genauso aus wie ein richtiger.

Ein Formattest in `tests/test_domaene.py` fängt Tippfehler der Bauart
`E1190` statt `E11.90`. Mehr kann Automatik hier nicht leisten.

## Quelle

Amtlicher ICD-10-GM-Katalog des BfArM, frei einsehbar:
<https://klassifikationen.bfarm.de/icd-10-gm/kode-suche/htmlgm2026/>

Besonders zu prüfen ist die **fünfte Stelle**. ICD-10-GM verlangt sie an
vielen Stellen, wo ICD-10-WHO mit vier Zeichen auskommt — bei Diabetes
(E10–E14) und der Hypertonie (I10) etwa. Ein vierstelliger Schlüssel ist
dort nicht kodierbar.

## Geprüfte Schlüssel

| ICD-10-GM | Bezeichnung laut Katalog | SNOMED CT | deutscher Anzeigetext |
|---|---|---|---|
| `E11.90` | Diabetes mellitus, Typ 2, ohne Komplikationen, nicht als entgleist bezeichnet | `44054006` | Diabetes mellitus Typ 2 |
| `E10.90` | Diabetes mellitus, Typ 1, ohne Komplikationen, nicht als entgleist bezeichnet | `46635009` | Diabetes mellitus Typ 1 |
| `I10.90` | Essentielle Hypertonie, nicht näher bezeichnet, ohne Angabe einer hypertensiven Krise | `38341003` | Arterielle Hypertonie |
| `E78.0` | Reine Hypercholesterinämie | `13644009` | Hypercholesterinämie |
| `E66.99` | Adipositas, nicht näher bezeichnet: Grad oder Ausmaß der Adipositas nicht näher bezeichnet | `414916001` | Adipositas |
| `J45.99` | Asthma bronchiale, nicht näher bezeichnet: Ohne Angabe zu Kontrollstatus und Schweregrad | `195967001` | Asthma bronchiale |
| `J44.99` | Chronische obstruktive Lungenkrankheit, nicht näher bezeichnet: FEV1 nicht näher bezeichnet | `13645005` | COPD |
| `I50.9` | Herzinsuffizienz, nicht näher bezeichnet | `84114007` | Herzinsuffizienz |
| `I48.9` | Vorhofflimmern und Vorhofflattern, nicht näher bezeichnet | `49436004` | Vorhofflimmern |
| `I21.9` | Akuter Myokardinfarkt, nicht näher bezeichnet | `22298006` | Myokardinfarkt |
| `I25.9` | Chronische ischämische Herzkrankheit, nicht näher bezeichnet | `53741008` | Koronare Herzkrankheit |
| `I64` | Schlaganfall, nicht als Blutung oder Infarkt bezeichnet | `230690007` | Schlaganfall |
| `N18.9` | Chronische Nierenkrankheit, nicht näher bezeichnet | `709044004` | Chronische Nierenkrankheit |
| `E03.9` | Hypothyreose, nicht näher bezeichnet | `40930008` | Hypothyreose |
| `E05.9` | Hyperthyreose, nicht näher bezeichnet | `34486009` | Hyperthyreose |
| `M19.99` | Arthrose, nicht näher bezeichnet: Nicht näher bezeichnete Lokalisation | `396275006` | Arthrose |
| `M06.99` | Chronische Polyarthritis, nicht näher bezeichnet: Nicht näher bezeichnete Lokalisation | `69896004` | Rheumatoide Arthritis |
| `M81.99` | Osteoporose, nicht näher bezeichnet: Nicht näher bezeichnete Lokalisation | `64859006` | Osteoporose |
| `F32.9` | Depressive Episode, nicht näher bezeichnet | `35489007` | Depressive Episode |
| `F41.9` | Angststörung, nicht näher bezeichnet | `197480006` | Angststörung |
| `G35.9` | Multiple Sklerose, nicht näher bezeichnet | `24700007` | Multiple Sklerose |
| `B18.19` | Chronische Virushepatitis B ohne Delta-Virus, Phase nicht näher bezeichnet | `66071002` | Chronische Hepatitis B |
| `K21.9` | Gastroösophageale Refluxkrankheit ohne Ösophagitis | `235595009` | Refluxkrankheit |
| `C80.9` | Bösartige Neubildung, nicht näher bezeichnet | `363346000` | Bösartige Neubildung |
| `G47.31` | Obstruktives Schlafapnoe-Syndrom | `73430006` | Schlafapnoe-Syndrom |

## Wenn eine Diagnose hinzukommt

Ihr ICD-Schlüssel ist an der Primärquelle zu prüfen, bevor er in
`src/synthfhir/domain/codes.py` landet — besonders auf die fünfte Stelle.
Ist sie nicht zweifelsfrei bestimmbar, bleibt `icd10gm=None`: Die Vorlage
baut dann gültiges FHIR mit SNOMED allein. Danach:

```bash
.venv/Scripts/python.exe -m pytest tests -q
```

Und diese Liste neu erzeugen, damit sie zum Katalog passt.

