# ADR-008: Server-Push — und die Kennzeichnung, die er nötig macht

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-08-30 |
| **Phase** | 2 (v1.x), PRD-Punkt „Direkter Server-Push" (Could) |
| **Betrifft** | Schreiben in fremde Systeme, Kennzeichnung aller Ausgaben |
| **Baut auf** | ADR-005 (Ladereihenfolge), ADR-007 (Ressourcentypen) |

---

## 1. Kontext

Bis hierher erzeugte SynthFHIR **Dateien**. Wer sie nicht mag, löscht sie.
Dieser Punkt ändert das Risikoprofil grundlegend: Ab jetzt schreibt das
Werkzeug in ein **fremdes System**, und ein Tippfehler in der Ziel-URL
schriebe zweihundert erfundene Patienten in etwas, das vielleicht kein
Testserver ist.

Die Spezifikation des Projekts sagt: *„Es dürfen zu keinem Zeitpunkt echte
Patientendaten verarbeitet werden."* Das ist eine Aussage über die
**Eingabe**. Ab hier braucht es die Gegenrichtung: Die Ausgabe darf nicht
dort landen, wo echte Daten liegen.

---

## 2. Entscheidung

**Der Push läuft über Transaction-Bundles mit PUT-Einträgen, in Paketen,
in der Ladereihenfolge aus ADR-005. Er ist voreingestellt ein Trockenlauf.
Und — die weiterreichende Hälfte dieser Entscheidung — jede erzeugte
Ressource trägt ab sofort ein `meta.security`-Label `HTEST`, unabhängig
davon, ob sie je gepusht wird.**

Vier Schutzmechanismen, in dieser Reihenfolge:

1. **Kennzeichnung an der Quelle.** `meta.security` = HTEST, gesetzt in den
   Vorlagen, nicht erst beim Push.
2. **Trockenlauf als Voreinstellung.** `--push` schreibt nichts;
   `--push-ausfuehren` schreibt.
3. **Vorabfrage des Ziels.** Ist es ein FHIR-Server? Liegen dort Daten ohne
   Testkennzeichen?
4. **Nur gültige Kohorten.** Was `fertig` nicht erfüllt, wird nicht
   gepusht.

---

## 3. Begründung

### Die Kennzeichnung ist der eigentliche Gewinn

Das Projekt verspricht an vielen Stellen, ausschließlich synthetische Daten
zu erzeugen: im README, im NDJSON-Manifest, in jeder Konsolenausgabe.
Alles davon steht dort, wo ein **Mensch** hinsieht. Nirgends stand es dort,
wo eine **Maschine** hinsieht.

`HTEST` ändert das. Ein Empfänger kann danach suchen (`_security=…|HTEST`,
an HAPI nachgeprüft), ein Server kann solche Daten aussondern, und die
Zusage wird von einer Behauptung zu einer Angabe. Die Definition des Codes
trifft diesen Fall wörtlich:

> To perform one or more operations on information that is simulated or
> synthetic health data used for testing system capabilities outside of a
> production or operational system environment.

**Das Label sitzt an jeder Ressource, nicht nur an gepushten.** Eine Datei,
die heute exportiert wird, kann morgen jemand anderes irgendwohin laden —
dann ist die Kennzeichnung schon drin. Angewandt wird es an genau einer
Stelle, am Ende von `baue_aus_parametern`; ein künftiger Ressourcentyp
bekommt es, ohne dass jemand daran denken muss.

#### Die System-URI war zuerst falsch

Eine Zusammenfassung der Spezifikationsseite nannte `v3-ActCode`. HAPI wies
das ab:

```
Unknown code 'http://terminology.hl7.org/CodeSystem/v3-ActCode#HTEST'
```

Richtig ist **`v3-ActReason`**, nachgeprüft an der Primärquelle
(terminology.hl7.org): HTEST gehört zur Gruppe SYSDEV unter PurposeOfUse.

Bemerkenswert daran ist, **wer** den Fehler fand. Für LOINC, SNOMED,
ICD-10-GM und ATC meldet HAPI nur `CodeSystem is unknown and can't be
validated` — dort hilft nur die Handprüfung. `v3-ActReason` dagegen kennt
HAPI, und deshalb hat es hier zum ersten Mal einen **Code** gefangen, nicht
nur eine Struktur.

### Warum Transaktionen und nicht einzelne PUTs

Gemessen an HAPI 4.0.1: Ein Transaction-Bundle mit einem fehlerhaften
Eintrag endet mit HTTP 400, und **auch der gute Eintrag ist danach nicht
angelegt** (404). Transaktionen sind also atomar — genau das, was man will,
wenn man in ein fremdes System schreibt: entweder das Paket ist drin oder
es ist nichts drin.

Einzelne PUTs hinterließen bei einem Fehler in der Mitte einen halben
Datensatz auf einem Server, auf den man womöglich keinen Löschzugriff hat.

**PUT und nicht POST**, weil die Kennungen aus diesem Projekt kommen: Der
Push ist damit idempotent, zweimal ausgeführt ergibt denselben Zustand
statt doppelter Patienten. Die Kehrseite ist, dass PUT überschreibt, was
unter derselben Kennung schon dort liegt — und genau deshalb gibt es
Schutzmechanismus 3.

**In Paketen**, weil ein Transaction-Bundle über tausend Ressourcen eine
einzige riesige Anfrage wäre und Server die Größe begrenzen. Die
Paketreihenfolge kommt aus derselben Funktion wie beim NDJSON-Export —
sie ist dafür aus `ndjson.py` in die Domänenschicht gezogen worden, damit
nicht zwei Abschriften auseinanderlaufen.

### Warum der Trockenlauf die Voreinstellung ist

Weil ein Tippfehler in einer URL sichtbar werden soll, **bevor** er wirkt.
`--push http://ziel/fhir` berichtet, was geschähe, und nennt den Schalter,
mit dem es wirklich geschieht. Das ist dieselbe Form wie beim Aufzeichnen,
das den Wiedergabebefehl ausgibt.

### Was der Wächter kann und was nicht

Er vergleicht zwei Zahlen: Patienten auf dem Ziel insgesamt, und Patienten
mit korrektem Testkennzeichen. Ist die erste größer, liegen dort Daten, die
nicht von SynthFHIR stammen.

Zwei Fallstricke, beide gemessen:

- **Das Suchtoken braucht sein System.** Eine Suche nach `HTEST` ohne
  System traf auch eine Ressource, die den Code unter einem *anderen*
  System trug. Der Wächter hätte fremde Daten für eigene gehalten.
- **`_total=accurate`** statt einer Schätzung. Für einen
  Schutzmechanismus taugt ein ungefährer Wert nicht.

**Und was er ausdrücklich nicht ist: ein Beweis.** Er liest den Suchindex
des Zielservers, und der hängt hinterher. Gemessen: Nach einem Push meldete
HAPI über eine Minute lang 0 Patienten, während ein direkter Lesezugriff
sie sehr wohl lieferte. Wer kurz vorher etwas auf das Ziel geschrieben hat,
sieht hier womöglich zu wenig.

Der Wächter senkt das Risiko, er beseitigt es nicht. Die eigentliche
Sicherung bleibt, dass die Ziel-URL ausdrücklich genannt werden muss und
der Trockenlauf zeigt, was geschähe.

### Warum eine Lücke den Push nicht verhindert

`fertig` heißt „alles Gelieferte ist gültig", nicht „alles Angefragte ist
da". Eine Kohorte mit 190 von 200 Patienten ist gültig und in sich
geschlossen; sie zu verweigern wäre bevormundend. Sie wird gepusht — aber
die Lücke steht **an der Stelle, an der nach außen geschrieben wird**, nicht
nur in der Zusammenfassung darüber, und der Rückgabewert bleibt 1.

### Das Token kommt aus der Umgebung

`SYNTHFHIR_PUSH_TOKEN`, ausdrücklich **kein** Kommandozeilenargument:
Argumente stehen in der Shell-Historie und in der Prozessliste, wo jeder
Mitbenutzer des Rechners sie lesen kann. Fehlermeldungen werden vor der
Ausgabe von einem etwaigen Token bereinigt — ein Token, das einmal in einem
Bericht steht, ist nicht mehr geheim.

---

## 3a. Nachweis (2026-08-30)

Gegen einen frisch aufgesetzten HAPI FHIR 4.0.1, 8 Patienten aus einer
wiedergegebenen Aufzeichnung:

| Prüfung | Ergebnis |
|---|---|
| Trockenlauf | 1 Transaktion *würde* geschrieben, **0 Anfragen abgesetzt** |
| Push | **80 Ressourcen in 1 Transaktion** |
| Auf dem Server | 8 Patient, 8 Encounter, 16 Condition, 32 Observation, 16 MedicationStatement = **80** |
| Davon gekennzeichnet | **80 von 80** |
| Verweise dort auflösbar | `pat-001`: 2 Diagnosen, 4 Messwerte, 2 Medikationen |
| Begegnungsverweis | 2 Diagnosen zu `enc-001` |
| Zweimal gepusht | Patientenzahl unverändert — idempotent |
| Wächter bei fremden Daten | verweigert, 0 Anfragen abgesetzt |

---

## 3b. Nachträglich gefundene Fehler (2026-08-30)

Eine gegnerische Durchsicht fand vier Fehler. Der erste hebt den
wichtigsten Schutzmechanismus dieses Moduls auf.

### Der Wächter versagte nach der falschen Seite

Ein FHIR-Server darf einen **unbekannten Suchparameter stillschweigend
ignorieren** — das ist die Voreinstellung (*lenient handling*). Beachtet
das Ziel `_security` nicht, liefert es auf den HTEST-Filter dieselbe Zahl
wie ohne Filter. Beide Zahlen sind dann gleich groß, und der Wächter
meldete: keine fremden Daten.

Er hätte also einen Server voller echter Patienten für einen leeren
Testserver gehalten — und den Push freigegeben. Ein Schutz, der nach der
falschen Seite versagt, ist schlechter als keiner: Er gibt Sicherheit vor.

Gemessen an zwei Servern:

```
                          lokaler HAPI    öffentlicher HAPI
ohne Filter                        24                 8253
erfundener Parameter               24                 8253   <- ignoriert
_security = Unsinnslabel            0                    0   <- Filter wirkt
```

Die Messung liefert die Abhilfe gleich mit: **Eine Gegenprobe mit einem
Sicherheitslabel, das es nirgends gibt.** Wirkt der Filter, ergibt sie
null. Kommt stattdessen die volle Trefferzahl, ignoriert der Server den
Parameter — und dann ist auch seine Auskunft über HTEST wertlos.
`fremde_daten` prüft das jetzt zuerst, und jede Unsicherheit zählt als Ja.

Nachgeprüft nach der Korrektur:

| Ziel | Bestand | gekennzeichnet | Filter wirkt | Urteil |
|---|---|---|---|---|
| lokaler HAPI | 24 | 24 | ja | Push frei |
| `hapi.fhir.org/baseR4` | 8253 | 0 | ja | **verweigert** |

### Die übrigen drei

| Befund | Was passierte | Behebung |
|---|---|---|
| **`resourceType` ungeprüft im URL-Pfad** | Ein Wert wie `"../Binary"` schriebe an eine andere Stelle des Servers als gemeint — dieselbe Lücke wie beim NDJSON-Export, dort schon behoben | Typ und Kennung müssen den Mustern genügen; geprüft wird **vor** dem ersten Paket |
| **Teilerfolg meldete Rückgabewert 2** | 2 heißt „nichts passiert". Nach drei durchgegangenen Paketen liegen aber Daten auf einem fremden Server | Rückgabewert 1, plus eine Zeile, die sagt, wie viel schon dort liegt |
| **Testlabel fehlte im Katalog-Fingerabdruck** | Es steht in jeder Ressource; ändert es sich, ändert sich jedes Bundle. Eine Wiedergabe meldete die Abweichung, nannte den Katalog aber unverändert | in `FESTE_WERTE` aufgenommen |

Der dritte ist zum vierten Mal dieselbe Klasse: eine Aufzählung von Hand,
die einen neuen Eintrag nicht kennt. Nach `vital_sign`, den
Katalogsammlungen und den Beanstandungsarten ist das ein Muster, kein
Zufall.

---

## 4. Konsequenzen

### Positiv

- Die Zusage „nur Testdaten" ist erstmals maschinenlesbar — überall, nicht
  nur beim Push.
- Der Push ist idempotent und atomar je Paket.
- Die Ladereihenfolge aus ADR-005 dient jetzt zwei Ausgabewegen aus einer
  Quelle.

### Negativ, bewusst in Kauf genommen

- **Alle Bundles ändern sich.** Das Label steht in jeder Ressource. Ältere
  Aufzeichnungen melden bei der Wiedergabe `ABWEICHUNG` — richtig so, das
  ist der Selbsttest aus ADR-006 bei der Arbeit.
- **Der Wächter ist kein Beweis** (siehe oben). Er verweigert inzwischen
  auch dann, wenn der Server `_security` gar nicht beantwortet — das ist
  streng, aber die einzige Haltung, die nicht nach der falschen Seite
  versagt.
- **Kein Löschen, kein Zurückrollen über Paketgrenzen.** Bricht Paket 3 von
  5 ab, stehen die ersten beiden auf dem Server. Sie sind gültig,
  gekennzeichnet und beim nächsten Versuch idempotent überschreibbar — aber
  sie stehen dort.
- **Keine Authentifizierung außer Bearer.** SMART on FHIR, mTLS oder Basic
  sind nicht gebaut.
- **`--push` schreibt in ein System, das dem Nutzer gehört.** Das Werkzeug
  kann prüfen, warnen und verweigern; die Verantwortung für die URL bleibt
  bei dem, der sie eingibt.

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| Einzelne PUTs statt Transaktionen | Ein Fehler in der Mitte hinterließe einen halben Datensatz auf einem fremden Server. Transaktionen sind atomar — nachgemessen. |
| POST statt PUT | Nicht idempotent: Jeder Lauf legte neue Patienten an. Die Kennungen kommen ohnehin aus diesem Projekt. |
| Ein einziges Transaction-Bundle für alles | Eine Anfrage über Megabyte; Server begrenzen die Größe. |
| `$import` (Bulk Data) | In HAPI nicht aktiviert (nachgeprüft: fehlt im CapabilityStatement) und bei den meisten Servern konfigurationspflichtig. |
| Push als Voreinstellung ausführen | Ein Tippfehler in der URL wirkte sofort. |
| Das Label nur an gepushten Ressourcen | Eine exportierte Datei kann später jemand anderes laden. Dann fehlte die Kennzeichnung genau dort, wo sie gebraucht wird. |
| Fehlende Kennzeichnung beim Push nachrüsten | Wenn dort etwas ohne Kennzeichen ankommt, stimmt weiter oben etwas nicht — das gehört gesehen, nicht stillschweigend geflickt. |
| Das Token als Kommandozeilenargument | Landet in der Shell-Historie und in der Prozessliste. |
| Dem Zielserver glauben, ohne die Filterwirkung zu prüfen | Ein Server, der `_security` ignoriert, sähe aus wie ein sauberer Testserver. Gemessen: Unbekannte Parameter werden stillschweigend ignoriert. |

---

## 6. Offen

- Wiederaufsetzen nach einem abgebrochenen Push (die geschriebenen Pakete
  sind idempotent, es fehlt nur die Buchführung darüber).
- Weitere Authentifizierungsverfahren.
- Ein `--push-loeschen`, das eine zuvor gepushte Kohorte wieder entfernt.
  Löschen auf einem fremden Server ist eine eigene Risikoklasse und braucht
  eine eigene Entscheidung.
