"""Tests for PROCESS/CBL compiler directive handling."""

from cobolparser.preprocess import strip_compiler_directives


class TestCompilerDirectives:
    """Test stripping of PROCESS and CBL directives."""

    def test_simple_process_directive(self):
        """Test basic PROCESS directive removal."""
        source = """PROCESS APOST
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST."""

        result = strip_compiler_directives(source)
        assert "PROCESS" not in result
        assert "IDENTIFICATION DIVISION" in result

    def test_multiple_process_directives(self):
        """Test multiple PROCESS lines."""
        source = """PROCESS &OPTION1& &OPTION2&
PROCESS APOST
       IDENTIFICATION DIVISION."""

        result = strip_compiler_directives(source)
        assert result.count("PROCESS") == 0

    def test_cbl_directive(self):
        """Test CBL directive (synonym for PROCESS)."""
        source = """CBL APOST,NODYNAM
       IDENTIFICATION DIVISION."""

        result = strip_compiler_directives(source)
        assert "CBL" not in result

    def test_fixed_format_process(self):
        """Test PROCESS in fixed-format (columns 8-72)."""
        source = """000100 PROCESS APOST
000200        IDENTIFICATION DIVISION."""

        result = strip_compiler_directives(source)
        assert "PROCESS" not in result

    def test_continuation_lines(self):
        """Test PROCESS with continuation."""
        source = """PROCESS OPTION1,
      -        OPTION2,
      -        OPTION3
       IDENTIFICATION DIVISION."""

        result = strip_compiler_directives(source)
        assert "PROCESS" not in result
        assert "OPTION" not in result

    def test_preserve_line_numbers(self):
        """Test that line numbers are preserved."""
        source = """PROCESS APOST
PROCESS NODYNAM
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST."""

        result = strip_compiler_directives(source, preserve_line_numbers=True)
        lines = result.splitlines()

        # First two lines should be blank
        assert lines[0].strip() == ""
        assert lines[1].strip() == ""
        # Rest should be preserved
        assert "IDENTIFICATION" in lines[2]

    def test_no_preserve_line_numbers(self):
        """Test that lines are removed when preserve_line_numbers=False."""
        source = """PROCESS APOST
PROCESS NODYNAM
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST."""

        result = strip_compiler_directives(source, preserve_line_numbers=False)
        lines = result.splitlines()

        # Should have only 2 lines (IDENTIFICATION and PROGRAM-ID)
        assert len(lines) == 2
        assert "IDENTIFICATION" in lines[0]
        assert "PROGRAM-ID" in lines[1]

    def test_no_directives(self):
        """Test source without directives."""
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST."""

        result = strip_compiler_directives(source)
        assert result == source

    def test_process_after_identification(self):
        """Test that PROCESS after IDENTIFICATION is not removed."""
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROCESS-TEST.
       AUTHOR. PROCESS ENGINEER."""

        result = strip_compiler_directives(source)
        # PROCESS in AUTHOR should remain
        assert "PROCESS ENGINEER" in result

    def test_real_world_example(self):
        """Test with real-world example from dobchq0a.cbl."""
        source = """PROCESS &IMSBATCH-ST-31& &HAUTE-PERFORM&
PROCESS APOST
       IDENTIFICATION DIVISION.
       PROGRAM-ID.    DOBCHQ0A."""

        result = strip_compiler_directives(source)
        assert "PROCESS" not in result
        assert "IMSBATCH" not in result
        assert "IDENTIFICATION DIVISION" in result
        assert "DOBCHQ0A" in result

    def test_empty_source(self):
        """Test with empty source."""
        source = ""
        result = strip_compiler_directives(source)
        assert result == ""

    def test_only_directives(self):
        """Test source with only directives (no IDENTIFICATION)."""
        source = """PROCESS APOST
CBL NODYNAM"""

        result = strip_compiler_directives(source, preserve_line_numbers=True)
        lines = result.splitlines()

        # Both lines should be blank
        assert all(line.strip() == "" for line in lines)

    def test_process_with_tabs(self):
        """Test PROCESS directive with tabs."""
        source = """PROCESS\tAPOST
       IDENTIFICATION DIVISION."""

        result = strip_compiler_directives(source)
        assert "PROCESS" not in result
        assert "APOST" not in result

    def test_cbl_standalone(self):
        """Test standalone CBL without options."""
        source = """CBL
       IDENTIFICATION DIVISION."""

        result = strip_compiler_directives(source)
        assert "CBL" not in result

    def test_process_standalone(self):
        """Test standalone PROCESS without options."""
        source = """PROCESS
       IDENTIFICATION DIVISION."""

        result = strip_compiler_directives(source)
        assert "PROCESS" not in result

    def test_mixed_process_and_cbl(self):
        """Test mix of PROCESS and CBL directives."""
        source = """PROCESS APOST
CBL NODYNAM
PROCESS OPT
       IDENTIFICATION DIVISION."""

        result = strip_compiler_directives(source)
        assert "PROCESS" not in result
        assert "CBL" not in result
        assert "NODYNAM" not in result

    def test_id_division_variant(self):
        """Test ID DIVISION (short form) stops directive processing."""
        source = """PROCESS APOST
       ID DIVISION.
       PROGRAM-ID. TEST."""

        result = strip_compiler_directives(source)
        assert "PROCESS" not in result
        assert "ID DIVISION" in result

    def test_preserve_line_endings(self):
        """Test that line endings are preserved."""
        source = "PROCESS APOST\r\n       IDENTIFICATION DIVISION.\r\n"

        result = strip_compiler_directives(source, preserve_line_numbers=True)

        # Should preserve \r\n line endings
        assert "\r\n" in result

    def test_continuation_without_directive(self):
        """Test continuation line that's not part of a directive."""
        source = """       IDENTIFICATION DIVISION.
      -PROGRAM-ID. TEST."""

        result = strip_compiler_directives(source)
        # Should not remove continuation lines after IDENTIFICATION
        assert "PROGRAM-ID" in result
