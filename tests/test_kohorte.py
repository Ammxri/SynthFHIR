"""Tests der stückweisen Erzeugung großer Kohorten (Phase 2).

Der Schwerpunkt liegt auf dem, was beim Stückeln schiefgeht: kollidierende
Kennungen, querverdrahtete Verweise und ausgefallene Teile. Dass der
Normalfall funktioniert, ist die leichtere Hälfte.
"""

from __future__ import annotations

import json
import re

import pytest

from synthfhir.kohorte import _teile, generiere_kohorte
from synthfhir.llm import LLMAntwort, LLMClient, LLMFehler


class TeilClient(LLMClient):
    """Liefert je Teil unterscheidbare Patienten, wie ein Modell es soll."""

    def __init__(
        self,
        faellt_aus: set[int] | None = None,
        wiederholt_namen: bool = False,
        nur_erster_versuch: bool = False,
    ):
        self.aufruf = 0
        self.faellt_aus = faellt_aus or set()
        self.wiederholt_namen = wiederholt_namen
        self.nur_erster_versuch = nur_erster_versuch
        self.mengen: list[int] = []
        self.versuche: dict[int, int] = {}

    def frage(self, *, system: str, benutzer: str) -> LLMAntwort:
        self.aufruf += 1
        menge = int(re.search(r"Erzeuge genau (\d+) Patienten", benutzer).group(1))
        teil = int(re.search(r"TEIL (\d+) VON", benutzer).group(1))
        self.mengen.append(menge)
        self.versuche[teil] = self.versuche.get(teil, 0) + 1

        # Der Fehlschlag hängt an der Teilnummer, nicht am Aufrufzähler.
        # Andernfalls geriete der Wiederholversuch eines ausgefallenen Teils
        # an eine andere Nummer und gelänge — der Test prüfte dann nichts.
        if teil in self.faellt_aus and not (
            self.nur_erster_versuch and self.versuche[teil] > 1
        ):
            raise LLMFehler(f"Teil {teil} konnte nicht erzeugt werden")

        marke = "gleich" if self.wiederholt_namen else f"t{teil}"
        patienten = [
            {
                "vorname": f"Vor-{marke}" if self.wiederholt_namen else f"Vor-{marke}-{i}",
                "nachname": "Nachname",
                "geschlecht": "female",
                "geburtsdatum": "1960-01-01",
                "diagnosen": [{"code": "44054006", "beginn": "2015-01-01"}],
                "messwerte": [{"code": "4548-4", "wert": 7.0, "datum": "2024-01-01"}],
            }
            for i in range(menge)
        ]
        text = json.dumps(
            {"verstanden": {"anzahl_patienten": menge, "kernkriterien": []},
             "patienten": patienten},
            ensure_ascii=False,
        )
        return LLMAntwort(text=text, modell="test", eingabe_token=100,
                          ausgabe_token=len(text) // 4, dauer_s=0.0, abbruchgrund="end_turn")


@pytest.fixture(autouse=True)
def keine_wartezeit(monkeypatch):
    """Tests warten nicht wirklich — sie halten nur fest, wie lange.

    Nullwerte fallen heraus, genau wie in `_warte` selbst: Ein `pause_s=0`
    zwischen zwei Teilen ist keine Wartezeit, sondern deren Abwesenheit.
    """
    gewartet: list[float] = []

    def merken(sekunden: float) -> None:
        if sekunden > 0:
            gewartet.append(sekunden)

    monkeypatch.setattr("synthfhir.kohorte._warte", merken)
    return gewartet


# --- Aufteilung ------------------------------------------------------------


@pytest.mark.parametrize(
    "anzahl, groesse, erwartet",
    [
        (1, 15, [1]),
        (15, 15, [15]),
        (16, 15, [16]),          # winziger Rest wandert in den letzten Teil
        (30, 15, [15, 15]),
        (31, 15, [15, 16]),
        (25, 15, [15, 10]),      # großer Rest bekommt einen eigenen Teil
        (100, 20, [20, 20, 20, 20, 20]),
    ],
)
def test_aufteilung(anzahl, groesse, erwartet):
    assert _teile(anzahl, groesse) == erwartet


def test_aufteilung_verliert_niemanden():
    for anzahl in range(1, 205):
        assert sum(_teile(anzahl, 15)) == anzahl


def test_kein_teil_fuer_einen_einzigen_patienten():
    """Ein eigener Aufruf für einen Rest von eins kostet denselben
    Prompt-Overhead wie ein voller Teil."""
    assert 1 not in _teile(46, 15)


# --- Der Normalfall --------------------------------------------------------


def test_grosse_kohorte_bleibt_referenziell_sauber():
    e = generiere_kohorte(TeilClient(), "50 Diabetikerinnen", 50, teilgroesse=15)
    assert e.fertig
    assert e.patienten == 50
    assert e.mengentreue == 1.0
    assert e.integritaet.broken_reference_count == 0
    assert e.integritaet.duplicate_ids == []
    assert e.integritaet.missing_patient_link == []


def test_kennungen_sind_ueber_alle_teile_eindeutig():
    """Der Kernfehler beim Stückeln: Ohne Versatz begänne jeder Teil wieder
    bei tmp-pat-0 und die Verweise zeigten quer."""
    e = generiere_kohorte(TeilClient(), "60 Patientinnen", 60, teilgroesse=15)
    ids = [r["id"] for r in e.ressourcen]
    assert len(ids) == len(set(ids))
    patienten = [r["id"] for r in e.ressourcen if r["resourceType"] == "Patient"]
    assert patienten[0] == "pat-001" and patienten[-1] == "pat-060"


def test_jede_diagnose_zeigt_auf_ihren_eigenen_patienten():
    """Bei vier Teilen darf keine Diagnose auf einen Patienten eines
    anderen Teils zeigen."""
    e = generiere_kohorte(TeilClient(), "40 Patientinnen", 40, teilgroesse=10)
    patienten_ids = {f"Patient/{r['id']}"
                     for r in e.ressourcen if r["resourceType"] == "Patient"}
    verweise = [r["subject"]["reference"]
                for r in e.ressourcen if r["resourceType"] == "Condition"]
    assert len(verweise) == 40
    assert set(verweise) == patienten_ids, "jeder Patient genau einmal referenziert"


def test_anzahl_der_aufrufe_entspricht_der_aufteilung():
    client = TeilClient()
    generiere_kohorte(client, "100 Patientinnen", 100, teilgroesse=20)
    assert client.aufruf == 5
    assert client.mengen == [20, 20, 20, 20, 20]


# --- Wenn ein Teil ausfällt ------------------------------------------------


def test_ausgefallener_teil_bricht_die_kohorte_nicht_ab():
    """Grundsatz aus Phase 0: Ein einzelner Fehlschlag darf die Reihe nicht
    beenden. Ein halbes Ergebnis ist ehrlicher als gar keines."""
    e = generiere_kohorte(TeilClient(faellt_aus={2}), "45 Patientinnen", 45, teilgroesse=15)
    assert e.patienten == 30
    assert [t.erfolgreich for t in e.teile] == [True, False, True]
    assert "nicht erzeugt werden" in e.teile[1].fehler


def test_ausgefallener_teil_senkt_die_mengentreue_sichtbar():
    """Die Lücke darf sich nicht verstecken — genau das war der Fehler der
    in Phase 0 verworfenen Variante A."""
    e = generiere_kohorte(TeilClient(faellt_aus={2}), "45 Patientinnen", 45, teilgroesse=15)
    assert e.mengentreue == pytest.approx(30 / 45)
    assert e.fertig, "Was geliefert wurde, ist trotzdem valide"


def test_alle_teile_fallen_aus():
    e = generiere_kohorte(TeilClient(faellt_aus={1, 2, 3}), "45 Patientinnen", 45, teilgroesse=15)
    assert not e.fertig
    assert e.ressourcen == []
    assert e.mengentreue == 0.0
    assert all(not t.erfolgreich for t in e.teile)


def test_vorruebergehender_ausfall_wird_wiederholt():
    """Groq wirft im kostenlosen Kontingent regelmäßig 429. Ein Teil, der
    beim zweiten Anlauf gelingt, darf keine Lücke hinterlassen."""
    client = TeilClient(faellt_aus={2}, nur_erster_versuch=True)
    e = generiere_kohorte(client, "45 Patientinnen", 45, teilgroesse=15,
                          versuche_je_teil=2)
    assert e.mengentreue == 1.0
    assert client.versuche[2] == 2, "Teil 2 wurde genau einmal wiederholt"
    assert all(t.erfolgreich for t in e.teile)


def test_ohne_wiederholung_bleibt_der_ausfall_stehen():
    """Gegenprobe: derselbe Ausfall, aber nur ein Versuch."""
    e = generiere_kohorte(TeilClient(faellt_aus={2}, nur_erster_versuch=True),
                          "45 Patientinnen", 45, teilgroesse=15, versuche_je_teil=1)
    assert e.patienten == 30


def test_ausgefallene_teile_hinterlassen_keine_luecken_in_den_kennungen():
    """Am 2026-08-29 brachen in einem echten Lauf über 200 Patienten die
    Teile 5 bis 13 weg (Ratengrenze, dann Namensauflösung). Der Versatz
    darf für einen ausgefallenen Teil nicht mitwachsen — sonst klaffte in
    der Nummerierung eine Lücke, wo nie ein Patient war."""
    e = generiere_kohorte(TeilClient(faellt_aus={2, 3}), "75 Patientinnen", 75,
                          teilgroesse=15)
    pat = [r["id"] for r in e.ressourcen if r["resourceType"] == "Patient"]
    assert pat == [f"pat-{i:03d}" for i in range(1, 46)], "45 lückenlos ab pat-001"
    assert e.integritaet.ok
    assert e.integritaet.broken_reference_count == 0


def test_verweise_bleiben_nach_einem_ausfall_korrekt():
    """Der gefährliche Fall: Teil 3 verweist nach dem Ausfall von Teil 2
    auf Patienten, die es gar nicht gibt."""
    e = generiere_kohorte(TeilClient(faellt_aus={2}), "45 Patientinnen", 45,
                          teilgroesse=15)
    pids = {f"Patient/{r['id']}" for r in e.ressourcen
            if r["resourceType"] == "Patient"}
    verweise = {r["subject"]["reference"] for r in e.ressourcen
                if r["resourceType"] != "Patient"}
    assert verweise == pids, "jeder vorhandene Patient genau einmal, keiner darüber"


def test_abgeschnittener_teil_nennt_die_teilgroesse():
    """Die Ursache liegt in der Konfiguration, nicht beim Modell — das muss
    die Meldung sagen, sonst sucht man an der falschen Stelle."""

    class AbgeschnittenerClient(LLMClient):
        def frage(self, *, system: str, benutzer: str) -> LLMAntwort:
            return LLMAntwort(text='{"patienten": [{"vorn', modell="test",
                              eingabe_token=10, ausgabe_token=5600, dauer_s=0.0,
                              abbruchgrund="max_tokens")

    e = generiere_kohorte(AbgeschnittenerClient(), "30 Patientinnen", 30, teilgroesse=15)
    assert not e.fertig
    assert "abgeschnitten" in e.teile[0].fehler
    assert "Teilgröße 15" in e.teile[0].fehler


# --- Vielfalt --------------------------------------------------------------


def test_namensvielfalt_misst_wiederholungen():
    """Eine Kohorte aus 200-mal derselben Person wäre als Testdaten
    wertlos. Der Wert macht das sichtbar, statt es zu verschweigen."""
    bunt = generiere_kohorte(TeilClient(), "30 Patientinnen", 30, teilgroesse=10)
    assert bunt.namensvielfalt == 1.0

    eintoenig = generiere_kohorte(
        TeilClient(wiederholt_namen=True), "30 Patientinnen", 30, teilgroesse=10
    )
    assert eintoenig.namensvielfalt < 0.2
    assert eintoenig.fertig, "Eintönig heißt nicht invalide — nur wenig brauchbar"


# --- Randfälle -------------------------------------------------------------


def test_null_patienten_ergibt_ein_leeres_ergebnis():
    client = TeilClient()
    e = generiere_kohorte(client, "keine", 0)
    assert not e.fertig
    assert client.aufruf == 0, "Ohne Bedarf darf kein Aufruf stattfinden"


def test_kleine_kohorte_braucht_nur_einen_aufruf():
    client = TeilClient()
    e = generiere_kohorte(client, "10 Patientinnen", 10, teilgroesse=15)
    assert client.aufruf == 1
    assert e.patienten == 10


def test_fortschritt_wird_je_teil_gemeldet():
    """Ein Lauf über zehn Minuten darf nicht stumm dastehen."""
    meldungen: list[tuple[int, int, str]] = []
    generiere_kohorte(TeilClient(), "45 Patientinnen", 45, teilgroesse=15,
                      fortschritt=lambda i, g, s: meldungen.append((i, g, s)))
    assert [m[0] for m in meldungen] == [1, 2, 3]
    assert all(m[1] == 3 for m in meldungen)
    assert "15/15" in meldungen[0][2]


# --- Takt und Wartezeit ----------------------------------------------------


def test_wiederholung_wartet_erst(keine_wartezeit):
    """Bei den beiden häufigsten Ursachen — Ratengrenze und
    Namensauflösungsfehler — kommt der Fehler sofort zurück. Ein sofortiger
    zweiter Versuch scheitert dann garantiert genauso."""
    from synthfhir.kohorte import WARTEZEIT_NACH_FEHLSCHLAG_S

    generiere_kohorte(TeilClient(faellt_aus={2}), "45 Patientinnen", 45,
                      teilgroesse=15, versuche_je_teil=2)
    assert keine_wartezeit == [WARTEZEIT_NACH_FEHLSCHLAG_S], (
        "genau eine Wartezeit: vor dem zweiten Versuch von Teil 2"
    )


def test_ohne_fehlschlag_wird_nicht_gewartet(keine_wartezeit):
    generiere_kohorte(TeilClient(), "45 Patientinnen", 45, teilgroesse=15)
    assert keine_wartezeit == []


def test_pause_taktet_die_teile(keine_wartezeit):
    """Vier Teile, drei Pausen — vor dem ersten Teil ist nichts zu takten."""
    generiere_kohorte(TeilClient(), "60 Patientinnen", 60, teilgroesse=15, pause_s=60)
    assert keine_wartezeit == [60, 60, 60]


def test_pause_null_haelt_nicht_auf(keine_wartezeit):
    """Der Normalfall: ohne Kontingentsorgen läuft nichts auf Wartezeit."""
    generiere_kohorte(TeilClient(), "60 Patientinnen", 60, teilgroesse=15)
    assert keine_wartezeit == []


def test_teilgroesse_traegt_die_gemessene_ausgabe():
    """Die Voreinstellung ist hergeleitet, nicht geraten — und sie hat
    schon einmal nicht getragen.

    Gemessen am 2026-08-30, nach Encounter und MedicationStatement: 504
    Ausgabe-Token je Patient, 4800 als max_tokens im Gratistarif. Wächst
    die Ausgabe je Patient weiter, ohne dass dieser Wert sinkt, laufen die
    Teile in die Abschneidung — der erste Lauf nach der Erweiterung
    scheiterte an genau dieser Rechnung.
    """
    from synthfhir.kohorte import TEILGROESSE

    ausgabe_je_patient = 504
    max_tokens = 4500
    assert TEILGROESSE * ausgabe_je_patient <= max_tokens, (
        f"{TEILGROESSE} Patienten brauchen rund "
        f"{TEILGROESSE * ausgabe_je_patient} Token, erlaubt sind {max_tokens}"
    )
