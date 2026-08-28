"""Dateiausgabe der Messartefakte (Abschnitt 9).

Ablage je Messreihe:

    output/<zeitstempel>/
        session.json                     Konfiguration und Überblick
        bericht.md                       Vergleichsbericht A gegen B
        variante-A/<szenario>/lauf-01/
            prompt.txt                   System- und User-Prompt
            llm-roh-1.txt                unveränderte Modellantwort
            ressourcen.json              nach ID-/Referenzvergabe
            bundle.json                  Bundle (collection)
            parameter.json               nur Variante B
            validierung/<Typ>-<id>.json  OperationOutcome je Ressource
            korrektur/<Typ>-<id>-runde-N.json  Zwischenstände (nur A)
            metriken.json                maschinenlesbare Metriken

Alles wird als UTF-8 geschrieben; deutsche Umlaute bleiben lesbar
(`ensure_ascii=False`).
"""

from __future__ import annotations

import json
from pathlib import Path

SAFE_CHARS = "-_."


def _safe(name: str) -> str:
    """Macht aus einem Bezeichner einen dateisystemtauglichen Namen."""
    cleaned = "".join(c if c.isalnum() or c in SAFE_CHARS else "-" for c in name)
    return cleaned.strip("-") or "unbenannt"


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class RunArtifacts:
    """Schreibt alle Artefakte eines einzelnen Durchlaufs."""

    def __init__(self, session_dir: Path, variant: str, scenario_key: str, run_index: int) -> None:
        self.dir = (
            session_dir
            / f"variante-{_safe(variant)}"
            / _safe(scenario_key)
            / f"lauf-{run_index:02d}"
        )
        self.dir.mkdir(parents=True, exist_ok=True)

    def prompt(self, system: str, user: str) -> None:
        write_text(
            self.dir / "prompt.txt",
            f"=== SYSTEM ===\n{system}\n\n=== USER ===\n{user}\n",
        )

    def raw_responses(self, responses: list[str]) -> None:
        for index, text in enumerate(responses, start=1):
            write_text(self.dir / f"llm-roh-{index}.txt", text)

    def parameters(self, payload: dict | None) -> None:
        if payload is not None:
            write_json(self.dir / "parameter.json", payload)

    def resources(self, resources: list[dict]) -> None:
        write_json(self.dir / "ressourcen.json", resources)

    def bundle(self, bundle: dict) -> None:
        write_json(self.dir / "bundle.json", bundle)

    def validation(self, resource_type: str, resource_id: str, outcome: dict) -> None:
        write_json(
            self.dir / "validierung" / f"{_safe(resource_type)}-{_safe(resource_id)}.json",
            outcome,
        )

    def repair_snapshot(
        self, resource_type: str, resource_id: str, round_no: int, resource: dict
    ) -> None:
        write_json(
            self.dir
            / "korrektur"
            / f"{_safe(resource_type)}-{_safe(resource_id)}-runde-{round_no}.json",
            resource,
        )

    def integrity(self, report: dict) -> None:
        write_json(self.dir / "integritaet.json", report)

    def metrics(self, payload: dict) -> None:
        write_json(self.dir / "metriken.json", payload)


def session_dir(output_dir: Path, stamp: str) -> Path:
    path = output_dir / stamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def collect_run_metrics(session_dir_path: Path) -> list[dict]:
    """Liest alle Metrikdateien einer Messreihe von der Platte.

    Damit lässt sich der Vergleichsbericht neu erzeugen, ohne die Messung
    zu wiederholen.
    """
    runs: list[dict] = []
    for path in sorted(session_dir_path.rglob("metriken.json")):
        try:
            runs.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return runs
