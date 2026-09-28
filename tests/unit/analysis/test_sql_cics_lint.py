"""Security/hygiene lint for embedded SQL and CICS.

Every program below is parsed for real: the point of these tests is to pin
what the analyzer does to actual parser output, including the two places
where that output is lossy (a literal's quotes are gone by the time an EXEC
block is text, and nothing says which conditions a CICS command can raise).
Assertions are on ``kind``, ``severity`` and ``symbol`` rather than on
message wording, so the messages can be improved without rewriting the
suite -- except where a specific caveat sentence is the thing being tested.

COBOL source here is fixed format: every line must stay inside column 72 or
the parser silently truncates it, which is a bug in the test, not a finding.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.sql_cics_lint import (
    CICS_NO_RESP_EXEMPT,
    KIND_CICS_ABEND_NO_HANDLER,
    KIND_CICS_NO_RESP,
    KIND_DYNAMIC_CONCATENATION,
    KIND_HARDCODED_CREDENTIALS,
    KIND_NO_SQLCODE_CHECK,
    KIND_SELECT_WITHOUT_INTO,
    SEVERITY_BY_KIND,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    SqlCicsAnalyzer,
    SqlCicsReport,
)

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXECLINT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-STMT     PIC X(200).
       01  WS-NAME     PIC X(30).
       01  WS-TABLE    PIC X(18).
       01  WS-KEY      PIC X(8).
       01  WS-RESP     PIC S9(8) COMP.
       01  WS-SAVE     PIC S9(9) COMP.
       PROCEDURE DIVISION.
"""


def _analyze(body: str) -> SqlCicsReport:
    """Parse ``HEAD + body`` and lint it, insisting the parse was clean."""
    result = parse_cobol(HEAD + body, filename="EXECLINT.cbl")
    assert result.errors == [], result.errors
    assert result.ast is not None
    return SqlCicsAnalyzer().analyze(result.ast)


def _kinds(report: SqlCicsReport) -> list[str]:
    return [violation.kind for violation in report.violations]


def _of_kind(report: SqlCicsReport, kind: str):
    return report.violations_of_kind(kind)


# ---------------------------------------------------------------------------
# The report shape itself
# ---------------------------------------------------------------------------


def test_a_clean_program_reports_nothing_and_claims_nothing():
    report = _analyze("""       MAIN-PARA.
           EXEC SQL
               SELECT NAME INTO :WS-NAME FROM CUSTOMER
           END-EXEC.
           IF SQLCODE NOT = 0
               DISPLAY 'DB2 FAILED'
           END-IF.
           GOBACK.
""")
    assert report.violations == []
    assert report.unchecked == []
    assert report.has_violations is False
    assert report.worst_severity() is None
    assert report.sql_statements == 1
    assert report.cics_statements == 0


def test_report_serialises_every_field_a_consumer_needs():
    report = _analyze("""       MAIN-PARA.
           EXEC SQL DELETE FROM CUSTOMER END-EXEC.
           GOBACK.
""")
    data = report.to_dict()
    assert data["violation_count"] == 1
    assert data["unchecked_count"] == 0
    assert data["worst_severity"] == SEVERITY_WARNING
    assert data["sql_statements"] == 1
    assert data["cics_statements"] == 0
    assert data["unchecked"] == []

    violation = data["violations"][0]
    assert set(violation) == {
        "kind",
        "severity",
        "message",
        "location",
        "symbol",
        "detail",
    }
    assert violation["kind"] == KIND_NO_SQLCODE_CHECK
    assert violation["severity"] == SEVERITY_WARNING
    assert violation["symbol"] == "DELETE"
    assert set(violation["location"]) == {"line", "column"}
    assert violation["location"]["line"] > 0
    assert isinstance(violation["detail"], dict)


def test_every_kind_grades_on_its_documented_severity():
    """``SEVERITY_BY_KIND`` is what the CLI and the lint rule will map on."""
    assert SEVERITY_BY_KIND == {
        KIND_NO_SQLCODE_CHECK: SEVERITY_WARNING,
        KIND_DYNAMIC_CONCATENATION: SEVERITY_ERROR,
        KIND_HARDCODED_CREDENTIALS: SEVERITY_ERROR,
        KIND_SELECT_WITHOUT_INTO: SEVERITY_WARNING,
        KIND_CICS_NO_RESP: SEVERITY_WARNING,
        KIND_CICS_ABEND_NO_HANDLER: SEVERITY_INFO,
    }


def test_violations_come_back_in_source_order():
    report = _analyze("""       MAIN-PARA.
           EXEC SQL DELETE FROM A END-EXEC.
           EXEC SQL DELETE FROM B END-EXEC.
           EXEC SQL DELETE FROM C END-EXEC.
           GOBACK.
""")
    lines = [violation.location.line for violation in report.violations]
    assert lines == sorted(lines)
    assert len(lines) == 3


def test_worst_severity_reports_the_highest_grade_present():
    report = _analyze("""       MAIN-PARA.
           EXEC SQL CONNECT TO DBX USER 'ADM' USING 'S3C'
           END-EXEC.
           GOBACK.
""")
    assert report.worst_severity() == SEVERITY_ERROR
    assert report.has_violations is True


def test_a_program_unit_without_a_procedure_division_says_so():
    """Nothing was examined -- which is not the same as nothing was wrong."""
    result = parse_cobol(
        """       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOPROC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC X(4).
""",
        filename="NOPROC.cbl",
    )
    assert result.ast is not None
    report = SqlCicsAnalyzer().analyze(result.ast)
    assert report.violations == []
    assert len(report.unchecked) == 1
    assert "no PROCEDURE DIVISION" in report.unchecked[0]


def test_a_program_with_no_exec_blocks_is_left_alone():
    report = _analyze("""       MAIN-PARA.
           MOVE 'X' TO WS-NAME.
           GOBACK.
""")
    assert report.violations == []
    assert report.unchecked == []
    assert report.sql_statements == 0


# ---------------------------------------------------------------------------
# SQL_NO_SQLCODE_CHECK
# ---------------------------------------------------------------------------


def test_an_unchecked_update_is_reported():
    report = _analyze("""       MAIN-PARA.
           EXEC SQL
               UPDATE CUSTOMER SET NAME = 'X'
           END-EXEC.
           DISPLAY 'DONE'.
           GOBACK.
""")
    violations = _of_kind(report, KIND_NO_SQLCODE_CHECK)
    assert len(violations) == 1
    assert violations[0].severity == SEVERITY_WARNING
    assert violations[0].symbol == "UPDATE"
    assert "SQLCODE" in violations[0].message
    assert violations[0].detail["whenever_sqlerror"] is None


@pytest.mark.parametrize(
    "checker",
    [
        "           IF SQLCODE NOT = 0 DISPLAY 'BAD' END-IF.",
        "           EVALUATE SQLSTATE\n"
        "             WHEN '00000' CONTINUE\n"
        "           END-EVALUATE.",
        "           MOVE SQLCODE TO WS-SAVE.",
        "           CALL 'DB2ERROR' USING SQLCA.",
        "           COMPUTE WS-SAVE = SQLCODE + 1.",
    ],
)
def test_any_reference_to_the_status_area_counts_as_a_check(checker):
    """The check need not be an IF -- saving, evaluating or passing the
    status area to an error routine are all real house styles."""
    report = _analyze(
        "       MAIN-PARA.\n"
        "           EXEC SQL DELETE FROM CUSTOMER END-EXEC.\n"
        f"{checker}\n"
        "           GOBACK.\n"
    )
    assert _of_kind(report, KIND_NO_SQLCODE_CHECK) == []


def test_a_check_in_a_performed_paragraph_counts():
    """The commonest correct shape in a DB2 shop: one CHECK-SQL paragraph."""
    report = _analyze("""       MAIN-PARA.
           EXEC SQL DELETE FROM CUSTOMER END-EXEC.
           PERFORM CHECK-SQL.
           GOBACK.
       CHECK-SQL.
           IF SQLCODE < 0
               DISPLAY 'DB2 FAILED'
           END-IF.
""")
    assert _of_kind(report, KIND_NO_SQLCODE_CHECK) == []


def test_a_check_in_a_performed_section_counts():
    report = _analyze("""       MAIN-SECTION SECTION.
       MAIN-PARA.
           EXEC SQL DELETE FROM CUSTOMER END-EXEC.
           PERFORM ERROR-SECTION.
           GOBACK.
       ERROR-SECTION SECTION.
       ERROR-PARA.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
""")
    assert _of_kind(report, KIND_NO_SQLCODE_CHECK) == []


def test_a_perform_cycle_does_not_hang_the_walk():
    report = _analyze("""       MAIN-PARA.
           EXEC SQL DELETE FROM CUSTOMER END-EXEC.
           PERFORM LOOP-A.
           GOBACK.
       LOOP-A.
           PERFORM LOOP-B.
       LOOP-B.
           PERFORM LOOP-A.
""")
    assert len(_of_kind(report, KIND_NO_SQLCODE_CHECK)) == 1


def test_a_check_before_the_statement_does_not_count():
    """Reading SQLCODE first tells you about the *previous* statement."""
    report = _analyze("""       MAIN-PARA.
           IF SQLCODE NOT = 0 DISPLAY 'BAD' END-IF.
           EXEC SQL DELETE FROM CUSTOMER END-EXEC.
           GOBACK.
""")
    assert len(_of_kind(report, KIND_NO_SQLCODE_CHECK)) == 1


def test_a_statement_nested_in_an_if_is_still_checked():
    report = _analyze("""       MAIN-PARA.
           IF WS-NAME = 'A'
               EXEC SQL DELETE FROM CUSTOMER END-EXEC
           END-IF.
           GOBACK.
""")
    assert len(_of_kind(report, KIND_NO_SQLCODE_CHECK)) == 1


def test_a_check_after_the_if_covers_a_statement_inside_it():
    report = _analyze("""       MAIN-PARA.
           IF WS-NAME = 'A'
               EXEC SQL DELETE FROM CUSTOMER END-EXEC
           END-IF.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           GOBACK.
""")
    assert _of_kind(report, KIND_NO_SQLCODE_CHECK) == []


def test_statements_written_before_any_paragraph_header_share_one_window():
    """The parser gives each pre-paragraph statement its own anonymous
    paragraph; treating those as real paragraph boundaries would report a
    check written on the very next line."""
    result = parse_cobol(
        """       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOPARA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NAME PIC X(4).
       PROCEDURE DIVISION.
           EXEC SQL SELECT A INTO :WS-NAME FROM T END-EXEC.
           IF SQLCODE NOT = 0
               DISPLAY 'BAD'
           END-IF.
           GOBACK.
""",
        filename="NOPARA.cbl",
    )
    assert result.errors == []
    assert result.ast is not None
    report = SqlCicsAnalyzer().analyze(result.ast)
    assert _of_kind(report, KIND_NO_SQLCODE_CHECK) == []


@pytest.mark.parametrize(
    "declaration",
    [
        "           EXEC SQL DECLARE C1 CURSOR FOR\n"
        "               SELECT NAME FROM CUSTOMER\n"
        "           END-EXEC.",
        "           EXEC SQL DECLARE S1 STATEMENT END-EXEC.",
        "           EXEC SQL INCLUDE SQLCA END-EXEC.",
        "           EXEC SQL BEGIN DECLARE SECTION END-EXEC.",
        "           EXEC SQL END DECLARE SECTION END-EXEC.",
    ],
)
def test_a_precompiler_declaration_is_never_flagged(declaration):
    """None of these executes, so none of them sets SQLCODE."""
    report = _analyze(f"       MAIN-PARA.\n{declaration}\n           GOBACK.\n")
    assert report.violations == []


def test_declare_cursor_is_not_a_select_without_into_either():
    report = _analyze("""       MAIN-PARA.
           EXEC SQL DECLARE C1 CURSOR FOR
               SELECT NAME FROM CUSTOMER
           END-EXEC.
           GOBACK.
""")
    assert report.violations == []
    assert report.sql_statements == 1


# ---------------------------------------------------------------------------
# WHENEVER
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    ["GOTO ERR-PARA", "GO TO ERR-PARA", "PERFORM ERR-PARA"],
)
def test_an_active_whenever_sqlerror_handler_suppresses_the_finding(action):
    report = _analyze(f"""       MAIN-PARA.
           EXEC SQL WHENEVER SQLERROR {action} END-EXEC.
           EXEC SQL DELETE FROM CUSTOMER END-EXEC.
           GOBACK.
       ERR-PARA.
           DISPLAY 'DB2 FAILED'.
""")
    assert _of_kind(report, KIND_NO_SQLCODE_CHECK) == []


def test_whenever_sqlerror_continue_is_not_a_handler():
    """CONTINUE is the precompiler default spelled out; it handles nothing."""
    report = _analyze("""       MAIN-PARA.
           EXEC SQL WHENEVER SQLERROR CONTINUE END-EXEC.
           EXEC SQL DELETE FROM CUSTOMER END-EXEC.
           GOBACK.
""")
    violations = _of_kind(report, KIND_NO_SQLCODE_CHECK)
    assert len(violations) == 1
    assert violations[0].detail["whenever_sqlerror"] == "CONTINUE"


def test_whenever_takes_effect_in_source_order_only():
    """A statement written above the directive is not covered by it -- which
    is exactly how the precompiler reads the file."""
    report = _analyze("""       MAIN-PARA.
           EXEC SQL DELETE FROM BEFORE-TAB END-EXEC.
           EXEC SQL WHENEVER SQLERROR GOTO ERR-PARA END-EXEC.
           EXEC SQL DELETE FROM AFTER-TAB END-EXEC.
           GOBACK.
       ERR-PARA.
           DISPLAY 'DB2 FAILED'.
""")
    violations = _of_kind(report, KIND_NO_SQLCODE_CHECK)
    assert len(violations) == 1
    assert violations[0].detail["sql"] == "DELETE FROM BEFORE-TAB"


def test_a_later_whenever_continue_cancels_an_earlier_handler():
    report = _analyze("""       MAIN-PARA.
           EXEC SQL WHENEVER SQLERROR GOTO ERR-PARA END-EXEC.
           EXEC SQL DELETE FROM COVERED-TAB END-EXEC.
           EXEC SQL WHENEVER SQLERROR CONTINUE END-EXEC.
           EXEC SQL DELETE FROM BARE-TAB END-EXEC.
           GOBACK.
       ERR-PARA.
           DISPLAY 'DB2 FAILED'.
""")
    violations = _of_kind(report, KIND_NO_SQLCODE_CHECK)
    assert len(violations) == 1
    assert violations[0].detail["sql"] == "DELETE FROM BARE-TAB"


def test_a_whenever_not_found_handler_does_not_cover_sqlerror():
    """NOT FOUND is +100 only; a negative SQLCODE still falls through."""
    report = _analyze("""       MAIN-PARA.
           EXEC SQL WHENEVER NOT FOUND GOTO EOF-PARA END-EXEC.
           EXEC SQL DELETE FROM CUSTOMER END-EXEC.
           GOBACK.
       EOF-PARA.
           DISPLAY 'NONE'.
""")
    assert len(_of_kind(report, KIND_NO_SQLCODE_CHECK)) == 1


def test_an_undecipherable_whenever_lands_in_unchecked():
    report = _analyze("""       MAIN-PARA.
           EXEC SQL WHENEVER SQLBOOM GOTO ERR-PARA END-EXEC.
           GOBACK.
       ERR-PARA.
           DISPLAY 'DB2 FAILED'.
""")
    assert report.violations == []
    assert len(report.unchecked) == 1
    assert "WHENEVER" in report.unchecked[0]
    assert "could not be decomposed" in report.unchecked[0]


# ---------------------------------------------------------------------------
# SQL_DYNAMIC_CONCATENATION
# ---------------------------------------------------------------------------


def test_a_prepare_of_a_string_built_statement_is_an_injection_finding():
    report = _analyze("""       MAIN-PARA.
           STRING 'SELECT * FROM ' DELIMITED BY SIZE
                  WS-TABLE DELIMITED BY SIZE
                  INTO WS-STMT
           END-STRING.
           EXEC SQL PREPARE S1 FROM :WS-STMT END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           GOBACK.
""")
    violations = _of_kind(report, KIND_DYNAMIC_CONCATENATION)
    assert len(violations) == 1
    violation = violations[0]
    assert violation.severity == SEVERITY_ERROR
    assert violation.symbol == "WS-STMT"
    assert violation.detail["built_by"] == ["STRING"]
    assert violation.detail["sources"] == ["WS-TABLE"]
    assert violation.detail["assignments"][0]["kind"] == "STRING"
    assert 0 < violation.detail["assignments"][0]["line"] < violation.location.line
    assert "injection" in violation.message


def test_an_execute_immediate_of_a_moved_in_variable_is_a_finding():
    report = _analyze("""       MAIN-PARA.
           MOVE WS-NAME TO WS-STMT.
           EXEC SQL EXECUTE IMMEDIATE :WS-STMT END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           GOBACK.
""")
    violations = _of_kind(report, KIND_DYNAMIC_CONCATENATION)
    assert len(violations) == 1
    assert violations[0].detail["built_by"] == ["MOVE"]
    assert violations[0].detail["sources"] == ["WS-NAME"]
    assert violations[0].detail["host_variable"] == "WS-STMT"


def test_a_reference_modified_move_target_is_still_traced():
    report = _analyze("""       MAIN-PARA.
           MOVE WS-NAME TO WS-STMT(1:30).
           EXEC SQL EXECUTE IMMEDIATE :WS-STMT END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           GOBACK.
""")
    assert len(_of_kind(report, KIND_DYNAMIC_CONCATENATION)) == 1


@pytest.mark.parametrize("source", ["'SELECT 1 FROM SYSDUMMY1'", "SPACES", "ALL", "0"])
def test_a_statement_moved_in_from_a_literal_is_not_a_finding(source):
    report = _analyze(f"""       MAIN-PARA.
           MOVE {source} TO WS-STMT.
           EXEC SQL EXECUTE IMMEDIATE :WS-STMT END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           GOBACK.
""")
    assert _of_kind(report, KIND_DYNAMIC_CONCATENATION) == []
    assert report.unchecked == []


def test_several_writers_produce_one_finding_that_lists_them_all():
    """The defect is that untrusted text reaches this PREPARE -- once."""
    report = _analyze("""       MAIN-PARA.
           MOVE WS-NAME TO WS-STMT.
           STRING 'SELECT * FROM ' DELIMITED BY SIZE
                  WS-TABLE DELIMITED BY SIZE
                  INTO WS-STMT
           END-STRING.
           EXEC SQL PREPARE S1 FROM :WS-STMT END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           GOBACK.
""")
    violations = _of_kind(report, KIND_DYNAMIC_CONCATENATION)
    assert len(violations) == 1
    detail = violations[0].detail
    assert detail["built_by"] == ["MOVE", "STRING"]
    assert detail["sources"] == ["WS-NAME", "WS-TABLE"]
    assert [entry["kind"] for entry in detail["assignments"]] == ["MOVE", "STRING"]
    assert "assembled by" in violations[0].message


def test_an_untraceable_host_variable_lands_in_unchecked_not_in_findings():
    """The house rule: nothing traced means nothing claimed, in either
    direction."""
    report = _analyze("""       MAIN-PARA.
           EXEC SQL PREPARE S1 FROM :WS-STMT END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           GOBACK.
""")
    assert report.violations == []
    assert len(report.unchecked) == 1
    assert ":WS-STMT" in report.unchecked[0]
    assert "could not be traced" in report.unchecked[0]


def test_a_string_of_undeclared_operands_lands_in_unchecked():
    """The lexer drops a literal's quotes, so a STRING whose operands name
    nothing declared cannot be told from a STRING of pure literals."""
    report = _analyze("""       MAIN-PARA.
           STRING 'SELECT 1 ' DELIMITED BY SIZE
                  'FROM SYSDUMMY1' DELIMITED BY SIZE
                  INTO WS-STMT
           END-STRING.
           EXEC SQL PREPARE S1 FROM :WS-STMT END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           GOBACK.
""")
    assert _of_kind(report, KIND_DYNAMIC_CONCATENATION) == []
    assert len(report.unchecked) == 1
    assert "STRING" in report.unchecked[0]
    assert "quotes" in report.unchecked[0]


def test_execute_with_parameter_markers_is_the_safe_idiom():
    """``EXECUTE stmt USING :hv`` passes values, not text: never flagged."""
    report = _analyze("""       MAIN-PARA.
           MOVE WS-NAME TO WS-STMT.
           EXEC SQL PREPARE S1 FROM 'SELECT A FROM T WHERE B = ?'
           END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           EXEC SQL EXECUTE S1 USING :WS-KEY END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           GOBACK.
""")
    assert _of_kind(report, KIND_DYNAMIC_CONCATENATION) == []
    assert report.unchecked == []


def test_a_static_statement_using_a_host_variable_is_not_dynamic_sql():
    report = _analyze("""       MAIN-PARA.
           MOVE WS-NAME TO WS-KEY.
           EXEC SQL
               DELETE FROM CUSTOMER WHERE ID = :WS-KEY
           END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           GOBACK.
""")
    assert report.violations == []
    assert report.unchecked == []


# ---------------------------------------------------------------------------
# SQL_HARDCODED_CREDENTIALS
# ---------------------------------------------------------------------------


def test_a_connect_with_a_literal_password_is_an_error():
    report = _analyze("""       MAIN-PARA.
           EXEC SQL
               CONNECT TO DBPROD USER 'DBADMIN' USING 'S3CRET'
           END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           GOBACK.
""")
    violations = _of_kind(report, KIND_HARDCODED_CREDENTIALS)
    assert len(violations) == 2
    assert all(v.severity == SEVERITY_ERROR for v in violations)
    assert all(v.symbol == "CONNECT" for v in violations)
    by_keyword = {v.detail["keyword"]: v.detail["credential"] for v in violations}
    assert by_keyword == {"USER": "authorization id", "USING": "password"}


def test_a_connect_through_host_variables_is_clean():
    report = _analyze("""       MAIN-PARA.
           EXEC SQL
               CONNECT TO DBPROD USER :WS-NAME USING :WS-KEY
           END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           GOBACK.
""")
    assert report.violations == []
    assert report.unchecked == []


def test_connect_reset_carries_no_credential():
    report = _analyze("""       MAIN-PARA.
           EXEC SQL CONNECT RESET END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           GOBACK.
""")
    assert report.violations == []


def test_a_credential_operand_naming_a_declared_item_is_unchecked():
    """``USING WS-KEY`` -- no colon, no quotes -- names a declared item
    written without its colon. It is not called a hardcoded password."""
    report = _analyze("""       MAIN-PARA.
           EXEC SQL
               CONNECT TO DBPROD USER :WS-NAME USING WS-KEY
           END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           GOBACK.
""")
    assert _of_kind(report, KIND_HARDCODED_CREDENTIALS) == []
    assert len(report.unchecked) == 1
    assert "WS-KEY" in report.unchecked[0]
    assert "could not be determined" in report.unchecked[0]


def test_a_quoted_credential_spelling_a_declared_name_is_still_a_literal():
    """EXEC SQL text keeps a literal's quotes: ``USING 'WS-KEY'`` is the
    password WS-KEY, not the data item. Before the quotes were kept the two
    spellings collapsed and this was filed as unchecked."""
    report = _analyze("""       MAIN-PARA.
           EXEC SQL
               CONNECT TO DBPROD USER :WS-NAME USING 'WS-KEY'
           END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           GOBACK.
""")
    assert len(_of_kind(report, KIND_HARDCODED_CREDENTIALS)) == 1
    assert report.unchecked == []


def test_the_word_user_outside_a_connect_is_not_a_credential():
    report = _analyze("""       MAIN-PARA.
           EXEC SQL
               SELECT NAME INTO :WS-NAME FROM CUSTOMER
                WHERE OWNER = USER
           END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           GOBACK.
""")
    assert report.violations == []


# ---------------------------------------------------------------------------
# SQL_SELECT_WITHOUT_INTO
# ---------------------------------------------------------------------------


def test_a_singleton_select_with_no_into_is_reported():
    report = _analyze("""       MAIN-PARA.
           EXEC SQL
               SELECT NAME FROM CUSTOMER WHERE ID = :WS-KEY
           END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           GOBACK.
""")
    violations = _of_kind(report, KIND_SELECT_WITHOUT_INTO)
    assert len(violations) == 1
    assert violations[0].severity == SEVERITY_WARNING
    assert violations[0].symbol == "SELECT"


def test_a_select_into_a_host_variable_is_clean():
    report = _analyze("""       MAIN-PARA.
           EXEC SQL
               SELECT NAME INTO :WS-NAME FROM CUSTOMER
           END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           GOBACK.
""")
    assert _of_kind(report, KIND_SELECT_WITHOUT_INTO) == []


def test_a_fetch_is_not_a_select_without_into():
    report = _analyze("""       MAIN-PARA.
           EXEC SQL FETCH C1 INTO :WS-NAME END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           GOBACK.
""")
    assert report.violations == []


# ---------------------------------------------------------------------------
# CICS_NO_RESP_HANDLING
# ---------------------------------------------------------------------------


def test_a_cics_read_with_no_error_handling_is_reported():
    report = _analyze("""       MAIN-PARA.
           EXEC CICS READ FILE('CUSTFIL')
                INTO(WS-NAME) RIDFLD(WS-KEY)
           END-EXEC.
           GOBACK.
""")
    violations = _of_kind(report, KIND_CICS_NO_RESP)
    assert len(violations) == 1
    assert violations[0].severity == SEVERITY_WARNING
    assert violations[0].symbol == "READ"
    assert "RESP" in violations[0].message
    assert report.cics_statements == 1


@pytest.mark.parametrize("option", ["RESP(WS-RESP)", "RESP2(WS-RESP)", "NOHANDLE"])
def test_an_explicit_response_option_suppresses_the_finding(option):
    report = _analyze(f"""       MAIN-PARA.
           EXEC CICS READ FILE('CUSTFIL')
                INTO(WS-NAME) RIDFLD(WS-KEY) {option}
           END-EXEC.
           GOBACK.
""")
    assert report.violations == []
    assert report.unchecked == []


def test_an_active_handle_condition_error_suppresses_the_finding():
    report = _analyze("""       MAIN-PARA.
           EXEC CICS HANDLE CONDITION ERROR(ERR-PARA)
           END-EXEC.
           EXEC CICS READ FILE('CUSTFIL')
                INTO(WS-NAME) RIDFLD(WS-KEY)
           END-EXEC.
           GOBACK.
       ERR-PARA.
           DISPLAY 'CICS FAILED'.
""")
    assert report.violations == []
    assert report.unchecked == []


def test_a_handle_condition_naming_only_specific_conditions_is_unchecked():
    """Nothing in the AST says which conditions a READ can raise, so a
    NOTFND-only handler is neither coverage nor a finding."""
    report = _analyze("""       MAIN-PARA.
           EXEC CICS HANDLE CONDITION NOTFND(NF-PARA)
           END-EXEC.
           EXEC CICS READ FILE('CUSTFIL')
                INTO(WS-NAME) RIDFLD(WS-KEY)
           END-EXEC.
           GOBACK.
       NF-PARA.
           DISPLAY 'NOT FOUND'.
""")
    assert report.violations == []
    assert len(report.unchecked) == 1
    assert "NOTFND" in report.unchecked[0]
    assert "could not be graded" in report.unchecked[0]


def test_a_bare_handle_condition_restores_the_default_action():
    """``HANDLE CONDITION ERROR`` with no label hands the condition back to
    CICS -- it cancels the handler rather than establishing one."""
    report = _analyze("""       MAIN-PARA.
           EXEC CICS HANDLE CONDITION ERROR(ERR-PARA)
           END-EXEC.
           EXEC CICS HANDLE CONDITION ERROR END-EXEC.
           EXEC CICS READ FILE('CUSTFIL')
                INTO(WS-NAME) RIDFLD(WS-KEY)
           END-EXEC.
           GOBACK.
       ERR-PARA.
           DISPLAY 'CICS FAILED'.
""")
    assert len(_of_kind(report, KIND_CICS_NO_RESP)) == 1


def test_ignore_condition_cancels_an_established_handler():
    report = _analyze("""       MAIN-PARA.
           EXEC CICS HANDLE CONDITION ERROR(ERR-PARA)
           END-EXEC.
           EXEC CICS IGNORE CONDITION ERROR END-EXEC.
           EXEC CICS READ FILE('CUSTFIL')
                INTO(WS-NAME) RIDFLD(WS-KEY)
           END-EXEC.
           GOBACK.
       ERR-PARA.
           DISPLAY 'CICS FAILED'.
""")
    assert len(_of_kind(report, KIND_CICS_NO_RESP)) == 1


def test_push_handle_suspends_and_pop_handle_restores():
    report = _analyze("""       MAIN-PARA.
           EXEC CICS HANDLE CONDITION ERROR(ERR-PARA)
           END-EXEC.
           EXEC CICS PUSH HANDLE END-EXEC.
           EXEC CICS READ FILE('CUSTFIL')
                INTO(WS-NAME) RIDFLD(WS-KEY)
           END-EXEC.
           EXEC CICS POP HANDLE END-EXEC.
           EXEC CICS READ FILE('CUSTFIL')
                INTO(WS-NAME) RIDFLD(WS-KEY)
           END-EXEC.
           GOBACK.
       ERR-PARA.
           DISPLAY 'CICS FAILED'.
""")
    violations = _of_kind(report, KIND_CICS_NO_RESP)
    assert len(violations) == 1
    assert violations[0].location.line == 16
    assert report.unchecked == []


def test_a_pop_handle_with_no_push_is_reported_as_unchecked():
    report = _analyze("""       MAIN-PARA.
           EXEC CICS POP HANDLE END-EXEC.
           GOBACK.
""")
    assert report.violations == []
    assert len(report.unchecked) == 1
    assert "POP HANDLE" in report.unchecked[0]


@pytest.mark.parametrize("command", sorted(CICS_NO_RESP_EXEMPT))
def test_every_exempt_command_carries_a_documented_reason(command):
    reason = CICS_NO_RESP_EXEMPT[command]
    assert reason and reason[0].islower()


@pytest.mark.parametrize(
    "block",
    [
        "           EXEC CICS RETURN TRANSID('AB01') END-EXEC.",
        "           EXEC CICS XCTL PROGRAM('NEXTPGM') END-EXEC.",
        "           EXEC CICS SEND MAP('M1') MAPSET('S1') END-EXEC.",
        "           EXEC CICS ASKTIME ABSTIME(WS-SAVE) END-EXEC.",
    ],
)
def test_an_exempt_command_is_not_flagged_for_a_missing_resp(block):
    report = _analyze(f"       MAIN-PARA.\n{block}\n           GOBACK.\n")
    assert _of_kind(report, KIND_CICS_NO_RESP) == []


def test_a_cics_block_with_no_command_verb_is_unchecked():
    report = _analyze("""       MAIN-PARA.
           EXEC CICS END-EXEC.
           GOBACK.
""")
    assert report.violations == []
    assert len(report.unchecked) == 1
    assert "command verb could not be identified" in report.unchecked[0]


def test_a_block_that_ran_past_its_end_exec_is_unchecked():
    """A fixed-format line truncated at column 72 loses its END-EXEC, and the
    collector swallows the next EXEC block; the option list that comes back
    is not this command's, so nothing is claimed from it."""
    report = _analyze("""       MAIN-PARA.
           EXEC CICS READ FILE('F') INTO(WS-NAME) RIDFLD(WS-KEY) END-EXEC.
           EXEC CICS LINK PROGRAM('SUBPGM') END-EXEC.
           GOBACK.
""")
    assert report.violations == []
    assert len(report.unchecked) == 1
    assert "ran into the following EXEC block" in report.unchecked[0]


# ---------------------------------------------------------------------------
# CICS_ABEND_WITHOUT_HANDLER
# ---------------------------------------------------------------------------


def test_an_abend_with_no_handler_is_reported_as_info():
    report = _analyze("""       MAIN-PARA.
           EXEC CICS ABEND ABCODE('X999') END-EXEC.
           GOBACK.
""")
    violations = _of_kind(report, KIND_CICS_ABEND_NO_HANDLER)
    assert len(violations) == 1
    assert violations[0].severity == SEVERITY_INFO
    assert violations[0].symbol == "ABEND"
    assert violations[0].detail["options"] == ["ABCODE"]
    assert _of_kind(report, KIND_CICS_NO_RESP) == []


def test_an_established_handle_abend_suppresses_the_abend_finding():
    report = _analyze("""       MAIN-PARA.
           EXEC CICS HANDLE ABEND LABEL(AB-PARA) END-EXEC.
           EXEC CICS ABEND ABCODE('X999') END-EXEC.
           GOBACK.
       AB-PARA.
           DISPLAY 'ABENDING'.
""")
    assert report.violations == []


def test_handle_abend_program_also_counts_as_a_handler():
    report = _analyze("""       MAIN-PARA.
           EXEC CICS HANDLE ABEND PROGRAM('ABPGM') END-EXEC.
           EXEC CICS ABEND ABCODE('X999') END-EXEC.
           GOBACK.
""")
    assert report.violations == []


def test_handle_abend_cancel_takes_the_handler_away_again():
    report = _analyze("""       MAIN-PARA.
           EXEC CICS HANDLE ABEND LABEL(AB-PARA) END-EXEC.
           EXEC CICS HANDLE ABEND CANCEL END-EXEC.
           EXEC CICS ABEND ABCODE('X999') END-EXEC.
           GOBACK.
       AB-PARA.
           DISPLAY 'ABENDING'.
""")
    assert len(_of_kind(report, KIND_CICS_ABEND_NO_HANDLER)) == 1


def test_handle_abend_reset_says_it_could_not_be_resolved():
    report = _analyze("""       MAIN-PARA.
           EXEC CICS HANDLE ABEND RESET END-EXEC.
           GOBACK.
""")
    assert report.violations == []
    assert len(report.unchecked) == 1
    assert "RESET" in report.unchecked[0]


def test_a_handle_condition_naming_nothing_is_reported_as_unmodelled():
    report = _analyze("""       MAIN-PARA.
           EXEC CICS HANDLE CONDITION END-EXEC.
           GOBACK.
""")
    assert report.violations == []
    assert len(report.unchecked) == 1
    assert "names no condition" in report.unchecked[0]


def test_a_handle_that_is_neither_condition_abend_nor_aid_is_unmodelled():
    report = _analyze("""       MAIN-PARA.
           EXEC CICS HANDLE END-EXEC.
           GOBACK.
""")
    assert report.violations == []
    assert len(report.unchecked) == 1
    assert "was not modelled" in report.unchecked[0]


def test_handle_aid_is_not_a_condition_handler_and_is_not_a_finding():
    report = _analyze("""       MAIN-PARA.
           EXEC CICS HANDLE AID PF3(EXIT-PARA) END-EXEC.
           GOBACK.
       EXIT-PARA.
           DISPLAY 'PF3'.
""")
    assert report.violations == []
    assert report.unchecked == []


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def test_only_the_program_unit_it_was_handed_is_linted():
    """Like every analyzer here, contained programs are the caller's job."""
    source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTER.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL DELETE FROM OUTER-TAB END-EXEC.
           GOBACK.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER.
       PROCEDURE DIVISION.
       INNER-PARA.
           EXEC SQL DELETE FROM INNER-TAB END-EXEC.
           GOBACK.
       END PROGRAM INNER.
       END PROGRAM OUTER.
"""
    result = parse_cobol(source, filename="OUTER.cbl")
    assert result.ast is not None
    report = SqlCicsAnalyzer().analyze(result.ast)
    assert len(_of_kind(report, KIND_NO_SQLCODE_CHECK)) == 1
    assert report.violations[0].location.line == 5


def test_a_mixed_program_reports_each_concern_once():
    report = _analyze("""       MAIN-PARA.
           EXEC SQL
               CONNECT TO DBPROD USER :WS-NAME USING 'S3CRET'
           END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           EXEC SQL
               SELECT NAME FROM CUSTOMER
           END-EXEC.
           IF SQLCODE < 0 DISPLAY 'BAD' END-IF.
           EXEC CICS LINK PROGRAM('SUBPGM') END-EXEC.
           EXEC CICS ABEND ABCODE('X999') END-EXEC.
           GOBACK.
""")
    assert _kinds(report) == [
        KIND_HARDCODED_CREDENTIALS,
        KIND_SELECT_WITHOUT_INTO,
        KIND_CICS_NO_RESP,
        KIND_CICS_ABEND_NO_HANDLER,
    ]
    assert report.worst_severity() == SEVERITY_ERROR
    assert report.sql_statements == 2
    assert report.cics_statements == 2


class TestReviewFollowUps:
    """Review follow-ups on PR #212."""

    def test_declare_global_temporary_table_is_executable(self):
        report = _analyze(
            "       MAIN.\n"
            "           EXEC SQL DECLARE GLOBAL TEMPORARY TABLE SESSION.T\n"
            "               (A INT) END-EXEC\n"
            "           STOP RUN.\n"
        )
        assert "SQL_NO_SQLCODE_CHECK" in _kinds(report)

    def test_declare_cursor_table_and_statement_stay_non_executable(self):
        report = _analyze(
            "       MAIN.\n"
            "           EXEC SQL DECLARE C1 CURSOR FOR SELECT A FROM T END-EXEC\n"
            "           EXEC SQL DECLARE T TABLE (A INT) END-EXEC\n"
            "           EXEC SQL DECLARE S1 STATEMENT END-EXEC\n"
            "           STOP RUN.\n"
        )
        assert "SQL_NO_SQLCODE_CHECK" not in _kinds(report)
