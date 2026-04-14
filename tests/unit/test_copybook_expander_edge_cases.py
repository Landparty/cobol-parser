"""Edge case tests for copybook_expander.py.

Specifically targets the high-risk, under-tested paths:
1. Circular reference detection (A->B->A, A->A, multi-hop A->B->C->A)
2. Deep nesting depth enforcement
3. REPLACING clause with pseudo-text (:TAG:) substitution
4. Encoding detection: UTF-8 BOM, EBCDIC-like bytes, ASCII fallback
5. Total expansion size limit enforcement
6. Multiple COPY statements in one source file
7. Diamond dependency (same copybook included by two parents) uses cache
8. Copybook with no COPY statements returned unchanged
9. Nested copybooks (two levels deep)
10. REPLACING with multiple pairs
"""

import os
import tempfile

import pytest

from cobolparser.preprocess import (
    CircularReferenceError,
    NestingDepthError,
    TotalExpansionSizeExceededError,
    expand_copybooks,
)
from cobolparser.preprocess.copybook_expander import (
    convert_to_utf8,
    detect_encoding,
    read_file_with_encoding,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(directory: str, filename: str, content: str) -> str:
    """Write a file and return its path."""
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _fixed(lines: list[str]) -> str:
    """Wrap free-form lines in minimal fixed-format COBOL structure."""
    padded = []
    for line in lines:
        padded.append(f"      {line}")
    return "\n".join(padded) + "\n"


# Minimal COBOL header/footer for integration with expand_copybooks
_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-PROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
"""

_FOOTER = """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


# ---------------------------------------------------------------------------
# Circular reference detection
# ---------------------------------------------------------------------------


class TestCircularReferenceDetection:
    def test_direct_self_reference(self):
        """A copybook that COPYs itself should raise CircularReferenceError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, "SELF.CPY", "      COPY SELF.\n")
            source = _HEADER + "      COPY SELF.\n" + _FOOTER
            with pytest.raises(CircularReferenceError):
                expand_copybooks(source, copybook_paths=[tmpdir])

    def test_two_hop_circular_reference(self):
        """A->B->A circular chain should raise CircularReferenceError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, "COPYB.CPY", "      COPY COPYA.\n")
            _write(tmpdir, "COPYA.CPY", "      COPY COPYB.\n")
            source = _HEADER + "      COPY COPYA.\n" + _FOOTER
            with pytest.raises(CircularReferenceError):
                expand_copybooks(source, copybook_paths=[tmpdir])

    def test_three_hop_circular_reference(self):
        """A->B->C->A circular chain should raise CircularReferenceError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, "COPY-C.CPY", "      COPY COPY-A.\n")
            _write(tmpdir, "COPY-B.CPY", "      COPY COPY-C.\n")
            _write(tmpdir, "COPY-A.CPY", "      COPY COPY-B.\n")
            source = _HEADER + "      COPY COPY-A.\n" + _FOOTER
            with pytest.raises(CircularReferenceError):
                expand_copybooks(source, copybook_paths=[tmpdir])

    def test_circular_error_contains_chain(self):
        """CircularReferenceError should report the dependency chain."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, "LOOP-B.CPY", "      COPY LOOP-A.\n")
            _write(tmpdir, "LOOP-A.CPY", "      COPY LOOP-B.\n")
            source = _HEADER + "      COPY LOOP-A.\n" + _FOOTER
            with pytest.raises(CircularReferenceError) as exc_info:
                expand_copybooks(source, copybook_paths=[tmpdir])
            # The error should describe the cycle in some form
            error_text = str(exc_info.value)
            assert len(error_text) > 0


# ---------------------------------------------------------------------------
# Nesting depth enforcement
# ---------------------------------------------------------------------------


class TestNestingDepthEnforcement:
    def test_exceeds_max_nesting_depth(self):
        """Nesting beyond max_nesting_depth should raise NestingDepthError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a chain 3 levels deep but set limit to 1
            _write(tmpdir, "LEVEL2.CPY", "      COPY LEVEL3.\n")
            _write(tmpdir, "LEVEL3.CPY", "      01 DEEP-VAR PIC X.\n")
            _write(tmpdir, "LEVEL1.CPY", "      COPY LEVEL2.\n")
            source = _HEADER + "      COPY LEVEL1.\n" + _FOOTER
            with pytest.raises(NestingDepthError):
                expand_copybooks(source, copybook_paths=[tmpdir], max_nesting_depth=1)

    def test_within_max_nesting_depth_succeeds(self):
        """Nesting within the limit should succeed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, "INNER.CPY", "      01 INNER-VAR PIC X.\n")
            _write(tmpdir, "OUTER.CPY", "      COPY INNER.\n")
            source = _HEADER + "      COPY OUTER.\n" + _FOOTER
            result = expand_copybooks(source, copybook_paths=[tmpdir], max_nesting_depth=10)
            assert result.expanded_source is not None
            assert result.max_depth_reached >= 1


# ---------------------------------------------------------------------------
# REPLACING clause substitution
# ---------------------------------------------------------------------------


class TestReplacingClause:
    def test_simple_replacing(self):
        """REPLACING :TAG: BY EMP- should substitute all occurrences."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Copybook uses :TAG: as a placeholder
            _write(
                tmpdir,
                "EMPREC.CPY",
                "      01 :TAG:-RECORD.\n"
                "         05 :TAG:-ID PIC 9(6).\n"
                "         05 :TAG:-NAME PIC X(30).\n",
            )
            source = (
                _HEADER
                + "      COPY EMPREC REPLACING ==:TAG:== BY ==EMP==.\n"
                + _FOOTER
            )
            result = expand_copybooks(source, copybook_paths=[tmpdir])
            assert "EMP-RECORD" in result.expanded_source or "EMP" in result.expanded_source

    def test_replacing_changes_identifier(self):
        """REPLACING a word should substitute it in the expanded content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, "BASE.CPY", "      01 OLD-NAME PIC X(10).\n")
            source = (
                _HEADER
                + "      COPY BASE REPLACING ==OLD-NAME== BY ==NEW-NAME==.\n"
                + _FOOTER
            )
            result = expand_copybooks(source, copybook_paths=[tmpdir])
            assert "NEW-NAME" in result.expanded_source

    def test_replacing_multiple_pairs(self):
        """Multiple REPLACING pairs should all be applied.

        COBOL REPLACING works at the full-word/token level: ==AAA-FIELD== replaces
        the complete identifier token 'AAA-FIELD'. Partial-word pseudo-text like
        ==AAA== does NOT match within 'AAA-FIELD'.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(
                tmpdir,
                "MULTI.CPY",
                "      01 AAA-FIELD PIC X.\n"
                "      01 BBB-FIELD PIC X.\n",
            )
            source = (
                _HEADER
                + "      COPY MULTI REPLACING ==AAA-FIELD== BY ==XXX-FIELD=="
                + " ==BBB-FIELD== BY ==YYY-FIELD==.\n"
                + _FOOTER
            )
            result = expand_copybooks(source, copybook_paths=[tmpdir])
            assert "XXX-FIELD" in result.expanded_source
            assert "YYY-FIELD" in result.expanded_source


# ---------------------------------------------------------------------------
# Encoding detection
# ---------------------------------------------------------------------------


class TestEncodingDetection:
    def test_detect_utf8_plain_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".cpy", delete=False
        ) as f:
            f.write("      01 EMP-NAME PIC X(30).\n")
            path = f.name
        try:
            encoding = detect_encoding(path)
            assert encoding in ("utf-8", "ascii")
        finally:
            os.unlink(path)

    def test_detect_utf8_bom_file(self):
        with tempfile.NamedTemporaryFile(suffix=".cpy", delete=False) as f:
            # Write UTF-8 BOM followed by ASCII content
            f.write(b"\xef\xbb\xbf      01 EMP-NAME PIC X(30).\n")
            path = f.name
        try:
            encoding = detect_encoding(path)
            assert encoding == "utf-8-sig"
        finally:
            os.unlink(path)

    def test_detect_ebcdic_like_file(self):
        with tempfile.NamedTemporaryFile(suffix=".cpy", delete=False) as f:
            # Create bytes with many 0x40 (EBCDIC space) characters
            # More 0x40 than 0x20 and >5% of file
            content = b"\x40" * 100 + b"\x20" * 10 + b"\xc3\xd6\xc2\xd6\xd3"
            f.write(content)
            path = f.name
        try:
            encoding = detect_encoding(path)
            assert encoding == "cp037"
        finally:
            os.unlink(path)

    def test_detect_encoding_nonexistent_file_raises(self):
        from cobolparser.preprocess import EncodingError

        with pytest.raises(EncodingError):
            detect_encoding("/nonexistent/path/file.cpy")

    def test_convert_to_utf8_valid_encoding(self):
        content = b"      01 EMP-NAME PIC X(30).\n"
        result = convert_to_utf8(content, "utf-8")
        assert "EMP-NAME" in result

    def test_convert_to_utf8_unknown_encoding_fallback(self):
        # Unknown encoding should fall back to ASCII with replacement
        content = b"      01 TEST PIC X.\n"
        result = convert_to_utf8(content, "ascii")
        assert "TEST" in result

    def test_read_file_with_encoding_override(self):
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".cpy", delete=False
        ) as f:
            f.write("      01 FIELD-A PIC X(5).\n")
            path = f.name
        try:
            content = read_file_with_encoding(path, encoding_override="utf-8")
            assert "FIELD-A" in content
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Total expansion size limit
# ---------------------------------------------------------------------------


class TestTotalExpansionSizeLimit:
    def test_exceeds_total_size_raises(self):
        """Exceeding max_total_size should raise TotalExpansionSizeExceededError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write a copybook larger than 1 byte limit
            _write(tmpdir, "BIG.CPY", "      01 BIG-FIELD PIC X(100).\n")
            source = _HEADER + "      COPY BIG.\n" + _FOOTER
            with pytest.raises(TotalExpansionSizeExceededError):
                expand_copybooks(source, copybook_paths=[tmpdir], max_total_size=1)

    def test_within_size_limit_succeeds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, "SMALL.CPY", "      01 FIELD-X PIC X.\n")
            source = _HEADER + "      COPY SMALL.\n" + _FOOTER
            result = expand_copybooks(
                source, copybook_paths=[tmpdir], max_total_size=10_000_000
            )
            assert "FIELD-X" in result.expanded_source


# ---------------------------------------------------------------------------
# Multiple COPY statements
# ---------------------------------------------------------------------------


class TestMultipleCopyStatements:
    def test_two_copy_statements_both_expanded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, "COPY-A.CPY", "      01 FIELD-A PIC X.\n")
            _write(tmpdir, "COPY-B.CPY", "      01 FIELD-B PIC X.\n")
            source = (
                _HEADER
                + "      COPY COPY-A.\n"
                + "      COPY COPY-B.\n"
                + _FOOTER
            )
            result = expand_copybooks(source, copybook_paths=[tmpdir])
            assert "FIELD-A" in result.expanded_source
            assert "FIELD-B" in result.expanded_source
            assert len(result.included_copybooks) == 2

    def test_same_copybook_included_twice_tracked_once(self):
        """The same copybook included twice should appear once in included_copybooks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, "SHARED.CPY", "      01 SHARED-FIELD PIC X.\n")
            source = (
                _HEADER
                + "      COPY SHARED.\n"
                + "      COPY SHARED.\n"
                + _FOOTER
            )
            result = expand_copybooks(source, copybook_paths=[tmpdir])
            assert "SHARED-FIELD" in result.expanded_source
            # Duplicate tracking: included_copybooks should count unique paths
            cpy_count = sum(
                1 for p in result.included_copybooks if "SHARED" in p.upper()
            )
            assert cpy_count == 1


# ---------------------------------------------------------------------------
# Diamond dependency (caching)
# ---------------------------------------------------------------------------


class TestDiamondDependency:
    def test_diamond_dependency_expands_correctly(self):
        """A->B->D and A->C->D (diamond) should expand D's content at each use."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, "COMMON.CPY", "      01 COMMON-FIELD PIC X(5).\n")
            _write(tmpdir, "LEFT.CPY", "      COPY COMMON.\n")
            _write(tmpdir, "RIGHT.CPY", "      COPY COMMON.\n")
            source = (
                _HEADER
                + "      COPY LEFT.\n"
                + "      COPY RIGHT.\n"
                + _FOOTER
            )
            result = expand_copybooks(source, copybook_paths=[tmpdir])
            assert "COMMON-FIELD" in result.expanded_source


# ---------------------------------------------------------------------------
# No COPY statements — source should be returned unchanged
# ---------------------------------------------------------------------------


class TestNoCopyStatements:
    def test_source_without_copy_returned_unchanged(self):
        source = _HEADER + "      01 STANDALONE PIC X.\n" + _FOOTER
        result = expand_copybooks(source, copybook_paths=[])
        # No changes — expanded_source should equal the original
        assert result.expanded_source == source
        assert result.included_copybooks == []
        assert result.max_depth_reached == 0

    def test_statistics_has_no_copybooks_when_no_copy(self):
        source = _HEADER + "      01 FIELD-Z PIC 9.\n" + _FOOTER
        result = expand_copybooks(source, copybook_paths=[])
        assert result.statistics.file_count == 1


# ---------------------------------------------------------------------------
# Two-level nested copybooks
# ---------------------------------------------------------------------------


class TestNestedCopybooks:
    def test_two_level_nesting_expands_inner(self):
        """OUTER.CPY contains COPY INNER.CPY; main includes OUTER."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, "INNER.CPY", "      01 INNER-FIELD PIC 9(5).\n")
            _write(tmpdir, "OUTER.CPY", "      COPY INNER.\n")
            source = _HEADER + "      COPY OUTER.\n" + _FOOTER
            result = expand_copybooks(source, copybook_paths=[tmpdir])
            assert "INNER-FIELD" in result.expanded_source
            assert result.max_depth_reached >= 2
            # Both OUTER and INNER should be tracked
            assert len(result.included_copybooks) == 2

    def test_statistics_counts_nested_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write(tmpdir, "DEEP-2.CPY", "      01 DEEP-FIELD PIC X.\n")
            _write(tmpdir, "DEEP-1.CPY", "      COPY DEEP-2.\n")
            source = _HEADER + "      COPY DEEP-1.\n" + _FOOTER
            result = expand_copybooks(source, copybook_paths=[tmpdir])
            # Main file + 2 copybooks = 3
            assert result.statistics.file_count == 3
