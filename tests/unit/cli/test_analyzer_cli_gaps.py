"""Tests for analyzer-subcommand CLI paths that previously had no coverage.

Covers (2026-08-16 analyzer-subcommand audit):

* ``unused-variables`` copybook-provenance flow (``--copybook-path`` /
  ``--exclude-copybook-variables``), including the no-op warning and the
  unexpanded-parse-failure fallback.
* ``_parse_or_fail``'s partial-parse stderr warning (analyzer subcommands
  proceed on a recovered AST but must say so).
* ``analyze`` emitting ``possible_values_incomplete`` for a dynamic CALL
  whose value set DynamicCallAnalyzer could not fully resolve.
* ``program-flow`` warning when ``--profile`` is combined with a text
  flowchart format that has nowhere to embed the metrics.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from cobolparser.cli.parse import main

COPYBOOK = """       01 CUST-REC.
          05 CUST-ID PIC 9(5).
          05 CUST-NAME PIC X(20).
"""

COPY_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. UVP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY CUSTREC.
       01 WS-LOCAL-UNUSED PIC X(4).
       01 WS-USED PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'ABCD' TO WS-USED.
           STOP RUN.
"""

# Parses under COLLECT_ALL to an AST *plus* one collected error.
PARTIAL_PARSE_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PARTIAL.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF
           STOP RUN.
"""

DYNAMIC_INCOMPLETE_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYNP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TARGET PIC X(8).
       01 WS-INPUT PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE WS-INPUT TO WS-TARGET.
           MOVE 'PROGA' TO WS-TARGET.
           CALL WS-TARGET.
           STOP RUN.
"""

DYNAMIC_COMPLETE_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYNC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TARGET PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'PROGA' TO WS-TARGET.
           CALL WS-TARGET.
           STOP RUN.
"""

FLOW_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. FLOWP.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM SUB-PARA.
           STOP RUN.
       SUB-PARA.
           DISPLAY 'HI'.
"""


def _run_main(argv: list[str]) -> None:
    with patch("sys.argv", ["cobol-parser", *argv]):
        main()


@pytest.fixture()
def copybook_setup(tmp_path):
    cpy_dir = tmp_path / "cpy"
    cpy_dir.mkdir()
    (cpy_dir / "CUSTREC.CPY").write_text(COPYBOOK)
    program = tmp_path / "uv.cbl"
    program.write_text(COPY_PROGRAM)
    return program, cpy_dir


class TestUnusedVariablesCopybookCLI:
    def test_copybook_items_flagged_with_provenance(self, copybook_setup, capsys):
        program, cpy_dir = copybook_setup
        _run_main(["unused-variables", str(program), "--copybook-path", str(cpy_dir)])
        data = json.loads(capsys.readouterr().out)
        by_name = {i["name"]: i for i in data["unused_variables"]}
        assert by_name["CUST-REC"]["from_copybook"] is True
        assert by_name["CUST-ID"]["from_copybook"] is True
        assert by_name["WS-LOCAL-UNUSED"]["from_copybook"] is False
        assert data["summary"]["skipped_copybook_variables"] == 0

    def test_locations_carry_the_on_disk_origin(self, copybook_setup, capsys):
        # `location` counts lines of the expanded text (the 3-line member
        # pushes WS-LOCAL-UNUSED from line 6 to line 8); `origin` says where
        # each item really is, the way lint findings already did.
        program, cpy_dir = copybook_setup
        _run_main(["unused-variables", str(program), "--copybook-path", str(cpy_dir)])
        data = json.loads(capsys.readouterr().out)
        by_name = {i["name"]: i for i in data["unused_variables"]}
        assert by_name["WS-LOCAL-UNUSED"]["origin"] == {
            "file": str(program),
            "line": 6,
        }
        assert by_name["CUST-ID"]["origin"]["file"].endswith("CUSTREC.CPY")
        assert by_name["CUST-ID"]["origin"]["line"] == 2

    def test_exclude_copybook_variables_filters_and_tallies(
        self, copybook_setup, capsys
    ):
        program, cpy_dir = copybook_setup
        _run_main(
            [
                "unused-variables",
                str(program),
                "--copybook-path",
                str(cpy_dir),
                "--exclude-copybook-variables",
            ]
        )
        data = json.loads(capsys.readouterr().out)
        names = {i["name"] for i in data["unused_variables"]}
        assert names == {"WS-LOCAL-UNUSED"}
        assert data["summary"]["skipped_copybook_variables"] == 3

    def test_exclude_without_copybook_path_warns_and_runs(self, tmp_path, capsys):
        program = tmp_path / "uv.cbl"
        program.write_text(COPY_PROGRAM)
        _run_main(["unused-variables", str(program), "--exclude-copybook-variables"])
        captured = capsys.readouterr()
        assert "--exclude-copybook-variables has no effect" in captured.err
        data = json.loads(captured.out)
        # COPY was never expanded, so only the two local items are declared.
        assert data["summary"]["total_variables"] == 2

    def test_unexpanded_parse_failure_disables_provenance(self, copybook_setup, capsys):
        program, cpy_dir = copybook_setup

        class _FailedResult:
            ast = None
            errors: list[str] = []

        # The unexpanded provenance parse goes through the module-level
        # ``parse_cobol`` import; the main (expanded) parse goes through
        # ``parse_cobol_with_expansion``, so only the provenance pass fails.
        with patch("cobolparser.cli.parse.parse_cobol", return_value=_FailedResult()):
            _run_main(
                [
                    "unused-variables",
                    str(program),
                    "--copybook-path",
                    str(cpy_dir),
                    "--exclude-copybook-variables",
                ]
            )
        captured = capsys.readouterr()
        assert "copybook-origin detection disabled" in captured.err
        data = json.loads(captured.out)
        # Provenance unavailable: nothing is skipped, everything unused is
        # reported (and not attributed to a copybook).
        assert data["summary"]["skipped_copybook_variables"] == 0
        names = {i["name"] for i in data["unused_variables"]}
        assert "CUST-REC" in names
        assert all(not i["from_copybook"] for i in data["unused_variables"])


class TestPartialParseWarning:
    def test_analyzer_subcommand_warns_but_exits_zero(self, tmp_path, capsys):
        program = tmp_path / "partial.cbl"
        program.write_text(PARTIAL_PARSE_PROGRAM)
        _run_main(["dead-code", str(program)])  # must not raise SystemExit
        captured = capsys.readouterr()
        assert "analysis may be incomplete" in captured.err
        data = json.loads(captured.out)
        assert data["program_id"] == "PARTIAL"

    def test_parse_subcommand_exits_two_on_partial_parse(self, tmp_path, capsys):
        program = tmp_path / "partial.cbl"
        program.write_text(PARTIAL_PARSE_PROGRAM)
        with pytest.raises(SystemExit) as exc_info:
            _run_main(["parse", str(program)])
        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "AST may be incomplete" in captured.err


class TestAnalyzeIncompleteValues:
    def test_incomplete_value_set_is_flagged(self, tmp_path, capsys):
        program = tmp_path / "dyn.cbl"
        program.write_text(DYNAMIC_INCOMPLETE_PROGRAM)
        _run_main(["analyze", str(program)])
        data = json.loads(capsys.readouterr().out)
        (call,) = data["calls"]
        assert call["is_dynamic"] is True
        assert call["possible_values"] == ["PROGA"]
        assert call["possible_values_incomplete"] is True

    def test_complete_value_set_has_no_flag(self, tmp_path, capsys):
        program = tmp_path / "dync.cbl"
        program.write_text(DYNAMIC_COMPLETE_PROGRAM)
        _run_main(["analyze", str(program)])
        data = json.loads(capsys.readouterr().out)
        (call,) = data["calls"]
        assert call["possible_values"] == ["PROGA"]
        assert "possible_values_incomplete" not in call


class TestProgramFlowProfileTextFormats:
    @pytest.mark.parametrize("fmt", ["mermaid", "dot"])
    def test_profile_with_text_format_warns(self, fmt, tmp_path, capsys):
        program = tmp_path / "flow.cbl"
        program.write_text(FLOW_PROGRAM)
        _run_main(["program-flow", str(program), "--format", fmt, "--profile"])
        captured = capsys.readouterr()
        assert "--profile metrics are only included in --format json" in captured.err
        assert captured.out  # the flowchart itself is still emitted

    def test_profile_with_json_format_embeds_metrics(self, tmp_path, capsys):
        program = tmp_path / "flow.cbl"
        program.write_text(FLOW_PROGRAM)
        _run_main(["program-flow", str(program), "--profile"])
        data = json.loads(capsys.readouterr().out)
        assert "profiling" in data

    def test_text_format_without_profile_does_not_warn(self, tmp_path, capsys):
        program = tmp_path / "flow.cbl"
        program.write_text(FLOW_PROGRAM)
        _run_main(["program-flow", str(program), "--format", "mermaid"])
        captured = capsys.readouterr()
        assert "warning:" not in captured.err


DEAD_COPY_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DCP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY CUSTREC.
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
       DEAD-PARA.
           DISPLAY 'DEAD'.
"""


class TestEveryAnalyzerStampsOrigins:
    """Only lint and unused-variables used to say where an expanded-listing
    location really is; every other analyzer subcommand taking
    --copybook-path reported DEAD-PARA at line 11 of a file whose line 11
    does not exist, with nothing to map it back."""

    def test_dead_code_location_gains_origin(self, tmp_path, capsys):
        cpy_dir = tmp_path / "cpy"
        cpy_dir.mkdir()
        (cpy_dir / "CUSTREC.CPY").write_text(COPYBOOK)
        program = tmp_path / "dead.cbl"
        program.write_text(DEAD_COPY_PROGRAM)

        _run_main(["dead-code", str(program), "--copybook-path", str(cpy_dir)])
        (item,) = json.loads(capsys.readouterr().out)["dead_code"]
        assert item["location"]["line"] == 11  # expanded listing, unchanged
        assert item["origin"] == {"file": str(program), "line": 9}

    def test_no_origin_without_expansion(self, tmp_path, capsys):
        program = tmp_path / "flow.cbl"
        program.write_text(FLOW_PROGRAM)
        _run_main(["complexity", str(program)])
        assert '"origin"' not in capsys.readouterr().out
