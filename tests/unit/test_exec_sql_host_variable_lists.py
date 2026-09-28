"""Regression tests: INTO / USING host-variable lists of parsed EXEC SQL.

The EXEC text collector writes no blank before a colon (``INTO:WS-A``), and the
list regexes required one (``INTO\\s+:``), so ``into_variables`` and a dynamic
statement's ``using_variables`` were empty for every statement parsed from
source -- only hand-written test strings with a blank populated them. An
indicator (``:WS-A:IND``) also ended the list at its first item.
"""

import pytest

from cobolparser import parse_cobol


def _sql(*lines):
    body = "\n".join(f"               {line}" for line in lines)
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. HVLIST.\n"
        "       PROCEDURE DIVISION.\n"
        "           EXEC SQL\n"
        f"{body}\n"
        "           END-EXEC.\n"
        "           GOBACK.\n"
    )
    result = parse_cobol(source, filename="t.cbl")
    assert result.ast is not None, result.errors
    (stmt,) = [s for s in result.ast.get_all_statements() if hasattr(s, "tables")]
    return stmt


def test_select_into_from_source():
    stmt = _sql("SELECT NAME, SAL INTO :WS-NAME, :WS-SAL", "FROM EMP WHERE ID = :WS-ID")
    assert stmt.into_variables == ["WS-NAME", "WS-SAL"]


def test_fetch_into_from_source():
    stmt = _sql("FETCH C1 INTO :WS-A, :WS-B")
    assert stmt.into_variables == ["WS-A", "WS-B"]


@pytest.mark.parametrize(
    "into",
    [":WS-A:IND-A, :WS-B:IND-B", ":WS-A INDICATOR :IND-A, :WS-B INDICATOR :IND-B"],
)
def test_indicators_do_not_end_the_list(into):
    # Fixed format: keep each line inside column 72.
    stmt = _sql("SELECT A, B", f"INTO {into}", "FROM T1")
    assert stmt.into_variables == ["WS-A", "IND-A", "WS-B", "IND-B"]
    assert stmt.null_indicators == ["IND-A", "IND-B"]


def test_execute_using_from_source():
    stmt = _sql("EXECUTE S1 USING :WS-A, :WS-B")
    assert stmt.using_variables == ["WS-A", "WS-B"]


def test_insert_into_table_has_no_into_variables():
    stmt = _sql("INSERT INTO T1 (A) VALUES (:WS-A)")
    assert stmt.into_variables == []


def test_structure_qualified_host_variables_name_the_field():
    """``:REC.FLD`` is FLD OF REC: the field is the host variable, not the
    structure (which used to be reported, hiding the field)."""
    stmt = _sql(
        "SELECT SAL INTO :DCLEMP.SAL:IND-SAL",
        "FROM EMP WHERE EMPNO = :DCLEMP.EMPNO",
    )
    assert stmt.host_variables == ["SAL", "IND-SAL", "EMPNO"]
    assert stmt.null_indicators == ["IND-SAL"]
    assert stmt.into_variables == ["SAL", "IND-SAL"]
