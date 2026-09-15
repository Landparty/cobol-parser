---
type: Module
title: Preprocessing
description: normalize_fixed_format, copybook expansion, conditional compilation — converts raw COBOL to lexer-ready text.
tags: [preprocessing, copybook, fixed-format, conditional-compilation]
timestamp: 2026-09-15T00:00:00Z
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
| `preprocess/__init__.py` | **Thin re-export stub only.** Re-exports everything from `_normalize.py` (including the fixed-format column constants `DEFAULT_SEQ_COL_END` / `INDICATOR_COL` / `TEXT_START_COL` / `TEXT_END_COL` / `IDENTIFICATION_END_COL`, which stay reachable at `cobolparser.preprocess` for external consumers) plus `copybook_expander.py`, and swaps in the `_preprocess_fast` Cython `normalize_fixed_format` when compiled (keeping the pure one reachable as `_normalize_fixed_format_pure`). Deliberately holds no implementation — the closed-source release build ships every `__init__.py` as readable `.py` source (see `setup.py`) |
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
    version_tag_lines_as_comments: bool = True,
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

**`V`/`v` version-tag lines (added 2026-08-22):** `V`/`v` in column 7 is
also treated as a comment by default (`version_tag_lines_as_comments`,
default `True`), matching a real shop's change-control convention that
stamps a short version tag (e.g. `V97`, `TFEC`) into Area A with `V` in
column 7 of its own line. Standard fixed-format COBOL never puts live code
in column 7 (reserved for `*`/`/`/`-`/`D`/`d`), so this is unambiguous with
real source. Without it, the tag text reached the lexer as un-normalized
code and surfaced as "Unparsed tokens" errors. Pass
`version_tag_lines_as_comments=False` to compile V-lines as live code
instead. `copy_statement_parser.is_comment_line()` and
`parser._detect_fixed_format`'s valid-indicator set were updated to match,
on both the pure-Python and Cython (`_preprocess_fast`) paths. Pinned by
`tests/regression/test_version_tag_line_handling.py`.

**Change-tracking tags in columns 1-6 (added 2026-08-25):** a related shop
convention stamps a ticket id (`SAPR24`, `28486`, `GART`, `JSINT`) into the
*sequence area* rather than column 7. `normalize_fixed_format` always
handled these — it slices `line[7:72]` regardless of what columns 1-6 hold
— but `parser._detect_fixed_format`, which decides *whether* to normalize
at all, counted a line as fixed-format evidence only when columns 1-6 were
blank or all digits. A tagged program therefore fell below the 60%
threshold, was classified free-form, skipped normalization entirely, and
its tag text reached the lexer as code (`No recognizable COBOL division
found near 'SAPR24'`). Because the detector samples only the first 10
non-blank lines, the misclassification could also flip as copybook
expansion changed which lines those were, making it look intermittent.

Detection now applies a second rule: a *tag-like* sequence area (a single
unbroken `[A-Za-z0-9][A-Za-z0-9_/#$.-]*` token — the "no internal
whitespace" property is what excludes ordinary free-form statement text
like `MOVE A`) also counts, but only when corroborated by an Area A
division header, i.e. a line whose columns 8+ start with
`IDENTIFICATION DIVISION`/`PROGRAM-ID`/etc. **at a word boundary** — the
header must be followed by a period, a space, or end of text, so an
identifier merely starting with a header string (`PROGRAM-ID-VAL`) can
never anchor. Free-form source puts real headers at column 1, where the
`line[7:]` slice lands mid-word and cannot match, so the anchor is what
keeps rule 2 from dragging free-form input in. The anchor scan is bounded
(`_HEADER_SCAN_LIMIT` candidate lines), but comment lines (column-7
indicator) and too-short lines do not consume the budget — tag-stamping
shops open programs with 100+-line change-history banners, which would
otherwise push the header out of the window and re-introduce the
misclassification. The strict blank/digit rule still decides on its own
and is unchanged, so this only ever *adds* detections. Pinned by
`tests/regression/test_tagged_sequence_area_detection.py`; the
`--source-format` escape hatch for layouts neither rule infers is in
[cli.md](cli.md).

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

**Line numbers survive continuation** (fixed 2026-09-09). A continuation
record used to vanish from the output — N physical lines became one logical
line — so every location after the first continued literal in a program was
off by the number of continuation records seen so far (a `MOVE` on physical
line 10 reported line 8). The normalizer now counts the continuation records
a logical line absorbed and emits that many empty placeholder lines *after*
the flushed logical line, so `output.count("\n") == len(lines)` for every
input and the logical line keeps its first record's number. The same
deferred-placeholder mechanism means a comment (or blank) line that
interrupts an open continued literal no longer severs it: the placeholder is
deferred, the next `-` record rejoins the literal (the IBM rule — the
continuation is the next line that is neither a comment nor blank). A
literal still open on the last *code* line still raises. `*>` inline
comments are now skipped by the quote-state scan, so an apostrophe inside
one no longer reads as an unterminated literal. The lexer's
`_fixed_format_comment_tokens` emits COMMENT tokens at physical line numbers
whenever that count invariant holds (it always does now).

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
`normalize_fixed_format` flags a line under either of two rules:

1. **Mid-token split** — column 72 (the last kept character) **and**
   column 73 (the first dropped character) are *both* non-blank — content
   actually split mid-token, not merely followed by an unrelated
   identification field.
2. **Word-boundary overflow** (added 2026-08-14) — the split lands on a
   space at column 72/73 (rule 1 misses it), but the line's real content,
   after trailing whitespace is stripped, extends past column 80 — the
   traditional maximum width of an 80-column punch-card line (72 code + 8
   identification). Content that survives past column 80 can never be
   legitimate identification-area text, wherever exactly it broke. Found
   via a data-item-layout test fixture: `OCCURS 1 TO 10 TIMES DEPENDING ON
   WS-COUNT.` written on one line kept `DEPENDING` (it fit by column 72)
   but silently dropped its ` ON WS-COUNT.` operand — columns 72/73
   straddle a space, so rule 1 alone never caught it, producing a silently
   *fixed* `OCCURS 10 TIMES` with no ODO clause and no diagnostic.

Comment lines (column-7 `*`/`/`, or `D`/`d`/`V`/`v` when
`debug_lines_as_comments`/`version_tag_lines_as_comments` is true) are never
checked under either rule: their text is discarded whether truncated or
not, so truncation there changes nothing.

**Sequence-numbered lines gate both rules** (added 2026-08-14, alongside
rule 2). Wiring the mid-token rule into the real parse pipeline for the
first time exposed that it's far noisier on genuinely traditional
80-column source than its own 2026-08-03 tests suggested: measured against
the vendored NIST CCVS85 corpus, 4434 of 4438 raw column-72/73 "mid-token"
hits were lines like `examples/cobol/IX209A.CBL:292` —
`029100          "...".IX2094.2` — where the statement's own closing
period genuinely lands on column 72 and the file's own per-line
identification code starts immediately at column 73 with zero authoring
mistake; nothing was actually split. A real numeric sequence number in
columns 1-6 (all digits, ignoring surrounding blanks) is independent,
reliable evidence a line belongs to that convention — hand-typed modern
source never bothers with sequence numbers — so both rules now skip
entirely whenever columns 1-6 hold one. Re-measured after the gate: 4
residual hits across the full vendored corpus, all genuine (harmless)
truncation of `*>` free-form inline-comment text running past column 72 in
files the preprocessor doesn't yet parse `*>` semantics for (that
recognition is lexer-level, not preprocessor-level — a separate, smaller
gap left as-is).

**Rule 1 has a second, independent gate: a purely-numeric dropped tail
never warns either** (added 2026-08-22). The columns-1-6 gate above assumes
the traditional convention stamps a sequence number at the *start* of the
line; some real shops instead (or additionally) stamp a per-line, purely
numeric sequence/change-tracking number into columns 73-80 with columns 1-6
left blank — e.g. IBM Z Open Editor/ISPF-style auto numbering such as
`03050009`, incrementing on nearly every line. Found via a real vendored
program (`WS000-D0000022-X PIC X(008) VALUE 'D0000022'.` immediately
followed, no separating blank, by `03050009`): the VALUE clause's own
closing period lands exactly on column 72, satisfying rule 1's mid-token
shape by column position alone even though columns 1-6 are blank and
nothing was actually split. `normalize_fixed_format` now also skips rule 1
whenever the dropped tail (`line[TEXT_END_COL:]`, right-stripped) is
non-empty and entirely digits *and* the line's total width still fits the
traditional 80-column identification-area boundary
(`not exceeds_traditional_width`) — a longer numeric run spilling past
column 80 is no longer plausible identification-area content and still
warns via rule 2. This is deliberately narrower than "any dropped tail":
a mixed alphanumeric tail like NIST's own `IX2094.2` test-case id does
**not** qualify (`.isdigit()` rejects it), so
`test_blank_sequence_area_with_same_shape_still_warns` — locking in that a
period-then-identification-text shape with blank columns 1-6 is still
flagged as a likely authoring mistake — is unaffected. Pinned by
`test_numeric_identification_stamp_does_not_warn_with_blank_seq_area` and
`test_numeric_identification_stamp_still_warns_past_traditional_width` in
`tests/regression/test_normalize_column_overflow_warning.py`.

When `warnings` is passed a list, each qualifying line appends one message
to it — `f"Line {n}: content beyond column {TEXT_END_COL} was dropped
mid-token: {dropped!r}"` for rule 1, or `f"Line {n}: content beyond column
{TEXT_END_COL} was dropped -- line is {content_len} columns wide, past the
traditional {IDENTIFICATION_END_COL}-column identification-area width:
{dropped!r}"` for rule 2 (`n` is the 1-based physical line number). The
pure-Python and Cython (`_preprocess_fast`) paths produce byte-identical
warning text; pinned by
`tests/regression/test_normalize_column_overflow_warning.py` (unit-level,
both rules, fast/pure parity) and
`tests/regression/test_fixed_format_word_boundary_overflow.py` (end-to-end
through `parse_cobol()`/`CobolParser.parse()`).

**Wired into the real parse pipeline (fixed 2026-08-14).** From
2026-08-03 to 2026-08-14 this was opt-in only — `warnings=None` by default
meant the check still ran internally but nothing was collected, and *none*
of the library's own entry points (`CobolParser.parse()`'s fixed-format
auto-detection in `_parse_core`, the module-level `parse_cobol()`
convenience function, `lexer.py`'s `_tokenize_source` / `tokenize_cobol()`,
and the CLI's `preprocess` subcommand) passed `warnings=` — so the
diagnostic channel existed but was completely unreachable from a normal
parse, and every one of those callers silently truncated with zero
indication. All four now collect and surface it: `CobolParser.parse()` and
`parse_cobol()` add it to `ParseResult.warnings` (a `CobolParser.
__init__(initial_warnings=...)` parameter carries `parse_cobol()`'s
pre-construction normalization warnings across the `self.warnings.clear()`
at the top of `parse()`, since that normalization runs before the
`CobolParser` instance exists), `_tokenize_source` folds it into its
returned warnings tuple element, and `cobol-parser preprocess` prints it to
stderr (matching the existing `--define` conditional-warnings pattern).
It's a warning, not an error, in both `FAIL_FAST` and `COLLECT_ALL` — the
AST still reflects the (now-diagnosed) truncated source. Callers that want
to turn this into a hard refusal (mocky-mock's `export` command does, via
`checks.py` → `mockymock/analysis/refusal.py`'s `check_normalize_warnings`)
should treat every entry in the returned list as actionable — the filters
above (mid-token, word-boundary, and the sequence-number gate) already
exclude the traditional sequence-number/identification-area case, so there
is no further filtering to do caller-side.

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

**`validate_copybook_content` missing-period check now judges the ENTRY, not
the physical line (fixed 2026-09-12):** `_DATA_DEF_RE` matched a single line
ending in a `PICTURE` clause with no trailing period. But a data-description
entry is one COBOL sentence and is routinely written across several lines --
`05 WS-B PIC X(30)` on one and `VALUE 'TEXT'.` on the next -- so every such
(correct) entry was reported as unterminated. On the `legacy-application`
corpus this produced 8 false warnings on every one of the 20 expansions, all
from one copybook's legal `PIC`/`VALUE` pairs, and those warnings are
rendered into the banner of the expanded listing by the COBOL Analyzer
extension, so they are read by users rather than discarded.

The scan is now `_unterminated_data_entries()`: `_DATA_ENTRY_START_RE` marks
where each entry begins, the entry runs to the line that starts the next one
(or to an `EXEC` block, or EOF), and the *joined* entry text is checked for a
trailing period. `_DATA_DEF_RE` survives as the "is this entry a PICTURE
entry at all" predicate, now matched against the whole entry with `DOTALL`
rather than against one line.

Both patterns are built from one shared `_ENTRY_HEAD` fragment (`\d{1,2}` +
name -- single-digit levels included, since `5 FIELD-B` is legal COBOL).
They must agree on what an entry head looks like, and a first cut of this
fix had them disagree: entry-start detection took `\d{1,2}` while the
predicate still carried the original `\d{2}`, so an entry starting at a
single-digit level closed the entry above it (correct) but could never be
reported for its own missing period (silently unchecked). Sharing the
fragment is what makes that class of drift impossible rather than merely
currently-absent; `test_single_digit_level_entry_is_checked_like_any_other`
pins both directions.

Blank lines deliberately do NOT close an entry: `remove_comment_lines` blanks
comment lines to whitespace *before* this runs (see the 2026-07-27 entry
below), and a comment between an entry's `PIC` line and its `VALUE` line is
ordinary source -- treating the blank it leaves behind as a terminator would
reintroduce the same false positive by another route. Both directions are
pinned by `tests/unit/test_preprocess_init_coverage.py::
TestValidateCopybookContent` (`test_no_false_positive_when_entry_continues_
onto_next_line`, `test_missing_period_detected_on_multi_line_entry`,
`test_multi_line_entry_does_not_swallow_the_entry_below_it`,
`test_blanked_comment_inside_an_entry_does_not_split_it`), alongside the
decimal-point-PIC pair from the earlier fix.

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

**Suggestion pool narrowed to real copybook extensions (2026-09-15):**
`suggest_similar_copybooks`'s did-you-mean candidate pool used to be
built from `get_available_copybooks(search_config)` with the search
config's own `extensions` -- correct for *resolution* (`.cpy`/`.cbl`/
`.cob`, plus `""` meaning "any extension," so a copybook without an
extension still resolves) but wrong for a *suggestion*: every file in
the search directory, including the referencing program's own `.cbl`
source, became a candidate. A missing copybook sitting next to its own
program's `.cbl` file suggested that `.cbl` file back. Fixed by a new
`suggestion_extensions` parameter (default `_SUGGESTION_EXTENSIONS =
(".cpy", ".CPY")`), applied via `dataclasses.replace(search_config,
extensions=...)` before calling `get_available_copybooks` -- the
caller's own `search_config` object is never mutated, and
`suggestion_extensions=search_config.extensions` restores the old broad
pool for a caller that wants it. Pinned by
`tests/regression/test_copybook_suggestion_pool.py`. Reported from
mocky-mock's real-world example corpus; see mocky-mock's
`docs/2026-09-15-copybook-discovery-defaults-design.md`.

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

**Formerly a residual, now fixed: +1 phantom line per `COPY`.** The splice
re-inserted each copybook's own trailing `"\n"` into a span that already
ended in one, so the expansion carried one blank physical line more than the
copybooks' real combined content per `COPY` statement, compounding with
nesting. `_expand_source_recursive` now strips exactly one trailing newline
from `expanded_copybook` (never more, so a member with a genuine blank final
line keeps it) *before* `copybook_line_count` is taken, since that count pads
the spliced-in origins to match. Expanded line counts are now exact:
`len(source) - len(COPY lines) + len(member lines)`.

**The splice reclaims the whole record when the `COPY` owns it.** The COPY
statement's own indentation is not the copied text's. Splicing at the `COPY`
keyword prepended it to the member's first line — pushing a member's `01` out
of Area A by however far right the `COPY` sat, and, on a far-right `COPY`,
past column 72, where `_fit_fixed_format_width` then squeezed the line's
blanks out or wrapped it onto an extra physical line. The splice now starts
at `head_start` (the beginning of the record) whenever `head_has_text` is
false — the same flag the origins splice already computed — and still starts
at the keyword when the parent has real program text before the `COPY` on
that line. Pinned by
`tests/regression/test_copy_splice_keeps_member_columns.py`.

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

# Expansion output: REPLACING width overflow + sequence-area change tags (2026-08-23)

Two `expand_copybooks` *output* defects found in a mainframe corpus retry
(the raw inputs were valid in both cases — only the re-assembled expansion
output was broken):

**REPLACING column overflow.** A `COPY ... REPLACING` whose replacement
text is longer than what it replaces (`==:LKPCB:== BY ==LKPCB-PCB1==`, +3
chars per occurrence) lengthens the lines it lands on; the expander's
6-space re-pad then leaves the tail — typically a data item's terminating
period — past column 72, where the final parse's fixed-format slice
silently drops it ("content beyond column 72 was dropped mid-token: '.'").
A dropped period merges the data item into its neighbor. Fixed by
`_fit_fixed_format_width` (`copybook_expander.py`), applied to every
re-padded line: interior multi-blank runs *outside quoted literals* are
squeezed, rightmost first, each to no less than one blank, until the line
fits — blanks are only separators in COBOL, alignment padding before a PIC
clause almost always has enough slack, and squeezing keeps the line count
(and every later line number) unchanged. When squeezing alone cannot fit
the line, it wraps at the rightmost quote-safe blank onto a fresh Area-B
continuation line (later line numbers then shift — the cost of not
corrupting the statement). A line with no safe break at all (one giant
token or literal) is left untouched so the parse's existing column-72
warning reports the drop instead of this helper corrupting a literal. The
wrap loop anchors its break point *after* the line's first non-blank
character and bails on any iteration that makes no forward progress — the
first version broke at any blank past index 7, and a wrapped tail's own
fresh 11-space prefix re-created such a blank every iteration, so a short
head followed by an unbreakable 62+-char token looped forever emitting
empty heads (caught when it hung the full test suite before ever
shipping).

**Sequence-area change tags.** Shops stamp a short change tag (`P2P`,
`M1005`, `E1A`, ... — any prefix, unlike the column-7 `V` convention
`normalize_fixed_format` handles via `version_tag_lines_as_comments`) into
columns 1-6 of its own line with nothing after it, so the physical line is
under 7 characters. `strip_sequence_area` (`copy_statement_parser.py`)
passed short lines through verbatim (rationalized as "might be
free-format" — incoherent, since the function unconditionally eats 6
leading chars off every full-width line); the 6-space re-pad then shifted
the tag's first letter into the indicator column and the rest into columns
8+ as live code, surfacing as "Unparsed tokens" or silently swallowed
garbage. Fixed: short lines are now blanked — every character of a
sub-7-char line lies within columns 1-6, the exact area the function
exists to strip — with line numbering preserved. (The direct
`parse_cobol` path was never affected: `normalize_fixed_format` already
emits a blank placeholder for sub-7-char lines.)

Both pinned by `tests/regression/test_expansion_width_and_tags.py`.

# Review-pass hardening of the expansion-output fixes (2026-08-23, same day)

A `/code-review` pass over the fixes above confirmed three gaps (each
reproduced before fixing):

1. **`strip_sequence_area` short-line blanking was too eager.** Blanking
   *every* sub-7-character line silently deleted real code from flush-left
   copybooks maintained without sequence numbers (`01 A.` vanished from
   the AST with no warning). Narrowed to tag-shaped content only: a single
   blank-free token that neither ends with a period nor is a
   compiler-directing word (EJECT/SKIP1/SKIP2/SKIP3). `01 A.`, `EXIT.`
   keep the passthrough; `P2P`, `M1005` are still blanked.
2. **Wrap break-point off-by-one.** `head = stripped[:break_at]` has
   length `break_at`, so a break at index 72 yields a 72-character head --
   fully inside the code area -- yet the filter capped at 71, leaving a
   token ending exactly at column 72 unsplittable and silently dropping
   its tail past the slice. Now `<= _CODE_AREA_WIDTH`.
3. **`ExpansionStatistics.total_lines` drift.** The stat was computed from
   the pre-re-pad line list, but the wrap fallback can add lines after
   that; recounted from the final emitted source so the documented "total
   lines in the expanded output" invariant holds.

Also from the same pass: the in-width common case is now guarded at the
re-pad call site (plain `append`, no helper call/rstrip copy per line),
the squeeze pass edits the string directly right-to-left (dropping the
cuts-dict/pieces reassembly), and the dead `not head.strip()` half of the
wrap progress check was removed (the `content_start` filter already
guarantees a non-empty head). Pinned by `TestReviewPassRefinements` and
the updated `TestSequenceAreaChangeTags` in
`tests/regression/test_expansion_width_and_tags.py`.

# See Also

* [lexer.md](lexer.md) — consumes output of `normalize_fixed_format`
* [parser.md](parser.md) — `CobolParser` calls `strip_compiler_directives` internally

# Indicator constants, stamp-gate narrowing, bounded wrap scan (2026-08-24)

* The column-7 comment-indicator characters live in ONE place now:
  `_normalize.py`'s `COMMENT_INDICATORS` (`*` `/`), `DEBUG_INDICATORS`
  (`D` `d`), `VERSION_TAG_INDICATORS` (`V` `v`), and their union
  `ALL_COMMENT_INDICATORS` (all re-exported from
  `cobolparser.preprocess`). Consumers: `normalize_fixed_format` (flag
  gating unchanged), `copy_statement_parser.is_comment_line`,
  `parser._detect_fixed_format`, `lexer._fixed_format_comment_tokens`
  (deferred import). `_preprocess_fast.pyx` keeps mirrored literals with a
  pointer comment — extend both together.
* The numeric identification-stamp gate on the column-72 mid-token
  truncation warning is stricter: the all-digit dropped tail must fill
  columns 73-80 EXACTLY (`content_len == 80`) — the real ISPF/Z Open
  Editor auto-number shape. Any shorter all-digit tail (a data name's own
  trailing digits spilling past 72 on, say, a 75-column line) warns again;
  the first version suppressed those silently. Both normalizers.
* `_fit_fixed_format_width`'s wrap loop uses `_rightmost_safe_blank(line,
  start, after, limit)` — quote-aware scan bounded at column 72 (quote
  state at an index depends only on the prefix), so a pathologically long
  REPLACING-expanded line wraps in O(len) total instead of O(len²).
  `_blank_runs_outside_literals` returns only the squeeze pass's runs now.

**Short-line tag blanking exempts all reserved words (same pass):**
`strip_sequence_area` blanks a sub-7-char single-token line only when the
token is not ANY COBOL reserved word (`_cobol_reserved_words()`, lazily
imported from `CobolLexer.KEYWORDS` -- eager import would be circular).
The first version excluded only EJECT/SKIP1-3, silently deleting flush-left
`GOBACK`/`EXIT`/`STOP` lines during expansion. Pinned by
`tests/regression/test_diff_scan_findings.py`.

**Bare terminal period does not warn (2026-08-24):** the column-72
mid-token overflow warning's rule 1 gains a third gate (alongside the
columns-1-6 sequence-number gate and the numeric-identification-stamp
gate): a dropped tail that is *only* the statement-terminating period
(`dropped == "."` exactly) never warns. Found via a banner-style `VALUE`
literal (`VALUE '**** REPORT TITLE ****'.`) whose closing quote lands
exactly on column 72, immediately followed by the period at column 73 with
no separating blank -- satisfying the "columns 72 and 73 both non-blank"
mid-token shape even though nothing was split: the literal closed cleanly,
and a lone dropped period costs nothing (every statement parser already
tolerates a missing terminating period). A dropped tail that merely
*starts* with a period but carries more (`.B`, `. WS-COUNT`) still warns —
the gate only matches the exact one-character tail. Mirrored in both
`_normalize.py` and `_preprocess_fast.pyx` (`.c` regenerated). Pinned by
`TestBareTerminalPeriodDoesNotWarn` in
`tests/regression/test_normalize_column_overflow_warning.py`.

**Flush-left PROCESS/CBL directive mangled by `strip_sequence_area`
(2026-08-27):** a PROCESS/CBL compiler-directing statement must start in
column 1 per the COBOL standard -- even inside an otherwise strictly
fixed-format program that carries real sequence numbers on every other
line -- so its own columns 1-6 are never a sequence area. `strip_sequence_area`
stripped columns 1-6 from every full-width line unconditionally, so
`PROCESS &CICS-31& &HAUTE-PERFORM-DB2&` was mangled into
`S &CICS-31& &HAUTE-PERFORM-DB2&` before any later PROCESS-stripping pass
(e.g. `strip_compiler_directives`, or a downstream consumer's own
directive handling) ever saw it intact -- the corrupted first line then
surfaced downstream as a missing PROGRAM-ID header. Fixed: a full-width
line is exempted from the columns-1-6 strip (passed through untouched,
not re-sliced at column 7) when its own columns 1-6 do NOT already look
like a real sequence area (blank or all-digit, the same strict test
`_sequence_area_is_fixed_like`/`strip_compiler_directives` use) AND the
line matches `^(?:PROCESS|CBL)(?:[ \t].*)?$` case-insensitively
(`_COMPILER_DIRECTIVE_RE`). Ordinary numbered/tagged source is
unaffected -- the sequence-area gate keeps a data name like
`PROCESS-FLAG` on a real numbered line from being misread as the
directive. Multi-line PROCESS/CBL continuation is out of scope (not
reproduced in the corpus). Pinned by `TestFlushLeftCompilerDirective` in
`tests/regression/test_expansion_width_and_tags.py`.

# Source map and comment preservation (2026-09-07)

Two additions to `expand_copybooks`, both about output that has to be read by
something other than the lexer.

## `preserve_source_locations` finally means something

The flag existed from the start and returned an always-empty dict:
`_expand_source_recursive`'s location branch was a literal `pass` with a note
that "line mapping is approximate or requires new logic". Every consumer
therefore had to *guess* where a line reported against the expanded text
belonged in the file on disk — the VS Code extension re-anchored lint findings
by searching the file for the name each finding was about, which works only
because most rules report something unreferenced, and cannot work at all for a
finding inside an inlined member (that name is not in that file).

`expand_copybooks` now carries a `LineOrigin` (`(file, 1-based line)`) per
expanded line through every step that can move one:

| Step | Effect on lines | How the map survives it |
|------|-----------------|-------------------------|
| `remove_comment_lines`, `strip_sequence_area` | blank in place | line-preserving by construction; nothing to track |
| `normalize_continuation_lines` | merges N records into 1 | new `line_origins` out-parameter records the input line each output line started on |
| the COPY splice | inserts a member's lines | `origins[:start] + copybook_origins + origins[end+1:]`, the first spliced line credited to the parent only when the parent had real text before the COPY on that line — the same flag that decides whether the text splice reclaims the whole record or starts at the `COPY` keyword, so map and text are spliced identically |
| the re-pad's `_fit_fixed_format_width` wrap | 1 line becomes several | every wrapped piece inherits the origin of the line it came from |

`ExpansionContext.content_origins` stores origins beside each cached content
entry (`cache_put(key, value, origins)` / `cache_get_origins`), so a diamond
dependency's *cache hit* contributes the same map a miss would — evicted
together with the content entry it belongs to. `_fit_origins` is the defensive
clamp: a map that ever drifted must mis-attribute nothing and raise nothing.

`expand_copybooks(..., source_file=...)` names the main program in the map
(default `"<main>"`); `parse_cobol_with_expansion` passes the real filename
and always requests the map, exposing it as
**`ParseResult.expansion_source_map`** — `None` when nothing was expanded,
which is exactly the case where expanded and on-disk line numbers are the
same thing. `analysis.lint.apply_source_map` stamps it onto every finding
(`origin_file` / `origin_line`), and the `lint` CLI applies it automatically
whenever `--copybook-path` was given.

Known residual, unchanged: the `+1` phantom line per `COPY` documented under
"Line-Number Preservation" is still there, and shows up in the map as one
extra line attributed to the copybook's own last line + 1.

## `preserve_comments` (`expand --keep-comments`)

Expansion blanks every comment line before it starts, and has to: the COPY
scanner works on the program-text stream, and a `COPY` written inside a
comment must not be expanded. That leaves a *listing* with comment line
numbers and no comment text — throwing away most of what a reader wants.

`preserve_comments=True` puts the original text back afterwards, using the
same map: `_restore_comment_lines` replaces a line only when it is blank in
the expansion AND its origin really is a comment line in its origin file, so
the pass cannot rewrite code. `_origin_sources` reads each member back through
`_cached_read_file` with the expansion's own encoding settings (no extra disk
I/O in the normal case, and never a differently-decoded string); a file that
has become unreadable is skipped rather than failing the expansion. Comment
restoration happens after every substitution and never changes the line count,
so `test_a_copy_inside_a_comment_is_still_not_expanded` holds: the comment text
comes back, the member does not.

Both pinned by `tests/regression/test_expansion_source_map_and_comments.py`
and, at the CLI level, `tests/unit/cli/test_expand_source_map_cli.py`.


# Conditional compilation by default, REPLACE partial words, EXEC SQL INCLUDE (2026-09-15)

* `CobolParser.parse` runs `preprocess_conditional_compilation` on every
  source that contains `>>` (after normalization, before the COPY strip
  and REPLACE), so `>>DEFINE` / `>>IF` / `>>EVALUATE` are honoured in
  `parse_cobol` and after expansion, not only under
  `expand_copybooks(process_conditionals=True)`. `_DEFINE_RE` accepts
  hyphenated symbols. An unrecognized `>>` directive is blanked with a
  warning ("ignored") instead of passed to the lexer.
  `_skip_to_identification_division` keeps `>>` lines ahead of the header.
* `apply_replace_statements`: a single pseudo-text word delimited by
  colons (`==:TAG:==`) is a *partial-word* pattern
  (`_ReplacePair.partial_word`): it matches inside any non-literal source
  word and only that substring is replaced.
* `CopyStatementLexer(sql_include=True)` also recognizes `EXEC SQL INCLUDE
  member END-EXEC [.]` (`_EXEC_SQL_TAIL_RE` anchors the span at `EXEC`) as
  a `CopyStatement(sql_include=True)`; `_expand_source_recursive` turns it
  on and, when the resolver raises `CopybookNotFoundError` for such a
  statement, leaves it as written (SQLCA/SQLDA come from the
  precompiler). `strip_unexpanded_copy_statements` keeps the default
  (off), so the un-expanding parse never touches an INCLUDE.
