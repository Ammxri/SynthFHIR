# ADR-013: Die SNOMED-Bindung entscheiden — und beweisen, dass entschieden wurde

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-09-01 |
| **Phase** | 3 (Vision) |
| **Betrifft** | `terminologie.py` (neu), `tools/isik_referenzvalidator.py` (neu), `profil_cli.py`, `NOTICE.md`, `LICENSE`, beide Compose-Dateien |
| **Ergänzt** | 2026-09-01: Der Referenzvalidator entscheidet die Bindung ebenfalls — Abschnitt 3c |
| **Baut auf** | ADR-002, ADR-003, ADR-009 |

---

## 1. Kontext

ADR-009 schloss die ISiK-Messung mit **0 Fehlern und 8 ungeprüften
Befunden** und nannte den Grund:

> Das Profil bindet `Condition.code` an ein SNOMED-ValueSet mit
> `is-a`-Filtern, und ohne Terminologieserver lässt sich die
> Zugehörigkeit weder bestätigen noch widerlegen.

Der offene Punkt lautete: „Ein Terminologieserver, der die SNOMED-Bindung
entscheidbar macht. Erst damit wird aus ‚0 Fehler' ein
Konformitätsnachweis."

Die Frage hat einen Namen. Das ValueSet heißt `DiagnosesSCT`, gehört zu
`ISiKDiagnose` und ist über drei `is-a`-Filter definiert: *Clinical
finding* (404684003), *Event* (272379006) und *Situation with explicit
context* (243796009).

### Der naheliegende Weg ist eine Falle

Dem messenden HAPI einen entfernten Terminologieserver mitzugeben, ist
der erste Gedanke. Er wurde ausgeführt und gemessen:

| Aufbau | geprüft | Fehler | ungeprüft | Warnungen |
|---|---|---|---|---|
| ohne Terminologie | 11 | 0 | **8** | 19 |
| `remote_terminology_service` gesetzt | 11 | **11** | **0** | **0** |

Die zweite Zeile sieht nach dem Ziel aus. Sie ist das Gegenteil: Jeder der
elf Fehler lautete

    HAPI-0389: Failed to call access method:
    java.lang.NullPointerException

Die Validierung war vollständig abgestürzt. Es wurde **nichts** geprüft,
nicht alles. Das einzige sichtbare Zeichen war, dass auch die 19
Warnungen verschwanden.

**Das ist der Befund, der diese Entscheidung prägt: Ein kaputter
Terminologieaufbau erzeugt die schönste Zahl, die dieser Bericht kennt.**
Ein Bericht, der `ungeprüft: 0` meldet, ist damit wertlos, solange er
nicht auch belegt, **dass** entschieden wurde.

---

## 2. Entscheidung

**Ein eigenes Modul `terminologie.py`, das die Bindung direkt entscheidet
— und mit Gegenproben nachweist, dass es entschieden hat.**

Nicht als Validatoreinstellung, sondern als eigene Messung neben der
Profilmessung. `synthfhir-profil --terminologie` führt beide aus und
schreibt beide in denselben Bericht.

Drei Probenarten:

1. **Mitglied** — jeder Diagnosecode des Katalogs. Das ist die Frage.
2. **Kein Mitglied** — `27113001` (*Body weight*): existiert in SNOMED,
   ist aber kein Befund.
3. **Erfunden** — `999999999`.

`Terminologienachweis.gueltig` ist nur wahr, wenn **beide** Gegenproben
richtig verneinen.

Vorgabeserver ist **tx.fhir.de** (HL7 Deutschland), Ausweichserver
**tx.fhir.org** (HL7 International).

---

## 3. Begründung

### Warum Gegenproben und nicht nur Fragen

Eine Messung, die nur „ja" sagen kann, sagt nichts. Der Kanarienvogel
`27113001` ist der wichtigere von beiden: Ein Server, der ihn bejaht,
entscheidet nicht, sondern winkt durch — und meldete dann „25 von 25
Mitglied", die bestmögliche Zahl.

Beide Fälle sind als Test gebaut und wurden gegen absichtliche Fehler
geprüft: Wird die Gültigkeitsprüfung entfernt, fallen zwei Tests; wird
eine fehlende Antwort als „nein" gelesen statt als „nicht gefragt", fällt
einer.

### Warum die Definition geholt und nicht mitgeliefert wird

Gegen ein selbstgeschriebenes ValueSet zu messen wäre ein Zirkelschluss —
man bekäme genau die Antwort, die man hineingeschrieben hat. Die
Definition kommt deshalb beim Messen aus dem Quellrepository der gematik,
am Tag `v.4.0.3`, und ihre **SHA-256-Summe wird geprüft**. Weicht sie ab,
bricht die Messung ab.

Das erspart zugleich die Frage, unter welchen Bedingungen fremde
Profilinhalte weiterverbreitet werden dürfen: Es wird nichts
weiterverbreitet.

### Warum tx.fhir.de die Vorgabe ist

Der Terminologieserver von HL7 Deutschland führt die **deutsche**
SNOMED-Edition (Modul 11000274103, Fassung 20260815). Sie enthält den
internationalen Kern und ist aktueller als die internationale Fassung auf
tx.fhir.org (20250201). Für ein deutsch lokalisiertes Werkzeug ist das
der passende Bezug, und gemessen antwortet er rund viermal schneller.

Beide sind **ohne Betriebszusage** — HL7 sagt zu tx.fhir.org ausdrücklich,
er sei kein Produktivserver. Deshalb ist der zweite eingebaut und nicht
nur erwähnt, und deshalb ist der Test ein **Übersprung**, solange nicht
`SYNTHFHIR_REQUIRE_TERMINOLOGIE=1` gesetzt ist: Ein fremder Dienst darf
die Prüfkette nicht anhalten, aber er darf auch nicht stillschweigend
ausfallen.

### Warum kein stiller Rückfall

Wer `--terminologie` anfordert und keinen Server erreicht, bekommt einen
**Abbruch mit Rückgabewert 2** — keinen Bericht ohne Terminologie. Ein
Bericht, der stillschweigend weniger misst als bestellt, ist genau der
Bericht, gegen den dieses Projekt seit ADR-001 antritt.

Ebenso: Ein Nachweis, der nicht entschieden hat, macht den Rückgabewert
1, auch wenn die Profilmessung selbst sauber war.

---

## 3a. Nachweis (2026-09-01)

**Die ValueSet-Definition**, geholt von
`raw.githubusercontent.com/gematik/spec-ISiK-Basismodul/v.4.0.3/…`:

    SHA-256  fee9b527c982a2eec48f64e724200667a4a8722486419e36dddbe3394c92b63b
    url      https://gematik.de/fhir/isik/ValueSet/DiagnosesSCT | version 4.0.3
    compose  3 × is-a auf 404684003, 272379006, 243796009

**Alle 25 Diagnosecodes des Katalogs**, gegen genau diese Definition:

| Server | SNOMED-Fassung | Mitglied | Gegenprobe `27113001` | Gegenprobe `999999999` |
|---|---|---|---|---|
| tx.fhir.de | DE 11000274103/20260815 | **25/25** | `false` ✓ | `false` ✓ |
| tx.fhir.org | Int 900000000000207008/20250201 | **25/25** | `false` ✓ | `false` ✓ |

**Testreihe: 583 grün** gegen HAPI, ISiK-Profilserver **und**
Terminologieserver (vorher 572).

### Was das heißt — und was nicht

Die Profilmessung **gegen HAPI** meldet weiterhin 8 ungeprüfte Befunde.
Daran ändert dieses Modul nichts: Dieser Validator kann sie nach wie vor
nicht entscheiden. (Der Referenzvalidator kann es — siehe Abschnitt 3c.
Dieser Abschnitt beschreibt den Stand *ohne* ihn, und die Aussage bleibt
gültig für jeden, der nur den HAPI-Weg fährt.)

Was sich ändert, ist die **Sachfrage dahinter**. Sie lautete: Sind die
SNOMED-Codes dieses Projekts Mitglied des ValueSets, das ISiK für
`Condition.code` verlangt? Die Antwort ist gemessen **ja, alle 25**, auf
zwei unabhängigen Servern, mit Gegenproben, die belegen, dass wirklich
entschieden wurde.

Die belastbare Aussage lautet damit:

> Gegen `de.gematik.isik-basismodul 4.0.3`, HAPI FHIR 8.10.0, Stand
> 2026-09-01: **0 Fehler** über 11 profilierte Ressourcen; **8 Befunde
> bleiben für diesen Validator ungeprüft**, weil ihm die SNOMED-Hierarchie
> fehlt. Die Bindung, an der sie hängen, ist **getrennt entschieden**:
> Alle 25 Diagnosecodes sind Mitglied von `DiagnosesSCT|4.0.3`.

Das ist noch immer **keine Konformitätsbescheinigung**. Es ist die
Auflösung genau der Unsicherheit, die ADR-009 benannt hat.

---

## 3b. Was die Lizenzrecherche zutage gefördert hat

Die Recherche zum Terminologieserver hat einen Befund geliefert, der
nichts mit ihm zu tun hat und schwerer wiegt: **`LICENSE` behauptete
MIT über den gesamten Inhalt** — auch über die SNOMED-, LOINC-,
ICD-10-GM- und ATC-Angaben im Katalog. MIT erlaubt ausdrücklich
Veränderung und Weiterlizenzierung. Das steht keinem der vier
Herausgeber zu, und es steht auch dem Betreiber nicht zu, es zu
gewähren.

Behoben durch `NOTICE.md` und einen Vorbehalt in `LICENSE`. Die
wesentlichen Punkte:

- **SNOMED CT**: Codes und englische Bezeichnungen stammen aus dem
  *Global Patient Set*, seit dem 11.03.2026 der volle Umfang der
  International Edition, CC BY-ND 4.0, weltweit gebührenfrei, **ohne**
  Affiliate-Lizenz. Es braucht also keinen Lizenzantrag — nur eine
  Namensnennung. Die deutschen Texte (`display_de`) sind eigene
  Bezeichnungen und werden nie als `Coding.display` ausgegeben.
- **LOINC**: frei nutzbar, verlangt aber einen vorgegebenen Hinweistext,
  den das Projekt nicht führte.
- **ICD-10-GM**: amtliches Werk nach § 5 Abs. 2 UrhG, frei mit
  Änderungsverbot (§ 62) und Quellenangabepflicht (§ 63).
- **SNOMED-Release-Dateien** gehören nicht in ein öffentliches
  Repository oder eine öffentliche CI. Das Projekt liefert keine mit —
  ein Grund mehr, die Terminologie über einen Server zu befragen statt
  sie lokal zu halten.

---

## 3c. Der Referenzvalidator — die Bindung ist auch dort entschieden

Abschnitt 6 führte den offiziellen HL7-Validator als offenen Punkt. Er
wurde geholt (`validator_cli.jar` 6.10.3, 191,5 MiB, SHA-256
`b2cd1c76…691b`) und ausgeführt. Das Ergebnis geht über den Nachweis aus
Abschnitt 3a hinaus: **Auch im Profilbericht bleibt jetzt nichts
ungeprüft.**

| Typ | geprüft | Fehler | Warnungen |
|---|---|---|---|
| Patient | 3 | **0** | 3 |
| Encounter | 4 | **0** | 8 |
| Condition | 4 | **0** | 12 |
| **Summe** | **11** | **0** | **23** |

Und ausdrücklich gesucht: **keine** Meldung der Form *„Unable to check
whether the code is in the value set"* oder *„cannot apply filters"*. Die
acht ungeprüften Befunde aus ADR-009 sind aufgelöst, nicht wegdefiniert.

### Zwei Einstellungen entscheiden über das Ergebnis

**`-sct intl`.** Ohne sie fragt der Validator die SNOMED-Fassung `null`
an. Ein Server, der nur versionierte Editionen führt, antwortet „kenne
ich nicht", und die Bindung bleibt offen. Gemessen war das der
Unterschied zwischen *1 Fehler, 5 Warnungen* und *0 Fehlern, 3
Warnungen* — bei identischer Eingabe.

**Ein eigener `-txCache` je Server.** Der Validator legt seinen
Terminologie-Zwischenspeicher sonst unter einem festen Pfad ab. Zwei
Läufe gegen **verschiedene** Server lieferten nachgemessen byteweise
dasselbe Ergebnis, einschließlich der Editionsnummern des jeweils
anderen. Wer so vergleicht, vergleicht nichts — und merkt es nicht.

### Die Gegenprobe des Messgeräts

`tools/isik_referenzvalidator.py` sucht ausdrücklich nach den
Meldungen, die „ungeprüft" bedeuten, und meldet sie als **ACHTUNG** mit
Rückgabewert 1. Gegen tx.fhir.de ohne passende Edition ausgeführt:

    SUMME  11 geprüft | 3 Fehler | 31 Warnungen
    ACHTUNG — Befunde blieben ungeprüft:
      Unable to check whether the code is in the value set 'DiagnosesSCT|4.0.3'

Das Werkzeug ist damit in beide Richtungen geprüft: Es erkennt die
gelöste Lage und die ungelöste.

### Die verbleibenden 23 Warnungen, benannt

| Anzahl | Warnung | Bewertung |
|---|---|---|
| 11 | `dom-6`: keine Narrative | Best-Practice-Empfehlung, war auch im HAPI-Bericht |
| 4 | ICD-10-GM-CodeSystem unbekannt | Kein öffentlicher Terminologieserver führt es. Nicht behebbar |
| 4 | `VN` nicht im ValueSet `identifier-type` | ISiK **verlangt** `VN` (ADR-009), der FHIR-Kern führt es in seiner *preferred*-Liste nicht. Ein Widerspruch zwischen zwei Vorgaben, kein Mangel |
| 4 | keine Anzeigenamen für Sprache `de` | Folge einer bewussten Entscheidung: Der englische SNOMED-Text steht in `Coding.display`, der deutsche in `CodeableConcept.text`. SNOMED-Descriptions zu übersetzen wäre lizenzrechtlich eine andere Sache (`NOTICE.md`) |

Keine davon ist ein Fehler, und keine ist ohne Preis behebbar.

### Warum das trotzdem im Repository nicht laufen kann

Der Validator ist 191 MiB groß, braucht zwei Minuten und einen fremden
Terminologieserver ohne Betriebszusage. `werkzeuge/` und `messlauf/`
sind deshalb von Git ausgeschlossen; eingecheckt wird allein der Bericht
unter `docs/belege/isik-referenzvalidator.json`.

---

## 4. Konsequenzen

### Positiv

- Die Unsicherheit aus ADR-009 ist aufgelöst, mit einer Messung statt
  einer Vermutung — **zweifach**: einmal als eigene Mitgliedschaftsprobe
  (Abschnitt 3a), einmal durch den Referenzvalidator selbst
  (Abschnitt 3c). Die beiden Wege sind unabhängig voneinander.
- Der Nachweis kann nicht stillschweigend versagen. Das ist wichtiger als
  das Ergebnis selbst — der gemessene NullPointer-Fall zeigt, wie leicht
  eine Terminologiemessung besser aussieht, als sie ist.
- Die Proben hängen am **Katalog**, nicht an einer Liste. Ein neuer
  Diagnosecode wird mitgeprüft; eine Handaufzählung hätte ihn übersehen —
  fünfmal geschehen in diesem Projekt.
- Beide Compose-Dateien fahren jetzt eine **feste HAPI-Fassung**
  (`v8.10.0-3`) statt `:latest`. Ein Messbericht, dessen Werkzeug sich
  unter der Hand ändert, ist keine Zeitreihe.
- Die Lizenzangabe stimmt.

### Negativ, bewusst in Kauf genommen

- **Die Messung hängt an einem fremden Dienst ohne Betriebszusage.**
  Deshalb ist sie ein Übersprung und nicht Teil des Commit-Pfads.
- **Sie ist kein Validatorurteil.** Sie beantwortet eine Teilfrage —
  Mitgliedschaft im gebundenen ValueSet —, nicht die Konformität der
  Ressource. Die 8 ungeprüften Befunde bleiben im Profilbericht stehen,
  und das ist ehrlicher als sie wegzurechnen.
- **Zwei Server, zwei SNOMED-Editionen.** „Mitglied" ist eine Aussage
  über eine Edition. Der Bericht nennt sie deshalb.
- **Nichts davon hilft ICD-10-GM.** Nachgemessen führt keiner der beiden
  Server ein CodeSystem unter `fhir.de` oder `bfarm`; ein `$lookup`
  antwortet mit HTTP 422.

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| `hapi.fhir.remote_terminology_service` am messenden HAPI | Gemessen: NullPointerException, jede Validierung abgestürzt — und das Ergebnis sah mit „0 ungeprüft" besser aus als vorher. |
| SNOMED lokal in HAPI laden | Braucht eine Affiliate-Lizenz und RF2-Dateien, die weder ins Repository noch in eine öffentliche CI dürfen. Halbjährliche Pflege für einen Nachweis, der schwächer ist als der eines Referenzwerkzeugs. |
| Die ValueSet-Definition mitliefern | Zirkelschluss: Man misst gegen das, was man selbst geschrieben hat. Und es wäre Weiterverbreitung fremder Profilinhalte. |
| Nur Mitgliedschaftsfragen, keine Gegenproben | Ein Server, der alles bejaht, meldete dann die bestmögliche Zahl. Genau der Fall, den dieses Modul fangen soll. |
| Bei unerreichbarem Server ohne Terminologie weitermessen | Ein Bericht, der stillschweigend weniger misst als bestellt. |
| Die 8 ungeprüften Befunde im Profilbericht auf 0 setzen | Der Validator hat sie nicht entschieden. Sie wegzurechnen wäre Schönfärberei mit Zahlen. |
| Die IPS Terminology lokal laden | SNOMED sagt selbst, sie sei für Nutzer in Mitgliedsländern wie Deutschland nicht vorgesehen. |

---

## 6. Offen

- **Ein planmäßiger Lauf** (nicht im Commit-Pfad), der die Messung
  regelmäßig wiederholt und meldet, wenn eine Edition die Antwort ändert.
- **ICD-10-GM bleibt ungeprüft.** Der zentrale Terminologieserver von
  BfArM und gematik (`terminologien.bfarm.de`) wäre der Kandidat; seine
  Nutzungsbedingungen sind ungeklärt.
- **Die zusammengezogenen ICD-Bezeichnungen** im Katalog berühren
  möglicherweise das Änderungsverbot. Geringes Risiko, in `NOTICE.md`
  benannt; sauber wäre, die beiden Textteile getrennt zu führen.
