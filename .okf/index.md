---
okf_version: "0.1"
---

# cobolparser — Knowledge Bundle

`cobolparser` is a Python library (v1.0.0, Python ≥3.11) that parses IBM Enterprise COBOL
into a traversable AST. Zero runtime dependencies.

## Pipeline

```
COBOL source
  → normalize_fixed_format()         [columns 8-72, drop comments, merge continuations]
  → (optional) expand_copybooks()    [inline COPY statements, apply REPLACING]
  → CobolLexer(text).tokenize()      [List[Token], 236 TokenType values]
  → TokenStream(tokens)              [peek / consume / expect]
  → CobolParser.parse()              [DivisionParserFactory → 4 division parsers]
      └─ StatementParserRegistry     [first-match dispatch → 26 statement parsers]
  → ParseResult(ast, errors, warnings, statistics)
  → (optional) analysis/             [15 analyzers]
```

## Key Facts

| Attribute | Value |
|-----------|-------|
| Package | `cobolparser` |
| Version | 1.0.0 |
| Python | ≥3.11 (3.11, 3.12, 3.13 tested in CI) |
| Runtime deps | **None** |
| Cython fast-paths | `_lexer_fast`, `_preprocess_fast`, `_data_fast` — disable with `COBOLPARSER_SKIP_EXT=1` |
| Backend integration | Vendored into `backend/_vendor/cobol-parser/` — manual copy required |
| Tests | ~5,969 tests across 226 files; 81% line coverage floor |

## Concepts

* [lexer.md](lexer.md) — `CobolLexer`, `Token`, `TokenType` (236 members), Cython fast-path
* [preprocessing.md](preprocessing.md) — `normalize_fixed_format`, copybook expansion, `PreprocessingError` hierarchy
* [parser.md](parser.md) — `CobolParser`, `DivisionParserFactory`, `TokenStream`, 26 statement parsers, exception hierarchy
* [ast-models.md](ast-models.md) — `ASTNode` hierarchy, all model classes, `to_dict()` contract, `ASTNodeFactory`
* [analysis.md](analysis.md) — 15 post-parse analyzers; purpose, input/output, exported symbols
* [cli.md](cli.md) — 14 CLI subcommands, all flags, IO coverage reporting tools
* [batch.md](batch.md) — `parse_files()`, `parse_files_with_copybooks()`, `ProfilerContext`
* [tests.md](tests.md) — test layout, pytest markers, fixtures, coverage floor, CI matrix
* [dialects.md](dialects.md) — `IBMEnterpriseCobol`, `DialectType`, EXEC SQL/CICS/IMS support
* [conventions.md](conventions.md) — code style, error hierarchy, Cython pattern, import rules, vendoring
