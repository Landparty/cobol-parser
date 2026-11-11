"""Integration test: ProgramLayoutIndex over the shamrice/COBOL-Examples corpus.

Mirrors test_shamrice_examples.py's corpus-sweep style. Exit criterion (Phase
1 of the program-scoped data-generation plan): the index builds over every
program in the corpus without raising, and every FD resolves to at least one
record or is explicitly reported in ``unresolved`` -- no silent third state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser.generators import ProgramLayoutIndex

pytestmark = pytest.mark.integration

SHAMRICE_DIR = Path(__file__).parent.parent.parent / "examples" / "cobol" / "shamrice"

_ALL_CBL = sorted(SHAMRICE_DIR.glob("*.cbl"))

# report_test.cbl's FD names a Report Writer REPORT SECTION record (RD), not a
# FILE SECTION 01 -- outside this index's scope (no REPORT SECTION support),
# so its FD is expected to land in `unresolved` rather than resolve.
# mouse_example.cbl COPYs GnuCOBOL's screenio, which is not in the corpus: a
# COPY that never reached the layout is named in `unresolved`.
_EXPECTED_UNRESOLVED = {
    "report_test.cbl": ["FD-REPORT-FILE"],
    "mouse_example.cbl": ["COPY screenio was not expanded"],
}


class TestProgramLayoutCorpus:
    """Build a ProgramLayoutIndex over every shamrice example program."""

    @pytest.mark.parametrize("cbl_path", [pytest.param(p, id=p.name) for p in _ALL_CBL])
    def test_builds_without_raising(self, cbl_path: Path) -> None:
        index = ProgramLayoutIndex.from_file(str(cbl_path))
        expected_unresolved_names = _EXPECTED_UNRESOLVED.get(cbl_path.name, [])
        unexpected = [
            u
            for u in index.unresolved
            if not any(name in u for name in expected_unresolved_names)
        ]
        assert (
            unexpected == []
        ), f"{cbl_path.name}: unexpected unresolved entries:\n" + "\n".join(unexpected)
        assert (
            index.ambiguities == {}
        ), f"{cbl_path.name}: unexpected ambiguous names: {index.ambiguities}"

    def test_corpus_is_non_trivial(self) -> None:
        assert len(_ALL_CBL) >= 20
