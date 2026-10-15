---
type: History
title: Lexer history
description: Archived dated notes moved out of lexer.md; not loaded by default.
tags: [history, lexer]
timestamp: 2026-10-15T00:00:00Z
---

# Lexer history

Archive of dated notes moved verbatim from [lexer.md](../lexer.md) on 2026-10-15, when the topic file was restructured to describe only the current state. Every still-valid behaviour, invariant and rationale in these notes is restated in present tense in the topic file; what remains here is the when, the before/after, the audit finding ids and the fix narratives. Newest first. Links inside quoted text point at the topic files as they stood.

## `debug_lines` in `_tokenize_source` (2026-10-14, #334)

**`debug_lines` (2026-10-14, #334):** `_tokenize_source(...,
debug_lines=True)` normalizes with `debug_lines_as_comments=False`, and
`_fixed_format_comment_tokens(..., debug_lines_as_comments=False)` then
leaves `D`/`d` lines out of the recovered COMMENT tokens (they are code).
`tokenize --debug-lines` uses it. See [preprocessing.md](../preprocessing.md).

## `*>` comments between `&` parts (2026-10-14, #389)

**`*>` comments between the parts (issue #389, 2026-10-14).** A floating
`*>` comment may sit between the two literals (`'AB' & *> note` / `'CD'`),
or a whole comment line may. The merge loop skips COMMENT tokens as it
skips NEWLINEs (the comment token is kept, after the merged literal), and
`_ampersand_joins` reads each *earlier* line only up to `_code_end()`: the
first `*>` outside a literal, or nothing for a fixed-format `*`/`/`
comment line. An `&` inside the comment text does not count.

## Typed locals in `_data_fast` (2026-09-28)

**Typed locals must not narrow what the pure path accepts (2026-09-28).**
`parse_data_item_clauses_fast` held the OCCURS min/max counts in `cdef int`s.
`int()` of a count past 2**31-1 then raised `OverflowError`, which escaped the
`(TypeError, ValueError)` guards mirrored from the pure walker; the division
loop recovered by abandoning the DATA DIVISION (every item gone, one "value
too large to convert to int" error at line 1) where the pure path kept the
count. They are `cdef object` now. When C-typing a mirror, only type values
whose range the pure path also bounds (loop indexes, positions) -- never a
value read out of the source.

## `&` literal concatenation introduced (2026-09-28)

(Merged post-tokenize since 2026-09-28.)

`"AB" & "CD"` is the literal `"ABCD"` anywhere a literal may appear;
before this a VALUE clause kept only `"AB"` (and warned about the rest) and
a MOVE source read `"AB" "CD"`. Only literals of one kind are joined

parts follow it. Fast path: no `&` in any line -> no work. The
`_lexer_fast.c` was regenerated with Cython 3.3.0. Pinned by

## IDENTIFICATION DIVISION comment-entries introduced (2026-09-28)

(Since 2026-09-28.)

`AUTHOR.` / `INSTALLATION.` / `DATE-WRITTEN.` / `DATE-COMPILED.` /
`SECURITY.` / `REMARKS.` take a *comment-entry*: free text (any character)
up to the next Area A entry. Lexed as program text, `AUTHOR. JOHN O'BRIEN.`
raised a spurious "Unterminated string literal" warning (the apostrophe) and
`DATE-WRITTEN. 01/02/99.` split into `01 / 02 / 99`. Now
`_comment_entry_starts(source, lines)` (module-level, pure Python, called

## Declared currency symbols introduced (2026-09-28)

(Since 2026-09-28.)

`CURRENCY SIGN IS '£'` / `CURRENCY SIGN IS 'EUR' WITH PICTURE SYMBOL '#'`
makes the symbol a PICTURE editing character like `$`. `__init__` now
collects the declared non-alphanumeric symbols
(`_declared_currency_symbols(source)`, one regex scan) into
`self._currency_symbols`; in `tokenize_program_text` (both lexers) a
character that would otherwise be an "Invalid character" error is emitted
as a `CURRENCY` token when it is declared. Characters that already lex as
something (`& ! | < > :`, letters) are not rerouted. Before, every `£` in
`PIC £££9.99` was a lexer error. See [ast-models.md](../ast-models.md) for

## `str.splitlines()` line-number shift (2026-09-17)

`_tokenize_source` all split through it, never `str.splitlines()`: the latter
also breaks on form feed / NEL / U+2028 etc., which shifted every later
token's line number by one (2026-09-17). See
[preprocessing.md](../preprocessing.md) ("Audit 2026-09-17: record
boundaries ...").

## Signature-drift guard for `_data_fast` (2026-09-05)

**Signature-drift guard (`_data_fast`, added 2026-09-05):** `ImportError` is not
the only way the fast path can be wrong. The extension is compiled separately
from its caller, so the binary can be *older* than the Python module that calls
it — a stale in-place `.so`, a cached `build/` tree, or an installed wheel
shadowing the source tree. `data_clauses.parse_data_item` calls
`parse_data_item_clauses_fast` with `_DATA_FAST_ARG_COUNT` (20) positional
arguments and no guard, so that drift raised a `TypeError` from the middle of
*every* data-description entry; the division loop recorded it as a generic
error and recovered by abandoning the division, so a build problem degraded
every program with a DATA DIVISION to a near-empty AST whose only clue was an
argument count. Observed on Python 3.14 against an 18-parameter build.

`data_clauses._data_fast_usable()` now probes the compiled helper once at

The checked-in `.c` files were verified in sync with their `.pyx` sources on
2026-09-05 (regenerated and compared argument tables), so this guard protects
against stale *builds*, not against a stale checked-in `.c`.

## `preprocess_fixed` in every flag combination (2026-08-26)

**`preprocess_fixed` honored in every flag combination (2026-08-26):**
`_tokenize_source`'s whole normalization block sat under `if not
free_form:`, so `free_form=True, preprocess_fixed=True` silently ignored
the forced layout even though the docstring claimed the parameter
"mirrors `parse_cobol`'s" (which normalizes for that combination). The
guard is now `if not free_form or preprocess_fixed:` — an explicit True
wins over `free_form`, matching `parse_cobol`; an explicit False still
never normalizes, and `parse_cobol` now honors False without
`free_form=True` too, via `CobolParser`'s new `preprocess_fixed`
parameter (see [preprocessing.md](../preprocessing.md) and the CHANGELOG
Unreleased entry). Pinned by
`tests/regression/test_tagged_sequence_area_detection.py`.

## Stray SQL characters post-pass and digit-word scan early exit (2026-08-24)

(Plus the digit-word scan early exit; 2026-08-24.)

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

## `_fixed_format_comment_tokens` V/v gap (2026-08-22)

**`_fixed_format_comment_tokens` V/v gap (fixed 2026-08-22, caught in PR
review):** when `normalize_fixed_format` gained `version_tag_lines_as_comments`
(see [preprocessing.md](../preprocessing.md)), `_fixed_format_comment_tokens`'s
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

## Digit-led hyphenated names (2026-08-21)

number. History (2026-08-21):

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

## Column-72 overflow warnings through `_tokenize_source` (2026-08-14)

**Column-72 overflow warnings now flow through (2026-08-14):** `_tokenize_source`'s
own `normalize_fixed_format` calls previously omitted `warnings=`, so any
overflow diagnostic (see [preprocessing.md](../preprocessing.md)'s "Column 73+
overflow warning") was silently discarded even though the function's return
type already carries a `warnings` slot. Now collected and prepended to the
returned `(tokens, errors, warnings)` tuple's third element (ahead of the
lexer's own `get_warnings()`); the unterminated-literal retry now lives in
`preprocess.source_format.normalize_with_recovery`. Both public callers
discard this element: CLI `tokenize` deliberately (best-effort token dump),
and `tokenize_cobol()` returns only the token list -- so today only a direct
`_tokenize_source()` caller sees these warnings.

## Lexer warnings reset in the compiled lexer (2026-08-12, P-B5)

> Until 2026-08-12 (audit finding P-B5) the reset was pure-Python-only, so
> repeated `tokenize()` calls on one compiled lexer *duplicated* every
> warning. Pinned by
> `tests/regression/test_audit_2026_08_12_core.py::TestPB5LexerWarningsReset`,
> which exercises both paths.

## Space-containing KEYWORDS entries removed (2026-08-12)

**Addendum (2026-08-12):** four more unreachable entries removed — the
space-containing keys `"KEY IS"`, `"WITH LOCK"`, `"NO REWIND"`, and
`"NO ADVANCING"`. `KEYWORDS` is only ever consulted with a *single* word
(`read_word_from_text`/`read_identifier` build one word at a time), so a key
containing a space could never match anything. The single-word aliases
(`"REWIND"`, `"ADVANCING"`, ...) remain; the parsers recognize the two-word
phrases word by word. A comment at the removal site explains why, so the
entries don't get re-added for "completeness".

## Free-form `*>` inline comments (2026-08-07)

`COMMENT` token (both lexers). History (2026-08-07):

`*>` (the free-form COBOL inline-comment marker -- legal in both fixed- and
free-form source, anywhere on a line) was previously recognized nowhere in
the pipeline: `normalize_fixed_format` only strips *whole* comment lines
(column-7 indicator `*`/`/`/`D`; see [preprocessing.md](../preprocessing.md)),
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

## NULL / NULLS figurative constants (2026-08-05)

`QUOTE(S)`, `NULL`, `NULLS`) lex as `FIGURATIVE_CONSTANT`. History (2026-08-05):

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
([parser.md](../parser.md)) happened to also accept a bare `IDENTIFIER` as a
VALUE operand, so `01 WS-PTR USAGE POINTER VALUE IS NULL.` already produced
`value_clause == "NULL"` by accident even before this fix; the fix corrects
the token's *type*, not its round-tripped text. `NULL`/`NULLS` were added to
the one `FIGURATIVE_CONSTANTS` set class attribute that both
`read_word_from_text` and `read_identifier` consult via `self.` lookup, so
the compiled `_lexer_fast` Cython subclass (which does not redefine that set)
picks up the change automatically with no `.pyx`/`.c` regeneration needed.
Pinned by `tests/regression/test_null_pointer_value_clause.py` and
`tests/unit/test_lexer.py::TestCobolLexerFigurativeConstants::test_null_figurative_constants`.

## Dead KEYWORDS entries removed (2026-08-05)

`CobolLexer.KEYWORDS` (186 entries on 2026-10-15) holds only single words
that some parser consumes. Rationale for what was taken out (2026-08-05):

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

## Unified tokenize pipeline (2026-07-20, M6)

(M6, 2026-07-20.)

`tokenize_cobol()` and CLI `tokenize` no longer run the lexer's own
fixed-format handler (`free_form=False`): both now route fixed-format
source through `normalize_fixed_format` + `free_form=True` lexing — the
exact path `parse_cobol()` uses — via the shared `_tokenize_source()`
helper in `lexer.py` (its fixed-or-free verdict comes from
`preprocess.source_format.detect_fixed_format`, the same detector
`parse_cobol()` uses), so the two pipelines agree on every non-COMMENT
token (count, values, line numbers). Comment lines are not lost:
`_fixed_format_comment_tokens()` captures them during normalization and
`_merge_comment_tokens()` re-emits them as `COMMENT` tokens at their
original line numbers. Free-form input behavior is unchanged, and the
helpers are module-level additions — no `_lexer_fast.pyx` /
`_preprocess_fast.pyx` mirror was touched. Pinned by
`tests/regression/test_open_findings_m6_regression.py`.

## Typed-literal hex validation (2026-07-09, M7)

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

## Unterminated free-form string literal warning (2026-07-08, H7)

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

## Pure/Cython parity audit (2026-07-08)

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

## Other dated remarks

* TokenType count: `TokenType(IntEnum)` — 244 members (`len(TokenType)`, verified 2026-10-15; `COMMENT_ENTRY` is last). Using `IntEnum` rather than plain `Enum`
* Cython acceleration: **Pure Python is the default backend (since 2026-10-15).** The accelerators
* Typed literals heading: **Typed literals (audit 2.1).** A typed literal's token carries
* Typed literals: as the digits. Level-88 `values` keep the prefixed spelling too (`88 C VALUE X"41"` -> `values == ['X"41"']`, verified 2026-10-15). Pinned by `tests/regression/test_audit_2026_09_27.py`.
* DECIMAL-POINT IS COMMA: hands it to `PictureClause` (see [ast-models.md](../ast-models.md)). The SPECIAL-NAMES parser's old "not honored by the lexer" warning (audit H4) is gone. Pinned by `tests/regression/test_decimal_point_is_comma.py`, which
* Free-form `*>` heading text: `*>` outside a literal ends the line's code: the rest of the line becomes one `COMMENT` token (both lexers). History (2026-08-07):
* Digit-led names heading text: A digit-led word with a letter anywhere in its hyphen-joined segments (`43E00-PROD`, `22310-01-TRAITE`, `25COUNT`) is an `IDENTIFIER`, not a number. History (2026-08-21):
* Signature-drift guard (original wording): `data_clauses._data_fast_usable()` now probes the compiled helper once at import: with an empty token list the clause loop never runs, so the helper ... **Why `logger.warning` and not `warnings.warn`:** this runs at module import, so under `-W error` / `PYTHONWARNINGS=error` / a downstream pytest `filterwarnings = error` a warning would turn a stale build into an `import cobolparser` failure — inverting the guard's own purpose and leaving those users strictly worse off than the bug it fixes. Pinned by `test_import_survives_warnings_as_errors`. and the `.pyx` while missing the call site leaves the probe passing and the real call raising `TypeError` — the original bug, unguarded and unreported.
