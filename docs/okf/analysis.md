# Analysis

> 15 post-parse analysis modules. 13 expose the standard `Analyzer().analyze(ast) -> Report` shape; 2 (`io_coverage_reporter` and `io_diagnostics`) are specialized utilities. One analyzer, `HostVariableResolver`, uses `.resolve(ast)` instead of `.analyze(ast)`.

## Files

| File | Purpose |
|------|---------|
| `cobolparser/analysis/__init__.py` | Lazy-loaded exports for all analyzers and report types |
| `cobolparser/analysis/dead_code.py` | Unreferenced paragraph/section detection |
| `cobolparser/analysis/value_tracker.py` | Value flow for dynamic CALL target analysis |
| `cobolparser/analysis/program_flow.py` | Control flow graph: edges typed by transfer mechanism (PERFORM, GO TO, CALL, etc.) |
| `cobolparser/analysis/io_logger.py` | I/O operation inventory (calls, file I/O, SQL, console I/O) |
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
- **What it finds:** Paragraphs and sections that are never referenced by PERFORM, GO TO, or CALL

### ProgramFlowAnalyzer

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> ProgramFlowReport`
- **Output:** `ProgramFlowReport` with `nodes: list[FlowNode]`, `edges: list[FlowEdge]`, `cycle_details`, `range_members: dict[str, list[str]]`
  - `FlowEdge`: `source: str`, `target: str`, `edge_type: FlowEdgeType`, `location: SourceLocation | None`
  - `FlowEdgeType`: PERFORM, PERFORM_THRU, GOTO, GOTO_DEPENDING, CALL, CALL_DYNAMIC, SORT_INPUT_PROCEDURE, SORT_INPUT_PROCEDURE_THRU, SORT_OUTPUT_PROCEDURE, SORT_OUTPUT_PROCEDURE_THRU, MERGE_OUTPUT_PROCEDURE, MERGE_OUTPUT_PROCEDURE_THRU, ALTER, FALL_THROUGH, IF_BRANCH, IF_THEN, IF_ELSE, EVALUATE_BRANCH, EVALUATE_WHEN, EVALUATE_WHEN_OTHER
  - `BranchNode`: a paragraph with multiple outgoing edges; includes `BranchArm` objects

### DynamicCallAnalyzer

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> None` (modifies AST in-place)
- **What it does:** Tracks MOVE and VALUE clauses to resolve possible values for identifier-based CALL targets; populates `call.possible_values` on dynamic CALL statements
- **Note:** Returns None; side-effects are the key behavior

### IOLogger

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> IOLogReport`
- **Output:** `IOLogReport` with `operations: list[IOOperation]`
  - `IOOperation`: `category: str` (CALL|SQL|FILE-IO|CONSOLE-IO|ENTRY), `operation: str` (e.g., READ, WRITE), `direction: str` (INPUT|OUTPUT|BIDIRECTIONAL), `variables: list[str]`, `target: str | None`, `location: SourceLocation | None`

### IOSequenceAnalyzer

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> IOSequenceReport`
- **Output:** `IOSequenceReport` with `violations: list[IOSequenceViolation]`
  - `IOSequenceViolation`: `kind: IOViolationKind`, `file_name: str`, `location: SourceLocation | None`
  - `IOViolationKind`: READ_BEFORE_OPEN, WRITE_BEFORE_OPEN, REWRITE_BEFORE_OPEN, DELETE_BEFORE_OPEN, START_BEFORE_OPEN, DOUBLE_OPEN, CLOSE_NOT_OPEN, DOUBLE_CLOSE, FILE_LEFT_OPEN

### MoveTypeChecker

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> MoveTypeReport`
- **Output:** `MoveTypeReport` with `violations: list[MoveTypeViolation]`
  - `MoveTypeViolation`: `kind: MoveViolationKind`, `source_name: str`, `target_name: str`, `source_category: DataCategory`, `target_category: DataCategory`, `location: SourceLocation | None`, `message: str`
  - `DataCategory`: NUMERIC, NUMERIC_EDITED, ALPHABETIC, ALPHANUMERIC, ALPHANUMERIC_EDITED, FIGURATIVE, UNKNOWN
  - `MoveViolationKind`: ERROR, WARNING

### LinkageChecker

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> LinkageReport`
- **Output:** `LinkageReport` with `violations: list[LinkageViolation]`
  - `LinkageViolation`: `kind: LinkageViolationKind`, `call_target: str | None`, `location: SourceLocation | None`, `message: str`
  - `LinkageViolationKind`: TOO_MANY_ARGS, TOO_FEW_ARGS, VALUE_TO_LINKAGE, UNREFERENCED_LINKAGE, UNKNOWN_ENTRY

### LanguageEnvironmentAnalyzer

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> LEAnalysisResult`
- **Output:** `LEAnalysisResult` with `le_functions: list[LEFunctionUsage]`, `service_calls: list[LEServiceCall]`
  - `LEFunctionUsage`: name, location
  - `LEServiceCall`: name, location
- **What it finds:** CALL statements to IBM LE functions (CEE*, IGZEDT*, etc.)

### CRUDMatrixGenerator

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> CRUDMatrix`
- **Output:** `CRUDMatrix` with `entries: list[FileEntry | TableEntry]`, `.to_csv()`, `.to_json()` methods
  - `FileEntry`: `name: str`, `flags: CRUDFlags`
  - `TableEntry`: `name: str`, `flags: CRUDFlags`
  - `CRUDFlags`: `create: bool`, `read: bool`, `update: bool`, `delete: bool`
- **Scope:** Tracks file-level operations (OPEN/READ/WRITE/REWRITE/DELETE) only; does NOT analyze SQL DML

### HostVariableResolver

- **Input:** `CobolProgram`
- **Method:** `.resolve(ast) -> HostVarResolutionReport` ← **Note: `.resolve()` not `.analyze()`**
- **Output:** `HostVarResolutionReport` with `resolved: dict[str, HostVariableInfo]`, `unresolved: set[str]`, `declare_tables: dict[str, DeclareTableStatement]`, `column_name_collisions: dict[str, list[str]]`
  - `HostVariableInfo`: `name: str`, `picture: str | None`, `usage: str`, `data_item: CobolDataItem | None`, `db2_column: DB2ColumnDefinition | None`, `sql_statements: list[ExecSQLStatement]`
- **What it finds:** Correlates SQL host variables (prefixed with `:`) to their COBOL data item definitions and optional DB2 column definitions from DECLARE TABLE blocks

### IMSSegmentAnalyzer

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> list[IMSDLICall]`
- **Output:** list of `IMSDLICall` objects with `function_code: str`, `pcb_name: str`, `segment_name: str | None`, `location: SourceLocation | None`
- **Also identifies:** `IMSEntryPoint` objects (ENTRY 'DLITCBL' USING) in the program

### CoverageAnalyzer

- **Input:** `CobolProgram`
- **Method:** `.analyze(ast) -> CoverageMap`
- **Output:** `CoverageMap` with `branch_points: list[BranchPoint]` (keyed by paragraph/section)
  - `BranchPoint`: location, branch_count, branch_type

### TestPlanGenerator

- **Input:** `CoverageMap`
- **Method:** `.generate(coverage_map) -> TestPlan` (not `.analyze()`)
- **Output:** `TestPlan` with test case specifications per branch type and coverage strategy

### IOCoverageReporter (Special: not a standard analyzer)

- **Input:** pytest results (JSON or JUnit XML) + catalog path
- **Methods:** `.generate_artifact()`, `.generate_report()` (not `.analyze()`)
- **Output:** `IoCoverageArtifact` with `variations: list[IoVariationCoverage]`, coverage summary
- **Purpose:** Machine-readable coverage artifacts mapped to IBM COBOL I/O variation catalog
- **Note:** This is a reporting/ingestion tool, not an AST analyzer

### IODiagnosticHelper (Special: not a standard analyzer)

- **Type:** Static helper class (not an analyzer instance)
- **Methods:** Static methods only
  - `.get_error_message(code: IOErrorCode) -> str`
  - `.create_io_error(code: IOErrorCode, line: int, column: int, context: str | None) -> ParseError`
  - `.validate_io_statement_type(statement_type: str, file_organization: str | None) -> IOErrorCode | None`
- **Output:** Error codes, messages, and `ParseError` objects
- **Purpose:** Diagnostic helpers for I/O statement validation; used by parser and analyzers

## Top-Level Pipeline

Test generation combines three analyzers in sequence:

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

Analyzers and report types exported from `cobolparser`:

```python
from cobolparser import (
    # Analyzers
    DeadCodeAnalyzer,
    ProgramFlowAnalyzer,
    DynamicCallAnalyzer,
    IOLogger,
    IOSequenceAnalyzer,
    MoveTypeChecker,
    LinkageChecker,
    LanguageEnvironmentAnalyzer,
    CRUDMatrixGenerator,
    CoverageAnalyzer,
    TestPlanGenerator,
    # Report types
    DeadCodeReport,
    ProgramFlowReport,
    IOLogReport,
    IOSequenceReport,
    MoveTypeReport,
    LinkageReport,
    LEAnalysisResult,
    CRUDMatrix,
    CoverageMap,
    TestPlan,
    # Utility
    generate_cobolcheck_tests,
)
```

Analyzers and types exported from `cobolparser.analysis` only:

```python
from cobolparser.analysis import (
    IMSSegmentAnalyzer,
    HostVariableResolver,
    # Report and helper types
    IMSDLICall,
    IMSEntryPoint,
    HostVarResolutionReport,
    HostVariableInfo,
    IOCoverageReporter,
    IODiagnosticHelper,
    IOErrorCode,
)
```

## Gotchas / Invariants

1. **HostVariableResolver.resolve()** — the only analyzer using `.resolve()` instead of `.analyze()`. This is deliberate (SQL-specific naming).

2. **DynamicCallAnalyzer returns None** — it modifies the AST in-place by populating `call.possible_values` on `CallStatement` nodes. Call it for side-effects, not return value.

3. **Analyzers are stateless** — create a new instance per program, or call `.analyze()` with a fresh AST each time. Instance state (e.g., `_variable_values` in `DynamicCallAnalyzer`) is reset on each `.analyze()` call.

4. **DynamicCallAnalyzer is conservative** — it only tracks MOVE-to-identifier assignments and literal VALUES clauses. It does NOT execute the program, so results may include multiple possible targets.

5. **ProgramFlowAnalyzer range tracking** — `range_members: dict[str, list[str]]` tracks paragraphs within PERFORM … THRU ranges; `cycle_details` lists detected control flow cycles (can exist in valid COBOL).

6. **CRUDMatrixGenerator file-only scope** — tracks file-level operations (OPEN/READ/WRITE/REWRITE/DELETE) as CRUD flags; does NOT analyze SQL DML (INSERT/UPDATE/DELETE on tables). Separate analyzers (e.g., dynamic SQL in value_tracker) handle SQL analysis.

7. **IOCoverageReporter is not an analyzer** — it ingests pytest results (JSON/XML) and maps test results to an external I/O variation catalog. Not a standard AST analyzer; does not follow `.analyze(ast) -> Report` shape.

8. **IODiagnosticHelper is static only** — use static methods directly (`IODiagnosticHelper.get_error_message(...)`) or create a helper instance if collecting results.

9. **IOViolationKind.FILE_LEFT_OPEN** — fires when a file is open at STOP RUN / GOBACK / end-of-program; this is a warning-level condition, not necessarily an error.

10. **Lazy imports in analysis.__init__** — analyzers are imported only on first access to avoid circular dependencies with `cobolparser.plugins`. This is transparent to users but explains why import times are fast.

## Refresh Checklist

- [ ] Verify analyzer count in `analysis/__init__.py` — should be 13 standard + 2 special (15 total analysis modules)
- [ ] Check `HostVariableResolver` still uses `.resolve()` not `.analyze()`
- [ ] Check `FlowEdgeType` enum values in `program_flow.py` — ensure PERFORM_THRU, GOTO_DEPENDING, ALTER, IF_BRANCH variants are current
- [ ] Verify `generate_cobolcheck_tests()` is still exported from top-level `__init__.py`
- [ ] Verify `IOCoverageReporter.generate_artifact()` / `generate_report()` signatures still match
- [ ] Verify `IODiagnosticHelper` methods are still static (no instance `.analyze()`)
- [ ] Check `DeadCodeItem.procedure_type` (not `item_type`)
- [ ] Check `IOOperation` fields: `category`, `operation`, `direction`, `variables`, `target` (not `verb`, `file_name`, `record_name`)
- [ ] Look for new analyzer classes in `analysis/__init__.py` not listed in this doc
