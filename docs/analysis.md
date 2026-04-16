# Analysis Toolkit

The `cobolparser.analysis` package provides static and dynamic analysis passes that run on a parsed AST. Every analyzer follows the same shape:

1. Instantiate the analyzer class (no required arguments).
2. Call `.analyze(result.ast)` (or `.resolve(...)` for `HostVariableResolver`).
3. Inspect the returned report — every report exposes `to_dict()` for JSON
   serialization and, where relevant, `to_json()` / `to_csv()`.

All analyzers are re-exported from the top-level `cobolparser` package or from
`cobolparser.analysis`.

## Table of Contents

1. [Dynamic Call Analysis](#1-dynamic-call-analysis)
2. [Dead Code Detection](#2-dead-code-detection)
3. [Program Flow Analysis](#3-program-flow-analysis)
4. [IO Operation Logging](#4-io-operation-logging)
5. [IO Sequence Validation](#5-io-sequence-validation)
6. [MOVE Type Checking](#6-move-type-checking)
7. [Linkage Section Checking](#7-linkage-section-checking)
8. [Language Environment Analysis](#8-language-environment-analysis)
9. [CRUD Matrix Generator](#9-crud-matrix-generator)
10. [IMS Segment Analyzer](#10-ims-segment-analyzer)
11. [Host Variable Resolver](#11-host-variable-resolver)
12. [IO Coverage Reporter](#12-io-coverage-reporter)
13. [Coverage Analyzer & Test Plan Generator](#13-coverage-analyzer--test-plan-generator)
14. [CLI Integration](#cli-integration)

---

## 1. Dynamic Call Analysis

Tracks possible values of variables used in dynamic `CALL` statements by
following `MOVE` and `VALUE` clause assignments.

```python
from cobolparser import parse_cobol, DynamicCallAnalyzer

result = parse_cobol(source)
analyzer = DynamicCallAnalyzer()
analyzer.analyze(result.ast)   # mutates AST in place

for stmt in result.ast.find_all_by_type("CallStatement"):
    if stmt.is_dynamic:
        print(f"Dynamic CALL at line {stmt.location.line}")
        print(f"  Possible targets: {stmt.possible_values}")
```

- **CLI**: `cobol-parser analyze program.cbl`
- **Key nodes**: `CallStatement.is_dynamic`, `CallStatement.possible_values`

---

## 2. Dead Code Detection

Identifies paragraphs and sections that are never referenced by `PERFORM`,
`GO TO`, or `CALL`.

```python
from cobolparser import parse_cobol, DeadCodeAnalyzer

result = parse_cobol(source)
report = DeadCodeAnalyzer().analyze(result.ast)

for item in report.dead_items:
    print(f"{item.kind} {item.name} at line {item.line}")
```

- **CLI**: `cobol-parser dead-code program.cbl`
- **Report fields**: `dead_items: list[DeadCodeItem]`, `to_dict()`

---

## 3. Program Flow Analysis

Builds a control-flow graph of the program's paragraphs and sections with
typed edges for `PERFORM`, `GO TO`, `CALL`, and fall-through.

```python
from cobolparser import parse_cobol, ProgramFlowAnalyzer

result = parse_cobol(source)
report = ProgramFlowAnalyzer().analyze(result.ast)

for edge in report.edges:
    print(f"{edge.from_node} --[{edge.edge_type.name}]--> {edge.to_node}")
```

- **CLI**: `cobol-parser program-flow program.cbl`
- **Edge types**: `PERFORM`, `GO_TO`, `CALL`, `FALLTHROUGH`
- **Types**: `FlowNode`, `FlowEdge`, `FlowEdgeType`, `ProgramFlowReport`

---

## 4. IO Operation Logging

Extracts every input/output operation (CALL, SQL, FILE-IO, CONSOLE-IO, ENTRY)
from the AST with direction (INPUT/OUTPUT/BIDIRECTIONAL).

```python
from cobolparser import parse_cobol, IOLogger

result = parse_cobol(source)
log = IOLogger().analyze(result.ast)

print(f"Inputs:  {len(log.inputs)}")
print(f"Outputs: {len(log.outputs)}")
print(f"Calls:   {len(log.calls)}")

for op in log.operations:
    print(f"{op.category:<10} {op.operation:<20} {op.target} @ line {op.line}")
```

- **Categories**: `CALL`, `SQL`, `FILE-IO`, `CONSOLE-IO`, `ENTRY`
- **Types**: `IOOperation`, `IOLogReport`

---

## 5. IO Sequence Validation

Detects invalid file I/O lifecycle sequences.

```python
from cobolparser import parse_cobol, IOSequenceAnalyzer

result = parse_cobol(source)
report = IOSequenceAnalyzer().analyze(result.ast)

for violation in report.violations:
    print(f"{violation.kind.name}: {violation.message}")
```

- **Detected violations** (`IOViolationKind`):
  - `READ_BEFORE_OPEN`, `WRITE_BEFORE_OPEN`, `REWRITE_BEFORE_OPEN`,
    `DELETE_BEFORE_OPEN`, `START_BEFORE_OPEN`
  - `DOUBLE_OPEN`, `CLOSE_NOT_OPEN`, `DOUBLE_CLOSE`
  - `FILE_LEFT_OPEN` (at `STOP RUN` / `GOBACK` / end-of-program)

---

## 6. MOVE Type Checking

Flags `MOVE` statements whose source and target data categories are
incompatible.

```python
from cobolparser import parse_cobol, MoveTypeChecker

result = parse_cobol(source)
report = MoveTypeChecker().analyze(result.ast)

for v in report.violations:
    print(f"{v.kind.name}: {v.source_name} ({v.source_category.name}) "
          f"→ {v.target_name} ({v.target_category.name})")
```

- **Severities**: `ERROR` (illegal), `WARNING` (legal but lossy)
- **Categories** (`DataCategory`): `NUMERIC`, `NUMERIC_EDITED`, `ALPHABETIC`,
  `ALPHANUMERIC`, `ALPHANUMERIC_EDITED`, `FIGURATIVE`, `UNKNOWN`

---

## 7. Linkage Section Checking

Correlates `CALL` argument lists with `ENTRY` / `PROCEDURE DIVISION USING`
declarations and `LINKAGE SECTION` data items.

```python
from cobolparser import parse_cobol, LinkageChecker

result = parse_cobol(source)
report = LinkageChecker().analyze(result.ast)

for v in report.violations:
    print(f"{v.kind.name}: {v.message}")

print("ENTRY interfaces:", report.entry_interfaces)
print("LINKAGE 01-items:", report.linkage_items)
```

- **Violation kinds** (`LinkageViolationKind`): `TOO_MANY_ARGS`,
  `TOO_FEW_ARGS`, `VALUE_TO_LINKAGE`, `UNREFERENCED_LINKAGE`, `UNKNOWN_ENTRY`

---

## 8. Language Environment Analysis

Identifies IBM Language Environment (LE) function calls, service calls (e.g.
`CEE3ABD`, `CEEDAYS`), and condition-handling patterns.

```python
from cobolparser import parse_cobol, LanguageEnvironmentAnalyzer

result = parse_cobol(source)
le = LanguageEnvironmentAnalyzer().analyze(result.ast)

for fn in le.le_functions:
    print(f"LE intrinsic: {fn.name} at line {fn.line}")
for svc in le.service_calls:
    print(f"LE service:  {svc.name} at line {svc.line}")
```

- **Types**: `LEAnalysisResult`, `LEFunctionUsage`, `LEServiceCall`

---

## 9. CRUD Matrix Generator

Produces a program × resource Create/Read/Update/Delete matrix covering both
COBOL files (`OPEN`/`READ`/`WRITE`/`REWRITE`/`DELETE`) and DB2 tables
(`INSERT`/`SELECT`/`UPDATE`/`DELETE` via `EXEC SQL`, plus `DECLARE CURSOR` /
`FETCH`). This is the standard deliverable for mainframe modernization
engagements.

```python
from cobolparser import parse_cobol
from cobolparser.analysis import CRUDMatrixGenerator

result = parse_cobol(source)
matrix = CRUDMatrixGenerator().analyze(result.ast)

# Pretty CSV suitable for spreadsheet delivery
print(matrix.to_csv())

# JSON
print(matrix.to_json())

# Per-entry access
for entry in matrix.entries:
    print(f"{entry.program_name} · {entry.to_dict()['resource_type']} "
          f"· {entry.crud.as_string()}")
```

- **File mapping**: `C ← WRITE`, `R ← READ`, `U ← REWRITE`, `D ← DELETE`;
  `OPEN` modes (`INPUT`/`OUTPUT`/`I-O`/`EXTEND`) and
  `ORGANIZATION`/`ACCESS MODE` are kept as metadata.
- **SQL mapping**: `C ← INSERT`, `R ← SELECT` / `DECLARE CURSOR` / `FETCH`,
  `U ← UPDATE`, `D ← DELETE`.
- **Types**: `CRUDMatrix`, `CRUDFlags`, `FileEntry`, `TableEntry`.
- **Serialization**: `to_dict()`, `to_json()`, `to_csv()`.

---

## 10. IMS Segment Analyzer

Resolves IMS DLI segment names for every `CALL 'CBLTDLI'` / `'AIBTDLI'` /
`'CEETDLI'`. The segment name is the first 8 bytes of each SSA data item and
is resolved through `VALUE` clauses and `MOVE` value propagation.

```python
from cobolparser import parse_cobol
from cobolparser.analysis import IMSSegmentAnalyzer

result = parse_cobol(source)
analyzer = IMSSegmentAnalyzer()
dli_calls = analyzer.analyze(result.ast)

for call in dli_calls:
    print(f"{call.interface} {call.function_code} "
          f"{call.pcb_name} segments={call.segment_names}")

all_segments = analyzer.get_all_segment_names(dli_calls)
```

- **IMS function codes** recognized: `GU`, `GN`, `GNP`, `GHU`, `GHN`, `GHNP`,
  `ISRT`, `DLET`, `REPL`, `CHKP`, `XRST`, `XDLT`, `XRPL`, `TERM`, `ROLLB`,
  `PURG`.
- **IMSDLICall fields**: `interface`, `function_code`, `function_code_var`,
  `pcb_name`, `io_area_name`, `ssa_names`, `segment_names`, `primary_segment`.

---

## 11. Host Variable Resolver

Walks the AST and resolves every `:host-var` reference found in `EXEC SQL`
blocks back to its DATA DIVISION definition, and cross-references against
DCLGEN `DECLARE TABLE` column definitions.

```python
from cobolparser import parse_cobol
from cobolparser.analysis import HostVariableResolver

result = parse_cobol(source)
report = HostVariableResolver().resolve(result.ast)

for name, info in report.resolved.items():
    print(f":{name}  PIC {info.picture}  USAGE {info.usage}")

for name in report.unresolved:
    print(f":{name}  — no DATA DIVISION definition found")

for col, tables in report.column_name_collisions.items():
    print(f"Ambiguous column {col} defined in: {', '.join(tables)}")
```

- **Types**: `HostVariableResolver`, `HostVariableInfo`,
  `HostVarResolutionReport`.
- **Three-pass pipeline**: build DATA DIVISION symbol table →
  collect `DECLARE TABLE` columns → scan `EXEC SQL` host variables.

---

## 12. IO Coverage Reporter

Machine-readable IO statement coverage tracking (OPEN, CLOSE, READ, WRITE,
REWRITE, DELETE, START, ACCEPT, DISPLAY, UNLOCK variants). Maintains an IO
variation catalog, generates artifacts from pytest results, validates against
a schema, and renders Markdown / CSV reports.

```bash
# Show coverage status (table)
python -m cobolparser.cli.coverage status

# Filter by verb
python -m cobolparser.cli.coverage status --verb READ

# Filter by qualifier (AT END, INVALID KEY, ...)
python -m cobolparser.cli.coverage status --qualifier "AT END"

# Generate an artifact from pytest JSON output
python -m cobolparser.cli.coverage generate \
    --pytest-results results.json \
    --output io-coverage.json

# Validate an artifact against the schema
python -m cobolparser.cli.coverage validate --artifact io-coverage.json

# Render as Markdown / CSV / summary
python -m cobolparser.cli.coverage render --input io-coverage.json \
    --output report.md --format markdown
```

- **Statuses**: `covered`, `partial`, `gap`, `unsupported`
- **Python API**: `from cobolparser.analysis.io_coverage_reporter import IOCoverageReporter`

---

## 13. Coverage Analyzer & Test Plan Generator

Power the `cobol-parser generate-tests` command (CobolCheck `.cut` files).

```python
from cobolparser import parse_cobol
from cobolparser.analysis.coverage_analyzer import CoverageAnalyzer
from cobolparser.analysis.test_plan import TestPlanGenerator
from cobolparser.generators.cobolcheck import CobolCheckGenerator

result = parse_cobol(source)
coverage_map = CoverageAnalyzer().analyze(result.ast)

print(f"Paragraphs:     {coverage_map.total_paragraphs}")
print(f"Branch points:  {coverage_map.total_branch_points}")
print(f"Data items:     {len(coverage_map.data_items)}")

plan = TestPlanGenerator(strategies=["paragraph", "branch", "boundary"]).generate(coverage_map)
print(f"Test cases:     {plan.total_test_cases}")

output = CobolCheckGenerator(include_comments=True).generate(plan)
```

- **Strategies**: `paragraph`, `branch`, `boundary`
- **Branch types**: 18 branch types (IF true/false, WHEN, SEARCH WHEN, AT END,
  NOT AT END, INVALID KEY, NOT INVALID KEY, AT END-OF-PAGE, ON SIZE ERROR,
  NOT ON SIZE ERROR, ON EXCEPTION, NOT ON EXCEPTION, ON OVERFLOW,
  NOT ON OVERFLOW, inline PERFORM body)
- **Convenience function**: `from cobolparser import generate_cobolcheck_tests`

See also the [main README CobolCheck section](../README.md#cobolcheck-test-generation).

---

## CLI Integration

| CLI subcommand | Analyzer(s) invoked |
|----------------|--------------------|
| `cobol-parser analyze`        | `DynamicCallAnalyzer` |
| `cobol-parser dead-code`      | `DeadCodeAnalyzer` |
| `cobol-parser program-flow`   | `ProgramFlowAnalyzer` |
| `cobol-parser generate-tests` | `CoverageAnalyzer` + `TestPlanGenerator` + `CobolCheckGenerator` |
| `python -m cobolparser.cli.coverage` | `IOCoverageReporter` |

Analyzers without a dedicated subcommand (`IOLogger`, `IOSequenceAnalyzer`,
`MoveTypeChecker`, `LinkageChecker`, `LanguageEnvironmentAnalyzer`,
`CRUDMatrixGenerator`, `IMSSegmentAnalyzer`, `HostVariableResolver`) are
Python-API only — instantiate them on a `ParseResult.ast` as shown above.

## Combining Analyzers

Multiple analyzers can be run on the same AST:

```python
from cobolparser import (
    parse_cobol,
    DeadCodeAnalyzer,
    DynamicCallAnalyzer,
    IOLogger,
    MoveTypeChecker,
    LinkageChecker,
    LanguageEnvironmentAnalyzer,
    ProgramFlowAnalyzer,
)
from cobolparser.analysis import (
    CRUDMatrixGenerator,
    HostVariableResolver,
    IMSSegmentAnalyzer,
    IOSequenceAnalyzer,
)

result = parse_cobol(source)
ast = result.ast

DynamicCallAnalyzer().analyze(ast)          # mutates AST
dead_code       = DeadCodeAnalyzer().analyze(ast)
flow            = ProgramFlowAnalyzer().analyze(ast)
io_log          = IOLogger().analyze(ast)
io_sequence     = IOSequenceAnalyzer().analyze(ast)
move_types      = MoveTypeChecker().analyze(ast)
linkage         = LinkageChecker().analyze(ast)
le_usage        = LanguageEnvironmentAnalyzer().analyze(ast)
crud            = CRUDMatrixGenerator().analyze(ast)
dli_calls       = IMSSegmentAnalyzer().analyze(ast)
host_vars       = HostVariableResolver().resolve(ast)

full_report = {
    "dead_code":     dead_code.to_dict(),
    "flow":          flow.to_dict(),
    "io_log":        {op.to_dict() for op in io_log.operations},
    "io_sequence":   io_sequence.to_dict(),
    "move_types":    move_types.to_dict(),
    "linkage":       linkage.to_dict(),
    "language_env":  le_usage.to_dict(),
    "crud_matrix":   crud.to_dict(),
    "ims_segments":  [c.__dict__ for c in dli_calls],
    "host_vars":     host_vars.to_dict(),
}
```

`DynamicCallAnalyzer` is special — it mutates the AST (populating
`CallStatement.possible_values`) rather than returning a report, so it does
not need its result captured.
