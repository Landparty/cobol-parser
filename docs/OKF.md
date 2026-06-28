# Organizational Knowledge File (OKF)

> Persistent structural memory for the `cobol-parser` repository.
> Load the relevant subsystem file at the start of any Claude session rather than re-deriving structure from source.

## Repo at a Glance

| Attribute | Value |
|-----------|-------|
| Language | Python >=3.11 (3.11, 3.12, 3.13 tested in CI) |
| Package | `cobolparser` |
| Version | 1.1.0 |
| Runtime deps | **None** (zero external dependencies for core library) |
| Optional extras | `[dev]` tests/lint, `[docs]` docs, `[fast]` Cython build, `[profiling]` psutil |
| Cython fast-paths | `_lexer_fast`, `_preprocess_fast`, `_data_fast` — opt-out: `COBOLPARSER_SKIP_EXT=1` |
| Vendored into | `backend/_vendor/cobol-parser/cobolparser/` (manual copy — never auto-synced) |
| Tests | ~5,969 tests across 226 files; 81% line coverage floor enforced |
| Entry point | `cobol-parser` CLI (console_scripts in setup) |
| Focus dialect | IBM Enterprise COBOL |

## Pipeline Overview

```
COBOL source (.cbl / .cob)
  │
  ▼
preprocess/normalize_fixed_format()
  ├─ extracts columns 8–72 from fixed-format lines
  ├─ drops comment lines (col 7 = * or /)
  └─ merges continuation lines (col 7 = -)
  │
  ▼ (optional)
preprocess/expand_copybooks()
  └─ inlines COPY statements recursively, applies REPLACING clauses
  │
  ▼
CobolLexer(text).tokenize()  →  List[Token]
  └─ TokenType enum (236 members); Cython fast-path via _lexer_fast if compiled
  │
  ▼
TokenStream(tokens)
  └─ peek() / consume() / expect() with configurable lookahead
  │
  ▼
CobolParser.parse()
  └─ DivisionParserFactory dispatches to:
       IdentificationDivisionParser
       EnvironmentDivisionParser
       DataDivisionParser  ←  _data_fast Cython path for PICTURE/clause loops
       ProcedureDivisionParser
         └─ StatementParserRegistry (first-match dispatch → 26+ statement parsers)
  │
  ▼
ParseResult(ast, errors, warnings, statistics)
  ├─ ast: CobolProgram  →  .to_json() / .find_all_by_type()
  ├─ errors: List[ParseError]
  ├─ warnings: List[str]
  └─ statistics: ParseStatistics
  │
  ▼ (optional post-parse)
analysis/  →  15+ analyzers (DeadCodeAnalyzer, ProgramFlowAnalyzer, IOLogger, …)
```

## Navigation

| File | Covers |
|------|--------|
| [okf/lexer.md](okf/lexer.md) | CobolLexer, Token, TokenType, Cython fast-path (`_lexer_fast`) |
| [okf/preprocessing.md](okf/preprocessing.md) | normalize_fixed_format, copybook expansion, COPY statement parsing, path resolution |
| [okf/parser.md](okf/parser.md) | CobolParser, DivisionParserFactory, TokenStream, StatementParserRegistry, all 26 statement parsers, core infrastructure |
| [okf/ast-models.md](okf/ast-models.md) | ASTNode hierarchy, every model class by category, to_dict() contract, ASTNodeFactory |
| [okf/analysis.md](okf/analysis.md) | All 15 analyzers with purpose, input/output, exported symbols |
| [okf/cli.md](okf/cli.md) | Every CLI subcommand, flags, and usage examples |
| [okf/tests.md](okf/tests.md) | Test directory layout, pytest markers, fixtures, coverage floor, how to run subsets |
| [okf/batch.md](okf/batch.md) | parse_files(), parse_files_with_copybooks(), ProcessPoolExecutor, profiling |
| [okf/dialects.md](okf/dialects.md) | IBMEnterpriseCobol, DialectType enum, EXEC SQL/CICS/IMS support |
| [okf/conventions.md](okf/conventions.md) | Code style, error hierarchy, Cython fast-path pattern, import rules, vendoring |

## Refresh Protocol

When starting a session or explicitly asked to refresh the OKF:

1. Read `cobolparser/__init__.py` — check exported symbols against `okf/` files
2. `glob cobolparser/**/*.py` — identify new or removed files
3. For each changed subsystem, read the relevant source files and patch the corresponding `docs/okf/*.md`
4. Update the Navigation table above if subsystem files were added or removed
5. Commit: `git commit -m "docs(okf): refresh OKF — <brief description of what changed>"`

**Invariant:** OKF is the source of truth for structural knowledge.
Code is the source of truth for implementation detail.
When they conflict, trust the code and update the OKF.
