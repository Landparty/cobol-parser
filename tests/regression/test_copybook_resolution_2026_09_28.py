"""Regression tests: copybook resolution / expansion bug hunt (2026-09-28)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from cobolparser import expand_copybooks
from cobolparser.batch import parse_files_with_copybooks
from cobolparser.cli.parse import main
from cobolparser.parser import parse_cobol_with_expansion
from cobolparser.preprocess import CopybookNotFoundError
from cobolparser.preprocess.copybook_expander import (
    detect_encoding,
    read_file_with_encoding,
)
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


class TestEightBitCopybookEncoding:
    """A cp1252 / latin-1 copybook (not valid UTF-8, ASCII-shaped) used to be
    detected as ``'ascii'``, so every accented character decoded to U+FFFD
    with a lossy-decode warning -- and failed outright under strict mode."""

    TEXT = "       01  CLIENT-NOM  PIC X(30) VALUE 'CAFÉ QUÉBEC €5'.\n"

    def test_cp1252_detected_and_decoded(self, tmp_path):
        cpy = tmp_path / "LAT.cpy"
        cpy.write_bytes(self.TEXT.encode("cp1252"))
        assert detect_encoding(str(cpy)) == "cp1252"
        assert read_file_with_encoding(str(cpy)) == self.TEXT

    def test_latin1_bytes_cp1252_leaves_undefined(self, tmp_path):
        # 0x81 is undefined in cp1252; latin-1 maps every byte.
        cpy = tmp_path / "RAW.cpy"
        cpy.write_bytes(b"       01  A PIC X VALUE '\x81\xe9'.\n")
        assert detect_encoding(str(cpy)) == "latin-1"
        assert "\xe9" in read_file_with_encoding(str(cpy))

    def test_expansion_keeps_accents_without_warning(self, tmp_path):
        (tmp_path / "LAT.cpy").write_bytes(self.TEXT.encode("cp1252"))
        out = expand_copybooks(
            "       COPY LAT.\n",
            copybook_paths=[str(tmp_path)],
            encoding_errors="strict",
        )
        assert "CAFÉ QUÉBEC €5" in out.expanded_source
        assert not any("Lossy" in w for w in out.statistics.warnings)

    def test_plain_ascii_and_utf8_unchanged(self, tmp_path):
        a = tmp_path / "A.cpy"
        a.write_bytes(b"       01  A PIC X.\n")
        assert detect_encoding(str(a)) in ("utf-8", "ascii")
        u = tmp_path / "U.cpy"
        u.write_bytes(self.TEXT.encode("utf-8"))
        assert detect_encoding(str(u)) == "utf-8"


_DBG_MEMBER = (
    "       >>IF DBG DEFINED\n"
    "       01  DBG-REC PIC X.\n"
    "       >>ELSE\n"
    "       01  NODBG-REC PIC X.\n"
    "       >>END-IF\n"
)
_HEADER = (
    "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n"
    "       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
)


def _records(text: str) -> list[str]:
    """The DBG-REC / NODBG-REC entries present in *text*, in line order."""
    found = []
    for line in text.split("\n"):
        words = line.split()
        found += [w for w in words if w in ("DBG-REC", "NODBG-REC")]
    return found


class TestDefinedSymbolsReachCopybooks:
    """A ``>>DEFINE`` in the program was invisible inside the copybooks it
    COPYs afterwards (the expander handed every member only the caller's
    initial symbols), and ``parse --define X --copybook-path`` / ``expand
    --define X`` pre-processed the program before expansion, so neither the
    program's own ``>>DEFINE`` lines nor (for ``parse``) ``--define`` itself
    reached a member's ``>>IF``."""

    def test_program_define_is_in_effect_in_member(self, tmp_path):
        (tmp_path / "MEM.cpy").write_text(_DBG_MEMBER)
        src = "       >>DEFINE DBG\n" + _HEADER + "       COPY MEM.\n"
        out = expand_copybooks(
            src, copybook_paths=[str(tmp_path)], process_conditionals=True
        )
        assert _records(out.expanded_source) == ["DBG-REC"]

    def test_define_is_positional_and_not_served_from_cache(self, tmp_path):
        # The same member before, after, and after undefining takes the
        # matching branch each time: the symbols in effect are part of the
        # expansion-cache key.
        (tmp_path / "MEM.cpy").write_text(_DBG_MEMBER)
        src = (
            _HEADER
            + "       COPY MEM.\n"
            + "       >>DEFINE DBG\n"
            + "       COPY MEM.\n"
            + "       >>DEFINE DBG OFF\n"
            + "       COPY MEM.\n"
        )
        out = expand_copybooks(
            src, copybook_paths=[str(tmp_path)], process_conditionals=True
        )
        assert _records(out.expanded_source) == ["NODBG-REC", "DBG-REC", "NODBG-REC"]

    def test_member_define_reaches_its_nested_copy(self, tmp_path):
        (tmp_path / "MEM.cpy").write_text(_DBG_MEMBER)
        (tmp_path / "OUTER.cpy").write_text("       >>DEFINE DBG\n       COPY MEM.\n")
        out = expand_copybooks(
            _HEADER + "       COPY OUTER.\n",
            copybook_paths=[str(tmp_path)],
            process_conditionals=True,
        )
        assert _records(out.expanded_source) == ["DBG-REC"]

    def test_caller_symbols_still_apply(self, tmp_path):
        (tmp_path / "MEM.cpy").write_text(_DBG_MEMBER)
        out = expand_copybooks(
            _HEADER + "       COPY MEM.\n",
            copybook_paths=[str(tmp_path)],
            process_conditionals=True,
            defined_symbols={"DBG": "TRUE"},
        )
        assert _records(out.expanded_source) == ["DBG-REC"]

    def _run_cli(self, capsys, *argv):
        with patch("sys.argv", ["cobol-parser", "--no-config", *argv]):
            try:
                main()
            except SystemExit as exc:
                assert not exc.code
        return capsys.readouterr().out

    def test_cli_parse_define_reaches_member(self, tmp_path, capsys):
        (tmp_path / "MEM.cpy").write_text(_DBG_MEMBER)
        prog = tmp_path / "P.cbl"
        prog.write_text(
            _HEADER
            + "       COPY MEM.\n       PROCEDURE DIVISION.\n           STOP RUN.\n"
        )
        out = self._run_cli(
            capsys,
            "parse",
            str(prog),
            "--copybook-path",
            str(tmp_path),
            "--define",
            "DBG",
            "--compact",
        )
        assert '"DBG-REC"' in out
        assert '"NODBG-REC"' not in out

    def test_cli_expand_program_define_reaches_member(self, tmp_path, capsys):
        (tmp_path / "MEM.cpy").write_text(_DBG_MEMBER)
        prog = tmp_path / "P.cbl"
        prog.write_text("       >>DEFINE DBG\n" + _HEADER + "       COPY MEM.\n")
        out = self._run_cli(
            capsys,
            "expand",
            str(prog),
            "--copybook-path",
            str(tmp_path),
            "--define",
            "OTHER",
            "--compact",
        )
        assert _records(json.loads(out)["expanded_source"]) == ["DBG-REC"]


_GUARDED_COPY = (
    _HEADER
    + "       >>IF CICS DEFINED\n"
    + "       COPY DFHAID.\n"
    + "       >>END-IF\n"
    + "       COPY MEM.\n"
    + "       PROCEDURE DIVISION.\n"
    + "           STOP RUN.\n"
)


class TestCopyInExcludedConditionalBlock:
    """A COPY inside an excluded ``>>IF`` block was resolved anyway: the
    expander ran before the parser's directive pass, so a member that exists
    only for the other branch (``COPY DFHAID`` under ``>>IF CICS DEFINED``)
    failed the whole parse with CopybookNotFoundError."""

    def test_parse_cobol_with_expansion_skips_excluded_copy(self, tmp_path):
        (tmp_path / "MEM.cpy").write_text(_DBG_MEMBER)
        result = parse_cobol_with_expansion(
            _GUARDED_COPY, "P.cbl", copybook_paths=[str(tmp_path)]
        )
        assert result.ast is not None
        assert not result.errors
        assert "NODBG-REC" in result.ast.to_json()

    def test_batch_expands_instead_of_falling_back(self, tmp_path):
        (tmp_path / "MEM.cpy").write_text(_DBG_MEMBER)
        prog = tmp_path / "P.cbl"
        prog.write_text(_GUARDED_COPY)
        [res] = parse_files_with_copybooks([prog], copybook_paths=[str(tmp_path)])
        assert res.result is not None
        # The member was really expanded (the old fallback parsed the raw,
        # unexpanded source after DFHAID failed to resolve).
        assert "NODBG-REC" in res.result.ast.to_json()

    def test_cli_parse_with_copybook_path(self, tmp_path, capsys):
        (tmp_path / "MEM.cpy").write_text(_DBG_MEMBER)
        prog = tmp_path / "P.cbl"
        prog.write_text(_GUARDED_COPY)
        argv = ["parse", str(prog), "--copybook-path", str(tmp_path), "--compact"]
        with patch("sys.argv", ["cobol-parser", "--no-config", *argv]):
            try:
                main()
            except SystemExit as exc:
                assert not exc.code
        assert '"NODBG-REC"' in capsys.readouterr().out

    def test_defined_symbol_still_selects_the_copy(self, tmp_path):
        (tmp_path / "MEM.cpy").write_text(_DBG_MEMBER)
        with pytest.raises(CopybookNotFoundError, match="DFHAID"):
            parse_cobol_with_expansion(
                _GUARDED_COPY,
                "P.cbl",
                copybook_paths=[str(tmp_path)],
                defined_symbols={"CICS": "TRUE"},
            )
