"""Comprehensive parser coverage tests using real COBOL examples.

These tests target specific uncovered code paths in parser.py to achieve
near-total test coverage. Each test uses realistic COBOL code examples.
"""

import pytest
from cobolparser.parser import CobolParser, ParseResult, parse_cobol
from cobolparser.plugins.core import ErrorRecoveryMode, DialectType


class TestProgramIDClauses:
    """Test PROGRAM-ID with optional clauses (IS INITIAL, IS COMMON)."""
    
    def test_program_id_with_is_initial(self):
        """Test PROGRAM-ID with IS INITIAL clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG IS INITIAL.
       PROCEDURE DIVISION.
           DISPLAY 'HELLO'.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
        assert result.ast.program_name == "TESTPROG"
    
    def test_program_id_with_is_common(self):
        """Test PROGRAM-ID with IS COMMON clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMMONPG IS COMMON.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
        assert result.ast.program_name == "COMMONPG"
    
    def test_program_id_with_multiple_clauses(self):
        """Test PROGRAM-ID with multiple IS clauses."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTIPROG IS INITIAL IS COMMON.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
        assert result.ast.program_name == "MULTIPROG"


class TestEnvironmentDivisionEdgeCases:
    """Test edge cases in ENVIRONMENT DIVISION parsing."""
    
    def test_environment_division_with_configuration_section(self):
        """Test ENVIRONMENT DIVISION with CONFIGURATION SECTION."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ENVTEST.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. IBM-390.
       OBJECT-COMPUTER. IBM-390.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TESTFILE ASSIGN TO "TEST.DAT".
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
        env_div = result.ast.get_division("ENVIRONMENT")
        assert env_div is not None
    
    def test_environment_division_missing_division_keyword(self):
        """Test ENVIRONMENT token not followed by DIVISION."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ENVTEST.
       ENVIRONMENT
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        # Should recover and continue parsing
        assert result.ast is not None


class TestSelectStatementClauses:
    """Test comprehensive SELECT statement clause parsing."""
    
    def test_select_with_optional_file(self):
        """Test SELECT OPTIONAL file."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELECTOPT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OPTIONAL INPUTFILE
               ASSIGN TO "INPUT.DAT"
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-FILE-STATUS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-FILE-STATUS PIC XX.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_select_with_indexed_organization(self):
        """Test SELECT with INDEXED organization and keys."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELECTIDX.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INDEXEDFILE
               ASSIGN TO DISK "INDEXED.DAT"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS FILE-KEY
               ALTERNATE RECORD KEY IS ALT-KEY WITH DUPLICATES.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 FILE-KEY PIC X(10).
       01 ALT-KEY PIC X(5).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_select_with_relative_organization(self):
        """Test SELECT with RELATIVE organization."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELECTREL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RELFILE
               ASSIGN TO "REL.DAT"
               ORGANIZATION IS RELATIVE
               ACCESS MODE IS RANDOM
               RELATIVE KEY IS REL-KEY-NUM
               FILE STATUS IS WS-STATUS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 REL-KEY-NUM PIC 9(5).
       01 WS-STATUS PIC XX.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_select_with_line_sequential(self):
        """Test SELECT with LINE SEQUENTIAL organization."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELECTLINE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TEXTFILE
               ASSIGN TO "TEXT.TXT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_select_with_reserve_clause(self):
        """Test SELECT with RESERVE clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELECTRES.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT BIGFILE
               ASSIGN TO "BIG.DAT"
               RESERVE 5 AREAS
               FILE STATUS IS WS-STATUS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STATUS PIC XX.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_select_with_padding_character(self):
        """Test SELECT with PADDING CHARACTER clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELECTPAD.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PADFILE
               ASSIGN TO "PAD.DAT"
               PADDING CHARACTER IS SPACES.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_select_with_record_delimiter(self):
        """Test SELECT with RECORD DELIMITER clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELECTDEL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT DELIMFILE
               ASSIGN TO "DELIM.DAT"
               RECORD DELIMITER IS STANDARD-1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_select_with_password(self):
        """Test SELECT with PASSWORD clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELECTPWD.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SECUREFILE
               ASSIGN TO "SECURE.DAT"
               PASSWORD IS WS-PASSWORD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-PASSWORD PIC X(8).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_select_with_lock_mode(self):
        """Test SELECT with LOCK MODE clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELECTLOCK.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT LOCKFILE
               ASSIGN TO "LOCK.DAT"
               LOCK MODE IS AUTOMATIC
               WITH LOCK ON RECORD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_select_with_sharing(self):
        """Test SELECT with SHARING clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELECTSHARE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SHAREFILE
               ASSIGN TO "SHARE.DAT"
               SHARING WITH ALL OTHER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_select_sharing_no_other(self):
        """Test SELECT with SHARING NO OTHER clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELECTSHRNO.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EXCLUSIVEFILE
               ASSIGN TO "EXCL.DAT"
               SHARING WITH NO OTHER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_select_sharing_read_only(self):
        """Test SELECT with SHARING READ ONLY clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELECTSHRD.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT READONLYFILE
               ASSIGN TO "READ.DAT"
               SHARING WITH READ ONLY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_select_with_device_type(self):
        """Test SELECT with device type ASSIGN."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELECTDEV.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PRINTFILE
               ASSIGN TO PRINTER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_select_with_alternate_key_password(self):
        """Test SELECT with ALTERNATE KEY and PASSWORD."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELECTALTPW.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SECUREIDX
               ASSIGN TO "SECIDX.DAT"
               ORGANIZATION IS INDEXED
               RECORD KEY IS PRIMARY-KEY
               ALTERNATE RECORD KEY IS ALT-KEY
                   WITH DUPLICATES
                   PASSWORD IS KEY-PASSWORD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 PRIMARY-KEY PIC X(10).
       01 ALT-KEY PIC X(5).
       01 KEY-PASSWORD PIC X(8).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_select_with_vsam_file_status(self):
        """Test SELECT with two FILE STATUS variables (VSAM)."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELECTVSAM.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT VSAMFILE
               ASSIGN TO "VSAM.DAT"
               ORGANIZATION IS INDEXED
               FILE STATUS IS WS-STATUS, WS-VSAM-STATUS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STATUS PIC XX.
       01 WS-VSAM-STATUS PIC X(6).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_select_with_record_key_source(self):
        """Test SELECT with RECORD KEY SOURCE clause (IBM extension)."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELECTSRC.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SRCFILE
               ASSIGN TO "SRC.DAT"
               ORGANIZATION IS INDEXED
               RECORD KEY IS FILE-KEY SOURCE IS WS-KEY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 FILE-KEY PIC X(10).
       01 WS-KEY PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None


class TestFDRecordClauses:
    """Test comprehensive FD/SD record clause parsing."""
    
    def test_fd_with_block_contains_range(self):
        """Test FD with BLOCK CONTAINS range."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDBLOCK.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT BLOCKFILE ASSIGN TO "BLOCK.DAT".
       DATA DIVISION.
       FILE SECTION.
       FD BLOCKFILE
           BLOCK CONTAINS 1 TO 10 RECORDS.
       01 BLOCK-REC PIC X(80).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_fd_with_record_contains_variable(self):
        """Test FD with RECORD CONTAINS variable length."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDRECVAR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT VARFILE ASSIGN TO "VAR.DAT".
       DATA DIVISION.
       FILE SECTION.
       FD VARFILE
           RECORD CONTAINS 50 TO 200 CHARACTERS
           DEPENDING ON REC-LENGTH.
       01 VAR-REC.
          05 REC-DATA PIC X(200).
       WORKING-STORAGE SECTION.
       01 REC-LENGTH PIC 9(4).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_fd_with_record_is_varying(self):
        """Test FD with RECORD IS VARYING clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDVARYING.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT VARYFILE ASSIGN TO "VARY.DAT".
       DATA DIVISION.
       FILE SECTION.
       FD VARYFILE
           RECORD IS VARYING IN SIZE
           FROM 10 TO 100 CHARACTERS
           DEPENDING ON WS-SIZE.
       01 VARY-REC PIC X(100).
       WORKING-STORAGE SECTION.
       01 WS-SIZE PIC 9(4).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_fd_with_label_records_standard(self):
        """Test FD with LABEL RECORDS STANDARD."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDLABEL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT LABELFILE ASSIGN TO "LABEL.DAT".
       DATA DIVISION.
       FILE SECTION.
       FD LABELFILE
           LABEL RECORDS ARE STANDARD.
       01 LABEL-REC PIC X(80).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_fd_with_label_records_omitted(self):
        """Test FD with LABEL RECORDS OMITTED."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDNOLABEL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT NOLABELFILE ASSIGN TO "NOLABEL.DAT".
       DATA DIVISION.
       FILE SECTION.
       FD NOLABELFILE
           LABEL RECORDS ARE OMITTED.
       01 NOLABEL-REC PIC X(80).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_fd_with_value_of(self):
        """Test FD with VALUE OF clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDVALUE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT VALUEFILE ASSIGN TO "VALUE.DAT".
       DATA DIVISION.
       FILE SECTION.
       FD VALUEFILE
           VALUE OF FILE-ID IS "MYFILE".
       01 VALUE-REC PIC X(80).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_fd_with_data_records(self):
        """Test FD with DATA RECORDS clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDDATA.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT DATAFILE ASSIGN TO "DATA.DAT".
       DATA DIVISION.
       FILE SECTION.
       FD DATAFILE
           DATA RECORDS ARE HEADER-REC, DETAIL-REC.
       01 HEADER-REC PIC X(80).
       01 DETAIL-REC PIC X(120).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_fd_with_linage(self):
        """Test FD with LINAGE clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDLINAGE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PRINTFILE ASSIGN TO "PRINT.DAT".
       DATA DIVISION.
       FILE SECTION.
       FD PRINTFILE
           LINAGE IS 60 LINES
           WITH FOOTING AT 55
           LINES AT TOP 3
           LINES AT BOTTOM 3.
       01 PRINT-LINE PIC X(132).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_fd_with_code_set(self):
        """Test FD with CODE-SET clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDCODESET.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CODEFILE ASSIGN TO "CODE.DAT".
       DATA DIVISION.
       FILE SECTION.
       FD CODEFILE
           CODE-SET IS ASCII.
       01 CODE-REC PIC X(80).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_fd_with_recording_mode(self):
        """Test FD with RECORDING MODE clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDRECMODE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MODEFILE ASSIGN TO "MODE.DAT".
       DATA DIVISION.
       FILE SECTION.
       FD MODEFILE
           RECORDING MODE IS V.
       01 MODE-REC PIC X(80).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_fd_with_report_clause(self):
        """Test FD with REPORT IS clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDREPORT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RPTFILE ASSIGN TO "RPT.DAT".
       DATA DIVISION.
       FILE SECTION.
       FD RPTFILE
           REPORT IS SALES-REPORT.
       01 RPT-REC PIC X(132).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_fd_with_external_global(self):
        """Test FD with EXTERNAL and GLOBAL attributes."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDEXTGLOB.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EXTFILE ASSIGN TO "EXT.DAT".
       DATA DIVISION.
       FILE SECTION.
       FD EXTFILE
           EXTERNAL
           GLOBAL
           BLOCK CONTAINS 10 RECORDS.
       01 EXT-REC PIC X(80).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_sd_sort_description(self):
        """Test SD (Sort Description) record."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SDSORT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SORTFILE ASSIGN TO "SORT.DAT".
       DATA DIVISION.
       FILE SECTION.
       SD SORTFILE.
       01 SORT-REC.
          05 SORT-KEY PIC X(10).
          05 SORT-DATA PIC X(70).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None


class TestExecStatements:
    """Test EXEC SQL, EXEC CICS, and EXEC IMS parsing."""
    
    def test_exec_sql_select(self):
        """Test EXEC SQL SELECT statement."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXECSQL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NAME PIC X(30).
       01 WS-ID PIC 9(5).
       PROCEDURE DIVISION.
           EXEC SQL
               SELECT NAME INTO :WS-NAME
               FROM EMPLOYEES
               WHERE ID = :WS-ID
           END-EXEC.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_exec_sql_insert(self):
        """Test EXEC SQL INSERT statement."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXECSQLINS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NAME PIC X(30).
       01 WS-ID PIC 9(5).
       PROCEDURE DIVISION.
           EXEC SQL
               INSERT INTO EMPLOYEES (ID, NAME)
               VALUES (:WS-ID, :WS-NAME)
           END-EXEC.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_exec_cics_send(self):
        """Test EXEC CICS SEND statement."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXECCICS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-MESSAGE PIC X(80).
       PROCEDURE DIVISION.
           EXEC CICS
               SEND FROM(WS-MESSAGE)
               LENGTH(80)
           END-EXEC.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_exec_cics_receive(self):
        """Test EXEC CICS RECEIVE statement."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXECCICSRCV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-INPUT PIC X(80).
       01 WS-LENGTH PIC S9(4) COMP.
       PROCEDURE DIVISION.
           EXEC CICS
               RECEIVE INTO(WS-INPUT)
               LENGTH(WS-LENGTH)
           END-EXEC.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_exec_ims_statement(self):
        """Test EXEC IMS statement."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXECIMS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-PCB PIC X(80).
       PROCEDURE DIVISION.
           EXEC IMS
               GU PCB(WS-PCB)
           END-EXEC.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None


class TestDataItemEdgeCases:
    """Test edge cases in data item parsing."""
    
    def test_data_item_with_sync(self):
        """Test data item with SYNC/SYNCHRONIZED clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DATASYNC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-RECORD.
          05 WS-NUMBER PIC 9(8) COMP SYNC.
          05 WS-AMOUNT PIC 9(9)V99 COMP-3 SYNCHRONIZED RIGHT.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_data_item_anonymous(self):
        """Test anonymous data items (level with FILLER implied)."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DATAANON.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-RECORD.
          05 PIC X(5).
          05 VALUE "TEST".
          05 PIC 9(4).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_data_item_with_redefines(self):
        """Test data item with REDEFINES clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DATAREDEF.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-RECORD.
          05 WS-DATE-NUM PIC 9(8).
          05 WS-DATE-CHAR REDEFINES WS-DATE-NUM.
             10 WS-YEAR PIC X(4).
             10 WS-MONTH PIC X(2).
             10 WS-DAY PIC X(2).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_data_item_with_occurs_depending(self):
        """Test data item with OCCURS DEPENDING ON."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DATAOCC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-COUNT PIC 9(3).
       01 WS-TABLE.
          05 WS-ITEM OCCURS 1 TO 100 TIMES DEPENDING ON WS-COUNT
             PIC X(20).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_data_item_usage_is_form(self):
        """Test data item with USAGE IS form."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DATAUSAGE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-FIELDS.
          05 WS-NUM1 PIC 9(8) USAGE IS COMP.
          05 WS-NUM2 PIC 9(8) USAGE IS COMPUTATIONAL.
          05 WS-NUM3 PIC 9(8) USAGE IS DISPLAY.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None


class TestProcedureStatementEdgeCases:
    """Test edge cases in procedure division statement parsing."""
    
    def test_goto_depending_on(self):
        """Test GO TO ... DEPENDING ON statement."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTODEP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-INDEX PIC 9.
       PROCEDURE DIVISION.
           GO TO PARA-1 PARA-2 PARA-3
               DEPENDING ON WS-INDEX.
       PARA-1.
           DISPLAY 'ONE'.
       PARA-2.
           DISPLAY 'TWO'.
       PARA-3.
           DISPLAY 'THREE'.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_if_else_statement(self):
        """Test IF/ELSE statement parsing."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IFELSE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VALUE PIC 9(3).
       PROCEDURE DIVISION.
           IF WS-VALUE > 100
               DISPLAY 'HIGH'
           ELSE
               DISPLAY 'LOW'.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_call_with_returning(self):
        """Test CALL statement with RETURNING clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLRET.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-RESULT PIC 9(8).
       01 WS-PARAM PIC X(10).
       PROCEDURE DIVISION.
           CALL 'SUBPROG' USING WS-PARAM
               RETURNING WS-RESULT.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_call_with_by_value(self):
        """Test CALL statement with BY VALUE."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLVAL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NUM PIC 9(8).
       PROCEDURE DIVISION.
           CALL 'SUBPROG' USING BY VALUE WS-NUM.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_call_with_by_content(self):
        """Test CALL statement with BY CONTENT."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLCONT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-DATA PIC X(20).
       PROCEDURE DIVISION.
           CALL 'SUBPROG' USING BY CONTENT WS-DATA.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_sort_statement(self):
        """Test SORT statement with procedures."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SORTTEST.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SORTFILE ASSIGN TO "SORT.DAT".
       DATA DIVISION.
       FILE SECTION.
       SD SORTFILE.
       01 SORT-REC.
          05 SORT-KEY PIC X(10).
          05 SORT-DATA PIC X(70).
       PROCEDURE DIVISION.
           SORT SORTFILE
               ASCENDING KEY SORT-KEY
               INPUT PROCEDURE IS INPUT-PARA
               OUTPUT PROCEDURE IS OUTPUT-PARA.
       INPUT-PARA.
           DISPLAY 'INPUT'.
       OUTPUT-PARA.
           DISPLAY 'OUTPUT'.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_move_with_decimal_literal(self):
        """Test MOVE with decimal literal starting with period."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MOVEDEC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-AMOUNT PIC 9V99.
       PROCEDURE DIVISION.
           MOVE .99 TO WS-AMOUNT.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_move_with_signed_decimal(self):
        """Test MOVE with signed decimal literal."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MOVESIGN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-AMOUNT PIC S9V99.
       PROCEDURE DIVISION.
           MOVE -.50 TO WS-AMOUNT.
           MOVE +.75 TO WS-AMOUNT.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_procedure_division_using(self):
        """Test PROCEDURE DIVISION USING clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROCUSING.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LS-PARAM1 PIC X(10).
       01 LS-PARAM2 PIC 9(5).
       PROCEDURE DIVISION USING LS-PARAM1, LS-PARAM2.
           DISPLAY LS-PARAM1.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None


class TestLocalAndLinkageSections:
    """Test LOCAL-STORAGE and LINKAGE SECTION parsing."""
    
    def test_local_storage_section(self):
        """Test LOCAL-STORAGE SECTION parsing."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOCALSTOR.
       DATA DIVISION.
       LOCAL-STORAGE SECTION.
       01 LS-COUNTER PIC 9(5) VALUE 0.
       01 LS-FLAG PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           ADD 1 TO LS-COUNTER.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_linkage_section(self):
        """Test LINKAGE SECTION parsing."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LINKTEST.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-INPUT-RECORD.
          05 LK-KEY PIC X(10).
          05 LK-DATA PIC X(90).
       PROCEDURE DIVISION USING LK-INPUT-RECORD.
           DISPLAY LK-KEY.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None


class TestPeriodHandlingEdgeCases:
    """Test period handling edge cases to cover lines 248-251."""
    
    def test_period_after_newline_in_data_division(self):
        """Test period that appears after newline in DATA DIVISION."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PERIODTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC

           PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_period_in_numeric_edited_picture(self):
        """Test period within numeric edited picture."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PERIODPIC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-AMOUNT PIC $$$,$$9.99.
       01 WS-RATE PIC ZZZ.99.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None


class TestSectionAndParagraphParsing:
    """Test section and paragraph parsing in PROCEDURE DIVISION."""
    
    def test_named_section(self):
        """Test named sections in PROCEDURE DIVISION."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       PROCEDURE DIVISION.
       MAIN-SECTION SECTION.
       MAIN-PARA.
           PERFORM UTIL-SECTION.
           STOP RUN.
       UTIL-SECTION SECTION.
       UTIL-PARA.
           DISPLAY 'UTILITY'.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
        proc_div = result.ast.get_division("PROCEDURE")
        assert proc_div is not None


class TestErrorRecoveryModes:
    """Test different error recovery modes."""
    
    def test_collect_all_mode_with_errors(self):
        """Test COLLECT_ALL mode collects all errors."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        # Should continue parsing despite errors
        assert result.ast is not None or len(result.errors) > 0
    
    def test_fail_fast_mode_with_errors(self):
        """Test FAIL_FAST mode stops on first error."""
        source = """
       XXXXXXXXXXX.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.FAIL_FAST)
        # Should fail fast
        assert result.ast is None or len(result.errors) > 0


class TestParseFileMethod:
    """Test the parse_file method."""
    
    def test_parse_nonexistent_file(self, tmp_path):
        """Test parsing a file that doesn't exist."""
        parser = CobolParser()
        result = parser.parse_file(str(tmp_path / "nonexistent.cob"))
        assert result.ast is None
        assert len(result.errors) > 0
    
    def test_parse_existing_file(self, tmp_path):
        """Test parsing an existing file."""
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILETEST.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        test_file = tmp_path / "test.cob"
        test_file.write_text(source)
        
        parser = CobolParser()
        result = parser.parse_file(str(test_file))
        assert result.ast is not None


class TestParseResultProperties:
    """Test ParseResult properties."""
    
    def test_success_property_true(self):
        """Test success property when parsing succeeds."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUCCESS.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success is True
    
    def test_has_warnings_property(self):
        """Test has_warnings property."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. WARNTEST.
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source)
        # Initially no warnings
        assert result.has_warnings is False


class TestConvenienceParseFunction:
    """Test the convenience parse_cobol function."""
    
    def test_parse_cobol_with_preprocessing(self):
        """Test parse_cobol with preprocess_fixed option."""
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PREPROC.
       PROCEDURE DIVISION.
           STOP RUN."""
        result = parse_cobol(source, preprocess_fixed=True)
        assert result.ast is not None
    
    def test_parse_cobol_free_form(self):
        """Test parse_cobol with free_form option."""
        source = """IDENTIFICATION DIVISION.
PROGRAM-ID. FREEFORM.
PROCEDURE DIVISION.
STOP RUN."""
        result = parse_cobol(source, free_form=True)
        assert result.ast is not None


class TestLockModeAdvanced:
    """Test advanced LOCK MODE clause variations."""
    
    def test_lock_mode_with_rollback(self):
        """Test LOCK MODE with ROLLBACK clause."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOCKROLL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT LOCKFILE
               ASSIGN TO "LOCK.DAT"
               LOCK MODE IS EXCLUSIVE
               WITH ROLLBACK.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
    
    def test_lock_mode_with_lock_on_multiple_records(self):
        """Test LOCK MODE with LOCK ON MULTIPLE RECORDS."""
        source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOCKMULT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT LOCKFILE
               ASSIGN TO "LOCK.DAT"
               LOCK MODE IS MANUAL
               WITH LOCK ON MULTIPLE RECORDS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       PROCEDURE DIVISION.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.ast is not None
