---
type: Module
title: Static Analysis
description: 16 static-analysis modules — dead code, unused variables, program flow, IO sequence, move-type, linkage, CRUD, boundary inventory, constraint extraction, constant folding, and more.
tags: [analysis, dead-code, unused-variables, program-flow, io, crud, boundary-inventory, fixtures, constraints, const-fold]
timestamp: 2026-08-16T00:00:00Z
---

# Overview

`cobolparser/analysis/` — 16 static-analysis modules. All follow the same
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
    UnusedVariableAnalyzer,
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
target of a PERFORM, GO TO, or fall-through control flow). The first
procedure is always referenced (program entry point), and so is any
paragraph containing an `EntryStatement` (2026-08-11 fix, see below).

**DeadCodeAnalyzer had no fall-through concept at all (2026-08-11 fix,
audit finding #1 of 7).** Unlike `ProgramFlowAnalyzer` (which has
`graph.build_fall_through_edges`), `_collect_references` only looked at
PERFORM/GO TO/SORT/MERGE/ALTER/ENTRY references — any paragraph reached
purely by falling off the end of the previous one (the default shape of a
straight-line COBOL program with no explicit control transfer) was
reported dead. Fixed by adding `_collect_fallthrough_refs`, which walks
`_ordered_procedures` left to right and marks a procedure referenced when
the one immediately before it is itself already known to be reachable
(gated on membership in `_referenced_names`, which this same pass keeps
extending) and does not terminate per `_terminates`: any of its own
top-level statements (not just the last one — see Copilot follow-up below)
is a hard terminator (`STOP RUN` — not `STOP 'literal'`, which merely
halts pending operator action; `GOBACK`; `EXIT PROGRAM`) or an
unconditional (non-`DEPENDING`) `GO TO`. The reachability gate matters:
without it, a chain of paragraphs that are *all* themselves unreached
would still credit each other purely for standing next to one another in
source, masking real dead code (`DEAD-1`/`DEAD-2`/`DEAD-3` stubs after an
unrelated `STOP RUN` would otherwise cascade-reference each other). Runs
after entry-point marking (moved earlier in `analyze()` for this reason)
so the first procedure seeds the pass. A bare `SECTION` header has no
statements of its own (`_paragraph_nodes` only holds paragraphs) so
`_terminates` always returns `False` for one — falling into a section
always reaches its content. Same termination semantics as
`ProgramFlowAnalyzer.build_fall_through_edges` (below), but implemented
independently per this module's existing flat reference-marking
architecture rather than sharing code with `program_flow`. Pinned by
`tests/unit/analysis/test_dead_code.py::TestFallThroughReferences`.

**`_terminates` only checked the last top-level statement — caught by
Copilot review on the PR.** A hard terminator or unconditional `GO TO`
earlier in a paragraph (not its last statement) still unconditionally
fires when reached — anything physically written after it is itself
unreachable and doesn't change whether the paragraph as a whole falls
through, so checking only `para.statements[-1]` missed it (e.g. `STOP
RUN. DISPLAY 'X'.` was wrongly treated as non-terminating, crediting the
next procedure as fall-through-reachable). Fixed by extracting a static
`_is_terminator(stmt)` helper and checking `any(...)` over every top-level
statement instead of just the last. Nested statements (inside an
IF/EVALUATE arm) are still deliberately excluded — same rationale as
before. Pinned by
`test_terminator_earlier_in_paragraph_still_cuts_off_fall_through`.

**A paragraph holding an ENTRY statement is always referenced (2026-08-11
fix, audit finding #5).** `EntryStatement` marks an alternate external entry
point (`CALL 'entry-name'`), so `_collect_references` now dispatches it to
`_collect_entry_refs`, which marks `stmt.section_name` (the *containing
paragraph's* name -- `CobolParagraph` overrides `ASTNode.section_name` to
return its own `paragraph_name`, so walking a statement's `.section_name` up
the `.parent` chain lands on its paragraph regardless of nesting depth or
whether a real SECTION also exists) as referenced. Before this, `dead_code.py`
had no `EntryStatement` handling at all, so an ENTRY paragraph reachable only
via its literal external name was falsely reported dead. `_collect_entry_refs`
applies the same blank/whitespace-only-literal filter
`program_flow/scanner.py`'s `collect_entry_points` does (a malformed ENTRY
with no real name isn't a real alternate entry point) so it doesn't mask an
otherwise-dead paragraph -- added after Copilot PR review caught the two
analyzers diverging on this filter. Pinned by
`tests/unit/analysis/test_dead_code.py::TestEntryReferences`.

**ALTER only references its target, not its subject (2026-08-11):**
`ALTER paragraph-name TO PROCEED TO target-name` modifies a GO TO living
inside `paragraph-name`; only `target-name` is an incoming jump.
`_collect_alter_refs` used to add both names to the reference set, so a
paragraph named solely as an ALTER's subject was wrongly protected from
dead-code detection even when nothing ever PERFORMed/GONE TO it. This put
`DeadCodeAnalyzer` out of step with `ProgramFlowAnalyzer`'s
`unreachable_nodes`, whose ALTER edge (`edges.py::process_alter`) already
only flowed subject to target and never had this bug. Fixed by dropping the
`from_paragraph` add in `_collect_alter_refs`; only `to_paragraph` counts as
referenced now. Pinned by
`TestAlterReferences.test_alter_never_called_paragraph_is_dead`
(`tests/unit/analysis/test_dead_code.py`).

**`_propagate_section_references` resurrected unrelated dead siblings
(2026-08-13 audit finding).** The function chained an upward pass (any
referenced paragraph marks its parent section referenced) followed by a
downward pass (a referenced section marks *all* its paragraphs referenced)
in that order. Since the two passes share the same mutable
`_referenced_names` set, a paragraph referenced only by a plain `PERFORM
child-paragraph` (not `PERFORM section-name`) bootstrapped its parent
section into "referenced" via the upward pass, and the downward pass then
broadcast that to every *sibling* paragraph in the section too --
resurrecting paragraphs nothing PERFORMs/GOes TO and that fall-through
never reaches. Real COBOL semantics only cascade to every paragraph in a
section when the *section itself* is PERFORMed/GONE TO (or fallen into);
PERFORMing one paragraph inside it returns to the caller afterward and does
not run the rest of the section. Fixed by reordering: downward now runs
*first*, so it only ever sees sections that were already directly
referenced by `_collect_references`/entry-point-marking/
`_collect_fallthrough_refs` before this function ran, never sections that
became "referenced" purely via a child's own reference. Pinned by
`tests/unit/analysis/test_dead_code.py::TestSectionPropagationDoesNotResurrectSiblings`.

**Computed GO TO targets read from `target_paragraphs`, not operand
filtering (2026-08-11):** `_collect_goto_refs` used to reconstruct a
computed `GO TO ... DEPENDING ON` statement's targets by filtering
`stmt.operands` against `stmt.depending_on_variable` (`[op for op in
stmt.operands if op != depending_on_variable]`). `GoStatement`'s setters
(`set_target_paragraph`/`add_target_paragraph`/`set_depending_on_variable`)
add operands via `_add_unique_operand`, which dedupes, so a target
paragraph that happens to share its name with the DEPENDING ON variable
(`GO TO PARA-A RUN-FLAG
DEPENDING ON RUN-FLAG.`) collapses into one operand entry, which the filter
then drops entirely — the shared-name target was reported dead despite
being live. `GoStatement.target_paragraphs`
(`cobolparser/models/statements/control.py`) already holds the exact,
unfiltered target list — populated correctly by `go_parser.py`'s
`set_target_paragraph`/`add_target_paragraph` calls — so `_collect_goto_refs`
now just iterates it directly. Same root cause and same fix shape in
`ProgramFlowAnalyzer.process_goto` below. Pinned by
`test_goto_depending_target_sharing_name_with_variable` in both
`tests/unit/analysis/test_dead_code.py` and
`tests/unit/analysis/test_program_flow.py`.

**Paragraphs before the first SECTION must stay first in source order
(2026-08-11, dead-code-section-550f0e finding #1).** COBOL legally allows
paragraphs before the first `SECTION` header. `_collect_procedures` used to
append all section-owned paragraphs to `_ordered_procedures` before the
top-level (pre-SECTION) paragraphs, so a program mixing the two produced an
`_ordered_procedures` list that no longer matched physical source order.
Since `analyze()` always treats `_ordered_procedures[0]` as the referenced
program entry point, this fabricated a false-dead-code report for the real
first paragraph (a section became entry point instead) whenever a program
had any top-level paragraph before its first section — a legal, if
uncommon, shape. Fixed by interleaving sections and top-level paragraphs by
`location.line` before walking them, so `_ordered_procedures` always matches
source order regardless of section/paragraph mix. `ProgramFlowAnalyzer`
(below) had the identical bug in the same shape, from the same duplicated
collection logic. Pinned by
`tests/unit/analysis/test_dead_code.py::TestDeadCodeIntegration::test_top_level_paragraph_before_section_stays_first_in_order`.

**The interleave fix made the pre-existing dedup guard order-dependent —
caught by review before landing.** The dedup guard (`if upper_pname not in
self._procedure_names`) previously lived only on the top-level-paragraph
branch, which was safe *only* because sections were always walked first —
by the time a top-level paragraph was considered, any same-named
section-owned paragraph was already registered. Interleaving by
`location.line` breaks that assumption: when a top-level occurrence of a
duplicated name sorts before its section-owned twin, the (still-unguarded)
section branch would append it to `_ordered_procedures` a second time. The
section-owned-paragraph branch now carries the identical guard. Pinned by
`tests/unit/analysis/test_dead_code.py::TestDeadCodeIntegration::test_duplicate_name_across_top_level_and_section_not_double_counted`.

**The SECTION-registration branch itself had no dedup guard at all —
caught by Copilot review on the PR.** Unlike both paragraph branches, the
code that records a `SECTION` header into `_procedure_names` never checked
whether that name was already registered. A top-level paragraph followed
later in source by a same-named `SECTION` (e.g. `DUP-NAME.` ... `DUP-NAME
SECTION.`) would have its `PARAGRAPH` entry silently overwritten by a
`SECTION` entry, and the name duplicated in `_ordered_procedures`. Fixed by
adding the same guard to the SECTION branch; `_section_paragraphs[name]`
is still unconditionally ensured via `.setdefault()` even when the guard
skips the SECTION's own registration, since the paragraph loop right below
it always appends into that bucket. Pinned by
`tests/unit/analysis/test_dead_code.py::TestDeadCodeIntegration::test_duplicate_name_across_top_level_paragraph_and_section_header`.

## UnusedVariableAnalyzer (`unused_variables.py`, 2026-08-13)

```python
report: UnusedVariableReport = UnusedVariableAnalyzer().analyze(ast)
# report.unused_items: list[UnusedVariableItem]  (name/level/section/location/from_copybook)
```

Detects DATA DIVISION items (FILE/WORKING-STORAGE/LOCAL-STORAGE/LINKAGE,
any level, FILLER and synthetic `ANONYMOUS-<level>-<line>` names always
excluded) never referenced anywhere in the PROCEDURE DIVISION. Single-program
scope, same as `DeadCodeAnalyzer`/`ProgramFlowAnalyzer` — does not recurse
into `ast.contained_programs`.

**Reference collection is `.operands`-first, with per-statement-type
extras.** Every `CobolStatement` already accumulates most of its own
identifier/literal tokens into `.operands` via `_add_unique_operand`/
`add_operand`, but an empirical audit (grepping every statement model's
setters) found real gaps where a setter never reaches `.operands` at all:
`ExecSqlStatement.host_variables`/`.null_indicators` (SQL statements don't
touch `.operands` at all), `UnstringStatement.source_operand`/
`.into_targets`/`.pointer_variable`/`.tallying_variable`,
`StringStatement.into_target`/`.pointer_variable`,
`InspectStatement.tallying_clauses`/`.replacing_clauses`/
`.converting_from`/`.converting_to`, `SearchStatement.table_name`/
`.varying_variable`, `SortStatement.keys`/`MergeStatement.keys` (the
`"field"` key), and `PerformStatement.varying_clause`/`.after_clauses`
(`"variable"`/`"from_value"`/`"by_value"`). All handled via the module-level
`_STR_ATTR_EXTRAS`/`_DICT_LIST_EXTRAS` lookup tables plus explicit
per-type branches in `_collect_referenced_names`, rather than trusting
`.operands` alone. The tables are looked up by walking `type(stmt).__mro__`,
not exact type — an exact-type lookup would silently lose a keyed
statement class's extras the moment any real subclass of it existed (none
do today, but the failure mode is exactly the "used field reported
unused" bug this module exists to avoid), pinned by
`TestExtrasLookupIsMroAware` in `tests/unit/analysis/test_unused_variables.py`.

**An operand string is tokenized, not treated as one opaque name (Copilot
PR-review fix, 2026-08-13).** Statement parsers routinely join a whole
qualified reference, subscript, special register, or intrinsic function
call into a *single* operand string rather than splitting out the
underlying data-name(s) — confirmed empirically: `MoveStatement.source`
for `MOVE WS-A OF WS-GRP TO ...` is the literal string `"WS-A OF WS-GRP"`;
`"FUNCTION UPPER-CASE(WS-X)"` and `"LENGTH OF WS-X"` are the same shape.
The first version of this module added such an operand verbatim as one
name, so `WS-A`/`WS-GRP`/`WS-X` never matched a declared item's bare name
and were falsely reported unused. `_extract_identifiers` (renamed from
the narrower `_extract_identifier_tokens`, which now also replaces the
old boolean `_is_identifier_operand` gate everywhere) is the single
extraction path for every operand/extra-field/condition-fallback value:
it strips quoted substrings, regex-extracts every letter-led token, and
filters `_NON_IDENTIFIER_WORDS` (figurative constants merged with
qualification/special-register/intrinsic-function keywords `OF`/`IN`/
`FUNCTION`/`LENGTH`/`ADDRESS` and the raw-condition-text stopwords). A
bare numeric literal never matches at all since a token must start with
a letter, so the old explicit numeric/quoted-literal pre-checks were
subsumed rather than kept as a separate fast path. Deliberately
over-inclusive in the same direction as the condition-text fallback
below: a stray token (an intrinsic function name, say) only risks
coincidentally matching an unrelated declared item, never causes a used
item to be reported unused. Pinned by `TestQualifiedAndFunctionOperands`
in `tests/unit/analysis/test_unused_variables.py`.

**Condition/expression trees are walked separately from `.operands`.**
`IfStatement.condition`, `PerformStatement.until_condition`/
`after_clauses[].until_condition`, and `ComputeStatement.expression_tree`
never reach `.operands` (confirmed: `IfStatement.set_condition` only calls
`add_child`, matching `program_flow/condition_text.py`'s note that the raw
condition text/tree lives entirely off the statement). `_walk_expression_operands`
mirrors `render_condition_text`'s dispatch (`LogicalExpression` ->
recurse both sides; `ConditionalExpression`/`ArithmeticExpression` ->
`left_operand`/`right_operand`; `FunctionCall` -> `arguments`) but collects
leaf identifiers instead of rendering text, falling back to a best-effort
regex over `operands[0]`/`raw_condition` for a node shape it can't
decompose structurally (SEARCH WHEN and `EVALUATE TRUE` Condition-type
selectors, per `constraints.py`'s same documented gap — see
`ConstraintExtractor`'s section above). The fallback is deliberately
over-inclusive: a false positive there only makes the analyzer *miss* an
unused variable, never wrongly flag a used one.

**EVALUATE subjects are walked explicitly — they never reach `.operands`
either (found during a review of this module, 2026-08-16).**
`evaluate_parser.py`'s `_parse_subjects` appends straight to
`EvaluateStatement.subjects`, bypassing `add_subject()` — the setter that
exists specifically to also call `add_operand()` — so `EVALUATE WS-CODE`/
`EVALUATE WS-A ALSO WS-B` left the subject name(s) out of `.operands`
entirely (confirmed empirically: `stmt.operands == []` for a bare
`EVALUATE WS-CODE` while `stmt.subjects == ["WS-CODE"]`). Only the `WHEN`
selectors were already special-cased in the `EvaluateStatement` branch of
`_collect_referenced_names`; a field referenced solely as the subject was
falsely reported unused. `constraints.py` and `program_flow/scanner.py`
already read `stmt.subjects` directly and were unaffected — the fix is
scoped to this module's `EvaluateStatement` branch, which now also walks
`stmt.subjects` (via `_walk_expression_operands` for a `CobolExpression`
subject, `_extract_identifiers` for the plain-string case the real parser
always produces). Pinned by `TestEvaluateSubjects` in
`tests/unit/analysis/test_unused_variables.py`.

**Group items, level-88s, REDEFINES, and OCCURS DEPENDING ON are
structural, not textual, dependencies.** A group item counts as used if
any descendant field is used (post-order `is_used()` over `item.children`);
a level-88 `ConditionNameItem` child being referenced (`IF ORDER-VALID`)
marks its parent elementary item used too. `X REDEFINES Y` marks `Y` used
whenever `X` is used (propagated to a fixpoint for REDEFINES chains,
resolved by uppercased name via a `by_name` index — not structural item
identity, a documented limitation for the rare case of duplicate
same-named items at different qualification scopes). An `OCCURS ...
DEPENDING ON` variable is unconditionally marked used via
`_collect_data_division_references`, since it's a real runtime dependency
even when never touched procedurally. Level-66 RENAMES targets
(`renames_from`/`renames_through`) are marked used the same
unconditional way.

**Copybook provenance is set-difference, not line-tracking — because the
line-tracking feature doesn't work.** `expand_copybooks`'s own
`preserve_source_locations` parameter threads all the way down to
`_expand_source_recursive` but never actually populates
`context.source_maps` (a literal `pass` at the write site, with a comment
admitting it's "disabled by default in the expander" — see
[preprocessing.md](preprocessing.md) if that file gains its own note, or
`copybook_expander.py` around the `preserve_locations and
statement.source_location` check). Discovered empirically while designing
this analyzer's copybook flag; not fixed here (a different, cached,
perf-sensitive subsystem). Instead, `analyze()` takes an optional
`copybook_item_names: set[str]` the caller computes by diffing
`collect_declared_items()` on an *unexpanded* parse against the expanded
one — see the `unused-variables` CLI subcommand
(`_parse_without_copybook_expansion` in `cli/parse.py`) for the reference
implementation. `include_copybook_variables=False` then excludes any
unused item in that set from `report.unused_items` (tallied instead in
`report.skipped_copybook_count`); the flag is a documented no-op when
`copybook_item_names` is None.

**SCREEN/REPORT/COMMUNICATION SECTION false-positive noise was fixed
upstream, not in this module.** This analyzer originally found (empirically,
against `tests/samples/screen_section_io.cbl` and `report_writer.cbl`
while validating against the sample corpus) that the DATA DIVISION parser
mis-parsed SCREEN/REPORT/COMMUNICATION SECTION clauses as nested
WORKING-STORAGE data items (a SCREEN SECTION `COLUMN 5` clause became an
item literally named `COLUMN`), spawned as a separate follow-up task
rather than fixed here. That parser fix has since landed (same day —
`parsers/divisions/data.py`'s `_skip_section`; see [log.md](log.md)): the
three section headers are now recognized and their
content discarded into distinctly-named, always-empty `SCREEN`/`REPORT`/
`COMMUNICATION` sections. `collect_declared_items` only ever recognized
FILE/WORKING-STORAGE/LOCAL-STORAGE/LINKAGE, so no analyzer-side change
was needed — the noise disappeared once the parser stopped corrupting
WORKING-STORAGE. Confirmed empirically post-fix: `screen_section_io.cbl`'s
WORKING-STORAGE dropped from 33 spurious items back to its real 5.

CLI: `unused-variables` subcommand — see [cli.md](cli.md).

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

**A conditional GO TO was treated the same as an unconditional
fall-through terminator (2026-08-11 fix, audit finding #5 of 7).**
`build_fall_through_edges` (`graph.py`) used to suppress a paragraph's
fall-through edge whenever *any* `GOTO`-type edge originated from it, with
no check that the GO TO was the paragraph's own unconditional last
statement — a GO TO nested inside an `IF` (no `ELSE`) only fires when the
condition is true, so the paragraph still falls through whenever it isn't.
Fixed by having `ProcedureScanner._scan_paragraph_statements` check, per
paragraph, whether it has a bare, non-`DEPENDING`, targeted `GO TO`
(checked directly against `para.statements` — not via the statement-tree
walk, so it's unaffected by nesting/arm context), threaded through
`ProcedureScanner`'s constructor and `build_fall_through_edges` as a
`terminating_paragraphs` set; suppression now gates on membership in that
set instead of "any GOTO edge exists". Dropped the pre-existing
`node.perform_count == 0` conjunct in the same change (folded in rather
than landing separately): it had no remaining justification once the
paragraph's own last statement is tracked directly — PERFORM always
returns control to the statement after it (the GO TO), so an earlier
PERFORM in the same paragraph cannot create a path back to a fall-through
(repro: `MAIN. PERFORM HELPER. GO TO MAIN.`, a self-looping main-loop
paragraph, used to produce a spurious `MAIN -> HELPER` edge). Pinned by
`TestProgramFlowFallThrough::
test_conditional_goto_inside_if_does_not_suppress_fall_through`,
`::test_unconditional_trailing_goto_still_suppresses_fall_through`, and
`::test_fall_through_when_goto_and_perform_both_present` (rewritten in
place to assert the corrected, suppressed behavior).

**Two more precision bugs in the same suppression logic — caught by
Copilot review on the PR, fixed in the same pass rather than landing
separately.** (1) Checking only `para.statements[-1]` for the GO TO missed
an *earlier* top-level terminator followed by now-dead trailing
statements (`STOP RUN. DISPLAY 'X'.` was wrongly treated as
non-terminating). (2) `build_fall_through_edges` *also* suppressed
whenever `node.has_stop_run`/`has_goback`/`has_exit_program` was set — but
`ProcedureScanner`'s statement-tree walk sets those flags whenever it
encounters the statement *anywhere*, including nested inside an
IF/EVALUATE arm, which is the exact same class of bug this finding fixes
for GO TO, just for the other three terminator kinds. Both fixed together
by replacing the last-statement-only GO TO check and the
`has_stop_run`/`has_goback`/`has_exit_program` check with one unified
signal: `ProcedureScanner._is_terminator(stmt)` (a static per-statement
predicate covering `STOP RUN`/`GOBACK`/`EXIT PROGRAM`/unconditional
`GO TO`, mirroring `DeadCodeAnalyzer._is_terminator`) is checked with
`any(...)` over `para.statements` directly — top-level-only by
construction, at any position, not just the last — populating the renamed
`terminating_paragraphs` set that `build_fall_through_edges` now relies on
exclusively (the `has_stop_run`/`has_goback`/`has_exit_program` fields
themselves are untouched and still used elsewhere — flowchart-generator
terminal nodes, `is_exit_point` — where their broader "anywhere in the
paragraph" semantics remain intentional). Known boundary, not addressed:
a terminator inside an *unconditional* bare `PERFORM ... END-PERFORM`
block (no `UNTIL`/`TIMES`) isn't detected either, since inline PERFORM
bodies aren't top-level statements — a rare construct, out of scope for
this fix. Pinned by
`test_terminator_earlier_in_paragraph_still_suppresses_fall_through` and
`test_conditional_stop_run_inside_if_does_not_suppress_fall_through`.

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
or `EXIT PROGRAM` — both `to_dict()` (present only when both fields are
set; absent from the dict entirely otherwise) and both flowchart generators
render a distinct terminal node (`shape=doublecircle` in DOT, `(((...)))` +
the `terminal` classDef in Mermaid) per exit statement, labeled `"{kind} @
{line}"` (ASCII `@` since 2026-08-12; see generators.md's "Label
fidelity"). First-write-wins: `_record_exit_statement` only sets the fields
the first time a paragraph's `scan()` walk reaches an exit-eligible
statement (e.g. `STOP RUN` in an `IF`'s THEN arm and `GOBACK` in its ELSE
arm keeps whichever is scanned first).

**Branch-arm statement summaries (2026-08-12):**
`cobolparser/analysis/program_flow/statement_text.py` adds
`summarize_statement(stmt) -> str` — a compact, COBOL-like one-liner
(`"MOVE 8 TO RETURN-CODE"`, `"PERFORM 4000-CLEANUP"`, `"IF <rendered
condition>"` via `render_condition_text`) with type-specific branches for
the common arm-opening statements (MOVE/PERFORM/GO TO/CALL/SET/COMPUTE/
ADD/SUBTRACT/MULTIPLY/DIVIDE/DISPLAY/IF/EVALUATE/STOP/GOBACK/EXIT) and a
`statement_type + operands` generic fallback that never raises, truncated
to 48 chars — and `summarize_arm(statements) -> str | None` (first
statement's summary, `None` for an empty arm; the "+N more" marker is the
generators' presentation concern, from `statement_count`). `BranchArm`
gained `summary: str | None` (`models.py`), populated by `scanner.py` for
all four arm kinds (THEN/ELSE/WHEN/WHEN OTHER); `to_dict()` includes the
key only when non-None, the report's usual optional-field convention. The
flowchart generators render it instead of the bare THEN/ELSE keyword —
see [generators.md](generators.md).

**Mypy narrowing fix (2026-08-13, no behavior change):** the EVALUATE
subject-summary line used `hasattr(s, "to_dict")` to distinguish a
`CobolExpression` subject from a bare `str` one
(`EvaluateStatement.subjects: list[str | CobolExpression]`) — mypy can't
narrow a union on `hasattr`, so it still saw the full union at the
`render_condition_text(s)` call, which only accepts `CobolExpression |
None`. Swapped for `isinstance(s, CobolExpression)`, which mypy narrows
correctly; runtime behavior is identical.

**RETURN is explicitly excluded (bug fixed 2026-08-11):** `RETURN` reads
the next record from a SORT/MERGE file — it does not terminate the
program, and `scanner.py` deliberately does not add RETURN's paragraph to
`self._exit_points` either (`node.is_exit_point` stays `False`). An earlier
task's `scan()` change called `_record_exit_statement(node, "RETURN",
stmt.location)` anyway, so a paragraph's RETURN got rendered as a red
terminal double-circle by both flowchart generators — directly
contradicting the analyzer's own `is_exit_point` classification for the
same node. Fixed by removing that call; `node.has_return` (unrelated,
correct) is unaffected.

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
# IOViolationKind: READ_BEFORE_OPEN, WRITE_BEFORE_OPEN, REWRITE_BEFORE_OPEN,
#                  DELETE_BEFORE_OPEN, START_BEFORE_OPEN, DOUBLE_OPEN,
#                  CLOSE_NOT_OPEN, DOUBLE_CLOSE, FILE_LEFT_OPEN
```

Validates that IO operations follow legal COBOL sequencing rules (file must be
opened before read/write, etc.).

**Only `STOP RUN` is program termination (2026-08-12 fix, audit A-B1):**
the end-of-program handling (flag still-open files, clear open-file state)
used to fire for ANY `StopStatement`, but `STOP 'literal'` merely pauses for
operator action and execution continues -- so `OPEN, STOP 'literal', READ,
CLOSE` produced spurious FILE_LEFT_OPEN + READ_BEFORE_OPEN violations. Now
gated on `stop_type == "RUN"`, the same distinction `dead_code.py`'s and
`program_flow/scanner.py`'s `_is_terminator` already draw. Pinned by
`tests/regression/test_audit_2026_08_12_analysis.py::TestB1StopLiteralIsNotTermination`.

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
report: LinkageReport = LinkageChecker().check(ast)   # note: .check(), not .analyze()
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

**Open modes are per-file (2026-08-12 fix, audit A-A3):** `OPEN INPUT
IN-FILE OUTPUT OUT-FILE` used to record INPUT (the statement's *first* mode
group, `stmt.open_mode`) for every file in the statement. `_collect_open_modes`
now reads `IOOpenStatement.file_modes` (the authoritative per-file dict the
parser populates per mode group), falling back to `open_mode` only for a
file with no per-file entry. Pinned by
`tests/regression/test_audit_2026_08_12_analysis.py::TestA3OpenModesPerFile`.

## DynamicCallAnalyzer

```python
from cobolparser.analysis import DynamicCallAnalyzer
DynamicCallAnalyzer().analyze(ast)   # mutates ast, annotating dynamic CALL targets
```

Tracks possible values for variables used in dynamic CALL statements via MOVE
and VALUE clause analysis.

**An untracked identifier-shaped MOVE source is not a value (2026-08-12 fix,
audit A-B3).** `MOVE WS-INPUT-PROG TO WS-TARGET` (where `WS-INPUT-PROG` has
no VALUE clause and no tracked MOVE) used to record the literal string
`"WS-INPUT-PROG"` -- a data-name, not a value -- into `WS-TARGET`'s possible
values (the parser keeps quotes on `MoveStatement.source`, so an unquoted
hyphenated token is always a reference). Value recording is now gated on
`_is_definite_literal` (quoted string / numeric literal / figurative
constant only); an untracked identifier source instead marks the target's
value set INCOMPLETE, propagated through variable-to-variable MOVEs, and any
dynamic CALL on such a variable gets
`get_metadata("possible_values_incomplete") == True` so a consumer knows
`possible_values` (even when non-empty) is not exhaustive. Pinned by
`tests/regression/test_audit_2026_08_12_analysis.py::TestB3UntrackedIdentifierSourceIsNotAValue`.

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
OUTPUT B` in one statement) and -- since 2026-08-12 (audit A-A7) -- carry
`status_field` resolved via `index.file_facts(...)` the same way
READ/DELETE/START/UNLOCK always did; before that, `ScenarioPlanner`'s
"OPEN -> FILE STATUS 35" error family could never fire because the OPEN
boundary it gates on never had a `status_field`. DELETE/START/UNLOCK are
`STATUS_ONLY` (no data payload); READ is `IN`; WRITE/REWRITE are `OUT`.

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
**Two-pass since 2026-08-12 (audit A-B2):** `analyze()` first collects every
SQL/CICS/DLI site's FULL normalized text per category
(`_collect_exec_texts`), and each site's prefix is checked against all
OTHER same-category sites' full texts (`_other_texts`). The old single-pass
compared against previously *assigned* (already-shortened) keys, which made
keys walk-order-dependent and let the first site keep a key that was a
prefix of a later sibling's text (`SELECT A FROM T` / `SELECT B FROM T`
yielded `SELECT` + `SELECT B`; now `SELECT A` / `SELECT B`, in either
source order). Pinned by
`tests/regression/test_audit_2026_08_12_analysis.py::TestB2ExecKeysAreOrderIndependentPrefixes`.

**Nested-body walk**: the same discipline `IOLogger` and mockymock's
`mock_surface` both converged on independently -- a fixed set of
`getattr()`-checked attributes (`then_statements`, `else_statements`,
`inline_statements`, the IO/CALL clause bodies) plus two special cases:
`EvaluateStatement.when_clauses`/`.default_when` are `WhenClause` *nodes*
with a `.statements` attribute, while `SearchStatement.when_clauses` is a
**list of dicts** with a `"statements"` key -- a different shape, and a
documented trap (mixing the two loop variables up trips mypy immediately,
which is how this was caught). **2026-08-12 (audit A-A5):** both this
module's and `constraints.py`'s `_NESTED_STATEMENT_ATTRS` were missing
`on_size_error`, `not_on_size_error`, `not_on_overflow`, and
`not_at_eop_clause` (all real model attributes `program_flow/scanner.py`
and `const_fold.py` already walked) -- a `CALL 'ERRLOG'` nested in an
arithmetic `ON SIZE ERROR` produced no boundary at all. All four added to
both tuples; pinned by
`tests/regression/test_audit_2026_08_12_analysis.py::TestA5SizeErrorBodiesAreWalked`.

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

**Numeric witnesses are picked on the field's decimal grid (2026-08-12 fix,
audit A-A6).** `domains.NumericDomain.pick()` used to take the raw float
midpoint of the interval and check exclusions by float equality -- `PIC 9`
with `ne "4"` picked 4.5 (not excluded as a float), which
`ValueFactory.render()` then ROUNDED back to the excluded "4". Candidates
are now enumerated in integer units of `10**-decimals` (starting from the
grid midpoint, scanning up, wrapping to the low bound), exclusions are
quantized to the same grid before comparison, and `solve()` re-verifies the
RENDERED witness against the numeric domain as a defensive backstop
(`_rendered_numeric_ok`). Still fully deterministic. Pinned by
`tests/regression/test_audit_2026_08_12_analysis.py::TestA6WitnessOnTheDecimalGrid`.

**The whole numeric pipeline is Decimal, never float (2026-08-12 bug
review).** `NumericDomain`'s bounds/exclusions, `_apply_numeric`'s literal
parsing, `_rendered_numeric_ok`, `scenarios._picture_ceiling`, and
`ValueFactory._format_number`/`_fit_domain_value`'s exact-value path all
used float64 internally, so any literal past ~16 significant digits (a
`PIC 9(17)`/`9(18)` account key) was silently rounded in transit:
`eq 123456789012345678` rendered the witness `123456789012345680`, the
fixture row could never take the branch, and `ScenarioCoverage` still
reported the arm as targeted — a silent violation of the "targeted +
merged + missed == total" guarantee (`_rendered_numeric_ok` re-checked in
float too, so the corruption passed its own backstop).
`_picture_ceiling` additionally emitted `'1e+18'` for `PIC 9(18)`.
Everything is `Decimal` end-to-end now, with `localcontext(prec=80)`
around the few multiplications/epsilon-nudges that could outgrow the
default 28-digit context on the widest PICTUREs. Pinned by
`tests/regression/test_bug_review_2026_08_12.py`.

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
* A conditional handler body (`AT END`/`NOT AT END`/`INVALID KEY`/`ON SIZE
  ERROR`/`ON OVERFLOW`/`ON EXCEPTION`/`AT EOP` and their `NOT` variants,
  the `_HANDLER_BODY_ATTRS` tuple) may or may not fire, so every field it
  could write is poisoned exactly like an `IF` arm -- and the poison runs
  AFTER the statement's own fold, so a handler writing the statement's own
  target (`ADD 1 TO X ON SIZE ERROR MOVE 0 TO X`) still leaves X unknown
  (2026-08-12 fix, audit A-A1: before this, `MOVE 'N' TO WS-EOF. READ F AT
  END MOVE 'Y' TO WS-EOF. DISPLAY WS-EOF.` emitted `field_equals
  WS-EOF="N"` even in a scenario where AT END fires). Pinned by
  `tests/regression/test_audit_2026_08_12_analysis.py::TestA1HandlerBodiesPoisonTheFold`.
* `DIVIDE` folds the unambiguous forms (2026-08-12 bug review):
  `DivideStatement.division_mode` now records `BY` vs `INTO` (the two
  invert dividend/divisor order), so `_fold_divide` computes
  `DIVIDE a BY b GIVING c` (c = a/b), `DIVIDE a INTO b GIVING c`
  (c = b/a), and the in-place `DIVIDE a INTO b [c ...]` (each target /= a).
  Still "exact by construction, or absent": a mode-less node (older AST),
  `ROUNDED`, the nonstandard `DIVIDE a BY b` without GIVING,
  divide-by-zero, and any non-exact quotient all poison — exactness is
  verified by multiplying the quotient back at `prec=80`
  (`_exact_divide`), so a context-rounded repeating fraction can never
  masquerade as exact. A `REMAINDER` target is always poisoned (it is
  defined via the quotient as truncated to the GIVING target's PICTURE,
  which this module does not model), and `_write_targets` now includes it
  in the IF-arm/handler-body write scan (previously missed). The GIVING
  value stays safe to fold alongside a poisoned REMAINDER: it is only
  recorded when the true quotient fits exactly, i.e. truncation was a
  no-op. A `/` inside a `COMPUTE` expression tree folds as before
  (divide-by-zero and non-terminating decimals poison, not truncate).
  Pinned by `tests/regression/test_bug_review_2026_08_12.py::TestDivideMode`.
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

**`_ordered_paragraphs` interleaves sections and top-level paragraphs by
source line (2026-08-12 fix, audit A-A4).** It used to append all
section-owned paragraphs first, then top-level ones -- inverting source
order for a program mixing the two, so a `PERFORM ... THRU ...` range
spanning a top-level paragraph and a section-owned one resolved to
`end_idx < start_idx` and came back as an EMPTY body (nothing inside the
range folded or poisoned; stale values survived). Now interleaved by
`location.line`, the same fix `program_flow/scanner.py` and `dead_code.py`
already carry for their own procedure collection (the old docstring claimed
it "mirrored scanner.py's sections-before-top-level traversal" -- wrong on
both counts, scanner.py had already been fixed to interleave). Behavior for
programs without sections is unchanged. Pinned by
`tests/regression/test_audit_2026_08_12_analysis.py::TestA4OrderedParagraphsInterleaveSections`.

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
| `unused_variables.py` | `UnusedVariableAnalyzer` |

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
