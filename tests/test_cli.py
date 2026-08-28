"""Tests der Kommandozeile.

Die Zusagen, auf die sich ein Aufrufer stützen darf: der Rückgabewert sagt,
ob die Kohorte vollständig ist, und stdout trägt nur das Bundle — damit
`synthfhir … > datei.json` eine brauchbare Datei ergibt.
"""

from __future__ import annotations

import json

import pytest

from synthfhir import cli
from tests.test_kohorte import TeilClient


@pytest.fixture
def stub(monkeypatch):
    """Ersetzt den echten Anbieter. Kein Test hier kostet Kontingent."""
    client = TeilClient()
    monkeypatch.setattr(cli, "client_aus_umgebung", lambda: client)
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    return client


def test_rueckgabewert_null_bei_vollstaendiger_kohorte(stub, tmp_path, capsys):
    rc = cli.main(["30 Diabetikerinnen", "-n", "30", "-o", str(tmp_path / "k.json")])
    assert rc == 0


def test_rueckgabewert_eins_wenn_patienten_fehlen(monkeypatch, tmp_path):
    """Eine Lücke ist kein Erfolg — auch wenn das Gelieferte valide ist."""
    monkeypatch.setattr(cli, "client_aus_umgebung", lambda: TeilClient(faellt_aus={2}))
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    rc = cli.main(["45 Diabetikerinnen", "-n", "45", "-o", str(tmp_path / "k.json")])
    assert rc == 1


def test_rueckgabewert_zwei_wenn_nichts_entsteht(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "client_aus_umgebung",
                        lambda: TeilClient(faellt_aus={1, 2, 3}))
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    rc = cli.main(["45 Diabetikerinnen", "-n", "45", "-o", str(tmp_path / "k.json")])
    assert rc == 2


def test_rueckgabewert_zwei_bei_unbrauchbarer_anzahl(stub):
    assert cli.main(["nichts", "-n", "0"]) == 2
    assert stub.aufruf == 0


def test_stdout_traegt_nur_das_bundle(stub, capsys):
    """Der Fortschritt muss auf stderr gehen, sonst ist die umgeleitete
    Datei kein JSON mehr."""
    cli.main(["20 Diabetikerinnen", "-n", "20"])
    ausgabe = capsys.readouterr()
    bundle = json.loads(ausgabe.out)          # wirft, wenn etwas dazwischenfunkt
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "collection"
    assert len(bundle["entry"]) == 60
    assert "Teil 1/" in ausgabe.err


def test_datei_statt_stdout(stub, tmp_path, capsys):
    ziel = tmp_path / "kohorte.json"
    cli.main(["20 Diabetikerinnen", "-n", "20", "-o", str(ziel)])
    assert capsys.readouterr().out == "", "bei -o gehört nichts auf stdout"
    assert json.loads(ziel.read_text(encoding="utf-8"))["resourceType"] == "Bundle"


def test_bericht_enthaelt_die_messwerte(stub, tmp_path):
    bericht = tmp_path / "b.json"
    cli.main(["30 Diabetikerinnen", "-n", "30", "-o", str(tmp_path / "k.json"),
              "--bericht", str(bericht)])
    daten = json.loads(bericht.read_text(encoding="utf-8"))
    assert daten["patienten"] == 30
    assert daten["mengentreue"] == 1.0
    assert daten["fertig"] is True
    assert len(daten["teile"]) == 2
    assert daten["integritaet"]["ok"] is True


def test_zusammenfassung_benennt_den_ausgefallenen_teil(monkeypatch, tmp_path, capsys):
    """Wer nur auf die Ausgabe schaut, muss die Lücke sehen."""
    monkeypatch.setattr(cli, "client_aus_umgebung", lambda: TeilClient(faellt_aus={2}))
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    cli.main(["45 Diabetikerinnen", "-n", "45", "-o", str(tmp_path / "k.json")])
    err = capsys.readouterr().err
    assert "30 von 45" in err
    assert "66.7%" in err
    assert "Teil 2 ausgefallen" in err


def test_hinweis_auf_testdaten_steht_in_der_ausgabe(stub, tmp_path, capsys):
    """Auflage aus der Spezifikation: Ausgaben sind als Testdaten
    gekennzeichnet."""
    cli.main(["20 Diabetikerinnen", "-n", "20", "-o", str(tmp_path / "k.json")])
    assert "Nicht für klinische Nutzung" in capsys.readouterr().err


def test_still_schweigt(stub, tmp_path, capsys):
    cli.main(["20 Diabetikerinnen", "-n", "20", "-o", str(tmp_path / "k.json"), "--still"])
    ausgabe = capsys.readouterr()
    assert ausgabe.err == ""
    assert ausgabe.out == ""


def test_teilgroesse_wird_durchgereicht(stub, tmp_path):
    cli.main(["40 Diabetikerinnen", "-n", "40", "-o", str(tmp_path / "k.json"),
              "--teilgroesse", "10"])
    assert stub.mengen == [10, 10, 10, 10]


def test_fehlender_schluessel_bricht_sauber_ab(monkeypatch, capsys):
    """Ohne Zugang: eine Meldung, kein Stapelabzug."""
    from synthfhir.llm import LLMFehler

    def wirft():
        raise LLMFehler("SYNTHFHIR_LLM_MODEL ist nicht gesetzt")

    monkeypatch.setattr(cli, "client_aus_umgebung", wirft)
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    assert cli.main(["egal", "-n", "10"]) == 2
    assert "SYNTHFHIR_LLM_MODEL" in capsys.readouterr().err
