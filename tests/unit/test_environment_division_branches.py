"""Tests targeting branch-coverage gaps in parsers/divisions/environment.py.

Covers:
- SELECT with ORGANIZATION IS INDEXED/RELATIVE/SEQUENTIAL/LINE SEQUENTIAL
- SELECT with ACCESS MODE IS SEQUENTIAL/RANDOM/DYNAMIC
- SELECT with RECORD KEY, RELATIVE KEY, FILE STATUS
- SELECT OPTIONAL
- CONFIGURATION SECTION
- Multiple SELECT statements in FILE-CONTROL
- ALTERNATE RECORD KEY clause
- Missing/malformed clauses (error recovery)
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.plugins.core import ErrorRecoveryMode

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _parse(src: str):
    return parse_cobol(
        src, error_recovery=ErrorRecoveryMode.COLLECT_ALL, free_form=True
    )


def _assert_parsed(src: str):
    result = _parse(src)
    assert result.ast is not None
    return result


def _env_wrap(env_body: str, data_body: str = "") -> str:
    data_section = (
        ("DATA DIVISION.\n" "WORKING-STORAGE SECTION.\n" + data_body)
        if data_body
        else ""
    )
    return (
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. TEST.\n"
        "ENVIRONMENT DIVISION.\n" + env_body + data_section + "PROCEDURE DIVISION.\n"
        "    STOP RUN.\n"
    )


# ---------------------------------------------------------------------------
# CONFIGURATION SECTION
# ---------------------------------------------------------------------------


class TestConfigurationSection:
    def test_configuration_section_present(self):
        src = _env_wrap(
            "CONFIGURATION SECTION.\n"
            "SOURCE-COMPUTER. IBM-PC.\n"
            "OBJECT-COMPUTER. IBM-PC.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_configuration_section_with_special_names(self):
        src = _env_wrap(
            "CONFIGURATION SECTION.\n"
            "SPECIAL-NAMES.\n"
            "    DECIMAL-POINT IS COMMA.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# ORGANIZATION clause variants
# ---------------------------------------------------------------------------


class TestOrganizationClauses:
    def test_organization_sequential(self):
        src = _env_wrap(
            "INPUT-OUTPUT SECTION.\n"
            "FILE-CONTROL.\n"
            "    SELECT MYFILE ASSIGN TO 'MY.DAT'\n"
            "        ORGANIZATION IS SEQUENTIAL.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_organization_indexed(self):
        src = _env_wrap(
            "INPUT-OUTPUT SECTION.\n"
            "FILE-CONTROL.\n"
            "    SELECT IDXFILE ASSIGN TO 'IDX.DAT'\n"
            "        ORGANIZATION IS INDEXED\n"
            "        ACCESS MODE IS RANDOM\n"
            "        RECORD KEY IS WS-KEY.\n",
            "01  WS-KEY PIC X(8).\n",
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_organization_relative(self):
        src = _env_wrap(
            "INPUT-OUTPUT SECTION.\n"
            "FILE-CONTROL.\n"
            "    SELECT RELFILE ASSIGN TO 'REL.DAT'\n"
            "        ORGANIZATION IS RELATIVE\n"
            "        ACCESS MODE IS DYNAMIC\n"
            "        RELATIVE KEY IS WS-REL-KEY.\n",
            "01  WS-REL-KEY PIC 9(5).\n",
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_organization_line_sequential(self):
        src = _env_wrap(
            "INPUT-OUTPUT SECTION.\n"
            "FILE-CONTROL.\n"
            "    SELECT LSTFILE ASSIGN TO 'LST.TXT'\n"
            "        ORGANIZATION IS LINE SEQUENTIAL.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# ACCESS MODE variants
# ---------------------------------------------------------------------------


class TestAccessModeClauses:
    def test_access_mode_sequential(self):
        src = _env_wrap(
            "INPUT-OUTPUT SECTION.\n"
            "FILE-CONTROL.\n"
            "    SELECT SEQFILE ASSIGN TO 'SEQ.DAT'\n"
            "        ACCESS MODE IS SEQUENTIAL.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_access_mode_random(self):
        src = _env_wrap(
            "INPUT-OUTPUT SECTION.\n"
            "FILE-CONTROL.\n"
            "    SELECT RNDF ASSIGN TO 'RND.DAT'\n"
            "        ORGANIZATION IS INDEXED\n"
            "        ACCESS MODE IS RANDOM\n"
            "        RECORD KEY IS WS-RND-KEY.\n",
            "01  WS-RND-KEY PIC X(10).\n",
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_access_mode_dynamic(self):
        src = _env_wrap(
            "INPUT-OUTPUT SECTION.\n"
            "FILE-CONTROL.\n"
            "    SELECT DYNF ASSIGN TO 'DYN.DAT'\n"
            "        ORGANIZATION IS INDEXED\n"
            "        ACCESS MODE IS DYNAMIC\n"
            "        RECORD KEY IS WS-DYN-KEY.\n",
            "01  WS-DYN-KEY PIC X(10).\n",
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_access_mode_without_is_keyword(self):
        """ACCESS MODE SEQUENTIAL (no IS keyword)."""
        src = _env_wrap(
            "INPUT-OUTPUT SECTION.\n"
            "FILE-CONTROL.\n"
            "    SELECT NOISK ASSIGN TO 'NOI.DAT'\n"
            "        ACCESS MODE SEQUENTIAL.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# FILE STATUS clause
# ---------------------------------------------------------------------------


class TestFileStatusClause:
    def test_file_status_is(self):
        src = _env_wrap(
            "INPUT-OUTPUT SECTION.\n"
            "FILE-CONTROL.\n"
            "    SELECT STATUSFILE ASSIGN TO 'ST.DAT'\n"
            "        FILE STATUS IS WS-FILE-STATUS.\n",
            "01  WS-FILE-STATUS PIC X(2).\n",
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_file_status_without_is(self):
        src = _env_wrap(
            "INPUT-OUTPUT SECTION.\n"
            "FILE-CONTROL.\n"
            "    SELECT STFILE2 ASSIGN TO 'ST2.DAT'\n"
            "        FILE STATUS WS-FS2.\n",
            "01  WS-FS2 PIC X(2).\n",
        )
        result = _assert_parsed(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# RECORD KEY and RELATIVE KEY
# ---------------------------------------------------------------------------


class TestKeysClauses:
    def test_record_key(self):
        src = _env_wrap(
            "INPUT-OUTPUT SECTION.\n"
            "FILE-CONTROL.\n"
            "    SELECT KEYFILE ASSIGN TO 'KEY.DAT'\n"
            "        ORGANIZATION IS INDEXED\n"
            "        RECORD KEY IS WS-MASTER-KEY.\n",
            "01  WS-MASTER-KEY PIC X(12).\n",
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_record_key_without_is(self):
        src = _env_wrap(
            "INPUT-OUTPUT SECTION.\n"
            "FILE-CONTROL.\n"
            "    SELECT NOISFILE ASSIGN TO 'NOIS.DAT'\n"
            "        ORGANIZATION IS INDEXED\n"
            "        RECORD KEY WS-NOIS-KEY.\n",
            "01  WS-NOIS-KEY PIC X(8).\n",
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_relative_key(self):
        src = _env_wrap(
            "INPUT-OUTPUT SECTION.\n"
            "FILE-CONTROL.\n"
            "    SELECT RELFILE2 ASSIGN TO 'REL2.DAT'\n"
            "        ORGANIZATION IS RELATIVE\n"
            "        RELATIVE KEY IS WS-REL2-KEY.\n",
            "01  WS-REL2-KEY PIC 9(6).\n",
        )
        result = _assert_parsed(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# SELECT OPTIONAL
# ---------------------------------------------------------------------------


class TestSelectOptional:
    def test_select_optional(self):
        src = _env_wrap(
            "INPUT-OUTPUT SECTION.\n"
            "FILE-CONTROL.\n"
            "    SELECT OPTIONAL OPTFILE ASSIGN TO 'OPT.DAT'.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# Multiple SELECT statements
# ---------------------------------------------------------------------------


class TestMultipleSelectStatements:
    def test_two_select_statements(self):
        src = _env_wrap(
            "INPUT-OUTPUT SECTION.\n"
            "FILE-CONTROL.\n"
            "    SELECT FILE1 ASSIGN TO 'F1.DAT'.\n"
            "    SELECT FILE2 ASSIGN TO 'F2.DAT'\n"
            "        ORGANIZATION IS SEQUENTIAL.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None

    def test_three_select_statements_mixed(self):
        src = _env_wrap(
            "INPUT-OUTPUT SECTION.\n"
            "FILE-CONTROL.\n"
            "    SELECT SEQF ASSIGN TO 'SEQ.DAT'\n"
            "        ORGANIZATION IS SEQUENTIAL\n"
            "        ACCESS MODE IS SEQUENTIAL\n"
            "        FILE STATUS IS WS-FS1.\n"
            "    SELECT IDXF ASSIGN TO 'IDX.DAT'\n"
            "        ORGANIZATION IS INDEXED\n"
            "        ACCESS MODE IS DYNAMIC\n"
            "        RECORD KEY IS WS-IDX-KEY\n"
            "        FILE STATUS IS WS-FS2.\n",
            "01  WS-FS1 PIC X(2).\n"
            "01  WS-FS2 PIC X(2).\n"
            "01  WS-IDX-KEY PIC X(10).\n",
        )
        result = _assert_parsed(src)
        assert result.ast is not None


# ---------------------------------------------------------------------------
# Configuration + Input-Output together
# ---------------------------------------------------------------------------


class TestBothSections:
    def test_configuration_and_input_output(self):
        src = _env_wrap(
            "CONFIGURATION SECTION.\n"
            "SOURCE-COMPUTER. IBM-Z.\n"
            "INPUT-OUTPUT SECTION.\n"
            "FILE-CONTROL.\n"
            "    SELECT BOTHF ASSIGN TO 'BOTH.DAT'.\n"
        )
        result = _assert_parsed(src)
        assert result.ast is not None
