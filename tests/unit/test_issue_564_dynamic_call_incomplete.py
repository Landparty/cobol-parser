"""Regression tests for #564: DynamicCallAnalyzer reported a dynamic CALL's
``possible_values`` as complete when the CALL variable's storage is also
filled by something other than this program's MOVEs (the caller, a READ or
RETURN, EXEC SQL, EXEC CICS), and copied MOVE sources in source order rather
than execution order."""

from cobolparser import parse_cobol
from cobolparser.analysis import DynamicCallAnalyzer


def _calls(source: str) -> dict:
    result = parse_cobol(source)
    assert result.errors == []
    DynamicCallAnalyzer().analyze(result.ast)
    return {
        call.called_program: call
        for call in result.ast.find_all_by_type("CallStatement")
        if call.is_dynamic
    }


def _incomplete(call) -> bool:
    return call.get_metadata("possible_values_incomplete") is True


def _program(data: str, procedure: str, using: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. DC564.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        "           SELECT CTL-FILE ASSIGN TO CTLDD.\n"
        "           SELECT OUT-FILE ASSIGN TO OUTDD.\n"
        "           SELECT SRT-FILE ASSIGN TO SRTWK.\n"
        "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
        "       FD CTL-FILE.\n"
        "       01 CTL-REC.\n"
        "          05 CTL-PGM PIC X(8).\n"
        "       FD OUT-FILE.\n"
        "       01 OUT-REC.\n"
        "          05 OUT-PGM PIC X(8).\n"
        "       SD SRT-FILE.\n"
        "       01 SRT-REC.\n"
        "          05 SRT-PGM PIC X(8).\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-IN PIC X(8).\n" + data + "       PROCEDURE DIVISION"
        f"{(' USING ' + using) if using else ''}.\n"
        "       MAIN-PARA.\n" + procedure + "           GOBACK.\n"
    )


class TestExecutionOrderPropagation:
    """Repro 1: a MOVE that runs earlier but sits later in the source."""

    SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DC1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-DEFAULT PIC X(8) VALUE 'PGMA'.
       01 WS-PGM     PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM SET-DEFAULT
           PERFORM DO-CALL
           GOBACK.
       DO-CALL.
           MOVE WS-DEFAULT TO WS-PGM
           CALL WS-PGM.
       SET-DEFAULT.
           MOVE 'PGMB' TO WS-DEFAULT.
"""

    def test_later_source_move_reaches_the_call(self):
        call = _calls(self.SOURCE)["WS-PGM"]
        assert call.possible_values == ["PGMA", "PGMB"]
        assert not _incomplete(call)

    def test_chain_of_moves_in_reverse_source_order(self):
        source = _program(
            "       01 WS-A PIC X(8).\n"
            "       01 WS-B PIC X(8).\n"
            "       01 WS-C PIC X(8).\n",
            "           MOVE WS-B TO WS-C\n"
            "           MOVE WS-A TO WS-B\n"
            "           MOVE 'PGMZ' TO WS-A\n"
            "           CALL WS-C\n",
        )
        call = _calls(source)["WS-C"]
        assert "PGMZ" in call.possible_values

    def test_untracked_source_seen_later_still_marks_incomplete(self):
        source = _program(
            "       01 WS-A PIC X(8) VALUE 'PGMA'.\n" "       01 WS-B PIC X(8).\n",
            "           MOVE WS-A TO WS-B\n"
            "           CALL WS-B\n"
            "           MOVE WS-IN TO WS-A\n",
        )
        assert _incomplete(_calls(source)["WS-B"])


class TestExternallySuppliedStorage:
    """Repro 2: storage written by READ, by the caller, by SQL or by CICS."""

    def test_field_of_a_read_files_record(self):
        source = _program(
            "",
            "           OPEN INPUT CTL-FILE\n"
            "           READ CTL-FILE\n"
            "           IF CTL-PGM = SPACES MOVE 'PGMA' TO CTL-PGM END-IF\n"
            "           CALL CTL-PGM\n",
        )
        call = _calls(source)["CTL-PGM"]
        assert call.possible_values == ["PGMA"]
        assert _incomplete(call)

    def test_read_into_also_fills_the_record_area(self):
        source = _program(
            "",
            "           READ CTL-FILE INTO WS-IN\n"
            "           MOVE 'PGMA' TO CTL-PGM\n"
            "           CALL CTL-PGM\n",
        )
        assert _incomplete(_calls(source)["CTL-PGM"])

    def test_field_of_a_returned_sort_record(self):
        source = _program(
            "",
            "           RETURN SRT-FILE AT END CONTINUE END-RETURN\n"
            "           MOVE 'PGMA' TO SRT-PGM\n"
            "           CALL SRT-PGM\n",
        )
        assert _incomplete(_calls(source)["SRT-PGM"])

    def test_record_of_a_file_never_read_stays_complete(self):
        source = _program(
            "",
            "           READ CTL-FILE\n"
            "           MOVE 'PGMA' TO OUT-PGM\n"
            "           CALL OUT-PGM\n",
        )
        call = _calls(source)["OUT-PGM"]
        assert call.possible_values == ["PGMA"]
        assert not _incomplete(call)

    def test_linkage_parameter(self):
        source = _program(
            "       LINKAGE SECTION.\n       01 LK-PGM PIC X(8).\n",
            "           IF LK-PGM = SPACES MOVE 'PGMB' TO LK-PGM END-IF\n"
            "           CALL LK-PGM\n",
            using="LK-PGM",
        )
        call = _calls(source)["LK-PGM"]
        assert call.possible_values == ["PGMB"]
        assert _incomplete(call)

    def test_linkage_subordinate_item(self):
        source = _program(
            "       LINKAGE SECTION.\n"
            "       01 LK-AREA.\n"
            "          05 LK-PGM PIC X(8).\n",
            "           MOVE 'PGMB' TO LK-PGM\n           CALL LK-PGM\n",
            using="LK-AREA",
        )
        assert _incomplete(_calls(source)["LK-PGM"])

    def test_move_out_of_a_linkage_item_carries_the_flag(self):
        source = _program(
            "       01 WS-PGM PIC X(8).\n"
            "       LINKAGE SECTION.\n"
            "       01 LK-PGM PIC X(8).\n",
            "           MOVE 'PGMB' TO LK-PGM\n"
            "           MOVE LK-PGM TO WS-PGM\n"
            "           CALL WS-PGM\n",
            using="LK-PGM",
        )
        call = _calls(source)["WS-PGM"]
        assert call.possible_values == ["PGMB"]
        assert _incomplete(call)

    def test_sql_select_into_host_variable(self):
        source = _program(
            "       01 WS-P1 PIC X(8) VALUE 'PGMA'.\n",
            "           EXEC SQL SELECT PGM INTO :WS-P1 FROM T END-EXEC\n"
            "           CALL WS-P1\n",
        )
        call = _calls(source)["WS-P1"]
        assert call.possible_values == ["PGMA"]
        assert _incomplete(call)

    def test_sql_fetch_into_group_host_variable(self):
        source = _program(
            "       01 WS-ROW.\n          05 WS-P1 PIC X(8) VALUE 'PGMA'.\n",
            "           EXEC SQL FETCH C1 INTO :WS-ROW END-EXEC\n"
            "           CALL WS-P1\n",
        )
        assert _incomplete(_calls(source)["WS-P1"])

    def test_sql_set_host_variable(self):
        source = _program(
            "       01 WS-P1 PIC X(8) VALUE 'PGMA'.\n",
            "           EXEC SQL SET :WS-P1 = CURRENT SERVER END-EXEC\n"
            "           CALL WS-P1\n",
        )
        assert _incomplete(_calls(source)["WS-P1"])

    def test_sql_where_input_host_variable_stays_complete(self):
        source = _program(
            "       01 WS-P1 PIC X(8) VALUE 'PGMA'.\n" "       01 WS-N  PIC X(8).\n",
            "           EXEC SQL SELECT N INTO :WS-N FROM T WHERE P = :WS-P1\n"
            "           END-EXEC\n"
            "           CALL WS-P1\n",
        )
        call = _calls(source)["WS-P1"]
        assert call.possible_values == ["PGMA"]
        assert not _incomplete(call)

    def test_cics_retrieve_into(self):
        source = _program(
            "       01 WS-P2 PIC X(8) VALUE 'PGMA'.\n",
            "           EXEC CICS RETRIEVE INTO(WS-P2) END-EXEC\n"
            "           CALL WS-P2\n",
        )
        call = _calls(source)["WS-P2"]
        assert call.possible_values == ["PGMA"]
        assert _incomplete(call)

    def test_cics_assign_option(self):
        source = _program(
            "       01 WS-P3 PIC X(8) VALUE 'PGMA'.\n",
            "           EXEC CICS ASSIGN USERID(WS-P3) END-EXEC\n"
            "           CALL WS-P3\n",
        )
        assert _incomplete(_calls(source)["WS-P3"])

    def test_cics_input_option_stays_complete(self):
        source = _program(
            "       01 WS-P4 PIC X(8) VALUE 'PGMA'.\n",
            "           EXEC CICS LINK PROGRAM(WS-P4) END-EXEC\n"
            "           CALL WS-P4\n",
        )
        assert not _incomplete(_calls(source)["WS-P4"])

    def test_plain_working_storage_call_stays_complete(self):
        source = _program(
            "       01 WS-OK PIC X(8) VALUE 'PGMA'.\n",
            "           CALL WS-OK\n",
        )
        call = _calls(source)["WS-OK"]
        assert call.possible_values == ["PGMA"]
        assert not _incomplete(call)
