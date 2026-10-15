"""Debugging lines (``D`` in column 7) and ``WITH DEBUGGING MODE`` (#334).

IBM Enterprise COBOL compiles debugging lines as code under
``SOURCE-COMPUTER ... WITH DEBUGGING MODE``. The parser keeps dropping them
as comments by default, but:

- a program that declares the clause while they are dropped gets a warning
  saying how many lines were dropped and how to keep them, instead of an
  AST that silently lacks statements the compiled program runs;
- ``debug_lines=True`` (``parse_cobol``, ``CobolParser``, the CLI's
  ``--debug-lines``, cobol.yml ``project.debug_lines``) compiles them as
  code.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cobolparser import CobolParser, parse_cobol
from cobolparser.analysis.unused_variables import UnusedVariableAnalyzer
from cobolparser.cli.parse import main
from cobolparser.config import ConfigError
from cobolparser.config.project import build_config
from cobolparser.lexer import TokenType, _tokenize_source
from cobolparser.preprocess.copybook_expander import parse_cobol_with_expansion
from cobolparser.preprocess.source_format import debug_line_numbers
from cobolparser.scan import ScanOptions, scan_files

DEBUG_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DBG.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. IBM-370 WITH DEBUGGING MODE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TRACE  PIC X(10).
       01  WS-CNT    PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           DISPLAY 'START'
      D    DISPLAY 'DEBUG ' WS-TRACE
      D    ADD 1 TO WS-CNT
           STOP RUN.
"""

COMPDIR = Path(__file__).parent.parent / "samples" / "enterprise" / "COMPDIR.cbl"


def _statement_types(result) -> list[str]:
    return [type(s).__name__ for s in result.ast.get_all_statements()]


def _debug_warnings(result) -> list[str]:
    return [w for w in result.warnings if "DEBUGGING MODE" in w]


# -- the default: dropped, but no longer silently -----------------------------


def test_default_drops_debug_lines_and_warns() -> None:
    result = parse_cobol(DEBUG_PROGRAM)
    assert result.errors == []
    assert _statement_types(result) == ["DisplayStatement", "StopStatement"]
    (warning,) = _debug_warnings(result)
    assert warning.startswith("Line 13: ")
    assert "2 debugging line(s)" in warning
    assert "debug_lines=True" in warning
    assert "--debug-lines" in warning


def test_no_warning_without_the_clause() -> None:
    # Without WITH DEBUGGING MODE the compiler treats D lines as comments
    # too, so dropping them loses nothing.
    source = DEBUG_PROGRAM.replace(" WITH DEBUGGING MODE", "")
    result = parse_cobol(source)
    assert _statement_types(result) == ["DisplayStatement", "StopStatement"]
    assert _debug_warnings(result) == []


def test_no_warning_when_the_clause_has_no_debug_lines() -> None:
    source = "".join(
        line
        for line in DEBUG_PROGRAM.splitlines(keepends=True)
        if not line.startswith("      D")
    )
    result = parse_cobol(source)
    assert result.errors == []
    assert _debug_warnings(result) == []


def test_reused_parser_does_not_carry_the_warning_over() -> None:
    parser = CobolParser()
    assert _debug_warnings(parser.parse(DEBUG_PROGRAM))
    clean = DEBUG_PROGRAM.replace(" WITH DEBUGGING MODE", "")
    assert _debug_warnings(parser.parse(clean)) == []


def test_compdir_sample_warns_by_default() -> None:
    result = parse_cobol(COMPDIR.read_text(encoding="utf-8"))
    (warning,) = _debug_warnings(result)
    assert "2 debugging line(s)" in warning


# -- debug_lines=True: compiled as code ---------------------------------------


def test_debug_lines_compiles_them_as_code() -> None:
    result = parse_cobol(DEBUG_PROGRAM, debug_lines=True)
    assert result.errors == []
    assert _statement_types(result) == [
        "DisplayStatement",
        "DisplayStatement",
        "AddStatement",
        "StopStatement",
    ]
    assert _debug_warnings(result) == []


def test_debug_lines_items_are_referenced() -> None:
    def unused(debug_lines: bool) -> set[str]:
        ast = parse_cobol(DEBUG_PROGRAM, debug_lines=debug_lines).ast
        return {
            item.name for item in UnusedVariableAnalyzer().analyze(ast).unused_items
        }

    assert {"WS-TRACE", "WS-CNT"} <= unused(False)
    assert not {"WS-TRACE", "WS-CNT"} & unused(True)


def test_cobol_parser_takes_debug_lines() -> None:
    result = CobolParser(debug_lines=True).parse(DEBUG_PROGRAM)
    assert "AddStatement" in _statement_types(result)


def test_parse_cobol_with_expansion_passes_debug_lines(tmp_path) -> None:
    result = parse_cobol_with_expansion(
        DEBUG_PROGRAM, "DBG.cbl", copybook_paths=[str(tmp_path)], debug_lines=True
    )
    assert "AddStatement" in _statement_types(result)


def test_tokenize_source_honours_debug_lines() -> None:
    def line_13(debug_lines: bool) -> list[TokenType]:
        tokens, _errors, _warnings = _tokenize_source(
            DEBUG_PROGRAM, debug_lines=debug_lines
        )
        return [t.type for t in tokens if t.location.line == 13]

    assert line_13(False) == [TokenType.COMMENT]
    as_code = line_13(True)
    assert TokenType.DISPLAY in as_code and TokenType.COMMENT not in as_code


def test_scan_options_debug_lines(tmp_path) -> None:
    path = tmp_path / "DBG.cbl"
    path.write_text(DEBUG_PROGRAM)

    def unused(debug_lines: bool) -> list[str]:
        report = scan_files(
            [str(path)],
            ScanOptions(analyzers=("unused-variables",), debug_lines=debug_lines),
            workers=1,
        )
        unit = report.files[0].units[0]
        return json.dumps(unit.reports["unused-variables"])

    assert "WS-CNT" in unused(False)
    assert "WS-CNT" not in unused(True)


# -- which lines count --------------------------------------------------------


def test_debug_line_numbers() -> None:
    lines = [
        "       PROCEDURE DIVISION.",
        "      D    DISPLAY 'A'",
        "      d    DISPLAY 'B'",
        "      *    COMMENT",
        "\tD",  # a tab is 8 columns: column 7 is blank
        "short",
    ]
    assert debug_line_numbers(lines) == [2, 3]


def test_debug_line_numbers_skips_free_format_lines() -> None:
    lines = [
        "      D    DISPLAY 'A'",
        "       >>SOURCE FORMAT IS FREE",
        "      DISPLAY 'B'",  # free format: the D starts DISPLAY
        ">>SOURCE FORMAT IS FIXED",
        "      D    DISPLAY 'C'",
    ]
    assert debug_line_numbers(lines) == [1, 5]


# -- CLI and cobol.yml --------------------------------------------------------


def _run(argv: list[str], capsys) -> str:
    with patch("sys.argv", ["cobol-parser", *argv]):
        try:
            main()
        except SystemExit as exc:
            assert not exc.code, capsys.readouterr()
    return capsys.readouterr().out


@pytest.fixture
def program(tmp_path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "DBG.cbl"
    path.write_text(DEBUG_PROGRAM)
    return path


def _unused_names(output: str) -> set[str]:
    return {item["name"] for item in json.loads(output)["unused_variables"]}


def test_cli_debug_lines_flag(program, capsys) -> None:
    default = _unused_names(_run(["unused-variables", str(program)], capsys))
    assert "WS-CNT" in default
    kept = _unused_names(
        _run(["unused-variables", str(program), "--debug-lines"], capsys)
    )
    assert "WS-CNT" not in kept


def test_cli_parse_reports_the_warning(program, capsys) -> None:
    out = _run(["parse", str(program), "--errors"], capsys)
    assert "DEBUGGING MODE" in out


def test_cli_preprocess_debug_lines(program, capsys) -> None:
    assert "ADD 1 TO WS-CNT" not in _run(["preprocess", str(program)], capsys)
    assert "ADD 1 TO WS-CNT" in _run(
        ["preprocess", str(program), "--debug-lines"], capsys
    )


def test_config_debug_lines_and_the_flag_overrides_it(program, capsys) -> None:
    (program.parent / "cobol.yml").write_text("project:\n  debug_lines: true\n")
    from_config = _unused_names(_run(["unused-variables", str(program)], capsys))
    assert "WS-CNT" not in from_config
    overridden = _unused_names(
        _run(["unused-variables", str(program), "--no-debug-lines"], capsys)
    )
    assert "WS-CNT" in overridden


def test_config_subcommand_prints_debug_lines(program, capsys) -> None:
    (program.parent / "cobol.yml").write_text("project:\n  debug_lines: true\n")
    assert "debug_lines: true" in _run(["config"], capsys)
    payload = json.loads(_run(["config", "--json"], capsys))
    assert payload["project"]["debug_lines"] is True


def test_config_debug_lines_must_be_a_boolean(tmp_path) -> None:
    source = tmp_path / "cobol.yml"
    assert (
        build_config({"project": {"debug_lines": False}}, source).debug_lines is False
    )
    assert build_config({}, source).debug_lines is None
    with pytest.raises(ConfigError, match="project.debug_lines"):
        build_config({"project": {"debug_lines": "yes"}}, source)
