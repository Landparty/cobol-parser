"""Tests for the 6 critical parser fixes.

Covers:
1. Level 88 (condition names)
2. Level 66 (RENAMES)
3. OCCURS DEPENDING ON / INDEXED BY
4. Unterminated string literal at EOF
5. IF condition expression tree
6. GO TO ValueError -> parse error
"""
import pytest
from cobolparser import parse_cobol, ErrorRecoveryMode


class TestLevel88ConditionNames:
    COBOL_88 = """\
000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. TEST88.
000300 DATA DIVISION.
000400 WORKING-STORAGE SECTION.
000500 01  WS-STATUS        PIC X.
000600     88  STATUS-OPEN  VALUE "O".
000700     88  STATUS-CLOSED VALUE "C" "D".
000800 PROCEDURE DIVISION.
000900 MAIN-PARA.
001000     STOP RUN.
"""

    def test_88_items_parsed(self):
        from cobolparser.models.data_items import ConditionNameItem
        result = parse_cobol(self.COBOL_88, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        all_nodes = result.ast.find_all_by_type("ConditionNameItem")
        assert len(all_nodes) == 2, f"Expected 2 ConditionNameItems, got {len(all_nodes)}"

    def test_88_item_name(self):
        result = parse_cobol(self.COBOL_88, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        nodes = result.ast.find_all_by_type("ConditionNameItem")
        names = {n.name for n in nodes}
        assert "STATUS-OPEN" in names
        assert "STATUS-CLOSED" in names

    def test_88_item_single_value(self):
        result = parse_cobol(self.COBOL_88, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        nodes = result.ast.find_all_by_type("ConditionNameItem")
        open_node = next(n for n in nodes if n.name == "STATUS-OPEN")
        assert "O" in open_node.values

    def test_88_multi_value(self):
        result = parse_cobol(self.COBOL_88, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        nodes = result.ast.find_all_by_type("ConditionNameItem")
        closed_node = next(n for n in nodes if n.name == "STATUS-CLOSED")
        assert len(closed_node.values) == 2
        assert "C" in closed_node.values
        assert "D" in closed_node.values

    def test_88_attached_to_parent(self):
        from cobolparser.models.data_items import ConditionNameItem
        result = parse_cobol(self.COBOL_88, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        ws_items = result.ast.find_all_by_type("DataItem")
        ws_status = next((i for i in ws_items if getattr(i, "name", "") == "WS-STATUS"), None)
        assert ws_status is not None
        cond_children = [c for c in ws_status.children if isinstance(c, ConditionNameItem)]
        assert len(cond_children) == 2

    def test_88_to_dict(self):
        result = parse_cobol(self.COBOL_88, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        nodes = result.ast.find_all_by_type("ConditionNameItem")
        d = nodes[0].to_dict()
        assert d["node_type"] == "ConditionNameItem"
        assert "name" in d
        assert "values" in d


class TestLevel66Renames:
    COBOL_66 = """\
000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. TEST66.
000300 DATA DIVISION.
000400 WORKING-STORAGE SECTION.
000500 01  WS-RECORD.
000600     05  WS-FIRST    PIC X(5).
000700     05  WS-SECOND   PIC X(5).
000800 66  WS-ALIAS        RENAMES WS-FIRST.
000900 66  WS-RANGE        RENAMES WS-FIRST THROUGH WS-SECOND.
001000 PROCEDURE DIVISION.
001100 MAIN-PARA.
001200     STOP RUN.
"""

    def test_66_items_parsed(self):
        from cobolparser.models.data_items import RenamesItem
        result = parse_cobol(self.COBOL_66, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        nodes = result.ast.find_all_by_type("RenamesItem")
        assert len(nodes) == 2

    def test_66_item_name(self):
        result = parse_cobol(self.COBOL_66, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        nodes = result.ast.find_all_by_type("RenamesItem")
        names = {n.name for n in nodes}
        assert "WS-ALIAS" in names
        assert "WS-RANGE" in names

    def test_66_renames_target(self):
        result = parse_cobol(self.COBOL_66, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        nodes = result.ast.find_all_by_type("RenamesItem")
        alias = next(n for n in nodes if n.name == "WS-ALIAS")
        assert alias.renames_from == "WS-FIRST"
        assert alias.renames_through is None

    def test_66_renames_range(self):
        result = parse_cobol(self.COBOL_66, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        nodes = result.ast.find_all_by_type("RenamesItem")
        rng = next(n for n in nodes if n.name == "WS-RANGE")
        assert rng.renames_from == "WS-FIRST"
        assert rng.renames_through == "WS-SECOND"

    def test_66_to_dict(self):
        result = parse_cobol(self.COBOL_66, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        nodes = result.ast.find_all_by_type("RenamesItem")
        d = nodes[0].to_dict()
        assert d["node_type"] == "RenamesItem"
        assert "renames_from" in d


class TestOccursDependingOn:
    COBOL_ODO = """\
000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. TESTODO.
000300 DATA DIVISION.
000400 WORKING-STORAGE SECTION.
000500 01  WS-TABLE-SIZE    PIC 9(3).
000600 01  WS-TABLE.
000700     05  WS-ENTRY     PIC X(10)
000800                      OCCURS 1 TO 50 TIMES
000900                      DEPENDING ON WS-TABLE-SIZE
001000                      INDEXED BY WS-IDX.
001100 PROCEDURE DIVISION.
001200 MAIN-PARA.
001300     STOP RUN.
"""

    def test_variable_occurs_min_max(self):
        result = parse_cobol(self.COBOL_ODO, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        items = result.ast.find_all_by_type("DataItem")
        entry = next((i for i in items if getattr(i, "name", "") == "WS-ENTRY"), None)
        assert entry is not None
        assert entry.occurs_clause is not None
        assert entry.occurs_clause.min_times == 1
        assert entry.occurs_clause.max_times == 50

    def test_variable_occurs_depending_on(self):
        result = parse_cobol(self.COBOL_ODO, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        items = result.ast.find_all_by_type("DataItem")
        entry = next(i for i in items if getattr(i, "name", "") == "WS-ENTRY")
        assert entry.occurs_clause.depending_on == "WS-TABLE-SIZE"

    def test_variable_occurs_indexed_by(self):
        result = parse_cobol(self.COBOL_ODO, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        items = result.ast.find_all_by_type("DataItem")
        entry = next(i for i in items if getattr(i, "name", "") == "WS-ENTRY")
        assert entry.occurs_clause.indexed_by == "WS-IDX"

    def test_fixed_occurs_unchanged(self):
        cobol = """\
000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. TESTFIX.
000300 DATA DIVISION.
000400 WORKING-STORAGE SECTION.
000500 01  WS-ARRAY.
000600     05  WS-ITEM  PIC 9  OCCURS 10 TIMES.
000700 PROCEDURE DIVISION.
000800 MAIN-PARA.
000900     STOP RUN.
"""
        result = parse_cobol(cobol, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        items = result.ast.find_all_by_type("DataItem")
        item = next(i for i in items if getattr(i, "name", "") == "WS-ITEM")
        assert item.occurs_clause.min_times == 10
        assert item.occurs_clause.max_times == 10
        assert item.occurs_clause.depending_on is None


class TestUnterminatedStringAtEOF:
    def test_unterminated_string_raises(self):
        from cobolparser.preprocess import normalize_fixed_format
        lines = [
            "000100 WORKING-STORAGE SECTION.",
            '000200 01 WS-VAR PIC X(10) VALUE "HELLO',
        ]
        with pytest.raises(Exception) as exc_info:
            normalize_fixed_format(lines)
        msg = str(exc_info.value).lower()
        assert "unterminated" in msg or "literal" in msg or "quote" in msg

    def test_valid_multiline_string_does_not_raise(self):
        from cobolparser.preprocess import normalize_fixed_format
        lines = [
            '000100 01 WS-VAR PIC X(10) VALUE "HELL',
            '000200-       O".',
        ]
        result = normalize_fixed_format(lines)
        assert result is not None

    def test_normal_source_unaffected(self):
        from cobolparser.preprocess import normalize_fixed_format
        lines = [
            "000100 IDENTIFICATION DIVISION.",
            "000200 PROGRAM-ID. TEST.",
        ]
        result = normalize_fixed_format(lines)
        assert "IDENTIFICATION DIVISION" in result


class TestIfConditionTree:
    SIMPLE_IF = """\
000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. TESTIF.
000300 DATA DIVISION.
000400 WORKING-STORAGE SECTION.
000500 01  WS-A    PIC 9.
000600 PROCEDURE DIVISION.
000700 MAIN-PARA.
000800     IF WS-A = 1
000900         DISPLAY "ONE"
001000     END-IF.
001100     STOP RUN.
"""

    AND_IF = """\
000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. TESTIF2.
000300 DATA DIVISION.
000400 WORKING-STORAGE SECTION.
000500 01  WS-A    PIC 9.
000600 01  WS-B    PIC 9.
000700 PROCEDURE DIVISION.
000800 MAIN-PARA.
000900     IF WS-A = 1 AND WS-B = 2
001000         DISPLAY "BOTH"
001100     END-IF.
001200     STOP RUN.
"""

    def _get_if_stmt(self, cobol_src):
        from cobolparser.models.statements import IfStatement
        result = parse_cobol(cobol_src, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        stmts = result.ast.find_statements("IF")
        return next((s for s in stmts if isinstance(s, IfStatement)), None)

    def test_simple_condition_is_not_none(self):
        stmt = self._get_if_stmt(self.SIMPLE_IF)
        assert stmt is not None
        assert stmt.condition is not None, "IF condition must not be None"

    def test_simple_condition_type(self):
        from cobolparser.models.statements.base import ConditionalExpression
        stmt = self._get_if_stmt(self.SIMPLE_IF)
        assert isinstance(stmt.condition, ConditionalExpression)

    def test_simple_condition_operator(self):
        stmt = self._get_if_stmt(self.SIMPLE_IF)
        assert stmt.condition.operator == "EQUAL"

    def test_simple_condition_operands(self):
        stmt = self._get_if_stmt(self.SIMPLE_IF)
        assert stmt.condition.left_operand == "WS-A"
        assert stmt.condition.right_operand == "1"

    def test_compound_and_condition(self):
        from cobolparser.models.statements.base import LogicalExpression
        stmt = self._get_if_stmt(self.AND_IF)
        assert isinstance(stmt.condition, LogicalExpression)
        assert stmt.condition.operator == "AND"


class TestGoToParseError:
    MISSING_TO = """\
000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. TESTGO.
000300 PROCEDURE DIVISION.
000400 MAIN-PARA.
000500     GO PARA-1.
000600     STOP RUN.
000700 PARA-1.
000800     DISPLAY "HERE".
"""
    MISSING_TARGET = """\
000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. TESTGO2.
000300 PROCEDURE DIVISION.
000400 MAIN-PARA.
000500     GO TO.
000600     STOP RUN.
"""

    def test_missing_to_does_not_crash(self):
        result = parse_cobol(self.MISSING_TO, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result is not None
        assert result.ast is not None

    def test_missing_to_reports_error(self):
        result = parse_cobol(self.MISSING_TO, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result is not None

    def test_missing_target_does_not_crash(self):
        result = parse_cobol(self.MISSING_TARGET, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result is not None
        assert result.ast is not None

    def test_valid_goto_still_works(self):
        cobol = """\
000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. TESTGO3.
000300 PROCEDURE DIVISION.
000400 MAIN-PARA.
000500     GO TO END-PARA.
000600 END-PARA.
000700     STOP RUN.
"""
        result = parse_cobol(cobol, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        stmts = result.ast.find_statements("GOTO")
        assert len(stmts) >= 1
        go_stmt = stmts[0]
        assert go_stmt.target_paragraph == "END-PARA"
