"""Regression tests for the 2026-07-09 "silent drops and gaps" audit.

Pins fixes for silent drops found by a re-audit of the DATA DIVISION parser,
the analysis layer, and the statement parsers that prior audits had not
covered in depth. Every case below previously returned ``success=True`` with
empty ``errors``/``warnings`` while losing real source content.

Findings pinned here:

- OCCURS ``ASCENDING/DESCENDING KEY IS ...`` was dropped entirely, and its
  presence cascaded into dropping a following ``INDEXED BY`` clause too.
  ``INDEXED BY a b`` also kept only the last index name.
- ``ProgramFlowAnalyzer`` never recursed into IO / arithmetic / STRING clause
  bodies (READ ``AT END``, WRITE ``INVALID KEY``, ``ON SIZE ERROR``,
  ``ON OVERFLOW``), so PERFORM/GO TO/CALL edges nested there vanished —
  cascading into false "unreachable" reports.
- ``REWRITE rec FROM data`` dropped the FROM source.
- ``START f KEY IS ... data-name`` dropped the KEY data-name.
- ``ACCEPT x FROM DATE YYYYMMDD`` dropped the format phrase and re-parsed it
  as a phantom paragraph; ``ACCEPT``/``UNLOCK`` with a missing operand
  swallowed the following statement's verb.
- ``STOP RUN RETURNING x`` dropped the return code.
- The DATA DIVISION clause loop dropped unrecognized clause tokens with no
  warning at all (asymmetric with the ENVIRONMENT division's SELECT handling).
"""

from cobolparser import CobolParser, ErrorRecoveryMode, parse_cobol
from cobolparser.analysis import ProgramFlowAnalyzer

DATA_TEMPLATE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROBE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
{data}
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'HI'.
"""

PROC_TEMPLATE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROBE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC PIC X(10).
       01 WS-DATA PIC X(10).
       01 WS-KEY PIC X(4).
       01 WS-RC PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
{proc}
           GOBACK.
"""


def _parse_data(data: str):
    return parse_cobol(DATA_TEMPLATE.format(data=data), filename="probe.cbl")


def _parse_proc(proc: str, mode: ErrorRecoveryMode = ErrorRecoveryMode.COLLECT_ALL):
    source = PROC_TEMPLATE.format(proc=proc)
    return CobolParser(error_recovery=mode).parse(source, filename="probe.cbl")


def _occurs(item_name: str, result):
    for di in result.ast.find_all_by_type("CobolDataItem"):
        d = di.to_dict()
        if d.get("name") == item_name and d.get("occurs_clause"):
            return d["occurs_clause"]
    return None


class TestOccursKeyAndIndex:
    def test_ascending_key_captured_and_indexed_by_survives(self):
        result = _parse_data(
            "       01 TBL.\n"
            "          05 ELT OCCURS 5 ASCENDING KEY IS ELT-K INDEXED BY IDX.\n"
            "             10 ELT-K PIC X(4)."
        )
        oc = _occurs("ELT", result)
        assert oc is not None
        assert oc.get("key_clauses") == [{"direction": "ASCENDING", "keys": ["ELT-K"]}]
        # The KEY clause no longer eats the following INDEXED BY.
        assert oc.get("indexed_by") == "IDX"

    def test_descending_key_multiple_keys_and_indexes(self):
        result = _parse_data(
            "       01 TBL.\n"
            "          05 E OCCURS 5 DESCENDING KEY IS EK EJ INDEXED BY I1 I2.\n"
            "             10 EK PIC X(4).\n"
            "             10 EJ PIC X(4)."
        )
        oc = _occurs("E", result)
        assert oc is not None
        assert oc.get("key_clauses") == [
            {"direction": "DESCENDING", "keys": ["EK", "EJ"]}
        ]
        assert oc.get("index_names") == ["I1", "I2"]
        assert oc.get("indexed_by") == "I1"

    def test_plain_indexed_by_still_works(self):
        result = _parse_data(
            "       01 TBL.\n"
            "          05 ELT OCCURS 5 INDEXED BY IDX.\n"
            "             10 ELT-K PIC X(4)."
        )
        oc = _occurs("ELT", result)
        assert oc is not None
        assert oc.get("indexed_by") == "IDX"
        assert oc.get("key_clauses") is None


class TestProgramFlowClauseBodyRecursion:
    SRC = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROBE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INF ASSIGN TO IN.
       DATA DIVISION.
       FILE SECTION.
       FD INF.
       01 IR PIC X(80).
       WORKING-STORAGE SECTION.
       01 WS-EOF PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           READ INF AT END PERFORM EOF-PARA
               NOT AT END PERFORM PROC-PARA END-READ.
           STOP RUN.
       PROC-PARA.
           DISPLAY IR.
       EOF-PARA.
           MOVE 'Y' TO WS-EOF.
"""

    def test_perform_edges_inside_read_clauses_are_emitted(self):
        result = parse_cobol(self.SRC, filename="probe.cbl")
        report = ProgramFlowAnalyzer().analyze(result.ast)
        targets = {e.target for e in report.edges if "PERFORM" in str(e.edge_type)}
        assert "PROC-PARA" in targets
        assert "EOF-PARA" in targets

    def test_paragraphs_reached_via_clause_perform_not_unreachable(self):
        result = parse_cobol(self.SRC, filename="probe.cbl")
        report = ProgramFlowAnalyzer().analyze(result.ast)
        assert "PROC-PARA" not in report.unreachable_nodes
        assert "EOF-PARA" not in report.unreachable_nodes


class TestRewriteFromSource:
    def test_rewrite_from_identifier_captured(self):
        result = _parse_proc("           REWRITE WS-REC FROM WS-DATA.")
        nodes = result.ast.find_all_by_type("IORewriteStatement")
        assert nodes
        assert nodes[0].to_dict().get("from_clause") == "WS-DATA"


class TestStartKeyName:
    def test_start_key_data_name_captured(self):
        result = _parse_proc("           START WS-REC KEY IS EQUAL TO WS-KEY.")
        nodes = result.ast.find_all_by_type("IOStartStatement")
        assert nodes
        d = nodes[0].to_dict()
        assert d.get("key_condition") == "EQUAL TO"
        assert d.get("key_name") == "WS-KEY"


class TestAcceptFromFormatPhrase:
    def test_format_phrase_captured_no_phantom_paragraph(self):
        result = _parse_proc("           ACCEPT WS-DATA FROM DATE YYYYMMDD.")
        para_names = {
            p.to_dict().get("name")
            for p in result.ast.find_all_by_type("CobolParagraph")
        }
        assert "YYYYMMDD" not in para_names
        accepts = result.ast.find_all_by_type("IOAcceptStatement")
        assert accepts
        assert "YYYYMMDD" in (accepts[0].to_dict().get("from_source") or "")

    def test_accept_missing_operand_does_not_swallow_next_statement(self):
        result = _parse_proc("           ACCEPT\n           MOVE 1 TO WS-RC.")
        assert len(result.ast.find_all_by_type("MoveStatement")) == 1


class TestUnlockMissingOperand:
    def test_unlock_missing_operand_does_not_swallow_next_statement(self):
        result = _parse_proc("           UNLOCK\n           MOVE 1 TO WS-RC.")
        assert len(result.ast.find_all_by_type("MoveStatement")) == 1


class TestStopReturning:
    def test_stop_run_returning_identifier(self):
        result = _parse_proc("           STOP RUN RETURNING WS-RC.")
        nodes = result.ast.find_all_by_type("StopStatement")
        assert nodes
        d = nodes[0].to_dict()
        assert d.get("stop_type") == "RUN"
        assert d.get("returning") == "WS-RC"


class TestDataDivisionDropWarning:
    def test_unrecognized_clause_token_warns(self):
        result = _parse_data(
            "       01 G GROUP-USAGE IS NATIONAL.\n          05 X PIC X."
        )
        assert any("GROUP-USAGE" in w for w in result.warnings)

    def test_supported_item_stays_warning_free(self):
        result = _parse_data("       01 WS-N PIC 9(4) COMP-3 VALUE 5.")
        assert result.warnings == []
