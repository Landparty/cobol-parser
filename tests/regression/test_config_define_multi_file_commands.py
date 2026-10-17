"""Regression (#324): cobol.yml ``project.define`` reached only the single-file
subcommands.

``apply_project_config`` skips a setting the running subcommand has no flag
for, and did so silently: ``scan`` reported code under ``>>IF DBG`` as dead,
``field-impact`` could not find a field MOVEd there, and ``gen-fixtures``
listed no boundary for a CALL there -- each analysing a different program
than ``dead-code`` / ``lineage`` / ``parse`` did on the same file.

Both options of the issue: ``scan`` and ``field-impact`` now take
``--define`` (``ScanOptions.defined_symbols``) and with it the config value,
and a subcommand that still has no flag for a program-shaping setting says
so on stderr instead of dropping it.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cobolparser.cli.parse import main
from cobolparser.scan import ScanOptions, scan_one

_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. Q.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC X(4).
       01  WS-B PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
       >>IF DBG DEFINED
           PERFORM DUMP-PARA
       >>END-IF
           GOBACK.
       DUMP-PARA.
           MOVE WS-A TO WS-B
           DISPLAY WS-B.
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "cobol.yml").write_text("project:\n  define: [DBG]\n")
    (tmp_path / "q.cbl").write_text(_PROGRAM)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = 0
    with patch("sys.argv", ["cobol-parser", *argv]):
        try:
            main()
        except SystemExit as exc:
            code = int(exc.code or 0)
    out, err = capsys.readouterr()
    return code, out, err


class TestScanHonoursDefines:
    def test_config_define_reaches_scan(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _, out, err = _run(["scan", "q.cbl", "--analyzer", "dead-code"], capsys)
        assert "DUMP-PARA" not in out
        assert "project.define" not in err

    def test_without_the_define_the_paragraph_is_dead(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _, out, _ = _run(
            ["--no-config", "scan", "q.cbl", "--analyzer", "dead-code"], capsys
        )
        assert "DUMP-PARA" in out

    def test_define_flag(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _, out, _ = _run(
            [
                "--no-config",
                "scan",
                "q.cbl",
                "--analyzer",
                "dead-code",
                "--define",
                "DBG",
            ],
            capsys,
        )
        assert "DUMP-PARA" not in out

    def test_scan_options_with_copybook_expansion(self, tmp_path: Path) -> None:
        (tmp_path / "cpy").mkdir()
        (tmp_path / "cpy" / "BODY.cpy").write_text(
            "       >>IF DBG DEFINED\n"
            "           PERFORM DUMP-PARA\n"
            "       >>END-IF\n"
        )
        source = _PROGRAM.replace(
            "       >>IF DBG DEFINED\n"
            "           PERFORM DUMP-PARA\n"
            "       >>END-IF\n",
            "           COPY BODY.\n",
        )
        path = tmp_path / "c.cbl"
        path.write_text(source)
        for defines, dead in (((("DBG", "TRUE"),), False), ((), True)):
            scan = scan_one(
                str(path),
                ScanOptions(
                    analyzers=("dead-code",),
                    copybook_paths=(str(tmp_path / "cpy"),),
                    defined_symbols=defines,
                ),
            )
            assert scan.error is None
            report = json.dumps(scan.units[0].reports)
            assert ("DUMP-PARA" in report) is dead


class TestFieldImpactHonoursDefines:
    def test_config_define_reaches_field_impact(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out, err = _run(
            ["field-impact", "WS-A", "q.cbl", "--format", "text"], capsys
        )
        assert code == 0, err
        assert "WS-B" in out

    def test_takes_source_format(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out, err = _run(
            ["field-impact", "WS-A", "q.cbl", "--source-format", "fixed"], capsys
        )
        assert code == 0, err
        assert "WS-B" in out


class TestUnappliedSettingsWarn:
    @pytest.mark.parametrize(
        "argv",
        [
            ["batch", "q.cbl"],
            ["gen-fixtures", "q.cbl", "--list-boundaries"],
            ["codebase-graph", "q.cbl"],
        ],
    )
    def test_dropped_define_is_reported(
        self, project: Path, capsys: pytest.CaptureFixture[str], argv: list[str]
    ) -> None:
        _, _, err = _run(argv, capsys)
        assert "project.define" in err
        assert f"`{argv[0]}` has no flag for it" in err

    def test_dropped_source_format_is_reported(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (project / "cobol.yml").write_text("project:\n  source_format: fixed\n")
        _, _, err = _run(["batch", "q.cbl"], capsys)
        assert "project.source_format" in err

    def test_default_valued_settings_are_not_reported(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (project / "cobol.yml").write_text(
            "project:\n  source_format: auto\n  debug_lines: false\n"
        )
        _, _, err = _run(["batch", "q.cbl"], capsys)
        assert "cobol.yml sets" not in err

    @pytest.mark.parametrize(
        "argv",
        [
            ["dead-code", "q.cbl"],
            ["scan", "q.cbl"],
            ["config"],
            ["le-info", "CEEDAYS"],
        ],
    )
    def test_commands_that_apply_it_or_parse_nothing_stay_quiet(
        self, project: Path, capsys: pytest.CaptureFixture[str], argv: list[str]
    ) -> None:
        _, _, err = _run(argv, capsys)
        assert "project.define" not in err
