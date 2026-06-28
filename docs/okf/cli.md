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

Registered as a `console_scripts` entry point in `setup.cfg` (command name: `cobol-parser`).

The `main()` function in `cobolparser/cli/parse.py` provides backward compatibility: if the first positional argument is not a recognized subcommand, it prepends `parse`, so `cobol-parser foo.cbl` is treated as `cobol-parser parse foo.cbl`.

## Subcommands

### `parse <file.cbl> [path] [flags]`

Parse a single COBOL file and print the AST to JSON.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `path` | positional | `None` | Dot-separated AST path (e.g., `procedure.MAIN-LOGIC`). If provided, returns that subtree instead of the full AST. |
| `--compact` | bool | `False` | Compact JSON output (no indentation) |
| `--free-form` | bool | `False` | Treat input as free-form COBOL (skip fixed-format normalization) |
| `--dialect` | choice | `ibm-enterprise` | COBOL dialect (currently only `ibm-enterprise` is supported) |
| `--error-recovery` | choice | `collect-all` | Error recovery mode: `fail-fast` or `collect-all` |
| `--copybook-path` | string (repeatable) | `[]` | Directory to search for copybooks (can be specified multiple times) |
| `--define` | string (repeatable) | `[]` | Define a conditional compilation symbol (format: `SYMBOL` or `SYMBOL=VALUE`, repeatable) |
| `--output`, `-o` | string | `None` | Write output to FILE instead of stdout |
| `--errors` | bool | `False` | Include parse errors and warnings in output (wraps AST in `{"ast": ..., "errors": [...], "warnings": [...]}`) |
| `--stats` | bool | `False` | Include parse statistics (lines, tokens, parse time, peak memory) |
| `--find-type` | string | `None` | Find all AST nodes of the given type (e.g., `MoveStatement`) and return as a list |
| `--profile` | bool | `False` | Profile the parse and include timing/memory metrics (cProfile, tracemalloc) |
| `--profile-top-n` | int | `20` | Number of top functions to include in profiling output |
| `--profile-output` | string | `None` | Write cProfile binary to PATH (`.prof` file for single-file parse) |

Examples:
```bash
cobol-parser parse examples/cobol/hello.cbl
cobol-parser parse examples/cobol/hello.cbl procedure.MAIN-LOGIC
cobol-parser parse examples/cobol/hello.cbl --dialect ibm-enterprise --stats
cobol-parser parse examples/cobol/hello.cbl --find-type MoveStatement --compact
cobol-parser parse examples/cobol/hello.cbl --profile --profile-top-n 10
cobol-parser parse examples/cobol/hello.cbl --copybook-path ./copybooks --define DEBUG=1
```

### `batch <file1.cbl> [file2.cbl ...] [flags]`

Parse multiple files in parallel using `ProcessPoolExecutor` and output combined results (array of results per file).

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `files` | positional | `[]` | Paths to COBOL source files (optional if `--glob` provided) |
| `--glob` | string (repeatable) | `[]` | Glob pattern to collect source files (e.g., `src/**/*.cbl`, repeatable, sorted results) |
| `--workers` | int | `None` | Number of worker processes (default: CPU count) |
| `--encoding` | string | `utf-8` | File encoding for input files |
| `--compact` | bool | `False` | Compact JSON output |
| `--dialect` | choice | `ibm-enterprise` | COBOL dialect |
| `--error-recovery` | choice | `collect-all` | Error recovery mode |
| `--output`, `-o` | string | `None` | Write output to FILE |
| `--errors` | bool | `False` | Include errors/warnings per file |
| `--stats` | bool | `False` | Include parse statistics per file |
| `--profile` | bool | `False` | Profile each parse |
| `--profile-top-n` | int | `20` | Top N functions in profiling output |
| `--profile-output` | string | `None` | Write cProfile binaries to directory (must be directory path, not `.prof` file) |

Examples:
```bash
cobol-parser batch src/*.cbl --stats
cobol-parser batch src/prog1.cbl src/prog2.cbl --compact
cobol-parser batch --glob "examples/**/*.cbl" --workers 4
cobol-parser batch --glob "src/**/*.cbl" --errors --dialect ibm-enterprise
```

### `tokenize <file.cbl> [flags]`

Tokenize a COBOL source file and print token stream as JSON array.

Each token is output as `{"type": "TOKEN_NAME", "value": "...", "line": N, "column": N}`.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `file` | positional | | Path to the COBOL source file |
| `--compact` | bool | `False` | Compact JSON output |
| `--free-form` | bool | `False` | Treat input as free-form |
| `--dialect` | choice | `ibm-enterprise` | COBOL dialect |
| `--output`, `-o` | string | `None` | Write output to FILE |

Examples:
```bash
cobol-parser tokenize src/PAYROLL.cbl
cobol-parser tokenize src/PAYROLL.cbl --compact
cobol-parser tokenize src/PAYROLL.cbl --output tokens.json
```

### `preprocess <file.cbl> [flags]`

Preprocess COBOL source: normalize fixed-format to free-form, expand conditional compilation symbols, strip compiler directives. Prints to stdout.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `file` | positional | | Path to the COBOL source file |
| `--free-form` | bool | `False` | Skip fixed-format normalization (input is already free-form) |
| `--define` | string (repeatable) | `[]` | Conditional compilation symbols (format: `SYMBOL` or `SYMBOL=VALUE`) |
| `--strip-directives` | bool | `False` | Strip PROCESS/CBL compiler directives before normalizing |

Examples:
```bash
cobol-parser preprocess src/PAYROLL.cbl
cobol-parser preprocess src/PAYROLL.cbl --define DEBUG=1 --define PROD=0
cobol-parser preprocess src/PAYROLL.cbl --strip-directives
```

### `expand <file.cbl> --copybook-path <dir> [flags]`

Expand COPY statements inline; outputs expansion result as JSON (containing original + expanded source, diagnostics, statistics).

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `file` | positional | | Path to the COBOL source file |
| `--copybook-path` | string (repeatable) | `[]` | Directory to search for copybooks (repeatable) |
| `--compact` | bool | `False` | Compact JSON output |
| `--max-depth` | int | `100` | Maximum copybook nesting depth |
| `--define` | string (repeatable) | `[]` | Conditional compilation symbols |
| `--output`, `-o` | string | `None` | Write output to FILE |

Examples:
```bash
cobol-parser expand src/PAYROLL.cbl --copybook-path ./copybooks
cobol-parser expand src/PAYROLL.cbl --copybook-path ./copybooks --copybook-path ./vendor --max-depth 50
```

### `analyze <file.cbl> [flags]`

Analyze dynamic CALL targets in COBOL source. Outputs JSON report with `calls` array showing called programs and possible values for dynamic calls.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `file` | positional | | Path to the COBOL source file |
| `--compact` | bool | `False` | Compact JSON output |
| `--free-form` | bool | `False` | Treat input as free-form |
| `--dialect` | choice | `ibm-enterprise` | COBOL dialect |
| `--error-recovery` | choice | `collect-all` | Error recovery mode |
| `--copybook-path` | string (repeatable) | `[]` | Directories for copybooks |
| `--define` | string (repeatable) | `[]` | Conditional symbols |
| `--output`, `-o` | string | `None` | Write output to FILE |
| `--profile` | bool | `False` | Profile the parse |
| `--profile-top-n` | int | `20` | Top N functions |
| `--profile-output` | string | `None` | Write cProfile binary to PATH |

Examples:
```bash
cobol-parser analyze src/PAYROLL.cbl
cobol-parser analyze src/PAYROLL.cbl --profile
```

### `dead-code <file.cbl> [flags]`

Detect unreferenced paragraphs and sections (dead code). Outputs JSON report with `dead_items` array.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `file` | positional | | Path to the COBOL source file |
| `--compact` | bool | `False` | Compact JSON output |
| `--free-form` | bool | `False` | Treat input as free-form |
| `--dialect` | choice | `ibm-enterprise` | COBOL dialect |
| `--error-recovery` | choice | `collect-all` | Error recovery mode |
| `--copybook-path` | string (repeatable) | `[]` | Directories for copybooks |
| `--define` | string (repeatable) | `[]` | Conditional symbols |
| `--output`, `-o` | string | `None` | Write output to FILE |
| `--profile` | bool | `False` | Profile the parse |
| `--profile-top-n` | int | `20` | Top N functions |
| `--profile-output` | string | `None` | Write cProfile binary to PATH |

Examples:
```bash
cobol-parser dead-code src/PAYROLL.cbl
cobol-parser dead-code src/PAYROLL.cbl --compact
```

### `program-flow <file.cbl> [flags]`

Display program control flow graph (paragraphs, PERFORM, GO TO, CALL, fall-through edges). Supports multiple output formats.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `file` | positional | | Path to the COBOL source file |
| `--format` | choice | `json` | Output format: `json`, `mermaid` (Mermaid flowchart), or `dot` (Graphviz DOT) |
| `--compact` | bool | `False` | Compact JSON output (only applies to `--format json`) |
| `--free-form` | bool | `False` | Treat input as free-form |
| `--dialect` | choice | `ibm-enterprise` | COBOL dialect |
| `--error-recovery` | choice | `collect-all` | Error recovery mode |
| `--copybook-path` | string (repeatable) | `[]` | Directories for copybooks |
| `--define` | string (repeatable) | `[]` | Conditional symbols |
| `--output`, `-o` | string | `None` | Write output to FILE |
| `--profile` | bool | `False` | Profile the parse |
| `--profile-top-n` | int | `20` | Top N functions |
| `--profile-output` | string | `None` | Write cProfile binary to PATH |

Examples:
```bash
cobol-parser program-flow src/PAYROLL.cbl
cobol-parser program-flow src/PAYROLL.cbl --format mermaid --output flow.mermaid
cobol-parser program-flow src/PAYROLL.cbl --format dot --output flow.dot
```

### `generate-tests <file.cbl> -o <output.cut> [flags]`

Generate CobolCheck unit test stubs from program structure. Outputs `.cut` (COBOL Unit Test) format.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `file` | positional | | Path to the COBOL source file |
| `--output`, `-o` | string | `None` | Output `.cut` file path (default: stdout) |
| `--strategy` | choice (repeatable) | `None` | Coverage strategy: `paragraph`, `branch`, `boundary` (repeatable; if omitted, all strategies used) |
| `--free-form` | bool | `False` | Treat input as free-form |
| `--dialect` | choice | `ibm-enterprise` | COBOL dialect |
| `--error-recovery` | choice | `collect-all` | Error recovery mode |
| `--copybook-path` | string (repeatable) | `[]` | Directories for copybooks |
| `--define` | string (repeatable) | `[]` | Conditional symbols |

Examples:
```bash
cobol-parser generate-tests src/PAYROLL.cbl -o tests/PAYROLL.cut
cobol-parser generate-tests src/PAYROLL.cbl --strategy paragraph --strategy branch -o tests/PAYROLL.cut
```

### `io-sequence <file.cbl> [flags]`

Validate I/O operation sequencing (OPEN before READ/WRITE, CLOSE after operations, etc.). Outputs JSON report with `violations` array.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `file` | positional | | Path to the COBOL source file |
| `--compact` | bool | `False` | Compact JSON output |
| `--free-form` | bool | `False` | Treat input as free-form |
| `--dialect` | choice | `ibm-enterprise` | COBOL dialect |
| `--error-recovery` | choice | `collect-all` | Error recovery mode |
| `--copybook-path` | string (repeatable) | `[]` | Directories for copybooks |
| `--define` | string (repeatable) | `[]` | Conditional symbols |
| `--output`, `-o` | string | `None` | Write output to FILE |

Examples:
```bash
cobol-parser io-sequence src/PAYROLL.cbl
cobol-parser io-sequence src/PAYROLL.cbl --compact
```

### `move-type-check <file.cbl> [flags]`

Validate MOVE statement source/destination type compatibility (numeric vs. alphanumeric, etc.). Outputs JSON report with `violations` array.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `file` | positional | | Path to the COBOL source file |
| `--compact` | bool | `False` | Compact JSON output |
| `--free-form` | bool | `False` | Treat input as free-form |
| `--dialect` | choice | `ibm-enterprise` | COBOL dialect |
| `--error-recovery` | choice | `collect-all` | Error recovery mode |
| `--copybook-path` | string (repeatable) | `[]` | Directories for copybooks |
| `--define` | string (repeatable) | `[]` | Conditional symbols |
| `--output`, `-o` | string | `None` | Write output to FILE |

Examples:
```bash
cobol-parser move-type-check src/PAYROLL.cbl
```

### `linkage-check <file.cbl> [flags]`

Validate LINKAGE SECTION items against CALL/ENTRY USING clauses. Outputs JSON report with `violations` array.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `file` | positional | | Path to the COBOL source file |
| `--compact` | bool | `False` | Compact JSON output |
| `--free-form` | bool | `False` | Treat input as free-form |
| `--dialect` | choice | `ibm-enterprise` | COBOL dialect |
| `--error-recovery` | choice | `collect-all` | Error recovery mode |
| `--copybook-path` | string (repeatable) | `[]` | Directories for copybooks |
| `--define` | string (repeatable) | `[]` | Conditional symbols |
| `--output`, `-o` | string | `None` | Write output to FILE |

Examples:
```bash
cobol-parser linkage-check src/PAYROLL.cbl
```

### `language-env <file.cbl> [flags]`

Detect IBM Language Environment function calls and COBOL intrinsic functions. Outputs JSON report.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `file` | positional | | Path to the COBOL source file |
| `--compact` | bool | `False` | Compact JSON output |
| `--free-form` | bool | `False` | Treat input as free-form |
| `--dialect` | choice | `ibm-enterprise` | COBOL dialect |
| `--error-recovery` | choice | `collect-all` | Error recovery mode |
| `--copybook-path` | string (repeatable) | `[]` | Directories for copybooks |
| `--define` | string (repeatable) | `[]` | Conditional symbols |
| `--output`, `-o` | string | `None` | Write output to FILE |

Examples:
```bash
cobol-parser language-env src/PAYROLL.cbl
cobol-parser language-env src/PAYROLL.cbl --compact
```

### `ims-dli <file.cbl> [flags]`

Analyze IMS DLI calls (CBLTDLI, AIBTDLI, CEETDLI) and extract segment references. Outputs JSON report with `dli_calls` array, entry points, and segment names.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `file` | positional | | Path to the COBOL source file |
| `--compact` | bool | `False` | Compact JSON output |
| `--free-form` | bool | `False` | Treat input as free-form |
| `--dialect` | choice | `ibm-enterprise` | COBOL dialect |
| `--error-recovery` | choice | `collect-all` | Error recovery mode |
| `--copybook-path` | string (repeatable) | `[]` | Directories for copybooks |
| `--define` | string (repeatable) | `[]` | Conditional symbols |
| `--output`, `-o` | string | `None` | Write output to FILE |

Examples:
```bash
cobol-parser ims-dli src/PAYROLL.cbl
cobol-parser ims-dli src/PAYROLL.cbl --compact
```

## Coverage Subcommands (`cli/coverage.py`)

The coverage CLI is a separate tool accessible as `python -m cobolparser.cli.coverage` or via direct import. It provides machine-readable and human-readable IO coverage reporting.

### `python -m cobolparser.cli.coverage status [flags]`

Show IO coverage status (filtered by verb/qualifier).

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--artifact` | string | `io-coverage.json` | Path to coverage artifact JSON |
| `--verb` | string | `None` | Filter by verb (e.g., `OPEN`, `READ`, `WRITE`) |
| `--qualifier` | string | `None` | Filter by qualifier (e.g., `AT END`, `INVALID KEY`) |
| `--format` | choice | `table` | Output format: `table` (human-readable) or `json` |

Examples:
```bash
python -m cobolparser.cli.coverage status
python -m cobolparser.cli.coverage status --verb OPEN --format json
python -m cobolparser.cli.coverage status --artifact coverage.json --verb READ
```

### `python -m cobolparser.cli.coverage generate [flags]`

Generate coverage artifact from pytest results.

| Flag | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `--pytest-results` | string | Yes | | Path to pytest results JSON file |
| `--output` | string | No | `io-coverage.json` | Path for output artifact |
| `--catalog` | string | No | | Path to IO variation catalog CSV |
| `--schema` | string | No | | Path to coverage schema JSON |

Examples:
```bash
python -m cobolparser.cli.coverage generate --pytest-results results.json
python -m cobolparser.cli.coverage generate --pytest-results results.json --output coverage.json --catalog catalog.csv
```

### `python -m cobolparser.cli.coverage validate [flags]`

Validate coverage artifact against schema.

| Flag | Type | Required | Description |
|------|------|----------|-------------|
| `--artifact` | string | Yes | Path to coverage artifact JSON |

Examples:
```bash
python -m cobolparser.cli.coverage validate --artifact io-coverage.json
```

### `python -m cobolparser.cli.coverage render [flags]`

Render coverage artifact as Markdown, CSV, or summary text.

| Flag | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `--input` | string | Yes | | Path to coverage artifact JSON |
| `--output` | string | No | `None` (stdout) | Path for output file |
| `--format` | choice | No | `markdown` | Output format: `markdown`, `csv`, or `summary` |

Examples:
```bash
python -m cobolparser.cli.coverage render --input io-coverage.json
python -m cobolparser.cli.coverage render --input io-coverage.json --output report.md --format markdown
python -m cobolparser.cli.coverage render --input io-coverage.json --format csv --output coverage.csv
```

## Gotchas / Invariants

### Dialect Flag
- `--dialect ibm-enterprise` (the only currently supported dialect) enables EXEC SQL, EXEC CICS, EXEC IMS DLI parsing, IBM data types (COMP-3, COMP-1, COMP-2), and IBM intrinsic functions. Without this flag, EXEC blocks may cause parse errors.

### Batch Processing
- `batch` uses `ProcessPoolExecutor` internally; on Windows, ensure the calling script is protected with `if __name__ == "__main__"` if calling `parse_files()` programmatically.
- File deduplication occurs before parsing (based on canonical/resolved paths), so redundant arguments like `./a.cbl` and `a.cbl` parse only once.
- `--profile-output` in batch mode must be a directory path, not a `.prof` file (single-file format is only for `parse` subcommand).

### Backward Compatibility
- If the first positional argument is not a recognized subcommand name, `cobol-parser` automatically prepends `parse`. For example, `cobol-parser foo.cbl` becomes `cobol-parser parse foo.cbl`.

### JSON Path Resolution
- The `parse` subcommand supports dot-separated paths with bracket notation: `procedure.MAIN-LOGIC`, `procedure.MAIN-LOGIC.0`, `data.working-storage[0].picture`.
- Paths are case-insensitive for division/section/paragraph names (internally uppercased).

### Error Recovery Modes
- `fail-fast`: Parser halts on first error; `result.ast` is `None`.
- `collect-all` (default): Parser collects all errors and warnings; `result.ast` may be partial but non-None.

### Profiling Output
- With `--profile`, output includes a `profiling` dict containing `wall_clock_seconds`, `cpu_seconds`, `peak_memory_mb`, and `function_profiles` (top N entries).
- cProfile binary output (`--profile-output`) is written as `.prof` files (single parse) or `.prof` files per file (batch).

### Conditional Compilation
- `--define` accepts `SYMBOL` (becomes `SYMBOL=TRUE`) or `SYMBOL=VALUE`.
- Symbols are case-sensitive in expansion.

### Free-Form Parsing
- `--free-form` skips fixed-format column normalization (columns 1–6, 7 indicator, 8–11 Area A, 12–72 Area B).
- If input is genuinely free-form and `--free-form` is omitted, the fixed-format normalizer still runs (and may misbehave on non-tabular input).

## Refresh Checklist

- [ ] Verify all 14 subcommands are listed (parse, batch, tokenize, preprocess, expand, analyze, dead-code, program-flow, generate-tests, io-sequence, move-type-check, linkage-check, language-env, ims-dli)
- [ ] Check that `--dialect ibm-enterprise` is mentioned in at least one subcommand section
- [ ] Verify `--profile` and `--profile-top-n` are documented
- [ ] Verify all 4 coverage subcommands are listed (status, generate, validate, render)
- [ ] Check that `--copybook-path` appears in all analyzer subcommands
- [ ] Verify `--error-recovery` has both `fail-fast` and `collect-all` options
- [ ] Check that `--format` for `program-flow` lists `json`, `mermaid`, and `dot`
- [ ] Verify `--strategy` for `generate-tests` is repeatable and lists all three strategies
