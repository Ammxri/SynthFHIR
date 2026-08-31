# ADR-010: Die Weboberfläche gibt heraus, was das Programm kann

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-08-31 |
| **Phase** | 3 |
| **Betrifft** | Weboberfläche, `ndjson.py`, `generation.Ergebnis` |
| **Baut auf** | ADR-005 (NDJSON), ADR-006 (Reproduzierbarkeit), ADR-007 (weitere Ressourcentypen), ADR-009 (ISiK) |

---

## 1. Kontext

Vier Entscheidungen hatten dieselbe offene Stelle hinterlassen, und in
dreien steht sie wörtlich als Nachtrag:

- ADR-005: „NDJSON-Download in der Weboberfläche (zustimmungspflichtig)."
- ADR-006: „Aufzeichnungen in der Weboberfläche (zustimmungspflichtig, weil UI)."
- ADR-007 hatte die Ressourcentypen von drei auf fünf erweitert — die
  Vorschau zeigte weiter zwei.

Der Auftrag verlangt Rückfrage vor jeder Scope-Erweiterung an der
Oberfläche. Die Zustimmung liegt jetzt vor, und damit schließt diese
Entscheidung alle drei Punkte.

Die Lage vorher war unangenehm genau: Wer über die Kommandozeile
arbeitete, bekam NDJSON, Aufzeichnungen und fünf Ressourcentypen. Wer die
Weboberfläche benutzte — also praktisch jeder, der das Produkt
ausprobiert — bekam ein Bundle und eine Vorschau, die zwei Fünftel des
Erzeugten zeigte. **Das Produkt war besser als sein einziger sichtbarer
Zugang.**

---

## 2. Entscheidung

Die Weboberfläche bietet drei Ausgabewege statt einem, und die Vorschau
zeigt alle fünf Ressourcentypen.

1. **NDJSON als ZIP-Archiv.** Je Ressourcentyp eine `.ndjson`-Datei, dazu
   `manifest.json` und ein `LIESMICH.txt`.
2. **Aufzeichnung als JSON**, abspielbar mit `synthfhir --wiedergeben`.
3. **Vorschau um Kontakte und Medikation erweitert**, und die
   Diagnosezeile nennt ihren Kontakt.

Dazu drei Änderungen unter der Oberfläche:

4. `ndjson.baue_dateien` ist der **gemeinsame Kern** beider Ausgabewege.
5. `generation.Ergebnis` merkt sich das Parameterobjekt, aus dem gebaut
   wurde — vorher konnte nur der stückweise Weg aufzeichnen.
6. Der Manifestrumpf steht in **einer** Funktion für Platte und Archiv.

---

## 3. Begründung

### Warum ein Archiv und keine einzelne Datei

Der bequeme Weg wäre gewesen, alle Ressourcen in **eine** `.ndjson` zu
schreiben. Ein Klick, eine Datei, kein Archiv.

Das widerspräche ADR-005 im Kern. Der Bulk-Data-Leitfaden schreibt vor,
dass jede Ausgabedatei Ressourcen **nur eines Typs** enthält. Eine
gemischte Datei wäre kein NDJSON-Export nach Leitfaden, sondern etwas,
das so aussieht — und der Empfänger merkte es erst beim Import.

Ein Browser lädt aber nur eine Datei. Also braucht es eine Hülle, und das
Archiv ist die Hülle, die die Aufteilung erhält, statt sie einzuebnen.

### Der gemeinsame Kern ist der eigentliche Punkt

Naheliegend wäre gewesen, im Webteil ein zweites Mal `json.dumps` zu
rufen und die Zeilen zusammenzufügen. Fünf Zeilen Code.

Dagegen spricht die Geschichte dieses Moduls. Die Regeln für eine
NDJSON-Datei sind: LF statt CRLF, kein BOM, kompakteste Form,
abschließender Zeilenvorschub, kein `NaN`, kein Zeilenumbruch im Inhalt.
**Jede einzelne dieser Regeln war schon einmal verletzt** — sie stehen im
Modulkopf, weil sie nachgemessen wurden, nicht weil sie naheliegen.

Eine zweite Abschrift hätte dieselben sechs Fehler wieder möglich
gemacht, an einer Stelle, wo sie schwerer auffallen: Ein CRLF in einer
heruntergeladenen Datei sieht in keiner Anzeige anders aus als ein LF.

Deshalb liefert `baue_dateien` die Bytes, und **beide** Wege benutzen
sie — der Dateiexport schreibt sie mit `write_bytes` auf Platte, das
Archiv legt sie als Eintrag ab. Ein Test vergleicht beide Ausgaben
byteweise.

Dasselbe Argument gilt für den Manifestrumpf. Dort waren einmal
`outputFormat` und `fileSize` eingesickert — Felder, die erst der
Continuous Build definiert und die veröffentlichte v3.0.0 nicht. Eine
zweite Abschrift für das Archiv wäre die Einladung gewesen, denselben
Fehler ein zweites Mal zu machen, an einer Stelle, die dann niemand mehr
mit der ersten vergleicht.

### Zwei bewusste Abweichungen im Archivmanifest

**`output[].url` trägt den Eintragsnamen, nicht den absoluten Pfad.** Der
Leitfaden sieht einen absoluten Pfad vor. Der wäre hier der Pfad *auf dem
Server* — für den Empfänger nutzlos und obendrein eine Auskunft über
fremde Verzeichnisse, die ihn nichts angeht. Innerhalb des Archivs ist
der Eintragsname die Adresse, die tatsächlich auflöst.

**Die Zeitstempel der Einträge sind fest.** ZIP schreibt je Eintrag eine
Uhrzeit. Nähme man die Systemuhr, unterschieden sich zwei Archive aus
denselben Daten in jedem Byte des Zeitfelds, und ein Prüfsummenvergleich
wäre wertlos — gegen die Zusage aus ADR-006. Gesetzt wird deshalb die
`transactionTime` des Manifests.

### Warum die Aufzeichnung nicht an `fertig` hängt

Die beiden Datenausgaben sind gesperrt, solange die Prüfung nicht
durchgeht (US-2 AC2). Die Aufzeichnung nicht, und das ist Absicht.

Eine Aufzeichnung ist die **Eingabe** eines Laufs, nicht sein Ergebnis.
Ihr stärkster Nutzen liegt gerade dort, wo etwas schiefging: Man will den
Lauf wiederholen können, ohne dafür noch einmal das Modell zu fragen — im
Gratistarif ist jeder Aufruf gezählt. Eine Sperre bei `fertig == false`
nähme die Funktion genau in dem Fall weg, für den es sie gibt.

Die Zusage bleibt trotzdem sichtbar; der Hinweistext sagt jetzt
„Datenausgabe" statt „Download", weil er sonst mehr verspräche, als er
hält.

### Warum ein `LIESMICH.txt` ins Archiv gehört

Die Kennzeichnungspflicht (PRD Block 6) ist im Produkt an drei Stellen
erfüllt: im Seitenkopf, in `meta.security` jeder Ressource und im
Manifest. Wer ein Archiv entpackt, sieht die Seite nicht mehr, und
`manifest.json` liest kaum jemand.

Der Leitfaden regelt Archive nicht — es gibt hier also keine Vorgabe, der
eine zusätzliche Datei widerspräche.

### Ein einziger Endpunkt für drei Formen

Drei Routen hätten den Namensfilter dreimal gebraucht. Der Filter ist
kein Beiwerk: Ein Feld aus dem Formular bestimmt den Dateinamen, und ein
Filter, der `../../etc/passwd` zu `....etcpasswd` macht, ist keiner.

Stattdessen ein Endpunkt mit einer Ausgabeart. **Endung und MIME-Typ
setzt der Server**, nicht das Formular — sonst erklärte ein Feld aus der
Seite ein ZIP zu einer `.json`.

Ebenso wichtig: Der Bundle-Inhalt kommt aus dem Formular zurück, ist also
Eingabe des Nutzers und nicht Ausgabe des Servers. `baue_dateien` prüft
jeden `resourceType` gegen `TYP_MUSTER`. Beim Dateiexport verhinderte das
einen Pfadausbruch; im Archiv verhindert es einen Eintragsnamen wie
`../entwischt.ndjson`, den manche Entpacker genauso behandeln. Ein Test
schickt genau dieses Bundle und erwartet HTTP 400.

### Eine Null ist keine Erwartung

Der stückweise Weg gibt `baue_aus_parametern` die Sollmenge
`{"patienten": angefragt}` mit. Für den Einzellauf der Weboberfläche kann
`angefragt` null sein — dann hat das Modell keine Patientenzahl
zurückgelesen. `{"patienten": 0}` erzeugte eine Mengenbeanstandung gegen
eine Zahl, die nie jemand verlangt hat. Null heißt jetzt: keine
Erwartung. Beim Stückeln kann der Fall nicht auftreten, Teile sind
mindestens eins groß.

---

## 3a. Nachweis (2026-08-31)

Gegen den laufenden Server, nicht nur im Test:

| Ausgabeart | MIME-Typ | Dateiname | Ergebnis |
|---|---|---|---|
| `json` | `application/fhir+json` | `synthfhir-bundle.json` | 12.901 Bytes |
| `ndjson` | `application/zip` | `synthfhir-ndjson.zip` | 3.314 Bytes, ZIP-Kennung am Dateianfang |
| `aufzeichnung` | `application/json` | `synthfhir-aufzeichnung.json` | 2.470 Bytes |

Die heruntergeladene Aufzeichnung, abgespielt mit der echten
Kommandozeile:

```
synthfhir --wiedergeben web-aufzeichnung.json
  identisch zum aufgezeichneten Lauf (Prüfsumme stimmt)
  Patienten: 2 von 2 · Integrität: ok (0 kaputte Referenzen)
  Token: 0 ein / 0 aus
```

Und die Kernzusage, quer über beide Wege: Die fünf `.ndjson`-Dateien aus
dem Kommandozeilen-Export und die fünf Einträge im Web-Archiv sind
**byteweise gleich** (5 von 5).

Vollständige Testreihe: **508 grün** gegen beide Server (vorher 492),
davon 16 neue. Die ISiK-Messung bleibt bei 0 Fehlern.

---

## 4. Konsequenzen

### Positiv

- Die Weboberfläche kann, was das Programm kann. Der Abstand zwischen
  Kommandozeile und Web ist geschlossen.
- Die NDJSON-Regeln und der Manifestrumpf stehen je an einer Stelle. Eine
  Abweichung zwischen den Ausgabewegen ist nicht mehr möglich, ohne dass
  ein Test rot wird.
- Ein Weblauf ist reproduzierbar. Vorher war ADR-006 auf die
  Kommandozeile beschränkt.
- Der Fußtext nennt wieder alle erzeugten Ressourcentypen; ein Test zählt
  ihn gegen die tatsächlich gebauten Typen, nicht gegen eine Liste.

### Negativ, bewusst in Kauf genommen

- **Die Seite wird größer.** Die Aufzeichnung reist als zweites
  verstecktes Feld mit. Bei 25 Patienten sind das einige Kilobyte — die
  drei Knöpfe teilen sich aber ein Formular, das Bundle reist also
  weiterhin einmal statt dreimal.
- **Das Archiv entsteht im Arbeitsspeicher.** Bei 25 Patienten
  unbedenklich; für die großen Kohorten aus ADR-004 bliebe der
  Dateiexport der richtige Weg. Die Oberfläche ist ohnehin auf 25
  begrenzt.
- **`Ergebnis` trägt ein Feld mehr.** Das Parameterobjekt ist die rohe
  Modellausgabe; wer `Ergebnis` protokolliert, protokolliert sie mit.
- **Der Testdatenhinweis liegt jetzt an vier Stellen.** Bewusst: Er soll
  überleben, dass eine davon wegfällt.

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| Eine einzelne, zusammengehängte `.ndjson` | Widerspricht ADR-005 und dem Leitfaden im Kern: eine Datei je Ressourcentyp. Sähe aus wie ein Export und wäre keiner. |
| NDJSON im Webteil neu serialisieren | Sechs Regeln, jede schon einmal verletzt. Eine zweite Abschrift macht sie alle wieder möglich — dort, wo sie niemand sieht. |
| Drei Endpunkte statt eines | Der Namensfilter dreimal. Genau die Stelle, an der eine der drei Kopien irgendwann nachhinkt. |
| `tar.gz` statt ZIP | Unter Windows — der Zielplattform vieler Nutzer — ohne Zusatzwerkzeug nicht zu öffnen. |
| Zustand serverseitig halten und per Kennung ausliefern | Der MVP speichert nichts. Das ist keine Bequemlichkeit, sondern der Grund, warum die Demo keine Nutzerdaten aufbewahrt. |
| Aufzeichnung bei `fertig == false` sperren | Nähme die Funktion genau im Fall weg, für den es sie gibt. |
| Ein zweites Aufzeichnungsformat für Einzelläufe | Ein Lauf in einem Stück ist ein Lauf mit einem Teil. Zwei Formate hießen: zwei Wiedergabewege, und eine Web-Aufzeichnung liefe auf der Kommandozeile nicht. |
| Dateiendung aus dem Formular übernehmen | Dann erklärte ein Feld aus der Seite ein ZIP zu einer `.json`. |

---

## 6. Offen

- Ein `LIESMICH.txt` auch beim Dateiexport auf Platte. Dort liegt das
  Manifest daneben, der Fall ist also schwächer — aber nicht null.
- Große Kohorten in der Weboberfläche bleiben ausgeschlossen (ADR-004).
  Der Archivweg im Arbeitsspeicher wäre dafür ohnehin der falsche.
