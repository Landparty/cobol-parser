"""Regression tests for section/paragraph location tracking (2026-07-09).

Every ``CobolSection`` (and the ENVIRONMENT division's ``FILE-CONTROL``
``CobolParagraph``) created by the ENVIRONMENT and DATA division parsers was
stamped with the *division's* own ``start_location`` instead of the location
of its own header token — so ``ENVIRONMENT``'s ``INPUT-OUTPUT SECTION`` (and
``DATA``'s ``WORKING-STORAGE``/``LINKAGE``/etc. sections) always reported the
same line as their parent division, regardless of where the section header
actually appeared in source. The PROCEDURE division parser already captured
each section's own token location (``procedure.py``'s
``section_info.get("location", start_location)`` pattern); this pins the same
behavior for ENVIRONMENT and DATA.
"""

from cobolparser import parse_cobol


class TestEnvironmentDivisionSectionLocations:
    """CONFIGURATION / INPUT-OUTPUT sections must report their own line."""

    def test_input_output_section_has_own_line(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"  # line 1
            "       PROGRAM-ID. TEST-PROG.\n"  # line 2
            "       ENVIRONMENT DIVISION.\n"  # line 3
            "       CONFIGURATION SECTION.\n"  # line 4
            "       SOURCE-COMPUTER. IBM-370.\n"  # line 5
            "       INPUT-OUTPUT SECTION.\n"  # line 6
            "       FILE-CONTROL.\n"  # line 7
            "           SELECT F1 ASSIGN TO 'F1.DAT'.\n"  # line 8
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC X.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = parse_cobol(src)
        assert result.success

        env = result.ast.get_division("ENVIRONMENT")
        config_section = env.get_section_by_name("CONFIGURATION")
        io_section = env.get_section_by_name("INPUT-OUTPUT")

        assert env.location.line == 3
        assert config_section.location.line == 4
        assert io_section.location.line == 6
        assert io_section.location.line != env.location.line

    def test_file_control_paragraph_has_own_line(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       ENVIRONMENT DIVISION.\n"  # line 3
            "       INPUT-OUTPUT SECTION.\n"  # line 4
            "\n"
            "       FILE-CONTROL.\n"  # line 6
            "           SELECT F1 ASSIGN TO 'F1.DAT'.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC X.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = parse_cobol(src)
        assert result.success

        env = result.ast.get_division("ENVIRONMENT")
        io_section = env.get_section_by_name("INPUT-OUTPUT")
        file_control_para = io_section.get_paragraph_by_name("FILE-CONTROL")

        assert io_section.location.line == 4
        assert file_control_para.location.line == 6


class TestDataDivisionSectionLocations:
    """FILE / WORKING-STORAGE / LOCAL-STORAGE / LINKAGE sections."""

    def test_working_storage_and_linkage_have_own_lines(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-PROG.\n"
            "       DATA DIVISION.\n"  # line 3
            "       WORKING-STORAGE SECTION.\n"  # line 4
            "       01 WS-A PIC X.\n"
            "       LINKAGE SECTION.\n"  # line 6
            "       01 LK-A PIC X.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = parse_cobol(src)
        assert result.success

        data_div = result.ast.get_division("DATA")
        ws_section = data_div.get_section_by_name("WORKING-STORAGE")
        linkage_section = data_div.get_section_by_name("LINKAGE")

        assert data_div.location.line == 3
        assert ws_section.location.line == 4
        assert linkage_section.location.line == 6
        assert ws_section.location.line != linkage_section.location.line
