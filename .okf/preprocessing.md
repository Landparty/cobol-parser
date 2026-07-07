---
type: Module
title: Preprocessing
description: normalize_fixed_format, copybook expansion, conditional compilation — converts raw COBOL to lexer-ready text.
tags: [preprocessing, copybook, fixed-format, conditional-compilation]
timestamp: 2026-07-06T00:00:00Z
---

# Overview

`cobolparser/preprocess/` — the first stage of the parse pipeline. Converts
raw fixed-format COBOL source into free-form text that the lexer can consume,
and optionally inlines COPY statements recursively.

# Pipeline

```
raw COBOL (fixed format)
  ──► normalize_fixed_format()   # columns 8-72, drops comment lines, merges continuations
  ──► expand_copybooks()         # optionally: inline COPY … REPLACING … statements
  ──► strip_compiler_directives()# drop compiler control statements (used inside CobolParser)
  ──► CobolLexer.tokenize()
```

# Public API

```python
from cobolparser import (
    normalize_fixed_format,          # raw lines → free-form text
    expand_copybooks,                # source + copybook paths → expanded source
    parse_cobol_with_expansion,      # parse + expand in one call
    clear_file_cache,                # reset copybook LRU cache
    set_file_cache_size,             # configure cache capacity
    get_file_cache_stats,
    # Exception types
    PreprocessingError,
    CircularReferenceError,
    CopybookNotFoundError,
    PathTraversalError,
    EncodingError,
    NestingDepthError,
    # Data models
    CopybookExpansion,
    CopybookSearchPath,
    CopyStatement,
    ExpansionStatistics,
)
from cobolparser.preprocess import (
    preprocess_conditional_compilation,
    validate_copybook_content,
    validate_level_numbers,
)
```

# Module Map

| File | Responsibility |
|------|---------------|
| `preprocess/__init__.py` | `normalize_fixed_format`, `preprocess_conditional_compilation`, `validate_copybook_content`, `validate_level_numbers`, plus exception classes |
| `preprocess/copybook_expander.py` | `expand_copybooks`, `parse_cobol_with_expansion` — recursive COPY inlining with circular-reference detection, encoding detection, content validation, and LRU caching |
| `preprocess/copy_statement_parser.py` | `CopyStatementLexer`, REPLACING clause handling, continuation line normalisation |
| `preprocess/path_resolver.py` | Secure copybook path resolution; prevents directory traversal. Found paths are canonicalised to the on-disk basename casing (`_on_disk_casing`, scandir-based) so probe-cased matches on case-insensitive filesystems never leak into reported paths |
| `preprocess/models.py` | `CopybookExpansion`, `CopyStatement`, `CopybookSearchPath`, `ExpansionStatistics` |

# normalize_fixed_format

```python
def normalize_fixed_format(
    lines: list[str] | str, *, merge_continued_literals: bool = True
) -> str: ...
```

Extracts columns 8–72 from each line, silently drops comment lines (column-7 is
`*` or `/`), and merges continuation lines (column-7 is `-`). Returns a single
free-form text string.

Continuation-line joining follows the COBOL rule that a continuation line's
first non-blank character is the successor of the continued line's last
non-blank character, **without an intervening space**:

* **Alphanumeric literal open at the split** (a quote is unbalanced on the
  continued line) → the continuation line's leading quote is dropped and the
  remainder is appended directly, resuming the literal (`pending_literal` path).
* **Any other continuation** (numeric literal or a word split mid-token, e.g.
  `-999.777` written one digit per line) → the continuation chunk is
  `strip()`-ped and appended with no leading space, so the token rejoins
  intact. Injecting a space here (the pre-2026-07-06 behaviour) spaced out the
  digits and left the decimal point as a free-standing `.` that the lexer read
  as a statement terminator — see the [log](log.md) entry and
  `tests/regression/test_continued_literal_normalization.py`.

The optional Cython `_preprocess_fast` fast-path mirrors this logic; the
pure-Python implementation stays reachable as `_normalize_fixed_format_pure`
for testing both paths.
**Unterminated literals.** With the default `merge_continued_literals=True`, a
string literal still open at end of input raises `ValueError` ("Unterminated
string literal…"). Passing `merge_continued_literals=False` disables
continuation-literal merging and never raises — it is the best-effort fallback.
`CobolParser._parse_core` relies on this: on the raise it records the error and,
unless in `FAIL_FAST`, re-normalizes with `merge_continued_literals=False` so one
bad literal no longer collapses the whole parse to `ast=None` under
`COLLECT_ALL`. `parse_cobol` defers to the parser for this recovery rather than
returning early. Both the pure-Python and Cython (`_preprocess_fast`) paths accept
`merge_continued_literals` identically.

# Copybook Expansion

```python
# Standalone expansion
result: CopybookExpansion = expand_copybooks(source, copybook_paths=["/path/to/cpy"])

# Parse + expand in one call
parse_result = parse_cobol_with_expansion(source, copybook_paths=["/path"])
```

Features:
- Recursive inlining with circular-reference detection
- Encoding detection (`utf-8`, `cp037`, `latin-1`, …)
- Content validation (`validate_copybook_content`)
- LRU file cache (configurable via `set_file_cache_size`)
- REPLACING clause support including multi-token substitution

`parse_cobol_with_expansion` copies `expansion.statistics.warnings` (lossy
encoding decodes, content-validation and level-number warnings) onto the
returned `ParseResult.warnings` (2026-07-07). Previously they lived only on
the discarded `CopybookExpansion` object, so this entry point's callers never
saw them.

**Dropped-COPY diagnostics (audit 2026-07-07 H6a/H6c):**
`CopyStatementLexer` records on `lexer.warnings` any COPY it recognized but
could not tokenize into a complete `CopyStatement` — a missing terminating
period (`COPY FOO` with no `.`, or `COPY FOO BAR.`) means the COPY is never
appended and therefore **never expanded**; an unterminated `==pseudo-text==`
REPLACING operand abandons the clause. Both used to be fully silent — the
copybook's data items simply did not exist. `_expand_source_recursive`
routes them into `ExpansionStatistics.warnings`;
`extract_copy_statements(source, source_file, warnings=None)` exposes the
same channel. The scanner also checks the **left** word boundary so
`GOODCOPY.` is not probed as a COPY statement (previously only the right
boundary was checked).

**Conditional-compilation diagnostics (audit 2026-07-07 H7):**
`preprocess_conditional_compilation(source, defined_symbols, warnings=None)`
appends to *warnings*: unsupported `>>IF` conditions (only
`sym IS [NOT] DEFINED` is evaluated — anything else **deletes the guarded
block**, now loudly), malformed `>>DEFINE`, stray `>>ELSE`/`>>END-IF`,
unknown `>>` directives (passed through to the lexer), and unclosed `>>IF`
at end of input. The copybook expansion path (`process_conditionals=True`)
routes these into `ExpansionStatistics.warnings`; the CLI (`--define`)
prints them to stderr. Pinned by
`tests/regression/test_tier4_audit_remediations.py::TestH6CopybookSilentChannels`
/ `::TestH7ConditionalCompilationWarnings`.

# Error Hierarchy

All preprocessing errors extend `PreprocessingError` which extends `ParseError`:

| Exception | When raised |
|-----------|------------|
| `CircularReferenceError` | COPY chain forms a cycle |
| `CopybookNotFoundError` | No matching file on any search path |
| `PathTraversalError` | COPY target escapes the allowed directory |
| `EncodingError` | Cannot decode copybook bytes |
| `NestingDepthError` | COPY nesting exceeds configured limit |

# See Also

* [lexer.md](lexer.md) — consumes output of `normalize_fixed_format`
* [parser.md](parser.md) — `CobolParser` calls `strip_compiler_directives` internally
