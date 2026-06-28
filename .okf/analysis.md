---
type: Module Reference
title: Analysis
description: 15 post-parse analysis modules covering dead code, program flow, IO sequencing, CRUD matrix, and more.
tags: [analysis, static-analysis, dead-code, program-flow, crud, io-sequence, host-variables]
timestamp: 2026-06-28T00:00:00Z
---

# Analysis

> 15 post-parse analysis modules. 13 expose the standard `Analyzer().analyze(ast) -> Report` shape; 2 (`io_coverage_reporter` and `io_diagnostics`) are specialized utilities. One analyzer, `HostVariableResolver`, uses `.resolve(ast)` instead of `.analyze(ast)`.

## Files

| File | Purpose |
|------|---------|
| `cobolparser/analysis/__init__.py` | Lazy-loaded exports for all analyzers and report types |
| `cobolparser/analysis/dead_code.py` | Unreferenced paragraph/section detection |
| `cobolparser/analysis/value_tracker.py` | Value flow for dynamic CALL target analysis |
| `cobolparser/analysis/program_flow.py` | Control flow graph: edges typed by transfer mechanism |
| `cobolparser/analysis/io_logger.py` | I/O operation inventory |
| `cobolparser/analysis/io_sequence.py` | I/O sequence state-machine validation |
| `cobolparser/analysis/io_coverage_reporter.py` | Machine-readable I/O coverage artifacts from pytest results (not a standard analyzer) |
| `cobolparser/analysis/io_diagnostics.py` | I/O error codes and diagnostic helpers (not a standard analyzer; static methods only) |
| `cobolparser/analysis/move_type_checker.py` | MOVE statement type compatibility validation |
| `cobolparser/analysis/linkage_checker.py` | LINKAGE SECTION usage validation |
| `cobolparser/analysis/language_env_analyzer.py` | IBM Language Environment CALL detection |
| `cobolparser/analysis/host_var_resolver.py` | SQL host variable resolution |
| `cobolparser/analysis/crud_matrix.py` | File/table CRUD matrix generation |
| `cobolparser/analysis/ims_segment_analyzer.py` | IMS DLI call and segment analysis |
| `cobolparser/analysis/coverage_analyzer.py` | Test coverage branch point analysis |
| `cobolparser/analysis/test_plan.py` | Test plan generation from coverage map |

## Analyzer Reference

### DeadCodeAnalyzer

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> DeadCodeReport`
- **Output:** `DeadCodeReport` with `dead_items: list[DeadCodeItem]`
  - `DeadCodeItem`: `name: str`, `procedure_type: str` (PARAGRAPH|SECTION), `location: SourceLocation | None`
- **What it finds:** Paragraphs and sections never referenced by PERFORM, GO TO, or CALL

### ProgramFlowAnalyzer

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> ProgramFlowReport`
- **Output:** `ProgramFlowReport` with `nodes: list[FlowNode]`, `edges: list[FlowEdge]`, `cycle_details`, `range_members: dict[str, list[str]]`
  - `FlowEdge`: `source: str`, `target: str`, `edge_type: FlowEdgeType`, `location: SourceLocation | None`
  - `FlowEdgeType`: PERFORM, PERFORM_THRU, GOTO, GOTO_DEPENDING, CALL, CALL_DYNAMIC, SORT_INPUT_PROCEDURE, SORT_INPUT_PROCEDURE_THRU, SORT_OUTPUT_PROCEDURE, SORT_OUTPUT_PROCEDURE_THRU, MERGE_OUTPUT_PROCEDURE, MERGE_OUTPUT_PROCEDURE_THRU, ALTER, FALL_THROUGH, IF_BRANCH, IF_THEN, IF_ELSE, EVALUATE_BRANCH, EVALUATE_WHEN, EVALUATE_WHEN_OTHER

### DynamicCallAnalyzer

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> None` (modifies AST in-place)
- **What it does:** Tracks MOVE and VALUE clauses to resolve possible values for identifier-based CALL targets; populates `call.possible_values` on dynamic CALL statements
- **Note:** Returns None; side-effects are the key behavior

### IOLogger

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> IOLogReport`
- **Output:** `IOLogReport` with `operations: list[IOOperation]`
  - `IOOperation`: `category: str` (CALL|SQL|FILE-IO|CONSOLE-IO|ENTRY), `operation: str`, `direction: str` (INPUT|OUTPUT|BIDIRECTIONAL), `variables: list[str]`, `target: str | None`, `location: SourceLocation | None`

### IOSequenceAnalyzer

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> IOSequenceReport`
- **Output:** `IOSequenceReport` with `violations: list[IOSequenceViolation]`
  - `IOViolationKind`: READ_BEFORE_OPEN, WRITE_BEFORE_OPEN, REWRITE_BEFORE_OPEN, DELETE_BEFORE_OPEN, START_BEFORE_OPEN, DOUBLE_OPEN, CLOSE_NOT_OPEN, DOUBLE_CLOSE, FILE_LEFT_OPEN

### MoveTypeChecker

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> MoveTypeReport`
- **Output:** `MoveTypeReport` with `violations: list[MoveTypeViolation]`
  - `DataCategory`: NUMERIC, NUMERIC_EDITED, ALPHABETIC, ALPHANUMERIC, ALPHANUMERIC_EDITED, FIGURATIVE, UNKNOWN
  - `MoveViolationKind`: ERROR, WARNING

### LinkageChecker

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> LinkageReport`
- **Output:** `LinkageReport` with `violations: list[LinkageViolation]`
  - `LinkageViolationKind`: TOO_MANY_ARGS, TOO_FEW_ARGS, VALUE_TO_LINKAGE, UNREFERENCED_LINKAGE, UNKNOWN_ENTRY

### LanguageEnvironmentAnalyzer

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> LEAnalysisResult`
- **Output:** `LEAnalysisResult` with `le_functions: list[LEFunctionUsage]`, `service_calls: list[LEServiceCall]`
- **What it finds:** CALL statements to IBM LE functions (CEE*, IGZEDT*, etc.)

### CRUDMatrixGenerator

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> CRUDMatrix`
- **Output:** `CRUDMatrix` with `entries: list[FileEntry | TableEntry]`, `.to_csv()`, `.to_json()` methods
- **Scope:** Tracks file-level operations (OPEN/READ/WRITE/REWRITE/DELETE) only; does NOT analyze SQL DML

### HostVariableResolver

- **Input:** `CobolProgram`
- **Method:** `.resolve(ast) -> HostVarResolutionReport` ← **Note: `.resolve()` not `.analyze()`**
- **Output:** `HostVarResolutionReport` with `resolved: dict[str, HostVariableInfo]`, `unresolved: set[str]`, `declare_tables: dict[str, DeclareTableStatement]`, `column_name_collisions: dict[str, list[str]]`
- **What it finds:** Correlates SQL host variables (`:name`) to their COBOL data item definitions and optional DB2 DECLARE TABLE columns

### IMSSegmentAnalyzer

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> list[IMSDLICall]`
- **Output:** list of `IMSDLICall` objects with `function_code`, `pcb_name`, `segment_name`, `location`
- **Also identifies:** `IMSEntryPoint` objects (ENTRY 'DLITCBL' USING)

### CoverageAnalyzer

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> CoverageMap`
- **Output:** `CoverageMap` with `branch_points: list[BranchPoint]` keyed by paragraph/section

### TestPlanGenerator

- **Input:** `CoverageMap`
- **Method:** `.generate(coverage_map) -> TestPlan` (not `.analyze()`)
- **Output:** `TestPlan` with test case specifications per branch type and coverage strategy

### IOCoverageReporter (Special: not a standard analyzer)

- **Input:** pytest results (JSON or JUnit XML) + catalog path
- **Methods:** `.generate_artifact()`, `.generate_report()` (not `.analyze()`)
- **Purpose:** Machine-readable coverage artifacts mapped to IBM COBOL I/O variation catalog

### IODiagnosticHelper (Special: not a standard analyzer)

- **Type:** Static helper class
- **Methods:** `.get_error_message(code)`, `.create_io_error(code, line, column, context)`, `.validate_io_statement_type(statement_type, file_organization)`
- **Purpose:** Diagnostic helpers for I/O statement validation; used by parser and analyzers

## Top-Level Pipeline (test generation)

```python
from cobolparser import generate_cobolcheck_tests

output = generate_cobolcheck_tests(source, strategies=["paragraph", "branch", "boundary"])

# Internally:
# 1. Parse source → CobolProgram AST
# 2. CoverageAnalyzer().analyze(ast) → CoverageMap
# 3. TestPlanGenerator().generate(coverage_map) → TestPlan
# 4. CobolCheckGenerator() writes .cut file
```

## Public API (Exported Symbols)

```python
from cobolparser import (
    # Analyzers
    DeadCodeAnalyzer, ProgramFlowAnalyzer, DynamicCallAnalyzer,
    IOLogger, IOSequenceAnalyzer, MoveTypeChecker,
    LinkageChecker, LanguageEnvironmentAnalyzer, CRUDMatrixGenerator,
    CoverageAnalyzer, TestPlanGenerator,
    # Report types
    DeadCodeReport, ProgramFlowReport, IOLogReport, IOSequenceReport,
    MoveTypeReport, LinkageReport, LEAnalysisResult,
    CRUDMatrix, CoverageMap, TestPlan,
    # Utility
    generate_cobolcheck_tests,
)
from cobolparser.analysis import (
    IMSSegmentAnalyzer, HostVariableResolver,
    IMSDLICall, IMSEntryPoint, HostVarResolutionReport, HostVariableInfo,
    IOCoverageReporter, IODiagnosticHelper, IOErrorCode,
)
```

## Gotchas / Invariants

1. **HostVariableResolver.resolve()** — the only analyzer using `.resolve()` instead of `.analyze()`. This is deliberate (SQL-specific naming).
2. **DynamicCallAnalyzer returns None** — modifies the AST in-place by populating `call.possible_values` on `CallStatement` nodes.
3. **Analyzers are stateless** — create a new instance per program, or call `.analyze()` with a fresh AST each time. Instance state is reset on each `.analyze()` call.
4. **DynamicCallAnalyzer is conservative** — only tracks MOVE-to-identifier assignments and literal VALUES clauses; does NOT execute the program.
5. **CRUDMatrixGenerator file-only scope** — does NOT analyze SQL DML (INSERT/UPDATE/DELETE). Separate analysis handles SQL.
6. **IOCoverageReporter is not an analyzer** — ingests pytest results (JSON/XML); does not follow `.analyze(ast) -> Report` shape.
7. **IODiagnosticHelper is static only** — use static methods directly.
8. **IOViolationKind.FILE_LEFT_OPEN** — fires at STOP RUN / GOBACK / end-of-program; warning-level, not always an error.
9. **Lazy imports in analysis.__init__** — analyzers are imported only on first access to avoid circular dependencies with `cobolparser.plugins`.

## Refresh Checklist

- [ ] Verify analyzer count in `analysis/__init__.py` — should be 13 standard + 2 special (15 total)
- [ ] Check `HostVariableResolver` still uses `.resolve()` not `.analyze()`
- [ ] Check `FlowEdgeType` enum values in `program_flow.py` — ensure PERFORM_THRU, GOTO_DEPENDING, ALTER, IF_BRANCH variants are current
- [ ] Verify `generate_cobolcheck_tests()` is still exported from top-level `__init__.py`
- [ ] Check `DeadCodeItem.procedure_type` (not `item_type`)
- [ ] Check `IOOperation` fields: `category`, `operation`, `direction`, `variables`, `target`
- [ ] Look for new analyzer classes in `analysis/__init__.py` not listed here
