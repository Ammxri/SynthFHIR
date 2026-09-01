"""LLM-Anbindung über OpenAI-kompatible Endpunkte.

Ein einziger Adapter erschließt alle Wege, die das Projekt braucht:

  * **Ollama, lokal** — kostet nichts, Daten verlassen den Rechner nicht.
    Ohne Angabe zeigt der Adapter dorthin.
  * **Groq, OpenRouter, Mistral, Google AI Studio** — kostenlose
    Kontingente, gleiche Schnittstelle, andere Basis-URL.

Die Robustheit stammt aus der Phase 0 und ist dort teuer gelernt worden:
Eine Messreihe war zu einem Drittel unbrauchbar, weil `max_tokens` das
Minutenkontingent des Anbieters überschritt und jede Anfrage mit HTTP 413
abgewiesen wurde. Beide Fälle — Ratengrenze und zu große Anfrage — werden
deshalb ausdrücklich behandelt und nicht als inhaltlicher Fehler verbucht.
"""

from __future__ import annotations

import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests

DEFAULT_BASE_URL = "http://localhost:11434/v1"  # Ollama

# OpenAI nennt den Abbruchgrund anders als Anthropic; vereinheitlicht, damit
# der aufrufende Code nur eine Schreibweise kennen muss.
#
# Zuvor war das ein exakter, kleinschreibungsempfindlicher Vergleich auf
# `"length"`. Ein Anbieter, der `MAX_TOKENS` oder `model_length` meldet,
# schaltete die Erkennung damit ab: `abgeschnitten` blieb False, und der
# Fehlschlag wurde als „kein Feld 'patienten' — vermutlich ein Bruchstück"
# verbucht. Der Betreiber suchte dann beim Modell statt bei `max_tokens` —
# genau die Unterscheidung, die in Phase 0 eine ganze Messreihe gekostet
# hat. Dieses Modul wirbt ausdrücklich mit Groq, OpenRouter, Mistral und
# Google AI Studio; auf eine gemeinsame Schreibweise ist kein Verlass.
FINISH_REASON = {
    "length": "max_tokens",
    "max_tokens": "max_tokens",
    "model_length": "max_tokens",
    "stop": "end_turn",
    "end_turn": "end_turn",
    "stop_sequence": "end_turn",
}

# Voreinstellung für die Antwortlänge. Der Wert MUSS zu dem Prompt passen,
# den dieser Code ausliefert: Anbieter rechnen `max_tokens` in die
# Anfragegröße ein, und im Gratistarif (8000 Token/Minute) bleibt neben
# einem Prompt von rund 2900 Token nicht mehr Platz.
#
# Er stand auf 5600 und passte zum Prompt mit drei Katalogen. Mit den
# Katalogen der Phase 2 wuchs der Prompt, und die veröffentlichte Seite
# antwortete auf JEDE Anfrage mit HTTP 413 — die Voreinstellung wurde in
# `.env.example` gesenkt, aber nicht hier, und ein Deployment ohne gesetzte
# Umgebungsvariable landet genau hier.
#
# `tests/test_llm.py` hält den Wert gegen den tatsächlichen Prompt.
# Gewählt mit Spielraum: Der Teil-Prompt für Kohorten trägt einen Zusatz
# und ist der längste, den dieses Projekt sendet. Bei 4800 lag er pessimistisch
# gerechnet zwei Token über der Grenze — ein Spielraum von zwei Token ist
# keiner.
STANDARD_MAX_TOKENS = 4500

_LIMIT_RE = re.compile(r"Limit\s+(\d+)", re.I)
_REQUESTED_RE = re.compile(r"Requested\s+(\d+)", re.I)


class LLMFehler(RuntimeError):
    """Der Aufruf ist endgültig fehlgeschlagen.

    `art` ist ein geschlossener Wortschatz. Ohne ihn müsste eine
    aufrufende Schicht deutsche Fehlerprosa zerlegen, um zu entscheiden,
    wessen Fehler das war — und ein umformulierter Satz änderte still das
    Verhalten. Die Meldung ist für Menschen, die Art für Code.

    * `nicht_konfiguriert` — der Betreiber hat etwas nicht gesetzt
    * `abgelehnt`          — der Anbieter weist den Schlüssel zurück (401)
    * `kein_zugriff`       — Schlüssel gültig, Modell oder Region gesperrt
    * `kontingent`         — Ratengrenze oder Anfrage zu groß (429/413)
    * `unbrauchbar`        — Antwort kam an, taugt aber nichts
    * `verbindung`         — kein Kontakt zum Anbieter
    """

    def __init__(self, meldung: str, *, art: str = "unbrauchbar") -> None:
        super().__init__(meldung)
        self.art = art


@dataclass(frozen=True)
class LLMAntwort:
    """Antwort eines Aufrufs samt Verbrauch."""

    text: str
    modell: str
    eingabe_token: int
    ausgabe_token: int
    dauer_s: float
    abbruchgrund: str | None = None
    # Die Grenze, gegen die dieser Aufruf lief. Für den Rückfall unten:
    # Ohne sie hinge die Erkennung allein an der Schreibweise, die der
    # Anbieter für „length" gewählt hat.
    token_grenze: int | None = None

    @property
    def abgeschnitten(self) -> bool:
        """True, wenn die Antwort an `max_tokens` endete.

        Wichtig zu unterscheiden: Eine abgeschnittene Antwort ist fast immer
        unparsbar, aber die Ursache liegt in der Konfiguration, nicht beim
        Modell. Wer beides zusammenwirft, misst Konfigurationsfehler als
        Modellversagen.

        Zwei Wege, und der zweite ist der Rückfall: Meldet ein Anbieter den
        Abbruchgrund in einer Schreibweise, die `FINISH_REASON` nicht kennt,
        bleibt immer noch die Zahl. Wer die Grenze ausgeschöpft hat, wurde
        abgeschnitten — auch wenn er es anders nennt.
        """
        if self.abbruchgrund == "max_tokens":
            return True
        return (
            self.token_grenze is not None
            and self.ausgabe_token >= self.token_grenze > 0
        )


class LLMClient(ABC):
    """Schnittstelle, gegen die der Rest des Programms arbeitet."""

    @abstractmethod
    def frage(self, *, system: str, benutzer: str) -> LLMAntwort:
        """Ein Aufruf. Wirft `LLMFehler`, wenn er endgültig scheitert."""


class OpenAIKompatiblerClient(LLMClient):
    """Anbindung an `/v1/chat/completions`."""

    def __init__(
        self,
        modell: str,
        basis_url: str | None = None,
        api_schluessel: str | None = None,
        temperatur: float = 0.7,
        max_tokens: int = STANDARD_MAX_TOKENS,
        timeout_s: float = 180.0,
        versuche: int = 3,
        umgebung_erlaubt: bool = True,
    ) -> None:
        self.modell = modell
        self.basis_url = (basis_url or DEFAULT_BASE_URL).rstrip("/")
        self.temperatur = temperatur
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.versuche = max(1, versuche)

        self.session = requests.Session()
        # `trust_env` steht voreingestellt auf True, und das ist hier
        # gefährlich: Der Schlüssel wird als KOPFZEILE gesetzt, nicht über
        # den `auth`-Parameter. requests sieht ihn an dieser Stelle also
        # nicht, hält die Anfrage für unauthentifiziert und ersetzt bei
        # vorhandener `.netrc` den Bearer-Kopf durch HTTPBasicAuth.
        # Nachgemessen: Ein gesetzter `Bearer sk-...` ging als
        # `Basic <netrc-Zugangsdaten>` hinaus. Aus derselben Wurzel griffen
        # HTTP_PROXY und REQUESTS_CA_BUNDLE der Betreiberumgebung auf einen
        # fremden Schlüssel zu.
        self.session.trust_env = False
        self.session.headers["Content-Type"] = "application/json"

        # Erst normalisieren, dann entscheiden. Vorher stand hier
        #   (api_schluessel or os.environ.get(...)).strip()
        # und das hatte DREI Ausgänge statt zwei: `None` und `""` fielen
        # still auf den Betreiberschlüssel zurück, `"   "` dagegen war für
        # `or` wahr, wurde von `.strip()` geleert und schickte die Anfrage
        # ganz OHNE Authorization hinaus. Alle drei nachgemessen.
        eigener = (api_schluessel or "").strip()
        if eigener:
            self.schluessel_herkunft = "aufrufer"
        elif umgebung_erlaubt:
            eigener = os.environ.get("SYNTHFHIR_LLM_API_KEY", "").strip()
            self.schluessel_herkunft = "betreiber" if eigener else "keiner"
        else:
            # Der Riegel. Ohne ihn hinge die Zusage „niemals auf Kosten des
            # Betreibers" allein daran, dass jeder Aufrufer vorher richtig
            # geprüft hat.
            raise LLMFehler(
                "Ohne eigenen Schlüssel ist dieser Weg gesperrt.",
                art="abgelehnt",
            )
        # Ollama braucht keinen Schlüssel, verträgt aber auch keinen leeren
        # Header - deshalb nur setzen, wenn tatsächlich einer da ist.
        if eigener:
            self.session.headers["Authorization"] = f"Bearer {eigener}"

    def frage(self, *, system: str, benutzer: str) -> LLMAntwort:
        rumpf = {
            "model": self.modell,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": benutzer},
            ],
            "temperature": self.temperatur,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        url = f"{self.basis_url}/chat/completions"
        beginn = time.perf_counter()

        try:
            antwort = self._post_mit_wartepausen(url, rumpf)
        except requests.exceptions.RequestException as exc:
            raise LLMFehler(
                f"Keine Verbindung zu {url}: {exc}\n"
                "  Lokales Ollama: läuft der Dienst?  ollama list\n"
                "  Cloud-Dienst: stimmt SYNTHFHIR_LLM_BASE_URL?",
                art="verbindung",
            ) from exc

        dauer = time.perf_counter() - beginn
        self._pruefe_status(antwort, url)

        try:
            koerper = antwort.json()
        except ValueError as exc:
            raise LLMFehler(f"Antwort von {url} war kein JSON: {antwort.text[:200]!r}") from exc

        auswahl = koerper.get("choices")
        if not isinstance(auswahl, list) or not auswahl:
            raise LLMFehler(f"Antwort ohne 'choices': {str(koerper)[:300]}")

        nachricht = auswahl[0].get("message") or {}
        text = nachricht.get("content")
        if not isinstance(text, str) or not text.strip():
            raise LLMFehler(f"Leere Antwort (finish_reason={auswahl[0].get('finish_reason')!r}).")

        verbrauch = koerper.get("usage") or {}
        grund = auswahl[0].get("finish_reason")
        return LLMAntwort(
            text=text,
            modell=str(koerper.get("model") or self.modell),
            eingabe_token=int(verbrauch.get("prompt_tokens") or 0),
            ausgabe_token=int(verbrauch.get("completion_tokens") or 0),
            dauer_s=dauer,
            abbruchgrund=FINISH_REASON.get(
                str(grund).strip().lower(), str(grund) if grund else None
            ),
            token_grenze=self.max_tokens,
        )

    # -- interne Hilfen -----------------------------------------------------

    def _post_mit_wartepausen(self, url: str, rumpf: dict) -> requests.Response:
        """Wartet bei Ratengrenzen ab, statt sie als Fehler zu verbuchen.

        Kostenlose Kontingente begrenzen Anfragen pro Minute. Ein HTTP 429
        ist eine Wartepause, kein Messergebnis.
        """
        letzte: requests.Response | None = None
        for versuch in range(self.versuche):
            antwort = self.session.post(url, json=rumpf, timeout=self.timeout_s)
            if antwort.status_code != 429 and antwort.status_code < 500:
                return antwort
            letzte = antwort
            if versuch == self.versuche - 1:
                break
            kopfzeile = antwort.headers.get("Retry-After", "")
            try:
                warten = float(kopfzeile)
            except ValueError:
                warten = 0.0
            time.sleep(min(max(warten, 2.0 * (2**versuch)), 60.0))
        assert letzte is not None
        return letzte

    def _pruefe_status(self, antwort: requests.Response, url: str) -> None:
        if antwort.status_code == 429:
            raise LLMFehler(
                f"Ratengrenze bei {url} auch nach Wartezeit aktiv (HTTP 429). "
                "Kontingent erschöpft — später erneut versuchen.",
                art="kontingent",
            )
        if antwort.status_code == 413:
            # Anbieter rechnen `max_tokens` in die Anfragegröße ein. Ein zu
            # großzügiger Wert lässt damit JEDE Anfrage scheitern, obwohl
            # inhaltlich nichts falsch ist.
            limit, angefragt = _grenzwerte(antwort.text)
            hinweis = ""
            if limit and angefragt:
                prompt_anteil = max(angefragt - self.max_tokens, 0)
                vorschlag = max(limit - prompt_anteil - 400, 512)
                hinweis = (
                    f"\n  Kontingent: {limit} Token/Minute, angefragt: {angefragt} "
                    f"(davon {self.max_tokens} als max_tokens reserviert)."
                    f"\n  -> max_tokens auf höchstens {vorschlag} setzen."
                )
            raise LLMFehler(
                f"Anfrage an {url} zu groß für das Kontingent (HTTP 413).{hinweis}",
                art="kontingent",
            )
        if antwort.status_code in (401, 403):
            # Getrennt, weil beide verschiedene Ratschläge verdienen: 401
            # heißt „falscher Schlüssel", 403 „richtiger Schlüssel, falsche
            # Berechtigung" — dasselbe noch einmal zu senden hilft dort
            # nie. Der frühere Text lautete hier „Fehlt
            # SYNTHFHIR_LLM_API_KEY?" und unterstellte damit jedem, der
            # seinen EIGENEN Schlüssel geschickt hatte, eine
            # Fehlkonfiguration des Betreibers.
            welcher = {
                "aufrufer": "Der übermittelte Schlüssel",
                "betreiber": "Der hinterlegte Schlüssel",
                "keiner": "Es wurde kein Schlüssel gesendet; er",
            }[self.schluessel_herkunft]
            if antwort.status_code == 401:
                raise LLMFehler(
                    f"{welcher} wurde vom Anbieter abgelehnt (HTTP 401).",
                    art="abgelehnt",
                )
            raise LLMFehler(
                f"{welcher} hat keinen Zugriff auf {self.modell!r} (HTTP 403).",
                art="kein_zugriff",
            )
        if antwort.status_code == 404:
            raise LLMFehler(
                f"{url} antwortete mit HTTP 404. Stimmt die Basis-URL, und gibt es "
                f"das Modell {self.modell!r}?",
                art="unbrauchbar",
            )
        if antwort.status_code >= 400:
            raise LLMFehler(
                f"{url} antwortete mit HTTP {antwort.status_code}: {antwort.text[:300]}",
                art="unbrauchbar",
            )


class FesterClient(LLMClient):
    """Liefert vorgegebene Antworten — für Tests, nie für den Betrieb."""

    def __init__(
        self,
        antworten: list[str] | str,
        *,
        wiederhole_letzte: bool | None = None,
    ) -> None:
        self.antworten = [antworten] if isinstance(antworten, str) else list(antworten)
        self.aufrufe: list[tuple[str, str]] = []
        self._naechste = 0
        # Eine EINZELNE Antwort ist die übliche Attrappe für „der Aufruf
        # gelingt" und darf sich wiederholen. Eine LISTE ist dagegen eine
        # Erwartung: genau diese Antworten, in dieser Reihenfolge.
        self.wiederhole_letzte = (
            len(self.antworten) == 1
            if wiederhole_letzte is None
            else wiederhole_letzte
        )

    def frage(self, *, system: str, benutzer: str) -> LLMAntwort:
        """Die nächste vorgegebene Antwort.

        Zuvor stand hier

            text = self.antworten.pop(0) if len(self.antworten) > 1 \\
                   else self.antworten[0]

        und damit ging die Liste nie aus: Beim letzten Eintrag hörte das
        Entnehmen auf, und jeder weitere Aufruf bekam ihn erneut. Die
        Schutzabfrage darüber (`if not self.antworten`) konnte nach der
        Konstruktion nie feuern — toter Code.

        Für ein Projekt, dessen Wiederholversuche und Teilaufrufe genau
        daran hängen, ist das eine Messlücke im Werkzeug selbst: Ein Test,
        der drei Antworten hinterlegt und fünf Aufrufe auslöst, konnte
        „öfter gefragt als vorgesehen" grundsätzlich nicht bemerken.
        """
        self.aufrufe.append((system, benutzer))
        if not self.antworten:
            raise LLMFehler("Keine vorgegebene Antwort vorhanden.")
        if self._naechste >= len(self.antworten):
            if not self.wiederhole_letzte:
                raise LLMFehler(
                    f"Der Code hat {len(self.aufrufe)} Mal gefragt, vorgegeben "
                    f"sind {len(self.antworten)} Antworten."
                )
            text = self.antworten[-1]
        else:
            text = self.antworten[self._naechste]
            self._naechste += 1
        return LLMAntwort(
            text=text,
            modell="fest",
            eingabe_token=len(system + benutzer) // 4,
            ausgabe_token=len(text) // 4,
            dauer_s=0.0,
            abbruchgrund="end_turn",
        )


def _zahl_aus_umgebung(name: str, vorgabe: str, wandler):
    """Liest eine Zahl aus der Umgebung — und scheitert wie alle anderen.

    `int(os.environ.get(...))` warf bei einem unlesbaren Wert einen
    `ValueError`. Alle Aufrufer fangen aber ausschliesslich `LLMFehler`
    (`cli.py`, `web/oberflaeche.py`, `web/api.py`), also brach die
    Kommandozeile mit einem Traceback ab und die Weboberfläche antwortete
    mit 500 statt mit 503.

    Das trifft keinen Sonderfall: `SYNTHFHIR_LLM_MAX_TOKENS` wird in
    `.env.example` ausdrücklich als Stellschraube beworben, ist also zum
    Verstellen gedacht — und `4.5k` ist eine naheliegende Schreibweise.
    """
    roh = os.environ.get(name)
    if roh is None or not roh.strip():
        roh = vorgabe
    try:
        return wandler(roh.strip())
    except ValueError:
        raise LLMFehler(
            f"{name} ist auf {roh.strip()!r} gesetzt und ist keine Zahl.",
            art="nicht_konfiguriert",
        ) from None


# Ein Schlüssel darf nur druckbare ASCII-Zeichen enthalten. Das ist keine
# Formsache: `requests` wirft bei einem Zeilenumbruch im Kopfwert eine
# `InvalidHeader`, deren Text den WERT enthält — und `frage()` bettet
# `{exc}` in den `LLMFehler` ein. Nachgemessen landete ein fremder
# Schlüssel so wörtlich in `Ergebnis.fehler`, und von dort in die
# gerenderte Seite und in jede mit `--bericht` geschriebene Datei.
_SCHLUESSEL_MUSTER = re.compile(r"^[!-~]+$")

# Großzügig, aber nicht unbegrenzt: 100 000 Zeichen gingen nachweislich
# ungeprüft an den Anbieter hinaus.
SCHLUESSEL_HOECHSTLAENGE = 4096


def client_mit_fremdschluessel(
    schluessel: str | None,
    *,
    modell: str | None = None,
    timeout_s: float = 40.0,
    versuche: int = 1,
) -> OpenAIKompatiblerClient:
    """Ein Client, der ausschließlich auf Rechnung des Aufrufers arbeitet.

    Der einzige Weg, auf dem der programmatische Zugang einen Client baut.
    Er kennt `client_aus_umgebung` nicht — was nicht importiert ist, kann
    nicht versehentlich aufgerufen werden.

    Drei Riegel, jeder gegen einen nachgemessenen Ausgang:

    1. **Der Schlüssel muss echt sein.** `None` und `""` fielen im
       Konstruktor still auf `SYNTHFHIR_LLM_API_KEY` zurück, reiner
       Leerraum schickte die Anfrage ganz ohne Authorization hinaus.
       Hier scheitert alles drei, bevor ein Client entsteht.
    2. **`umgebung_erlaubt=False`.** Der Riegel sitzt damit an der Quelle
       und nicht bei einem Aufrufer, der ihn vergessen kann.
    3. **Die Basis-URL muss gesetzt sein.** Ohne
       `SYNTHFHIR_LLM_BASE_URL` griffe `DEFAULT_BASE_URL` — und der zeigt
       auf ein lokales Ollama. Der Schlüssel eines Fremden ginge dann an
       einen Dienst, den niemand gemeint hat.

    Zeitgrenzen sind knapper als in der Oberfläche: Dort wartet ein
    Mensch, der zusieht. Hier wartet ein Programm, und jede Sekunde
    belegt einen Platz im Threadpool, der auch die Weboberfläche bedient.
    """
    roh = (schluessel or "").strip()
    if not roh:
        raise LLMFehler(
            "Dieser Zugang verlangt einen eigenen Schlüssel.",
            art="abgelehnt",
        )
    if len(roh) > SCHLUESSEL_HOECHSTLAENGE:
        raise LLMFehler("Der Schlüssel ist zu lang.", art="abgelehnt")
    if not _SCHLUESSEL_MUSTER.match(roh):
        # Absichtlich ohne den Wert: Diese Meldung wird weitergereicht.
        raise LLMFehler(
            "Der Schlüssel enthält Zeichen, die in einer HTTP-Kopfzeile "
            "nicht zulässig sind.",
            art="abgelehnt",
        )

    basis_url = (os.environ.get("SYNTHFHIR_LLM_BASE_URL") or "").strip()
    if not basis_url:
        raise LLMFehler(
            "SYNTHFHIR_LLM_BASE_URL ist nicht gesetzt.",
            art="nicht_konfiguriert",
        )
    gewaehlt = (modell or os.environ.get("SYNTHFHIR_LLM_MODEL", "")).strip()
    if not gewaehlt:
        raise LLMFehler(
            "SYNTHFHIR_LLM_MODEL ist nicht gesetzt.",
            art="nicht_konfiguriert",
        )

    return OpenAIKompatiblerClient(
        modell=gewaehlt,
        basis_url=basis_url,
        api_schluessel=roh,
        max_tokens=_zahl_aus_umgebung(
            "SYNTHFHIR_LLM_MAX_TOKENS", str(STANDARD_MAX_TOKENS), int
        ),
        timeout_s=timeout_s,
        versuche=versuche,
        umgebung_erlaubt=False,
    )


def client_aus_umgebung() -> LLMClient:
    """Baut den Client aus den Umgebungsvariablen.

    Schlüssel kommen ausschließlich aus der Umgebung, niemals aus dem Code
    (PRD Block 6).
    """
    modell = os.environ.get("SYNTHFHIR_LLM_MODEL", "").strip()
    if not modell:
        raise LLMFehler(
            "SYNTHFHIR_LLM_MODEL ist nicht gesetzt. Verfügbare Modelle des Anbieters:\n"
            f"  curl {os.environ.get('SYNTHFHIR_LLM_BASE_URL', DEFAULT_BASE_URL)}/models",
            art="nicht_konfiguriert",
        )
    return OpenAIKompatiblerClient(
        modell=modell,
        basis_url=os.environ.get("SYNTHFHIR_LLM_BASE_URL") or None,
        temperatur=_zahl_aus_umgebung("SYNTHFHIR_LLM_TEMPERATURE", "0.7", float),
        max_tokens=_zahl_aus_umgebung(
            "SYNTHFHIR_LLM_MAX_TOKENS", str(STANDARD_MAX_TOKENS), int
        ),
    )


def _grenzwerte(text: str) -> tuple[int | None, int | None]:
    """Liest "Limit N ... Requested M" aus der Fehlermeldung des Anbieters."""
    limit = _LIMIT_RE.search(text)
    angefragt = _REQUESTED_RE.search(text)
    return (
        int(limit.group(1)) if limit else None,
        int(angefragt.group(1)) if angefragt else None,
    )
