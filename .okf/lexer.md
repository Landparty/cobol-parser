---
type: Module
title: Lexer
description: Tokenizes COBOL source into Token objects; 236 TokenType values; optional Cython hot-path.
tags: [lexer, tokenizer, cython, token-type]
timestamp: 2026-06-28T00:00:00Z
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

# Errors

`LexerError` — extends `ParseError` (`cobolparser/_errors.py`). Raised for
unrecognised characters or malformed string literals.

# See Also

* [preprocessing.md](preprocessing.md) — upstream fixed-format normalisation
* [parser.md](parser.md) — consumes `List[Token]` via `TokenStream`
