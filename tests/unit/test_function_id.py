"""User-defined functions: ``FUNCTION-ID`` units (IBM Enterprise COBOL 6.4).

A FUNCTION-ID unit used to fail the whole compilation unit with "PROGRAM-ID
is mandatory". It now parses as its own unit (``unit_kind`` "FUNCTION"),
``END FUNCTION`` closes it like ``END PROGRAM``, the REPOSITORY paragraph's
``FUNCTION name`` entries are read, and ``FUNCTION name(...)`` invoking a
declared function is a ``function`` edge in the codebase graph.
"""

from pathlib import Path

from cobolparser import CobolParser, ErrorRecoveryMode, parse_cobol
from cobolparser.analysis.codebase import CALL_KIND_FUNCTION, CodebaseGraphBuilder
from cobolparser.analysis.language_env_analyzer import function_references
from cobolparser.analysis.program_signature import ProgramSignatureExtractor

FUNCTION_AND_CALLER = """\
       IDENTIFICATION DIVISION.
       FUNCTION-ID. DOUBLER AS 'DBLR'.
       DATA DIVISION.
       LINKAGE SECTION.
       01 ARG-IN      PIC S9(5) COMP-3.
       01 RESULT-OUT  PIC S9(6) COMP-3.
       PROCEDURE DIVISION USING BY VALUE ARG-IN RETURNING RESULT-OUT.
           COMPUTE RESULT-OUT = ARG-IN * 2
           GOBACK.
       END FUNCTION DOUBLER.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       REPOSITORY.
           FUNCTION DOUBLER
           FUNCTION ALL INTRINSIC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC S9(5) COMP-3 VALUE 21.
       01 WS-B PIC S9(6) COMP-3.
       PROCEDURE DIVISION.
       MAIN-PARA.
           COMPUTE WS-B = FUNCTION DOUBLER(WS-A)
           MOVE FUNCTION DOUBLER(WS-B) TO WS-A
           IF FUNCTION DOUBLER(WS-A) > 10
              DISPLAY 'BIG ' FUNCTION UPPER-CASE('x')
           END-IF
           GOBACK.
       END PROGRAM CALLER.
"""


def _parse(source: str):
    result = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST).parse(source)
    assert result.errors == []
    return result.ast


class TestFunctionIdParsing:
    def test_function_unit_parses_with_its_kind_and_external_name(self):
        ast = _parse(FUNCTION_AND_CALLER)
        function, caller = ast.program_units()
        assert (function.unit_kind, function.program_name) == ("FUNCTION", "DOUBLER")
        ident = function.get_division("IDENTIFICATION")
        assert ident.metadata["external_name"] == "DBLR"
        assert (caller.unit_kind, caller.program_name) == ("PROGRAM", "CALLER")

    def test_end_function_closes_the_unit(self):
        ast = _parse(FUNCTION_AND_CALLER)
        function, caller = ast.program_units()
        # The function's body stops at END FUNCTION: the caller's statements
        # are not attributed to it.
        own = function.get_division("PROCEDURE")
        assert own.find_all_by_type("MoveStatement") == []
        assert caller.find_all_by_type("MoveStatement") != []
        assert caller.enclosing_program is None

    def test_function_alone_parses(self):
        source = FUNCTION_AND_CALLER.split("       IDENTIFICATION DIVISION.\n")[1]
        ast = _parse("       IDENTIFICATION DIVISION.\n" + source)
        assert ast.unit_kind == "FUNCTION"
        assert ast.program_name == "DOUBLER"

    def test_external_name_absent_for_programs(self):
        ast = _parse(FUNCTION_AND_CALLER)
        caller = ast.program_units()[1]
        assert "external_name" not in caller.get_division("IDENTIFICATION").metadata

    def test_unit_kind_round_trips_to_dict(self):
        ast = _parse(FUNCTION_AND_CALLER)
        assert ast.to_dict()["unit_kind"] == "FUNCTION"


class TestRepositoryParagraph:
    def test_user_functions_and_all_intrinsic(self):
        caller = _parse(FUNCTION_AND_CALLER).program_units()[1]
        repository = caller.repository()
        assert repository == {
            "functions": [{"name": "DOUBLER", "external_name": None}],
            "intrinsic": [],
            "all_intrinsic": True,
            "classes": [],
        }
        assert caller.user_function_names() == ["DOUBLER"]

    def test_named_intrinsics_as_names_and_classes(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. P.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       REPOSITORY.
           FUNCTION TRIM UPPER-CASE INTRINSIC
           FUNCTION F1 AS 'f-one'
           FUNCTION F2
           CLASS JSTRING IS 'java.lang.String'.
       PROCEDURE DIVISION.
           GOBACK.
"""
        repository = _parse(source).repository()
        assert repository["intrinsic"] == ["TRIM", "UPPER-CASE"]
        assert repository["functions"] == [
            {"name": "F1", "external_name": "f-one"},
            {"name": "F2", "external_name": None},
        ]
        assert repository["classes"] == [
            {"name": "JSTRING", "external_name": "java.lang.String"}
        ]
        assert repository["all_intrinsic"] is False

    def test_no_repository(self):
        source = (
            "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n"
            "       PROCEDURE DIVISION.\n           GOBACK.\n"
        )
        ast = _parse(source)
        assert ast.repository() is None
        assert ast.user_function_names() == []


class TestFunctionReferences:
    def test_every_statement_shape_is_found(self):
        caller = _parse(FUNCTION_AND_CALLER).program_units()[1]
        declared = frozenset(caller.user_function_names())
        found = [
            name
            for statement in caller.get_all_statements()
            for name in function_references(statement, declared)
        ]
        assert found == ["DOUBLER", "DOUBLER", "DOUBLER", "UPPER-CASE"]


class TestCodebaseGraph:
    def test_function_edge(self, tmp_path: Path):
        path = tmp_path / "fn.cbl"
        path.write_text(FUNCTION_AND_CALLER)
        graph = CodebaseGraphBuilder().build([str(path)])
        edges = [e.to_dict() for e in graph.call_edges]
        assert edges == [
            {
                "caller": "CALLER",
                "callee": "DOUBLER",
                "is_dynamic": False,
                "resolved": True,
                "kind": CALL_KIND_FUNCTION,
            }
        ]
        assert graph.callers_of("DOUBLER") == ["CALLER"]
        assert '-->|"FUNCTION"|' in graph.to_mermaid()

    def test_undeclared_function_is_not_an_edge(self, tmp_path: Path):
        # Without a REPOSITORY entry, IBM treats the name as an intrinsic
        # (and rejects it); it is not a reference to a FUNCTION-ID.
        source = FUNCTION_AND_CALLER.replace("           FUNCTION DOUBLER\n", "")
        path = tmp_path / "fn.cbl"
        path.write_text(source)
        graph = CodebaseGraphBuilder().build([str(path)])
        assert graph.call_edges == []


class TestSignature:
    def test_function_call_example(self):
        result = parse_cobol(FUNCTION_AND_CALLER)
        signature = ProgramSignatureExtractor().analyze(result.ast)
        entry = signature.entry_points[0]
        assert entry.is_function
        assert entry.returning == "RESULT-OUT"
        assert entry.call_example() == "FUNCTION DOUBLER(ARG-IN)"
        assert entry.to_dict()["is_function"] is True

    def test_program_entry_has_no_function_flag(self):
        source = (
            "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n"
            "       DATA DIVISION.\n       LINKAGE SECTION.\n"
            "       01 A PIC X.\n"
            "       PROCEDURE DIVISION USING A.\n           GOBACK.\n"
        )
        signature = ProgramSignatureExtractor().analyze(parse_cobol(source).ast)
        assert "is_function" not in signature.entry_points[0].to_dict()
        assert signature.entry_points[0].call_example() == 'CALL "P" USING A'
