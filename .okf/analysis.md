---
type: Module
title: Static Analysis
description: 15 static-analysis modules — dead code, program flow, IO sequence, move-type, linkage, CRUD, test generation, and more.
tags: [analysis, dead-code, program-flow, io, crud, test-generation]
timestamp: 2026-06-28T00:00:00Z
---

# Overview

`cobolparser/analysis/` — 15 static-analysis modules. All follow the same
`<Analyzer>().analyze(ast) -> <Report>` shape, except `HostVariableResolver`
which uses `.resolve(ast)`.

# Public API

```python
from cobolparser import (
    DeadCodeAnalyzer,
    ProgramFlowAnalyzer,
    IOLogger,
    IOSequenceAnalyzer,
    MoveTypeChecker,
    LinkageChecker,
    LanguageEnvironmentAnalyzer,
    CRUDMatrixGenerator,
    CoverageAnalyzer,
    TestPlanGenerator,
    CobolCheckGenerator,         # from cobolparser.generators
    DynamicCallAnalyzer,
    generate_cobolcheck_tests,   # convenience wrapper
)
from cobolparser.analysis import IMSSegmentAnalyzer, HostVariableResolver
```

# Analyzer Reference

## DeadCodeAnalyzer

```python
report: DeadCodeReport = DeadCodeAnalyzer().analyze(ast)
# report.dead_items: list[DeadCodeItem]
```

Detects unreferenced paragraphs and sections (paragraphs/sections never the
target of a PERFORM, GO TO, or fall-through control flow).

## ProgramFlowAnalyzer

```python
report: ProgramFlowReport = ProgramFlowAnalyzer().analyze(ast)
# report.edges: list[FlowEdge]  (typed: PERFORM / GO_TO / CALL / FALL_THROUGH)
# report.nodes: list[FlowNode]
```

Produces a control-flow graph. Edge types:
- `FlowEdgeType.PERFORM` — PERFORM target
- `FlowEdgeType.GO_TO` — unconditional/conditional GO TO
- `FlowEdgeType.CALL` — static CALL (target known at parse time)
- `FlowEdgeType.FALL_THROUGH` — sequential paragraph fall-through

THRU ranges expand to `range_members`; cycles are classified in `cycle_details`.

## IOLogger

```python
report: IOLogReport = IOLogger().analyze(ast)
# report.operations: list[IOOperation]
```

Records every IO statement (OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START,
ACCEPT, DISPLAY, UNLOCK) in execution order with file name and paragraph context.

## IOSequenceAnalyzer

```python
report: IOSequenceReport = IOSequenceAnalyzer().analyze(ast)
# report.violations: list[IOSequenceViolation]
# IOViolationKind: READ_WITHOUT_OPEN, WRITE_WITHOUT_OPEN, CLOSE_WITHOUT_OPEN, …
```

Validates that IO operations follow legal COBOL sequencing rules (file must be
opened before read/write, etc.).

## MoveTypeChecker

```python
report: MoveTypeReport = MoveTypeChecker().analyze(ast)
# report.violations: list[MoveTypeViolation]
# MoveViolationKind: NUMERIC_TO_ALPHANUMERIC, ALPHANUMERIC_TO_NUMERIC, …
```

Detects MOVE statements with type-incompatible sending/receiving fields based on
PICTURE clause categories.

## LinkageChecker

```python
report: LinkageReport = LinkageChecker().analyze(ast)
# report.violations: list[LinkageViolation]
# LinkageViolationKind: MISSING_USING_CLAUSE, UNDEFINED_LINKAGE_ITEM, …
```

Validates LINKAGE SECTION items against the PROCEDURE DIVISION USING clause.

## LanguageEnvironmentAnalyzer

```python
result: LEAnalysisResult = LanguageEnvironmentAnalyzer().analyze(ast)
# result.le_functions: list[LEFunctionUsage]   — CEE* calls
# result.service_calls: list[LEServiceCall]    — IBM LE runtime calls
```

Detects IBM Language Environment function calls (CEEGTST, CEEMGET, etc.) and
LE service calls.

## CRUDMatrixGenerator

```python
matrix: CRUDMatrix = CRUDMatrixGenerator().analyze(ast)
# matrix.entries: list[CRUDFlags]
matrix.to_csv()
matrix.to_json()
```

Generates a CRUD matrix of file operations (Create/Read/Update/Delete) per
paragraph.

## DynamicCallAnalyzer

```python
from cobolparser.analysis import DynamicCallAnalyzer
DynamicCallAnalyzer().analyze(ast)   # mutates ast, annotating dynamic CALL targets
```

Tracks possible values for variables used in dynamic CALL statements via MOVE
and VALUE clause analysis.

## IMSSegmentAnalyzer

```python
from cobolparser.analysis import IMSSegmentAnalyzer
result = IMSSegmentAnalyzer().analyze(ast)
```

Analyses IMS DLI segment calls (EXEC DLI GU/GN/ISRT/DLET/REPL).

## HostVariableResolver

```python
from cobolparser.analysis import HostVariableResolver
resolved = HostVariableResolver().resolve(ast)   # note: .resolve(), not .analyze()
```

Resolves SQL host variables (`:var-name`) in EXEC SQL blocks against WORKING-STORAGE
definitions.

## CoverageAnalyzer + TestPlanGenerator + CobolCheckGenerator

Three-stage test-generation pipeline:

```python
from cobolparser.analysis.coverage_analyzer import CoverageAnalyzer
from cobolparser.analysis.test_plan import TestPlanGenerator
from cobolparser.generators.cobolcheck import CobolCheckGenerator

coverage_map: CoverageMap = CoverageAnalyzer().analyze(ast)
test_plan: TestPlan     = TestPlanGenerator(strategies=["paragraph","branch","boundary"]).generate(coverage_map)
cut_content: str        = CobolCheckGenerator().generate(test_plan)

# Or, one-shot convenience:
from cobolparser import generate_cobolcheck_tests
cut_content = generate_cobolcheck_tests(source, strategies=["paragraph","branch","boundary"])
```

# Module File Map

| File | Analyzer |
|------|---------|
| `value_tracker.py` | `DynamicCallAnalyzer` |
| `io_coverage_reporter.py` | `CoverageStatus`, `TestType` — machine-readable IO coverage |
| `io_diagnostics.py` | IO operation diagnostics |
| `io_logger.py` | `IOLogger` |
| `io_sequence.py` | `IOSequenceAnalyzer` |
| `coverage_analyzer.py` | `CoverageAnalyzer` |
| `crud_matrix.py` | `CRUDMatrixGenerator` |
| `dead_code.py` | `DeadCodeAnalyzer` |
| `host_var_resolver.py` | `HostVariableResolver` |
| `ims_segment_analyzer.py` | `IMSSegmentAnalyzer` |
| `language_env_analyzer.py` | `LanguageEnvironmentAnalyzer` |
| `linkage_checker.py` | `LinkageChecker` |
| `move_type_checker.py` | `MoveTypeChecker` |
| `program_flow.py` | `ProgramFlowAnalyzer` |
| `test_plan.py` | `TestPlanGenerator` |

# See Also

* [ast-models.md](ast-models.md) — input AST structure
* [cli.md](cli.md) — CLI wrappers for the most common analyzers
* [tests.md](tests.md) — `tests/unit/analysis/` covers each analyzer
