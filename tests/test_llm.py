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
