"""Regression tests for the CLI / config findings of the 2026-09-09 review.

One class per finding; each pins the corrected behaviour of a defect that was
reproduced by running the CLI against a real program.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from cobolparser import CobolParser, SerializationConfig, parse_cobol
from cobolparser.dialects.ibm_enterprise import IBMEnterpriseCobol
from cobolparser.dialects.le_signatures import intrinsic_signature

NESTED = textwrap.dedent("""\
           IDENTIFICATION DIVISION.
           PROGRAM-ID. OUTERP.
           DATA DIVISION.
           WORKING-STORAGE SECTION.
           01  WS-OUTER   PIC X.
           PROCEDURE DIVISION.
           MAIN-PARA.
               MOVE 'A' TO WS-OUTER.
               CALL 'INNERP'.
               STOP RUN.
           IDENTIFICATION DIVISION.
           PROGRAM-ID. INNERP.
           DATA DIVISION.
           WORKING-STORAGE SECTION.
           01  WS-INNER   PIC X.
           01  WS-NEVER   PIC X.
           PROCEDURE DIVISION.
           INNER-PARA.
               MOVE 'B' TO WS-INNER.
               GOBACK.
           END PROGRAM INNERP.
           END PROGRAM OUTERP.
    """)

SIMPLE = textwrap.dedent("""\
           IDENTIFICATION DIVISION.
           PROGRAM-ID. SIMPLE.
           DATA DIVISION.
           WORKING-STORAGE SECTION.
           01  WS-A   PIC 9.
           PROCEDURE DIVISION.
           MAIN-PARA.
               MOVE 1 TO WS-A.
               STOP RUN.
    """)


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "cobolparser", *args],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def nested_file(tmp_path: Path) -> Path:
    path = tmp_path / "NESTED.cbl"
    path.write_text(NESTED)
    return path


@pytest.fixture
def simple_file(tmp_path: Path) -> Path:
    path = tmp_path / "SIMPLE.cbl"
    path.write_text(SIMPLE)
    return path


class TestFinding1ProgramArgOnEveryAnalyzer:
    """``unused-variables`` and ``program-flow`` lacked ``--program``."""

    def test_unused_variables_selects_the_named_unit(self, nested_file: Path) -> None:
        proc = _cli("unused-variables", str(nested_file), "--program", "INNERP")
        assert proc.returncode == 0, proc.stderr
        report = json.loads(proc.stdout)
        assert report["program_id"] == "INNERP"
        names = {item["name"] for item in report["unused_variables"]}
        assert "WS-NEVER" in names
        assert "WS-OUTER" not in names

    def test_program_flow_selects_the_named_unit(self, nested_file: Path) -> None:
        proc = _cli("program-flow", str(nested_file), "--program", "INNERP")
        assert proc.returncode == 0, proc.stderr
        report = json.loads(proc.stdout)
        assert report["program_id"] == "INNERP"
        assert "INNER-PARA" in json.dumps(report)


class TestFinding2StatsLinesProcessed:
    """``--stats`` always reported ``lines_processed: 0``."""

    def test_parse_stats_count_lines(self, simple_file: Path) -> None:
        proc = _cli("parse", str(simple_file), "--stats", "--compact")
        assert proc.returncode == 0, proc.stderr
        stats = json.loads(proc.stdout)["statistics"]
        assert stats["lines_processed"] == SIMPLE.count("\n")

    def test_batch_stats_count_lines(self, simple_file: Path) -> None:
        proc = _cli("batch", str(simple_file), "--stats", "--compact")
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        text = json.dumps(payload)
        assert '"lines_processed": 0' not in text

    def test_parse_statistics_object_keeps_both_counters(self) -> None:
        result = parse_cobol(SIMPLE)
        assert result.statistics.lines_processed == result.statistics.lines_parsed
        assert result.statistics.lines_processed > 0


class TestFinding3SerializationConfigHonoured:
    """``SerializationConfig`` was accepted by the parser and then ignored."""

    def test_constructor_config_applies_to_to_json(self) -> None:
        cfg = SerializationConfig(
            include_source_locations=False, include_metadata=False, compact_format=True
        )
        result = CobolParser(serialization_config=cfg).parse(SIMPLE)
        assert result.ast is not None
        text = result.ast.to_json()
        assert "\n" not in text
        assert '"location"' not in text
        # include_metadata governs the program-level metadata block (nested
        # nodes' metadata carries real clause data and is kept)
        assert "metadata" not in result.ast.to_dict()
        assert "metadata" in result.ast.to_dict(SerializationConfig())

    def test_explicit_config_strips_every_nested_location(self) -> None:
        result = parse_cobol(SIMPLE)
        assert result.ast is not None
        cfg = SerializationConfig(include_source_locations=False)
        assert '"location"' not in result.ast.to_json(cfg)
        # and the default still carries them everywhere
        assert result.ast.to_json().count('"location"') > 1

    def test_compact_format_is_single_line(self) -> None:
        result = parse_cobol(SIMPLE)
        assert result.ast is not None
        assert "\n" not in result.ast.to_json(SerializationConfig(compact_format=True))
        assert "\n" in result.ast.to_json(SerializationConfig())


class TestFinding4BatchWorkersGuard:
    """``batch --workers 0`` raised an uncaught ``ValueError``."""

    def test_zero_workers_is_a_clean_usage_error(self, simple_file: Path) -> None:
        proc = _cli("batch", str(simple_file), "--workers", "0")
        assert proc.returncode != 0
        assert "Traceback" not in proc.stderr
        assert "--workers" in proc.stderr


class TestFinding5CoverageRenderNonObject:
    """``coverage render`` tracebacked on a JSON array."""

    def test_array_artifact_is_reported_not_raised(self, tmp_path: Path) -> None:
        artifact = tmp_path / "arr.json"
        artifact.write_text("[1, 2]")
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cobolparser.cli.coverage",
                "render",
                "--input",
                str(artifact),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 1
        assert "Traceback" not in proc.stderr
        assert "does not contain a coverage artifact object" in proc.stdout


class TestFinding6LintTextProfileWarns:
    """``lint --format text --profile`` silently dropped the profile."""

    def test_warning_on_stderr(self, simple_file: Path) -> None:
        proc = _cli("lint", str(simple_file), "--format", "text", "--profile")
        assert proc.returncode in (0, 3), proc.stderr
        assert "--profile metrics are only included in --format json" in proc.stderr


class TestFinding7DialectIntrinsicSignatures:
    """The dialect knew 5 of its 44 intrinsic signatures."""

    def test_every_intrinsic_has_a_signature(self) -> None:
        missing = [
            name
            for name in IBMEnterpriseCobol.IBM_INTRINSIC_FUNCTIONS
            if intrinsic_signature(name) is None
        ]
        assert missing == []


class TestFinding8ParseReportsProgramUnits:
    """``parse`` omitted ``program_units`` for a multi-program file."""

    def test_program_units_in_identification(self, nested_file: Path) -> None:
        proc = _cli("parse", str(nested_file), "--compact")
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["program_units"] == ["OUTERP", "INNERP"]

    def test_single_program_output_unchanged(self, simple_file: Path) -> None:
        proc = _cli("parse", str(simple_file), "--compact")
        assert proc.returncode == 0, proc.stderr
        assert "program_units" not in json.loads(proc.stdout)


class TestFinding9MissingCopybookIsACleanError:
    """A copybook that cannot be found escaped as a raw traceback."""

    def test_lint_reports_one_line_and_exits_1(self, tmp_path: Path) -> None:
        src = tmp_path / "PROG.cbl"
        src.write_text(textwrap.dedent("""\
                       IDENTIFICATION DIVISION.
                       PROGRAM-ID. PROG.
                       DATA DIVISION.
                       WORKING-STORAGE SECTION.
                       COPY NOSUCH.
                       PROCEDURE DIVISION.
                           STOP RUN.
                """))
        proc = _cli(
            "lint",
            str(src),
            "--compact",
            "--copybook-path",
            str(tmp_path),
            "--strict-copybooks",
        )
        assert proc.returncode == 1
        assert "Traceback" not in proc.stderr
        assert "NOSUCH" in proc.stderr
        assert "not found" in proc.stderr

    def test_lint_without_strict_copybooks_lints_and_says_so(
        self, tmp_path: Path
    ) -> None:
        """By default lint finishes the file and names the missing member in
        its caveats, rather than failing it (CardDemo: 17 of 29 programs
        failed on IBM's DFHAID / DFHBMSCA)."""
        import json

        src = tmp_path / "PROG.cbl"
        src.write_text(textwrap.dedent("""\
                       IDENTIFICATION DIVISION.
                       PROGRAM-ID. PROG.
                       DATA DIVISION.
                       WORKING-STORAGE SECTION.
                       COPY NOSUCH.
                       PROCEDURE DIVISION.
                           STOP RUN.
                """))
        proc = _cli("lint", str(src), "--compact", "--copybook-path", str(tmp_path))
        assert proc.returncode == 0, proc.stderr
        report = json.loads(proc.stdout)
        assert any("NOSUCH" in c and "left as written" in c for c in report["caveats"])


class TestFinding10VersionMatchesPackage:
    """``--version`` said 1.8.0 while the package was 1.9.0."""

    def test_dunder_version_matches_pyproject(self) -> None:
        import re

        from cobolparser import __version__

        pyproject = (Path(__file__).parents[2] / "pyproject.toml").read_text()
        declared = re.search(r'^version = "([^"]+)"', pyproject, re.M)
        assert declared is not None
        assert __version__ == declared.group(1)
