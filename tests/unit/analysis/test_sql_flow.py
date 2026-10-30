"""Embedded SQL -> host variable / column flows (``analysis._sql_flow``)."""

from __future__ import annotations

from cobolparser.analysis._sql_flow import analyze_sql, host_var_name


def _flows(sql: str, cursors: dict[str, str] | None = None) -> list[tuple]:
    result = analyze_sql(sql, cursors or {})
    return [(f.host_var, f.table, f.column, f.direction, f.kind) for f in result.flows]


def _keys(sql: str) -> list[tuple]:
    return [(k.host_var, k.table, k.column) for k in analyze_sql(sql, {}).keys]


class TestSelectInto:
    SQL = "SELECT BALANCE, NAME INTO :WS-BAL, :WS-NAME FROM ACCOUNT WHERE ACCT_NO = :WS-ACCT"

    def test_select_list_pairs_with_into_list(self) -> None:
        assert _flows(self.SQL) == [
            ("WS-BAL", "ACCOUNT", "BALANCE", "in", "sql"),
            ("WS-NAME", "ACCOUNT", "NAME", "in", "sql"),
        ]

    def test_where_equality_is_a_key_use(self) -> None:
        assert _keys(self.SQL) == [("WS-ACCT", "ACCOUNT", "ACCT_NO")]

    def test_aggregate_is_value_changing(self) -> None:
        sql = "SELECT SUM(AMOUNT) INTO :WS-TOT FROM TRAN T WHERE T.ACCT = :WS-ACCT"
        assert _flows(sql) == [("WS-TOT", "TRAN", "AMOUNT", "in", "aggregate")]
        assert _keys(sql) == [("WS-ACCT", "TRAN", "ACCT")]

    def test_expression_is_sql_expr(self) -> None:
        assert _flows("SELECT AMOUNT * 2 INTO :WS-X FROM TRAN") == [
            ("WS-X", "TRAN", "AMOUNT", "in", "sql-expr")
        ]

    def test_case_conditions_are_not_values(self) -> None:
        sql = (
            "SELECT CASE WHEN STATUS = 'C' THEN AMOUNT ELSE 0 END "
            "INTO :WS-X FROM TRAN"
        )
        columns = {f[2] for f in _flows(sql)}
        assert "AMOUNT" in columns
        assert "STATUS" not in columns


class TestWrites:
    def test_insert_with_column_list(self) -> None:
        assert _flows("INSERT INTO HIST (ACCT, AMT) VALUES (:WS-ACCT, :WS-AMT)") == [
            ("WS-ACCT", "HIST", "ACCT", "out", "sql"),
            ("WS-AMT", "HIST", "AMT", "out", "sql"),
        ]

    def test_insert_without_column_list_is_positional_with_caveat(self) -> None:
        result = analyze_sql("INSERT INTO HIST VALUES (:WS-ACCT, :WS-AMT)", {})
        assert [f.column for f in result.flows] == ["#1", "#2"]
        assert any("no column list" in c for c in result.caveats)

    def test_update_set_and_where(self) -> None:
        sql = (
            "UPDATE ACCOUNT SET BAL = BAL + :WS-AMT, STATUS = 'A' "
            "WHERE ACCT_NO = :WS-ACCT"
        )
        assert _flows(sql) == [("WS-AMT", "ACCOUNT", "BAL", "out", "sql-expr")]
        assert _keys(sql) == [("WS-ACCT", "ACCOUNT", "ACCT_NO")]

    def test_delete_has_only_keys(self) -> None:
        sql = "DELETE FROM ACCOUNT WHERE ACCT_NO = :WS-ACCT"
        assert _flows(sql) == []
        assert _keys(sql) == [("WS-ACCT", "ACCOUNT", "ACCT_NO")]


class TestCursors:
    DECLARE = (
        "DECLARE C1 CURSOR FOR SELECT A.BAL, B.NAME FROM ACCOUNT A "
        "JOIN CUST B ON A.CID = B.CID WHERE A.ACCT = :WS-ACCT"
    )

    def test_declare_returns_the_cursor_and_its_keys(self) -> None:
        result = analyze_sql(self.DECLARE, {})
        assert result.declared_cursor is not None
        assert result.declared_cursor[0] == "C1"
        assert [(k.table, k.column) for k in result.keys] == [("ACCOUNT", "ACCT")]

    def test_fetch_resolves_aliases_through_the_declare(self) -> None:
        cursor = analyze_sql(self.DECLARE, {}).declared_cursor
        assert cursor is not None
        flows = _flows("FETCH C1 INTO :WS-BAL, :WS-NAME", {cursor[0]: cursor[1]})
        assert flows == [
            ("WS-BAL", "ACCOUNT", "BAL", "in", "sql"),
            ("WS-NAME", "CUST", "NAME", "in", "sql"),
        ]

    def test_fetch_of_unknown_cursor_is_a_caveat(self) -> None:
        result = analyze_sql("FETCH C2 INTO :WS-BAL", {})
        assert result.flows == []
        assert any("C2" in c for c in result.caveats)


def test_merge_is_reported_untraced() -> None:
    assert analyze_sql("MERGE INTO X USING Y ON 1=1", {}).caveats == [
        "MERGE is not traced"
    ]


def test_host_var_name_qualification() -> None:
    assert host_var_name("REC.FIELD") == "FIELD OF REC"
    assert host_var_name(":REC.FIELD") == "FIELD OF REC"
    assert host_var_name(":ws-a") == "WS-A"


class TestTableFunctionDetection:
    """Issue #340: only ``TABLE(...)`` is a table function, not ``TABLE_*``."""

    def test_table_prefixed_name_is_an_ordinary_table(self) -> None:
        sql = "SELECT NAME INTO :WS-NAME FROM TABLE_CUST WHERE ID = :WS-ID"
        result = analyze_sql(sql, {})
        assert _flows(sql) == [("WS-NAME", "TABLE_CUST", "NAME", "in", "sql")]
        assert _keys(sql) == [("WS-ID", "TABLE_CUST", "ID")]
        assert result.caveats == []

    def test_other_table_prefixed_names_are_traced(self) -> None:
        for table in ("TABLES_CFG", "TABLEX"):
            sql = f"SELECT V INTO :WS-V FROM {table}"
            assert _flows(sql) == [("WS-V", table, "V", "in", "sql")]

    def test_table_function_is_still_skipped(self) -> None:
        for spelling in ("TABLE(UDF(:WS-A)) AS T", "TABLE (UDF(:WS-A)) T"):
            result = analyze_sql(f"SELECT C INTO :WS-C FROM {spelling}", {})
            assert result.flows == []
            assert "a table function in FROM is not traced" in result.caveats


class TestFromClauseShapes:
    """``FROM FINAL TABLE (INSERT ...)`` is not a table named FINAL, and
    ``BANK . CUST`` (blanks around the dot) is one qualified table name."""

    def test_data_change_table_reference_is_not_a_table(self) -> None:
        for keyword in ("FINAL", "NEW", "OLD"):
            sql = (
                f"SELECT ID INTO :WS-ID FROM {keyword} TABLE "
                "(INSERT INTO CUST (NAME) VALUES (:WS-NM))"
            )
            result = analyze_sql(sql, {})
            assert all(flow.table != keyword for flow in result.flows)
            assert (
                "a data-change table reference in FROM is not traced" in result.caveats
            )

    def test_blanks_around_the_qualifier_dot(self) -> None:
        sql = "SELECT A.NAME INTO :WS-NM FROM BANK . CUST A WHERE A.ID = :WS-ID"
        assert _flows(sql) == [("WS-NM", "BANK.CUST", "NAME", "in", "sql")]
        assert _keys(sql) == [("WS-ID", "BANK.CUST", "ID")]
