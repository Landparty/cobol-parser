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

| Module | Accelerates |
|--------|------------|
| `cobolparser/_lexer_fast.pyx` | `CobolLexer` hot-path methods |
| `cobolparser/_preprocess_fast.pyx` | Preprocessing inner loops |
| `cobolparser/_data_fast.pyx` | DATA DIVISION `PICTURE`/clause loops |

Pre-generated `.c` files are checked in — the build does **not** require Cython
at install time:

```bash
# Build in-place
python setup.py build_ext --inplace

# Skip entirely (no compiler/Cython)
COBOLPARSER_SKIP_EXT=1 pip install -e ".[dev]"
```

# Errors

`LexerError` — extends `ParseError` (`cobolparser/_errors.py`). Raised for
unrecognised characters or malformed string literals.

# See Also

* [preprocessing.md](preprocessing.md) — upstream fixed-format normalisation
* [parser.md](parser.md) — consumes `List[Token]` via `TokenStream`
