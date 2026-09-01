"""Tests des NDJSON-Exports.

NDJSON scheitert selten laut. Eine Datei mit CRLF, einem BOM oder einer
eingerückten Ressource sieht im Editor völlig richtig aus und wird erst
beim Empfänger zum Problem — oft als Fehler, der genau einen Datensatz
betrifft und deshalb wie ein Datenfehler aussieht, nicht wie ein
Formatfehler.

Die Tests hier prüfen deshalb überwiegend auf **Byte-Ebene**, nicht gegen
das, was `json.loads` gerade noch durchgehen lässt.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from synthfhir.ndjson import (
    ENDUNG,
    MANIFEST_NAME,
    MIME_TYP,
    ExportFehler,
    baue_archiv,
    baue_dateien,
    lies_ndjson,
    schreibe_ndjson,
)


def patient(nummer: int, familie: str = "Müller") -> dict:
    return {
        "resourceType": "Patient",
        "id": f"pat-{nummer:03d}",
        "name": [{"use": "official", "family": familie, "given": ["Käthe"]}],
        "gender": "female",
        "birthDate": "1960-01-01",
    }


def condition(nummer: int) -> dict:
    return {
        "resourceType": "Condition",
        "id": f"cond-{nummer:03d}",
        "subject": {"reference": f"Patient/pat-{nummer:03d}"},
        "code": {"text": "Diabetes mellitus Typ 2"},
    }


@pytest.fixture
def kohorte() -> list[dict]:
    """Drei Patienten mit je einer Diagnose, in Kohortenreihenfolge."""
    aus = []
    for i in range(1, 4):
        aus.append(patient(i))
        aus.append(condition(i))
    return aus


# --- Byte-Ebene: die Fallen, die man nicht sieht ---------------------------


def test_zeilen_enden_mit_lf_nicht_crlf(kohorte, tmp_path):
    """Die wichtigste Zusage dieses Moduls.

    Python übersetzt im Textmodus unter Windows jedes \\n zu \\r\\n.
    Nachgemessen: Path.write_text — womit der Rest des Projekts Bundles
    schreibt — erzeugt hier CRLF. In einem zeilenweisen Format ist das kein
    Schönheitsfehler.
    """
    schreibe_ndjson(kohorte, tmp_path)
    roh = (tmp_path / f"Patient{ENDUNG}").read_bytes()
    assert b"\r" not in roh, "kein Wagenrücklauf, nirgends"
    assert roh.count(b"\n") == 3


def test_keine_bom(kohorte, tmp_path):
    """Drei Bytes vor der ersten Klammer, und nur die erste Zeile bricht —
    das sieht aus wie ein kaputter Datensatz, nicht wie ein Kodierfehler."""
    schreibe_ndjson(kohorte, tmp_path)
    for pfad in tmp_path.glob(f"*{ENDUNG}"):
        assert not pfad.read_bytes().startswith(b"\xef\xbb\xbf"), pfad.name


def test_datei_endet_mit_zeilenvorschub(kohorte, tmp_path):
    """Ohne ihn hängt die letzte Zeile an dem, was ein Werkzeug beim
    Zusammenfügen mehrerer Dateien dahinterschreibt."""
    schreibe_ndjson(kohorte, tmp_path)
    assert (tmp_path / f"Patient{ENDUNG}").read_bytes().endswith(b"\n")


def test_jede_zeile_ist_fuer_sich_gueltiges_json(kohorte, tmp_path):
    """Das ist die ganze Idee des Formats: zeilenweise verarbeitbar, ohne
    die Datei als Ganzes im Speicher zu halten."""
    schreibe_ndjson(kohorte, tmp_path)
    text = (tmp_path / f"Patient{ENDUNG}").read_text(encoding="utf-8")
    zeilen = text.split("\n")[:-1]          # letzter Eintrag ist leer
    assert len(zeilen) == 3
    for zeile in zeilen:
        r = json.loads(zeile)
        assert r["resourceType"] == "Patient"


def test_keine_eingerueckte_ausgabe(kohorte, tmp_path):
    """`indent=2` verteilte eine Ressource über viele Zeilen — in NDJSON
    wäre dann jede Zeile ein Bruchstück."""
    schreibe_ndjson(kohorte, tmp_path)
    text = (tmp_path / f"Patient{ENDUNG}").read_text(encoding="utf-8")
    assert '{"resourceType": "Patient",\n' not in text
    assert '", "' not in text, "kompakte Trennzeichen, keine Leerzeichen"


def test_umlaute_bleiben_utf8_und_werden_nicht_maskiert(tmp_path):
    """`ensure_ascii=True` schriebe \\u00fc. Gültig, aber unlesbar — und der
    Rest des Projekts schreibt echtes UTF-8."""
    schreibe_ndjson([patient(1, "Schäfer")], tmp_path)
    roh = (tmp_path / f"Patient{ENDUNG}").read_bytes()
    assert "Schäfer".encode("utf-8") in roh
    assert b"\\u00e4" not in roh


# --- Aufteilung nach Typ ---------------------------------------------------


def test_eine_datei_je_ressourcentyp(kohorte, tmp_path):
    """Auflage des Bulk-Data-Leitfadens: Eine Ausgabedatei enthält
    Ressourcen nur eines Typs."""
    ergebnis = schreibe_ndjson(kohorte, tmp_path)
    assert {d.typ for d in ergebnis.dateien} == {"Patient", "Condition"}
    assert (tmp_path / f"Patient{ENDUNG}").exists()
    assert (tmp_path / f"Condition{ENDUNG}").exists()


def test_jede_datei_ist_typrein(kohorte, tmp_path):
    schreibe_ndjson(kohorte, tmp_path)
    for pfad in tmp_path.glob(f"*{ENDUNG}"):
        typen = {r["resourceType"] for r in lies_ndjson(pfad)}
        assert typen == {pfad.stem}, f"{pfad.name} enthält {typen}"


def test_reihenfolge_innerhalb_eines_typs_bleibt(tmp_path):
    """Aufsteigende Kennungen machen einen Unterschied beim Vergleichen
    zweier Läufe."""
    schreibe_ndjson([patient(i) for i in (3, 1, 2)], tmp_path)
    ids = [r["id"] for r in lies_ndjson(tmp_path / f"Patient{ENDUNG}")]
    assert ids == ["pat-003", "pat-001", "pat-002"]


def test_rueckgelesen_ist_identisch(kohorte, tmp_path):
    """Der Export darf nichts verlieren und nichts hinzufügen."""
    schreibe_ndjson(kohorte, tmp_path)
    zurueck = []
    for pfad in sorted(tmp_path.glob(f"*{ENDUNG}")):
        zurueck.extend(lies_ndjson(pfad))
    schluessel = lambda rs: sorted(json.dumps(r, sort_keys=True) for r in rs)
    assert schluessel(zurueck) == schluessel(kohorte)


def test_verweise_ueberstehen_die_aufteilung(kohorte, tmp_path):
    """Der gefährliche Fall beim Aufteilen: Die Diagnosen landen in einer
    anderen Datei als die Patienten, auf die sie zeigen."""
    schreibe_ndjson(kohorte, tmp_path)
    pids = {f"Patient/{r['id']}" for r in lies_ndjson(tmp_path / f"Patient{ENDUNG}")}
    verweise = {r["subject"]["reference"]
                for r in lies_ndjson(tmp_path / f"Condition{ENDUNG}")}
    assert verweise == pids


# --- Manifest --------------------------------------------------------------


def test_manifest_traegt_die_felder_des_leitfadens(kohorte, tmp_path):
    ergebnis = schreibe_ndjson(
        kohorte, tmp_path, zeitpunkt=datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    )
    m = json.loads(ergebnis.manifest.read_text(encoding="utf-8"))
    assert m["transactionTime"] == "2026-08-29T12:00:00Z"
    assert m["requiresAccessToken"] is False
    assert {e["type"] for e in m["output"]} == {"Patient", "Condition"}
    for eintrag in m["output"]:
        assert eintrag["url"].startswith("file:")


def test_manifest_erfindet_keine_felder(kohorte, tmp_path):
    """Der ernsteste Fehler, den dieses Modul machen könnte.

    Hier standen `outputFormat` auf Wurzelebene und `fileSize` je
    Ausgabedatei. Beide definiert erst der Continuous Build, die
    veröffentlichte v3.0.0 kennt sie nicht. Ein erfundenes Feld an
    normativer Stelle sieht aus wie Norm, stört nirgends — und genau
    deshalb fällt es niemandem auf.
    """
    ergebnis = schreibe_ndjson(kohorte, tmp_path)
    m = json.loads(ergebnis.manifest.read_text(encoding="utf-8"))

    erlaubt_wurzel = {"transactionTime", "request", "requiresAccessToken",
                      "output", "error", "extension"}
    assert set(m) <= erlaubt_wurzel, f"unbekannt: {set(m) - erlaubt_wurzel}"

    erlaubt_output = {"type", "url", "count"}
    for eintrag in m["output"]:
        assert set(eintrag) <= erlaubt_output, (
            f"unbekannt: {set(eintrag) - erlaubt_output}"
        )


def test_eigene_angaben_stehen_unter_extension(kohorte, tmp_path):
    """Der Leitfaden sieht `extension` genau dafür vor. Verloren geht die
    Dateigröße dadurch nicht — sie steht nur nicht mehr da, wo sie wie
    Norm aussähe."""
    ergebnis = schreibe_ndjson(kohorte, tmp_path)
    m = json.loads(ergebnis.manifest.read_text(encoding="utf-8"))
    assert m["extension"]["dateiformat"] == MIME_TYP
    groessen = m["extension"]["dateigroessen"]
    for d in ergebnis.dateien:
        assert groessen[d.pfad.name] == d.pfad.stat().st_size


def test_error_ist_pflicht_trotz_des_namens(kohorte, tmp_path):
    """„If there are no relevant messages, the server SHOULD return an
    empty array." Ein fehlendes Feld ist etwas anderes als ein leeres."""
    ergebnis = schreibe_ndjson(kohorte, tmp_path)
    m = json.loads(ergebnis.manifest.read_text(encoding="utf-8"))
    assert m["error"] == []


def test_manifest_zaehlt_was_wirklich_drinsteht(kohorte, tmp_path):
    """Eine Zahl im Manifest, die nicht stimmt, ist schlimmer als keine."""
    ergebnis = schreibe_ndjson(kohorte, tmp_path)
    m = json.loads(ergebnis.manifest.read_text(encoding="utf-8"))
    for eintrag in m["output"]:
        pfad = tmp_path / f"{eintrag['type']}{ENDUNG}"
        assert eintrag["count"] == len(lies_ndjson(pfad))
        assert m["extension"]["dateigroessen"][pfad.name] == pfad.stat().st_size


def test_manifest_nennt_die_daten_als_testdaten(kohorte, tmp_path):
    """Auflage aus der Spezifikation: Ausgaben sind gekennzeichnet."""
    ergebnis = schreibe_ndjson(kohorte, tmp_path)
    m = json.loads(ergebnis.manifest.read_text(encoding="utf-8"))
    assert "Nicht für klinische Nutzung" in m["extension"]["hinweis"]


def test_manifest_kann_entfallen(kohorte, tmp_path):
    ergebnis = schreibe_ndjson(kohorte, tmp_path, manifest=False)
    assert ergebnis.manifest is None
    assert not (tmp_path / MANIFEST_NAME).exists()


# --- Schutz vor Resten -----------------------------------------------------


def test_belegtes_verzeichnis_wird_verweigert(kohorte, tmp_path):
    """Der Empfänger lädt, was im Verzeichnis liegt — nicht, was gemeint
    war."""
    schreibe_ndjson(kohorte, tmp_path)
    with pytest.raises(ExportFehler, match="enthält bereits"):
        schreibe_ndjson(kohorte, tmp_path)


def test_ueberschreiben_ersetzt(kohorte, tmp_path):
    schreibe_ndjson(kohorte, tmp_path)
    ergebnis = schreibe_ndjson([patient(9)], tmp_path, ueberschreiben=True)
    assert ergebnis.ressourcen == 1
    assert [r["id"] for r in lies_ndjson(tmp_path / f"Patient{ENDUNG}")] == ["pat-009"]


def test_ueberschreiben_raeumt_typen_weg_die_nicht_mehr_vorkommen(kohorte, tmp_path):
    """Der stille Fehler: Ein zweiter, kleinerer Lauf überschreibt
    Patient.ndjson, aber Condition.ndjson des ersten Laufs bleibt liegen.
    Der Empfänger lüde Diagnosen zu Patienten, die es nicht mehr gibt."""
    schreibe_ndjson(kohorte, tmp_path)
    assert (tmp_path / f"Condition{ENDUNG}").exists()

    ergebnis = schreibe_ndjson([patient(9)], tmp_path, ueberschreiben=True)
    assert not (tmp_path / f"Condition{ENDUNG}").exists()
    assert any("Condition" in h for h in ergebnis.entfernt)


def test_fremde_dateien_bleiben_unangetastet(kohorte, tmp_path):
    """Nur was ein Empfänger mitlesen würde, wird angefasst.

    Der Test muss über den Aufräumzweig laufen — also mit
    `ueberschreiben` und einem Vorlauf. Ohne das prüfte er nur, dass ein
    Export in ein fast leeres Verzeichnis nichts löscht, und trüge trotzdem
    diesen Namen.
    """
    schreibe_ndjson(kohorte, tmp_path)
    (tmp_path / "LIESMICH.md").write_text("Hände weg", encoding="utf-8")

    ergebnis = schreibe_ndjson([patient(9)], tmp_path, ueberschreiben=True)
    assert any("Condition" in h for h in ergebnis.entfernt), "Aufräumen lief"
    assert (tmp_path / "LIESMICH.md").read_text(encoding="utf-8") == "Hände weg"


def test_leeres_verzeichnis_ist_kein_hindernis(kohorte, tmp_path):
    ziel = tmp_path / "leer"
    ziel.mkdir()
    assert schreibe_ndjson(kohorte, ziel).ressourcen == 6


def test_verzeichnis_wird_angelegt(kohorte, tmp_path):
    ziel = tmp_path / "a" / "b" / "c"
    schreibe_ndjson(kohorte, ziel)
    assert (ziel / f"Patient{ENDUNG}").exists()


# --- Fehlerfälle -----------------------------------------------------------


def test_ohne_ressourcen_kein_export(tmp_path):
    """Ein leeres Verzeichnis mit einem Manifest über nichts wäre
    irreführend."""
    with pytest.raises(ExportFehler, match="Keine Ressourcen"):
        schreibe_ndjson([], tmp_path)


def test_ressource_ohne_resourcetype_bricht_ab(tmp_path):
    """Nicht stillschweigend in eine Datei namens 'None.ndjson'
    einsortieren."""
    with pytest.raises(ExportFehler, match="kein resourceType"):
        schreibe_ndjson([patient(1), {"id": "x"}], tmp_path)


def test_abbruch_hinterlaesst_keine_halben_dateien(tmp_path):
    """Die Prüfung läuft vor dem ersten Schreibvorgang."""
    with pytest.raises(ExportFehler):
        schreibe_ndjson([patient(1), {"id": "x"}], tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_ziel_ist_eine_datei(kohorte, tmp_path):
    datei = tmp_path / "keinverzeichnis"
    datei.write_text("x", encoding="utf-8")
    with pytest.raises(ExportFehler, match="kein Verzeichnis"):
        schreibe_ndjson(kohorte, datei)


def test_zeilenumbruch_im_inhalt_wird_maskiert(tmp_path):
    """Ein Umbruch in einem Textfeld zerrisse den Datensatz in zwei halbe
    Zeilen. json.dumps maskiert ihn — hier wird nachgeprüft, dass das auch
    wirklich so ankommt."""
    p = patient(1)
    p["name"][0]["family"] = "Zeile1\nZeile2"
    schreibe_ndjson([p], tmp_path)
    roh = (tmp_path / f"Patient{ENDUNG}").read_bytes()
    assert roh.count(b"\n") == 1, "genau ein echter Umbruch: das Zeilenende"
    assert b"\\n" in roh
    assert lies_ndjson(tmp_path / f"Patient{ENDUNG}")[0]["name"][0]["family"] == "Zeile1\nZeile2"


# --- Rücklesen -------------------------------------------------------------


def test_leerzeilen_werden_uebersprungen(tmp_path):
    pfad = tmp_path / f"Patient{ENDUNG}"
    with open(pfad, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(patient(1)) + "\n\n" + json.dumps(patient(2)) + "\n")
    assert len(lies_ndjson(pfad)) == 2


def test_kaputte_zeile_nennt_die_zeilennummer(tmp_path):
    """Bei 600 Zeilen ist 'ungültiges JSON' ohne Ortsangabe wertlos."""
    pfad = tmp_path / f"Patient{ENDUNG}"
    with open(pfad, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(patient(1)) + "\n{kaputt\n")
    with pytest.raises(ExportFehler, match="Zeile 2"):
        lies_ndjson(pfad)


def test_crlf_datei_wird_beim_lesen_noch_verstanden(tmp_path):
    """Toleranz beim Lesen, Strenge beim Schreiben: Fremde Dateien mit CRLF
    sollen sich noch prüfen lassen."""
    pfad = tmp_path / f"Patient{ENDUNG}"
    pfad.write_bytes((json.dumps(patient(1)) + "\r\n").encode("utf-8"))
    assert lies_ndjson(pfad)[0]["id"] == "pat-001"


# --- Ladereihenfolge -------------------------------------------------------


def test_manifest_nennt_patient_vor_condition(kohorte, tmp_path):
    """Wer die Dateien alphabetisch abarbeitet, lädt Diagnosen vor ihren
    Patienten. HAPI nimmt das hin, Server mit
    enforceReferentialIntegrityOnWrite nicht. Der Leitfaden schreibt keine
    Reihenfolge vor — also kostet die richtige nichts."""
    ergebnis = schreibe_ndjson(kohorte, tmp_path)
    typen = [d.typ for d in ergebnis.dateien]
    assert typen.index("Patient") < typen.index("Condition")

    m = json.loads(ergebnis.manifest.read_text(encoding="utf-8"))
    aus_manifest = [e["type"] for e in m["output"]]
    assert aus_manifest.index("Patient") < aus_manifest.index("Condition")


def test_reihenfolge_kommt_aus_den_daten_nicht_aus_einer_liste(tmp_path):
    """Fest verdrahtet stimmte sie beim nächsten Ressourcentyp nicht mehr.
    Observation zeigt hier auf Encounter, Encounter auf Patient."""
    from synthfhir.domain.integrity import ladereihenfolge

    daten = {
        "Observation": [{"subject": {"reference": "Patient/p"},
                         "encounter": {"reference": "Encounter/e"}}],
        "Condition": [{"subject": {"reference": "Patient/p"}}],
        "Encounter": [{"subject": {"reference": "Patient/p"}}],
        "Patient": [{"id": "p"}],
    }
    assert ladereihenfolge(daten) == ["Patient", "Condition", "Encounter", "Observation"]


def test_ring_wird_alphabetisch_aufgeloest(tmp_path):
    """Zeigen zwei Typen aufeinander, gibt es keine richtige Reihenfolge —
    dann wenigstens eine vorhersagbare."""
    from synthfhir.domain.integrity import ladereihenfolge

    assert ladereihenfolge({
        "B": [{"x": {"reference": "A/1"}}],
        "A": [{"y": {"reference": "B/1"}}],
    }) == ["A", "B"]


def test_verweise_auf_typen_ausserhalb_des_exports_stoeren_nicht(tmp_path):
    """Ein Verweis auf Organization, die gar nicht exportiert wird, darf
    die Reihenfolge nicht blockieren."""
    from synthfhir.domain.integrity import ladereihenfolge

    assert ladereihenfolge({
        "Patient": [{"managingOrganization": {"reference": "Organization/o1"}}],
    }) == ["Patient"]


# --- Gegen den echten Server -----------------------------------------------


def test_rueckgelesene_zeilen_sind_bei_hapi_weiterhin_valide(hapi, tmp_path):
    """Die Byte-Tests oben sehen das Format, nicht den Inhalt.

    Ein Kodierungsschaden — ein zerschnittener Umlaut, ein verlorenes Feld —
    überstünde sie alle und fiele erst beim Empfänger auf. Deshalb geht der
    Weg hier einmal ganz durch: bauen, schreiben, zurücklesen, und was
    dabei herauskommt, dem echten Server vorlegen.
    """
    from synthfhir.domain import assign_ids, baue_aus_parametern

    gebaut = baue_aus_parametern({
        "patienten": [{
            "vorname": "Käthe", "nachname": "Schäfer-Weiß",
            "geschlecht": "female", "geburtsdatum": "1955-03-17",
            "diagnosen": [{"code": "44054006", "beginn": "2015-01-01"}],
            "messwerte": [{"code": "4548-4", "wert": 7.4, "datum": "2024-06-01"}],
        }]
    })
    ressourcen = assign_ids(gebaut.ressourcen).resources
    schreibe_ndjson(ressourcen, tmp_path)

    zurueck = [r for pfad in tmp_path.glob(f"*{ENDUNG}") for r in lies_ndjson(pfad)]
    assert len(zurueck) == len(ressourcen)

    for r in zurueck:
        fehler = hapi.fehler(r)
        assert not fehler, f"{r['resourceType']}/{r.get('id')}: {fehler}"

    # Und der Umlaut hat den Weg überstanden.
    patient = next(r for r in zurueck if r["resourceType"] == "Patient")
    assert patient["name"][0]["family"] == "Schäfer-Weiß"


# --- Nachgestellte Befunde -------------------------------------------------


def test_resourcetype_kommt_nicht_in_den_dateinamen_ohne_pruefung(tmp_path):
    """Nachgestellt: `resourceType` von "../entwischt" schrieb die Datei
    AUSSERHALB des Zielverzeichnisses. Der Typ wird zum Dateinamen, also
    muss er einer sein."""
    ziel = tmp_path / "ziel"
    ziel.mkdir()
    with pytest.raises(ExportFehler, match="kein Ressourcentyp"):
        schreibe_ndjson([{"resourceType": "../entwischt", "id": "x"}], ziel)
    assert list(tmp_path.glob("*.ndjson")) == [], "nichts ausserhalb gelandet"
    assert list(ziel.glob("*")) == [], "und nichts darin"


@pytest.mark.parametrize("typ", ["../weg", "a/b", "Patient.ndjson", "", "  ",
                                 "Pat-ient", "Patient2", r"C:\weg"])
def test_untaugliche_ressourcentypen_werden_abgewiesen(typ, tmp_path):
    with pytest.raises(ExportFehler):
        schreibe_ndjson([{"resourceType": typ, "id": "x"}], tmp_path)


def test_nan_wird_nicht_als_json_ausgegeben(tmp_path):
    """Voreingestellt schriebe json.dumps das Wort NaN — RFC 8259 kennt es
    nicht. Die Zeile sähe aus wie JSON und wäre keines."""
    p = patient(1)
    p["unsinn"] = float("nan")
    with pytest.raises(ExportFehler, match="abgebrochen"):
        schreibe_ndjson([p], tmp_path)


def test_abbruch_nimmt_angefangene_dateien_zurueck(tmp_path):
    """Ein halber Export ohne Manifest sieht aus wie ein ganzer: Der
    Empfänger sieht NDJSON-Dateien und lädt sie."""
    kaputt = {"resourceType": "Zzz", "id": "x", "wert": float("inf")}
    with pytest.raises(ExportFehler):
        schreibe_ndjson([patient(1), kaputt], tmp_path)
    assert list(tmp_path.iterdir()) == [], "kein halber Export zurückgeblieben"


def test_ohne_neues_manifest_bleibt_kein_altes_liegen(kohorte, tmp_path):
    """Nachgestellt: Lauf 1 schrieb Patient und Condition, Lauf 2 nur
    Patient — und das Manifest des ersten wies weiter beide aus."""
    schreibe_ndjson(kohorte, tmp_path)
    assert (tmp_path / MANIFEST_NAME).exists()

    schreibe_ndjson([patient(9)], tmp_path, manifest=False, ueberschreiben=True)
    assert not (tmp_path / MANIFEST_NAME).exists(), (
        "ein Manifest, das nicht mehr stimmt, ist schlimmer als keines"
    )


def test_naiver_zeitpunkt_wird_abgewiesen(kohorte, tmp_path):
    """Nachgestellt: 12:00 ohne Zeitzone wurde in der Sommerzeit zu 10:00Z.
    `transactionTime` ist ein `instant` — ein Zeitpunkt ohne Zone ist
    keiner."""
    with pytest.raises(ExportFehler, match="Zeitzone"):
        schreibe_ndjson(kohorte, tmp_path, zeitpunkt=datetime(2026, 8, 29, 12, 0))


def test_zeitpunkt_wird_nach_utc_umgerechnet(kohorte, tmp_path):
    """Eine andere Zone ist in Ordnung — sie wird umgerechnet, nicht
    abgelehnt."""
    from datetime import timedelta

    ergebnis = schreibe_ndjson(
        kohorte, tmp_path,
        zeitpunkt=datetime(2026, 8, 29, 14, 0, tzinfo=timezone(timedelta(hours=2))),
    )
    m = json.loads(ergebnis.manifest.read_text(encoding="utf-8"))
    assert m["transactionTime"] == "2026-08-29T12:00:00Z"


def test_rest_mit_abweichender_schreibweise_wird_erkannt(kohorte, tmp_path):
    """Nachgestellt: `Encounter.NDJSON` rutschte durch die Sperre und blieb
    neben dem neuen Export liegen. Unter Windows ist es dieselbe Datei, und
    ein Empfänger unterscheidet ohnehin nicht."""
    (tmp_path / "Encounter.NDJSON").write_text("{}", encoding="utf-8")
    with pytest.raises(ExportFehler, match="enthält bereits"):
        schreibe_ndjson(kohorte, tmp_path)

    ergebnis = schreibe_ndjson(kohorte, tmp_path, ueberschreiben=True)
    assert not (tmp_path / "Encounter.NDJSON").exists()
    assert any("Encounter" in h for h in ergebnis.entfernt)


# --- Ein Kern, zwei Ausgänge -----------------------------------------------


def test_archiv_und_platte_liefern_dieselben_bytes(kohorte, tmp_path):
    """Die Zusage hinter `baue_dateien`.

    Solange Datei- und Archivweg denselben Kern benutzen, kann eine der
    beiden Ausgaben nicht still von den Regeln abweichen. Genau das wäre
    der Fehler, den niemand bemerkt: Ein CRLF im heruntergeladenen Archiv
    sieht in keiner Anzeige anders aus als ein LF.
    """
    import io
    import zipfile

    schreibe_ndjson(kohorte, tmp_path)
    archiv = zipfile.ZipFile(io.BytesIO(baue_archiv(kohorte)))

    auf_platte = {
        p.name: p.read_bytes() for p in tmp_path.glob(f"*{ENDUNG}")
    }
    im_archiv = {
        n: archiv.read(n) for n in archiv.namelist() if n.endswith(ENDUNG)
    }
    assert auf_platte == im_archiv


def test_archiv_ist_bei_gleichem_zeitpunkt_byteweise_gleich(kohorte):
    """ADR-006 verspricht, dass gleiche Eingaben gleiche Ausgaben ergeben.

    Ohne festen Zeitstempel je Eintrag unterschieden sich zwei Archive aus
    denselben Daten — nicht im Inhalt, aber in jedem Byte des Zeitfelds.
    Ein Prüfsummenvergleich wäre damit wertlos.
    """
    t = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    assert baue_archiv(kohorte, zeitpunkt=t) == baue_archiv(kohorte, zeitpunkt=t)


def test_archivmanifest_bleibt_bei_der_veroeffentlichten_fassung(kohorte):
    """Dieselbe Auflage wie beim Manifest auf Platte, und sie steht hier,
    weil genau an dieser Stelle schon einmal etwas eingesickert ist:
    `outputFormat` und `fileSize` definiert erst der Continuous Build."""
    import io
    import zipfile

    archiv = zipfile.ZipFile(io.BytesIO(baue_archiv(kohorte)))
    manifest = json.loads(archiv.read(MANIFEST_NAME))
    assert set(manifest) == {
        "transactionTime", "request", "requiresAccessToken",
        "output", "error", "extension",
    }
    for eintrag in manifest["output"]:
        assert set(eintrag) == {"type", "url", "count"}
        # Im Archiv ist der Eintragsname die richtige Adresse. Ein
        # absoluter Pfad wäre der Pfad auf dem Server — für den Empfänger
        # nutzlos und eine Auskunft, die ihn nichts angeht.
        assert eintrag["url"] == f"{eintrag['type']}{ENDUNG}"
        assert archiv.read(eintrag["url"])


def test_archiv_ohne_ressourcen_wird_abgelehnt():
    with pytest.raises(ExportFehler, match="Keine Ressourcen"):
        baue_archiv([])


def test_archiv_verlangt_eine_zeitzone(kohorte):
    """Ohne Zeitzone deutete astimezone den Wert als Ortszeit und verschöbe
    transactionTime still um den lokalen Versatz."""
    with pytest.raises(ExportFehler, match="Zeitzone"):
        baue_archiv(kohorte, zeitpunkt=datetime(2026, 8, 30, 12, 0))


def test_archiv_haelt_die_ladereihenfolge(kohorte):
    """Wer die Dateien der Reihe nach lädt, soll keine Verweise ins Leere
    bekommen.

    Im Archiv steht die Reihenfolge an zwei Stellen — als Eintragsfolge und
    im Manifest. Beide müssen dieselbe sein, sonst folgt ein Werkzeug der
    einen und ein Mensch der anderen.
    """
    import io
    import zipfile

    typen = [d.typ for d in baue_dateien(kohorte)]
    assert typen.index("Patient") < typen.index("Condition")

    archiv = zipfile.ZipFile(io.BytesIO(baue_archiv(kohorte)))
    im_archiv = [
        n[: -len(ENDUNG)] for n in archiv.namelist() if n.endswith(ENDUNG)
    ]
    assert im_archiv == typen
    manifest = json.loads(archiv.read(MANIFEST_NAME))
    assert [o["type"] for o in manifest["output"]] == typen


# --- Was ein Abbruch zurücklässt -------------------------------------------


def test_abgebrochener_export_laesst_kein_luegendes_manifest_zurueck(
    kohorte, tmp_path, monkeypatch
):
    """Die Rücknahme nahm die Datendateien weg und liess das Manifest stehen.

    Es stand unter `behalten`, weil dieser Lauf es „gleich überschreibt" —
    was nach dem Abbruch nie geschieht. Zurück blieb ein Verzeichnis mit
    nichts als einem Manifest, das zwei `output`-Einträge und zwei
    `file:`-URLs behauptet, die auf nichts mehr zeigen. Genau das lügende
    Manifest, das ADR-005 als behobenen Fehler führt — nur über den Weg des
    Abbruchs statt über `manifest=False`.
    """
    schreibe_ndjson(kohorte, tmp_path)
    assert (tmp_path / MANIFEST_NAME).exists(), "der Vorlauf muss stehen"

    echt = Path.write_bytes
    geschrieben = {"n": 0}

    def bricht_beim_zweiten_ab(self, daten):
        geschrieben["n"] += 1
        if geschrieben["n"] >= 2:
            raise OSError("kein Platz auf dem Gerät")
        return echt(self, daten)

    monkeypatch.setattr(Path, "write_bytes", bricht_beim_zweiten_ab)
    with pytest.raises(ExportFehler, match="abgebrochen"):
        schreibe_ndjson(kohorte, tmp_path, ueberschreiben=True)
    monkeypatch.undo()

    uebrig = sorted(p.name for p in tmp_path.iterdir())
    assert uebrig == [], f"zurückgeblieben: {uebrig}"


def test_zeitpunkt_ohne_zeitzone_schreibt_gar_nichts(kohorte, tmp_path):
    """Die Prüfung stand in `_schreibe_manifest` — also nach allen
    NDJSON-Dateien und ausserhalb der Rücknahme.

    Ergebnis war der halbe Export ohne Manifest, den ADR-005 als behoben
    führt: Für einen Empfänger von einem vollständigen nicht zu
    unterscheiden. `baue_archiv` prüft seit jeher vorab — die beiden
    Ausgabewege waren nicht gleich streng.
    """
    with pytest.raises(ExportFehler, match="Zeitzone"):
        schreibe_ndjson(kohorte, tmp_path, zeitpunkt=datetime(2026, 1, 1, 12, 0, 0))

    uebrig = sorted(p.name for p in tmp_path.iterdir())
    assert uebrig == [], f"geschrieben trotz Abbruch: {uebrig}"
