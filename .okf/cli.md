---
type: Module
title: CLI
description: cobol-parser command-line subcommands and flags — entry point cobolparser.cli:main.
tags: [cli, command-line, subcommands]
timestamp: 2026-06-28T00:00:00Z
---

# Overview

Entry point: `cobol-parser` → `cobolparser.cli:main`

Source: `cobolparser/cli/parse.py` (all subcommands), `cobolparser/cli/coverage.py` (IO coverage tools).

# Subcommand Reference

## Parse

```bash
cobol-parser parse <file.cbl> [json-path] [--compact] [--free-form] \
    [--dialect ibm-enterprise] [--errors] [--stats]
```

Parses a COBOL file and prints the AST as JSON. `json-path` (dotted) extracts
a specific subtree. `--errors` shows parse errors only. `--stats` appends
`ParseStatistics`.

## Tokenize

```bash
cobol-parser tokenize <file.cbl>
```

Prints the token stream as JSON: `[{"type": "...", "value": "...", "line": N}]`.

## Preprocess

```bash
cobol-parser preprocess <file.cbl> [--define DEBUG]
```

Runs fixed-format normalisation and conditional compilation; prints the resulting
free-form text. `--define` sets compiler flags for conditional blocks.

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

Runs all static analyzers and prints a JSON summary (dead code, IO issues,
MOVE type violations, linkage violations, LE usage).

## Dead-Code

```bash
cobol-parser dead-code <file.cbl>
```

Runs `DeadCodeAnalyzer` and lists unreferenced paragraphs/sections.

## Program-Flow

```bash
cobol-parser program-flow <file.cbl>
```

Runs `ProgramFlowAnalyzer` and emits the control-flow graph as JSON edges.

## Batch

```bash
cobol-parser batch prog1.cbl prog2.cbl ... [--stats]
```

Parallel multi-file parsing via `ProcessPoolExecutor`. Prints one JSON result
per file. `--stats` appends per-file `ParseStatistics`.

## Generate-Tests

```bash
cobol-parser generate-tests <file.cbl> -o <file.cut>
```

Runs the three-stage test-generation pipeline (`CoverageAnalyzer` →
`TestPlanGenerator` → `CobolCheckGenerator`) and writes a CobolCheck `.cut` file.

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
