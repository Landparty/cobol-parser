"""Regression coverage for the expander's source map and comment preservation.

**1. A real source map.** ``expand_copybooks(preserve_source_locations=True)``
used to return an always-empty dict: ``_expand_source_recursive``'s
location-tracking branch was a literal ``pass`` with a note that "line
mapping is approximate or requires new logic". Every consumer therefore had
to guess where a finding reported against the expanded text belonged in the
file on disk -- the VS Code extension re-anchored lint findings by searching
the file for the name each one was about, which only works because most
rules report something *unreferenced*, and cannot work at all for a finding
inside an inlined member (it is not in that file).

``expand_copybooks`` now carries one ``(file, line)`` origin per expanded
line through all four steps that can move a line: comment blanking and the
sequence-area strip (line-preserving), continuation joining (merges lines),
the COPY splice (inserts them), and the re-pad's width wrap (splits one into
several). ``ParseResult.expansion_source_map`` carries it out of
``parse_cobol_with_expansion``, and ``lint.apply_source_map`` stamps each
finding with the file and line it is really on.

**2. Comments survive into the listing.** Expansion blanks every comment
line before it starts -- it has to, or a ``COPY`` written inside a comment
would be expanded -- so the expanded output kept comment line *numbers* but
not their text. ``preserve_comments=True`` (``expand --keep-comments``) puts
the original text back afterwards, via the same map, for output meant to be
read. It restores a line only when that line is blank in the expansion AND
its origin really is a comment line, so it can never rewrite code.
"""

import pytest

from cobolparser.analysis.lint import (
    LintAnalyzer,
    LintFinding,
    LintReport,
    apply_source_map,
)
from cobolparser.models.ast_base import SourceLocation
from cobolparser.preprocess import expand_copybooks
from cobolparser.preprocess.copybook_expander import parse_cobol_with_expansion


def _pad(text: str) -> str:
    """A fixed-format record: 6 blank sequence columns, then Area A/B text."""
    return "      " + text


CUSTOMER_CPY = "\n".join(
    [
        _pad("* customer master record"),
        _pad(" 01  CUST-REC."),
        _pad("     05  CUST-ID     PIC 9(6)."),
        _pad("     05  CUST-NAME   PIC X(20)."),
    ]
)


PROGRAM = "\n".join(
    [
        _pad("* payroll driver"),
        _pad(" IDENTIFICATION DIVISION."),
        _pad(" PROGRAM-ID. PAYROLL."),
        _pad(" DATA DIVISION."),
        _pad(" WORKING-STORAGE SECTION."),
        _pad("* the customer layout"),
        _pad(" COPY CUSTOMER."),
        _pad(" 01  WS-UNUSED       PIC X."),
        _pad(" PROCEDURE DIVISION."),
        _pad(" MAIN-PARA."),
        _pad("*    DISPLAY CUST-NAME."),
        _pad("     DISPLAY CUST-ID."),
        _pad("     GOBACK."),
    ]
)


@pytest.fixture
def library(tmp_path):
    (tmp_path / "CUSTOMER.cpy").write_text(CUSTOMER_CPY + "\n")
    program = tmp_path / "PAYROLL.cbl"
    program.write_text(PROGRAM + "\n")
    return tmp_path


def _origins(result):
    """The map as a list indexed the way the expanded source's lines are."""
    lines = result.expanded_source.split("\n")
    return [result.source_location_map.get(n) for n in range(1, len(lines) + 1)]


class TestSourceMap:
    def test_no_copy_maps_every_line_to_itself(self, tmp_path):
        source = "\n".join([_pad(" IDENTIFICATION DIVISION."), _pad(" PROGRAM-ID. X.")])
        result = expand_copybooks(
            source, [str(tmp_path)], preserve_source_locations=True, source_file="x.cbl"
        )

        assert result.source_location_map == {1: ("x.cbl", 1), 2: ("x.cbl", 2)}

    def test_map_is_absent_unless_asked_for(self, library):
        result = expand_copybooks(PROGRAM, [str(library)])

        assert result.source_location_map is None

    def test_lines_after_a_copy_map_back_to_the_program(self, library):
        result = expand_copybooks(
            PROGRAM,
            [str(library)],
            preserve_source_locations=True,
            source_file="PAYROLL.cbl",
        )
        lines = result.expanded_source.split("\n")

        # The COPY sits on line 7 of the program; the four copybook lines are
        # inlined in its place, so everything below it has shifted down -- and
        # every one of those lines still maps to the line it occupies on disk.
        unused = next(i for i, line in enumerate(lines) if "WS-UNUSED" in line)
        assert result.source_location_map[unused + 1] == ("PAYROLL.cbl", 8)

        goback = next(i for i, line in enumerate(lines) if "GOBACK" in line)
        assert result.source_location_map[goback + 1] == ("PAYROLL.cbl", 13)

    def test_inlined_lines_map_into_the_copybook(self, library):
        result = expand_copybooks(
            PROGRAM,
            [str(library)],
            preserve_source_locations=True,
            source_file="PAYROLL.cbl",
        )
        lines = result.expanded_source.split("\n")
        cpy = str(library / "CUSTOMER.cpy")

        cust_id = next(i for i, line in enumerate(lines) if "CUST-ID" in line)
        # Line 3 of the copybook, in the copybook -- not a line of the program.
        assert result.source_location_map[cust_id + 1] == (cpy, 3)

    def test_every_expanded_line_is_accounted_for(self, library):
        result = expand_copybooks(
            PROGRAM,
            [str(library)],
            preserve_source_locations=True,
            source_file="PAYROLL.cbl",
        )
        origins = _origins(result)

        # Only the trailing empty line after the final newline may be unmapped.
        assert all(o is not None for o in origins[:-1])

    def test_a_merged_continuation_maps_to_the_line_it_started_on(self, tmp_path):
        # A VALUE literal continued onto a second record: continuation joining
        # merges the two into one line, which must map to the FIRST of them.
        # (The COPY is what puts the file through the joining path at all --
        # expansion returns a file with no COPY statements untouched.)
        (tmp_path / "FLAG.cpy").write_text(_pad(" 01  WS-FLAG PIC X.") + "\n")
        source = "\n".join(
            [
                _pad(" IDENTIFICATION DIVISION."),
                _pad(" PROGRAM-ID. CONT."),
                _pad(" DATA DIVISION."),
                _pad(" WORKING-STORAGE SECTION."),
                _pad(' 01  WS-TEXT PIC X(12) VALUE "ABCDEF'),
                "      -" + '    "GHIJKL".',  # '-' in column 7: a continuation
                _pad(" COPY FLAG."),
                _pad(" PROCEDURE DIVISION."),
                _pad("     GOBACK."),
            ]
        )
        result = expand_copybooks(
            source,
            [str(tmp_path)],
            preserve_source_locations=True,
            source_file="cont.cbl",
        )
        lines = result.expanded_source.split("\n")

        merged = next(i for i, line in enumerate(lines) if "GHIJKL" in line)
        assert result.source_location_map[merged + 1] == ("cont.cbl", 5)
        # And the lines after the merge keep pointing at their real records,
        # despite the merge having removed a line above them.
        procedure = next(i for i, line in enumerate(lines) if "PROCEDURE" in line)
        assert result.source_location_map[procedure + 1] == ("cont.cbl", 8)

    def test_nested_copybook_lines_name_the_inner_member(self, tmp_path):
        (tmp_path / "INNER.cpy").write_text(_pad("     10  INNER-FIELD PIC X.") + "\n")
        (tmp_path / "OUTER.cpy").write_text(
            "\n".join([_pad(" 01  OUTER-REC."), _pad("     COPY INNER.")]) + "\n"
        )
        source = "\n".join(
            [
                _pad(" IDENTIFICATION DIVISION."),
                _pad(" PROGRAM-ID. NEST."),
                _pad(" DATA DIVISION."),
                _pad(" WORKING-STORAGE SECTION."),
                _pad(" COPY OUTER."),
                _pad(" PROCEDURE DIVISION."),
                _pad("     GOBACK."),
            ]
        )
        result = expand_copybooks(
            source,
            [str(tmp_path)],
            preserve_source_locations=True,
            source_file="nest.cbl",
        )
        lines = result.expanded_source.split("\n")

        inner = next(i for i, line in enumerate(lines) if "INNER-FIELD" in line)
        assert result.source_location_map[inner + 1] == (str(tmp_path / "INNER.cpy"), 1)
        outer = next(i for i, line in enumerate(lines) if "OUTER-REC" in line)
        assert result.source_location_map[outer + 1] == (str(tmp_path / "OUTER.cpy"), 1)

    def test_the_same_member_copied_twice_maps_both_copies(self, tmp_path):
        # The second COPY of a member is served from the expansion cache; its
        # origins have to come back with it, or the cheap path would produce a
        # map the slow path would not.
        (tmp_path / "SHARED.cpy").write_text(_pad(" 01  SHARED-REC PIC X.") + "\n")
        source = "\n".join(
            [
                _pad(" IDENTIFICATION DIVISION."),
                _pad(" PROGRAM-ID. TWICE."),
                _pad(" DATA DIVISION."),
                _pad(" WORKING-STORAGE SECTION."),
                _pad(" COPY SHARED."),
                _pad(" LINKAGE SECTION."),
                _pad(" COPY SHARED."),
                _pad(" PROCEDURE DIVISION."),
                _pad("     GOBACK."),
            ]
        )
        result = expand_copybooks(
            source,
            [str(tmp_path)],
            preserve_source_locations=True,
            source_file="twice.cbl",
        )
        lines = result.expanded_source.split("\n")
        shared = str(tmp_path / "SHARED.cpy")

        hits = [i for i, line in enumerate(lines) if "SHARED-REC" in line]
        assert len(hits) == 2
        assert [result.source_location_map[i + 1] for i in hits] == [
            (shared, 1),
            (shared, 1),
        ]

    def test_parse_with_expansion_carries_the_map(self, library):
        result = parse_cobol_with_expansion(
            PROGRAM,
            filename=str(library / "PAYROLL.cbl"),
            copybook_paths=[str(library)],
        )

        assert result.expansion_source_map is not None
        assert result.expansion_source_map[1] == (str(library / "PAYROLL.cbl"), 1)


class TestNoPhantomLinePerCopy:
    """A COPY splice used to retain both the copybook's own trailing "\\n"
    and the COPY statement's own line terminator, inserting one extra blank
    physical line per COPY beyond the real net growth (a 2-line copybook
    replacing a 1-line COPY grew the file by +2 instead of +1). See
    reports/open-findings.md's "Every COPY statement inserts one extra
    phantom line" entry -- this pins the fix.
    """

    def test_one_copybook_grows_by_real_content_only(self, tmp_path):
        (tmp_path / "TWO.cpy").write_text(
            _pad(" 01  WS-A PIC X.") + "\n" + _pad(" 01  WS-B PIC X.") + "\n"
        )
        source = "\n".join(
            [_pad(" IDENTIFICATION DIVISION."), _pad(" COPY TWO."), _pad(" GOBACK.")]
        )
        result = expand_copybooks(source, [str(tmp_path)])

        # The 2-line copybook replaces the 1-line COPY statement: net growth
        # is +1, not +2 (the phantom line's excess on top of that).
        assert len(result.expanded_source.splitlines()) == len(source.splitlines()) + 1

    def test_no_blank_line_separates_copybook_content_from_what_follows(self, tmp_path):
        (tmp_path / "TWO.cpy").write_text(
            _pad(" 01  WS-A PIC X.") + "\n" + _pad(" 01  WS-B PIC X.") + "\n"
        )
        source = "\n".join(
            [_pad(" IDENTIFICATION DIVISION."), _pad(" COPY TWO."), _pad(" GOBACK.")]
        )
        result = expand_copybooks(source, [str(tmp_path)])
        lines = result.expanded_source.splitlines()

        ws_b = next(i for i, line in enumerate(lines) if "WS-B" in line)
        assert "GOBACK" in lines[ws_b + 1]

    def test_two_copies_do_not_compound_the_excess(self, tmp_path):
        (tmp_path / "TWOLINE.cpy").write_text(
            _pad(" 01  WS-A PIC X.") + "\n" + _pad(" 01  WS-B PIC X.") + "\n"
        )
        (tmp_path / "ONELINE.cpy").write_text(_pad(" 01  WS-C PIC X.") + "\n")
        source = "\n".join(
            [
                _pad(" IDENTIFICATION DIVISION."),
                _pad(" COPY TWOLINE."),
                _pad(" COPY ONELINE."),
                _pad(" GOBACK."),
            ]
        )
        result = expand_copybooks(source, [str(tmp_path)])

        # 3 copybook lines total replace 2 COPY statements: net growth +1,
        # not +3 (a +1 excess per COPY compounding with the count of COPYs).
        assert len(result.expanded_source.splitlines()) == len(source.splitlines()) + 1


class TestApplySourceMap:
    def _report(self, line):
        return LintReport(
            findings=[
                LintFinding(
                    rule="dead-code",
                    severity="warning",
                    message="unreferenced",
                    location=SourceLocation(line=line, column=1),
                )
            ]
        )

    def test_maps_a_finding_onto_its_origin(self):
        report = apply_source_map(self._report(9), {9: ("CUSTOMER.cpy", 3)})

        assert report.findings[0].origin_file == "CUSTOMER.cpy"
        assert report.findings[0].origin_line == 3
        assert report.findings[0].to_dict()["origin"] == {
            "file": "CUSTOMER.cpy",
            "line": 3,
        }
        assert report.findings[0].origin_column is None

    def test_column_offset_stamps_the_on_disk_column(self):
        # #301: a fixed-format file's columns 1-7 never reach the analyzers.
        report = apply_source_map(
            self._report(9),
            {9: ("CUSTOMER.cpy", 3)},
            lambda file, line: 7 if (file, line) == ("CUSTOMER.cpy", 3) else None,
        )

        assert report.findings[0].to_dict()["origin"] == {
            "file": "CUSTOMER.cpy",
            "line": 3,
            "column": 8,
        }

    def test_a_parse_error_without_a_column_gets_none_mapped(self):
        # The placeholder column 1 must not become a real-looking column 8.
        from types import SimpleNamespace

        from cobolparser.analysis.lint import add_parse_errors

        report = add_parse_errors(
            LintReport(),
            [SimpleNamespace(line_number=4, column=None, message="bad", code=None)],
        )
        apply_source_map(report, {4: ("x.cbl", 4)}, lambda _f, _l: 7)

        finding = report.findings[0]
        assert finding.column_known is False
        assert finding.origin_column is None
        assert finding.to_dict()["origin"] == {"file": "x.cbl", "line": 4}

    def test_column_offset_none_leaves_the_column_unset(self):
        report = apply_source_map(
            self._report(9), {9: ("CUSTOMER.cpy", 3)}, lambda _f, _l: None
        )

        assert report.findings[0].origin_column is None

    def test_fixed_format_column_offset_per_layout(self):
        from cobolparser.analysis.lint import fixed_format_column_offset

        assert fixed_format_column_offset(parsed_fixed=True, file_fixed=True) == 7
        assert fixed_format_column_offset(parsed_fixed=True, file_fixed=False) == 0
        assert fixed_format_column_offset(parsed_fixed=False, file_fixed=True) == 6
        assert fixed_format_column_offset(parsed_fixed=False, file_fixed=False) == 0

    def test_no_map_leaves_the_finding_alone(self):
        report = apply_source_map(self._report(9), None)

        assert report.findings[0].origin_file is None
        assert "origin" not in report.findings[0].to_dict()

    def test_an_uncovered_line_claims_nothing(self):
        report = apply_source_map(self._report(9), {4: ("x.cbl", 4)})

        assert report.findings[0].origin_line is None

    def test_a_half_known_origin_is_not_serialized(self):
        # A partial origin (file but no line, or the reverse) would read as an
        # answer to a consumer checking for the key; nobody produces one
        # today, and the serialization must not start if anybody does.
        finding = LintFinding(
            rule="dead-code",
            severity="warning",
            message="unreferenced",
            origin_file="CUSTOMER.cpy",
        )

        assert "origin" not in finding.to_dict()

    def test_a_finding_with_no_location_is_skipped(self):
        report = LintReport(
            findings=[
                LintFinding(rule="recursion-check", severity="error", message="cycle")
            ]
        )

        assert (
            apply_source_map(report, {1: ("x.cbl", 1)}).findings[0].origin_line is None
        )


class TestPreserveComments:
    def test_comments_are_blanked_by_default(self, library):
        result = expand_copybooks(PROGRAM, [str(library)])

        assert "payroll driver" not in result.expanded_source
        assert "customer master record" not in result.expanded_source

    def test_comments_come_back_in_program_and_copybook(self, library):
        result = expand_copybooks(PROGRAM, [str(library)], preserve_comments=True)

        assert "* payroll driver" in result.expanded_source
        assert "* the customer layout" in result.expanded_source
        assert "* customer master record" in result.expanded_source
        assert "*    DISPLAY CUST-NAME." in result.expanded_source

    def test_restoring_comments_does_not_move_any_line(self, library):
        plain = expand_copybooks(PROGRAM, [str(library)])
        kept = expand_copybooks(PROGRAM, [str(library)], preserve_comments=True)

        plain_lines = plain.expanded_source.split("\n")
        kept_lines = kept.expanded_source.split("\n")
        assert len(plain_lines) == len(kept_lines)
        # Every line that was not a blanked comment is byte-identical.
        for before, after in zip(plain_lines, kept_lines, strict=True):
            if before.strip():
                assert before == after

    def test_a_copy_inside_a_comment_is_still_not_expanded(self, tmp_path):
        (tmp_path / "GHOST.cpy").write_text(_pad(" 01  GHOST-REC PIC X.") + "\n")
        source = "\n".join(
            [
                _pad(" IDENTIFICATION DIVISION."),
                _pad(" PROGRAM-ID. GHOSTED."),
                _pad(" DATA DIVISION."),
                _pad(" WORKING-STORAGE SECTION."),
                _pad("* COPY GHOST."),
                _pad(" PROCEDURE DIVISION."),
                _pad("     GOBACK."),
            ]
        )
        result = expand_copybooks(source, [str(tmp_path)], preserve_comments=True)

        # The comment text is back, and it is still only a comment.
        assert "* COPY GHOST." in result.expanded_source
        assert "GHOST-REC" not in result.expanded_source
        assert result.included_copybooks == []

    @pytest.mark.parametrize("eol", ["\r", "\r\n"], ids=["cr-only", "crlf"])
    def test_a_cr_or_crlf_copybook_restores_each_comment_once(self, tmp_path, eol):
        # #581: the comment read-back split files on "\n" only, while the
        # source map counts lines with split_source_lines. A CR-only member
        # came back as ONE line and was pasted whole in place of its first
        # comment (its record listed twice); a CRLF member left a "\r" on
        # every restored comment.
        (tmp_path / "CB.cpy").write_bytes(
            eol.join(
                [
                    _pad("* COPYBOOK COMMENT"),
                    _pad(" 01  CB-REC."),
                    _pad("     05  CB-A PIC X."),
                    "",
                ]
            ).encode("ascii")
        )
        source = "\n".join(
            [
                _pad(" IDENTIFICATION DIVISION."),
                _pad(" PROGRAM-ID. CRPROG."),
                _pad(" DATA DIVISION."),
                _pad(" WORKING-STORAGE SECTION."),
                _pad(" COPY CB."),
                _pad(" PROCEDURE DIVISION."),
                _pad("     GOBACK."),
            ]
        )
        result = expand_copybooks(source, [str(tmp_path)], preserve_comments=True)

        assert result.expanded_source.count("* COPYBOOK COMMENT") == 1
        assert result.expanded_source.count("CB-REC") == 1
        assert "\r" not in result.expanded_source

    def test_a_cr_only_program_restores_its_own_comments(self, tmp_path):
        (tmp_path / "CB.cpy").write_text(_pad(" 01  CB-REC PIC X.") + "\n")
        source = "\r".join(
            [
                _pad(" IDENTIFICATION DIVISION."),
                _pad(" PROGRAM-ID. CRMAIN."),
                _pad("* MAIN COMMENT"),
                _pad(" DATA DIVISION."),
                _pad(" WORKING-STORAGE SECTION."),
                _pad(" COPY CB."),
                _pad(" PROCEDURE DIVISION."),
                _pad("     GOBACK."),
            ]
        )
        result = expand_copybooks(source, [str(tmp_path)], preserve_comments=True)

        assert result.expanded_source.count("* MAIN COMMENT") == 1
        assert result.expanded_source.count("PROGRAM-ID") == 1
        assert "\r" not in result.expanded_source


class TestTextAfterCopyOnItsLine:
    """#355: text after a COPY's period was appended to the copybook's last
    line and inherited its origin, so lint blamed the member for a parent
    item. It now gets a physical line of its own, credited to the parent."""

    AREC = "\n".join([_pad(" 05 A-ONE PIC X."), _pad(" 05 A-TWO PIC X.")])
    SOURCE = "\n".join(
        [
            _pad(" IDENTIFICATION DIVISION."),
            _pad(" PROGRAM-ID. M."),
            _pad(" DATA DIVISION."),
            _pad(" WORKING-STORAGE SECTION."),
            _pad(" 01 REC."),
            _pad("     COPY AREC"),
            _pad("         REPLACING A-ONE BY Z-ONE. 05 TAIL-X PIC X."),
            _pad(" PROCEDURE DIVISION."),
            _pad("     DISPLAY Z-ONE."),
            _pad("     GOBACK."),
        ]
    )

    def _expand(self, tmp_path):
        (tmp_path / "AREC.cpy").write_text(self.AREC + "\n")
        return expand_copybooks(
            self.SOURCE,
            [str(tmp_path)],
            preserve_source_locations=True,
            source_file="M.cbl",
        )

    def test_tail_is_on_its_own_line_mapped_to_the_parent(self, tmp_path):
        result = self._expand(tmp_path)
        lines = result.expanded_source.split("\n")
        origins = _origins(result)
        cpy = str(tmp_path / "AREC.cpy")

        two = next(i for i, line in enumerate(lines) if "A-TWO" in line)
        tail = next(i for i, line in enumerate(lines) if "TAIL-X" in line)
        assert "TAIL-X" not in lines[two]
        assert origins[two] == (cpy, 2)
        assert origins[tail] == ("M.cbl", 7)
        # The tail keeps the columns it has on disk.
        original = self.SOURCE.split("\n")[6]
        assert lines[tail].index("05 TAIL-X") == original.index("05 TAIL-X")

    def test_lines_below_keep_their_origin(self, tmp_path):
        result = self._expand(tmp_path)
        lines = result.expanded_source.split("\n")
        origins = _origins(result)

        goback = next(i for i, line in enumerate(lines) if "GOBACK" in line)
        assert origins[goback] == ("M.cbl", 10)

    def test_lint_locates_the_tail_item_in_the_parent(self, tmp_path):
        (tmp_path / "AREC.cpy").write_text(self.AREC + "\n")
        parsed = parse_cobol_with_expansion(
            self.SOURCE, "M.cbl", copybook_paths=[str(tmp_path)]
        )
        report = apply_source_map(
            LintAnalyzer(["unused-variables"]).analyze(parsed.ast),
            parsed.expansion_source_map,
        )

        tail = next(f for f in report.findings if f.symbol == "TAIL-X")
        assert (tail.origin_file, tail.origin_line) == ("M.cbl", 7)

    def test_a_copy_alone_on_its_line_adds_no_line(self, tmp_path):
        (tmp_path / "AREC.cpy").write_text(self.AREC + "\n")
        source = self.SOURCE.replace(" 05 TAIL-X PIC X.", "")
        result = expand_copybooks(source, [str(tmp_path)])

        assert len(result.expanded_source.split("\n")) == 10
