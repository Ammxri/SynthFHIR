"""Tests der Anbieter-Anbindung — vor allem des Token-Haushalts.

Der Test in dieser Datei hätte einen Ausfall der veröffentlichten Seite
verhindert, und das ist sein einziger Zweck.

Am 2026-08-30 wuchs der Prompt um zwei Kataloge. Die Voreinstellung für
`max_tokens` wurde daraufhin in `.env.example` gesenkt — aber nicht im
Code, und ein Deployment ohne gesetzte Umgebungsvariable landet genau
dort. Die Live-Seite antwortete danach auf **jede** Anfrage mit HTTP 413.

Die Testsuite konnte das nicht sehen: Sie ruft kein Modell auf, und die
beiden Werte — Prompt-Größe und reservierte Antwortlänge — wurden nirgends
gegeneinander gehalten. Genau das tut dieser Test.
"""

from __future__ import annotations

import pytest

from synthfhir.llm import STANDARD_MAX_TOKENS
from synthfhir.prompts import baue_prompt, baue_teil_prompt

# Das Kontingent, gegen das dieses Projekt entwickelt wird: Groq im
# kostenlosen Tarif. Es ist die engste Umgebung, in der das Produkt laufen
# soll, und damit die richtige Meßlatte.
GRATISTARIF_TOKEN_JE_MINUTE = 8000

# Zeichen je Token, hergeleitet aus einer echten Anbieterantwort: Der
# Anbieter meldete 2883 Token für einen Prompt von 9243 Zeichen, also 3,21.
# Aufgerundet auf 3,0 — für eine Obergrenze rechnet man besser zu
# pessimistisch als zu optimistisch.
ZEICHEN_JE_TOKEN = 3.0


def geschaetzte_token(system: str, benutzer: str) -> int:
    return int((len(system) + len(benutzer)) / ZEICHEN_JE_TOKEN)


def test_voreinstellung_passt_zum_ausgelieferten_prompt():
    """Die eine Zusage dieser Datei.

    Anbieter rechnen `max_tokens` in die ANFRAGEGRÖSSE ein — der Wert zählt
    also mit, auch wenn er nie ausgeschöpft wird. Prompt plus Reserve muss
    darum unter das Kontingent passen.
    """
    system, benutzer = baue_prompt("5 Patientinnen mit Typ-2-Diabetes", max_patienten=5)
    prompt = geschaetzte_token(system, benutzer)
    gesamt = prompt + STANDARD_MAX_TOKENS

    assert gesamt <= GRATISTARIF_TOKEN_JE_MINUTE, (
        f"Prompt ~{prompt} + max_tokens {STANDARD_MAX_TOKENS} = {gesamt} Token, "
        f"erlaubt sind {GRATISTARIF_TOKEN_JE_MINUTE}. Jede Anfrage scheiterte "
        "mit HTTP 413. Entweder den Prompt kürzen oder STANDARD_MAX_TOKENS senken."
    )


def test_auch_der_teil_prompt_passt():
    """Der Prompt für Teilkohorten trägt einen Zusatz und ist damit
    länger — er ist der Fall, der zuerst reißt."""
    system, benutzer = baue_teil_prompt("15 Patientinnen", 15, 3, 13)
    gesamt = geschaetzte_token(system, benutzer) + STANDARD_MAX_TOKENS
    assert gesamt <= GRATISTARIF_TOKEN_JE_MINUTE, gesamt


def test_die_reserve_traegt_eine_ganze_teilkohorte():
    """Nutzlos wäre eine Reserve, die zwar unter das Kontingent passt, aber
    keinen vollen Teil mehr trägt: Dann liefe jeder Teil in die
    Abschneidung."""
    from synthfhir.kohorte import TEILGROESSE

    ausgabe_je_patient = 504          # gemessen am 2026-08-30
    assert TEILGROESSE * ausgabe_je_patient <= STANDARD_MAX_TOKENS


def test_umgebungsvariable_sticht_die_voreinstellung(monkeypatch):
    """Wer ein größeres Kontingent hat, soll den Wert anheben können."""
    from synthfhir.llm import client_aus_umgebung

    monkeypatch.setenv("SYNTHFHIR_LLM_MODEL", "testmodell")
    monkeypatch.setenv("SYNTHFHIR_LLM_MAX_TOKENS", "12000")
    assert client_aus_umgebung().max_tokens == 12000


def test_ohne_umgebungsvariable_gilt_die_voreinstellung(monkeypatch):
    """Der Fall, der die Live-Seite gekostet hat: Render setzt die Variable
    nicht, also greift der Wert aus dem Code."""
    from synthfhir.llm import client_aus_umgebung

    monkeypatch.setenv("SYNTHFHIR_LLM_MODEL", "testmodell")
    monkeypatch.delenv("SYNTHFHIR_LLM_MAX_TOKENS", raising=False)
    assert client_aus_umgebung().max_tokens == STANDARD_MAX_TOKENS


def test_render_setzt_denselben_wert():
    """Die Bereitstellungsdatei und der Code dürfen nicht auseinanderlaufen.

    Doppelt gepflegt ist zwar doppelt zu ändern — aber wer in render.yaml
    nachsieht, soll den Zusammenhang sehen und nicht raten müssen.
    """
    import re
    from pathlib import Path

    yaml = Path(__file__).resolve().parents[1] / "render.yaml"
    text = yaml.read_text(encoding="utf-8")
    m = re.search(r'SYNTHFHIR_LLM_MAX_TOKENS\s*\n\s*value:\s*"(\d+)"', text)
    assert m, "render.yaml setzt SYNTHFHIR_LLM_MAX_TOKENS nicht"
    assert int(m.group(1)) == STANDARD_MAX_TOKENS


@pytest.mark.parametrize("beschreibung", [
    "Ein Patient",
    "25 Patientinnen und Patienten mit Typ-2-Diabetes, Bluthochdruck, "
    "Asthma und Osteoporose, mit Medikation, mehreren Messwerten und "
    "je zwei stationären Aufenthalten über die letzten fünf Jahre",
])
def test_die_beschreibung_sprengt_das_kontingent_nicht(beschreibung):
    """Die Beschreibung des Nutzers geht wörtlich in den Prompt. Ein langer
    Satz darf ihn nicht über die Grenze heben."""
    system, benutzer = baue_prompt(beschreibung, max_patienten=25)
    gesamt = geschaetzte_token(system, benutzer) + STANDARD_MAX_TOKENS
    assert gesamt <= GRATISTARIF_TOKEN_JE_MINUTE, gesamt


# --- Was das Werkzeug selbst nicht messen konnte ---------------------------


def test_fester_client_geht_aus_wenn_eine_liste_vorgegeben_ist():
    """Die Schutzabfrage in `FesterClient` war toter Code.

    `self.antworten.pop(0) if len(self.antworten) > 1 else self.antworten[0]`
    hörte beim letzten Eintrag auf zu entnehmen: Die Liste wurde nie leer,
    also feuerte `if not self.antworten` nach der Konstruktion nie. Ein
    Test, der drei Antworten hinterlegt und fünf Aufrufe auslöst, bekam
    stillschweigend die dritte zweimal — „der Code hat öfter gefragt als
    vorgesehen" liess sich grundsätzlich nicht bemerken.
    """
    from synthfhir.llm import FesterClient, LLMFehler

    client = FesterClient(["eins", "zwei"])
    assert client.frage(system="s", benutzer="b").text == "eins"
    assert client.frage(system="s", benutzer="b").text == "zwei"
    with pytest.raises(LLMFehler, match="3 Mal gefragt"):
        client.frage(system="s", benutzer="b")


def test_eine_einzelne_antwort_darf_sich_wiederholen():
    """Die übliche Attrappe für „der Aufruf gelingt" bleibt, wie sie war."""
    from synthfhir.llm import FesterClient

    client = FesterClient("immer dasselbe")
    assert [client.frage(system="s", benutzer="b").text for _ in range(5)] == [
        "immer dasselbe"
    ] * 5


def test_unlesbare_umgebungsvariable_wird_zum_llmfehler(monkeypatch):
    """`int(os.environ.get(...))` warf einen ValueError.

    Alle Aufrufer fangen ausschliesslich `LLMFehler` — die Kommandozeile
    brach mit einem Traceback ab, die Weboberfläche antwortete mit 500
    statt 503. `SYNTHFHIR_LLM_MAX_TOKENS` wird in `.env.example`
    ausdrücklich als Stellschraube beworben; `4.5k` ist eine naheliegende
    Schreibweise.
    """
    from synthfhir.llm import LLMFehler, client_aus_umgebung

    monkeypatch.setenv("SYNTHFHIR_LLM_MODEL", "modell")
    monkeypatch.setenv("SYNTHFHIR_LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("SYNTHFHIR_LLM_MAX_TOKENS", "4.5k")

    with pytest.raises(LLMFehler) as exc:
        client_aus_umgebung()
    assert exc.value.art == "nicht_konfiguriert"
    assert "SYNTHFHIR_LLM_MAX_TOKENS" in str(exc.value)


@pytest.mark.parametrize("grund", ["length", "LENGTH", "MAX_TOKENS", "model_length"])
def test_abschneiden_wird_auch_bei_anderer_schreibweise_erkannt(grund):
    """Der Vergleich war exakt und kleinschreibungsempfindlich.

    Ein Anbieter, der `MAX_TOKENS` meldet, schaltete die Erkennung ab, und
    der Fehlschlag wurde als „kein Feld 'patienten' — vermutlich ein
    Bruchstück" verbucht. Der Betreiber suchte dann beim Modell statt bei
    `max_tokens` — genau die Unterscheidung, die in Phase 0 eine ganze
    Messreihe gekostet hat.
    """
    from synthfhir.llm import FINISH_REASON

    assert FINISH_REASON.get(grund.strip().lower()) == "max_tokens"


def test_ausgeschoepfte_grenze_gilt_auch_ohne_bekannten_abbruchgrund():
    """Der Rückfall für Anbieter mit unbekannter Schreibweise: Wer die
    Grenze ausgeschöpft hat, wurde abgeschnitten — auch wenn er es anders
    nennt."""
    from synthfhir.llm import LLMAntwort

    a = LLMAntwort(text="x", modell="m", eingabe_token=10, ausgabe_token=4500,
                   dauer_s=0.0, abbruchgrund="voellig-unbekannt",
                   token_grenze=4500)
    assert a.abgeschnitten

    b = LLMAntwort(text="x", modell="m", eingabe_token=10, ausgabe_token=120,
                   dauer_s=0.0, abbruchgrund="voellig-unbekannt",
                   token_grenze=4500)
    assert not b.abgeschnitten


# --- Kein Anbietertext in der Fehlermeldung (Fix 2, Befund) ----------------
#
# Ein Anbieter oder vorgelagertes Gateway kann den Authorization-Kopf in
# seiner Fehlermeldung wiederholen. Der rohe Antworttext darf deshalb NICHT
# in die LLMFehler-Meldung — sonst steht er ueber `str(exc)` in der Seite
# und im Bericht. Er gehoert nach `exc.roh`, das kein oeffentlicher Pfad
# rendert.


class _FakeAntwort:
    """Das Minimum, das `frage()` von einer requests.Response liest."""

    def __init__(self, status_code, text, json_body=None):
        self.status_code = status_code
        self.text = text
        self.headers = {}
        self._json = json_body

    def json(self):
        if self._json is None:
            raise ValueError("kein JSON")
        return self._json


def _client(monkeypatch, antwort):
    from synthfhir import llm

    c = llm.OpenAIKompatiblerClient(
        modell="m", basis_url="https://anbieter.invalid/v1",
        api_schluessel="sk-BETREIBER-GEHEIM-4711",
    )
    monkeypatch.setattr(c, "_post_mit_wartepausen", lambda url, rumpf: antwort)
    return c


GEHEIM = "sk-BETREIBER-GEHEIM-4711"


def test_http_fehler_traegt_den_anbietertext_nicht_in_der_meldung(monkeypatch):
    from synthfhir.llm import LLMFehler

    echo = f'{{"error": {{"message": "rejected (Bearer {GEHEIM})"}}}}'
    c = _client(monkeypatch, _FakeAntwort(500, echo))
    with pytest.raises(LLMFehler) as fehler:
        c.frage(system="s", benutzer="b")
    assert GEHEIM not in str(fehler.value), "der Schluessel steht in der Meldung"
    assert "HTTP 500" in str(fehler.value)
    # Fuer die Server-Logs des Betreibers bleibt er erreichbar.
    assert fehler.value.roh is not None and GEHEIM in fehler.value.roh


def test_kein_json_traegt_den_anbietertext_nicht_in_der_meldung(monkeypatch):
    from synthfhir.llm import LLMFehler

    c = _client(monkeypatch, _FakeAntwort(200, f"<html>Bearer {GEHEIM}</html>"))
    with pytest.raises(LLMFehler) as fehler:
        c.frage(system="s", benutzer="b")
    assert GEHEIM not in str(fehler.value)
    assert GEHEIM in (fehler.value.roh or "")


def test_ohne_choices_traegt_den_koerper_nicht_in_der_meldung(monkeypatch):
    from synthfhir.llm import LLMFehler

    c = _client(monkeypatch, _FakeAntwort(
        200, "{}", json_body={"schluessel_echo": f"Bearer {GEHEIM}"}))
    with pytest.raises(LLMFehler) as fehler:
        c.frage(system="s", benutzer="b")
    assert GEHEIM not in str(fehler.value)
    assert GEHEIM in (fehler.value.roh or "")
