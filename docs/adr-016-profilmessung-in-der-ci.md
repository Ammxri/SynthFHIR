# ADR-016: Die Profilmessung als Auflage der CI — und was sie nicht verspricht

| | |
|---|---|
| **Status** | Angenommen und umgesetzt (2026-09-01) |
| **Datum** | 2026-09-01 |
| **Phase** | 3 (Vision) |
| **Betrifft** | `.github/workflows/ci.yml`, `tests/conftest.py`, `docker-compose.yml`, `docs/belege/docker-compose.isik.yml` |
| **Baut auf** | ADR-002, ADR-009 |

---

## 1. Kontext

Die Fixture `profilserver` in `tests/conftest.py` begründet ihren
Übersprung so:

> Anders als bei `hapi` ist ein fehlender Server hier standardmäßig ein
> Übersprung und **kein** Fehlschlag, auch nicht in der CI: Die
> Profilmessung ist nach ADR-002 keine Produktzusage, sondern eine
> Sondierung. Sie zur Auflage zu machen hieße, ein Versprechen zu geben,
> über das noch gar nicht entschieden ist.

Der Satz ist richtig — und er deckt zwei verschiedene Dinge zu.

Eine gegnerische Durchsicht am 2026-09-01 hat gemessen, was er in der
Praxis bedeutet: **Von den 84 übersprungenen Tests eines normalen Laufs
entfallen 6 auf `test_profil.py`.** Der gesamte Servermesspfad von
`profil.py` — `$validate`, die Einstufung gegen echte HAPI-Meldungen, der
Nachweis „0 Fehler" — läuft in der CI nie. Genau in diesem Pfad fanden sich
danach drei Wege, auf denen der Zähler zu niedrig zählen konnte.

Seither hat sich die Lage in zwei Richtungen verändert:

**Die Lücke ist kleiner geworden.** Die Einstufungslogik und die
Netzpfad-Zweige laufen seit dem 2026-09-01 ohne Container, mit einer
Attrappe der Sitzung. Was container-gebunden bleibt, ist die Messung von
Ende zu Ende.

**Und sie ist an einer Stelle grösser geworden.** Die Negativkontrolle
`test_isik_con1_wird_ueberhaupt_noch_gefunden` braucht den Container. Sie
wurde gebaut, weil der Abwesenheitstest daneben ohne sie nichts aussagt —
gegen einen Server ohne die ISiK-Pakete meldeten 11 Fehler, dass gar nichts
geprüft wurde, und `assert "isik-con1" not in alle` war zufrieden. Heute
läuft in der CI **weder die Messung noch ihre Kontrolle**.

---

## 2. Entscheidung

**`SYNTHFHIR_REQUIRE_PROFIL=1` wird in der CI gesetzt**, und der Workflow
startet den ISiK-Profilserver als zweiten Service-Container.

Zwei Bedingungen gehören untrennbar dazu:

1. **Vorher wird das HAPI-Image festgenagelt.** Ohne das hinge ein Gate an
   einer Version, die sich unter der Hand ändert. Siehe unten.
2. **Die Begründung der Fixture wird berichtigt.** Sie sagt heute, was der
   Schalter verspräche; sie muss sagen, was er sichert.

Was der Schalter sichert, in einem Satz:

> Die fünf Felder und die strukturelle Zusage aus ADR-009 dürfen nicht
> stillschweigend zurückgehen.

Was er **nicht** verspricht:

> Dass SynthFHIR ISiK-konform ist, dass es das behauptet, oder dass über
> das Gate der Phase 3 entschieden wäre.

---

## 3. Begründung

### Zwei Dinge, die vermengt waren

**Unentschieden ist**, ob SynthFHIR ISiK-Konformität *bewirbt*. Das Gate
der Phase 3 verlangt „Nachweisbare Nachfrage aus der Nische", und die hat
niemand gemessen — `docs/sondierung-isik.md` sagt das ausdrücklich als
Argument dagegen. Auch die offene Frage aus jenem Dokument, ob ein
Profilmodus oder die Felder immer, ist offen. Daran ändert eine CI-Zeile
nichts.

**Entschieden ist dagegen ADR-009.** Die fünf Felder sind gebaut, die
strukturelle Zusage — jede kodierte Diagnose nennt ihren Kontakt — ist im
Bauweg verankert, und beides ist ausgeliefert. Es ist keine Sondierung
mehr, sondern Bestand.

Und dieser Bestand ist ungeschützt. Wer morgen `Encounter.type` entfernt
oder die Automatik in `templates.py` herausnimmt, bekommt eine grüne Suite.
Der Schalter schafft also kein neues Versprechen; er sichert eines, das es
schon gibt.

### Der Präzedenzfall steht im Haus

`SYNTHFHIR_REQUIRE_HAPI=1` ist längst gesetzt, mit einer Begründung, die
hier wörtlich zutrifft: Die Strukturvalidierung prüft Codes nicht, nur der
Katalogtest gegen HAPI tut das; fällt er aus, prüft die CI etwas anderes
als gemeint. Für ADR-009 gilt dasselbe — die Laufzeitprüfung sieht die
ISiK-Slices nicht.

### Was es kostet, gemessen

**Service-Container in GitHub Actions starten parallel.** Ein zweiter HAPI
verdoppelt die Wartezeit nicht; er kostet die Differenz.

Gemessen am 2026-09-01, lokal, beide auf `v8.10.0-3`:

| | bereit nach |
|---|---|
| `hapiproject/hapi` ohne Pakete | **53,18 s** |
| derselbe mit zwei ISiK-Paketen | 56,01 s |
| derselbe mit **vier** (Basismodul, Vitalparameter, Medikation, Basisprofile) | **57,33 s** |

**Der Aufschlag beträgt gut vier Sekunden.** Das ist deutlich weniger, als
die Formulierung „lädt vier Pakete" vermuten lässt, und es entscheidet die
Frage: Der zweite Container kostet in der CI praktisch nichts, weil er
parallel startet und das Laden im Anlauf des Servers untergeht. Die
Wartezeit bleibt die des langsameren von beiden.

Die mittlere Zeile ist der Stand vor ADR-014, als der Messaufbau nur das
Basismodul lud. Sie steht hier, weil sie zeigt, wie flach die Kurve ist:
Zwei zusätzliche Pakete kosten gut eine Sekunde.

Die Zahl stand in der ersten Fassung dieses ADR als offene Lücke — der
Messcontainer war zum Zeitpunkt der Niederschrift nicht mehr vorhanden. Sie
ist vor der Umsetzung nachgeholt worden, und sie hat die Entscheidung
bestätigt statt sie umzustossen. Wäre sie in der Grössenordnung von
Minuten ausgefallen, wäre der nächtliche Lauf aus Abschnitt 5 die bessere
Antwort gewesen.

### Die Vorbedingung: erst festnageln

`docker-compose.yml` benutzt `hapiproject/hapi:latest`, und sein eigener
Kommentar sagt, warum das nicht bleiben soll:

> Reproduzierbarkeit: `latest` kann sich zwischen Messreihen ändern und
> damit das Validierungsverhalten verschieben. Sobald eine Version läuft,
> sollte sie festgenagelt werden.

Für ein CI-Gate wiegt das schwerer als für eine Messreihe. Die Sondierung
hat gezeigt, dass die Einstufung am **Wortlaut** der HAPI-Meldungen hängt:
Die acht ungeprüften Befunde bleiben nur deshalb ungeprüft, weil HAPI die
Expansionsklage wörtlich in den angehängten `error message = …` wiederholt.
Ändert HAPI diese Verschachtelung, wandert der Bericht — und mit gesetztem
Schalter färbte er die CI rot, aus einem Grund, der nichts mit dem Code zu
tun hat.

`latest` zeigt am 2026-09-01 auf `v8.10.0-3`. Das ist der naheliegende
Kandidat, und beide Compose-Dateien sollten dieselbe Version tragen.

> **Nachtrag.** Diese Vorbedingung war beim Zusammenführen bereits
> erfüllt: Die Arbeit an den ISiK-Modulen hat dasselbe Bedürfnis gehabt
> und dieselbe Fassung festgenagelt — „Mit `:latest` misst der nächste
> Lauf gegen ein anderes Werkzeug, ohne dass es im Bericht steht." Zwei
> Wege, dieselbe Begründung. Geblieben ist die Fassung von dort; dieses
> ADR trägt nur den zusätzlichen Grund nach, dass an derselben Version
> jetzt auch ein Gate hängt.
>
> Nachgezogen werden musste dafür der **Workflow**: Er startete den
> Profilserver zunächst mit zwei Paketen, während der Messaufbau seit
> ADR-014 vier lädt. Eine CI, die gegen einen anderen Aufbau misst als
> der dokumentierte Befehl, prüft etwas anderes als sie behauptet — und
> das ist genau die Fehlerklasse, gegen die dieses ADR antritt. Beide
> Listen sind jetzt deckungsgleich, und der Kommentar über dem Dienst
> sagt, dass sie es bleiben müssen.

---

## 4. Konsequenzen

### Positiv

- **ADR-009 ist gegen stille Rückschritte gesichert.** Die fünf Felder,
  die Kontaktebene und die strukturelle Zusage werden bei jedem Lauf
  gemessen statt behauptet.
- **Die Negativkontrolle läuft.** Ohne sie ist der Abwesenheitstest
  daneben eine Selbstbestätigung; mit ihr ist er eine Aussage.
- **Der Beleg bleibt aktuell.** Ein Auseinanderlaufen von
  `docs/belege/isik-profilbericht.json` und der Wirklichkeit fällt beim
  nächsten Lauf auf statt bei der nächsten Durchsicht.
- **Reproduzierbarkeit steigt** — die Vorbedingung ist ohnehin überfällig
  und wirkt auch auf den Katalogtest.

### Negativ, bewusst in Kauf genommen

- **Ein zweiter Container in der CI**, mit zwei zusätzlichen Paketen.
  Parallel gestartet, aber nicht kostenlos.
- **Ein HAPI-Update kann die CI rot färben**, ohne dass sich der Code
  geändert hat. Das Festnageln verschiebt diesen Fall auf den Zeitpunkt,
  an dem jemand die Version hochsetzt — und dort gehört er hin.
- **Die Grenze zwischen „gesichert" und „versprochen" muss erklärt
  bleiben.** Ein grünes Gate liest sich leicht als Konformitätsnachweis.
  Deshalb steht der Satz, was der Schalter nicht verspricht, in diesem ADR,
  in der Fixture und im Kopf des Workflows — an allen drei Stellen, an
  denen jemand darauf stösst.
- **Die CI hängt jetzt an einem fremden Paketregister.** Beim Messen im
  Protokoll gesehen: Der Server lädt die Pakete beim Start von
  `packages2.fhir.org`. Ist das Register nicht erreichbar, fährt der
  Profilserver ohne Profile hoch — und seit dem 2026-09-01 bricht die
  Messung dann ab, statt eine Zahl zu liefern (`_PROFIL_UNBEKANNT` in
  `profil.py`). Das ist die richtige Richtung für einen Fehler, macht die
  CI aber von einem Dienst abhängig, über den das Projekt keine Kontrolle
  hat. Ein vorgehaltener Paketspiegel wäre die Antwort, falls das je
  stört; heute wäre er Aufwand ohne belegten Anlass.

---

## 5. Verworfene Alternativen

**Beim Übersprung bleiben.** Die heutige Lage: Weder Messung noch
Kontrolle laufen. Verworfen, weil sie eine bereits getroffene Entscheidung
ungeschützt lässt und die Begründung dafür eine andere Frage beantwortet.

**Ein eigener nächtlicher Workflow.** Trennte Messung und Prüfkette sauber,
meldete einen Rückschritt aber erst nach dem Merge — und niemand liest
nächtliche Läufe zuverlässig. Der Zweck ist, den Rückschritt zu
*verhindern*, nicht ihn zu protokollieren.

**Nur die container-freien Tests als Absicherung nehmen.** Sie decken seit
dem 2026-09-01 die Einstufungslogik und die Netzpfad-Zweige ab, aber
naturgemäss nicht die Frage, ob die erzeugten Ressourcen das Profil noch
erfüllen. Genau das ist die Zusage von ADR-009.

**Den Schalter setzen, ohne festzunageln.** Verworfen: Ein Gate auf
`latest` ist ein Gate auf ein bewegliches Ziel, und die Sondierung hat
gezeigt, wie beweglich es ist.

---

## 6. Offen

- **Das Gate der Phase 3 bleibt offen.** Nachfrage ist weiterhin nicht
  gemessen, und dieses ADR misst sie nicht.
- **Die ISiK-Stufe ist weiterhin nicht entschieden.** Gemessen wird gegen
  4.0.3; tragend ist derzeit Stufe 3 mit anderen kanonischen URLs. Ein
  gesetztes Gate zementiert die heutige Wahl ein Stück weit — es sollte
  nicht als Entscheidung darüber gelesen werden.
- **Observation und MedicationStatement** bleiben ungeprüft, solange die
  Module für Vitalparameter und Medikation nicht geladen sind. Der Bericht
  weist das aus; das Gate ändert daran nichts.
