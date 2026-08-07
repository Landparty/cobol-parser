"""Integration test: BoundaryInventoryAnalyzer over the shamrice corpus.

Mirrors test_program_layout_corpus.py's style. Exit criterion (Phase 2 of the
program-scoped data-generation plan): every boundary in the corpus is either
inventoried with a layout or listed in `unresolved` with a reason -- no
program crashes the analyzer, and no third (silently dropped) state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.generators import ProgramLayoutIndex

pytestmark = pytest.mark.integration

SHAMRICE_DIR = Path(__file__).parent.parent.parent / "examples" / "cobol" / "shamrice"

_ALL_CBL = sorted(SHAMRICE_DIR.glob("*.cbl"))

_EXPECTED_UNRESOLVED = {
    # report_test.cbl's FD names a Report Writer REPORT SECTION record (RD),
    # not a FILE SECTION 01 -- a ProgramLayoutIndex-level gap (Phase 1, no
    # REPORT SECTION support) that this analyzer now merges into its own
    # `unresolved` list rather than silently losing it. See
    # test_program_layout_corpus.py, which pins the same gap at the index
    # level.
    "report_test.cbl": ["FD-REPORT-FILE"],
}


class TestBoundaryInventoryCorpus:
    """Build a BoundaryInventory over every shamrice example program."""

    @pytest.mark.parametrize("cbl_path", [pytest.param(p, id=p.name) for p in _ALL_CBL])
    def test_builds_without_raising(self, cbl_path: Path) -> None:
        result = parse_cobol(str(cbl_path))
        assert result.ast is not None, result.errors
        index = ProgramLayoutIndex.build(result.ast)
        report = BoundaryInventoryAnalyzer().analyze(result.ast, index)

        expected = _EXPECTED_UNRESOLVED.get(cbl_path.name, [])
        unexpected = [u for u in report.unresolved if not any(e in u for e in expected)]
        assert (
            unexpected == []
        ), f"{cbl_path.name}: unexpected unresolved entries:\n" + "\n".join(unexpected)

    def test_corpus_is_non_trivial(self) -> None:
        assert len(_ALL_CBL) >= 20

    def test_every_boundary_has_a_category_and_a_key(self) -> None:
        for cbl_path in _ALL_CBL:
            result = parse_cobol(str(cbl_path))
            assert result.ast is not None
            index = ProgramLayoutIndex.build(result.ast)
            report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
            for boundary in report.boundaries:
                assert boundary.ref.category, cbl_path.name
                # OPEN/CLOSE/READ/... always carry a real key; CALL/DYNCALL
                # do too (a CALL with no name is reported in `unresolved`,
                # never given an empty-string key silently).
                if boundary.ref.category not in ("CALL", "DYNCALL"):
                    assert boundary.ref.key, f"{cbl_path.name}: {boundary.ref.category}"
