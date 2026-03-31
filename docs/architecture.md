# Architecture

## Pipeline

```
COBOL source
  → preprocess/__init__.py   normalize_fixed_format(), copybook expansion
  → lexer.py                 CobolLexer → List[Token]
  → parser.py                CobolParser → ParseResult
  → models/                  AST node classes
```

1. `normalize_fixed_format(lines)` converts fixed-format COBOL (72-column lines) to free-form text. Comment lines (column 7 `*`/`/`) are silently dropped. Continuation lines (`-`) are merged.
2. `CobolLexer(text).tokenize()` produces `List[Token]` with 150+ `TokenType` values.
3. `TokenStream(tokens)` wraps the list with `peek()`, `consume()`, `expect()`.
4. `CobolParser.parse()` calls `DivisionParserFactory.parse_division()` per division encountered.
5. Each division parser uses `StatementParserRegistry.get_parser()` to dispatch individual statements.
6. Returns `ParseResult(ast, errors, warnings, statistics)`.

## Fixed-Format Column Layout

| Columns | Purpose |
|---------|---------|
| 1–6 | Sequence number (ignored) |
| 7 | Indicator: space=code, `*`/`/`=comment, `-`=continuation |
| 8–11 | Area A (division/section/paragraph headers, level 01/77) |
| 12–72 | Area B (statements, subordinate data items) |
| 73–80 | Identification (ignored) |

## Key Packages

**`cobolparser/lexer.py`** — Tokenises COBOL text. Handles fixed vs. free format, string continuations, figurative constants. Comment lines must be stripped by the preprocessor before the lexer runs.

**`cobolparser/preprocess/__init__.py`** — `normalize_fixed_format()` and `expand_copybooks()` (inlines `COPY` statements recursively).

**`cobolparser/parser.py`** — Top-level parse loop. Delegates to `DivisionParserFactory` which routes to division-specific parsers.

**`cobolparser/core/`** — Infrastructure only:
- `interfaces.py` — `ITokenStream`, `IDivisionParser`, `IStatementParser` protocols
- `token_stream.py` — `TokenStream`
- `registry.py` — `StatementParserRegistry`
- `exceptions.py` — `TokenMismatch`, `UnexpectedEndOfInput`, etc.
- `ast_factory.py` — `ASTNodeFactory`; use `get_factory()` / `create_node()` rather than instantiating nodes directly

**`cobolparser/parsers/`** — All statement and division parsers:
- `divisions/` — One parser per COBOL division
- `statements/` — One file per statement verb or verb group

**`cobolparser/models/`** — All AST node classes. Every node extends `ASTNode` and implements `to_dict()`:
- `ast_base.py` — `ASTNode`, `SourceLocation`, `ASTValidator`
- `program.py` — `CobolProgram`, `CobolDivision`, `CobolSection`, `CobolParagraph`
- `data_items.py` — `CobolDataItem`, `PictureClause`, `OccursClause`
- `statements/` — `arithmetic.py`, `call.py`, `control.py`, `data.py`, `io.py`, `misc.py`, `base.py`

**`cobolparser/dialects/ibm_enterprise.py`** — COMP-3, EXEC SQL/CICS, IBM intrinsic functions.

**`cobolparser/batch.py`** — `parse_files(paths)` for parallel multi-file parsing via multiprocessing.

## Adding a New Statement Parser

1. Create `cobolparser/parsers/statements/foo_parser.py` implementing `IStatementParser`.
2. Register it in `cobolparser/core/registry.py`.
3. Add a `TokenType` entry in `lexer.py` if the verb is new.
4. Add AST node(s) in the appropriate `cobolparser/models/statements/<category>.py` with `to_dict()`; use `ASTNodeFactory` to instantiate nodes.
