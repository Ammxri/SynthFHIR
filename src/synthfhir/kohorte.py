"""Große Kohorten durch stückweise Erzeugung (Phase 2).

Das Gate-Kriterium der Phase 2 lautet „stabile Validität bei größeren
Kohorten". Ein einzelner LLM-Aufruf trägt das nicht: Gemessen am
2026-08-28 schöpften 25 Patienten mit je zwei Messwerten bereits 84,9 %
der Token-Obergrenze aus. Hunderte gehen nur in Teilen.

===========================================================================
WAS BEIM STÜCKELN SCHIEFGEHEN KANN
===========================================================================

**Kennungen kollidieren.** Die Vorlagen vergeben vorläufige Kennungen ab
`tmp-pat-0`. Ohne Versatz begänne jeder Teil wieder bei null; zwei
aneinandergehängte Teile trügen dieselben Kennungen, und die Verweise des
zweiten Teils zeigten auf Patienten des ersten. Nachgestellt ergibt das
vier kaputte Referenzen — die Integritätsprüfung meldet sie, aber erst
nachdem der Schaden entstanden ist. Deshalb bekommt jeder Teil einen
`index_versatz`.

**IDs werden zu früh vergeben.** `assign_ids` läuft **einmal über die
gesamte Kohorte**, nicht je Teil. Liefe es je Teil, hätte jeder Teil wieder
`pat-001` — dasselbe Problem eine Ebene höher.

**Ein Teil fällt aus.** Nach dem Grundsatz aus Phase 0 darf ein einzelner
Fehlschlag die Reihe nicht abbrechen. Ein gescheiterter Teil wird
protokolliert, die übrigen laufen weiter, und die Mengentreue weist die
Lücke aus. Ein halb geliefertes Ergebnis ist ehrlicher als gar keines —
solange sichtbar ist, dass es halb ist.

**Alle Teile ähneln einander.** Das Modell sieht die anderen Teile nicht
und greift ohne Hinweis auf dieselben Namen zurück. Der Prompt streut
dagegen; wie gut, misst `Kohortenergebnis.namensvielfalt`.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable

from .domain.identity import assign_ids
from .domain.integrity import IntegrityReport, check_resources
from .domain.templates import (
    FALLBACK_NACHNAME,
    Beanstandung,
    baue_aus_parametern,
    baue_bundle,
)
from .generation import Verstanden, _lies_verstanden
from .llm import LLMAntwort, LLMClient, LLMFehler
from .parsing import JsonExtractionError, extract_json
from .prompts import baue_teil_prompt
from .validation import Pruefergebnis, pruefe_alle

# Voreinstellung je Teil, hergeleitet statt geraten. Gemessen am 2026-08-30,
# nachdem Encounter und MedicationStatement hinzukamen:
#
#   Ausgabe je Patient          504 Token   (vorher rund 276 mit drei Typen)
#   max_tokens im Gratistarif  4500         (8000/Minute minus Prompt,
#                                            mit Spielraum gewählt)
#   ergibt rechnerisch            8,9 Patienten   (4500 / 504)
#   gewählt mit Reserve           8         — Patienten mit mehreren
#                                             Diagnosen kosten mehr
#
# Hier stand „9,5". Die Zahl stammte noch von `max_tokens = 4800` und ist
# mit der Senkung auf 4500 nicht mitgewandert — eine Herleitung, die ihr
# eigenes Ergebnis nicht mehr stützte. Sie ist folgenlos geblieben, weil
# die gewählte 8 ohnehin darunter liegt, aber eine Herleitung, die man
# nicht nachrechnen kann, ist keine.
#
# Der Wert stand vorher auf 15 und trug drei Ressourcentypen. Genau diese
# Abhängigkeit hatte ADR-004 als offenen Punkt vermerkt: „Ob die Teilgröße
# von 15 auch bei Ressourcentypen jenseits der heutigen drei trägt." Sie
# trug nicht — der erste Lauf nach der Erweiterung scheiterte an HTTP 413.
#
# Wer ein größeres Kontingent hat, setzt `teilgroesse` höher: Die Grenze ist
# der Tarif, nicht das Modell.
TEILGROESSE = 8

# Wartezeit zwischen zwei Versuchen desselben Teils. Ohne sie ist der zweite
# Versuch bei den beiden häufigsten Ursachen sinnlos: Eine Ratengrenze steht
# noch, und ein Namensauflösungsfehler kommt sofort zurück — gemessen am
# 2026-08-29 verbrannte ein Teil so beide Versuche in unter einer Sekunde.
WARTEZEIT_NACH_FEHLSCHLAG_S = 15.0

# Fehlerarten, bei denen ein zweiter Versuch nicht helfen kann: ein
# abgelehnter Schlüssel bleibt abgelehnt, ein fehlender Zugang fehlt weiter,
# und eine fehlende Konfiguration konfiguriert sich nicht von selbst.
#
# `kontingent` und `verbindung` stehen bewusst NICHT hier — bei beiden ist
# Warten genau die richtige Antwort.
#
# Ohne diese Unterscheidung behandelte der Kohortenweg alles gleich:
# `except LLMFehler as exc: letzter_fehler = str(exc)` behielt nur den Satz
# und warf `exc.art` weg. Ein falscher Schlüssel mahlte damit durch alle
# Teile — bei `-n 200 --pause 60` waren das 25 Teile mal 60 s Pause plus
# 15 s Wiederholpause, also rund 31 Minuten garantiert erfolgloser Aufrufe,
# bevor „0 von 200 Patienten" herauskam. `generation.py` macht es an
# derselben Stelle richtig und behält `exc.art`.
ENDGUELTIG = frozenset({"abgelehnt", "kein_zugriff", "nicht_konfiguriert"})

# Der Ersatznachname aus `baue_patient`: `FALLBACK_NACHNAME` plus globalem
# Patientenindex. Siehe `namensvielfalt` — er ist je Patient verschieden und
# täuschte damit Vielfalt vor, wo das Modell gar keine Namen geliefert hat.
_ERSATZNACHNAME = re.compile(rf"^{re.escape(FALLBACK_NACHNAME)}\d+$")

Fortschritt = Callable[[int, int, str], None]


def _warte(sekunden: float) -> None:
    """Eigene Funktion, damit Tests sie ersetzen können.

    Ein durchgereichter Parameter hätte die Signatur aufgebläht, und
    `time.sleep` global zu verbiegen träfe auch alles andere.
    """
    if sekunden > 0:
        time.sleep(sekunden)


@dataclass(frozen=True)
class TeilParameter:
    """Was ein Teil dem Bau beigesteuert hat.

    `angefragt` gehört dazu: `baue_aus_parametern` bekommt es als
    Sollmenge, und ohne sie liefe eine Wiedergabe mit einer anderen
    Erwartung als der ursprüngliche Lauf.
    """

    angefragt: int
    parameter: dict

    def to_dict(self) -> dict:
        return {"angefragt": self.angefragt, "parameter": self.parameter}

    @classmethod
    def from_dict(cls, d: dict) -> "TeilParameter":
        """Liest einen Teil und prüft dabei die Form.

        Ohne diese Prüfung kam `{"angefragt": 1, "parameter": "hallo"}`
        unbeanstandet durch und stürzte erst viel später in
        `baue_aus_parametern` mit `AttributeError: 'str' object has no
        attribute 'get'` ab — auf der Kommandozeile als Traceback, über
        das Netz als HTTP 500 für sechzig Bytes Eingabe.

        Die Meldungen nennen den empfangenen **Typ**, nie den Wert:
        `int("GEHEIM-XY")` schrieb ihn wörtlich in die Ausnahme, und die
        wandert bis in den Antwortkörper.
        """
        if not isinstance(d, dict):
            raise ValueError(f"Teil ist kein Objekt, sondern {type(d).__name__}.")
        parameter = d.get("parameter")
        if not isinstance(parameter, dict):
            raise ValueError(
                f"'parameter' ist kein Objekt, sondern {type(parameter).__name__}."
            )
        angefragt = d.get("angefragt")
        if isinstance(angefragt, bool) or not isinstance(angefragt, int):
            raise ValueError(
                f"'angefragt' ist keine ganze Zahl, sondern "
                f"{type(angefragt).__name__}."
            )
        return cls(angefragt=angefragt, parameter=parameter)


@dataclass
class Teilergebnis:
    """Was ein einzelner Teil geliefert hat."""

    nummer: int
    angefragt: int
    geliefert: int = 0
    fehler: str | None = None
    # Die Art des Fehlers, aus `LLMFehler.art` — wie bei `Ergebnis` in
    # `generation.py`. `fehler` ist ein Satz für Menschen; wer daraus eine
    # Entscheidung ableiten will, müsste ihn zerlegen.
    fehlerart: str | None = None
    dauer_s: float = 0.0

    @property
    def erfolgreich(self) -> bool:
        return self.fehler is None and self.geliefert > 0

    def to_dict(self) -> dict:
        return {
            "nummer": self.nummer,
            "angefragt": self.angefragt,
            "geliefert": self.geliefert,
            "erfolgreich": self.erfolgreich,
            "fehler": self.fehler,
            "dauer_s": round(self.dauer_s, 2),
        }


@dataclass
class Kohortenergebnis:
    """Ergebnis einer stückweise erzeugten Kohorte."""

    beschreibung: str
    angefragt: int
    ressourcen: list[dict] = field(default_factory=list)
    bundle: dict | None = None
    teile: list[Teilergebnis] = field(default_factory=list)
    beanstandungen: list[Beanstandung] = field(default_factory=list)
    validierung: list[Pruefergebnis] = field(default_factory=list)
    integritaet: IntegrityReport | None = None
    nicht_abbildbar: list[str] = field(default_factory=list)
    llm_antworten: list[LLMAntwort] = field(default_factory=list)
    # Die Parameterobjekte, aus denen tatsächlich gebaut wurde — je Teil,
    # in Reihenfolge. Nicht dasselbe wie `llm_antworten`: dort stehen auch
    # verworfene Versuche. Dies hier ist der Beitrag des Modells zum
    # Ergebnis, und damit alles, was eine Aufzeichnung braucht.
    parameter: list[TeilParameter] = field(default_factory=list)
    # Der Name des Szenarios, falls die Kohorte aus einer Vorlage stammt
    # (ADR-016). Gegenstueck zu `Ergebnis.szenario` auf der Weboberflaeche.
    #
    # Ohne dieses Feld beschrieb `--szenario ... --bericht b.json` einen
    # Modelllauf, den es nie gab: `teile` mit einem Eintrag, `dauer_s: 0.0`
    # und null Token - nachgemessen. Wer den Bericht liest, muss erkennen
    # koennen, dass hier nichts gefragt wurde.
    szenario: str | None = None

    # Die Art des Fehlers, an dem der Lauf endgültig gescheitert ist — wie
    # bei `Ergebnis` in `generation.py`. `Kohortenergebnis` hatte weder
    # `fehler` noch `fehlerart`; keine Schicht darüber konnte einen
    # abgelehnten Schlüssel von einem stummen Modell unterscheiden.
    fehlerart: str | None = None
    # Nach welchem Teil abgebrochen wurde, oder None, wenn alle liefen.
    # Ohne diese Angabe sähe eine abgebrochene Kohorte aus wie eine, die
    # vollständig durchlief und nichts fand.
    abgebrochen_nach: int | None = None

    # -- die Zusage, unverändert aus Phase 1 --------------------------------
    @property
    def fertig(self) -> bool:
        """Darf ausgeliefert werden? (US-2 AC2)"""
        return (
            bool(self.ressourcen)
            and all(e.valide for e in self.validierung)
            and self.integritaet is not None
            and self.integritaet.ok
        )

    @property
    def patienten(self) -> int:
        return sum(1 for r in self.ressourcen if r.get("resourceType") == "Patient")

    @property
    def mengentreue(self) -> float:
        """Gelieferte gegen angefragte Patienten.

        Das entscheidende Kriterium aus Phase 0 — hier auf Kohortenebene.
        Ein ausgefallener Teil senkt diesen Wert sichtbar, statt sich zu
        verstecken.
        """
        return self.patienten / self.angefragt if self.angefragt else 0.0

    @property
    def namensvielfalt(self) -> float:
        """Anteil eindeutiger Namen unter den Patienten.

        Misst, ob die Teile sich tatsächlich unterscheiden. Ein Wert nahe 1
        heißt: kaum Wiederholungen. Sinkt er, produziert das Modell über die
        Teile hinweg dieselben Personen, und die Kohorte ist als Testdaten
        weniger wert.

        **Gemessen wird, was das Modell geliefert hat.** Fehlt ein Name,
        setzt `baue_patient` einen Ersatz, und der trägt den globalen
        Patientenindex (`Testperson1`, `Testperson2`, …). Gezählt wurde
        damit die Eindeutigkeit, die der CODE hergestellt hat: 30 Patienten
        ganz ohne Namen ergaben `namensvielfalt = 1.0` — den Bestwert im
        denkbar schlechtesten Fall, und in der Zusammenfassung stand
        „Namensvielfalt: 100.0%" für eine Kohorte, die als Testdaten
        wertlos ist. Zum Vergleich: 30-mal derselbe echte Name ergab
        korrekt 0,033.

        Alle Ersatznamen zählen deshalb als **ein** Name.
        """
        namen = []
        for r in self.ressourcen:
            if r.get("resourceType") != "Patient":
                continue
            eintrag = (r.get("name") or [{}])[0]
            vorname = " ".join(eintrag.get("given") or [])
            nachname = eintrag.get("family", "")
            if _ERSATZNACHNAME.match(nachname):
                nachname = FALLBACK_NACHNAME
            namen.append(f"{vorname} {nachname}")
        return len(set(namen)) / len(namen) if namen else 0.0


    @property
    def mengengrenze_gegriffen(self) -> bool:
        """Hat die Mengengrenze Ressourcen verworfen?

        Ohne diese Eigenschaft wäre die Grenze **still**: `mengentreue`
        zählt nur Patienten, `fertig` sieht Beanstandungen gar nicht an.
        Ein Lauf, der 19.921 Messwerte verwirft, meldete sonst
        „Mengentreue 100 %" und Rückgabewert 0.

        Präfix statt Aufzählung — derselbe Grund wie bei
        `erfundene_codes`: Mit `mengengrenze_bauaufruf` kam eine zweite
        Art hinzu, und eine Aufzählung von Hand hätte sie übersehen.
        """
        return any(b.art.startswith("mengengrenze") for b in self.beanstandungen)

    @property
    def erfundene_codes(self) -> int:
        return sum(
            1
            for b in self.beanstandungen
            # Präfix statt Aufzählung: Mit Phase 2 kamen zwei weitere
            # Arten hinzu, und eine Aufzählung von Hand hätte sie
            # übersehen — die Metrik meldete dann zwei von vier.
            if b.art.startswith("erfunden")
        )

    @property
    def ausgabe_token(self) -> int:
        return sum(a.ausgabe_token for a in self.llm_antworten)

    @property
    def eingabe_token(self) -> int:
        return sum(a.eingabe_token for a in self.llm_antworten)

    @property
    def anzahl_je_typ(self) -> dict[str, int]:
        zaehler: dict[str, int] = {}
        for r in self.ressourcen:
            typ = str(r.get("resourceType") or "?")
            zaehler[typ] = zaehler.get(typ, 0) + 1
        return zaehler

    def to_dict(self) -> dict:
        return {
            "beschreibung": self.beschreibung,
            "fertig": self.fertig,
            "szenario": self.szenario,
            "angefragt": self.angefragt,
            "patienten": self.patienten,
            "mengentreue": round(self.mengentreue, 4),
            "namensvielfalt": round(self.namensvielfalt, 4),
            "ressourcen": self.anzahl_je_typ,
            "erfundene_codes": self.erfundene_codes,
            # Alle Beanstandungen, nicht nur ihre Zählung.
            #
            # `erfundene_codes` zählt Beanstandungen mit dem Präfix
            # `erfunden*`. Die übrigen Arten — `ungueltiges_datum`,
            # `ungueltiges_geschlecht`, `ungueltiger_messwert`,
            # `mengenabweichung`, `fehlendes_feld` — wurden gesammelt und
            # hier weggeworfen. Sie erschienen weder in `--bericht` noch in
            # der Zusammenfassung, obwohl `Ergebnis.to_dict()` beim
            # Einzellauf sie mitführt: dieselbe Frage, zwei Antworten.
            #
            # Praktische Folge: Ein Teil, dessen Antwort `{"patienten": []}`
            # war, meldete „Teil 2 ausgefallen: None", und die einzige
            # Erklärung stand in dieser verworfenen Liste.
            "beanstandungen": [b.to_dict() for b in self.beanstandungen],
            "nicht_abbildbar": self.nicht_abbildbar,
            "fehlerart": self.fehlerart,
            "abgebrochen_nach": self.abgebrochen_nach,
            "teile": [t.to_dict() for t in self.teile],
            "integritaet": self.integritaet.to_dict() if self.integritaet else None,
            "eingabe_token": self.eingabe_token,
            "ausgabe_token": self.ausgabe_token,
        }


def generiere_kohorte(
    client: LLMClient,
    beschreibung: str,
    anzahl: int,
    *,
    teilgroesse: int = TEILGROESSE,
    versuche_je_teil: int = 2,
    pause_s: float = 0.0,
    fortschritt: Fortschritt | None = None,
) -> Kohortenergebnis:
    """Erzeugt eine Kohorte beliebiger Größe in Teilen.

    `fortschritt` wird nach jedem Teil mit (Teilnummer, Gesamtzahl, Text)
    aufgerufen — für eine Kommandozeilenanzeige, damit ein Lauf über zehn
    Minuten nicht stumm dasteht.

    `pause_s` taktet die Teile. Anbieter rechnen `max_tokens` in die
    Anfragegröße ein; bei einem Kontingent von 8000 Token je Minute trägt
    ein Teil mit 5600 reservierten Ausgabe-Token knapp einen Aufruf pro
    Minute. Am 2026-08-29 lieferte ein ungetakteter Lauf über 200 Patienten
    genau vier Teile, dann stand die Ratengrenze. Ohne Kontingentsorgen
    bleibt der Wert bei 0.
    """
    ergebnis = Kohortenergebnis(beschreibung=beschreibung, angefragt=anzahl)
    if anzahl < 1:
        return ergebnis

    aufteilung = _teile(anzahl, teilgroesse)
    gesamt = len(aufteilung)
    gebaute: list[dict] = []
    versatz = 0

    for nummer, menge in enumerate(aufteilung, start=1):
        if nummer > 1:
            _warte(pause_s)

        teil = Teilergebnis(nummer=nummer, angefragt=menge)
        beginn = time.perf_counter()

        parameter = _hole_teil(client, beschreibung, menge, nummer, gesamt,
                               versuche_je_teil, teil, ergebnis)
        if parameter is not None:
            versatz = _verarbeite_teil(
                TeilParameter(angefragt=menge, parameter=parameter),
                versatz, teil, ergebnis, gebaute,
            )

        teil.dauer_s = time.perf_counter() - beginn
        ergebnis.teile.append(teil)
        if fortschritt:
            stand = teil.fehler or f"{teil.geliefert}/{menge} Patienten"
            fortschritt(nummer, gesamt, stand)

        if teil.fehlerart in ENDGUELTIG:
            # Nicht weiterlaufen. Was den ersten Teil abgewiesen hat, weist
            # auch den fünfundzwanzigsten ab; jeder weitere Durchgang
            # kostete nur `pause_s` und lieferte dasselbe Nichts.
            ergebnis.fehlerart = teil.fehlerart
            ergebnis.abgebrochen_nach = nummer
            break

    return _schliesse_ab(ergebnis, gebaute)


# --- Der Bauweg, einmal für Erzeugung und Wiedergabe ------------------------
#
# Beide Wege müssen durch dieselben Funktionen laufen. Zwei getrennte
# Bauwege liefen mit der Zeit auseinander, und die Wiedergabe lieferte
# stillschweigend etwas anderes als der aufgezeichnete Lauf — ohne dass
# irgendein Test das bemerkte.


def _verarbeite_teil(
    teilparameter: TeilParameter,
    versatz: int,
    teil: Teilergebnis,
    ergebnis: Kohortenergebnis,
    gebaute: list[dict],
) -> int:
    """Baut einen Teil ein und gibt den neuen Versatz zurück."""
    verstanden = _lies_verstanden(teilparameter.parameter)
    for luecke in verstanden.nicht_abbildbar:
        if luecke not in ergebnis.nicht_abbildbar:
            ergebnis.nicht_abbildbar.append(luecke)

    bau = baue_aus_parametern(
        teilparameter.parameter,
        # Null ist keine Erwartung, sondern das Fehlen einer. Beim
        # stückweisen Erzeugen kann das nicht vorkommen — Teile sind
        # immer mindestens eins gross. Beim Einzellauf der Weboberfläche
        # schon: Liest das Modell keine Patientenzahl zurück, gibt es
        # nichts zu vergleichen, und `{"patienten": 0}` erzeugte eine
        # Mengenbeanstandung gegen eine Zahl, die nie jemand verlangt hat.
        {"patienten": teilparameter.angefragt} if teilparameter.angefragt else {},
        index_versatz=versatz,
    )
    ergebnis.beanstandungen.extend(bau.beanstandungen)
    gebaute.extend(bau.ressourcen)
    ergebnis.parameter.append(teilparameter)
    teil.geliefert = sum(
        1 for r in bau.ressourcen if r.get("resourceType") == "Patient"
    )
    if teil.geliefert == 0 and teil.fehler is None:
        # Der Teil ist nicht am Aufruf gescheitert, sondern an der Antwort:
        # Das Modell hat geantwortet, `_hole_teil` hat das Feld `patienten`
        # gefunden — es war nur leer oder unbrauchbar. Ohne diese Zeile
        # stand im Bericht „Teil N ausgefallen: None" und im JSON
        # `{"erfolgreich": false, "fehler": null}`, während die Erklärung
        # nur in den Beanstandungen lag.
        teil.fehler = next(
            (b.detail for b in bau.beanstandungen),
            "Das Modell hat keine verwertbaren Patienten geliefert.",
        )
        teil.fehlerart = "unbrauchbar"
    # Der Versatz wächst um die verbrauchten KENNUNGSPLÄTZE, nicht um die
    # Zahl der gebauten Patienten und nicht um die angefragte Menge.
    #
    # Die drei Zahlen sind meist gleich und gingen genau dann auseinander,
    # wenn ein Eintrag der Liste kein Objekt ist: `baue_aus_parametern`
    # überspringt ihn, sein Platz ist über `enumerate` aber vergeben.
    # Vorher wuchs der Versatz um `teil.geliefert` — ein einziges `null` in
    # der Modellantwort genügte, damit der nächste Teil auf schon
    # vergebenen `tmp-pat-*` begann. Nachgestellt mit 6 Patienten und
    # `teilgroesse=3`: sechs kaputte Verweise, ein doppelter Identifier
    # SYN-0003, `integritaet.ok = False` — die GESAMTE Kohorte fiel wegen
    # eines Ausreissers durch, und die einzige Spur war eine Beanstandung,
    # die im Bericht gar nicht auftauchte.
    #
    # Angefragt wäre die falsche Zahl in die andere Richtung: Liefert das
    # Modell weniger als verlangt, entstünden Lücken in den Kennungen. Die
    # schaden nicht, machen die Artefakte aber unnötig schwer lesbar.
    return versatz + max(bau.plaetze_belegt, 1)


def _schliesse_ab(ergebnis: Kohortenergebnis, gebaute: list[dict]) -> Kohortenergebnis:
    """Normalisiert, prüft und bündelt — einmal über die GESAMTE Kohorte."""
    if not gebaute:
        return ergebnis
    normalisiert = assign_ids(gebaute)
    ergebnis.ressourcen = normalisiert.resources
    ergebnis.validierung = pruefe_alle(ergebnis.ressourcen)
    ergebnis.integritaet = check_resources(ergebnis.ressourcen)
    ergebnis.bundle = baue_bundle(ergebnis.ressourcen)
    return ergebnis


def baue_aus_aufzeichnung(
    beschreibung: str,
    angefragt: int,
    teile: list[TeilParameter],
) -> Kohortenergebnis:
    """Baut eine Kohorte ohne Modellaufruf, allein aus Parameterobjekten.

    Genau derselbe Weg wie bei der Erzeugung — nur ohne den einzigen
    Schritt, der nicht deterministisch ist.
    """
    ergebnis = Kohortenergebnis(beschreibung=beschreibung, angefragt=angefragt)
    gebaute: list[dict] = []
    versatz = 0
    for nummer, tp in enumerate(teile, start=1):
        teil = Teilergebnis(nummer=nummer, angefragt=tp.angefragt)
        versatz = _verarbeite_teil(tp, versatz, teil, ergebnis, gebaute)
        ergebnis.teile.append(teil)
    return _schliesse_ab(ergebnis, gebaute)


# --- Teilschritte ----------------------------------------------------------


def _teile(anzahl: int, teilgroesse: int) -> list[int]:
    """Zerlegt die Gesamtmenge in Teile — **keiner über `teilgroesse`**.

    Zwei Ziele, die sich zu widersprechen scheinen:

    1. Kein Teil darf grösser sein als `teilgroesse`. Der Wert ist aus dem
       Token-Budget hergeleitet und nicht geraten; ihn zu überschreiten
       heisst, dass die Antwort abgeschnitten zurückkommt.
    2. Kein Teil sollte winzig sein. Ein eigener Aufruf für einen
       einzelnen Patienten kostet denselben Prompt-Overhead wie ein
       voller Teil.

    Zuvor gewann Ziel 2, und Ziel 1 fiel dabei still unter den Tisch: Ein
    Rest bis `teilgroesse // 3` wurde dem letzten Teil zugeschlagen, was
    bei `teilgroesse=8` Teile von 9 und 10 ergab. `_teile(10, 8)` lieferte
    `[10]`, also **einen** Aufruf über rund 5040 Ausgabe-Token gegen ein
    `max_tokens` von 4500. Die Antwort kam abgeschnitten zurück, beide
    Versuche scheiterten, und `synthfhir "…" -n 10` endete mit null
    Patienten. Betroffen war jede Menge `n ≡ 1, 2 (mod 8)` über 8, also
    rund ein Viertel aller Anfragen.

    Beide Ziele sind zugleich zu haben, wenn man nicht auffüllt, sondern
    **verteilt**: so viele Teile wie nötig, dann gleichmässig belegt.

        _teile(10, 8)  -> [5, 5]        statt [10]
        _teile(18, 8)  -> [6, 6, 6]     statt [8, 10]
        _teile(25, 8)  -> [7, 6, 6, 6]  statt [8, 8, 9]

    Bei glatt teilbaren Mengen ändert sich nichts — `_teile(40, 10)` bleibt
    `[10, 10, 10, 10]`. Genau diese Mengen benutzten die Tests, weshalb
    ihnen der Fehler entging.
    """
    teilgroesse = max(1, teilgroesse)
    if anzahl <= teilgroesse:
        return [anzahl]
    # Aufrunden: so wenige Teile wie möglich, aber keines zu gross.
    anzahl_teile = -(-anzahl // teilgroesse)
    grund, rest = divmod(anzahl, anzahl_teile)
    # Der Rest verteilt sich auf die vorderen Teile, einer je Teil. Damit
    # unterscheiden sich zwei Teile um höchstens 1.
    return [grund + 1] * rest + [grund] * (anzahl_teile - rest)


def _hole_teil(
    client: LLMClient,
    beschreibung: str,
    menge: int,
    nummer: int,
    gesamt: int,
    versuche: int,
    teil: Teilergebnis,
    ergebnis: Kohortenergebnis,
) -> dict | None:
    """Holt einen Teil und gibt das Parameterobjekt zurück, oder None."""
    system, benutzer = baue_teil_prompt(beschreibung, menge, nummer, gesamt)
    letzter_fehler = "unbekannt"
    letzte_art: str | None = None

    for versuch in range(max(1, versuche)):
        if versuch > 0:
            _warte(WARTEZEIT_NACH_FEHLSCHLAG_S)
        try:
            antwort = client.frage(system=system, benutzer=benutzer)
        except LLMFehler as exc:
            letzter_fehler = str(exc)
            letzte_art = exc.art
            if exc.art in ENDGUELTIG:
                # Kein zweiter Versuch und keine Wartepause: Beides kostet
                # nur Zeit, an der sich nichts ändert.
                break
            continue

        ergebnis.llm_antworten.append(antwort)

        # Abschneiden vor dem Parsen prüfen — ein Bruchstück kann parsbar
        # sein und still falsche Daten liefern (Befund aus Phase 1).
        # Ab hier hat der Anbieter geantwortet. Die Art eines FRÜHEREN
        # Versuchs gilt damit nicht mehr — sie stehen zu lassen hiesse,
        # einen Formatfehler als Ratengrenze auszuweisen.
        if antwort.abgeschnitten:
            letzter_fehler = (
                f"Antwort von max_tokens abgeschnitten. Teilgröße {menge} ist zu groß."
            )
            letzte_art = "abgeschnitten"
            continue

        try:
            geparst = extract_json(antwort.text)
        except JsonExtractionError as exc:
            letzter_fehler = f"kein gültiges JSON: {exc}"
            letzte_art = "unbrauchbar"
            continue

        if not isinstance(geparst, dict) or "patienten" not in geparst:
            letzter_fehler = "Antwort ohne Feld 'patienten' — vermutlich ein Bruchstück."
            letzte_art = "unbrauchbar"
            continue

        return geparst

    teil.fehler = letzter_fehler
    teil.fehlerart = letzte_art
    return None
