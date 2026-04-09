"""Tests for the 19 newly-added COBOL statement parsers.

Covers: ACCEPT, ALTER, CANCEL, CONTINUE, EXIT, GENERATE, GOBACK,
INITIALIZE, INSPECT, MERGE, RELEASE, RETURN, SEARCH, SET, SORT,
STRING, UNSTRING, UNLOCK, USE.
"""

from cobolparser import parse_cobol


def _prog(procedure_stmts: str) -> str:
    return f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-VAR   PIC X(10).
       01  WS-VAR2  PIC X(10).
       01  WS-IDX   PIC 9(4).
       01  WS-COUNT PIC 9(4).
       01  WS-PTR   PIC 9(4).
       01  WS-FLAG  PIC 9 VALUE 0.
         88  WS-FLAG-ON VALUE 1.
       PROCEDURE DIVISION.
{procedure_stmts}
           STOP RUN.
    """


# ── CONTINUE ──────────────────────────────────────────────────────


class TestContinueParser:
    def test_continue_basic(self):
        result = parse_cobol(_prog("           CONTINUE."))
        assert result.ast is not None
        stmts = result.ast.find_statements("CONTINUE")
        assert len(stmts) >= 1

    def test_continue_in_if(self):
        src = _prog(
            "           IF WS-FLAG = 1\n"
            "               CONTINUE\n"
            "           END-IF."
        )
        result = parse_cobol(src)
        assert result.ast is not None


# ── EXIT ──────────────────────────────────────────────────────────


class TestExitParser:
    def test_exit_bare(self):
        result = parse_cobol(_prog("           EXIT."))
        assert result.ast is not None
        stmts = result.ast.find_statements("EXIT")
        assert len(stmts) >= 1
        assert stmts[0].exit_type is None

    def test_exit_program(self):
        result = parse_cobol(_prog("           EXIT PROGRAM."))
        assert result.ast is not None
        stmts = result.ast.find_statements("EXIT")
        assert len(stmts) >= 1
        assert stmts[0].exit_type == "PROGRAM"

    def test_exit_paragraph(self):
        result = parse_cobol(_prog("           EXIT PARAGRAPH."))
        assert result.ast is not None
        stmts = result.ast.find_statements("EXIT")
        assert len(stmts) >= 1
        assert stmts[0].exit_type == "PARAGRAPH"

    def test_exit_section(self):
        # EXIT SECTION inside an IF to avoid procedure parser interpreting
        # EXIT as a section name followed by SECTION keyword
        src = _prog(
            "           IF WS-FLAG = 1\n"
            "               EXIT SECTION\n"
            "           END-IF."
        )
        result = parse_cobol(src)
        assert result.ast is not None

    def test_exit_perform(self):
        result = parse_cobol(_prog("           EXIT PERFORM."))
        assert result.ast is not None
        stmts = result.ast.find_statements("EXIT")
        assert len(stmts) >= 1
        assert stmts[0].exit_type == "PERFORM"

    def test_exit_perform_cycle(self):
        result = parse_cobol(_prog("           EXIT PERFORM CYCLE."))
        assert result.ast is not None
        stmts = result.ast.find_statements("EXIT")
        assert len(stmts) >= 1
        assert stmts[0].exit_type == "PERFORM CYCLE"


# ── GOBACK ────────────────────────────────────────────────────────


class TestGobackParser:
    def test_goback_basic(self):
        result = parse_cobol(_prog("           GOBACK."))
        assert result.ast is not None
        stmts = result.ast.find_statements("GOBACK")
        assert len(stmts) >= 1

    def test_goback_returning(self):
        result = parse_cobol(_prog("           GOBACK RETURNING WS-VAR."))
        assert result.ast is not None
        stmts = result.ast.find_statements("GOBACK")
        assert len(stmts) >= 1
        assert stmts[0].returning_value == "WS-VAR"


# ── CANCEL ────────────────────────────────────────────────────────


class TestCancelParser:
    def test_cancel_single(self):
        result = parse_cobol(_prog("           CANCEL 'SUBPROG'."))
        assert result.ast is not None
        stmts = result.ast.find_statements("CANCEL")
        assert len(stmts) >= 1
        assert stmts[0].program_names == ["SUBPROG"]

    def test_cancel_multiple(self):
        result = parse_cobol(_prog("           CANCEL 'PROG1' 'PROG2'."))
        assert result.ast is not None
        stmts = result.ast.find_statements("CANCEL")
        assert len(stmts) >= 1
        assert len(stmts[0].program_names) == 2


# ── ALTER ─────────────────────────────────────────────────────────


class TestAlterParser:
    def test_alter_basic(self):
        result = parse_cobol(_prog("           ALTER PARA-1 TO PROCEED TO PARA-2."))
        assert result.ast is not None
        stmts = result.ast.find_statements("ALTER")
        assert len(stmts) >= 1
        assert len(stmts[0].alterations) >= 1
        assert stmts[0].alterations[0]["from_paragraph"] == "PARA-1"
        assert stmts[0].alterations[0]["to_paragraph"] == "PARA-2"

    def test_alter_without_proceed(self):
        result = parse_cobol(_prog("           ALTER PARA-1 TO PARA-2."))
        assert result.ast is not None
        stmts = result.ast.find_statements("ALTER")
        assert len(stmts) >= 1


# ── GENERATE ──────────────────────────────────────────────────────


class TestGenerateParser:
    def test_generate_basic(self):
        result = parse_cobol(_prog("           GENERATE DETAIL-LINE."))
        assert result.ast is not None
        stmts = result.ast.find_statements("GENERATE")
        assert len(stmts) >= 1
        assert stmts[0].report_name == "DETAIL-LINE"


# ── RELEASE ───────────────────────────────────────────────────────


class TestReleaseParser:
    def test_release_basic(self):
        result = parse_cobol(_prog("           RELEASE SORT-RECORD."))
        assert result.ast is not None
        stmts = result.ast.find_statements("RELEASE")
        assert len(stmts) >= 1
        assert stmts[0].record_name == "SORT-RECORD"

    def test_release_from(self):
        result = parse_cobol(_prog("           RELEASE SORT-RECORD FROM WS-VAR."))
        assert result.ast is not None
        stmts = result.ast.find_statements("RELEASE")
        assert len(stmts) >= 1
        assert stmts[0].from_source == "WS-VAR"


# ── RETURN ────────────────────────────────────────────────────────


class TestReturnParser:
    def test_return_basic(self):
        result = parse_cobol(
            _prog("           RETURN SORT-FILE AT END DISPLAY 'DONE'.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("RETURN")
        assert len(stmts) >= 1
        assert stmts[0].file_name == "SORT-FILE"

    def test_return_into(self):
        result = parse_cobol(
            _prog("           RETURN SORT-FILE INTO WS-VAR AT END DISPLAY 'X'.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("RETURN")
        assert len(stmts) >= 1
        assert stmts[0].into_target == "WS-VAR"


# ── USE ───────────────────────────────────────────────────────────


class TestUseParser:
    def test_use_exception(self):
        result = parse_cobol(
            _prog("           USE AFTER STANDARD EXCEPTION PROCEDURE ON INPUT.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("USE")
        assert len(stmts) >= 1
        assert stmts[0].use_type == "EXCEPTION"

    def test_use_global(self):
        result = parse_cobol(
            _prog("           USE GLOBAL AFTER STANDARD ERROR PROCEDURE ON OUTPUT.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("USE")
        assert len(stmts) >= 1
        assert stmts[0].is_global is True
        assert stmts[0].use_type == "ERROR"


# ── ACCEPT ────────────────────────────────────────────────────────


class TestAcceptParser:
    def test_accept_basic(self):
        result = parse_cobol(_prog("           ACCEPT WS-VAR."))
        assert result.ast is not None
        stmts = result.ast.find_statements("ACCEPT")
        assert len(stmts) >= 1
        assert stmts[0].target == "WS-VAR"

    def test_accept_from(self):
        result = parse_cobol(_prog("           ACCEPT WS-VAR FROM CONSOLE."))
        assert result.ast is not None
        stmts = result.ast.find_statements("ACCEPT")
        assert len(stmts) >= 1
        assert stmts[0].from_source == "CONSOLE"

    def test_accept_from_date(self):
        result = parse_cobol(_prog("           ACCEPT WS-VAR FROM DATE."))
        assert result.ast is not None
        stmts = result.ast.find_statements("ACCEPT")
        assert len(stmts) >= 1
        assert stmts[0].from_source == "DATE"


# ── SEARCH ────────────────────────────────────────────────────────


class TestSearchParser:
    def test_search_basic(self):
        result = parse_cobol(
            _prog(
                "           SEARCH WS-VAR\n"
                "               WHEN WS-IDX = 1 DISPLAY 'FOUND'\n"
                "           END-SEARCH."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("SEARCH")
        assert len(stmts) >= 1
        assert stmts[0].table_name == "WS-VAR"

    def test_search_all(self):
        result = parse_cobol(
            _prog(
                "           SEARCH ALL WS-VAR\n"
                "               WHEN WS-IDX = 1 DISPLAY 'FOUND'\n"
                "           END-SEARCH."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("SEARCH")
        assert len(stmts) >= 1
        assert stmts[0].metadata.get("is_search_all") is True


# ── STRING ────────────────────────────────────────────────────────


class TestStringParser:
    def test_string_basic(self):
        result = parse_cobol(
            _prog(
                "           STRING WS-VAR DELIMITED BY SPACE\n"
                "               INTO WS-VAR2."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("STRING")
        assert len(stmts) >= 1
        assert stmts[0].into_target == "WS-VAR2"

    def test_string_with_pointer(self):
        result = parse_cobol(
            _prog(
                "           STRING WS-VAR DELIMITED BY SPACE\n"
                "               INTO WS-VAR2 WITH POINTER WS-PTR."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("STRING")
        assert len(stmts) >= 1
        assert stmts[0].pointer_variable == "WS-PTR"


# ── UNSTRING ──────────────────────────────────────────────────────


class TestUnstringParser:
    def test_unstring_basic(self):
        result = parse_cobol(
            _prog(
                "           UNSTRING WS-VAR DELIMITED BY SPACE\n"
                "               INTO WS-VAR2."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("UNSTRING")
        assert len(stmts) >= 1

    def test_unstring_multiple_into(self):
        result = parse_cobol(
            _prog(
                "           UNSTRING WS-VAR DELIMITED BY SPACE\n"
                "               INTO WS-VAR2 WS-IDX."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("UNSTRING")
        assert len(stmts) >= 1


# ── INITIALIZE ────────────────────────────────────────────────────


class TestInitializeParser:
    def test_initialize_basic(self):
        result = parse_cobol(_prog("           INITIALIZE WS-VAR."))
        assert result.ast is not None
        stmts = result.ast.find_statements("INITIALIZE")
        assert len(stmts) >= 1
        assert stmts[0].targets == ["WS-VAR"]

    def test_initialize_multiple(self):
        result = parse_cobol(_prog("           INITIALIZE WS-VAR WS-VAR2."))
        assert result.ast is not None
        stmts = result.ast.find_statements("INITIALIZE")
        assert len(stmts) >= 1
        assert len(stmts[0].targets) == 2

    def test_initialize_replacing(self):
        result = parse_cobol(
            _prog(
                "           INITIALIZE WS-VAR\n"
                "               REPLACING NUMERIC BY ZEROS."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("INITIALIZE")
        assert len(stmts) >= 1
        assert len(stmts[0].replacing_clauses) >= 1
        assert stmts[0].replacing_clauses[0]["category"] == "NUMERIC"


# ── SET ───────────────────────────────────────────────────────────


class TestSetParser:
    def test_set_to(self):
        result = parse_cobol(_prog("           SET WS-IDX TO 1."))
        assert result.ast is not None
        stmts = result.ast.find_statements("SET")
        assert len(stmts) >= 1
        assert stmts[0].set_type == "TO"
        assert stmts[0].targets == ["WS-IDX"]
        assert stmts[0].value == "1"

    def test_set_up_by(self):
        result = parse_cobol(_prog("           SET WS-IDX UP BY 1."))
        assert result.ast is not None
        stmts = result.ast.find_statements("SET")
        assert len(stmts) >= 1
        assert stmts[0].set_type == "UP_BY"

    def test_set_down_by(self):
        result = parse_cobol(_prog("           SET WS-IDX DOWN BY 1."))
        assert result.ast is not None
        stmts = result.ast.find_statements("SET")
        assert len(stmts) >= 1
        assert stmts[0].set_type == "DOWN_BY"

    def test_set_to_true(self):
        result = parse_cobol(_prog("           SET WS-FLAG-ON TO TRUE."))
        assert result.ast is not None
        stmts = result.ast.find_statements("SET")
        assert len(stmts) >= 1
        assert stmts[0].set_type == "TRUE"


# ── INSPECT ───────────────────────────────────────────────────────


class TestInspectParser:
    def test_inspect_tallying(self):
        result = parse_cobol(
            _prog(
                "           INSPECT WS-VAR TALLYING WS-COUNT\n"
                "               FOR ALL 'A'."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("INSPECT")
        assert len(stmts) >= 1
        assert stmts[0].inspect_type == "TALLYING"
        assert stmts[0].target == "WS-VAR"

    def test_inspect_replacing(self):
        result = parse_cobol(
            _prog("           INSPECT WS-VAR REPLACING ALL 'A' BY 'B'.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("INSPECT")
        assert len(stmts) >= 1
        assert stmts[0].inspect_type == "REPLACING"

    def test_inspect_converting(self):
        result = parse_cobol(
            _prog("           INSPECT WS-VAR CONVERTING 'abc' TO 'ABC'.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("INSPECT")
        assert len(stmts) >= 1
        assert stmts[0].inspect_type == "CONVERTING"
        assert stmts[0].converting_from == "abc"
        assert stmts[0].converting_to == "ABC"


# ── SORT ──────────────────────────────────────────────────────────


class TestSortParser:
    def test_sort_basic(self):
        result = parse_cobol(
            _prog(
                "           SORT SORT-FILE ON ASCENDING KEY SORT-KEY\n"
                "               USING INPUT-FILE GIVING OUTPUT-FILE."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("SORT")
        assert len(stmts) >= 1
        assert stmts[0].file_name == "SORT-FILE"
        assert len(stmts[0].keys) >= 1
        assert stmts[0].keys[0]["order"] == "ASCENDING"

    def test_sort_descending(self):
        result = parse_cobol(
            _prog(
                "           SORT SORT-FILE ON DESCENDING KEY SORT-KEY\n"
                "               USING INPUT-FILE GIVING OUTPUT-FILE."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("SORT")
        assert len(stmts) >= 1
        assert stmts[0].keys[0]["order"] == "DESCENDING"

    def test_sort_with_procedure(self):
        result = parse_cobol(
            _prog(
                "           SORT SORT-FILE ON ASCENDING KEY SORT-KEY\n"
                "               INPUT PROCEDURE IS INPUT-PARA\n"
                "               OUTPUT PROCEDURE IS OUTPUT-PARA."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("SORT")
        assert len(stmts) >= 1
        assert stmts[0].input_procedure == "INPUT-PARA"
        assert stmts[0].output_procedure == "OUTPUT-PARA"


# ── MERGE ─────────────────────────────────────────────────────────


class TestMergeParser:
    def test_merge_basic(self):
        result = parse_cobol(
            _prog(
                "           MERGE MERGE-FILE ON ASCENDING KEY MERGE-KEY\n"
                "               USING FILE-1 FILE-2 GIVING OUTPUT-FILE."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("MERGE")
        assert len(stmts) >= 1
        assert stmts[0].file_name == "MERGE-FILE"
        assert len(stmts[0].using_files) >= 2


# ── UNLOCK ────────────────────────────────────────────────────────


class TestUnlockParser:
    def test_unlock_basic(self):
        result = parse_cobol(_prog("           UNLOCK WS-VAR."))
        assert result.ast is not None
        stmts = result.ast.find_statements("UNLOCK_STATEMENT")
        assert len(stmts) >= 1

    def test_unlock_record(self):
        result = parse_cobol(_prog("           UNLOCK WS-VAR RECORD."))
        assert result.ast is not None
        stmts = result.ast.find_statements("UNLOCK_STATEMENT")
        assert len(stmts) >= 1
        assert stmts[0].record_scope == "RECORD"


# ── to_dict() serialization ──────────────────────────────────────


class TestSerialization:
    """Verify that to_dict() includes the new fields."""

    def test_all_new_statements_serialize(self):
        source = _prog(
            "           CONTINUE.\n"
            "           EXIT PROGRAM.\n"
            "           GOBACK.\n"
            "           INITIALIZE WS-VAR.\n"
            "           SET WS-IDX TO 1.\n"
            "           ACCEPT WS-VAR.\n"
            "           CANCEL 'SUBPROG'.\n"
            "           GENERATE DETAIL-LINE.\n"
        )
        result = parse_cobol(source)
        assert result.ast is not None
        json_str = result.ast.to_json()
        assert "CONTINUE" in json_str
        assert "EXIT" in json_str
        assert "GOBACK" in json_str
        assert "INITIALIZE" in json_str
        assert "SET" in json_str
        assert "ACCEPT" in json_str
        assert "CANCEL" in json_str
        assert "GENERATE" in json_str
