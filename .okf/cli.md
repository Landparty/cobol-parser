---
type: Module
title: CLI
description: cobol-parser command-line subcommands and flags — entry point cobolparser.cli:main.
tags: [cli, command-line, subcommands, output-identification]
timestamp: 2026-07-09T00:00:00Z
---

# Overview

Entry point: `cobol-parser` → `cobolparser.cli:main`

Source: `cobolparser/cli/parse.py` (all subcommands), `cobolparser/cli/coverage.py` (IO coverage tools).

# Output Identification

Every output the CLI emits is self-describing — it identifies the source it
was produced from (helper: `_identification()` in `cobolparser/cli/parse.py`;
pinned by `tests/unit/cli/test_output_identification.py`):

* **JSON documents** start with `"source_file"` (the input path as given on
  the command line). Subcommands that parse the source also emit
  `"program_id"` (the PROGRAM-ID, or `null` if the program has none) as the
  second key. Analyzer reports get both via `_emit_report(..., ast=ast)`.
* **`parse`** — full-AST output gets `"source_file"` spliced in (the AST dict
  already carries `program_name`). With `--errors`/`--stats` the wrapper is
  `{"source_file", "program_id", "ast", ...}`. Dotted-path extraction emits
  `{"source_file", "program_id", "path", "result"}`; `--find-type` emits
  `{"source_file", "program_id", "node_type", "matches"}`.
* **`tokenize`** — `{"source_file": ..., "tokens": [...]}` (previously a bare
  token list).
* **`expand`** — expansion dict prefixed with `"source_file"` (no
  `program_id`: the source is not parsed).
* **`batch`** — a JSON list; each entry carries `"path"` and, when the parse
  produced an AST, `"program_id"`.
* **Text outputs** — Mermaid flowcharts start with a `%% Program: <name>`
  comment; DOT names the digraph after the program. `preprocess`
  output is deliberately unidentified (it is transformed source meant to be
  fed onward).

# Subcommand Reference

## Parse

```bash
cobol-parser parse <file.cbl> [json-path] [--compact] [--free-form] \
    [--dialect ibm-enterprise] [--errors] [--stats] [--find-type NODE_TYPE] \
    [--profile] [--profile-top-n N] [--profile-output PATH]
```

Parses a COBOL file and prints the AST as JSON. `json-path` (dotted) extracts
a specific subtree. `--errors` shows parse errors only. `--stats` appends
`ParseStatistics`. `--find-type` finds all AST nodes of the given type (e.g.
`MoveStatement`), equivalent to `ast.find_all_by_type()`. `--profile` /
`--profile-top-n` / `--profile-output` wrap the parse in a `ProfilerContext`
(see [parser.md](parser.md)) and embed timing/memory metrics in the output, or
write a binary `.prof` to `PATH`.

Exit codes (2026-07-07): `0` clean parse; `1` hard failure (`ast is None`,
bad arguments); `2` recovered-but-errored parse — the JSON is still printed,
a summary goes to stderr. Previously the CLI exited `0` whenever an AST
existed, even with collected errors, so scripts gating on `$?` saw every
partial parse as success. `batch` likewise exits `2` when any file has a
`read_error` or `success=false`. Analyzer subcommands still exit `0` on a
partial parse but print a stderr warning that analysis may be incomplete.

## Tokenize

```bash
cobol-parser tokenize <file.cbl>
```

Prints the token stream as JSON:
`{"source_file": "...", "tokens": [{"type": "...", "value": "...", "line": N, "column": N}]}`.

## Preprocess

```bash
cobol-parser preprocess <file.cbl> [--define DEBUG]
```

Runs fixed-format normalisation and conditional compilation; prints the resulting
free-form text. `--define` sets compiler flags for conditional blocks.

All subcommands that run conditional compilation (`parse`, `preprocess`,
`expand` with `--define`) print any conditional-compilation diagnostics
(unknown `>>IF` conditions, stray `>>ELSE`/`>>END-IF`, malformed
`>>DEFINE`, unclosed `>>IF` — audit 2026-07-07 H7) to **stderr** as
`warning: ...` lines, so deleted guarded blocks are no longer silent.
`coverage status` reports malformed artifact JSON (or a non-object
artifact) with a clean error and exit code 1 instead of an uncaught
traceback (M10). `coverage generate` had the same gap (a malformed or
non-object pytest-results JSON file raised uncaught inside
`IOCoverageReporter.load_pytest_results`) — fixed the same way, audit
2026-07-08.

## Expand

```bash
cobol-parser expand <file.cbl> --copybook-path ./copybooks
```

Runs copybook expansion and prints the expanded source. `--copybook-path` may be
specified multiple times for multiple search directories.

## Analyze

```bash
cobol-parser analyze <file.cbl>
```

Runs `DynamicCallAnalyzer` and prints a JSON summary of dynamic `CALL`
targets only (`called_program`, `is_dynamic`, and `possible_values` when
dynamic). Despite the generic name, this is *not* an all-analyzers summary —
dead code, IO, MOVE-type, linkage, and LE checks each have their own
dedicated subcommand below.

## Dead-Code

```bash
cobol-parser dead-code <file.cbl>
```

Runs `DeadCodeAnalyzer` and lists unreferenced paragraphs/sections.

## Program-Flow

```bash
cobol-parser program-flow <file.cbl> [--format json|mermaid|dot] [--profile ...]
```

Runs `ProgramFlowAnalyzer` and emits the control-flow graph. `--format`
selects the output: `json` (default, raw `report.to_dict()` edges), `mermaid`
(via `generators/flowchart.py`'s `MermaidFlowchartGenerator`), or `dot`
(Graphviz DOT via `DotFlowchartGenerator`). Also accepts the shared
profiling flags (`--profile`, `--profile-top-n`, `--profile-output`).

## Batch

```bash
cobol-parser batch [prog1.cbl prog2.cbl ...] [--glob PATTERN] [--workers N] \
    [--encoding utf-8] [--stats] [--errors] [--profile ...]
```

Parallel multi-file parsing via `ProcessPoolExecutor`. Files may be given
positionally and/or collected via repeatable `--glob` patterns (e.g.
`--glob 'src/**/*.cbl'`). `--workers` sets the process-pool size (default: CPU
count). `--encoding` sets file read encoding (default `utf-8`). Prints one
JSON result per file. `--errors` includes parse errors/warnings per file;
`--stats` appends per-file `ParseStatistics`. `--profile-output` in batch mode
must be a directory (one `.prof` per file), not a single file path.

## IO-Sequence

```bash
cobol-parser io-sequence <file.cbl>
```

Runs `IOSequenceAnalyzer` and reports sequencing violations.

## Move-Type-Check

```bash
cobol-parser move-type-check <file.cbl>
```

Runs `MoveTypeChecker` and reports type-incompatible MOVE statements.

## Linkage-Check

```bash
cobol-parser linkage-check <file.cbl>
```

Runs `LinkageChecker` and reports LINKAGE SECTION violations.

## Language-Env

```bash
cobol-parser language-env <file.cbl>
```

Runs `LanguageEnvironmentAnalyzer` and reports IBM LE function/service usage.

## IMS-DLI

```bash
cobol-parser ims-dli <file.cbl>
```

Runs `IMSSegmentAnalyzer` and reports IMS DLI segment calls.

# See Also

* [analysis.md](analysis.md) — the underlying analyzers
* [parser.md](parser.md) — `parse_cobol` used by most subcommands
