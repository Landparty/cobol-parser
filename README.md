# COBOL Parser for Python

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-5800%2B%20passing-green.svg)](#testing)
[![Coverage](https://img.shields.io/badge/coverage-81%25%2B%20enforced-green.svg)](#testing)
[![License: Proprietary](https://img.shields.io/badge/License-Proprietary-red.svg)](LICENSE)
[![IBM COBOL](https://img.shields.io/badge/IBM%20Enterprise%20COBOL-supported-blue.svg)](docs/ibm-enterprise.md)

A COBOL source code parser for Python 3.11+ that converts COBOL programs into structured ASTs. Supports IBM Enterprise COBOL, configurable memory management, JSON export, and robust error recovery. Built with TDD — 5,800+ tests, 81%+ coverage enforced, 99.1% parse success on NIST COBOL-85.

## Features

- **IBM Enterprise COBOL** — COMP-3, EXEC SQL, EXEC CICS, 75+ verbs, IBM intrinsic functions
- **Real-world validation** — 99.1% parse success on the 512-program NIST COBOL-85 corpus and 24-program shamrice/COBOL-Examples corpus
- **Full CLI** — parse, tokenize, preprocess, expand copybooks, analyze dynamic calls, detect dead code, inspect program flow, and generate tests from the terminal
- **Error recovery** — fail-fast or collect-all modes with detailed diagnostics
- **JSON export** — cross-platform AST serialization with source locations and metadata
- **Memory management** — configurable limits from 64MB to 8GB with streaming support for large files
- **Batch parsing** — parallel multi-file processing via `parse_files()` and `cobol-parser batch`
- **Copybook expansion** — recursive COPY statement inlining with circular reference detection and REPLACING clause support
- **Dynamic call analysis** — tracks possible values for variables used in dynamic CALL statements
- **Dead code detection** — identifies unreferenced paragraphs and sections
- **Program flow analysis** — builds control flow graphs across paragraphs, PERFORM, GO TO, and CALL edges
- **IO operation logging** — records every OPEN/CLOSE/READ/WRITE/REWRITE/DELETE/START at runtime with source location
- **IO sequence validation** — detects invalid I/O operation sequences (e.g., writing to a closed file)
- **MOVE type checking** — flags type-incompatible MOVE statements (numeric to alphanumeric, etc.)
- **Linkage section checking** — validates LINKAGE SECTION data items and USING/RETURNING clause consistency
- **Language Environment analysis** — identifies IBM LE function calls, service calls, and condition handling
- **CRUD matrix generator** — program × file/table Create/Read/Update/Delete matrix with CSV and JSON export
- **IMS segment analyzer** — resolves IMS DLI segment names for CBLTDLI/AIBTDLI/CEETDLI calls
- **Host variable resolver** — resolves `:host-var` references in EXEC SQL to DATA DIVISION and DCLGEN types
- **CobolCheck test generation** — automatically generates `.cut` unit test suites targeting paragraph, branch, and boundary coverage

## Installation

```bash
pip install cobolparser

# or from source
git clone https://github.com/Landparty/cobol-parser.git
cd cobol-parser
pip install -e ".[dev]"
```

Requires Python 3.11, 3.12, or 3.13.

## Quick Start

### CLI

```bash
# Parse a COBOL file and output AST as JSON
cobol-parser parse program.cbl

# Parse and extract only the PROCEDURE division
cobol-parser parse program.cbl procedure

# Compact JSON output
cobol-parser parse program.cbl --compact

# Find all CALL statements in a program
cobol-parser parse program.cbl --find-type CallStatement

# Tokenize a file (see all tokens)
cobol-parser tokenize program.cbl

# Preprocess fixed-format to free-form
cobol-parser preprocess program.cbl

# Preprocess with conditional compilation symbols
cobol-parser preprocess program.cbl --define DEBUG --define ENV=PROD

# Expand COPY statements
cobol-parser expand program.cbl --copybook-path ./copybooks

# Analyze dynamic CALL targets
cobol-parser analyze program.cbl

# Detect dead code (unreferenced paragraphs)
cobol-parser dead-code program.cbl

# Display program control flow graph
cobol-parser program-flow program.cbl

# Batch parse multiple files in parallel
cobol-parser batch prog1.cbl prog2.cbl prog3.cbl --stats

# Generate CobolCheck unit tests
cobol-parser generate-tests program.cbl -o program.cut
```

### Python API

```python
from cobolparser import parse_cobol

result = parse_cobol(source, filename="prog.cob")

if result.success:
    print(result.ast.program_name)
    print(result.ast.to_json())
else:
    for err in result.errors:
        print(f"Line {err.line}: {err.message}")
```

See [docs/PARSER_INVOCATION_GUIDE.md](docs/PARSER_INVOCATION_GUIDE.md) for the full API including `CobolParser`, `MemoryConfiguration`, `ErrorRecoveryMode`, and `parse_files()`.

## Analysis Tools

The `cobolparser.analysis` module provides static and dynamic analysis passes that run on a parsed AST.

### Dynamic Call Analysis

Tracks possible values of variables used in dynamic CALL statements by following MOVE and VALUE clause assignments:

```python
from cobolparser import parse_cobol, DynamicCallAnalyzer

result = parse_cobol(source)
analyzer = DynamicCallAnalyzer()
analyzer.analyze(result.ast)

for stmt in result.ast.find_all_by_type("CallStatement"):
    if stmt.is_dynamic:
        print(f"Dynamic CALL, possible targets: {stmt.possible_values}")
```

### Dead Code Detection

Identifies paragraphs and sections that are never referenced by PERFORM, GO TO, or CALL:

```python
from cobolparser import parse_cobol, DeadCodeAnalyzer

result = parse_cobol(source)
report = DeadCodeAnalyzer().analyze(result.ast)

for item in report.dead_items:
    print(f"Unreferenced: {item.name} ({item.kind}) at line {item.line}")
```

### Program Flow Analysis

Builds a control flow graph of the program's paragraphs and sections, with typed edges for PERFORM, GO TO, CALL, and fall-through:

```python
from cobolparser import parse_cobol, ProgramFlowAnalyzer

result = parse_cobol(source)
report = ProgramFlowAnalyzer().analyze(result.ast)

for edge in report.edges:
    print(f"{edge.from_node} --[{edge.edge_type.name}]--> {edge.to_node}")
```

### IO Operation Logging

Records every I/O operation (OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START) with file name, operation type, and source location:

```python
from cobolparser import parse_cobol, IOLogger

result = parse_cobol(source)
log_report = IOLogger().analyze(result.ast)

for op in log_report.operations:
    print(f"{op.file_name}: {op.operation} at line {op.line}")
```

### IO Sequence Validation

Detects invalid I/O operation sequences, such as reading from a file that was never opened or writing after a close:

```python
from cobolparser import parse_cobol, IOSequenceAnalyzer

result = parse_cobol(source)
report = IOSequenceAnalyzer().analyze(result.ast)

for violation in report.violations:
    print(f"{violation.kind.name}: {violation.message} at line {violation.line}")
```

### MOVE Type Checking

Flags MOVE statements where the source and destination data types are incompatible (e.g., numeric to alphabetic, or truncating a value that does not fit the target PIC clause):

```python
from cobolparser import parse_cobol, MoveTypeChecker

result = parse_cobol(source)
report = MoveTypeChecker().analyze(result.ast)

for violation in report.violations:
    print(f"{violation.kind.name}: {violation.message} at line {violation.line}")
```

### Linkage Section Checking

Validates that LINKAGE SECTION data items are referenced consistently in PROCEDURE DIVISION USING/RETURNING clauses:

```python
from cobolparser import parse_cobol, LinkageChecker

result = parse_cobol(source)
report = LinkageChecker().analyze(result.ast)

for violation in report.violations:
    print(f"{violation.kind.name}: {violation.message}")
```

### Language Environment Analysis

Identifies IBM Language Environment (LE) function calls, service calls (e.g., `CEE*`), and condition-handling patterns:

```python
from cobolparser import parse_cobol, LanguageEnvironmentAnalyzer

result = parse_cobol(source)
le_result = LanguageEnvironmentAnalyzer().analyze(result.ast)

for fn in le_result.le_functions:
    print(f"LE function: {fn.name} at line {fn.line}")
for svc in le_result.service_calls:
    print(f"LE service call: {svc.name} at line {svc.line}")
```

### CRUD Matrix Generation

Generates a Create/Read/Update/Delete matrix for every resource touched by a
program — both COBOL files (`OPEN`/`READ`/`WRITE`/`REWRITE`/`DELETE`) and
DB2 tables (`INSERT`/`SELECT`/`UPDATE`/`DELETE` via `EXEC SQL`). Standard
deliverable for mainframe modernization engagements; renders to CSV or JSON
for spreadsheet delivery.

```python
from cobolparser import parse_cobol
from cobolparser.analysis import CRUDMatrixGenerator

result = parse_cobol(source)
matrix = CRUDMatrixGenerator().analyze(result.ast)

# Per-entry inspection
for entry in matrix.entries:
    print(f"{entry.program_name} · {entry.crud.as_string()}")

print(matrix.to_csv())    # spreadsheet-friendly
print(matrix.to_json())   # machine-readable
```

### IMS Segment Analysis

Statically resolves the IMS DLI segment names accessed by each
`CALL 'CBLTDLI' / 'AIBTDLI' / 'CEETDLI'` by inspecting SSA data-item
definitions and `MOVE` value propagation. Recognizes all 16 standard DLI
function codes (GU, GN, GNP, GHU, GHN, GHNP, ISRT, DLET, REPL, CHKP, XRST,
XDLT, XRPL, TERM, ROLLB, PURG):

```python
from cobolparser import parse_cobol
from cobolparser.analysis import IMSSegmentAnalyzer

result = parse_cobol(source)
analyzer = IMSSegmentAnalyzer()
dli_calls = analyzer.analyze(result.ast)

for call in dli_calls:
    print(f"{call.interface} {call.function_code} {call.pcb_name}")
    print(f"  Segments: {call.segment_names}")

# All distinct segment names touched by the program
all_segments = analyzer.get_all_segment_names(dli_calls)
```

### Host Variable Resolution

Walks the AST and resolves every `:host-var` reference in `EXEC SQL` blocks
back to its DATA DIVISION definition, cross-referencing with DCLGEN
`DECLARE TABLE` column definitions so PICTURE, USAGE, and DB2 column types
are available in one place:

```python
from cobolparser import parse_cobol
from cobolparser.analysis import HostVariableResolver

result = parse_cobol(source)
report = HostVariableResolver().resolve(result.ast)

for name, info in report.resolved.items():
    print(f":{name}  PIC {info.picture}  USAGE {info.usage}")

for name in report.unresolved:
    print(f":{name}  — no DATA DIVISION entry found")

for col, tables in report.column_name_collisions.items():
    print(f"ambiguous column {col} across tables: {', '.join(tables)}")
```

See [docs/analysis.md](docs/analysis.md) for the full reference covering
every analyzer, report types, and CLI integration.

## CobolCheck Test Generation

Automatically generate [CobolCheck](https://github.com/openmainframeproject/cobol-check) unit test suites (`.cut` files) from any COBOL program. The generator analyzes the AST and produces tests targeting paragraph execution, branch coverage, and boundary values -- no manual test writing required.

### CLI

```bash
# Generate tests for a COBOL program (all strategies)
cobol-parser generate-tests program.cbl

# Write output to a file
cobol-parser generate-tests program.cbl -o program.cut

# Use specific coverage strategies
cobol-parser generate-tests program.cbl --strategy paragraph
cobol-parser generate-tests program.cbl --strategy branch --strategy boundary
```

### Python API

```python
from cobolparser import generate_cobolcheck_tests

source = open("program.cbl").read()

# Generate with all strategies (paragraph + branch + boundary)
output = generate_cobolcheck_tests(source)

# Or pick specific strategies
output = generate_cobolcheck_tests(source, strategies=["paragraph", "branch"])

# Write the .cut file
with open("program.cut", "w") as f:
    f.write(output)
```

### Pipeline API

For finer control, use the three-stage pipeline directly:

```python
from cobolparser import parse_cobol
from cobolparser.analysis.coverage_analyzer import CoverageAnalyzer
from cobolparser.analysis.test_plan import TestPlanGenerator
from cobolparser.generators.cobolcheck import CobolCheckGenerator

# 1. Parse
result = parse_cobol(source)

# 2. Analyze coverage targets
analyzer = CoverageAnalyzer()
coverage_map = analyzer.analyze(result.ast)

print(f"Paragraphs: {coverage_map.total_paragraphs}")
print(f"Branch points: {coverage_map.total_branch_points}")
print(f"Data items: {len(coverage_map.data_items)}")

# 3. Generate test plan
planner = TestPlanGenerator(strategies=["paragraph", "branch"])
plan = planner.generate(coverage_map)

print(f"Test cases: {plan.total_test_cases}")

# 4. Emit CobolCheck .cut file
generator = CobolCheckGenerator(include_comments=True)
output = generator.generate(plan)
```

### Example Output

Given a COBOL program with arithmetic operations, the generator produces:

```cobol
    *> Generated CobolCheck tests for ARITHOPS
    *> Auto-generated by cobol-parser coverage analyzer

    TESTSUITE "Paragraph coverage for ARITHOPS"

    TESTCASE "Should execute ADD-TESTS"
        MOVE ZEROS TO WS-NUM-1
        MOVE ZEROS TO WS-NUM-2
        MOVE ZEROS TO WS-RESULT
        PERFORM ADD-TESTS
        EXPECT WS-RESULT TO BE NUMERIC

    TESTSUITE "Branch coverage for ARITHOPS"

    TESTCASE "Should take ON SIZE ERROR in ADD-TESTS"
        MOVE 99999.99 TO WS-NUM-1
        MOVE 99999.99 TO WS-NUM-2
        MOVE 9999999.99 TO WS-RESULT
        PERFORM ADD-TESTS
        EXPECT WS-RESULT TO BE NUMERIC

    TESTSUITE "Boundary value tests for ARITHOPS"

    TESTCASE "Should handle zero value for WS-RESULT in ADD-TESTS"
        MOVE 0 TO WS-NUM-1
        MOVE 0 TO WS-NUM-2
        MOVE 0 TO WS-RESULT
        PERFORM ADD-TESTS
        EXPECT WS-RESULT TO BE NUMERIC
```

### Coverage Strategies

| Strategy | Description |
|---|---|
| `paragraph` | One test per paragraph -- verifies basic execution of every reachable paragraph |
| `branch` | One test per branch point -- IF true/false, EVALUATE WHEN, SEARCH, AT END, ON SIZE ERROR, ON EXCEPTION, ON OVERFLOW |
| `boundary` | Boundary value tests for numeric data items -- zero, max, and min values based on PIC clause |

### Supported Branch Types

The analyzer detects 18 branch types across all major COBOL constructs:

- **Conditional**: IF true/false
- **EVALUATE**: WHEN clauses, WHEN OTHER (default)
- **SEARCH**: WHEN conditions, AT END
- **I/O**: AT END, NOT AT END, INVALID KEY, NOT INVALID KEY, AT END-OF-PAGE
- **Arithmetic**: ON SIZE ERROR, NOT ON SIZE ERROR
- **CALL**: ON EXCEPTION, NOT ON EXCEPTION
- **STRING/UNSTRING**: ON OVERFLOW, NOT ON OVERFLOW
- **PERFORM**: Inline PERFORM body

## Documentation

| Topic | Guide |
|---|---|
| Full API reference & invocation | [PARSER_INVOCATION_GUIDE.md](docs/PARSER_INVOCATION_GUIDE.md) |
| Real-world recipes | [cookbook.md](docs/cookbook.md) |
| Architecture & pipeline | [architecture.md](docs/architecture.md) |
| Configuration options | [configuration.md](docs/configuration.md) |
| Performance & optimization | [performance.md](docs/performance.md) |
| Analysis toolkit (all analyzers) | [analysis.md](docs/analysis.md) |
| Copybook expansion | [copybook-expansion.md](docs/copybook-expansion.md) |
| IBM Enterprise COBOL | [ibm-enterprise.md](docs/ibm-enterprise.md) |
| IBM dialect registration | [ibm-dialect-registration.md](docs/ibm-dialect-registration.md) |
| Factory API (AST node creation) | [factory-api.md](docs/factory-api.md) |
| Factory extension guide | [factory-extension-guide.md](docs/factory-extension-guide.md) |
| CobolCheck test generation | [README.md](#cobolcheck-test-generation) |
| Packaging (mypyc binary wheel) | [packaging-mypyc.md](docs/packaging-mypyc.md) |
| Troubleshooting | [troubleshooting.md](docs/troubleshooting.md) |
| Contributing | [contributing.md](docs/contributing.md) |

## Testing

```bash
python -m pytest tests/ -v                              # all tests
python -m pytest tests/unit/ -v                         # unit only
python -m pytest --cov=cobolparser --cov-report=html    # with coverage
```

81%+ line coverage is enforced. Running a subset of tests will cause the coverage check to fail — this is expected.

## License

Proprietary — Copyright © 2026 Samuel Dion. All rights reserved. See [LICENSE](LICENSE) for terms.
