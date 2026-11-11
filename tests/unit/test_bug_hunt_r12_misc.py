"""Bug hunt round 12: CLI error handling, profiling, config YAML, the
ENVIRONMENT DIVISION's unrecorded paragraphs, INSPECT / condition
operands, and JSON round-trips.

Each test reproduces a defect found in this round and pins the fix.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tracemalloc
from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser.cli.parse import main
from cobolparser.config._yaml import YamlError, parse_yaml
from cobolparser.models.program import CobolProgram, LossyDeserializationWarning
from cobolparser.models.statements.base import ConditionalExpression
from cobolparser.profiling import ProfilerContext

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTERPRISE = REPO_ROOT / "tests" / "samples" / "enterprise"


def _program(body: str, data: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. T.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"{data}"
        "       PROCEDURE DIVISION.\n"
        f"{body}"
        "           STOP RUN.\n"
    )


def _run_main(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["cobol-parser", "--no-config", *argv])
    try:
        main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


# -- CLI: expand ----------------------------------------------------------


def test_expand_missing_copybook_is_a_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # `parse --copybook-path` reported this on one line with exit 1; `expand`
    # let CopybookNotFoundError escape as a traceback.
    src = tmp_path / "p.cbl"
    src.write_text(
        _program("", data="       COPY MISSING.\n"),
        encoding="utf-8",
    )
    # Lenient by default now (C2); --strict-copybooks keeps the clean error.
    code = _run_main(
        monkeypatch,
        "expand",
        str(src),
        "--copybook-path",
        str(tmp_path),
        "--strict-copybooks",
    )
    err = capsys.readouterr().err
    assert code == 1
    assert "Copybook expansion failed" in err
    assert "MISSING" in err


def test_expand_circular_copybook_is_a_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    (tmp_path / "A.cpy").write_text("       COPY B.\n", encoding="utf-8")
    (tmp_path / "B.cpy").write_text("       COPY A.\n", encoding="utf-8")
    src = tmp_path / "p.cbl"
    src.write_text(_program("", data="       COPY A.\n"), encoding="utf-8")
    code = _run_main(monkeypatch, "expand", str(src), "--copybook-path", str(tmp_path))
    assert code == 1
    assert "Copybook expansion failed" in capsys.readouterr().err


# -- CLI: a closed stdout ---------------------------------------------------


def test_closed_stdout_pipe_exits_quietly(tmp_path: Path) -> None:
    # `cobol-parser batch ... | head` printed a BrokenPipeError traceback.
    src = ENTERPRISE / "BATCHSEQ.cbl"
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; sys.argv[0] = 'cobol-parser'; "
            "from cobolparser.cli.parse import main; main()",
            "--no-config",
            "batch",
            *([str(src)] * 20),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert proc.stdout is not None and proc.stderr is not None
    proc.stdout.close()  # the reader is gone before anything is written
    stderr = proc.stderr.read().decode()
    proc.wait(timeout=120)
    assert "Traceback" not in stderr
    assert "BrokenPipeError" not in stderr
    assert proc.returncode == 141


# -- profiling ----------------------------------------------------------------


def test_profiler_peak_excludes_memory_held_before_the_call() -> None:
    # Under an outer tracemalloc session the reported "peak within the
    # profiled call" was the session's all-time peak, memory allocated long
    # before the call included.
    tracemalloc.start()
    try:
        held = bytearray(20 * 1024 * 1024)  # live across the call
        with ProfilerContext(top_n=0) as ctx:
            inner = bytearray(8 * 1024 * 1024)
            del inner
        assert ctx.result is not None
        assert ctx.result.peak_memory_exact is True
        assert 7.5 < ctx.result.peak_memory_mb < 12
        del held
    finally:
        tracemalloc.stop()


def test_profiler_flags_an_unknowable_peak_and_keeps_the_outer_one() -> None:
    tracemalloc.start()
    try:
        big = bytearray(40 * 1024 * 1024)
        del big
        outer_peak = tracemalloc.get_traced_memory()[1]
        with ProfilerContext(top_n=0) as ctx:
            small = bytearray(1024)
            del small
        assert ctx.result is not None
        # The call never rose above the earlier peak: its own peak cannot be
        # known without resetting the outer session's, so it is flagged.
        assert ctx.result.peak_memory_exact is False
        assert ctx.result.to_dict()["peak_memory_exact"] is False
        # ...and the outer session's peak is left alone.
        assert tracemalloc.get_traced_memory()[1] >= outer_peak
    finally:
        tracemalloc.stop()


def test_profiler_fresh_session_is_exact() -> None:
    assert not tracemalloc.is_tracing()
    with ProfilerContext(top_n=0) as ctx:
        data = bytearray(4 * 1024 * 1024)
        del data
    assert ctx.result is not None
    assert ctx.result.peak_memory_exact is True
    assert ctx.result.peak_memory_mb >= 3.5
    assert not tracemalloc.is_tracing()


# -- config YAML ------------------------------------------------------------


def test_yaml_flow_sequence_across_lines() -> None:
    assert parse_yaml("rules: [a,\n  b]\nx: 1\n") == {"rules": ["a", "b"], "x": 1}


def test_yaml_flow_collections_across_lines_variants() -> None:
    assert parse_yaml("rules: [\n  a,  # first\n  b,\n]\n") == {"rules": ["a", "b"]}
    assert parse_yaml("k:\n  - {a: 1,\n     b: 2}\n") == {"k": [{"a": 1, "b": 2}]}
    assert parse_yaml("- [a,\n  b]\n") == [["a", "b"]]
    assert parse_yaml('r: [a, "x]",\n  b]\n') == {"r": ["a", "x]", "b"]}


def test_yaml_unclosed_flow_collection_still_rejected() -> None:
    with pytest.raises(YamlError, match=r":2: unterminated flow collection"):
        parse_yaml("a:\n  rules: [a,\nb: 1\n")
    with pytest.raises(YamlError, match="unterminated flow collection"):
        parse_yaml("rules: [a,\n")


# -- ENVIRONMENT DIVISION ---------------------------------------------------

_ENV_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IOC.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. IBM-370 WITH DEBUGGING MODE.
       OBJECT-COMPUTER. IBM-370
           MEMORY SIZE 8000 WORDS
           PROGRAM COLLATING SEQUENCE IS ASC-SEQ
           SEGMENT-LIMIT IS 40.
       SPECIAL-NAMES.
           ALPHABET ASC-SEQ IS STANDARD-1.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INFILE.
           SELECT OUT-FILE ASSIGN TO OUTFILE.
       I-O-CONTROL.
           SAME RECORD AREA FOR IN-FILE, OUT-FILE
           APPLY WRITE-ONLY ON OUT-FILE
           RERUN ON CHKPT EVERY 1000 RECORDS OF IN-FILE
           MULTIPLE FILE TAPE CONTAINS IN-FILE POSITION 1 OUT-FILE.
       DATA DIVISION.
       FILE SECTION.
       FD IN-FILE.
       01 IN-REC PIC X(80).
       FD OUT-FILE.
       01 OUT-REC PIC X(80).
       PROCEDURE DIVISION.
           STOP RUN.
"""


def _env_sections() -> dict:
    result = parse_cobol(_ENV_PROGRAM)
    assert result.errors == []
    env = result.ast.environment_division
    return {s.section_name: s for s in env.sections}


def test_io_control_entries_are_recorded() -> None:
    # I-O-CONTROL matched the FILE-CONTROL check (any word ending in CONTROL)
    # and every entry in it was consumed without a trace.
    io_section = _env_sections()["INPUT-OUTPUT"]
    entries = io_section.get_metadata("io_control")
    assert [e["clause"] for e in entries] == ["SAME", "APPLY", "RERUN", "MULTIPLE"]
    assert entries[0]["text"] == "SAME RECORD AREA FOR IN-FILE OUT-FILE"
    assert entries[2]["text"] == "RERUN ON CHKPT EVERY 1000 RECORDS OF IN-FILE"
    assert entries[3]["line"] == 20
    # FILE-CONTROL itself is unchanged.
    (file_control,) = io_section.paragraphs
    assert [s.file_name for s in file_control.statements] == ["IN-FILE", "OUT-FILE"]
    assert "io_control" in io_section.to_dict()["metadata"]


def test_source_and_object_computer_are_recorded() -> None:
    config = _env_sections()["CONFIGURATION"]
    source = config.get_metadata("source_computer")
    assert source["computer_name"] == "IBM-370"
    assert source["debugging_mode"] is True
    obj = config.get_metadata("object_computer")
    assert obj["computer_name"] == "IBM-370"
    assert obj["collating_sequence"] == "ASC-SEQ"
    assert "SEGMENT-LIMIT IS 40" in obj["text"]
    # SPECIAL-NAMES after them is still parsed.
    assert config.get_metadata("special_names")["alphabet_definitions"][0]["name"] == (
        "ASC-SEQ"
    )


# -- PROCEDURE DIVISION operands -------------------------------------------


def test_inspect_replacing_characters_has_no_from_value() -> None:
    # The CHARACTERS keyword was recorded as the search operand, which
    # reads as a reference to a data item named CHARACTERS.
    result = parse_cobol(
        _program(
            '           INSPECT A REPLACING CHARACTERS BY "X" AFTER INITIAL "Y".\n'
            '           INSPECT A REPLACING ALL "A" BY "B" CHARACTERS BY "Z".\n',
            data="       01 A PIC X(10).\n",
        )
    )
    first, second = result.ast.find_all_by_type("InspectStatement")[:2]
    assert first.replacing_clauses[0]["replace_type"] == "CHARACTERS"
    assert first.replacing_clauses[0]["from_value"] is None
    assert first.replacing_clauses[0]["to_value"] == '"X"'
    assert second.replacing_clauses[0]["from_value"] is not None
    assert second.replacing_clauses[1]["from_value"] is None


def test_if_equals_is_a_structured_equal_relation() -> None:
    # `IF A EQUALS B` fell back to an operand-less COMPARISON node, though
    # NOT EQUALS / GREATER OR EQUALS were already accepted.
    result = parse_cobol(
        _program(
            '           IF A EQUALS "B" DISPLAY "EQ" END-IF.\n',
            data="       01 A PIC X.\n",
        )
    )
    (if_stmt,) = result.ast.find_all_by_type("IfStatement")
    cond = if_stmt.condition
    assert isinstance(cond, ConditionalExpression)
    assert cond.operator == "EQUAL"
    assert cond.left_operand == "A"
    assert cond.right_operand == "'B'"


def test_subscripted_and_qualified_condition_names() -> None:
    # Only a single-token condition-name was recognised; `CN1 (1)` became an
    # operand-less COMPARISON and `NOT CN1 (3)` kept its NOT as raw text.
    result = parse_cobol(
        _program(
            '           IF CN1 (1) DISPLAY "A" END-IF.\n'
            '           IF CN1 OF G (2) DISPLAY "A" END-IF.\n'
            '           IF NOT CN1 (3) DISPLAY "A" END-IF.\n',
            data=(
                "       01 G.\n"
                "          05 E PIC X OCCURS 3.\n"
                '             88 CN1 VALUE "Y".\n'
            ),
        )
    )
    first, second, third = result.ast.find_all_by_type("IfStatement")
    assert first.condition.operator == "CONDITION_NAME"
    assert first.condition.left_operand == "CN1 ( 1 )"
    assert second.condition.operator == "CONDITION_NAME"
    assert second.condition.left_operand == "CN1 OF G ( 2 )"
    assert third.condition.operator == "NOT"
    assert third.condition.left_condition.operator == "CONDITION_NAME"


def test_parenthesised_non_condition_name_is_not_a_condition_name() -> None:
    result = parse_cobol(
        _program(
            '           IF (A) DISPLAY "A" END-IF.\n'
            '           IF A (1) (2) DISPLAY "A" END-IF.\n',
            data="       01 A PIC X.\n",
        )
    )
    first, second = result.ast.find_all_by_type("IfStatement")
    # `(A)` is unwrapped to a bare condition-name; `A (1) (2)` is not one.
    assert first.condition.operator == "CONDITION_NAME"
    assert second.condition.operator != "CONDITION_NAME"


# -- JSON round-trip --------------------------------------------------------


@pytest.mark.parametrize("sample", ["NESTED.cbl", "OOCOBOL.cbl"])
def test_from_json_keeps_program_units(sample: str) -> None:
    # A CLASS-ID came back as a PROGRAM and every contained unit was dropped.
    ast = parse_cobol((ENTERPRISE / sample).read_text(encoding="utf-8")).ast
    with pytest.warns(LossyDeserializationWarning):
        restored = CobolProgram.from_json(ast.to_json())
    assert [(u.program_name, u.unit_kind) for u in restored.program_units()] == [
        (u.program_name, u.unit_kind) for u in ast.program_units()
    ]
    assert len(ast.program_units()) > 1
