"""scan grades and gen-fixtures errors from a private-checkout run (2026-11-11).

* A4 -- ``scan`` graded files that failed to parse. Its ``health`` report
  never received the parse-error count, so a file the single-file
  ``health`` subcommand leaves ungraded ("parsed with 13 errors") got a B;
  and a file whose copybook expansion failed (CKBADR02, DPBRSTF2) fell back
  to an unexpanded parse with no errors and got an A with no caveat. Both
  now carry the grade withheld with a caveat, and the summary counts them as
  ``degraded_file_count``.
* A7 -- ``gen-fixtures`` let a ``CopybookSyntaxError`` escape as a
  traceback; it is now ``error: ...`` and exit 1.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cobolparser.cli.parse import main
from cobolparser.scan import ScanOptions, scan_files, scan_one


def _rec(text: str) -> str:
    return ("       " + text).ljust(72)[:72]


def _program(body: list[str], data: list[str] | None = None) -> str:
    lines = [
        _rec("IDENTIFICATION DIVISION."),
        _rec("PROGRAM-ID. CKBADR02."),
        _rec("DATA DIVISION."),
        _rec("WORKING-STORAGE SECTION."),
        *[_rec(line) for line in (data or ["01  WS-A  PIC X."])],
        _rec("PROCEDURE DIVISION."),
        _rec("MAIN-PARA."),
        *[_rec(line) for line in body],
        _rec("    GOBACK."),
    ]
    return "\n".join(lines) + "\n"


@pytest.fixture
def binary_copybook(tmp_path: Path) -> Path:
    books = tmp_path / "copy"
    books.mkdir()
    # Mostly control bytes: refused as binary (CopybookSyntaxError).
    (books / "W1CKBADR.cpy").write_bytes(b"\x00\x01\x02\x03\x04\x05\x06\x07" * 20)
    return books


class TestA4ScanGrades:
    def test_copybook_failure_withholds_the_grade(
        self, tmp_path: Path, binary_copybook: Path
    ) -> None:
        path = tmp_path / "CKBADR02.cbl"
        path.write_text(
            _program(
                ["    MOVE 'X' TO WS-A."], ["01  WS-A  PIC X.", "    COPY W1CKBADR."]
            )
        )
        scan = scan_one(
            str(path),
            ScanOptions(analyzers=("health",), copybook_paths=(str(binary_copybook),)),
        )
        assert scan.copybook_error
        health = scan.units[0].reports["health"]
        assert health["grade"] is None
        assert any("copybook expansion failed" in c for c in health["caveats"])

    def test_parse_errors_withhold_the_grade(self, tmp_path: Path) -> None:
        path = tmp_path / "SMPONT01.cbl"
        path.write_text(_program(["    MOVE 'X'.", "    MOVE WS-A."]))
        scan = scan_one(str(path), ScanOptions(analyzers=("health",)))
        assert scan.parse_error_count > 0
        health = scan.units[0].reports["health"]
        assert health["grade"] is None
        assert health["parse_error_count"] == scan.parse_error_count

    def test_clean_file_keeps_its_grade(self, tmp_path: Path) -> None:
        path = tmp_path / "CLEAN.cbl"
        path.write_text(_program(["    MOVE 'X' TO WS-A."]))
        scan = scan_one(str(path), ScanOptions(analyzers=("health",)))
        assert scan.units[0].reports["health"]["grade"] is not None

    def test_summary_counts_degraded_files(self, tmp_path: Path) -> None:
        clean = tmp_path / "CLEAN.cbl"
        clean.write_text(_program(["    MOVE 'X' TO WS-A."]))
        broken = tmp_path / "BROKEN.cbl"
        broken.write_text(_program(["    MOVE 'X'."]))
        summary = scan_files(
            [str(clean), str(broken)], ScanOptions(analyzers=("health",)), workers=1
        ).to_dict()["summary"]
        assert summary["degraded_file_count"] == 1
        assert summary["failed_file_count"] == 0
        assert summary["file_count"] == 2


class TestA7GenFixturesCopybookError:
    def test_copybook_syntax_error_is_one_line(
        self,
        tmp_path: Path,
        binary_copybook: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        path = tmp_path / "CKBADR02.cbl"
        path.write_text(
            _program(
                ["    MOVE 'X' TO WS-A."], ["01  WS-A  PIC X.", "    COPY W1CKBADR."]
            )
        )
        for extra in ([], ["--list-boundaries"]):
            argv = ["cobol-parser", "gen-fixtures", str(path)]
            argv += ["--copybook-path", str(binary_copybook), *extra]
            with patch("sys.argv", argv), pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 1
            err = capsys.readouterr().err
            assert err.startswith("error: Copybook expansion failed")
            assert "Traceback" not in err
