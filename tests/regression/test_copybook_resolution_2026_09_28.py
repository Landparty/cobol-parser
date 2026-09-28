"""Regression tests: copybook resolution / expansion bug hunt (2026-09-28)."""

from __future__ import annotations

from cobolparser import expand_copybooks
from cobolparser.preprocess.models import CopybookSearchPath
from cobolparser.preprocess.path_resolver import PathResolver, find_copybook_file


class TestIndexedLookupHonoursConfiguredExtensions:
    """The Tier-2 directory index used to key every file by its bare stem, so
    ``COPY MEM`` resolved to ``MEM.bak`` / ``MEM.txt`` / ``ZZ.exe`` -- any
    extension at all, picked by ``os.scandir()`` order -- instead of walking
    ``CopybookSearchPath.extensions`` in order as Tier 3 does."""

    def _dir(self, tmp_path, names):
        d = tmp_path / "copy"
        d.mkdir()
        for n in names:
            (d / n).write_text(f"       01  {n.split('.')[0]}-REC PIC X.\n")
        return d

    def test_unconfigured_extension_never_resolves(self, tmp_path):
        d = self._dir(tmp_path, ["ZZ.exe", "OTHER.cpy.orig", "NOTES.txt"])
        config = CopybookSearchPath(directories=[str(d)], case_sensitive=True)
        resolver = PathResolver(config)
        for member in ("ZZ", "OTHER.cpy", "NOTES"):
            try:
                got = resolver.resolve(member)
            except Exception as exc:  # noqa: BLE001
                assert type(exc).__name__ == "CopybookNotFoundError"
            else:
                raise AssertionError(f"{member} resolved to {got}")

    def test_configured_extension_beats_stray_backup(self, tmp_path):
        # A backup file sitting beside the member must never shadow it,
        # whatever order the directory lists them in.
        d = self._dir(tmp_path, ["MEM.bak", "MEM.cpy", "MEM.old"])
        for case_sensitive in (True, False):
            config = CopybookSearchPath(
                directories=[str(d)], case_sensitive=case_sensitive
            )
            got = PathResolver(config).resolve("MEM")
            assert got == str(d / "MEM.cpy")
            assert got == find_copybook_file("MEM", config)

    def test_extension_order_matches_tier_3(self, tmp_path):
        # .cpy is probed before .cbl: the program source must not win.
        d = self._dir(tmp_path, ["SUB.cbl", "SUB.cpy"])
        config = CopybookSearchPath(directories=[str(d)], case_sensitive=True)
        assert PathResolver(config).resolve("SUB") == str(d / "SUB.cpy")
        assert find_copybook_file("SUB", config) == str(d / "SUB.cpy")

    def test_first_directory_still_wins_across_extensions(self, tmp_path):
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()
        (first / "SHARED.cbl").write_text("       01  A PIC X.\n")
        (second / "SHARED.cpy").write_text("       01  B PIC X.\n")
        config = CopybookSearchPath(
            directories=[str(first), str(second)], case_sensitive=True
        )
        # SYSLIB concatenation order: the first directory holding the
        # member wins, as in Tier 3.
        assert PathResolver(config).resolve("SHARED") == str(first / "SHARED.cbl")
        assert find_copybook_file("SHARED", config) == str(first / "SHARED.cbl")

    def test_expansion_uses_the_real_member(self, tmp_path):
        d = tmp_path / "copy"
        d.mkdir()
        (d / "MEM.bak").write_text("       01  STALE-REC PIC X.\n")
        (d / "MEM.cpy").write_text("       01  LIVE-REC PIC X.\n")
        out = expand_copybooks("       COPY MEM.\n", copybook_paths=[str(d)])
        assert "LIVE-REC" in out.expanded_source
        assert "STALE-REC" not in out.expanded_source
