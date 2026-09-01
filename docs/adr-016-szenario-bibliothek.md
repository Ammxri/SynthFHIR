# ADR-016: Die Szenario-Bibliothek — Vorlagen statt Modellaufrufe

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-09-01 |
| **Phase** | 3 (Vision) |
| **Betrifft** | `szenarien.py` (neu), `generation.py`, `kohorte.py`, `cli.py`, `web/api.py`, `web/oberflaeche.py` |
| **Baut auf** | ADR-006 (Aufzeichnung), ADR-009, ADR-011, ADR-012, ADR-014 |

---

## 1. Kontext

Das PRD führt „Teilbare Kohorten-Vorlagen" unter *Could* (Zeile 143). Der
Anlass, sie jetzt zu bauen, kam aber nicht aus dieser Zeile, sondern aus
einer Rechnung.

### Was eine Vorführung heute kostet

Die Weboberfläche bot drei Beispieltexte an. Wer einen las und abtippte,
zahlte danach einen Modellaufruf — bei einem Gratiskontingent, das für
**rund eine Anfrage je Minute für alle Besucher zusammen** reicht
(ADR-011). Der erste Besucher, der etwas ausprobiert, nimmt dem zweiten
den Platz weg.

Für eine Seite, deren Zweck das Vorführen ist, ist das die falsche
Reihenfolge: Der teuerste Weg war der einzige, der etwas zeigte.

### Was es nicht ist

Eine **Aufzeichnung** (ADR-006) läuft ebenfalls ohne Modell. Sie ist
trotzdem etwas anderes, und der Unterschied ist die Zusage:

| | Aufzeichnung | Szenario |
|---|---|---|
| verspricht | *dasselbe Ergebnis wie damals* | *eine Diabetes-Kohorte* |
| trägt Prüfsummen | ja, zwei | nein |
| Katalog ändert sich | meldet `ABWEICHUNG` | liefert die **neue** Ausgabe |
| Herkunft | ein gelaufener Modelllauf | von Hand kuratiert |

Eine Prüfsumme im Szenario wäre kein Schutz, sondern Dauerlärm: Nach
ADR-015 bekam jeder Laborwert eine SNOMED-Kodierung dazu — die *bessere*
Ausgabe. Eine Vorlage soll die liefern, nicht die alte melden.

---

## 2. Entscheidung

**Fünf kuratierte Kohortenvorlagen im Code, ohne Prüfsummen, über
dieselbe Prüfkette wie ein Modelllauf — erreichbar über Kommandozeile,
Weboberfläche und API, überall ohne Schlüssel und ohne Kontingent.**

1. `szenarien.py` hält `Szenario` (Name, Titel, Beschreibung, `zeigt`,
   Parameter) und fünf eingebaute Vorlagen.
2. Gebaut wird über `baue_und_pruefe` — herausgelöst aus `generiere`,
   damit Szenario- und Modelllauf **eine** Kette teilen.
3. `Ergebnis.szenario` und `Kohortenergebnis.szenario` tragen den Namen —
   **auch in `to_dict()`**, damit nicht nur stderr es sagt. Ein
   Vorlagenlauf ist damit von einem Modelllauf unterscheidbar.
4. Eigene Vorlagen kommen als JSON-Datei dazu (`--szenario meins.json`).
5. Keine Prüfsummen. Die Absicherung leisten Tests, nicht Zahlen im
   Format.

---

## 3. Begründung

### Warum die Vorlagen im Code stehen und nicht in einer Datei

`.env.example` führte seit Phase 0 die Zeile
`SYNTHFHIR_SCENARIOS_FILE=scenarios.yaml`. **Nichts hat sie je gelesen.**
Sie ist ersatzlos entfallen.

Vorlagen im Code haben eine Eigenschaft, die eine Konfigurationsdatei
nicht hat: Sie laufen in der Testreihe mit. Die eingebauten fünf werden
bei jedem Lauf gegen den Katalog und gegen die Prüfkette gehalten. Eine
Datei am Rand veraltet still.

JSON und nicht YAML: PyYAML ist in diesem Projekt nur transitiv
vorhanden, und eine Vorlage soll keine Abhängigkeit rechtfertigen müssen.

### Warum diese fünf

Zwei von fünf zeigen ausdrücklich **unbequeme** Fälle. Glatte Kohorten
findet man überall; an den schiefen scheitern Importwerkzeuge.

| Szenario | zeigt |
|---|---|
| `diabetes-ambulanz` | alle fünf Ressourcentypen im Zusammenspiel |
| `blutdruck-kontrolle` | das Panel aus ADR-014 — eine Observation, zwei Komponenten |
| `labor-grundprofil` | viele Observations, UCUM-Einheiten, SNOMED-Doppelkodierung |
| `mehrere-kontakte` | mehrere Encounter je Patient (ADR-007: Kennungskollision) |
| `ohne-kontakt` | Diagnose ohne angegebenen Kontakt — `isik-con1` ergänzt ihn (ADR-009) |

### Was ein Szenario nicht darf

**Codes erfinden.** Nennt eine Vorlage einen Code, den der Katalog nicht
führt, ersetzt `baue_aus_parametern` ihn still durch einen anderen und
hinterlässt nur eine Beanstandung. Das Ergebnis wäre gültiges FHIR mit
falschem Inhalt, ausgeliefert unter einem Namen, der etwas anderes
verspricht — in einem Werkzeug, dessen Produkt die Verlässlichkeit ist,
die schlimmste Sorte Fehler.

`tests/test_szenarien.py` hält deshalb **jeden Code jedes Szenarios**
gegen den Katalog und jedes Szenario gegen die Prüfkette. Die Gefahr ist
nicht, dass eine Vorlage heute kaputt ist, sondern dass sie in einem Jahr
still falsch wird.

### Warum die API-Route keine Gleichzeitigkeitsgrenze hat

`/api/v1/wiedergeben` trägt vier Grenzen (ADR-012), weil die Last dort
aus dem Anfragekörper kommt und nach oben offen ist. Hier steht sie fest:
fünf Vorlagen, höchstens 17 Ressourcen. Gemessen **3,1 ms je Bau** und
**12,8 KiB größte Antwort**. Eine Bremse davor kostete den Zweck (die
Seite soll auch bei leerem Kontingent etwas zeigen) und brächte nichts.

### Warum `GET /szenario/{name}` und nicht ein Formular

Das Ergebnis hängt an nichts als dem Namen, ist beliebig oft wiederholbar
und ändert nichts. Damit ist es **verlinkbar**:
`synthfhir.onrender.com/szenario/blutdruck-kontrolle` lässt sich in eine
Bewerbung schreiben, ein POST-Ergebnis nicht.

---

## 3a. Nachweis (2026-09-01)

**Alle fünf bauen und validieren**, gemessen über beide Hüllen
(`Ergebnis` für das Web, `Kohortenergebnis` für die CLI) mit
byte-identischem Bundle:

    diabetes-ambulanz      3 Pat. | 17 Ressourcen | fertig | 0 erfundene Codes
    blutdruck-kontrolle    2 Pat. | 11 Ressourcen | fertig | 0
    labor-grundprofil      1 Pat. | 12 Ressourcen | fertig | 0
    mehrere-kontakte       1 Pat. |  9 Ressourcen | fertig | 0
    ohne-kontakt           2 Pat. |  8 Ressourcen | fertig | 0

**Gegen die ISiK-Profile** (HAPI 8.10.0-3, Basismodul 4.0.3,
Vitalparameter 4.0.2, Medikation 4.0.3):

    42 profiliert | 0 Fehler | 38 ungeprüft | 101 Warnungen

**Kein Modellaufruf**, geprüft durch Verminen statt durch Augenschein:
`client_aus_umgebung`, `client_mit_fremdschluessel` und
`OpenAIKompatiblerClient` werfen im Test — alle fünf Szenarien bauen
weiterhin über CLI, Web und API.

**Die Bremse bleibt unberührt:** acht Aufrufe von `/szenario/…` erhöhen
den Zählerstand der Gesamtbremse um null.

**Testreihe: 698 grün**, 3 übersprungen (ohne Terminologieserver).

### Drei Fehler, die erst dieses Vorhaben sichtbar gemacht hat

**Das Blutdruckpanel zeigte in der Vorschau einen Gedankenstrich.** Seit
ADR-014 ist der Blutdruck eine Observation *ohne* `valueQuantity`; die
Werte stehen in `component[]`. `_ansicht` las nur `valueQuantity` — und
zeigte damit ausgerechnet bei der Ressource nichts an, die das Panel
vorführen soll. Gefunden, weil `blutdruck-kontrolle` genau dorthin zeigt.

**`EMER` genügt ISiK nicht.** Siehe *Offen*.

**Der Bericht beschrieb einen Modellaufruf, den es nie gab.** `--szenario …
--bericht b.json` schrieb `teile` mit einem Eintrag, `dauer_s: 0.0` und
null Token — und nannte kein Szenario. Wer die Datei las, konnte Vorlage
und Modelllauf nicht unterscheiden; genau das, was `Ergebnis.szenario`
verhindern soll. Der Fehler saß darin, dass das Feld existierte, aber in
**keinem** der beiden `to_dict()` auftauchte, und dass `baue_kohorte` es
gar nicht erst setzte. Gefunden beim Durchsehen des Diffs vor dem Commit,
nicht von einem Test — die Tests prüften bis dahin nur das Objekt, nicht
seine maschinenlesbare Form.

Beide Berichte führen `szenario` jetzt **immer**, auch als `null`: Ein
fehlendes Feld ließe offen, ob der Lauf keins hatte oder ob die Fassung es
nicht kennt.

---

## 4. Konsequenzen

### Positiv

- Die Seite zeigt jetzt auch dann etwas, wenn das Kontingent leer oder
  der Anbieter ausgefallen ist. Für eine Portfolio-Demo ist das der
  Unterschied zwischen „probier es aus" und „probier es aus, wenn gerade
  frei ist".
- `baue_und_pruefe` ist herausgelöst; Szenario- und Modelllauf können
  nicht mehr auseinanderlaufen. Ein Szenario, das die Integritätsprüfung
  überspringt, wäre baulich nicht möglich.
- Fünf verlinkbare Adressen, die immer dasselbe liefern.
- Die Vorschau zeigt Panels richtig an — unabhängig von Szenarien.
- Die Kontaktarten des Katalogs sind zum ersten Mal **vollständig** gegen
  ISiK vermessen.

### Negativ, bewusst in Kauf genommen

- **Fünf Vorlagen mehr, die gepflegt sein wollen.** Abgefedert durch
  Tests, die bei jeder Katalogänderung anschlagen — aber Arbeit bleibt
  Arbeit.
- **Keine Prüfsummen.** Wer wirklich „dasselbe wie damals" braucht,
  nimmt eine Aufzeichnung. Das ist eine bewusste Trennung und kein
  Versehen.
- **`--aufzeichnen` wird bei `--szenario` übergangen.** Mit Hinweis, nicht
  stumm: Eine angeforderte Datei, die nicht entsteht, ist genau die Sorte
  Überraschung, die später Zeit kostet.
- **Eine geladene Fremddatei kann Codes nennen, die dieser Katalog nicht
  führt.** Sie wird nicht abgewiesen — der Katalog des Empfängers darf ein
  anderer sein —, aber die Ersetzung wird vorgezogen gemeldet.

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| Prüfsummen wie bei der Aufzeichnung | Meldete nach jeder Katalogverbesserung `ABWEICHUNG`. Eine Vorlage soll die neue Ausgabe liefern, nicht die alte verteidigen. |
| Die drei Beispieltexte einfach ins Textfeld schreiben lassen | Kostet weiterhin einen Modellaufruf — genau das Problem, das den Anlass gab. |
| Szenarien aus `scenarios.yaml` laden | Die Variable war seit Phase 0 tot. Vorlagen im Code laufen in der Testreihe mit; eine Datei am Rand veraltet still. Und YAML wäre eine neue Abhängigkeit für nichts. |
| `Sollmenge` an `baue_und_pruefe` durchreichen | Gemessen: `Szenario.patienten` **ist** die Länge derselben Liste, gegen die verglichen wird. Der Vergleich könnte nie ausschlagen; er sähe nur nach Prüfung aus. |
| Ein zweiter Bauweg für die CLI | Es gibt schon zwei Hüllen (`Ergebnis`, `Kohortenergebnis`). Ein Szenario ist aus Sicht des Baus eine einteilige Aufzeichnung — `baue_aus_aufzeichnung` genügt. Ein Test hält beide Wege auf byte-identisches Ergebnis. |
| Eine Gleichzeitigkeitsgrenze auf `/api/v1/szenarien/{name}` | 3,1 ms je Bau bei fester Last. Die Grenze kostete den Zweck und brächte nichts. |
| `EMER` im Szenario lassen | Eine kuratierte Vorlage mit bekanntem Profilfehler wäre ein Pflegefehler. Der Katalogbefund gehört gemeldet, nicht ausgeliefert. *(Seit ADR-018 ist `EMER` konform und wieder im Szenario — es führt den Aufnahmeanlass vor.)* |

---

## 6. Offen

- ~~**`EMER` im Katalog.**~~ **Erledigt am 2026-09-01 durch
  [ADR-018](adr-018-notfall-als-aufnahmeanlass.md).** Der Notfall steht
  jetzt in `hospitalization.admitSource` (`N`) statt in `Encounter.class`.
  Die Vermutung „`IMP` plus Aufnahmeanlass" hat sich bestätigt.
  `test_diese_kontaktart_genuegt_isik_nicht` wurde beim Umbau rot — genau
  wie gebaut — und ist ersetzt.
- **Mehr Szenarien?** Fünf decken die fünf Ressourcentypen und zwei
  unbequeme Fälle ab. Weitere lohnen erst, wenn ein sechster
  Ressourcentyp oder ein neues Modul dazukommt.
- **Szenarien teilen.** `--szenario meins.json` funktioniert. Ein Weg,
  eine Vorlage aus der Weboberfläche *heraus* zu bekommen, gibt es noch
  nicht.
