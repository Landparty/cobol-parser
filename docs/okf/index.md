# cobol-parser — OKF Index

> **AI quick-start:** Load this file first. Then load the sub-file that matches your task.

**Last Updated:** 2026-06-27

---

## What Is This Repo?

`cobolparser` is a comprehensive Python library that parses IBM Enterprise COBOL source code into a traversable AST. It covers all four COBOL divisions, 26+ statement types, copybook expansion, 15 static analysis modules, and a rich CLI.

| Attribute | Value |
|-----------|-------|
| Package | `cobolparser` |
| Version | 1.0.0 |
| Python | ≥3.11 (3.11, 3.12, 3.13 tested in CI) |
| Runtime deps | **None** |
| Cython fast-paths | `_lexer_fast`, `_preprocess_fast`, `_data_fast` — opt-out: `COBOLPARSER_SKIP_EXT=1` |
| Integration | Vendored into `backend/_vendor/cobol-parser/` — manual copy required |
| Vendor sync | `cp -r cobolparser/ ../backend/_vendor/cobol-parser/cobolparser/` |
| Tests | ~5,969 tests across 226 files; 81% line coverage floor enforced |
| Interface contract | [`interface-contract.md`](../../interface-contract.md) |

---

## Pipeline

```
COBOL source (.cbl / .cob)
  → preprocess/normalize_fixed_format()     [columns 8-72, drop comments, merge continuations]
  → (optional) preprocess/expand_copybooks() [inline COPY statements, apply REPLACING]
  → CobolLexer(text).tokenize()             [List[Token], 236 TokenType values]
  → TokenStream(tokens)                     [peek / consume / expect]
  → CobolParser.parse()                     [DivisionParserFactory → 4 division parsers]
      └─ StatementParserRegistry            [first-match dispatch → 26+ statement parsers]
  → ParseResult(ast, errors, warnings, statistics)
  → (optional) analysis/                   [15+ analyzers]
```

---

## OKF Sub-files

| File | Load when you need to… |
|------|------------------------|
| [lexer.md](lexer.md) | Understand `CobolLexer`, `Token`, `TokenType` (236 types), Cython fast-path |
| [preprocessing.md](preprocessing.md) | Understand `normalize_fixed_format`, copybook expansion, COPY parsing, path resolution |
| [parser.md](parser.md) | Understand `CobolParser`, `DivisionParserFactory`, `TokenStream`, all 26 statement parsers |
| [ast-models.md](ast-models.md) | Understand `ASTNode` hierarchy, every model class, `to_dict()`, `ASTNodeFactory` |
| [analysis.md](analysis.md) | Understand all 15 analyzers — purpose, input/output, exported symbols |
| [cli.md](cli.md) | Understand every CLI subcommand, flags, and usage examples |
| [tests.md](tests.md) | Run tests, understand layout, pytest markers, fixtures, coverage floor |
| [batch.md](batch.md) | Understand `parse_files()`, `parse_files_with_copybooks()`, `ProcessPoolExecutor`, profiling |
| [dialects.md](dialects.md) | Understand `IBMEnterpriseCobol`, `DialectType`, EXEC SQL/CICS/IMS support |
| [conventions.md](conventions.md) | Code style, error hierarchy, Cython fast-path pattern, import rules, vendoring |

---

## Key Cross-Cutting Facts

- **Vendored** — changes to `cobolparser/` must be copied to `backend/_vendor/cobol-parser/cobolparser/`.
- **No runtime dependencies** — zero external imports in the core library.
- **Cython is optional** — `COBOLPARSER_SKIP_EXT=1` disables it; pure-Python fallback always works.
- **Fixed-format COBOL:** columns 1-6 = sequence, 7 = indicator, 8-11 = Area A, 12-72 = Area B, 73-80 = ignored.
- **Coverage floor:** 81% line coverage enforced by pytest on every run.
- **CI:** GitHub Actions tests Python 3.11, 3.12, 3.13 on push/PR to `main`.

---

## Public API Quick Reference

```python
from cobolparser import parse_cobol, CobolParser, ErrorRecoveryMode

# Simple
result = parse_cobol(source, filename="prog.cob")

# Configurable
parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
result = parser.parse(source)

result.success        # bool
result.ast            # CobolProgram or None
result.errors         # List[ParseError]
result.statistics     # ParseStatistics

# Post-parse analysis
from cobolparser import DynamicCallAnalyzer, ProgramFlowAnalyzer
DynamicCallAnalyzer().analyze(result.ast)
flow = ProgramFlowAnalyzer().analyze(result.ast).to_dict()

# Batch multi-file
from cobolparser import parse_files
results = parse_files(["a.cbl", "b.cbl"])
```

---

## Maintenance

Update the relevant OKF sub-file in the same commit as the source change. Bump `Last Updated` in this file on every OKF edit.
