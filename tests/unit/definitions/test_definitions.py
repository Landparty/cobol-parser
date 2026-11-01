"""cobolparser.definitions: CICS CSD, BMS, DB2 DDL, IMS DBD and PSB."""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser.definitions import (
    SYSTEM_DEFAULT,
    detect_definition_kind,
    parse_bms,
    parse_csd,
    parse_dbd,
    parse_ddl,
    parse_definitions,
    parse_psb,
)
from cobolparser.definitions._asm import (
    as_int,
    parse_operands,
    parse_value,
    read_statements,
)

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "definitions"


def _sample(name: str) -> str:
    return (SAMPLES / name).read_text()


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("ACCTSET.bms", "BMS"),
        ("BANKCSD.csd", "CSD"),
        ("BANKPCT.asm", "CSD"),
        ("BANKDDL.ddl", "DDL"),
        ("CUSTDBD.dbd", "DBD"),
        ("CUSTPSB.psb", "PSB"),
    ],
)
def test_detects_each_sample(name: str, kind: str) -> None:
    assert detect_definition_kind(_sample(name)) == kind
    report = parse_definitions(_sample(name))
    assert report is not None
    assert report.to_dict()["kind"] == kind


def test_cobol_with_embedded_create_table_is_not_ddl() -> None:
    source = (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. X.\n"
        "       PROCEDURE DIVISION.\n           EXEC SQL\n"
        "CREATE TABLE T (A INT)\n           END-EXEC.\n"
    )
    assert detect_definition_kind(source) is None
    assert parse_definitions(source) is None


def test_plain_assembler_is_not_a_definition() -> None:
    assert (
        detect_definition_kind("TEST     CSECT\n         BR    14\n         END\n")
        is None
    )


def test_parse_definitions_with_explicit_kind() -> None:
    report = parse_definitions("CREATE TABLE T (A INT);", "DDL")
    assert report is not None and report.to_dict()["tables"][0]["name"] == "T"


# ---------------------------------------------------------------------------
# Assembler statement reader
# ---------------------------------------------------------------------------


def test_operands_keywords_positional_and_nested_lists() -> None:
    keywords, positional = parse_operands("A,(B,C),K=(1,(2,3)),Q='X,''Y'''")
    assert positional == ["A", ["B", "C"]]
    assert keywords == {"K": ["1", ["2", "3"]], "Q": "X,'Y'"}
    assert parse_value("()") == []
    assert parse_value("(A)(B)") == "(A)(B)"
    assert parse_operands("  ") == ({}, [])
    assert as_int("12") == 12 and as_int("X") is None and as_int(["1"]) is None


def test_column_72_continuation_and_sequence_field() -> None:
    first = "NAME     DFHMDF POS=(1,1),".ljust(71) + "X" + "00000010"
    second = " " * 15 + "LENGTH=5".ljust(56) + " " + "00000020"
    stmt = read_statements(first + "\n" + second + "\n")[0]
    assert stmt.name == "NAME" and stmt.operation == "DFHMDF"
    assert stmt.keywords == {"POS": ["1", "1"], "LENGTH": "5"}


def test_continued_string_keeps_its_blanks() -> None:
    first = "         DFHMDF INITIAL='HELLO".ljust(71) + "X"
    second = " " * 15 + "WORLD'"
    stmt = read_statements(f"{first}\n{second}\n")[0]
    assert (
        stmt.text("INITIAL")
        == "HELLO" + " " * (71 - len(first.rstrip("X").rstrip())) + "WORLD"
    )


def test_unmarked_continuation_after_trailing_comma() -> None:
    source = (
        "X        DBD   NAME=DB1,\n               ACCESS=HDAM\n         SEGM  NAME=S\n"
    )
    statements = read_statements(source)
    assert statements[0].keywords == {"NAME": "DB1", "ACCESS": "HDAM"}
    assert statements[1].operation == "SEGM"


def test_overflowing_record_is_not_a_continuation() -> None:
    long_line = (
        "         DFHMDF POS=(4,18),LENGTH=10,ATTRB=(UNPROT,NUM,IC),PICIN='9(10)'"
    )
    assert len(long_line) == 72
    statements = read_statements(long_line + "\n         DFHMDF POS=(4,29)\n")
    assert statements[0].text("PICIN") == "9(10)"
    assert len(statements) == 2


def test_blank_and_operation_less_lines_are_skipped() -> None:
    assert read_statements("\n.* macro comment\nLABELONLY\n") == []


def test_statement_text_and_keyword_accessors() -> None:
    stmt = read_statements("         X     A=(1,2),B=C\n")[0]
    assert stmt.text("A") == "1,2" and stmt.text("B") == "C" and stmt.text("Z") is None
    assert stmt.keyword("B") == "C" and stmt.keyword("Z") is None


# ---------------------------------------------------------------------------
# BMS
# ---------------------------------------------------------------------------


def test_bms_mapset_maps_and_fields() -> None:
    report = parse_bms(_sample("ACCTSET.bms"))
    (mapset,) = report.mapsets
    assert (
        mapset.name == "ACCTSET"
        and mapset.mode == "INOUT"
        and mapset.language == "COBOL"
    )
    assert mapset.attributes["CTRL"] == "FREEKB,FRSET"
    menu, detail = mapset.maps
    data = menu.to_dict()
    assert (data["rows"], data["columns"]) == (24, 80)
    assert data["input_fields"] == ["ACCTNO"]
    assert data["output_fields"] == ["CUSTNM", "BALANCE", "MSG"]
    assert data["title"] == "ACCTMNU"
    footer = [f for f in menu.fields if f.row == 23][0]
    assert footer.initial == "PF3=EXIT  ENTER=INQUIRE  CUSTOMER'S DATA"
    msg = [f for f in menu.fields if f.name == "MSG"][0]
    assert msg.color == "RED" and msg.kind == "output"
    acctno = [f for f in menu.fields if f.name == "ACCTNO"][0]
    assert acctno.picin == "9(10)" and acctno.kind == "input"
    # POS=0 is an offset: row 1, column 1.
    assert (detail.fields[0].row, detail.fields[0].column) == (1, 1)
    assert detail.to_dict()["title"] == "ACCOUNT DETAIL"
    assert report.warnings == []


def test_bms_warnings_and_positions() -> None:
    source = "\n".join(
        [
            "         DFHMDF POS=(1,1)",
            "         DFHMDI SIZE=(10,40)",
            "         DFHMSD TYPE=MAP",
            "SET1     DFHMSD TYPE=MAP,SIZE=(12,40),XINIT=1",
            "         DFHMDI SIZE=(10,40)",
            "MAP1     DFHMDI LINE=1",
            "         DFHMDF POS=85,LENGTH=3,XINIT=C1C2C3",
            "         DFHMDF POS=(1,1),XINIT=ZZ",
            "         DFHMDF LENGTH=3,OCCURS=2",
            "MAP2     DFHMDI SIZE=(1,1,1)",
            "         DFHMSD TYPE=FINAL",
            "         DFHMDF POS=1",
        ]
    )
    report = parse_bms(source)
    messages = [w["message"] for w in report.warnings]
    assert messages == [
        "DFHMDF outside a DFHMDI",
        "DFHMDI outside a DFHMSD",
        "DFHMSD without a mapset name",
        "DFHMDI without a map name",
        "DFHMDF outside a DFHMDI",
    ]
    (mapset,) = report.mapsets
    map1, map2 = mapset.maps
    assert (map1.rows, map1.columns) == (12, 40)  # from the mapset SIZE
    assert (map2.rows, map2.columns) == (12, 40)
    hex_field, bad_hex, no_pos = map1.fields
    assert (hex_field.row, hex_field.column) == (3, 6)
    assert hex_field.initial == "ABC" and hex_field.kind == "constant"
    assert bad_hex.initial is None
    assert (no_pos.row, no_pos.column, no_pos.occurs) == (None, None, 2)
    assert map1.title == "ABC"


def test_bms_default_size_and_unreadable_mapset_size() -> None:
    report = parse_bms("S        DFHMSD TYPE=MAP,SIZE=(A,B)\nM        DFHMDI LINE=1\n")
    assert (report.mapsets[0].maps[0].rows, report.mapsets[0].maps[0].columns) == (
        24,
        80,
    )


# ---------------------------------------------------------------------------
# CSD
# ---------------------------------------------------------------------------


def test_csd_transactions_files_and_db2() -> None:
    report = parse_csd(_sample("BANKCSD.csd"))
    data = report.to_dict()
    by_id = {t["transid"]: t for t in data["transactions"]}
    assert set(by_id) == {"ACCT", "ACUP", "PAYM"}
    assert by_id["ACCT"]["program"] == "ACCTINQ"
    assert by_id["ACCT"]["description"] == "Account inquiry from the branch terminals"
    assert by_id["ACCT"]["profile"] == "DFHCICST"
    # ALTER applied to the existing definition.
    assert by_id["ACUP"]["description"] == "Account update"
    assert (by_id["ACUP"]["db2_entry"], by_id["ACUP"]["db2_plan"]) == (
        "BANKENT",
        "BANKPLN",
    )
    # Abbreviated keywords: DEF TRANS(...) PROG(...)
    assert (
        by_id["PAYM"]["program"] == "PAYMENT"
        and by_id["PAYM"]["remote_system"] == "CICB"
    )
    assert data["files"] == [
        {
            "name": "ACCTFIL",
            "group": "BANKGRP",
            "dsname": "PROD.BANK.ACCOUNT.KSDS",
            "line": 11,
            "source": "DFHCSDUP",
        }
    ]
    assert [m["name"] for m in data["mapsets"]] == ["ACCTSET"]
    assert [p["name"] for p in data["programs"]] == ["ACCTINQ", "ACCTUPD"]
    assert data["lists"] == {"BANKLIST": ["BANKGRP"]}
    assert data["resource_counts"]["DB2TRAN"] == 1
    messages = [w["message"] for w in data["warnings"]]
    assert "ALTER of TRANSACTION NONE, which this deck does not define" in messages
    assert "DEFINE without a resource type" in messages


def test_csd_db2entry_transid_and_unknown_entry() -> None:
    source = (
        "DEFINE DB2ENTRY(E1) GROUP(G) PLAN(P1) TRANSID(T1)\n"
        "DEFINE DB2TRAN(X) GROUP(G) ENTRY(NOPE) TRANSID(T2)\n"
        "DEFINE TRANSACTION(T1) GROUP(G) PROGRAM(A)\n"
        "DEFINE TRANSACTION(T2) GROUP(G) PROGRAM(B)\n"
    )
    by_id = {t["transid"]: t for t in parse_csd(source).transactions()}
    assert by_id["T1"]["db2_plan"] == "P1"
    assert (by_id["T2"]["db2_entry"], by_id["T2"]["db2_plan"]) == ("NOPE", None)


def test_csd_sequence_numbers_quotes_and_unclosed_value() -> None:
    record = "DEFINE TRANSACTION(T1) GROUP(G) PROGRAM(P1)".ljust(72) + "00000100"
    source = record + "\nDEFINE FILE(F1) GROUP(G) DESCRIPTION('It''s here') DSNAME(A.B"
    report = parse_csd(source)
    assert report.transactions()[0]["program"] == "P1"
    file_res = report.of_type("FILE")[0]
    assert file_res.attributes["DESCRIPTION"] == "It's here"


def test_csd_alter_in_another_group_is_reported() -> None:
    source = "DEFINE PROGRAM(P) GROUP(A)\nALTER PROGRAM(P) GROUP(B) LANGUAGE(PLI)\n"
    report = parse_csd(source)
    assert report.of_type("PROGRAM")[0].attributes == {}
    assert len(report.warnings) == 1


def test_csd_tokens_before_any_command_are_ignored() -> None:
    assert (
        parse_csd("GROUP(X) DEFINE PROGRAM(P) GROUP(G)").of_type("PROGRAM")[0].name
        == "P"
    )


def test_pct_ppt_fct_tables() -> None:
    report = parse_csd(_sample("BANKPCT.asm"))
    data = report.to_dict()
    assert data["transactions"][0]["transid"] == "ACCT"
    assert data["transactions"][0]["program"] == "ACCTINQ"
    assert data["transactions"][0]["source"] == "DFHPCT"
    assert data["mapsets"][0]["name"] == "ACCTSET"
    assert data["files"][0]["name"] == "ACCTFIL" and data["files"][0]["dsname"] is None
    assert data["warnings"] == [{"line": 4, "message": "DFHPCT entry without TRANSID="}]


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------


def test_ddl_tables_keys_indexes_and_comments() -> None:
    report = parse_ddl(_sample("BANKDDL.ddl"))
    account = report.table("BANK.ACCOUNT")
    assert account is not None
    data = account.to_dict()
    assert (data["schema"], data["table"]) == ("BANK", "ACCOUNT")
    assert data["primary_key"] == ["ACCT_NO"]
    assert data["tablespace"] == "BANKDB.ACCTTS"
    assert data["comment"] == "One row per customer account"
    columns = {c["name"]: c for c in data["columns"]}
    assert columns["ACCT_NO"]["type"] == "DECIMAL(10, 0)"
    assert columns["ACCT_NO"]["nullable"] is False
    assert columns["ACCT_TYPE"]["default"] == "C"
    assert columns["BALANCE"]["default"] == SYSTEM_DEFAULT
    assert columns["BALANCE"]["comment"] == "Ledger balance, in cents"
    assert columns["OPENED_TS"]["default"] == "CURRENT TIMESTAMP"
    assert columns["NOTES"]["type"] == "VARCHAR(200) FOR BIT DATA"
    assert columns["CLOSED_DT"]["position"] == 7  # added by ALTER TABLE
    assert data["foreign_keys"] == [
        {
            "name": "ACCT_CUST_FK",
            "columns": ["CUST_ID"],
            "references": "BANK.CUSTOMER",
            "referenced_columns": ["CUST_ID"],
            "on_delete": "RESTRICT",
        }
    ]
    assert [i["name"] for i in data["indexes"]] == ["BANK.ACCTIX1", "BANK.ACCTIX2"]
    assert data["indexes"][0]["unique"] and data["indexes"][0]["cluster"]
    assert data["indexes"][1]["columns"] == ["CUST_ID", "ACCT_TYPE"]

    customer = report.table("BANK.CUSTOMER")
    assert customer is not None
    assert customer.primary_key == ["CUST_ID"]
    assert customer.unique_keys == [["NAME"]]
    assert customer.foreign_keys[0]["references"] == "BANK.BRANCH"
    assert customer.column("NAME") is not None
    assert customer.column("NAME").label == "Customer's name"  # type: ignore[union-attr]

    hist = report.table("BANK.ACCT_HIST")
    assert hist is not None and hist.like == "BANK.ACCOUNT"
    # The table after "--#SET TERMINATOR #".
    assert report.table("BANK.BRANCH") is not None


def test_ddl_views_aliases_other_objects_and_ignored() -> None:
    data = parse_ddl(_sample("BANKDDL.ddl")).to_dict()
    assert data["views"] == [
        {
            "name": "BANK.V_CUST_ACCT",
            "columns": ["CUST_ID", "NAME", "ACCT_NO"],
            "base_tables": ["BANK.CUSTOMER", "BANK.ACCOUNT"],
            "line": 27,
        }
    ]
    assert data["aliases"] == [
        {"name": "ACCOUNT", "kind": "ALIAS", "target": "BANK.ACCOUNT", "line": 32}
    ]
    assert [o["kind"] for o in data["other_objects"]] == ["DATABASE", "TABLESPACE"]
    assert data["ignored_statements"] == {"GRANT": 1}
    assert data["warnings"] == [
        {
            "line": 34,
            "message": "ALTER TABLE BANK.MISSING, which this member does not create",
        }
    ]


def test_ddl_view_from_list_and_subquery() -> None:
    source = (
        "CREATE VIEW V AS SELECT * FROM A X, B, (SELECT 1 FROM C) Z "
        "LEFT OUTER JOIN D ON 1=1 WHERE A.K IN (SELECT K FROM E);"
    )
    assert parse_ddl(source).views[0]["base_tables"] == ["A", "B", "C", "D", "E"]


def test_ddl_misc_statements() -> None:
    source = """
    CREATE TABLE ;
    CREATE OR REPLACE GLOBAL TEMPORARY TABLE "Mixed"."Case" (ID INT NOT NULL);
    CREATE TRIGGER T1 AFTER INSERT ON X FOR EACH ROW;
    DROP TABLE OLD;
    SET CURRENT SQLID = 'X';
    ALTER TABLE "Mixed"."Case" ADD PRIMARY KEY (ID) ADD CONSTRAINT U1 UNIQUE (ID);
    CREATE TABLE K (A INT, B INT, CONSTRAINT C1 FOREIGN KEY FK1 (A) REFERENCES P (A),
                    FOREIGN KEY (B) REFERENCES Q, CONSTRAINT C9 CHECK (A > 0));
    COMMENT ON COLUMN K.NOPE IS 'x';
    COMMENT ON TABLE NOPE IS 'x';
    COMMENT ON INDEX I IS 'x';
    COMMENT ON K (A IS 1);
    CREATE INDEX I2 ON NOPE (A);
    CREATE SYNONYM S1 FOR K;
    CREATE ALIAS A1;
    /* multi
       line */ CREATE TABLE L (X CHAR(1) DEFAULT 'Y' NOT NULL, Y INT DEFAULT NOT NULL);
    """
    report = parse_ddl(source)
    data = report.to_dict()
    assert data["warnings"] == [{"line": 2, "message": "CREATE TABLE without a name"}]
    mixed = report.table("Mixed.Case")
    assert (
        mixed is not None
        and mixed.primary_key == ["ID"]
        and mixed.unique_keys == [["ID"]]
    )
    assert data["ignored_statements"] == {
        "CREATE TRIGGER": 1,
        "DROP TABLE": 1,
        "SET": 1,
    }
    k_table = report.table("K")
    assert k_table is not None
    assert [fk["name"] for fk in k_table.foreign_keys] == ["C1", None]
    assert k_table.foreign_keys[1]["referenced_columns"] == []
    assert k_table.column("A") is not None and k_table.column("A").comment is None  # type: ignore[union-attr]
    assert [a["kind"] for a in data["aliases"]] == ["SYNONYM", "ALIAS"]
    assert data["aliases"][1]["target"] is None
    assert data["indexes"][0]["table"] == "NOPE"
    l_table = report.table("L")
    assert l_table is not None
    assert l_table.column("X").default == "Y"  # type: ignore[union-attr]
    assert l_table.column("X").nullable is False  # type: ignore[union-attr]
    assert l_table.column("Y").default == SYSTEM_DEFAULT  # type: ignore[union-attr]


def test_ddl_sequence_field_is_stripped() -> None:
    source = "CREATE TABLE T (A INT);".ljust(72) + "00000100\n"
    assert parse_ddl(source).table("T") is not None


def test_ddl_statement_without_terminator() -> None:
    assert parse_ddl("CREATE TABLE T (A INT)").table("T") is not None


# ---------------------------------------------------------------------------
# IMS DBD / PSB
# ---------------------------------------------------------------------------


def test_dbd_segments_fields_and_hierarchy() -> None:
    report = parse_dbd(_sample("CUSTDBD.dbd"))
    (database,) = report.databases
    data = database.to_dict()
    assert data["name"] == "CUSTDB" and data["access"] == ["HIDAM", "VSAM"]
    assert data["datasets"] == ["CUSTDD"] and data["root"] == "CUSTOMER"
    segments = {s["name"]: s for s in data["segments"]}
    assert (
        segments["CUSTOMER"]["parent"] is None
        and segments["CUSTOMER"]["key"] == "CUSTNO"
    )
    assert (
        segments["ACCOUNT"]["parent"] == "CUSTOMER"
        and segments["ACCOUNT"]["bytes"] == 80
    )
    assert segments["ACCOUNT"]["fields"][0]["unique"] is False
    assert segments["TXN"]["parent"] == "ACCOUNT" and segments["TXN"]["key"] is None
    assert segments["CUSTOMER"]["lchildren"][0]["database"] == "CUSTIX"
    assert segments["CUSTOMER"]["xdfields"][0]["search_fields"] == ["CUSTNAME"]


def test_dbd_warnings() -> None:
    source = "\n".join(
        [
            "         SEGM  NAME=EARLY",
            "         FIELD NAME=F",
            "         LCHILD NAME=X",
            "         XDFLD NAME=X",
            "         DATASET DD1=X",
            "         DBD   ACCESS=HDAM",
            "         DBD   NAME=D",
            "         SEGM  PARENT=0",
            "         SEGM  NAME=S",
            "         FIELD BYTES=1",
            "         LCHILD POINTER=SNGL",
        ]
    )
    report = parse_dbd(source)
    assert [w["message"] for w in report.warnings] == [
        "SEGM before a DBD statement",
        "FIELD outside a SEGM",
        "DBD without NAME=",
        "SEGM without NAME=",
        "FIELD without NAME=",
    ]
    lchild = report.databases[0].segments[0].lchildren[0]
    assert lchild["segment"] is None and lchild["database"] is None
    assert report.databases[0].to_dict()["root"] == "S"
    assert parse_dbd("         DBD   NAME=E").databases[0].to_dict()["root"] is None


def test_psb_pcbs_and_sensitive_segments() -> None:
    report = parse_psb(_sample("CUSTPSB.psb"))
    (psb,) = report.psbs
    data = psb.to_dict()
    assert data["name"] == "CUSTUPD" and data["language"] == "COBOL"
    assert data["databases"] == ["CUSTDB", "EXTRACT"]
    io_pcb, db_pcb, gsam = data["pcbs"]
    assert io_pcb["type"] == "TP" and io_pcb["name"] == "IOPCB"
    assert (
        db_pcb["name"] == "CUSTPCB"
        and db_pcb["procopt"] == "A"
        and db_pcb["keylen"] == 26
    )
    assert [s["name"] for s in db_pcb["sensitive_segments"]] == ["CUSTOMER", "ACCOUNT"]
    assert db_pcb["sensitive_segments"][0]["procopt"] == "G"
    # SENSEG without PROCOPT inherits the PCB's.
    assert db_pcb["sensitive_segments"][1]["procopt"] == "A"
    assert gsam["type"] == "GSAM" and gsam["procopt"] == "LS"


def test_psb_positional_dbdname_and_missing_psbgen() -> None:
    source = (
        "         PCB   TYPE=DB,CUSTDB,PROCOPT=G\n"
        "         SENSEG PARENT=0\n"
        "         PCB   TYPE=TP\n"
    )
    report = parse_psb(source)
    assert report.psbs[0].name is None
    assert report.psbs[0].pcbs[0].dbdname == "CUSTDB"
    assert [w["message"] for w in report.warnings] == [
        "SENSEG outside a PCB",
        "PCBs without a PSBGEN statement",
    ]
    assert (
        parse_psb("         SENSEG NAME=X\n").warnings[0]["message"]
        == "SENSEG outside a PCB"
    )
