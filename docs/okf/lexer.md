# Lexer
> Tokenizes COBOL source text into a flat `List[Token]` with full column-layout awareness.

## Files

| File | Purpose |
|------|---------|
| `cobolparser/lexer.py` | Pure-Python `_CobolLexerPure`, `CobolLexer` (public alias), `Token` dataclass, `TokenType` IntEnum (236 members), `LexerError`, `tokenize_cobol()` helper |
| `cobolparser/_lexer_fast.pyx` | Cython subclass of `CobolLexer`; overrides hot-path methods (`check_division_header`, `read_word_from_text`, `tokenize_program_text`) with C-typed implementations |

## Key Classes / Functions

| Name | Location | Description |
|------|----------|-------------|
| `_CobolLexerPure` | `lexer.py` | Pure-Python lexer implementation; handles tokenization of COBOL source text |
| `CobolLexer` | `lexer.py` | Public-facing lexer class; either Cython-accelerated (if compiled) or alias to `_CobolLexerPure`. Instantiated with source text; call `.tokenize()` to generate tokens |
| `Token` | `lexer.py` | Dataclass: `type: TokenType`, `value: str`, `location: SourceLocation`, `raw_value: str \| None = None` |
| `TokenType` | `lexer.py` | `IntEnum` with 236 members covering every COBOL keyword, literal type, figurative constant, and punctuation |
| `LexerError` | `lexer.py` | Raised on unrecoverable tokenization errors; extends `ParseError` with `location` and `token_value` fields |
| `tokenize_cobol()` | `lexer.py` | Convenience wrapper: `tokenize_cobol(text, filename, dialect) -> List[Token]` |

## Data Flow / Lifecycle

1. Caller passes preprocessed free-form COBOL text (columns 1–6 and 73–80 already stripped by `normalize_fixed_format`, comment lines already removed).
2. `CobolLexer(text, filename, dialect)` instantiates the lexer; no tokenization yet.
3. `.tokenize()` iterates character-by-character through the source:
   - Recognizes division/section/paragraph headers via `check_division_header()`
   - Reads words/identifiers via `read_word_from_text()`
   - Classifies each word against `TokenType` keyword table in `KEYWORDS` dict
   - Handles string literals (single-quoted and double-quoted), numeric literals, figurative constants (`ZERO`, `SPACE`, `HIGH-VALUE`, etc.)
   - Produces a `Token` for each meaningful unit; emits `NEWLINE` tokens; skips whitespace (not emitted as tokens)
   - Collects any lexing errors in `.errors` list (per error recovery mode)
4. Returns `List[Token]` — the input to `TokenStream` in `cobolparser/core/token_stream.py`.

**Cython fast-path:** If `cobolparser._lexer_fast` is importable (compiled via `python setup.py build_ext --inplace`), the module transparently replaces the pure-Python `_CobolLexerPure` base class with a Cython subclass. If not compiled or if `COBOLPARSER_SKIP_EXT=1` was set at install time, the pure-Python version is used unchanged. No caller code changes required; `CobolLexer` always refers to the active implementation.

## Fixed-Format Column Layout (handled by preprocessor, not lexer)

| Columns | Purpose |
|---------|---------|
| 1–6 | Sequence number (ignored by preprocessor) |
| 7 | Indicator: space=code, `*`/`/`=comment, `-`=continuation (handled by preprocessor) |
| 8–11 | Area A (division/section/paragraph headers, level 01/77) |
| 12–72 | Area B (statements, subordinate data items) |
| 73–80 | Identification (ignored by preprocessor) |

The lexer receives text that has already been normalized to free-form by `cobolparser/preprocess/__init__.py::normalize_fixed_format()`; it does NOT handle fixed-format column layout itself.

## Public API (exported symbols)

```python
from cobolparser import CobolLexer, Token, TokenType
from cobolparser.lexer import LexerError, tokenize_cobol
```

## Gotchas / Invariants

- Comment lines (col 7 = `*` or `/`) must be stripped by `normalize_fixed_format()` BEFORE the lexer runs — if they reach the lexer, tokenization breaks or produces malformed tokens.
- `TokenType` uses `IntEnum`, so tokens can be compared with `==` to either the enum member or its integer value; this makes membership tests and hash lookups faster on the hot path.
- The Cython subclass is loaded transparently via try/except in `lexer.py` lines 1718–1721; never import `_lexer_fast` or `_CobolLexerPure` directly. Always use `CobolLexer`.
- Figurative constants (`ZERO`, `ZEROS`, `ZEROES`, `SPACE`, `SPACES`, `HIGH-VALUE`, `HIGH-VALUES`, `LOW-VALUE`, `LOW-VALUES`, `QUOTE`, `QUOTES`, `ALL`) are recognized as `TokenType.FIGURATIVE_CONSTANT` keywords (via `KEYWORDS` dict), not literals.
- `Token.location` is a `SourceLocation(line, column, offset)` tuple-like object; `line` and `column` are 1-indexed for error reporting.
- `FUNCTION` is intentionally NOT registered as a keyword in `KEYWORDS` (see comment at `lexer.py` line 313) — this allows expressions like `DISPLAY FUNCTION CURRENT-DATE` to parse correctly, even though `FUNCTION` appears in the token stream as an `IDENTIFIER`.

## Refresh Checklist

- [ ] Count `TokenType` members in `lexer.py` via `grep -c "= auto()"` in the enum (currently 236)
- [ ] Verify `check_division_header`, `read_word_from_text`, `tokenize_program_text` are still the three hot-path methods in `_lexer_fast.pyx`
- [ ] Check that `_lexer_fast.pyx` still subclasses `_CobolLexerBase` (which is `_CobolLexerPure`)
- [ ] Verify `__init__.py` still exports `CobolLexer`, `Token`, `TokenType` at the package level
- [ ] Confirm `tokenize_cobol()` signature at line 1684 still takes `(source, filename, dialect)`
