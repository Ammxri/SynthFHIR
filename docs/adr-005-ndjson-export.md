# ADR-005: NDJSON als eine Datei je Ressourcentyp, nicht als ein Strom

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-08-29 |
| **Phase** | 2 (v1.x), PRD-Punkt „Bulk-Export (NDJSON)" |
| **Betrifft** | Ausgabeformat für den Import in Fremdsysteme |
| **Baut auf** | ADR-004 (große Kohorten), ADR-002 (Validierungsarchitektur) |

---

## 1. Kontext

Nach ADR-004 entstehen Kohorten in dreistelliger Größe. Das Bundle als
einzige Ausgabe wird damit zum Engpass: Es ist zum Ansehen gut und zum
Laden schlecht. Wer 200 Patienten in ein System bringen will, muss es
selbst zerlegen — und trifft dabei genau die Fehler, die dieses Projekt
sonst vermeidet.

Das PRD führt „Bulk-Export (NDJSON)" unter Phase 2 als *Should*. Die
Notwendigkeit ist damit gesetzt; zu entscheiden ist die **Form**.

---

## 2. Entscheidung

**Der Export schreibt ein Verzeichnis: eine NDJSON-Datei je Ressourcentyp,
dazu ein `manifest.json` in der Form der Bulk-Data-Abschlussantwort.**
Nicht einen einzelnen Strom in eine Datei.

Fünf Festlegungen im Einzelnen:

1. **Eine Datei je Typ.** Der Bulk-Data-Leitfaden (v3.0.0 STU 3) verlangt
   ausdrücklich, dass eine Ausgabedatei Ressourcen nur eines Typs enthält.
2. **LF als Zeilenende, kein BOM, kompakte Serialisierung**, jede Zeile mit
   Zeilenvorschub abgeschlossen — auch die letzte.
3. **Ein Manifest** mit `transactionTime`, `requiresAccessToken`,
   `outputFormat` und `output[]` aus `type`, `url`, `count`, `fileSize`.
4. **Referenzierte Typen zuerst** im Manifest, abgeleitet aus den
   tatsächlichen Verweisen.
5. **Ein belegtes Zielverzeichnis wird verweigert**, solange nicht
   ausdrücklich überschrieben wird.

---

## 3. Begründung

### Warum nicht ein Strom in eine Datei?

Das wäre die kleinere Änderung gewesen: `-o kohorte.ndjson` neben
`-o kohorte.json`, fertig. Dagegen steht der Leitfaden — *„each output file
SHALL contain resources of only one type"*. Eine gemischte Datei ist kein
Bulk-Data-NDJSON, sondern nur zeilenweises JSON. Da der Zweck des Formats
gerade der Import in fremde Systeme ist, wäre eine hausgemachte Variante
sinnlos.

### Warum LF, obwohl die FHIR-Kernseite CRLF sagt?

**Die Quellen widersprechen sich.** <https://hl7.org/fhir/R4/nd-json.html>
schreibt wörtlich, Ressourcen seien *„separated by a newline pair
(characters 13 and 10)"* — also CRLF. Der Bulk-Data-Leitfaden verweist
dagegen auf die NDJSON-Spezifikation, und deren §3.1 kennt den
Zeilenvorschub als **Abschluss** jeder Zeile, nicht als Trenner dazwischen;
ein vorangehendes CR ist erlaubt, aber nicht nötig.

Entschieden wurde für LF, in dieser Reihenfolge:

1. Für diesen Anwendungsfall ist der Bulk-Data-Leitfaden die einschlägige
   und **veröffentlichte** Spezifikation (v3.0.0 STU 3); die Kernseite
   steht auf *Maturity Level 2, Standards Status: Draft*.
2. Die NDJSON-Spezifikation verlangt von Parsern ohnehin, **beides** zu
   akzeptieren (§3.2).
3. Die Werkzeuge, die NDJSON tatsächlich einlesen, erwarten LF.

Beim **Lesen** ist `lies_ndjson` deshalb nachsichtig und verkraftet CRLF.
Strenge gehört an die Stelle, an der wir etwas erzeugen, nicht an die, an
der wir etwas Fremdes prüfen.

### Warum das überhaupt eine Entscheidung ist

Weil Python im Textmodus unter Windows still CRLF schreibt. Nachgemessen:
`Path.write_text` — womit dieses Projekt seine Bundles schreibt — erzeugt
hier CRLF. Bei einem Bundle ist das folgenlos, bei einem zeilenweisen
Format nicht. Der Fehler wäre nicht aufgefallen: Die Datei sieht im Editor
richtig aus, und tolerante Leser überleben ihn.

Dasselbe gilt für die BOM. RFC 8259 §8.1 verbietet sie ausdrücklich, und
die Windows-Werkzeugkette schreibt sie gern mit. Sie landet vor der ersten
öffnenden Klammer und lässt **genau die erste Zeile** scheitern — ein
Fehlerbild, das wie ein kaputter Datensatz aussieht, nicht wie ein
Kodierungsfehler.

### Warum ein Manifest, obwohl wir kein Bulk-Data-Server sind

Weil der Leitfaden Dateinamen **nicht** vorschreibt. Der Ressourcentyp
steht normativ im Feld `type` des Manifests; ein Empfänger darf ihn nicht
aus dem Dateinamen ableiten. `Patient.ndjson` ist Konvention — dieselbe,
die der SMART-Referenzserver benutzt — aber verlassen kann sich darauf
niemand. Ohne Manifest wäre der Export formal typlos.

Es ist ausdrücklich **keine Protokollzusage**: Es gibt keine
`$export`-Operation, keinen Kick-off, kein Polling, keine
Zugriffsverwaltung. Das Manifest ist ein Beipackzettel in bekannter Form.

### Warum die Sperre gegen ein belegtes Verzeichnis

Ein zweiter, kleinerer Lauf überschriebe `Patient.ndjson`, ließe aber
`Condition.ndjson` des ersten liegen. Der Empfänger lüde Diagnosen zu
Patienten, die es nicht mehr gibt — und nichts im Verzeichnis sagte, dass
die beiden Dateien nicht zusammengehören. Dieselbe Klasse von Fehler wie
die kollidierenden Kennungen aus ADR-004: strukturell einwandfrei,
inhaltlich falsch, lautlos.

Beim Überschreiben werden Reste deshalb entfernt und im Ergebnis benannt.
Dateien, die kein Empfänger mitlesen würde — eine `LIESMICH.md` etwa —
bleiben unangetastet.

---

## 3a. Nachweis (2026-08-29)

Die Kohorte aus ADR-004 (200 Patienten, 1020 Ressourcen) exportiert und in
einen **echten HAPI FHIR 4.0.1** geladen, streng in Manifest-Reihenfolge,
so wie ein Import-Werkzeug es täte.

| Prüfung | Ergebnis |
|---|---|
| Dateien | `Patient.ndjson` 200 · `Condition.ndjson` 220 · `Observation.ndjson` 600 |
| Größe | 508 KB gegenüber 1,03 MB als eingerücktes Bundle |
| Zeilenenden | 0 × CR, jede Datei endet auf LF |
| BOM | keine |
| Rücklesen | 1020 Ressourcen, byteweise identisch zum Bundle |
| Typreinheit | jede Datei enthält nur ihren Typ |
| Umlaute | erhalten, nicht als `\uXXXX` maskiert |
| **Import in HAPI** | **1020 Ressourcen in 55 s, 0 Fehler** |
| Verweise im Server | auflösbar — `pat-001` findet 1 Condition, 3 Observations |
| Bestand danach | 200 Patienten, 600 Observations |

Zusätzlich prüft ein Test in der Pflichtprüfkette (ADR-002), dass eine
**zurückgelesene** Zeile bei HAPI weiterhin valide ist. Die Byte-Tests
sehen das Format, nicht den Inhalt; ein Kodierungsschaden überstünde sie
alle.

---

## 4. Konsequenzen

### Positiv

- Die Ausgabe ist ohne Nacharbeit importierbar — nachgewiesen, nicht
  behauptet.
- Halb so groß wie das Bundle.
- Der Typ steht normativ im Manifest, nicht nur im Dateinamen.

### Negativ, bewusst in Kauf genommen

- **Ein Verzeichnis statt einer Datei.** Weitergeben heißt jetzt packen.
  Das ist der Preis der Spezifikationstreue.
- **Keine Aufteilung großer Dateien.** Der Leitfaden erlaubt mehrere
  Dateien je Typ (`<index>.<Typ>.ndjson`). Bei 508 KB für 200 Patienten
  ist das kein Problem; bei sechsstelligen Kohorten würde es eines.
- **Kein gzip.** Neu in v3.0.0 und für große Exporte vorgesehen. Nicht
  gebaut, weil es beim Schreiben auf Platte keinen Gewinn bringt, den ein
  nachgelagertes Packen nicht auch hätte.
- **Die Sortierung im Manifest ist keine Garantie.** Große Import-Werkzeuge
  verarbeiten die Dateien parallel und sichern keine Reihenfolge zu
  (Microsoft Bulk Import: *„this order is not guaranteed by distributed
  parallel import"*). Sie prüfen dafür meist auch keine referentielle
  Integrität. Die Sortierung hilft dem sequentiellen Lader und schadet dem
  parallelen nicht — mehr ist sie nicht.

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| Ein Strom `-o kohorte.ndjson` | Verstößt gegen *„each output file SHALL contain resources of only one type"*. Wäre zeilenweises JSON, kein Bulk-Data-NDJSON — und damit für den Zweck wertlos. |
| CRLF nach der FHIR-Kernseite | Die Seite ist *Draft, Maturity 2*; der Bulk-Data-Leitfaden ist für diesen Fall einschlägig und veröffentlicht. Parser müssen beides akzeptieren, also entscheidet die gelebte Praxis: LF. |
| Kein Manifest, Typ aus dem Dateinamen | Der Leitfaden schreibt Dateinamen nicht vor und erklärt `type` zum normativen Feld. Ein Empfänger, der den Namen parst, tut etwas, das die Spezifikation ihm untersagt. |
| Stillschweigend überschreiben | Reste eines früheren Laufs würden mitgeladen, ohne dass es irgendwo steht. |
| Zielverzeichnis vollständig leeren | Zu übergriffig: Der Export darf löschen, was er selbst erzeugt haben könnte, nicht was sonst dort liegt. |
| NDJSON auch in der Weboberfläche | UI-Änderungen sind laut Auftrag zustimmungspflichtig. Der `/export`-Endpunkt ist zudem fest auf `application/fhir+json` verdrahtet. Offen, nicht verworfen. |

---

## 6. Offen

- NDJSON-Download in der Weboberfläche (zustimmungspflichtig).
- Aufteilung großer Dateien nach dem Muster `<index>.<Typ>.ndjson`.
- gzip nach v3.0.0, falls Exporte je einmal groß genug werden.
