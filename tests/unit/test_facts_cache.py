"""The on-disk facts cache (``cobolparser._facts_cache``) and ``scan``'s use
of it (``ScanOptions.cache_dir`` / ``scan --cache-dir``).

A cached answer is only correct while nothing that went into it changed, so
most of these tests change one input -- the program, a copybook, a copybook
directory, an option -- and check the next run recomputes.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from cobolparser._facts_cache import FactsCache, directory_stamps, stamp
from cobolparser.scan import ScanOptions, scan_files, scan_one

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COPYUSER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC.
           COPY TESTCPY.
       PROCEDURE DIVISION.
       ONLY-PARA.
           MOVE 1 TO WS-REC
           DISPLAY "DONE"
           STOP RUN.
"""

COPYBOOK = """\
       05 CPY-FIELD-A PIC X(10).
       05 CPY-FIELD-B PIC 9(5).
"""


def _touch(path: Path) -> None:
    """Move *path*'s mtime well clear of its old one (filesystems with coarse
    timestamps would otherwise see no change)."""
    info = path.stat()
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 5_000_000_000))


def _layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    books = tmp_path / "books"
    books.mkdir()
    (books / "TESTCPY.cpy").write_text(COPYBOOK)
    program = tmp_path / "COPYUSER.cbl"
    program.write_text(PROGRAM)
    return program, books, tmp_path / "cache"


def _options(books: Path, cache: Path, **kw: object) -> ScanOptions:
    return ScanOptions(
        analyzers=("unused-variables",),
        copybook_paths=(str(books),),
        cache_dir=str(cache),
        **kw,  # type: ignore[arg-type]
    )


class TestFactsCache:
    def test_round_trip_and_counts(self, tmp_path: Path) -> None:
        source = tmp_path / "a.cbl"
        source.write_text("x")
        cache = FactsCache(tmp_path / "c", "ns", ("s",))
        assert cache.get(str(source)) is None
        cache.put(str(source), {"k": [1, 2]}, {str(source): stamp(str(source))})
        assert cache.get(str(source)) == {"k": [1, 2]}
        assert (cache.hits, cache.misses) == (1, 1)

    def test_changed_stamp_is_a_miss(self, tmp_path: Path) -> None:
        source = tmp_path / "a.cbl"
        source.write_text("x")
        cache = FactsCache(tmp_path / "c", "ns", ())
        cache.put(str(source), 1, {str(source): stamp(str(source))})
        _touch(source)
        assert cache.get(str(source)) is None

    def test_missing_file_stamp_holds_until_it_appears(self, tmp_path: Path) -> None:
        source = tmp_path / "a.cbl"
        source.write_text("x")
        absent = tmp_path / "LATER.cpy"
        cache = FactsCache(tmp_path / "c", "ns", ())
        cache.put(str(source), 1, {str(absent): stamp(str(absent))})
        assert cache.get(str(source)) == 1
        absent.write_text("now here")
        assert cache.get(str(source)) is None

    def test_settings_and_namespace_separate_entries(self, tmp_path: Path) -> None:
        source = tmp_path / "a.cbl"
        source.write_text("x")
        FactsCache(tmp_path / "c", "ns", ("one",)).put(str(source), 1, {})
        assert FactsCache(tmp_path / "c", "ns", ("two",)).get(str(source)) is None
        assert FactsCache(tmp_path / "c", "other", ("one",)).get(str(source)) is None
        assert FactsCache(tmp_path / "c", "ns", ("one",)).get(str(source)) == 1

    def test_corrupt_entry_is_a_miss(self, tmp_path: Path) -> None:
        source = tmp_path / "a.cbl"
        source.write_text("x")
        cache = FactsCache(tmp_path / "c", "ns", ())
        cache.put(str(source), 1, {})
        (entry,) = (tmp_path / "c" / "ns").rglob("*.json")
        entry.write_text("{not json")
        assert cache.get(str(source)) is None
        entry.write_text(json.dumps({"facts": 1}))  # no stamps
        assert cache.get(str(source)) is None

    @pytest.mark.skipif(
        sys.platform == "win32" or os.geteuid() == 0,
        reason="needs a directory the user cannot write",
    )
    def test_unwritable_directory_is_ignored(self, tmp_path: Path) -> None:
        locked = tmp_path / "locked"
        locked.mkdir()
        locked.chmod(0o500)
        try:
            cache = FactsCache(locked, "ns", ())
            cache.put("a.cbl", 1, {})  # does not raise
            assert cache.get("a.cbl") is None
        finally:
            locked.chmod(0o700)

    def test_directory_stamps_cover_direct_subdirectories(self, tmp_path: Path) -> None:
        (tmp_path / "LIB").mkdir()
        (tmp_path / "LIB" / "deeper").mkdir()
        stamps = directory_stamps([str(tmp_path), str(tmp_path / "gone")])
        assert set(stamps) == {
            str(tmp_path),
            str(tmp_path / "LIB"),
            str(tmp_path / "gone"),
        }
        assert stamps[str(tmp_path / "gone")] is None


class TestScanCache:
    def test_second_scan_is_served_from_the_cache(self, tmp_path: Path) -> None:
        program, books, cache = _layout(tmp_path)
        first = scan_one(str(program), _options(books, cache))
        second = scan_one(str(program), _options(books, cache))
        assert not first.from_cache and second.from_cache
        assert second.to_dict() == first.to_dict()
        assert second.path == str(program)

    def test_report_summary_counts_cached_files(self, tmp_path: Path) -> None:
        program, books, cache = _layout(tmp_path)
        options = _options(books, cache)
        assert (
            scan_files([str(program)], options, workers=1).to_dict()["summary"][
                "cached_file_count"
            ]
            == 0
        )
        again = scan_files([str(program)], options, workers=1).to_dict()
        assert again["summary"]["cached_file_count"] == 1

    def test_no_cache_dir_no_summary_key(self, tmp_path: Path) -> None:
        program, books, _ = _layout(tmp_path)
        report = scan_files(
            [str(program)], ScanOptions(copybook_paths=(str(books),)), workers=1
        )
        assert "cached_file_count" not in report.to_dict()["summary"]

    def test_edited_program_is_rescanned(self, tmp_path: Path) -> None:
        program, books, cache = _layout(tmp_path)
        scan_one(str(program), _options(books, cache))
        program.write_text(PROGRAM.replace('"DONE"', '"FINISHED"'))
        _touch(program)
        assert not scan_one(str(program), _options(books, cache)).from_cache

    def test_edited_copybook_is_rescanned(self, tmp_path: Path) -> None:
        program, books, cache = _layout(tmp_path)
        before = scan_one(str(program), _options(books, cache))
        member = books / "TESTCPY.cpy"
        member.write_text(COPYBOOK + "       05 CPY-FIELD-C PIC X.\n")
        _touch(member)
        after = scan_one(str(program), _options(books, cache))
        assert not after.from_cache
        assert after.to_dict() != before.to_dict()

    def test_new_member_in_a_copybook_directory_is_rescanned(
        self, tmp_path: Path
    ) -> None:
        # A member added earlier on the search path would shadow the one
        # used, though no file the parse read changed.
        program, books, cache = _layout(tmp_path)
        scan_one(str(program), _options(books, cache))
        (books / "OTHER.cpy").write_text(COPYBOOK)
        _touch(books)
        assert not scan_one(str(program), _options(books, cache)).from_cache

    def test_different_options_do_not_share_entries(self, tmp_path: Path) -> None:
        program, books, cache = _layout(tmp_path)
        scan_one(str(program), _options(books, cache))
        other = scan_one(
            str(program), _options(books, cache, defined_symbols=(("DBG", ""),))
        )
        assert not other.from_cache

    def test_failed_file_is_not_cached(self, tmp_path: Path) -> None:
        missing = str(tmp_path / "NOPE.cbl")
        options = ScanOptions(cache_dir=str(tmp_path / "cache"))
        assert scan_one(missing, options).error
        assert not (tmp_path / "cache").exists() or not list(
            (tmp_path / "cache").rglob("*.json")
        )

    def test_cli_flag(self, tmp_path: Path, monkeypatch, capsys) -> None:
        from cobolparser.cli.parse import main

        program, books, cache = _layout(tmp_path)
        out = tmp_path / "out.json"
        argv = [
            "cobol-parser",
            "--no-config",
            "scan",
            str(program),
            "--copybook-path",
            str(books),
            "--cache-dir",
            str(cache),
            "--workers",
            "1",
            "-o",
            str(out),
        ]
        for expected in (0, 1):
            monkeypatch.setattr(sys, "argv", argv)
            try:
                main()
            except SystemExit as exc:
                assert not exc.code
            summary = json.loads(out.read_text())["summary"]
            assert summary["cached_file_count"] == expected
