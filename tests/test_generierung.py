"""Tests der Erzeugungskette — ohne Netz, mit vorgegebenen Modellantworten.

Geprüft wird vor allem, was passiert, wenn das Modell sich **nicht** an die
Vorgaben hält. Genau dafür ist die Architektur gebaut: Das Modell darf
irren, das Ergebnis darf es nicht.
"""

from __future__ import annotations

import json

from synthfhir.domain.integrity import check_resources
from synthfhir.generation import generiere
from synthfhir.llm import FesterClient, LLMAntwort, LLMClient, LLMFehler
from synthfhir.validation import Befund


def _antwort(patienten: list[dict], anzahl: int | None = None, kriterien=None) -> str:
    return json.dumps(
        {
            "verstanden": {
                "anzahl_patienten": anzahl if anzahl is not None else len(patienten),
                "kernkriterien": kriterien or ["Testkriterium"],
            },
            "patienten": patienten,
        },
        ensure_ascii=False,
    )


def _patient(**abweichend) -> dict:
    basis = {
        "vorname": "Ingrid",
        "nachname": "Baumgartner",
        "geschlecht": "female",
        "geburtsdatum": "1958-03-14",
        "diagnosen": [{"code": "44054006", "beginn": "2012-05-01"}],
        "messwerte": [{"code": "4548-4", "wert": 7.8, "datum": "2024-01-15"}],
    }
    basis.update(abweichend)
    return basis


# --- Der Normalfall --------------------------------------------------------


def test_gute_antwort_ergibt_ein_fertiges_bundle():
    e = generiere(FesterClient(_antwort([_patient()])), "Eine Diabetikerin über 60")
    assert e.fertig
    assert e.anzahl_je_typ == {
        "Patient": 1, "Encounter": 1, "Condition": 1, "Observation": 1
    }, "der Encounter kommt vom Code, nicht vom Modell (ADR-009)"
    assert e.bundle["type"] == "collection"
    assert e.befunde_als_text() == []


def test_ruecklesung_wird_uebernommen():
    """US-1 AC3: Der Nutzer muss sehen, wie seine Anfrage gelesen wurde."""
    e = generiere(
        FesterClient(_antwort([_patient()], kriterien=["Diabetes Typ 2", "Alter über 60"])),
        "Eine Diabetikerin über 60",
    )
    assert e.verstanden.anzahl_patienten == 1
    assert "Diabetes Typ 2" in e.verstanden.kernkriterien


def test_referenzen_zeigen_auf_patienten_im_selben_bundle():
    """US-3: keine Referenz ins Leere."""
    e = generiere(FesterClient(_antwort([_patient(), _patient(vorname="Helmut")])), "Zwei Patienten")
    assert e.integritaet.ok
    assert e.integritaet.broken_reference_count == 0
    conditions = [r for r in e.ressourcen if r["resourceType"] == "Condition"]
    assert {c["subject"]["reference"] for c in conditions} == {
        "Patient/pat-001",
        "Patient/pat-002",
    }


# --- Wenn das Modell sich nicht an die Vorgaben hält ------------------------


def test_erfundener_code_wird_ersetzt_und_gezaehlt():
    """Die Zusage „keine erfundenen Codes" hängt am Katalog, nicht am Modell."""
    e = generiere(
        FesterClient(_antwort([_patient(messwerte=[{"code": "99999-9", "wert": 1.0,
                                                    "datum": "2024-01-01"}])])),
        "Irgendein Laborwert",
    )
    assert e.erfundene_codes == 1
    assert e.fertig, "Trotz ersetztem Code muss die Ausgabe valide sein"
    observation = next(r for r in e.ressourcen if r["resourceType"] == "Observation")
    assert observation["code"]["coding"][0]["code"] != "99999-9"


def test_mengenabweichung_gegen_die_eigene_ruecklesung_wird_gemeldet():
    """Der Hauptfehler der in Phase 0 verworfenen Variante A: Das Modell
    erkennt eine Zahl und liefert dann weniger."""
    e = generiere(FesterClient(_antwort([_patient()], anzahl=5)), "Fünf Patienten")
    arten = [b.art for b in e.beanstandungen]
    assert "mengenabweichung" in arten
    assert e.verstanden.anzahl_patienten == 5
    assert e.anzahl_je_typ["Patient"] == 1


def test_obergrenze_wird_durchgesetzt_und_gemeldet():
    """PRD Block 4 begrenzt den MVP auf 25 Patienten — sichtbar gekappt,
    nicht stillschweigend."""
    e = generiere(
        FesterClient(_antwort([_patient() for _ in range(40)])),
        "Vierzig Patienten",
        max_patienten=25,
    )
    assert e.anzahl_je_typ["Patient"] == 25
    assert any(b.art == "obergrenze" for b in e.beanstandungen)


def test_unsinnige_werte_ergeben_trotzdem_gueltiges_fhir():
    e = generiere(
        FesterClient(
            _antwort([_patient(geschlecht="weiblich", geburtsdatum="14.03.1958",
                               messwerte=[{"code": "4548-4", "wert": "hoch", "datum": "gestern"}])])
        ),
        "Eine Patientin",
    )
    assert e.fertig, e.befunde_als_text()
    patient = next(r for r in e.ressourcen if r["resourceType"] == "Patient")
    assert patient["gender"] == "unknown"
    assert len(e.beanstandungen) >= 3


# --- Wenn die Antwort gar nicht verwertbar ist ------------------------------


def test_kein_json_ergibt_einen_klaren_fehler():
    e = generiere(FesterClient("Das kann ich leider nicht liefern."), "Irgendwas")
    assert not e.fertig
    assert "kein gültiges JSON" in e.fehler
    assert e.versuche == 2, "Es muss ein zweiter Versuch stattfinden"


def test_markdown_rahmen_stoert_nicht():
    text = "Gerne!\n```json\n" + _antwort([_patient()]) + "\n```\n"
    assert generiere(FesterClient(text), "Eine Patientin").fertig


def test_leere_beschreibung_wird_abgewiesen():
    client = FesterClient(_antwort([_patient()]))
    e = generiere(client, "   ")
    assert not e.fertig
    assert "leer" in e.fehler
    assert client.aufrufe == [], "Ohne Beschreibung darf kein Aufruf stattfinden"


def test_abgeschnittene_antwort_wird_als_solche_benannt():
    """Ein Konfigurationsproblem, kein Modellfehler — die Unterscheidung hat
    in Phase 0 eine ganze Messreihe gekostet."""

    class AbgeschnittenerClient(LLMClient):
        def frage(self, *, system: str, benutzer: str) -> LLMAntwort:
            return LLMAntwort(
                text='{"verstanden": {"anzahl_patienten": 25}, "patienten": [{"vorn',
                modell="test", eingabe_token=10, ausgabe_token=5600, dauer_s=0.1,
                abbruchgrund="max_tokens",
            )

    e = generiere(AbgeschnittenerClient(), "25 Patienten")
    assert not e.fertig
    assert "max_tokens" in e.fehler and "abgeschnitten" in e.fehler


def test_llm_ausfall_wird_durchgereicht():
    class KaputterClient(LLMClient):
        def frage(self, *, system: str, benutzer: str) -> LLMAntwort:
            raise LLMFehler("Keine Verbindung zum Anbieter")

    e = generiere(KaputterClient(), "Eine Patientin")
    assert not e.fertig
    assert "Keine Verbindung" in e.fehler


def test_parameterobjekt_ohne_patienten_scheitert_sauber():
    e = generiere(FesterClient(json.dumps({"verstanden": {}, "patienten": []})), "Nichts")
    assert not e.fertig
    assert "keine einzige Ressource" in e.fehler


# --- Die Zusage selbst -----------------------------------------------------


def test_fertig_verlangt_validitaet_und_integritaet():
    """US-2 AC2: Nur ein vollständig geprüftes Ergebnis darf fertig heißen."""
    e = generiere(FesterClient(_antwort([_patient()])), "Eine Patientin")
    assert e.fertig
    assert all(pr.valide for pr in e.validierung)
    assert e.integritaet.ok

    # Wird nachträglich etwas kaputtgemacht, muss `fertig` kippen.
    e.validierung[0].befunde.append(Befund("test", "künstlich eingefügt"))
    assert not e.fertig


def test_fertig_kippt_bei_kaputter_referenz():
    """Die zweite Bedingung: Struktur allein genügt nicht."""
    e = generiere(FesterClient(_antwort([_patient()])), "Eine Patientin")
    assert e.fertig
    condition = next(r for r in e.ressourcen if r["resourceType"] == "Condition")
    condition["subject"]["reference"] = "Patient/gibt-es-nicht"
    e.integritaet = check_resources(e.ressourcen)
    assert not e.fertig
    assert e.integritaet.broken_reference_count == 1


def test_prompt_enthaelt_die_beschreibung_woertlich():
    client = FesterClient(_antwort([_patient()]))
    generiere(client, "Drei Patientinnen mit Asthma")
    system, benutzer = client.aufrufe[0]
    assert "Drei Patientinnen mit Asthma" in benutzer
    assert "SNOMED" in benutzer and "LOINC" in benutzer, "Beide Kataloge müssen mitgehen"
    assert "GERMAN" in system, "Die Lokalisierungsvorgabe muss im Prompt stehen"


def test_parsbares_bruchstueck_wird_nicht_als_ergebnis_akzeptiert():
    """Regression: Eine abgeschnittene Antwort kann parsbar sein.

    Aus '{"verstanden": {"anzahl_patienten": 25}, "patienten": [{"vorn'
    holt die JSON-Extraktion das innere Objekt heraus - syntaktisch
    einwandfrei, inhaltlich ein Bruchstück. Ohne die zusätzliche Prüfung
    auf das Feld 'patienten' liefe daraus ein stillschweigend falsches
    Ergebnis statt einer Fehlermeldung.
    """
    bruchstueck = '{"verstanden": {"anzahl_patienten": 3}, "patienten": [{"vorname": "An'
    e = generiere(FesterClient(bruchstueck), "Drei Patienten")
    assert not e.fertig
    assert "Bruchstück" in e.fehler


def test_nicht_abbildbare_kriterien_werden_sichtbar_gemacht():
    """Gefunden bei der ersten echten Messung: Die Anfrage nannte
    Vitamin-D-Werte, der Katalog hat dafür keinen Code. Das Modell erfand
    keinen Code - es nahm stillschweigend einen anderen, und die Ausgabe sah
    einwandfrei aus. Alle Zusagen formal erfüllt, die Anfrage trotzdem
    verfehlt. Dasselbe Muster wie die Mengentreue in Phase 0.
    """
    antwort = json.dumps({
        "verstanden": {
            "anzahl_patienten": 1,
            "kernkriterien": ["Osteoporose", "Vitamin-D-Werte"],
            "nicht_abbildbar": ["Vitamin-D-Werte - kein passender LOINC-Code im Katalog"],
        },
        "patienten": [_patient()],
    }, ensure_ascii=False)
    e = generiere(FesterClient(antwort), "Patientin mit Osteoporose und Vitamin-D-Werten")

    assert e.fertig, "Eine benannte Lücke macht das Ergebnis nicht invalide"
    assert e.verstanden.nicht_abbildbar == [
        "Vitamin-D-Werte - kein passender LOINC-Code im Katalog"
    ]
    assert any(b.art == "nicht_abbildbar" for b in e.beanstandungen)
    assert any("Vitamin-D" in zeile for zeile in e.befunde_als_text())


def test_fehlendes_luecken_feld_ist_kein_fehler():
    """Ältere oder knappere Antworten ohne das Feld müssen weiter laufen."""
    e = generiere(FesterClient(_antwort([_patient()])), "Eine Patientin")
    assert e.fertig
    assert e.verstanden.nicht_abbildbar == []
