"""Every CLI output must be properly identified.

Each JSON document emitted by the ``cobol-parser`` CLI starts with a
``source_file`` key (the input path as given on the command line) and, for
subcommands that parse the source, a ``program_id`` key (the PROGRAM-ID from
the IDENTIFICATION DIVISION). Text outputs (flowcharts, generated tests)
carry the program name in a header. These tests pin that contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cobolparser.cli.parse import main

SAMPLES = Path(__file__).parents[2] / "samples"

_SIMPLE = str(SAMPLES / "simple_calculation.cbl")
_PROGRAM_ID = "CALC-DEMO"


def _run(capsys, *argv: str) -> str:
    with patch("sys.argv", ["cobol-parser", *argv]):
        main()
    return capsys.readouterr().out


def _run_json(capsys, *argv: str) -> dict:
    return json.loads(_run(capsys, *argv))


class TestReportIdentification:
    """Analyzer subcommands: source_file + program_id lead the report."""

    @pytest.mark.parametrize(
        "subcommand",
        [
            "analyze",
            "dead-code",
            "program-flow",
            "io-sequence",
            "move-type-check",
            "linkage-check",
            "language-env",
            "ims-dli",
        ],
    )
    def test_report_is_identified(self, capsys, subcommand):
        data = _run_json(capsys, subcommand, _SIMPLE)
        assert data["source_file"] == _SIMPLE
        assert data["program_id"] == _PROGRAM_ID
        # Identification comes first so the output is self-describing
        assert list(data)[:2] == ["source_file", "program_id"]


class TestParseIdentification:
    def test_full_ast_carries_source_file(self, capsys):
        data = _run_json(capsys, "parse", _SIMPLE)
        assert data["source_file"] == _SIMPLE
        # program identification comes from the AST itself
        assert data["program_name"] == _PROGRAM_ID

    def test_errors_stats_wrapper_is_identified(self, capsys):
        data = _run_json(capsys, "parse", _SIMPLE, "--errors", "--stats")
        assert data["source_file"] == _SIMPLE
        assert data["program_id"] == _PROGRAM_ID
        assert "ast" in data
        assert "errors" in data
        assert "statistics" in data

    def test_path_extraction_is_identified(self, capsys):
        data = _run_json(capsys, "parse", _SIMPLE, "identification")
        assert data["source_file"] == _SIMPLE
        assert data["program_id"] == _PROGRAM_ID
        assert data["path"] == "identification"
        assert data["result"]["division_name"] == "IDENTIFICATION"

    def test_find_type_is_identified(self, capsys):
        data = _run_json(capsys, "parse", _SIMPLE, "--find-type", "MoveStatement")
        assert data["source_file"] == _SIMPLE
        assert data["program_id"] == _PROGRAM_ID
        assert data["node_type"] == "MoveStatement"
        assert isinstance(data["matches"], list)


class TestNonParsingIdentification:
    def test_tokenize_is_identified(self, capsys):
        data = _run_json(capsys, "tokenize", _SIMPLE)
        assert data["source_file"] == _SIMPLE
        assert isinstance(data["tokens"], list)
        assert data["tokens"]

    def test_expand_is_identified(self, capsys):
        data = _run_json(capsys, "expand", _SIMPLE)
        assert data["source_file"] == _SIMPLE
        assert "expanded_source" in data


class TestBatchIdentification:
    def test_batch_entries_carry_path_and_program_id(self, capsys):
        data = json.loads(_run(capsys, "batch", _SIMPLE))
        assert isinstance(data, list)
        entry = data[0]
        assert entry["path"] == _SIMPLE
        assert entry["program_id"] == _PROGRAM_ID


class TestStatementTypeIdentification:
    """Statements are identifiable by their concrete class name.

    All statement nodes share the generic node_type "Statement", so
    find_all_by_type (and therefore ``analyze`` and ``--find-type``) also
    matches the concrete class name — otherwise CALL/SQL/IO statements could
    never be identified in CLI output.
    """

    def test_analyze_identifies_call_statements(self, capsys):
        sample = str(SAMPLES / "call_dynamic_programs.cbl")
        data = _run_json(capsys, "analyze", sample)
        assert data["source_file"] == sample
        assert len(data["calls"]) > 0
        for call in data["calls"]:
            assert "called_program" in call
            assert "is_dynamic" in call

    def test_find_type_matches_statement_class(self, capsys):
        data = _run_json(capsys, "parse", _SIMPLE, "--find-type", "DisplayStatement")
        assert data["node_type"] == "DisplayStatement"
        assert len(data["matches"]) > 0
        for node in data["matches"]:
            assert node["statement_type"] == "DISPLAY"

    def test_find_type_matches_io_statement_class(self, capsys):
        sample = str(SAMPLES / "file_operations.cbl")
        data = _run_json(capsys, "parse", sample, "--find-type", "IOReadStatement")
        assert len(data["matches"]) > 0
        for node in data["matches"]:
            assert node["statement_type"] == "READ"

    def test_find_type_generic_statement_still_matches_node_type(self, capsys):
        data = _run_json(capsys, "parse", _SIMPLE, "--find-type", "Statement")
        assert len(data["matches"]) > 0


class TestTextOutputIdentification:
    def test_mermaid_flowchart_has_program_header(self, capsys):
        out = _run(capsys, "program-flow", _SIMPLE, "--format", "mermaid")
        assert out.splitlines()[0] == "%% Program: CALC-DEMO"

    def test_dot_flowchart_names_digraph_after_program(self, capsys):
        out = _run(capsys, "program-flow", _SIMPLE, "--format", "dot")
        assert out.splitlines()[0] == f'digraph "{_PROGRAM_ID}" {{'
