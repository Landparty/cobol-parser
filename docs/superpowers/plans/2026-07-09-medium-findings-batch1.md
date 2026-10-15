# Medium Findings Batch 1 (M1,M2,M3,M4,M5,M7,M8,M9,M14,M16) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 10 well-contained MEDIUM findings from `reports/open-findings.md` (M1, M2, M3, M4, M5, M7, M8, M9, M14, M16), each with a TDD-driven repro-becomes-regression-test cycle, matching the rigor already applied to H1-H9.

**Architecture:** Each finding is an isolated bug fix in the existing parser/preprocessor pipeline (lexer -> preprocess -> parser -> AST). No new subsystems. Findings are grouped into tasks by which source files they touch, so no file is edited by two different tasks.

**Tech Stack:** Python 3.11+, optional Cython acceleration (`_preprocess_fast.pyx`, compiled `.pyd`/`.c`), pytest.

**Explicitly out of scope for this batch** (per user decision): M6, M10, M11, M12, M13, M15 (each is close to its own subsystem — deferred to separate plans) and M17 (test-coverage debt, not a bug).

## Global Constraints

- Python `>=3.11`. No new runtime dependencies (zero-dependency core library).
- Every new/changed behavior needs a regression test in
  `tests/regression/test_open_findings_medium_regressions.py` (new file,
  mirrors `test_open_findings_high_regressions.py`'s per-finding
  `TestM<N>...` class convention).
- Coverage floor: 81% (`pytest --cov-fail-under=81`); a subset run will
  legitimately fail this — that's expected, ignore it for single-file runs.
- **Cython trap:** `cobolparser/_preprocess_fast.pyx` is compiled to a
  `.pyd`/`.so` that is what actually runs (`preprocess/__init__.py` imports
  it and shadows the pure-Python `normalize_fixed_format` silently). Any
  change to `preprocess/__init__.py`'s `normalize_fixed_format` MUST be
  mirrored in `_preprocess_fast.pyx`, then rebuilt with
  `python setup.py build_ext --inplace`, and the regenerated
  `_preprocess_fast.c` must be committed alongside the `.pyx`. Skipping the
  rebuild means tests silently run against the stale compiled extension.
- After the rebuild, verify both code paths behave identically (there is
  an existing `_normalize_fixed_format_pure` private alias for this;
  precedent: `test_fast_preprocess_is_active`).
- Run the full sample/regression suite once at the end (not just the new
  tests) because M4 flips a default (D-column-7 lines: code -> comment) —
  this is a real behavior change that could affect any fixture relying on
  the old (undocumented, inconsistent) behavior.
- End of batch: update `CHANGELOG.md` (Unreleased -> Fixed), update
  `reports/open-findings.md` (move M1,M2,M3,M4,M5,M7,M8,M9,M14,M16 out of
  "open", noting residuals same style as H6/H9), refresh the relevant
  `.okf/` concept files (`.okf/lexer.md`, `.okf/parser.md`,
  `.okf/preprocessing.md`) per this repo's CLAUDE.md OKF policy, and run
  `/okf:validate .okf --strict` before committing (the pre-commit hook
  blocks on OKF staleness).

---

## Root causes (reference — verified empirically against current `main`, commit `7405700`)

| Finding | File:Line | Root cause |
|---|---|---|
| M16 | `cobolparser/parsers/divisions/data.py` `_PICTURE_SYMBOL_TOKEN_TYPES` (~line 100-108) | Uses `TokenType.DIVIDE` and `TokenType.MULTIPLY` (the DIVIDE/MULTIPLY **statement** keywords) instead of `TokenType.DIVIDE_OP`/`TokenType.MULTIPLY_OP` (what `/` and `*` actually lex to per `lexer.py:381,380`). Picture pattern collection silently stops at the first `/` or `*`, leaving the remainder to be misparsed as new data items. |
| M14 | `cobolparser/preprocess/copybook_expander.py` `_expand_source_recursive`, cache-hit branch (~line 571-573) | `context.total_bytes` is only incremented in the cache-miss branch; a cache hit (diamond dependency) contributes 0 bytes even though real content is inserted into the expansion. |
| M9 | `cobolparser/parsers/statements/_utils.py` `try_parse_nested_statement` (~line 686-724) | `except Exception as exc:` logs at DEBUG only and returns `None`. Exceptions that bypass `report_or_raise` (raised directly by e.g. `token_stream.expect()`) never reach `ParseResult.errors`/`.warnings`. |
| M7 | `cobolparser/lexer.py` `read_prefixed_literal_from_text` (~line 1261-1323) | No hex-digit / even-length validation for `X'..'`/`NX'..'` typed literals; malformed hex is accepted silently. |
| M4 | `cobolparser/preprocess/__init__.py` `normalize_fixed_format` (~line 494-496) and `_preprocess_fast.pyx` (~line 60) | Only `*`/`/` are treated as comment indicators; `D`/`d` falls through as live code, disagreeing with `copy_statement_parser.is_comment_line()` which already treats `D`/`d` as comment. |
| M5 | `cobolparser/preprocess/__init__.py:534` and `_preprocess_fast.pyx:140` (opening line), plus the literal-continuation branch (~line 513-514 / ~line 80) | `rstrip()` unconditionally strips trailing blanks from a line even when a literal is left open at end-of-line, where those blanks are semantically part of the literal per fixed-format continuation rules. |
| M8 | `cobolparser/preprocess/__init__.py` `normalize_fixed_format` and `_preprocess_fast.pyx` | No tab expansion before column-index slicing; a tab shifts every subsequent column. |
| M1 | `cobolparser/parsers/statements/display_parser.py` display-item loop (~line 121-125) | Accepted token types for a display item are `STRING_LITERAL`/`IDENTIFIER`/`NUMERIC_LITERAL`; `TokenType.FIGURATIVE_CONSTANT` (what `SPACE`/`ZERO`/etc. lex to) is missing. |
| M2 | `cobolparser/parsers/statements/display_parser.py` | No handling for `TokenType.WITH`/`TokenType.NO`/`TokenType.ADVANCING` — the loop's final `else: break` stops on `WITH`, leaving `NO ADVANCING` unconsumed. |
| M3 | `cobolparser/parsers/statements/display_parser.py`, `accept_parser.py`, `cobolparser/models/statements/data.py` (`DisplayStatement`), `cobolparser/models/statements/io.py` (`IOAcceptStatement`) | No handling for `TokenType.AT` positioning or the extended ACCEPT clauses at all. |

**M3 corpus-evidence scope decision** (from `examples/cobol/shamrice/*.cbl`, the corpus the audit's hit-counts came from):
- `AT <4-digit-numeric>` (combined LLCC form, e.g. `AT 0132`): **34 confirmed hits** (27 DISPLAY + 7 ACCEPT). This is the dominant real-world form — implement it.
- `AT LINE n [COLUMN m]` keyword form: **0 hits** in this corpus, but documented IBM syntax and cheap to add alongside the numeric form — implement it too (purely additive, no risk).
- `SECURE` (1 hit, `accept-secure.cbl`): confirmed. Per that file's own comment, **SECURE is NOT a NO-ECHO synonym** — it shows `*` per character where NO-ECHO shows nothing. Model as a distinct field.
- `NO-ECHO` (1 hit, `accept.cbl`): confirmed, lexes as **one hyphenated IDENTIFIER token** `"no-echo"`, not two tokens `NO` + `ECHO`.
- `TIMEOUT <numeric>` (1 hit): confirmed, e.g. `ACCEPT ws-input TIMEOUT 3 AT 0132`.
- `AUTO-SKIP` (1 hit + 1 combined `WITH AUTO-SKIP NO-ECHO`): confirmed, one hyphenated IDENTIFIER token.
- `UPPER` (1 hit): confirmed, bare IDENTIFIER keyword.
- `CURSOR`, `BEEP`/`BELL`, `COLOR` (FOREGROUND-COLOR/BACKGROUND-COLOR), `UPDATE`, `BLANK SCREEN`: **not implemented this pass** — zero-to-one corpus hits, and (for COLOR especially) the real grammar is a GnuCOBOL-flavored two-part clause not confidently specified by the finding text. Leave as documented residuals in the report update (Task 10), same convention as H6/H9's residual-gap sections.

---

## Task 1: M16 — PIC clause stops at `/` and `*` (wrong TokenType)

**Files:**
- Modify: `cobolparser/parsers/divisions/data.py:100-108` (`_PICTURE_SYMBOL_TOKEN_TYPES`)
- Test: `tests/regression/test_open_findings_medium_regressions.py` (new file)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: nothing consumed by later tasks (independent).

- [ ] **Step 1: Write the failing tests**

Create `tests/regression/test_open_findings_medium_regressions.py`:

```python
"""Regression tests for the MEDIUM-severity findings in reports/open-findings.md.

Mirrors tests/regression/test_open_findings_high_regressions.py's convention:
one TestM<N>... class per finding, named for direct traceability.
"""

from __future__ import annotations

import textwrap

from cobolparser import parse_cobol
from cobolparser.models.statements import DisplayStatement


def _data_program(data_item_line: str) -> str:
    """Wrap a single WORKING-STORAGE data-item line in a minimal program."""
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. REGTEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        {data_item_line}
        PROCEDURE DIVISION.
        MAIN-PARA.
            DISPLAY "OK".
            STOP RUN.
        """)


def _proc_program(procedure_body: str) -> str:
    """Wrap bare PROCEDURE DIVISION statements in a minimal COBOL program."""
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. REGTEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-X PIC X(20).
        PROCEDURE DIVISION.
        MAIN-PARA.
        {procedure_body}
        """)


def _statements(result):
    proc = result.ast.procedure_division
    if proc.paragraphs:
        return proc.paragraphs[0].statements
    if proc.sections and proc.sections[0].paragraphs:
        return proc.sections[0].paragraphs[0].statements
    return []


class TestM16SlashEditedPicture:
    """M16 -- PIC 99/99/99 corrupted DATA DIVISION structure.

    _PICTURE_SYMBOL_TOKEN_TYPES used TokenType.DIVIDE/MULTIPLY (the DIVIDE/
    MULTIPLY *statement* keywords) instead of TokenType.DIVIDE_OP/
    MULTIPLY_OP (what '/' and '*' actually lex to), so picture pattern
    collection stopped at the first edit symbol and the remainder was
    misparsed as phantom level-99 data items.
    """

    def test_slash_edited_picture_pattern_is_not_truncated(self):
        result = parse_cobol(
            _data_program("    05 WS-FIELD PIC 99/99/99.")
        )
        assert result.errors == []
        items = result.ast.find_all_by_type("CobolDataItem")
        names = [i.name for i in items]
        assert "WS-FIELD" in names
        assert not any(n.startswith("ANONYMOUS-99") for n in names), names
        field = next(i for i in items if i.name == "WS-FIELD")
        assert field.picture_clause.pattern == "99/99/99"
        assert not any("Unparsed token" in w for w in result.warnings), result.warnings

    def test_check_protect_asterisk_picture_pattern_is_not_truncated(self):
        result = parse_cobol(
            _data_program("    01 WS-AMT PIC $***,**9.99.")
        )
        assert result.errors == []
        items = result.ast.find_all_by_type("CobolDataItem")
        field = next(i for i in items if i.name == "WS-AMT")
        assert field.picture_clause.pattern == "$***,**9.99"
        assert not any("Unparsed token" in w for w in result.warnings), result.warnings
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/regression/test_open_findings_medium_regressions.py -v`
Expected: `TestM16SlashEditedPicture` FAILs (pattern truncated to `"99"` / `"$"`, phantom `ANONYMOUS-99-*` items present).

- [ ] **Step 3: Fix the token types**

In `cobolparser/parsers/divisions/data.py`, change:

```python
_PICTURE_SYMBOL_TOKEN_TYPES: frozenset[TokenType] = frozenset(
    {
        TokenType.CURRENCY,
        TokenType.MINUS,
        TokenType.PLUS,
        TokenType.MULTIPLY,
        TokenType.DIVIDE,
    }
)
```

to:

```python
_PICTURE_SYMBOL_TOKEN_TYPES: frozenset[TokenType] = frozenset(
    {
        TokenType.CURRENCY,
        TokenType.MINUS,
        TokenType.PLUS,
        TokenType.MULTIPLY_OP,  # '*' (check-protect symbol) -- not the
        TokenType.DIVIDE_OP,  # '/' (stroke/slash editing symbol) -- not the
        # MULTIPLY/DIVIDE *statement* keyword tokens (see reports/open-
        # findings.md M16 for the bug this fixes).
    }
)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/regression/test_open_findings_medium_regressions.py::TestM16SlashEditedPicture -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cobolparser/parsers/divisions/data.py tests/regression/test_open_findings_medium_regressions.py
git commit -m "fix(parser): M16 -- PIC clause no longer truncates at / or * (wrong TokenType)"
```

---

## Task 2: M14 — Copybook cache hits bypass `total_bytes` accounting

**Files:**
- Modify: `cobolparser/preprocess/copybook_expander.py` `_expand_source_recursive` (~line 571-573)
- Test: `tests/regression/test_open_findings_medium_regressions.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing (independent).

- [ ] **Step 1: Write the failing test**

Append to the regression test file (needs `tempfile`/`os` imports and a
helper — add at top of file: `import os`, `import tempfile`):

```python
class TestM14CacheHitBytesAccounting:
    """M14 -- copybook cache hits bypassed total_bytes accounting.

    context.total_bytes was only incremented on a cache miss; a copybook
    served from the intra-expansion cache (diamond dependency: the same
    member COPYd multiple times) contributed zero bytes to the running
    total, so max_total_size was never enforced against the true expanded
    content size.
    """

    def test_repeated_copy_of_same_member_counts_every_inclusion(self, tmp_path):
        from cobolparser.preprocess import expand_copybooks
        from cobolparser.preprocess import TotalExpansionSizeExceededError
        from cobolparser.preprocess.models import CopybookSearchPath

        copybook_dir = tmp_path / "copybooks"
        copybook_dir.mkdir()
        # 76-byte payload (matches the finding's repro size).
        payload = "01 WS-FIELD-" + "X" * 60 + " PIC X.\n"
        (copybook_dir / "MEMBER.cpy").write_text(payload)

        source = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. REGTEST.\n"
            "DATA DIVISION.\n"
            "WORKING-STORAGE SECTION.\n"
            "       COPY MEMBER.\n"
            "       COPY MEMBER.\n"
            "       COPY MEMBER.\n"
        )
        search_paths = [CopybookSearchPath(directory=str(copybook_dir), extensions=[".cpy"])]

        try:
            expand_copybooks(
                source, copybook_paths=search_paths, max_total_size=96
            )
            raised = False
        except TotalExpansionSizeExceededError:
            raised = True
        assert raised, (
            "3x inclusion of a copybook whose combined size exceeds "
            "max_total_size must raise, even when later inclusions are "
            "served from the intra-expansion cache"
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/regression/test_open_findings_medium_regressions.py::TestM14CacheHitBytesAccounting -v`
Expected: FAIL (no exception raised — check the actual `CopybookSearchPath`/`expand_copybooks` call signature against `cobolparser/preprocess/models.py` and `copybook_expander.py`'s public entry point first if this errors on signature mismatch rather than assertion; adjust the test call to match the real signature, the behavior under test is unaffected).

- [ ] **Step 3: Fix the cache-hit branch**

In `cobolparser/preprocess/copybook_expander.py`, in `_expand_source_recursive`, change:

```python
        expanded_copybook = context.cache_get(full_cache_key)
        if expanded_copybook is not None:
            nested_depth = context.current_depth + 1
        else:
```

to:

```python
        expanded_copybook = context.cache_get(full_cache_key)
        if expanded_copybook is not None:
            nested_depth = context.current_depth + 1
            # A cache hit still inserts real content into the expansion
            # (diamond dependency: same member COPYd multiple times) --
            # it must count toward total_bytes the same as a miss does,
            # or max_total_size silently under-enforces (M14).
            content_size = len(expanded_copybook.encode("utf-8"))
            context.total_bytes += content_size
            if stats:
                stats.total_bytes_processed = context.total_bytes
            if context.total_bytes > path_resolver.search_config.max_total_size:
                raise TotalExpansionSizeExceededError(
                    context.total_bytes, path_resolver.search_config.max_total_size
                )
        else:
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/regression/test_open_findings_medium_regressions.py::TestM14CacheHitBytesAccounting -v`
Expected: PASS

- [ ] **Step 5: Run the full copybook expansion suite to check for regressions**

Run: `python -m pytest tests/unit/test_copybook_expansion.py tests/contracts/test_copybook_expansion_contracts.py tests/integration/test_copybook_expansion_integration.py -v`
Expected: All PASS (same pass/skip counts as before this change -- 12 tests were already permanently skipped per the report's Test/tooling section; that count should not change).

- [ ] **Step 6: Commit**

```bash
git add cobolparser/preprocess/copybook_expander.py tests/regression/test_open_findings_medium_regressions.py
git commit -m "fix(preprocess): M14 -- copybook cache hits now count toward total_bytes"
```

---

## Task 3: M9 — `try_parse_nested_statement` swallows exceptions with no trace

**Files:**
- Modify: `cobolparser/parsers/statements/_utils.py` `try_parse_nested_statement` (~line 686-724)
- Test: `tests/regression/test_open_findings_medium_regressions.py` (append)

**Interfaces:**
- Consumes: `get_parse_context(stream)` (already defined earlier in the same file, ~line 617).
- Produces: nothing (independent).

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestM9NestedStatementSwallowedException:
    """M9 -- try_parse_nested_statement's bare except Exception had no
    trace at all (not even a warning) for exceptions that bypass
    report_or_raise, e.g. TokenMismatch/UnexpectedEndOfInput raised
    directly by token_stream.expect().
    """

    def test_unrecorded_exception_surfaces_as_warning(self, monkeypatch):
        from cobolparser.parsers.statements import _utils

        class _FakeRegistry:
            def find_parser(self, stream):
                return self

            def parse(self, stream):
                raise ValueError("boom -- not routed through report_or_raise")

        class _FakeStream:
            _registry = _FakeRegistry()
            context = None

        collected_warnings = []

        class _FakeHost:
            def add_warning(self, message):
                collected_warnings.append(message)

        class _FakeContext:
            host = _FakeHost()

        monkeypatch.setattr(
            _utils, "get_parse_context", lambda stream: _FakeContext()
        )

        result = _utils.try_parse_nested_statement(_FakeStream())

        assert result is None
        assert len(collected_warnings) == 1
        assert "boom" in collected_warnings[0]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/regression/test_open_findings_medium_regressions.py::TestM9NestedStatementSwallowedException -v`
Expected: FAIL (`collected_warnings` is empty — nothing was recorded).

- [ ] **Step 3: Fix `try_parse_nested_statement`**

In `cobolparser/parsers/statements/_utils.py`, change the `except` block:

```python
    except Exception as exc:
        # Exploratory nested dispatch must never raise (the real error is
        # surfaced via the parse context); log at debug for diagnosability.
        logger.debug("try_parse_nested suppressed %r", exc, exc_info=True)
        return None
```

to:

```python
    except Exception as exc:
        # Exploratory nested dispatch must never raise (the real error is
        # surfaced via the parse context when report_or_raise pre-records
        # it into host.errors before raising). Exceptions that bypass
        # report_or_raise entirely -- e.g. TokenMismatch/UnexpectedEndOfInput
        # raised directly by token_stream.expect() -- would otherwise vanish
        # with only this DEBUG line; surface those as a warning so a caller
        # checking ParseResult.warnings isn't blind to the failure (M9).
        logger.debug("try_parse_nested suppressed %r", exc, exc_info=True)
        if not getattr(exc, "_already_recorded", False):
            context = get_parse_context(stream)
            host = getattr(context, "host", None) if context else None
            add_warning = getattr(host, "add_warning", None)
            if callable(add_warning):
                add_warning(
                    f"Nested statement parse failed and was skipped: {exc}"
                )
        return None
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/regression/test_open_findings_medium_regressions.py::TestM9NestedStatementSwallowedException -v`
Expected: PASS

- [ ] **Step 5: Run the broader statement-parser suite**

Run: `python -m pytest tests/unit/test_utils_clause_collection.py tests/integration -k "perform or evaluate or if" -v`
Expected: All PASS -- this change only adds a warning path when an exception was NOT already recorded; it must not change control flow for the (much more common) `report_or_raise` path, which already sets `_already_recorded`.

- [ ] **Step 6: Commit**

```bash
git add cobolparser/parsers/statements/_utils.py tests/regression/test_open_findings_medium_regressions.py
git commit -m "fix(parser): M9 -- surface exceptions swallowed by try_parse_nested_statement as warnings"
```

---

## Task 4: M7 — Typed hex literals (`X'..'`, `NX'..'`) accepted with invalid content

**Files:**
- Modify: `cobolparser/lexer.py` `read_prefixed_literal_from_text` (~line 1261-1323)
- Test: `tests/regression/test_open_findings_medium_regressions.py` (append)

**Interfaces:**
- Consumes: `self.warnings` (already exists on `CobolLexer`, line 655), `LexerError`/`self.errors` (already exists).
- Produces: nothing (independent).

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestM7TypedLiteralHexValidation:
    """M7 -- typed X'..'/NX'..' literals had no hex-validity or
    even-length check; malformed hex was accepted with no diagnostic.
    """

    def test_odd_length_hex_literal_warns(self):
        result = parse_cobol(
            _proc_program('    MOVE X\'ABC\' TO WS-X.\n')
        )
        assert any(
            "odd" in w.lower() or "hex" in w.lower() for w in result.warnings
        ), result.warnings

    def test_invalid_hex_digit_warns(self):
        result = parse_cobol(
            _proc_program('    MOVE X\'ZZ\' TO WS-X.\n')
        )
        assert any(
            "hex" in w.lower() for w in result.warnings
        ), result.warnings

    def test_valid_hex_literal_does_not_warn(self):
        result = parse_cobol(
            _proc_program('    MOVE X\'1F2A\' TO WS-X.\n')
        )
        assert not any(
            "hex" in w.lower() for w in result.warnings
        ), result.warnings
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/regression/test_open_findings_medium_regressions.py::TestM7TypedLiteralHexValidation -v`
Expected: FAIL on the first two tests (no warnings emitted today).

- [ ] **Step 3: Add hex validation**

In `cobolparser/lexer.py`, in `read_prefixed_literal_from_text`, after the
existing unterminated-literal handling and before `return token, new_pos`
(i.e. right before the final `assert token is not None` / `token.raw_value
= ...` block at the end of the method), add a validity check that only
applies to the `X`/`NX` hex prefixes:

```python
        assert token is not None
        token.raw_value = text[start_pos:new_pos]
        token.location = location

        # Hex-content validation for X'..'/NX'..' typed literals only
        # (G'..'/N'..' have different, codepage-dependent validity rules
        # that this parser does not attempt to decode -- M7 scopes this
        # fix to the unambiguous hex case).
        if first.upper() in ("X", "N") and prefix_len in (1, 2):
            is_hex_prefix = first.upper() == "X" or (
                prefix_len == 2 and text[start_pos : start_pos + 2].upper() == "NX"
            )
            if is_hex_prefix and not unterminated:
                hex_content = token.value or ""
                if hex_content:
                    invalid_chars = set(hex_content) - set("0123456789ABCDEFabcdef")
                    if invalid_chars:
                        self.warnings.append(
                            f"Invalid hex digit(s) {sorted(invalid_chars)!r} in "
                            f"typed literal {token.raw_value} at line "
                            f"{location.line}, column {location.column}"
                        )
                    elif len(hex_content) % 2 != 0:
                        self.warnings.append(
                            f"Typed literal {token.raw_value} at line "
                            f"{location.line}, column {location.column} has an "
                            "odd number of hex digits (each byte needs two)"
                        )
        return token, new_pos
```

Note: `first` and `prefix_len` are already local variables earlier in this
method (see the existing prefix-detection code above the quote-reading
call) -- reuse them, do not redeclare.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/regression/test_open_findings_medium_regressions.py::TestM7TypedLiteralHexValidation -v`
Expected: PASS

- [ ] **Step 5: Run the full lexer suite**

Run: `python -m pytest tests/unit/test_lexer.py tests/unit/test_lexer_multiline_strings.py tests/unit/test_lexer_multiline_edge_cases.py -v`
Expected: All PASS -- confirm no existing typed-literal test asserts zero warnings for a case that happens to be odd-length/invalid hex (if one does, it was asserting the bug; update it to expect the new warning).

- [ ] **Step 6: Commit**

```bash
git add cobolparser/lexer.py tests/regression/test_open_findings_medium_regressions.py
git commit -m "fix(lexer): M7 -- warn on invalid/odd-length hex content in X'..'/NX'..' literals"
```

---

## Task 5: M4 + M5 + M8 — `normalize_fixed_format` (D-lines, literal trailing blanks, tabs)

This task touches the **same function** in two files (pure-Python and
Cython) for three related findings; doing them together avoids three
separate edits to the same hot spot.

**Files:**
- Modify: `cobolparser/preprocess/__init__.py` `normalize_fixed_format` (~line 403-552)
- Modify: `cobolparser/_preprocess_fast.pyx` `normalize_fixed_format` (whole file, mirrors the above)
- Regenerate: `cobolparser/_preprocess_fast.c` (via `build_ext --inplace`)
- Test: `tests/regression/test_open_findings_medium_regressions.py` (append)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: nothing consumed by later tasks (independent), but **must run
  before** Tasks 6-9 only in the sense that they share no code — order is
  arbitrary, listed here for file-cluster grouping only.

- [ ] **Step 1: Write the failing tests**

Append (needs `from cobolparser.preprocess import normalize_fixed_format`
and, for the parity check, the private pure alias):

```python
class TestM4DebugLineHandling:
    """M4 -- D/d in column 7 fell through as live code in
    normalize_fixed_format, disagreeing with copy_statement_parser's
    is_comment_line() (which already treats D/d as comment). Default
    behavior now matches is_comment_line(); a debug_lines_as_comments=False
    override is available for callers that need D-lines compiled as code.
    """

    def _line(self, indicator: str, text: str) -> str:
        # cols 1-6 seq area, col 7 indicator, cols 8+ text
        return " " * 6 + indicator + text

    def test_d_line_is_dropped_by_default(self):
        lines = [
            self._line(" ", "       DISPLAY 'BEFORE'."),
            self._line("D", "       DISPLAY 'DEBUG-ONLY'."),
            self._line(" ", "       DISPLAY 'AFTER'."),
        ]
        out = normalize_fixed_format(lines)
        assert "DEBUG-ONLY" not in out
        assert "BEFORE" in out
        assert "AFTER" in out

    def test_d_line_kept_as_code_when_opted_in(self):
        lines = [
            self._line(" ", "       DISPLAY 'BEFORE'."),
            self._line("D", "       DISPLAY 'DEBUG-ONLY'."),
        ]
        out = normalize_fixed_format(lines, debug_lines_as_comments=False)
        assert "DEBUG-ONLY" in out


class TestM5ContinuedLiteralTrailingBlanks:
    """M5 -- trailing blanks that are part of a literal's value (per
    fixed-format continuation rules) were stripped from the opening line
    before we knew the literal would continue.
    """

    def _line(self, indicator: str, text: str) -> str:
        return " " * 6 + indicator + text

    def test_opening_line_trailing_blanks_preserved_when_continued(self):
        lines = [
            self._line(" ", '       VALUE "ABC   '),
            self._line("-", '           "DEF".'),
        ]
        out = normalize_fixed_format(lines)
        assert '"ABC   DEF"' in out, out

    def test_trailing_blanks_still_stripped_when_not_continued(self):
        lines = [
            self._line(" ", "       DISPLAY 'X'          "),
        ]
        out = normalize_fixed_format(lines)
        first_line = out.splitlines()[0]
        assert first_line == "       DISPLAY 'X'"


class TestM8TabHandling:
    """M8 -- no tab-expansion logic in normalize_fixed_format; a leading
    tab shifted every subsequent column.
    """

    def test_leading_tab_does_not_shift_columns(self):
        # A literal tab in column 1 should expand to the next tab stop
        # (8 columns) before column-sensitive slicing, so the indicator
        # and text-area columns land where they would for the untabbed
        # equivalent.
        untabbed = normalize_fixed_format(
            [" " * 6 + " " + "       DISPLAY 'OK'."]
        )
        tabbed = normalize_fixed_format(["\t" + "       DISPLAY 'OK'."])
        assert tabbed == untabbed


def test_fast_and_pure_normalize_fixed_format_agree_on_m4_m5_m8_cases():
    """Parity check: the Cython fast path must match the pure-Python
    implementation on every new behavior introduced by M4/M5/M8 (mirrors
    the existing test_fast_preprocess_is_active precedent)."""
    from cobolparser.preprocess import _normalize_fixed_format_pure

    cases = [
        [" " * 6 + " " + "       DISPLAY 'BEFORE'.",
         " " * 6 + "D" + "       DISPLAY 'DEBUG-ONLY'."],
        [" " * 6 + " " + '       VALUE "ABC   ',
         " " * 6 + "-" + '           "DEF".'],
        ["\t" + "       DISPLAY 'OK'."],
    ]
    for lines in cases:
        assert normalize_fixed_format(lines) == _normalize_fixed_format_pure(lines)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/regression/test_open_findings_medium_regressions.py -k "M4DebugLine or M5Continued or M8Tab or parity" -v`
Expected: FAIL (D-lines kept as code; trailing blanks stripped in the M5
case; tab case mismatched columns; parity test passes trivially since both
sides currently share the same, unfixed, behavior -- it exists to catch
drift once the fix lands, not to fail now).

- [ ] **Step 3: Fix the pure-Python implementation**

In `cobolparser/preprocess/__init__.py`, change the signature:

```python
def normalize_fixed_format(
    lines: Iterable[str], *, merge_continued_literals: bool = True
) -> str:
```

to:

```python
def normalize_fixed_format(
    lines: Iterable[str],
    *,
    merge_continued_literals: bool = True,
    debug_lines_as_comments: bool = True,
) -> str:
```

Update the docstring's "Steps" list to add a line: `- Optionally treat
'D'/'d' in the indicator column as a comment too (debug_lines_as_comments,
default True) -- matches copy_statement_parser.is_comment_line().`

Then, inside the loop, change (M8 -- tab expansion, must happen before any
column-index slicing):

```python
    for raw in lines:
        line = raw.rstrip("\n")
```

to:

```python
    for raw in lines:
        line = raw.rstrip("\n").expandtabs(8)
```

Then (M4 -- D-line comment handling), change:

```python
        indicator = line[INDICATOR_COL - 1] if len(line) >= INDICATOR_COL else " "
        text_slice = line[TEXT_START_COL - 1 : TEXT_END_COL]
        if indicator in ("*", "/"):  # comment (including page eject)
```

to:

```python
        indicator = line[INDICATOR_COL - 1] if len(line) >= INDICATOR_COL else " "
        text_slice = line[TEXT_START_COL - 1 : TEXT_END_COL]
        is_debug_comment = debug_lines_as_comments and indicator in ("D", "d")
        if indicator in ("*", "/") or is_debug_comment:  # comment (incl. page eject, debug lines)
```

Then (M5 -- preserve trailing blanks of a literal that remains open),
change the "Non-continuation line - start new logical line" branch:

```python
        else:
            # Non-continuation line - start new logical line
            flush_parts()
            stripped = text_slice.rstrip()
            parts.append(stripped)
            if merge_continued_literals:
                _update_quote_state(stripped)
```

to:

```python
        else:
            # Non-continuation line - start new logical line
            flush_parts()
            if merge_continued_literals:
                _update_quote_state(text_slice)
                # Trailing blanks up to column 72 are part of a literal's
                # value when it remains open at end of line (COBOL
                # fixed-format continuation rule) -- only strip them once
                # we know no literal is left dangling (M5).
                chunk = text_slice if pending_literal else text_slice.rstrip()
            else:
                chunk = text_slice.rstrip()
            parts.append(chunk)
```

And the literal-continuation branch:

```python
        if is_cont:
            # This is a continuation line - merge with previous buffer
            if pending_literal and merge_continued_literals:
                chunk = text_slice.lstrip()
                if chunk and chunk[0] == quote_char:
                    chunk = chunk[1:]
                stripped = chunk.rstrip()
                parts.append(stripped)
                if merge_continued_literals:
                    _update_quote_state(stripped)
```

to:

```python
        if is_cont:
            # This is a continuation line - merge with previous buffer
            if pending_literal and merge_continued_literals:
                chunk = text_slice.lstrip()
                if chunk and chunk[0] == quote_char:
                    chunk = chunk[1:]
                _update_quote_state(chunk)
                # Same M5 fix as the opening-line branch: only strip
                # trailing blanks once the literal is confirmed closed.
                out_chunk = chunk if pending_literal else chunk.rstrip()
                parts.append(out_chunk)
```

- [ ] **Step 4: Mirror the fix in the Cython implementation**

In `cobolparser/_preprocess_fast.pyx`, change the signature:

```python
def normalize_fixed_format(lines, *, merge_continued_literals=True):
```

to:

```python
def normalize_fixed_format(lines, *, merge_continued_literals=True, debug_lines_as_comments=True):
```

Change the tab-expansion line:

```python
        line = raw.rstrip("\n")
```

to:

```python
        line = raw.rstrip("\n").expandtabs(8)
```

Change the comment-indicator check:

```python
        if indicator == "*" or indicator == "/":
```

to:

```python
        cdef bint is_debug_comment = debug_lines_as_comments and (indicator == "D" or indicator == "d")
        if indicator == "*" or indicator == "/" or is_debug_comment:
```

(Cython requires `cdef` declarations near the top of the function body,
not inline mid-function inside a loop after other statements have already
executed conditionally -- move `cdef bint is_debug_comment` up next to the
other `cdef` declarations at the top of `normalize_fixed_format`, and just
assign to it here instead of declaring it inline.)

For M5, in the non-continuation `else` branch (~line 130-160), change:

```python
        else:
            # Non-continuation: flush previous logical line
            combined = "".join(parts)
            if combined:
                result.append(combined)
            parts         = []
            quote_open    = False
            quote_ch      = None
            pending_literal = False

            stripped = text_slice.rstrip()
            parts.append(stripped)
            if merge_continued_literals:
                n = len(stripped)
                i = 0
                while i < n:
                    ch = stripped[i]
                    if quote_open:
                        if ch == quote_ch:
                            if i + 1 < n and stripped[i + 1] == quote_ch:
                                i += 2
                                continue
                            quote_open = False
                            quote_ch   = None
                        i += 1
                    else:
                        if ch == "'" or ch == '"':
                            quote_open = True
                            quote_ch   = ch
                        i += 1
                pending_literal = quote_open
```

to:

```python
        else:
            # Non-continuation: flush previous logical line
            combined = "".join(parts)
            if combined:
                result.append(combined)
            parts         = []
            quote_open    = False
            quote_ch      = None
            pending_literal = False

            if merge_continued_literals:
                n = len(text_slice)
                i = 0
                while i < n:
                    ch = text_slice[i]
                    if quote_open:
                        if ch == quote_ch:
                            if i + 1 < n and text_slice[i + 1] == quote_ch:
                                i += 2
                                continue
                            quote_open = False
                            quote_ch   = None
                        i += 1
                    else:
                        if ch == "'" or ch == '"':
                            quote_open = True
                            quote_ch   = ch
                        i += 1
                pending_literal = quote_open
                # M5: trailing blanks are part of the literal's value when
                # it remains open at end of line -- only strip once closed.
                parts.append(text_slice if pending_literal else text_slice.rstrip())
            else:
                parts.append(text_slice.rstrip())
```

And in the literal-continuation branch (~line 76-100), change:

```python
            if pending_literal and merge_continued_literals:
                chunk = text_slice.lstrip()
                if chunk and quote_ch is not None and chunk[0] == quote_ch:
                    chunk = chunk[1:]
                stripped = chunk.rstrip()
                parts.append(stripped)
                # Inline quote-state update
                n = len(stripped)
                i = 0
                while i < n:
                    ch = stripped[i]
```

to:

```python
            if pending_literal and merge_continued_literals:
                chunk = text_slice.lstrip()
                if chunk and quote_ch is not None and chunk[0] == quote_ch:
                    chunk = chunk[1:]
                # Inline quote-state update (scan the un-rstripped chunk
                # so trailing blanks don't get discarded before we know
                # whether the literal is still open -- M5).
                n = len(chunk)
                i = 0
                while i < n:
                    ch = chunk[i]
```

...and after that `while` loop (still inside the `if pending_literal and
merge_continued_literals:` block, replacing the old
`parts.append(stripped)` which must be removed since `parts.append` now
happens after the loop, not before), append:

```python
                pending_literal = quote_open
                parts.append(chunk if pending_literal else chunk.rstrip())
```

(Delete the old trailing `pending_literal = quote_open` that previously
followed this loop, since it's now folded into the block above — check
the full function body after editing to make sure there is exactly one
`pending_literal = quote_open` assignment per branch, not two.)

- [ ] **Step 5: Rebuild the Cython extension and commit the regenerated `.c`**

Run: `python setup.py build_ext --inplace`
Expected: Build succeeds with no errors; `cobolparser/_preprocess_fast.c`
is regenerated (check `git status` shows it modified) and a `.pyd` (or
`.so`) file is rebuilt in place.

- [ ] **Step 6: Run to verify all new tests pass, including the parity check**

Run: `python -m pytest tests/regression/test_open_findings_medium_regressions.py -k "M4DebugLine or M5Continued or M8Tab or parity" -v`
Expected: All PASS.

Run also: `python -m pytest tests/unit/test_fast_import.py -v` to confirm
`test_fast_preprocess_is_active` (or equivalent) still reports the Cython
path as active -- if it reports the pure-Python fallback instead, the
build in Step 5 did not take effect (stale `.pyd`) and must be re-run
after checking for build errors.

- [ ] **Step 7: Run the full preprocessing + sample suites for the M4 default-flip regression check**

Run: `python -m pytest tests/unit/test_preprocess_and_freeform.py tests/unit/test_preprocess_init_coverage.py tests/unit/test_lexer_fixed_format_coverage.py tests/regression/test_lexer_preprocessor_regression.py tests/regression/test_continued_literal_normalization.py tests/regression/test_normalize_line_number_preservation.py tests/test_all_samples.py tests/integration/test_shamrice_examples.py -v`
Expected: All PASS. If any fixture relied on a `D`-column-7 line being
compiled as live code (the old, inconsistent default), it will now fail
loudly here -- if so, that fixture needs `debug_lines_as_comments=False`
threaded through, or (more likely, since no such fixture was found during
planning) it confirms the old behavior had no real dependents.

- [ ] **Step 8: Commit**

```bash
git add cobolparser/preprocess/__init__.py cobolparser/_preprocess_fast.pyx cobolparser/_preprocess_fast.c tests/regression/test_open_findings_medium_regressions.py
git commit -m "fix(preprocess): M4/M5/M8 -- D-line comments, literal trailing blanks, tab expansion in normalize_fixed_format"
```

---

## Task 6: M1 — DISPLAY doesn't accept figurative constants

**Files:**
- Modify: `cobolparser/parsers/statements/display_parser.py` (~line 121-125)
- Test: `tests/regression/test_open_findings_medium_regressions.py` (append)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `DisplayStatement` instance shape consumed by Tasks 7 and 8
  (same class, additive fields only -- no signature conflicts since each
  task adds independent fields/setters).

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestM1DisplayFigurativeConstants:
    """M1 -- DISPLAY SPACE / DISPLAY SPACES (and other figurative
    constants) were not accepted as display items.
    """

    def test_display_space_is_captured(self):
        result = parse_cobol(_proc_program("    DISPLAY SPACE.\n"))
        stmts = [s for s in _statements(result) if isinstance(s, DisplayStatement)]
        assert len(stmts) == 1
        assert stmts[0].display_items == ["SPACE"]
        assert not any("Unparsed tokens" in w for w in result.warnings), result.warnings

    def test_display_spaces_mixed_with_identifier(self):
        result = parse_cobol(_proc_program("    DISPLAY WS-X SPACES.\n"))
        stmts = [s for s in _statements(result) if isinstance(s, DisplayStatement)]
        assert stmts[0].display_items == ["WS-X", "SPACES"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/regression/test_open_findings_medium_regressions.py::TestM1DisplayFigurativeConstants -v`
Expected: FAIL (`display_items == []`, `"Unparsed tokens"` warning present).

- [ ] **Step 3: Accept `FIGURATIVE_CONSTANT` as a display item**

In `cobolparser/parsers/statements/display_parser.py`, change:

```python
            # Collect display item
            if token.type in (
                TokenType.STRING_LITERAL,
                TokenType.IDENTIFIER,
                TokenType.NUMERIC_LITERAL,
            ):
```

to:

```python
            # Collect display item
            if token.type in (
                TokenType.STRING_LITERAL,
                TokenType.IDENTIFIER,
                TokenType.NUMERIC_LITERAL,
                TokenType.FIGURATIVE_CONSTANT,  # SPACE(S), ZERO(S), HIGH-VALUE(S), ... (M1)
            ):
```

Below, the string-literal-quoting branch (`if token.type ==
TokenType.STRING_LITERAL: item_value = f'"{item_value}"'`) and the
subscript-consumption branch (`if token.type == TokenType.IDENTIFIER:
item_value += self._consume_subscript(...)`) are both unaffected --
figurative constants fall through both `if`s unchanged and are appended
as their raw upper-case value (e.g. `"SPACE"`), which matches how
`IDENTIFIER`/`NUMERIC_LITERAL` items are already handled.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/regression/test_open_findings_medium_regressions.py::TestM1DisplayFigurativeConstants -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cobolparser/parsers/statements/display_parser.py tests/regression/test_open_findings_medium_regressions.py
git commit -m "fix(parser): M1 -- DISPLAY accepts figurative constants (SPACE, ZERO, ...) as items"
```

---

## Task 7: M2 — `DISPLAY ... WITH NO ADVANCING` dropped

**Files:**
- Modify: `cobolparser/models/statements/data.py` (`DisplayStatement`, ~line 48-71)
- Modify: `cobolparser/parsers/statements/display_parser.py`
- Test: `tests/regression/test_open_findings_medium_regressions.py` (append)

**Interfaces:**
- Consumes: `DisplayStatement` from Task 6 (additive; no conflict).
- Produces: `DisplayStatement.with_no_advancing: bool`,
  `DisplayStatement.set_no_advancing(no_advancing: bool = True) -> None`,
  consumed by nothing later (independent field).

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestM2DisplayWithNoAdvancing:
    """M2 -- DISPLAY ... WITH NO ADVANCING was silently dropped; the
    display item before WITH survived but the clause itself vanished.
    """

    def test_with_no_advancing_is_captured(self):
        result = parse_cobol(
            _proc_program('    DISPLAY "PROMPT: " WITH NO ADVANCING.\n')
        )
        stmts = [s for s in _statements(result) if isinstance(s, DisplayStatement)]
        assert len(stmts) == 1
        assert stmts[0].display_items == ['"PROMPT: "']
        assert stmts[0].with_no_advancing is True
        assert not any("Unparsed tokens" in w for w in result.warnings), result.warnings

    def test_bare_no_advancing_without_with_is_captured(self):
        result = parse_cobol(
            _proc_program('    DISPLAY "X" NO ADVANCING.\n')
        )
        stmts = [s for s in _statements(result) if isinstance(s, DisplayStatement)]
        assert stmts[0].with_no_advancing is True

    def test_display_without_the_clause_defaults_false(self):
        result = parse_cobol(_proc_program('    DISPLAY "X".\n'))
        stmts = [s for s in _statements(result) if isinstance(s, DisplayStatement)]
        assert stmts[0].with_no_advancing is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/regression/test_open_findings_medium_regressions.py::TestM2DisplayWithNoAdvancing -v`
Expected: FAIL (`AttributeError: 'DisplayStatement' object has no attribute 'with_no_advancing'`).

- [ ] **Step 3: Add the field to `DisplayStatement`**

In `cobolparser/models/statements/data.py`, change:

```python
class DisplayStatement(CobolStatement):
    """AST node for DISPLAY statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("DISPLAY", location)
        self.display_items: list[str] = []
        self.output_device: str | None = None

    def add_display_item(self, item: str) -> None:
        """Add an item to display."""
        self.display_items.append(item)
        self.operands.append(item)

    def set_output_device(self, device: str) -> None:
        """Set the output device (UPON clause)."""
        self.output_device = device

    def to_dict(self) -> dict[str, Any]:
        """Convert DISPLAY statement to dictionary representation."""
        result = super().to_dict()
        result.update(
            {"display_items": self.display_items, "output_device": self.output_device}
        )
        return result
```

to:

```python
class DisplayStatement(CobolStatement):
    """AST node for DISPLAY statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("DISPLAY", location)
        self.display_items: list[str] = []
        self.output_device: str | None = None
        self.with_no_advancing: bool = False

    def add_display_item(self, item: str) -> None:
        """Add an item to display."""
        self.display_items.append(item)
        self.operands.append(item)

    def set_output_device(self, device: str) -> None:
        """Set the output device (UPON clause)."""
        self.output_device = device

    def set_no_advancing(self, no_advancing: bool = True) -> None:
        """Set the WITH NO ADVANCING flag (suppresses the implicit newline)."""
        self.with_no_advancing = no_advancing

    def to_dict(self) -> dict[str, Any]:
        """Convert DISPLAY statement to dictionary representation."""
        result = super().to_dict()
        result.update(
            {
                "display_items": self.display_items,
                "output_device": self.output_device,
                "with_no_advancing": self.with_no_advancing,
            }
        )
        return result
```

- [ ] **Step 4: Parse the clause in `display_parser.py`**

Add `TokenType.WITH` and `TokenType.NO` handling. Insert a new branch
right after the UPON branch and before the paragraph-boundary checks
(order matters: `WITH`/`NO`/`ADVANCING` are dedicated `TokenType`s that
would otherwise fall through to the final `else: break`):

```python
            # Check for WITH NO ADVANCING (M2) -- WITH is an optional
            # filler word; NO ADVANCING is the fixed phrase. Neither
            # currently introduces any other DISPLAY clause, so once we
            # commit to consuming WITH we must find NO ADVANCING or stop
            # (matching the loop's "unknown token -> stop" convention).
            if token.type in (TokenType.WITH, TokenType.NO):
                if token.type == TokenType.WITH:
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    token = token_stream.peek()
                if token and token.type == TokenType.NO:
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    adv_token = token_stream.peek()
                    if adv_token and adv_token.type == TokenType.ADVANCING:
                        token_stream.consume()
                        stmt.set_no_advancing(True)
                        skip_whitespace(token_stream)
                        continue
                break
```

This requires the enclosing `while` loop to support `continue` (it
already does -- it's a plain `while not token_stream.is_empty():` loop;
`continue` re-evaluates the loop condition and re-peeks, which is correct
here since we've fully consumed the clause).

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/regression/test_open_findings_medium_regressions.py::TestM2DisplayWithNoAdvancing -v`
Expected: PASS

- [ ] **Step 6: Run the broader DISPLAY test suite**

Run: `python -m pytest tests/unit -k display -v tests/integration -k display -v`
Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add cobolparser/models/statements/data.py cobolparser/parsers/statements/display_parser.py tests/regression/test_open_findings_medium_regressions.py
git commit -m "fix(parser): M2 -- DISPLAY WITH NO ADVANCING is now captured"
```

---

## Task 8: M3a — DISPLAY `AT` positioning

**Files:**
- Modify: `cobolparser/models/statements/data.py` (`DisplayStatement`)
- Modify: `cobolparser/parsers/statements/display_parser.py`
- Test: `tests/regression/test_open_findings_medium_regressions.py` (append)

**Interfaces:**
- Consumes: `DisplayStatement` from Tasks 6-7 (additive).
- Produces: `DisplayStatement.at_line: int | None`,
  `DisplayStatement.at_column: int | None`,
  `DisplayStatement.set_position(line: int | None = None, column: int | None = None) -> None`.

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestM3aDisplayAtPositioning:
    """M3a -- DISPLAY ... AT LINE/COLUMN (and the corpus-dominant bare
    combined-numeric AT nnnn form) were dropped entirely.
    """

    def test_combined_numeric_at_form_decodes_line_and_column(self):
        # AT 0330 -> line 3, column 30 (confirmed real-world form, e.g.
        # examples/cobol/shamrice/accept.cbl's `AT 0330`).
        result = parse_cobol(_proc_program('    DISPLAY "X" AT 0330.\n'))
        stmts = [s for s in _statements(result) if isinstance(s, DisplayStatement)]
        assert stmts[0].at_line == 3
        assert stmts[0].at_column == 30
        assert not any("Unparsed tokens" in w for w in result.warnings), result.warnings

    def test_at_line_column_keyword_form(self):
        result = parse_cobol(_proc_program('    DISPLAY "X" AT LINE 5 COLUMN 10.\n'))
        stmts = [s for s in _statements(result) if isinstance(s, DisplayStatement)]
        assert stmts[0].at_line == 5
        assert stmts[0].at_column == 10

    def test_at_line_only(self):
        result = parse_cobol(_proc_program('    DISPLAY "X" AT LINE 5.\n'))
        stmts = [s for s in _statements(result) if isinstance(s, DisplayStatement)]
        assert stmts[0].at_line == 5
        assert stmts[0].at_column is None

    def test_multiple_items_each_with_their_own_at_clause(self):
        # examples/cobol/shamrice/accept_from.cbl-style:
        # DISPLAY "a" AT 0201 ws-input AT 0214.
        # Only the LAST AT clause's position is retained on the single
        # DisplayStatement node (the AST models one position per
        # statement, matching IOAcceptStatement's existing shape) --
        # document this as the intended, if simplified, representation.
        result = parse_cobol(
            _proc_program('    DISPLAY "a" AT 0201 WS-X AT 0214.\n')
        )
        stmts = [s for s in _statements(result) if isinstance(s, DisplayStatement)]
        assert stmts[0].display_items == ['"a"', "WS-X"]
        assert stmts[0].at_line == 2
        assert stmts[0].at_column == 14
        assert not any("Unparsed tokens" in w for w in result.warnings), result.warnings
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/regression/test_open_findings_medium_regressions.py::TestM3aDisplayAtPositioning -v`
Expected: FAIL (`AttributeError: 'DisplayStatement' object has no attribute 'at_line'`).

- [ ] **Step 3: Add fields to `DisplayStatement`**

In `cobolparser/models/statements/data.py`, add to `__init__`:

```python
        self.with_no_advancing: bool = False
        self.at_line: int | None = None
        self.at_column: int | None = None
```

Add a method (mirrors `IOAcceptStatement.set_position` in
`models/statements/io.py`):

```python
    def set_position(self, line: int | None = None, column: int | None = None) -> None:
        """Set the AT LINE/COLUMN screen position."""
        self.at_line = line
        self.at_column = column
```

Add to `to_dict()`'s `result.update({...})`:

```python
                "at_line": self.at_line,
                "at_column": self.at_column,
```

- [ ] **Step 4: Add an `AT`-clause helper and wire it into the parse loop**

In `cobolparser/parsers/statements/display_parser.py`, add a new
staticmethod near `_consume_subscript`:

```python
    @staticmethod
    def _parse_at_clause(token_stream: ITokenStream, stmt: DisplayStatement) -> None:
        """Parse an ``AT`` positioning clause and call ``stmt.set_position``.

        Supports both forms confirmed in real-world usage (see
        reports/open-findings.md M3): the combined 4-digit numeric form
        (``AT 0330`` -> line 3, column 30, where the low-order two digits
        are the column and the remainder is the line) and the explicit
        ``AT LINE n [COLUMN m]`` / ``AT COLUMN m [LINE n]`` keyword form.
        Assumes the ``AT`` token itself has already been peeked but not
        consumed.
        """
        token_stream.consume()  # AT
        skip_whitespace(token_stream)
        token = token_stream.peek()
        if not token:
            return

        line: int | None = None
        column: int | None = None

        if token.type == TokenType.NUMERIC_LITERAL and token.value and token.value.isdigit():
            token_stream.consume()
            value = int(token.value)
            line, column = divmod(value, 100)
            stmt.set_position(line, column)
            return

        # Keyword form: LINE and/or COLUMN, in either order.
        for _ in range(2):
            token = token_stream.peek()
            if token and token.type == TokenType.LINE:
                token_stream.consume()
                skip_whitespace(token_stream)
                num = token_stream.peek()
                if num and num.value and num.value.lstrip("-").isdigit():
                    token_stream.consume()
                    line = int(num.value)
                skip_whitespace(token_stream)
            elif (
                token
                and token.type == TokenType.IDENTIFIER
                and token.value
                and token.value.upper() == "COLUMN"
            ):
                token_stream.consume()
                skip_whitespace(token_stream)
                num = token_stream.peek()
                if num and num.value and num.value.lstrip("-").isdigit():
                    token_stream.consume()
                    column = int(num.value)
                skip_whitespace(token_stream)
            else:
                break

        if line is not None or column is not None:
            stmt.set_position(line, column)
```

Wire it into the parse loop, immediately after the UPON branch and before
the WITH/NO/ADVANCING branch added in Task 7 (order between the two new
branches doesn't matter functionally since they match disjoint token
types, but placing AT first matches the corpus's typical clause order
`... AT nnnn WITH NO ADVANCING` if both ever co-occur):

```python
            # Check for AT LINE/COLUMN positioning (M3a)
            if token.type == TokenType.AT:
                self._parse_at_clause(token_stream, stmt)
                skip_whitespace(token_stream)
                continue
```

Add `DisplayStatement` to this file's imports if not already the type
hint target (`from ...models.statements import DisplayStatement` already
exists per the file's current top -- reuse it for the new method's type
hint).

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/regression/test_open_findings_medium_regressions.py::TestM3aDisplayAtPositioning -v`
Expected: PASS

- [ ] **Step 6: Run against the real corpus files that motivated this fix**

Run:
```bash
python -c "
from cobolparser import parse_cobol
for f in ['examples/cobol/shamrice/accept.cbl', 'examples/cobol/shamrice/accept_from.cbl', 'examples/cobol/shamrice/accept-secure.cbl']:
    src = open(f, encoding='utf-8', errors='replace').read()
    r = parse_cobol(src, filename=f)
    print(f, 'errors=', len(r.errors), 'at-related warnings=', [w for w in r.warnings if 'AT' in w or 'Unparsed' in w][:5])
"
```
Expected: No new `"Unparsed tokens starting at 'AT'"` (or similar)
warnings for these files compared to a run against the pre-fix code (spot
check; these files also exercise TIMEOUT/AUTO-SKIP/etc. which are still
unhandled until Task 9, so some unrelated warnings may remain -- confirm
they are NOT about `AT`/`LINE`/`COLUMN`).

- [ ] **Step 7: Commit**

```bash
git add cobolparser/models/statements/data.py cobolparser/parsers/statements/display_parser.py tests/regression/test_open_findings_medium_regressions.py
git commit -m "fix(parser): M3a -- DISPLAY AT LINE/COLUMN and combined-numeric positioning"
```

---

## Task 9: M3b — ACCEPT `AT` positioning + SECURE/NO-ECHO/TIMEOUT/AUTO-SKIP/UPPER

**Files:**
- Modify: `cobolparser/models/statements/io.py` (`IOAcceptStatement`, ~line 384-469)
- Modify: `cobolparser/parsers/statements/accept_parser.py`
- Test: `tests/regression/test_open_findings_medium_regressions.py` (append)

**Interfaces:**
- Consumes: `IOAcceptStatement.set_position`, `.set_no_echo` (already
  exist, unchanged).
- Produces: `IOAcceptStatement.secure: bool`,
  `.set_secure(secure: bool = True) -> None`,
  `.timeout_value: int | None`, `.set_timeout(seconds: int) -> None`,
  `.auto_skip: bool`, `.set_auto_skip(auto_skip: bool = True) -> None`,
  `.upper: bool`, `.set_upper(upper: bool = True) -> None`.

- [ ] **Step 1: Write the failing tests**

Append (these mirror the exact shapes confirmed in
`examples/cobol/shamrice/accept.cbl` and `accept-secure.cbl`):

```python
class TestM3bAcceptExtendedClauses:
    """M3b -- ACCEPT's AT positioning and extended clauses (SECURE,
    NO-ECHO, TIMEOUT, AUTO-SKIP, UPPER) were dropped. Grammar shapes below
    are taken verbatim from examples/cobol/shamrice/accept.cbl and
    accept-secure.cbl, the corpus the original audit's hit-counts came
    from.
    """

    def test_combined_numeric_at_form(self):
        result = parse_cobol(_proc_program("    ACCEPT WS-X AT 0117.\n"))
        stmts = [
            s for s in _statements(result)
            if s.__class__.__name__ == "IOAcceptStatement"
        ]
        assert stmts[0].at_line == 1
        assert stmts[0].at_column == 17
        assert not any("Unparsed tokens" in w for w in result.warnings), result.warnings

    def test_secure_is_distinct_from_no_echo(self):
        result = parse_cobol(_proc_program("    ACCEPT WS-X SECURE AT 0117.\n"))
        stmts = [
            s for s in _statements(result)
            if s.__class__.__name__ == "IOAcceptStatement"
        ]
        assert stmts[0].secure is True
        assert stmts[0].with_no_echo is False

    def test_no_echo_hyphenated_token(self):
        result = parse_cobol(_proc_program("    ACCEPT WS-X NO-ECHO AT 0526.\n"))
        stmts = [
            s for s in _statements(result)
            if s.__class__.__name__ == "IOAcceptStatement"
        ]
        assert stmts[0].with_no_echo is True
        assert stmts[0].secure is False

    def test_timeout_with_numeric_value(self):
        result = parse_cobol(_proc_program("    ACCEPT WS-X TIMEOUT 3 AT 0132.\n"))
        stmts = [
            s for s in _statements(result)
            if s.__class__.__name__ == "IOAcceptStatement"
        ]
        assert stmts[0].timeout_value == 3
        assert stmts[0].at_line == 1
        assert stmts[0].at_column == 32

    def test_auto_skip(self):
        result = parse_cobol(_proc_program("    ACCEPT WS-X AUTO-SKIP AT 0330.\n"))
        stmts = [
            s for s in _statements(result)
            if s.__class__.__name__ == "IOAcceptStatement"
        ]
        assert stmts[0].auto_skip is True

    def test_upper(self):
        result = parse_cobol(_proc_program("    ACCEPT WS-X UPPER AT 0716.\n"))
        stmts = [
            s for s in _statements(result)
            if s.__class__.__name__ == "IOAcceptStatement"
        ]
        assert stmts[0].upper is True

    def test_combined_with_prefix_form(self):
        # examples/cobol/shamrice/mouse_example.cbl: `with auto-skip no-echo`
        result = parse_cobol(
            _proc_program("    ACCEPT WS-X WITH AUTO-SKIP NO-ECHO.\n")
        )
        stmts = [
            s for s in _statements(result)
            if s.__class__.__name__ == "IOAcceptStatement"
        ]
        assert stmts[0].auto_skip is True
        assert stmts[0].with_no_echo is True
        assert not any("Unparsed tokens" in w for w in result.warnings), result.warnings
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/regression/test_open_findings_medium_regressions.py::TestM3bAcceptExtendedClauses -v`
Expected: FAIL (`AttributeError` on `.secure`/`.timeout_value`/etc., and
`at_line`/`with_no_echo` never set since nothing calls the existing
setters yet).

- [ ] **Step 3: Add fields to `IOAcceptStatement`**

In `cobolparser/models/statements/io.py`, add to `IOAcceptStatement.__init__`:

```python
        self.secure: bool = False
        self.timeout_value: int | None = None
        self.auto_skip: bool = False
        self.upper: bool = False
```

Add setters:

```python
    def set_secure(self, secure: bool = True) -> None:
        """Set the SECURE flag (asterisk-masked input; distinct from
        NO-ECHO, which shows nothing -- see reports/open-findings.md M3)."""
        self.secure = secure

    def set_timeout(self, seconds: int) -> None:
        """Set the TIMEOUT clause value, in seconds."""
        self.timeout_value = seconds

    def set_auto_skip(self, auto_skip: bool = True) -> None:
        """Set the AUTO-SKIP flag."""
        self.auto_skip = auto_skip

    def set_upper(self, upper: bool = True) -> None:
        """Set the UPPER flag (force uppercase input)."""
        self.upper = upper
```

Add to `to_dict()`'s `result.update({...})`:

```python
                "secure": self.secure,
                "timeout_value": self.timeout_value,
                "auto_skip": self.auto_skip,
                "upper": self.upper,
```

- [ ] **Step 4: Wire clause parsing into `accept_parser.py`**

In `cobolparser/parsers/statements/accept_parser.py`, the current method
parses the target and an optional `FROM` clause, then consumes a trailing
period. Insert clause parsing between the `FROM`-clause block and the
period-consumption, replacing:

```python
        skip_whitespace(token_stream)

        # Consume period if present
        if not token_stream.is_empty():
            p = token_stream.peek()
            if p and p.type == TokenType.PERIOD:
                token_stream.consume()

        return stmt
```

with:

```python
        skip_whitespace(token_stream)

        # Extended ACCEPT clauses (M3b): AT positioning, SECURE, NO-ECHO,
        # TIMEOUT, AUTO-SKIP, UPPER, optionally introduced by WITH and in
        # any order/combination (grammar shapes taken from
        # examples/cobol/shamrice/accept.cbl and accept-secure.cbl).
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            if token.type == TokenType.PERIOD:
                break
            if token.type == TokenType.WITH:
                token_stream.consume()
                skip_whitespace(token_stream)
                continue
            if token.type == TokenType.AT:
                token_stream.consume()
                skip_whitespace(token_stream)
                num = token_stream.peek()
                if num and num.value and num.value.isdigit():
                    token_stream.consume()
                    line, column = divmod(int(num.value), 100)
                    stmt.set_position(line, column)
                skip_whitespace(token_stream)
                continue
            if token.type == TokenType.IDENTIFIER and token.value:
                upper = token.value.upper()
                if upper == "SECURE":
                    token_stream.consume()
                    stmt.set_secure(True)
                    skip_whitespace(token_stream)
                    continue
                if upper == "NO-ECHO":
                    token_stream.consume()
                    stmt.set_no_echo(True)
                    skip_whitespace(token_stream)
                    continue
                if upper == "AUTO-SKIP":
                    token_stream.consume()
                    stmt.set_auto_skip(True)
                    skip_whitespace(token_stream)
                    continue
                if upper == "UPPER":
                    token_stream.consume()
                    stmt.set_upper(True)
                    skip_whitespace(token_stream)
                    continue
                if upper == "TIMEOUT":
                    token_stream.consume()
                    skip_whitespace(token_stream)
                    num = token_stream.peek()
                    if num and num.value and num.value.isdigit():
                        token_stream.consume()
                        stmt.set_timeout(int(num.value))
                    skip_whitespace(token_stream)
                    continue
            # Unrecognized clause token: stop rather than silently
            # consuming (matches the rest of this file's convention).
            break

        # Consume period if present
        if not token_stream.is_empty():
            p = token_stream.peek()
            if p and p.type == TokenType.PERIOD:
                token_stream.consume()

        return stmt
```

Note: `AT LINE n [COLUMN m]` keyword form is intentionally **not**
duplicated here for ACCEPT (only the corpus-confirmed combined-numeric
form is implemented for ACCEPT) -- DISPLAY's `_parse_at_clause` handles
both forms because DISPLAY's own AT usage in the corpus is also 100%
combined-numeric, so the keyword-form branch there is speculative
IBM-grammar coverage, not corpus-driven. If a future finding surfaces real
`ACCEPT ... AT LINE n` usage, extract `DisplayStatementParser._parse_at_clause`
into a shared `_utils.py` helper and reuse it here rather than
re-implementing.

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/regression/test_open_findings_medium_regressions.py::TestM3bAcceptExtendedClauses -v`
Expected: PASS

- [ ] **Step 6: Run against the real corpus files**

Run:
```bash
python -c "
from cobolparser import parse_cobol
for f in ['examples/cobol/shamrice/accept.cbl', 'examples/cobol/shamrice/accept-secure.cbl', 'examples/cobol/shamrice/mouse_example.cbl']:
    src = open(f, encoding='utf-8', errors='replace').read()
    r = parse_cobol(src, filename=f)
    print(f, 'errors=', len(r.errors))
    for w in r.warnings:
        if 'Unparsed' in w:
            print('  ', w)
"
```
Expected: No `"Unparsed tokens"` warnings remaining that mention `AT`,
`SECURE`, `NO-ECHO`, `TIMEOUT`, `AUTO-SKIP`, or `UPPER` for these three
files (warnings about `CURSOR`/`COLOR`/`BLANK SCREEN`/other undocumented
clauses may remain -- those are the documented residuals, not
regressions).

- [ ] **Step 7: Run the broader ACCEPT test suite**

Run: `python -m pytest tests/unit -k accept -v tests/integration -k accept -v`
Expected: All PASS.

- [ ] **Step 8: Commit**

```bash
git add cobolparser/models/statements/io.py cobolparser/parsers/statements/accept_parser.py tests/regression/test_open_findings_medium_regressions.py
git commit -m "fix(parser): M3b -- ACCEPT AT/SECURE/NO-ECHO/TIMEOUT/AUTO-SKIP/UPPER"
```

---

## Task 10: Wrap-up — full suite, CHANGELOG, report update, OKF refresh

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `reports/open-findings.md`
- Modify: `.okf/lexer.md`, `.okf/parser.md`, `.okf/preprocessing.md` (whichever concepts document the touched behaviors -- read `.okf/index.md` first per this repo's CLAUDE.md)
- No test changes (verification task).

**Interfaces:**
- Consumes: all prior tasks' committed changes.
- Produces: nothing (terminal task).

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass (coverage floor 81% should hold since this is a
full run, not a subset). Investigate and fix any failure before
proceeding -- do not skip this step.

- [ ] **Step 2: Run lint/format/typecheck**

Run: `python -m ruff check .` then `python -m black --check .` then `python -m mypy cobolparser/`
Expected: Clean. Fix any violations introduced by the new code (e.g. run
`python -m black .` and `python -m ruff check . --fix` if needed, then
re-run the full test suite from Step 1 to confirm formatting changes
didn't break anything).

- [ ] **Step 3: Update `CHANGELOG.md`**

Add to the `Unreleased -> Fixed` section (matching the existing H1-H9
entries' style), one bullet per finding fixed in this batch: M1, M2, M3
(note the documented residuals: CURSOR/BEEP/COLOR/UPDATE/BLANK SCREEN not
covered), M4 (note the default-behavior change), M5, M7, M8, M9, M14, M16.

- [ ] **Step 4: Update `reports/open-findings.md`**

Move M1, M2, M3, M4, M5, M7, M8, M9, M14, M16 out of the active MEDIUM
list, following the same convention H1-H9 used at the top of the HIGH
section (a summary note plus "left in place for traceability", or fully
rewritten entries marked FIXED with residual-gap call-outs where
applicable -- M3 needs a residual note for CURSOR/BEEP/COLOR/UPDATE/BLANK
SCREEN). Add a pointer to
`tests/regression/test_open_findings_medium_regressions.py` the same way
the HIGH section points to
`tests/regression/test_open_findings_high_regressions.py`.

- [ ] **Step 5: Refresh OKF concepts**

Read `.okf/index.md`, follow links to whichever concepts document
`normalize_fixed_format`, the PICTURE clause parsing, DISPLAY/ACCEPT
statement parsing, and typed literals. Update their bodies and
`timestamp` fields, and append dated entries to the nearest `log.md` per
this repo's CLAUDE.md OKF policy. Use the `/okf:okf` skill in `maintain`
mode if easier than hand-editing.

- [ ] **Step 6: Validate OKF**

Run: `/okf:validate .okf --strict` (or the underlying command it wraps)
Expected: No errors. Fix any before proceeding -- the pre-commit hook
will block otherwise.

- [ ] **Step 7: Commit**

```bash
git add CHANGELOG.md reports/open-findings.md .okf/
git commit -m "docs: update CHANGELOG, open-findings report, and OKF for M1,M2,M3,M4,M5,M7,M8,M9,M14,M16"
```

- [ ] **Step 8: Final verification**

Run: `python -m pytest tests/ -v --cov-fail-under=81` one more time on the
fully committed state to confirm nothing regressed across the whole batch.
