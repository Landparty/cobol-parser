---
type: Module
title: Lexer
description: Tokenizes COBOL source into Token objects (CobolLexer, tokenize_cobol), the TokenType enum, literal helpers (_literals.py), line splitting (_lines.py), and the opt-in Cython fast path (_lexer_fast.pyx, gated by _accel.py / COBOLPARSER_ACCEL=1).
tags: [lexer, tokenizer, cython, token-type]
timestamp: 2026-10-15T00:00:00Z
---

# Lexer

`cobolparser/lexer.py` — `CobolLexer` converts COBOL text into `list[Token]`.
The parser always lexes **normalized free-form** text (`free_form=True`):
`normalize_fixed_format` (see [preprocessing.md](preprocessing.md)) strips
fixed-format comment lines (column 7 `*`/`/`) and the sequence/identification
areas **before** the lexer sees them. `tokenize_cobol()` (and CLI `tokenize`)
runs the same normalize-then-lex pipeline.

Entry points: `CobolLexer(source, filename, dialect, free_form).tokenize()`,
`tokenize_cobol(source, ...)`, and the private `_tokenize_source()` the CLI
uses. Supporting modules: `_literals.py` (re-emitting / reading back literal
text), `_lines.py` (`split_source_lines`), `_accel.py` (the accelerator
switch), `_lexer_fast.pyx` (Cython subclass).

**Pure Python is the default backend.** `CobolLexer` is `_CobolLexerPure`
unless `COBOLPARSER_ACCEL=1` is set at import time *and* the compiled
`cobolparser._lexer_fast` imports; see [Cython acceleration](#cython-acceleration).
Any lexing change must be made in both `lexer.py` and `_lexer_fast.pyx` when
it touches one of the overridden methods (table below).

To get started: read [Public API](#public-api), then [TokenType enum](#tokentype-enum);
the later sections are per-feature behaviour notes, each pinned by a
regression test.

## Contents

* [Public API](#public-api)
* [TokenType enum](#tokentype-enum)
* [Fixed-format column layout](#fixed-format-column-layout)
* [Cython acceleration](#cython-acceleration)
* [Literal round trip (`_literals.py`)](#literal-round-trip-_literalspy)
* [DECIMAL-POINT IS COMMA](#decimal-point-is-comma)
* [Errors](#errors)
* [Warnings (non-fatal diagnostics)](#warnings-non-fatal-diagnostics)
* [Figurative constants](#figurative-constants)
* [`KEYWORDS` table](#keywords-table)
* [Free-form `*>` inline comments](#free-form--inline-comments)
* [Tokenize pipeline (`_tokenize_source`)](#tokenize-pipeline-_tokenize_source)
* [Digit-led hyphenated names](#digit-led-hyphenated-names)
* [Stray SQL characters post-pass](#stray-sql-characters-post-pass)
* [Line splitting (`_lines.py`)](#line-splitting-_linespy)
* [`&` literal concatenation](#-literal-concatenation)
* [IDENTIFICATION DIVISION comment-entries](#identification-division-comment-entries)
* [Declared currency symbols](#declared-currency-symbols)
* [See also](#see-also)

## Public API

```python
from cobolparser import CobolLexer, Token, TokenType, tokenize_cobol, LexerError

lexer = CobolLexer(source, filename="<string>",
                   dialect=DialectType.IBM_ENTERPRISE, free_form=False)
tokens: list[Token] = lexer.tokenize()     # also lexer.get_tokens()
lexer.get_errors() / lexer.has_errors()    # list[LexerError]
lexer.get_warnings() / lexer.has_warnings()
lexer.decimal_point_is_comma               # bool, from SPECIAL-NAMES

tokens = tokenize_cobol(source, filename="<string>", dialect=...,
                        free_form=False, keep_comments=True)
# raises the first LexerError; discards warnings
```

`Token` is a `@dataclass(slots=True)`: `type: TokenType`, `value: str`,
`location: SourceLocation`, `raw_value: str | None = None` (the source
spelling when it differs from `value` -- typed literals, `DECIMAL-POINT IS
COMMA` numbers, merged `&` literals), and `quote: str | None = None` (the
delimiter a `STRING_LITERAL` was written with, `'` or `"`; excluded from
equality and repr; None for a continued multi-line literal or a merged `&`
literal). `STRING_LITERAL` `value`s arrive **decoded** (delimiters stripped,
doubled delimiter collapsed). `quote` exists for embedded SQL, where `"X"` is
a delimited identifier rather than a string (#597); the Cython
`_try_single_line_string` sets it too.

Module-level helpers also used outside the lexer:
`mask_comment_entries(source)` (blanks IDENTIFICATION comment-entry text,
same length/line breaks -- used by the COPY/REPLACE text scanners) and
`declares_decimal_point_comma(source, fixed_format=False)`.

## TokenType enum

`TokenType(IntEnum)` — 244 members (`len(TokenType)`;
`COMMENT_ENTRY` is last). Using `IntEnum` rather than plain `Enum`
makes hot-path membership tests and `hash()` lookups significantly cheaper.

Major groups:

| Group | Examples |
|-------|---------|
| Literals | `STRING_LITERAL`, `NUMERIC_LITERAL`, `BOOLEAN_LITERAL`, `FIGURATIVE_CONSTANT`, `LEVEL_NUMBER` |
| Identifiers | `IDENTIFIER`, `QUALIFIED_IDENTIFIER` |
| Division keywords | `IDENTIFICATION_DIVISION`, `ENVIRONMENT_DIVISION`, `DATA_DIVISION`, `PROCEDURE_DIVISION` |
| Paragraph / section keywords | `PROGRAM_ID`, `AUTHOR`, `CONFIGURATION_SECTION`, `FILE_SECTION`, `WORKING_STORAGE_SECTION`, `LOCAL_STORAGE_SECTION`, `LINKAGE_SECTION`, … |
| File description | `FD`, `SD` |
| FILE-CONTROL | `ASSIGN_TO`, `ORGANIZATION`, `ACCESS`, `RECORD`, `KEY`, `ALTERNATE`, `DUPLICATES`, … |
| Statement verbs | `MOVE`, `PERFORM`, `CALL`, `IF`, `EVALUATE`, `COMPUTE`, `ADD`, `SUBTRACT`, … |
| Operators | `EQUAL`, `LESS`, `GREATER`, `PLUS`, `MINUS`, `MULTIPLY_OP`, `DIVIDE_OP`, `POWER`, `AND`, `OR`, `NOT`, … |
| Punctuation | `PERIOD`, `COMMA`, `SEMICOLON`, `COLON`, `LEFT_PAREN`, `RIGHT_PAREN` |
| Embedded EXEC | `EXEC`, `SQL`, `CICS`, `END_EXEC` (there are no fused `EXEC_SQL`/`EXEC_CICS`/`EXEC_IMS` tokens; the EXEC parsers read the word after `EXEC`) |
| EXEC-SQL-only characters | `BANG`, `PIPE`, `NOT_SIGN` (error outside `EXEC ... END-EXEC`) |
| Layout / other | `NEWLINE`, `EOF`, `COMMENT`, `COMMENT_ENTRY`, `CURRENCY` |

## Fixed-format column layout

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

## Cython acceleration

**Pure Python is the default backend.** The accelerators
are an opt-in, chosen by one environment variable, `COBOLPARSER_ACCEL=1`
(`1`/`true`/`yes`/`on`, case-insensitive), read at both ends:

* **build time** — `setup.py` compiles the three extensions only when it is
  set, so a stock `pip install .` builds nothing and needs no compiler.
  `COBOLPARSER_SKIP_EXT=1` (the old opt-out) is still honoured and wins.
* **import time** — `cobolparser/_accel.py`'s `accelerators_enabled()` gates
  each fast-path import site (`lexer.py`, `preprocess/__init__.py`,
  `parsers/divisions/data_clauses.py`). An installed `.so` is ignored without
  the variable, so a stale or mismatched binary cannot change what a default
  install does. It reads `os.environ` on every call (not cached), so a test can
  flip the variable and `importlib.reload` a module that owns a fast path.
  `_accel.py` has zero internal imports; `setup.py` reads the variable itself.

The PyPI wheels still ship compiled (`[tool.cibuildwheel] environment`), so
wheel users only need the variable at run time.

```bash
# Build in-place (development); pre-generated .c files are checked in, so
# only a C compiler is needed (Cython, via the [fast] extra, re-cythonizes)
COBOLPARSER_ACCEL=1 python setup.py build_ext --inplace

# Run with them (the suite too: this is how the fast paths get exercised)
COBOLPARSER_ACCEL=1 python -m pytest tests/ --no-cov
```

Three optional extension modules live alongside the pure-Python sources:

| Module | Overrides (pure-Python file) | Accelerated symbols |
|--------|------------------------------|---------------------|
| `cobolparser/_lexer_fast.pyx` | `cobolparser/lexer.py` (`_CobolLexerPure`) | `check_division_header`, `read_word_from_text`, `tokenize_program_text`, `_try_single_line_string`, `read_number_from_text`, `tokenize` |
| `cobolparser/_preprocess_fast.pyx` | `cobolparser/preprocess/__init__.py` | `normalize_fixed_format` |
| `cobolparser/_data_fast.pyx` | `cobolparser/parsers/divisions/data_clauses.py` | `parse_data_item_clauses_fast` (the `.pyx` also defines `parse_picture_clause_fast`, which nothing imports) |

`_lexer_fast.CobolLexer` subclasses `_CobolLexerPure` and inherits
everything else (`KEYWORDS`, `FIGURATIVE_CONSTANTS`, `_post_tokenize` and its
passes, the warning accessors), so a change to those reaches both paths with
no `.pyx`/`.c` regeneration. A change to an overridden method has no shared
helper to lean on: make it in both files and regenerate the checked-in `.c`.

### Activation

Each host module swaps the fast symbol in only under the
switch, and stays pure silently when the extension is absent:

```python
# lexer.py (bottom of file)
CobolLexer = _CobolLexerPure
if accelerators_enabled():
    try:
        from cobolparser._lexer_fast import CobolLexer
    except ImportError:
        pass
```

`preprocess/__init__.py` (`normalize_fixed_format`) does the same;
`parsers/divisions/data_clauses.py` raises `ImportError` itself when the
switch is off and then runs the signature probe below.

### Typed locals must not narrow what the pure path accepts

When C-typing a mirror, only type values whose range the pure path also
bounds (loop indexes, positions) -- never a value read out of the source.
`parse_data_item_clauses_fast` holds the OCCURS min/max counts in
`cdef object`, not `cdef int`: a count past 2**31-1 would raise
`OverflowError`, which escapes the `(TypeError, ValueError)` guards mirrored
from the pure walker, and the division loop would recover by abandoning the
whole DATA DIVISION where the pure path keeps the count.

### Signature-drift guard (`_data_fast`)

`ImportError` is not the only way the fast path can be wrong. The extension
is compiled separately from its caller, so the binary can be *older* than the
Python module that calls it — a stale in-place `.so`, a cached `build/` tree,
or an installed wheel shadowing the source tree. `data_clauses.parse_data_item`
calls `parse_data_item_clauses_fast` with `_DATA_FAST_ARG_COUNT` (20)
positional arguments; an arity mismatch raises `TypeError` in the middle of
every data-description entry, and the division loop then abandons the
division, leaving a near-empty AST.

`data_clauses._data_fast_usable()` probes the compiled helper once at
import: with an empty token list the clause loop never runs, so the helper
returns its `pos` argument without reading any other parameter (hence `None`
placeholders for the rest). On mismatch the fast path is disabled
(`_HAS_DATA_FAST = False`, helper set to `None`) and `logger.warning` names the
rebuild. A *missing* extension stays silent — that is a normal pure-Python
install, not a misconfiguration.

**Why `logger.warning` and not `warnings.warn`:** this runs at module import,
so under `-W error` / `PYTHONWARNINGS=error` / a downstream pytest
`filterwarnings = error` a warning would turn a stale build into an
`import cobolparser` failure — inverting the guard's own purpose. Pinned by
`test_import_survives_warnings_as_errors`.

Arity is the drift that actually happens (parameters get appended as the fast
path grows); a same-arity extension with reordered parameters is not detected,
and nothing cheap would. When adding a parameter to
`parse_data_item_clauses_fast`, update `_DATA_FAST_ARG_COUNT` alongside the
call site. `_DATA_FAST_ARG_COUNT` is a *third* copy of the arity (after the
`.pyx` and the literal call), so two tests
(`tests/regression/test_data_fast_signature_drift.py`) pin it from both sides: one against
the compiled extension's real signature, one parsing `data_clauses.py`'s AST to
count the literal call's arguments. Without the second, bumping the constant
and the `.pyx` while missing the call site leaves the probe passing and the
real call raising `TypeError`, unguarded and unreported.

The guard protects against stale *builds*, not against a stale checked-in `.c`;
keeping each `.c` in sync with its `.pyx` is a separate obligation.

### Pure/Cython parity

Decisions the two lexers both make must use the same character classes.
`is_line_start_quote` (whether an unterminated string could continue a
preceding VALUE clause) checks only `" \t"` before the quote in both lexers,
never `str.strip()` / `isspace()`, which also accepts `\v`, `\f`, NBSP and so
classifies the same line differently. Pinned by
`tests/regression/test_normalize_line_number_preservation.py::TestLexerLineStartQuoteWhitespaceParity`.

### Performance

Approximately **~3× lexer throughput** over pure Python
(stated in `README.md`). Preprocessor and DATA DIVISION gains are comparable
but are not separately benchmarked in the checked-in docs.

## Literal round trip (`_literals.py`)

`_literals.py` (zero internal imports) is the one place literal text is
re-emitted and read back:

| Symbol | Does |
|--------|------|
| `quote_literal(value)` | decoded content -> `"..."` literal, each embedded `"` doubled |
| `unquote_literal(text)` | inverse: strips the delimiters *and* collapses the doubled delimiter (`"A""B"` -> `A"B`); non-literal text comes back stripped |
| `typed_literal_content(text)` | what a typed literal stands for (below); `None` if untyped |
| `is_quoted_literal(text)` | whether *text* as a whole is one quoted or typed literal (never a data name) -- used by `program_fixtures`, `field_lineage` |
| `QUOTED_LITERAL_RE` | a quoted literal inside operand/condition text, typed prefix included only when no word character precedes it (so `WS-X"..."` keeps its `X`) -- used by `unused_variables` |

Any consumer reading a re-emitted literal back must use `unquote_literal`,
not strip the delimiters: `generators/data/layout.py` (VALUE clauses),
`analysis/constraints.py` (branch witnesses) and `analysis/const_fold.py`
(MOVE sources) all do. Delimiter-only stripping makes `VALUE "A""B"` generate
`A""B` and `MOVE '"'` fold to two quote characters. Pinned by
`tests/regression/test_doubled_quote_literal_values.py`.

**Typed literals.** A typed literal's token carries
its prefixed source text in `raw_value` (`X"4142"`); `value` is the
undecoded content between the delimiters (`4142`). Anything that re-emits one
as COBOL must use `raw_value`, not `quote_literal(value)`, or the two-byte hex
literal becomes the four-character text literal `"4142"`. MOVE/DISPLAY and
the VALUE clause (`data_clauses.literal_source()`) all do. The reading side is
`_literals.typed_literal_content()`: `X` decodes to its bytes' code points
(Latin-1, so `X"4142"` is `AB`), `NX` as UTF-16BE, `UX` as UTF-8, `Z` gains
its NUL, `N`/`G`/`U` are their content; hex that does not decode comes back
as the digits. Level-88 `values` keep the prefixed spelling too (`88 C VALUE
X"41"` -> `values == ['X"41"']`). Pinned by
`tests/regression/test_audit_2026_09_27.py`.

## DECIMAL-POINT IS COMMA

`declares_decimal_point_comma(source, fixed_format)` scans the whole source up
front (the same way `_declared_currency_symbols` does) for `DECIMAL-POINT [IS]
COMMA`, over `_code_text()` -- the source with `*>` comments, fixed-format
comment lines and literal text blanked, so a commented-out or quoted clause
declares nothing;
the result is `CobolLexer.decimal_point_is_comma` and `_decimal_char`
(`","` or `"."`). Under it, in **both** `read_number_from_text`s (pure and
`_lexer_fast.pyx`, which reads `self._decimal_char`):

* a `,` between digits is the decimal point: `2,75` is one
  `NUMERIC_LITERAL` whose `value` is the canonical `2.75` (every consumer
  parses it as a number: `Decimal`, const-fold, generators) and whose
  `raw_value` is the source text `2,75` -- the typed-literal convention;
* `.` is not a decimal point: `1.5` lexes `1` PERIOD `5`;
* a leading-decimal literal is `,5`, recognised only after a space/tab or
  at line start -- `A,5` keeps the comma a separator; a comma followed by a
  space (`MOVE A, B`) is always a separator.

The scope is the whole compilation unit (nested programs inherit the
containing program's SPECIAL-NAMES; stacked programs that disagree are not
modelled). `CobolParser` copies the flag onto itself
(`decimal_point_is_comma`, reset per `parse()`), and the DATA DIVISION
hands it to `PictureClause` (see [ast-models.md](ast-models.md)). The
SPECIAL-NAMES parser emits no "not honored by the lexer" warning for the
clause. Pinned by `tests/regression/test_decimal_point_is_comma.py`, which
runs every lexer case against both lexers.

## Errors

`LexerError` — extends `ParseError` (`cobolparser/_errors.py`). Raised for
unrecognised characters or malformed string literals.

## Warnings (non-fatal diagnostics)

`CobolLexer` (both the pure-Python `_CobolLexerPure` and the `_lexer_fast`
Cython subclass) also collects a `self.warnings: list[str]`, reset at the
top of each `tokenize()` call in both lexers (so repeated `tokenize()` calls
never duplicate warnings), exposed via:

```python
lexer = CobolLexer(text, free_form=True)
tokens = lexer.tokenize()
lexer.has_warnings()   # -> bool
lexer.get_warnings()   # -> list[str]
```

Pinned by
`tests/regression/test_audit_2026_08_12_core.py::TestPB5LexerWarningsReset`,
which exercises both paths.

`CobolParser.parse()` forwards every lexer warning into `ParseResult.warnings`
(prefixed `"Lexer warning: "`) after the `lexer.has_errors()` check.
`tokenize_cobol()` and CLI `tokenize` discard warnings; only
`_tokenize_source()` returns them (third tuple element).

Producers:

* **Unterminated string literal (free-form).** `parse_cobol()` always lexes
  with `free_form=True` after normalization, and the free-form path treats a
  string literal that runs to end-of-line without a closing quote as closed
  at the line boundary. That is intentional — a lone quote can legitimately
  appear inside a free-form comment (e.g. `COMPILER"S`), so a hard
  `LexerError` would break valid input — but it is reported:
  `"Unterminated string literal at line N, column C: closed at end of line
  instead of a matching quote"`. Pinned by
  `tests/regression/test_open_findings_high_regressions.py::TestH7UnterminatedStringWarns`.
* **Typed-literal hex content.** `read_prefixed_literal_from_text` — which
  handles typed literals (`X'..'`, `N'..'`, `G'..'`, `NX'..'`) — validates hex
  content for the `X'..'`/`NX'..'` prefixes: `X'ABC'` (odd number of hex
  digits — each byte needs two) and `X'ZZ'` (non-hex characters) each append
  a warning. `G'..'`/`N'..'` literals are not validated — they have
  codepage-dependent validity rules — and neither form is decoded to actual
  bytes/characters at lex time. Pinned by
  `tests/regression/test_open_findings_medium_regressions.py::TestM7TypedLiteralHexValidation`.

## Figurative constants

`FIGURATIVE_CONSTANTS` (`ALL`, `SPACE(S)`, `ZERO(S|ES)`, `HIGH-/LOW-VALUE(S)`,
`QUOTE(S)`, `NULL`, `NULLS`) lex as `FIGURATIVE_CONSTANT`. `NULL`/`NULLS` are
the `VALUE` of `USAGE POINTER` / `PROCEDURE-POINTER` / `FUNCTION-POINTER`
items and the operand of `SET ptr TO NULL` / `IF ptr = NULL`; lexed as
`IDENTIFIER` they would be indistinguishable from a data-name reference. The
set is one class attribute that `read_word_from_text` and `read_identifier`
both consult via `self.`, so `_lexer_fast` (which does not redefine it) needs
no regeneration when it changes. `analysis/move_type_checker.py`,
`analysis/constraints.py` and `generators/data/values.py` carry their own
`NULL`/`NULLS` lists that must agree with it. Pinned by
`tests/regression/test_null_pointer_value_clause.py` and
`tests/unit/test_lexer.py::TestCobolLexerFigurativeConstants::test_null_figurative_constants`.

## `KEYWORDS` table

`CobolLexer.KEYWORDS` (186 entries) holds only single words that some parser
consumes. Two rules keep it that way; comments at the removal sites say why,
so entries are not re-added for "completeness":

* **No keyword without a consumer.** An entry mapped to a `TokenType` no
  parser consumes never matches real syntax and only steals a legitimately
  named data item / paragraph / condition-name, silently turning it into an
  `ANONYMOUS-N` item or an empty paragraph with `result.success` still `True`.
  So these lex as plain `IDENTIFIER`s: `FILE-STATUS`, `RECORD-DELIMITER`,
  `READ-ONLY` (real syntax writes two words, and the SELECT clause parsers in
  `environment_select.py` dispatch on the leading `FILE`/`RECORD`/`READ` and
  read the second word as text); `END-SET`, `OTHERWISE` (not reserved: SET
  has no scope terminator, EVALUATE's default is `WHEN OTHER`); `EOF`,
  `END-OF-FILE` (not reserved; they are the conventional names of a
  programmer-defined AT END flag / level-88, cf. `IF END-OF-FILE` in
  `parsers/statements/_conditions.py`'s docstring). Pinned by
  `tests/regression/test_dead_keyword_removal.py`.
* **No multi-word keys.** `KEYWORDS` is only ever consulted with a *single*
  word (`read_word_from_text`/`read_identifier` build one word at a time), so
  a key containing a space (`"KEY IS"`, `"WITH LOCK"`, `"NO REWIND"`,
  `"NO ADVANCING"`) can never match. The single-word aliases (`"REWIND"`,
  `"ADVANCING"`, ...) remain; the parsers recognize the phrases word by word.

`_lexer_fast.pyx` consults the inherited `self.KEYWORDS` dict, so a change to
it applies to both lexers with no regeneration.

## Free-form `*>` inline comments

`*>` outside a literal ends the line's code: the rest of the line becomes one
`COMMENT` token (both lexers). `normalize_fixed_format` strips only *whole*
comment lines, so without this the comment's words lex as code (`*` as
`MULTIPLY_OP`, `>` as `GREATER`, and `*> start at 2` yields a bogus
`IOStartStatement`; cf. `examples/cobol/shamrice/unstring.cbl:243`).

`tokenize_program_text` (pure and `_lexer_fast.pyx`) checks `char == "*" and
text[pos+1] == ">"` immediately before the single-character-token dispatch (so
`*` isn't read as `MULTIPLY_OP` first). The check runs after the
string-literal branch, so `*>` inside a quoted literal (`"A *> B"`) is literal
text; `**` (exponentiation) is unaffected. Statement parsers skip `COMMENT`
tokens via `skip_whitespace()` (`parsers/statements/_utils.py`). Pinned by
`tests/regression/test_inline_comment_stripping.py`, including a pure/Cython
parity check.

## Tokenize pipeline (`_tokenize_source`)

`tokenize_cobol()` and CLI `tokenize` do not use the lexer's own
fixed-format handler (`free_form=False`): both route fixed-format
source through `normalize_fixed_format` + `free_form=True` lexing — the
exact path `parse_cobol()` uses — via the shared `_tokenize_source()`
helper in `lexer.py` (its fixed-or-free verdict comes from
`preprocess.source_format.detect_fixed_format`, the same detector
`parse_cobol()` uses), so the two pipelines agree on every non-COMMENT
token (count, values, line numbers). Comment lines are not lost:
`_fixed_format_comment_tokens()` captures them during normalization and
`_merge_comment_tokens()` re-emits them as `COMMENT` tokens at their
original line numbers. These helpers are module-level, with no
`_lexer_fast.pyx` / `_preprocess_fast.pyx` mirror. Pinned by
`tests/regression/test_open_findings_m6_regression.py`.

* **Normalization warnings.** `_tokenize_source` passes `warnings=` to its
  `normalize_fixed_format` calls, so column-73+ overflow diagnostics (see
  [preprocessing.md](preprocessing.md)) are prepended to the returned
  `(tokens, errors, warnings)` tuple's third element, ahead of the lexer's
  own `get_warnings()`; the unterminated-literal retry lives in
  `preprocess.source_format.normalize_with_recovery`. Both public callers
  discard this element: CLI `tokenize` deliberately (best-effort token dump),
  and `tokenize_cobol()` returns only the token list -- so only a direct
  `_tokenize_source()` caller sees these warnings.
* **`preprocess_fixed`.** The normalization guard is `if not free_form or
  preprocess_fixed:` — an explicit True wins over `free_form`, matching
  `parse_cobol`; an explicit False never normalizes (`CobolParser` takes the
  same `preprocess_fixed` parameter; see [preprocessing.md](preprocessing.md)).
  Pinned by `tests/regression/test_tagged_sequence_area_detection.py`.
* **`debug_lines` (#334).** `_tokenize_source(..., debug_lines=True)`
  normalizes with `debug_lines_as_comments=False`, and
  `_fixed_format_comment_tokens(..., debug_lines_as_comments=False)` then
  leaves `D`/`d` lines out of the recovered COMMENT tokens (they are code).
  `tokenize --debug-lines` uses it. See [preprocessing.md](preprocessing.md).
* **Indicator parity with `normalize_fixed_format`.**
  `_fixed_format_comment_tokens` re-scans the physical lines and must
  recognise every indicator `normalize_fixed_format` blanks (`*`, `/`,
  `D`/`d`, and `V`/`v` under `version_tag_lines_as_comments`): the pairing
  between blank normalized lines and placeholder-producing physical lines is
  1:1, and one missing indicator shifts every later comment to the wrong
  line and drops that line's text. Pinned by
  `tests/regression/test_version_tag_line_handling.py::TestVersionTagCommentTokenPreservation`.

## Digit-led hyphenated names

A digit-led word with a letter anywhere in its hyphen-joined segments
(`43E00-PROD`, `22310-01-TRAITE`, `25COUNT`) is an `IDENTIFIER`, not a
number.

`tokenize_program_text`'s digit branch (identical logic in `lexer.py` and
`_lexer_fast.pyx`, no shared helper) decides identifier-vs-numeric-literal for
a token starting with a digit. A one-segment lookahead is not enough:
`43E00-PROD`'s first segment looks like scientific notation, and
`22310-01-TRAITE`'s second segment is all digits. So the lookahead skips past
any matched E-exponent shape, then walks further hyphen-joined segments (each
a digit run or a letter run) for a letter anywhere in the rest of the word;
that `has_alpha` result is ORed with the one-hop check (still needed for
no-hyphen shapes like `25COUNT`/`45A`). The segment scan stops at the first
letter found — the answer is final there, and `read_word_from_text` re-scans
the whole word anyway. Plain scientific-notation literals with no trailing
hyphen segment (`5E10`, `5E+5`, `5E-3`, `1.5E10`) stay numeric — pinned by
`tests/regression/test_real_corpus_parse_failures.py::TestDigitLedHyphenatedProcedureNames`.

**Accepted trade-off, not a bug:** a *space-free* arithmetic expression whose
left operand looks like scientific notation — `COMPUTE X = 5E10-Y.` — lexes
as one `IDENTIFIER("5E10-Y")`. The character sequence is structurally
identical to a real hyphenated name, and no context-free lexer can tell the
two apart; real COBOL writes spaces around operators. Pinned as an *expected*
result by
`TestDigitLedHyphenatedProcedureNames::test_space_free_exponent_shaped_subtraction_is_an_accepted_tradeoff`.

## Stray SQL characters post-pass

`!`, `|` and `¬` (tokens `BANG`, `PIPE`, `NOT_SIGN`) are errors outside `EXEC ... END-EXEC`.

`CobolLexer._flag_stray_sql_chars()` runs at the end of `tokenize()` (both
the pure-Python and `_lexer_fast.pyx` implementations call it — the fast
path inherits the pure-Python method; one linear scan, no C mirror): every
BANG/PIPE/NOT_SIGN token *outside* an `EXEC ... END-EXEC` token span
records an `Invalid character` LexerError. The tokens exist only
so embedded EXEC SQL (`!=`, `||`, `¬=`) round-trips; accepting them
everywhere would let garbage like `MOVE BOGUS !!! TO WS-A` parse
"successfully" with zero diagnostics. Pinned by
`tests/regression/test_stray_sql_chars.py`.

## Line splitting (`_lines.py`)

`split_source_lines(text, keepends=False) -> list[str]` splits on `\n` /
`\r\n` / `\r` only and is otherwise `str.splitlines()`-shaped (no trailing
empty line, `[]` for `""`). `CobolLexer.__init__` (`self.lines`), the
fixed-format placeholder walk, `_code_text`, `mask_comment_entries` and
`_tokenize_source` all split through it, never `str.splitlines()`: the latter
also breaks on form feed / NEL / U+2028 etc., which shifts every later
token's line number by one. See [preprocessing.md](preprocessing.md).

## `&` literal concatenation

`&` is never a token (both lexers skip it as a separator), but
`tokenize()` -- pure-Python and `_lexer_fast.pyx` alike -- ends with
`CobolLexer._post_tokenize()`, which runs `_merge_concatenated_literals()`,
`_flag_stray_sql_chars()`, `_retype_operator_currency_symbols()` (see
[Declared currency symbols](#declared-currency-symbols)), then
`_retype_legacy_verb_data_names()`, and rewrites `self.tokens` in place (the
Cython path returns the same list). The last pass (#525) retypes the legacy
verbs CHAIN / NOTE / EXHIBIT / EXAMINE / TRANSFORM to IDENTIFIER, everywhere
in the source, when the program declares the word as a data name: it directly
follows a level number that starts an entry (line start or after a period)
outside the PROCEDURE DIVISION. None is reserved under IBM Enterprise COBOL,
and lexed as a verb `05 NOTE PIC X(30)` (a DCLGEN NOTE column) became a
FILLER and `MOVE x TO CHAIN` a CHAIN statement. Undeclared, they keep their
TokenTypes and stay verbs. Two consecutive STRING_LITERAL tokens
(NEWLINEs between them allowed) are joined into one when the source text
between them is whitespace + exactly one `&` + whitespace
(`_ampersand_joins` reads `self.lines` back from the second literal's
location; a fixed-format line is read in columns 8-72 only). IBM:
`"AB" & "CD"` is the literal `"ABCD"` anywhere a literal may appear;
unmerged, a VALUE clause keeps only `"AB"` and a MOVE source reads
`"AB" "CD"`. Only literals of one kind are joined
(plain, or the same `X` / `N` / `NX` / `G` / `U` prefix; `Z` and `B`
literals never); a typed result's `raw_value` is rebuilt (`X"C1C2"`). The
merged token keeps the first literal's location; NEWLINEs between the
parts follow it. Fast path: no `&` in any line -> no work. The checked-in
`_lexer_fast.c` is generated with Cython 3.3.0. Pinned by
`tests/regression/test_literal_concatenation.py`.

**`*>` comments between the parts (#389).** A floating
`*>` comment may sit between the two literals (`'AB' & *> note` / `'CD'`),
or a whole comment line may. The merge loop skips COMMENT tokens as it
skips NEWLINEs (the comment token is kept, after the merged literal), and
`_ampersand_joins` reads each *earlier* line only up to `_code_end()`: the
first `*>` outside a literal, or nothing for a fixed-format `*`/`/`
comment line. An `&` inside the comment text does not count.

## IDENTIFICATION DIVISION comment-entries

`AUTHOR.` / `INSTALLATION.` / `DATE-WRITTEN.` / `DATE-COMPILED.` /
`SECURITY.` / `REMARKS.` take a *comment-entry*: free text (any character)
up to the next Area A entry. Lexed as program text, `AUTHOR. JOHN O'BRIEN.`
would raise a spurious "Unterminated string literal" warning (the apostrophe)
and `DATE-WRITTEN. 01/02/99.` would split into `01 / 02 / 99`. So
`_comment_entry_starts(source, lines)` (module-level, pure Python, called
once per `tokenize()` on the free-form path by **both** lexers -- the
Cython `tokenize` mirrors the dispatch) maps each IDENTIFICATION DIVISION
line holding comment-entry text to the offset where it starts;
`_comment_entry_line_tokens()` lexes the paragraph name normally and emits
the rest of the line as one `COMMENT_ENTRY` token, verbatim. Area rules
match the IDENTIFICATION parser's: a paragraph name at or left of the
`IDENTIFICATION DIVISION` header's indentation (Area A) also claims every
following line indented deeper (Area B) -- NIST OBNC1M's phony program
included -- up to the next Area A line; one indented deeper claims only its
own line. The whole scan is skipped unless one multiline regex search finds
a comment-entry paragraph name at a line start. The fixed-format
(`free_form=False`) path does not do this; the parser always lexes normalized
free-form text. `tests/regression/test_comment_entry_verbatim.py` (includes
a pure/Cython parity check).

## Declared currency symbols

`CURRENCY SIGN IS '£'` / `CURRENCY SIGN IS 'EUR' WITH PICTURE SYMBOL '#'`
makes the symbol a PICTURE editing character like `$`. `__init__`
collects the declared symbols (`declared_currency_signs(source)`, one regex
scan; digits, spaces and the letters A B C D E G N P R S U V X Z are never
symbols) and keeps the non-letters in `self._currency_symbols`; in `tokenize_program_text` (both lexers) a
character that would otherwise be an "Invalid character" error is emitted
as a `CURRENCY` token when it is declared. Characters that already lex as
something (`& ! | < > :`, letters) are not rerouted. Without the declaration,
every `£` in `PIC £££9.99` is a lexer error. See [ast-models.md](ast-models.md) for
how the PictureClause sizes it. The same scan
(`declared_currency_signs(source)`) also keeps each symbol's currency string,
public as `lexer.currency_signs` (`{"#": "EUR"}`); `CobolParser` copies it to
`parser.currency_signs` for the PICTURE clauses (#491). A letter symbol
(`PICTURE SYMBOL 'F'`) is in `currency_signs` but not `_currency_symbols`: it
lexes inside the PICTURE word, and `DataItemClauseParser._picture_clause`
finds it in the pattern, case-sensitively as IBM documents the PICTURE
SYMBOL literal (`'F'` does not match `PIC fff9`), though the rest of the
PICTURE grammar here is case-insensitive.

**Operator-shaped symbols.** A declared `<`, `>` or `=` already lexes as
`LESS`/`GREATER`/`ASSIGN`, so `tokenize_program_text` cannot reroute it;
instead the `_post_tokenize` pass `_retype_operator_currency_symbols()`
retypes those tokens to `CURRENCY` only inside a PICTURE character-string
(the run of abutting same-line tokens right after `PIC`/`PICTURE` [`IS`]),
so `PIC <(3),<<<.99` keeps its picture (NIST NC108M) and `IF A < B` keeps
its operator. `tests/regression/test_currency_sign_picture_symbol.py`.

## See also

* [preprocessing.md](preprocessing.md) — upstream fixed-format normalisation
* [parser.md](parser.md) — consumes `list[Token]` via `TokenStream`
* [ast-models.md](ast-models.md) — `PictureClause` (currency symbols, DECIMAL-POINT IS COMMA)
* [history](history/lexer.md) — archived dated notes (accelerator bugs, keyword sweeps, audit findings)
