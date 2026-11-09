"""Integration test: compute_program_data_items over real fixtures.

Confirms the offset walk produces a correct top-level REDEFINES chain for
the existing REDEFINES/level-88 fixture, and separately sweeps the
shamrice corpus (same corpus test_program_layout_corpus.py uses) purely
for "doesn't crash" coverage -- that corpus wasn't authored with
REDEFINES-chain assertions in mind, so this test only checks it completes
without an exception, not exact offsets.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.layout.offsets import compute_program_data_items

pytestmark = pytest.mark.integration

SHAMRICE_DIR = Path(__file__).parent.parent.parent / "examples" / "cobol" / "shamrice"
_ALL_CBL = sorted(SHAMRICE_DIR.glob("*.cbl"))


class TestRedefinesFixture:
    def test_redefines_test_cbl_resolves_top_level_redefines_fan_out(self):
        result = parse_cobol(
            "tests/samples/redefines_test.cbl",
            error_recovery=ErrorRecoveryMode.FAIL_FAST,
        )
        assert result.ast is not None, result.errors
        output = compute_program_data_items(result.ast)
        by_name = {item["name"]: item for item in output["items"]}

        # WS-REDEF-1 and WS-REDEF-2 both independently redefine
        # WS-BASE-AREA directly (a fan-out, not a chain) -- see the fixture:
        #   01  WS-BASE-AREA  PIC X(10).
        #   01  WS-REDEF-1    REDEFINES WS-BASE-AREA PIC 9(10).
        #   01  WS-REDEF-2    REDEFINES WS-BASE-AREA.
        #       05  WS-REDEF-2-PART1  PIC X(5).
        #       05  WS-REDEF-2-PART2  PIC X(5).
        assert by_name["WS-REDEF-1"]["redefines_chain"] == ["WS-BASE-AREA"]
        assert by_name["WS-REDEF-2"]["redefines_chain"] == ["WS-BASE-AREA"]

        # All three are independently record-relative -- each top-level
        # 01-item starts its own record at byte 0.
        assert by_name["WS-BASE-AREA"]["byte_offset"] == 0
        assert by_name["WS-REDEF-1"]["byte_offset"] == 0
        assert by_name["WS-REDEF-2"]["byte_offset"] == 0


class TestShamriceCorpusDoesNotRaise:
    @pytest.mark.parametrize("cbl_path", [pytest.param(p, id=p.name) for p in _ALL_CBL])
    def test_computes_without_raising(self, cbl_path: Path) -> None:
        result = parse_cobol(
            str(cbl_path), error_recovery=ErrorRecoveryMode.COLLECT_ALL
        )
        if result.ast is None:
            pytest.skip(f"{cbl_path.name} did not produce an AST")
        compute_program_data_items(result.ast)  # must not raise

    def test_corpus_is_non_trivial(self) -> None:
        assert len(_ALL_CBL) >= 20
