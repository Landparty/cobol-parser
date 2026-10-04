"""DCLGEN ``DECLARE TABLE`` vs. COBOL host variable type checking.

Each program below is a mismatch a DB2 precompiler accepts and a runtime
quietly acts on -- which is the whole reason the check exists. The tests
assert on ``kind`` and ``severity`` rather than on message wording, so the
messages can be improved without rewriting the suite.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.dclgen_check import DclgenChecker

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DCLTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
"""

TAIL = """       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
               SELECT {columns}
                 INTO {hostvars}
                 FROM CUSTOMER
           END-EXEC.
           GOBACK.
"""


def _program(declare: str, structure: str, columns: str, hostvars: str) -> str:
    return HEAD + declare + structure + TAIL.format(columns=columns, hostvars=hostvars)


def _check(source: str):
    result = parse_cobol(source, filename="DCLTEST.cbl")
    assert result.ast is not None
    return DclgenChecker().check(result.ast)


def _kinds(report) -> set[str]:
    return {violation.kind for violation in report.violations}


def _by_kind(report, kind):
    return [v for v in report.violations if v.kind == kind]


ONE_COLUMN = """           EXEC SQL DECLARE CUSTOMER TABLE
               ({column})
           END-EXEC.
"""


def _one(column: str, item: str):
    return _program(
        ONE_COLUMN.format(column=column),
        f"       01  DCLCUSTOMER.\n           05  {item}\n",
        "CUST_VAL",
        ":CUST-VAL",
    )


# ---------------------------------------------------------------------------
# The pairing itself
# ---------------------------------------------------------------------------


def test_an_underscored_column_is_matched_to_its_hyphenated_host_variable():
    """DCLGEN substitutes ``-`` for ``_`` itself; a checker that compared the
    names verbatim would check nothing while looking like it had."""
    report = _check(_one("CUST_VAL CHAR(10) NOT NULL", "CUST-VAL PIC X(10)."))
    assert report.checked == ["CUST-VAL"]
    assert report.unchecked == {}
    assert report.violations == []


def test_a_host_variable_with_no_column_is_reported_as_unchecked():
    report = _check(
        _program(
            ONE_COLUMN.format(column="CUST_VAL CHAR(10) NOT NULL"),
            "       01  WS-OTHER    PIC X(4).\n",
            "CUST_VAL",
            ":WS-OTHER",
        )
    )
    assert report.checked == []
    assert "WS-OTHER" in report.unchecked
    assert "column of this name" in report.unchecked["WS-OTHER"]


def test_a_program_with_no_declare_table_is_unchecked_not_clean():
    source = (
        HEAD
        + "       01  WS-ID   PIC S9(9) COMP.\n"
        + TAIL.format(columns="CUST_ID", hostvars=":WS-ID")
    )
    report = _check(source)
    assert report.violations == []
    assert report.checked == []
    assert report.unchecked["WS-ID"] == "no DECLARE TABLE in this program"


def test_the_declared_tables_are_reported_with_their_column_counts():
    report = _check(_one("CUST_VAL CHAR(10) NOT NULL", "CUST-VAL PIC X(10)."))
    assert report.tables == {"CUSTOMER": 1}


# ---------------------------------------------------------------------------
# The individual checks
# ---------------------------------------------------------------------------


def test_a_short_host_variable_truncates_every_fetch():
    report = _check(_one("CUST_VAL CHAR(30) NOT NULL", "CUST-VAL PIC X(20)."))
    violation = _by_kind(report, "length")[0]
    assert violation.severity == "error"
    assert violation.expected_picture == "X(30)"
    assert violation.actual_picture == "X(20)"
    assert violation.column == "CUST_VAL"
    assert violation.table == "CUSTOMER"


def test_an_over_long_host_variable_only_wastes_space():
    report = _check(_one("CUST_VAL CHAR(10) NOT NULL", "CUST-VAL PIC X(20)."))
    violation = _by_kind(report, "length")[0]
    assert violation.severity == "info"


def test_a_dropped_decimal_place_is_an_error():
    report = _check(
        _one("CUST_VAL DECIMAL(9,2) NOT NULL", "CUST-VAL PIC S9(7)V9 COMP-3.")
    )
    violation = _by_kind(report, "scale")[0]
    assert violation.severity == "error"
    assert violation.expected_picture == "S9(7)V9(2)"


def test_too_few_integer_digits_is_an_error():
    report = _check(
        _one("CUST_VAL DECIMAL(9,2) NOT NULL", "CUST-VAL PIC S9(4)V99 COMP-3.")
    )
    violation = _by_kind(report, "precision")[0]
    assert violation.severity == "error"
    assert "overflow" in violation.message


def test_a_character_column_bound_to_a_numeric_item_is_an_error():
    report = _check(_one("CUST_VAL CHAR(6) NOT NULL", "CUST-VAL PIC 9(6)."))
    violation = _by_kind(report, "category")[0]
    assert violation.severity == "error"
    # Every later check would be comparing digits with characters, so the
    # category finding stands alone rather than dragging four more with it.
    assert _kinds(report) == {"category"}


def test_a_numeric_column_bound_to_an_alphanumeric_item_is_an_error():
    report = _check(_one("CUST_VAL DECIMAL(7,2) NOT NULL", "CUST-VAL PIC X(10)."))
    assert _kinds(report) == {"category"}
    assert report.violations[0].severity == "error"


def test_a_display_item_for_a_packed_column_is_a_usage_warning():
    report = _check(_one("CUST_VAL DECIMAL(7,2) NOT NULL", "CUST-VAL PIC S9(5)V99."))
    violation = _by_kind(report, "usage")[0]
    assert violation.severity == "warning"
    assert violation.expected_usage == "COMP-3"
    assert violation.actual_usage == "DISPLAY"


def test_an_unsigned_host_variable_loses_the_sign():
    report = _check(
        _one("CUST_VAL DECIMAL(7,2) NOT NULL", "CUST-VAL PIC 9(5)V99 COMP-3.")
    )
    violation = _by_kind(report, "sign")[0]
    assert violation.severity == "warning"


def test_a_nullable_column_with_no_indicator_is_a_warning():
    report = _check(_one("CUST_VAL CHAR(10)", "CUST-VAL PIC X(10)."))
    violation = _by_kind(report, "null-indicator")[0]
    assert violation.severity == "warning"
    assert "-305" in violation.message


def test_an_indicator_variable_silences_the_nullable_warning():
    source = _program(
        ONE_COLUMN.format(column="CUST_VAL CHAR(10)"),
        "       01  CUST-VAL    PIC X(10).\n       01  IND-VAL  PIC S9(4) COMP.\n",
        "CUST_VAL",
        ":CUST-VAL:IND-VAL",
    )
    report = _check(source)
    assert _by_kind(report, "null-indicator") == []


def test_the_indicator_keyword_form_is_recognised_too():
    source = _program(
        ONE_COLUMN.format(column="CUST_VAL CHAR(10)"),
        "       01  CUST-VAL    PIC X(10).\n       01  IND-VAL  PIC S9(4) COMP.\n",
        "CUST_VAL",
        ":CUST-VAL INDICATOR :IND-VAL",
    )
    report = _check(source)
    assert _by_kind(report, "null-indicator") == []


@pytest.mark.parametrize(
    "hostvars", [":CUST-VAL:IND-VAL", ":CUST-VAL INDICATOR :IND-VAL"]
)
def test_an_indicator_variable_is_not_an_unchecked_host_variable(hostvars):
    """An indicator binds to no column; it used to be reported as unchecked
    ("no DECLARE TABLE declares a column of this name")."""
    source = _program(
        ONE_COLUMN.format(column="CUST_VAL CHAR(10)"),
        "       01  CUST-VAL    PIC X(10).\n       01  IND-VAL  PIC S9(4) COMP.\n",
        "CUST_VAL",
        hostvars,
    )
    report = _check(source)
    assert report.checked == ["CUST-VAL"]
    assert report.unchecked == {}


@pytest.mark.parametrize(
    "hostvars",
    [":DCLCUSTOMER.CUST-VAL:IND-VAL", ":DCLCUSTOMER.CUST-VAL INDICATOR :IND-VAL"],
)
def test_a_structure_qualified_host_variable_is_checked(hostvars):
    """``:DCLCUSTOMER.CUST-VAL`` is CUST-VAL OF DCLCUSTOMER. The SQL model
    used to report the structure (DCLCUSTOMER) as the host variable and the
    indicator as a second one, so neither was checked and both were filed as
    unchecked."""
    source = _program(
        ONE_COLUMN.format(column="CUST_VAL CHAR(10)"),
        "       01  DCLCUSTOMER.\n           05  CUST-VAL    PIC X(10).\n"
        "       01  IND-VAL  PIC S9(4) COMP.\n",
        "CUST_VAL",
        hostvars,
    )
    report = _check(source)
    assert report.checked == ["CUST-VAL"]
    assert report.unchecked == {}
    assert _by_kind(report, "null-indicator") == []


def test_a_not_null_column_never_asks_for_an_indicator():
    report = _check(_one("CUST_VAL CHAR(10) NOT NULL", "CUST-VAL PIC X(10)."))
    assert report.violations == []


# ---------------------------------------------------------------------------
# What it declines to check
# ---------------------------------------------------------------------------


def test_a_varchar_column_is_declined_rather_than_compared_wrongly():
    """VARCHAR binds to a group (a length halfword plus the text), so a
    comparison against one elementary PICTURE compares the wrong things."""
    report = _check(_one("CUST_VAL VARCHAR(40) NOT NULL", "CUST-VAL PIC X(40)."))
    assert report.violations == []
    assert "group item" in report.unchecked["CUST-VAL"]


def test_a_type_with_no_cobol_picture_is_declined():
    report = _check(_one("CUST_VAL BLOB NOT NULL", "CUST-VAL PIC X(40)."))
    assert report.violations == []
    assert "CUST-VAL" in report.unchecked


# ---------------------------------------------------------------------------
# Report shape
# ---------------------------------------------------------------------------


def test_violations_come_back_in_source_order():
    declare = """           EXEC SQL DECLARE CUSTOMER TABLE
               (CUST_A CHAR(30) NOT NULL,
                CUST_B CHAR(30) NOT NULL)
           END-EXEC.
"""
    structure = (
        "       01  DCLCUSTOMER.\n"
        "           05  CUST-A     PIC X(10).\n"
        "           05  CUST-B     PIC X(10).\n"
    )
    report = _check(_program(declare, structure, "CUST_A, CUST_B", ":CUST-A, :CUST-B"))
    assert [v.host_variable for v in report.violations] == ["CUST-A", "CUST-B"]
    lines = [v.location.line for v in report.violations]
    assert lines == sorted(lines)


def test_worst_severity_and_to_dict():
    report = _check(_one("CUST_VAL CHAR(30) NOT NULL", "CUST-VAL PIC X(20)."))
    assert report.has_violations
    assert report.worst_severity() == "error"
    data = report.to_dict()
    assert data["violation_count"] == 1
    assert data["checked_count"] == 1
    assert data["worst_severity"] == "error"
    assert data["violations"][0]["kind"] == "length"
    assert data["violations"][0]["location"]["line"] > 0


def test_a_clean_report_has_no_worst_severity():
    report = _check(_one("CUST_VAL CHAR(10) NOT NULL", "CUST-VAL PIC X(10)."))
    assert report.worst_severity() is None
    assert not report.has_violations


def test_a_column_declared_by_two_tables_is_reported_as_ambiguous():
    declare = """           EXEC SQL DECLARE CUSTOMER TABLE
               (CUST_VAL CHAR(10) NOT NULL)
           END-EXEC.
           EXEC SQL DECLARE ARCHIVE TABLE
               (CUST_VAL CHAR(30) NOT NULL)
           END-EXEC.
"""
    report = _check(
        _program(
            declare,
            "       01  CUST-VAL    PIC X(10).\n",
            "CUST_VAL",
            ":CUST-VAL",
        )
    )
    assert report.ambiguous_columns["CUST-VAL"] == ["ARCHIVE", "CUSTOMER"]
    # The first declaration wins, so the 10-character column is the one used.
    assert report.violations == []


@pytest.mark.parametrize(
    ("db2_type", "picture", "usage"),
    [
        ("SMALLINT", "S9(4)", "COMP"),
        ("INTEGER", "S9(9)", "COMP"),
        ("BIGINT", "S9(18)", "COMP"),
        ("DECIMAL(7,2)", "S9(5)V99", "COMP-3"),
        ("CHAR(12)", "X(12)", "DISPLAY"),
        ("DATE", "X(10)", "DISPLAY"),
        ("TIMESTAMP", "X(26)", "DISPLAY"),
    ],
)
def test_what_dclgen_itself_would_generate_is_always_clean(db2_type, picture, usage):
    """The mapping and the check come from the same functions, so what DCLGEN
    would have written must never be reported as wrong."""
    clause = "" if usage == "DISPLAY" else f" {usage}"
    report = _check(
        _one(f"CUST_VAL {db2_type} NOT NULL", f"CUST-VAL PIC {picture}{clause}.")
    )
    assert report.violations == [], [v.message for v in report.violations]


@pytest.mark.parametrize(
    ("db2_type", "picture"),
    [("SMALLINT", "S9(4)"), ("INTEGER", "S9(9)"), ("BIGINT", "S9(18)")],
)
@pytest.mark.parametrize("usage", ["COMP-5", "COMPUTATIONAL-5"])
def test_a_comp5_integer_host_variable_is_not_a_usage_warning(db2_type, picture, usage):
    """Regression for #259: on z/OS ``COMP-5`` is a big-endian binary integer,
    byte for byte the storage of ``COMP``, and is IBM's recommended spelling
    for an integer host variable -- DB2 converts nothing."""
    report = _check(
        _one(f"CUST_VAL {db2_type} NOT NULL", f"CUST-VAL PIC {picture} {usage}.")
    )
    assert _by_kind(report, "usage") == []
    assert report.violations == [], [v.message for v in report.violations]


def test_the_issue_259_program_reports_no_violation():
    source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DCL1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL DECLARE CUST TABLE
           ( CUST_ID     INTEGER NOT NULL,
             CNT         SMALLINT NOT NULL
           ) END-EXEC.
       01 DCLCUST.
          10 CUST-ID      PIC S9(9) USAGE COMP-5.
          10 CNT          PIC S9(4) USAGE BINARY.
       PROCEDURE DIVISION.
           EXEC SQL SELECT CUST_ID, CNT INTO :CUST-ID, :CNT
                FROM CUST END-EXEC
           STOP RUN.
"""
    report = _check(source)
    assert sorted(report.checked) == ["CNT", "CUST-ID"]
    assert report.violations == [], [v.message for v in report.violations]
