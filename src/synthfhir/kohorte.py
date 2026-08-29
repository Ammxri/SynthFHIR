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

import time
from dataclasses import dataclass, field
from typing import Callable

from .domain.identity import assign_ids
from .domain.integrity import IntegrityReport, check_resources
from .domain.templates import Beanstandung, baue_aus_parametern, baue_bundle
from .generation import Verstanden, _lies_verstanden
from .llm import LLMAntwort, LLMClient, LLMFehler
from .parsing import JsonExtractionError, extract_json
from .prompts import baue_teil_prompt
from .validation import Pruefergebnis, pruefe_alle

# Voreinstellung je Teil. Bewusst unter den gemessenen 25: Dort lagen wir
# bei 84,9 % der Token-Obergrenze, und bei mehr als zwei Messwerten je
# Patient reißt es. 15 lässt Luft für Patienten mit mehreren Diagnosen.
TEILGROESSE = 15

# Wartezeit zwischen zwei Versuchen desselben Teils. Ohne sie ist der zweite
# Versuch bei den beiden häufigsten Ursachen sinnlos: Eine Ratengrenze steht
# noch, und ein Namensauflösungsfehler kommt sofort zurück — gemessen am
# 2026-08-29 verbrannte ein Teil so beide Versuche in unter einer Sekunde.
WARTEZEIT_NACH_FEHLSCHLAG_S = 15.0

Fortschritt = Callable[[int, int, str], None]


def _warte(sekunden: float) -> None:
    """Eigene Funktion, damit Tests sie ersetzen können.

    Ein durchgereichter Parameter hätte die Signatur aufgebläht, und
    `time.sleep` global zu verbiegen träfe auch alles andere.
    """
    if sekunden > 0:
        time.sleep(sekunden)


@dataclass
class Teilergebnis:
    """Was ein einzelner Teil geliefert hat."""

    nummer: int
    angefragt: int
    geliefert: int = 0
    fehler: str | None = None
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
        """
        namen = [
            f"{' '.join((r.get('name') or [{}])[0].get('given', []))} "
            f"{(r.get('name') or [{}])[0].get('family', '')}"
            for r in self.ressourcen
            if r.get("resourceType") == "Patient"
        ]
        return len(set(namen)) / len(namen) if namen else 0.0

    @property
    def erfundene_codes(self) -> int:
        return sum(
            1
            for b in self.beanstandungen
            if b.art in ("erfundener_diagnosecode", "erfundener_messwertcode")
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
            "angefragt": self.angefragt,
            "patienten": self.patienten,
            "mengentreue": round(self.mengentreue, 4),
            "namensvielfalt": round(self.namensvielfalt, 4),
            "ressourcen": self.anzahl_je_typ,
            "erfundene_codes": self.erfundene_codes,
            "nicht_abbildbar": self.nicht_abbildbar,
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
            verstanden = _lies_verstanden(parameter)
            for luecke in verstanden.nicht_abbildbar:
                if luecke not in ergebnis.nicht_abbildbar:
                    ergebnis.nicht_abbildbar.append(luecke)

            bau = baue_aus_parametern(
                parameter, {"patienten": menge}, index_versatz=versatz
            )
            ergebnis.beanstandungen.extend(bau.beanstandungen)
            gebaute.extend(bau.ressourcen)
            teil.geliefert = sum(
                1 for r in bau.ressourcen if r.get("resourceType") == "Patient"
            )
            # Der Versatz wächst um das, was tatsächlich kam — nicht um das,
            # was angefragt war. Sonst entstünden Lücken in den vorläufigen
            # Kennungen, was zwar nicht schadet, aber die Artefakte
            # unnötig schwer lesbar macht.
            versatz += max(teil.geliefert, 1)

        teil.dauer_s = time.perf_counter() - beginn
        ergebnis.teile.append(teil)
        if fortschritt:
            stand = teil.fehler or f"{teil.geliefert}/{menge} Patienten"
            fortschritt(nummer, gesamt, stand)

    if not gebaute:
        return ergebnis

    # Einmal über die GESAMTE Kohorte, nicht je Teil.
    normalisiert = assign_ids(gebaute)
    ergebnis.ressourcen = normalisiert.resources
    ergebnis.validierung = pruefe_alle(ergebnis.ressourcen)
    ergebnis.integritaet = check_resources(ergebnis.ressourcen)
    ergebnis.bundle = baue_bundle(ergebnis.ressourcen)
    return ergebnis


# --- Teilschritte ----------------------------------------------------------


def _teile(anzahl: int, teilgroesse: int) -> list[int]:
    """Zerlegt die Gesamtmenge in Teile.

    Ein winziger Rest wird dem vorletzten Teil zugeschlagen: Ein eigener
    Aufruf für einen einzelnen Patienten kostet denselben Prompt-Overhead
    wie ein voller Teil.
    """
    teilgroesse = max(1, teilgroesse)
    if anzahl <= teilgroesse:
        return [anzahl]
    teile = [teilgroesse] * (anzahl // teilgroesse)
    rest = anzahl % teilgroesse
    if rest:
        if rest <= teilgroesse // 3:
            teile[-1] += rest
        else:
            teile.append(rest)
    return teile


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

    for versuch in range(max(1, versuche)):
        if versuch > 0:
            _warte(WARTEZEIT_NACH_FEHLSCHLAG_S)
        try:
            antwort = client.frage(system=system, benutzer=benutzer)
        except LLMFehler as exc:
            letzter_fehler = str(exc)
            continue

        ergebnis.llm_antworten.append(antwort)

        # Abschneiden vor dem Parsen prüfen — ein Bruchstück kann parsbar
        # sein und still falsche Daten liefern (Befund aus Phase 1).
        if antwort.abgeschnitten:
            letzter_fehler = (
                f"Antwort von max_tokens abgeschnitten. Teilgröße {menge} ist zu groß."
            )
            continue

        try:
            geparst = extract_json(antwort.text)
        except JsonExtractionError as exc:
            letzter_fehler = f"kein gültiges JSON: {exc}"
            continue

        if not isinstance(geparst, dict) or "patienten" not in geparst:
            letzter_fehler = "Antwort ohne Feld 'patienten' — vermutlich ein Bruchstück."
            continue

        return geparst

    teil.fehler = letzter_fehler
    return None
