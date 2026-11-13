"""Issue #897: a COPY member that is not found keeps the health grade but
gets a caveat naming it, and the file counts in ``degraded_file_count``
(Samuel picked option 2). A failed expansion still withholds the grade."""

from __future__ import annotations

import json
from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.analysis.technical_debt import TechnicalDebtAnalyzer
from cobolparser.cli.parse import main
from cobolparser.scan import ScanOptions, scan_files, scan_one

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. A.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY MISSING.
       PROCEDURE DIVISION.
           DISPLAY 'X'.
           GOBACK.
"""

CLEAN = PROGRAM.replace("       COPY MISSING.\n", "       01  WS-A  PIC X.\n")


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def test_analyzer_keeps_the_grade_and_names_the_members():
    ast = parse_cobol(CLEAN).ast
    report = TechnicalDebtAnalyzer().analyze(
        ast, unexpanded_copybooks=["MISSING", "OTHER", "MISSING"]
    )
    assert report.grade is not None
    assert len(report.caveats) == 1
    assert "MISSING, OTHER" in report.caveats[0]
    assert "2 copybook member(s)" in report.caveats[0]


def test_failed_expansion_still_withholds_without_a_second_caveat():
    ast = parse_cobol(CLEAN).ast
    report = TechnicalDebtAnalyzer().analyze(
        ast, copybook_error="CircularReferenceError: x", unexpanded_copybooks=["X"]
    )
    assert report.grade is None
    assert len(report.caveats) == 1


def test_scan_caveats_and_counts_a_not_found_member(tmp_path):
    books = tmp_path / "cb"
    books.mkdir()
    path = _write(tmp_path, "A.cbl", PROGRAM)
    clean = _write(tmp_path, "C.cbl", CLEAN)
    options = ScanOptions(analyzers=("health",), copybook_paths=(str(books),))
    scan = scan_one(str(path), options)
    assert scan.unexpanded_copybooks == ["MISSING"]
    health = scan.units[0].reports["health"]
    assert health["grade"] is not None
    assert any("MISSING" in c for c in health["caveats"])

    summary = scan_files([str(path), str(clean)], options, workers=1).to_dict()[
        "summary"
    ]
    assert summary["degraded_file_count"] == 1


def test_health_subcommand_caveats_a_not_found_member(tmp_path, capsys, monkeypatch):
    books = tmp_path / "cb"
    books.mkdir()
    path = _write(tmp_path, "A.cbl", PROGRAM)
    argv = ["cobol-parser", "health", str(path), "--copybook-path", str(books)]
    monkeypatch.setattr("sys.argv", [*argv, "--no-config"])
    main()
    report = json.loads(capsys.readouterr().out)
    assert report["grade"] is not None
    assert any("MISSING" in c for c in report["caveats"])
