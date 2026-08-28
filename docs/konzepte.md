# Die vier Konzepte hinter dem Spike

Diese Datei erklärt die vier Komponenten, die laut Abschnitt 12 der
Spezifikation verstanden sein müssen, bevor der Code sinnvoll gelesen werden
kann. Jede Erklärung steht zusätzlich als Docstring direkt am jeweiligen
Modul.

| Konzept | Modul |
|---|---|
| 1. `$validate` und `OperationOutcome` | `synthfhir/validator.py` |
| 2. Warum Strukturvalidierung Referenzen ins Leere nicht findet | `synthfhir/integrity.py` |
| 3. Welche Pflichtfelder die drei Ressourcen wirklich brauchen | `synthfhir/templates.py` |
| 4. Wo die Korrekturschleife an ihre Grenzen stößt | `synthfhir/repair.py` |

---

## 1. Validator-Anbindung: `$validate` und `OperationOutcome`

### Was ist `$validate`?

FHIR kennt neben den REST-Operationen (GET/POST/PUT auf Ressourcen)
sogenannte *Operations*, adressiert mit einem Dollarzeichen. Der Aufruf sieht
aus wie ein Anlegen, hat aber **keine Nebenwirkung**:

```http
POST http://localhost:8080/fhir/Observation/$validate
Content-Type: application/fhir+json

{ "resourceType": "Observation", ... }
```

Der Server legt nichts an. Er prüft die Ressource gegen die
StructureDefinition ihres Typs und antwortet mit genau einer Ressource: einem
`OperationOutcome`.

Wichtig für die Implementierung: Der Endpunkt liegt **unter dem
Ressourcentyp**. `Observation/$validate` prüft gegen die
Observation-Definition. Der Code muss den Typ also aus der Ressource lesen
und die URL daraus bauen — schickt man eine Observation an
`Patient/$validate`, prüft der Server gegen das falsche Profil und meldet
Unsinn.

### Was prüft der Server, was nicht?

Er prüft:

- **Kardinalitäten** – Pflichtfelder vorhanden, Obergrenzen eingehalten
- **Datentypen und Formate** – `date`, `dateTime`, `decimal`, `code` …
- **unbekannte Elemente** – ein Feld, das es in FHIR gar nicht gibt
- **Invarianten** – die `con-*`/`obs-*`/`bdl-*`-Regeln der Spezifikation
- **Bindings**, soweit ihm die Terminologie bekannt ist

Er prüft **nicht**:

- ob eine Referenz auf eine existierende Ressource zeigt (→ Konzept 2)
- ob der Inhalt klinisch plausibel ist

### Aufbau eines `OperationOutcome`

```json
{
  "resourceType": "OperationOutcome",
  "issue": [
    {
      "severity": "error",
      "code": "structure",
      "diagnostics": "Observation.status: minimum required = 1, but only found 0",
      "expression": ["Observation.status"]
    }
  ]
}
```

`issue` ist eine Liste von **Befunden**, kein Ergebnis. Der OperationOutcome
sagt nirgends „valide“ oder „invalide“ — diese Entscheidung trifft der
aufrufende Code anhand der Schweregrade.

| Feld | Bedeutung |
|---|---|
| `severity` | `fatal` \| `error` \| `warning` \| `information` |
| `code` | grobe Fehlerklasse: `structure`, `required`, `value`, `invariant`, `code-invalid`, `processing` … |
| `diagnostics` | Klartext – genau das geht in der Korrekturschleife an das LLM zurück |
| `expression` | FHIRPath auf die Fundstelle, z. B. `Observation.valueQuantity.code` |

`expression` ist der wertvollste Teil, weil er den **Fehlerort** nennt und
nicht nur die Beschreibung. Ohne ihn müsste das Modell in der Korrekturrunde
die Fundstelle erst suchen. Ältere Server schreiben stattdessen `location` —
der Code liest beides.

### Interpretation der Schweregrade

Festlegung dieses Spikes (Abschnitt 6.5):

- `fatal`, `error` → die Ressource gilt als **invalide**
- `warning`, `information` → wird protokolliert, ist aber **kein Fehlschlag**

Das folgt der FHIR-Semantik: `error` heißt „das verletzt die Spezifikation“,
`warning` heißt „das ist erlaubt, aber verdächtig“.

Der praktisch wichtigste Fall dafür ist **Terminologie**. Ein HAPI-Server
ohne geladene LOINC-/SNOMED-Pakete kann Codes nicht nachschlagen und meldet
„unable to validate code“ als Warnung. Ein frei erfundener LOINC-Code fällt
damit **nicht** als Fehler auf. Das ist eine echte Grenze der Messung.
Deshalb zählt der Bericht codebezogene Fehler und codebezogene Warnungen
getrennt: Die Warnungszeile ist das Maß dafür, wie groß dieser blinde Fleck
im konkreten Lauf war.

### Zwei Eigenheiten von HAPI, die der Code abfangen muss

1. **Der HTTP-Status ist nicht verlässlich.** Je nach Version antwortet HAPI
   mit 200 (auch bei Fehlern) oder mit 412/422. Maßgeblich ist immer der
   Inhalt des OperationOutcome, nie der Statuscode. Nur ein 5xx gilt als
   Serverproblem und bricht den Lauf ab.
2. **Ein leeres `issue`-Array bedeutet valide.** Ebenso ein einzelner
   Eintrag mit `severity: information` („No issues detected“).

---

## 2. Referenz-Integrität: warum der Validator das nicht findet

Eine FHIR-Referenz ist im Datenmodell **nur ein String**:

```json
"subject": { "reference": "Patient/pat-042" }
```

`Reference.reference` hat den Datentyp `string`. Die StructureDefinition
sagt: Dieses Feld ist eine Zeichenkette, es soll die Form `Typ/ID` haben, und
der Zieltyp muss zu den erlaubten Zieltypen des Feldes gehören. Mehr weiß sie
nicht.

Ob unter dieser Adresse etwas liegt, ist **keine Frage der Struktur, sondern
eine Frage des Datenbestands**. Ein Strukturvalidator, der eine Ressource
einzeln prüft, kann das gar nicht wissen — er hat nur diese eine Ressource
vor sich. `Patient/pat-042` ist für ihn syntaktisch einwandfrei, auch wenn es
`pat-042` nirgends gibt.

Drei weitere Gründe, warum man sich hier nicht auf den Server verlassen darf:

1. Ein `$validate`-Aufruf legt nichts an. Selbst wenn der Server
   referentielle Integrität erzwingen könnte, hätte er beim Prüfen einer
   einzelnen Ressource keinen Bezug zu den anderen Ressourcen desselben
   Durchlaufs — die liegen ja nicht auf dem Server.
2. Bundle-Typ `collection` hat bewusst keine Transaktionssemantik. Anders als
   bei `transaction` löst der Server hier keine Verweise auf.
3. Referentielle Integrität ist in HAPI ohnehin eine abschaltbare
   Servereinstellung (`enforce_referential_integrity_on_write`), keine
   Eigenschaft von FHIR.

Deshalb ist die Prüfung eine **eigenständige, zwingende Komponente**.
Sie prüft drei Dinge:

- **(a)** Zeigt jede `Condition` und jede `Observation` auf einen Patienten,
  der im selben Bundle existiert?
- **(b)** Sind alle IDs innerhalb des Bundles eindeutig?
- **(c)** Gibt es irgendwo im Baum Verweise auf nicht existierende
  Ressourcen?

Punkt (c) ist bewusst weiter gefasst als (a): Verweise stecken nicht nur in
`subject`, sondern können überall auftauchen — `encounter`, `performer`,
`hasMember`, `derivedFrom`. Deshalb durchläuft der Code den kompletten
JSON-Baum und fragt nicht nur bekannte Felder ab. Verweise auf
`contained`-Ressourcen (`#irgendwas`) bleiben außen vor: Sie verlassen die
Ressource nicht.

### Die Kopplung an die ID-Vergabe

Damit diese Prüfung überhaupt etwas messen kann, darf die ID-Vergabe die
Referenzen nicht stillschweigend heilen. Die Regel im Spike lautet deshalb:

> Der Code vergibt IDs neu und zieht bestehende Verweise über eine
> Abbildungstabelle mit. Er erfindet aber **kein Ziel** für einen Verweis,
> der ins Leere zeigt.

Der Code besitzt den ID-Raum (Syntax), das Modell besitzt die Verknüpfung
(Semantik) — und genau diese Verknüpfung wird gemessen.

---

## 3. Die Vorlagen der Variante B: was FHIR wirklich verlangt

Die Vorlagen sind der ganze Trick der Variante B. Sie müssen die Struktur von
sich aus richtig setzen, damit strukturell nichts vom Modell abhängt. Dafür
muss man wissen, was FHIR R4 **wirklich** verlangt — also das, was der
Validator als `error` meldet, nicht das, was schön wäre.

Es gibt drei Klassen von Anforderungen:

1. **Kardinalität** (1..1 = Pflicht). Fehlt so ein Feld, ist es ein Fehler.
2. **Datentyp.** Ein `date` muss `YYYY[-MM[-DD]]` sein. `12.05.1980` ist kein
   `date`.
3. **Required Binding.** Manche `code`-Felder dürfen nur Werte aus einer
   festen Liste tragen; ein Tippfehler dort ist ein Fehler, keine Warnung.
   Dazu kommen **Invarianten** — Regeln, die Beziehungen zwischen Feldern
   erzwingen.

### Patient

Überraschung: `Patient` hat in R4 **kein einziges Pflichtfeld** außer
`resourceType`. `{"resourceType": "Patient"}` ist valide. Die Fehlerquellen
liegen deshalb ausschließlich bei Datentyp und Binding:

| Feld | Fallstrick |
|---|---|
| `gender` | `code` mit required binding auf `male \| female \| other \| unknown`. `"Male"`, `"m"`, `"männlich"` sind **Fehler**, keine Warnungen. |
| `birthDate` | Datentyp `date`. Deutsche Schreibweise ist ein Fehler. |
| `name` | 0..* `HumanName` – ein **Objekt** im Array, kein String. `"name": "Anna Meier"` ist ein Datentypfehler. `family` ist ein String, `given` ein Array von Strings. |
| `identifier` | 0..* `Identifier` mit `system` (uri) und `value` (string). |

### Condition

| Feld | Anforderung |
|---|---|
| `subject` | **1..1** Reference. Der einzige harte Kardinalitätsfehler dieser Ressource. |
| `clinicalStatus` | CodeableConcept, required binding auf `condition-clinical`: `active`, `recurrence`, `relapse`, `inactive`, `remission`, `resolved` |
| `verificationStatus` | CodeableConcept, required binding auf `condition-ver-status`: `unconfirmed`, `provisional`, `differential`, `confirmed`, `refuted`, `entered-in-error` |
| `code` | 0..1 CodeableConcept, nur **example binding** – ein erfundener Code ist strukturell erlaubt |
| `onsetDateTime` | Teil der Auswahl `onset[x]`; es darf immer nur **eine** Ausprägung gesetzt sein |

Die Invarianten `con-3` und `con-5` koppeln die beiden Statusfelder:
`clinicalStatus` **muss** da sein, wenn `verificationStatus` nicht
`entered-in-error` ist — und **darf nicht** da sein, wenn er es doch ist. Die
Vorlage setzt fest `active` + `confirmed`; damit sind beide Invarianten immer
erfüllt, unabhängig davon, was das Modell liefert.

Dass `Condition.code` nur ein example binding hat, ist genau der Grund, warum
Variante B einen **eigenen Katalog** braucht und sich nicht auf den Validator
verlassen kann.

### Observation

Die fehleranfälligste der drei: zwei Pflichtfelder **und** ein
zusammengesetzter Datentyp.

| Feld | Anforderung |
|---|---|
| `status` | **1..1** `code` mit required binding (`registered`, `preliminary`, `final`, `amended`, `corrected`, `cancelled`, `entered-in-error`, `unknown`). Vergessenes `status` ist der Klassiker. |
| `code` | **1..1** CodeableConcept |
| `subject` | 0..1 — formal optional, semantisch unverzichtbar. Der Strukturvalidator beanstandet eine Messung ohne Patient **nicht**. Ein Grund mehr für Konzept 2. |
| `effectiveDateTime` | Auswahl `effective[x]`, Datentyp `dateTime` |
| `valueQuantity` | Auswahl `value[x]` |

`Quantity` braucht für eine maschinell auswertbare Messung vier Teile:

```json
"valueQuantity": {
  "value":  7.9,                              // decimal – JSON-Zahl, kein String
  "unit":   "mmHg",                           // menschenlesbar
  "system": "http://unitsofmeasure.org",
  "code":   "mm[Hg]"                          // UCUM
}
```

`unit` und `code` sind **nicht dasselbe**: `mmHg` ist die Anzeige, `mm[Hg]`
der UCUM-Code. Genau hier vertun sich Modelle regelmäßig — und genau deshalb
liefert das Modell in Variante B nur den LOINC-Code, die Zahl und das Datum;
Einheit, UCUM-Code und Anzeigetext kommen aus dem Katalog.

### Bundle

Typ `collection` ist eine reine Sammlung ohne Transaktionssemantik. Daraus
folgt: `entry.request` und `entry.response` dürfen **nicht** gesetzt sein
(Invariante `bdl-3`), und `fullUrl` muss innerhalb des Bundles eindeutig sein
(`bdl-7`). Da der Code die IDs vergibt, ist Letzteres garantiert.

---

## 4. Die Korrekturschleife: warum sie funktioniert und wo sie aufhört

### Warum sie funktioniert

Die Schleife verwandelt eine schwere Aufgabe in eine leichte.

Beim **ersten** Aufruf muss das Modell aus einer Prosabeschreibung eine
komplette, spezifikationskonforme Ressource erzeugen und dabei alles
gleichzeitig richtig machen: Pflichtfelder, Datentypen, Bindings,
Invarianten, Referenzen, klinischen Inhalt.

In der **Korrekturrunde** bekommt es etwas völlig anderes: einen konkreten
Gegenstand, einen benannten Ort und eine benannte Abweichung.

```
[error] at Observation.valueQuantity.code
Unable to validate code "mg/dl" - code is case-sensitive
```

Das ist eine lokale Bearbeitungsaufgabe, keine Erzeugungsaufgabe. Der
`expression`-Pfad sagt, **wo**. Deshalb ist die Trefferquote einer
Korrekturrunde typischerweise deutlich höher als die einer Neugenerierung.

### Wo sie an Grenzen stößt

**1. Fehlermeldungen beschreiben das Symptom, nicht die Lösung.**
`minimum required = 1, but only found 0` sagt, dass `status` fehlt — nicht,
welcher der acht erlaubten Statuswerte hier richtig ist. Bei required
bindings muss das Modell die zulässige Werteliste kennen oder raten. Weiß es
sie nicht, hilft auch die zehnte Runde nicht.

**2. Flicken erzeugt neue Löcher.**
Ein Modell, das ein fehlendes `valueQuantity` ergänzt, ohne das vorhandene
`valueString` zu entfernen, verletzt danach die Regel, dass von einer Auswahl
`value[x]` nur **eine** Ausprägung gesetzt sein darf. Die Fehlerzahl kann von
Runde zu Runde steigen.

**3. Fehler verdecken einander.**
Manche Validierungsschritte laufen erst, wenn der vorherige durchkommt. Nach
dem Beheben eines Strukturfehlers taucht plötzlich ein bis dahin unsichtbarer
Terminologiefehler auf. Die Fehlerzahl fällt deshalb nicht monoton — „0
Fehler nach 3 Runden“ ist nicht dasselbe wie „dreimal je ein Drittel
behoben“.

**4. Stagnation ist das eigentliche Risiko.**
Wenn eine Runde die Fehlerzahl nicht senkt, formuliert das Modell in der
Regel nur um. Das kostet Geld und Zeit, ohne dem Ziel näher zu kommen.
Deshalb zählt der Spike `non_improving_rounds` gesondert — der direkte
Hinweis auf Endlosschleifenverhalten aus Abschnitt 6.6 und einer der
wichtigsten Werte der ganzen Messung.

**5. Die Korrektur kann Inhalt zerstören.**
Beim Reparieren der Struktur ändert ein Modell gern nebenbei Werte,
Datumsangaben oder Referenzen. Deshalb wird nach jeder Runde die Identität
wieder festgenagelt (`repin_identity`) und jeder Zwischenstand als Artefakt
gespeichert — nur so ist nachvollziehbar, was das Modell tatsächlich
verändert hat.

**6. Die Kosten wachsen linear mit den Runden.**
Jede Runde schickt die vollständige Ressource erneut hin und zurück. Drei
Runden auf einer schlechten Ressource können teurer sein als die
ursprüngliche Erzeugung des ganzen Szenarios. Das ist der Grund, warum die
Metrik „Ø Korrekturrunden“ nicht nur ein Qualitäts-, sondern auch ein
Kostenindikator ist.

### Eine bewusste Festlegung

Dem Modell werden **nur blockierende Befunde** (`fatal`/`error`)
zurückgegeben. Warnungen mitzuschicken würde es zu Änderungen verleiten, die
nichts verbessern, aber neue Fehler einbauen können — siehe Grenze 2.
