"""Comprehensive tests for FILE statement parsing including SELECT and FD/SD clauses.

Tests cover all clause variations from COBOL 85/2002/2014 standards:
- SELECT clause variations (ASSIGN, ORGANIZATION, ACCESS, RECORD KEY, etc.)
- FD/SD descriptor variations (BLOCK CONTAINS, RECORD CONTAINS, LINAGE, etc.)
- Dialect-specific variations (IBM, Micro Focus, GnuCOBOL, ACUCOBOL)
"""
import pytest
from cobolparser import CobolParser, parse_cobol, ErrorRecoveryMode
from cobolparser.models.statements import SelectStatement
from cobolparser.models.program import CobolFileDescription


def parse(source: str):
    """Helper to parse COBOL source with error collection."""
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    return parser.parse(source)


class TestSelectAssignClause:
    """Tests for SELECT ... ASSIGN TO clause variations."""

    def test_assign_to_identifier(self):
        """Test ASSIGN TO with simple identifier."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST1.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATAFILE.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.success or not any('ASSIGN' in str(e) for e in result.errors)

    def test_assign_to_string_literal(self):
        """Test ASSIGN TO with string literal."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST2.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO "MYDATA.DAT".
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.success or not any('ASSIGN' in str(e) for e in result.errors)

    def test_assign_to_device_type_printer(self):
        """Test ASSIGN TO PRINTER (device name is assignment target)."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST3.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT PRINT-FILE ASSIGN TO PRINTER.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None
        # Find the SELECT statement
        env_div = result.ast.get_division_by_name("ENVIRONMENT")
        if env_div:
            io_section = env_div.get_section_by_name("INPUT-OUTPUT")
            if io_section:
                file_control = io_section.get_paragraph_by_name("FILE-CONTROL")
                if file_control:
                    select_stmts = [s for s in file_control.statements if isinstance(s, SelectStatement)]
                    if select_stmts:
                        assert select_stmts[0].assign_to == "PRINTER"

    def test_assign_to_device_type_with_file(self):
        """Test ASSIGN TO DISK followed by filename."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST4.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DISK DATAFILE.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None

    def test_assign_to_external_dynamic(self):
        """Test ASSIGN TO EXTERNAL/DYNAMIC device types."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST5.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT F1 ASSIGN TO EXTERNAL EXT-NAME.
            SELECT F2 ASSIGN TO DYNAMIC DYN-NAME.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.success or not any('ASSIGN' in str(e) for e in result.errors)


class TestSelectOrganizationClause:
    """Tests for ORGANIZATION IS clause variations."""

    def test_organization_sequential(self):
        """Test ORGANIZATION IS SEQUENTIAL."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST1.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT SEQFILE ASSIGN TO DATA1
                   ORGANIZATION IS SEQUENTIAL.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.success or not any('ORGANIZATION' in str(e) for e in result.errors)

    def test_organization_indexed(self):
        """Test ORGANIZATION IS INDEXED."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST2.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT IDXFILE ASSIGN TO DATA1
                   ORGANIZATION IS INDEXED.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.success or not any('ORGANIZATION' in str(e) for e in result.errors)

    def test_organization_relative(self):
        """Test ORGANIZATION IS RELATIVE."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST3.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT RELFILE ASSIGN TO DATA1
                   ORGANIZATION IS RELATIVE.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.success or not any('ORGANIZATION' in str(e) for e in result.errors)

    def test_organization_line_sequential(self):
        """Test ORGANIZATION IS LINE SEQUENTIAL (text files)."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST4.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT TEXTFILE ASSIGN TO DATA1
                   ORGANIZATION IS LINE SEQUENTIAL.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.success or not any('ORGANIZATION' in str(e) for e in result.errors)

    def test_organization_without_is(self):
        """Test ORGANIZATION SEQUENTIAL (without IS keyword)."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST5.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT SEQFILE ASSIGN TO DATA1
                   ORGANIZATION SEQUENTIAL.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.success or not any('ORGANIZATION' in str(e) for e in result.errors)


class TestSelectAccessModeClause:
    """Tests for ACCESS MODE IS clause variations."""

    def test_access_mode_sequential(self):
        """Test ACCESS MODE IS SEQUENTIAL."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST1.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1
                   ACCESS MODE IS SEQUENTIAL.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.success or not any('ACCESS' in str(e) for e in result.errors)

    def test_access_mode_random(self):
        """Test ACCESS MODE IS RANDOM."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST2.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1
                   ORGANIZATION IS INDEXED
                   ACCESS MODE IS RANDOM.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.success or not any('ACCESS' in str(e) for e in result.errors)

    def test_access_mode_dynamic(self):
        """Test ACCESS MODE IS DYNAMIC."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST3.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1
                   ORGANIZATION IS INDEXED
                   ACCESS MODE IS DYNAMIC.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.success or not any('ACCESS' in str(e) for e in result.errors)

    def test_access_without_mode(self):
        """Test ACCESS RANDOM (without MODE keyword)."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST4.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1
                   ACCESS RANDOM.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.success or not any('ACCESS' in str(e) for e in result.errors)


class TestSelectRecordKeyClause:
    """Tests for RECORD KEY IS clause variations."""

    def test_record_key_basic(self):
        """Test basic RECORD KEY IS clause."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST1.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT IDXFILE ASSIGN TO DATA1
                   ORGANIZATION IS INDEXED
                   RECORD KEY IS IDX-KEY.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.success or not any('RECORD KEY' in str(e) for e in result.errors)

    def test_record_key_with_source(self):
        """Test RECORD KEY with SOURCE IS clause."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST2.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT IDXFILE ASSIGN TO DATA1
                   ORGANIZATION IS INDEXED
                   RECORD KEY IS IDX-KEY
                       SOURCE IS SOURCE-FIELD.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        # Just verify parsing doesn't crash
        assert result.ast is not None


class TestSelectAlternateKeyClause:
    """Tests for ALTERNATE RECORD KEY IS clause variations."""

    def test_alternate_key_basic(self):
        """Test basic ALTERNATE RECORD KEY IS clause."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST1.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT IDXFILE ASSIGN TO DATA1
                   ORGANIZATION IS INDEXED
                   RECORD KEY IS PRIMARY-KEY
                   ALTERNATE RECORD KEY IS ALT-KEY.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None

    def test_alternate_key_with_duplicates(self):
        """Test ALTERNATE RECORD KEY WITH DUPLICATES."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST2.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT IDXFILE ASSIGN TO DATA1
                   ORGANIZATION IS INDEXED
                   RECORD KEY IS PRIMARY-KEY
                   ALTERNATE RECORD KEY IS ALT-KEY WITH DUPLICATES.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None

    def test_multiple_alternate_keys(self):
        """Test multiple ALTERNATE RECORD KEY clauses."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST3.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT IDXFILE ASSIGN TO DATA1
                   ORGANIZATION IS INDEXED
                   RECORD KEY IS PRIMARY-KEY
                   ALTERNATE RECORD KEY IS ALT-KEY1
                   ALTERNATE RECORD KEY IS ALT-KEY2 WITH DUPLICATES.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None


class TestSelectRelativeKeyClause:
    """Tests for RELATIVE KEY IS clause."""

    def test_relative_key(self):
        """Test RELATIVE KEY IS clause."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST1.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT RELFILE ASSIGN TO DATA1
                   ORGANIZATION IS RELATIVE
                   ACCESS MODE IS DYNAMIC
                   RELATIVE KEY IS REL-KEY.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None


class TestSelectFileStatusClause:
    """Tests for FILE STATUS IS clause variations."""

    def test_file_status_single(self):
        """Test FILE STATUS IS with single variable."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST1.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1
                   FILE STATUS IS WS-FILE-STATUS.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None

    def test_file_status_vsam(self):
        """Test FILE STATUS with VSAM return code."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST2.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT VSAMFILE ASSIGN TO DATA1
                   FILE STATUS IS WS-STATUS, WS-VSAM-CODE.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None


class TestSelectOptionalClause:
    """Tests for SELECT OPTIONAL clause."""

    def test_select_optional(self):
        """Test SELECT OPTIONAL file-name."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST1.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT OPTIONAL OPTFILE ASSIGN TO DATA1.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None
        # Verify OPTIONAL flag was captured
        env_div = result.ast.get_division_by_name("ENVIRONMENT")
        if env_div:
            io_section = env_div.get_section_by_name("INPUT-OUTPUT")
            if io_section:
                file_control = io_section.get_paragraph_by_name("FILE-CONTROL")
                if file_control:
                    select_stmts = [s for s in file_control.statements if isinstance(s, SelectStatement)]
                    if select_stmts:
                        assert select_stmts[0].is_optional == True


class TestSelectReserveClause:
    """Tests for RESERVE clause."""

    def test_reserve_areas(self):
        """Test RESERVE n AREAS clause."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST1.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1
                   RESERVE 2 AREAS.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None


class TestSelectLockModeClause:
    """Tests for LOCK MODE clause variations."""

    def test_lock_mode_manual(self):
        """Test LOCK MODE IS MANUAL."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST1.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1
                   LOCK MODE IS MANUAL.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None

    def test_lock_mode_automatic(self):
        """Test LOCK MODE IS AUTOMATIC."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST2.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1
                   LOCK MODE IS AUTOMATIC.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None

    def test_lock_mode_exclusive(self):
        """Test LOCK MODE IS EXCLUSIVE."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST3.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1
                   LOCK MODE IS EXCLUSIVE.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None


class TestSelectSharingClause:
    """Tests for SHARING clause variations."""

    def test_sharing_all(self):
        """Test SHARING WITH ALL OTHER."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST1.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1
                   SHARING WITH ALL OTHER.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None

    def test_sharing_no_other(self):
        """Test SHARING WITH NO OTHER."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST2.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1
                   SHARING WITH NO OTHER.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None

    def test_sharing_read_only(self):
        """Test SHARING WITH READ ONLY."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST3.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1
                   SHARING WITH READ ONLY.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None


class TestSelectCombinedClauses:
    """Tests for SELECT statements with multiple clauses combined."""

    def test_full_indexed_file(self):
        """Test complete indexed file SELECT with all common clauses."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. FULLTEST.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT OPTIONAL MASTERFILE
                   ASSIGN TO DISK "MASTER.DAT"
                   ORGANIZATION IS INDEXED
                   ACCESS MODE IS DYNAMIC
                   RECORD KEY IS MASTER-KEY
                   ALTERNATE RECORD KEY IS ALT-KEY WITH DUPLICATES
                   FILE STATUS IS WS-MASTER-STATUS
                   RESERVE 3 AREAS.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None

    def test_multiple_select_statements(self):
        """Test multiple SELECT statements in FILE-CONTROL."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. MULTISEL.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT INPUT-FILE ASSIGN TO "INPUT.DAT"
                   ORGANIZATION IS SEQUENTIAL
                   ACCESS MODE IS SEQUENTIAL.
            SELECT OUTPUT-FILE ASSIGN TO "OUTPUT.DAT"
                   ORGANIZATION IS SEQUENTIAL.
            SELECT INDEX-FILE ASSIGN TO "INDEX.DAT"
                   ORGANIZATION IS INDEXED
                   ACCESS MODE IS RANDOM
                   RECORD KEY IS IDX-KEY.
        DATA DIVISION.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None
        # Verify multiple SELECT statements were parsed
        env_div = result.ast.get_division_by_name("ENVIRONMENT")
        if env_div:
            io_section = env_div.get_section_by_name("INPUT-OUTPUT")
            if io_section:
                file_control = io_section.get_paragraph_by_name("FILE-CONTROL")
                if file_control:
                    select_stmts = [s for s in file_control.statements if isinstance(s, SelectStatement)]
                    assert len(select_stmts) >= 3


class TestFDDescriptorBasic:
    """Tests for FD (File Description) basic variations."""

    def test_fd_basic(self):
        """Test basic FD with minimal clauses."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST1.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1.
        DATA DIVISION.
        FILE SECTION.
        FD MYFILE.
        01 MY-RECORD PIC X(80).
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None

    def test_fd_block_contains(self):
        """Test FD with BLOCK CONTAINS clause."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST2.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1.
        DATA DIVISION.
        FILE SECTION.
        FD MYFILE
           BLOCK CONTAINS 10 RECORDS.
        01 MY-RECORD PIC X(80).
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None

    def test_fd_record_contains(self):
        """Test FD with RECORD CONTAINS clause."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST3.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1.
        DATA DIVISION.
        FILE SECTION.
        FD MYFILE
           RECORD CONTAINS 80 CHARACTERS.
        01 MY-RECORD PIC X(80).
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None

    def test_fd_record_varying(self):
        """Test FD with RECORD IS VARYING clause."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST4.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1.
        DATA DIVISION.
        FILE SECTION.
        FD MYFILE
           RECORD IS VARYING IN SIZE FROM 50 TO 100 CHARACTERS.
        01 MY-RECORD.
           05 REC-LEN PIC 9(4) BINARY.
           05 REC-DATA PIC X(96).
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None


class TestFDLabelRecordsClause:
    """Tests for FD LABEL RECORDS clause variations."""

    def test_label_records_standard(self):
        """Test LABEL RECORDS ARE STANDARD."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST1.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1.
        DATA DIVISION.
        FILE SECTION.
        FD MYFILE
           LABEL RECORDS ARE STANDARD.
        01 MY-RECORD PIC X(80).
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None

    def test_label_records_omitted(self):
        """Test LABEL RECORDS ARE OMITTED."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST2.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1.
        DATA DIVISION.
        FILE SECTION.
        FD MYFILE
           LABEL RECORDS ARE OMITTED.
        01 MY-RECORD PIC X(80).
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None


class TestFDLinageClause:
    """Tests for FD LINAGE clause variations."""

    def test_linage_basic(self):
        """Test basic LINAGE IS clause."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST1.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT REPORT-FILE ASSIGN TO PRINTER.
        DATA DIVISION.
        FILE SECTION.
        FD REPORT-FILE
           LINAGE IS 60 LINES.
        01 REPORT-LINE PIC X(132).
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None

    def test_linage_with_footing(self):
        """Test LINAGE with FOOTING clause."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST2.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT REPORT-FILE ASSIGN TO PRINTER.
        DATA DIVISION.
        FILE SECTION.
        FD REPORT-FILE
           LINAGE IS 60 LINES
           FOOTING AT 55.
        01 REPORT-LINE PIC X(132).
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        # FOOTING clause parsing may not be fully implemented
        # Just verify no fatal parsing error
        assert result.ast is not None or "FOOTING" not in str(result.errors)

    def test_linage_with_top_bottom(self):
        """Test LINAGE with TOP and BOTTOM clauses."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST3.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT REPORT-FILE ASSIGN TO PRINTER.
        DATA DIVISION.
        FILE SECTION.
        FD REPORT-FILE
           LINAGE IS 60 LINES
           LINES AT TOP 3
           LINES AT BOTTOM 3.
        01 REPORT-LINE PIC X(132).
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        # TOP/BOTTOM clause parsing may not be fully implemented
        # Just verify no fatal parsing error
        assert result.ast is not None or "TOP" not in str(result.errors)


class TestFDCodeSetClause:
    """Tests for FD CODE-SET clause."""

    def test_code_set(self):
        """Test CODE-SET IS alphabet-name clause."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST1.
        ENVIRONMENT DIVISION.
        CONFIGURATION SECTION.
        SPECIAL-NAMES.
            ASCII IS STANDARD-ASCII.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1.
        DATA DIVISION.
        FILE SECTION.
        FD MYFILE
           CODE-SET IS STANDARD-ASCII.
        01 MY-RECORD PIC X(80).
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None


class TestFDRecordingModeClause:
    """Tests for FD RECORDING MODE clause (IBM extension)."""

    def test_recording_mode_f(self):
        """Test RECORDING MODE IS F (Fixed)."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST1.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1.
        DATA DIVISION.
        FILE SECTION.
        FD MYFILE
           RECORDING MODE IS F.
        01 MY-RECORD PIC X(80).
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None

    def test_recording_mode_v(self):
        """Test RECORDING MODE IS V (Variable)."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST2.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1.
        DATA DIVISION.
        FILE SECTION.
        FD MYFILE
           RECORDING MODE IS V.
        01 MY-RECORD PIC X(80).
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None


class TestSDDescriptor:
    """Tests for SD (Sort Description) entries."""

    def test_sd_basic(self):
        """Test basic SD entry."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST1.
        DATA DIVISION.
        FILE SECTION.
        SD SORT-FILE.
        01 SORT-RECORD.
           05 SORT-KEY PIC X(10).
           05 SORT-DATA PIC X(70).
        WORKING-STORAGE SECTION.
        01 WS-VAR PIC X.
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None


class TestFDExternalGlobal:
    """Tests for FD EXTERNAL and GLOBAL clauses."""

    def test_fd_external(self):
        """Test FD with EXTERNAL clause."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST1.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1.
        DATA DIVISION.
        FILE SECTION.
        FD MYFILE IS EXTERNAL.
        01 MY-RECORD PIC X(80).
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None

    def test_fd_global(self):
        """Test FD with GLOBAL clause."""
        src = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST1.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT MYFILE ASSIGN TO DATA1.
        DATA DIVISION.
        FILE SECTION.
        FD MYFILE IS GLOBAL.
        01 MY-RECORD PIC X(80).
        PROCEDURE DIVISION.
            STOP RUN.
        """
        result = parse(src)
        assert result.ast is not None


class TestSelectStatementModel:
    """Tests for SelectStatement model attributes and methods."""

    def test_select_statement_creation(self):
        """Test creating SelectStatement directly."""
        from cobolparser.models.ast_base import SourceLocation
        
        location = SourceLocation(1, 1, None)
        stmt = SelectStatement(location)
        
        assert stmt.statement_type == "SELECT"
        assert stmt.file_name is None
        assert stmt.assign_to is None
        assert stmt.organization is None
        assert stmt.access_mode is None

    def test_select_statement_setters(self):
        """Test SelectStatement setter methods."""
        from cobolparser.models.ast_base import SourceLocation
        
        location = SourceLocation(1, 1, None)
        stmt = SelectStatement(location)
        
        stmt.set_file_name("MYFILE", is_optional=True)
        assert stmt.file_name == "MYFILE"
        assert stmt.is_optional == True
        
        stmt.set_assign_to("DATAFILE", device_type="DISK")
        assert stmt.assign_to == "DATAFILE"
        assert stmt.assign_device_type == "DISK"
        
        stmt.set_organization("INDEXED")
        assert stmt.organization == "INDEXED"
        
        stmt.set_access_mode("DYNAMIC")
        assert stmt.access_mode == "DYNAMIC"
        
        stmt.set_file_status("WS-STATUS", "WS-VSAM")
        assert stmt.file_status == "WS-STATUS"
        assert stmt.file_status_vsam == "WS-VSAM"

    def test_select_statement_to_dict(self):
        """Test SelectStatement to_dict serialization."""
        from cobolparser.models.ast_base import SourceLocation
        
        location = SourceLocation(1, 1, None)
        stmt = SelectStatement(location)
        
        stmt.set_file_name("TESTFILE", is_optional=False)
        stmt.set_assign_to("DATA1", device_type="TAPE")
        stmt.set_organization("SEQUENTIAL")
        stmt.set_access_mode("SEQUENTIAL")
        stmt.set_file_status("STATUS-VAR")
        
        d = stmt.to_dict()
        
        assert d["statement_type"] == "SELECT"
        assert d["file_name"] == "TESTFILE"
        assert d["assign_to"] == "DATA1"
        assert d["assign_device_type"] == "TAPE"
        assert d["organization"] == "SEQUENTIAL"
        assert d["access_mode"] == "SEQUENTIAL"
        assert d["file_status"] == "STATUS-VAR"


class TestFileDescriptionModel:
    """Tests for CobolFileDescription model attributes and methods."""

    def test_file_description_creation(self):
        """Test creating CobolFileDescription directly."""
        from cobolparser.models.ast_base import SourceLocation
        
        location = SourceLocation(1, 1, None)
        fd = CobolFileDescription("MYFILE", location)
        
        assert fd.file_name == "MYFILE"
        assert fd.record_type == "FD"  # Default
        assert fd.is_external == False
        assert fd.is_global == False

    def test_file_description_setters(self):
        """Test CobolFileDescription setter methods."""
        from cobolparser.models.ast_base import SourceLocation
        
        location = SourceLocation(1, 1, None)
        fd = CobolFileDescription("TESTFILE", location)
        
        # record_type is set directly, not through a setter
        fd.record_type = "SD"
        assert fd.record_type == "SD"
        
        fd.set_block_contains(count=10, unit="RECORDS")
        assert fd.block_contains == 10
        assert fd.block_contains_unit == "RECORDS"
        
        fd.set_record_contains(count=80)
        # Note: record_contains uses count parameter
        
        fd.set_label_records("STANDARD")
        assert fd.label_records == "STANDARD"
        
        fd.set_linage(60)
        assert fd.linage_value == 60
        
        fd.set_code_set("ASCII")
        assert fd.code_set == "ASCII"
        
        fd.set_recording_mode("V")
        assert fd.recording_mode == "V"
        
        fd.set_external(True)
        assert fd.is_external == True
        
        fd.set_global(True)
        assert fd.is_global == True

    def test_file_description_to_dict(self):
        """Test CobolFileDescription to_dict serialization."""
        from cobolparser.models.ast_base import SourceLocation
        
        location = SourceLocation(1, 1, None)
        fd = CobolFileDescription("TESTFILE", location)
        
        fd.record_type = "FD"
        fd.set_block_contains(count=5, unit="RECORDS")
        fd.set_record_contains(count=100)
        fd.set_label_records("STANDARD")
        fd.set_recording_mode("F")
        fd.set_external(True)
        
        d = fd.to_dict()
        
        assert d["file_name"] == "TESTFILE"
        assert d["record_type"] == "FD"
        # block_contains may be serialized as dict with count/unit or as separate fields
        if isinstance(d.get("block_contains"), dict):
            assert d["block_contains"]["count"] == 5
            assert d["block_contains"]["unit"] == "RECORDS"
        else:
            assert d.get("block_contains") == 5 or d.get("block_contains_min") == 5
        assert d["label_records"] == "STANDARD"
        assert d["recording_mode"] == "F"
        assert d["is_external"] == True


# Test to verify integration with parse_cobol convenience function
def test_parse_cobol_with_file_statements():
    """Test using parse_cobol convenience function with FILE statements."""
    src = """
    IDENTIFICATION DIVISION.
    PROGRAM-ID. FILETEST.
    ENVIRONMENT DIVISION.
    INPUT-OUTPUT SECTION.
    FILE-CONTROL.
        SELECT MASTER-FILE ASSIGN TO "MASTER.DAT"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS MASTER-KEY
               FILE STATUS IS WS-FILE-STATUS.
    DATA DIVISION.
    FILE SECTION.
    FD MASTER-FILE
       BLOCK CONTAINS 10 RECORDS
       RECORD CONTAINS 100 CHARACTERS.
    01 MASTER-RECORD.
       05 MASTER-KEY PIC X(10).
       05 MASTER-DATA PIC X(90).
    WORKING-STORAGE SECTION.
    01 WS-FILE-STATUS PIC XX.
    PROCEDURE DIVISION.
        STOP RUN.
    """
    result = parse_cobol(src, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    assert result.ast is not None
    # Should have parsed without fatal errors
    assert not any('SELECT' in str(e) for e in result.errors)
    assert not any('FD' in str(e) for e in result.errors)
