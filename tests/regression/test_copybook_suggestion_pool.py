"""Regression test for docs/2026-09-15-copybook-discovery-defaults-design.md
(tracked in the sibling mocky-mock repo): `suggest_similar_copybooks`'s
did-you-mean pool used to include every file in the search directory --
`.cbl`/`.cob` program sources included, via `CopybookSearchPath`'s own
`extensions` default (which has a trailing `""` meaning "any extension,"
correct for resolution but wrong for a typo suggestion). A missing
copybook next to the program's own `.cbl` file suggested that `.cbl`
file back to the user."""

import tempfile
from pathlib import Path

from cobolparser.preprocess.models import CopybookSearchPath
from cobolparser.preprocess.path_resolver import (
    get_available_copybooks,
    suggest_similar_copybooks,
)


def test_suggestion_pool_never_includes_the_programs_own_cbl_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Only the program's own source file lives here -- no real
        # copybook at all. This is the exact real-world-example shape
        # (ACCTMNT.cbl referencing a missing ACCTMAST copybook).
        (Path(tmpdir) / "ACCTMNT.cbl").write_text("       IDENTIFICATION DIVISION.\n")

        config = CopybookSearchPath(directories=[tmpdir])
        assert suggest_similar_copybooks("ACCTMAST", config) == []


def test_suggestion_pool_still_finds_a_real_near_miss():
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "ACCTMAST.cpy").write_text("01 ACCT-REC.\n")
        (Path(tmpdir) / "ACCTMNT.cbl").write_text("       IDENTIFICATION DIVISION.\n")

        config = CopybookSearchPath(directories=[tmpdir])
        suggestions = suggest_similar_copybooks("ACCTMSTR", config)
        assert suggestions == ["ACCTMAST"]


def test_suggestion_extensions_parameter_restores_old_broad_pool():
    """An explicit override is still available for a caller that wants
    the old (resolution-shaped) breadth."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "ACCTMNT.cbl").write_text("       IDENTIFICATION DIVISION.\n")

        config = CopybookSearchPath(directories=[tmpdir])
        suggestions = suggest_similar_copybooks(
            "ACCTMAST", config, suggestion_extensions=config.extensions
        )
        assert suggestions == ["ACCTMNT"]


def test_get_available_copybooks_resolution_pool_is_unaffected():
    """suggest_similar_copybooks's narrower pool must not change what
    get_available_copybooks reports when called directly with the
    search config's own (unmodified) extensions -- only the suggestion
    function's internal candidate pool is narrowed, never the config
    object it was given."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "ACCTMNT.cbl").write_text("       IDENTIFICATION DIVISION.\n")

        config = CopybookSearchPath(directories=[tmpdir])
        suggest_similar_copybooks("ACCTMAST", config)  # must not mutate config
        assert "ACCTMNT" in get_available_copybooks(config)
