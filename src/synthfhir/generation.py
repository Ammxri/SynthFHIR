"""Die Erzeugungskette: Freitext → validiertes Bundle.

    Beschreibung
         ↓
    Prompt + LLM                         llm.py, prompts.py
         ↓
    JSON herausschälen                   parsing.py
         ↓
    Obergrenze durchsetzen               hier
         ↓
    Vorlagen bauen FHIR                  domain/templates.py
         ↓
    IDs und Referenzen vergeben          domain/identity.py
         ↓
    Strukturvalidierung                  validation.py
         ↓
    Referenz-Integritätsprüfung          domain/integrity.py
         ↓
    Bundle

Der Kern der Zusage steht in `Ergebnis.fertig`: Nur wenn jede Ressource
strukturell valide ist und die Referenzintegrität stimmt, darf das Ergebnis
als fertig gelten (US-2 AC2). Ein nicht fertiges Ergebnis wird trotzdem
zurückgegeben — mit Befunden —, damit der Nutzer sieht, was schiefging,
statt vor einer leeren Seite zu stehen. Ausgeliefert werden darf es nicht.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .domain.identity import NormalisationResult, assign_ids
from .domain.integrity import IntegrityReport, check_resources
from .domain.templates import Beanstandung, Bauergebnis, baue_aus_parametern, baue_bundle
from .llm import LLMAntwort, LLMClient, LLMFehler
from .parsing import JsonExtractionError, extract_json
from .prompts import MAX_PATIENTEN, baue_prompt
from .validation import Pruefergebnis, pruefe_alle


@dataclass
class Verstanden:
    """Die Rücklesung der Anfrage durch das Modell.

    Macht sichtbar, was ankam. Ohne diesen Block ließe sich weder dem Nutzer
    zeigen, wie seine Anfrage gelesen wurde (US-1 AC3), noch die
    Trefferquote messen (PRD Block 8).
    """

    anzahl_patienten: int | None = None
    kernkriterien: list[str] = field(default_factory=list)
    # Kriterien, die der Katalog nicht ausdrücken kann. Ohne dieses Feld
    # ersetzt das Modell sie stillschweigend durch etwas anderes, und die
    # Ausgabe sieht einwandfrei aus, obwohl sie die Anfrage verfehlt.
    nicht_abbildbar: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "anzahl_patienten": self.anzahl_patienten,
            "kernkriterien": self.kernkriterien,
            "nicht_abbildbar": self.nicht_abbildbar,
        }


@dataclass
class Ergebnis:
    """Ergebnis einer Erzeugung — vollständig, auch wenn sie scheiterte."""

    beschreibung: str
    verstanden: Verstanden | None = None
    ressourcen: list[dict] = field(default_factory=list)
    bundle: dict | None = None
    beanstandungen: list[Beanstandung] = field(default_factory=list)
    validierung: list[Pruefergebnis] = field(default_factory=list)
    integritaet: IntegrityReport | None = None
    normalisierung: NormalisationResult | None = None
    llm_antworten: list[LLMAntwort] = field(default_factory=list)
    versuche: int = 0
    fehler: str | None = None
    # Die Art des Fehlers, aus `LLMFehler.art`. `fehler` ist ein Satz für
    # Menschen; wer daraus einen HTTP-Statuscode ableiten will, müsste ihn
    # zerlegen — und eine Umformulierung änderte still das Verhalten.
    fehlerart: str | None = None
    # Das Parameterobjekt, aus dem tatsächlich gebaut wurde — nicht
    # dasselbe wie `llm_antworten`, wo auch verworfene Versuche stehen.
    # Ohne dieses Feld liess sich der Einzellauf nicht aufzeichnen, und
    # damit war ADR-006 auf den Kommandozeilenweg beschränkt: Wer über
    # die Weboberfläche erzeugte, bekam kein wiederholbares Ergebnis.
    parameter: dict | None = None
    # Die Sollmenge, gegen die geprüft wurde. 0 heisst: keine — das Modell
    # hat keine Patientenzahl zurückgelesen.
    angefragt: int = 0

    # -- die Zusage ---------------------------------------------------------
    @property
    def fertig(self) -> bool:
        """Darf dieses Ergebnis ausgeliefert werden? (US-2 AC2)"""
        return (
            self.fehler is None
            and bool(self.ressourcen)
            and all(e.valide for e in self.validierung)
            and self.integritaet is not None
            and self.integritaet.ok
        )

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
    def anzahl_je_typ(self) -> dict[str, int]:
        zaehler: dict[str, int] = {}
        for r in self.ressourcen:
            typ = str(r.get("resourceType") or "?")
            zaehler[typ] = zaehler.get(typ, 0) + 1
        return zaehler

    @property
    def eingabe_token(self) -> int:
        return sum(a.eingabe_token for a in self.llm_antworten)

    @property
    def ausgabe_token(self) -> int:
        return sum(a.ausgabe_token for a in self.llm_antworten)

    def befunde_als_text(self) -> list[str]:
        """Alle Beanstandungen in einer für Menschen lesbaren Liste."""
        zeilen = [f"{b.art}: {b.detail}" for b in self.beanstandungen]
        for e in self.validierung:
            for befund in e.befunde:
                zeilen.append(f"{e.ressourcentyp}/{e.ressourcen_id}: {befund}")
        if self.integritaet:
            for f in self.integritaet.broken_references:
                zeilen.append(f"kaputte Referenz: {f.source} -> {f.reference} ({f.reason})")
            zeilen.extend(f"fehlende Verknüpfung: {m}" for m in self.integritaet.missing_patient_link)
            zeilen.extend(f"doppelte ID: {d}" for d in self.integritaet.duplicate_ids)
        return zeilen

    def to_dict(self) -> dict:
        return {
            "beschreibung": self.beschreibung,
            "fertig": self.fertig,
            "verstanden": self.verstanden.to_dict() if self.verstanden else None,
            "ressourcen": self.anzahl_je_typ,
            "erfundene_codes": self.erfundene_codes,
            "beanstandungen": [b.to_dict() for b in self.beanstandungen],
            "validierung": [e.to_dict() for e in self.validierung],
            "integritaet": self.integritaet.to_dict() if self.integritaet else None,
            "versuche": self.versuche,
            "eingabe_token": self.eingabe_token,
            "ausgabe_token": self.ausgabe_token,
            "fehler": self.fehler,
        }


def generiere(
    client: LLMClient,
    beschreibung: str,
    *,
    max_patienten: int = MAX_PATIENTEN,
    versuche: int = 2,
) -> Ergebnis:
    """Erzeugt aus einer Freitextbeschreibung ein validiertes Bundle."""
    ergebnis = Ergebnis(beschreibung=beschreibung)

    if not beschreibung.strip():
        ergebnis.fehler = "Die Beschreibung ist leer."
        return ergebnis

    system, benutzer = baue_prompt(beschreibung, max_patienten)
    parameter = _hole_parameter(client, system, benutzer, versuche, ergebnis)
    if parameter is None:
        return ergebnis

    ergebnis.parameter = parameter
    ergebnis.verstanden = _lies_verstanden(parameter)
    ergebnis.angefragt = ergebnis.verstanden.anzahl_patienten or 0
    # Nicht abbildbare Kriterien wandern in die Beanstandungen, damit sie im
    # selben Kanal landen wie alles andere, was der Nutzer wissen muss.
    for luecke in ergebnis.verstanden.nicht_abbildbar:
        ergebnis.beanstandungen.append(Beanstandung("nicht_abbildbar", luecke))
    _setze_obergrenze_durch(parameter, max_patienten, ergebnis.beanstandungen)

    bau: Bauergebnis = baue_aus_parametern(parameter, _erwartungen(ergebnis.verstanden))
    ergebnis.beanstandungen.extend(bau.beanstandungen)
    if not bau.ressourcen:
        ergebnis.fehler = "Aus den Parametern ließ sich keine einzige Ressource bauen."
        return ergebnis

    # IDs und Referenzen vergibt ausschließlich der Code (PRD Block 6).
    normalisiert = assign_ids(bau.ressourcen)
    ergebnis.normalisierung = normalisiert
    ergebnis.ressourcen = normalisiert.resources

    ergebnis.validierung = pruefe_alle(ergebnis.ressourcen)
    ergebnis.integritaet = check_resources(ergebnis.ressourcen)
    ergebnis.bundle = baue_bundle(ergebnis.ressourcen)
    return ergebnis


# --- Teilschritte ----------------------------------------------------------


def _hole_parameter(
    client: LLMClient, system: str, benutzer: str, versuche: int, ergebnis: Ergebnis
) -> dict | None:
    """Ruft das Modell auf, bis eine parsbare Antwort kommt.

    Eine abgeschnittene Antwort wird ausdrücklich benannt: Sie ist ein
    Konfigurationsproblem (`max_tokens` zu klein), nicht ein Modellfehler.
    Die Unterscheidung hat in Phase 0 eine ganze Messreihe gekostet.
    """
    letzter_fehler, letzte_art = "unbekannt", "unbrauchbar"
    for _ in range(max(1, versuche)):
        ergebnis.versuche += 1
        try:
            antwort = client.frage(system=system, benutzer=benutzer)
        except LLMFehler as exc:
            letzter_fehler, letzte_art = str(exc), exc.art
            continue

        ergebnis.llm_antworten.append(antwort)

        # ZUERST auf Abschneiden prüfen, nicht erst wenn das Parsen scheitert.
        # Eine abgeschnittene Antwort kann ein parsbares Bruchstück enthalten:
        # Aus '{"verstanden": {"anzahl_patienten": 25}, "patienten": [{"vorn'
        # holt die Extraktion das innere Objekt heraus und liefert es
        # klaglos zurück. Das Ergebnis wäre still falsch statt sichtbar
        # kaputt — der schlimmste denkbare Ausgang für ein Werkzeug, dessen
        # Produkt die Verlässlichkeit ist.
        if antwort.abgeschnitten:
            letzter_fehler = (
                "Die Antwort wurde von max_tokens abgeschnitten und ist unvollständig. "
                "Für diese Kohortengröße reicht die Obergrenze nicht."
            )
            letzte_art = "unbrauchbar"
            continue

        try:
            geparst = extract_json(antwort.text)
        except JsonExtractionError as exc:
            letzter_fehler = f"Die Antwort war kein gültiges JSON: {exc}"
            letzte_art = "unbrauchbar"
            continue

        # `letzte_art` gehört in JEDEN dieser Zweige. In den beiden
        # folgenden fehlte sie, und der Wert des vorherigen Durchlaufs blieb
        # stehen: Endete Versuch 1 an der Ratengrenze (`kontingent`) und
        # lieferte Versuch 2 eine Antwort ohne `patienten`, stand am Ende
        # `fehler` = „kein Feld 'patienten'" neben `fehlerart` =
        # „kontingent". `web/api.py` bildet daraus über `_ZUORDNUNG` HTTP
        # 429 mit „Der Anbieter hat die Anfrage wegen seiner Ratengrenze
        # abgewiesen" — im selben JSON-Rumpf wie die widersprechende
        # Meldung. Der Aufrufer wurde auf „später erneut versuchen"
        # verwiesen, obwohl das Modell Unsinn geliefert hatte.
        if not isinstance(geparst, dict):
            letzter_fehler = (
                f"Erwartet wurde ein Parameterobjekt, geliefert wurde {type(geparst).__name__}."
            )
            letzte_art = "unbrauchbar"
            continue

        # Zweite Absicherung gegen ein herausgelöstes Bruchstück: Ohne den
        # Schlüssel 'patienten' ist es nicht das gesuchte Objekt, egal wie
        # gültig das JSON für sich genommen ist.
        if "patienten" not in geparst:
            letzter_fehler = (
                "Die Antwort enthält kein Feld 'patienten'. Vermutlich wurde nur ein "
                "Bruchstück der Antwort übertragen."
            )
            letzte_art = "unbrauchbar"
            continue

        return geparst

    ergebnis.fehler = letzter_fehler
    ergebnis.fehlerart = letzte_art
    return None


def _lies_verstanden(parameter: dict) -> Verstanden:
    roh = parameter.get("verstanden")
    if not isinstance(roh, dict):
        return Verstanden()
    anzahl = roh.get("anzahl_patienten")
    kriterien = roh.get("kernkriterien")
    luecken = roh.get("nicht_abbildbar")
    return Verstanden(
        anzahl_patienten=anzahl if isinstance(anzahl, int) and not isinstance(anzahl, bool) else None,
        kernkriterien=[str(k) for k in kriterien] if isinstance(kriterien, list) else [],
        nicht_abbildbar=[str(k) for k in luecken] if isinstance(luecken, list) else [],
    )


def _erwartungen(verstanden: Verstanden | None) -> dict[str, int]:
    """Sollzahlen für die Mengenprüfung.

    Nur die Patientenzahl ist prüfbar, und auch die nur gegen die eigene
    Rücklesung des Modells: Wie viele Diagnosen ein Satz verlangt, steht
    nirgends. Der Vergleich deckt damit den Fall ab, dass das Modell
    erkennt „fünf Patienten" und dann drei liefert — das war in Phase 0 der
    Hauptfehler der verworfenen Variante A.
    """
    if verstanden and verstanden.anzahl_patienten:
        return {"patienten": verstanden.anzahl_patienten}
    return {}


def _setze_obergrenze_durch(
    parameter: dict, max_patienten: int, beanstandungen: list[Beanstandung]
) -> None:
    """Kappt zu große Kohorten und meldet das.

    PRD Block 4 begrenzt den MVP auf 1–25 Patienten. Der Prompt sagt das
    dem Modell; hält es sich nicht daran, greift diese Grenze — sichtbar,
    nicht stillschweigend.
    """
    patienten = parameter.get("patienten")
    if not isinstance(patienten, list) or len(patienten) <= max_patienten:
        return
    beanstandungen.append(
        Beanstandung(
            "obergrenze",
            f"{len(patienten)} Patienten angefragt, der MVP erzeugt höchstens "
            f"{max_patienten}. Die übrigen wurden verworfen.",
        )
    )
    parameter["patienten"] = patienten[:max_patienten]
