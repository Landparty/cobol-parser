"""The OKF staleness map must cover every source file.

``scripts/okf_staleness_check.py`` is what makes the pre-commit hook ask for
an OKF update when source changes.  A file missing from its ``OKF_MAP`` is
not a lint nit: it is a file whose documentation can silently rot, because
nothing will ever prompt for it.  That is exactly how ``cobolparser/jcl/``
(a 1,900-line JCL front end) and ``cobolparser/parser.py`` (the parse
orchestrator, missed because the map's ``cobolparser/parsers/`` prefix ends
in a slash) both went unmapped.

These tests fail the moment a new module or package lands without a home in
the map, and the moment the map names an OKF file that does not exist.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from okf_staleness_check import OKF_MAP, _get_okf_files  # noqa: E402


def _tracked_source_files() -> list[str]:
    """Every tracked .py file under ``cobolparser/``."""
    out = subprocess.run(
        ["git", "ls-files", "cobolparser"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [f for f in out if f.endswith(".py")]


class TestOkfMapCoverage:
    def test_every_source_file_maps_to_an_okf_doc(self):
        """No source file may be invisible to the staleness check."""
        tracked = _tracked_source_files()
        assert tracked, "expected to find tracked cobolparser sources"

        unmapped = sorted(f for f in tracked if not _get_okf_files(f))
        assert not unmapped, (
            "these source files map to no OKF doc, so changing them will "
            "never prompt an OKF update: " + ", ".join(unmapped)
        )

    @pytest.mark.parametrize("prefix,okf_files", OKF_MAP)
    def test_mapped_okf_files_exist(self, prefix, okf_files):
        """A map entry pointing at a missing doc silently covers nothing."""
        for okf_file in okf_files:
            assert (
                REPO_ROOT / okf_file
            ).is_file(), f"OKF_MAP maps {prefix!r} to {okf_file}, which does not exist"

    def test_directory_prefixes_end_with_a_slash(self):
        """``cobolparser/parsers`` would also match ``cobolparser/parser.py``.

        The slash is what keeps a package prefix from swallowing a same-named
        module beside it; requiring it here is cheaper than rediscovering the
        overlap from a wrong staleness prompt.
        """
        for prefix, _ in OKF_MAP:
            if (REPO_ROOT / prefix).is_dir():
                assert prefix.endswith(
                    "/"
                ), f"{prefix!r} is a directory and must end with '/'"
