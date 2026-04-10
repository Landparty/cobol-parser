"""Tests targeting Priority 3 coverage gaps across multiple modules.

Covers:
- sort_merge_parsers.py (86.90%, 33 missing branches)
- search_parser.py (84.25%, 11 missing branches)
- if_parser.py (86.60%, 22 missing branches)
- io_logger.py (83.03%, 18 missing branches)
- data division (parsers/divisions/data.py, 88.22%, 42 missing branches)
"""

from cobolparser import CobolParser, ErrorRecoveryMode, parse_cobol
from cobolparser.analysis.io_logger import IOLogger, IOLogReport, IOOperation


def _parse(src):
    return parse_cobol(src)


def _parse_with_recovery(src):
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    return parser.parse(src)


# ---------------------------------------------------------------------------
# Sort/Merge Parsers
# ---------------------------------------------------------------------------


class TestSortParser:
    """Tests for SORT statement parsing."""

    def test_sort_ascending_key(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-SORT.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC X(10).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           SORT SORT-FILE\n"
            "               ASCENDING KEY SORT-KEY\n"
            "               USING INPUT-FILE\n"
            "               GIVING OUTPUT-FILE.\n"
            "           STOP RUN.\n"
        )
        result = _parse_with_recovery(src)
        assert result.ast is not None

    def test_sort_descending_key(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-SORT.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           SORT SORT-FILE\n"
            "               DESCENDING KEY SORT-KEY\n"
            "               USING INPUT-FILE\n"
            "               GIVING OUTPUT-FILE.\n"
            "           STOP RUN.\n"
        )
        result = _parse_with_recovery(src)
        assert result.ast is not None

    def test_sort_input_output_procedure(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-SORT.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           SORT SORT-FILE\n"
            "               ASCENDING KEY SORT-KEY\n"
            "               INPUT PROCEDURE IS INPUT-PROC\n"
            "               OUTPUT PROCEDURE IS OUTPUT-PROC.\n"
            "           STOP RUN.\n"
            "       INPUT-PROC.\n"
            "           DISPLAY 'INPUT'.\n"
            "       OUTPUT-PROC.\n"
            "           DISPLAY 'OUTPUT'.\n"
        )
        result = _parse_with_recovery(src)
        assert result.ast is not None


class TestMergeParser:
    """Tests for MERGE statement parsing."""

    def test_merge_ascending_key(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-MERGE.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           MERGE MERGE-FILE\n"
            "               ASCENDING KEY MERGE-KEY\n"
            "               USING FILE-A FILE-B\n"
            "               GIVING OUTPUT-FILE.\n"
            "           STOP RUN.\n"
        )
        result = _parse_with_recovery(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# Search Parser
# ---------------------------------------------------------------------------


class TestSearchParser:
    """Tests for SEARCH statement parsing."""

    def test_search_with_when(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-SEARCH.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-TABLE.\n"
            "           05 WS-ENTRY OCCURS 10 TIMES\n"
            "              INDEXED BY WS-IDX.\n"
            "               10 WS-NAME PIC X(10).\n"
            "       01 WS-TARGET PIC X(10).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           SEARCH WS-ENTRY\n"
            "               WHEN WS-NAME(WS-IDX) = WS-TARGET\n"
            "                   DISPLAY 'FOUND'\n"
            "           END-SEARCH.\n"
            "           STOP RUN.\n"
        )
        result = _parse_with_recovery(src)
        assert result.ast is not None
        stmts = result.ast.get_all_statements()
        types = [s.statement_type for s in stmts]
        assert "SEARCH" in types

    def test_search_with_at_end(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-SEARCH.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-TABLE.\n"
            "           05 WS-ENTRY OCCURS 10 TIMES\n"
            "              INDEXED BY WS-IDX.\n"
            "               10 WS-NAME PIC X(10).\n"
            "       01 WS-TARGET PIC X(10).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           SEARCH WS-ENTRY\n"
            "               AT END\n"
            "                   DISPLAY 'NOT FOUND'\n"
            "               WHEN WS-NAME(WS-IDX) = WS-TARGET\n"
            "                   DISPLAY 'FOUND'\n"
            "           END-SEARCH.\n"
            "           STOP RUN.\n"
        )
        result = _parse_with_recovery(src)
        assert result.ast is not None

    def test_search_all(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-SEARCH.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-TABLE.\n"
            "           05 WS-ENTRY OCCURS 10 TIMES\n"
            "              ASCENDING KEY WS-KEY\n"
            "              INDEXED BY WS-IDX.\n"
            "               10 WS-KEY PIC 9(4).\n"
            "               10 WS-DATA PIC X(10).\n"
            "       01 WS-SEARCH-KEY PIC 9(4).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           SEARCH ALL WS-ENTRY\n"
            "               WHEN WS-KEY(WS-IDX) = WS-SEARCH-KEY\n"
            "                   DISPLAY WS-DATA(WS-IDX)\n"
            "           END-SEARCH.\n"
            "           STOP RUN.\n"
        )
        result = _parse_with_recovery(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# IF Parser
# ---------------------------------------------------------------------------


class TestIfParserEdgeCases:
    """Tests for IF statement parsing edge cases."""

    def test_deeply_nested_if(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-IF.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC 9 VALUE 1.\n"
            "       01 WS-B PIC 9 VALUE 2.\n"
            "       01 WS-C PIC 9 VALUE 3.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           IF WS-A = 1\n"
            "               IF WS-B = 2\n"
            "                   IF WS-C = 3\n"
            "                       DISPLAY 'DEEP'\n"
            "                   END-IF\n"
            "               END-IF\n"
            "           END-IF.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success

    def test_if_with_and_or(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-IF.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC 9 VALUE 1.\n"
            "       01 WS-B PIC 9 VALUE 2.\n"
            "       01 WS-C PIC 9 VALUE 3.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           IF WS-A = 1 AND WS-B = 2 OR WS-C = 3\n"
            "               DISPLAY 'MATCH'\n"
            "           END-IF.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success

    def test_if_with_not(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-IF.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC 9 VALUE 1.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           IF NOT WS-A = 1\n"
            "               DISPLAY 'NOT ONE'\n"
            "           END-IF.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success

    def test_if_period_terminated(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-IF.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC 9 VALUE 1.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           IF WS-A = 1\n"
            "               DISPLAY 'YES'.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success

    def test_if_else_period_terminated(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-IF.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC 9 VALUE 1.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           IF WS-A = 1\n"
            "               DISPLAY 'YES'\n"
            "           ELSE\n"
            "               DISPLAY 'NO'.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success

    def test_if_with_next_sentence(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-IF.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC 9 VALUE 1.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           IF WS-A = 1\n"
            "               NEXT SENTENCE.\n"
            "           STOP RUN.\n"
        )
        result = _parse_with_recovery(src)
        assert result.ast is not None

    def test_if_greater_than_or_equal(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-IF.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC 9 VALUE 5.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           IF WS-A >= 3\n"
            "               DISPLAY 'BIG'\n"
            "           END-IF.\n"
            "           IF WS-A <= 7\n"
            "               DISPLAY 'SMALL'\n"
            "           END-IF.\n"
            "           IF WS-A NOT = 0\n"
            "               DISPLAY 'NON-ZERO'\n"
            "           END-IF.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success


# ---------------------------------------------------------------------------
# IO Logger
# ---------------------------------------------------------------------------


class TestIOLoggerCallOperations:
    """Tests for IOLogger CALL operation extraction."""

    def test_call_with_using_parameters(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-IO.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-PARAM PIC X(10).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           CALL 'SUBPROG' USING WS-PARAM.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        logger = IOLogger()
        report = logger.analyze(result.ast)
        call_ops = [op for op in report.operations if op.category == "CALL"]
        assert len(call_ops) >= 1
        assert call_ops[0].target == "SUBPROG"

    def test_call_parameterless(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-IO.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           CALL 'SUBPROG'.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        logger = IOLogger()
        report = logger.analyze(result.ast)
        call_ops = [op for op in report.operations if op.category == "CALL"]
        assert len(call_ops) >= 1
        assert call_ops[0].direction == "BIDIRECTIONAL"

    def test_call_with_returning(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-IO.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-RC PIC 9(4).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           CALL 'SUBPROG' RETURNING WS-RC.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        logger = IOLogger()
        report = logger.analyze(result.ast)
        returning_ops = [
            op
            for op in report.operations
            if op.category == "CALL" and op.direction == "OUTPUT"
        ]
        assert len(returning_ops) >= 1


class TestIOLoggerConsoleIO:
    """Tests for IOLogger console IO extraction."""

    def test_display_operation(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-IO.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-LOGIC.\n"
            "           DISPLAY 'HELLO WORLD'.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        logger = IOLogger()
        report = logger.analyze(result.ast)
        console_ops = [op for op in report.operations if op.category == "CONSOLE-IO"]
        assert len(console_ops) >= 1
        assert console_ops[0].direction == "OUTPUT"


class TestIOLogReportMethods:
    """Tests for IOLogReport properties and methods."""

    def test_report_properties(self):
        report = IOLogReport(program_name="TEST")
        report.operations.append(
            IOOperation(
                category="CALL", operation="CALL X", direction="INPUT", variables=[]
            )
        )
        report.operations.append(
            IOOperation(
                category="CALL", operation="CALL Y", direction="OUTPUT", variables=[]
            )
        )
        report.operations.append(
            IOOperation(
                category="CALL",
                operation="CALL Z",
                direction="BIDIRECTIONAL",
                variables=[],
            )
        )
        assert len(report.inputs) == 1
        assert len(report.outputs) == 1
        assert len(report.bidirectional) == 1
        assert len(report.calls) == 3

    def test_report_to_dict(self):
        report = IOLogReport(program_name="TEST")
        report.operations.append(
            IOOperation(
                category="FILE-IO",
                operation="READ",
                direction="INPUT",
                variables=["REC-A"],
                target="FILE-A",
            )
        )
        d = report.to_dict()
        assert d["program_name"] == "TEST"
        assert d["summary"]["total"] == 1
        assert d["summary"]["inputs"] == 1

    def test_report_to_json(self):
        report = IOLogReport(program_name="TEST")
        report.operations.append(
            IOOperation(
                category="CONSOLE-IO",
                operation="DISPLAY",
                direction="OUTPUT",
                variables=["MSG"],
            )
        )
        j = report.to_json()
        assert '"program_name": "TEST"' in j

    def test_io_operation_to_dict(self):
        op = IOOperation(
            category="SQL",
            operation="SELECT",
            direction="OUTPUT",
            variables=["HOST-VAR"],
            target="TABLE-A",
            line=10,
            details={"sql_type": "SELECT"},
        )
        d = op.to_dict()
        assert d["category"] == "SQL"
        assert d["direction"] == "OUTPUT"
        assert d["target"] == "TABLE-A"
        assert d["line"] == 10


# ---------------------------------------------------------------------------
# Data Division Edge Cases
# ---------------------------------------------------------------------------


class TestDataDivisionEdgeCases:
    """Tests for data division parser branch coverage."""

    def test_nested_data_hierarchy(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-DATA.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-RECORD.\n"
            "           05 WS-NAME PIC X(20).\n"
            "           05 WS-ADDRESS.\n"
            "               10 WS-STREET PIC X(30).\n"
            "               10 WS-CITY PIC X(20).\n"
            "           05 WS-AGE PIC 9(3).\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success
        items = result.ast.get_data_items()
        assert len(items) >= 5

    def test_88_level_condition_names(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-DATA.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-STATUS PIC X.\n"
            "           88 WS-ACTIVE VALUE 'A'.\n"
            "           88 WS-INACTIVE VALUE 'I'.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success

    def test_occurs_clause(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-DATA.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-TABLE.\n"
            "           05 WS-ENTRY OCCURS 100 TIMES.\n"
            "               10 WS-KEY PIC 9(4).\n"
            "               10 WS-VALUE PIC X(20).\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success

    def test_redefines(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-DATA.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-DATE PIC 9(8).\n"
            "       01 WS-DATE-R REDEFINES WS-DATE.\n"
            "           05 WS-YEAR PIC 9(4).\n"
            "           05 WS-MONTH PIC 9(2).\n"
            "           05 WS-DAY PIC 9(2).\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success

    def test_usage_comp3(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-DATA.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-AMOUNT PIC S9(9)V99 USAGE COMP-3.\n"
            "       01 WS-COUNT PIC S9(4) COMP.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success

    def test_linkage_section(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-DATA.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC X.\n"
            "       LINKAGE SECTION.\n"
            "       01 LS-PARAM PIC X(100).\n"
            "       PROCEDURE DIVISION USING LS-PARAM.\n"
            "           STOP RUN.\n"
        )
        result = _parse_with_recovery(src)
        assert result.ast is not None

    def test_group_item_without_pic(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-DATA.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-GROUP.\n"
            "           05 WS-ITEM-A PIC X(10).\n"
            "           05 WS-ITEM-B PIC 9(5).\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success

    def test_value_clauses(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-DATA.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-STR PIC X(10) VALUE 'HELLO'.\n"
            "       01 WS-NUM PIC 9(4) VALUE 1234.\n"
            "       01 WS-ZERO PIC 9(4) VALUE ZEROS.\n"
            "       01 WS-SPACE PIC X(10) VALUE SPACES.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = _parse(src)
        assert result.success
