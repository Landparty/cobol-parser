"""Regression tests for the 2026-07-07 audit's silent-drop fixes.

Pins the fixes for reports/audit-2026-07-07.md findings:

- C1: multi-program compilation units are parsed (contained_programs) instead
  of everything after the first program being silently dropped
- C2: unknown/unsupported verbs produce a ParseResult warning instead of a
  silent skip
- C3: XML/JSON GENERATE/PARSE produce real XmlJsonStatement nodes instead of
  a mis-parsed Report Writer GENERATE
- C4: GO TO with multiple targets keeps all targets and the DEPENDING ON
  variable
- C5: level-88 condition names and level-66 RENAMES survive to_dict()
- C6: CALL NOT ON EXCEPTION is serialized and handler statements are
  reachable via find_all_by_type
- C8: a worker exception in batch parsing becomes a per-file read_error
  instead of aborting the whole batch
- H3: WRITE ... ADVANCING keeps the count and unit
- H6: copybook expansion warnings propagate through
  parse_cobol_with_expansion
"""

import json

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode

PROG_TEMPLATE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROBE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC X(10).
       01 WS-B PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
{proc}
           GOBACK.
"""


def _parse(source: str, mode: ErrorRecoveryMode = ErrorRecoveryMode.COLLECT_ALL):
    return CobolParser(error_recovery=mode).parse(source, filename="probe.cbl")


def _parse_proc(proc: str, mode: ErrorRecoveryMode = ErrorRecoveryMode.COLLECT_ALL):
    return _parse(PROG_TEMPLATE.format(proc=proc), mode)


def _statement_types(result) -> list[str]:
    types: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if "statement_type" in node:
                types.append(node["statement_type"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(result.ast.to_dict())
    return types


class TestMultiProgramCompilationUnits:
    """C1 — stacked/nested programs must not be silently dropped."""

    SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAIN1.
       PROCEDURE DIVISION.
           DISPLAY 'MAIN'.
           CALL 'SUB1'.
           GOBACK.
       END PROGRAM MAIN1.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUB1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC 9.
       PROCEDURE DIVISION.
           DISPLAY 'SUB ONE'.
           MOVE 1 TO WS-X.
           GOBACK.
       END PROGRAM SUB1.
"""

    def test_second_program_is_parsed_and_attached(self):
        result = _parse(self.SOURCE)
        assert result.success
        assert result.ast.program_name == "MAIN1"
        assert [p.program_name for p in result.ast.contained_programs] == ["SUB1"]

    def test_second_program_content_is_in_ast_and_json(self):
        result = _parse(self.SOURCE)
        dumped = json.dumps(result.ast.to_dict())
        assert "SUB ONE" in dumped
        assert "contained_programs" in dumped
        # get_all_statements must reach the contained program's statements
        types = [s.statement_type for s in result.ast.get_all_statements()]
        assert types.count("DISPLAY") == 2
        assert "MOVE" in types

    def test_additional_programs_produce_a_warning(self):
        result = _parse(self.SOURCE)
        assert any("program units" in w for w in result.warnings)

    def test_single_program_unchanged(self):
        result = _parse_proc("           DISPLAY 'X'.")
        assert result.success
        assert result.ast.contained_programs == []
        assert result.warnings == []

    def test_single_program_with_end_program_marker(self):
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. ONE.
       PROCEDURE DIVISION.
           DISPLAY 'X'.
           GOBACK.
       END PROGRAM ONE.
"""
        result = _parse(source)
        assert result.success
        assert result.warnings == []


class TestUnknownStatementWarning:
    """C2 — unknown verbs must be visible on ParseResult.warnings."""

    def test_transform_is_skipped_with_warning(self):
        # TRANSFORM is a genuinely unsupported (obsolete) verb. INVOKE was
        # originally used here, but it now has a registered parser
        # (invoke_parser.py) and no longer takes this path -- see
        # test_invoke_allocate_free_statements.py for its coverage.
        result = _parse_proc(
            "           MOVE 'A' TO WS-A.\n"
            "           TRANSFORM WS-B CHARACTERS FROM 'a' TO 'b'.\n"
            "           MOVE 'B' TO WS-A."
        )
        assert any("TRANSFORM" in w and "skipped" in w for w in result.warnings)
        # surrounding statements survive
        types = _statement_types(result)
        assert types.count("MOVE") == 2

    def test_exhibit_is_skipped_with_warning(self):
        result = _parse_proc("           EXHIBIT NAMED WS-A.")
        assert any("EXHIBIT" in w for w in result.warnings)

    def test_clean_program_has_no_warnings(self):
        result = _parse_proc("           MOVE 'A' TO WS-A.\n           DISPLAY WS-A.")
        assert result.warnings == []


class TestXmlJsonStatements:
    """C3 — XML/JSON GENERATE/PARSE must produce faithful nodes."""

    def test_xml_generate(self):
        result = _parse_proc(
            "           XML GENERATE WS-A FROM WS-B COUNT IN WS-B\n"
            "              ON EXCEPTION DISPLAY 'BAD'\n"
            "           END-XML."
        )
        assert result.success
        nodes = result.ast.find_all_by_type("XmlJsonStatement")
        assert len(nodes) == 1
        node = nodes[0]
        assert node.verb == "XML"
        assert node.action == "GENERATE"
        assert node.primary_operand == "WS-A"
        assert node.from_item == "WS-B"
        assert "COUNT IN WS-B" in (node.clause_text or "")
        assert "EXCEPTION" in (node.clause_text or "")

    def test_json_parse(self):
        result = _parse_proc(
            "           JSON PARSE WS-A INTO WS-B\n           END-JSON."
        )
        nodes = result.ast.find_all_by_type("XmlJsonStatement")
        assert len(nodes) == 1
        assert nodes[0].statement_type == "JSON PARSE"

    def test_xml_without_period_does_not_swallow_next_statement(self):
        result = _parse_proc(
            "           XML GENERATE WS-A FROM WS-B COUNT IN WS-B\n"
            "           MOVE 'B' TO WS-A."
        )
        types = _statement_types(result)
        assert "XML GENERATE" in types
        assert "MOVE" in types

    def test_no_bogus_report_writer_generate(self):
        result = _parse_proc("           JSON GENERATE WS-A FROM WS-B.")
        types = _statement_types(result)
        assert "JSON GENERATE" in types
        assert "GENERATE" not in types


class TestGoToDependingOn:
    """C4 — computed GO TO must keep every target and the variable."""

    def test_all_targets_and_variable_kept(self):
        result = _parse_proc("           GO TO P1 P2 P3 DEPENDING ON WS-B.")
        assert result.success
        gos = result.ast.find_all_by_type("GoStatement")
        assert len(gos) == 1
        go = gos[0]
        assert go.target_paragraph == "P1"
        assert go.target_paragraphs == ["P1", "P2", "P3"]
        assert go.depending_on_variable == "WS-B"

    def test_no_phantom_paragraph_from_variable(self):
        result = _parse_proc("           GO TO P1 P2 P3 DEPENDING ON WS-B.")
        dumped = json.dumps(result.ast.to_dict())
        names = [
            p["paragraph_name"]
            for p in [
                node
                for node in _iter_dicts(json.loads(dumped))
                if node.get("node_type") == "Paragraph"
            ]
        ]
        assert "WS-B" not in names

    def test_simple_go_to_unchanged(self):
        result = _parse_proc("           GO TO P1.")
        go = result.ast.find_all_by_type("GoStatement")[0]
        assert go.target_paragraph == "P1"
        assert go.target_paragraphs == ["P1"]
        assert go.depending_on_variable is None

    def test_multiline_target_list_with_depending(self):
        result = _parse_proc(
            "           GO TO P1 P2 P3\n"
            "               P4 P5\n"
            "               DEPENDING ON WS-B."
        )
        go = result.ast.find_all_by_type("GoStatement")[0]
        assert go.target_paragraphs == ["P1", "P2", "P3", "P4", "P5"]
        assert go.depending_on_variable == "WS-B"

    def test_missing_period_does_not_eat_next_paragraph(self):
        result = _parse_proc(
            "           GO TO EXIT-PARA\n"
            "       NEXT-PARA.\n"
            "           DISPLAY WS-A."
        )
        go = result.ast.find_all_by_type("GoStatement")[0]
        assert go.target_paragraphs == ["EXIT-PARA"]
        dumped = json.dumps(result.ast.to_dict())
        assert '"NEXT-PARA"' in dumped


def _iter_dicts(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_dicts(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_dicts(item)


class TestConditionNamesAndRenamesSerialization:
    """C5 — 88/66 level items must survive the to_dict() boundary."""

    SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROBE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
          05 WS-X PIC 9(3).
          05 WS-Y PIC X(4).
       66 WS-REN RENAMES WS-X THRU WS-Y.
       01 WS-FLAG PIC X.
          88 FLAG-ON VALUE 'Y'.
          88 FLAG-OFF VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN.
           GOBACK.
"""

    def test_condition_names_serialized_under_parent(self):
        result = _parse(self.SOURCE)
        section = result.ast.to_dict()["divisions"]["DATA"]["sections"][
            "WORKING-STORAGE"
        ]
        flag = next(d for d in section["data_items"] if d["name"] == "WS-FLAG")
        names = {c["name"] for c in flag["condition_names"]}
        assert names == {"FLAG-ON", "FLAG-OFF"}
        flag_on = next(c for c in flag["condition_names"] if c["name"] == "FLAG-ON")
        assert flag_on["values"] == ["Y"]

    def test_renames_serialized_on_section(self):
        result = _parse(self.SOURCE)
        section = result.ast.to_dict()["divisions"]["DATA"]["sections"][
            "WORKING-STORAGE"
        ]
        renames = section["renames_items"]
        assert len(renames) == 1
        assert renames[0]["name"] == "WS-REN"
        assert renames[0]["renames_from"] == "WS-X"
        assert renames[0]["renames_through"] == "WS-Y"


class TestCallExceptionHandlerFidelity:
    """C6 — CALL handler bodies must serialize and be traversable."""

    PROC = (
        "           CALL 'SUB' USING WS-A\n"
        "              ON EXCEPTION MOVE 'E' TO WS-A\n"
        "              NOT ON EXCEPTION MOVE 'O' TO WS-A\n"
        "           END-CALL."
    )

    def test_not_on_exception_serialized(self):
        result = _parse_proc(self.PROC)
        dumped = json.dumps(result.ast.to_dict())
        assert '"not_on_exception"' in dumped

    def test_handler_statements_visible_to_find_all_by_type(self):
        result = _parse_proc(self.PROC)
        moves = result.ast.find_all_by_type("MoveStatement")
        assert len(moves) == 2

    def test_traversal_apis_agree(self):
        result = _parse_proc(self.PROC)
        via_find = len(result.ast.find_all_by_type("MoveStatement"))
        via_all = sum(
            1
            for s in result.ast.get_all_statements()
            if type(s).__name__ == "MoveStatement"
        )
        assert via_find == via_all == 2


class TestWriteAdvancingClause:
    """H3 — ADVANCING count and unit must be kept."""

    def test_advancing_lines(self):
        result = _parse_proc(
            "           WRITE OUT-REC FROM WS-A AFTER ADVANCING 2 LINES."
        )
        write = result.ast.find_all_by_type("IOWriteStatement")[0]
        assert write.advancing_mode == "AFTER"
        assert write.advancing_clause == {
            "type": "AFTER",
            "value": 2,
            "unit": "LINES",
        }

    def test_advancing_page(self):
        result = _parse_proc("           WRITE OUT-REC BEFORE ADVANCING PAGE.")
        write = result.ast.find_all_by_type("IOWriteStatement")[0]
        assert write.advancing_clause is not None
        assert write.advancing_clause["value"] == "PAGE"


class TestBatchWorkerContainment:
    """C8 — one poisoned file must not abort the batch."""

    def test_parse_exception_becomes_per_file_read_error(self, tmp_path, monkeypatch):
        good = tmp_path / "good.cbl"
        good.write_text(PROG_TEMPLATE.format(proc="           DISPLAY 'X'."))
        bad = tmp_path / "bad.cbl"
        bad.write_text(PROG_TEMPLATE.format(proc="           DISPLAY 'Y'."))

        from cobolparser import CobolParser
        from cobolparser import batch as batch_mod

        class ExplodingParser:
            def parse(self, source, *args, **kwargs):
                if "'Y'" in source:
                    raise RuntimeError("worker blew up")
                return CobolParser().parse(source, *args, **kwargs)

        monkeypatch.setattr(
            batch_mod, "_get_reusable_parser", lambda *a, **kw: ExplodingParser()
        )
        results = batch_mod.parse_files([str(good), str(bad)], workers=1)
        assert len(results) == 2
        by_name = {r.path.name: r for r in results}
        assert by_name["good.cbl"].result is not None
        assert by_name["good.cbl"].result.success
        assert by_name["bad.cbl"].result is None
        assert "worker blew up" in (by_name["bad.cbl"].read_error or "")

    def test_strict_decode_failure_is_per_file(self, tmp_path):
        good = tmp_path / "good.cbl"
        good.write_text(PROG_TEMPLATE.format(proc="           DISPLAY 'X'."))
        undecodable = tmp_path / "bad.cbl"
        undecodable.write_bytes(b"\xff\xfe\x00 not utf-8 \x9c")

        from cobolparser.batch import parse_files

        results = parse_files([str(good), str(undecodable)], workers=1, errors="strict")
        assert len(results) == 2
        by_name = {r.path.name: r for r in results}
        assert by_name["good.cbl"].result is not None
        assert by_name["bad.cbl"].read_error


class TestExpansionWarningsPropagate:
    """H6 — expansion warnings must reach the ParseResult."""

    def test_warnings_copied_onto_parse_result(self, monkeypatch):
        from cobolparser.preprocess import copybook_expander as ce

        class FakeStats:
            warnings = ["copybook FOO decoded with replacement characters"]

        class FakeExpansion:
            expanded_source = PROG_TEMPLATE.format(proc="           DISPLAY 'X'.")
            statistics = FakeStats()

        monkeypatch.setattr(ce, "expand_copybooks", lambda **kwargs: FakeExpansion())
        result = ce.parse_cobol_with_expansion(
            source_code="ignored", filename="probe.cbl", copybook_paths=["/none"]
        )
        assert any("replacement characters" in w for w in result.warnings)

    def test_profiled_parse_returns_tuple_with_warnings(self, monkeypatch):
        # With enable_profiling=True parse_cobol returns
        # (ParseResult, ProfilingResult); warning propagation must not
        # AttributeError on the tuple and must land on the ParseResult.
        from cobolparser.preprocess import copybook_expander as ce

        class FakeStats:
            warnings = ["copybook FOO decoded with replacement characters"]

        class FakeExpansion:
            expanded_source = PROG_TEMPLATE.format(proc="           DISPLAY 'X'.")
            statistics = FakeStats()

        monkeypatch.setattr(ce, "expand_copybooks", lambda **kwargs: FakeExpansion())
        result = ce.parse_cobol_with_expansion(
            source_code="ignored",
            filename="probe.cbl",
            copybook_paths=["/none"],
            enable_profiling=True,
        )
        assert isinstance(result, tuple)
        parse_result, profiling = result
        assert any("replacement characters" in w for w in parse_result.warnings)
        assert profiling is not None


class TestCliExitCodes:
    """C7 — the CLI must not exit 0 on an errored parse."""

    @staticmethod
    def _run_cli(monkeypatch, *argv: str) -> None:
        import sys as _sys

        from cobolparser.cli.parse import main

        monkeypatch.setattr(_sys, "argv", ["cobol-parser", *argv])
        main()

    def test_parse_exits_nonzero_on_errored_parse(self, tmp_path, monkeypatch, capsys):
        bad = tmp_path / "bad.cbl"
        bad.write_text(
            PROG_TEMPLATE.format(proc="           MOVE TO .\n           DISPLAY WS-A.")
        )
        with pytest.raises(SystemExit) as exc_info:
            self._run_cli(monkeypatch, "parse", str(bad))
        assert exc_info.value.code == 2
        assert "error(s)" in capsys.readouterr().err

    def test_parse_exits_zero_on_clean_parse(self, tmp_path, monkeypatch, capsys):
        good = tmp_path / "good.cbl"
        good.write_text(PROG_TEMPLATE.format(proc="           DISPLAY 'X'."))
        # No SystemExit means exit code 0
        self._run_cli(monkeypatch, "parse", str(good))
        capsys.readouterr()

    def test_batch_exits_nonzero_when_a_file_fails(self, tmp_path, monkeypatch, capsys):
        good = tmp_path / "good.cbl"
        good.write_text(PROG_TEMPLATE.format(proc="           DISPLAY 'X'."))
        missing = tmp_path / "missing.cbl"
        with pytest.raises(SystemExit) as exc_info:
            self._run_cli(monkeypatch, "batch", str(good), str(missing))
        assert exc_info.value.code == 2
        capsys.readouterr()
