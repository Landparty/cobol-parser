"""SARIF 2.1.0 output: ``lint``, ``scan`` and ``call-check --format sarif``.

The logs were validated against the OASIS SARIF 2.1.0 JSON schema when
this was written (the schema is not vendored: the suite runs offline);
these tests pin the shape consumers depend on -- levels, locations relative
to the source root, copybook findings placed in the copybook, and caveats
as run notifications.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from cobolparser.analysis.sarif import (
    SARIF_VERSION,
    SarifNotification,
    SarifResult,
    lint_results,
    sarif_log,
)
from cobolparser.cli.parse import main
from cobolparser.scan import ScanOptions, scan_one

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
ENTERPRISE = SAMPLES / "enterprise"

CALLEE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLEE.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-REC     PIC X(30).
       PROCEDURE DIVISION USING LK-REC.
           GOBACK.
"""

CALLER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-SHORT   PIC X(20).
       PROCEDURE DIVISION.
           CALL 'CALLEE' USING WS-SHORT
           GOBACK.
"""


def _run(argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys) -> tuple[Any, int]:
    monkeypatch.setattr(sys, "argv", ["cobol-parser", "--no-config", *argv])
    code = 0
    try:
        main()
    except SystemExit as exc:
        code = int(exc.code or 0)
    return json.loads(capsys.readouterr().out), code


def _run_of(log: dict[str, Any]) -> dict[str, Any]:
    assert log["version"] == SARIF_VERSION
    assert log["$schema"].endswith("sarif-2.1.0.json")
    (run,) = log["runs"]
    return run


def _uris(run: dict[str, Any]) -> set[str]:
    return {
        loc["physicalLocation"]["artifactLocation"]["uri"]
        for result in run["results"]
        for loc in result.get("locations", [])
    }


class TestSarifLog:
    def test_levels_rules_and_regions(self, tmp_path: Path) -> None:
        source = tmp_path / "A.cbl"
        log = sarif_log(
            [
                SarifResult("dead-code", "warning", "dead", str(source), 7, 12),
                SarifResult("complexity", "info", "busy", str(source), 9),
                SarifResult("dead-code", "error", "again", str(source), 3),
            ],
            base=tmp_path,
        )
        run = _run_of(log)
        assert [r["id"] for r in run["tool"]["driver"]["rules"]] == [
            "dead-code",
            "complexity",
        ]
        assert [(r["ruleId"], r["ruleIndex"], r["level"]) for r in run["results"]] == [
            ("dead-code", 0, "warning"),
            ("complexity", 1, "note"),
            ("dead-code", 0, "error"),
        ]
        location = run["results"][0]["locations"][0]["physicalLocation"]
        assert location["artifactLocation"] == {
            "uri": "A.cbl",
            "uriBaseId": "%SRCROOT%",
        }
        assert location["region"] == {"startLine": 7, "startColumn": 12}
        assert (
            "startColumn"
            not in run["results"][1]["locations"][0]["physicalLocation"]["region"]
        )
        assert run["originalUriBaseIds"]["%SRCROOT%"]["uri"] == (
            tmp_path.resolve().as_uri() + "/"
        )

    def test_outside_the_base_is_an_absolute_uri(self, tmp_path: Path) -> None:
        elsewhere = tmp_path / "other" / "B.cbl"
        run = _run_of(
            sarif_log(
                [SarifResult("parse", "error", "x", str(elsewhere), 1)],
                base=tmp_path / "root",
            )
        )
        artifact = run["results"][0]["locations"][0]["physicalLocation"][
            "artifactLocation"
        ]
        assert artifact == {"uri": elsewhere.as_uri()}

    def test_no_line_no_location(self) -> None:
        run = _run_of(sarif_log([SarifResult("parse", "error", "x", "A.cbl", None)]))
        assert "locations" not in run["results"][0]

    def test_notifications(self) -> None:
        run = _run_of(
            sarif_log([], [SarifNotification("a COPY could not be resolved")])
        )
        (note,) = run["invocations"][0]["toolExecutionNotifications"]
        assert note == {
            "level": "note",
            "message": {"text": "a COPY could not be resolved"},
        }
        assert run["results"] == [] and run["tool"]["driver"]["rules"] == []

    def test_origin_wins_over_location(self) -> None:
        report = {
            "findings": [
                {
                    "rule": "unused-variables",
                    "severity": "info",
                    "message": "m",
                    "location": {"line": 90, "column": 5},
                    "origin": {"file": "copy/REC.cpy", "line": 4, "column": 12},
                    "symbol": "REC-A",
                    "kind": "WORKING-STORAGE",
                }
            ]
        }
        (result,) = lint_results(report, "PROG.cbl")
        assert (result.file, result.line, result.column) == ("copy/REC.cpy", 4, 12)
        assert result.properties == {"kind": "WORKING-STORAGE", "symbol": "REC-A"}


class TestLintCli:
    def test_lint_sarif(self, monkeypatch, capsys) -> None:
        monkeypatch.chdir(SAMPLES.parent.parent)
        log, code = _run(
            [
                "lint",
                str(ENTERPRISE / "BATCHSEQ.cbl"),
                "--copybook-path",
                str(ENTERPRISE / "copybooks"),
                "--format",
                "sarif",
            ],
            monkeypatch,
            capsys,
        )
        assert code == 0
        run = _run_of(log)
        assert run["results"]
        assert all(r["level"] in ("error", "warning", "note") for r in run["results"])
        assert _uris(run) == {"tests/samples/enterprise/BATCHSEQ.cbl"}

    def test_fail_on_still_applies(self, monkeypatch, capsys) -> None:
        _log, code = _run(
            [
                "lint",
                str(ENTERPRISE / "BATCHSEQ.cbl"),
                "--format",
                "sarif",
                "--fail-on",
                "info",
            ],
            monkeypatch,
            capsys,
        )
        assert code == 3


class TestScanCli:
    def test_scan_lint_is_once_per_file(self) -> None:
        # NESTED.cbl holds contained programs; lint covers them all, so a
        # per-unit run would report each contained program's findings again.
        scanned = scan_one(
            str(ENTERPRISE / "NESTED.cbl"), ScanOptions(analyzers=("lint",))
        )
        assert len(scanned.units) > 1
        assert all("lint" not in unit.reports for unit in scanned.units)
        findings = scanned.reports["lint"]["findings"]
        keys = [(f["rule"], f["message"], f["location"]["line"]) for f in findings]
        assert len(keys) == len(set(keys))
        assert scanned.to_dict()["reports"]["lint"]["findings"] == findings

    def test_scan_sarif_places_copybook_findings_in_the_copybook(
        self, monkeypatch, capsys
    ) -> None:
        log, code = _run(
            [
                "scan",
                *[str(p) for p in sorted(ENTERPRISE.glob("*.cbl"))],
                "--copybook-path",
                str(ENTERPRISE / "copybooks"),
                "--format",
                "sarif",
                "--workers",
                "1",
            ],
            monkeypatch,
            capsys,
        )
        assert code == 0
        uris = _uris(_run_of(log))
        assert any(uri.endswith(".cpy") for uri in uris)
        assert len({uri for uri in uris if uri.endswith(".cbl")}) > 5

    def test_scan_sarif_with_other_analyzers_adds_lint(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        out = tmp_path / "out.sarif"
        code = 0
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "cobol-parser",
                "--no-config",
                "scan",
                str(ENTERPRISE / "SUBPROG.cbl"),
                "--analyzer",
                "health",
                "--format",
                "sarif",
                "--workers",
                "1",
                "-o",
                str(out),
            ],
        )
        try:
            main()
        except SystemExit as exc:
            code = int(exc.code or 0)
        assert code == 0
        _run_of(json.loads(out.read_text()))

    def test_scan_sarif_failed_file(self, tmp_path: Path, monkeypatch, capsys) -> None:
        missing = tmp_path / "GONE.cbl"
        log, code = _run(
            ["scan", str(missing), "--format", "sarif", "--workers", "1"],
            monkeypatch,
            capsys,
        )
        assert code == 2
        (note,) = _run_of(log)["invocations"][0]["toolExecutionNotifications"]
        assert note["level"] == "error" and "not scanned" in note["message"]["text"]


class TestCallCheckCli:
    def test_call_check_sarif(self, tmp_path: Path, monkeypatch, capsys) -> None:
        (tmp_path / "CALLEE.cbl").write_text(CALLEE)
        (tmp_path / "CALLER.cbl").write_text(CALLER)
        monkeypatch.chdir(tmp_path)
        log, code = _run(
            ["call-check", "CALLEE.cbl", "CALLER.cbl", "--format", "sarif"],
            monkeypatch,
            capsys,
        )
        assert code == 0
        run = _run_of(log)
        (result,) = run["results"]
        assert result["ruleId"] == "call-check/length"
        assert result["level"] == "error"
        location = result["locations"][0]["physicalLocation"]
        assert location["artifactLocation"]["uri"] == "CALLER.cbl"
        assert location["region"]["startLine"] == 7
        assert result["properties"]["callee"] == "CALLEE"
