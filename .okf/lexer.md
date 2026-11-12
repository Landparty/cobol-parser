---
type: Module
title: Lexer
description: Tokenizes COBOL source into Token objects (CobolLexer, tokenize_cobol), the TokenType enum, literal helpers (_literals.py) and line splitting (_lines.py). Pure Python.
tags: [lexer, tokenizer, token-type]
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
text), `_lines.py` (`split_source_lines`).

The lexer is one pure-Python class. (Opt-in Cython accelerators existed until
2026-11; they were removed because a ~1.34x measured speedup did not justify
a second implementation of every hot path.)

To get started: read [Public API](#public-api), then [TokenType enum](#tokentype-enum);
the later sections are per-feature behaviour notes, each pinned by a
regression test.

## Contents

* [Public API](#public-api)
* [TokenType enum](#tokentype-enum)
* [Fixed-format column layout](#fixed-format-column-layout)
* [Line-start quote whitespace](#line-start-quote-whitespace)
* [Literal round trip (`_literals.py`)](#literal-round-trip-_literalspy)
* [DECIMAL-POINT IS COMMA](#decimal-point-is-comma)
* [Errors](#errors)
* [Warnings (non-fatal diagnostics)](#warnings-non-fatal-diagnostics)
* [Figurative constants](#figurative-constants)
* [`KEYWORDS` table](#keywords-table)
* [Free-form `*>` inline comments](#free-form--inline-comments)
* [Tokenize pipeline (`_tokenize_source`)](#tokenize-pipeline-_tokenize_source)
* [Digit-led hyphenated names](#digit-led-hyphenated-names)
* [Stray characters post-pass](#stray-characters-post-pass)
* [COPY REPLACING placeholders in names](#copy-replacing-placeholders-in-names)
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
tokens: list[Token] = lexer.tokenize()
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
a delimited identifier rather than a string (#597).

Module-level helpers also used outside the lexer:
`mask_comment_entries(source)` (blanks IDENTIFICATION comment-entry text,
same length/line breaks -- used by the COPY/REPLACE text scanners) and
`declares_decimal_point_comma(source, fixed_format=False)`.

## TokenType enum

`TokenType(IntEnum)` — 245 members (`len(TokenType)`;
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
| EXEC-only characters | `BANG`, `PIPE`, `NOT_SIGN`, `SQL_NAME_CHAR` (`#` / `@`), `STRAY_CHAR` (any other unknown character); dropped with a warning outside `EXEC ... END-EXEC` |
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

## Line-start quote whitespace

`is_line_start_quote` (whether an unterminated string could continue a
preceding VALUE clause) checks only `" \t"` before the quote, never
`str.strip()` / `isspace()`, which also accepts `\v`, `\f`, NBSP and so
classifies the same line differently. Pinned by
`tests/regression/test_normalize_line_number_preservation.py::TestLexerLineStartQuoteWhitespaceParity`.

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
not strip the delimiters: `layout/fields.py` (VALUE clauses),
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
front (the same way `declared_currency_signs` does) for `DECIMAL-POINT [IS]
COMMA`, over `_code_text()` -- the source with `*>` comments, fixed-format
comment lines and literal text blanked, so a commented-out or quoted clause
declares nothing;
the result is `CobolLexer.decimal_point_is_comma` and `_decimal_char`
(`","` or `"."`). Under it, in `read_number_from_text` (which reads
`self._decimal_char`):

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
clause. Pinned by `tests/regression/test_decimal_point_is_comma.py`.

## Errors

`LexerError` — extends `ParseError` (`cobolparser/_errors.py`). Raised for
unrecognised characters or malformed string literals.

## Warnings (non-fatal diagnostics)

`CobolLexer` also collects a `self.warnings: list[str]`, reset at the top of
each `tokenize()` call (so repeated `tokenize()` calls never duplicate
warnings), exposed via:

```python
lexer = CobolLexer(text, free_form=True)
tokens = lexer.tokenize()
lexer.has_warnings()   # -> bool
lexer.get_warnings()   # -> list[str]
```

Pinned by
`tests/regression/test_audit_2026_08_12_core.py::TestPB5LexerWarningsReset`.

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
set is one class attribute that `read_word_from_text` consults via `self.`,
a mutable copy of `cobolparser._vocabulary.FIGURATIVE_CONSTANTS_WITH_ALL`.

**`cobolparser/_vocabulary.py`** (layer-1 leaf) is the package's one home for
COBOL word lists: `FIGURATIVE_CANONICAL` (every spelling -> its singular),
`FIGURATIVE_CONSTANTS` (the 13 words, no `ALL`),
`FIGURATIVE_CONSTANTS_WITH_ALL`, `ZERO_WORDS`, `SPACE_WORDS`,
`HIGH_VALUE_WORDS`, `LOW_VALUE_WORDS`, `QUOTE_WORDS`, `NULL_WORDS`,
`SIGN_CONDITION_WORDS`. Parsers, layout, analyzers and generators import
these instead of spelling the words out; a module that needs a deliberate
subset builds it from them (`value_tracker`'s literal test is
`ZERO_WORDS | SPACE_WORDS | LOW_VALUE_WORDS | HIGH_VALUE_WORDS`), so the
difference is visible. Copies drifted before (some lacked `NULL` / `NULLS`).
Value tables keyed by these words (`layout/values.py`, `domains.py`,
`encoding.py`'s fill table, `ims_segment_analyzer.py`) still carry their own
per-word values.
`analysis/move_type_checker.py`,
`analysis/constraints.py` and `layout/values.py` carry their own
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
  word (`read_word_from_text` builds one word at a time), so
  a key containing a space (`"KEY IS"`, `"WITH LOCK"`, `"NO REWIND"`,
  `"NO ADVANCING"`) can never match. The single-word aliases (`"REWIND"`,
  `"ADVANCING"`, ...) remain; the parsers recognize the phrases word by word.

## Free-form `*>` inline comments

`*>` outside a literal ends the line's code: the rest of the line becomes one
`COMMENT` token. `normalize_fixed_format` strips only *whole*
comment lines, so without this the comment's words lex as code (`*` as
`MULTIPLY_OP`, `>` as `GREATER`, and `*> start at 2` yields a bogus
`IOStartStatement`; cf. `examples/cobol/shamrice/unstring.cbl:243`).

`tokenize_program_text` checks `char == "*" and
text[pos+1] == ">"` immediately before the single-character-token dispatch (so
`*` isn't read as `MULTIPLY_OP` first). The check runs after the
string-literal branch, so `*>` inside a quoted literal (`"A *> B"`) is literal
text; `**` (exponentiation) is unaffected. Statement parsers skip `COMMENT`
tokens via `skip_whitespace()` (`parsers/statements/_utils.py`). Pinned by
`tests/regression/test_inline_comment_stripping.py`.

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
original line numbers. These helpers are module-level. Pinned by
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

`tokenize_program_text`'s digit branch decides identifier-vs-numeric-literal for
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

### All-digit procedure names

A procedure name may be digits alone (`1000-0`, `0100-0200`). The digit
branch above still reads `1000-0` as `1000` `-` `0` (no letter), so the
`_post_tokenize` pass `_merge_numeric_procedure_names()` joins digit runs glued by hyphens, with no gap between the tokens,
into one `IDENTIFIER` when nothing but a period, comma, semicolon or line
end abuts the last run. `1000-0.5` and anything inside `EXEC ... END-EXEC`
(SQL `10-5` is arithmetic) are left alone. Before 2026-10-29 the paragraph
header and every PERFORM / GO TO of it were dropped as unparsed tokens.
Pinned by `tests/regression/test_all_digit_procedure_names.py`. Same
trade-off as above: a space-free `COMPUTE X = 10-1` is one word.

## Stray characters post-pass

No character fails a file. `!`, `|`, `¬`, `#`, `@` (tokens `BANG`, `PIPE`,
`NOT_SIGN`, `SQL_NAME_CHAR`) and every other character the lexer does not
know (`STRAY_CHAR`: `¦`, `§`, `?`, `{`, box-drawing `│`, a codepage-mangled
glyph, a control byte) are kept as tokens inside `EXEC ... END-EXEC` and
dropped elsewhere, with a warning.

`CobolLexer._drop_stray_chars()` runs at the end of `tokenize()` (one linear
scan). Outside an
EXEC token span:

- a `#` / `@` declared as a SPECIAL-NAMES currency symbol is retyped
  `CURRENCY` inside a PICTURE string (the run of abutting tokens right
  after PIC / PICTURE [IS]);
- a `#` / `@` that abuts a word (same line, no gap: `WS-#CPT`, `@ADDR`) is
  glued into one IDENTIFIER with it, so every reference stays one name --
  also when it is the declared currency symbol (`WS-#N` with `PICTURE
  SYMBOL '#'`, #809; it used to be cut to `WS-`); outside a PICTURE string
  an unglued currency symbol is still retyped `CURRENCY`;
  warning `Non-standard character '#' read as part of a data name (N
  occurrences, lines ...)`;
- any other stray token is dropped; warning `Ignored invalid character '|'
  (N occurrences, lines 68, 70, ... and K more)`.

One warning per distinct character (first 10 line numbers), surfaced as
`Lexer warning: ...` in `ParseResult.warnings`. They used to be hard
`Invalid character` LexerErrors, which cost a whole program over a
box-drawing comment whose `*` was not in column 7 (tab-shifted, no sequence
area) or a `#` in a data name; the warning keeps junk such as
`MOVE BOGUS !!! TO WS-A` from parsing with zero diagnostics. The only hard
lexer error left is an unterminated literal. Pinned by
`tests/regression/test_stray_characters_never_fail_the_file.py` and
`tests/regression/test_stray_sql_chars.py`.

`#` and `@` are letters of a DB2 ordinary identifier (`ACCT#`, `@ADDR`,
`T#TAB`), like `$`. `CobolLexer._merge_exec_name_chars()` runs first: inside
an EXEC block it glues each `SQL_NAME_CHAR` or `CURRENCY` token to the words
it abuts (same line, no gap) into one IDENTIFIER, so `SELECT ACCT#` and
`X$Y` round-trip unchanged. Pinned by `tests/regression/test_sql_name_chars.py`.

## COPY REPLACING placeholders in names

Template copybooks spell names with a placeholder the including program
replaces: `01 (9999-)MOD-DTTX0F.` for `COPY X REPLACING ==(9999-)== BY
==WS-==`, or `05 :PFX:-CODE`. `CobolLexer._merge_template_placeholders()`
runs in `_post_tokenize()` after `_merge_exec_name_chars()` and before
`_drop_stray_chars()`: outside EXEC, a run of abutting tokens (same line, no
gap, not crossing `.` `,` `;` or a literal) whose text fully matches
`_TEMPLATE_NAME_RE` becomes one IDENTIFIER spelled as written. A `(...)`
placeholder must hold a letter or `-` and have name text after it, or a
name ending in `-` before it (`WS-(SFX)`); `:TAG:` may stand alone. A condition's own parentheses abutting the name
(`IF (FLG-(TESTVAR1)-NOT-OK` / `OR FLG-(TESTVAR1)-BLANK)`, AWS CardDemo's
`CSSETATY.cpy`) are peeled off the run, fewest first, by
`_template_name_span`, so `WS-(SFX)` keeps its `)`. A reserved word the
`(` abuts (`NOT(`, `AND(`, `OR(`, `UNTIL(`) is peeled off the front of the
run first (`_is_reserved_word`, #814), so `IF NOT(FLG-(T)-OK)` lexes like
`IF NOT (FLG-(T)-OK)`. So
`PIC -(5)9`, `TAB(I)`, `B(1:2)` and `A-(4)` are untouched; runs right after
PIC / PICTURE [IS] are skipped. Before, each item of such a copybook parsed
as `ANONYMOUS-n-m`. After `expand_copybooks` applies REPLACING there is no
placeholder left. Pinned by
`tests/regression/test_copybook_template_placeholders.py`.

## Line splitting (`_lines.py`)

`split_source_lines(text, keepends=False) -> list[str]` splits on `\n` /
`\r\n` / `\r` only and is otherwise `str.splitlines()`-shaped (no trailing
empty line, `[]` for `""`). `CobolLexer.__init__` (`self.lines`), the
fixed-format placeholder walk, `_code_text`, `mask_comment_entries` and
`_tokenize_source` all split through it, never `str.splitlines()`: the latter
also breaks on form feed / NEL / U+2028 etc., which shifts every later
token's line number by one. See [preprocessing.md](preprocessing.md).

## `&` literal concatenation

`&` is never a token (the lexer skips it as a separator), but
`tokenize()` ends with
`CobolLexer._post_tokenize()`, which runs `_merge_concatenated_literals()`,
`_merge_template_placeholders()`, `_drop_stray_chars()`, `_retype_operator_currency_symbols()` (see
[Declared currency symbols](#declared-currency-symbols)), then
`_retype_legacy_verb_data_names()`, and rewrites `self.tokens` in place. The last pass (#525) retypes the legacy
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
literals never); a typed result's `raw_value` is rebuilt (`X"C1C2"`). A
basic and an `X` literal are both alphanumeric and are joined too
(`_mixed_alphanumeric`, #479): `'AB' & X'0102'` becomes one literal whose
`value` holds each hex part's bytes as Latin-1 characters (`AB\x01\x02`; so
`'AB' & X'C1C2'` reads `ABÁÂ`, not the `ABAB` it is in EBCDIC -- the
convention a lone `X'..'` cell follows too) and
whose `raw_value` is every part's source joined with ` & `
(`"AB" & X'0102'`, a basic part re-quoted with `"`; not one quoted literal,
so a caller reading a prefix off it must treat it as a concatenation), which the record-image
generator reads back as bytes plus characters. The
merged token keeps the first literal's location; NEWLINEs between the
parts follow it. Fast path: no `&` in any line -> no work. Pinned by
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
once per `tokenize()` on the free-form path) maps each IDENTIFICATION DIVISION
line holding comment-entry text to the offset where it starts;
`_comment_entry_line_tokens()` lexes the paragraph name normally and emits
the rest of the line as one `COMMENT_ENTRY` token, verbatim. Area rules
match the IDENTIFICATION parser's: a paragraph name at or left of the
`IDENTIFICATION DIVISION` header's indentation (Area A) also claims every
following line indented deeper (Area B) -- NIST OBNC1M's phony program
included -- up to the next Area A line, or to an Area B line opening with
`COPY`, `EJECT`, `SKIP1-3`, or `TITLE` followed by its literal
(`_COMMENT_ENTRY_END_RE`; a `TITLE` with no literal, such as `TITLE PAGE IS
PRINTED FIRST.`, is a line of REMARKS prose and stays in the entry: IBM processes
those wherever they are written, so `DATE-COMPILED.` over an indented `COPY
E1MDFRE1.` now copies the member instead of hiding its ENVIRONMENT and DATA
DIVISIONs); one indented deeper claims only its own line. `CobolParser`
warns when a unit has no DATA DIVISION but a comment-entry holds DATA
DIVISION / storage-section text (`_warn_data_without_data_division`). The whole scan is skipped unless one multiline regex search finds
a comment-entry paragraph name at a line start. The fixed-format
(`free_form=False`) path does not do this; the parser always lexes normalized
free-form text. `tests/regression/test_comment_entry_verbatim.py`.

## Declared currency symbols

`CURRENCY SIGN IS '£'` / `CURRENCY SIGN IS 'EUR' WITH PICTURE SYMBOL '#'`
makes the symbol a PICTURE editing character like `$`. `__init__`
collects the declared symbols (`declared_currency_signs(source)`, one regex
scan; digits, spaces and the letters A B C D E G N P R S U V X Z are never
symbols) and keeps the non-letters in `self._currency_symbols`; in `tokenize_program_text` a
character that would otherwise be a dropped stray character is emitted
as a `CURRENCY` token when it is declared. Characters that already lex as
something (`& ! | < > :`, letters) are not rerouted. Without the declaration,
every `£` in `PIC £££9.99` is dropped with a warning. See [ast-models.md](ast-models.md) for
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
