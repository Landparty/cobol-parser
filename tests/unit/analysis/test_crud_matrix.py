"""Unit tests for CRUDMatrixGenerator, CRUDMatrix, CRUDFlags, FileEntry, TableEntry.

Covers:
- CRUDFlags helpers (as_string, any, to_dict), each individual flag
- FileEntry / TableEntry to_dict, null fields, deduplication
- CRUDMatrix to_dict / to_json(indent) / to_csv / entries ordering
- CRUDMatrix CSV: Extra and Organization column content
- CRUDMatrix: program_name=None
- CRUDMatrixGenerator: file CRUD (READ/WRITE/REWRITE/DELETE)
- CRUDMatrixGenerator: OPEN mode metadata – EXTEND, multi-file, dedup
- CRUDMatrixGenerator: file open but no IO ops → open_modes set, CRUD ----
- CRUDMatrixGenerator: no DATA DIVISION (no crash)
- CRUDMatrixGenerator: SD (sort description) FD variant
- CRUDMatrixGenerator: multiple 01-level records per FD
- CRUDMatrixGenerator: WRITE/REWRITE with record not in any FD → no entry
- CRUDMatrixGenerator: case normalisation (all names → upper-case)
- CRUDMatrixGenerator: SQL CRUD (SELECT/INSERT/UPDATE/DELETE, same table all ops)
- CRUDMatrixGenerator: SELECT with JOIN → multiple tables as R
- CRUDMatrixGenerator: non-DML SQL (COMMIT/ROLLBACK/WHENEVER/OPEN/CLOSE) → no entries
- CRUDMatrixGenerator: DECLARE CURSOR + FETCH read-path marking
- CRUDMatrixGenerator: two cursors on same table → both cursor names tracked
- CRUDMatrixGenerator: DECLARE CURSOR with no FROM tables → no table entry
- CRUDMatrixGenerator: FETCH for undeclared cursor → no crash, no entry
- CRUDMatrixGenerator: mixed file + SQL program
- CRUDMatrixGenerator: empty program (no IO)
- CRUDMatrixGenerator: entries ordering
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
        lines = [ln for ln in csv_text.strip().splitlines() if ln]
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
        assert len([ln for ln in csv_text.strip().splitlines() if ln]) == 1


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
    from cobolparser import (
        CRUDFlags,
        CRUDMatrix,
        CRUDMatrixGenerator,
        FileEntry,
        TableEntry,
    )

    assert CRUDMatrixGenerator is not None
    assert CRUDMatrix is not None
    assert CRUDFlags is not None
    assert FileEntry is not None
    assert TableEntry is not None


# ---------------------------------------------------------------------------
# CRUDFlags – each individual flag in as_string
# ---------------------------------------------------------------------------


class TestCRUDFlagsEachFlag:
    def test_only_create(self):
        assert CRUDFlags(create=True).as_string() == "C---"

    def test_only_read(self):
        assert CRUDFlags(read=True).as_string() == "-R--"

    def test_only_update(self):
        assert CRUDFlags(update=True).as_string() == "--U-"

    def test_only_delete(self):
        assert CRUDFlags(delete=True).as_string() == "---D"

    def test_create_delete(self):
        assert CRUDFlags(create=True, delete=True).as_string() == "C--D"

    def test_read_update(self):
        assert CRUDFlags(read=True, update=True).as_string() == "-RU-"


# ---------------------------------------------------------------------------
# FileEntry – null fields and open_modes deduplication in to_dict
# ---------------------------------------------------------------------------


class TestFileEntryNullFields:
    def test_null_organization_and_access_mode(self):
        entry = FileEntry(program_name="PROG", file_name="F")
        d = entry.to_dict()
        assert d["organization"] is None
        assert d["access_mode"] is None

    def test_open_modes_deduplicated_in_to_dict(self):
        entry = FileEntry("P", "F", open_modes=["INPUT", "INPUT", "I-O"])
        d = entry.to_dict()
        assert d["open_modes"] == ["I-O", "INPUT"]  # sorted(set(...))

    def test_empty_open_modes(self):
        entry = FileEntry("P", "F")
        assert entry.to_dict()["open_modes"] == []


# ---------------------------------------------------------------------------
# TableEntry – empty cursors
# ---------------------------------------------------------------------------


class TestTableEntryEmptyCursors:
    def test_empty_cursors_list(self):
        entry = TableEntry("P", "T")
        assert entry.to_dict()["cursors"] == []

    def test_duplicate_cursors_deduplicated(self):
        entry = TableEntry("P", "T", cursors=["CUR1", "CUR1", "CUR2"])
        d = entry.to_dict()
        assert d["cursors"] == ["CUR1", "CUR2"]  # sorted(set(...))


# ---------------------------------------------------------------------------
# CRUDMatrix – detailed CSV field content and ordering
# ---------------------------------------------------------------------------


class TestCRUDMatrixCSVDetails:
    def test_csv_open_modes_in_extra_column(self):
        fe = FileEntry("P", "INFILE", CRUDFlags(read=True), open_modes=["I-O", "INPUT"])
        m = CRUDMatrix(program_name="P", file_entries=[fe])
        csv_text = m.to_csv()
        # Extra column should contain pipe-separated open modes
        assert "I-O|INPUT" in csv_text

    def test_csv_cursor_names_in_extra_column(self):
        te = TableEntry("P", "ORDERS", CRUDFlags(read=True), cursors=["CUR1", "CUR2"])
        m = CRUDMatrix(program_name="P", table_entries=[te])
        csv_text = m.to_csv()
        assert "CUR1|CUR2" in csv_text

    def test_csv_organization_in_organization_column(self):
        fe = FileEntry(
            "P", "IDX", CRUDFlags(read=True), organization="INDEXED", open_modes=[]
        )
        m = CRUDMatrix(program_name="P", file_entries=[fe])
        csv_text = m.to_csv()
        assert "INDEXED" in csv_text

    def test_csv_empty_flags_shown_as_blank(self):
        fe = FileEntry("P", "F", CRUDFlags())  # no CRUD at all
        m = CRUDMatrix(program_name="P", file_entries=[fe])
        csv_text = m.to_csv()
        data_line = [ln for ln in csv_text.strip().splitlines() if "FILE" in ln][0]
        # C, R, U, D columns should be empty (not "C"/"R"/"U"/"D")
        assert "----" in data_line


class TestCRUDMatrixEntriesOrdering:
    def test_files_sorted_alphabetically(self):
        fe1 = FileEntry("P", "ZFILE", CRUDFlags())
        fe2 = FileEntry("P", "AFILE", CRUDFlags())
        m = CRUDMatrix(program_name="P", file_entries=[fe1, fe2])
        names = [e.file_name for e in m.entries]
        assert names == sorted(names)

    def test_tables_sorted_alphabetically(self):
        te1 = TableEntry("P", "ZTABLE", CRUDFlags())
        te2 = TableEntry("P", "ATABLE", CRUDFlags())
        m = CRUDMatrix(program_name="P", table_entries=[te1, te2])
        names = [e.table_name for e in m.entries]
        assert names == sorted(names)

    def test_mixed_sorted_together_by_name(self):
        fe = FileEntry("P", "MFILE", CRUDFlags())
        te = TableEntry("P", "ATABLE", CRUDFlags())
        m = CRUDMatrix(program_name="P", file_entries=[fe], table_entries=[te])
        # ATABLE < MFILE alphabetically
        assert m.entries[0].table_name == "ATABLE"  # type: ignore[union-attr]
        assert m.entries[1].file_name == "MFILE"  # type: ignore[union-attr]


class TestCRUDMatrixToJsonCustomIndent:
    def test_indent_4(self):
        import json

        te = TableEntry("P", "T", CRUDFlags(read=True))
        m = CRUDMatrix(program_name="P", table_entries=[te])
        data = json.loads(m.to_json(indent=4))
        assert data["program_name"] == "P"
        assert m.to_json(indent=4).startswith("{\n    ")

    def test_indent_0(self):
        # json.dumps(indent=0) still emits newlines but no leading spaces
        m = CRUDMatrix(program_name="P")
        output = m.to_json(indent=0)
        assert "    " not in output  # no 4-space indentation
        assert '"program_name"' in output


class TestCRUDMatrixProgramNameNone:
    def test_none_program_name_in_json(self):
        import json

        m = CRUDMatrix(program_name=None)
        data = json.loads(m.to_json())
        assert data["program_name"] is None

    def test_none_program_name_in_csv(self):
        fe = FileEntry("", "F", CRUDFlags(read=True))
        m = CRUDMatrix(program_name=None, file_entries=[fe])
        csv_text = m.to_csv()
        assert "FILE" in csv_text  # must not crash


# ---------------------------------------------------------------------------
# CRUDMatrixGenerator – OPEN mode edge cases
# ---------------------------------------------------------------------------

_EXTEND_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXTDPROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT LOG-FILE ASSIGN TO 'LOG.TXT'
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD LOG-FILE.
       01 LOG-RECORD PIC X(132).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN EXTEND LOG-FILE
           WRITE LOG-RECORD
           CLOSE LOG-FILE
           STOP RUN.
"""

_MULTI_OPEN_STMT_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTIOP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT FILE1 ASSIGN TO F1.
           SELECT FILE2 ASSIGN TO F2.
       DATA DIVISION.
       FILE SECTION.
       FD FILE1.
       01 REC1 PIC X(80).
       FD FILE2.
       01 REC2 PIC X(80).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT FILE1 FILE2
           CLOSE FILE1
           CLOSE FILE2
           STOP RUN.
"""

_OPEN_ONLY_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OPENONLY.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT GHOST-FILE ASSIGN TO GH.
       DATA DIVISION.
       FILE SECTION.
       FD GHOST-FILE.
       01 GHOST-REC PIC X(80).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT GHOST-FILE
           CLOSE GHOST-FILE
           STOP RUN.
"""

_DUP_OPEN_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DUPOPEN.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SEQ-FILE ASSIGN TO X.
       DATA DIVISION.
       FILE SECTION.
       FD SEQ-FILE.
       01 SEQ-REC PIC X(80).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT SEQ-FILE
           CLOSE SEQ-FILE
           OPEN INPUT SEQ-FILE
           CLOSE SEQ-FILE
           STOP RUN.
"""


class TestOpenModeEdgeCases:
    def test_extend_mode_tracked(self):
        result = parse_cobol(_EXTEND_SOURCE)
        m = CRUDMatrixGenerator().analyze(result.ast)
        files = {e.file_name: e for e in m.file_entries}
        assert "EXTEND" in files["LOG-FILE"].open_modes

    def test_extend_write_marks_create(self):
        result = parse_cobol(_EXTEND_SOURCE)
        m = CRUDMatrixGenerator().analyze(result.ast)
        files = {e.file_name: e for e in m.file_entries}
        assert files["LOG-FILE"].crud.create

    def test_multiple_files_in_one_open_stmt(self):
        result = parse_cobol(_MULTI_OPEN_STMT_SOURCE)
        m = CRUDMatrixGenerator().analyze(result.ast)
        files = {e.file_name: e for e in m.file_entries}
        assert "INPUT" in files["FILE1"].open_modes
        assert "INPUT" in files["FILE2"].open_modes

    def test_file_open_only_no_crud(self):
        result = parse_cobol(_OPEN_ONLY_SOURCE)
        m = CRUDMatrixGenerator().analyze(result.ast)
        files = {e.file_name: e for e in m.file_entries}
        ghost = files["GHOST-FILE"]
        assert "INPUT" in ghost.open_modes
        assert ghost.crud.as_string() == "----"
        assert not ghost.crud.any()

    def test_duplicate_open_mode_deduplicated(self):
        result = parse_cobol(_DUP_OPEN_SOURCE)
        m = CRUDMatrixGenerator().analyze(result.ast)
        files = {e.file_name: e for e in m.file_entries}
        # INPUT should appear exactly once
        assert files["SEQ-FILE"].open_modes.count("INPUT") == 1


# ---------------------------------------------------------------------------
# CRUDMatrixGenerator – case normalisation
# ---------------------------------------------------------------------------

_MIXEDCASE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MIXCASE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT My-File ASSIGN TO X.
       DATA DIVISION.
       FILE SECTION.
       FD My-File.
       01 My-Record PIC X(80).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT My-File
           READ My-File AT END STOP RUN END-READ
           WRITE My-Record
           STOP RUN.
"""


class TestCaseNormalisation:
    def test_file_name_upper_cased(self):
        result = parse_cobol(_MIXEDCASE_SOURCE)
        m = CRUDMatrixGenerator().analyze(result.ast)
        file_names = {e.file_name for e in m.file_entries}
        assert "MY-FILE" in file_names
        assert "My-File" not in file_names

    def test_read_and_write_on_same_normalised_entry(self):
        result = parse_cobol(_MIXEDCASE_SOURCE)
        m = CRUDMatrixGenerator().analyze(result.ast)
        files = {e.file_name: e for e in m.file_entries}
        assert files["MY-FILE"].crud.read
        assert files["MY-FILE"].crud.create


# ---------------------------------------------------------------------------
# CRUDMatrixGenerator – WRITE/REWRITE with unknown record (no mapping)
# ---------------------------------------------------------------------------

_UNKNOWN_RECORD_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNKRCD.
       PROCEDURE DIVISION.
       MAIN-PARA.
           WRITE GHOST-RECORD
           REWRITE GHOST-RECORD
           STOP RUN.
"""


class TestUnknownRecordWrite:
    def test_no_entry_when_record_not_in_mapping(self):
        """WRITE/REWRITE for records with no FD mapping must not create entries."""
        result = parse_cobol(_UNKNOWN_RECORD_SOURCE)
        assert result.ast is not None
        m = CRUDMatrixGenerator().analyze(result.ast)
        assert m.file_entries == []

    def test_no_crash(self):
        result = parse_cobol(_UNKNOWN_RECORD_SOURCE)
        assert result.ast is not None
        # Must not raise
        CRUDMatrixGenerator().analyze(result.ast)


# ---------------------------------------------------------------------------
# CRUDMatrixGenerator – multiple 01-level records per FD
# ---------------------------------------------------------------------------

_MULTI_REC_FD_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTIREC.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT VSAM-FILE ASSIGN TO VSAM.
       DATA DIVISION.
       FILE SECTION.
       FD VSAM-FILE.
       01 VSAM-REC-A.
          05 KEY-A PIC X(10).
       01 VSAM-REC-B.
          05 KEY-B PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN I-O VSAM-FILE
           WRITE VSAM-REC-A
           REWRITE VSAM-REC-B
           CLOSE VSAM-FILE
           STOP RUN.
"""


class TestMultipleRecordsPerFD:
    @pytest.fixture(autouse=True)
    def _parse(self):
        result = parse_cobol(_MULTI_REC_FD_SOURCE)
        assert result.ast is not None
        self.matrix = CRUDMatrixGenerator().analyze(result.ast)

    def test_single_file_entry(self):
        assert len(self.matrix.file_entries) == 1

    def test_write_via_first_record_sets_create(self):
        files = {e.file_name: e for e in self.matrix.file_entries}
        assert files["VSAM-FILE"].crud.create

    def test_rewrite_via_second_record_sets_update(self):
        files = {e.file_name: e for e in self.matrix.file_entries}
        assert files["VSAM-FILE"].crud.update


# ---------------------------------------------------------------------------
# CRUDMatrixGenerator – SD (sort description) declaration
# ---------------------------------------------------------------------------

_SD_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SDPROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INP.
           SELECT SORT-WK ASSIGN TO SORTWORK.
           SELECT OUT-FILE ASSIGN TO OUTP.
       DATA DIVISION.
       FILE SECTION.
       FD IN-FILE.
       01 IN-RECORD PIC X(80).
       SD SORT-WK.
       01 SORT-RECORD PIC X(80).
       FD OUT-FILE.
       01 OUT-RECORD PIC X(80).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE
           OPEN OUTPUT OUT-FILE
           READ IN-FILE AT END STOP RUN END-READ
           WRITE SORT-RECORD FROM IN-RECORD
           WRITE OUT-RECORD FROM SORT-RECORD
           CLOSE IN-FILE
           CLOSE OUT-FILE
           STOP RUN.
"""


class TestSDDeclaration:
    @pytest.fixture(autouse=True)
    def _parse(self):
        result = parse_cobol(_SD_SOURCE)
        assert result.ast is not None
        self.matrix = CRUDMatrixGenerator().analyze(result.ast)

    def test_sort_record_maps_to_sort_file(self):
        files = {e.file_name: e for e in self.matrix.file_entries}
        assert "SORT-WK" in files

    def test_write_via_sort_record_sets_create(self):
        files = {e.file_name: e for e in self.matrix.file_entries}
        assert files["SORT-WK"].crud.create

    def test_out_record_maps_to_out_file(self):
        files = {e.file_name: e for e in self.matrix.file_entries}
        assert files["OUT-FILE"].crud.create


# ---------------------------------------------------------------------------
# CRUDMatrixGenerator – no DATA DIVISION (no crash)
# ---------------------------------------------------------------------------

_NO_DATA_DIV_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NODATA.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT FILE1 ASSIGN TO F1.
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


class TestNoDataDivision:
    def test_no_crash_and_no_file_entries(self):
        result = parse_cobol(_NO_DATA_DIV_SOURCE)
        assert result.ast is not None
        m = CRUDMatrixGenerator().analyze(result.ast)
        # File appears from SELECT metadata but no FD records
        # No CRUD operations, so CRUD is ----
        files = {e.file_name: e for e in m.file_entries}
        if files:
            assert not files["FILE1"].crud.any()

    def test_no_crash_at_all(self):
        result = parse_cobol(_NO_DATA_DIV_SOURCE)
        assert result.ast is not None
        CRUDMatrixGenerator().analyze(result.ast)  # must not raise


# ---------------------------------------------------------------------------
# CRUDMatrixGenerator – SQL: same table with all four DML operations
# ---------------------------------------------------------------------------

_ALL_SQL_OPS_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALLSQL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ID PIC 9(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
               SELECT ID FROM MYTABLE WHERE ID = :WS-ID
           END-EXEC
           EXEC SQL
               INSERT INTO MYTABLE (ID) VALUES (:WS-ID)
           END-EXEC
           EXEC SQL
               UPDATE MYTABLE SET ID = :WS-ID WHERE ID = :WS-ID
           END-EXEC
           EXEC SQL
               DELETE FROM MYTABLE WHERE ID = :WS-ID
           END-EXEC
           STOP RUN.
"""


class TestSQLAllOperationsOneTable:
    def test_all_crud_flags_set(self):
        result = parse_cobol(_ALL_SQL_OPS_SOURCE)
        assert result.ast is not None
        m = CRUDMatrixGenerator().analyze(result.ast)
        tables = {e.table_name: e for e in m.table_entries}
        assert "MYTABLE" in tables
        assert tables["MYTABLE"].crud.as_string() == "CRUD"


# ---------------------------------------------------------------------------
# CRUDMatrixGenerator – SQL: SELECT with JOIN marks multiple tables as R
# ---------------------------------------------------------------------------

_JOIN_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. JOINPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STATUS PIC X(6).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
               SELECT C.NAME, O.AMOUNT
               FROM CUSTOMER C
               JOIN ORDERS O ON C.ID = O.CUST_ID
               WHERE C.STATUS = :WS-STATUS
           END-EXEC
           STOP RUN.
"""


class TestSQLSelectWithJoin:
    def test_both_tables_marked_read(self):
        result = parse_cobol(_JOIN_SOURCE)
        assert result.ast is not None
        m = CRUDMatrixGenerator().analyze(result.ast)
        tables = {e.table_name: e for e in m.table_entries}
        assert "CUSTOMER" in tables
        assert "ORDERS" in tables
        assert tables["CUSTOMER"].crud.read
        assert tables["ORDERS"].crud.read

    def test_no_create_update_delete_from_select_join(self):
        result = parse_cobol(_JOIN_SOURCE)
        assert result.ast is not None
        m = CRUDMatrixGenerator().analyze(result.ast)
        tables = {e.table_name: e for e in m.table_entries}
        for table in tables.values():
            assert not table.crud.create
            assert not table.crud.update
            assert not table.crud.delete


# ---------------------------------------------------------------------------
# CRUDMatrixGenerator – SQL: non-DML statements produce no table entries
# ---------------------------------------------------------------------------

_NONDML_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NONDML.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL COMMIT WORK END-EXEC
           EXEC SQL ROLLBACK END-EXEC
           EXEC SQL WHENEVER SQLERROR CONTINUE END-EXEC
           EXEC SQL INCLUDE SQLCA END-EXEC
           STOP RUN.
"""


class TestSQLNonDMLStatements:
    def test_commit_rollback_whenever_include_produce_no_entries(self):
        result = parse_cobol(_NONDML_SOURCE)
        assert result.ast is not None
        m = CRUDMatrixGenerator().analyze(result.ast)
        assert m.table_entries == []
        assert m.file_entries == []


# ---------------------------------------------------------------------------
# CRUDMatrixGenerator – Cursor edge cases
# ---------------------------------------------------------------------------

_TWO_CURSORS_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWOCURS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ID  PIC 9(8).
       01 WS-AMT PIC 9(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
               DECLARE CUR1 CURSOR FOR
               SELECT ID FROM ORDERS
           END-EXEC
           EXEC SQL
               DECLARE CUR2 CURSOR FOR
               SELECT AMT FROM ORDERS
           END-EXEC
           EXEC SQL
               FETCH CUR1 INTO :WS-ID
           END-EXEC
           EXEC SQL
               FETCH CUR2 INTO :WS-AMT
           END-EXEC
           STOP RUN.
"""

_ORPHAN_CURSOR_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORPHANC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAL PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
               FETCH ORPHAN-CURSOR INTO :WS-VAL
           END-EXEC
           STOP RUN.
"""

_CURSOR_NO_TABLES_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CNTBL.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
               DECLARE DYN-CUR CURSOR FOR STMT1
           END-EXEC
           EXEC SQL
               FETCH DYN-CUR INTO :WS1
           END-EXEC
           STOP RUN.
"""


class TestCursorEdgeCases:
    def test_two_cursors_on_same_table_both_tracked(self):
        result = parse_cobol(_TWO_CURSORS_SOURCE)
        assert result.ast is not None
        m = CRUDMatrixGenerator().analyze(result.ast)
        tables = {e.table_name: e for e in m.table_entries}
        assert "ORDERS" in tables
        cursors = sorted(tables["ORDERS"].cursors)
        assert "CUR1" in cursors
        assert "CUR2" in cursors

    def test_two_cursors_on_same_table_single_entry(self):
        result = parse_cobol(_TWO_CURSORS_SOURCE)
        assert result.ast is not None
        m = CRUDMatrixGenerator().analyze(result.ast)
        assert len(m.table_entries) == 1

    def test_fetch_for_undeclared_cursor_no_crash(self):
        result = parse_cobol(_ORPHAN_CURSOR_SOURCE)
        assert result.ast is not None
        m = CRUDMatrixGenerator().analyze(result.ast)
        assert m.table_entries == []

    def test_declare_cursor_no_tables_no_entry(self):
        """DECLARE CURSOR using a prepared statement name has no FROM tables."""
        result = parse_cobol(_CURSOR_NO_TABLES_SOURCE)
        assert result.ast is not None
        m = CRUDMatrixGenerator().analyze(result.ast)
        assert m.table_entries == []


# ---------------------------------------------------------------------------
# CRUDMatrixGenerator – SQL: a write statement's subquery tables are only read
# ---------------------------------------------------------------------------

_SUBQUERY_WRITES_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBQ.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL DELETE FROM ORDERS
               WHERE CUST_ID IN (SELECT ID FROM CLOSED_CUST)
           END-EXEC
           EXEC SQL UPDATE ACCOUNT SET RATE = 1
               WHERE TIER = (SELECT MAX(TIER) FROM TIERS)
           END-EXEC
           EXEC SQL INSERT INTO ARCHIVE SELECT * FROM HISTORY END-EXEC
           EXEC SQL MERGE INTO BALANCE B USING DAILY_TXN D
               ON B.ID = D.ID
               WHEN MATCHED THEN UPDATE SET B.AMT = D.AMT
               WHEN NOT MATCHED THEN INSERT (ID, AMT) VALUES (D.ID, D.AMT)
           END-EXEC
           EXEC SQL SELECT EXTRACT(YEAR FROM HIRE_DATE) INTO :WS-Y
               FROM EMP
           END-EXEC
           STOP RUN.
"""


class TestSQLWriteSubqueryTables:
    def test_crud_per_table(self):
        result = parse_cobol(_SUBQUERY_WRITES_SOURCE)
        assert result.ast is not None
        m = CRUDMatrixGenerator().analyze(result.ast)
        crud = {e.table_name: e.crud.as_string() for e in m.table_entries}
        assert crud == {
            "ORDERS": "---D",
            "CLOSED_CUST": "-R--",
            "ACCOUNT": "--U-",
            "TIERS": "-R--",
            "ARCHIVE": "C---",
            "HISTORY": "-R--",
            "BALANCE": "C-U-",
            "DAILY_TXN": "-R--",
            "EMP": "-R--",
        }


# ---------------------------------------------------------------------------
# Regression (2026-09-28): SORT/MERGE USING/GIVING and RELEASE/RETURN
# ---------------------------------------------------------------------------

_SORT_USING_GIVING_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SRTUG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE  ASSIGN TO INFILE.
           SELECT OUT-FILE ASSIGN TO OUTFILE.
           SELECT M2-FILE  ASSIGN TO M2FILE.
           SELECT SRT-FILE ASSIGN TO SORTWK.
           SELECT WRK-FILE ASSIGN TO SORTWK2.
       DATA DIVISION.
       FILE SECTION.
       FD IN-FILE.
       01 IN-REC  PIC X(80).
       FD OUT-FILE.
       01 OUT-REC PIC X(80).
       FD M2-FILE.
       01 M2-REC  PIC X(80).
       SD SRT-FILE.
       01 SRT-REC.
          05 SRT-KEY PIC X(10).
          05 FILLER  PIC X(70).
       SD WRK-FILE.
       01 WRK-REC.
          05 WRK-KEY PIC X(10).
          05 FILLER  PIC X(70).
       WORKING-STORAGE SECTION.
       01 WS-EOF PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           SORT SRT-FILE ON ASCENDING KEY SRT-KEY
                USING IN-FILE GIVING OUT-FILE
           MERGE SRT-FILE ON ASCENDING KEY SRT-KEY
                USING IN-FILE M2-FILE GIVING OUT-FILE
           SORT WRK-FILE ON ASCENDING KEY WRK-KEY
                INPUT PROCEDURE IS IN-PROC
                OUTPUT PROCEDURE IS OUT-PROC
           STOP RUN.
       IN-PROC.
           RELEASE WRK-REC.
       OUT-PROC.
           RETURN WRK-FILE AT END MOVE 'Y' TO WS-EOF.
"""


class TestSortMergeFileAccess:
    """A SORT/MERGE reads its USING files and writes its GIVING files
    itself -- no READ/WRITE statement of the program names them -- so they
    used to come out of the matrix as ``----``."""

    def test_crud_per_file(self):
        result = parse_cobol(_SORT_USING_GIVING_SOURCE)
        assert result.ast is not None
        m = CRUDMatrixGenerator().analyze(result.ast)
        crud = {e.file_name: e.crud.as_string() for e in m.file_entries}
        assert crud["IN-FILE"] == "-R--"
        assert crud["M2-FILE"] == "-R--"
        assert crud["OUT-FILE"] == "C---"
        # RELEASE writes the SD work file, RETURN reads it back.
        assert crud["WRK-FILE"] == "CR--"
