"""Unit tests for CRUDMatrixGenerator, CRUDMatrix, CRUDFlags, FileEntry, TableEntry.

Covers:
- CRUDFlags helpers (as_string, any, to_dict)
- FileEntry / TableEntry to_dict
- CRUDMatrix to_dict / to_json / to_csv / entries ordering
- CRUDMatrixGenerator: file CRUD (READ/WRITE/REWRITE/DELETE)
- CRUDMatrixGenerator: OPEN mode metadata tracking
- CRUDMatrixGenerator: SQL CRUD (SELECT/INSERT/UPDATE/DELETE)
- CRUDMatrixGenerator: DECLARE CURSOR + FETCH read-path marking
- CRUDMatrixGenerator: mixed file + SQL program
- CRUDMatrixGenerator: empty program (no IO)
- CRUDMatrixGenerator: multiple files / tables
"""

import json

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.crud_matrix import (
    CRUDFlags,
    CRUDMatrix,
    CRUDMatrixGenerator,
    FileEntry,
    TableEntry,
)


# ---------------------------------------------------------------------------
# CRUDFlags unit tests
# ---------------------------------------------------------------------------


class TestCRUDFlags:
    def test_default_all_false(self):
        flags = CRUDFlags()
        assert not flags.create
        assert not flags.read
        assert not flags.update
        assert not flags.delete

    def test_as_string_all_set(self):
        flags = CRUDFlags(create=True, read=True, update=True, delete=True)
        assert flags.as_string() == "CRUD"

    def test_as_string_none_set(self):
        assert CRUDFlags().as_string() == "----"

    def test_as_string_partial(self):
        flags = CRUDFlags(create=True, read=False, update=True, delete=False)
        assert flags.as_string() == "C-U-"

    def test_any_true_when_at_least_one(self):
        assert CRUDFlags(read=True).any()
        assert CRUDFlags(delete=True).any()

    def test_any_false_when_none(self):
        assert not CRUDFlags().any()

    def test_to_dict_keys(self):
        d = CRUDFlags(create=True, read=True).to_dict()
        assert d["create"] is True
        assert d["read"] is True
        assert d["update"] is False
        assert d["delete"] is False
        assert d["summary"] == "CR--"


# ---------------------------------------------------------------------------
# FileEntry unit tests
# ---------------------------------------------------------------------------


class TestFileEntry:
    def test_to_dict_structure(self):
        entry = FileEntry(
            program_name="MYPROG",
            file_name="CUSTOMER-FILE",
            crud=CRUDFlags(create=True, read=True),
            open_modes=["OUTPUT", "INPUT"],
            organization="INDEXED",
            access_mode="DYNAMIC",
        )
        d = entry.to_dict()
        assert d["program_name"] == "MYPROG"
        assert d["resource_type"] == "FILE"
        assert d["resource_name"] == "CUSTOMER-FILE"
        assert d["crud"]["create"] is True
        assert d["crud"]["read"] is True
        assert d["organization"] == "INDEXED"
        assert d["access_mode"] == "DYNAMIC"
        assert sorted(d["open_modes"]) == ["INPUT", "OUTPUT"]


# ---------------------------------------------------------------------------
# TableEntry unit tests
# ---------------------------------------------------------------------------


class TestTableEntry:
    def test_to_dict_structure(self):
        entry = TableEntry(
            program_name="DBPROG",
            table_name="ORDERS",
            crud=CRUDFlags(read=True, update=True),
            cursors=["CUR1"],
        )
        d = entry.to_dict()
        assert d["resource_type"] == "TABLE"
        assert d["resource_name"] == "ORDERS"
        assert d["crud"]["read"] is True
        assert d["crud"]["update"] is True
        assert "CUR1" in d["cursors"]


# ---------------------------------------------------------------------------
# CRUDMatrix unit tests
# ---------------------------------------------------------------------------


class TestCRUDMatrix:
    def _matrix(self):
        fe = FileEntry(
            "PROG",
            "INFILE",
            CRUDFlags(read=True),
            open_modes=["INPUT"],
            organization="SEQUENTIAL",
        )
        te = TableEntry("PROG", "ACCOUNTS", CRUDFlags(read=True, update=True))
        return CRUDMatrix(program_name="PROG", file_entries=[fe], table_entries=[te])

    def test_to_dict_keys(self):
        d = self._matrix().to_dict()
        assert "program_name" in d
        assert "files" in d
        assert "tables" in d
        assert d["summary"]["total_files"] == 1
        assert d["summary"]["total_tables"] == 1
        assert d["summary"]["total_resources"] == 2

    def test_to_json_valid(self):
        data = json.loads(self._matrix().to_json())
        assert data["program_name"] == "PROG"

    def test_to_csv_header_and_rows(self):
        csv_text = self._matrix().to_csv()
        lines = [l for l in csv_text.strip().splitlines() if l]
        assert lines[0].startswith("Program,ResourceType,ResourceName")
        # Header + 2 data rows
        assert len(lines) == 3

    def test_to_csv_file_row(self):
        csv_text = self._matrix().to_csv()
        assert "INFILE" in csv_text
        assert "FILE" in csv_text
        assert "R" in csv_text

    def test_to_csv_table_row(self):
        csv_text = self._matrix().to_csv()
        assert "ACCOUNTS" in csv_text
        assert "TABLE" in csv_text

    def test_entries_property_combined(self):
        m = self._matrix()
        entries = m.entries
        assert len(entries) == 2

    def test_empty_matrix(self):
        m = CRUDMatrix(program_name="EMPTY")
        assert m.to_dict()["summary"]["total_resources"] == 0
        assert m.entries == []
        csv_text = m.to_csv()
        # Only header line
        assert len([l for l in csv_text.strip().splitlines() if l]) == 1


# ---------------------------------------------------------------------------
# CRUDMatrixGenerator – file CRUD
# ---------------------------------------------------------------------------

_FILE_CRUD_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILECRUD.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUSTOMER-FILE
               ASSIGN TO 'CUST.DAT'
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS CUST-KEY
               FILE STATUS IS WS-STATUS.
           SELECT REPORT-FILE
               ASSIGN TO 'REPORT.TXT'
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-RPT-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD CUSTOMER-FILE.
       01 CUSTOMER-RECORD.
          05 CUST-KEY     PIC 9(8).
          05 CUST-NAME    PIC X(30).
       FD REPORT-FILE.
       01 REPORT-RECORD  PIC X(132).
       WORKING-STORAGE SECTION.
       01 WS-STATUS       PIC XX.
       01 WS-RPT-STATUS   PIC XX.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT CUSTOMER-FILE
           OPEN OUTPUT REPORT-FILE
           READ CUSTOMER-FILE
               AT END MOVE 'Y' TO WS-STATUS
           END-READ
           WRITE REPORT-RECORD FROM CUSTOMER-RECORD
           REWRITE CUSTOMER-RECORD
           DELETE CUSTOMER-FILE RECORD
           CLOSE CUSTOMER-FILE
           CLOSE REPORT-FILE
           STOP RUN.
"""


class TestCRUDMatrixGeneratorFiles:
    @pytest.fixture(autouse=True)
    def _parse(self):
        result = parse_cobol(_FILE_CRUD_SOURCE)
        assert result.ast is not None
        gen = CRUDMatrixGenerator()
        self.matrix = gen.analyze(result.ast)

    def test_customer_file_crud(self):
        files = {e.file_name: e for e in self.matrix.file_entries}
        assert "CUSTOMER-FILE" in files
        cf = files["CUSTOMER-FILE"]
        assert cf.crud.read, "READ should set R"
        assert cf.crud.update, "REWRITE should set U"
        assert cf.crud.delete, "DELETE should set D"
        # No WRITE to CUSTOMER-FILE
        assert not cf.crud.create

    def test_report_file_create(self):
        files = {e.file_name: e for e in self.matrix.file_entries}
        assert "REPORT-FILE" in files
        rf = files["REPORT-FILE"]
        assert rf.crud.create, "WRITE should set C"
        assert not rf.crud.read
        assert not rf.crud.update
        assert not rf.crud.delete

    def test_open_modes_tracked(self):
        files = {e.file_name: e for e in self.matrix.file_entries}
        cf = files["CUSTOMER-FILE"]
        assert "INPUT" in cf.open_modes
        rf = files["REPORT-FILE"]
        assert "OUTPUT" in rf.open_modes

    def test_file_metadata_from_select(self):
        files = {e.file_name: e for e in self.matrix.file_entries}
        cf = files["CUSTOMER-FILE"]
        assert cf.organization == "INDEXED"
        assert cf.access_mode == "DYNAMIC"

    def test_no_table_entries(self):
        assert self.matrix.table_entries == []

    def test_crud_string(self):
        files = {e.file_name: e for e in self.matrix.file_entries}
        assert files["CUSTOMER-FILE"].crud.as_string() == "-RUD"


# ---------------------------------------------------------------------------
# CRUDMatrixGenerator – SQL CRUD
# ---------------------------------------------------------------------------

_SQL_CRUD_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLCRUD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CUST-ID    PIC 9(8).
       01 WS-CUST-NAME  PIC X(30).
       01 WS-SQLCODE    PIC S9(9) COMP.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
               SELECT CUST_NAME INTO :WS-CUST-NAME
               FROM CUSTOMER
               WHERE CUST_ID = :WS-CUST-ID
           END-EXEC
           EXEC SQL
               INSERT INTO ORDERS (ORD_ID, CUST_ID)
               VALUES (:WS-CUST-ID, :WS-CUST-ID)
           END-EXEC
           EXEC SQL
               UPDATE CUSTOMER SET CUST_NAME = :WS-CUST-NAME
               WHERE CUST_ID = :WS-CUST-ID
           END-EXEC
           EXEC SQL
               DELETE FROM AUDIT_LOG
               WHERE CUST_ID = :WS-CUST-ID
           END-EXEC
           STOP RUN.
"""


class TestCRUDMatrixGeneratorSQL:
    @pytest.fixture(autouse=True)
    def _parse(self):
        result = parse_cobol(_SQL_CRUD_SOURCE)
        assert result.ast is not None
        gen = CRUDMatrixGenerator()
        self.matrix = gen.analyze(result.ast)

    def test_customer_read_and_update(self):
        tables = {e.table_name: e for e in self.matrix.table_entries}
        assert "CUSTOMER" in tables
        ct = tables["CUSTOMER"]
        assert ct.crud.read, "SELECT should mark R"
        assert ct.crud.update, "UPDATE should mark U"
        assert not ct.crud.create
        assert not ct.crud.delete

    def test_orders_create(self):
        tables = {e.table_name: e for e in self.matrix.table_entries}
        assert "ORDERS" in tables
        assert tables["ORDERS"].crud.create
        assert not tables["ORDERS"].crud.read

    def test_audit_log_delete(self):
        tables = {e.table_name: e for e in self.matrix.table_entries}
        assert "AUDIT_LOG" in tables
        assert tables["AUDIT_LOG"].crud.delete
        assert not tables["AUDIT_LOG"].crud.create

    def test_no_file_entries(self):
        assert self.matrix.file_entries == []

    def test_program_name_set(self):
        assert self.matrix.program_name == "SQLCRUD"


# ---------------------------------------------------------------------------
# CRUDMatrixGenerator – DECLARE CURSOR + FETCH
# ---------------------------------------------------------------------------

_CURSOR_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CURSTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ORD-ID   PIC 9(8).
       01 WS-ORD-AMT  PIC 9(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
               DECLARE ORDER-CURSOR CURSOR FOR
               SELECT ORD_ID, ORD_AMOUNT FROM ORDERS
               WHERE STATUS = 'OPEN'
           END-EXEC
           EXEC SQL
               OPEN ORDER-CURSOR
           END-EXEC
           EXEC SQL
               FETCH ORDER-CURSOR INTO :WS-ORD-ID, :WS-ORD-AMT
           END-EXEC
           EXEC SQL
               CLOSE ORDER-CURSOR
           END-EXEC
           STOP RUN.
"""


class TestCRUDMatrixGeneratorCursor:
    @pytest.fixture(autouse=True)
    def _parse(self):
        result = parse_cobol(_CURSOR_SOURCE)
        assert result.ast is not None
        gen = CRUDMatrixGenerator()
        self.matrix = gen.analyze(result.ast)

    def test_orders_read_via_cursor(self):
        tables = {e.table_name: e for e in self.matrix.table_entries}
        assert "ORDERS" in tables
        ot = tables["ORDERS"]
        assert ot.crud.read, "DECLARE CURSOR + FETCH should mark R"
        assert not ot.crud.create
        assert not ot.crud.update
        assert not ot.crud.delete

    def test_cursor_name_tracked(self):
        tables = {e.table_name: e for e in self.matrix.table_entries}
        ot = tables["ORDERS"]
        assert "ORDER-CURSOR" in ot.cursors


# ---------------------------------------------------------------------------
# CRUDMatrixGenerator – empty / no-IO program
# ---------------------------------------------------------------------------

_EMPTY_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOOP.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'Hello'.
           STOP RUN.
"""


class TestCRUDMatrixGeneratorEmpty:
    def test_empty_program_returns_empty_matrix(self):
        result = parse_cobol(_EMPTY_SOURCE)
        assert result.ast is not None
        gen = CRUDMatrixGenerator()
        matrix = gen.analyze(result.ast)
        assert matrix.file_entries == []
        assert matrix.table_entries == []
        assert matrix.program_name == "NOOP"


# ---------------------------------------------------------------------------
# CRUDMatrixGenerator – mixed file + SQL
# ---------------------------------------------------------------------------

_MIXED_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MIXED.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TRANS-FILE
               ASSIGN TO 'TRANS.DAT'
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD TRANS-FILE.
       01 TRANS-RECORD PIC X(80).
       WORKING-STORAGE SECTION.
       01 WS-AMOUNT PIC 9(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT TRANS-FILE
           READ TRANS-FILE AT END STOP RUN END-READ
           EXEC SQL
               INSERT INTO TRANSACTION_LOG (AMOUNT)
               VALUES (:WS-AMOUNT)
           END-EXEC
           CLOSE TRANS-FILE
           STOP RUN.
"""


class TestCRUDMatrixGeneratorMixed:
    @pytest.fixture(autouse=True)
    def _parse(self):
        result = parse_cobol(_MIXED_SOURCE)
        assert result.ast is not None
        gen = CRUDMatrixGenerator()
        self.matrix = gen.analyze(result.ast)

    def test_file_read(self):
        files = {e.file_name: e for e in self.matrix.file_entries}
        assert "TRANS-FILE" in files
        assert files["TRANS-FILE"].crud.read
        assert not files["TRANS-FILE"].crud.create

    def test_table_create(self):
        tables = {e.table_name: e for e in self.matrix.table_entries}
        assert "TRANSACTION_LOG" in tables
        assert tables["TRANSACTION_LOG"].crud.create

    def test_csv_has_both_resource_types(self):
        csv_text = self.matrix.to_csv()
        assert "FILE" in csv_text
        assert "TABLE" in csv_text

    def test_reanalyze_is_idempotent(self):
        """Calling analyze() twice on same generator resets state."""
        result = parse_cobol(_MIXED_SOURCE)
        gen = CRUDMatrixGenerator()
        m1 = gen.analyze(result.ast)
        m2 = gen.analyze(result.ast)
        assert len(m1.file_entries) == len(m2.file_entries)
        assert len(m1.table_entries) == len(m2.table_entries)


# ---------------------------------------------------------------------------
# CRUDMatrixGenerator – multiple OPEN modes on same file
# ---------------------------------------------------------------------------

_MULTI_OPEN_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTIOPEN.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MASTER-FILE
               ASSIGN TO 'MASTER.DAT'
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC.
       DATA DIVISION.
       FILE SECTION.
       FD MASTER-FILE.
       01 MASTER-RECORD.
          05 MASTER-KEY PIC 9(8).
       WORKING-STORAGE SECTION.
       PROCEDURE DIVISION.
       INIT-PARA.
           OPEN I-O MASTER-FILE
           READ MASTER-FILE AT END STOP RUN END-READ
           REWRITE MASTER-RECORD
           DELETE MASTER-FILE RECORD
           WRITE MASTER-RECORD
           CLOSE MASTER-FILE
           STOP RUN.
"""


class TestMultipleOpenModes:
    @pytest.fixture(autouse=True)
    def _parse(self):
        result = parse_cobol(_MULTI_OPEN_SOURCE)
        assert result.ast is not None
        gen = CRUDMatrixGenerator()
        self.matrix = gen.analyze(result.ast)

    def test_all_crud_set(self):
        files = {e.file_name: e for e in self.matrix.file_entries}
        mf = files["MASTER-FILE"]
        assert mf.crud.create
        assert mf.crud.read
        assert mf.crud.update
        assert mf.crud.delete
        assert mf.crud.as_string() == "CRUD"

    def test_io_open_mode_tracked(self):
        files = {e.file_name: e for e in self.matrix.file_entries}
        assert "I-O" in files["MASTER-FILE"].open_modes


# ---------------------------------------------------------------------------
# Public API import
# ---------------------------------------------------------------------------


def test_public_api_imports():
    """CRUDMatrixGenerator and friends are importable from cobolparser."""
    from cobolparser import CRUDFlags, CRUDMatrix, CRUDMatrixGenerator, FileEntry, TableEntry

    assert CRUDMatrixGenerator is not None
    assert CRUDMatrix is not None
    assert CRUDFlags is not None
    assert FileEntry is not None
    assert TableEntry is not None
