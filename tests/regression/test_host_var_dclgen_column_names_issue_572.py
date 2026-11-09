"""Regression tests for issue #572: HostVariableResolver and DCLGEN names.

DECLARE TABLE columns were indexed by their raw names (``CUST_ID``) and host
variables looked up by theirs (``CUST-ID``), so only a column with no
underscore ever matched: ``db2_column`` was ``None`` for almost every real
DCLGEN host variable, and a host variable with no DATA DIVISION item was
unresolved even when a column described it.
"""

from cobolparser import DclgenChecker, parse_cobol
from cobolparser.analysis import HostVariableResolver

_DECLARE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HV572.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL DECLARE CUST TABLE
             ( CUST_ID    INTEGER NOT NULL,
               CUST_NAME  VARCHAR(30) NOT NULL,
               BAL        DECIMAL(9,2)
             ) END-EXEC.
"""

_DCLCUST = """\
       01 DCLCUST.
          10 CUST-ID     PIC S9(9) COMP.
          10 CUST-NAME.
             49 CUST-NAME-LEN  PIC S9(4) COMP.
             49 CUST-NAME-TEXT PIC X(30).
          10 BAL         PIC S9(7)V99 COMP-3.
"""

_PROC = """\
       PROCEDURE DIVISION.
           EXEC SQL SELECT CUST_NAME, BAL INTO :CUST-NAME, :BAL
                FROM CUST WHERE CUST_ID = :CUST-ID END-EXEC.
           GOBACK.
"""


def _resolve(source: str):
    result = parse_cobol(source)
    assert result.errors == []
    return result.ast, HostVariableResolver().resolve(result.ast)


def test_underscored_columns_link_to_hyphenated_host_variables():
    _, report = _resolve(_DECLARE + _DCLCUST + _PROC)
    assert report.resolved["CUST-ID"].db2_column.name == "CUST_ID"
    assert report.resolved["CUST-NAME"].db2_column.name == "CUST_NAME"
    assert report.resolved["BAL"].db2_column.name == "BAL"
    assert report.resolved["CUST-ID"].data_item is not None


def test_host_variable_without_data_item_falls_back_to_its_column():
    _, report = _resolve(_DECLARE + _PROC)
    assert report.unresolved == set()
    info = report.resolved["CUST-ID"]
    assert info.data_item is None
    assert info.db2_column.name == "CUST_ID"
    assert info.picture == info.db2_column.cobol_picture


def test_dclgen_checker_agrees_with_the_resolver():
    ast, report = _resolve(_DECLARE + _DCLCUST + _PROC)
    dclgen = DclgenChecker().check(ast)
    assert "CUST-ID" in dclgen.checked
    for name in dclgen.checked:
        assert report.resolved[name].db2_column is not None
