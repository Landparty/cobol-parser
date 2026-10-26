"""Tests for cobol.yml's effect on the CLI: the flag > config > default merge.

Covers:
- A config file found by walking up fills flags the user did not pass, for
  every bound argument (copybook paths, source format, dialect, error
  recovery, defines, seed, record encoding, lint rules)
- An explicitly passed flag ALWAYS wins, including for flags whose built-in
  default is not None -- the case a plain `is None` test cannot detect, and
  the reason `_project_config` parses argv a second time
- `--config FILE` / `--no-config` work on either side of the subcommand, and
  do not confuse the legacy "bare filename means parse" rewrite, and an
  abbreviation of either (`--no-conf`, `--conf=FILE`) on either side is an
  error rather than silently ignored
- A malformed or missing config file is a clean exit-1 error naming it,
  never a silent fallback to built-in defaults
- The `config` subcommand reports the file and only what it actually sets
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from cobolparser.cli.parse import _SUBCOMMANDS, _build_parser, main
from cobolparser.config import ConfigError

CONFIG = """\
project:
  copybook_path: [copybooks]
  source_format: fixed
  dialect: ibm-enterprise
  error_recovery: fail-fast
  seed: 42
  extensions: [.cbl]
  define:
    DEBUG: "TRUE"

data:
  charset: ebcdic
  endian: big
  record_format: variable
  record_separator: newline
  rows: 25

lint:
  rules: [dead-code]
  min_severity: warning
  fail_on: error
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "cobol.yml").write_text(CONFIG)
    (tmp_path / "copybooks").mkdir()
    (tmp_path / "PROG.cbl").write_text("       IDENTIFICATION DIVISION.\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run_capturing_args(argv: list[str], command: str):
    """Run main() with `_cmd_<command>` stubbed, and return the Namespace it
    would have been handed. Patching the module attribute works because
    `_build_parser()` resolves each `set_defaults(func=...)` when main()
    calls it, not at import time."""
    captured = {}

    def fake(args):
        captured["args"] = args

    with patch(f"cobolparser.cli.parse._cmd_{command}", fake):
        with patch("sys.argv", ["cobol-parser", *argv]):
            main()
    return captured["args"]


# -- the config fills what the user did not pass ------------------------------


def test_copybook_path_comes_from_the_config(project):
    args = run_capturing_args(["lint", "PROG.cbl"], "lint")
    assert args.copybook_path == [str(project / "copybooks")]


def test_config_found_by_walking_up_from_a_subdirectory(project, monkeypatch):
    nested = project / "src" / "deep"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    args = run_capturing_args(["lint", str(project / "PROG.cbl")], "lint")
    # Anchored to the config file, so the same libraries as from the root.
    assert args.copybook_path == [str(project / "copybooks")]


def test_parse_flags_come_from_the_config(project):
    args = run_capturing_args(["parse", "PROG.cbl"], "parse")
    assert args.source_format == "fixed"
    assert args.dialect == "ibm-enterprise"
    assert args.error_recovery == "fail-fast"
    assert args.define == ["DEBUG=TRUE"]


def test_record_encoding_defaults_come_from_the_config(project):
    args = run_capturing_args(["gen-data", "CUST.cpy"], "gen_data")
    assert args.charset == "ebcdic"
    assert args.endian == "big"
    assert args.record_format == "variable"
    assert args.record_separator == "newline"
    assert args.rows == 25
    assert args.seed == 42


def test_lint_rules_come_from_the_config(project):
    args = run_capturing_args(["lint", "PROG.cbl"], "lint")
    assert args.rules == ["dead-code"]
    assert args.min_severity == "warning"
    assert args.fail_on == "error"


def test_tree_walking_extensions_come_from_the_config(project):
    # --extension declares dest="extensions"; codebase-graph and
    # copybook-impact are the two subcommands that walk a source tree.
    args = run_capturing_args(["codebase-graph", "."], "codebase_graph")
    assert args.extensions == [".cbl"]


# -- an explicit flag always wins ---------------------------------------------


def test_explicit_copybook_path_replaces_the_config_list(project):
    # Not merged: the user asked for exactly these directories.
    args = run_capturing_args(["lint", "PROG.cbl", "--copybook-path", "/other"], "lint")
    assert args.copybook_path == ["/other"]


def test_explicit_flag_wins_even_when_it_equals_the_built_in_default(project):
    # `--charset ascii` is also the built-in default, so "did the user type
    # it?" cannot be answered by comparing against the default. This is the
    # case the second argv parse exists for.
    args = run_capturing_args(
        ["gen-data", "CUST.cpy", "--charset", "ascii"], "gen_data"
    )
    assert args.charset == "ascii"


def test_explicit_rows_wins_over_config_rows(project):
    args = run_capturing_args(["gen-data", "CUST.cpy", "--rows", "3"], "gen_data")
    assert args.rows == 3


def test_explicit_source_format_wins(project):
    args = run_capturing_args(["parse", "PROG.cbl", "--source-format", "free"], "parse")
    assert args.source_format == "free"


def test_legacy_free_form_flag_not_overridden_by_config_source_format(project):
    # --free-form and --source-format are the same setting under two
    # spellings, and _source_format_kwargs reads --source-format first.
    # Filling it from the config here would silently override the layout the
    # user stated on the command line.
    args = run_capturing_args(["parse", "PROG.cbl", "--free-form"], "parse")
    assert args.free_form is True
    assert args.source_format == "auto"


def test_explicit_min_severity_wins(project):
    args = run_capturing_args(["lint", "PROG.cbl", "--min-severity", "info"], "lint")
    assert args.min_severity == "info"


# -- --config / --no-config ---------------------------------------------------


def test_no_config_ignores_the_file(project):
    args = run_capturing_args(["lint", "PROG.cbl", "--no-config"], "lint")
    assert args.copybook_path == []
    assert args.min_severity == "info"  # the built-in default


def test_explicit_config_path_is_used_instead_of_the_search(project, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "cobol.yml").write_text("project:\n  copybook_path: [elsewhere]\n")
    args = run_capturing_args(
        ["--config", str(other / "cobol.yml"), "lint", "PROG.cbl"], "lint"
    )
    assert args.copybook_path == [str(other / "elsewhere")]


def test_config_flag_works_after_the_subcommand_too(project, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "cobol.yml").write_text("project:\n  copybook_path: [elsewhere]\n")
    args = run_capturing_args(
        ["lint", "PROG.cbl", f"--config={other / 'cobol.yml'}"], "lint"
    )
    assert args.copybook_path == [str(other / "elsewhere")]


def test_config_path_is_not_mistaken_for_a_source_file(project, tmp_path):
    # main() rewrites `cobol-parser FILE` as `cobol-parser parse FILE` when
    # the first positional is not a subcommand. If --config's argument were
    # still in argv at that point, it would be taken for the source file.
    other = tmp_path / "cobol.yml"
    other.write_text("project:\n  dialect: ibm-enterprise\n")
    args = run_capturing_args(["--config", str(other), "PROG.cbl"], "parse")
    assert args.file == "PROG.cbl"


def test_config_and_no_config_together_is_an_error(project):
    with patch(
        "sys.argv", ["cobol-parser", "--no-config", "--config", "x", "lint", "P"]
    ):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1


def test_config_without_a_path_is_an_error(project):
    with patch("sys.argv", ["cobol-parser", "lint", "PROG.cbl", "--config"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1


@pytest.mark.parametrize(
    "spelling",
    [
        ["--no-conf"],
        ["--no"],
        ["--conf=other.yml"],
        ["--conf", "other.yml"],
        ["--co"],
    ],
)
@pytest.mark.parametrize("side", ["before", "after"])
def test_abbreviated_config_flags_are_rejected(project, capsys, spelling, side):
    # Only the exact spellings are stripped by extract_config_flags(). An
    # abbreviation reaching argparse was either swallowed by the top-level
    # parser or, after the subcommand, prefix-matched to one of its own
    # options -- either way the discovered cobol.yml stayed in force while
    # the user believed they had switched it off or replaced it (#323).
    argv = (
        [*spelling, "lint", "PROG.cbl"]
        if side == "before"
        else ["lint", "PROG.cbl", *spelling]
    )
    with patch("cobolparser.cli.parse._cmd_lint") as cmd:
        with patch("sys.argv", ["cobol-parser", *argv]):
            with pytest.raises(SystemExit) as exc:
                main()
    assert exc.value.code == 1
    assert "spelled out in full" in capsys.readouterr().err
    cmd.assert_not_called()


def test_rejected_before_argparse_can_prefix_match_it():
    # Rejected on the raw argv, so the answer does not depend on which
    # options the subcommand happens to have: once lint gains, say,
    # --no-debug-lines, argparse alone would read `--no` as that option.
    from cobolparser.cli import _project_config

    with pytest.raises(ConfigError):
        _project_config.extract_config_flags(["lint", "P.cbl", "--no"])


@pytest.mark.parametrize(
    "arg", ["--copybook-path", "--compact", "--no-debug-lines", "--conf-x", "-c"]
)
def test_options_that_cannot_mean_config_pass_through(arg):
    from cobolparser.cli import _project_config

    remaining, path, disabled = _project_config.extract_config_flags(["lint", arg])
    assert remaining == ["lint", arg]
    assert path is None and not disabled


def test_missing_explicit_config_file_is_a_clean_error(project, capsys):
    with patch("sys.argv", ["cobol-parser", "--config", "nope.yml", "lint", "P"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    assert "config file not found" in capsys.readouterr().err


def test_malformed_config_fails_closed_naming_the_file(project, capsys):
    # Never a silent fallback to built-in defaults: the user would be
    # running with a config they believe is in effect and isn't.
    (project / "cobol.yml").write_text("project:\n  copybook-path: [x]\n")
    with patch("sys.argv", ["cobol-parser", "lint", "PROG.cbl"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "cobol.yml" in err and "copybook-path" in err


# -- the config subcommand ----------------------------------------------------


def test_config_is_a_registered_subcommand():
    # Without this, main()'s legacy shim mistakes "config" for a filename
    # and rewrites the call as `parse config`.
    assert "config" in _SUBCOMMANDS
    assert _build_parser().parse_args(["config"]).func is not None


def test_config_subcommand_reports_the_file_and_its_settings(project, capsys):
    with patch("sys.argv", ["cobol-parser", "config"]):
        main()
    out = capsys.readouterr().out
    assert str(project / "cobol.yml") in out
    assert "charset: ebcdic" in out
    assert str(project / "copybooks") in out


def test_config_subcommand_json_omits_unset_keys(project, capsys):
    with patch("sys.argv", ["cobol-parser", "config", "--json"]):
        main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["config_file"] == str(project / "cobol.yml")
    assert payload["data"]["charset"] == "ebcdic"
    # callee_path is not in the fixture, so it is absent rather than shown
    # at a built-in default -- what is printed is exactly what the file changes.
    assert "callee_path" not in payload["project"]


def test_config_subcommand_says_so_when_no_file_exists(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["cobol-parser", "config"]):
        main()
    assert "No cobol.yml found" in capsys.readouterr().out


def test_config_subcommand_under_no_config_reports_nothing_in_effect(project, capsys):
    with patch("sys.argv", ["cobol-parser", "config", "--no-config"]):
        main()
    assert "No cobol.yml found" in capsys.readouterr().out


# -- a path entry that is not a directory is reported (#550) -------------------


@pytest.fixture
def typo_project(tmp_path, monkeypatch):
    (tmp_path / "cobol.yml").write_text(
        "project:\n  copybook_path: [copybooks, copybokos]\n"
    )
    (tmp_path / "copybooks").mkdir()
    (tmp_path / "PROG.cbl").write_text("       IDENTIFICATION DIVISION.\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_config_subcommand_marks_a_missing_directory(typo_project, capsys):
    with patch("sys.argv", ["cobol-parser", "config"]):
        main()
    out = capsys.readouterr().out
    assert f"{typo_project / 'copybokos'}  (not an existing directory)" in out
    assert f"{typo_project / 'copybooks'}  (not" not in out


def test_config_subcommand_json_lists_missing_directories(typo_project, capsys):
    with patch("sys.argv", ["cobol-parser", "config", "--json"]):
        main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["missing_directories"] == [str(typo_project / "copybokos")]


def test_config_json_has_no_missing_key_when_all_exist(project, capsys):
    with patch("sys.argv", ["cobol-parser", "config", "--json"]):
        main()
    assert "missing_directories" not in json.loads(capsys.readouterr().out)


def test_a_parsing_command_warns_once_per_missing_directory(typo_project, capsys):
    run_capturing_args(["lint", "PROG.cbl"], "lint")
    err = capsys.readouterr().err
    assert err.count("is not an existing directory") == 1
    assert str(typo_project / "copybokos") in err


def test_no_warning_when_the_flag_overrides_the_config(typo_project, capsys):
    run_capturing_args(["lint", "PROG.cbl", "--copybook-path", "copybooks"], "lint")
    assert "not an existing directory" not in capsys.readouterr().err
