# ADR-018: Der Notfall steht nicht in `Encounter.class`

| | |
|---|---|
| **Status** | Angenommen |
| **Datum** | 2026-09-01 |
| **Phase** | 3 (Vision) |
| **Betrifft** | `domain/codes.py`, `domain/templates.py`, `web/oberflaeche.py`, `szenarien.py`, `test_profil.py`, `test_domaene.py` |
| **Baut auf** | ADR-002, ADR-007, ADR-009, ADR-016, ADR-018 |

---

## 1. Kontext

ADR-007 nahm vier Begegnungsarten in den Katalog: `AMB`, `IMP`, `EMER`,
`VR`. Sie stammen aus `v3-ActEncounterCode` und wurden am 2026-08-30 gegen
die HL7-Terminologie geprüft. Alle vier existieren, alle vier sind gültiges
FHIR.

Beim Bau der Szenario-Bibliothek (ADR-016) fiel auf, dass eine davon
trotzdem nicht durchgeht.

### Der Befund

ISiK bindet `Encounter.class` an ein **deutsches** ValueSet, nicht an das
internationale:

    Encounter.class    bind=required -> http://fhir.de/ValueSet/EncounterClassDE

Dessen Expansion enthält genau sechs Codes:

    AMB (ambulatory)      HH (home health)    SS (short stay)
    VR (virtual)          IMP (inpatient)     PRENC (pre-admission)

**`EMER` ist nicht darunter.** Die Bindung ist `required` — es gibt also
keinen Spielraum. Jeder Notfallkontakt, den dieses Werkzeug erzeugte, war
gültiges FHIR und konnte trotzdem niemals ISiK-konform sein.

### Warum es niemand bemerkt hat

Die feste Testkohorte benutzte `EMER` nicht. Der Profiltest maß also die
Kontaktarten, die ohnehin durchgingen — der Fall, den man messen muss, war
der einzige, der fehlte. Dieser Fehler ist in diesem Projekt der vierte
seiner Art.

---

## 2. Entscheidung

**`EMER` bleibt im Katalog als *Schlüssel*, verschwindet aber aus
`Encounter.class`. Gebaut wird `class: IMP` plus
`hospitalization.admitSource: N` („Notfall").**

Dafür trennt `EncounterClass` zwei Dinge, die bisher dasselbe waren:

| Feld | Bedeutung |
|---|---|
| `schluessel` | wonach gefragt wird — im Prompt, im Parametersatz, im Szenario |
| `code` | was in `Encounter.class` landet — **muss** in `EncounterClassDE` liegen |

Für drei der vier Einträge sind beide gleich. Beim Notfall nicht.

---

## 3. Begründung

### Warum nicht einfach ein neueres Paket

Die naheliegendste Lösung wäre gewesen, dass eine spätere Fassung von
`de.basisprofil.r4` den Code nachträgt. Gemessen über drei Fassungen:

| Fassung | Codes in `EncounterClassDE` | `EMER` |
|---|---|---|
| 1.5.3 (von ISiK 4.0.3 benutzt) | AMB, IMP, PRENC, VR, SS, HH | nein |
| 1.5.4 | AMB, IMP, PRENC, VR, SS, HH | nein |
| **1.6.0 (aktuell)** | AMB, IMP, PRENC, VR, SS, HH | **nein** |

Über drei Releases identisch. **Das Fehlen ist Absicht, kein Versehen** —
und Warten hilft nicht.

### Warum `admitSource` und nicht etwas anderes

Sechs Stellen kämen in Frage. Alle wurden gemessen:

| Stelle | Bindung | Notfall-Code darin? |
|---|---|---|
| `Encounter.class` | **required** → `EncounterClassDE` | **nein** |
| `type:Kontaktebene` | required → `kontaktebene-de` | nein (nur Ebenen) |
| `type:KontaktArt` | required → `kontaktart-de` | nein (12 Codes, keiner) |
| `serviceType` | required → Fachabteilungsschlüssel | nein (Abteilungen) |
| `hospitalization.admitSource` | **extensible** → `dgkev/Aufnahmeanlass` | **ja: `N` = „Notfall"** |
| `extension:Aufnahmegrund` → `VierteStelle` | required → `dkgev/AufnahmegrundVierteStelle` | **ja: `7` = „Notfall"** |
| *(`priority`)* | von ISiK **nicht profiliert**, example | ja: `EM`, aber ungeprüft |

Es gibt also **zwei** taugliche Stellen, nicht eine. Gewählt ist
`admitSource`, und zwar weil die Spezifikation selbst dort hinzeigt. Das
ISiK-Profil kommentiert genau dieses Element:

> „Anlass der stationären Aufnahme, z.B. 'Einweisung', 'Notfall' etc."

Das ist die einzige Stelle im ganzen Profiltext, an der das Wort
„Notfall" überhaupt vorkommt.

Und es ist keine Notlösung, sondern das Modell dahinter: `class` sagt,
**wie** der Kontakt stattfand (ambulant, stationär). `admitSource` sagt,
**warum** er zustande kam (Einweisung, Verlegung, Geburt, Notfall). Ein
Notfall ist kein Setting, sondern ein Anlass. Die deutsche Modellierung
trennt beides, die internationale wirft es in `class` zusammen.

Dass die Bindung `extensible` ist und nicht `required`, ist am Server
nachweisbar und kein Formfehler: Ein Fremdcode an dieser Stelle
(`admit-source#emd` aus der HL7-Terminologie) ergibt eine **Warnung**,
derselbe Verstoß bei `class` einen **Fehler**.

### Warum `EMER` als Schlüssel bleibt

Der naheliegende Reflex wäre, `EMER` ersatzlos zu streichen. Gemessen, was
dann passiert: `_begegnungsart` findet den Code nicht, ersetzt ihn durch
`AMB` und meldet `erfundene_begegnungsart`.

Das wäre gleich dreifach falsch. Wer „20 Patienten aus der Notaufnahme"
anfordert, bekäme **ambulante** Kontakte; der Notfall wäre spurlos
verschwunden; und die Metrik „Anteil erfundener Codes" zählte einen Code
mit, den niemand erfunden hat. `EMER` ist ein anerkanntes Konzept — es hat
in diesem ValueSet nur nichts zu suchen.

### Warum die Vorschau die Ressource liest

`_kontaktart` bekam bisher nur `Encounter.class`. Bei einem Notfall stünde
dort jetzt `IMP`, und die Vorschau zeigte **„stationär"** — richtig und
trotzdem irreführend, weil genau die Information fehlte, nach der gefragt
wurde. Sie bekommt deshalb die ganze Ressource und zeigt
**„stationär · Notfall"**.

Gelesen wird die Ressource, nicht der Katalogschlüssel: Die Vorschau soll
zeigen, was in den Daten steht. Die Bezeichnung kommt trotzdem aus dem
Katalog und nicht aus der Ressource — bei einer geladenen Fremddatei
stammt `display` vom Aufrufer, und der gehört nicht ungeprüft in die
Seite.

---

## 3a. Nachweis (2026-09-01)

**Alle vier Katalogeinträge gegen `ISiKKontaktGesundheitseinrichtung`:**

    AMB    class=AMB  admitSource=-   ->  0 Fehler
    IMP    class=IMP  admitSource=-   ->  0 Fehler
    EMER   class=IMP  admitSource=N   ->  0 Fehler
    VR     class=VR   admitSource=-   ->  0 Fehler

Vorher ergab `EMER` genau einen Fehler:

    The Coding provided (…v3-ActCode#EMER) was not found in the
    value set 'EncounterClassDE'

**Alle fünf Szenarien:** 42 profilierte Ressourcen, **0 Fehler** — mit dem
Notfall darin, nicht ohne ihn.

**Der Test, der den Umbau angekündigt hat.** ADR-016 hinterließ
`test_diese_kontaktart_genuegt_isik_nicht`, gebaut so, dass er **rot wird,
sobald der Befund behoben ist**. Beim Umbau wurde er rot:

    AssertionError: EMER genuegt ISiK jetzt — Befund behoben,
    diesen Test loeschen.

Er ist ersetzt durch den Test, der `EMER` von Anfang an hätte verhindern
müssen — und zwar in **zwei** Ausfertigungen, aus einem Grund, der erst
die Gegenprüfung zutage gefördert hat (siehe Mangel 3 unten):

* `…_auch_ohne_server` hält die Katalogcodes gegen eine festgeschriebene
  Liste der sechs Codes. Läuft immer, auch in der CI.
* `…_liegt_in_encounterclassde` holt dieselbe Menge **vom Server** und
  ist damit still, sobald keiner da ist.

Dazu `test_die_festgeschriebene_liste_stimmt_noch`, der beide gegeneinander
hält. Eine festgeschriebene Liste ist sonst genau das, wovor dieses Projekt
sich hütet; sie ist hier vertretbar, weil sie nicht still veralten kann —
sie kann nur unbemerkt richtig bleiben.

**Testreihe: 721 grün**, 3 übersprungen.

### Drei Mängel an dieser Umsetzung, gefunden und behoben

Eine parallele Untersuchung (zehn Agenten, jeder mit eigener Messung) hat
den ersten Entwurf dieser Entscheidung angegriffen. Drei Treffer:

**1. Der Fingerabdruck deckte das neue System nicht ab.**
`AUFNAHMEANLASS_SYSTEM` stand nicht in `SYSTEME`. Nachgestellt: Der Dreher
`dgkev` → `dkgev` — ein Buchstabe — änderte das Bundle und ließ den
Fingerabdruck **gleich**. Eine Wiedergabe hätte `ABWEICHUNG` gemeldet und
dazu „Der Katalog ist unverändert" — die genau falsche Fährte. Das ist
derselbe Fehler, den `katalog_pruefsumme` für `vital_sign` schon einmal
dokumentiert, eine Ebene höher.
Behoben, und die *Fehlerklasse* dazu:
`test_jede_system_konstante_steht_im_fingerabdruck` liest die Konstanten
aus dem Modul, statt sie zu wiederholen. Er fand sofort einen zweiten
Kandidaten (`ACT_REASON_SYSTEM`) — der allerdings über `FESTE_WERTE`
gedeckt ist.

**2. Die profilkritische Prüfung zählte von Hand auf.**
`@pytest.mark.parametrize("art", ["AMB", "IMP", "EMER", "VR"])` — eine
zweite Aufzählung neben dem Katalog, an der einzigen Stelle, die
Katalogeinträge gegen ISiK hält. Ein fünfter Eintrag wäre lautlos hinten
runtergefallen. Jetzt `sorted(ENCOUNTER_CLASSES)`.

**3. Ohne Profilserver wachte niemand.**
`test_jeder_katalogcode_liegt_in_encounterclassde` hängt an der Fixture
`profilserver` und wird **übersprungen**, wenn keiner läuft — in der CI
immer. Gemessen: Ein Katalogeintrag mit `code = "FLD"` (ein Code, den
`EncounterClassDE` ebenso auslässt wie `EMER`) kam offline durch die
gesamte Testreihe. `test_begegnungsarten_stammen_aus_dem_valueset` fängt
das nicht — es prüft gegen `v3-ActEncounterCode`, und dort stehen `FLD`
und `EMER` drin. **Die ISiK-Bindung ist enger als der Standard, und genau
diese Verengung war ungewacht.**
Behoben durch eine festgeschriebene Liste der sechs Codes, die *immer*
läuft, plus einen Servertest, der die Liste gegen die Quelle hält, sobald
ein Server da ist. Die Liste kann damit nicht still veralten.

Alle drei nachgemessen — **ohne** Profilserver, also unter
CI-Bedingungen:

    Systemdreher dgkev -> dkgev                    GEFANGEN
    AUFNAHMEANLASS_SYSTEM nicht im Fingerabdruck   GEFANGEN
    Katalogcode ausserhalb EncounterClassDE (FLD)  GEFANGEN

---

## 4. Konsequenzen

### Positiv

- **Jeder Katalogeintrag ist ISiK-konform.** Vorher galt das für drei von
  vier, und welcher fehlte, hing davon ab, was jemand anforderte.
- Ein Notfall ist weiterhin anforderbar und **inhaltlich reicher als
  vorher**: `IMP` + Aufnahmeanlass sagt mehr als `EMER` allein.
- Die Kontaktarten sind zum ersten Mal **vollständig** vermessen, und der
  Test holt die Sollmenge, statt sie zu behaupten.
- Der Aufnahmeanlass wird gegen den Server geprüft — Code **und**
  Bezeichnung. Ein richtiger Code mit falschem Text ist genau die Sorte
  Fehler, die niemand bemerkt.

### Negativ, bewusst in Kauf genommen

- **`Encounter.class` von Notfällen ändert sich von `EMER` zu `IMP`.**
  Bestehende Aufzeichnungen melden `ABWEICHUNG`. Das ist die vorgesehene
  Wirkung (ADR-006) und derselbe Fall wie bei ADR-015.
- **Schlüssel und Code gehen bei einem Eintrag auseinander.** Das ist eine
  Falle für den nächsten Leser. Abgefedert durch einen ausführlichen
  Docstring und einen Test, der das Auseinandergehen festhält.
- **Ein ambulanter Notfall ist nicht ausdrückbar.** `admitSource` liegt
  unter `hospitalization`, und das meint eine Aufnahme. Wer eine
  Notaufnahme *ohne* stationäre Aufnahme braucht, bekommt hier keine.
  Siehe *Offen*.
- **Der Katalog-Fingerabdruck ändert sich**, weil `EncounterClass` zwei
  Felder mehr hat.

---

## 5. Verworfene Alternativen

| Alternative | Warum verworfen |
|---|---|
| `EMER` ersatzlos streichen | Gemessen: `_begegnungsart` ersetzt ihn durch `AMB` und meldet `erfundene_begegnungsart`. Wer eine Notaufnahme anfordert, bekäme ambulante Kontakte, der Notfall wäre spurlos weg, und die Metrik zählte einen Code als erfunden, den niemand erfunden hat. |
| Auf eine neuere Fassung von `de.basisprofil.r4` warten | Gemessen über 1.5.3, 1.5.4 und 1.6.0: dieselben sechs Codes. Das Fehlen ist Absicht. |
| `EMER` behalten und den Profilfehler dokumentiert in Kauf nehmen | Der Bericht zeigte dann bei jeder Notaufnahme einen Fehler — und ein Fehler, den man erklären muss, wird irgendwann überlesen. |
| Den Notfall über `Encounter.type:KontaktArt` ausdrücken | Gemessen: `kontaktart-de` führt zwölf Codes (teilstationär, Konsil, Operation …) und keinen für einen Notfall. |
| Zusätzlich `extension:Aufnahmegrund` → `VierteStelle = 7` setzen | Funktioniert (gemessen: 0 Fehler, auch auf `AMB`) und wäre der Weg zum ambulanten Notfall. Aber `Aufnahmegrund` ist der **vierstellige Schlüssel nach § 301 SGB V**; nur seine vierte Stelle zu senden, ergäbe einen halben Verwaltungsschlüssel. Für das, was hier gebaut wird — eine stationäre Notaufnahme —, zeigt die Spezifikation ausdrücklich auf `admitSource`. Aufgenommen unter *Offen*, weil es die Lösung für den ambulanten Fall wäre. |
| `Encounter.priority` benutzen | Sagt die Dringlichkeit der *Behandlung*, nicht den Anlass der Aufnahme. ISiK profiliert das Feld nicht, es wäre also ungeprüft — und ein ungeprüftes Feld ist in diesem Projekt kein Fortschritt. |
| Die Zuordnung EMER → IMP+N in `baue_encounter` schreiben | Dann stünde dort eine zweite Aufzählung neben dem Katalog, und beim nächsten Eintrag würde sie vergessen. Fünfmal in diesem Projekt passiert. Der Katalog entscheidet, die Vorlage führt aus. |

---

## 6. Offen

- **Der ambulante Notfall.** `hospitalization.admitSource` setzt eine
  Aufnahme voraus — das ISiK-Profil sagt wörtlich „Anlass der stationären
  Aufnahme". Eine Notaufnahme, aus der der Patient wieder nach Hause geht,
  wäre `AMB`, und dort passte der Anlass nicht.
  **Der Weg ist inzwischen gemessen:** `extension:Aufnahmegrund` mit
  `VierteStelle = 7` („Notfall") validiert auch auf einem `AMB`-Kontakt
  fehlerfrei. Offen ist nicht mehr das *Ob*, sondern ob ein halber
  § 301-Schlüssel (nur die vierte Stelle, ohne die ersten drei) in
  Testdaten vertretbar ist. Das ist eine fachliche Frage, keine
  technische.
- **`Encounter.type:KontaktArt` bleibt ungenutzt.** Zwölf Codes, die
  Testdaten reicher machen könnten (`normalstationaer`,
  `intensivstationaer`, `tagesklinik` …). Eigene Entscheidung, eigener
  Aufwand.
- **Die übrigen Codes von `EncounterClassDE`** — `HH`, `SS`, `PRENC` —
  stehen nicht im Katalog. Sie wären ohne Risiko aufnehmbar, weil das
  ValueSet sie führt; gebraucht hat sie bisher niemand.
