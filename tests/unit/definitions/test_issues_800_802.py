"""Definition detection, DDL views/defaults and PSB NAME= (#800, #801, #802)."""

from __future__ import annotations

import pytest

from cobolparser.definitions import detect_definition_kind, parse_ddl, parse_psb

# ---------------------------------------------------------------------------
# #800: detection
# ---------------------------------------------------------------------------

_IDCAMS_JOB = """//DEFGDG   JOB (ACCT),'DEFINE GDG',CLASS=A,MSGCLASS=X
//STEP1    EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//SYSIN    DD *
  DEFINE GDG(NAME(PROD.DAILY.TXN) LIMIT(7) SCRATCH)
/*
"""

_DSNTEP2_JOB = """//CRTAB    JOB (ACCT),CLASS=A
//STEP1    EXEC PGM=IKJEFT01
//SYSTSIN  DD *
  RUN PROGRAM(DSNTEP2) PLAN(DSNTEP2)
//SYSIN    DD *
  CREATE TABLE T1 (A INT);
/*
"""

_CSDUP_JOB = """//CSDUP    JOB (ACCT)
//STEP1    EXEC PGM=DFHCSDUP
//SYSIN    DD *
  DEFINE TRANSACTION(ABCD) GROUP(G) PROGRAM(P)
/*
"""


@pytest.mark.parametrize("source", [_IDCAMS_JOB, _DSNTEP2_JOB, _CSDUP_JOB])
def test_jcl_jobs_are_not_definitions(source: str) -> None:
    assert detect_definition_kind(source) is None


@pytest.mark.parametrize(
    "source",
    [
        "  DEFINE GDG(NAME(X) LIMIT(7))\n",
        "  DEFINE CLUSTER(NAME(A.B) INDEXED)\n",
        "  DEF GDG(NAME(X))\n",
        "def main(argv):\n    return 0\n",
        "def program(x):\n    pass\n",
    ],
)
def test_non_csd_define_is_not_csd(source: str) -> None:
    assert detect_definition_kind(source) is None


@pytest.mark.parametrize(
    "source",
    ["DEFINE TRANSACTION(ABCD) GROUP(G)\n", "  DEF PROG(P1) GROUP(G)\n"],
)
def test_csd_resource_types_still_detected(source: str) -> None:
    assert detect_definition_kind(source) == "CSD"


# ---------------------------------------------------------------------------
# #801: DDL
# ---------------------------------------------------------------------------


def _base_tables(sql: str) -> list[str]:
    return list(parse_ddl(sql).to_dict()["views"][0]["base_tables"])


def test_view_leaves_out_common_table_expressions() -> None:
    sql = (
        "CREATE VIEW V2 AS WITH CTE1 AS (SELECT * FROM T1), CTE2 (C) AS "
        "(SELECT A FROM T3) SELECT * FROM CTE1 JOIN T2 ON 1=1 JOIN CTE2 ON 1=1;"
    )
    assert _base_tables(sql) == ["T1", "T3", "T2"]


def test_view_ignores_from_inside_function_calls() -> None:
    sql = (
        "CREATE VIEW V3 AS SELECT EXTRACT(YEAR FROM D) AS Y, SUBSTR(X FROM 1), "
        "TRIM(LEADING '0' FROM Z) FROM T1;"
    )
    assert _base_tables(sql) == ["T1"]


def test_view_subquery_tables_are_kept() -> None:
    sql = "CREATE VIEW V5 AS SELECT * FROM A WHERE X IN (SELECT Y FROM B);"
    assert _base_tables(sql) == ["A", "B"]


def test_view_table_function_is_not_a_table() -> None:
    assert _base_tables("CREATE VIEW V4 AS SELECT * FROM TABLE(F1(1)) AS X, T4;") == [
        "T4"
    ]


def test_with_default_null_and_signed_default() -> None:
    table = parse_ddl(
        "CREATE TABLE T (B CHAR(3) WITH DEFAULT NULL, C INT DEFAULT -1,"
        " D INT DEFAULT NULL NOT NULL);"
    ).tables[0]
    assert [(c.name, c.default) for c in table.columns] == [
        ("B", "NULL"),
        ("C", "-1"),
        ("D", "NULL"),
    ]
    assert table.column("D") is not None and table.column("D").nullable is False


def test_inline_unique_and_inline_on_delete() -> None:
    table = parse_ddl(
        "CREATE TABLE T (ID INT NOT NULL, A CHAR(1) UNIQUE,"
        " B INT REFERENCES P(ID) ON DELETE SET NULL,"
        " FOREIGN KEY (ID) REFERENCES Q (ID) ON DELETE CASCADE);"
    ).to_dict()["tables"][0]
    assert table["unique_keys"] == [["A"]]
    assert [fk["on_delete"] for fk in table["foreign_keys"]] == ["SET NULL", "CASCADE"]


# ---------------------------------------------------------------------------
# #802: PSB NAME=
# ---------------------------------------------------------------------------

_PSB = """         PCB   TYPE=DB,DBDNAME=CUSTDB,PROCOPT=G
         SENSEG NAME=CUSTOMER,PARENT=0
         PCB   TYPE=DB,NAME=ACCTDB,PROCOPT=A,PROCSEQ=ACCTX
         SENSEG NAME=ACCT
         PCB   TYPE=DB,PROCOPT=A
         PSBGEN LANG=COBOL,PSBNAME=PSB1
         END
"""


def test_db_pcb_name_keyword_is_the_dbd_name() -> None:
    report = parse_psb(_PSB).to_dict()
    psb = report["psbs"][0]
    assert psb["databases"] == ["ACCTDB", "CUSTDB"]
    assert [p["dbdname"] for p in psb["pcbs"]] == ["CUSTDB", "ACCTDB", None]
    assert [p["procseq"] for p in psb["pcbs"]] == [None, "ACCTX", None]
    assert report["warnings"] == [
        {"line": 5, "message": "TYPE=DB PCB without a DBD name"}
    ]
