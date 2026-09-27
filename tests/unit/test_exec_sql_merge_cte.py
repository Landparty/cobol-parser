"""Regression tests: DB2 MERGE and WITH (common table expression) statements.

Both used to come back as ``sql_type == "UNKNOWN"`` with no tables:
``_determine_sql_type`` only knew statements that *start* with their verb,
and table extraction is keyed on the type. A program that MERGEs into a
table, or reads through a CTE, therefore showed no DB2 table use at all --
and the backend's MERGE handling (a WRITE of the target table) never ran.
"""

from cobolparser import parse_cobol


def _program(*sql_lines: str) -> str:
    body = "\n".join(f"             {line}" for line in sql_lines)
    return f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC X(10).
       PROCEDURE DIVISION.
           EXEC SQL
{body}
           END-EXEC.
           GOBACK.
"""


def _sql(*sql_lines: str):
    result = parse_cobol(_program(*sql_lines), filename="t.cbl")
    assert result.success, result.errors
    (stmt,) = [s for s in result.ast.get_all_statements() if hasattr(s, "tables")]
    return stmt


class TestMerge:
    def test_merge_with_table_source(self):
        stmt = _sql(
            "MERGE INTO ACCT.BALANCE T",
            "USING ACCT.DAILY_TXN S",
            "ON T.ACCT_ID = S.ACCT_ID",
            "WHEN MATCHED THEN UPDATE SET T.AMT = T.AMT + S.AMT",
            "WHEN NOT MATCHED THEN INSERT (ACCT_ID, AMT)",
            "VALUES (S.ACCT_ID, S.AMT)",
        )
        assert stmt.sql_type == "MERGE"
        assert stmt.tables[0] == "ACCT.BALANCE"  # the target comes first
        assert sorted(stmt.tables) == ["ACCT.BALANCE", "ACCT.DAILY_TXN"]

    def test_merge_with_subquery_source(self):
        stmt = _sql(
            "MERGE INTO TGT T",
            "USING (SELECT K, A FROM SRC WHERE A > 0) S",
            "ON T.K = S.K",
            "WHEN MATCHED THEN UPDATE SET T.A = S.A",
        )
        assert stmt.sql_type == "MERGE"
        assert stmt.tables[0] == "TGT"
        assert "SRC" in stmt.tables

    def test_merge_with_host_variable_source(self):
        stmt = _sql(
            "MERGE INTO TGT T",
            "USING (VALUES (:WS-A)) AS S (K)",
            "ON T.K = S.K",
            "WHEN NOT MATCHED THEN INSERT (K) VALUES (S.K)",
        )
        assert stmt.sql_type == "MERGE"
        assert stmt.tables == ["TGT"]
        assert "WS-A" in stmt.host_variables


class TestCommonTableExpression:
    def test_with_select_reports_base_tables_not_cte_names(self):
        stmt = _sql(
            "WITH RECENT (ID) AS (SELECT ID FROM ORDERS WHERE D > 1),",
            "     BIG AS (SELECT ID FROM LINES)",
            "SELECT R.ID INTO :WS-A FROM RECENT R",
            "JOIN BIG B ON R.ID = B.ID",
        )
        assert stmt.sql_type == "SELECT"
        assert sorted(stmt.tables) == ["LINES", "ORDERS"]

    def test_with_select_columns_come_from_main_select(self):
        stmt = _sql(
            "WITH X AS (SELECT K FROM TCTE)",
            "SELECT K INTO :WS-A FROM X",
        )
        assert stmt.select_columns == ["K"]
        assert stmt.tables == ["TCTE"]

    def test_plain_select_unchanged(self):
        stmt = _sql("SELECT A INTO :WS-A FROM T1 WHERE B = 1")
        assert (stmt.sql_type, stmt.tables) == ("SELECT", ["T1"])
