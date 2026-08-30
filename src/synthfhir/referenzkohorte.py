"""Die Referenzkohorte für wiederholbare Messungen (Phase 3).

Fest verdrahtet und ohne Modellaufruf. Das ist der Punkt: Ein Messbericht
taugt nur zum Vergleich, wenn sich zwischen zwei Läufen ausschließlich das
ändert, was man messen will. Eine vom Modell erzeugte Kohorte ändert sich
bei jedem Lauf und macht jeden Vergleich wertlos.

Der Zuschnitt ist nicht beliebig. Drei Patienten, und der dritte ist der
wichtigste:

  1. **Vollständig** — Begegnung, Diagnose, Messwert, Medikation. Der
     Normalfall.
  2. **Mehrfach** — zwei Begegnungen, zwei Diagnosen. Deckt die
     Kennungsvergabe über mehrere Ressourcen desselben Typs ab.
  3. **Ohne Begegnung** — und genau deshalb dabei.

Der dritte Fall ist der, den die erste Sondierung übersehen hat. ISiK
verlangt über `isik-con1`, dass eine kodierte Diagnose auf den Kontakt
verweist, in dem sie gestellt wurde. Eine Messkohorte, in der jeder Patient
eine Begegnung hat, läuft daran vorbei und meldet eine Konformität, die es
nicht gibt.

Ein Messaufbau, der nur den Fall enthält, der ohnehin durchgeht, misst
nichts. Dieser Fall gehört hierher, gerade **weil** er scheitert.
"""

from __future__ import annotations

from .domain import assign_ids, baue_aus_parametern

# Bewusst dieselbe Form, die das Modell liefert — geprüft wird der Weg des
# Produkts, nicht ein Sonderweg für die Messung.
PARAMETER: dict = {
    "verstanden": {
        "anzahl_patienten": 3,
        "kernkriterien": ["Referenzkohorte", "fest verdrahtet"],
        "nicht_abbildbar": [],
    },
    "patienten": [
        {
            "vorname": "Käthe",
            "nachname": "Schäfer",
            "geschlecht": "female",
            "geburtsdatum": "1955-03-17",
            "begegnungen": [{"art": "AMB", "datum": "2024-06-01"}],
            "diagnosen": [{"code": "44054006", "beginn": "2015-01-01"}],
            "messwerte": [{"code": "4548-4", "wert": 7.4, "datum": "2024-06-01"}],
            "medikamente": [{"code": "A10BA02", "beginn": "2015-02-01"}],
        },
        {
            "vorname": "Hans-Jürgen",
            "nachname": "Weiß",
            "geschlecht": "male",
            "geburtsdatum": "1948-11-02",
            "begegnungen": [
                {"art": "IMP", "datum": "2024-02-14"},
                {"art": "AMB", "datum": "2024-08-03"},
            ],
            "diagnosen": [
                {"code": "38341003", "beginn": "2010-05-01"},
                {"code": "84114007", "beginn": "2019-01-20"},
            ],
            "messwerte": [
                {"code": "8480-6", "wert": 148, "datum": "2024-08-03"},
                {"code": "8462-4", "wert": 92, "datum": "2024-08-03"},
            ],
            "medikamente": [{"code": "C09AA05", "beginn": "2010-06-01"}],
        },
        {
            # OHNE Begegnung — der Fall, an dem isik-con1 greift.
            "vorname": "Ayşe",
            "nachname": "Öztürk",
            "geschlecht": "female",
            "geburtsdatum": "1979-07-22",
            "diagnosen": [{"code": "195967001", "beginn": "2005-09-15"}],
            "messwerte": [{"code": "718-7", "wert": 13.2, "datum": "2024-04-11"}],
        },
    ],
}


def baue() -> list[dict]:
    """Die Referenzkohorte als fertige Ressourcen.

    Läuft durch denselben Bauweg wie jede andere Kohorte. Ein eigener Pfad
    für die Messung würde messen, was es sonst nicht gibt.
    """
    return assign_ids(baue_aus_parametern(PARAMETER).ressourcen).resources
