---
type: Module
title: Preprocessing
description: normalize_fixed_format, copybook expansion, conditional compilation — converts raw COBOL to lexer-ready text.
tags: [preprocessing, copybook, fixed-format, conditional-compilation]
timestamp: 2026-07-09T00:00:00Z
---

# Overview

`cobolparser/preprocess/` — the first stage of the parse pipeline. Converts
raw fixed-format COBOL source into free-form text that the lexer can consume,
and optionally inlines COPY statements recursively.

# Pipeline

```
raw COBOL (fixed format)
  ──► normalize_fixed_format()   # columns 8-72, blanks comment/blank lines (preserving line numbers), merges continuations
  ──► expand_copybooks()         # optionally: inline COPY … REPLACING … statements
  ──► strip_compiler_directives()# drop compiler control statements (used inside CobolParser)
  ──► strip_unexpanded_copy_statements() / apply_replace_statements()  # source-text manipulation (inside CobolParser, pre-lex)
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
    lines: list[str] | str,
    *,
    merge_continued_literals: bool = True,
    debug_lines_as_comments: bool = True,
) -> str: ...
```

Each line is tab-expanded (`str.expandtabs(8)`, added 2026-07-09 —
finding M8) **before** any column-index slicing, so a tab in the source
doesn't shift the indicator/text-area columns. Extracts columns 8–72 from
each line, drops comment lines (column-7 is `*`/`/`, or `D`/`d` when
`debug_lines_as_comments` is true — the default, added 2026-07-09 for
finding M4 to match `copy_statement_parser.is_comment_line()`, which
already treated `D`/`d` as a comment; pass `debug_lines_as_comments=False`
to compile debug lines as live code instead), and merges continuation
lines (column-7 is `-`). Returns a single free-form text string.

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

**Trailing blanks in a continued literal** (fixed 2026-07-09, finding M5):
a line's text is only `rstrip()`-ped once it's known no literal is left
open at end of line. A literal that remains open (continuing to the next
line) keeps its trailing blanks, since fixed-format continuation rules
make them part of the literal's value — e.g. opening line `VALUE "ABC   `
(3 trailing blanks) + continuation `-    "DEF".` now normalizes to
`VALUE "ABCDEF"` → correctly `"ABC   DEF"`, not the pre-fix `"ABCDEF"`
(blanks silently dropped). Applies to both the opening-line branch and
the literal-continuation branch, pure-Python and Cython.

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

**`total_bytes` accounting on cache hits (fixed 2026-07-09, finding
M14):** `_expand_source_recursive`'s intra-expansion cache (`context.
content_cache`, keyed by copybook path + REPLACING clauses — for diamond
dependencies, the same member `COPY`d multiple times within one
expansion) previously only counted a copybook's bytes toward
`context.total_bytes` on a cache **miss**. A cache hit still inserts the
same real content into the expansion, so `max_total_size` was silently
under-enforced: 3x inclusion of a 76-byte copybook with `max_total_size=
114` (1.5x) never raised `TotalExpansionSizeExceededError`, despite ~228
true content bytes. Cache hits now add the cached content's byte length
to `context.total_bytes` and re-check the limit, identically to a miss.

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

**Conditional-compilation diagnostics (audit 2026-07-07 H7; semantics
completed 2026-07-20, M10):**
`preprocess_conditional_compilation(source, defined_symbols, warnings=None)`
now **evaluates** `>>IF` conditions instead of blanking on anything beyond
`DEFINED`: comparisons (`=`, `<>`, `>`, `<`, `>=`, `<=`) between symbol
values and numeric/string literals, `DEFINED(sym)` / `sym IS [NOT]
DEFINED`, and `AND`/`OR`/`NOT` with parentheses. `defined_symbols` accepts
the legacy name-only set/list forms *or* a `dict[str, str | int | float |
bool]` carrying values (values from the CLI's existing `--define
NAME=VALUE` form now take effect).
`>>EVALUATE sym` (literal `>>WHEN`s), `>>EVALUATE TRUE` (condition
`>>WHEN`s), `>>WHEN OTHER`, and `>>END-EVALUATE` are implemented.
Warnings still appended: a comparison referencing an **undefined symbol**
(warns, evaluates false), genuinely unparseable `>>IF` conditions
(warn + skip, as before), malformed `>>DEFINE`, stray `>>ELSE`/`>>END-IF`,
unknown `>>` directives (passed through to the lexer), and unclosed
`>>IF` / `>>EVALUATE` at end of input. Directive/skipped lines are still
blanked in place so line numbers stay stable. The copybook expansion path
(`process_conditionals=True`) routes warnings into
`ExpansionStatistics.warnings`; the CLI (`--define`) prints them to
stderr. Pinned by
`tests/regression/test_tier4_audit_remediations.py::TestH6CopybookSilentChannels`
/ `::TestH7ConditionalCompilationWarnings` (updated to the new semantics)
and `tests/regression/test_open_findings_m10_regression.py`.

# Source-Text Manipulation: REPLACE + un-expanded COPY (2026-07-14)

`preprocess/replace_statement.py` implements the two source-text
pseudo-text-substitution passes the standalone (non-copybook-expanding) parse
pipeline needs. Both run inside `CobolParser._parse_core` on the normalized
free-form source, immediately before `CobolLexer`, and both preserve their
input's physical line count (every newline in a removed/replaced span is
re-emitted). Each is a cheap no-op when its keyword is absent.

```python
from cobolparser.preprocess.replace_statement import (
    apply_replace_statements,          # REPLACE ==a== BY ==b== . / REPLACE OFF.
    strip_unexpanded_copy_statements,  # blank COPY the pipeline won't expand
)
```

* **`apply_replace_statements(source, warnings=None)`** — applies the
  `REPLACE ==pseudo-text-1== BY ==pseudo-text-2== [ ... ] .` compiler-directing
  statement (one or more operand pairs) and cancels the active set at
  `REPLACE OFF.`. A new `REPLACE` **replaces** the active set rather than
  accumulating. Matching is on a COBOL **text-word** stream (`_tokenize_text_words`):
  * space / comma / semicolon separators are equivalent and are *not* text
    words (so `MOVE; "FAIL" , TO` matches `MOVE , "FAIL"; TO`);
  * a **separator period** is its own text word (so a find of
    `MOVE WS-A TO WS-B` matches source `MOVE WS-A TO WS-B.` and leaves the
    sentence period in place);
  * a literal (`"..."` / `'...'`) is one text word compared case-sensitively;
    other words compare case-insensitively;
  * a decimal point inside a numeric literal (`3.14`) stays part of the word.

  Each source segment between REPLACE statements is rewritten by a single
  left-to-right word scan (first active pair to match at a position wins);
  the REPLACE statements themselves are blanked. `REPLACE` inside a string
  literal is ignored. A `warnings` list receives a diagnostic if a set is
  still active at EOF (no closing `REPLACE OFF.`).

* **`strip_unexpanded_copy_statements(source, warnings=None)`** — blanks
  `COPY` statements the standalone pipeline is not going to expand
  (`parse_cobol` does not resolve copybooks). It **reuses `CopyStatementLexer`**
  (the same pseudo-text-aware scanner the expansion path uses — one COPY
  parser, not a divergent second one) to find each statement's full span,
  including a `REPLACING ==pseudo-text==` operand that legally contains COBOL
  statement keywords and periods. Removing the whole statement mirrors a
  compiler with the copybook unavailable and stops that pseudo-text from
  leaking as a malformed statement (e.g. `BY MOVE ==DELETE==` had leaked a
  `MOVE` with no `TO`). In the **copybook-expansion** pipeline COPY is already
  inlined before this point, so the strip is a no-op there. `warnings` receives
  one diagnostic per removed COPY plus any the lexer recorded.

These two passes are what let NIST `SM208A` (30x `REPLACE`) and `SM206A`
(`COPY ... REPLACING` pseudo-text) parse error-free; pinned by
`tests/regression/test_replace_and_copy_pseudo_text.py`.

# Copybook Path Resolution (`path_resolver.py`)

`PathResolver.resolve(member_name)` finds a copybook file across
`CopybookSearchPath.directories`, in three tiers of increasing cost:

1. **Tier 1** — a resolution cache keyed by `member_name` (exact repeat
   lookups are O(1) with no filesystem access).
2. **Tier 2** — a per-directory index (`_dir_index`, built once via
   `os.scandir()`) keyed by uppercased basename-without-extension, for
   O(1) lookup against every directory without re-scanning.
3. **Tier 3** — a full filesystem search (`find_copybook_file`) as the
   fallback when the index misses.

All three tiers funnel through `validate_path_within_directory(path,
search_dir)`, which resolves symlinks (`Path.resolve()`) and confirms the
resolved path is still inside `search_dir` before it can be returned —
this is the directory-traversal containment check.

**Tier-2 containment gap (audit 2026-07-08, finding H6, fixed
2026-07-09):** the Tier-2 fast path returned `self._dir_index[lookup_key]`
after only an `os.path.getsize()` check — it never called
`validate_path_within_directory()`, unlike Tier 3. Since the index is
built via `os.scandir()` + `entry.is_file()` (which follows symlinks), a
symlink inside a search directory pointing outside the search root would
have been served with no containment check. Fixed by a new
`PathResolver._validate_indexed_result(result)` method (iterates
`search_config.directories`, validating against each, raising
`PathTraversalError` if none contain the result) called at both Tier-2
hit points (exact `lookup_key` match and extension-suffixed `ext_key`
match). A live Windows symlink needs elevated privilege to create in CI,
so the regression test seeds `_dir_index` directly with an
escaping absolute path instead — exactly what a followed symlink would
produce.

Separately (same finding, H6), the `".." in file_path` traversal guard
(`preprocess/__init__.py`'s `validate_path_within_directory`) was naive
substring matching — a filename merely *containing* `".."` (e.g.
`weird..name.cpy`) triggered `PathTraversalError` despite not being a
traversal attempt. Now a path-segment check: `.replace("\\", "/").split
("/")` and reject only when a whole segment equals `".."`. Both pinned by
`tests/regression/test_open_findings_high_regressions.py::TestH6PathResolverContainment`.

# Line-Number Preservation (audit 2026-07-08)

`normalize_fixed_format` used to silently *drop* blank/short lines and
comment lines (indicator `*`/`/`) — no placeholder was appended for them —
so every subsequent line's number shifted by however many such lines
preceded it. Every real COBOL program has blank/comment lines, so a "clean"
parse could report an error several lines away from the actual problem.
Fixed by appending an empty string to `result` for each dropped line instead
of a bare `continue`, in both the pure-Python implementation and
`_preprocess_fast.pyx` (checked-in `.c` regenerated). `output.count("\n")`
now always equals the input line count.

`preprocess_conditional_compilation` had the same gap for `>>DEFINE`/`>>IF`/
`>>ELSE`/`>>END-IF` directive lines *and* for source lines inside a skipped
`>>IF` block (deleted outright rather than blanked) — fixed the same way:
every non-included physical line contributes an empty placeholder to
`result_lines`, so `len(output.split("\n"))` always equals the input's
`splitlines()` length.

Pinned by `tests/regression/test_normalize_line_number_preservation.py`,
which also confirms the Cython/pure-Python paths agree.

# Error Hierarchy

All preprocessing errors extend `PreprocessingError` which extends `ParseError`:

| Exception | When raised |
|-----------|------------|
| `CircularReferenceError` | COPY chain forms a cycle |
| `CopybookNotFoundError` | No matching file on any search path |
| `PathTraversalError` | COPY target escapes the allowed directory |
| `EncodingError` | Cannot decode copybook bytes |
| `NestingDepthError` | COPY nesting exceeds configured limit |

# Context-Aware REPLACING + Encoding Detection (2026-07-20, M13/M15)

**REPLACING is context-aware (M13):** `apply_replacing_clauses`
(`copy_statement_parser.py`) is a line-based scanner, not whole-text regex.
Fixed-format comment lines (column-7 `*`/`/`, mask computed once from the
original content) are never rewritten; text inside string literals (both
quote styles, doubled-quote escapes, unterminated literal runs to EOL) is
never rewritten — *unless* the clause's own search text contains a quote
(quoted pseudo-text deliberately targets literal text). Boundary semantics
(hyphen-aware word boundaries, longest-first ordering, LEADING/TRAILING,
case-insensitivity) are unchanged. `CopyStatementLexer._read_operand`
recognizes `:ABC:` pseudo-text and strips the delimiters, so
`REPLACING :ABC: BY :XYZ:` substitutes `ABC`→`XYZ` (previously a silent
no-op — the colons were captured as literal text). No Cython mirror.
Pinned by `tests/regression/test_open_findings_m13_regression.py`.

**Encoding detection + strictness (M15):** `detect_encoding`
(`copybook_expander.py`) scores ASCII-vs-EBCDIC plausibility over a
bounded 64 KiB prefix (BOM / strict-UTF-8 checks first, then COBOL-charset
proportion, EBCDIC newline conventions 0x15/0x25, keyword tiebreaker via
`_score_cobol_plausibility`) instead of the old single 0x40-vs-0x20
byte-ratio test — an ASCII file full of `@` (0x40) is no longer
misdetected. `CopybookSearchPath.encoding_errors` /
`expand_copybooks(..., encoding_errors=...)` selects decode strictness:
`"replace"` (default) substitutes U+FFFD and warns with a replacement
count; `"strict"` raises `EncodingError` with file/offset context. Pinned
by `tests/regression/test_open_findings_m15_regression.py`.

# See Also

* [lexer.md](lexer.md) — consumes output of `normalize_fixed_format`
* [parser.md](parser.md) — `CobolParser` calls `strip_compiler_directives` internally
