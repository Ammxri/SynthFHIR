"""Tests der Ratenbremse.

Sie ist die einzige Absicherung des Demo-Kontingents. Fällt sie aus, leert
ein einzelner Besucher den Schlüssel des Betreibers für alle anderen.
"""

from __future__ import annotations

import threading

from synthfhir.web.ratenbremse import Ratenbremse, kennung_aus_anfrage


class FalscheAnfrage:
    """Nachbau des Teils von `Request`, den die Kennung braucht."""

    def __init__(self, host: str | None = "1.2.3.4", weitergeleitet: str | None = None):
        self.headers = {"x-forwarded-for": weitergeleitet} if weitergeleitet else {}
        self.client = type("K", (), {"host": host})() if host else None


def test_kontingent_wird_eingehalten():
    bremse = Ratenbremse(anfragen=3, zeitfenster_s=3600)
    assert [bremse.pruefe("a")[0] for _ in range(4)] == [True, True, True, False]


def test_kennungen_zaehlen_getrennt():
    """Ein Vielnutzer darf andere Besucher nicht aussperren."""
    bremse = Ratenbremse(anfragen=2, zeitfenster_s=3600)
    for _ in range(2):
        bremse.pruefe("a")
    assert bremse.pruefe("a")[0] is False
    assert bremse.pruefe("b")[0] is True


def test_wartezeit_wird_genannt():
    bremse = Ratenbremse(anfragen=1, zeitfenster_s=3600)
    bremse.pruefe("a")
    erlaubt, wartezeit = bremse.pruefe("a")
    assert not erlaubt
    assert 3500 < wartezeit <= 3600


def test_alte_eintraege_verfallen():
    bremse = Ratenbremse(anfragen=1, zeitfenster_s=0.05)
    assert bremse.pruefe("a")[0]
    assert not bremse.pruefe("a")[0]
    import time

    time.sleep(0.06)
    assert bremse.pruefe("a")[0], "Nach dem Zeitfenster muss wieder etwas gehen"


def test_aufraeumen_gibt_speicher_frei():
    """Ohne das wüchse der Speicher mit jeder je gesehenen Adresse."""
    bremse = Ratenbremse(anfragen=5, zeitfenster_s=0.01)
    for i in range(50):
        bremse.pruefe(f"adresse-{i}")
    import time

    time.sleep(0.02)
    bremse.aufraeumen()
    assert len(bremse._verlauf) == 0


def test_zuruecksetzen_leert_alles():
    bremse = Ratenbremse(anfragen=1, zeitfenster_s=3600)
    bremse.pruefe("a")
    bremse.zuruecksetzen()
    assert bremse.pruefe("a")[0]


def test_gleichzeitige_zugriffe_vergeben_keinen_platz_doppelt():
    """uvicorn bedient Anfragen in mehreren Threads. Ohne Sperre könnten
    zwei gleichzeitige Besucher denselben Platz belegen."""
    bremse = Ratenbremse(anfragen=10, zeitfenster_s=3600)
    ergebnisse: list[bool] = []
    sperre = threading.Lock()

    def anfragen():
        erlaubt, _ = bremse.pruefe("gemeinsam")
        with sperre:
            ergebnisse.append(erlaubt)

    faeden = [threading.Thread(target=anfragen) for _ in range(40)]
    for f in faeden:
        f.start()
    for f in faeden:
        f.join()

    assert sum(ergebnisse) == 10, "Genau zehn Plätze, nicht mehr und nicht weniger"


# --- Kennung des Aufrufers -------------------------------------------------


def test_kennung_kommt_aus_der_verbindung():
    assert kennung_aus_anfrage(FalscheAnfrage(host="9.9.9.9")) == "9.9.9.9"


def test_proxy_kopf_hat_vorrang():
    """Hinter einem Proxy - und das ist bei jedem Hosting-Anbieter der Fall -
    wäre die Verbindungsadresse für alle Besucher dieselbe.

    Gelesen wird das Glied, das der letzte vertrauenswürdige Proxy
    geschrieben hat: bei einem Proxy das rechte. Dieser Test stand einmal
    auf `== "203.0.113.7"`, also auf dem LINKEN Glied — und schrieb damit
    genau die Annahme fest, die sich als fälschbar erwies.
    """
    anfrage = FalscheAnfrage(host="10.0.0.1", weitergeleitet="203.0.113.7, 10.0.0.1")
    assert kennung_aus_anfrage(anfrage) == "10.0.0.1"


def test_gefaelschte_glieder_aendern_die_kennung_nicht():
    """Die Eigenschaft, um die es wirklich geht.

    Ein Aufrufer kann beliebig viele Glieder voranstellen — er ändert
    damit nichts, denn gezählt wird von rechts. Vorher ergaben 30 solcher
    Anfragen nachweislich 30 Aufrufe auf den Betreiberschlüssel und kein
    einziges 429.
    """
    echt = "198.51.100.4"
    kennungen = {
        kennung_aus_anfrage(
            FalscheAnfrage(host="10.0.0.1", weitergeleitet=f"{luege}, {echt}")
        )
        for luege in ("203.0.113.1", "203.0.113.2", "8.8.8.8, 1.1.1.1", "")
    }
    assert kennungen == {echt}, "die Kennung liess sich verschieben"


def test_ohne_vertrauenswuerdigen_proxy_gilt_die_verbindung():
    """Steht kein Proxy davor, ist jedes Glied der Kopfzeile erfunden."""
    anfrage = FalscheAnfrage(host="10.0.0.1", weitergeleitet="203.0.113.7")
    assert kennung_aus_anfrage(anfrage, vertraute_proxys=0) == "10.0.0.1"


def test_zu_kurze_kette_greift_nicht_ins_leere():
    """Kommt weniger an als erwartet, ist das linkeste Glied das beste,
    was zu haben ist — und kein IndexError."""
    anfrage = FalscheAnfrage(host="10.0.0.1", weitergeleitet="203.0.113.7")
    assert kennung_aus_anfrage(anfrage, vertraute_proxys=3) == "203.0.113.7"


def test_fehlende_adresse_bricht_nicht():
    assert kennung_aus_anfrage(FalscheAnfrage(host=None)) == "unbekannt"
