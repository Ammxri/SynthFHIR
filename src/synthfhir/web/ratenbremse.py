"""Ratenbremse für den Demo-Betrieb.

Die veröffentlichte Seite bedient anonyme Besucher mit dem Schlüssel des
Betreibers. Beim genutzten Gratiskontingent reicht das für rund **eine
Anfrage pro Minute — weltweit**: Eine Generierung kostet gemessen etwa 2100
Eingabe- und bis zu 4800 Ausgabe-Token, das Minutenkontingent liegt bei
8000. Ohne Bremse leert ein einziger Besucher das Kontingent für alle
anderen.

Bewusst im Arbeitsspeicher, nicht in einer Datenbank: Das PRD schließt
Persistenz für den MVP aus (Block 9). Daraus folgen zwei Grenzen, die man
kennen muss:

  * Ein Neustart setzt alle Zähler zurück.
  * Bei mehreren Instanzen zählt jede für sich.

Für eine Portfolio-Demo ist beides tragbar. Wer die Bremse umgehen will,
bringt seinen eigenen Schlüssel mit — das ist der vorgesehene Weg und keine
Lücke.

===========================================================================
ZWEI BREMSEN, WEIL EINE FÄLSCHBAR IST
===========================================================================

Die Bremse je Adresse hat eine Schwäche, die gemessen wurde und nicht
theoretisch ist: 30 Anfragen mit jeweils anderem ``X-Forwarded-For``
ergaben **30 Aufrufe auf den Betreiberschlüssel und kein einziges 429**.
Mit fester Adresse greift sie korrekt ab der sechsten.

Die Ursache war die Auswahl des Glieds. ``X-Forwarded-For`` wächst von
links nach rechts: Jeder Proxy hängt **an**, von welcher Adresse er
empfangen hat. Das linke Glied stammt damit aus der Anfrage selbst und ist
frei erfunden; das rechte hat der letzte — und einzige vertrauenswürdige —
Proxy geschrieben. Gelesen wurde bisher das linke.

Von rechts zu zählen behebt den Fall, verlässt sich aber weiterhin auf eine
richtig eingestellte Zahl vertrauenswürdiger Proxys. Deshalb steht daneben
eine **Gesamtbremse**, die keine Kennung kennt: Sie zählt schlicht, wie oft
der Schlüssel des Betreibers insgesamt benutzt wurde. Sie lässt sich nicht
fälschen, weil es nichts zu fälschen gibt.

Der Preis ist ehrlich zu nennen: Wer die Gesamtbremse ausschöpft, sperrt
für den Rest des Fensters auch alle anderen anonymen Besucher aus. Das ist
gewollt. Die Zusage lautet „das Kontingent des Betreibers bleibt seines",
nicht „jeder Besucher bekommt seinen Anteil" — und ein erschöpftes
Gratiskontingent sperrt ohnehin alle aus, nur eben ohne dass es jemand
gewollt hätte.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque


class Ratenbremse:
    """Begrenzt Anfragen je Kennung innerhalb eines Zeitfensters."""

    def __init__(self, anfragen: int = 5, zeitfenster_s: float = 3600.0) -> None:
        self.anfragen = max(1, anfragen)
        self.zeitfenster_s = zeitfenster_s
        self._verlauf: dict[str, deque[float]] = defaultdict(deque)
        # uvicorn bedient Anfragen in mehreren Threads; ohne Sperre könnten
        # zwei gleichzeitige Besucher denselben Platz belegen.
        self._sperre = threading.Lock()

    def pruefe(self, kennung: str) -> tuple[bool, int]:
        """(erlaubt, Sekunden bis zum nächsten freien Platz).

        Ein erlaubter Aufruf wird sofort verbucht — die Methode fragt nicht
        nur, sie nimmt den Platz auch in Anspruch.
        """
        jetzt = time.monotonic()
        with self._sperre:
            eintraege = self._verlauf[kennung]
            while eintraege and jetzt - eintraege[0] > self.zeitfenster_s:
                eintraege.popleft()

            if len(eintraege) < self.anfragen:
                eintraege.append(jetzt)
                return True, 0

            wartezeit = self.zeitfenster_s - (jetzt - eintraege[0])
            return False, max(1, int(wartezeit))

    def zuruecksetzen(self) -> None:
        """Leert alle Zähler.

        Für Tests, und als Notausgang im Betrieb, falls die Bremse einmal
        jemanden aussperrt, der nicht ausgesperrt gehört.
        """
        with self._sperre:
            self._verlauf.clear()

    def aufraeumen(self) -> None:
        """Entfernt Kennungen ohne aktuelle Einträge.

        Ohne das wüchse der Speicher mit jeder je gesehenen IP-Adresse.
        """
        jetzt = time.monotonic()
        with self._sperre:
            for kennung in list(self._verlauf):
                eintraege = self._verlauf[kennung]
                while eintraege and jetzt - eintraege[0] > self.zeitfenster_s:
                    eintraege.popleft()
                if not eintraege:
                    del self._verlauf[kennung]


# Wie viele Proxys zwischen Aufrufer und Anwendung stehen, deren Angaben
# man glauben darf. Bei Render ist es genau einer, und `render.yaml` setzt
# die Variable dort ausdrücklich auf 1.
#
# Die Vorgabe war 1, und der Kommentar behauptete, das sei die
# kleinstmögliche. Das war falsch, und der Unterschied ist keine
# Wortklauberei: Steht **kein** Proxy davor, ist die Kette genau ein Glied
# lang, dieses Glied hat der Aufrufer selbst geschrieben, und
# `glieder[-min(1, 1)]` gibt genau es zurück. Wer `X-Forwarded-For`
# rotieren liess, bekam damit bei jeder Anfrage eine neue Kennung — also
# wieder die Lücke, die das Zählen von rechts gerade schliessen sollte,
# nur eine Ebene tiefer. Betroffen war jeder Betrieb ohne Reverse-Proxy:
# `docker run -p 8000:8000`, `synthfhir-web`, eigenes Hosting. Das
# Dockerfile bindet uvicorn direkt, ohne dass ein Proxy Teil des Abbilds
# wäre.
#
# 0 heisst: keiner Kopfzeile glauben, die Verbindung zählt. Das ist die
# einzige Vorgabe, die ohne Kenntnis der Umgebung sicher ist. Sie ist im
# Zweifel zu streng — hinter einem Proxy teilen sich dann alle Besucher
# eine Kennung —, und das ist die richtige Richtung für einen Fehler, der
# über fremde Abrechnung entscheidet. Wer einen Proxy davor hat, sagt es.
VERTRAUTE_PROXYS = int(os.environ.get("SYNTHFHIR_VERTRAUTE_PROXYS", "0"))


def kennung_aus_anfrage(request, vertraute_proxys: int | None = None) -> str:
    """Ermittelt die Kennung des Aufrufers.

    Hinter einem Proxy — und das ist bei jedem Hosting-Anbieter der Fall —
    steht die echte Adresse in `X-Forwarded-For`. Gelesen wird das Glied,
    das der letzte vertrauenswürdige Proxy geschrieben hat, also das
    `vertraute_proxys`-te von **rechts**.

    Zuvor stand hier `split(",")[0]`, also das linke Glied. Das schreibt
    der Aufrufer selbst, und die Bremse wirkte damit ausschließlich gegen
    ehrliche Clients — nachgemessen: 30 Anfragen mit rotierendem Kopf,
    30 Aufrufe, kein 429.
    """
    hops = VERTRAUTE_PROXYS if vertraute_proxys is None else vertraute_proxys

    # Mehrfach gesendete Kopfzeilen zusammenführen, statt still die erste zu
    # nehmen. Starlettes `Headers` ist ein Multidict, und `.get()` liefert
    # dort das erste Vorkommen. `api.py` liest den Schlüsselkopf aus genau
    # diesem Grund über `getlist` und begründet es dort: „Bei einer Frage,
    # die über fremde Abrechnung entscheidet, ist ‚still den ersten nehmen'
    # die falsche Vorgabe." Für die Bremse gilt dieselbe Frage, hier stand
    # aber `get`.
    #
    # Zusammengeführt und nicht bloss ersetzt: Hängt ein Proxy die echte
    # Adresse als ZWEITE Kopfzeile an, statt sie in die erste einzureihen,
    # stünde sie sonst nirgends — und gezählt würde ausschliesslich die
    # gefälschte.
    kopfzeilen = request.headers
    if hasattr(kopfzeilen, "getlist"):
        roh = ", ".join(kopfzeilen.getlist("x-forwarded-for"))
    else:
        roh = kopfzeilen.get("x-forwarded-for", "")

    glieder = [g.strip() for g in roh.split(",") if g.strip()]
    if glieder and hops > 0:
        # min(): Sind weniger Glieder da als erwartet, ist das linkeste das
        # beste, was zu haben ist — und nicht etwa ein Griff ins Leere.
        return glieder[-min(hops, len(glieder))]
    return request.client.host if request.client else "unbekannt"
