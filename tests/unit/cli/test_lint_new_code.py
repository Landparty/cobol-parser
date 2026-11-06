"""``lint --new-code-since`` / ``--scope`` (Sonar-style new-code gate) and
``--summary-file``."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from cobolparser.analysis.lint import LintFinding, LintReport
from cobolparser.cli._new_code import (
    NewCode,
    apply_new_code,
    every_rule_new,
    parse_scopes,
    parse_unified_diff,
    scope_of,
)
from cobolparser.cli.parse import main
from cobolparser.config import ConfigError, load_project_config
from cobolparser.models.ast_base import SourceLocation

BASE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-OLD-UNUSED   PIC X(10).
       01 WS-A            PIC 9(5).
       01 WS-SHORT        PIC 9(2).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 12345 TO WS-A
           DISPLAY WS-A
           DISPLAY WS-SHORT
           STOP RUN.
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

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


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


def _run(*argv: str) -> int:
    with patch("sys.argv", ["cobol-parser", "lint", *argv]):
        try:
            main()
        except SystemExit as exc:
            return int(exc.code or 0)
    return 0


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    """A repo whose ``feature`` branch adds one unused item and one
    truncating MOVE to a program that already had an unused item."""
    (tmp_path / "src").mkdir()
    (tmp_path / "cpy").mkdir()
    (tmp_path / "src" / "PAY.cbl").write_text(BASE)
    (tmp_path / "src" / "OTHER.cbl").write_text(BASE.replace("PAY.", "OTHER."))
    (tmp_path / "src" / "USESCUST.cbl").write_text(USES_CUST)
    (tmp_path / "cpy" / "CUST.cpy").write_text(CUST)
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "checkout", "-qb", "feature")
    changed = BASE.replace(
        "       01 WS-SHORT        PIC 9(2).\n",
        "       01 WS-SHORT        PIC 9(2).\n       01 WS-NEW-UNUSED   PIC X(4).\n",
    ).replace(
        "           DISPLAY WS-SHORT\n",
        "           MOVE WS-A TO WS-SHORT\n           DISPLAY WS-SHORT\n",
    )
    (tmp_path / "src" / "PAY.cbl").write_text(changed)
    _git(tmp_path, "commit", "-qam", "feature")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _json(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def _symbols(document: dict) -> set[tuple[str, str]]:
    return {
        (f["rule"], f["symbol"] or f["message"])
        for entry in document["files"]
        for f in entry["findings"]
    }


@needs_git
class TestNewCodeSince:
    def test_only_findings_on_new_lines(self, repo: Path, capsys) -> None:
        assert _run("--new-code-since", "main") == 0
        document = _json(capsys)
        rules = sorted(f["rule"] for e in document["files"] for f in e["findings"])
        assert rules == ["truncation", "unused-variables"]
        assert "WS-OLD-UNUSED" not in json.dumps(document["files"])
        assert document["summary"]["outside_new_code"] == 1
        assert document["new_code"]["ref"] == "main"
        assert document["new_code"]["default_scope"] == "new"
        # Every rule on new code: only the changed program is linted.
        assert [e["source_file"] for e in document["files"]] == ["src/PAY.cbl"]

    def test_rule_scoped_all_reports_everywhere(self, repo: Path, capsys) -> None:
        assert _run("--new-code-since", "main", "--scope", "unused-variables=all") == 0
        document = _json(capsys)
        text = json.dumps(document["files"])
        assert "WS-OLD-UNUSED" in text and "WS-NEW-UNUSED" in text
        # A rule on the whole codebase: every program is linted.
        assert {e["source_file"] for e in document["files"]} == {
            "src/OTHER.cbl",
            "src/PAY.cbl",
            "src/USESCUST.cbl",
        }
        assert document["new_code"]["rule_scopes"] == {"unused-variables": "all"}

    def test_default_all_with_a_rule_on_new_code(self, repo: Path, capsys) -> None:
        argv = ("--new-code-since", "main", "--scope", "all")
        assert _run(*argv, "--scope", "unused-variables=new", "src/PAY.cbl") == 0
        text = json.dumps(_json(capsys)["files"])
        assert "WS-NEW-UNUSED" in text and "WS-OLD-UNUSED" not in text

    def test_rule_kind_selector(self) -> None:
        finding = LintFinding(rule="io-sequence", severity="error", message="m")
        finding.kind = "FILE_LEFT_OPEN"
        per_rule = {"io-sequence": "new", "io-sequence/FILE_LEFT_OPEN": "all"}
        assert scope_of(finding, "new", per_rule) == "all"
        finding.kind = "READ_BEFORE_OPEN"
        assert scope_of(finding, "all", per_rule) == "new"

    def test_fail_on_only_counts_new_code(self, repo: Path, capsys) -> None:
        argv = ("--new-code-since", "main", "--rule", "unused-variables")
        assert _run(*argv, "--fail-on", "warning", "src/OTHER.cbl") == 0
        assert _run(*argv, "--fail-on", "warning", "src/PAY.cbl") == 3

    def test_text_summary_counts_what_was_left_out(self, repo: Path, capsys) -> None:
        _run("--new-code-since", "main", "--format", "text")
        assert "1 outside new code" in capsys.readouterr().out

    def test_untracked_program_is_all_new(self, repo: Path, capsys) -> None:
        (repo / "src" / "NEWPROG.cbl").write_text(BASE.replace("PAY.", "NEWPROG."))
        _run("--new-code-since", "main", "--rule", "unused-variables")
        document = _json(capsys)
        new = next(
            e for e in document["files"] if e["source_file"].endswith("NEW" "PROG.cbl")
        )
        assert {f["symbol"] for f in new["findings"]} == {"WS-OLD-UNUSED"}

    def test_copybook_change_lints_its_programs(self, repo: Path, capsys) -> None:
        (repo / "cpy" / "CUST.cpy").write_text(
            CUST + "           05  CUST-SPARE  PIC X(3).\n"
        )
        _git(repo, "commit", "-qam", "copybook")
        argv = ("--new-code-since", "main", "--copybook-path", "cpy")
        _run(*argv, "--rule", "unused-variables")
        document = _json(capsys)
        uses = next(e for e in document["files"] if "USESCUST" in e["source_file"])
        findings = uses["findings"]
        assert [f["symbol"] for f in findings] == ["CUST-SPARE"]
        assert findings[0]["origin"]["file"].endswith("CUST.cpy")

    def test_nothing_changed(self, repo: Path, capsys) -> None:
        _git(repo, "checkout", "-q", "main")
        assert _run("--new-code-since", "main", "--format", "text") == 0
        assert "nothing to lint" in capsys.readouterr().err

    def test_unknown_ref_exits_one(self, repo: Path, capsys) -> None:
        assert _run("--new-code-since", "nope") == 1
        assert "fetch-depth: 0" in capsys.readouterr().err

    def test_bad_scope_exits_two(self, repo: Path, capsys) -> None:
        assert _run("--new-code-since", "main", "--scope", "everything") == 2
        assert _run("--new-code-since", "main", "--scope", "no-such-rule=all") == 2

    def test_cobol_yml_scope(self, repo: Path, capsys) -> None:
        (repo / "cobol.yml").write_text(
            "version: 1\nlint:\n  scope:\n    default: new\n"
            "    unused-variables: all\n"
        )
        _run("--new-code-since", "main", "src/PAY.cbl")
        text = json.dumps(_json(capsys)["files"])
        assert "WS-OLD-UNUSED" in text

    def test_scope_without_new_code_changes_nothing(self, repo: Path, capsys) -> None:
        _run("src/PAY.cbl", "src/OTHER.cbl", "--scope", "new")
        assert "WS-OLD-UNUSED" in capsys.readouterr().out


@needs_git
class TestSummaryFile:
    def test_markdown_summary(self, repo: Path, capsys) -> None:
        summary = repo / "summary.md"
        summary.write_text("before\n")
        _run(
            "--new-code-since",
            "main",
            "--format",
            "github",
            "--summary-file",
            str(summary),
        )
        text = summary.read_text()
        assert text.startswith("before\n## COBOL lint")
        assert "New code since `main`" in text
        assert "**2 finding(s)** in 1 file(s)" in text
        assert "1 outside new code" in text
        assert "| `truncation` | 0 | 1 | 0 |" in text
        assert "WS-NEW-UNUSED" in text

    def test_single_file_and_clean(self, tmp_path: Path) -> None:
        program = tmp_path / "C.cbl"
        program.write_text(
            "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. C.\n"
            "       PROCEDURE DIVISION.\n           GOBACK.\n"
        )
        summary = tmp_path / "s.md"
        _run(str(program), "--format", "text", "--summary-file", str(summary))
        assert "No findings in 1 file(s)" in summary.read_text()

    def test_long_list_is_capped(self, repo: Path, capsys, monkeypatch) -> None:
        monkeypatch.setattr("cobolparser.cli.parse._SUMMARY_FINDING_LIMIT", 1)
        summary = repo / "s.md"
        _run("src/PAY.cbl", "src/OTHER.cbl", "--summary-file", str(summary))
        assert "more (run with" in summary.read_text()

    def test_unwritable_summary_warns(self, repo: Path, capsys) -> None:
        _run(
            "src/PAY.cbl", "src/OTHER.cbl", "--summary-file", str(repo / "no" / "s.md")
        )
        assert "could not write --summary-file" in capsys.readouterr().err


class TestUnits:
    def test_parse_unified_diff(self, tmp_path: Path) -> None:
        diff = (
            "diff --git a/a.cbl b/a.cbl\n--- a/a.cbl\n+++ b/a.cbl\n"
            "@@ -3 +3,2 @@\n-x\n+y\n+z\n@@ -9,2 +10,0 @@\n-gone\n-gone\n"
            "diff --git a/n.cbl b/n.cbl\nnew file mode 100644\n--- /dev/null\n"
            "+++ b/n.cbl\n@@ -0,0 +1 @@\n+new\n"
            "diff --git a/d.cbl b/d.cbl\n--- a/d.cbl\n+++ /dev/null\n@@ -1 +0,0 @@\n"
            'diff --git "a/q\\"x.cbl" "b/q\\"x.cbl"\n--- "a/q\\"x.cbl"\n'
            '+++ "b/q\\"x.cbl"\t\n@@ -1 +1 @@\n'
        )
        lines, new_files = parse_unified_diff(diff, str(tmp_path))
        a = NewCode.key(str(tmp_path / "a.cbl"))
        n = NewCode.key(str(tmp_path / "n.cbl"))
        assert lines[a] == {3, 4}
        assert new_files == {n}
        assert lines[NewCode.key(str(tmp_path / 'q"x.cbl'))] == {1}
        assert NewCode.key(str(tmp_path / "d.cbl")) not in lines

    def test_contains(self, tmp_path: Path) -> None:
        code = NewCode(
            ref="r", lines={NewCode.key("a"): {2}}, new_files={NewCode.key("n")}
        )
        assert code.contains("a", 2) and not code.contains("a", 3)
        assert not code.contains("a", None)
        assert code.contains("n", None)
        assert code.changed_paths() == ["a", "n"]

    def test_apply_new_code_uses_origin_then_location(self) -> None:
        report = LintReport()
        in_copybook = LintFinding(rule="dead-code", severity="warning", message="m")
        in_copybook.origin_file, in_copybook.origin_line = "C.cpy", 4
        no_line = LintFinding(rule="dead-code", severity="warning", message="n")
        located = LintFinding(
            rule="dead-code",
            severity="warning",
            message="o",
            location=SourceLocation(line=7, column=1),
        )
        report.findings = [in_copybook, no_line, located]
        code = NewCode(
            ref="r", lines={NewCode.key("C.cpy"): {4}, NewCode.key("P.cbl"): {7}}
        )
        apply_new_code(report, "P.cbl", code, "new", {})
        assert report.findings == [in_copybook, located]
        assert report.outside_new_code == 1
        assert report.to_dict()["summary"]["outside_new_code"] == 1

    def test_parse_scopes(self) -> None:
        assert parse_scopes(None) == ("new", {})
        assert parse_scopes("all") == ("all", {})
        assert parse_scopes({"default": "all", "call-check": "new"}) == (
            "all",
            {"call-check": "new"},
        )
        assert parse_scopes(["new", "parse=all"]) == ("new", {"parse": "all"})
        with pytest.raises(ValueError):
            parse_scopes(["call-check=sometimes"])

    def test_every_rule_new(self) -> None:
        assert every_rule_new("new", {"dead-code": "new"})
        assert not every_rule_new("new", {"dead-code": "all"})
        assert not every_rule_new("all", {})

    def test_summary_absent_without_new_code(self) -> None:
        assert "outside_new_code" not in LintReport().to_dict()["summary"]


class TestConfig:
    def _load(self, tmp_path: Path, body: str):
        path = tmp_path / "cobol.yml"
        path.write_text("version: 1\nlint:\n" + body)
        return load_project_config(path)

    def test_string(self, tmp_path: Path) -> None:
        assert self._load(tmp_path, "  scope: all\n").lint.scope == ("all",)

    def test_mapping(self, tmp_path: Path) -> None:
        config = self._load(
            tmp_path, "  scope:\n    default: new\n    call-check: all\n"
        )
        assert config.lint.scope == ("new", "call-check=all")

    @pytest.mark.parametrize(
        "body",
        ["  scope: sometimes\n", "  scope:\n    bogus-rule: all\n", "  scope: [new]\n"],
    )
    def test_rejected(self, tmp_path: Path, body: str) -> None:
        with pytest.raises(ConfigError):
            self._load(tmp_path, body)

    def test_config_command_shows_it(self, tmp_path: Path, capsys, monkeypatch) -> None:
        (tmp_path / "cobol.yml").write_text("version: 1\nlint:\n  scope: all\n")
        monkeypatch.chdir(tmp_path)
        with patch("sys.argv", ["cobol-parser", "config", "--json"]):
            main()
        assert json.loads(capsys.readouterr().out)["lint"]["scope"] == ["all"]
