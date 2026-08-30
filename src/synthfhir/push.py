"""Kohorten direkt in einen FHIR-Server laden (Phase 2).

===========================================================================
WARUM DIESES MODUL ANDERS BEHANDELT WIRD ALS ALLES BISHERIGE
===========================================================================

Bis hierher erzeugte SynthFHIR **Dateien**. Wer sie nicht mag, löscht sie.
Dieses Modul schreibt in ein **fremdes System**, und ein Tippfehler in der
Ziel-URL schriebe zweihundert erfundene Patienten in etwas, das vielleicht
kein Testserver ist.

Die Spezifikation des Projekts sagt: *„Es dürfen zu keinem Zeitpunkt echte
Patientendaten verarbeitet werden."* Das ist eine Aussage über die Eingabe.
Ab hier braucht es die Gegenrichtung: Die Ausgabe darf nicht dort landen,
wo echte Daten liegen.

Deshalb vier Schutzmechanismen, in dieser Reihenfolge:

**1. Jede Ressource trägt `meta.security` HTEST.** Nicht erst beim Push —
das Kennzeichen sitzt schon in den Vorlagen (`templates.py`). Damit ist die
Zusage „nur Testdaten" nicht mehr nur eine Zeile im README, sondern eine
Angabe, nach der ein Server suchen kann (`_security=HTEST`, an HAPI
nachgeprüft).

**2. Trockenlauf ist die Voreinstellung.** `pushe(...)` schreibt nichts,
solange nicht ausdrücklich `ausfuehren=True` gesetzt ist. Wer sich vertippt,
sieht den Tippfehler, bevor er wirkt.

**3. Der Zielserver wird vorher befragt.** Zwei Fragen: Ist das überhaupt
ein FHIR-Server (`/metadata`)? Und liegen dort Daten **ohne** HTEST-Label?
Die zweite ist die wichtigere — sie ist der einzige Hinweis darauf, dass
das Ziel womöglich kein Testserver ist. Antwortet der Server darauf nicht,
gilt das als Warnung, nicht als Freigabe.

Zwei Fallstricke dabei, beide gemessen. Die Zählung läuft über
`_total=accurate`, nicht über eine Schätzung. Und das Label wird mit
seinem System gesucht (`System|HTEST`): Eine Suche nach dem Code allein
traf auch eine Ressource, die HTEST unter einem anderen System trug — der
Wächter hätte fremde Daten für eigene gehalten.

**Und was dieser Wächter ausdrücklich nicht ist: ein Beweis.** Er liest
den Suchindex des Zielservers, und der hängt hinterher. Gemessen: Nach
einem Push meldete HAPI über eine Minute lang 0 Patienten, während ein
direkter Lesezugriff sie sehr wohl lieferte. Wer also kurz vorher etwas
auf das Ziel geschrieben hat — ein anderer Nutzer, ein anderer Lauf —,
sieht hier womöglich zu wenig.

Der Wächter senkt das Risiko, er beseitigt es nicht. Die eigentliche
Sicherung bleibt, dass die Ziel-URL ausdrücklich genannt werden muss und
der Trockenlauf zeigt, was geschähe, bevor es geschieht.

**4. Nur vollständige, geprüfte Kohorten.** Was `fertig` nicht erfüllt,
wird nicht gepusht. Eine halbe Kohorte in einen fremden Server zu schreiben
und dort liegen zu lassen, wäre schlimmer als gar nichts zu schreiben.

===========================================================================
WARUM TRANSAKTIONEN UND NICHT EINZELNE PUTS
===========================================================================

Gemessen an HAPI 4.0.1 (2026-08-30): Ein Transaction-Bundle mit einem
fehlerhaften Eintrag endet mit HTTP 400, und **auch der gute Eintrag ist
danach nicht angelegt** (404). Transaktionen sind also atomar — genau das,
was man will, wenn man in ein fremdes System schreibt: entweder das Paket
ist drin oder es ist nichts drin.

Einzelne PUTs hinterließen bei einem Fehler in der Mitte einen halben
Datensatz auf einem Server, auf den man womöglich keinen Löschzugriff hat.

Gepusht wird in **Paketen**, nicht als ein einziges Bundle: Ein
Transaction-Bundle über tausend Ressourcen ist eine einzige riesige
Anfrage, und Server begrenzen die Größe. Die Pakete folgen der
Ladereihenfolge aus ADR-005 — referenzierte Typen zuerst —, damit ein
Verweis nicht auf etwas zeigt, das erst im nächsten Paket kommt.

Die Einträge benutzen **PUT**, nicht POST: Die Kennungen vergibt dieses
Projekt selbst (`pat-001`), und PUT ist damit idempotent. Zweimal denselben
Push auszuführen ergibt denselben Serverzustand statt doppelter Patienten.
Das ist zugleich die Kehrseite: PUT **überschreibt**, was unter derselben
Kennung schon dort liegt. Genau deshalb Schutzmechanismus 3.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import requests

from .domain.codes import TESTDATEN_LABEL
from .domain.integrity import ladereihenfolge

# Ressourcen je Transaktion. Klein genug, dass kein Server die Anfrage
# ablehnt, groß genug, dass ein Push über 1000 Ressourcen nicht in
# hunderten Anfragen zerfällt.
PAKETGROESSE = 100

TIMEOUT_S = 120.0

# Umgebungsvariable für das Zugangstoken. Ausdrücklich **kein**
# Kommandozeilenargument: Argumente stehen in der Shell-Historie und in der
# Prozessliste, wo sie jeder Mitbenutzer des Rechners lesen kann.
TOKEN_VARIABLE = "SYNTHFHIR_PUSH_TOKEN"

# Ein Sicherheitslabel, das es nirgends gibt. Es dient als Gegenprobe: Ein
# Server, der `_security` beachtet, findet darauf nichts. Liefert er
# stattdessen die volle Trefferzahl, ignoriert er den Parameter — und dann
# ist auch seine Auskunft über HTEST wertlos.
UNSINNSLABEL = "http://synthfhir.invalid/kein-system|KEIN-CODE"

# FHIR-Ressourcentypen bestehen nur aus Buchstaben. Der Typ wird zum
# URL-Pfad der Transaktion; ohne diese Prüfung schriebe ein Wert wie
# "../woanders" an eine andere Stelle des Servers.
TYP_MUSTER = re.compile(r"^[A-Za-z]+$")
KENNUNG_MUSTER = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")


class PushFehler(RuntimeError):
    """Der Push konnte nicht ausgeführt werden."""


@dataclass
class Zielbefund:
    """Was die Vorabfrage über den Zielserver ergeben hat."""

    url: str
    erreichbar: bool = False
    fhir_version: str | None = None
    ressourcen_gesamt: int | None = None
    ressourcen_mit_testlabel: int | None = None
    security_filter_wirkt: bool | None = None
    hinweise: list[str] = field(default_factory=list)

    @property
    def fremde_daten(self) -> bool:
        """Liegen dort Daten, die NICHT als Testdaten gekennzeichnet sind?

        Jede Unsicherheit zählt als Ja. Wer nicht sagen kann, was auf dem
        Zielsystem liegt, sollte nicht hineinschreiben.

        Der erste Zweig ist der wichtigste und war zuerst nicht da: Ein
        FHIR-Server darf einen unbekannten Suchparameter stillschweigend
        ignorieren, und beide gemessenen Server tun das auch (ein
        erfundener Parameter liefert die volle Trefferzahl). Beachtet das
        Ziel `_security` nicht, wären beide Zahlen gleich groß — und der
        Wächter hielte einen Server voller echter Patienten für einen
        leeren Testserver. Er versagte damit nach der falschen Seite.
        """
        if self.security_filter_wirkt is not True:
            return True
        if self.ressourcen_gesamt is None or self.ressourcen_mit_testlabel is None:
            return True
        return self.ressourcen_gesamt > self.ressourcen_mit_testlabel

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "erreichbar": self.erreichbar,
            "fhir_version": self.fhir_version,
            "ressourcen_gesamt": self.ressourcen_gesamt,
            "ressourcen_mit_testlabel": self.ressourcen_mit_testlabel,
            "security_filter_wirkt": self.security_filter_wirkt,
            "fremde_daten": self.fremde_daten,
            "hinweise": self.hinweise,
        }


@dataclass
class Pushergebnis:
    """Was der Push bewirkt hat — oder bewirkt hätte."""

    ziel: str
    trockenlauf: bool
    befund: Zielbefund | None = None
    pakete: int = 0
    geschrieben: int = 0
    fehler: list[str] = field(default_factory=list)
    reihenfolge: list[str] = field(default_factory=list)

    @property
    def erfolgreich(self) -> bool:
        return not self.fehler and (self.trockenlauf or self.geschrieben > 0)

    def to_dict(self) -> dict:
        return {
            "ziel": self.ziel,
            "trockenlauf": self.trockenlauf,
            "reihenfolge": self.reihenfolge,
            "pakete": self.pakete,
            "geschrieben": self.geschrieben,
            "fehler": self.fehler,
            "befund": self.befund.to_dict() if self.befund else None,
        }


def _sitzung(token: str | None) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"}
    )
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


def befrage_ziel(url: str, token: str | None = None) -> Zielbefund:
    """Fragt den Zielserver, bevor irgendetwas geschrieben wird.

    Zwei Fragen, und die zweite ist die wichtige: Wie viele Ressourcen
    liegen dort insgesamt, und wie viele davon tragen das Testdaten-Label?
    Ist die erste Zahl größer, liegen dort Daten, die nicht von SynthFHIR
    stammen — ein starker Hinweis darauf, dass das Ziel kein Testserver ist.
    """
    basis = url.rstrip("/")
    befund = Zielbefund(url=basis)
    s = _sitzung(token)

    try:
        antwort = s.get(f"{basis}/metadata", timeout=TIMEOUT_S)
    except requests.exceptions.RequestException as exc:
        befund.hinweise.append(f"nicht erreichbar: {_ohne_token(str(exc))}")
        return befund

    if antwort.status_code >= 400:
        befund.hinweise.append(
            f"/metadata antwortet mit HTTP {antwort.status_code} — "
            "kein FHIR-Server, oder die Anmeldung fehlt."
        )
        return befund

    try:
        koerper = antwort.json()
    except ValueError:
        befund.hinweise.append("/metadata liefert kein JSON — vermutlich kein FHIR-Server.")
        return befund

    if koerper.get("resourceType") != "CapabilityStatement":
        befund.hinweise.append(
            f"/metadata liefert {koerper.get('resourceType')!r} statt eines "
            "CapabilityStatement."
        )
        return befund

    befund.erreichbar = True
    befund.fhir_version = str(koerper.get("fhirVersion") or "unbekannt")

    befund.ressourcen_gesamt = _zaehle(s, basis, {})
    befund.ressourcen_mit_testlabel = _zaehle(
        s, basis, {"_security": f"{TESTDATEN_LABEL['system']}|{TESTDATEN_LABEL['code']}"}
    )
    # Gegenprobe VOR der Auswertung: Beachtet der Server den Filter?
    probe = _zaehle(s, basis, {"_security": UNSINNSLABEL})
    befund.security_filter_wirkt = None if probe is None else probe == 0
    if befund.security_filter_wirkt is False:
        befund.hinweise.append(
            "Der Server beantwortet Suchen nach _security nicht: Ein Filter "
            "auf ein erfundenes Label liefert Treffer. Seine Auskunft "
            "darüber, was dort liegt, ist damit wertlos."
        )
    if befund.ressourcen_gesamt is None:
        befund.hinweise.append(
            "Der Server beantwortet keine Zählabfrage. Ob dort echte Daten "
            "liegen, lässt sich damit nicht feststellen."
        )
    return befund


def _zaehle(s: requests.Session, basis: str, zusatz: dict) -> int | None:
    """Zählt Patienten auf dem Zielserver, oder None wenn er nicht antwortet.

    Gezählt werden Patienten und nicht alle Ressourcen: Eine Suche über
    alle Typen unterstützt nicht jeder Server, eine Suche auf `Patient`
    dagegen praktisch jeder. Für die Frage „liegen hier echte Daten?"
    genügt der Patientenbestand.

    `_total=accurate` statt `_summary=count`: Beide liefern hier dasselbe,
    aber `_total` ist der Suchparameter, der eine **genaue** Gesamtzahl
    verlangt. Ein geschätzter Wert taugt für einen Schutzmechanismus nicht.

    Das Sicherheitslabel wird immer mit seinem System gesucht
    (`System|HTEST`), nie mit dem Code allein. Nachgemessen: Eine Suche
    nach `HTEST` ohne System traf auch eine Ressource, die den Code unter
    einem **anderen** System trug. Für einen Wächter, der Testdaten von
    echten unterscheiden soll, wäre das ein Treffer zu viel — er hielte
    fremde Daten für eigene.
    """
    try:
        antwort = s.get(
            f"{basis}/Patient",
            params={"_total": "accurate", "_count": 0, **zusatz},
            timeout=TIMEOUT_S,
        )
        if antwort.status_code >= 400:
            return None
        return int(antwort.json().get("total"))
    except (requests.exceptions.RequestException, ValueError, TypeError):
        return None


def _ohne_token(text: str) -> str:
    """Entfernt ein etwaiges Token aus einer Meldung.

    Fehlermeldungen von `requests` können die vollständige Anfrage
    enthalten. Ein Token, das einmal in einem Bericht oder einem Protokoll
    steht, ist nicht mehr geheim.
    """
    token = os.environ.get(TOKEN_VARIABLE, "").strip()
    if token and token in text:
        text = text.replace(token, "<Token entfernt>")
    return text


def baue_transaktion(ressourcen: list[dict]) -> dict:
    """Ein Transaction-Bundle mit PUT-Einträgen.

    PUT und nicht POST: Die Kennungen kommen aus diesem Projekt, damit ist
    der Push idempotent — zweimal ausgeführt ergibt denselben Zustand statt
    doppelter Patienten.
    """
    eintraege = []
    for r in ressourcen:
        typ = str(r.get("resourceType") or "")
        kennung = str(r.get("id") or "")
        # Beide wandern ungefiltert in den URL-Pfad der Transaktion. Ein
        # `resourceType` von "../Binary" schriebe an eine andere Stelle des
        # Servers, als der Aufrufer meint. Im eigenen Ablauf setzen die
        # Vorlagen beides, aber `pushe` nimmt beliebige dicts entgegen.
        if not TYP_MUSTER.match(typ):
            raise PushFehler(
                f"{typ!r} ist kein Ressourcentyp. Der Typ wird zum URL-Pfad."
            )
        if not KENNUNG_MUSTER.match(kennung):
            raise PushFehler(
                f"{typ}: {kennung!r} ist keine zulässige Kennung. Sie wird "
                "zum URL-Pfad."
            )
        eintraege.append(
            {"resource": r, "request": {"method": "PUT", "url": f"{typ}/{kennung}"}}
        )
    return {"resourceType": "Bundle", "type": "transaction", "entry": eintraege}


def _pakete(ressourcen: list[dict], groesse: int) -> list[list[dict]]:
    """Zerlegt in Pakete, referenzierte Typen zuerst.

    Die Reihenfolge kommt aus derselben Funktion wie beim NDJSON-Export
    (ADR-005): abgeleitet aus den tatsächlichen Verweisen. Innerhalb eines
    Pakets löst der Server Verweise selbst auf; über Paketgrenzen hinweg
    muss das Ziel schon dagewesen sein.
    """
    nach_typ: dict[str, list[dict]] = {}
    for r in ressourcen:
        nach_typ.setdefault(str(r.get("resourceType") or "?"), []).append(r)

    geordnet: list[dict] = []
    for typ in ladereihenfolge(nach_typ):
        geordnet.extend(nach_typ[typ])
    return [geordnet[i : i + groesse] for i in range(0, len(geordnet), max(1, groesse))]


def pushe(
    ressourcen: list[dict],
    url: str,
    *,
    ausfuehren: bool = False,
    fremde_daten_ok: bool = False,
    token: str | None = None,
    paketgroesse: int = PAKETGROESSE,
) -> Pushergebnis:
    """Lädt eine Kohorte in einen FHIR-Server.

    **Schreibt nur, wenn `ausfuehren=True`.** Die Voreinstellung ist ein
    Trockenlauf: Er befragt das Ziel und berichtet, was geschähe. Das ist
    Absicht — ein Tippfehler in der URL soll sichtbar werden, bevor er
    wirkt, nicht danach.

    `fremde_daten_ok` hebt die Sperre auf, die greift, wenn auf dem Ziel
    Daten ohne Testkennzeichen liegen. Wer sie setzt, sagt damit: Ich weiß,
    was dort liegt.
    """
    if token is None:
        token = os.environ.get(TOKEN_VARIABLE, "").strip() or None

    ergebnis = Pushergebnis(ziel=url.rstrip("/"), trockenlauf=not ausfuehren)
    if not ressourcen:
        ergebnis.fehler.append("Keine Ressourcen zum Übertragen.")
        return ergebnis

    ohne_label = [
        f"{r.get('resourceType')}/{r.get('id')}"
        for r in ressourcen
        if not _traegt_testlabel(r)
    ]
    if ohne_label:
        # Nicht nachrüsten, sondern abbrechen: Wenn hier etwas ohne
        # Kennzeichen ankommt, stimmt weiter oben etwas nicht, und das
        # gehört gesehen statt stillschweigend geflickt.
        ergebnis.fehler.append(
            f"{len(ohne_label)} Ressourcen ohne Testdaten-Kennzeichen, "
            f"z. B. {ohne_label[0]}. Push abgebrochen."
        )
        return ergebnis

    befund = befrage_ziel(url, token)
    ergebnis.befund = befund
    if not befund.erreichbar:
        ergebnis.fehler.extend(befund.hinweise or ["Ziel nicht erreichbar."])
        return ergebnis

    if befund.fremde_daten and not fremde_daten_ok:
        ergebnis.fehler.append(
            f"Auf {befund.url} liegen Daten ohne Testkennzeichen "
            f"({befund.ressourcen_gesamt} Patienten, davon "
            f"{befund.ressourcen_mit_testlabel} als Testdaten markiert). "
            "Das könnte ein produktives System sein. Push abgebrochen."
            if befund.ressourcen_gesamt is not None
            else f"Auf {befund.url} lässt sich der Bestand nicht ermitteln. "
            "Ob dort echte Daten liegen, ist damit unbekannt. Push abgebrochen."
        )
        return ergebnis

    try:
        # Einmal über alles, bevor irgendetwas gesendet wird: Ein Abbruch
        # mitten in der Reihe hinterließe geschriebene Pakete auf einem
        # fremden Server.
        for r in ressourcen:
            baue_transaktion([r])
    except PushFehler as exc:
        ergebnis.fehler.append(str(exc))
        return ergebnis

    pakete = _pakete(ressourcen, paketgroesse)
    ergebnis.pakete = len(pakete)
    ergebnis.reihenfolge = list(
        dict.fromkeys(r["resourceType"] for p in pakete for r in p)
    )

    if not ausfuehren:
        return ergebnis

    s = _sitzung(token)
    for nummer, paket in enumerate(pakete, start=1):
        rumpf = json.dumps(baue_transaktion(paket), ensure_ascii=False).encode("utf-8")
        try:
            antwort = s.post(befund.url, data=rumpf, timeout=TIMEOUT_S)
        except requests.exceptions.RequestException as exc:
            ergebnis.fehler.append(f"Paket {nummer}: {_ohne_token(str(exc))}")
            break
        if antwort.status_code >= 400:
            ergebnis.fehler.append(
                f"Paket {nummer}: HTTP {antwort.status_code} — "
                f"{_ohne_token(antwort.text[:200])}"
            )
            # Die Transaktion ist atomar: Dieses Paket ist vollständig
            # zurückgerollt. Abbrechen statt weiterzumachen — sonst
            # entstünde eine Lücke mitten in der Kohorte.
            break
        ergebnis.geschrieben += len(paket)

    return ergebnis


def _traegt_testlabel(ressource: dict) -> bool:
    security = (ressource.get("meta") or {}).get("security") or []
    return any(
        isinstance(s, dict)
        and s.get("system") == TESTDATEN_LABEL["system"]
        and s.get("code") == TESTDATEN_LABEL["code"]
        for s in security
    )
