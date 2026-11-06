"""``lint`` CLI policy flags: the default --min-severity per format,
--disable, --severity, --exclude, --baseline / --write-baseline,
--strict-copybooks and the IBM copybook stand-ins, --workers, and the same
settings from cobol.yml."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cobolparser.cli.parse import main

# One warning (WS-UNUSED), one info (the EXIT-only dead paragraph).
PROG = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-UNUSED   PIC X.
       PROCEDURE DIVISION.
       0000-MAIN.
           GOBACK.
       0000-MAIN-EXIT.
           EXIT.
"""

ONLINE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ONLINE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY DFHAID.
       01  WS-KEY   PIC X.
       PROCEDURE DIVISION.
           IF WS-KEY = DFHPF3
               DISPLAY WS-KEY
           END-IF
           GOBACK.
"""


def _run(capsys, *argv: str) -> tuple[int, str, str]:
    code = 0
    with patch("sys.argv", ["cobol-parser", "lint", "--no-config", *argv]):
        try:
            main()
        except SystemExit as exc:
            code = int(exc.code or 0)
    out, err = capsys.readouterr()
    return code, out, err


@pytest.fixture
def prog(tmp_path: Path) -> Path:
    path = tmp_path / "PROG.cbl"
    path.write_text(PROG)
    return path


class TestDefaultMinSeverity:
    def test_text_hides_info_by_default(self, capsys, prog) -> None:
        _, out, _ = _run(capsys, str(prog), "--format", "text")
        assert "WS-UNUSED" in out
        assert "0000-MAIN-EXIT" not in out

    def test_json_keeps_everything_by_default(self, capsys, prog) -> None:
        _, out, _ = _run(capsys, str(prog))
        symbols = {f["symbol"] for f in json.loads(out)["findings"]}
        assert {"WS-UNUSED", "0000-MAIN-EXIT"} <= symbols

    def test_explicit_flag_wins(self, capsys, prog) -> None:
        _, out, _ = _run(
            capsys, str(prog), "--format", "text", "--min-severity", "info"
        )
        assert "0000-MAIN-EXIT" in out


class TestRuleSelection:
    def test_disable(self, capsys, prog) -> None:
        _, out, _ = _run(capsys, str(prog), "--disable", "unused-variables")
        report = json.loads(out)
        assert "unused-variables" not in report["rules_run"]
        assert all(f["rule"] != "unused-variables" for f in report["findings"])

    def test_severity_override(self, capsys, prog) -> None:
        code, out, _ = _run(
            capsys,
            str(prog),
            "--severity",
            "unused-variables/WORKING-STORAGE=error",
            "--fail-on",
            "error",
        )
        assert code == 3
        [unused] = [
            f for f in json.loads(out)["findings"] if f["symbol"] == "WS-UNUSED"
        ]
        assert unused["severity"] == "error"

    def test_bad_severity_override_exits_2(self, capsys, prog) -> None:
        code, _, err = _run(capsys, str(prog), "--severity", "dead-code=fatal")
        assert code == 2 and "RULE=LEVEL" in err


class TestBaselineFlags:
    def test_write_then_use(self, capsys, prog, tmp_path) -> None:
        baseline = tmp_path / "lint-baseline.json"
        code, _, err = _run(
            capsys, str(prog), "--write-baseline", str(baseline), "--fail-on", "warning"
        )
        assert code == 0  # recording is not failing
        assert "wrote 2 finding(s)" in err
        assert json.loads(baseline.read_text())["version"] == 1

        prog.write_text(
            PROG.replace(
                "       01  WS-UNUSED",
                "       01  WS-NEW  PIC X.\n       01  WS-UNUSED",
            )
        )
        code, out, _ = _run(
            capsys, str(prog), "--baseline", str(baseline), "--fail-on", "warning"
        )
        report = json.loads(out)
        assert [f["symbol"] for f in report["findings"]] == ["WS-NEW"]
        assert report["summary"]["baselined"] == 2
        assert code == 3

    def test_missing_baseline_exits_1(self, capsys, prog, tmp_path) -> None:
        code, _, err = _run(capsys, str(prog), "--baseline", str(tmp_path / "no.json"))
        assert code == 1 and "--write-baseline" in err

    def test_multi_file_write_and_summary(self, capsys, prog, tmp_path) -> None:
        other = tmp_path / "OTHER.cbl"
        other.write_text(PROG.replace("PROG.", "OTHER."))
        baseline = tmp_path / "b.json"
        _run(capsys, str(prog), str(other), "--write-baseline", str(baseline))
        files = {e["file"] for e in json.loads(baseline.read_text())["findings"]}
        assert files == {"PROG.cbl", "OTHER.cbl"}
        _, out, _ = _run(
            capsys,
            str(prog),
            str(other),
            "--baseline",
            str(baseline),
            "--format",
            "text",
            "--workers",
            "1",
        )
        assert out.strip().endswith("in baseline")


class TestSuppressionFromTheCli:
    def test_inline_comment(self, capsys, prog) -> None:
        prog.write_text(
            PROG.replace(
                "       01  WS-UNUSED   PIC X.",
                "      * cobol-lint: disable-next-line=unused-variables\n"
                "       01  WS-UNUSED   PIC X.",
            )
        )
        _, out, _ = _run(capsys, str(prog), "--format", "text")
        assert "WS-UNUSED" not in out
        assert "1 suppressed" in out


class TestManyFiles:
    def test_exclude(self, capsys, prog, tmp_path) -> None:
        skip = tmp_path / "skip"
        skip.mkdir()
        (skip / "X.cbl").write_text(PROG)
        _, out, err = _run(
            capsys,
            "--glob",
            str(tmp_path / "**" / "*.cbl"),
            "--exclude",
            str(skip),
            "--workers",
            "1",
        )
        assert [f["source_file"] for f in json.loads(out)["files"]] == [str(prog)]
        assert "left out by exclude" in err

    def test_workers_give_the_same_report(self, capsys, prog, tmp_path) -> None:
        other = tmp_path / "OTHER.cbl"
        other.write_text(PROG.replace("PROG.", "OTHER."))
        _, serial, _ = _run(capsys, str(prog), str(other), "--workers", "1")
        _, parallel, _ = _run(capsys, str(prog), str(other), "--workers", "2")
        assert json.loads(serial) == json.loads(parallel)


class TestCopybooks:
    def test_dfhaid_comes_from_the_stand_in(self, capsys, tmp_path) -> None:
        src = tmp_path / "ONLINE.cbl"
        src.write_text(ONLINE)
        code, out, _ = _run(capsys, str(src), "--copybook-path", str(tmp_path))
        assert code == 0
        report = json.loads(out)
        assert not any("DFHAID" in c for c in report["caveats"])
        # Its fields are known, so DFHPF3 is an IBM copybook item: info at most.
        assert all(f["severity"] == "info" for f in report["findings"])

    def test_strict_copybooks_does_not_use_them_for_a_missing_member(
        self, capsys, tmp_path
    ) -> None:
        src = tmp_path / "ONLINE.cbl"
        src.write_text(ONLINE.replace("COPY DFHAID.", "COPY NOSUCH."))
        code, _, err = _run(
            capsys, str(src), "--copybook-path", str(tmp_path), "--strict-copybooks"
        )
        assert code == 1 and "NOSUCH" in err


class TestConfigFile:
    def test_lint_section_keys(self, capsys, prog, tmp_path, monkeypatch) -> None:
        (tmp_path / "cobol.yml").write_text(
            "version: 1\n"
            "lint:\n"
            "  disable: [dead-code]\n"
            "  severity:\n"
            "    unused-variables: error\n"
            "  baseline: none.json\n"
        )
        (tmp_path / "none.json").write_text('{"version": 1, "findings": []}')
        monkeypatch.chdir(tmp_path)
        code = 0
        with patch(
            "sys.argv", ["cobol-parser", "lint", str(prog), "--fail-on", "error"]
        ):
            try:
                main()
            except SystemExit as exc:
                code = int(exc.code or 0)
        report = json.loads(capsys.readouterr().out)
        assert code == 3
        assert "dead-code" not in report["rules_run"]
        assert {f["severity"] for f in report["findings"]} == {"error"}

    def test_unknown_rule_in_severity_is_rejected(self, tmp_path) -> None:
        from cobolparser.config import ConfigError, load_project_config

        path = tmp_path / "cobol.yml"
        path.write_text("version: 1\nlint:\n  severity:\n    nosuch: info\n")
        with pytest.raises(ConfigError):
            load_project_config(path=path)
