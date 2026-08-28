"""Tests des OpenAI-kompatiblen Adapters.

Ohne Netz: die HTTP-Schicht wird durch eine Attrappe ersetzt. Geprüft wird
das Verhalten, auf das sich die Messreihe verlässt – vor allem, dass eine
Ratengrenze als Wartepause behandelt wird und nicht als Messergebnis.
"""

from __future__ import annotations

import pytest

from synthfhir.config import LLMSettings
from synthfhir.llm import LLMError
from synthfhir.llm.openai_compatible import OpenAICompatibleClient


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = str(self._payload)

    def json(self) -> dict:
        return self._payload


def _ok_payload(content: str = '{"ok": true}') -> dict:
    return {
        "model": "test-model",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }


def _settings(**overrides) -> LLMSettings:
    base = dict(
        provider="openai_compatible",
        model="test-model",
        temperature=0.8,
        max_tokens=1000,
        effort=None,
        thinking=None,
        timeout_s=10.0,
        max_retries=2,
        price_in_usd_per_mtok=None,
        price_out_usd_per_mtok=None,
        eur_per_usd=0.92,
        base_url="https://example.invalid/v1",
    )
    base.update(overrides)
    return LLMSettings(**base)


def _client(monkeypatch, responses: list[FakeResponse]) -> OpenAICompatibleClient:
    client = OpenAICompatibleClient(_settings())
    queue = list(responses)
    calls: list[dict] = []

    def fake_post(url, json=None, timeout=None):  # noqa: A002
        calls.append({"url": url, "json": json})
        return queue.pop(0)

    monkeypatch.setattr(client.session, "post", fake_post)
    monkeypatch.setattr("synthfhir.llm.openai_compatible.time.sleep", lambda _: None)
    client.calls_made = calls  # für Zusicherungen im Test
    return client


def test_erfolgreiche_antwort_wird_ausgewertet(monkeypatch):
    client = _client(monkeypatch, [FakeResponse(200, _ok_payload())])
    response = client.complete(system="s", user="u", purpose="test")
    assert response.text == '{"ok": true}'
    assert response.input_tokens == 11
    assert response.output_tokens == 7
    assert response.stop_reason == "end_turn"


def test_abgeschnittene_antwort_wird_als_max_tokens_gemeldet(monkeypatch):
    payload = _ok_payload()
    payload["choices"][0]["finish_reason"] = "length"
    client = _client(monkeypatch, [FakeResponse(200, payload)])
    assert client.complete(system="s", user="u", purpose="test").stop_reason == "max_tokens"


def test_ratengrenze_wird_abgewartet_statt_als_fehler_gezaehlt(monkeypatch):
    """429 ist eine Wartepause, kein Messergebnis."""
    client = _client(
        monkeypatch,
        [
            FakeResponse(429, {}, {"Retry-After": "1"}),
            FakeResponse(429, {}, {"Retry-After": "1"}),
            FakeResponse(200, _ok_payload()),
        ],
    )
    response = client.complete(system="s", user="u", purpose="test")
    assert response.text == '{"ok": true}'
    # Ein einziger protokollierter Aufruf – die Wartepausen sind keine
    # eigenen LLM-Aufrufe und dürfen die Kostenmetrik nicht aufblähen.
    assert len(client.calls) == 1
    assert client.calls[0].ok


def test_dauerhafte_ratengrenze_wird_zum_klaren_fehler(monkeypatch):
    client = _client(monkeypatch, [FakeResponse(429, {}) for _ in range(3)])
    with pytest.raises(LLMError, match="Ratengrenze"):
        client.complete(system="s", user="u", purpose="test")


def test_serverfehler_wird_wiederholt(monkeypatch):
    client = _client(monkeypatch, [FakeResponse(503, {}), FakeResponse(200, _ok_payload())])
    assert client.complete(system="s", user="u", purpose="test").text == '{"ok": true}'


def test_fehlender_schluessel_ergibt_verstaendliche_meldung(monkeypatch):
    client = _client(monkeypatch, [FakeResponse(401, {})])
    with pytest.raises(LLMError, match="SYNTHFHIR_LLM_API_KEY"):
        client.complete(system="s", user="u", purpose="test")


def test_leere_antwort_ist_ein_fehler(monkeypatch):
    client = _client(monkeypatch, [FakeResponse(200, _ok_payload(content="   "))])
    with pytest.raises(LLMError, match="Leere Antwort"):
        client.complete(system="s", user="u", purpose="test")


def test_lokales_modell_gilt_als_kostenlos():
    assert _settings(base_url="http://localhost:11434/v1").is_local
    assert _settings(base_url="http://localhost:11434/v1").prices() == (0.0, 0.0)
    assert not _settings(base_url="https://api.groq.com/openai/v1").is_local


def test_referenztarif_schlaegt_die_automatik():
    """Explizite Preise gewinnen – so bleibt der Kostenvergleich aussagekräftig."""
    settings = _settings(
        base_url="http://localhost:11434/v1",
        price_in_usd_per_mtok=1.0,
        price_out_usd_per_mtok=5.0,
    )
    assert settings.prices() == (1.0, 5.0)


def test_zu_grosse_anfrage_nennt_den_konkreten_grenzwert(monkeypatch):
    """HTTP 413 ist ein Konfigurationsfehler, kein Messergebnis.

    Die Meldung muss so konkret sein, dass sie ohne Nachdenken behebbar ist –
    sonst entwertet ein zu großes max_tokens unbemerkt eine ganze Messreihe.
    """
    body = {
        "error": {
            "message": (
                "Request too large for model `openai/gpt-oss-120b` on tokens per "
                "minute (TPM): Limit 8000, Requested 17844, please reduce your "
                "message size and try again."
            )
        }
    }
    client = _client(monkeypatch, [FakeResponse(413, body)])
    with pytest.raises(LLMError) as exc:
        client.complete(system="s", user="u", purpose="test")
    text = str(exc.value)
    assert "8000" in text and "SYNTHFHIR_LLM_MAX_TOKENS" in text
    # Vorschlag = Limit - Promptanteil - Reserve; muss unter dem Limit liegen.
    assert "höchstens" in text
