---
type: CLI Reference
title: CLI
description: cobol-parser command-line interface covering 14 subcommands and IO coverage reporting tools.
tags: [cli, command-line, parse, batch, analyze, io-coverage, profiling]
timestamp: 2026-06-28T00:00:00Z
---

# CLI

> `cobol-parser` — command-line interface to every parser feature.

## Files

| File | Purpose |
|------|---------|
| `cobolparser/cli/__init__.py` | Module hub; exports `main()` |
| `cobolparser/cli/parse.py` | All subcommand implementations and entry point |
| `cobolparser/cli/coverage.py` | IO coverage reporting subcommands (separate CLI tool) |

## Entry Point

```
cobol-parser <subcommand> [options]
```

Registered as a `console_scripts` entry point in `setup.cfg`.

**Backward compatibility:** If the first positional argument is not a recognized subcommand, `cobol-parser` automatically prepends `parse`. So `cobol-parser foo.cbl` is treated as `cobol-parser parse foo.cbl`.

## Subcommands

### `parse <file.cbl> [path] [flags]`

Parse a single COBOL file and print the AST to JSON.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `path` | positional | `None` | Dot-separated AST path (e.g., `procedure.MAIN-LOGIC`). Returns that subtree instead of the full AST. |
| `--compact` | bool | `False` | Compact JSON output (no indentation) |
| `--free-form` | bool | `False` | Treat input as free-form COBOL (skip fixed-format normalization) |
| `--dialect` | choice | `ibm-enterprise` | COBOL dialect (currently only `ibm-enterprise` supported) |
| `--error-recovery` | choice | `collect-all` | Error recovery mode: `fail-fast` or `collect-all` |
| `--copybook-path` | string (repeatable) | `[]` | Directory to search for copybooks |
| `--define` | string (repeatable) | `[]` | Conditional compilation symbol (`SYMBOL` or `SYMBOL=VALUE`) |
| `--output`, `-o` | string | `None` | Write output to FILE instead of stdout |
| `--errors` | bool | `False` | Include parse errors/warnings in output |
| `--stats` | bool | `False` | Include parse statistics |
| `--find-type` | string | `None` | Find all AST nodes of the given type |
| `--profile` | bool | `False` | Profile the parse (cProfile + tracemalloc) |
| `--profile-top-n` | int | `20` | Top N functions in profiling output |
| `--profile-output` | string | `None` | Write cProfile binary to PATH |

```bash
cobol-parser parse examples/cobol/hello.cbl
cobol-parser parse examples/cobol/hello.cbl procedure.MAIN-LOGIC
cobol-parser parse examples/cobol/hello.cbl --dialect ibm-enterprise --stats
cobol-parser parse examples/cobol/hello.cbl --find-type MoveStatement --compact
cobol-parser parse examples/cobol/hello.cbl --profile --profile-top-n 10
cobol-parser parse examples/cobol/hello.cbl --copybook-path ./copybooks --define DEBUG=1
```

### `batch <file1.cbl> [file2.cbl ...] [flags]`

Parse multiple files in parallel using `ProcessPoolExecutor`. See [batch.md](batch.md).

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--glob` | string (repeatable) | `[]` | Glob pattern to collect source files |
| `--workers` | int | `None` | Number of worker processes (default: CPU count) |
| `--encoding` | string | `utf-8` | File encoding |
| `--compact` | bool | `False` | Compact JSON output |
| `--errors` | bool | `False` | Include errors/warnings per file |
| `--stats` | bool | `False` | Include parse statistics per file |
| `--profile` | bool | `False` | Profile each parse |
| `--profile-output` | string | `None` | Write cProfile binaries to **directory** (not a .prof file) |

```bash
cobol-parser batch src/*.cbl --stats
cobol-parser batch --glob "examples/**/*.cbl" --workers 4
cobol-parser batch --glob "src/**/*.cbl" --errors --dialect ibm-enterprise
```

### `tokenize <file.cbl> [flags]`

Tokenize a COBOL source file and print token stream as JSON array. Each token: `{"type": "TOKEN_NAME", "value": "...", "line": N, "column": N}`.

```bash
cobol-parser tokenize src/PAYROLL.cbl
cobol-parser tokenize src/PAYROLL.cbl --output tokens.json
```

### `preprocess <file.cbl> [flags]`

Normalize fixed-format to free-form, expand conditional compilation symbols, strip compiler directives.

| Flag | Description |
|------|-------------|
| `--define` | Conditional compilation symbols |
| `--strip-directives` | Strip PROCESS/CBL compiler directives |

### `expand <file.cbl> --copybook-path <dir> [flags]`

Expand COPY statements inline; outputs JSON with expanded source, diagnostics, and statistics.

| Flag | Description |
|------|-------------|
| `--copybook-path` | Directory to search for copybooks (repeatable) |
| `--max-depth` | Maximum copybook nesting depth (default 100) |

### `analyze <file.cbl> [flags]`

Analyze dynamic CALL targets. Outputs JSON report with `calls` array showing called programs and possible values for dynamic calls.

### `dead-code <file.cbl> [flags]`

Detect unreferenced paragraphs and sections. Outputs JSON report with `dead_items` array.

### `program-flow <file.cbl> [flags]`

Display program control flow graph. Supports multiple output formats.

| Flag | Description |
|------|-------------|
| `--format` | Output format: `json`, `mermaid` (Mermaid flowchart), or `dot` (Graphviz DOT) |

```bash
cobol-parser program-flow src/PAYROLL.cbl
cobol-parser program-flow src/PAYROLL.cbl --format mermaid --output flow.mermaid
cobol-parser program-flow src/PAYROLL.cbl --format dot --output flow.dot
```

### `generate-tests <file.cbl> -o <output.cut> [flags]`

Generate CobolCheck unit test stubs from program structure. Outputs `.cut` (COBOL Unit Test) format.

| Flag | Description |
|------|-------------|
| `--strategy` | Coverage strategy: `paragraph`, `branch`, `boundary` (repeatable; all used if omitted) |
| `--output`, `-o` | Output `.cut` file path |

### `io-sequence <file.cbl> [flags]`

Validate I/O operation sequencing (OPEN before READ/WRITE, CLOSE after operations, etc.). Outputs JSON `violations` array.

### `move-type-check <file.cbl> [flags]`

Validate MOVE statement source/destination type compatibility. Outputs JSON `violations` array.

### `linkage-check <file.cbl> [flags]`

Validate LINKAGE SECTION items against CALL/ENTRY USING clauses. Outputs JSON `violations` array.

### `language-env <file.cbl> [flags]`

Detect IBM Language Environment function calls and COBOL intrinsic functions.

### `ims-dli <file.cbl> [flags]`

Analyze IMS DLI calls (CBLTDLI, AIBTDLI, CEETDLI) and extract segment references. Outputs JSON with `dli_calls` array.

## Coverage Subcommands (`cli/coverage.py`)

Accessible as `python -m cobolparser.cli.coverage`. Provides machine-readable and human-readable IO coverage reporting. See [analysis.md](analysis.md) for `IOCoverageReporter`.

### `status [flags]`

Show IO coverage status (filtered by verb/qualifier).

| Flag | Description |
|------|-------------|
| `--artifact` | Path to coverage artifact JSON (default `io-coverage.json`) |
| `--verb` | Filter by verb (e.g., `OPEN`, `READ`) |
| `--qualifier` | Filter by qualifier (e.g., `AT END`) |
| `--format` | Output: `table` or `json` |

### `generate [flags]`

Generate coverage artifact from pytest results.

| Flag | Description |
|------|-------------|
| `--pytest-results` (required) | Path to pytest results JSON |
| `--output` | Output path (default `io-coverage.json`) |

### `validate [flags]`

Validate coverage artifact against schema.

| Flag | Description |
|------|-------------|
| `--artifact` (required) | Path to coverage artifact JSON |

### `render [flags]`

Render coverage artifact as Markdown, CSV, or summary text.

| Flag | Description |
|------|-------------|
| `--input` (required) | Path to coverage artifact JSON |
| `--format` | `markdown`, `csv`, or `summary` (default `markdown`) |

## Gotchas / Invariants

- `--dialect ibm-enterprise` enables EXEC SQL, EXEC CICS, EXEC IMS DLI parsing and IBM data types. Without this flag, EXEC blocks cause `UnknownStatementError`.
- `batch` uses `ProcessPoolExecutor`; on Windows, the calling script must be protected with `if __name__ == "__main__"`.
- `--profile-output` in batch mode must be a **directory path**, not a `.prof` file.
- `--free-form` skips fixed-format column normalization (columns 1–6, 7 indicator, 8–11 Area A, 12–72 Area B).
- `--define` accepts `SYMBOL` (becomes `SYMBOL=TRUE`) or `SYMBOL=VALUE`; symbols are case-sensitive.
- JSON path resolution in `parse`: dot-separated with bracket notation — `procedure.MAIN-LOGIC`, `data.working-storage[0].picture`. Names are case-insensitive (uppercased internally).
- Error recovery: `fail-fast` → parser halts on first error, `result.ast` is `None`. `collect-all` (default) → collects all errors, `result.ast` may be partial.

## Refresh Checklist

- [ ] Verify all 14 subcommands are listed (parse, batch, tokenize, preprocess, expand, analyze, dead-code, program-flow, generate-tests, io-sequence, move-type-check, linkage-check, language-env, ims-dli)
- [ ] Verify 4 coverage subcommands (status, generate, validate, render)
- [ ] Check `--profile` and `--profile-top-n` are documented
- [ ] Verify `--format` for `program-flow` lists `json`, `mermaid`, and `dot`
- [ ] Verify `--strategy` for `generate-tests` is repeatable and lists all three strategies
