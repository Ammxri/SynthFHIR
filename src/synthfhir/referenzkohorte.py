"""Die Referenzkohorte für wiederholbare Messungen (Phase 3).

Fest verdrahtet und ohne Modellaufruf. Das ist der Punkt: Ein Messbericht
taugt nur zum Vergleich, wenn sich zwischen zwei Läufen ausschließlich das
ändert, was man messen will. Eine vom Modell erzeugte Kohorte ändert sich
bei jedem Lauf und macht jeden Vergleich wertlos.

Der Zuschnitt ist nicht beliebig. Fünf Patienten; der dritte ist der
wichtigste, der vierte kam mit ADR-020, der fünfte mit ADR-022 dazu:

  1. **Vollständig** — Begegnung, Diagnose, Messwert, Medikation. Der
     Normalfall.
  2. **Mehrfach** — zwei Begegnungen, zwei Diagnosen. Deckt die
     Kennungsvergabe über mehrere Ressourcen desselben Typs ab.
  3. **Ohne Begegnung in den Parametern** — und genau deshalb dabei.
  4. **Breiter Laborsatz** — seit ADR-020 tragen Laborwerte das
     allgemeine ISiKLaboruntersuchung; dieser Patient misst es an mehr als
     zwei Einzelwerten und deckt beide Fälle ab (mit und ohne SNOMED).
  5. **Säugling** — der einzige pädiatrische Fall und der einzige Träger
     des Kopfumfangs (ADR-022), damit ISiKKopfumfang nicht im Katalog
     steht, ohne je gemessen zu werden.

Der dritte Fall ist der, den die erste Sondierung übersehen hat. ISiK
verlangt über `isik-con1`, dass eine kodierte Diagnose auf den Kontakt
verweist, in dem sie gestellt wurde. Eine Messkohorte, in der jeder Patient
eine Begegnung liefert, läuft daran vorbei und meldet eine Konformität, die
es nicht gibt.

**Seine Rolle hat sich seit ADR-009 gedreht.** Damals scheiterte er, und
das war sein Zweck; hier stand deshalb einmal „Dieser Fall gehört hierher,
gerade **weil** er scheitert." Heute ergänzt der Bauweg den Kontakt
selbsttätig (`templates.py`), und derselbe Patient belegt die Zusage statt
der Lücke: An ihm zeigt sich, dass der Code die strukturelle Zusage
wirklich herstellt und nicht bloss dort konform ist, wo das Modell
mitgespielt hat. Ihn zu entfernen, weil er jetzt durchgeht, hiesse die
Messung um genau den Fall zu erleichtern, der sie einmal gerettet hat.

Was er seither **nicht** mehr leistet: Er beweist nicht, dass der Validator
den Verstoss überhaupt noch fände. Das kann eine Kohorte, in der jeder Fall
durchgeht, grundsätzlich nicht — und ein Ausbleiben des Befundes belegt
dann nichts. Ein Messaufbau, der nur Fälle enthält, die ohnehin durchgehen,
misst nichts.

Diesen Beweis führt deshalb die Negativkontrolle in
`test_isik_con1_wird_ueberhaupt_noch_gefunden`: Sie nimmt eine gebaute
Diagnose, entfernt genau den Kontakt und zeigt, dass der Befund dann
auftritt. Erst zusammen sagen die beiden Tests etwas aus.
"""

from __future__ import annotations

from .domain import assign_ids, baue_aus_parametern

# Bewusst dieselbe Form, die das Modell liefert — geprüft wird der Weg des
# Produkts, nicht ein Sonderweg für die Messung.
PARAMETER: dict = {
    "verstanden": {
        "anzahl_patienten": 5,
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
            # Körpergewicht und -größe an der Diabetes-Ambulanz plausibel
            # (BMI-Verlauf). Sie stehen hier, weil ihre Profile
            # (ISiKKoerpergewicht, ISiKKoerpergroesse) seit ADR-014 im
            # Katalog sind, aber bis ADR-019 nie in der Referenzkohorte —
            # also nie im eingecheckten Validator-Beleg gemessen wurden.
            "messwerte": [
                {"code": "4548-4", "wert": 7.4, "datum": "2024-06-01"},
                {"code": "29463-7", "wert": 71, "datum": "2024-06-01"},
                {"code": "8302-2", "wert": 164, "datum": "2024-06-01"},
            ],
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
                # Die drei Vitalparameter aus ADR-019, an einem stationären
                # Patienten plausibel — und damit in der Messung, nicht nur
                # im Katalog. Ohne sie hier bliebe ihre Profilkonformität
                # ungeprüft (derselbe blinde Fleck, an dem EMER unbemerkt
                # blieb, ADR-018).
                {"code": "9279-1", "wert": 18, "datum": "2024-08-03"},
                {"code": "8310-5", "wert": 38.4, "datum": "2024-08-03"},
                {"code": "2708-6", "wert": 96, "datum": "2024-08-03"},
            ],
            "medikamente": [{"code": "C09AA05", "beginn": "2010-06-01"}],
        },
        {
            # OHNE Begegnung in den Parametern. Seit ADR-009 ergänzt der
            # Bauweg sie — dieser Patient ist deshalb der Beleg dafür, dass
            # er das wirklich tut, und nicht mehr der Fall, an dem
            # isik-con1 greift. Dass der Befund überhaupt noch auftreten
            # kann, zeigt die Negativkontrolle im Test.
            "vorname": "Ayşe",
            "nachname": "Öztürk",
            "geschlecht": "female",
            "geburtsdatum": "1979-07-22",
            "diagnosen": [{"code": "195967001", "beginn": "2005-09-15"}],
            "messwerte": [{"code": "718-7", "wert": 13.2, "datum": "2024-04-11"}],
        },
        {
            # Ein breiter Laborsatz, damit das seit ADR-020 profilierte
            # ISiKLaboruntersuchung im Beleg nicht an zwei Einzelwerten
            # hängt. Bewusst gemischt: Kreatinin und CRP tragen die
            # SNOMED-Doppelkodierung (ADR-015), Natrium/Kalium/Glukose
            # nicht — beide Fälle erfüllen das allgemeine Laborprofil, und
            # der Beleg zeigt das.
            "vorname": "Ludwig",
            "nachname": "Achterberg",
            "geschlecht": "male",
            "geburtsdatum": "1961-12-03",
            "begegnungen": [{"art": "IMP", "datum": "2024-09-10"}],
            "diagnosen": [{"code": "709044004", "beginn": "2018-03-01"}],
            "messwerte": [
                {"code": "2160-0", "wert": 1.6, "datum": "2024-09-10"},  # Kreatinin (SNOMED)
                {"code": "1988-5", "wert": 42.0, "datum": "2024-09-10"},  # CRP (SNOMED)
                {"code": "2951-2", "wert": 141, "datum": "2024-09-10"},  # Natrium
                {"code": "2823-3", "wert": 4.8, "datum": "2024-09-10"},  # Kalium
                {"code": "2345-7", "wert": 112, "datum": "2024-09-10"},  # Glukose
            ],
        },
        {
            # Ein Säugling bei der U-Untersuchung — der einzige pädiatrische
            # Fall und der einzige Träger des Kopfumfangs (ADR-022). Ohne
            # ihn stünde ISiKKopfumfang im Katalog, aber nie im
            # eingecheckten Beleg — derselbe blinde Fleck, an dem EMER
            # unbemerkt blieb (ADR-018) und den ADR-019 für Gewicht und
            # Größe schloss. 43 cm sind für ein halbes Jahr normal.
            "vorname": "Mia",
            "nachname": "Sommer",
            "geschlecht": "female",
            "geburtsdatum": "2024-03-01",
            "begegnungen": [{"art": "AMB", "datum": "2024-09-01"}],
            "messwerte": [
                {"code": "9843-4", "wert": 43, "datum": "2024-09-01"},
            ],
        },
    ],
}


def baue() -> list[dict]:
    """Die Referenzkohorte als fertige Ressourcen.

    Läuft durch denselben Bauweg wie jede andere Kohorte. Ein eigener Pfad
    für die Messung würde messen, was es sonst nicht gibt.
    """
    return assign_ids(baue_aus_parametern(PARAMETER).ressourcen).resources
