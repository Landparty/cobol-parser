"""Integration test: ConstantFolder over the shamrice corpus.

Exit criterion (Phase 7 tier 2, per the parent plan): no generated
`field_equals` expectation can be wrong. Over a real corpus that means: the
walk never raises, and every value it reports is layout-valid for its
field's PICTURE -- an exact-fit-or-poison violation would show up here as a
value that fails to parse as a number (for a numeric field) or wildly
exceeds its declared size (for a text field).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.const_fold import ConstantFolder
from cobolparser.generators import ProgramLayoutIndex
from cobolparser.layout.fields import FieldCategory

pytestmark = pytest.mark.integration

SHAMRICE_DIR = Path(__file__).parent.parent.parent / "examples" / "cobol" / "shamrice"

_ALL_CBL = sorted(SHAMRICE_DIR.glob("*.cbl"))
_EXTRA_SAMPLES = [
    Path(__file__).parent.parent / "samples" / "file_operations.cbl",
    Path(__file__).parent.parent / "samples" / "enterprise" / "COMPDIR.cbl",
]


def _fold(cbl_path: Path):
    source = cbl_path.read_text(encoding="utf-8", errors="replace")
    result = parse_cobol(source, filename=str(cbl_path))
    assert result.ast is not None, result.errors
    index = ProgramLayoutIndex.build(result.ast)
    return index, ConstantFolder().fold(result.ast, index)


class TestConstFoldCorpus:
    @pytest.mark.parametrize("cbl_path", [pytest.param(p, id=p.name) for p in _ALL_CBL])
    def test_folds_without_raising(self, cbl_path: Path) -> None:
        _fold(cbl_path)

    @pytest.mark.parametrize("cbl_path", [pytest.param(p, id=p.name) for p in _ALL_CBL])
    def test_every_known_value_is_layout_valid(self, cbl_path: Path) -> None:
        index, result = _fold(cbl_path)
        for qualified_name, value in result.known.items():
            resolved = index.resolve(qualified_name)
            assert resolved is not None, (
                f"{cbl_path.name}: {qualified_name} reported as known but no "
                "longer resolves"
            )
            spec = resolved.spec
            if spec.category is FieldCategory.NUMERIC:
                float(value)  # must parse as a number -- raises if it doesn't
            else:
                assert len(value) <= max(spec.size, 1), (
                    f"{cbl_path.name}: {qualified_name}={value!r} exceeds "
                    f"field size {spec.size}"
                )

    def test_corpus_is_non_trivial(self) -> None:
        assert len(_ALL_CBL) >= 20

    def test_at_least_one_program_yields_a_known_value(self) -> None:
        # The shamrice programs used to contribute here (`sub.cbl`,
        # `unstring.cbl`), but only through the end-of-walk reading #246
        # fixed: each displays its field at several sites with different
        # values, so no single `field_equals` is right for it. The
        # non-triviality check therefore also covers the repo's own
        # samples, where a field is shown with one value.
        paths = [*_ALL_CBL, *_EXTRA_SAMPLES]
        totals = [len(result.known) for _, result in (_fold(p) for p in paths)]
        assert sum(totals) > 0
