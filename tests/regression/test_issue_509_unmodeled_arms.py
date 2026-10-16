"""#509: an arm whose precondition the constraint extractor could not model
(an EVALUATE ``WHEN OTHER`` whose earlier arms do not negate to one
``not_in_set``, every SEARCH ``AT END``) is registered with an empty conjunct
list. ``ScenarioPlanner`` used to solve that ``[]`` as "anything goes", count
the arm ``targeted``, and verification then called zero conjuncts
``verified`` -- while the random rows ran an earlier WHEN (for SEARCH, the
WHEN arm every time). Such an arm is now ``missed`` with the extractor's own
reason, the reason reaches ``FixtureBundle.unresolved``, and ``gen-fixtures
--strict`` exits 2.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.cli.parse import main
from cobolparser.generators import ProgramFixtureGenerator, ProgramLayoutIndex

_EVALUATE_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EV4.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-F ASSIGN TO INDD.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-F.
       01  IN-REC.
           05 IN-CODE   PIC 9(2).
           05 IN-TYPE   PIC X.
           05 IN-AMT    PIC S9(5)V99.
       WORKING-STORAGE SECTION.
       01  WS-OUT       PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-F
           READ IN-F
"""

_TRAILER = """\
           DISPLAY WS-OUT
           CLOSE IN-F
           STOP RUN.
"""

EVALUATE_THRU = _EVALUATE_HEADER + """\
           EVALUATE IN-CODE
              WHEN 1
                 MOVE 'ONE' TO WS-OUT
              WHEN 2 THRU 50
                 MOVE 'MID' TO WS-OUT
              WHEN OTHER
                 MOVE 'OTH' TO WS-OUT
           END-EVALUATE
""" + _TRAILER

EVALUATE_GT = _EVALUATE_HEADER + """\
           EVALUATE TRUE
              WHEN IN-AMT > 1000
                 MOVE 'BIG' TO WS-OUT
              WHEN IN-CODE = 5
                 MOVE 'FIVE' TO WS-OUT
              WHEN OTHER
                 MOVE 'OTH' TO WS-OUT
           END-EVALUATE
""" + _TRAILER

# Control: every arm one equality on the same field -- WHEN OTHER negates to
# a single not_in_set and stays targeted.
EVALUATE_MODELED = _EVALUATE_HEADER + """\
           EVALUATE IN-CODE
              WHEN 1
                 MOVE 'ONE' TO WS-OUT
              WHEN 2
                 MOVE 'TWO' TO WS-OUT
              WHEN OTHER
                 MOVE 'OTH' TO WS-OUT
           END-EVALUATE
""" + _TRAILER

SEARCH_AT_END = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SR1.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-F ASSIGN TO INDD.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-F.
       01  IN-REC.
           05 IN-KEY    PIC X(2).
              88 KEY-ZZ VALUE 'ZZ'.
       WORKING-STORAGE SECTION.
       01  WS-TBL.
           05 WS-ENT OCCURS 3 TIMES INDEXED BY WS-IX.
              10 WS-CODE PIC X(2).
       01  WS-OUT       PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-F
           READ IN-F
           SET WS-IX TO 1
           SEARCH WS-ENT
              AT END MOVE 'NOTFOUND' TO WS-OUT
              WHEN KEY-ZZ
                 MOVE 'ZZ' TO WS-OUT
           END-SEARCH
           DISPLAY WS-OUT
           CLOSE IN-F
           STOP RUN.
"""


def _analyze(source: str):
    result = parse_cobol(source, filename="t.cbl")
    assert result.ast is not None and result.errors == [], result.errors
    index = ProgramLayoutIndex.build(result.ast)
    report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    return result.ast, index, report


def _bundle(source: str, seed: int = 1):
    ast, index, report = _analyze(source)
    return ProgramFixtureGenerator().generate_with_scenarios(
        ast, index, report, mode="branches", seed=seed
    )


def _outcome(bundle, arm_suffix: str) -> dict:
    (outcome,) = [
        d
        for d in bundle.scenario_coverage["details"]
        if d["arm_key"].endswith(arm_suffix)
    ]
    return outcome


UNMODELED = [
    pytest.param(EVALUATE_THRU, "/WHEN_OTHER", "WHEN OTHER", id="evaluate-thru"),
    pytest.param(EVALUATE_GT, "/WHEN_OTHER", "WHEN OTHER", id="evaluate-true-gt"),
    pytest.param(SEARCH_AT_END, "/AT_END", "AT_END", id="search-at-end"),
]


class TestExtractorNamesTheUnmodeledArm:
    @pytest.mark.parametrize(("source", "suffix", "_label"), UNMODELED)
    def test_arm_is_listed_with_its_reason(self, source, suffix, _label):
        ast, index, report = _analyze(source)
        (branch,) = ConstraintExtractor().extract(ast, index, report).branches
        arm_id = suffix.lstrip("/")
        assert branch.arms[arm_id] == []
        assert "not modeled" in branch.unmodeled_arms[arm_id]
        assert branch.to_dict()["unmodeled_arms"] == branch.unmodeled_arms

    def test_modeled_when_other_is_not_listed(self):
        ast, index, report = _analyze(EVALUATE_MODELED)
        (branch,) = ConstraintExtractor().extract(ast, index, report).branches
        assert branch.arms["WHEN_OTHER"][0].op == "not_in_set"
        assert branch.unmodeled_arms == {}


class TestPlannerMissesTheUnmodeledArm:
    @pytest.mark.parametrize(("source", "suffix", "label"), UNMODELED)
    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_arm_is_missed_not_targeted(self, source, suffix, label, seed):
        bundle = _bundle(source, seed)
        coverage = bundle.scenario_coverage
        assert coverage["missed"] == 1
        assert (
            coverage["targeted"] + coverage["merged"] + coverage["missed"]
            == coverage["total_arms"]
        )
        outcome = _outcome(bundle, suffix)
        assert outcome["status"] == "missed"
        assert outcome["reason"].startswith("precondition not modeled: ")
        # No scenario claims an arm its data was never built to reach.
        assert not any(label in s.name for s in bundle.scenarios)
        assert any(
            suffix in note and "precondition not modeled" in note
            for note in bundle.unresolved
        )

    def test_modeled_when_other_is_still_targeted(self):
        bundle = _bundle(EVALUATE_MODELED)
        assert bundle.scenario_coverage["missed"] == 0
        assert _outcome(bundle, "/WHEN_OTHER")["status"] == "targeted"
        assert bundle.unresolved == []


class TestStrictRefusesTheBundle:
    @pytest.mark.parametrize(("source", "_suffix", "_label"), UNMODELED)
    def test_strict_exits_2(
        self, source, _suffix, _label, monkeypatch, capsys, tmp_path
    ):
        path = tmp_path / "prog.cbl"
        path.write_text(source)
        monkeypatch.setattr(
            "sys.argv",
            [
                "cobol-parser",
                "--no-config",
                "gen-fixtures",
                str(path),
                "--scenarios",
                "branches",
                "--seed",
                "1",
                "--strict",
                "--compact",
            ],
        )
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2
        assert "precondition not modeled" in capsys.readouterr().err

    def test_strict_passes_when_when_other_is_modeled(
        self, monkeypatch, capsys, tmp_path
    ):
        path = tmp_path / "prog.cbl"
        path.write_text(EVALUATE_MODELED)
        monkeypatch.setattr(
            "sys.argv",
            [
                "cobol-parser",
                "--no-config",
                "gen-fixtures",
                str(path),
                "--scenarios",
                "branches",
                "--seed",
                "1",
                "--strict",
                "--compact",
            ],
        )
        main()
        assert capsys.readouterr().out
