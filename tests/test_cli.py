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
    rc = cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "-o", str(tmp_path / "k.json")])
    assert rc == 0


def test_rueckgabewert_eins_wenn_patienten_fehlen(monkeypatch, tmp_path):
    """Eine Lücke ist kein Erfolg — auch wenn das Gelieferte valide ist."""
    monkeypatch.setattr(cli, "client_aus_umgebung", lambda: TeilClient(faellt_aus={2}))
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    rc = cli.main(["45 Diabetikerinnen", "-n", "45", "--teilgroesse", "15", "-o", str(tmp_path / "k.json")])
    assert rc == 1


def test_rueckgabewert_zwei_wenn_nichts_entsteht(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "client_aus_umgebung",
                        lambda: TeilClient(faellt_aus={1, 2, 3}))
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    rc = cli.main(["45 Diabetikerinnen", "-n", "45", "--teilgroesse", "15", "-o", str(tmp_path / "k.json")])
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
    cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "-o", str(tmp_path / "k.json"),
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
    cli.main(["45 Diabetikerinnen", "-n", "45", "--teilgroesse", "15", "-o", str(tmp_path / "k.json")])
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
    cli.main(["60 Diabetikerinnen", "-n", "60", "--teilgroesse", "15", "-o", str(tmp_path / "k.json"),
              "--pause", "60"])
    assert keine_wartezeit == [60, 60, 60]


# --- NDJSON-Export ---------------------------------------------------------


def test_ndjson_schreibt_eine_datei_je_typ(stub, tmp_path, capsys):
    ziel = tmp_path / "export"
    rc = cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "--ndjson", str(ziel)])
    assert rc == 0
    assert {p.name for p in ziel.glob("*.ndjson")} == {
        "Patient.ndjson", "Condition.ndjson", "Observation.ndjson"
    }
    assert (ziel / "manifest.json").exists()
    assert "NDJSON:" in capsys.readouterr().err


def test_ndjson_unterdrueckt_die_bundle_ausgabe_auf_stdout(stub, tmp_path, capsys):
    """Ohne das schriebe `--ndjson ./export` nebenbei ein Megabyte in die
    Konsole — die man dann auch noch versehentlich umleiten könnte."""
    cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "--ndjson", str(tmp_path / "e")])
    assert capsys.readouterr().out == ""


def test_ndjson_und_bundle_zugleich(stub, tmp_path, capsys):
    ziel = tmp_path / "export"
    bundle = tmp_path / "k.json"
    cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "-o", str(bundle),
              "--ndjson", str(ziel)])
    assert bundle.exists() and (ziel / "Patient.ndjson").exists()
    assert capsys.readouterr().out == ""


def test_ndjson_enthaelt_alle_ressourcen_des_bundles(stub, tmp_path):
    """Die beiden Ausgabewege müssen dasselbe enthalten."""
    import json as _json

    from synthfhir.ndjson import lies_ndjson

    ziel = tmp_path / "export"
    bundle = tmp_path / "k.json"
    cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "-o", str(bundle),
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
    cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "--ndjson", str(ziel)])
    rc = cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "--ndjson", str(ziel)])
    assert rc == 2
    assert "NDJSON-Export fehlgeschlagen" in capsys.readouterr().err


def test_ueberschreiben_hebt_die_sperre_auf(stub, tmp_path):
    ziel = tmp_path / "export"
    cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "--ndjson", str(ziel)])
    rc = cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "--ndjson", str(ziel),
                   "--ueberschreiben"])
    assert rc == 0


def test_ndjson_traegt_auch_eine_unvollstaendige_kohorte(monkeypatch, tmp_path):
    """Was geliefert wurde, wird exportiert — die Lücke steht in der
    Zusammenfassung, nicht in einer verweigerten Datei."""
    monkeypatch.setattr(cli, "client_aus_umgebung", lambda: TeilClient(faellt_aus={2}))
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    ziel = tmp_path / "export"
    rc = cli.main(["45 Diabetikerinnen", "-n", "45", "--teilgroesse", "15", "--ndjson", str(ziel)])
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
    cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "--ndjson", str(ziel)])

    rc = cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "--ndjson", str(ziel),
                   "--bericht", str(bericht)])
    assert rc == 2, "der Export ist gescheitert"
    assert bericht.exists(), "der Bericht ist trotzdem da"
    assert json.loads(bericht.read_text(encoding="utf-8"))["patienten"] == 30


# --- Aufzeichnen und Wiedergeben -------------------------------------------


def test_aufzeichnen_und_wiedergeben_ergeben_dasselbe(stub, tmp_path, capsys):
    """Die Zusage in einem Test: derselbe Auftrag, dasselbe Bundle — ohne
    dass das Modell noch einmal gefragt wird."""
    aufz_datei = tmp_path / "lauf.aufz.json"
    erst = tmp_path / "erst.json"
    dann = tmp_path / "dann.json"

    assert cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "-o", str(erst),
                     "--aufzeichnen", str(aufz_datei)]) == 0
    aufrufe_nach_erzeugung = stub.aufruf

    assert cli.main(["--wiedergeben", str(aufz_datei), "-o", str(dann)]) == 0
    assert stub.aufruf == aufrufe_nach_erzeugung, "kein weiterer Modellaufruf"
    assert erst.read_bytes() == dann.read_bytes()


def test_wiedergeben_braucht_weder_beschreibung_noch_anzahl(stub, tmp_path):
    """Beides steht in der Aufzeichnung. Sie noch einmal zu verlangen wäre
    eine Fehlerquelle: Wer sie abweichend angibt, bekäme trotzdem die
    aufgezeichnete Kohorte."""
    aufz_datei = tmp_path / "lauf.aufz.json"
    cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "-o", str(tmp_path / "a.json"),
              "--aufzeichnen", str(aufz_datei)])
    assert cli.main(["--wiedergeben", str(aufz_datei),
                     "-o", str(tmp_path / "b.json")]) == 0


def test_wiedergabe_meldet_den_befund_auf_stderr(stub, tmp_path, capsys):
    aufz_datei = tmp_path / "lauf.aufz.json"
    cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "-o", str(tmp_path / "a.json"),
              "--aufzeichnen", str(aufz_datei)])
    capsys.readouterr()
    cli.main(["--wiedergeben", str(aufz_datei), "-o", str(tmp_path / "b.json")])
    err = capsys.readouterr().err
    assert "kein Modellaufruf" in err
    assert "Prüfsumme stimmt" in err


def test_abweichung_wird_auch_im_stillen_betrieb_gemeldet(stub, tmp_path, capsys):
    """`--still` unterdrückt Fortschritt, nicht Befunde. Eine Wiedergabe,
    die stillschweigend etwas anderes liefert, wäre schlimmer als keine."""
    from dataclasses import replace

    from synthfhir.domain.codes import CONDITION_CODES

    aufz_datei = tmp_path / "lauf.aufz.json"
    cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "-o", str(tmp_path / "a.json"),
              "--aufzeichnen", str(aufz_datei)])
    capsys.readouterr()

    schluessel = "44054006"
    alt = CONDITION_CODES[schluessel]
    try:
        CONDITION_CODES[schluessel] = replace(alt, display_de="Anders")
        cli.main(["--wiedergeben", str(aufz_datei), "--still",
                  "-o", str(tmp_path / "b.json")])
    finally:
        CONDITION_CODES[schluessel] = alt
    assert "ABWEICHUNG" in capsys.readouterr().err


def test_fehlende_aufzeichnung_gibt_zwei(stub, tmp_path, capsys):
    assert cli.main(["--wiedergeben", str(tmp_path / "nichts.json")]) == 2
    assert "gibt es nicht" in capsys.readouterr().err


def test_ohne_beschreibung_und_ohne_wiedergeben_gibt_zwei(stub, capsys):
    assert cli.main(["-n", "5"]) == 2
    assert "braucht es eine Beschreibung" in capsys.readouterr().err


def test_wiedergabe_kann_ndjson_schreiben(stub, tmp_path):
    """Die Wiedergabe ist ein vollwertiger Lauf — alle Ausgabewege stehen
    offen."""
    aufz_datei = tmp_path / "lauf.aufz.json"
    cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "-o", str(tmp_path / "a.json"),
              "--aufzeichnen", str(aufz_datei)])
    ziel = tmp_path / "export"
    assert cli.main(["--wiedergeben", str(aufz_datei), "--ndjson", str(ziel)]) == 0
    assert (ziel / "Patient.ndjson").exists()
    m = json.loads((ziel / "manifest.json").read_text(encoding="utf-8"))
    assert "--wiedergeben" in m["request"], "die Herkunft darf nicht lügen"


def test_abweichende_wiedergabe_gibt_eins_zurueck(stub, tmp_path):
    """Nachgestellt: Die Wiedergabe meldete ABWEICHUNG auf stderr und gab
    trotzdem 0 zurück. Der Rückgabewert ist der maschinenlesbare Kanal —
    eine Prüfkette liefe darüber hinweg."""
    from dataclasses import replace

    from synthfhir.domain.codes import CONDITION_CODES

    datei = tmp_path / "lauf.aufz.json"
    cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "-o", str(tmp_path / "a.json"),
              "--aufzeichnen", str(datei)])

    alt = CONDITION_CODES["44054006"]
    try:
        CONDITION_CODES["44054006"] = replace(alt, display_de="Anders")
        rc = cli.main(["--wiedergeben", str(datei), "--still",
                       "-o", str(tmp_path / "b.json")])
    finally:
        CONDITION_CODES["44054006"] = alt
    assert rc == 1, "geliefert, aber nicht dasselbe"


def test_identische_wiedergabe_gibt_null_zurueck(stub, tmp_path):
    datei = tmp_path / "lauf.aufz.json"
    cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "-o", str(tmp_path / "a.json"),
              "--aufzeichnen", str(datei)])
    assert cli.main(["--wiedergeben", str(datei), "--still",
                     "-o", str(tmp_path / "b.json")]) == 0


def test_aufzeichnung_ueberlebt_einen_gescheiterten_ndjson_export(stub, tmp_path):
    """Derselbe Fehler wie beim Bericht, nur teurer: Die Aufzeichnung ist
    das Einzige, womit sich der Lauf wiederholen lässt."""
    ziel = tmp_path / "export"
    datei = tmp_path / "lauf.aufz.json"
    cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "--ndjson", str(ziel)])

    rc = cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15", "--ndjson", str(ziel),
                   "--aufzeichnen", str(datei)])
    assert rc == 2, "der Export ist gescheitert"
    assert datei.exists(), "die Aufzeichnung ist trotzdem da"


# --- Server-Push -----------------------------------------------------------


def test_push_ist_voreingestellt_ein_trockenlauf(stub, tmp_path, capsys, monkeypatch):
    gesendet = []
    monkeypatch.setattr("synthfhir.cli.pushe",
                        lambda res, url, **kw: _stub_push(res, url, gesendet, **kw))
    rc = cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15",
                   "-o", str(tmp_path / "k.json"), "--push", "http://ziel/fhir"])
    assert rc == 0
    assert gesendet[0]["ausfuehren"] is False
    assert "TROCKENLAUF" in capsys.readouterr().err


def test_push_ausfuehren_wird_durchgereicht(stub, tmp_path, monkeypatch):
    gesendet = []
    monkeypatch.setattr("synthfhir.cli.pushe",
                        lambda res, url, **kw: _stub_push(res, url, gesendet, **kw))
    cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15",
              "-o", str(tmp_path / "k.json"), "--push", "http://ziel/fhir",
              "--push-ausfuehren", "--fremde-daten-ok"])
    assert gesendet[0]["ausfuehren"] is True
    assert gesendet[0]["fremde_daten_ok"] is True


def test_luecke_wird_beim_pushen_ausdruecklich_gemeldet(monkeypatch, tmp_path, capsys):
    """Eine Lücke verhindert den Push nicht — was geliefert wurde, ist
    gültig und in sich geschlossen. Sie muss aber dort stehen, wo nach
    außen geschrieben wird, nicht nur in der Zusammenfassung darüber."""
    monkeypatch.setattr(cli, "client_aus_umgebung", lambda: TeilClient(faellt_aus={2}))
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    gesendet = []
    monkeypatch.setattr("synthfhir.cli.pushe",
                        lambda res, url, **kw: _stub_push(res, url, gesendet, **kw))
    rc = cli.main(["45 Diabetikerinnen", "-n", "45", "--teilgroesse", "15",
                   "-o", str(tmp_path / "k.json"), "--push", "http://ziel/fhir",
                   "--push-ausfuehren"])
    err = capsys.readouterr().err
    assert gesendet, "gepusht wird trotzdem"
    assert "ACHTUNG" in err and "30 von 45" in err
    assert rc == 1, "der Rückgabewert sagt weiterhin: Lücken"


def test_ungueltige_kohorte_wird_nicht_gepusht(stub, tmp_path, capsys, monkeypatch):
    """Ungültig ist etwas anderes als unvollständig: In ein fremdes System
    gehört nur, was die Prüfung besteht."""
    gesendet = []
    monkeypatch.setattr("synthfhir.cli.pushe",
                        lambda res, url, **kw: _stub_push(res, url, gesendet, **kw))

    from synthfhir.kohorte import Kohortenergebnis
    monkeypatch.setattr(Kohortenergebnis, "fertig", property(lambda self: False))
    rc = cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15",
                   "-o", str(tmp_path / "k.json"), "--push", "http://ziel/fhir",
                   "--push-ausfuehren"])
    assert rc == 2
    assert gesendet == [], "es darf gar nicht erst versucht werden"
    assert "nicht vollständig gültig" in capsys.readouterr().err


def test_push_unterdrueckt_das_bundle_auf_stdout(stub, capsys, monkeypatch):
    gesendet = []
    monkeypatch.setattr("synthfhir.cli.pushe",
                        lambda res, url, **kw: _stub_push(res, url, gesendet, **kw))
    cli.main(["30 Diabetikerinnen", "-n", "30", "--teilgroesse", "15",
              "--push", "http://ziel/fhir"])
    assert capsys.readouterr().out == ""


def _stub_push(res, url, gesendet, **kw):
    """Ein Push, der nichts tut und mitschreibt, wie er gerufen wurde."""
    from synthfhir.push import Pushergebnis, Zielbefund

    gesendet.append(dict(kw))
    e = Pushergebnis(ziel=url, trockenlauf=not kw.get("ausfuehren"))
    e.befund = Zielbefund(url=url, erreichbar=True, fhir_version="4.0.1",
                          ressourcen_gesamt=0, ressourcen_mit_testlabel=0)
    e.pakete = 1
    e.reihenfolge = ["Patient"]
    if kw.get("ausfuehren"):
        e.geschrieben = len(res)
    return e
