---
type: Module
title: Static Analysis
description: 14 static-analysis modules — dead code, program flow, IO sequence, move-type, linkage, CRUD, boundary inventory, and more.
tags: [analysis, dead-code, program-flow, io, crud, boundary-inventory, fixtures]
timestamp: 2026-08-04T00:00:00Z
---

# Overview

`cobolparser/analysis/` — 14 static-analysis modules. All follow the same
`<Analyzer>().analyze(ast) -> <Report>` shape, except `HostVariableResolver`
which uses `.resolve(ast)`, and `BoundaryInventoryAnalyzer`, which additionally
takes a Phase 1 `ProgramLayoutIndex` (`.analyze(ast, index, ...)`).

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
    DynamicCallAnalyzer,
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

**THRU range members count as reachable (2026-07-20):** `PERFORM A THRU C`
(and SORT/MERGE procedure ranges) execute every paragraph the range
physically spans, but the graph only carries explicit edges to the two
endpoints — the intermediates ride along in `FlowEdge.range_members`.
`find_unreachable_nodes` (`graph.py`) therefore adds each range member as a
neighbor of the edge's source when building its BFS adjacency. Before this,
an intermediate member whose fall-through edge from its predecessor was
suppressed (predecessor contains a GO TO, or ends with a terminator) was
falsely listed in `unreachable_nodes` even though the range provably
executes it. Cycle detection (`cycles.py`) intentionally still uses only
explicit edges — member-hops have no `(source, target)` edge record, so
adding them would misclassify cycles as `MIXED`. Pinned by
`tests/unit/analysis/test_program_flow_thru_reachability.py`.

**Structure (2026-07-14):** `program_flow` is a package, not a single module.
`cobolparser/analysis/program_flow/` splits the former god class into
collaborators — `models.py` (`FlowNode`/`FlowEdge`/`FlowEdgeType`/`BranchArm`/
`BranchNode`/`ProgramFlowReport`), `scanner.py` (`ProcedureScanner`: procedure
collection + the recursive `scan()` statement walk, `_CLAUSE_BODY_ATTRS`),
`edges.py` (`EdgeCollector`: PERFORM/GO TO/CALL/SORT/MERGE/CANCEL/ALTER edge
construction, `INTERNAL_EDGE_TYPES`/`PERFORM_EDGE_TYPES`/`GOTO_EDGE_TYPES`),
`cycles.py` (`detect_cycles`/`classify_cycles`), `graph.py`
(`build_fall_through_edges`/`compute_convergence_nodes`/
`find_unreachable_nodes`), and `analyzer.py` (`ProgramFlowAnalyzer`
orchestrator). All public names still import from
`cobolparser.analysis.program_flow`; behavior and `to_dict()` output are
unchanged.

Unlike most analyzers (which walk `get_all_statements()`), the flow graph is
built by a hand-rolled `scan()` that recurses statement-by-statement. Audit
2026-07-09: `scan()` special-cased only PERFORM inline blocks, CALL handlers,
and IF/EVALUATE/SEARCH/RETURN — it never descended into IO clause bodies
(`AT END` / `INVALID KEY` / `AT EOP`), arithmetic `ON SIZE ERROR`, or
STRING/UNSTRING `ON OVERFLOW`. A PERFORM/GO TO/CALL nested in one of those
produced no edge, cascading into **false `unreachable_nodes`** and missing
flowchart arrows. Fixed with a final `else` branch iterating
`_CLAUSE_BODY_ATTRS`; the `id`-based `visited` set keeps the
generic pass from double-counting statements the specialized branches already
handled. Pinned by `tests/regression/test_tier6_silent_drop_audit.py`.

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
report: MoveTypeReport = MoveTypeChecker().check(ast)
# report.violations: list[MoveTypeViolation]
# report.unresolved_count: int   -- MOVE operands whose DataCategory could
#                                    not be resolved (undeclared identifier,
#                                    unexpanded copybook, ...); serialized
#                                    in report.to_dict()
# MoveViolationKind: NUMERIC_TO_ALPHANUMERIC, ALPHANUMERIC_TO_NUMERIC, …
```

Detects MOVE statements with type-incompatible sending/receiving fields based on
PICTURE clause categories.

**`unresolved_count` (2026-07-09, audit finding H5):** before this field
existed, an unresolvable source category (`UNKNOWN`/`FIGURATIVE`) caused
`_validate_move` to `return` early, and an unresolvable target category
caused it to `continue` past that target — both silently, with no counter
anywhere on `MoveTypeReport`. Three MOVEs on undeclared identifiers
(simulating an unexpanded copybook) produced `violations: [], error_count:
0, warning_count: 0` — a **false all-clear** indistinguishable from "every
MOVE was actually checked and found compatible." `MoveTypeChecker` now
increments an internal counter at every such early-exit point, and
`check()` returns it as `MoveTypeReport.unresolved_count`. A caller that
wants a real all-clear must now check `not violations and unresolved_count
== 0`, not just `not violations`. Pinned by
`tests/regression/test_open_findings_high_regressions.py::TestH5MoveTypeCheckerUnresolvedCount`.

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

## BoundaryInventoryAnalyzer

Phase 2 of program-scoped test-data generation (the `gen-fixtures` initiative
-- see `docs/plans/2026-08-02-program-data-generation-design.md` and
`.okf/generators.md`'s `ProgramLayoutIndex` section, Phase 1). Walks the
PROCEDURE DIVISION and emits one `Boundary` per mockable statement, using the
same `(category, key)` convention mockymock's own `mock_surface` module uses
-- two independent walks over the same AST that must agree on keys (the
dependency direction is mockymock -> cobol-parser, never the reverse; the
unique-prefix key algorithm and the non-interactive-ACCEPT-sources list are
re-derived independently against that module's source, not imported).

```python
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.generators import ProgramLayoutIndex

index = ProgramLayoutIndex.build(ast)
report = BoundaryInventoryAnalyzer().analyze(
    ast, index,
    callee_indexes={"CALCULATOR": callee_index},   # optional, Phase 2b rung 2
    callee_asts={"CALCULATOR": callee_ast},
)
report.boundaries          # list[Boundary]: ref (category/key/paragraph/line),
                           # direction, record_names, status_field, handlers,
                           # call_args, unresolved
report.unresolved          # program-level gaps (never silently dropped)
```

**Categories**: `CALL`/`DYNCALL` (per-argument direction, see below),
`OPEN`/`CLOSE`/`READ`/`WRITE`/`REWRITE`/`DELETE`/`START`/`UNLOCK` (the eight
file-op verbs), `SQL`, `CICS`, `DLI`, `ACCEPT` (console only --
non-interactive sources filtered). `DISPLAY` is never a boundary (assert-only,
out of scope for this phase, matching mockymock's own `mock_surface`).

**File ops.** WRITE/REWRITE key on the *record* name (COBOL syntax names the
record, not the FD) and READ's `INTO` target also names a whole record --
both resolved via `ProgramLayoutIndex.record_named()`, not `.resolve()`
(`.resolve()` only ever finds elementary fields; a WRITE/REWRITE/READ-INTO
target is a group item, which `flatten_record` never emits a `FieldSpec`
for -- this gap is exactly why `record_named()` exists; found via direct
reproduction against `tests/samples/file_operations.cbl`, not theorized).
OPEN/CLOSE emit one `Boundary` per file named (COBOL allows `OPEN INPUT A
OUTPUT B` in one statement). DELETE/START/UNLOCK are `STATUS_ONLY` (no data
payload); READ is `IN`; WRITE/REWRITE are `OUT`.

**CALL/DYNCALL argument-direction ladder (Phase 2b)**, first rung wins,
`CallArg.provenance` records which:

1. `passing_mode` in `CONTENT`/`VALUE` -> **OUT**, always (language rule --
   the callee cannot write back through either mode).
2. Callee source available (`callee_indexes`/`callee_asts`, keyed by
   uppercased called-program name): does the callee write to its Nth
   LINKAGE 01 *at all* -> **IN**; read-only -> **OUT**. "Writes" is checked
   generically via `.targets` (shared verbatim by `MoveStatement`,
   `ArithmeticStatement` -- ADD/SUBTRACT/MULTIPLY/DIVIDE --, `ComputeStatement`,
   `InitializeStatement`, `SetStatement`) plus `.givings` (arithmetic GIVING)
   and `.into_target`/`.into_targets` (READ INTO, STRING/UNSTRING) -- **not**
   just `MoveStatement`, which would miss a `COMPUTE LK-RESULT = ...`
   subprogram entirely (found via `tests/samples/subprogram_demo.cbl`'s
   CALCULATOR, which computes its result exactly that way; a MOVE-only
   check silently mis-classified it as OUT).
3. Caller-side dataflow in the enclosing paragraph's own statement list
   (source order): last write before the CALL with no read after -> **OUT**;
   first read after with no write before -> **IN**; both -> **BIDIRECTIONAL**.
   A write to a *parent group* counts as touching a child field (and vice
   versa), checked via `FieldSpec.path` prefix comparison through the index,
   not bare string equality. "Read" for a write-shaped statement (rung 2's
   list above) checks only its own read-only attribute (MOVE's `.source`);
   the generic `.operands` fallback is reserved for statement types with no
   write-shape at all (DISPLAY, IF conditions, ...) since a write-shaped
   statement's own `.operands` also contains its target, which would
   otherwise misread a write as a read of the same name.
4. Otherwise **BIDIRECTIONAL**, `provenance="assumed-bidirectional"`.

`RETURNING`/`GIVING` parameters are always `IN` (`provenance=
"giving-parameter"`) -- the callee produces them by definition.

**SQL.** `into_variables` is unreliable in practice: an inline `SELECT ...
INTO :a FROM t WHERE x = :b` places *both* `:a` and `:b` in `host_variables`,
never populating `into_variables` at all (verified empirically against
`tests/samples/ibm_extensions.cbl` and `database_interface.cbl` -- the parent
plan's Phase 2 table assumed `into_variables` cleanly separated IN from OUT
variables; it does not). `host_variables` is therefore the only layout
source used, for every SQL shape; direction comes from `sql_type`
(`SELECT`/`FETCH` -> IN, `INSERT`/`UPDATE`/`DELETE` -> OUT, else
`STATUS_ONLY`), independent of which variables are attached.
`status_field="SQLCODE"` always.

**CICS/DLI** have no fixed INTO/FROM-shaped attributes to key layout
resolution off -- `ExecCicsStatement.options` is a generic option-keyword ->
argument-text dict, and `ExecImsStatement.arguments` is a positional list
with no fixed role per position. Best-effort in v1: every option
value/argument is tried against the layout index (via the same
`resolve()`-then-`record_named()` fallback used elsewhere), direction
defaults to `BIDIRECTIONAL`, and an unresolved entry on the `Boundary` itself
(not the report-level list) notes the limitation rather than claiming
precision this phase does not have.

**ACCEPT.** Non-interactive sources (`DATE`, `DAY`, `DAY-OF-WEEK`, `TIME`,
`COMMAND-LINE`, `ENVIRONMENT`, `ENVIRONMENT-VALUE`, `ARGUMENT-NUMBER`,
`ARGUMENT-VALUE`) are not boundaries at all -- resolved without touching
stdin, mirroring mockymock's own `_NON_INTERACTIVE_ACCEPT_SOURCES`.
`ACCEPT OMITTED` (waits for console input but stores nothing -- a real COBOL
idiom, not a gap) is still recorded as a boundary but with no fields to
resolve and no unresolved note.

**Key convention.** Static CALL keys keep the literal's original case (a
COBOL program name is written case-sensitively); dynamic CALL/SQL/CICS/DLI
keys are uppercased/normalized. SQL/CICS/DLI keys are the shortest
word-prefix of the normalized command text no other same-category site in
the program shares (`_unique_prefix`, re-derived from mockymock's
`generator._unique_prefix`), falling back to the full text on a genuine tie.

**Nested-body walk**: the same discipline `IOLogger` and mockymock's
`mock_surface` both converged on independently -- a fixed set of
`getattr()`-checked attributes (`then_statements`, `else_statements`,
`inline_statements`, the IO/CALL clause bodies) plus two special cases:
`EvaluateStatement.when_clauses`/`.default_when` are `WhenClause` *nodes*
with a `.statements` attribute, while `SearchStatement.when_clauses` is a
**list of dicts** with a `"statements"` key -- a different shape, and a
documented trap (mixing the two loop variables up trips mypy immediately,
which is how this was caught).

## Module File Map

| File | Analyzer |
|------|---------|
| `value_tracker.py` | `DynamicCallAnalyzer` |
| `io_coverage_reporter.py` | `CoverageStatus`, `TestType` — machine-readable IO coverage |
| `io_diagnostics.py` | IO operation diagnostics |
| `io_logger.py` | `IOLogger` |
| `io_sequence.py` | `IOSequenceAnalyzer` |
| `crud_matrix.py` | `CRUDMatrixGenerator` |
| `dead_code.py` | `DeadCodeAnalyzer` |
| `host_var_resolver.py` | `HostVariableResolver` |
| `ims_segment_analyzer.py` | `IMSSegmentAnalyzer` |
| `language_env_analyzer.py` | `LanguageEnvironmentAnalyzer` |
| `linkage_checker.py` | `LinkageChecker` |
| `move_type_checker.py` | `MoveTypeChecker` |
| `program_flow/` | `ProgramFlowAnalyzer` (package: `models` / `scanner` / `edges` / `cycles` / `graph` / `analyzer`) |
| `boundary_inventory.py` | `BoundaryInventoryAnalyzer` (Phase 2 of `gen-fixtures`) |

# Silent-Failure Audit (2026-07-08)

`IOCoverageReporter.load_pytest_results` (`io_coverage_reporter.py`) called
`json.load()` on the pytest-results file and then unconditionally
`data.get("tests", [])` — a syntactically valid JSON file whose root wasn't
an object (e.g. a bare list) raised an uncaught `AttributeError` deep inside
the loader instead of a clean error. Now raises `ValueError` immediately
after the `json.load()` if `data` isn't a `dict`, matching the "artifact
must be a JSON object" check `IOCoverageReporter`'s CLI callers already
apply elsewhere (see [cli.md](cli.md) M10). Pinned by
`tests/unit/analysis/test_io_coverage_reporter.py::test_load_pytest_results_non_object_json_raises_value_error`.

# See Also

* [ast-models.md](ast-models.md) — input AST structure
* [cli.md](cli.md) — CLI wrappers for the most common analyzers
* [tests.md](tests.md) — `tests/unit/analysis/` covers each analyzer
* [generators.md](generators.md) — `ProgramLayoutIndex` (Phase 1), the layout
  source `BoundaryInventoryAnalyzer` resolves record/field names through
* `docs/plans/2026-08-02-program-data-generation-design.md` and its per-phase
  implementation plan — the full 9-phase `gen-fixtures` plan this analyzer
  is Phase 2 of
