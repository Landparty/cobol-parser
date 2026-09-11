---
okf_version: "0.1"
---

# cobol-parser OKF Bundle

Knowledge bundle for the **cobolparser** Python library — COBOL → AST for IBM Enterprise COBOL.
Version 1.9.0. Author: Samuel Dion.

## Core Pipeline

* [Lexer](lexer.md) — Tokenization, `TokenType`, Cython fast-path (`_lexer_fast`)
* [Parser](parser.md) — `CobolParser`, `DivisionParserFactory`, statement-parser registry
* [Preprocessing](preprocessing.md) — `normalize_fixed_format`, copybook expansion, conditional compilation
* [AST Models](ast-models.md) — `ASTNode` hierarchy, `CobolProgram`, `to_dict()` / `to_json()`

## Analysis & Generation

* [Analysis](analysis.md) — 24 static-analysis modules plus the `program_flow/` package (`DeadCodeAnalyzer`, `ProgramFlowAnalyzer`, `RecursionRiskAnalyzer`, `ComplexityAnalyzer`, `RedundancyAnalyzer`, `TechnicalDebtAnalyzer`, etc.)
* [Dialects](dialects.md) — `IBMEnterpriseCobol`, EXEC SQL/CICS/IMS AST node types, intrinsic-function/LE-service lookups (`le_signatures.py` details live in `analysis.md`)
* [Generators](generators.md) — flowcharts (Mermaid/DOT) and copybook → CSV synthetic test data
* [Batch Parsing](batch.md) — `parse_files()` / `parse_files_with_copybooks()`, per-file fault isolation
* [CLI](cli.md) — `cobol-parser` subcommands and flags
* [Tests](tests.md) — Test layout, pytest markers, coverage floor (90 %)

## Integration

* [Integration Contract](integration.md) — Dict shape returned by `cobolparser` and consumed by `backend/src/parsers/cobol/parser.py`; critical relationship paths for graph extraction

## Change History

* [log.md](log.md) — Dated update log
