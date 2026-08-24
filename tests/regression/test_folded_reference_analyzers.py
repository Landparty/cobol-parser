"""Analyzers must see through folded qualifier/subscript reference strings.

The corpus series taught MOVE/arithmetic/SET/PERFORM to fold ``OF``/``IN``
qualifier chains and ``( subscript )`` groups into one operand string so no
reference tokens are dropped from the AST. Analyzers that key data items by
bare name must recover the base name from that folded string
(``analysis._names.base_data_name``) -- before that, a qualified MOVE target
silently missed every lookup:

* ``MoveTypeChecker`` reported zero violations for ``MOVE 'ABCD' TO WS-NUM
  OF GRP-1`` (the catalog lookup of the folded string failed, so the target
  classified as a literal);
* ``DynamicCallAnalyzer`` returned ``[]`` possible values for a dynamic
  ``CALL WS-PROG`` whose value arrived via ``MOVE 'SUBPROG1' TO WS-PROG OF
  GRP-1`` (the tracked-variable table was keyed by the folded string, the
  CALL looked up the bare name).
"""

from cobolparser import MoveTypeChecker, parse_cobol
from cobolparser.analysis import DynamicCallAnalyzer
from cobolparser.analysis._names import base_data_name


def _parse(source: str):
    result = parse_cobol(source, filename="QREF.cbl")
    assert result.success, result.errors
    return result.ast


QUALIFIED_SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. QREF.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  GRP-1.
           05  WS-NUM PIC 9(4).
           05  WS-PROG PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'ABCD' TO WS-NUM OF GRP-1
           MOVE 'SUBPROG1' TO WS-PROG OF GRP-1
           CALL WS-PROG
           STOP RUN.
"""


class TestBaseDataName:
    def test_qualified_and_subscripted_forms(self):
        assert base_data_name("WS-NUM OF GRP-1") == "WS-NUM"
        assert base_data_name("WS-NUM IN GRP-1") == "WS-NUM"
        assert base_data_name("WS-TAB ( 3 )") == "WS-TAB"
        assert base_data_name("WS-TAB OF GRP ( IDX )") == "WS-TAB"

    def test_non_reference_strings_unchanged(self):
        assert base_data_name("WS-NUM") == "WS-NUM"
        assert base_data_name("'AB CD'") == "'AB CD'"
        assert base_data_name("ALL 'X'") == "ALL 'X'"
        assert base_data_name("") == ""


class TestMoveTypeCheckerQualifiedTarget:
    def test_qualified_numeric_target_still_flags_alnum_move(self):
        ast = _parse(QUALIFIED_SOURCE)
        report = MoveTypeChecker().check(ast)
        messages = [v.message for v in report.violations]
        assert any("WS-NUM" in m for m in messages), messages


class TestDynamicCallAnalyzerQualifiedMoveTarget:
    def test_qualified_move_target_feeds_bare_dynamic_call(self):
        ast = _parse(QUALIFIED_SOURCE)
        DynamicCallAnalyzer().analyze(ast)
        calls = ast.find_all_by_type("CallStatement")
        assert len(calls) == 1
        assert calls[0].possible_values == ["SUBPROG1"]
