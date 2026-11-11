---
type: Module
title: Preprocessing
description: Everything ahead of the lexer -- normalize_fixed_format (fixed -> free form, continuation, column-72 warnings, >>SOURCE FORMAT), format detection, copybook expansion (COPY/REPLACING, path resolution, encoding, source map), conditional compilation, REPLACE, and the record-boundary line splitter.
tags: [preprocessing, copybook, fixed-format, conditional-compilation, replace, source-map]
timestamp: 2026-10-15T00:00:00Z
---

# Preprocessing

`cobolparser/preprocess/` (plus `_lines.py` and `_source_directive.py` at the
package root) is
everything done to source text before `CobolLexer` sees it. Entry points:
`normalize_fixed_format`, `detect_fixed_format` / `normalize_with_recovery`,
`expand_copybooks` / `parse_cobol_with_expansion`, and the in-parser passes
(conditional compilation, COPY strip, REPLACE). Every pass **preserves the
physical line count**. Start with Pipeline and Module map, then the section
for the stage you are touching.

## Contents

* [Pipeline](#pipeline)
* [Public API](#public-api)
* [Module map](#module-map)
* [Line-count invariant and record boundaries](#line-count-invariant-and-record-boundaries)
* [Fixed-format normalization](#fixed-format-normalization)
* [Fixed-format detection](#fixed-format-detection)
* [Compiler directives: PROCESS / CBL](#compiler-directives-process--cbl)
* [Conditional compilation](#conditional-compilation)
* [Copybook expansion](#copybook-expansion)
* [REPLACE and un-expanded COPY](#replace-and-un-expanded-copy)
* [Copybook path resolution](#copybook-path-resolution)
* [Error hierarchy](#error-hierarchy)
* [See also](#see-also)

## Pipeline

What `CobolParser` (and so `parse_cobol`) does to the text, in order
(`CobolParser._preprocess_source` in `parser.py`):

```
raw COBOL
  ──► [parse_cobol_with_expansion only] expand_copybooks()   # inline COPY ... REPLACING, before CobolParser runs
  ──► _skip_to_identification_division()                    # blank banner text ahead of the header (keeps >> lines, REPLACE)
  ──► strip_compiler_directives()                           # blank PROCESS / CBL records
  ──► detect_fixed_format() ? normalize_with_recovery()     # -> normalize_fixed_format(); retry without literal merging on an unterminated literal
  ──► preprocess_conditional_compilation()                  # only when ">>" occurs: >>DEFINE / >>IF / >>EVALUATE
  ──► strip_unexpanded_copy_statements()                    # blank COPY the pipeline will not expand (no-op after expansion)
  ──► apply_replace_statements()                            # REPLACE ==a== BY ==b== / REPLACE OFF
  ──► CobolLexer(...).tokenize()
```

Every arrow preserves the line count. Inside `expand_copybooks` each member
goes through its own sub-pipeline (encoding detection -> `strip_sequence_area`
-> `remove_comment_lines` -> `normalize_continuation_lines` -> optional
conditional compilation -> REPLACING -> validation -> recursive COPY scan ->
splice -> 6-space re-pad with `_fit_fixed_format_width`); see
[Copybook expansion](#copybook-expansion).

## Public API

```python
from cobolparser import (
    normalize_fixed_format,          # raw lines → free-form text
    expand_copybooks,                # source + copybook paths → CopybookExpansion
    parse_cobol_with_expansion,      # expand + parse in one call (process_conditionals=True)
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
# Only on the subpackage (not re-exported from the top level):
from cobolparser.preprocess import (
    preprocess_conditional_compilation,
    strip_compiler_directives,
    validate_copybook_content,
    validate_level_numbers,
    CopybookSizeExceededError,
    CopybookSyntaxError,
    TotalExpansionSizeExceededError,
    LevelNumberMismatchWarning,
    COMMENT_INDICATORS, DEBUG_INDICATORS, VERSION_TAG_INDICATORS, ALL_COMMENT_INDICATORS,
    INDICATOR_COL, TEXT_START_COL, TEXT_END_COL, IDENTIFICATION_END_COL, DEFAULT_SEQ_COL_END,
)
from cobolparser.preprocess.source_format import (
    detect_fixed_format, normalize_with_recovery, debug_line_numbers, free_format_flags,
)
from cobolparser.preprocess.replace_statement import (
    apply_replace_statements, strip_unexpanded_copy_statements, find_replace_statement_spans,
)
from cobolparser.preprocess.copy_statement_parser import CopyStatementLexer, extract_copy_statements
from cobolparser.parser import warn_dropped_debug_lines  # moved from copybook_expander (old path deprecated)
from cobolparser.preprocess.copybook_expander import detect_encoding
from cobolparser.preprocess.path_resolver import PathResolver, validate_path_within_directory
from cobolparser._lines import split_source_lines
from cobolparser._source_directive import source_format_directive
```

Key signatures:

```python
expand_copybooks(source_code, copybook_paths, max_nesting_depth=100,
    preserve_source_locations=False, validate_content=True, validate_levels=False,
    process_conditionals=False, defined_symbols=None, max_file_size=10 MiB,
    max_total_size=100 MiB, path_resolver=None, encoding=None,
    encoding_errors="replace", source_file="<main>", preserve_comments=False,
    debug_lines=False) -> CopybookExpansion
parse_cobol_with_expansion(source_code, filename, copybook_paths,
    max_nesting_depth=100, process_conditionals=True, defined_symbols=None,
    **parser_kwargs) -> ParseResult
```

`CopybookExpansion` fields: `expanded_source`, `included_copybooks`,
`max_depth_reached`, `source_location_map` (`{expanded line: (file, line)}`,
filled only with `preserve_source_locations=True`), `statistics`
(`ExpansionStatistics`: `parse_time_ms`, `file_count`, `total_lines`,
`peak_memory_bytes`, `warnings`, `total_bytes_processed`),
`dropped_debug_lines`. `CopybookSearchPath` fields: `directories`,
`extensions` (default `.cpy .CPY .cbl .CBL .cob .COB .copy .COPY .dcl .DCL`
then `""`, tried in that order; `.copy`/`.dcl` cover PDS checkouts and
DCLGEN members, pinned by
`tests/regression/test_copybook_dcl_copy_extensions.py`), `case_sensitive`, `max_nesting_depth`, `max_file_size`,
`max_total_size`, `max_cache_entries`, `encoding`, `encoding_errors`.

## Module map

| File | Responsibility |
|------|---------------|
| `preprocess/__init__.py` | **Re-export stub only, no implementation.** Re-exports `_source_text/normalize.py` (incl. the column constants `DEFAULT_SEQ_COL_END` / `INDICATOR_COL` / `TEXT_START_COL` / `TEXT_END_COL` / `IDENTIFICATION_END_COL`) and `copybook_expander.py`'s public functions. Sibling modules import from `._normalize`, never `from . import`: the stub imports `copybook_expander`, so a name read back from the package is a module-level import loop |
| `_source_text/normalize.py` (alias `preprocess/_normalize.py`, the same module object) | `normalize_fixed_format`, `strip_compiler_directives`, `preprocess_conditional_compilation` (with the `_ConditionParser` / `_evaluate_condition` constant-condition evaluator), `validate_copybook_content`, `validate_level_numbers`, the column / indicator constants, `ID_DIVISION_HEADER_RE`, plus the `PreprocessingError` hierarchy. Every name is importable from `cobolparser.preprocess` |
| `_source_text/source_format.py` (alias `preprocess/source_format.py`) | `detect_fixed_format` (see [Fixed-format detection](#fixed-format-detection); alias `cobolparser.parser._detect_fixed_format`), `normalize_with_recovery` (normalize + unterminated-literal retry, shared by `CobolParser` and the lexer's `_tokenize_source`), `debug_line_numbers`; re-exports `free_format_flags` |
| `preprocess/copybook_expander.py` | `expand_copybooks` (`parse_cobol_with_expansion` and `warn_dropped_debug_lines` moved to `parser.py`; the old names resolve with a `DeprecationWarning`, see [`docs/public-api.md`](../docs/public-api.md#moved-names)); recursive inlining (`_expand_source_recursive`) with cycle detection, encoding detection (`detect_encoding` / `convert_to_utf8`), validation, LRU file cache (`clear_file_cache` / `set_file_cache_size` / `get_file_cache_stats`), the re-pad / width fitter (`_fit_fixed_format_width`) and the source map |
| `preprocess/copy_statement_parser.py` | `CopyStatementLexer` (COPY / `EXEC SQL INCLUDE` scanner), `extract_copy_statements`, `apply_replacing_clauses`, and the line-preserving member passes `strip_sequence_area` / `remove_comment_lines` / `normalize_continuation_lines`; `is_comment_line` |
| `preprocess/replace_statement.py` | `apply_replace_statements`, `strip_unexpanded_copy_statements`, `find_replace_statement_spans` (the REPLACE text-word scanner `_ReplaceScanner`) |
| `preprocess/path_resolver.py` | `PathResolver` (three-tier lookup), `find_copybook_file`, `get_available_copybooks`, `suggest_similar_copybooks`, `validate_path_within_directory` -- see [Copybook path resolution](#copybook-path-resolution) |
| `preprocess/models.py` | `CopybookExpansion`, `CopyStatement`, `CopybookSearchPath`, `ExpansionStatistics`, `ExpansionContext` (per-expansion stack, byte budget, content/origin cache, `debug_lines`), `ReplacingClause`, `SuppressClause`, `SourceLocationMap` |
| `_lines.py` (package root) | `split_source_lines(text, keepends=False)` -- the one line splitter for source text (`\n` / `\r\n` / `\r` only) |
| `_source_text/` (package root) | Layer-1 leaf holding the two modules above (moved out of `preprocess` so the lexer, one layer below `preprocess`, can normalize fixed-format source and read the indicator sets without an upward import). It imports only `_lines` and `_source_directive`. Package code imports `cobolparser._source_text.*`; the `preprocess` aliases keep old imports and patches working |
| `_source_directive.py` (package root) | `source_format_directive(text)` (`"FIXED"` / `"FREE"` / `None` for a `>>SOURCE [FORMAT] [IS] ...` record) and `free_format_flags(lines, indicator_position=6)`. Dependency-free so the lexer and `preprocess` can both import it without a cycle |

## Line-count invariant and record boundaries

Every pass in this area emits exactly one output line per input record, so
`output.count("\n")` equals the input line count, and an expansion has exactly
`len(source) - len(COPY lines) + len(member lines)` lines. A location the
parser reports against the processed text is therefore a location in the
file -- the most important invariant in this area. How each pass keeps it:

* `normalize_fixed_format` appends an empty placeholder for every dropped
  record (blank/short, comment, debug, version-tag), and emits one placeholder
  per absorbed continuation record *after* the flushed logical line, so a
  logical line keeps its first record's number. Whether a logical line was
  started is tracked explicitly (`has_line`), not inferred from its merged
  text being non-empty: a full-width record with a blank indicator and blank
  columns 8-72 (what `remove_comment_lines` leaves of a comment line, which
  the parser re-normalizes after expansion) must still produce its line.
* `preprocess_conditional_compilation` blanks directive lines and every line
  of a skipped block in place.
* The COPY splice strips exactly one trailing newline from the expanded
  member (never more -- a genuine blank final line stays) before counting its
  lines.
* The only passes allowed to add lines are the expander's width-fitting wrap
  (see [Output re-pad and width fitting](#output-re-pad-and-width-fitting))
  and the COPY splice's tail line (see [The COPY splice](#the-copy-splice)),
  and the source map accounts for both.

Pinned by `tests/regression/test_normalize_line_number_preservation.py`.

**A line is a record, nothing else.** `split_source_lines` (`_lines.py`)
splits on `\n` / `\r\n` / `\r` only and is otherwise `splitlines`-shaped.
`str.splitlines()` also breaks on form feed, vertical tab, NEL (U+0085),
U+2028/2029 and `\x1c`-`\x1e`, so a page eject inside a comment (`*\x0c`) or
a cp1252 `…` decoded through latin-1 would shift every later line number.
`parse_cobol`, `CobolParser`, `detect_fixed_format`, `CobolLexer.__init__`,
`normalize_fixed_format` (string form),
`preprocess_conditional_compilation`, `strip_compiler_directives`,
`validate_copybook_content` and the expander's line counts all use it. The
member passes in `copy_statement_parser.py` (`normalize_continuation_lines`,
`strip_sequence_area`, `remove_comment_lines`, REPLACING) split through
`_records()` (`split_source_lines` plus the trailing empty element `str.split`
gives, so `"\n".join` round-trips); splitting on `\n` alone made a bare-CR
program one record whose COPY was never expanded. Do not reintroduce
`splitlines()` or `split("\n")` on source text.

## Fixed-format normalization

```python
def normalize_fixed_format(
    lines: Iterable[str] | str,   # a str is split with split_source_lines
    *,
    merge_continued_literals: bool = True,
    debug_lines_as_comments: bool = True,
    version_tag_lines_as_comments: bool = True,
    warnings: list[str] | None = None,
) -> str: ...
```

Each line is tab-expanded (`str.expandtabs(8)`) **before** any column slicing,
so a tab does not shift the indicator/text-area columns. Columns 8-72 are
kept; comment lines are dropped; continuation lines (column 7 `-`) are
merged. Returns one free-form string with exactly one output line per input
record. Raises `ValueError` for a literal still open on the last code line
unless `merge_continued_literals=False`. `warnings`, when a list, collects the
column-72 overflow diagnostics.

### Comment, debug and version-tag lines

The column-7 indicator characters live in one place, `_source_text/normalize.py`:
`COMMENT_INDICATORS` (`*` `/`), `DEBUG_INDICATORS` (`D` `d`),
`VERSION_TAG_INDICATORS` (`V` `v`) and their union `ALL_COMMENT_INDICATORS`
(re-exported from `cobolparser.preprocess`). Consumers:
`normalize_fixed_format`, `copy_statement_parser.is_comment_line`,
`source_format.detect_fixed_format`, `lexer._fixed_format_comment_tokens`
(deferred import).

* `*` / `/` lines are always comments.
* `D` / `d` lines are comments when `debug_lines_as_comments` (default
  `True`, matching `is_comment_line`); pass `False` to compile them.
* `V` / `v` lines are comments when `version_tag_lines_as_comments` (default
  `True`): a shop change-control convention stamps a short version tag
  (`V97`, `TFEC`) into Area A with `V` in column 7. Standard COBOL never puts
  code in column 7, so this is unambiguous; without it the tag reaches the
  lexer as "Unparsed tokens". Pinned by
  `tests/regression/test_version_tag_line_handling.py`.

### Debugging lines and `WITH DEBUGGING MODE`

IBM compiles `D` lines as code under `SOURCE-COMPUTER ... WITH DEBUGGING
MODE`. The parse drops them by default and says so (#334). The switch is
`debug_lines` on `parse_cobol` / `CobolParser` / `_tokenize_source` /
`ScanOptions` / `parse_files` / `parse_files_with_copybooks` /
`expand_copybooks` / `parse_cobol_with_expansion` (via parser kwargs) /
`ProgramLayoutIndex.from_file` / `ProgramFixtureGenerator.analyze_from_file`
(not `generate*_from_file`, whose signatures are mocky-mock's contract) /
`CodebaseGraphBuilder`; the CLI's `--debug-lines` / `--no-debug-lines` (every
COBOL-parsing subcommand; `gen-data`, `decode`, `compare` drop `D` lines in a
copybook layout); cobol.yml `project.debug_lines`.
`normalize_with_recovery(..., debug_lines_as_comments=...)` passes it to both
normalization passes.

With it off, `CobolParser._normalize_fixed_source` records
`source_format.debug_line_numbers()` (skipping `>>SOURCE FORMAT IS FREE`
regions), and a unit whose `source_computer` metadata has `debugging_mode`
gets one warning: `Line N: SOURCE-COMPUTER is WITH DEBUGGING MODE, but K
debugging line(s) ... were dropped as comments; parse with debug_lines=True
...`. With it on, D lines are compiled whether or not the clause is present
(like GnuCOBOL's `-fdebugging-line`) and `_fixed_format_comment_tokens` stops
emitting them as COMMENT tokens.

Through expansion: `remove_comment_lines(..., keep_debug_lines=)` keeps `D`
lines when `ExpansionContext.debug_lines` is on (main source and all
members), `D` restored to column 7 after the re-pad; otherwise any COPY would
make `debug_lines=True` a no-op. With it off they are blanked and listed in
`CopybookExpansion.dropped_debug_lines` (`(file, line)` via the source map; a
member COPYd twice counts twice; only computed when `DEBUGGING` appears).
`warn_dropped_debug_lines()` (called by `parse_cobol_with_expansion` and
`parse_files_with_copybooks`) raises the same warning from that list --
`FILE: Line N` when the first is in a member -- unless the parser already
did. One spelling for both: `parser.dropped_debug_lines_warning()`.

### Continuation lines

A continuation line's first non-blank character is the successor of the
continued line's last non-blank character, **without an intervening space**:

* **Alphanumeric literal open at the split** → the continuation's leading
  quote is dropped and the rest appended directly (`pending_literal` path).
* **Anything else** (a numeric literal or word split mid-token, e.g.
  `-999.777` one digit per line) → the chunk is `strip()`-ped and appended
  with no space; a space would leave a free-standing `.` that the lexer reads
  as a terminator. Pinned by `tests/regression/test_continued_literal_normalization.py`.

Further rules:

* **Trailing blanks of an open literal are part of it**: a line is
  `rstrip()`-ped only once no literal is open at its end (`VALUE "ABC   ` +
  `-    "DEF".` gives `"ABC   DEF"`).
* **Short records are padded to column 72**: a literal open at end of line
  runs through column 72 even when trailing blanks were stripped by an editor
  or transfer. `_literal_pad()` supplies them, only when a continuation
  resumes the literal. The expander's `normalize_continuation_lines` pads the
  same way (`tail_width`) so direct and expanded parses agree. Test fixtures
  with short-record pieces must follow the column-72 rule.
* **The continuation is the next line that is neither comment nor blank**,
  whatever is continued: the comment and blank branches look ahead
  (`_continuation_follows`, cached) and defer the
  placeholder when a `-` record follows, so `MOVE WS-CO` / `* note` /
  `-    UNT TO X.` gives `WS-COUNT`.
* **Quote in column 72 + continuation starting `''`** is one doubled quote in
  a literal that continues (IBM): `closing_quote_at_72` re-opens it and keeps
  one of the pair (`'AB''CD'`).
* `*>` inline comments are skipped by the quote-state scan.

### Unterminated literals

With the default `merge_continued_literals=True`, a literal still open at end
of input raises `ValueError` ("Unterminated string literal…").
`merge_continued_literals=False` disables continuation-literal merging and
never raises -- the best-effort fallback. `source_format.normalize_with_recovery`
packages the retry; `CobolParser._normalize_fixed_source` (called from
`_preprocess_source`) records the error and, unless in `FAIL_FAST`,
re-normalizes with `merge_continued_literals=False`, so one bad literal does
not collapse a `COLLECT_ALL` parse to `ast=None`. `parse_cobol` defers to the
parser for this. Both paths accept the flag identically.

### `>>SOURCE FORMAT` inside a fixed-format file

`normalize_fixed_format` recognises
`>>SOURCE [FORMAT] [IS] {FREE|FIXED}` (`_source_directive.py`) from column 7
to 72 of a fixed record, or anywhere on a free line. The directive record
becomes a blank line; each free-format line is passed through whole as its
own logical line (no continuation merging, no column-72 warnings) until
`>>SOURCE FIXED`. One output line per physical line. The copybook expander
carries it too: `free_format_flags()` makes `remove_comment_lines` /
`strip_sequence_area` keep free lines whole (behind a blank indicator) and
the final re-pad skip them (no pad, no width wrap), so the source map stays
1:1; the expander's conditional-compilation passes use
`preprocess_conditional_compilation(..., keep_source_format_directives=True)`
so the directive survives to the final parse; without that flag a recognised
`>>SOURCE` is blanked silently, never "unknown compiler directive" (#502).
Not handled: a free-format
literal continuation, and a `>>SOURCE FIXED` in a file the detector calls
free (that file never goes through the fixed normalizer). Pinned by
`tests/regression/test_fixes_2026_09_28_preprocessing.py`.

### Column 72 overflow warning

For a non-comment record longer than 72 columns whose columns 1-6 are *not* a
numeric sequence number, with `dropped = line[72:].rstrip()` and
`content_len = len(line.rstrip())`:

* **Rule 1 (mid-token)** warns when columns 72 and 73 are both non-blank,
  unless `dropped == "."` (bare terminal period), or `dropped` is
  numeric-id-stamp text (`_is_numeric_id_stamp_text`: at least one digit,
  only digits and blanks) and either `content_len == 80` exactly or the file
  shows the stamp convention (`_has_identification_stamp_convention`, at
  least `MIN_ID_STAMP_EVIDENCE_LINES` = 3 unambiguous stamp lines) with
  `content_len <= 80`.
* **Rule 2 (word boundary)** otherwise warns when `content_len > 80`.

Messages (`n` = 1-based physical line):
rule 1 `f"Line {n}: content beyond column {TEXT_END_COL} was dropped mid-token: {dropped!r}"`;
rule 2 `f"Line {n}: content beyond column {TEXT_END_COL} was dropped -- line is {content_len} columns wide, past the traditional {IDENTIFICATION_END_COL}-column identification-area width: {dropped!r}"`.

Why each gate exists (each was a real false positive or negative):

* Columns 73-80 are the identification area, ignored by compilers whatever it
  holds (NIST puts `IC1014.2` on every line), so rule 1 needs a split token.
* Rule 2: `... DEPENDING ON WS-COUNT.` split on a blank at 72/73 silently lost
  its operand; content past column 80 is never identification text.
* A numeric sequence number in columns 1-6 marks the traditional convention,
  where a period on 72 then an id at 73 (NIST `"...".IX2094.2`) is normal.
* Comment lines (incl. `D`/`V` when comments) are discarded, never checked.
* A lone dropped `.` (closing quote on 72) splits nothing; `.B` still warns.
* Numeric stamp (ISPF auto-numbering `03050009`, columns 1-6 blank) is excused
  at exactly 80 columns. A shorter all-digit tail is per line
  indistinguishable from a name's trailing digits being cut, so it is excused
  only when the *file* shows the convention (lines with column 72 blank and a
  numeric tail; lazy scan, once per call, stops at the third). Blanks inside
  a stamp are allowed (`01636  0`); any letter or punctuation fails it.

Every gate is narrow on purpose: mockymock refuses a program on *any*
`ParseResult.warnings` entry. The warning reaches `ParseResult.warnings`
(`CobolParser.parse()` / `parse_cobol()`), `_tokenize_source`'s returned
warnings and `cobol-parser preprocess` (stderr); it is never an error.
Callers wanting a refusal (mocky-mock's `check_normalize_warnings`) treat
every entry as actionable. Pinned by
`tests/regression/test_normalize_column_overflow_warning.py` (incl.
multi-line fast/pure parity) and
`tests/regression/test_fixed_format_word_boundary_overflow.py` (end-to-end).

## Fixed-format detection

`source_format.detect_fixed_format(source)` decides whether to normalize at
all (alias: `cobolparser.parser._detect_fixed_format`). It samples the first
10 non-blank lines against a 60% threshold. The `--source-format` escape
hatch is in [cli.md](cli.md).

* **Rule 0 (opening directive):** a first non-blank line that is
  `>>SOURCE [FORMAT] [IS] FREE` starting in columns 1-6 makes the file
  free-form (option (a) of #502). Read as fixed, such a directive sat in the
  sequence area, was sliced to `E FORMAT FREE` and the parse failed ("no
  division near 'E'"). From column 7 on, the per-line flags below already
  honour it, and keep a later `>>SOURCE FORMAT FIXED` section with sequence
  numbers fixed, so an opening `>>SOURCE FREE` works in any column. Only the
  opening line decides; a later column-1 directive does not.
* **Rule 1 (strict):** columns 1-6 blank or all digits. Decides on its own;
  rule 2 only ever *adds* detections. A *numbered blank line* (`000300` and
  nothing else, as an export that strips trailing blanks leaves every empty
  record; `_is_numbered_blank_line`) counts as a strict hit too, here and in
  `_looks_fixed_format()`'s short-member path. Before 2026-10-29 such a line
  was skipped but still counted in the sample, so a copybook with a few in
  its banner was judged free-form and its comment lines reached the lexer
  (`Invalid character: #`, `tests/regression/test_numbered_blank_copybook_lines.py`).
* **Rule 2 (change tags `SAPR24`, `28486`, `JSINT` in columns 1-6):** a
  tag-like sequence area (`_sequence_area_is_fixed_like`, `_CHANGE_TAG_RE`:
  one unbroken `[A-Za-z0-9#@$][A-Za-z0-9_/#@$.-]*` token -- no internal
  whitespace, which excludes free text like `MOVE A`) counts only with an
  anchor:
  * an Area A division header (`IDENTIFICATION DIVISION`, `PROGRAM-ID`, ...
    in columns 8+) **at a word boundary** (`PROGRAM-ID-VAL` never anchors).
    Free-form headers sit at column 1, where `line[7:]` lands mid-word, so the
    anchor keeps free-form input out. The scan is bounded
    (`_HEADER_SCAN_LIMIT` = 100) but comment and short lines do not consume
    it -- tag-stamping shops open with 100+-line change-history banners;
  * for copybooks, `_has_tagged_line_anchor()`: a tagged line with a column-7
    comment indicator (`CHG001*...`) or whose code area is a data entry
    (`_TAGGED_DATA_ENTRY_RE`: level + name + period or clause keyword, which
    keeps `DIVIDE 10 INTO X` out). `copybook_expander._looks_fixed_format()`'s
    short-member path (< 3 lines) uses the same anchor.

A misdetected tagged program skips normalization and its tags reach the lexer
as code (and the result can flip as expansion changes the sampled lines); a
misdetected tagged copybook splices comments in raw (`Invalid character:
#`). Pinned by `tests/regression/test_tagged_sequence_area_detection.py` and
`tests/regression/test_tagged_copybook_comment_hash.py`.
`normalize_fixed_format` slices `line[7:72]` whatever columns 1-6 hold.

## Compiler directives: PROCESS / CBL

`strip_compiler_directives` blanks PROCESS / CBL records ahead of the
program. Whether a record has a sequence area is decided from columns 1-6
(blank or digits); the "directive section" also ends on
`ID_DIVISION_HEADER_RE` (any six characters, then a blank column 7 -- the
regex `CobolParser._skip_to_identification_division` uses too), so a
change-tagged header `CHG001 IDENTIFICATION DIVISION.` ends it and a later
`PROCESS SECTION.` is not blanked. Pinned by
`tests/regression/test_sequence_area_tag_header.py`.

**Batch compiles.** An `END PROGRAM` line reopens the directive section, since
IBM lets the next program of a batch carry its own cards there. A reopened
section closes at the first line that is neither a card nor a comment, and a
`PROCESS` / `CBL` line ending in a period (`PROCESS SECTION.`) is code, not a
card. Before this the card reached the parser, which stopped at "No
recognizable COBOL division" and lost every later program (IBM DBB
`epscsmrd.cbl`). Pinned by
`tests/regression/test_process_card_between_programs.py`.

In copybook expansion, `strip_sequence_area` passes a full-width line through
untouched when its columns 1-6 do not look like a real sequence area AND it
matches `^(?:PROCESS|CBL)(?:[ \t].*)?$` case-insensitively
(`_COMPILER_DIRECTIVE_RE`): PROCESS/CBL must start in column 1, so its
columns 1-6 are never a sequence area, and stripping them turns `PROCESS
&CICS-31& ...` into `S &CICS-31& ...`. The sequence-area gate keeps
`PROCESS-FLAG` on a numbered line from being misread. Multi-line PROCESS/CBL
continuation is out of scope. Pinned by `TestFlushLeftCompilerDirective` in
`tests/regression/test_expansion_width_and_tags.py`.

## Conditional compilation

`preprocess_conditional_compilation(source, defined_symbols, warnings=None,
define_log=None, keep_source_format_directives=False)`. `CobolParser.parse`
runs it on every source containing `>>` (after normalization, before the COPY
strip and REPLACE), so `parse_cobol` honours directives too;
`_skip_to_identification_division` keeps `>>` lines ahead of the header.
Directive and skipped lines are blanked in place.

* `>>IF` is **evaluated**: `=`, `<>`, `>`, `<`, `>=`, `<=` and their word
  forms (`[IS] [NOT] GREATER [THAN]`, `LESS [THAN]`, `EQUAL [TO]`, `... OR
  EQUAL [TO]`; an `OR` is part of the operator only when `EQUAL` follows it)
  between symbol values and numeric/string literals; `DEFINED(sym)` / `sym
  [IS] [NOT] DEFINED` (`IS` optional per IBM; a dangling `IS`/`NOT` is a
  syntax error); `AND`/`OR`/`NOT` with parentheses. A `(` that turns out to
  open an arithmetic operand (`(X + 1) * 2 = 16`) is re-read as one; when
  the text cannot be an operand either, the group's own error is reported
  (`(FOO = 1)` still names the undefined `FOO`). Word
  forms used to be "unsupported ... treated as FALSE", compiling the `>>ELSE`
  instead (#512); pinned by
  `tests/regression/test_conditional_compilation_word_operators.py`.
* `>>EVALUATE sym` (literal `>>WHEN`s), `>>EVALUATE TRUE` (condition
  `>>WHEN`s), `>>WHEN OTHER`, `>>END-EVALUATE`. Stacked `>>WHEN`s (no text
  between them; blank and comment lines do not count) share the text that
  follows: `_CondFrame.when_pending` keeps the branch on when an earlier
  phrase of the stack matched. Without it a match on the first phrase was
  switched off by the next and the `>>EVALUATE` produced nothing, silently
  (#492; `tests/regression/test_conditional_compilation_stacked_when.py`).
* `defined_symbols`: a name set/list or a `dict[str, str | int | float |
  bool]` (the CLI's `--define NAME=VALUE`). A quoted value keeps its case; an
  unquoted one is a word and is upper-cased (`{"ENV": "prod"}` matches
  `'PROD'`).
* `>>DEFINE` symbols may be hyphenated (`_DEFINE_RE`). `>>DEFINE name AS
  arithmetic-expression` over integer literals / defined integer variables
  (`+ - * /`, parentheses) is evaluated exactly (`_eval_define_arithmetic`:
  `AS 2 + 1` is `3`); otherwise the raw text is kept. A lone word
  (`_DEFINE_WORD_RE`, `AS A`) copies A's current value, any type (`AS (A)`
  goes through the arithmetic, integers only); an
  undefined one warns and keeps the word -- storing "A" made `>>IF B = 3`
  silently FALSE (#567). An `>>IF` / `>>WHEN`
  comparison operand may be the same arithmetic (`X + 1 = 8`), evaluated by
  the same function so the two directives agree; an inexact or non-integer
  one warns and is FALSE (#512). `_COND_TOKEN_RE` reads `X -1` as `X`, `-1`;
  between two operands the sign is taken as the binary operator.
* **Literal contents are case-sensitive**: only text outside quotes is
  upper-cased (`_upper_outside_literals`); `_compare` / `_values_equal`
  compare non-numeric values exactly. `_COND_TOKEN_RE` accepts signed
  numbers and doubled delimiters, un-doubled by `_strip_quotes` (`'O''BRIEN'`
  -> `O'BRIEN`). Pinned by `tests/regression/test_conditional_compilation_literals.py`.
* A `*>` comment on a directive line (outside a literal) is stripped first
  (`_strip_directive_comment`), else `>>DEFINE DEBUG AS 1 *> on` defines
  `1 *> ON`.

Warnings: comparison on an **undefined symbol** (evaluates false),
unparseable `>>IF` (skipped), malformed `>>DEFINE`, stray `>>ELSE`/`>>END-IF`,
unclosed `>>IF` / `>>EVALUATE`, and an unrecognized `>>` directive (blanked,
"ignored"). Expansion routes them into `ExpansionStatistics.warnings`; the CLI
prints them to stderr without `--copybook-path` and to the JSON's `warnings`
with it (always for `expand`). Pinned by
`tests/regression/test_tier4_audit_remediations.py::TestH7ConditionalCompilationWarnings`
and `tests/regression/test_open_findings_m10_regression.py`. Directives in
copybooks: [Conditional compilation during expansion](#conditional-compilation-during-expansion).

## Copybook expansion

```python
# Standalone expansion
result: CopybookExpansion = expand_copybooks(source, copybook_paths=["/path/to/cpy"])

# Parse + expand in one call (conditional compilation on by default)
parse_result = parse_cobol_with_expansion(source, "prog.cbl", copybook_paths=["/path"])
```

Features:
- Recursive inlining with circular-reference detection and a nesting limit
- `COPY member [OF|IN library]`, `COPY "literal/path"`, and `EXEC SQL INCLUDE`
  (members that do not resolve, e.g. SQLCA, are left as written)
- Encoding detection (BOM / UTF-8 / cp037 and other EBCDIC / cp1252 / latin-1)
- Content validation (`validate_copybook_content`, optional `validate_level_numbers`)
- Per-file (`max_file_size`) and whole-expansion (`max_total_size`) byte limits
- LRU file cache (configurable via `set_file_cache_size`)
- REPLACING clause support including multi-token pseudo-text, literals,
  qualified/subscripted identifiers and LEADING/TRAILING
- Optional source map (`preserve_source_locations`) and comment restoration
  (`preserve_comments`)

`parse_cobol_with_expansion` copies `expansion.statistics.warnings` (lossy
decodes, content-validation, level-number and dropped-COPY warnings) onto
`ParseResult.warnings`.

### Member sub-pipeline order

The sequence (columns 1-6) and identification (73-80) areas are stripped
(`strip_sequence_area` + `remove_comment_lines`) immediately after a member is
read, **before** REPLACING, conditional compilation and validation. On the raw
80-column line a length-changing REPLACING would move the column-72 boundary
(pulling identification text in, or cutting a terminating period), and `>>IF`
behind numeric sequence digits would not be recognized.
`apply_replacing_clauses` and `validate_copybook_content` take
`indicator_position` (6 for raw source, 0 after `strip_sequence_area`, `None`
for a free-form member), and `_expand_source_recursive(already_stripped=True)`
skips its own strip so content is never stripped twice. Pinned by
`tests/regression/test_copybook_sequence_area_before_replacing.py`.

`remove_comment_lines` blanks comment lines to whitespace of the same length
(indicator included) and must: the COPY scanner works on program text, and a
`COPY` inside a comment must not be expanded.

**Short change-tag lines.** Shops stamp a tag (`P2P`, `M1005`, `E1A`) into
columns 1-6 of its own line, so the line is under 7 characters.
`strip_sequence_area` blanks a sub-7-char line only when it is one blank-free
token that does not end with a period and is not ANY COBOL reserved word
(`_cobol_reserved_words()`, lazily imported from `CobolLexer.KEYWORDS` --
eager import is circular). Blanking every short line would delete flush-left
code (`01 A.`, `GOBACK`, `EXIT`); passing tags through lets the re-pad shift
them into live code. The direct `parse_cobol` path already emits a blank for
sub-7-char lines. Pinned by `tests/regression/test_expansion_width_and_tags.py`
and `tests/regression/test_diff_scan_findings.py`.

### COPY statement scanner

`CopyStatementLexer` (`copy_statement_parser.py`) is a linear hand-written
scanner; there is deliberately no monolithic COPY regex (one backtracked
exponentially on unterminated REPLACING).

* **Linear**: on a failed match it jumps past the whole separator run
  (`_SEPARATOR_RUN_RE`) or identifier (`_WORD_RUN_RE`); stepping one
  character re-scanned every blank run (minutes on blank-line files). Pinned
  by `tests/regression/test_audit_2026_09_27.py::TestCopyScannerLinear`.
* **Word boundaries on both sides** (`GOODCOPY.` is not a COPY).
* **Literals end at end of line** (continuations are merged first), and it
  scans `lexer.mask_comment_entries(source)` (comment-entry text blanked,
  offsets kept, via the lexer's `_comment_entry_starts`), so `AUTHOR. JOHN
  O'BRIEN.` cannot flip quote parity and a `COPY` inside a comment-entry is
  prose. `_ReplaceScanner` does the same. Pinned by
  `tests/regression/test_comment_entry_copy_replace_scan.py`.
* **Dropped COPYs are reported**: a missing period (`COPY FOO`, `COPY FOO
  BAR.`) or unterminated `==pseudo-text==` goes to `lexer.warnings`, routed
  into `ExpansionStatistics.warnings`; `extract_copy_statements(source,
  source_file, warnings=None, sql_include=False)` exposes the same channel.
* **Diagnostics name the original line**: `_expand_source_recursive` passes
  its `merged_from` list as `CopyStatementLexer(line_origins=...)`
  (`_report_line`), and `parse_cobol_with_expansion` maps the parser's
  strip-pass COPY warnings through the source map
  (`_locate_strip_pass_warning`) so they collapse into the expander's.
  `CopyStatement.source_location` stays in merged-text lines. Pinned by
  `tests/regression/test_copy_diagnostic_line_numbers.py`.
* **`EXEC SQL INCLUDE member END-EXEC [.]`** is recognized with
  `sql_include=True` (`_EXEC_SQL_TAIL_RE` anchors the span at `EXEC`) as
  `CopyStatement(sql_include=True)`. The expander turns it on and leaves the
  statement as written on `CopybookNotFoundError` (SQLCA/SQLDA come from the
  precompiler). Any member outside `models.PRECOMPILER_MEMBERS` also gets an
  "EXEC SQL INCLUDE X was not expanded: ...; the statement was left as
  written" warning in `statistics.warnings` (it reaches `ParseResult.warnings`),
  and the CLI analyzers print one stderr line naming the members
  (`_hint_unexpanded_sql_includes`), with or without `--copybook-path`.
  Pinned by `tests/regression/test_missing_sql_include_warns.py`.
  `strip_unexpanded_copy_statements` keeps it off. The codebase
  graph sees INCLUDE edges through `extract_copy_statements(...,
  sql_include=True)` (#295).
* **`skip_missing_copybooks=True`** (`expand_copybooks`,
  `parse_cobol_with_expansion`; `ExpansionContext.skip_missing`) does the
  same for an ordinary COPY: the statement stays as written, a "... the COPY
  was left as written" warning goes to `statistics.warnings`, every other
  member still expands, and the parse then warns "COPY X was not expanded".
  Default False (raise). The MCP workspace turns it on, and so does the
  `lint` CLI (unless `--strict-copybooks`), which also appends the IBM
  stand-ins below.
* **IBM-supplied CICS copybooks** (`preprocess/_system_copybooks.py`):
  `system_copybooks/` ships `DFHAID.cpy` and `DFHBMSCA.cpy` (IBM's field
  names and PICTUREs, EBCDIC VALUEs as hex literals; package data in
  `pyproject.toml` and `MANIFEST.in`). `with_system_copybooks(paths)`
  appends that folder last (a real copy on the path wins), and leaves an
  empty path empty. Only `lint` uses it so far.

### REPLACING

`apply_replacing_clauses` (`copy_statement_parser.py`)
scans the member's whole text in one pass (lines joined with `\n`):

* **Operands.** `CopyStatementLexer._read_replacing_operand` reads
  pseudo-text, literals, and word operands extended greedily with `(OF|IN)
  word` pairs and parenthesised groups (blank before `(` or not, commas kept).
  Once REPLACING has started `OF`/`IN` can only be qualification, so
  `REPLACING X BY WS-FLD OF WS-GRP` is not read as a library qualifier (NIST
  SM202A / SM206A rely on this; pinned by
  `tests/regression/test_copy_replacing_identifier_operand.py`). Literal
  operands keep their quotes (`keep_literal_quotes=True`): `REPLACING 'ABC' BY
  'XYZ'` replaces the *literal* (checked against `cobc -E`), while `COPY
  'MEMBER'` strips them (pinned by
  `tests/regression/test_copy_replacing_literal_operand.py`). `:ABC:`
  pseudo-text has its delimiters stripped, so `REPLACING :ABC: BY :XYZ:`
  substitutes `ABC`→`XYZ`.
* **Text-word comparison.** Pseudo-text is stripped at the operand and
  compiled through `_PSEUDO_TEXT_WORD_RE`: blanks between words match a run of
  blanks; a parenthesis is a word with optional blanks beside it (`X (10)`
  matches `X(10)`). A separator comma/semicolon is a blank (IBM):
  `_build_clause_pattern` joins words with `_SEPARATOR_GAP` (a blank, or `,`/`;`
  then a blank), and `_pseudo_text_words` drops a `,`/`;` ending a non-literal
  search word before a blank or the end; `A,B` / `1,5` still compare as text.
  A line break is a separator like a blank (`_SEPARATOR_GAP` includes `\n`),
  so a search text whose words the copybook splits across lines matches, as
  the REPLACE statement already did; per-line matching skipped it silently
  (#560).
* **Each word is replaced at most once.** All clauses go into ONE alternation
  (longest search text first) applied in ONE left-to-right pass;
  applying clauses one pass each would let `==A== BY ==B== ==B== BY ==A==`
  rewrite replacements. A LEADING / TRAILING hit settles its whole word: the
  first partial clause (in clause order) that fits the word replaces it, and
  scanning resumes after the word -- the leftmost hit alone turned
  `XX-NAME-XX` into `CUST-NAME-END` under LEADING + TRAILING `==XX==`, unlike
  REPLACE (#513). Clause order is the written order here, not the
  longest-first order of the alternation (`LEADING ==X==` written before
  `TRAILING ==XX==` settles `X-NAME-XX`). A whole-word clause still beats a
  partial one by length, whatever the written order (known gap).
* **Boundaries.** Hyphen-aware word boundaries, `_` counts as a word
  character, a decimal point binds (`(?<![0-9]\.)` / `(?!\.[0-9])`, so `==1==
  BY ==2==` leaves `VALUE 1.5`), LEADING/TRAILING, case-insensitive words.
* **Context.** Comment lines (column-7 `*`/`/`, mask computed once from the
  original content) are never rewritten: a match overlapping one is
  rejected. Text inside literals (both quote styles, doubled-quote escapes,
  found per line; an unterminated literal runs to EOL) is not rewritten
  unless the clause's search text contains a quote. A search text mixing
  code and a literal (`==VALUE 'A'==`) can match; a match of a quote-free
  clause inside a literal is rejected and quote-bearing clauses still get
  their turn there.
* **Line origins.** `line_origins=` (out-parameter) receives the input line
  of each output line: lines a `BY` text adds repeat the line its match
  started on, a match spanning lines keeps the first. The expander passes
  them to the member's recursion as `initial_origins` (#561). The literal words of a search text compare
  **case-sensitively** (`(?-i:...)`).

Pinned by `tests/regression/test_open_findings_m13_regression.py`,
`tests/unit/test_copy_edge_cases.py::TestReplacingLiteralAndWordBoundaries`,
`tests/regression/test_audit_2026_09_17_preprocessing.py` and
`tests/regression/test_fixes_2026_09_28_preprocessing.py`.

### Size limits and caching

`context.total_bytes` is charged for every inclusion against `max_total_size`
(`TotalExpansionSizeExceededError`):

* on a cache miss, the raw member, then any positive REPLACING growth (a `BY`
  text longer than its operand can otherwise multiply a member past the limit
  unchecked);
* on a cache hit (`context.content_cache`, keyed by path + REPLACING clauses
  + the conditional symbols in effect -- diamond dependencies), the cached
  post-REPLACING content's length, identically to a miss.

`expand_copybooks(path_resolver=...)` uses a caller-supplied resolver as-is
(its warm caches are the point -- `batch.parse_files_with_copybooks` passes
one) and builds a new one only for `None`; the supplied resolver's
`search_config` then governs nesting/size/encoding limits. Pinned by
`tests/regression/test_audit_2026_08_12_core.py::TestPD1CallerSuppliedPathResolver`.

### Content validation

`validate_copybook_content(content, ..., raw_content=None,
indicator_position=6)` raises `CopybookSyntaxError` only for NUL bytes;
everything else is a warning, shown to users in the COBOL Analyzer's
expanded-listing banner, so false positives matter.

* **Missing period is judged per entry** (`_unterminated_data_entries`): an
  entry runs from a `_DATA_ENTRY_START_RE` match to the next entry, an `EXEC`
  block, a `>>` directive line (`_NON_ENTRY_LINE_RE`; directives are not yet
  evaluated) or EOF, and the joined text must end in a period. Blank lines do
  not close an entry (blanked comments). `_DATA_DEF_RE` (is it a PICTURE
  entry) and the start regex share one `_ENTRY_HEAD` fragment (`\d{1,2}` +
  name) so they cannot drift apart.
* Whitespace in the patterns is `[ \t]` (`\s` crosses newlines); the value
  token is `[^\s]*[^\s.]`, so only a *trailing* period terminates
  (`PIC 9(5).99` is flagged, `PIC 9(5).99.` is not; `[^\s.]+` would miss
  every decimal-point PIC).
* Blank stripped `content` with non-blank `raw_content` warns "contains only
  comments", not "is empty".
* The quote-balance check discounts continuation records at
  `indicator_position`.

Pinned by `tests/unit/test_preprocess_init_coverage.py::TestValidateCopybookContent`
and `tests/unit/test_copybook_expander_coverage.py::TestExpandCopybooks::test_content_validation`.

### Encoding detection

`detect_encoding` (`copybook_expander.py`) scores ASCII-vs-EBCDIC
plausibility over a bounded 64 KiB prefix: BOM / strict-UTF-8 checks first,
then COBOL-charset proportion, EBCDIC newline conventions 0x15/0x25, keyword
tiebreaker (`_score_cobol_plausibility`). A single 0x40-vs-0x20 ratio would
misdetect an ASCII file full of `@`. ASCII-shaped bytes that are not valid
UTF-8 are `cp1252`, or `latin-1` when a byte cp1252 leaves undefined is
present (`_single_byte_codec`), so accented `VALUE` text survives.

**Program sources are read the same way** (#522):
`read_program_source(path, encoding=None, *, warnings=None,
encoding_errors="replace")` wraps `read_file_with_encoding` -- `None` /
`""` / `"auto"` detects, a named codec is used as given (an unknown one is an
`EncodingError`, never a silent ASCII fallback), and a lossy decode lands in
*warnings* naming `--encoding`. The CLI's `_read_source`, `batch`, `scan`,
`CodebaseGraphBuilder` and the MCP workspace all read a main program through
it, so they cannot disagree about a cp1252 program's text. CR LF and a lone
CR come back as LF, as the text-mode reads it replaced returned them (a
copybook read keeps its CRs; `split_source_lines` numbers both alike).

`encoding_errors` (`CopybookSearchPath` / `expand_copybooks`): `"replace"`
(default) substitutes U+FFFD and warns with a count; `"strict"` raises
`EncodingError` with file/offset context.

**EBCDIC NL records.** cp037 decodes 0x15 to U+0085, which the member passes
do not treat as a break, so `convert_to_utf8` runs
`_normalize_record_separators` after an EBCDIC decode (`\r\x85` and `\x85` ->
`\n`); the codec is classified by what it does to the bytes of `ABC`
(`_is_ebcdic_codec`). ASCII/UTF-8 text is never rewritten.

Pinned by `tests/regression/test_open_findings_m15_regression.py`,
`tests/regression/test_copybook_resolution_2026_09_28.py::TestEightBitCopybookEncoding`
and `tests/regression/test_audit_2026_09_17_preprocessing.py`.

### The COPY splice

* The member's trailing newline is stripped once before splicing (see the
  line-count invariant).
* **The splice reclaims the whole record when the `COPY` owns it**: it starts
  at `head_start` (beginning of the record) whenever `head_has_text` is false,
  and at the `COPY` keyword only when the parent has real program text before
  it on that line. The `COPY`'s own indentation is not the member's; splicing
  at the keyword pushes a member's `01` out of Area A or past column 72.
  Pinned by `tests/regression/test_copy_splice_keeps_member_columns.py`.
* **Text after the COPY's period gets a line of its own** (`tail_has_text`;
  option (b) of #355): the member is followed by a newline and the tail's own
  columns of blanks, and the source map credits that line to the parent line
  the tail was on. Appended to the member's last line it inherited the
  member's origin, so lint blamed the copybook for a parent item. Known
  limit: with `COPY A. COPY B.` on one line, B's first line is that tail and
  maps to the parent line, not to `B.cpy:1`.

### Output re-pad and width fitting

Each expanded line is re-padded with 6 spaces. Lines that fit are appended
directly; longer ones (a growing REPLACING such as `==:LKPCB:== BY
==LKPCB-PCB1==`) go through `_fit_fixed_format_width`, because a terminating
period pushed past column 72 is dropped by the final parse and merges a data
item into its neighbour:

1. **Squeeze**: interior multi-blank runs outside literals
   (`_blank_runs_outside_literals`) are shrunk rightmost first, each to no
   less than one blank, editing the string right-to-left. Keeps the line count.
2. **Continue an open literal**: `_split_open_literal` cuts at column 72 with
   the literal left open (trailing blanks kept) and resumes it on a `      -
   '...` record (hyphen in column 7, quote in column 12), moving the cut one
   column left when column 72 is the first quote of a `''` escape. Preferred
   over a blank wrap whose tail would not fit anyway. Needed because the
   expander merges continuation records before splicing, so any COPY in a
   file turns a long continued `VALUE` back into one >72-column line.
3. **Wrap** at the rightmost quote-safe blank onto a fresh Area-B line
   (`_rightmost_safe_blank(line, start, after, limit)`, bounded at column 72,
   O(len) total). A break at index 72 gives a 72-character head, so the
   filter is `<= _CODE_AREA_WIDTH`. The break point is anchored *after* the
   line's first non-blank character and the loop bails on any iteration
   without forward progress -- a wrapped tail's own 11-space prefix otherwise
   re-creates a breakable blank forever.
4. A line with no safe break (one giant token) is left as is, so the parse's
   column-72 warning reports the drop.

Wrapping adds lines (later line numbers shift -- the price of not corrupting
the statement); `ExpansionStatistics.total_lines` is counted from the final
emitted source. Pinned by `tests/regression/test_expansion_width_and_tags.py`
and `tests/unit/test_copybook_expander_edge_cases.py::TestContinuedLiteralSurvivesExpansion`.

### Source map

With `preserve_source_locations=True`, `expand_copybooks` carries a
`LineOrigin` (`(file, 1-based line)`) per expanded line through every step
that can move one:

| Step | Effect on lines | How the map survives it |
|------|-----------------|-------------------------|
| `remove_comment_lines`, `strip_sequence_area` | blank in place | line-preserving by construction; nothing to track |
| `normalize_continuation_lines` | merges N records into 1 | `line_origins` out-parameter records the input line each output line started on |
| `apply_replacing_clauses` | a `BY` text adds or removes lines | its `line_origins` out-parameter, handed to the member's recursion as `initial_origins` so it does not number the replaced text from 1 (which pushed every later member line down, past the end of the file -- #561) |
| the COPY splice | inserts a member's lines | `origins[:start] + copybook_origins + origins[end+1:]`, the first spliced line credited to the parent only when the parent had real text before the COPY on that line — the same flag that decides where the text splice starts, so map and text are spliced identically; text after the COPY's period becomes one more line credited to the parent's line (#355) |
| the re-pad's `_fit_fixed_format_width` wrap | 1 line becomes several | each piece inherits its line's origin; pieces of a line merged from continuation records map to those records (`_wrapped_origins`: piece k -> first record + k, capped at the last one absorbed) |

`ExpansionContext.content_origins` stores origins beside each cached content
entry (`cache_put(key, value, origins)` / `cache_get_origins`), so a cache hit
contributes the same map a miss would, and both are evicted together.
`_fit_origins` is a defensive clamp: a map that ever drifted must
mis-attribute nothing and raise nothing. A member's lines map 1:1 and the
next parent line maps to its own record.

`expand_copybooks(..., source_file=...)` names the main program (default
`"<main>"`); `parse_cobol_with_expansion` passes the real filename, always
requests the map and exposes it as **`ParseResult.expansion_source_map`**
(and the expansion's `included_copybooks` as `ParseResult.expansion_copybooks`:
every member opened, including one that only COPYs another and so names no
line in the map -- what the scan and MCP caches stamp, #763) --
`None` when nothing was expanded, exactly when expanded and on-disk line
numbers coincide. `analysis.lint.apply_source_map` stamps it onto findings
(`origin_file` / `origin_line`); the `lint` CLI applies it whenever
`--copybook-path` is given. Consumers must use the map, not guess (searching
the file for a finding's name cannot work for a finding inside a member).

### Comment preservation

`preserve_comments=True` (`expand --keep-comments`) puts comment text back
after every substitution, using the source map: `_restore_comment_lines`
replaces a line only when it is blank in the expansion AND its origin is a
comment line in its origin file, so it cannot rewrite code or change the line
count. `_origin_sources` reads members back through `_cached_read_file` with
the expansion's own encoding settings; an unreadable file is skipped. It
splits each file with `split_source_lines`, the splitter the source map counts
with: a `split("\n")` read a CR-only member as one line (pasted whole over its
first comment) and left `\r` on every CRLF comment (#581). A `COPY`
inside a comment comes back as text and is not expanded.

Source map and comments pinned by
`tests/regression/test_expansion_source_map_and_comments.py` and
`tests/unit/cli/test_expand_source_map_cli.py`.

### Conditional compilation during expansion

* `parse_cobol_with_expansion(process_conditionals=True)` is the default, and
  `parse_files_with_copybooks` and the CLI's `--copybook-path` parse path
  pass it, so a `COPY DFHAID` under a false `>>IF CICS DEFINED` is never
  resolved (a member that exists only for the other branch would otherwise
  fail the parse). `expand_copybooks` keeps `process_conditionals=False` by
  default (its output is the text as written), and `expand` processes
  directives only with `--define`. Pinned by
  `tests/regression/test_copybook_resolution_2026_09_28.py::TestCopyInExcludedConditionalBlock`.
* **`>>DEFINE` reaches the members below it.** Each COPY's member is
  processed with the symbols in effect on the COPY's own line: the caller's
  `defined_symbols` plus every active `>>DEFINE` above it, in the program or
  an enclosing member. `preprocess_conditional_compilation(...,
  define_log=[...])` records `(line, symbols)` after each `>>DEFINE` (`(0,
  initial)` first); `_expand_source_recursive(define_log=...)` looks the COPY's
  line up through its origin (`_symbols_at_line`), and those symbols join the
  cache key, so one member COPYd before and after a `>>DEFINE` expands both
  ways. With copybook paths the CLI leaves conditionals to the expander
  (`parse_cobol_with_expansion(process_conditionals=True,
  defined_symbols=...)`) rather than pre-processing the program, which would
  consume its `>>DEFINE` lines before expansion. A `>>DEFINE` *inside* a
  member does not reach the parent's text after the COPY. Pinned by
  `tests/regression/test_copybook_resolution_2026_09_28.py::TestDefinedSymbolsReachCopybooks`.

## REPLACE and un-expanded COPY

`preprocess/replace_statement.py` holds the two pseudo-text passes the
standalone parse runs in `CobolParser._preprocess_source`, on normalized
free-form text just before the lexer. Both preserve the line count and are
no-ops when their keyword is absent.

* **`apply_replace_statements(source, warnings=None)`** applies `REPLACE
  ==pseudo-text-1== BY ==pseudo-text-2== [ ... ] .` and cancels at `REPLACE
  OFF.`; a new `REPLACE` **replaces** the active set. Matching is on a COBOL
  **text-word** stream (`_tokenize_text_words`):
  * space / comma / semicolon are equivalent separators, not words (`MOVE;
    "FAIL" , TO` matches `MOVE , "FAIL"; TO`);
  * a **separator period** is its own word (find `MOVE WS-A TO WS-B` matches
    `MOVE WS-A TO WS-B.` and keeps the period);
  * `(` and `)` are words of their own, so `==WS-A==` reaches `WS-A(1)` and
    `WS-A(1:2)`; a replacement's parentheses stay attached (`WS-B(2)`);
  * a literal is one word compared case-sensitively, other words
    case-insensitively; `3.14` keeps its decimal point.

  Each segment between REPLACE statements gets one left-to-right scan (first
  matching pair wins); REPLACE statements are blanked; `REPLACE` inside a
  literal is ignored (the scanner shares the COPY scanner's comment-entry
  masking and end-of-line literal rule). Warnings: a set still active at EOF,
  and each `REPLACE` that does not start a well-formed statement.
  * `LEADING` / `TRAILING`: pseudo-text-1 one non-literal word, pseudo-text-2
    at most one; matches the start / end of each non-literal word
    (`REPLACE LEADING ==XX-== BY ==WS-==.` turns `XX-A` into `WS-A`).
  * IBM `==:TAG:==` partial words (`_ReplacePair.partial_word`) match inside
    any non-literal word and replace **every** occurrence (`:P:-A-:P:` ->
    `XX-A-XX`).
  Pinned by `tests/unit/test_enterprise_syntax.py::TestReplaceLeadingTrailing`
  / `TestReplacePartialWord`.

* **`find_replace_statement_spans(source)`**: `(start, end)` of every
  well-formed REPLACE, from the same `_ReplaceScanner`;
  `_skip_to_identification_division` uses it to keep a REPLACE written ahead
  of the IDENTIFICATION DIVISION header.

* **`strip_unexpanded_copy_statements(source, warnings=None)`** blanks COPY
  statements the standalone pipeline will not expand. It **reuses
  `CopyStatementLexer`** (one COPY parser, not a second one) to find each full
  span, including `REPLACING ==pseudo-text==` holding keywords and periods,
  which would otherwise leak as malformed statements (`BY MOVE ==DELETE==`
  -> a `MOVE` with no `TO`). A no-op after expansion. `warnings` gets one
  diagnostic per removed COPY plus the lexer's; `omitted_lines` gets each
  removed COPY's 1-based `(first, last)`, stored on the `TokenStream` as
  `omitted_source_lines` so EVALUATE can tell a WHEN whose body was an
  unexpanded COPY from a stacked WHEN (#314).

These passes let NIST `SM208A` (30x `REPLACE`) and `SM206A` (`COPY ...
REPLACING` pseudo-text) parse error-free; pinned by
`tests/regression/test_replace_and_copy_pseudo_text.py`.

## Copybook path resolution

`PathResolver.resolve(member_name)` searches `CopybookSearchPath.directories`
in three tiers:

1. **Tier 1** — a resolution cache keyed by `member_name` (O(1), no I/O).
2. **Tier 2** — a per-directory index (`_dir_index`, one `os.scandir()`)
   keyed by full filename only (uppercased when case-insensitive; built with
   `setdefault`). `resolve` probes the name, then name + each configured
   extension in order. A bare-stem key would let `COPY MEM` hit `MEM.bak` or
   the program's own `SUB.cbl`.
3. **Tier 3** — a full filesystem search (`find_copybook_file`).

**First-configured directory wins** in every tier, then first probe. Pinned
by `tests/regression/test_audit_2026_08_12_core.py::TestPB6FirstDirectoryWins`
and `tests/regression/test_copybook_resolution_2026_09_28.py::TestIndexedLookupHonoursConfiguredExtensions`.

**Case folding** (like Enterprise COBOL's COPY text-name,
`_member_probe_names`): the name as written first, then per configured
extension the uppercased name before the name as written (bare uppercased name
in the `""` slot) -- `copy errorcd.` finds `ERRORCD.cpy` over `errorcd.cpy`,
but extension order decides before case (`COPY Foo` takes `Foo.cpy` over
`FOO.cbl`). A name with `.`, `/` or `\` is a literal path and not folded.
`OF`/`IN` library names fold the same way (`_library_directories`: `MYLIB/`,
`mylib/`, then the search directory); SYSLIB order outranks both. Found paths
take the on-disk basename casing (`_on_disk_casing`). See #289,
`tests/regression/test_copy_member_case_folding.py`.

**Containment**: every tier goes through
`validate_path_within_directory(path, search_dir)` (symlinks resolved, result
must stay inside). Tier-2 hits use `_validate_indexed_result` (any configured
directory, else `PathTraversalError`) because `entry.is_file()` follows
symlinks. The `..` guard is per path segment, so `weird..name.cpy` is fine.
Pinned by `tests/regression/test_open_findings_high_regressions.py::TestH6PathResolverContainment`.

**Suggestions**: `suggest_similar_copybooks` uses `suggestion_extensions`
(default `(".cpy", ".CPY", "")`, applied with `dataclasses.replace`, caller's
config untouched) rather than the resolution extensions, which would suggest
the program's own `.cbl` back; `""` stays for extensionless PDS downloads. In
`get_available_copybooks`, `""` lists only
extensionless files. Pinned by `tests/regression/test_copybook_suggestion_pool.py`.
The name just looked up is never suggested back: an upper-cased stem equal to
it is a file differing only in letter case, which `find_copybook_file` reports
as `CopybookNotFoundError(..., case_variant_exists=True)` ("A copybook named X
exists in a different letter case; the member is matched as written") instead
of "Did you mean: X?" (#580). Pinned by
`tests/regression/test_issue_580_copy_member_as_written.py`.

## Error hierarchy

All preprocessing errors extend `PreprocessingError` (`_normalize.py`),
which extends plain `Exception` -- **not** `cobolparser._errors.ParseError`,
so `except ParseError` does not catch them:

| Exception | When raised |
|-----------|------------|
| `CircularReferenceError` | COPY chain forms a cycle |
| `CopybookNotFoundError` | No matching file on any search path (not with `skip_missing_copybooks=True`) |
| `PathTraversalError` | COPY target escapes the allowed directory |
| `EncodingError` | Cannot decode copybook bytes (`encoding_errors="strict"`) |
| `NestingDepthError` | COPY nesting exceeds configured limit |
| `CopybookSizeExceededError` | One copybook exceeds `max_file_size` |
| `TotalExpansionSizeExceededError` | The whole expansion exceeds `max_total_size` |
| `CopybookSyntaxError` | `validate_copybook_content` finds binary content (NUL bytes); everything else it checks is a warning |

`LevelNumberMismatchWarning` is a `UserWarning`, not a `PreprocessingError`.
`CopybookNotFoundError`, `PathTraversalError` and `CopybookSizeExceededError`
are also importable from `path_resolver`.

## See also

* [lexer.md](lexer.md) — consumes output of `normalize_fixed_format`; `_fixed_format_comment_tokens`, `mask_comment_entries`
* [parser.md](parser.md) — `CobolParser._preprocess_source` runs the in-parser passes (Pipeline above)
* [batch.md](batch.md) — `parse_files_with_copybooks` and `scan` with copybook expansion
* [cli.md](cli.md) — `preprocess` / `expand` subcommands, `--copybook-path`, `--define`, `--debug-lines`, `--source-format`, `cobol.yml`
* [analysis.md](analysis.md) — `lint`'s `apply_source_map` (consumer of `expansion_source_map`)
* [history](history/preprocessing.md) — archived dated notes (fix write-ups, audits, bug hunts) moved out of this file
