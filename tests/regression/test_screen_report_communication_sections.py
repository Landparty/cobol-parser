"""Regression tests: SCREEN/REPORT/COMMUNICATION SECTION recognition.

Before this fix, ``DataDivisionParser`` only recognized FILE, WORKING-STORAGE,
LOCAL-STORAGE, and LINKAGE as DATA DIVISION sections (see
``cobolparser/parsers/divisions/data.py``). A SCREEN SECTION, REPORT SECTION,
or COMMUNICATION SECTION header was not treated as a section boundary, so the
in-progress section scan (almost always WORKING-STORAGE) kept consuming past
the header: the header tokens were dropped one at a time, and the section's
own level-numbered content -- and its clause keywords (COLUMN, LINE, TYPE,
...), which the DATA DIVISION clause loop cannot recognize -- was misparsed
as bogus nested ``CobolDataItem`` entries under WORKING-STORAGE. E.g. a
SCREEN SECTION ``COLUMN 5`` clause produced a data item literally named
``COLUMN`` with a level number equal to the column position.

``DataDivisionParser`` now recognizes all three headers as section
boundaries. SCREEN and COMMUNICATION, whose grammars are not modeled, have
their bodies discarded (no spurious data items) while still surfacing as
their own named ``CobolSection`` (empty ``data_items``) with a
``has_<name>`` division-metadata flag -- so downstream consumers can tell
the section was present without being polluted by misparsed content. The
REPORT SECTION has been parsed for real since 2026-09-02 (RD clauses and
report groups; see ``tests/unit/test_report_section.py``), so its tests
below pin the parsed shape and the absence of any warning instead.

Known limitation: a data item declared directly under one of these sections
(e.g. a record following a COMMUNICATION SECTION ``CD`` entry, or a plain
01-level item placed after it without its own section header) is discarded
along with the rest of the unmodeled body -- it does not survive into
WORKING-STORAGE (the pre-fix, corrupting behavior) nor into the new section
(whose grammar is not modeled). This trades a real content loss for the
avoidance of AST corruption; see
``TestCommunicationSectionRecognition::test_item_trailing_unsupported_section_is_dropped_not_merged``.
Because that loss is otherwise invisible (``errors=0``), ``_skip_section``
records a ``ParseResult.warnings`` entry naming the section -- this repo's
established convention for "recognized but degraded" content (see
parser.md's silent-drop audits) -- pinned by the ``*_warns_that_its_body_was_skipped``
tests below.

``REPORT`` (and, less commonly, ``COMMUNICATION``/``SCREEN``) can also
appear as an ordinary clause word, not a section header -- e.g. an FD's
``REPORT IS report-name.`` clause (see ``examples/cobol/shamrice/report_test.cbl``).
The DATA DIVISION dispatch loop only treats one of these three words as a
section header when the *next* token is literally ``SECTION`` (the same
lookahead ``_parse_section``'s own break check already used), so a bare
clause-word use falls through to the generic unknown-token skip instead of
wrongly discarding whatever follows it. Pinned by
``test_bare_report_clause_word_is_not_treated_as_a_section_header``.
"""

from cobolparser import parse_cobol

FD_REPORT_CLAUSE_TEMPLATE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROBE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RPT-FILE ASSIGN TO 'R.TXT'.
       DATA DIVISION.
       FILE SECTION.
       FD  RPT-FILE
           REPORT IS SALES-REPORT.
       WORKING-STORAGE SECTION.
       01  WS-ONE                  PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'HI'.
"""

DATA_TEMPLATE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROBE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ONE                  PIC X(10).
       01  WS-TWO                  PIC 9(4).
{extra_section}
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'HI'.
"""


def _parse(extra_section: str):
    source = DATA_TEMPLATE.format(extra_section=extra_section)
    return parse_cobol(source, filename="probe.cbl")


def _sections_by_name(result):
    return {s.section_name: s for s in result.ast.data_division.sections}


SCREEN_SECTION = """       SCREEN SECTION.
       01  MAIN-SCREEN.
           05  BLANK SCREEN.
           05  LINE 1  COLUMN 5    VALUE 'HELLO'.
           05  LINE 2  COLUMN 5    PIC X(10) TO WS-ONE
               REQUIRED
               AUTO.
"""

REPORT_SECTION = """       REPORT SECTION.
       RD  SALES-REPORT
           PAGE LIMIT IS 60 LINES
           HEADING 1
           FIRST DETAIL 10.
       01  TYPE IS PAGE HEADING.
           05  LINE NUMBER IS 1.
               10  COLUMN 1        PIC X(20) VALUE 'REPORT'.
"""

COMMUNICATION_SECTION = """       COMMUNICATION SECTION.
       CD  INPUT-QUEUE FOR INPUT.
           05  MESSAGE-DATE        PIC 9(8).
           05  TEXT-LENGTH         PIC 9(4).
       01  WS-AFTER-CD             PIC X(5).
"""


class TestScreenSectionRecognition:
    def test_working_storage_not_polluted_by_screen_content(self):
        result = _parse(SCREEN_SECTION)
        assert result.ast is not None
        sections = _sections_by_name(result)
        ws_names = {d.name for d in sections["WORKING-STORAGE"].data_items}
        assert ws_names == {"WS-ONE", "WS-TWO"}

    def test_screen_section_is_its_own_empty_section(self):
        result = _parse(SCREEN_SECTION)
        sections = _sections_by_name(result)
        assert "SCREEN" in sections
        assert sections["SCREEN"].data_items == []

    def test_no_bogus_column_or_line_data_items_anywhere(self):
        result = _parse(SCREEN_SECTION)
        names = {
            d.to_dict().get("name")
            for d in result.ast.find_all_by_type("CobolDataItem")
        }
        assert "COLUMN" not in names
        assert "LINE" not in names
        assert "BLANK" not in names

    def test_has_screen_metadata_flag_set(self):
        result = _parse(SCREEN_SECTION)
        assert result.ast.data_division.metadata["has_screen"] is True

    def test_procedure_division_still_parses_after_screen_section(self):
        result = _parse(SCREEN_SECTION)
        assert result.success
        displays = result.ast.find_all_by_type("DisplayStatement")
        assert len(displays) == 1

    def test_skipping_section_records_a_warning(self):
        result = _parse(SCREEN_SECTION)
        assert any("SCREEN SECTION" in w for w in result.warnings)


class TestReportSectionRecognition:
    def test_working_storage_not_polluted_by_report_content(self):
        result = _parse(REPORT_SECTION)
        sections = _sections_by_name(result)
        ws_names = {d.name for d in sections["WORKING-STORAGE"].data_items}
        assert ws_names == {"WS-ONE", "WS-TWO"}

    def test_report_section_is_its_own_parsed_section(self):
        """Since 2026-09-02 the REPORT SECTION is parsed, not skipped: the
        RD's clauses and the report groups (anonymous ``01 TYPE IS ...``
        entries included) land under their own section -- see
        tests/unit/test_report_section.py for the clause-level pins."""
        result = _parse(REPORT_SECTION)
        sections = _sections_by_name(result)
        assert "REPORT" in sections
        (group,) = sections["REPORT"].data_items
        assert group.get_metadata("rd_report_name") == "SALES-REPORT"
        assert group.get_metadata("report_clauses") == {"type": "PAGE HEADING"}
        assert group.get_metadata("rd_clauses")["page_limit"] == 60

    def test_has_report_metadata_flag_set(self):
        result = _parse(REPORT_SECTION)
        assert result.ast.data_division.metadata["has_report"] is True

    def test_procedure_division_still_parses_after_report_section(self):
        result = _parse(REPORT_SECTION)
        assert result.success
        displays = result.ast.find_all_by_type("DisplayStatement")
        assert len(displays) == 1

    def test_parsed_section_records_no_warning(self):
        result = _parse(REPORT_SECTION)
        assert result.warnings == []


class TestBareReportClauseWordIsNotMisreadAsASectionHeader:
    """``REPORT`` is also an FD clause word (``REPORT IS report-name``), not
    only a section header -- see ``examples/cobol/shamrice/report_test.cbl``
    line 32. The DATA DIVISION dispatch loop must only treat SCREEN/REPORT/
    COMMUNICATION as a section header when the next token is literally
    SECTION (mirroring ``_parse_section``'s own lookahead for these same
    three headers), or a bare clause-word use would wrongly discard
    whatever source follows it -- the same "swallow" bug class this parser
    has been repeatedly audited for elsewhere.
    """

    def test_bare_report_clause_word_is_not_treated_as_a_section_header(self):
        result = parse_cobol(FD_REPORT_CLAUSE_TEMPLATE, filename="probe.cbl")
        assert result.success
        assert result.errors == []
        sections = _sections_by_name(result)
        assert "REPORT" not in sections
        ws_names = {d.name for d in sections["WORKING-STORAGE"].data_items}
        assert ws_names == {"WS-ONE"}

    def test_bare_report_clause_word_does_not_record_the_skip_warning(self):
        result = parse_cobol(FD_REPORT_CLAUSE_TEMPLATE, filename="probe.cbl")
        assert not any("REPORT SECTION" in w for w in result.warnings)

    def test_bare_report_clause_word_does_not_swallow_procedure_division(self):
        result = parse_cobol(FD_REPORT_CLAUSE_TEMPLATE, filename="probe.cbl")
        displays = result.ast.find_all_by_type("DisplayStatement")
        assert len(displays) == 1


class TestCommunicationSectionRecognition:
    def test_working_storage_not_polluted_by_communication_content(self):
        result = _parse(COMMUNICATION_SECTION)
        sections = _sections_by_name(result)
        ws_names = {d.name for d in sections["WORKING-STORAGE"].data_items}
        assert ws_names == {"WS-ONE", "WS-TWO"}

    def test_communication_section_is_its_own_empty_section(self):
        result = _parse(COMMUNICATION_SECTION)
        sections = _sections_by_name(result)
        assert "COMMUNICATION" in sections
        assert sections["COMMUNICATION"].data_items == []

    def test_has_communication_metadata_flag_set(self):
        result = _parse(COMMUNICATION_SECTION)
        assert result.ast.data_division.metadata["has_communication"] is True

    def test_procedure_division_still_parses_after_communication_section(self):
        result = _parse(COMMUNICATION_SECTION)
        assert result.success
        displays = result.ast.find_all_by_type("DisplayStatement")
        assert len(displays) == 1

    def test_item_trailing_unsupported_section_is_dropped_not_merged(self):
        """WS-AFTER-CD (declared after the CD entry, with no section header
        of its own) must NOT reappear in WORKING-STORAGE -- that cross-
        boundary merge was the original bug. It is not modeled anywhere
        else either; this pins the documented discard tradeoff, not an
        aspiration that it be preserved.
        """
        result = _parse(COMMUNICATION_SECTION)
        sections = _sections_by_name(result)
        ws_names = {d.name for d in sections["WORKING-STORAGE"].data_items}
        assert "WS-AFTER-CD" not in ws_names
        all_names = {
            d.to_dict().get("name")
            for d in result.ast.find_all_by_type("CobolDataItem")
        }
        assert "WS-AFTER-CD" not in all_names

    def test_skipping_section_records_a_warning(self):
        result = _parse(COMMUNICATION_SECTION)
        assert any("COMMUNICATION SECTION" in w for w in result.warnings)


class TestRealSamplesNoLongerPolluteWorkingStorage:
    """End-to-end pin against the real fixture files that triggered this bug."""

    def test_screen_section_io_sample(self, samples_dir):
        source = (samples_dir / "screen_section_io.cbl").read_text(encoding="utf-8")
        result = parse_cobol(source, filename="screen_section_io.cbl")
        sections = _sections_by_name(result)
        # 5 real WORKING-STORAGE 01-level items in the fixture -- previously
        # ballooned to 33 by absorbed SCREEN SECTION content.
        assert len(sections["WORKING-STORAGE"].data_items) == 5
        assert sections["SCREEN"].data_items == []

    def test_report_writer_sample(self, samples_dir):
        source = (samples_dir / "report_writer.cbl").read_text(encoding="utf-8")
        result = parse_cobol(source, filename="report_writer.cbl")
        sections = _sections_by_name(result)
        # 3 real WORKING-STORAGE 01-level items -- previously ballooned to 29.
        assert len(sections["WORKING-STORAGE"].data_items) == 3
        # 8 report groups under RD SALES-REPORT (parsed since 2026-09-02)
        assert len(sections["REPORT"].data_items) == 8
        assert {
            g.get_metadata("rd_report_name") for g in sections["REPORT"].data_items
        } == {"SALES-REPORT"}

    def test_communication_module_sample(self, samples_dir):
        source = (samples_dir / "communication_module.cbl").read_text(encoding="utf-8")
        result = parse_cobol(source, filename="communication_module.cbl")
        sections = _sections_by_name(result)
        # 5 real WORKING-STORAGE 01-level items -- previously ballooned to 12.
        assert len(sections["WORKING-STORAGE"].data_items) == 5
        assert sections["COMMUNICATION"].data_items == []
