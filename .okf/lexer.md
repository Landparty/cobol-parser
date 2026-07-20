---
type: Module
title: Lexer
description: Tokenizes COBOL source into Token objects; 236 TokenType values; optional Cython hot-path.
tags: [lexer, tokenizer, cython, token-type]
timestamp: 2026-07-09T00:00:00Z
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

`TokenType(IntEnum)` — 236 members. Using `IntEnum` rather than plain `Enum`
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

# See Also

* [preprocessing.md](preprocessing.md) — upstream fixed-format normalisation
* [parser.md](parser.md) — consumes `List[Token]` via `TokenStream`
