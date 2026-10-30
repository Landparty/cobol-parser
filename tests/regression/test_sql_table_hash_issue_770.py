"""#770: ``#``, ``@`` and ``$`` are characters of a DB2 table name, the
first one included, so ``FROM T#TAB`` is one table and not also a phantom
``T`` listed first."""

import pytest

from cobolparser import parse_cobol


def _tables(sql: str) -> list[str]:
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. P.\n"
        "       PROCEDURE DIVISION.\n"
        f"           EXEC SQL {sql} END-EXEC\n"
        "           GOBACK.\n"
    )
    (statement,) = parse_cobol(source).ast.find_all_by_type("ExecSQLStatement")
    return list(statement.tables)


@pytest.mark.parametrize(
    ("sql", "tables"),
    [
        ("SELECT A INTO :B FROM T#TAB", ["T#TAB"]),
        ("SELECT A INTO :B FROM SCH#.T@B", ["SCH#.T@B"]),
        ("UPDATE $T SET A = 1", ["$T"]),
        ("INSERT INTO #TAB (A) VALUES (:H)", ["#TAB"]),
        ("SELECT A INTO :B FROM T1 JOIN T2 ON X = Y", ["T1", "T2"]),
    ],
)
def test_one_table_per_name(sql: str, tables: list[str]) -> None:
    assert _tables(sql) == tables
