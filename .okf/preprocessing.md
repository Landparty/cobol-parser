---
type: Module
title: Preprocessing
description: normalize_fixed_format, copybook expansion, conditional compilation — converts raw COBOL to lexer-ready text.
tags: [preprocessing, copybook, fixed-format, conditional-compilation]
timestamp: 2026-08-14T00:00:00Z
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
| `preprocess/__init__.py` | **Thin re-export stub only.** Re-exports everything from `_normalize.py` (including the fixed-format column constants `DEFAULT_SEQ_COL_END` / `INDICATOR_COL` / `TEXT_START_COL` / `TEXT_END_COL`, which stay reachable at `cobolparser.preprocess` for external consumers) plus `copybook_expander.py`, and swaps in the `_preprocess_fast` Cython `normalize_fixed_format` when compiled (keeping the pure one reachable as `_normalize_fixed_format_pure`). Deliberately holds no implementation — the closed-source release build ships every `__init__.py` as readable `.py` source (see `setup.py`) |
| `preprocess/_normalize.py` | `normalize_fixed_format`, `strip_compiler_directives`, `preprocess_conditional_compilation` (with the `_ConditionParser` / `_evaluate_condition` constant-condition evaluator), `validate_copybook_content`, `validate_level_numbers`, plus the `PreprocessingError` hierarchy. Split out of `__init__.py` on 2026-08-14; every name stays importable from `cobolparser.preprocess` unchanged |
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
    warnings: list[str] | None = None,
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

**Column 73+ overflow warning** (added 2026-08-03): the `line[TEXT_START_COL
- 1 : TEXT_END_COL]` slice never bounds-checked the line length, so any
non-comment line longer than 72 columns had its columns-73+ tail silently
dropped — no warning, no error. Found via a whole-branch review of
mocky-mock's `export` command: a hand-written 77-column `DISPLAY "X"
WS-FIELD.` line (56 columns of indentation) was silently chopped to
`DISPLAY "X" WS-F` — no closing quote, no period — and mocky-mock still
wrote it to its "durable deliverable" output and exited 0.

Columns 73–80 are the identification area, and real fixed-format compilers
ignore them regardless of content — traditional 80-column source
legitimately puts non-blank sequence/identification text there (e.g. NIST
CCVS85's `IC1014.2`, repeated on every line of the vendored
`examples/nist-cobol85` corpus). Flagging every such line would be noise. So
`normalize_fixed_format` only flags a line whose column 72 (the last kept
character) **and** column 73 (the first dropped character) are *both*
non-blank — content actually split mid-token, not merely followed by an
unrelated identification field. Comment lines (column-7 `*`/`/`, or `D`/`d`
when `debug_lines_as_comments` is true) are never checked: their text is
discarded whether truncated or not, so truncation there changes nothing.

When `warnings` is passed a list, each qualifying line appends one
`f"Line {n}: content beyond column {TEXT_END_COL} was dropped mid-token:
{dropped!r}"` message (`n` is the 1-based physical line number). Default
`None` means the check still runs but nothing is collected — existing
callers that don't pass `warnings` see no behavior change (still silently
truncates). The pure-Python and Cython (`_preprocess_fast`) paths produce
byte-identical warning text; pinned by
`tests/regression/test_normalize_column_overflow_warning.py`, including a
parity test over the `warnings` list itself (not just the returned string).

Callers that want to turn this into a hard refusal (mocky-mock's `export`
command does, via `checks.py` → `mockymock/analysis/refusal.py`'s
`check_normalize_warnings`) should treat every entry in the returned list as
actionable — the mid-token filter above already excludes the traditional
sequence-number/identification-area case, so there is no further filtering
to do caller-side.

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

**Sequence/identification areas stripped before REPLACING and
conditional compilation (fixed 2026-07-21):** in `_expand_source_recursive`,
a copybook's sequence-number (columns 1-6) and identification (columns
73-80) areas used to be stripped (`strip_sequence_area` +
`remove_comment_lines`) only *after* `apply_replacing_clauses`,
`preprocess_conditional_compilation`, `validate_copybook_content`, and
`validate_level_numbers` had already run on the raw 80-column line. Two
concrete failures: (1) a length-changing `REPLACING` shifts every character
after its match point on that raw line, so the column-72 boundary — applied
afterward — lands in the wrong place: a shrinking replacement pulls
identification text into the kept code window, a growing one truncates real
code (including its terminating period); (2) `>>IF`/`>>END-IF` inside a
copybook with real (non-blank) numeric sequence numbers were never
recognized as directives, since the raw sequence-number digits sit before
`>>` on the line. Fixed by moving the strip to run immediately after the
copybook is read from disk, before any of those four calls.
`apply_replacing_clauses` gained an `indicator_position: int = 6` parameter
(same pattern as `normalize_continuation_lines`) so it can locate the
indicator column correctly whether it's operating on raw (index 6) or
already-stripped (index 0) content, and `_expand_source_recursive` gained an
`already_stripped: bool = False` parameter so its own internal strip is
skipped when the caller already normalized the content (avoiding a
double-strip that would eat 6 more real characters off each line). Pinned by
`tests/regression/test_copybook_sequence_area_before_replacing.py`.

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

**`validate_copybook_content` missing-period regex no longer crosses blanked
comment lines, and comment-only copybooks report correctly (fixed
2026-07-27):** `_DATA_DEF_RE` (the "may be missing terminating period"
check) used bare `\s` for its leading/internal/trailing whitespace, which
matches newlines. Since `remove_comment_lines` blanks comment lines to
whitespace-only lines *before* `validate_copybook_content` runs (see the
sequence/identification-area strip above), `^\s*` could bridge across those
blanked lines to a later real code line, and `[^\s]+` — not excluding `.` —
swallowed a data item's trailing period as part of the "value" token.
Together this produced false "missing terminating period" warnings on
correctly-terminated lines, misattributed to the wrong line (typically a
blanked comment line above, not the real code line). Fixed by switching
every internal `\s`/`\s+`/`\s*` to `[ \t]`/`[ \t]+`/`[ \t]*` (space/tab
only — can't cross a line) and the value token to `[^\s]*[^\s.]` — "one or
more non-whitespace characters, the last of which is not a period". This
excludes only a *trailing* period (the sentence terminator), not an
*internal* one: a decimal-point PICTURE like `PIC 9(5).99` (no terminator)
is still correctly flagged, while `PIC 9(5).99.` (terminated) is not. An
earlier draft of this fix used `[^\s.]+` (excludes periods everywhere in
the token), which silently stopped detecting missing terminators on any
decimal-point PIC — caught in review before landing; pinned by
`test_missing_period_detected_with_decimal_point_pic` /
`test_no_false_positive_with_decimal_point_pic`.

Separately, the "contains only comments" check
(`lines = [... not line.strip().startswith("*") ...]`) was dead code when
reached through the real pipeline: by the time `validate_copybook_content`
runs, `remove_comment_lines` has already blanked every comment line, so
`content` can never contain a literal `*`-prefixed line — a genuinely
comment-only copybook instead falls into the earlier "is empty" branch,
which is misleading (comment-only is a legitimate documentation-only
pattern, not an empty file). `validate_copybook_content` gained an optional
`raw_content: str | None` parameter: when the post-strip `content` is blank
but `raw_content` (the pre-strip source) is not, the warning is "contains
only comments" instead of "is empty". `_expand_source_recursive` now
captures the copybook's raw content before the sequence/comment strip and
passes it through. Direct callers that omit `raw_content` keep the old
behavior — exercised by `TestValidateCopybookContent::test_comment_only`,
which passes raw `*`-comment lines straight in without going through
`remove_comment_lines` first. Pinned by
`tests/unit/test_preprocess_init_coverage.py::TestValidateCopybookContent`
and `tests/unit/test_copybook_expander_coverage.py::TestExpandCopybooks::
test_content_validation`.

**Caller-supplied `path_resolver` honored (audit 2026-08-12, P-D1):**
`expand_copybooks(..., path_resolver=...)` used to overwrite the parameter
unconditionally with a fresh `PathResolver`; a caller-supplied resolver
(whose warm resolution/directory-index caches are the whole point of
passing one — `batch.parse_files_with_copybooks` does) is now used as-is,
and a new one is constructed only when the argument is `None`. Note the
supplied resolver's own `search_config` governs nesting/size/encoding
limits during expansion. Pinned by
`tests/regression/test_audit_2026_08_12_core.py::TestPD1CallerSuppliedPathResolver`.

**`COPY_PATTERN` removed (audit 2026-08-12, S-1):**
`copy_statement_parser.py` exported a monolithic `COPY_PATTERN` regex that
was unused by the live expansion path (the real scanner is
`CopyStatementLexer.tokenize_copy_statements`, a linear hand-written lexer)
and whose ambiguous REPLACING sub-pattern backtracked exponentially on
unterminated input (`COPY X REPLACING BY BY ... BY %`). Deleted (and
removed from `__all__`) rather than de-ambiguated. Guarded by
`tests/regression/test_audit_2026_08_12_core.py::TestS1CopyPatternRemoved`.

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
   `os.scandir()`) keyed by uppercased basename-without-extension AND full
   filename, for O(1) lookup against every directory without re-scanning.
3. **Tier 3** — a full filesystem search (`find_copybook_file`) as the
   fallback when the index misses.

**Tier precedence is first-configured-directory-wins everywhere (audit
2026-08-12, P-B6):** when the same copybook name exists in two search
directories, the first configured directory wins for the Tier-2 stem key,
the Tier-2 full-filename key, and Tier 3 alike. Previously the Tier-2
full-filename key alone was *last*-directory-wins (built with an
unconditional `index[name_upper] = abs_path` instead of `setdefault`), so
`resolve("SHARED.cpy")` and `resolve("SHARED")` could return files from
different directories. Pinned by
`tests/regression/test_audit_2026_08_12_core.py::TestPB6FirstDirectoryWins`.

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

**`flush_parts()` still dropped one line shape (fixed 2026-08-10, issue
#123):** the 2026-07-08 fix above covers "short/blank physical line" and
"`*`/`/`/debug comment line" — both explicitly emit an empty placeholder.
A third shape falls through neither special case: a full-width physical
line with a blank (non-comment) indicator column whose extracted
program-text (columns 8-72) is itself entirely blank. This starts a new
logical line, buffers an empty string into `parts`, and used to only reach
`result` via `flush_parts()`'s `if combined: result.append(combined)` —
which is false for an empty string, so the line vanished with **no**
placeholder at all (not even the correct empty one). This shape never
arises in a plain fixed-format parse — a blank line is always short, and a
comment line always has a non-blank indicator — so it went unnoticed until
copybook expansion: `copy_statement_parser.remove_comment_lines` blanks a
`*`-comment line to an all-spaces string of the *same length*, indicator
column included, before `CobolParser._parse_core` re-runs
`normalize_fixed_format` on the already-expanded source. On that second
pass the former comment line has nothing left to recognize it as a
comment, so it takes the buggy generic path instead. Symptom: `program-flow`
`location.line` (and any other lexer/parser line number) drifted backward
by exactly one per full-line comment anywhere earlier in the file, but
only in source with at least one `COPY` statement. Fixed in both
`normalize_fixed_format` and `_preprocess_fast.pyx` by tracking whether a
logical line was actually *started* (`has_line`, reset on each flush, set
whenever a physical line is consumed into `parts`) rather than inferring
that from whether the merged text happens to be non-empty. Pinned by
`tests/regression/test_normalize_line_number_preservation.py`
(`TestNormalizeFixedFormatPreservesFullWidthBlankLines`,
`TestCopybookCommentDriftIssue123`).

**Known residual (not fixed by the above): +1 phantom line per `COPY`.**
The per-comment *drift* is gone and the copybook-expansion offset is now
constant per file, but that constant itself is one line larger than the
copybooks' real combined content for every `COPY` statement in the file —
`copybook_expander.py::_expand_source_recursive`'s splice re-inserts each
copybook's own trailing `"\n"` into a span that already ends in one. See
`reports/open-findings.md` (LOW) for the measured `+1`-per-`COPY` table and
exact splice location.

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
