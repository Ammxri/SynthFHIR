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
"""

from __future__ import annotations

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


def kennung_aus_anfrage(request) -> str:
    """Ermittelt die Kennung des Aufrufers.

    Hinter einem Proxy — und das ist bei jedem Hosting-Anbieter der Fall —
    steht die echte Adresse in `X-Forwarded-For`. Der Kopf ist fälschbar;
    für eine Portfolio-Demo ist das hinnehmbar, für eine Abrechnung wäre es
    das nicht.
    """
    weitergeleitet = request.headers.get("x-forwarded-for", "")
    if weitergeleitet:
        return weitergeleitet.split(",")[0].strip()
    return request.client.host if request.client else "unbekannt"
