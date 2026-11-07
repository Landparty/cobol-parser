# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## OKF Hooks Setup (one-time)

Run this once after cloning to enable the pre-commit staleness check:

```bash
git config core.hooksPath .githooks
```

The hook warns (and blocks the commit) when source files change without a corresponding OKF update. Bypass with `git commit --no-verify` when you intentionally skip the OKF.

A Claude Code `PostToolUse` hook also prints a one-line reminder inline when Claude edits OKF-covered source files. See `.claude/settings.json`.

## Open Knowledge Format (OKF)

This repo uses a structured knowledge base at `.okf/`. **Load `.okf/index.md` at the start of every session** — it tells you which sub-file to load for your task:

| Task type | Load |
|-----------|------|
| Tokenization, `TokenType`, Cython fast-path | `.okf/lexer.md` |
| Parser, `DivisionParserFactory`, statement parsers | `.okf/parser.md` (routing page for `.okf/parser/`) |
| `normalize_fixed_format`, copybook expansion | `.okf/preprocessing.md` |
| `ASTNode` hierarchy, `CobolProgram`, `to_dict()` | `.okf/ast-models.md` |
| Static analysis (`DeadCodeAnalyzer`, `ProgramFlowAnalyzer`, `LintAnalyzer`, `XrefAnalyzer`, `ProgramSignatureExtractor`, `CodebaseGraphBuilder`, `SqlCicsAnalyzer`, `ProgramDiffer`, `FieldWideningAnalyzer`, etc.) | `.okf/analysis.md` (routing page for `.okf/analysis/`) |
| Dialects, EXEC SQL/CICS/IMS nodes, LE/intrinsic signature lookups | `.okf/dialects.md` |
| Flowcharts, copybook → CSV/record-image data (`CopybookDataGenerator`), decode/compare, `gen-fixtures` bundles and scenarios | `.okf/generators.md` (routing page for `.okf/generators/`) |
| `parse_files`, `parse_files_with_copybooks`, `scan_files`, batch fault isolation | `.okf/batch.md` |
| z/OS JCL: jobs/steps, DD → dataset bindings (read by jcl-parser) | `.okf/jcl.md` |
| CICS CSD and BMS maps, DB2 DDL, IMS DBD/PSB (`cobolparser.definitions`) | `.okf/definitions.md` |
| CLI subcommands and flags, the `cobol.yml` project config | `.okf/cli.md` |
| The MCP server for AI agents (`cobol-parser mcp`), its tools, envelope and caveats | `.okf/mcp.md` |
| Test layout, markers, coverage floor | `.okf/tests.md` |
| Backend adapter dict shape (summary of `interface-contract.md`) | `.okf/integration.md` |

The OKF is more specific and more current than this file for the above topics. When they conflict, trust the OKF. Point-in-time history lives in `.okf/history/` and `.okf/log.md` and is not loaded by default. The pre-commit hook also runs `scripts/okf_check.py`, which tests what the OKF files claim against the code, and the same for this file, `README.md`, `interface-contract.md` and the user guides in `docs/` (its `EXTRA_FILES`); `python scripts/okf_check.py --write` refreshes its generated `<!-- okf:gen -->` spans.

This file is the short orientation. Module-by-module detail, report shapes and caveats live in the OKF topic files above; the full CLI reference is the generated subcommand table in `.okf/cli.md`.

## Project Overview

**cobolparser** is a COBOL parser for Python with an IBM Enterprise COBOL focus. It turns COBOL source into a traversable AST with JSON export and error recovery, and builds static analyzers, test-data generators and an MCP server on top. See `pyproject.toml` for the current version (release-please keeps it current); authored by Samuel Dion. License is AGPL-3.0-or-later (see `LICENSE`).

## Consumers

- **backend** vendors this library into `backend/_vendor/cobol-parser/`; it does not install it from PyPI. Changes reach it only by copying: `cp -r cobolparser/ ../backend/_vendor/cobol-parser/cobolparser/`.
- **PyPI** `cobol-parser` (wheels plus sdist) exists for `mocky-mock` and other external users. It does not change the backend's vendoring flow.
- **Interface contract:** [`interface-contract.md`](interface-contract.md) documents what the backend adapter and `mocky-mock`'s generators surface (`ProgramFixtureGenerator`, gated on `FixtureBundle`'s `bundle_version`) call. Read it before changing a public API shape; a breaking change to either surface bumps the relevant version field.

## Commands

```bash
# Requires Python >= 3.11 (supports 3.11, 3.12, 3.13)
pip install -e ".[dev,docs]"

# Pure Python is the default backend: nothing is compiled. The Cython hot-path
# modules are opt-in via COBOLPARSER_ACCEL=1, read at build time AND import time:
pip install -e ".[fast]"
COBOLPARSER_ACCEL=1 python setup.py build_ext --inplace
COBOLPARSER_ACCEL=1 python -m pytest tests/ --no-cov

# Tests (90% coverage floor; measure it on pure Python, see "Tests" below)
python -m pytest tests/ -v
python -m pytest tests/ -q -n 4 --no-cov          # fast full run (pytest-xdist)
python -m pytest tests/unit/test_lexer.py -v
python -m pytest -m "integration"                 # also: slow, contract, io
COBOLPARSER_PERF=1 python -m pytest tests/performance/test_large_program.py   # 40k-line lane

# Lint, format, types
python -m ruff check .
python -m black .
python -m mypy cobolparser/

# CLI: one subcommand per analyzer or generator. Examples:
cobol-parser parse prog.cbl --copybook-path ./copybooks -o out.json
cobol-parser lint prog.cbl --format sarif
cobol-parser scan src/*.cbl --analyzer health --cache-dir .cache
cobol-parser widen-check CUST-ID src/ --to '9(9)'
cobol-parser gen-fixtures prog.cbl --scenarios all -o bundle.json
cobol-parser mcp --root .                         # MCP server for AI agents ([mcp] extra)
```

Every subcommand, its positionals and its flags: `.okf/cli.md` (generated from the argparse tree by `scripts/okf_check.py --write`). Every subcommand takes `--config FILE` / `--no-config` for the `cobol.yml` project config ([`docs/project-config.md`](docs/project-config.md)); precedence is CLI flag > config file > built-in default. Parsing subcommands take `--error-recovery fail-fast|collect-all` (the CLI defaults to collect-all, the library to fail-fast).

## Architecture

A multi-stage pipeline: **preprocess -> lex -> parse -> AST**, with analyzers and generators reading the AST.

```
COBOL source (.cbl/.cob)
  -> preprocess/   normalize_fixed_format, copybook expansion + source map, REPLACE, >>IF/>>DEFINE
  -> lexer.py      CobolLexer -> List[Token]
  -> parser.py     CobolParser -> ParseResult(ast, errors, warnings, statistics, expansion_source_map)
  -> models/       ASTNode classes with to_dict()/to_json()
  -> analysis/, generators/, scan.py, mcp/
```

| Package | What it holds | OKF |
|---|---|---|
| `cobolparser/preprocess/` | fixed-format normalization, `expand_copybooks`, source map, conditional compilation, REPLACE, secure path resolution | `.okf/preprocessing.md` |
| `cobolparser/lexer.py` | `CobolLexer`, `TokenType` (<!-- okf:gen tokentype-count -->246<!-- /okf:gen --> members) | `.okf/lexer.md` |
| `cobolparser/parser.py`, `core/`, `parsers/` | `CobolParser`, `TokenStream`, `DivisionParserFactory`, <!-- okf:gen statement-parser-file-count -->33<!-- /okf:gen --> statement parser files | `.okf/parser.md` |
| `cobolparser/models/` | `CobolProgram` and every AST node | `.okf/ast-models.md` |
| `cobolparser/dialects/` | IBM Enterprise dialect, EXEC SQL/CICS/IMS, LE and intrinsic signatures | `.okf/dialects.md` |
| `cobolparser/analysis/` | <!-- okf:gen analysis-module-count -->40<!-- /okf:gen --> analyzer modules plus `program_flow/` | `.okf/analysis.md` |
| `cobolparser/generators/` | flowcharts, copybook data and record images, decode/compare, `gen-fixtures` bundles and scenarios | `.okf/generators.md` |
| `cobolparser/batch.py`, `scan.py`, `_facts_cache.py` | parallel parsing, multi-file analysis with per-file fault isolation, the on-disk cache | `.okf/batch.md` |
| `cobolparser/jcl/` | JCL jobs, steps, DD bindings (through the `[jcl]` extra) | `.okf/jcl.md` |
| `cobolparser/definitions/` | CICS CSD and BMS maps, DB2 DDL, IMS DBD and PSB | `.okf/definitions.md` |
| `cobolparser/cli/`, `config/` | the CLI and the `cobol.yml` reader | `.okf/cli.md` |
| `cobolparser/mcp/` | the MCP server ([`docs/mcp-server.md`](docs/mcp-server.md)) | `.okf/mcp.md` |

Two rules that bite: split source text with `cobolparser/_lines.py`'s `split_source_lines()`, never `str.splitlines()` (form feed and U+2028 shift line numbers); and the analyzers follow "exact by construction, or absent", reporting what they could not check as caveats rather than guessing.

### Public API

```python
from cobolparser import parse_cobol, CobolParser, ErrorRecoveryMode

result = parse_cobol(source, filename="prog.cob")   # FAIL_FAST by default
result.ast            # CobolProgram
result.errors         # list[ParseError]
result.success        # ast is not None and no errors
result.ast.to_json()
result.ast.find_all_by_type("MoveStatement")

parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
result = parser.parse(source)

from cobolparser import parse_cobol_with_expansion
result = parse_cobol_with_expansion(source, "prog.cbl", copybook_paths=["copybooks"])

# Analyzers share one shape: <Analyzer>().analyze(ast) -> <Report> with to_dict()
from cobolparser import LintAnalyzer, DeadCodeAnalyzer, ComplexityAnalyzer
report = LintAnalyzer().analyze(result.ast)
```

Per-analyzer and per-generator APIs, with examples: the OKF topic for that area.

### Adding a New Statement Parser

1. Create `cobolparser/parsers/statements/foo_parser.py` implementing `IStatementParser` (`parse()` and `matches()`)
2. Register it in the `ProcedureDivisionParser` (or via the `StatementParserRegistry`)
3. Add a `TokenType` entry in `lexer.py` if the verb isn't already a keyword
4. Add AST node(s) in `cobolparser/models/statements/<category>.py` with `to_dict()`; instantiate through `ASTNodeFactory` (`core/ast_factory.py`)
5. Export the parser from `cobolparser/parsers/statements/__init__.py` and the node from `cobolparser/models/statements/__init__.py`
6. Add a fixture to the swallow sweep (see `.okf/parser.md`); its test fails when a parser is registered without one

### Fixed-Format COBOL Column Layout

| Columns | Purpose |
|---------|---------|
| 1-6 | Sequence number (ignored) |
| 7 | Indicator: space=code, `*`/`/`=comment, `-`=continuation |
| 8-11 | Area A (division/section/paragraph headers, level 01/77) |
| 12-72 | Area B (statements, subordinate data items) |
| 73-80 | Identification (ignored) |

`normalize_fixed_format` extracts columns 8-72, drops comment lines, and merges continuation lines.


## Tests

Layout, markers, fixtures and the per-directory breakdown: `.okf/tests.md`. `tests/samples/` holds the shared COBOL fixtures (`tests/samples/enterprise/` has one program per IBM Enterprise COBOL program type, see [`docs/enterprise-program-types.md`](docs/enterprise-program-types.md)); `examples/cobol/` holds the NIST COBOL-85 suite and the shamrice examples, which must parse cleanly.

**Coverage:** `--cov-fail-under=90` with branch coverage, from `pyproject.toml`'s `addopts`. Measure it on the pure-Python backend (leave `COBOLPARSER_ACCEL` unset): coverage.py cannot see into a compiled Cython extension, so with the accelerators on, the pure-Python bodies they shadow read as unexecuted. A subset run fails the floor; that is expected.

## CI/CD

**Manual dispatch only:** `.github/workflows/ci.yml` has only a `workflow_dispatch` trigger (push, PR and the nightly schedule are off), to save cost. Run lint, typecheck and the full suite locally before pushing. When dispatched it runs lint, mypy, a build matrix over Python 3.11-3.13 against the compiled extensions (`--no-cov`), and a pure-Python coverage job that enforces the floor.

## Release & Distribution

`release-please` (`.github/workflows/release-please.yml`, Conventional Commits) cuts versions and `CHANGELOG.md` sections on pushes to `main`, then publishes `cobol-parser` to PyPI: `cibuildwheel` wheels (`[tool.cibuildwheel]` in `pyproject.toml`) for manylinux x86_64, macOS arm64 and Windows AMD64 on Python 3.11-3.13, plus an sdist. Wheels ship the three Cython accelerators compiled but still run pure Python unless `COBOLPARSER_ACCEL=1` is set; every other module ships as plain `.py`. `workflow_dispatch` with `target: testpypi` rehearses the pipeline against test.pypi.org.

`CHANGELOG.md`: the `Unreleased` section lists what has landed on `main` since the last release. When a release ships, its hand-written entries move under that release's `### Release notes`.

## Code Style and Conventions

- **Formatter**: Black (line length 88, target py311)
- **Linter**: Ruff (pycodestyle, pyflakes, isort, bugbear, comprehensions, pyupgrade; E501 ignored)
- **Type checker**: mypy with strict settings (`disallow_untyped_defs`, `strict_equality`, etc.; tests are exempted from typed def requirements)
- **Python**: `>=3.11`, uses modern syntax (`list[]`, `dict[]`, `X | None` unions)
- **No runtime dependencies**: zero external dependencies for the core library. The optional extra `[jcl]` installs `jcl-parser`, which `cobolparser.jcl` reads JCL through -- never re-implement JCL parsing here; likewise `[pl1]` / `[hlasm]` install the PL/I and assembler parsers the MCP server reads those programs through
- **Imports**: `__init__.py` files may have unused imports (F401 ignored via ruff per-file config)

## File Organization Conventions

- One parser file per COBOL verb or verb group
- AST models grouped by category (arithmetic, control, data, io, call, misc)
- All parsers implement `IStatementParser` with `parse()` and `matches()` methods
- All AST nodes extend `ASTNode` and implement `to_dict()`
- Exception hierarchy rooted at `ParseError` in `_errors.py` (except the preprocessing errors -- `PreprocessingError` and its subclasses extend plain `Exception`)


## Other Directories

- `docs/` -- [`docs/README.md`](docs/README.md) maps where each kind of doc lives; user guides ([`docs/mcp-server.md`](docs/mcp-server.md), [`docs/project-config.md`](docs/project-config.md), [`docs/fixture-bundle-schema.md`](docs/fixture-bundle-schema.md)), design docs in `docs/plans/`, and the idea backlog in [`docs/feature-ideas.md`](docs/feature-ideas.md)
- `scripts/` -- `okf_check.py` (OKF claims vs. code, run by the pre-commit hook), `okf_staleness_check.py` (which OKF file a source file maps to), `validate_io_coverage.py`
- `tools/` -- IO catalog, IO coverage, metrics and perf-threshold utilities
- `benchmarks/`, `reports/` -- benchmark programs; dated audit reports and `reports/open-findings.md`
- `.pre-commit-config.yaml` -- ruff, ruff-format, black and mypy hooks; `pre-commit run --all-files` matches what CI would check
