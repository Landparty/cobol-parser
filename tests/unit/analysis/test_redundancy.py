"""Tests for RedundancyAnalyzer (redundancy.py).

Covers:
- Type-1 (exact) clone detection between identical paragraphs
- Type-2 (renamed) clone detection where identifiers differ consistently
- A changed literal breaks the match entirely (not even a Type-2 clone)
- Below-min-size paragraphs are not reported
- A Type-1 match takes priority over Type-2 grouping for the same paragraph
- Dead-code / unused-variable ratios agree with the underlying analyzers
- Report serialization shape
"""

from cobolparser.analysis.dead_code import DeadCodeAnalyzer
from cobolparser.analysis.redundancy import RedundancyAnalyzer, _canonical
from cobolparser.analysis.unused_variables import UnusedVariableAnalyzer
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.program import CobolDivision, CobolParagraph, CobolProgram
from cobolparser.models.statements.control import StopStatement
from cobolparser.models.statements.data import DisplayStatement, MoveStatement
from cobolparser.parser import parse_cobol

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. REDUNTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9 VALUE 0.
       01 WS-B PIC 9 VALUE 0.
       01 WS-C PIC 9 VALUE 0.
"""


def _analyze(source: str, **kwargs):
    result = parse_cobol(source, filename="reduntest.cbl")
    assert result.ast is not None, result.errors
    return result.ast, RedundancyAnalyzer().analyze(result.ast, **kwargs)


def _group_with(report, name: str):
    for g in report.clone_groups:
        if any(m.name == name for m in g.members):
            return g
    return None


LOC = SourceLocation(1, 12)


def _make_program(paragraphs: list[tuple[str, list]]) -> CobolProgram:
    """Build a CobolProgram directly from paragraph name/statement lists,
    bypassing the parser entirely -- used to test invariants (like clone
    member name casing) that the real parser happens to already normalize
    for every paragraph name it produces, so a source-text-based test could
    never actually exercise a lowercase `paragraph_name`."""
    loc = SourceLocation(1, 1)
    prog = CobolProgram("CASETEST", loc)
    proc_div = CobolDivision("PROCEDURE", loc)
    prog.add_division(proc_div)

    line = 10
    for pname, stmts in paragraphs:
        para = CobolParagraph(pname, SourceLocation(line, 8))
        for s in stmts:
            para.add_statement(s)
        proc_div.add_paragraph(para)
        line += 1

    return prog


def _move(source: str, target: str) -> MoveStatement:
    stmt = MoveStatement(LOC)
    stmt.set_source(source)
    stmt.add_target(target)
    return stmt


def _display(text: str) -> DisplayStatement:
    stmt = DisplayStatement(LOC)
    stmt.add_operand(text)
    return stmt


def _stop_run() -> StopStatement:
    return StopStatement(LOC)


class TestType1Clones:
    def test_identical_paragraphs_are_type1_clones(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM CLONE-A
           PERFORM CLONE-B
           STOP RUN.
       CLONE-A.
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY "DONE"
           STOP RUN.
       CLONE-B.
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY "DONE"
           STOP RUN.
"""
        _, report = _analyze(source)
        group = _group_with(report, "CLONE-A")
        assert group is not None
        assert group.clone_type == "TYPE_1"
        assert {m.name for m in group.members} == {"CLONE-A", "CLONE-B"}
        assert group.statement_count == 4

    def test_different_literal_breaks_the_match(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM CLONE-A
           PERFORM CLONE-B
           STOP RUN.
       CLONE-A.
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY "DONE"
           STOP RUN.
       CLONE-B.
           MOVE 1 TO WS-A
           MOVE 3 TO WS-B
           DISPLAY "DONE"
           STOP RUN.
"""
        _, report = _analyze(source)
        assert report.clone_groups == []


class TestType2Clones:
    def test_renamed_identifiers_are_type2_clones(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM CLONE-A
           PERFORM CLONE-B
           STOP RUN.
       CLONE-A.
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY "DONE"
           STOP RUN.
       CLONE-B.
           MOVE 1 TO WS-B
           MOVE 2 TO WS-C
           DISPLAY "DONE"
           STOP RUN.
"""
        _, report = _analyze(source)
        group = _group_with(report, "CLONE-A")
        assert group is not None
        assert group.clone_type == "TYPE_2"
        assert {m.name for m in group.members} == {"CLONE-A", "CLONE-B"}

    def test_different_statement_shape_does_not_match(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM CLONE-A
           PERFORM CLONE-B
           STOP RUN.
       CLONE-A.
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY "DONE"
           STOP RUN.
       CLONE-B.
           MOVE 1 TO WS-A
           DISPLAY "DONE"
           STOP RUN.
"""
        _, report = _analyze(source)
        assert report.clone_groups == []


class TestClonePriority:
    def test_type1_group_excludes_members_from_type2_pass(self) -> None:
        """A three-way clone where two are exact and one is renamed: the
        exact pair reports as TYPE_1, and the renamed one-off is alone (no
        TYPE_2 group of size 1 is ever reported)."""
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM CLONE-A
           PERFORM CLONE-B
           PERFORM CLONE-C
           STOP RUN.
       CLONE-A.
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY "DONE"
           STOP RUN.
       CLONE-B.
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY "DONE"
           STOP RUN.
       CLONE-C.
           MOVE 1 TO WS-B
           MOVE 2 TO WS-C
           DISPLAY "DONE"
           STOP RUN.
"""
        _, report = _analyze(source)
        assert len(report.clone_groups) == 1
        group = report.clone_groups[0]
        assert group.clone_type == "TYPE_1"
        assert {m.name for m in group.members} == {"CLONE-A", "CLONE-B"}


class TestMinCloneStatements:
    def test_below_min_size_not_reported(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM CLONE-A
           PERFORM CLONE-B
           STOP RUN.
       CLONE-A.
           DISPLAY "X".
       CLONE-B.
           DISPLAY "X".
"""
        _, report = _analyze(source, min_clone_statements=3)
        assert report.clone_groups == []

    def test_custom_threshold_allows_small_groups(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM CLONE-A
           PERFORM CLONE-B
           STOP RUN.
       CLONE-A.
           DISPLAY "X".
       CLONE-B.
           DISPLAY "X".
"""
        _, report = _analyze(source, min_clone_statements=1)
        assert len(report.clone_groups) == 1


class TestDeadAndUnusedRatios:
    def test_ratios_agree_with_underlying_analyzers(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-A
           STOP RUN.
       NEVER-CALLED.
           DISPLAY "DEAD"
           STOP RUN.
"""
        ast, report = _analyze(source)
        dead_report = DeadCodeAnalyzer().analyze(ast)
        unused_report = UnusedVariableAnalyzer().analyze(ast)

        assert report.total_procedures == dead_report.total_procedures
        assert len(report.dead_items) == len(dead_report.dead_items)
        assert {i.name for i in report.dead_items} == {
            i.name for i in dead_report.dead_items
        }
        assert report.total_variables == unused_report.total_variables
        assert {i.name for i in report.unused_items} == {
            i.name for i in unused_report.unused_items
        }

    def test_dead_ratio_and_unused_ratio_computed(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-A
           STOP RUN.
       NEVER-CALLED.
           DISPLAY "DEAD"
           STOP RUN.
"""
        _, report = _analyze(source)
        assert report.dead_ratio == 1 / 2
        # WS-B and WS-C are never referenced (only WS-A is moved to).
        assert report.unused_ratio == 2 / 3

    def test_no_procedure_division_returns_empty_report(self) -> None:
        from cobolparser.models.ast_base import SourceLocation
        from cobolparser.models.program import CobolProgram

        prog = CobolProgram("EMPTY", SourceLocation(1, 1))
        report = RedundancyAnalyzer().analyze(prog)
        assert report.clone_groups == []
        assert report.dead_ratio == 0.0
        assert report.unused_ratio == 0.0


class TestCloneMemberNameCasing:
    """CloneMember.name must be uppercased, matching the convention every
    other analyzer uses for procedure names (DeadCodeItem, FlowNode, ...) --
    TechnicalDebtAnalyzer's top-offender matching compares clone membership
    by name against those always-uppercase sets. The real parser happens to
    already uppercase every paragraph_name it produces regardless of source
    casing, so this can only be exercised by constructing the AST directly."""

    def test_clone_members_are_uppercased(self) -> None:
        prog = _make_program(
            [
                ("main-para", [_stop_run()]),
                (
                    "clone-a",
                    [_move("1", "ws-a"), _move("2", "ws-b"), _display("DONE")],
                ),
                (
                    "clone-b",
                    [_move("1", "ws-a"), _move("2", "ws-b"), _display("DONE")],
                ),
            ]
        )
        report = RedundancyAnalyzer().analyze(prog)
        group = _group_with(report, "CLONE-A")
        assert group is not None
        assert {m.name for m in group.members} == {"CLONE-A", "CLONE-B"}

    def test_lowercase_type1_pair_not_duplicated_into_type2(self) -> None:
        """Regression: type1_names must be built from already-uppercased
        member names so the Type-2 pass's `.upper()` comparison actually
        excludes paragraphs already grouped as Type-1 -- otherwise a
        lowercase-named Type-1 pair could double-report into a Type-2 group
        too."""
        prog = _make_program(
            [
                ("main-para", [_stop_run()]),
                (
                    "clone-a",
                    [_move("1", "ws-a"), _move("2", "ws-b"), _display("DONE")],
                ),
                (
                    "clone-b",
                    [_move("1", "ws-a"), _move("2", "ws-b"), _display("DONE")],
                ),
            ]
        )
        report = RedundancyAnalyzer().analyze(prog)
        assert len(report.clone_groups) == 1
        assert report.clone_groups[0].clone_type == "TYPE_1"


class TestReportSerialization:
    def test_to_dict_shape(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM CLONE-A
           PERFORM CLONE-B
           STOP RUN.
       CLONE-A.
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY "DONE"
           STOP RUN.
       CLONE-B.
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY "DONE"
           STOP RUN.
"""
        _, report = _analyze(source)
        data = report.to_dict()
        assert data["program_name"] == "REDUNTEST"
        assert "dead_code" in data
        assert "unused_variables" in data
        assert "clone_groups" in data
        summary = data["summary"]
        for key in (
            "total_procedures",
            "dead_procedure_count",
            "dead_ratio",
            "total_variables",
            "unused_variable_count",
            "unused_ratio",
            "clone_group_count",
            "cloned_statement_count",
        ):
            assert key in summary
        assert summary["clone_group_count"] == 1
        assert summary["cloned_statement_count"] == 8


class TestParagraphFingerprints:
    """The digests that make clone detection work ACROSS programs.

    `clone_groups` can only ever answer "which paragraphs in this one
    program duplicate each other". These tests pin the property the
    cross-file consumer actually depends on: two paragraphs in two
    SEPARATE programs, neither duplicated within its own file (so neither
    program reports a clone group at all), still carry equal digests.
    """

    @staticmethod
    def _fingerprint(report, name: str):
        for fingerprint in report.paragraph_fingerprints:
            if fingerprint.name == name:
                return fingerprint
        return None

    def test_identical_paragraphs_in_separate_programs_share_a_type1_digest(
        self,
    ) -> None:
        body = """\
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY "DONE"
           STOP RUN.
"""
        _, left = _analyze(
            HEADER + "       PROCEDURE DIVISION.\n       ONLY-PARA.\n" + body
        )
        _, right = _analyze(
            HEADER + "       PROCEDURE DIVISION.\n       OTHER-NAME.\n" + body
        )

        # Neither program duplicates anything internally, which is exactly
        # the case the group-level report cannot see.
        assert left.clone_groups == []
        assert right.clone_groups == []

        a = self._fingerprint(left, "ONLY-PARA")
        b = self._fingerprint(right, "OTHER-NAME")
        assert a is not None and b is not None
        assert a.type1 == b.type1
        assert a.statement_count == b.statement_count == 4

    def test_renamed_identifiers_share_a_type2_digest_but_not_type1(self) -> None:
        _, left = _analyze(HEADER + """\
       PROCEDURE DIVISION.
       ONLY-PARA.
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY "DONE"
           STOP RUN.
""")
        _, right = _analyze(HEADER + """\
       PROCEDURE DIVISION.
       OTHER-NAME.
           MOVE 1 TO WS-C
           MOVE 2 TO WS-A
           DISPLAY "DONE"
           STOP RUN.
""")
        a = self._fingerprint(left, "ONLY-PARA")
        b = self._fingerprint(right, "OTHER-NAME")
        assert a is not None and b is not None
        assert a.type1 != b.type1
        assert a.type2 == b.type2

    def test_a_changed_literal_breaks_both_digests(self) -> None:
        """A literal is behavior, not a name -- the Type-2 pass must not
        normalize it away, or a scan would report two paragraphs that write
        different values as duplicates."""
        _, left = _analyze(HEADER + """\
       PROCEDURE DIVISION.
       ONLY-PARA.
           MOVE 1 TO WS-A
           DISPLAY "ALPHA"
           STOP RUN.
""")
        _, right = _analyze(HEADER + """\
       PROCEDURE DIVISION.
       ONLY-PARA.
           MOVE 1 TO WS-A
           DISPLAY "OMEGA"
           STOP RUN.
""")
        a = self._fingerprint(left, "ONLY-PARA")
        b = self._fingerprint(right, "ONLY-PARA")
        assert a is not None and b is not None
        assert a.type1 != b.type1
        assert a.type2 != b.type2

    def test_digests_agree_with_the_within_program_grouping(self) -> None:
        """The two halves of this module must not be able to disagree: a
        pair the group pass calls a Type-1 clone must have equal `type1`
        digests, and vice versa."""
        source = HEADER + """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM CLONE-A
           PERFORM CLONE-B
           STOP RUN.
       CLONE-A.
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY "DONE"
           STOP RUN.
       CLONE-B.
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY "DONE"
           STOP RUN.
"""
        _, report = _analyze(source)
        group = _group_with(report, "CLONE-A")
        assert group is not None and group.clone_type == "TYPE_1"

        digests = {
            m.name: self._fingerprint(report, m.name).type1 for m in group.members
        }
        assert len(set(digests.values())) == 1

    def test_min_clone_statements_filters_fingerprints_too(self) -> None:
        """The same threshold the group pass applies: a paragraph too small
        to be meaningful redundancy in one program is no more meaningful
        across two."""
        source = HEADER + """\
       PROCEDURE DIVISION.
       BIG-PARA.
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY "DONE"
           STOP RUN.
       TINY-PARA.
           STOP RUN.
"""
        _, report = _analyze(source)
        names = {f.name for f in report.paragraph_fingerprints}
        assert "BIG-PARA" in names
        assert "TINY-PARA" not in names

        _, permissive = _analyze(source, min_clone_statements=1)
        assert "TINY-PARA" in {f.name for f in permissive.paragraph_fingerprints}

    def test_digest_is_stable_across_runs(self) -> None:
        """The digest travels between processes -- a scan hashes it in one
        worker and groups it in another -- so it may never depend on
        anything per-run (an id(), a PYTHONHASHSEED-sensitive hash())."""
        source = HEADER + """\
       PROCEDURE DIVISION.
       ONLY-PARA.
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY "DONE"
           STOP RUN.
"""
        _, first = _analyze(source)
        _, second = _analyze(source)
        assert (
            first.paragraph_fingerprints[0].type1
            == second.paragraph_fingerprints[0].type1
        )
        assert (
            first.paragraph_fingerprints[0].type2
            == second.paragraph_fingerprints[0].type2
        )

    def test_to_dict_carries_fingerprints(self) -> None:
        source = HEADER + """\
       PROCEDURE DIVISION.
       ONLY-PARA.
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY "DONE"
           STOP RUN.
"""
        _, report = _analyze(source)
        entries = report.to_dict()["paragraph_fingerprints"]
        assert len(entries) == 1
        entry = entries[0]
        assert entry["name"] == "ONLY-PARA"
        assert entry["statement_count"] == 4
        assert len(entry["type1"]) == 16
        assert len(entry["type2"]) == 16
        assert entry["location"]["line"] > 0


class TestFingerprintSerialization:
    """`_canonical` is what the digest is taken over, so its injectivity is
    the whole correctness argument for the digest."""

    def test_length_prefix_stops_content_forging_structure(self) -> None:
        """Without the length prefix, ("A,B",) and ("A", "B") would
        serialize alike and two structurally different paragraphs would
        collide."""
        assert _canonical(("A,B",)) != _canonical(("A", "B"))

    def test_none_and_the_string_none_are_distinct(self) -> None:
        """EVALUATE's absent WHEN OTHER is None; a paragraph whose operand
        is literally the text "N" must not look like it."""
        assert _canonical(None) != _canonical("N")

    def test_nesting_is_not_flattened(self) -> None:
        assert _canonical((("A",), ("B",))) != _canonical(("A", "B"))

    def test_a_non_string_scalar_is_carried_through(self) -> None:
        """A PERFORM_INLINE fingerprint carries `perform_type`, which is not
        a str. It must serialize, and it must not collide with the string of
        the same text -- hence the distinct `V` prefix."""
        assert _canonical(3) != _canonical("3")
        assert _canonical(("PERFORM_INLINE", 3)) == _canonical(("PERFORM_INLINE", 3))
        assert _canonical(("PERFORM_INLINE", 3)) != _canonical(("PERFORM_INLINE", 4))
