# Test Coverage Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise test coverage from 83.98% to ≥90% by writing targeted tests for 10 under-covered modules.

**Architecture:** Pure test additions — no production code changes. Each task adds one new test file that exercises specific uncovered code paths in existing parsers, models, and analysis modules. Tests follow the existing pattern: `parse_cobol()` → assert on AST structure and attributes.

**Tech Stack:** pytest, cobolparser.parse_cobol, CobolParser, ErrorRecoveryMode

---

## Coverage Baseline (pre-plan)

| File | Current | Target | Gap |
|------|---------|--------|-----|
| `analysis/io_diagnostics.py` | 0% | 90% | 57 lines |
| `models/statements/data.py` | 38% | 85% | 63 lines |
| `parsers/statements/write_parser.py` | 58% | 90% | 22 lines |
| `parsers/statements/start_parser.py` | 59% | 85% | 38 lines |
| `parsers/statements/close_parser.py` | 59% | 90% | 27 lines |
| `parsers/statements/ibm_exec_statements.py` | 61% | 85% | 28 lines |
| `parsers/statements/go_parser.py` | 73% | 90% | 14 lines |
| `parsers/statements/open_parser.py` | 74% | 90% | 14 lines |
| `parsers/statements/read_parser.py` | 75% | 90% | 34 lines |
| `parsers/statements/stop_parser.py` | 76% | 90% | 5 lines |

---

## Task 1: WRITE and CLOSE parser coverage

**Files:**
- Create: `tests/unit/io_statements/test_write_close_parsers.py`

### What's uncovered

`write_parser.py`: FROM clause (lines 56-67), BEFORE/AFTER ADVANCING (lines 69-87), missing record name early-return (lines 48-50), exception path in `matches` (lines 30-31).

`close_parser.py`: REEL option (line 62-65), UNIT option (lines 68-71), WITH NO REWIND (lines 73-85), WITH LOCK via `LOCK` token type (lines 90-93), multiple files in one CLOSE.

- [ ] **Step 1: Write the test file**

```python
"""Tests for WRITE and CLOSE statement parser coverage."""
import pytest
from cobolparser import parse_cobol


def _prog(procedure_stmts: str) -> str:
    return f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DATA   PIC X(80).
       PROCEDURE DIVISION.
{procedure_stmts}
           STOP RUN.
    """


class TestWriteParserCoverage:
    """Cover uncovered branches in write_parser.py."""

    def test_write_from_clause(self):
        """WRITE rec FROM src hits the FROM branch (lines 56-67)."""
        result = parse_cobol(_prog("           WRITE OUT-REC FROM WS-DATA."))
        assert result.ast is not None
        stmts = result.ast.find_statements("WRITE")
        assert len(stmts) >= 1
        stmt = stmts[0]
        assert stmt.from_data == "WS-DATA"

    def test_write_before_advancing(self):
        """WRITE rec BEFORE ADVANCING hits advancing branch (lines 69-87)."""
        result = parse_cobol(_prog("           WRITE PRINT-REC BEFORE ADVANCING."))
        assert result.ast is not None
        stmts = result.ast.find_statements("WRITE")
        assert len(stmts) >= 1
        stmt = stmts[0]
        assert stmt.advancing_mode == "BEFORE"

    def test_write_after_advancing(self):
        """WRITE rec AFTER ADVANCING."""
        result = parse_cobol(_prog("           WRITE PRINT-REC AFTER ADVANCING."))
        assert result.ast is not None
        stmts = result.ast.find_statements("WRITE")
        assert len(stmts) >= 1
        stmt = stmts[0]
        assert stmt.advancing_mode == "AFTER"

    def test_write_from_and_before_advancing(self):
        """WRITE rec FROM src BEFORE ADVANCING covers combined path."""
        result = parse_cobol(
            _prog("           WRITE PRINT-REC FROM WS-DATA BEFORE ADVANCING.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("WRITE")
        assert len(stmts) >= 1
        stmt = stmts[0]
        assert stmt.from_data == "WS-DATA"
        assert stmt.advancing_mode == "BEFORE"

    def test_write_minimal(self):
        """WRITE with record name only — baseline coverage."""
        result = parse_cobol(_prog("           WRITE OUT-REC."))
        assert result.ast is not None
        stmts = result.ast.find_statements("WRITE")
        assert len(stmts) >= 1
        assert stmts[0].record_name == "OUT-REC"


class TestCloseParserCoverage:
    """Cover uncovered branches in close_parser.py."""

    def test_close_reel(self):
        """CLOSE file REEL hits the REEL token branch (line 62-65)."""
        result = parse_cobol(_prog("           CLOSE TAPE-FILE REEL."))
        assert result.ast is not None
        stmts = result.ast.find_statements("CLOSE")
        assert len(stmts) >= 1
        files = stmts[0].files
        assert len(files) >= 1
        assert files[0].get("reel") is True

    def test_close_unit(self):
        """CLOSE file UNIT hits UNIT identifier branch (lines 68-71)."""
        result = parse_cobol(_prog("           CLOSE TAPE-FILE UNIT."))
        assert result.ast is not None
        stmts = result.ast.find_statements("CLOSE")
        assert len(stmts) >= 1
        files = stmts[0].files
        assert files[0].get("unit") is True

    def test_close_with_no_rewind(self):
        """CLOSE file WITH NO REWIND hits no_rewind branch (lines 73-85)."""
        result = parse_cobol(_prog("           CLOSE TAPE-FILE WITH NO REWIND."))
        assert result.ast is not None
        stmts = result.ast.find_statements("CLOSE")
        assert len(stmts) >= 1
        files = stmts[0].files
        assert files[0].get("no_rewind") is True

    def test_close_with_lock(self):
        """CLOSE file WITH LOCK hits with_lock identifier path (lines 86-89)."""
        result = parse_cobol(_prog("           CLOSE IDX-FILE WITH LOCK."))
        assert result.ast is not None
        stmts = result.ast.find_statements("CLOSE")
        assert len(stmts) >= 1
        files = stmts[0].files
        assert files[0].get("with_lock") is True

    def test_close_multiple_files(self):
        """CLOSE with multiple file names iterates the while loop."""
        result = parse_cobol(_prog("           CLOSE FILE-A FILE-B FILE-C."))
        assert result.ast is not None
        stmts = result.ast.find_statements("CLOSE")
        assert len(stmts) >= 1
        assert len(stmts[0].files) >= 3
```

- [ ] **Step 2: Run the tests to establish baseline**

```
python -m pytest tests/unit/io_statements/test_write_close_parsers.py -v
```

Expected: Some tests may FAIL if AST attribute names differ — read the error, fix attribute names to match actual `IOWriteStatement` / `IOCloseStatement` fields.

- [ ] **Step 3: Check actual attribute names on IOWriteStatement and IOCloseStatement**

Read `cobolparser/models/statements/io.py` — find the exact field names for `from_data`, `record_name`, `advancing_mode`, and `IOCloseStatement.files` structure. Update test assertions to match.

- [ ] **Step 4: Run again until all pass**

```
python -m pytest tests/unit/io_statements/test_write_close_parsers.py -v
```

Expected: All PASS.

- [ ] **Step 5: Verify coverage improvement**

```
python -m pytest tests/unit/io_statements/test_write_close_parsers.py --cov=cobolparser/parsers/statements/write_parser --cov=cobolparser/parsers/statements/close_parser --cov-report=term-missing -v
```

Expected: `write_parser.py` ≥ 85%, `close_parser.py` ≥ 85%.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/io_statements/test_write_close_parsers.py
git commit -m "test: add coverage for WRITE FROM/ADVANCING and CLOSE REEL/UNIT/NO REWIND/LOCK"
```

---

## Task 2: START statement parser coverage

**Files:**
- Create: `tests/unit/io_statements/test_start_parser.py`

### What's uncovered

Lines 33-34 (`matches` exception path), 56 (missing file name early-return), 67-77 (KEY token path + IS keyword), 73-74 (IS as identifier), 86-106 (comparison ops: GREATER/LESS + THAN/TO + OR EQUAL), 117→120 (INVALID KEY), 128-141 (NOT INVALID KEY), 147-148 (END-START).

- [ ] **Step 1: Write the test file**

```python
"""Tests for START statement parser coverage."""
import pytest
from cobolparser import parse_cobol


def _prog(procedure_stmts: str) -> str:
    return f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-KEY    PIC 9(5).
       PROCEDURE DIVISION.
{procedure_stmts}
           STOP RUN.
    """


class TestStartParserCoverage:
    """Cover uncovered branches in start_parser.py."""

    def test_start_minimal(self):
        """START file-name with no clauses — baseline."""
        result = parse_cobol(_prog("           START IDX-FILE."))
        assert result.ast is not None
        stmts = result.ast.find_statements("START")
        assert len(stmts) >= 1
        assert stmts[0].file_name == "IDX-FILE"

    def test_start_key_is_equal(self):
        """START file KEY IS EQUAL — covers KEY_IS token + EQUAL condition."""
        result = parse_cobol(_prog("           START IDX-FILE KEY IS EQUAL WS-KEY."))
        assert result.ast is not None
        stmts = result.ast.find_statements("START")
        assert len(stmts) >= 1
        assert stmts[0].key_condition is not None

    def test_start_key_greater_than(self):
        """START file KEY IS GREATER THAN — covers GREATER + THAN path (lines 86-96)."""
        result = parse_cobol(_prog("           START IDX-FILE KEY IS GREATER THAN WS-KEY."))
        assert result.ast is not None
        stmts = result.ast.find_statements("START")
        assert len(stmts) >= 1
        assert "GREATER" in (stmts[0].key_condition or "")

    def test_start_key_not_less(self):
        """START file KEY NOT LESS — covers NOT prefix path (lines 79-82) + LESS."""
        result = parse_cobol(_prog("           START IDX-FILE KEY NOT LESS WS-KEY."))
        assert result.ast is not None
        stmts = result.ast.find_statements("START")
        assert len(stmts) >= 1
        assert "NOT" in (stmts[0].key_condition or "")

    def test_start_key_greater_than_or_equal(self):
        """START file KEY GREATER THAN OR EQUAL — covers OR EQUAL path (lines 99-106)."""
        result = parse_cobol(
            _prog("           START IDX-FILE KEY GREATER THAN OR EQUAL WS-KEY.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("START")
        assert len(stmts) >= 1
        assert "OR EQUAL" in (stmts[0].key_condition or "")

    def test_start_with_invalid_key(self):
        """START file KEY IS EQUAL INVALID KEY — covers INVALID KEY clause (lines 111-123)."""
        result = parse_cobol(
            _prog(
                "           START IDX-FILE KEY IS EQUAL WS-KEY\n"
                "               INVALID KEY DISPLAY 'NOT FOUND'\n"
                "           END-START."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("START")
        assert len(stmts) >= 1
        assert stmts[0].invalid_key_clause is not None

    def test_start_with_not_invalid_key(self):
        """NOT INVALID KEY clause — covers lines 125-141."""
        result = parse_cobol(
            _prog(
                "           START IDX-FILE KEY IS EQUAL WS-KEY\n"
                "               NOT INVALID KEY DISPLAY 'FOUND'\n"
                "           END-START."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("START")
        assert len(stmts) >= 1
        assert stmts[0].not_invalid_key_clause is not None

    def test_start_with_end_start(self):
        """END-START delimiter — covers lines 146-148."""
        result = parse_cobol(_prog("           START IDX-FILE KEY IS EQUAL WS-KEY END-START."))
        assert result.ast is not None
        stmts = result.ast.find_statements("START")
        assert len(stmts) >= 1
```

- [ ] **Step 2: Run the tests**

```
python -m pytest tests/unit/io_statements/test_start_parser.py -v
```

Expected: Some may fail due to attribute name mismatches. Read `cobolparser/models/statements/io.py` to find exact field names on `IOStartStatement` (`key_condition`, `invalid_key_clause`, `not_invalid_key_clause`), then fix.

- [ ] **Step 3: Fix attribute names if needed and re-run**

```
python -m pytest tests/unit/io_statements/test_start_parser.py -v
```

Expected: All PASS.

- [ ] **Step 4: Verify coverage**

```
python -m pytest tests/unit/io_statements/test_start_parser.py --cov=cobolparser/parsers/statements/start_parser --cov-report=term-missing -v
```

Expected: `start_parser.py` ≥ 80%.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/io_statements/test_start_parser.py
git commit -m "test: add coverage for START KEY conditions, INVALID KEY, NOT INVALID KEY, END-START"
```

---

## Task 3: OPEN and READ parser coverage

**Files:**
- Create: `tests/unit/io_statements/test_open_read_parsers.py`

### What's uncovered

`open_parser.py` (74%): EXTEND mode (line 50 `_OPEN_MODES`), I-O mode (line 50 `I-O`), WITH REPOSITION (lines 82-89), multiple file names in one OPEN.

`read_parser.py` (75%): FIRST/LAST/PREVIOUS/CURRENT access modes (lines 62-67), INTO clause (lines 77-84), KEY IS clause (lines 88-104), WITH LOCK (lines 108-124), WITH NO LOCK (lines 112-120), AT END clause (lines 132-143), NOT AT END (lines 147-164), NOT INVALID KEY via first NOT branch (lines 165-177), INVALID KEY (lines 182-192), END-READ (lines 215-216).

- [ ] **Step 1: Write the test file**

```python
"""Tests for OPEN and READ statement parser coverage."""
import pytest
from cobolparser import parse_cobol


def _prog(procedure_stmts: str) -> str:
    return f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-BUF    PIC X(80).
       01  WS-KEY    PIC 9(5).
       PROCEDURE DIVISION.
{procedure_stmts}
           STOP RUN.
    """


class TestOpenParserCoverage:
    """Cover uncovered branches in open_parser.py."""

    def test_open_extend_mode(self):
        """OPEN EXTEND hits EXTEND in _OPEN_MODES (line 50)."""
        result = parse_cobol(_prog("           OPEN EXTEND SEQ-FILE."))
        assert result.ast is not None
        stmts = result.ast.find_statements("OPEN")
        assert len(stmts) >= 1
        assert stmts[0].open_mode == "EXTEND"

    def test_open_io_mode(self):
        """OPEN I-O hits I-O branch (line 50)."""
        result = parse_cobol(_prog("           OPEN I-O IDX-FILE."))
        assert result.ast is not None
        stmts = result.ast.find_statements("OPEN")
        assert len(stmts) >= 1
        assert stmts[0].open_mode == "I-O"

    def test_open_multiple_files(self):
        """OPEN INPUT with multiple file names iterates the while loop."""
        result = parse_cobol(_prog("           OPEN INPUT FILE-A FILE-B."))
        assert result.ast is not None
        stmts = result.ast.find_statements("OPEN")
        assert len(stmts) >= 1
        assert len(stmts[0].files) >= 2

    def test_open_with_reposition(self):
        """OPEN I-O file WITH REPOSITION covers lines 82-89."""
        result = parse_cobol(_prog("           OPEN I-O VSAM-FILE WITH REPOSITION."))
        assert result.ast is not None
        stmts = result.ast.find_statements("OPEN")
        assert len(stmts) >= 1
        assert stmts[0].reposition is True


class TestReadParserCoverage:
    """Cover uncovered branches in read_parser.py."""

    def test_read_into_clause(self):
        """READ file INTO ws-var covers INTO branch (lines 77-84)."""
        result = parse_cobol(_prog("           READ SEQ-FILE INTO WS-BUF."))
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].into == "WS-BUF"

    def test_read_next_record(self):
        """READ file NEXT covers NEXT access mode (line 58-61)."""
        result = parse_cobol(_prog("           READ SEQ-FILE NEXT."))
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].access_mode == "NEXT"

    def test_read_first_record(self):
        """READ file FIRST covers FIRST identifier branch (lines 62-67)."""
        result = parse_cobol(_prog("           READ IDX-FILE FIRST."))
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].access_mode == "FIRST"

    def test_read_key_is_clause(self):
        """READ file KEY IS key-name covers KEY_IS/KEY branch (lines 88-104)."""
        result = parse_cobol(_prog("           READ IDX-FILE KEY IS WS-KEY."))
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].key == "WS-KEY"

    def test_read_with_lock(self):
        """READ file WITH LOCK covers lock branch (lines 121-124)."""
        result = parse_cobol(_prog("           READ IDX-FILE WITH LOCK."))
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].with_lock is True

    def test_read_with_no_lock(self):
        """READ file WITH NO LOCK covers no-lock branch (lines 112-120)."""
        result = parse_cobol(_prog("           READ IDX-FILE WITH NO LOCK."))
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1

    def test_read_at_end(self):
        """READ file AT END ... END-READ covers AT END clause (lines 132-143) + END-READ."""
        result = parse_cobol(
            _prog(
                "           READ SEQ-FILE\n"
                "               AT END DISPLAY 'DONE'\n"
                "           END-READ."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].at_end_clause is not None

    def test_read_not_at_end(self):
        """READ file NOT AT END ... END-READ covers NOT AT END branch (lines 147-164)."""
        result = parse_cobol(
            _prog(
                "           READ SEQ-FILE\n"
                "               NOT AT END DISPLAY 'GOT REC'\n"
                "           END-READ."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].not_at_end_clause is not None

    def test_read_invalid_key(self):
        """READ file INVALID KEY covers INVALID KEY clause (lines 182-192)."""
        result = parse_cobol(
            _prog(
                "           READ IDX-FILE\n"
                "               INVALID KEY DISPLAY 'NOT FOUND'\n"
                "           END-READ."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].invalid_key_clause is not None

    def test_read_not_invalid_key(self):
        """READ file NOT INVALID KEY via the NOT→INVALID branch (lines 165-177)."""
        result = parse_cobol(
            _prog(
                "           READ IDX-FILE\n"
                "               NOT INVALID KEY DISPLAY 'FOUND'\n"
                "           END-READ."
            )
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("READ")
        assert len(stmts) >= 1
        assert stmts[0].not_invalid_key_clause is not None
```

- [ ] **Step 2: Run the tests**

```
python -m pytest tests/unit/io_statements/test_open_read_parsers.py -v
```

Expected: Check any attribute name mismatches (e.g., `open_mode`, `files`, `reposition`, `into`, `access_mode`, `key`, `with_lock`, `at_end_clause`, `not_at_end_clause`, `invalid_key_clause`, `not_invalid_key_clause`). Read `cobolparser/models/statements/io.py` and fix names.

- [ ] **Step 3: Fix attribute names if needed and re-run until all pass**

```
python -m pytest tests/unit/io_statements/test_open_read_parsers.py -v
```

- [ ] **Step 4: Verify coverage**

```
python -m pytest tests/unit/io_statements/test_open_read_parsers.py --cov=cobolparser/parsers/statements/open_parser --cov=cobolparser/parsers/statements/read_parser --cov-report=term-missing -v
```

Expected: `open_parser.py` ≥ 88%, `read_parser.py` ≥ 88%.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/io_statements/test_open_read_parsers.py
git commit -m "test: add coverage for OPEN EXTEND/IO/REPOSITION and READ INTO/KEY/LOCK/AT-END/INVALID-KEY"
```

---

## Task 4: GO TO and STOP parser coverage

**Files:**
- Create: `tests/unit/test_go_stop_parsers.py`

### What's uncovered

`go_parser.py` (73%): DEPENDING ON clause (lines 100-139 of `_parse_depending_on_clause`), missing TO keyword (lines 65-72), empty stream after GO (lines 65-67), `matches` exception path (lines 35-39).

`stop_parser.py` (76%): STOP with string literal (lines 41-43), empty start_token path (lines 24-27).

- [ ] **Step 1: Write the test file**

```python
"""Tests for GO TO and STOP statement parser coverage."""
import pytest
from cobolparser import parse_cobol
from cobolparser import CobolParser, ErrorRecoveryMode


def _prog(procedure_stmts: str) -> str:
    return f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  IDX  PIC 9.
       PROCEDURE DIVISION.
{procedure_stmts}
           STOP RUN.
    """


class TestGoParserCoverage:
    """Cover uncovered branches in go_parser.py."""

    def test_goto_basic(self):
        """GO TO PARA-1 — baseline."""
        result = parse_cobol(_prog("           GO TO PARA-1."))
        assert result.ast is not None
        stmts = result.ast.find_statements("GO")
        assert len(stmts) >= 1
        assert stmts[0].target_paragraph == "PARA-1"

    def test_goto_depending_on(self):
        """GO TO PARA-1 DEPENDING ON IDX — covers lines 100-139."""
        result = parse_cobol(_prog("           GO TO PARA-1 DEPENDING ON IDX."))
        assert result.ast is not None
        stmts = result.ast.find_statements("GO")
        assert len(stmts) >= 1
        assert stmts[0].depending_on_variable == "IDX"

    def test_goto_multiple_targets_depending(self):
        """GO TO with multiple targets DEPENDING ON covers multi-target path."""
        result = parse_cobol(
            _prog("           GO TO PARA-1 PARA-2 PARA-3 DEPENDING ON IDX.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("GO")
        assert len(stmts) >= 1

    def test_goto_missing_to_recovers(self):
        """GO without TO in error-recovery mode covers error report path (lines 65-72)."""
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(
            """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
           GO PARA-1.
           STOP RUN.
        """
        )
        # Parser should not crash; may emit error or produce partial AST
        assert result is not None


class TestStopParserCoverage:
    """Cover uncovered branches in stop_parser.py."""

    def test_stop_run(self):
        """STOP RUN — baseline, stop_type = 'RUN'."""
        result = parse_cobol(_prog(""))  # already has STOP RUN in template
        assert result.ast is not None

    def test_stop_with_string_literal(self):
        """STOP 'message' covers string literal branch (lines 41-43)."""
        result = parse_cobol(
            """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
           STOP 'HALTED'.
        """
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("STOP")
        assert len(stmts) >= 1
        stmt = stmts[0]
        # stop_type should be the literal value
        assert stmt.stop_type is not None and stmt.stop_type != "RUN"
```

- [ ] **Step 2: Run the tests**

```
python -m pytest tests/unit/test_go_stop_parsers.py -v
```

Expected: Check `target_paragraph`, `depending_on_variable`, `stop_type` attribute names against `cobolparser/models/statements/control.py`. Fix if needed.

- [ ] **Step 3: Fix attribute names and re-run until all pass**

```
python -m pytest tests/unit/test_go_stop_parsers.py -v
```

- [ ] **Step 4: Verify coverage**

```
python -m pytest tests/unit/test_go_stop_parsers.py --cov=cobolparser/parsers/statements/go_parser --cov=cobolparser/parsers/statements/stop_parser --cov-report=term-missing -v
```

Expected: `go_parser.py` ≥ 88%, `stop_parser.py` ≥ 90%.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_go_stop_parsers.py
git commit -m "test: add coverage for GO TO DEPENDING ON and STOP literal paths"
```

---

## Task 5: IBM EXEC SQL and EXEC CICS coverage

**Files:**
- Create: `tests/unit/test_ibm_exec_coverage.py`

### What's uncovered

`ibm_exec_statements.py` (61%): `ExecCicsStatementParser.matches` (lines 107-129), `ExecCicsStatementParser.parse` body with CICS content loop (lines 136-168), `ExecSqlStatementParser.matches` with IDENTIFIER-based EXEC token (lines 33-46), host-variable colon-prefix path in SQL parsing (lines 81-88).

- [ ] **Step 1: Write the test file**

```python
"""Tests for IBM EXEC SQL and EXEC CICS statement parser coverage."""
import pytest
from cobolparser import parse_cobol


def _prog(procedure_stmts: str) -> str:
    return f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
{procedure_stmts}
           STOP RUN.
    """


class TestExecSqlCoverage:
    """Cover uncovered branches in ExecSqlStatementParser."""

    def test_exec_sql_basic(self):
        """EXEC SQL SELECT covers basic SQL parsing path."""
        result = parse_cobol(
            _prog(
                "           EXEC SQL\n"
                "               SELECT COUNT(*) INTO :WS-COUNT FROM MYTABLE\n"
                "           END-EXEC."
            )
        )
        assert result.ast is not None

    def test_exec_sql_with_host_variable(self):
        """EXEC SQL with :VAR host variable covers colon-prefix path (lines 81-88)."""
        result = parse_cobol(
            _prog(
                "           EXEC SQL\n"
                "               INSERT INTO ORDERS (ID, NAME)\n"
                "               VALUES (:WS-ID, :WS-NAME)\n"
                "           END-EXEC."
            )
        )
        assert result.ast is not None

    def test_exec_sql_identifier_based_exec(self):
        """EXEC parsed as IDENTIFIER token still matches SQL parser (lines 33-46)."""
        # Use free-form COBOL where EXEC may lex as identifier
        result = parse_cobol(
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. TESTPROG.\n"
            "PROCEDURE DIVISION.\n"
            "    EXEC SQL SELECT 1 INTO :X FROM DUAL END-EXEC.\n"
            "    STOP RUN.\n"
        )
        assert result.ast is not None


class TestExecCicsCoverage:
    """Cover uncovered branches in ExecCicsStatementParser."""

    def test_exec_cics_basic(self):
        """EXEC CICS RECEIVE covers CICS parser matches + parse body (lines 107-168)."""
        result = parse_cobol(
            _prog(
                "           EXEC CICS\n"
                "               RECEIVE INTO WS-BUF\n"
                "           END-EXEC."
            )
        )
        assert result.ast is not None

    def test_exec_cics_send(self):
        """EXEC CICS SEND TEXT covers content-loop iteration."""
        result = parse_cobol(
            _prog(
                "           EXEC CICS\n"
                "               SEND TEXT FROM WS-MSG LENGTH 80\n"
                "           END-EXEC."
            )
        )
        assert result.ast is not None

    def test_exec_cics_link(self):
        """EXEC CICS LINK PROGRAM covers another CICS variant."""
        result = parse_cobol(
            _prog(
                "           EXEC CICS\n"
                "               LINK PROGRAM('SUBPROG') COMMAREA(WS-CA)\n"
                "           END-EXEC."
            )
        )
        assert result.ast is not None
```

- [ ] **Step 2: Run the tests**

```
python -m pytest tests/unit/test_ibm_exec_coverage.py -v
```

Expected: Tests pass (parsers skip to END-EXEC so CICS content doesn't need to be valid COBOL).

- [ ] **Step 3: Verify coverage**

```
python -m pytest tests/unit/test_ibm_exec_coverage.py --cov=cobolparser/parsers/statements/ibm_exec_statements --cov-report=term-missing -v
```

Expected: `ibm_exec_statements.py` ≥ 80%.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_ibm_exec_coverage.py
git commit -m "test: add coverage for EXEC CICS and EXEC SQL host-variable parsing"
```

---

## Task 6: StringStatement and UnstringStatement model coverage

**Files:**
- Create: `tests/unit/test_string_unstring_models.py`

### What's uncovered

`models/statements/data.py` (38%): `StringStatement.__init__`, `StringStatement.to_dict`, `UnstringStatement.__init__`, `UnstringStatement.to_dict`, and their setter methods. These models exist but no parser creates them, so they must be tested directly via unit instantiation.

- [ ] **Step 1: Read the model definitions**

Read `cobolparser/models/statements/data.py` lines 74–end to find all fields and methods on `StringStatement` and `UnstringStatement`.

- [ ] **Step 2: Write the test file**

```python
"""Unit tests for StringStatement and UnstringStatement AST models."""
import pytest
from cobolparser.models.statements.data import StringStatement, UnstringStatement
from cobolparser.models.ast_base import SourceLocation


LOC = SourceLocation(line=1, column=1)


class TestStringStatementModel:
    """Direct unit tests for StringStatement (no parser needed)."""

    def test_init_sets_node_type(self):
        """StringStatement node_type is 'STRING'."""
        stmt = StringStatement(LOC)
        assert stmt.node_type == "STRING"

    def test_init_default_fields(self):
        """StringStatement starts with empty/None fields."""
        stmt = StringStatement(LOC)
        assert stmt.on_overflow is None
        assert stmt.not_on_overflow is None
        assert stmt.operands == []

    def test_to_dict_contains_node_type(self):
        """to_dict includes node_type key."""
        stmt = StringStatement(LOC)
        d = stmt.to_dict()
        assert d["node_type"] == "STRING"

    def test_to_dict_contains_location(self):
        """to_dict includes location."""
        stmt = StringStatement(LOC)
        d = stmt.to_dict()
        assert "location" in d

    def test_to_dict_roundtrip(self):
        """to_dict output is a non-empty dict."""
        stmt = StringStatement(LOC)
        d = stmt.to_dict()
        assert isinstance(d, dict)
        assert len(d) > 0


class TestUnstringStatementModel:
    """Direct unit tests for UnstringStatement (no parser needed)."""

    def test_init_sets_node_type(self):
        """UnstringStatement node_type is 'UNSTRING'."""
        stmt = UnstringStatement(LOC)
        assert stmt.node_type == "UNSTRING"

    def test_init_default_fields(self):
        """UnstringStatement starts with expected defaults."""
        stmt = UnstringStatement(LOC)
        assert stmt.on_overflow is None
        assert stmt.not_on_overflow is None

    def test_to_dict_contains_node_type(self):
        """to_dict includes node_type key."""
        stmt = UnstringStatement(LOC)
        d = stmt.to_dict()
        assert d["node_type"] == "UNSTRING"

    def test_to_dict_roundtrip(self):
        """to_dict output is a non-empty dict."""
        stmt = UnstringStatement(LOC)
        d = stmt.to_dict()
        assert isinstance(d, dict)
        assert len(d) > 0
```

**Note:** After reading `data.py` in Step 1, add tests for any setter methods found (e.g. `set_source`, `add_delimited_by`, etc.).

- [ ] **Step 3: Run the tests**

```
python -m pytest tests/unit/test_string_unstring_models.py -v
```

Expected: All PASS (these are pure model tests with no parsing).

- [ ] **Step 4: Verify coverage**

```
python -m pytest tests/unit/test_string_unstring_models.py --cov=cobolparser/models/statements/data --cov-report=term-missing -v
```

Expected: `data.py` ≥ 70% (up from 38%).

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_string_unstring_models.py
git commit -m "test: add unit coverage for StringStatement and UnstringStatement AST models"
```

---

## Task 7: IO Diagnostics module coverage

**Files:**
- Create: `tests/unit/analysis/test_io_diagnostics.py`

### What's uncovered

`analysis/io_diagnostics.py` (0%): All 57 lines. `IOErrorCode` enum (all values), `IODiagnosticHelper.get_error_message()`, `IODiagnosticHelper.create_io_error()`, `IODiagnosticHelper.validate_io_statement_type()`.

- [ ] **Step 1: Write the test file**

```python
"""Unit tests for IODiagnosticHelper and IOErrorCode — currently at 0% coverage."""
import pytest
from cobolparser.analysis.io_diagnostics import IOErrorCode, IODiagnosticHelper
from cobolparser._errors import ParseError


class TestIOErrorCodeEnum:
    """Verify all IOErrorCode enum members are accessible."""

    def test_read_error_codes_exist(self):
        assert IOErrorCode.IO_READ_INVALID_KEY_ORDER.value == "IO_READ_INVALID_KEY_ORDER"
        assert IOErrorCode.IO_READ_LOCK_ON_SEQUENTIAL.value == "IO_READ_LOCK_ON_SEQUENTIAL"
        assert IOErrorCode.IO_READ_AT_END_WITHOUT_FILE.value == "IO_READ_AT_END_WITHOUT_FILE"

    def test_write_error_codes_exist(self):
        assert IOErrorCode.IO_WRITE_ADVANCING_INVALID_UNIT.value == "IO_WRITE_ADVANCING_INVALID_UNIT"
        assert IOErrorCode.IO_WRITE_DELETE_INVALID_ORG.value == "IO_WRITE_DELETE_INVALID_ORG"

    def test_open_error_codes_exist(self):
        assert IOErrorCode.IO_OPEN_INVALID_MODE.value == "IO_OPEN_INVALID_MODE"
        assert IOErrorCode.IO_OPEN_REEL_ON_DISK.value == "IO_OPEN_REEL_ON_DISK"

    def test_close_error_codes_exist(self):
        assert IOErrorCode.IO_CLOSE_NO_REWIND_INVALID.value == "IO_CLOSE_NO_REWIND_INVALID"
        assert IOErrorCode.IO_CLOSE_WITH_LOCK_INVALID.value == "IO_CLOSE_WITH_LOCK_INVALID"

    def test_start_error_codes_exist(self):
        assert IOErrorCode.IO_START_INVALID_ORG.value == "IO_START_INVALID_ORG"
        assert IOErrorCode.IO_START_MISSING_KEY.value == "IO_START_MISSING_KEY"
        assert IOErrorCode.IO_START_INVALID_KEY_CONDITION.value == "IO_START_INVALID_KEY_CONDITION"

    def test_all_codes_are_strings(self):
        """Every IOErrorCode value is a non-empty string."""
        for code in IOErrorCode:
            assert isinstance(code.value, str)
            assert len(code.value) > 0


class TestIODiagnosticHelperGetMessage:
    """Tests for IODiagnosticHelper.get_error_message()."""

    def test_known_code_returns_message(self):
        msg = IODiagnosticHelper.get_error_message(IOErrorCode.IO_READ_LOCK_ON_SEQUENTIAL)
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_all_codes_have_messages(self):
        """Every IOErrorCode should have an entry in ERROR_MESSAGES."""
        for code in IOErrorCode:
            msg = IODiagnosticHelper.get_error_message(code)
            assert isinstance(msg, str), f"No message for {code}"
            assert len(msg) > 0, f"Empty message for {code}"

    def test_message_contains_useful_text(self):
        msg = IODiagnosticHelper.get_error_message(IOErrorCode.IO_START_INVALID_ORG)
        assert "indexed" in msg.lower() or "relative" in msg.lower() or "sequential" in msg.lower()


class TestIODiagnosticHelperCreateError:
    """Tests for IODiagnosticHelper.create_io_error()."""

    def test_returns_parse_error(self):
        err = IODiagnosticHelper.create_io_error(IOErrorCode.IO_READ_LOCK_ON_SEQUENTIAL)
        assert isinstance(err, ParseError)

    def test_error_has_code_attribute(self):
        err = IODiagnosticHelper.create_io_error(IOErrorCode.IO_OPEN_INVALID_MODE)
        assert hasattr(err, "code")
        assert err.code == "IO_OPEN_INVALID_MODE"

    def test_error_message_from_code(self):
        err = IODiagnosticHelper.create_io_error(IOErrorCode.IO_CLOSE_NO_REWIND_INVALID)
        expected = IODiagnosticHelper.get_error_message(IOErrorCode.IO_CLOSE_NO_REWIND_INVALID)
        assert expected in err.message

    def test_error_with_context(self):
        err = IODiagnosticHelper.create_io_error(
            IOErrorCode.IO_START_INVALID_ORG,
            line=10,
            column=5,
            context="CLOSE TAPEFILE WITH NO REWIND"
        )
        assert "CLOSE TAPEFILE WITH NO REWIND" in err.message

    def test_error_with_line_and_column(self):
        err = IODiagnosticHelper.create_io_error(
            IOErrorCode.IO_DELETE_INVALID_ORG, line=42, column=8
        )
        assert err.line == 42
        assert err.column == 8


class TestIODiagnosticHelperValidate:
    """Tests for IODiagnosticHelper.validate_io_statement_type()."""

    def test_no_org_returns_none(self):
        """No file organization info → no error."""
        result = IODiagnosticHelper.validate_io_statement_type("START")
        assert result is None

    def test_start_on_sequential_returns_error(self):
        result = IODiagnosticHelper.validate_io_statement_type("START", "SEQUENTIAL")
        assert result == IOErrorCode.IO_START_INVALID_ORG

    def test_start_on_indexed_returns_none(self):
        result = IODiagnosticHelper.validate_io_statement_type("START", "INDEXED")
        assert result is None

    def test_rewrite_on_sequential_returns_error(self):
        result = IODiagnosticHelper.validate_io_statement_type("REWRITE", "SEQUENTIAL")
        assert result == IOErrorCode.IO_REWRITE_INVALID_ORG

    def test_delete_on_sequential_returns_error(self):
        result = IODiagnosticHelper.validate_io_statement_type("DELETE", "SEQUENTIAL")
        assert result == IOErrorCode.IO_DELETE_INVALID_ORG

    def test_delete_on_indexed_returns_none(self):
        result = IODiagnosticHelper.validate_io_statement_type("DELETE", "INDEXED")
        assert result is None

    def test_unlock_on_relative_returns_error(self):
        result = IODiagnosticHelper.validate_io_statement_type("UNLOCK", "RELATIVE")
        assert result == IOErrorCode.IO_UNLOCK_INVALID_ORG

    def test_unlock_on_indexed_returns_none(self):
        result = IODiagnosticHelper.validate_io_statement_type("UNLOCK", "INDEXED")
        assert result is None

    def test_case_insensitive_org(self):
        """Validation is case-insensitive."""
        result = IODiagnosticHelper.validate_io_statement_type("start", "sequential")
        assert result == IOErrorCode.IO_START_INVALID_ORG

    def test_read_on_any_org_returns_none(self):
        """READ is valid on all organizations."""
        for org in ("SEQUENTIAL", "INDEXED", "RELATIVE"):
            result = IODiagnosticHelper.validate_io_statement_type("READ", org)
            assert result is None, f"READ should be valid on {org}"
```

- [ ] **Step 2: Run the tests**

```
python -m pytest tests/unit/analysis/test_io_diagnostics.py -v
```

Expected: All PASS (pure unit tests on a plain Python module).

If `ParseError` doesn't have a `.message` attribute, check `cobolparser/_errors.py` and fix the assertion to use the actual attribute name.

- [ ] **Step 3: Verify coverage**

```
python -m pytest tests/unit/analysis/test_io_diagnostics.py --cov=cobolparser/analysis/io_diagnostics --cov-report=term-missing -v
```

Expected: `io_diagnostics.py` ≥ 90% (from 0%).

- [ ] **Step 4: Commit**

```bash
git add tests/unit/analysis/test_io_diagnostics.py
git commit -m "test: add full coverage for IODiagnosticHelper and IOErrorCode (was 0%)"
```

---

## Task 8: Full suite — verify overall coverage target

**Files:**
- Modify (if needed): any test file from Tasks 1–7

- [ ] **Step 1: Run the full test suite with coverage**

```
python -m pytest tests/ --cov=cobolparser --cov-report=term-missing -q
```

Expected: `TOTAL ≥ 88%`, required minimum of 81% still met, 0 regressions.

- [ ] **Step 2: Identify any remaining files below 75%**

From the output, note any files still below 75%. Priority fixes:

- `models/statements/misc.py` (70%) — add `SelectStatement` method tests to `tests/unit/test_select_clauses.py`
- `models/statements/control.py` (72%) — add `WhenClause` / `SearchStatement` model tests
- `analysis/io_coverage_reporter.py` (72%) — run `tests/integration/io/test_io_coverage_reporting.py` and check what's still uncovered

- [ ] **Step 3: Add targeted fill-in tests for any remaining gaps**

For `models/statements/misc.py` — add direct model instantiation tests to `tests/unit/test_select_clauses.py`:

```python
from cobolparser.models.statements.misc import SelectStatement, CopyStatement
from cobolparser.models.ast_base import SourceLocation

LOC = SourceLocation(1, 1)

def test_select_statement_to_dict():
    stmt = SelectStatement(LOC)
    stmt.file_name = "MY-FILE"
    d = stmt.to_dict()
    assert d["node_type"] == "SELECT"
    assert "file_name" in d or "MY-FILE" in str(d)

def test_copy_statement_to_dict():
    from cobolparser.models.statements.misc import CopyStatement
    stmt = CopyStatement(LOC)
    d = stmt.to_dict()
    assert d["node_type"] == "COPY"
```

- [ ] **Step 4: Run suite again and confirm ≥ 88%**

```
python -m pytest tests/ --cov=cobolparser --cov-report=term-missing -q
```

- [ ] **Step 5: Final commit**

```bash
git add -u
git commit -m "test: fill remaining coverage gaps — overall suite ≥ 88%"
```
