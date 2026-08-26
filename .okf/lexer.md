---
type: Module
title: Lexer
description: Tokenizes COBOL source into Token objects; 243 TokenType values; optional Cython hot-path.
tags: [lexer, tokenizer, cython, token-type]
timestamp: 2026-08-14T23:45:00Z
---

# Overview

`cobolparser/lexer.py` — `CobolLexer` converts preprocessed COBOL text into
`List[Token]`. The preprocessor must strip fixed-format comment lines (column 7
`*`/`/`) **before** the lexer sees them.

When `cobolparser._lexer_fast` is compiled (see Cython section below), the lexer
transparently uses the Cython subclass for hot-path methods. Falls back to
pure-Python without configuration.

# Public API

```python
from cobolparser import CobolLexer, Token, TokenType, tokenize_cobol, LexerError

tokens: list[Token] = CobolLexer(text).tokenize()
tokens: list[Token] = tokenize_cobol(text)       # convenience wrapper
```

`Token` fields: `type: TokenType`, `value: str`, `location: SourceLocation`.

# TokenType Enum

`TokenType(IntEnum)` — 243 members. Using `IntEnum` rather than plain `Enum`
makes hot-path membership tests and `hash()` lookups significantly cheaper.

Major groups:

| Group | Examples |
|-------|---------|
| Literals | `STRING_LITERAL`, `NUMERIC_LITERAL`, `BOOLEAN_LITERAL`, `FIGURATIVE_CONSTANT` |
| Identifiers | `IDENTIFIER`, `QUALIFIED_IDENTIFIER` |
| Division keywords | `IDENTIFICATION_DIVISION`, `ENVIRONMENT_DIVISION`, `DATA_DIVISION`, `PROCEDURE_DIVISION` |
| Section keywords | `PROGRAM_ID`, `CONFIGURATION_SECTION`, `WORKING_STORAGE_SECTION`, `LINKAGE_SECTION`, … |
| File description | `FD`, `SD` |
| FILE-CONTROL | `ASSIGN_TO`, `ORGANIZATION`, `ACCESS`, `RECORD`, `KEY`, `ALTERNATE`, `DUPLICATES`, … |
| Statement verbs | `MOVE`, `PERFORM`, `CALL`, `IF`, `EVALUATE`, `COMPUTE`, `ADD`, `SUBTRACT`, … |
| Operators | `EQUAL`, `LESS_THAN`, `GREATER_THAN`, `AND`, `OR`, `NOT`, … |
| Punctuation | `PERIOD`, `COMMA`, `LEFT_PAREN`, `RIGHT_PAREN` |
| IBM extensions | `EXEC_SQL`, `EXEC_CICS`, `EXEC_IMS` |

# Fixed-Format Column Layout

| Columns | Purpose |
|---------|---------|
| 1–6 | Sequence number (ignored) |
| 7 | Indicator: space=code, `*`/`/`=comment, `-`=continuation |
| 8–11 | Area A (division/section/paragraph headers, level 01/77) |
| 12–72 | Area B (statements, subordinate data items) |
| 73–80 | Identification (ignored) |

The lexer works on free-form text. `normalize_fixed_format` (see
[preprocessing.md](preprocessing.md)) handles column extraction and continuation
line merging before tokenization.

# Cython Acceleration

Three optional extension modules live alongside the pure-Python sources:

| Module | Overrides (pure-Python file) | Accelerated symbols |
|--------|------------------------------|---------------------|
| `cobolparser/_lexer_fast.pyx` | `cobolparser/lexer.py` (`_CobolLexerPure`) | `check_division_header`, `read_word_from_text`, `tokenize_program_text`, `_try_single_line_string`, `read_number_from_text`, `tokenize` |
| `cobolparser/_preprocess_fast.pyx` | `cobolparser/preprocess/__init__.py` | `normalize_fixed_format` |
| `cobolparser/_data_fast.pyx` | `cobolparser/parsers/divisions/data.py` | `parse_picture_clause_fast`, `parse_data_item_clauses_fast` |

**Activation** — each module is imported via a guarded `try/except ImportError`
at the bottom of its host Python file; the pure-Python path is used silently
when the extension is absent:

```python
# lexer.py (bottom of file)
try:
    from cobolparser._lexer_fast import CobolLexer  # type: ignore
except ImportError:
    CobolLexer = _CobolLexerPure   # pure-Python fallback
```

The same pattern applies in `preprocess/__init__.py` (for `normalize_fixed_format`)
and `parsers/divisions/data.py` (for `parse_data_item_clauses_fast`).

**Performance** — approximately **~3× lexer throughput** over pure Python
(documented in `setup.py`). Preprocessor and DATA DIVISION gains are comparable
but are not separately benchmarked in the checked-in docs.

**Building** — pre-generated `.c` files are checked in so only a C compiler
(not Cython) is required for a normal install:

```bash
# Build in-place (development)
python setup.py build_ext --inplace

# Or via the [fast] extra (recommended)
pip install -e ".[fast]"

# Opt out entirely (no compiler or Cython needed)
COBOLPARSER_SKIP_EXT=1 pip install -e ".[dev]"
```

**Pure/Cython parity (audit 2026-07-08):** `_lexer_fast.pyx`'s
`is_line_start_quote` check (used to decide whether an unterminated string
could be a continuation of a preceding VALUE clause) used `text[:pos].strip()
== ""`, a broader whitespace definition (`str.isspace()` — `\v`, `\f`, NBSP,
…) than the pure-Python version's explicit `char not in " \t"` loop. A
control byte other than space/tab immediately before the quote made the
compiled build classify the line differently from the fallback path for the
same input. Fixed by replacing the Cython `.strip()` call with the same
explicit `" \t"`-only loop the pure-Python lexer uses. Pinned by
`tests/regression/test_normalize_line_number_preservation.py::TestLexerLineStartQuoteWhitespaceParity`.

# Errors

`LexerError` — extends `ParseError` (`cobolparser/_errors.py`). Raised for
unrecognised characters or malformed string literals.

# Warnings (non-fatal diagnostics)

`CobolLexer` (both the pure-Python `_CobolLexerPure` and the `_lexer_fast`
Cython subclass) also collects a `self.warnings: list[str]`, reset at the
top of each `tokenize()` call, exposed via:

> Until 2026-08-12 (audit finding P-B5) the reset was pure-Python-only:
> `_lexer_fast.pyx`'s `tokenize()` reset only `self.tokens`/`self.errors`,
> so repeated `tokenize()` calls on one compiled lexer *duplicated* every
> warning. Fixed by adding `self.warnings = []` to the `.pyx` (checked-in
> `_lexer_fast.c` regenerated). Pinned by
> `tests/regression/test_audit_2026_08_12_core.py::TestPB5LexerWarningsReset`,
> which exercises both paths.

```python
lexer = CobolLexer(text, free_form=True)
tokens = lexer.tokenize()
lexer.has_warnings()   # -> bool
lexer.get_warnings()   # -> list[str]
```

`CobolParser.parse()` forwards every lexer warning into `ParseResult.warnings`
(prefixed `"Lexer warning: "`) after the existing `lexer.has_errors()` check.

Currently the only producer is the free-form unterminated-string-literal
case: `parse_cobol()` always lexes with `free_form=True` after
normalization, and the free-form path never raised `LexerError` for a
string literal that runs to end-of-line without a closing quote — it was
silently treated as closed at the line boundary (audit 2026-07-08,
finding H7 in `reports/open-findings.md`). That silence is intentional —
a lone quote can legitimately appear inside a free-form comment (e.g.
`COMPILER"S`), so promoting it to a hard `LexerError` would break valid
input — but it is no longer *undetectable*: a caller that checks
`ParseResult.warnings` now sees
`"Unterminated string literal at line N, column C: closed at end of line
instead of a matching quote"`. Pinned by
`tests/regression/test_open_findings_high_regressions.py::TestH7UnterminatedStringWarns`.

A second producer (added 2026-07-09, finding M7 in
`reports/open-findings.md`): `read_prefixed_literal_from_text` — which
handles typed literals (`X'..'`, `N'..'`, `G'..'`, `NX'..'`) — now
validates hex content for the `X'..'`/`NX'..'` prefixes specifically.
`X'ABC'` (odd number of hex digits — each byte needs two) and `X'ZZ'`
(non-hex characters) previously round-tripped with no diagnostic; both
now append to `self.warnings`. `G'..'`/`N'..'` literals are untouched —
they have codepage-dependent validity rules out of scope for this fix,
and the value is still not *decoded* to actual bytes/characters for
either form (that would require a codepage decision this fix doesn't
make). Pinned by
`tests/regression/test_open_findings_medium_regressions.py::TestM7TypedLiteralHexValidation`.

# NULL / NULLS figurative constants (2026-08-05)

`FIGURATIVE_CONSTANTS` previously omitted `NULL`/`NULLS` -- the standard
COBOL figurative constants used as the `VALUE` of `USAGE POINTER` /
`PROCEDURE-POINTER` / `FUNCTION-POINTER` data items (`VALUE IS NULL`) and as
the operand of `SET ptr TO NULL` / relational pointer comparisons (`IF ptr =
NULL`). The word instead fell through to the generic `IDENTIFIER` branch of
`read_word_from_text`/`read_identifier`, making it lexically indistinguishable
from a real data-name reference. Notably, several downstream analysis modules
(`analysis/move_type_checker.py`, `analysis/constraints.py`,
`generators/data/values.py`) already carried their own private
`NULL`/`NULLS` figurative-constant lists in anticipation of this classification,
but the lexer -- the single source of truth for token typing -- had never
actually been updated to match. `parse_value_clause`
([parser.md](parser.md)) happened to also accept a bare `IDENTIFIER` as a
VALUE operand, so `01 WS-PTR USAGE POINTER VALUE IS NULL.` already produced
`value_clause == "NULL"` by accident even before this fix; the fix corrects
the token's *type*, not its round-tripped text. `NULL`/`NULLS` were added to
the one `FIGURATIVE_CONSTANTS` set class attribute that both
`read_word_from_text` and `read_identifier` consult via `self.` lookup, so
the compiled `_lexer_fast` Cython subclass (which does not redefine that set)
picks up the change automatically with no `.pyx`/`.c` regeneration needed.
Pinned by `tests/regression/test_null_pointer_value_clause.py` and
`tests/unit/test_lexer.py::TestCobolLexerFigurativeConstants::test_null_figurative_constants`.

# Dead KEYWORDS entries removed (2026-08-05)

A full sweep of all 194 `CobolLexer.KEYWORDS` entries against the actual
parser (fed each keyword as a data-item name, a paragraph name, and checked
every non-lexer reference to its `TokenType`) found seven entries that were
pure landmines: mapped to a `TokenType` **zero parsers anywhere consumed**,
so the entry never matched any real COBOL syntax and existed only to steal a
legitimately-named data item/paragraph/condition-name, silently corrupting
it to an `ANONYMOUS-N` item or an empty paragraph with `result.success` still
`True`.

* `"FILE-STATUS"`, `"RECORD-DELIMITER"`, `"READ-ONLY"` -- real COBOL syntax
  always writes these as two separate words (`FILE STATUS`, `RECORD
  DELIMITER`, `READ ONLY`); every clause parser that recognizes them
  (`environment_select.py`'s `_parse_file_status_clause` /
  `_parse_record_key_clause` / `_parse_sharing_clause`) already dispatches on
  the leading word (`"FILE"`/`"RECORD"`/`"READ"`, each already a keyword in
  its own right) and consumes the second word as plain text -- the fused
  single-token spelling was never how the parser actually recognized these
  clauses, so it could never fire on real input.
* `"END-SET"`, `"OTHERWISE"` -- not COBOL reserved words at all. `SET` has no
  scope terminator in the grammar (it carries no conditional/nested body,
  unlike `MOVE`/`PERFORM`/etc.), and EVALUATE's default branch keyword is
  `WHEN OTHER`, never `OTHERWISE`.
* `"END-OF-FILE"`, `"EOF"` -- not reserved words either. End-of-file testing
  in COBOL is done via a `READ` statement's `AT END` clause plus a
  programmer-defined level-88 condition-name, and `EOF`/`END-OF-FILE` are
  exactly the names real IBM COBOL programs conventionally give that
  condition (or its backing flag). This one was independently confirmed by
  the project's own `parsers/statements/_conditions.py` docstring, which
  already documented `IF END-OF-FILE` as *the* canonical bare
  condition-name example -- the code's own comment describes the behavior
  this bug prevented.

All seven were removed from `KEYWORDS` (comments left in place explaining
why, so a future contributor doesn't re-add them by "completeness"); the word
now lexes as a plain `IDENTIFIER` in every position. Because `_lexer_fast.pyx`
consults the inherited `self.KEYWORDS` dict rather than defining its own copy
(see "Cython Acceleration" above), this fix applies to both the pure-Python
and compiled lexer paths with no `.pyx`/`.c` regeneration needed. The real,
two-word SELECT clauses these words are named after (`FILE STATUS IS`,
`RECORD DELIMITER IS`, `SHARING WITH READ ONLY`) are unaffected -- verified
by an end-to-end SELECT-clause test. Pinned by
`tests/regression/test_dead_keyword_removal.py`.

**Addendum (2026-08-12):** four more unreachable entries removed — the
space-containing keys `"KEY IS"`, `"WITH LOCK"`, `"NO REWIND"`, and
`"NO ADVANCING"`. `KEYWORDS` is only ever consulted with a *single* word
(`read_word_from_text`/`read_identifier` build one word at a time), so a key
containing a space could never match anything. The single-word aliases
(`"REWIND"`, `"ADVANCING"`, ...) remain; the parsers recognize the two-word
phrases word by word. A comment at the removal site explains why, so the
entries don't get re-added for "completeness".

# Free-form `*>` inline comments now stripped (2026-08-07)

`*>` (the free-form COBOL inline-comment marker -- legal in both fixed- and
free-form source, anywhere on a line) was previously recognized nowhere in
the pipeline: `normalize_fixed_format` only strips *whole* comment lines
(column-7 indicator `*`/`/`/`D`; see [preprocessing.md](preprocessing.md)),
and the lexer had no `*>` handling at all -- `*` tokenized as `MULTIPLY_OP`,
`>` as `GREATER`, and the comment's English words as ordinary
identifiers/keywords. A comment like `*> start at 2 ...` could lex "start"
as the `START` keyword and produce a real (bogus) `IOStartStatement` with no
actual START verb anywhere in the source -- confirmed via
`examples/cobol/shamrice/unstring.cbl:243`, previously special-cased as a
known-unresolved entry in `tests/integration/test_boundary_inventory_corpus.py`
(now removed, since the underlying bug is fixed).

`tokenize_program_text` (pure-Python `_CobolLexerPure` in `lexer.py`, and the
Cython `_lexer_fast.pyx` mirror) now checks `char == "*" and text[pos+1] ==
">"` immediately before the single-character-token dispatch (so `*` isn't
read as `MULTIPLY_OP` first) and, when it matches, emits the rest of the
line as one `COMMENT` token rather than continuing to tokenize it. The check
runs after the string-literal branch, so `*>` inside a quoted literal
(`"A *> B"`) is unaffected -- it's already consumed as literal text before
the comment check is reached. `**` (exponentiation) is also unaffected: it
only matches `SINGLE_CHAR_TOKENS` twice in a row, never `text[pos+1] ==
">"`. No parser changes were needed: every statement parser already skips
`COMMENT` tokens via `skip_whitespace()` (`parsers/statements/_utils.py`).
Pinned by `tests/regression/test_inline_comment_stripping.py`, including a
pure/Cython parity check.

# Unified tokenize pipeline (2026-07-20, M6)

`tokenize_cobol()` and CLI `tokenize` no longer run the lexer's own
fixed-format handler (`free_form=False`): both now route fixed-format
source through `normalize_fixed_format` + `free_form=True` lexing — the
exact path `parse_cobol()` uses — via the shared `_tokenize_source()`
helper in `lexer.py`, so the two pipelines agree on every non-COMMENT
token (count, values, line numbers). Comment lines are not lost:
`_fixed_format_comment_tokens()` captures them during normalization and
`_merge_comment_tokens()` re-emits them as `COMMENT` tokens at their
original line numbers. Free-form input behavior is unchanged, and the
helpers are module-level additions — no `_lexer_fast.pyx` /
`_preprocess_fast.pyx` mirror was touched. Pinned by
`tests/regression/test_open_findings_m6_regression.py`.

**Column-72 overflow warnings now flow through (2026-08-14):** `_tokenize_source`'s
own `normalize_fixed_format` calls previously omitted `warnings=`, so any
overflow diagnostic (see [preprocessing.md](preprocessing.md)'s "Column 73+
overflow warning") was silently discarded even though the function's return
type already carries a `warnings` slot. Now collected and prepended to the
returned `(tokens, errors, warnings)` tuple's third element (ahead of the
lexer's own `get_warnings()`), with the same clear-before-retry handling as
the unterminated-literal recovery path (an EOF `ValueError` mid-scan can
leave partial entries that the retry would otherwise duplicate). CLI
`tokenize` still discards this element deliberately (best-effort token
dump, unchanged); `tokenize_cobol()` callers now see it.

**`preprocess_fixed` honored in every flag combination (2026-08-26):**
`_tokenize_source`'s whole normalization block sat under `if not
free_form:`, so `free_form=True, preprocess_fixed=True` silently ignored
the forced layout even though the docstring claimed the parameter
"mirrors `parse_cobol`'s" (which normalizes for that combination). The
guard is now `if not free_form or preprocess_fixed:` — an explicit True
wins over `free_form`, matching `parse_cobol`; an explicit False still
never normalizes, and `parse_cobol` now honors False without
`free_form=True` too, via `CobolParser`'s new `preprocess_fixed`
parameter (see [preprocessing.md](preprocessing.md) and the CHANGELOG
Unreleased entry). Pinned by
`tests/regression/test_tagged_sequence_area_detection.py`.

**`_fixed_format_comment_tokens` V/v gap (fixed 2026-08-22, caught in PR
review):** when `normalize_fixed_format` gained `version_tag_lines_as_comments`
(see [preprocessing.md](preprocessing.md)), `_fixed_format_comment_tokens`'s
own re-scan of the physical lines was not updated to match — it still only
recognized `*`/`D`/`d` (plus `/` for page breaks) when building its
`placeholders` list. A V-line still produces a blank placeholder line in
`normalize_fixed_format`'s output (comment lines are always blanked,
regardless of which indicator triggered it), but the re-scan skipped it
entirely (no placeholder appended), desynchronizing the 1:1 pairing between
blank normalized lines and physical placeholder-producing lines by one:
`tokenize_cobol(..., keep_comments=True)` then attributed the *next* real
comment to the V-line's own (earlier) line number, and the V-line's own
comment text was dropped instead of re-emitted. Fixed by adding `V`/`v` to
the same `elif` branch as `D`/`d`. Pinned by
`tests/regression/test_version_tag_line_handling.py::TestVersionTagCommentTokenPreservation`.

# Digit-led hyphenated names beyond one hyphen segment (2026-08-21)

`tokenize_program_text`'s digit-branch (identical logic in `lexer.py` and
`_lexer_fast.pyx`) decides identifier-vs-numeric-literal for a token
starting with a digit. It previously only looked one hyphen segment past
the leading digit run, which misread two real-corpus paragraph/data-name
shapes as numbers:

* `43E00-PROD` / `4E000-X` — the first segment alone looks like scientific
  notation (`E` followed by digits), so the existing E-exponent exclusion
  fired and the name was split into `NUMERIC_LITERAL("43E00")` + `MINUS` +
  `IDENTIFIER("PROD")`.
* `22310-01-TRAITE` — the *second* segment (`01`) is also all-digit, so the
  one-hop lookahead never reached the third segment's letters at all.

Fixed by extending the lookahead past any matched E-exponent shape and then
walking further hyphen-joined segments (each a digit run or a letter run)
for a letter anywhere in the rest of the word; that `has_alpha` result is
ORed with the original one-hop check (still needed for no-hyphen shapes
like `25COUNT`/`45A`, which the hyphen-walk doesn't cover since it only
triggers on a `-` continuation). Plain scientific-notation literals with no
trailing hyphen segment (`5E10`, `5E+5`, `5E-3`, `1.5E10`) are unaffected —
verified via `tests/regression/test_real_corpus_parse_failures.py::
TestDigitLedHyphenatedProcedureNames`. Both lexers needed the identical fix
independently (no shared helper — see "Cython Acceleration" above): the
`.pyx` was recompiled and its checked-in `.c` regenerated.

**Accepted trade-off, not a bug (found by a `/code-review` pass on the fix
itself):** a *space-free* arithmetic expression whose left operand happens to
look like scientific notation — `COMPUTE X = 5E10-Y.` — now lexes as one
`IDENTIFIER("5E10-Y")` instead of `NUMERIC_LITERAL("5E10") MINUS
IDENTIFIER("Y")`. This is unavoidable: the character sequence is
structurally identical to a real hyphenated name (`43E00-PROD`, this fix's
own corpus-confirmed repro), and no context-free lexer can tell the two
apart without look-ahead into the statement's semantics. Real COBOL
arithmetic is written with spaces around operators (this shape requires
omitting every space), so the trade-off favors the common, corpus-confirmed
case. Pinned as an *expected* result (not a regression to chase) by
`TestDigitLedHyphenatedProcedureNames::
test_space_free_exponent_shaped_subtraction_is_an_accepted_tradeoff`.

# See Also

* [preprocessing.md](preprocessing.md) — upstream fixed-format normalisation
* [parser.md](parser.md) — consumes `List[Token]` via `TokenStream`

# Stray '!' / '|' / '¬' post-pass + digit-word scan early exit (2026-08-24)

`CobolLexer._flag_stray_sql_chars()` runs at the end of `tokenize()` (both
the pure-Python and `_lexer_fast.pyx` implementations call it — the fast
path inherits the pure-Python method; one linear scan, no C mirror): every
BANG/PIPE/NOT_SIGN token *outside* an `EXEC ... END-EXEC` token span
records the old hard `Invalid character` LexerError. The tokens exist only
so embedded EXEC SQL (`!=`, `||`, `¬=`) round-trips; the first version
accepted them everywhere, which let garbage like `MOVE BOGUS !!! TO WS-A`
parse "successfully" with zero diagnostics. Pinned by
`tests/regression/test_stray_sql_chars.py`.

The digit-led-identifier heuristic's hyphen-segment scan (`has_alpha`,
both lexers) stops at the first letter found — the answer is final there,
and `read_word_from_text` re-scans the whole word anyway. The old
dash-then-letter disjunct in the decision expression was removed as dead:
the segment scan already sets `has_alpha` for it, and when an exponent was
consumed the character at `lookahead_pos` is E/e, never a dash.
