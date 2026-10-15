---
okf_version: "0.1"
---

# cobol-parser OKF Bundle

Knowledge bundle for the **cobolparser** Python library — COBOL → AST for IBM
Enterprise COBOL, plus the static analysis, generators and z/OS JCL front end
built on top of it. Author: Samuel Dion. (The package version lives in
`pyproject.toml`, kept current by release-please; it is deliberately not
mirrored here.)

## Which file do I load?

| Task | Load |
|------|------|
| Tokenization, `TokenType`, Cython fast-path | [lexer.md](lexer.md) |
| Parser, `DivisionParserFactory`, statement parsers, `ParseResult` | [parser.md](parser.md) |
| `normalize_fixed_format`, copybook expansion, source maps | [preprocessing.md](preprocessing.md) |
| `ASTNode` hierarchy, `CobolProgram`, `to_dict()` | [ast-models.md](ast-models.md) |
| Any analyzer, `LintAnalyzer`, xref, program signatures, codebase graph, SQL/CICS lint, semantic diff, business rule extraction | [analysis.md](analysis.md) |
| Dialects, EXEC SQL/CICS/IMS nodes, LE/intrinsic signatures | [dialects.md](dialects.md) |
| Flowcharts, copybook → CSV/record data, `gen-fixtures` bundles, scenarios | [generators.md](generators.md) |
| `parse_files`, `scan_files`, batch fault isolation | [batch.md](batch.md) |
| **z/OS JCL: jobs, steps, DD → dataset bindings (via jcl-parser)** | [jcl.md](jcl.md) |
| CLI subcommands and flags | [cli.md](cli.md) |
| Test layout, markers, coverage floor | [tests.md](tests.md) |
| Backend adapter dict shape, mocky-mock `ProgramFixtureGenerator` surface, field-lineage contract (summary of `interface-contract.md`) | [integration.md](integration.md) |

## How each file reads

Every topic file opens the same way: frontmatter, an **Overview** (what the
area is, its entry points, how to get started), then a **Contents** list.
Current behaviour comes first, as reference sections; dated notes
("2026-09-05 ...") further down are *rationale* -- why the code is the way it
is, and the gotchas that bit before -- not a second description of current
behaviour. When the two seem to disagree, the reference section wins; tell
the next reader by fixing the dated note.

## Core Pipeline

* [Lexer](lexer.md) — Tokenization, `TokenType`, Cython fast-path (`_lexer_fast`)
* [Parser](parser.md) — `CobolParser`, `DivisionParserFactory`, statement-parser registry, `plugins/core.py` configuration, profiling
* [Preprocessing](preprocessing.md) — `normalize_fixed_format`, copybook expansion, conditional compilation
* [AST Models](ast-models.md) — `ASTNode` hierarchy, `CobolProgram`, `to_dict()` / `to_json()`

## Analysis & Generation

* [Analysis](analysis.md) — 33 static-analysis modules plus the `program_flow/`
  package and six private helpers. Program-scoped: `DeadCodeAnalyzer`, `UnusedVariableAnalyzer`,
  `ProgramFlowAnalyzer`, `RecursionRiskAnalyzer`, `ComplexityAnalyzer`,
  `RedundancyAnalyzer`, `TechnicalDebtAnalyzer`, `XrefAnalyzer`,
  `ProgramSignatureExtractor`, `SqlCicsAnalyzer`, `DclgenChecker`,
  `LintAnalyzer`, `BusinessRuleExtractor`, … Cross-program: `CodebaseGraphBuilder` /
  `CopybookImpactAnalyzer`. Two-program: `ProgramDiffer`.
* [Dialects](dialects.md) — `IBMEnterpriseCobol`, EXEC SQL/CICS/IMS AST node types, intrinsic-function/LE-service lookups (`le_signatures.py` details live in `analysis.md`)
* [Generators](generators.md) — flowcharts (Mermaid/DOT), copybook → CSV/record-image data, the `gen-fixtures` bundle/scenario stack
* [Batch Parsing](batch.md) — `parse_files()` / `parse_files_with_copybooks()`, `scan_files()`, per-file fault isolation
* [JCL](jcl.md) — the `ddname -> dataset` binding a COBOL `SELECT ... ASSIGN
  TO` resolves through. The JCL is read by the `jcl-parser` package (optional
  extra `cobol-parser[jcl]`); `cobolparser.jcl` adapts its model.
* [CLI](cli.md) — `cobol-parser` subcommands and flags (one-table reference of all 38), the `cobol.yml` project config
* [Tests](tests.md) — Test layout, pytest markers, coverage floor (90 %)

## Integration

* [Integration Contract](integration.md) — summary of `interface-contract.md`: the dict shape `backend/src/parsers/cobol/parser.py` consumes, the mocky-mock `ProgramFixtureGenerator` / `bundle_version` surface, and the field-lineage contract

## Change History

* [log.md](log.md) — Dated update log, **newest first**

## Keeping this bundle honest

`scripts/okf_staleness_check.py` maps every source path to the OKF file that
documents it, and the pre-commit hook (`.githooks/pre-commit`) blocks a commit
that changes mapped source without touching that file. Every non-test
`.py`/`.pyx` under `cobolparser/` must appear in its `OKF_MAP`, which
`tests/test_okf_staleness_map.py` enforces — an unmapped file is one whose
documentation can rot with nothing ever asking for an update.
