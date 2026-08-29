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


@pytest.fixture(autouse=True)
def keine_wartezeit(monkeypatch):
    """Tests warten nicht wirklich — sie halten nur fest, wie lange.

    Nullwerte fallen heraus, genau wie in `_warte` selbst: Ein `pause_s=0`
    zwischen zwei Teilen ist keine Wartezeit, sondern deren Abwesenheit.
    """
    gewartet: list[float] = []

    def merken(sekunden: float) -> None:
        if sekunden > 0:
            gewartet.append(sekunden)

    monkeypatch.setattr("synthfhir.kohorte._warte", merken)
    return gewartet

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


def test_pause_wird_durchgereicht(stub, tmp_path, keine_wartezeit):
    cli.main(["60 Diabetikerinnen", "-n", "60", "-o", str(tmp_path / "k.json"),
              "--pause", "60"])
    assert keine_wartezeit == [60, 60, 60]


# --- NDJSON-Export ---------------------------------------------------------


def test_ndjson_schreibt_eine_datei_je_typ(stub, tmp_path, capsys):
    ziel = tmp_path / "export"
    rc = cli.main(["30 Diabetikerinnen", "-n", "30", "--ndjson", str(ziel)])
    assert rc == 0
    assert {p.name for p in ziel.glob("*.ndjson")} == {
        "Patient.ndjson", "Condition.ndjson", "Observation.ndjson"
    }
    assert (ziel / "manifest.json").exists()
    assert "NDJSON:" in capsys.readouterr().err


def test_ndjson_unterdrueckt_die_bundle_ausgabe_auf_stdout(stub, tmp_path, capsys):
    """Ohne das schriebe `--ndjson ./export` nebenbei ein Megabyte in die
    Konsole — die man dann auch noch versehentlich umleiten könnte."""
    cli.main(["30 Diabetikerinnen", "-n", "30", "--ndjson", str(tmp_path / "e")])
    assert capsys.readouterr().out == ""


def test_ndjson_und_bundle_zugleich(stub, tmp_path, capsys):
    ziel = tmp_path / "export"
    bundle = tmp_path / "k.json"
    cli.main(["30 Diabetikerinnen", "-n", "30", "-o", str(bundle),
              "--ndjson", str(ziel)])
    assert bundle.exists() and (ziel / "Patient.ndjson").exists()
    assert capsys.readouterr().out == ""


def test_ndjson_enthaelt_alle_ressourcen_des_bundles(stub, tmp_path):
    """Die beiden Ausgabewege müssen dasselbe enthalten."""
    import json as _json

    from synthfhir.ndjson import lies_ndjson

    ziel = tmp_path / "export"
    bundle = tmp_path / "k.json"
    cli.main(["30 Diabetikerinnen", "-n", "30", "-o", str(bundle),
              "--ndjson", str(ziel)])
    aus_bundle = [e["resource"] for e in
                  _json.loads(bundle.read_text(encoding="utf-8"))["entry"]]
    aus_ndjson = [r for p in ziel.glob("*.ndjson") for r in lies_ndjson(p)]
    schluessel = lambda rs: sorted(_json.dumps(r, sort_keys=True) for r in rs)
    assert schluessel(aus_ndjson) == schluessel(aus_bundle)


def test_ndjson_verweigert_belegtes_verzeichnis_mit_rueckgabewert_zwei(
    stub, tmp_path, capsys
):
    ziel = tmp_path / "export"
    cli.main(["30 Diabetikerinnen", "-n", "30", "--ndjson", str(ziel)])
    rc = cli.main(["30 Diabetikerinnen", "-n", "30", "--ndjson", str(ziel)])
    assert rc == 2
    assert "NDJSON-Export fehlgeschlagen" in capsys.readouterr().err


def test_ueberschreiben_hebt_die_sperre_auf(stub, tmp_path):
    ziel = tmp_path / "export"
    cli.main(["30 Diabetikerinnen", "-n", "30", "--ndjson", str(ziel)])
    rc = cli.main(["30 Diabetikerinnen", "-n", "30", "--ndjson", str(ziel),
                   "--ueberschreiben"])
    assert rc == 0


def test_ndjson_traegt_auch_eine_unvollstaendige_kohorte(monkeypatch, tmp_path):
    """Was geliefert wurde, wird exportiert — die Lücke steht in der
    Zusammenfassung, nicht in einer verweigerten Datei."""
    monkeypatch.setattr(cli, "client_aus_umgebung", lambda: TeilClient(faellt_aus={2}))
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    ziel = tmp_path / "export"
    rc = cli.main(["45 Diabetikerinnen", "-n", "45", "--ndjson", str(ziel)])
    assert rc == 1, "Lücke bleibt sichtbar"
    from synthfhir.ndjson import lies_ndjson
    assert len(lies_ndjson(ziel / "Patient.ndjson")) == 30


def test_still_schweigt_auch_beim_ndjson_export(stub, tmp_path, capsys):
    cli.main(["20 Diabetikerinnen", "-n", "20", "--ndjson", str(tmp_path / "e"),
              "--still"])
    ausgabe = capsys.readouterr()
    assert ausgabe.err == "" and ausgabe.out == ""


def test_bericht_ueberlebt_einen_gescheiterten_ndjson_export(stub, tmp_path, capsys):
    """Die Erzeugung hat Minuten gedauert und Kontingent gekostet. Ein
    Dateisystemfehler beim Export darf ihre Messwerte nicht mitnehmen —
    vorher stand der Bericht hinter dem Export und ging bei `return 2`
    verloren."""
    ziel = tmp_path / "export"
    bericht = tmp_path / "b.json"
    cli.main(["30 Diabetikerinnen", "-n", "30", "--ndjson", str(ziel)])

    rc = cli.main(["30 Diabetikerinnen", "-n", "30", "--ndjson", str(ziel),
                   "--bericht", str(bericht)])
    assert rc == 2, "der Export ist gescheitert"
    assert bericht.exists(), "der Bericht ist trotzdem da"
    assert json.loads(bericht.read_text(encoding="utf-8"))["patienten"] == 30
