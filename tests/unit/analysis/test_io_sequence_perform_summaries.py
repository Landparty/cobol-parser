"""IOSequenceAnalyzer: PERFORM ranges are summarized, not re-inlined (#371).

The walk used to re-run a PERFORM target's paragraphs at every call site
through Python recursion: a PERFORM chain ~250 deep raised RecursionError,
and a paragraph PERFORMed twice per level of nesting cost 2**depth walks.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.io_sequence import IOSequenceAnalyzer

_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F-FILE ASSIGN TO 'F'.
           SELECT G-FILE ASSIGN TO 'G'.
           SELECT H-FILE ASSIGN TO 'H'.
       DATA DIVISION.
       FILE SECTION.
       FD F-FILE.
       01 F-REC PIC X(10).
       FD G-FILE.
       01 G-REC PIC X(10).
       FD H-FILE.
       01 H-REC PIC X(10).
       PROCEDURE DIVISION.
"""


def _analyze(paragraphs: dict[str, list[str]]) -> list[tuple[str, str]]:
    src = _HEADER + "".join(
        f"       {name}.\n" + "".join(f"           {s}.\n" for s in body)
        for name, body in paragraphs.items()
    )
    result = parse_cobol(src)
    assert result.ast is not None
    report = IOSequenceAnalyzer().analyze(result.ast)
    return [(v.kind.name, v.file_name) for v in report.violations]


def _count_paragraph_runs(monkeypatch) -> list[int]:
    calls = [0]
    original = IOSequenceAnalyzer._run_paragraph

    def counting(self, para):
        calls[0] += 1
        return original(self, para)

    monkeypatch.setattr(IOSequenceAnalyzer, "_run_paragraph", counting)
    return calls


class TestDeepPerformChain:
    def test_chain_past_the_recursion_limit(self):
        depth = 1500
        paras: dict[str, list[str]] = {
            "MAIN-P": ["OPEN INPUT F-FILE", "PERFORM P1", "STOP RUN"]
        }
        for i in range(1, depth):
            paras[f"P{i}"] = [f"PERFORM P{i + 1}"]
        paras[f"P{depth}"] = ["READ F-FILE", "CLOSE F-FILE"]
        # The CLOSE at the bottom of the chain is seen: nothing left open.
        assert _analyze(paras) == []

    def test_violation_at_the_bottom_of_a_deep_chain(self):
        depth = 1500
        paras: dict[str, list[str]] = {"MAIN-P": ["PERFORM P1", "STOP RUN"]}
        for i in range(1, depth):
            paras[f"P{i}"] = [f"PERFORM P{i + 1}"]
        paras[f"P{depth}"] = ["READ F-FILE"]
        assert _analyze(paras) == [("READ_BEFORE_OPEN", "F-FILE")]


class TestSharedPerformTargets:
    def test_fan_out_is_walked_once_per_level(self, monkeypatch):
        calls = _count_paragraph_runs(monkeypatch)
        depth = 40
        paras: dict[str, list[str]] = {
            "MAIN-P": ["OPEN OUTPUT F-FILE", "PERFORM L1", "CLOSE F-FILE", "STOP RUN"]
        }
        for i in range(1, depth):
            paras[f"L{i}"] = [f"PERFORM L{i + 1}"] * 2
        paras[f"L{depth}"] = ["WRITE F-REC"]
        assert _analyze(paras) == []
        # MAIN-P plus each level once; 2**40 before the fix.
        assert calls[0] == depth + 1

    def test_shared_helper_runs_again_from_a_new_file_state(self):
        # The helper's READ is a violation before the OPEN and not after:
        # a summary is only reused from the same open/closed state.
        assert _analyze(
            {
                "MAIN-P": [
                    "PERFORM READ-P",
                    "OPEN INPUT F-FILE",
                    "PERFORM READ-P",
                    "CLOSE F-FILE",
                    "STOP RUN",
                ],
                "READ-P": ["READ F-FILE"],
            }
        ) == [("READ_BEFORE_OPEN", "F-FILE")]

    def test_replayed_summary_restores_file_state(self):
        # The second PERFORM INIT-P is replayed: its OPEN must still take
        # effect, or the READ after it would look unopened.
        assert _analyze(
            {
                "MAIN-P": [
                    "PERFORM INIT-P",
                    "CLOSE F-FILE",
                    "PERFORM INIT-P",
                    "READ F-FILE",
                    "PERFORM INIT-P",
                    "STOP RUN",
                ],
                "INIT-P": ["PERFORM OPEN-P"],
                "OPEN-P": ["OPEN INPUT F-FILE"],
            }
        ) == [("DOUBLE_OPEN", "F-FILE"), ("FILE_LEFT_OPEN", "F-FILE")]

    def test_one_violation_per_location_across_call_sites(self):
        assert _analyze(
            {
                "MAIN-P": ["PERFORM A-P", "PERFORM B-P", "STOP RUN"],
                "A-P": ["PERFORM LOG-P"],
                "B-P": ["PERFORM LOG-P", "PERFORM LOG-P"],
                "LOG-P": ["WRITE H-REC"],
            }
        ) == [("WRITE_BEFORE_OPEN", "H-FILE")]

    def test_summary_not_reused_when_the_recursion_guard_differs(self):
        # B-P first runs inside A-P, where its PERFORM A-P is skipped by the
        # re-entrancy guard. MAIN-P then PERFORMs B-P from the same file
        # state with A-P *not* running: A-P's OPEN G-FILE must happen.
        violations = _analyze(
            {
                "MAIN-P": [
                    "OPEN INPUT F-FILE G-FILE",
                    "CLOSE F-FILE G-FILE",
                    "PERFORM A-P",
                    "CLOSE F-FILE G-FILE",
                    "PERFORM B-P",
                    "STOP RUN",
                ],
                "A-P": ["PERFORM B-P", "OPEN INPUT G-FILE"],
                "B-P": ["PERFORM A-P", "OPEN INPUT F-FILE"],
            }
        )
        assert sorted(violations) == [
            ("FILE_LEFT_OPEN", "F-FILE"),
            ("FILE_LEFT_OPEN", "G-FILE"),
        ]
