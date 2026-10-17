"""Tests for the multi-file analyzer scan (scan.py).

Covers the three properties the module's docstring promises its callers:

- Fault isolation per file: an unreadable or unparseable file costs its own
  entry and nothing else, and the summary's counts still add up.
- Every program unit is reported, contained programs included -- the case a
  portfolio view would otherwise present as a clean file.
- Nothing is silently omitted: an analyzer that raises is named against the
  unit it raised on, with that unit's other reports intact.

Plus the cross-file clone grouping built on top of the scan, which is the
whole reason paragraph fingerprints are reported at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser.scan import (
    ANALYZERS,
    DEFAULT_ANALYZERS,
    SCAN_VERSION,
    CrossFileCloneGroup,
    ScanOptions,
    cross_file_clone_groups,
    parse_analyzer_list,
    scan_files,
    scan_one,
)

SAMPLES = Path(__file__).parents[1] / "samples"


def _program(name: str, paragraph: str, body: str) -> str:
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. {name}.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9 VALUE 0.
       01 WS-B PIC 9 VALUE 0.
       01 WS-C PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       {paragraph}.
{body}
"""


_BODY = """\
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY "DONE"
           STOP RUN.
"""


def _write(tmp_path: Path, filename: str, source: str) -> str:
    path = tmp_path / filename
    path.write_text(source)
    return str(path)


class TestScanOne:
    def test_reports_every_requested_analyzer(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA", _BODY))
        scan = scan_one(path, ScanOptions())
        assert scan.error is None
        assert len(scan.units) == 1
        assert set(scan.units[0].reports) == set(DEFAULT_ANALYZERS)

    def test_unreadable_file_is_a_failure_not_a_crash(self, tmp_path: Path) -> None:
        scan = scan_one(str(tmp_path / "nope.cbl"), ScanOptions())
        assert scan.units == []
        assert scan.error is not None
        assert "could not read" in scan.error

    def test_contained_programs_are_each_reported(self, tmp_path: Path) -> None:
        """A file with two PROGRAM-IDs must not report only the outer one:
        the contained program would read as clean because nothing looked."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTER.
       PROCEDURE DIVISION.
       OUTER-PARA.
           DISPLAY "OUTER"
           STOP RUN.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER.
       PROCEDURE DIVISION.
       INNER-PARA.
           DISPLAY "INNER"
           STOP RUN.
       END PROGRAM INNER.
       END PROGRAM OUTER.
"""
        scan = scan_one(_write(tmp_path, "NEST.cbl", source), ScanOptions())
        assert scan.error is None
        names = [u.program_name for u in scan.units]
        assert "OUTER" in names
        assert "INNER" in names

    def test_contained_unit_carries_a_deeper_depth(self, tmp_path: Path) -> None:
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTER.
       PROCEDURE DIVISION.
       OUTER-PARA.
           DISPLAY "OUTER"
           STOP RUN.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER.
       PROCEDURE DIVISION.
       INNER-PARA.
           DISPLAY "INNER"
           STOP RUN.
       END PROGRAM INNER.
       END PROGRAM OUTER.
"""
        scan = scan_one(_write(tmp_path, "NEST.cbl", source), ScanOptions())
        by_name = {u.program_name: u.depth for u in scan.units}
        assert by_name["OUTER"] == 0
        assert by_name["INNER"] > 0

    def test_a_failing_analyzer_costs_only_its_own_report(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        import cobolparser.scan as scan_module

        real = scan_module._run_analyzer

        def explode(name, unit, options, source_map=None):
            if name == "health":
                raise RuntimeError("boom")
            return real(name, unit, options, source_map)

        monkeypatch.setattr(scan_module, "_run_analyzer", explode)

        path = _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA", _BODY))
        scan = scan_one(path, ScanOptions())
        unit = scan.units[0]
        assert "health" not in unit.reports
        assert "redundancy" in unit.reports
        assert "boom" in unit.failed_analyzers["health"]

    def test_failed_analyzers_are_serialized(self, tmp_path: Path, monkeypatch) -> None:
        import cobolparser.scan as scan_module

        monkeypatch.setattr(
            scan_module,
            "_run_analyzer",
            lambda name, unit, options: (_ for _ in ()).throw(RuntimeError("nope")),
        )
        path = _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA", _BODY))
        unit = scan_one(path, ScanOptions()).units[0].to_dict()
        assert "failed_analyzers" in unit
        assert unit["reports"] == {}

    def test_clean_unit_omits_the_failed_analyzers_key(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA", _BODY))
        unit = scan_one(path, ScanOptions()).units[0].to_dict()
        assert "failed_analyzers" not in unit


class TestScanFiles:
    def test_empty_input_is_an_empty_report(self) -> None:
        report = scan_files([], ScanOptions(), workers=1)
        assert report.to_dict()["summary"]["file_count"] == 0

    def test_counts_account_for_every_file(self, tmp_path: Path) -> None:
        """file_count == scanned + failed. The identity a consumer relies on
        to prove nothing went missing."""
        good = _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA", _BODY))
        missing = str(tmp_path / "gone.cbl")
        summary = scan_files([good, missing], ScanOptions(), workers=1).to_dict()[
            "summary"
        ]
        assert summary["file_count"] == 2
        assert summary["scanned_file_count"] == 1
        assert summary["failed_file_count"] == 1
        assert (
            summary["scanned_file_count"] + summary["failed_file_count"]
            == summary["file_count"]
        )

    def test_one_bad_file_does_not_stop_the_others(self, tmp_path: Path) -> None:
        paths = [
            str(tmp_path / "gone.cbl"),
            _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA", _BODY)),
            _write(tmp_path, "B.cbl", _program("PROGB", "ONLY-PARA", _BODY)),
        ]
        report = scan_files(paths, ScanOptions(), workers=1)
        assert len(report.ok_files) == 2
        assert len(report.failed_files) == 1

    def test_output_is_in_input_order(self, tmp_path: Path) -> None:
        paths = [
            _write(tmp_path, f"P{i}.cbl", _program(f"PROG{i}", "ONLY-PARA", _BODY))
            for i in range(4)
        ]
        report = scan_files(list(reversed(paths)), ScanOptions(), workers=1)
        assert [f.path for f in report.files] == list(reversed(paths))

    def test_unknown_analyzer_is_rejected(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA", _BODY))
        with pytest.raises(ValueError, match="unknown analyzer"):
            scan_files([path], ScanOptions(analyzers=("nope",)), workers=1)

    def test_zero_workers_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="workers must be"):
            scan_files([], ScanOptions(), workers=0)

    def test_parallel_and_sequential_agree(self, tmp_path: Path) -> None:
        """The pool path exists only to go faster. A difference in what it
        produces would be a bug nobody notices until a scan is big enough to
        take it."""
        paths = [
            _write(tmp_path, f"P{i}.cbl", _program(f"PROG{i}", "ONLY-PARA", _BODY))
            for i in range(6)
        ]
        sequential = scan_files(paths, ScanOptions(), workers=1).to_dict()
        parallel = scan_files(paths, ScanOptions(), workers=2).to_dict()
        assert sequential == parallel

    def test_scan_version_is_reported(self, tmp_path: Path) -> None:
        report = scan_files([], ScanOptions(), workers=1).to_dict()
        assert report["scan_version"] == SCAN_VERSION

    def test_real_samples_scan_without_failures(self) -> None:
        paths = sorted(str(p) for p in SAMPLES.glob("*.cbl"))[:10]
        report = scan_files(paths, ScanOptions(), workers=1)
        assert report.failed_files == []
        assert all(u.reports for f in report.ok_files for u in f.units)


class TestCrossFileCloneGroups:
    def test_identical_paragraphs_in_two_files_are_one_group(
        self, tmp_path: Path
    ) -> None:
        """Neither file duplicates anything internally, so neither program's
        own clone_groups is non-empty -- this is the finding that only exists
        once several programs are looked at together."""
        paths = [
            _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA", _BODY)),
            _write(tmp_path, "B.cbl", _program("PROGB", "OTHER-NAME", _BODY)),
        ]
        report = scan_files(paths, ScanOptions(), workers=1)
        for file_scan in report.ok_files:
            assert file_scan.units[0].reports["redundancy"]["clone_groups"] == []

        groups = cross_file_clone_groups(report)
        assert len(groups) == 1
        assert groups[0].clone_type == "TYPE_1"
        assert groups[0].file_count == 2
        assert {m.program_name for m in groups[0].members} == {"PROGA", "PROGB"}

    def test_renamed_identifiers_group_as_type2(self, tmp_path: Path) -> None:
        renamed = _BODY.replace("WS-A", "WS-C")
        paths = [
            _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA", _BODY)),
            _write(tmp_path, "B.cbl", _program("PROGB", "OTHER-NAME", renamed)),
        ]
        groups = cross_file_clone_groups(scan_files(paths, ScanOptions(), workers=1))
        assert [g.clone_type for g in groups] == ["TYPE_2"]

    def test_an_exact_group_is_not_also_reported_as_renamed(
        self, tmp_path: Path
    ) -> None:
        """Type-1 wins, the same precedence the within-program pass applies.
        Reporting one duplicated paragraph under both types would make the
        group count meaningless."""
        paths = [
            _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA", _BODY)),
            _write(tmp_path, "B.cbl", _program("PROGB", "OTHER-NAME", _BODY)),
        ]
        groups = cross_file_clone_groups(scan_files(paths, ScanOptions(), workers=1))
        assert [g.clone_type for g in groups] == ["TYPE_1"]

    def test_unrelated_paragraphs_do_not_group(self, tmp_path: Path) -> None:
        other = """\
           MOVE 9 TO WS-C
           MOVE 8 TO WS-B
           DISPLAY "OTHER"
           STOP RUN.
"""
        paths = [
            _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA", _BODY)),
            _write(tmp_path, "B.cbl", _program("PROGB", "OTHER-NAME", other)),
        ]
        assert (
            cross_file_clone_groups(scan_files(paths, ScanOptions(), workers=1)) == []
        )

    def test_min_members_filters_groups(self, tmp_path: Path) -> None:
        paths = [
            _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA", _BODY)),
            _write(tmp_path, "B.cbl", _program("PROGB", "OTHER-NAME", _BODY)),
        ]
        report = scan_files(paths, ScanOptions(), workers=1)
        assert cross_file_clone_groups(report, min_members=3) == []
        assert len(cross_file_clone_groups(report, min_members=2)) == 1

    def test_a_scan_without_redundancy_reports_no_groups(self, tmp_path: Path) -> None:
        """Not an empty result presented as 'no clones' -- the analyzer that
        produces fingerprints simply was not run."""
        paths = [
            _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA", _BODY)),
            _write(tmp_path, "B.cbl", _program("PROGB", "OTHER-NAME", _BODY)),
        ]
        report = scan_files(paths, ScanOptions(analyzers=("health",)), workers=1)
        assert cross_file_clone_groups(report) == []

    def test_groups_rank_by_duplicated_volume_not_spread(self, tmp_path: Path) -> None:
        """A 4-statement boilerplate paragraph in five files must not outrank
        a 12-statement paragraph copy-pasted into two. Ranking on file_count
        does exactly that, which is why the sort is on statements x members."""
        small = """\
           MOVE 1 TO WS-A
           MOVE 2 TO WS-B
           DISPLAY "S"
           STOP RUN.
"""
        big_lines = "".join(f"           MOVE {i % 9} TO WS-C\n" for i in range(11))
        big = big_lines + "           STOP RUN.\n"

        paths = [
            _write(tmp_path, f"S{i}.cbl", _program(f"SMALL{i}", "SMALL-PARA", small))
            for i in range(5)
        ] + [
            _write(tmp_path, f"B{i}.cbl", _program(f"BIG{i}", "BIG-PARA", big))
            for i in range(2)
        ]
        groups = cross_file_clone_groups(scan_files(paths, ScanOptions(), workers=1))
        assert len(groups) == 2
        first, second = groups
        assert first.statement_count * len(
            first.members
        ) >= second.statement_count * len(second.members)
        assert {m.paragraph for m in first.members} == {"BIG-PARA"}
        assert first.file_count < second.file_count

    def test_ordering_is_stable(self, tmp_path: Path) -> None:
        paths = [
            _write(tmp_path, f"P{i}.cbl", _program(f"PROG{i}", "ONLY-PARA", _BODY))
            for i in range(4)
        ]
        report = scan_files(paths, ScanOptions(), workers=1)
        first = [g.fingerprint for g in cross_file_clone_groups(report)]
        second = [g.fingerprint for g in cross_file_clone_groups(report)]
        assert first == second

    def test_members_carry_a_navigable_position(self, tmp_path: Path) -> None:
        paths = [
            _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA", _BODY)),
            _write(tmp_path, "B.cbl", _program("PROGB", "OTHER-NAME", _BODY)),
        ]
        group = cross_file_clone_groups(scan_files(paths, ScanOptions(), workers=1))[0]
        for member in group.members:
            assert member.line > 0
            assert Path(member.path).exists()


class TestParseAnalyzerList:
    def test_none_is_the_default_set(self) -> None:
        assert parse_analyzer_list(None) == DEFAULT_ANALYZERS
        assert parse_analyzer_list([]) == DEFAULT_ANALYZERS

    def test_comma_separated_and_repeated_both_work(self) -> None:
        assert parse_analyzer_list(["health,complexity"]) == ("health", "complexity")
        assert parse_analyzer_list(["health", "complexity"]) == ("health", "complexity")

    def test_duplicates_are_dropped_keeping_first_seen_order(self) -> None:
        assert parse_analyzer_list(["complexity", "health", "complexity"]) == (
            "complexity",
            "health",
        )

    def test_whitespace_is_tolerated(self) -> None:
        assert parse_analyzer_list([" health , complexity "]) == (
            "health",
            "complexity",
        )

    def test_every_default_is_a_known_analyzer(self) -> None:
        assert set(DEFAULT_ANALYZERS) <= set(ANALYZERS)


class TestNonDefaultAnalyzers:
    """`--analyzer` can name any of the five. The two in the default set are
    covered everywhere above; these three are reachable only when a caller
    asks for them by name, which is exactly when nothing else would catch a
    mis-wired branch in `_run_analyzer`."""

    @pytest.mark.parametrize(
        "analyzer", ["complexity", "dead-code", "unused-variables"]
    )
    def test_each_optional_analyzer_produces_a_report(
        self, tmp_path: Path, analyzer: str
    ) -> None:
        path = _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA", _BODY))
        scan = scan_one(path, ScanOptions(analyzers=(analyzer,)))
        assert scan.error is None
        assert scan.units[0].failed_analyzers == {}
        assert isinstance(scan.units[0].reports[analyzer], dict)

    def test_every_declared_analyzer_is_actually_wired(self, tmp_path: Path) -> None:
        """ANALYZERS is the list `scan_files` validates against, so a name in
        it that `_run_analyzer` does not handle would pass validation and then
        raise into `failed_analyzers` for every unit in the shop."""
        path = _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA", _BODY))
        scan = scan_one(path, ScanOptions(analyzers=ANALYZERS))
        assert set(scan.units[0].reports) == set(ANALYZERS)
        assert scan.units[0].failed_analyzers == {}


class TestParseFailures:
    @pytest.mark.parametrize(
        "content",
        ["", "this is not cobol at all\nnor is this\n"],
        ids=["empty", "junk"],
    )
    def test_a_file_that_is_not_cobol_is_reported_with_its_parse_errors(
        self, tmp_path: Path, content: str
    ) -> None:
        """The error recovery is good enough that an empty file, or a JCL
        file misfiled under a .cbl extension, still yields one UNKNOWN unit
        with a grade of A and a score of 0 -- i.e. it reads as the healthiest
        program in the shop.

        That unit is NOT dropped (the caller asked about the file and is
        owed an answer), so what makes it distinguishable is
        ``parse_error_count``. This pins it, because a consumer builds its
        "do not trust this row" marker on exactly that: the COBOL Analyzer
        extension's portfolio table sinks such a row below every program that
        parsed cleanly. If this ever came back 0, that table would rank a
        misfiled file top as its healthiest program.
        """
        path = _write(tmp_path, "NOTCOBOL.cbl", content)
        scan = scan_one(path, ScanOptions())
        assert scan.error is None
        assert len(scan.units) == 1
        assert scan.parse_error_count > 0
        assert scan.to_dict()["parse_error_count"] > 0

    def test_a_parser_that_raises_costs_only_that_file(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        import cobolparser.scan as scan_module

        monkeypatch.setattr(
            scan_module,
            "_parse",
            lambda source, path, options, *_: (_ for _ in ()).throw(
                RuntimeError("kaboom")
            ),
        )
        paths = [
            _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA", _BODY)),
            _write(tmp_path, "B.cbl", _program("PROGB", "OTHER-NAME", _BODY)),
        ]
        report = scan_files(paths, ScanOptions(), workers=1)
        assert len(report.failed_files) == 2
        assert all("kaboom" in (f.error or "") for f in report.failed_files)

    def test_surviving_parse_errors_are_reported_on_the_file(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A unit graded out of a partially recovered AST is worth grading and
        worth labelling -- the consumer marks such a row suspect."""

        class _Recovered:
            ast = None
            errors = ["e1", "e2"]

        source = _program("PROGA", "ONLY-PARA", _BODY)
        path = _write(tmp_path, "A.cbl", source)

        real_scan = scan_one(path, ScanOptions())
        assert real_scan.parse_error_count == 0
        assert "parse_error_count" not in real_scan.to_dict()

        import cobolparser.scan as scan_module
        from cobolparser.parser import parse_cobol

        def recovered(src, p, options, *_):
            result = parse_cobol(src, filename=p)
            result.errors = ["e1", "e2"]
            return result

        monkeypatch.setattr(scan_module, "_parse", recovered)
        scan = scan_one(path, ScanOptions())
        assert scan.parse_error_count == 2
        assert scan.to_dict()["parse_error_count"] == 2


class TestCopybookExpansion:
    """The module docstring claims copybook paths change what a scan reports
    and that a failed expansion degrades rather than dropping the file.
    Both are load-bearing -- an unexpanded program's WORKING-STORAGE is
    missing whatever its COPY members declare, so `unused-variables` (and
    therefore `health`'s grade) would be measured against a record layout the
    program cannot see."""

    COPYBOOK = """\
       05 CPY-FIELD-A PIC X(10).
       05 CPY-FIELD-B PIC 9(5).
"""

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

    def test_expansion_brings_copybook_fields_into_the_report(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "TESTCPY.cpy").write_text(self.COPYBOOK)
        path = _write(tmp_path, "COPYUSER.cbl", self.PROGRAM)

        without = scan_one(path, ScanOptions(analyzers=("unused-variables",)))
        with_copybooks = scan_one(
            path,
            ScanOptions(
                analyzers=("unused-variables",), copybook_paths=(str(tmp_path),)
            ),
        )
        assert without.error is None and with_copybooks.error is None

        expanded_total = with_copybooks.units[0].reports["unused-variables"]["summary"][
            "total_variables"
        ]
        plain_total = without.units[0].reports["unused-variables"]["summary"][
            "total_variables"
        ]
        # The copybook's own fields are counted only once expansion ran.
        assert expanded_total > plain_total

    def test_expanded_locations_carry_their_on_disk_origin(
        self, tmp_path: Path
    ) -> None:
        # The member is spliced in ahead of the paragraph, so the report's
        # expanded-text line is not the paragraph's line in the file.
        (tmp_path / "PARAS.cpy").write_text(
            "       COPY-PARA.\n           DISPLAY 'IN COPY'.\n"
            "       DEAD-COPY-PARA.\n           DISPLAY 'DEAD'.\n"
        )
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORIGINS.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM COPY-PARA
           STOP RUN.
           COPY PARAS.
       LAST-DEAD.
           DISPLAY 'Z'.
"""
        path = _write(tmp_path, "ORIGINS.cbl", source)
        scan = scan_one(
            path,
            ScanOptions(analyzers=("dead-code",), copybook_paths=(str(tmp_path),)),
        )
        dead = {d["name"]: d for d in scan.units[0].reports["dead-code"]["dead_code"]}
        assert dead["LAST-DEAD"]["location"]["line"] == 11
        assert dead["LAST-DEAD"]["origin"] == {"file": path, "line": 8}
        assert dead["DEAD-COPY-PARA"]["origin"] == {
            "file": str(tmp_path / "PARAS.cpy"),
            "line": 3,
        }

    def test_cross_file_clone_members_keep_the_origin(self, tmp_path: Path) -> None:
        (tmp_path / "PARAS.cpy").write_text(
            "       SHARED-PARA.\n           MOVE 1 TO WS-A\n"
            "           MOVE 2 TO WS-B\n           DISPLAY 'X'.\n"
        )
        body = "           PERFORM SHARED-PARA\n           STOP RUN.\n           COPY PARAS.\n"
        paths = [
            _write(tmp_path, f"{n}.cbl", _program(n, "MAIN-PARA", body))
            for n in ("PROGA", "PROGB")
        ]
        report = scan_files(
            paths,
            ScanOptions(analyzers=("redundancy",), copybook_paths=(str(tmp_path),)),
            workers=1,
        )
        cpy = str(tmp_path / "PARAS.cpy")
        fingerprints = [
            f
            for file_scan in report.ok_files
            for f in file_scan.units[0].reports["redundancy"]["paragraph_fingerprints"]
            if f["name"] == "SHARED-PARA"
        ]
        assert [f["origin"] for f in fingerprints] == [
            {"file": cpy, "line": 1},
            {"file": cpy, "line": 1},
        ]

    _SHARED_COPYBOOK = (
        "       SHARED-PARA.\n           MOVE 1 TO WS-A\n"
        "           MOVE 2 TO WS-B\n           DISPLAY 'X'.\n"
    )
    _INCLUDER = (
        "           PERFORM SHARED-PARA\n           STOP RUN.\n           COPY PARAS.\n"
    )

    def _scan_with_copybooks(
        self, tmp_path: Path, paths: list[str]
    ) -> list[CrossFileCloneGroup]:
        report = scan_files(
            paths,
            ScanOptions(analyzers=("redundancy",), copybook_paths=(str(tmp_path),)),
            workers=1,
        )
        return cross_file_clone_groups(report)

    def test_a_shared_copybook_paragraph_is_not_a_clone(self, tmp_path: Path) -> None:
        """#352: one copybook included by several programs is one source,
        not copy-paste. Reporting it would put every shop's shared error
        handler at the top of the ranking."""
        (tmp_path / "PARAS.cpy").write_text(self._SHARED_COPYBOOK)
        paths = [
            _write(tmp_path, f"{n}.cbl", _program(n, "MAIN-PARA", self._INCLUDER))
            for n in ("PROGA", "PROGB", "PROGC")
        ]
        assert self._scan_with_copybooks(tmp_path, paths) == []

    def test_a_real_copy_of_a_copybook_paragraph_is_still_a_clone(
        self, tmp_path: Path
    ) -> None:
        """The copybook text pasted verbatim into another program is a second
        copy to keep in step. The group keeps every inclusion as a member so
        a reader sees each program the text reaches, but counts the copybook
        once."""
        (tmp_path / "PARAS.cpy").write_text(self._SHARED_COPYBOOK)
        paths = [
            _write(tmp_path, f"{n}.cbl", _program(n, "MAIN-PARA", self._INCLUDER))
            for n in ("PROGA", "PROGB")
        ]
        pasted = (
            self._INCLUDER.replace("           COPY PARAS.\n", "")
            + self._SHARED_COPYBOOK
        )
        paths.append(
            _write(tmp_path, "PROGC.cbl", _program("PROGC", "MAIN-PARA", pasted))
        )
        (group,) = self._scan_with_copybooks(tmp_path, paths)
        assert group.clone_type == "TYPE_1"
        assert len(group.members) == 3
        assert group.source_count == 2
        assert group.to_dict()["source_count"] == 2
        assert group.file_count == 3

    _BODY_COPYBOOK = "           MOVE 1 TO WS-A\n           MOVE 2 TO WS-B\n           DISPLAY 'X'.\n"
    _HEADER_THEN_BODY = (
        "           PERFORM ERR-PARA\n           STOP RUN.\n"
        "       ERR-PARA.\n           COPY BODY.\n"
    )

    def test_a_copybook_body_under_each_programs_own_header_is_not_a_clone(
        self, tmp_path: Path
    ) -> None:
        """#470: each program writes the header and copies in only the body.
        The duplicated statements live in one place on disk, so this is
        shared code like #352, not copy-paste."""
        (tmp_path / "BODY.cpy").write_text(self._BODY_COPYBOOK)
        paths = [
            _write(
                tmp_path, f"{n}.cbl", _program(n, "MAIN-PARA", self._HEADER_THEN_BODY)
            )
            for n in ("B1", "B2")
        ]
        report = scan_files(
            paths,
            ScanOptions(analyzers=("redundancy",), copybook_paths=(str(tmp_path),)),
            workers=1,
        )
        body = str(tmp_path / "BODY.cpy")
        fingerprints = [
            f
            for file_scan in report.ok_files
            for f in file_scan.units[0].reports["redundancy"]["paragraph_fingerprints"]
            if f["name"] == "ERR-PARA"
        ]
        assert [f["body_origin"] for f in fingerprints] == [
            {"file": body, "line": 1},
            {"file": body, "line": 1},
        ]
        assert cross_file_clone_groups(report) == []

    def test_a_copybook_body_plus_own_statements_is_still_a_clone(
        self, tmp_path: Path
    ) -> None:
        """A body that mixes the copybook with statements written in each
        program is not one source: the program's own lines are duplicated."""
        (tmp_path / "BODY.cpy").write_text(self._BODY_COPYBOOK)
        mixed = self._HEADER_THEN_BODY.replace(
            "           COPY BODY.\n",
            "           DISPLAY 'START'\n           COPY BODY.\n",
        )
        paths = [
            _write(tmp_path, f"{n}.cbl", _program(n, "MAIN-PARA", mixed))
            for n in ("B1", "B2")
        ]
        (group,) = self._scan_with_copybooks(tmp_path, paths)
        assert {m.paragraph for m in group.members} == {"ERR-PARA"}
        assert group.source_count == 2

    def test_min_members_counts_sources_not_inclusions(self, tmp_path: Path) -> None:
        (tmp_path / "PARAS.cpy").write_text(self._SHARED_COPYBOOK)
        paths = [
            _write(tmp_path, f"{n}.cbl", _program(n, "MAIN-PARA", self._INCLUDER))
            for n in ("PROGA", "PROGB", "PROGC")
        ]
        pasted = (
            self._INCLUDER.replace("           COPY PARAS.\n", "")
            + self._SHARED_COPYBOOK
        )
        paths.append(
            _write(tmp_path, "PROGD.cbl", _program("PROGD", "MAIN-PARA", pasted))
        )
        report = scan_files(
            paths,
            ScanOptions(analyzers=("redundancy",), copybook_paths=(str(tmp_path),)),
            workers=1,
        )
        # Four members, but only two copies of the text.
        assert cross_file_clone_groups(report, min_members=3) == []
        assert len(cross_file_clone_groups(report, min_members=2)) == 1

    def test_ranking_counts_a_shared_copybook_once(self, tmp_path: Path) -> None:
        """A small copybook paragraph included widely, and copied once, must
        not outrank a bigger paragraph copy-pasted into two programs."""
        (tmp_path / "PARAS.cpy").write_text(self._SHARED_COPYBOOK)
        big = "".join(f"           MOVE {i % 10} TO WS-C\n" for i in range(14))
        big_para = "       BIG-PARA.\n" + big + "           DISPLAY 'BIG'.\n"
        includers = [
            _write(
                tmp_path,
                f"INC{i}.cbl",
                _program(f"INC{i}", "MAIN-PARA", self._INCLUDER),
            )
            for i in range(10)
        ]
        pasted = (
            self._INCLUDER.replace("           COPY PARAS.\n", "")
            + self._SHARED_COPYBOOK
            + big_para
        )
        copies = [
            _write(tmp_path, f"CP{i}.cbl", _program(f"CP{i}", "MAIN-PARA", pasted))
            for i in range(2)
        ]
        groups = self._scan_with_copybooks(tmp_path, includers + copies)
        names = [{m.paragraph for m in g.members} for g in groups]
        assert names[0] == {"BIG-PARA"}
        assert {"SHARED-PARA"} in names

    def test_no_origin_without_expansion(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "A.cbl", _program("PROGA", "ONLY-PARA", _BODY))
        scan = scan_one(path, ScanOptions(analyzers=("redundancy",)))
        fingerprints = scan.units[0].reports["redundancy"]["paragraph_fingerprints"]
        assert fingerprints and all("origin" not in f for f in fingerprints)

    def test_an_unresolvable_copybook_falls_back_rather_than_dropping_the_file(
        self, tmp_path: Path
    ) -> None:
        # No TESTCPY.cpy anywhere: expansion cannot succeed.
        path = _write(tmp_path, "COPYUSER.cbl", self.PROGRAM)
        scan = scan_one(path, ScanOptions(copybook_paths=(str(tmp_path / "nowhere"),)))
        assert scan.error is None
        assert len(scan.units) == 1
        assert scan.units[0].reports

    def test_the_fallback_says_why_expansion_failed(self, tmp_path: Path) -> None:
        """The fallback used to be a bare `pass`: the unexpanded parse is
        error-free (a COPY statement parses without its member), so the
        file's reports were indistinguishable from an expanded scan's while
        grading a record layout the scan never saw."""
        path = _write(tmp_path, "COPYUSER.cbl", self.PROGRAM)
        scan = scan_one(path, ScanOptions(copybook_paths=(str(tmp_path / "nowhere"),)))
        assert scan.copybook_error is not None
        assert "TESTCPY" in scan.copybook_error
        assert scan.to_dict()["copybook_error"] == scan.copybook_error

    def test_no_copybook_error_when_expansion_succeeds(self, tmp_path: Path) -> None:
        (tmp_path / "TESTCPY.cpy").write_text(self.COPYBOOK)
        path = _write(tmp_path, "COPYUSER.cbl", self.PROGRAM)
        scan = scan_one(path, ScanOptions(copybook_paths=(str(tmp_path),)))
        assert scan.copybook_error is None
        assert "copybook_error" not in scan.to_dict()

    def test_free_form_is_passed_through(self, tmp_path: Path) -> None:
        source = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. FREEFORM.
PROCEDURE DIVISION.
ONLY-PARA.
    DISPLAY "DONE"
    STOP RUN.
"""
        path = _write(tmp_path, "FREE.cbl", source)
        scan = scan_one(path, ScanOptions(free_form=True))
        assert scan.error is None
        assert scan.units[0].program_name == "FREEFORM"


class TestExecutorReuse:
    def test_a_caller_supplied_executor_is_used(self, tmp_path: Path) -> None:
        """The pool path a caller amortising spawn cost across several scans
        takes. Its own branch, and nothing else exercises it."""
        from concurrent.futures import ProcessPoolExecutor

        paths = [
            _write(tmp_path, f"P{i}.cbl", _program(f"PROG{i}", "ONLY-PARA", _BODY))
            for i in range(3)
        ]
        with ProcessPoolExecutor(max_workers=2) as pool:
            first = scan_files(paths, ScanOptions(), executor=pool)
            second = scan_files(paths, ScanOptions(), executor=pool)
        assert first.to_dict() == second.to_dict()
        assert [f.path for f in first.files] == paths
