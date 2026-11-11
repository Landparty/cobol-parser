"""``lint`` for CI: the line-length rule, many files in one run,
``--changed-since``, ``--format github`` and the pre-commit hooks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from cobolparser.analysis.lint import (
    ALL_RULES,
    LINE_LENGTH_RULE,
    LintAnalyzer,
    LintReport,
    add_line_length_findings,
    line_length_findings,
)
from cobolparser.cli._changed_files import (
    ChangedFilesError,
    changed_files,
    program_candidates,
    select_changed_programs,
)
from cobolparser.cli.commands.lint import _github_command
from cobolparser.cli.parse import main

CLEAN = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CLEAN.
       PROCEDURE DIVISION.
           GOBACK.
"""

USES_CUST = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. USESCUST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY CUST.
       PROCEDURE DIVISION.
           DISPLAY CUST-ID
           GOBACK.
"""

CUST = """\
       01  CUST-REC.
           05  CUST-ID     PIC 9(5).
"""


def _fixed(code: str, tail: str = "") -> str:
    """One fixed-format line: 7 blank columns, *code* from column 8 padded
    to column 72, then *tail* from column 73."""
    return (" " * 7 + code).ljust(72) + tail if tail else " " * 7 + code


def _run(*argv: str) -> None:
    with patch("sys.argv", ["cobol-parser", "lint", *argv]):
        main()


def _exit_code(*argv: str) -> int:
    try:
        _run(*argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


# -- the rule ----------------------------------------------------------------


class TestLineLengthFindings:
    def test_past_column_80_is_an_error_at_column_81(self) -> None:
        text = _fixed("DISPLAY 'X'.", "SEQ00001EXTRA") + "\n"
        [finding] = line_length_findings("P.cbl", text)
        assert finding.rule == LINE_LENGTH_RULE
        assert finding.severity == "error"
        assert finding.kind == "LINE_PAST_COLUMN_80"
        assert (finding.origin_file, finding.origin_line) == ("P.cbl", 1)
        assert finding.origin_column == 81
        assert "85 columns" in finding.message

    def test_comment_line_past_80_is_only_a_warning(self) -> None:
        text = "      *" + "X" * 80 + "\n"
        [finding] = line_length_findings("P.cbl", text)
        assert finding.severity == "warning"
        assert "comment text only" in finding.message

    def test_word_cut_at_column_72_is_a_warning(self) -> None:
        code = "05  CUST-ADDRESS".ljust(60) + "PIC X(30)"
        line = (" " * 7 + code).ljust(72)[:72] + "IOUS."
        # Column 72 holds ')' and column 73 'I': one word across the edge.
        assert line[71] != " " and line[72] != " "
        [finding] = line_length_findings("C.cpy", line + "\n")
        assert finding.severity == "warning"
        assert finding.kind == "TEXT_PAST_COLUMN_72"
        assert finding.origin_column == 73

    def test_clean_identification_area_is_not_flagged(self) -> None:
        text = "\n".join(_fixed(f"DISPLAY 'LINE {n}'.", f"{n:08d}") for n in range(5))
        assert line_length_findings("P.cbl", text) == []

    def test_lone_period_past_72_is_not_flagged(self) -> None:
        line = (" " * 7 + "MOVE A TO B").rjust(72, " ")
        line = (" " * 7 + ("MOVE A TO " + "B" * 60)[:65]) + "."
        assert len(line) == 73
        assert line_length_findings("P.cbl", line + "\n") == []

    def test_full_numeric_stamp_abutting_column_72_is_not_flagged(self) -> None:
        line = " " * 7 + "MOVE A TO B".rjust(65, "X")
        assert len(line) == 72
        assert line_length_findings("P.cbl", line + "00001000\n") == []

    def test_file_stamp_convention_is_learned_from_unambiguous_lines(self) -> None:
        # NIST style: an alphanumeric id in 73-80. Three lines with column 72
        # blank prove the convention; the one abutting column 72 is a stamp.
        lines = [_fixed(f"DISPLAY {n}.", "IX2094.2") for n in range(3)]
        lines.append((" " * 7 + "MOVE A TO B".rjust(65, "X")) + "IX2094.2")
        assert line_length_findings("P.cbl", "\n".join(lines)) == []

    def test_unproven_alphanumeric_tail_is_flagged(self) -> None:
        line = (" " * 7 + "MOVE A TO B".rjust(65, "X")) + "IX2094.2"
        [finding] = line_length_findings("P.cbl", line + "\n")
        assert finding.kind == "TEXT_PAST_COLUMN_72"

    def test_cut_inside_inline_comment_is_not_flagged(self) -> None:
        line = (" " * 7 + "01  A PIC X. *> " + "C" * 60)[:80]
        assert line_length_findings("P.cbl", line + "\n") == []

    def test_free_format_lines_are_skipped(self) -> None:
        text = _fixed("DISPLAY 'X'.", "SEQ00001EXTRA") + "\n"
        assert line_length_findings("P.cbl", text, free_lines=[True]) == []

    def test_tabs_are_expanded_before_counting(self) -> None:
        line = "\t" * 10 + "Y" * 5  # 85 columns once expanded
        [finding] = line_length_findings("P.cbl", line + "\n")
        assert finding.kind == "LINE_PAST_COLUMN_80"


class TestAddLineLengthFindings:
    def test_free_format_program_is_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "FREE.cbl"
        path.write_text(
            "IDENTIFICATION DIVISION.\nPROGRAM-ID. FREE.\nPROCEDURE DIVISION.\n"
            "    DISPLAY '" + "X" * 90 + "'.\n"
        )
        report = add_line_length_findings(LintReport(), str(path), None, False)
        assert report.findings == []
        assert report.rules_run == [LINE_LENGTH_RULE]

    def test_copybook_finding_names_the_copybook(self, tmp_path: Path) -> None:
        main_file = tmp_path / "P.cbl"
        main_file.write_text(CLEAN)
        copybook = tmp_path / "C.cpy"
        copybook.write_text(_fixed("01  A PIC X.", "SEQ00001EXTRA") + "\n")
        source_map = {1: (str(main_file), 1), 5: (str(copybook), 1)}
        report = add_line_length_findings(
            LintReport(), str(main_file), source_map, True
        )
        [finding] = report.findings
        assert finding.origin_file == str(copybook)
        assert finding.origin_line == 1
        assert finding.location is not None and finding.location.line == 5

    def test_unreadable_copybook_is_skipped(self, tmp_path: Path) -> None:
        main_file = tmp_path / "P.cbl"
        main_file.write_text(CLEAN)
        report = add_line_length_findings(
            LintReport(), str(main_file), None, True, [str(tmp_path / "GONE.cpy")]
        )
        assert report.findings == []


class TestRuleSelection:
    def test_line_length_is_a_selectable_rule(self) -> None:
        assert LINE_LENGTH_RULE in ALL_RULES

    def test_analyzer_accepts_but_does_not_run_it(self) -> None:
        assert LintAnalyzer([LINE_LENGTH_RULE]).rules == ()

    def test_only_line_length(self, tmp_path: Path, capsys) -> None:
        path = tmp_path / "P.cbl"
        path.write_text(CLEAN + _fixed("*> x", "SEQ00001" + "Z" * 10) + "\n")
        _run(str(path), "--rule", "line-length", "--compact")
        data = json.loads(capsys.readouterr().out)
        assert data["rules_run"] == ["line-length"]
        assert {f["rule"] for f in data["findings"]} == {"line-length"}

    def test_other_rule_alone_skips_it(self, tmp_path: Path, capsys) -> None:
        path = tmp_path / "P.cbl"
        path.write_text(CLEAN + _fixed("*> x", "SEQ00001" + "Z" * 10) + "\n")
        _run(str(path), "--rule", "dead-code", "--compact")
        data = json.loads(capsys.readouterr().out)
        assert "line-length" not in data["rules_run"]

    def test_cobol_yml_accepts_it(self, tmp_path: Path) -> None:
        from cobolparser.config import load_project_config

        (tmp_path / "cobol.yml").write_text("lint:\n  rules: [line-length]\n")
        config = load_project_config(path=tmp_path / "cobol.yml")
        assert config.lint.rules == ("line-length",)


# -- many files --------------------------------------------------------------


@pytest.fixture
def estate(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "copybooks").mkdir()
    (tmp_path / "src" / "CLEAN.cbl").write_text(CLEAN)
    (tmp_path / "src" / "USESCUST.cbl").write_text(USES_CUST)
    (tmp_path / "copybooks" / "CUST.cpy").write_text(CUST)
    return tmp_path


class TestManyFiles:
    def test_json_shape(self, estate: Path, capsys) -> None:
        _run(
            str(estate / "src" / "CLEAN.cbl"),
            str(estate / "src" / "USESCUST.cbl"),
            "--copybook-path",
            str(estate / "copybooks"),
            "--compact",
        )
        data = json.loads(capsys.readouterr().out)
        assert [f["program_id"] for f in data["files"]] == ["CLEAN", "USESCUST"]
        assert data["failures"] == []
        assert data["summary"]["file_count"] == 2
        assert data["summary"]["linted"] == 2
        assert "changed_since" not in data

    def test_glob(self, estate: Path, capsys) -> None:
        _run("--glob", str(estate / "src" / "*.cbl"), "--compact")
        data = json.loads(capsys.readouterr().out)
        assert data["summary"]["linted"] == 2

    def test_files_from(self, estate: Path, capsys) -> None:
        listing = estate / "list.txt"
        listing.write_text(f"# programs\n{estate / 'src' / 'CLEAN.cbl'}\n")
        _run("--files-from", str(listing), "--compact")
        data = json.loads(capsys.readouterr().out)
        assert [f["program_id"] for f in data["files"]] == ["CLEAN"]

    def test_unreadable_file_is_reported_and_exits_two(
        self, estate: Path, capsys
    ) -> None:
        code = _exit_code(
            str(estate / "src" / "CLEAN.cbl"),
            str(estate / "src" / "MISSING.cbl"),
            "--compact",
        )
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        # 2, as scan / batch exit when one file of a multi-file run failed.
        assert code == 2
        assert data["summary"]["linted"] == 1
        [failure] = data["failures"]
        assert failure["source_file"].endswith("MISSING.cbl")
        assert failure["error"]

    def test_failure_outranks_fail_on(self, estate: Path) -> None:
        bad = estate / "src" / "BAD.cbl"
        bad.write_text(CLEAN.replace("GOBACK.", "MOVE TO."))
        code = _exit_code(
            str(bad), str(estate / "src" / "MISSING.cbl"), "--fail-on", "error"
        )
        assert code == 2

    def test_fail_on_any_file_exits_three(self, estate: Path) -> None:
        bad = estate / "src" / "BAD.cbl"
        bad.write_text(CLEAN.replace("GOBACK.", "MOVE TO."))
        code = _exit_code(
            str(estate / "src" / "CLEAN.cbl"), str(bad), "--fail-on", "error"
        )
        assert code == 3

    def test_text_prints_one_total(self, estate: Path, capsys) -> None:
        _run("--glob", str(estate / "src" / "*.cbl"), "--format", "text")
        lines = capsys.readouterr().out.strip().splitlines()
        assert lines[-1].startswith("0 finding(s) in 2 file(s)")
        assert sum("finding(s)" in line for line in lines) == 1

    def test_text_names_a_failed_file(self, estate: Path, capsys) -> None:
        _exit_code(
            str(estate / "src" / "MISSING.cbl"), "--glob", "x", "--format", "text"
        )
        out = capsys.readouterr().out
        assert "MISSING.cbl: error [lint] could not be linted" in out
        assert "1 file(s) could not be linted" in out

    def test_sarif_is_one_log(self, estate: Path, capsys) -> None:
        bad = estate / "src" / "BAD.cbl"
        bad.write_text(CLEAN.replace("GOBACK.", "MOVE TO."))
        _exit_code(
            str(estate / "src" / "CLEAN.cbl"),
            str(bad),
            str(estate / "src" / "MISSING.cbl"),
            "--format",
            "sarif",
        )
        log = json.loads(capsys.readouterr().out)
        [run] = log["runs"]
        assert {r["ruleId"] for r in run["results"]} == {"parse"}
        notes = run["invocations"][0]["toolExecutionNotifications"]
        assert any("could not be linted" in n["message"]["text"] for n in notes)

    def test_copybook_layout_finding_reported_once(self, estate: Path, capsys) -> None:
        (estate / "copybooks" / "CUST.cpy").write_text(
            CUST + _fixed("05  CUST-X PIC X.", "SEQ00001EXTRA") + "\n"
        )
        (estate / "src" / "AGAIN.cbl").write_text(
            USES_CUST.replace("USESCUST", "AGAIN")
        )
        _run(
            "--glob",
            str(estate / "src" / "*.cbl"),
            "--copybook-path",
            str(estate / "copybooks"),
            "--rule",
            "line-length",
            "--format",
            "text",
        )
        out = capsys.readouterr().out
        assert out.count("CUST.cpy:3:81: error [line-length]") == 1

    def test_nothing_named_exits_two(self, capsys) -> None:
        assert _exit_code() == 2
        assert "needs a FILE" in capsys.readouterr().err

    def test_glob_matching_nothing_fails(self, tmp_path: Path) -> None:
        assert _exit_code("--glob", str(tmp_path / "*.cbl")) == 1

    def test_profile_is_ignored_with_a_warning(self, estate: Path, capsys) -> None:
        _run("--glob", str(estate / "src" / "*.cbl"), "--profile", "--compact")
        assert "only supported when linting one file" in capsys.readouterr().err


# -- github format -----------------------------------------------------------


class TestGithubFormat:
    def test_one_command_per_finding(self, tmp_path: Path, capsys, monkeypatch) -> None:
        monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
        path = tmp_path / "BAD.cbl"
        path.write_text(CLEAN.replace("GOBACK.", "MOVE TO."))
        _run(str(path), "--format", "github")
        lines = capsys.readouterr().out.strip().splitlines()
        assert lines[0].startswith(
            "::error file=BAD.cbl,line=4,col=12,title=cobol-lint [parse]::"
        )
        assert lines[-1].startswith("1 finding(s)")

    def test_info_is_a_notice(self) -> None:
        line = _github_command("notice", "x", file="a.cbl", line=1)
        assert line.startswith("::notice file=a.cbl,line=1::")

    def test_escaping(self) -> None:
        line = _github_command("error", "50%\nnext", file="a,b:c.cbl", title="t")
        assert line == "::error file=a%2Cb%3Ac.cbl,title=t::50%25%0Anext"

    def test_path_outside_workspace_is_kept(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path / "ws"))
        outside = str(tmp_path / "other" / "a.cbl")
        assert f"file={outside.replace(':', '%3A')}" in _github_command(
            "error", "m", file=outside
        )

    def test_no_properties(self) -> None:
        assert _github_command("warning", "m") == "::warning::m"

    def test_many_files(self, estate: Path, capsys) -> None:
        bad = estate / "src" / "BAD.cbl"
        bad.write_text(CLEAN.replace("GOBACK.", "MOVE TO."))
        _exit_code(str(bad), str(estate / "src" / "MISSING.cbl"), "--format", "github")
        out = capsys.readouterr().out
        assert "::error file=" in out and "title=cobol-lint [parse]" in out
        assert "title=lint::could not be linted" in out


# -- --changed-since ---------------------------------------------------------


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        },
    )


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture
def repo(estate: Path, monkeypatch) -> Path:
    _git(estate, "init", "-q", "-b", "base")
    _git(estate, "add", "-A")
    _git(estate, "commit", "-qm", "base")
    _git(estate, "checkout", "-qb", "feature")
    monkeypatch.chdir(estate)
    return estate


@needs_git
class TestChangedSince:
    def test_nothing_changed_is_a_clean_run(self, repo: Path, capsys) -> None:
        assert _exit_code("--changed-since", "base", "--compact") == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["files"] == []
        assert data["changed_since"]["ref"] == "base"
        assert "nothing to lint" in captured.err

    def test_changed_program_only(self, repo: Path, capsys) -> None:
        (repo / "src" / "CLEAN.cbl").write_text(CLEAN.replace("GOBACK.", "STOP RUN."))
        _run("--changed-since", "base", "--compact")
        data = json.loads(capsys.readouterr().out)
        assert [f["source_file"] for f in data["files"]] == [
            os.path.join("src", "CLEAN.cbl")
        ]

    def test_changed_copybook_pulls_in_its_programs(self, repo: Path, capsys) -> None:
        (repo / "copybooks" / "CUST.cpy").write_text(CUST + "           05  X PIC X.\n")
        _git(repo, "commit", "-qam", "copybook")
        _run("--changed-since", "base", "--copybook-path", "copybooks", "--compact")
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        programs = [f["source_file"] for f in data["files"]]
        assert programs == [os.path.join("src", "USESCUST.cbl")]
        assert data["changed_since"]["via_copybook"] == {
            os.path.join("src", "USESCUST.cbl"): ["CUST"]
        }
        assert "copies changed copybook(s) CUST" in captured.err

    def test_untracked_program_counts(self, repo: Path, capsys) -> None:
        (repo / "src" / "NEW.cbl").write_text(CLEAN.replace("CLEAN", "NEW"))
        _run("--changed-since", "base", "--compact")
        data = json.loads(capsys.readouterr().out)
        assert [f["program_id"] for f in data["files"]] == ["NEW"]

    def test_explicit_files_are_the_candidates(self, repo: Path, capsys) -> None:
        (repo / "src" / "CLEAN.cbl").write_text(CLEAN.replace("GOBACK.", "STOP RUN."))
        (repo / "src" / "USESCUST.cbl").write_text(USES_CUST + "\n")
        _run(
            os.path.join("src", "USESCUST.cbl"), "--changed-since", "base", "--compact"
        )
        data = json.loads(capsys.readouterr().out)
        assert [f["program_id"] for f in data["files"]] == ["USESCUST"]

    def test_unknown_ref_exits_one_with_a_hint(self, repo: Path, capsys) -> None:
        assert _exit_code("--changed-since", "no-such-branch") == 1
        assert "fetch-depth: 0" in capsys.readouterr().err

    def test_outside_a_repository(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
        with pytest.raises(ChangedFilesError):
            changed_files("HEAD")


class TestSelection:
    def test_nested_copybook(self, tmp_path: Path) -> None:
        cpy = tmp_path / "cpy"
        cpy.mkdir()
        (cpy / "OUTER.cpy").write_text("           COPY INNER.\n")
        (cpy / "INNER.cpy").write_text("           05 X PIC X.\n")
        program = tmp_path / "P.cbl"
        program.write_text(USES_CUST.replace("COPY CUST.", "COPY OUTER."))
        selection = select_changed_programs(
            [str(cpy / "INNER.cpy")], [str(program)], [str(cpy)]
        )
        assert selection.programs == [str(program)]
        assert selection.via_copybook[str(program)] == ["INNER"]

    @pytest.mark.parametrize("operand", ['"custrec.cpy"', '"cpy/custrec.cpy"'])
    def test_quoted_file_name_copy(self, tmp_path: Path, operand: str) -> None:
        """`COPY "custrec.cpy"` uses the changed custrec.cpy (#829)."""
        cpy = tmp_path / "cpy"
        cpy.mkdir()
        (cpy / "custrec.cpy").write_text("           05 X PIC X.\n")
        quoted = tmp_path / "QUOT.cbl"
        quoted.write_text(USES_CUST.replace("COPY CUST.", f"COPY {operand}."))
        bare = tmp_path / "BARE.cbl"
        bare.write_text(USES_CUST.replace("COPY CUST.", "COPY CUSTREC."))
        selection = select_changed_programs(
            [str(cpy / "custrec.cpy")], [str(bare), str(quoted)], [str(cpy)]
        )
        assert selection.programs == sorted([str(bare), str(quoted)])
        assert selection.via_copybook[str(quoted)] == ["CUSTREC"]

    def test_copybook_cycle_terminates(self, tmp_path: Path) -> None:
        cpy = tmp_path / "cpy"
        cpy.mkdir()
        (cpy / "A.cpy").write_text("           COPY B.\n")
        (cpy / "B.cpy").write_text("           COPY A.\n")
        program = tmp_path / "P.cbl"
        program.write_text(USES_CUST.replace("COPY CUST.", "COPY A."))
        selection = select_changed_programs(
            [str(cpy / "Z.cpy")], [str(program)], [str(cpy)]
        )
        assert selection.programs == []

    def test_cbl_in_copybook_dir_is_a_copybook(self, tmp_path: Path) -> None:
        cpy = tmp_path / "cpy"
        cpy.mkdir()
        (cpy / "CUST.cbl").write_text(CUST)
        program = tmp_path / "P.cbl"
        program.write_text(USES_CUST)
        assert program_candidates(
            [str(cpy / "CUST.cbl"), str(program)], (".cbl",), [str(cpy)]
        ) == [str(program)]
        selection = select_changed_programs(
            [str(cpy / "CUST.cbl")], [str(program)], [str(cpy)]
        )
        assert selection.programs == [str(program)]

    def test_unreadable_program_names_no_members(self, tmp_path: Path) -> None:
        selection = select_changed_programs(["X.cpy"], [str(tmp_path / "GONE.cbl")], [])
        assert selection.programs == []

    def test_extensions_any_case(self) -> None:
        assert program_candidates(["A.CBL", "B.cob", "C.cpy"], ("cbl", ".COB")) == [
            "A.CBL",
            "B.cob",
        ]


class TestPreCommitHooks:
    def test_hook_file_names_the_cli(self) -> None:
        text = (Path(__file__).parents[3] / ".pre-commit-hooks.yaml").read_text()
        assert "- id: cobol-lint\n" in text
        assert "- id: cobol-lint-changed\n" in text
        assert "entry: cobol-parser lint --format text --changed-since HEAD" in text
