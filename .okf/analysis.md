---
type: Module
title: Static Analysis
description: 16 static-analysis modules — dead code, program flow, IO sequence, move-type, linkage, CRUD, boundary inventory, constraint extraction, constant folding, and more.
tags: [analysis, dead-code, program-flow, io, crud, boundary-inventory, fixtures, constraints, const-fold]
timestamp: 2026-08-11T00:00:00Z
---

# Overview

`cobolparser/analysis/` — 15 static-analysis modules. All follow the same
`<Analyzer>().analyze(ast) -> <Report>` shape, except `HostVariableResolver`
which uses `.resolve(ast)`; `BoundaryInventoryAnalyzer`, which additionally
takes a Phase 1 `ProgramLayoutIndex` (`.analyze(ast, index, ...)`); and
`ConstraintExtractor`, which uses `.extract(ast, index, boundary_report) ->
ConstraintReport` (Phase 1's index *and* Phase 2's boundary report).

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

**Real condition text + exit-statement tracking (2026-08-11):**
`cobolparser/analysis/program_flow/condition_text.py` adds
`render_condition_text(expr: CobolExpression | None) -> str`, walking a
`ConditionalExpression`/`LogicalExpression` tree back into human-readable
COBOL text (`"WS-EOF-SW = 'Y'"`, with nested `AND`/`OR`/`NOT` correctly
parenthesized), falling back through the node's raw `operands[0]`,
`metadata["raw_condition"]`, then its bare `expression_type` tag — so every
caller gets *something* even for a partially-built or synthetic node.
Before this, `BranchNode.condition_text` (and `PerformStatement`'s UNTIL
guard) only ever carried the AST node's type TAG (e.g. `"COMPARISON"`),
never the actual condition — both flowchart generators now render the real
text on IF/EVALUATE diamonds and PERFORM UNTIL loop-test nodes.

`FlowNode` gained `exit_statement_kind: str | None` /
`exit_statement_location: SourceLocation | None` (`models.py`), set by
`scanner.py` when a paragraph's terminal statement is `STOP RUN`, `GOBACK`,
or an EXIT-family verb — both `to_dict()` and both flowchart generators
render a distinct terminal node (`shape=doublecircle` in DOT, `(((...)))` +
the `terminal` classDef in Mermaid) per exit statement, labeled `"{kind} ·
{line}"`.

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

## ConstraintExtractor

Phase 4 of program-scoped test-data generation (the `gen-fixtures` initiative
-- see `docs/plans/2026-08-02-program-data-generation-design.md`). Walks
IF/EVALUATE/SEARCH conditions and PERFORM UNTIL loop guards and, for every
operand that resolves (via Phase 1's `ProgramLayoutIndex`) to a field a
boundary actually feeds (per Phase 2's `BoundaryReport`), emits a
`FieldConstraint`; the domain-propagation solver in `domains.py` (same PR)
turns a field's constraints into a concrete witness value.

```python
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.analysis.domains import solve

report = ConstraintExtractor().extract(ast, index, boundary_report)
report.branches              # list[BranchConstraints]: one per IF/EVALUATE/
                              # SEARCH decision point
report.sequence_constraints  # list[SequenceConstraint]: the READ/AT-END/
                              # PERFORM-UNTIL EOF-loop idiom
report.unsupported           # program-level gaps (never silently dropped)

branch = report.branches[0]
branch.arms                  # dict[str, list[FieldConstraint]]: arm_id ->
                              # conjuncts, e.g. {"THEN": [...], "ELSE": [...]}

witness = solve(field_spec, branch.arms["THEN"])   # Witness | Unsatisfiable
```

**Extraction sources and op vocabulary** (`FieldConstraint.op`): `eq ne lt le
gt ge in_set not_in_set class_numeric class_alphabetic figurative`.
Relational comparisons (`=`, `>`, `<`, `>=`, `<=`, `NOT =`/`<>`) map directly;
a level-88 bare condition-name (`IF ORDER-VALID`) resolves through
`ProgramLayoutIndex.resolve()` to its *parent* field and becomes `in_set`
over the 88's already-parsed `condition_values` (THRU ranges included);
figurative constants (`SPACES`/`ZEROS`/`LOW-VALUES`/...) become `figurative`
with the symbolic name preserved in `values`, not its literal expansion;
class tests (`IS NUMERIC`/`IS ALPHABETIC`) become `class_numeric`/
`class_alphabetic`; sign/zero tests (`IS POSITIVE`/`NEGATIVE`/`ZERO`) fold
directly into the relational vocabulary (`gt 0`/`lt 0`/`eq 0`) rather than
getting their own domain-handling branch. `negated` only carries meaning for
`class_numeric`/`class_alphabetic`/`figurative`, which have no separate "not"
op name (unlike `eq`/`ne` or `in_set`/`not_in_set`, which absorb negation
directly into the op choice).

**`class_numeric`/`class_alphabetic` extract cleanly but do not narrow a
witness in v1.** `domains.py`'s `solve()` treats both ops as a no-op on
whichever domain (`NumericDomain`/`TextDomain`) the field's category picked —
the arm containing an `IS NUMERIC`/`IS ALPHABETIC` test is still correctly
`"targeted"` (or `"merged"`) in `ScenarioPlanner`'s coverage accounting, and
every *other* constraint on the same field still narrows normally, but the
generated value for a field constrained *only* by a class test is not
guaranteed to actually satisfy that test — found producing
`docs/fixture-bundle-schema.md`'s worked example (Phase 6): an `IS NUMERIC`
arm's witness rendered as an arbitrary alphanumeric value, not a digit
string. Every other op in the vocabulary above is fully solved.

**AND/OR/NOT via De Morgan.** `IfStatement.condition` is walked once for the
THEN arm (`negate=False`) and once more for the ELSE arm (`negate=True`) --
there is no structural "NOT" node in this parser to walk instead (confirmed
against `_conditions.py`: negation is baked directly into concrete operator
strings like `NOT_EQUAL`/`IS NOT NUMERIC`, or resolved by the caller passing
`negate=True`). An AND stays a single conjunct list; a negated AND becomes a
disjunction (`NOT(A AND B) = NOT A OR NOT B`) and vice versa for OR --
implemented as one `(operator == "AND") != negate` boolean flip, not two
separate code paths. A conjunction drops the *whole* variant if either side
fails to extract (keeping only one conjunct would silently widen the modeled
domain past what the source requires); a disjunction safely keeps whichever
side(s) did extract (narrowing to fewer alternatives is still sound for
witness generation, just incomplete). More than one variant means an OR was
present; each becomes its own arm via a `#1`/`#2` suffix (`arms["THEN"]` vs.
`arms["THEN#1"]`/`arms["THEN#2"]`) -- the parent plan's dataclass models one
flat conjunct list per arm *id*, not a list of variants per arm, so OR
alternatives are represented as separate arms rather than nested lists.

**`branch_id` is not `ProgramFlowAnalyzer`'s `BranchNode.node_id`.**
Replicating `program_flow/scanner.py`'s exact sequential counter would
couple this module to that scanner's specific traversal order; instead
`branch_id` self-encodes `f"{parent_proc}@{line}:{column}"`, the same join
key `BranchNode` really is keyed by in substance. The actual join a later
phase should perform is `(line, column)` alone, via the dedicated `line`/
`column` fields (`column` added when Phase 5's `ScenarioPlanner` needed it --
see [generators.md](generators.md)) -- **not** by comparing `parent_proc`
strings: `program_flow/scanner.py` uppercases its own `parent_proc`
(`pname.upper()`) while this module preserves the source's original casing,
so the two are not directly comparable even when they name the same
paragraph (found writing Phase 5's own tests).

**PERFORM UNTIL's `until_condition` is never itself a `ConditionalExpression`
/`LogicalExpression`.** It is always the historical
`CobolExpression("CONDITION")` wrapper holding the raw joined string in
`.operands`; the real structural tree (when `_conditions.py`'s shared
machinery could build one) lives on its `.condition_tree` attribute (M12 --
see `perform_parser.py`'s `_make_until_condition_expression`). Walking
`until_condition` directly instead of `until_condition.condition_tree` was
the first bug found writing this module's own tests -- every PERFORM UNTIL
condition came back `"unsupported expression node: CobolExpression"`.

**The EOF/loop-flag idiom -> `SequenceConstraint`.** `_collect_eof_flags`
walks `ast.get_all_statements()` for every `IOReadStatement` whose
`at_end_clause` contains a `MoveStatement`, mapping the MOVE's target field
name to that READ's file name. When a `PERFORM UNTIL`'s condition mentions
that same field (by name only -- exact value match is not required, matching
on field identity is simpler and more robust to minor variations), the
`SequenceConstraint.boundary` is looked up from the *existing* `Boundary` in
`boundary_report.boundaries` (never freshly synthesized) so it is always a
real, already-resolved `BoundaryRef`. `length` is `None` in v1 -- "the flag
pattern exists" -- picking a concrete record count is Phase 5's job. A
condition that touches a boundary-fed field but matches no such pattern gets
one `unsupported` note rather than silence; a pure internal counter loop
(`PERFORM UNTIL I > 10`, `I` not boundary-fed) is correctly silent -- out of
scope, not a gap.

**SEARCH WHEN and `EVALUATE TRUE`'s non-compound selectors share one text
parser.** `SearchStatement.when_clauses`' `"condition"` key is a single raw
joined string, not a structured tree (unlike IF/PERFORM, SEARCH conditions
were never given the M12 structural treatment) -- confirmed against
`search_parser.py`. `EVALUATE TRUE WHEN <selector>` also lacks structure for
a simple relational selector: `evaluate_parser.py`'s `_build_selector` never
emits an `"Identifier"` selector type at all (a documented assumption this
module's first draft got wrong) -- a bare condition-name like `WHEN
F1-VALID` and a simple comparison like `WHEN F1-QTY = 5` both arrive as
`{"type": "Literal", ...}` / `{"type": "Condition", "text": ...}` with no
`"operator"` key, the *same* raw-text shapes SEARCH already has to handle.
Both route through the same minimal relational-text parser
(`_parse_relational_text`); a compound `AND`/`OR` selector text (`sel
["operator"]` present) stays unsupported in v1, same limitation as a
compound SEARCH WHEN.

**Two-field comparisons are unsupported in v1** (`IF F1-QTY > F1-STATUS`) --
stated as a parent-plan limitation, not attempted.

**Bug found writing this module's tests, fixed at the root (not worked
around): `>=`/`<=`/`<>` were silently mis-parsed everywhere**, not just
here. The lexer emits these as two separate single-character tokens (`>`
then `=`, never a combined `>=`); `_conditions.py`'s normalisation pass only
recombined `NOT`-prefixed pairs, so the comparison scan grabbed the bare `>`
as `GREATER` and left `= 5` dangling in the right-hand operand text --
confirmed empirically (`IF WS-X >= 5` parsed as `operator="GREATER",
right_operand="= 5"`) before this fix, for *every* consumer of
`build_condition_expression` (IF and PERFORM UNTIL both), not something
introduced by this phase. Fixed by recombining `">"+"="`, `"<"+"="`, and
`"<"+">"` into their compound tokens during the same cleaning pass that
already recombines `NOT`-prefixed operators (`_COMPOUND_SYMBOL_OPS`, see
[parser.md](parser.md)).

## ConstantFolder (`const_fold.py`)

Phase 7 tier 2 of the `gen-fixtures` initiative (see
`docs/plans/2026-08-02-program-data-generation-design.md`): a single forward
walk of a program's entry paragraph chain, seeded by one scenario's own
mock-supplied inputs, that tracks which data items hold a knowable literal
value after a MOVE or a simple arithmetic/COMPUTE statement. Wired into
`ProgramFixtureGenerator` (`generators/program_fixtures.py`'s
`_tier2_expectations`), which builds the seed dict from every
`BoundaryFixture` with *exactly one* generated row and turns every field
still knowable at a `DISPLAY`/`WRITE` into a `kind="field_equals"`
`Expectation` -- see `docs/fixture-bundle-schema.md`'s Expectation section
for the full worked example.

```python
from cobolparser.analysis.const_fold import ConstantFolder

folder = ConstantFolder()
result = folder.fold(ast, index, seed_values={"WS-QTY": "622"})
result.known   # dict[qualified_name, str]: fields still knowable at a
               # DISPLAY/WRITE, by the end of the walk
```

**"Exact by construction, or absent" -- never a guess.** Every ambiguity
below resolves by leaving a field unknown (poisoned: removed from the
internal env) rather than approximating:

* A `PERFORM ... UNTIL`/`VARYING`/`TIMES` loop may run zero or many times,
  so nothing inside it is knowable at fold time -- every field its body
  (including through a nested `PERFORM` to another paragraph) could write is
  poisoned, and the walk continues *after* the loop, since it still runs;
  the walk just cannot see inside it. A non-looping `PERFORM` (a plain
  paragraph call, optionally `THRU` a range) is walked inline exactly once,
  including into paragraphs it in turn `PERFORM`s, guarded against a
  non-looping `PERFORM` cycle by tracking which paragraphs are already on
  the current call stack.
* An `IF`/`EVALUATE` branches on data this walk does not evaluate (Phase 5's
  `ScenarioPlanner` already owns targeting one specific arm elsewhere), so
  every field either arm could write is poisoned the same way as a loop
  body -- this is a conjunctive walk, not per-scenario branch evaluation.
* `DIVIDE` is poisoned unconditionally: `DivideStatement` does not record
  whether `BY` or `INTO` was used (`_parse_binary_arithmetic` shares one
  code path for both, see [parser.md](parser.md)), and the two invert
  dividend/divisor order -- there is no way to compute the correct value
  from the node alone. A `/` inside a `COMPUTE` expression tree has no such
  ambiguity (both operands are structurally explicit, M12's
  `expression_tree`) and folds normally, including a divide-by-zero or
  non-terminating-decimal guard (both poison, not truncate).
* `ROUNDED`, `CORRESPONDING`, and any target that does not resolve to an
  elementary field are poisoned rather than approximated. A numeric
  MOVE/arithmetic result is only ever recorded when it fits its target
  field's PICTURE *exactly* (`_fits_exactly`: no truncated decimal digits,
  no truncated integer digits, no sign coercion into an unsigned field) --
  real COBOL's MOVE truncation rules are well-defined, but replicating them
  exactly is out of scope for v1; an overflowing result is poisoned instead.
* **A well-formed ADD/SUBTRACT self-reference is poisoned, not
  under-computed.** `ArithmeticStatement.operands` is a deduplicated union
  of the real addend/subtrahend tokens *and* the target/giving names
  (`set_target`/`set_giving` both call the same `_add_unique_operand` the
  addend-collection phase does) -- so `ADD X TO X` (doubling X) and "X was
  never a separate addend at all" produce the *identical* `.operands`
  shape, and the distinction is unrecoverable from the final AST. Since a
  well-formed ADD/SUBTRACT always has >= 1 real addend (parser-enforced),
  filtering target/giving names out of `.operands` and finding *nothing
  left* proves every addend coincided with a target -- the one shape this
  module can safely detect and poison. A blanket "poison on any operand/
  target overlap" was tried and rejected during development: a target's own
  name *always* ends up in `.operands` by construction (regardless of any
  genuine overlap), so that check fired on every ordinary `ADD 1 TO WS-X`,
  not just a self-reference -- found immediately via this module's own
  tests, before it ever reached the corpus sweep. A *partial* overlap
  (`ADD X, Y TO X`) is not caught and silently undercounts -- narrower and
  rarer, and documented in the source rather than silently. `MULTIPLY`'s
  format-1 (`MULTIPLY A BY B`, no GIVING) has no analogous issue:
  reusing the target's own name as the second operand is directly what the
  statement means (multiplication has no target-is-also-an-addend hidden
  term the way ADD/SUBTRACT's TO/FROM accumulation does), so only GIVING
  names are filtered from its operand list, never targets.
* **ACCEPT/READ are a deliberate no-op, not an omission.** They are exactly
  the boundary categories `_tier2_expectations` seeds `env` from before the
  walk starts; falling through to the generic "unmodeled write" fallback
  below would poison that seed the instant the walk reached the very
  statement it represents. `CALL`/`EXEC SQL`/`CICS`/`DLI` are *not* given
  the same treatment -- their operand lists mix genuinely-unknowable
  OUT-direction values with seedable IN ones, and the raw AST does not carry
  resolved direction to tell them apart (only `BoundaryInventoryAnalyzer`'s
  own richer analysis does) -- deferred to a future version rather than risk
  treating an OUT value as still-known.
* Any other statement type this module has no specific rule for
  (`INITIALIZE`, `SET`, `STRING`/`UNSTRING`, `INSPECT`, and the CALL/SQL/
  CICS/DLI cases above) conservatively poisons every name in its `.operands`
  -- a fail-safe default, not a silent skip.
* Only a `DISPLAY`/`WRITE` operand that resolves *directly* to an elementary
  field is an observation point -- a whole-record `WRITE`'s individual
  member fields are not (yet) walked, so some real `field_equals`
  opportunities are silently not offered. Never wrong, sometimes just
  quieter than it could be. `GO TO`, `STOP RUN`, `GOBACK`, and `EXIT
  PROGRAM` all stop the walk outright (unreachable code after them is never
  folded or observed).

**Bug found via a NIST-corpus smoke sweep, fixed at the root (not worked
around): `ProgramLayoutIndex.resolve()` crashed (`IndexError`) on an
all-punctuation name** (`"."`, from a stray token that leaks into some
statement's `.operands` for at least one real-world program -- a parser
artifact this module cannot prevent at the source). `resolve()`'s dotted-
name and `OF`/`IN` branches both stripped every segment to nothing and then
indexed into the resulting empty list; both now return `None` instead. Also
hardened at this module's own call site (`_safe_resolve`, a thin wrapper
that rejects empty/punctuation-only tokens before ever calling `resolve()`)
as a second line of defense, since the generic "poison via `.operands`"
fallback above is exactly the path most exposed to non-name garbage.
Verified against the full 459-file NIST COBOL-85 corpus (zero crashes, zero
layout violations) in addition to the 24-file shamrice corpus test below.

**Bug found via a manual stress repro, fixed at the root: an uncaught
`RecursionError` on an ordinary large program.** `_walk_perform` followed a
chain of out-of-line `PERFORM`s (`P1` performs `P2` performs `P3` ... `PN`)
by recursing through Python's own call stack, one frame per paragraph in the
chain -- a few hundred chained paragraphs (well under
`sys.getrecursionlimit()`'s default of 1000) was enough to crash, and a
"long straight-line paragraph chain" is not an adversarial input shape, it's
an ordinary large COBOL program. `_poison_written_names` had the identical
defect for a `PERFORM`-to-paragraph chain reached from inside a poisoned
loop/branch body (confirmed reproducible around ~1000-1500 chained
paragraphs, a higher threshold since it recurses through fewer stack frames
per paragraph than `_walk_perform`'s three-function call chain did). Both
now follow the chain via an explicit frame stack -- one entry per open
paragraph, `visiting` add/discard bracketing the frame's lifetime exactly as
the recursive version did -- the same fix this file's `ProgramFlowAnalyzer`
section above documents `program_flow/cycles.py`'s own paragraph-graph
traversal already applying, for the identical reason. Recursion is still
used for genuinely *nested* statement lists (an
`IF`/`EVALUATE` arm or loop body found within a block already being
poisoned, and an inline `PERFORM ... END-PERFORM` nested inside another
inline `PERFORM`) -- that depth is bounded by real source nesting, not by
paragraph-chain length, so it was left alone rather than rewritten
speculatively. Pinned by
`tests/unit/analysis/test_const_fold.py::TestPerformChaining::test_long_straight_line_perform_chain_does_not_blow_the_stack`
and `::test_long_perform_chain_inside_a_loop_body_does_not_blow_the_stack`
(2000-paragraph chains, both directions).

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
| `constraints.py` | `ConstraintExtractor` (Phase 4 of `gen-fixtures`) |
| `domains.py` | `solve()` constraint/witness solver (Phase 4 of `gen-fixtures`) |
| `const_fold.py` | `ConstantFolder` (Phase 7 of `gen-fixtures`) |

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
  source `BoundaryInventoryAnalyzer`/`ConstraintExtractor`/`ConstantFolder`
  all resolve record/field names through; `ProgramFixtureGenerator`, which
  wires `ConstantFolder` into `field_equals` expectations (Phase 7)
* [`../docs/fixture-bundle-schema.md`](../docs/fixture-bundle-schema.md) —
  the full `Expectation` shape `call_count`/`field_equals`/`stub` produce
* `docs/plans/2026-08-02-program-data-generation-design.md` and its per-phase
  implementation plan — the full 9-phase `gen-fixtures` plan this file
  documents Phases 2, 4, and 7 of
