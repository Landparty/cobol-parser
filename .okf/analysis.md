---
type: Module
title: Static Analysis
description: 29 static-analysis modules — dead code, unused variables, program flow, IO sequence, move-type, linkage, DCLGEN/host-variable, CRUD, boundary inventory, constraint extraction, constant folding, recursion risk, complexity, redundancy, technical debt, cross-reference, program signatures, whole-codebase call/copy graph, SQL/CICS lint, structural program diff and business rule extraction.
tags: [analysis, business-rules, dead-code, unused-variables, program-flow, io, crud, boundary-inventory, fixtures, constraints, const-fold, recursion-risk, xref, program-signature, codebase-graph, sql-cics-lint, ast-diff]
timestamp: 2026-09-30T00:00:00Z
---

# Overview

`cobolparser/analysis/` — 29 static-analysis modules. All follow the same
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
    RecursionRiskAnalyzer,
    ComplexityAnalyzer,
    RedundancyAnalyzer,
    TechnicalDebtAnalyzer,
    LintAnalyzer,
)
from cobolparser.analysis import IMSSegmentAnalyzer, HostVariableResolver
```

# Analyzer Reference

## Same-named procedures and data items (issue #258)

Two paragraphs may share a name when they sit in different sections
(`X1` in `S1` and `S2`), and two records routinely carry the same field
names (`CUST-ID OF IN-REC` / `CUST-ID OF OUT-REC`). Analyzers must not key
either by bare name.

- **Procedures** — `analysis/_procedures.py`: `ProcedureIndex.build(proc_div)`
  gives every section/paragraph a unique *key*: the bare name when unique,
  `"X1 OF S2"` when the name is shared. `resolve(name, qualifier,
  from_section)` applies the COBOL rule: the `OF`/`IN` qualifier (parser
  metadata `target_qualifier` / `thru_qualifier` on PERFORM and GO TO),
  else the paragraph of that name in the referencing statement's own
  section (`enclosing_section(stmt)` walks `.parent`), else the unique
  name; an ambiguous reference resolves to *every* candidate (keeps code
  alive, never hides it). Used by `program_flow` (scanner + `EdgeCollector`),
  `DeadCodeAnalyzer` and `ComplexityAnalyzer`.
- **Flow output contract** — `FlowNode.name` stays the bare name;
  `FlowNode.qualified_name` is set (and emitted by `to_dict`) only for a
  shared name; `FlowNode.key` is the one every edge `source`/`target`,
  `thru_target`, `range_members`, entry/exit point, cycle,
  `unreachable_nodes` entry and branch `parent_proc` uses. Consumers that
  join edges to nodes must join on `qualified_name ?? name`. Same
  `qualified_name` field on `DeadCodeItem` and `ProcedureComplexity`.
- **Data items** — `_extract_identifiers` (unused_variables.py) returns
  references with their qualifiers, spelled `"AMT OF IN-REC"` (`IN` is
  normalized to `OF`), plus each qualifier as its own reference
  (`_names.qualified_references`; `_names.bare_names` recovers plain
  tokens). `_NameMatcher` resolves them: qualifiers must name enclosing
  items in ascending order (levels may be skipped); an unqualified
  reference to a shared name, or qualifiers matching no candidate (a
  file-name qualifier), count for every candidate. REDEFINES resolves to
  the same-named *sibling* first. `UnusedVariableItem.qualified_name`
  (`"AMT OF OUT-REC"`, full enclosing chain) is set for shared names.
  `XrefAnalyzer` gives each same-named item in a *different* record its
  own `XrefEntry` with `qualified_name` (`entry_for` accepts it); the same
  chain declared twice (a copybook COPYed into two sections) is still a
  `duplicate_declarations` entry. `ProgramSignatureExtractor` keys field
  directions by `qualified_name` where xref set one. Procedure xref
  entries are still name-keyed.

## DeadCodeAnalyzer

> 2026-09-27: a referenced section no longer marks *every* paragraph in it
> live. `_propagate_section_references` walks the section's paragraphs in
> order and stops after one that `_terminates` (STOP RUN, GOBACK, EXIT
> PROGRAM, unconditional GO TO); a later paragraph is live only if it is a
> fall-through source of its own (GO TO/ALTER/ENTRY target). A paragraph
> after `STOP RUN`, or one jumped over by `GO TO`, in a PERFORMed or
> fallen-into section is now reported dead.

> 2026-09-28: references are collected from the unit's **own** statements
> only. `get_all_statements()` also returns every contained program's, and
> procedure names are local to a program unit, so a nested program's
> `PERFORM HELPER` kept the container's same-named, never-referenced
> `HELPER` alive. `ProcedureScanner.collect_entry_points` had the same leak
> (a nested `ENTRY` made the container's same-named paragraph an entry
> point). Pinned by `TestContainedProgramScope` in `test_dead_code.py`.

> 2026-10-14 (issue #312): the SECTION form of the `GO TO nnnn-EXIT` idiom.
> The last paragraph of every section a PERFORM / SORT / MERGE / XML PARSE
> runs (`_section_exits`) is treated like a THRU range end: a GO TO onto it
> is a reference, not a fall-through source, so it no longer keeps every
> later section alive. Exception: when the section is itself a fall-through
> source (fallen into, or a GO TO target), `_collect_fallthrough_refs`
> restores the exit as a fall-through source, since on that path it runs
> on. The same holds when the section is entered by a jump from *outside*
> it (`_sections_entered_by_jump`: a GO TO written in another section, an
> ALTER, a CICS HANDLE, an ENTRY). Pinned by `TestSectionExitGoTo`.

> 2026-10-14 (issue #384): dead code is followed **transitively** -- "dead"
> now means unreachable, not merely unreferenced. `analyze` runs a worklist
> from the roots (entry point, declaratives, the leading body, ENTRY
> paragraphs, CICS HANDLE labels): a procedure's statements are admitted
> to `_collect_references` only once the procedure itself is reached, so a
> paragraph PERFORMed only from a dead paragraph is reported dead too
> (retired report code, NIST IC222A/IC227A). THRU range ends and section
> exits are still collected from *every* statement up front, which keeps
> each round monotone (admitting statements only adds references). Lint's
> message is now "can never be reached". Pinned by `TestTransitiveDeadCode`.

```python
report: DeadCodeReport = DeadCodeAnalyzer().analyze(ast)
# report.dead_items: list[DeadCodeItem]
```

Detects unreachable paragraphs and sections (paragraphs/sections never the
target of a PERFORM, GO TO, or fall-through control flow *from reachable
code*). The first
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
halts pending operator action; `GOBACK`; `EXIT PROGRAM`; `EXEC CICS
RETURN` / `XCTL` / `ABEND`, see `_cics.py` below) or an
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

**...and then over-corrected: fall-through escaped a PERFORM target too
(2026-09-05 fix, repo audit).** The gate above was membership in
`_referenced_names`, which also holds PERFORM, `PERFORM ... THRU`, and
SORT/MERGE INPUT/OUTPUT procedure targets. A PERFORM *returns to its
caller* at the end of its range — it does not run on into the next
paragraph — so crediting one with fall-through invents a runtime edge that
cannot happen, and it fires on the single most common COBOL program shape:
a `MAIN` paragraph of `PERFORM`s followed by the paragraphs it performs.
Every unreferenced paragraph after the first performed one was kept alive
by that phantom edge, so the analyzer reported **no dead code at all** for
the shape it is most often pointed at (`0000-MAIN` performing
`1000-INIT`/`2000-PROCESS`/`3000-TERM`, with `9999-NEVER-CALLED` after
them, came back clean). Every pre-existing test missed it because each one
puts a `STOP RUN` in the paragraph before the orphan specifically so
fall-through would not mask it — the workaround, not the fix.

Fixed by splitting the two notions apart. `_fallthrough_sources` is a new,
strictly smaller set than `_referenced_names`: procedures control can
arrive at *and keep running from*. It is seeded with the entry point and
extended by `_add_jump_ref` (a new sibling of `_add_ref`) from GO TO
targets, `ALTER ... TO PROCEED TO` targets, and ENTRY paragraphs — all
transfers that land in a procedure and carry on — and then by
`_collect_fallthrough_refs` itself as it propagates left to right, so a
paragraph reached by falling in is itself a fall-through source. PERFORM
and SORT/MERGE procedure targets are deliberately absent: they stay in
`_referenced_names` (so they are never reported dead) without licensing an
edge out of their own end. `_mark_thru_range` still marks a whole
`PERFORM A THRU C` range referenced, and C still does not escape. Pinned by
`tests/unit/analysis/test_dead_code.py::TestFallThroughOnlyEscapesReachableRuns`.

**Known related over-approximation, deliberately not changed.**
`ProgramFlowAnalyzer`'s `graph.build_fall_through_edges` still emits a
`FALL_THROUGH` edge between *any* two adjacent non-terminating procedures,
PERFORM targets included, so `flow_report.unreachable_nodes` under-reports
in the same way. That is a CFG-shape question with a much wider blast
radius (flowcharts, `ScenarioPlanner` arm reachability,
`TechnicalDebtAnalyzer`'s unreachable-node smell) and was left alone; the
two modules therefore no longer agree on reachability by design, not by
accident.

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
`ExecSQLStatement.host_variables`/`.null_indicators` (SQL statements don't
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
it strips quoted substrings, regex-extracts every letter-led token
(`_names.IDENTIFIER_TOKEN_RE`, shared with `redundancy.py`'s clone-detection
renaming and `boundary_inventory.py`'s `EVALUATE TRUE` selector-text read
scan -- the latter uses the sibling `RELAXED_IDENTIFIER_TOKEN_RE`, which
also accepts a token starting with a digit, harmless there since a match is
only ever looked up against a name map), and filters `_NON_IDENTIFIER_WORDS` (figurative constants merged with
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
decompose structurally (`EVALUATE TRUE` Condition-type selectors, and
SEARCH WHEN conditions that carry no `condition_tree`, per `constraints.py`'s same documented gap — see
`ConstraintExtractor`'s section above). The fallback is deliberately
over-inclusive: a false positive there only makes the analyzer *miss* an
unused variable, never wrongly flag a used one.

**EVALUATE subjects AND `Literal`-typed WHEN selectors (found during a
review of this module, 2026-08-16; root-caused and widened by the
2026-08-17 review follow-up).** The original 2026-08-16 fix walked
`stmt.subjects` explicitly because `evaluate_parser.py`'s
`_parse_subjects` appended straight to `EvaluateStatement.subjects`,
bypassing `add_subject()`, leaving `stmt.operands == []`. The 2026-08-17
follow-up moved that fix to its root: the parser now routes each subject
through `add_subject()`, so string subjects reach `.operands` and every
generic `.operands` consumer (`find_statements_using_variable`,
intrinsic-function detection, `LanguageEnvironmentAnalyzer`,
`BoundaryInventoryAnalyzer`'s caller-dataflow rung) sees them — see
[parser.md](parser.md). This module's explicit subjects walk is KEPT: an
earlier revision of this passage claimed `add_subject()` "exists
specifically to also call `add_operand()`", which is wrong for half its
branches — a `CobolExpression` subject goes to `add_child()`, never
`add_operand()` (models/statements/control.py), so the explicit walk (now
via the shared `_names_from_value` dispatch helper, also used for
`FunctionCall` arguments and `ConditionalExpression`/
`ArithmeticExpression` operands) is the ONLY coverage for
expression-shaped subjects; the string double-count is a harmless set
union. The same follow-up fixed the sibling false positive the original
pass missed: `_build_selector` classifies a bare data-name (or level-88
condition-name) WHEN selector as `{"type": "Literal"}` — it never emits
`"Identifier"`, a fact constraints.py's EVALUATE handling also relies on —
so `_selector_identifiers` now scans `Literal` values too; previously a
variable referenced only as a WHEN selector was falsely reported unused.
Caveat (documented in `_selector_identifiers`'s TODO): selector values
arrive with string-literal quotes already stripped (the unquoted shape is
pinned — see parser.md's blank-literal passage and the reverted `17fa400`
attempt), so literal contents that coincidentally match a declared name
mark it used — the accepted over-inclusive direction.
`_walk_expression_operands`'s opaque-shape fallback also now scans every
`expr.operands` entry, not just `operands[0]`. All pinned by
`TestEvaluateSubjects` in `tests/unit/analysis/test_unused_variables.py`
(each parsed-source test carries a deliberately-unused positive-control
item so the negative assertions can never pass vacuously).

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

**The four documented limitations are now tagged inline as `TODO`s
(2026-08-16 review).** Each spot in the module backing a limitation
already called out in the class docstring carries a `TODO(known
limitation)` comment: `_DATA_SECTION_NAMES` (SCREEN/REPORT/COMMUNICATION
SECTION out of scope), the `SearchStatement` branch and
`_selector_identifiers`'s `"Condition"` case (SEARCH WHEN / EVALUATE TRUE
regex-only fallback), and the `redefines_edges` comment in `analyze()`
(REDEFINES/OCCURS-DEPENDING-ON/RENAMES resolved by name, not structural
identity; since issue #258 REDEFINES prefers the same-named sibling). No behavior change — purely so a `TODO`/`grep` sweep of the
codebase surfaces these instead of only living in prose here and in the
docstring.

**EXEC CICS/DLI arguments fixed, not just documented (2026-08-19 coverage
audit).** The former `TODO` here was wrong about *why* EXEC CICS/DLI args
were unscanned: it isn't that the sweep was unimplemented, it's that
`ExecCicsStatement`/`ExecImsStatement` extend `ASTNode` directly rather
than `CobolStatement` (unlike `ExecSQLStatement`, which does extend
`CobolStatement`), so neither ever appears in `ast.get_all_statements()` —
the per-statement loop in `_collect_referenced_names` that holds the
`host_variables`/`null_indicators` sweep for EXEC SQL never sees them at
all, regardless of what fields it reads. Fixed with a separate sweep after
that loop, using `ast.find_all_by_type("ExecCicsStatement")` /
`ast.find_all_by_type("ExecImsStatement")` directly (these two classes
aren't imported into `unused_variables.py` — an analysis -> parsers
layering dependency for no real type-safety benefit, since `.options`/
`.arguments` are untyped raw text either way) over `ExecCicsStatement.
options` (option keyword -> parenthesized argument text) and
`ExecImsStatement.arguments` (positional list). A field referenced only
inside one of these statements is no longer falsely reported unused. See
`TestExecCicsAndImsArguments` in `test_unused_variables.py`.

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

**Clause fidelity fix (#274, 2026-10-05):** `SET x UP BY v` / `DOWN BY v`
rendered as `SET x TO v` (`set_type` was ignored; `TO FALSE` is now
rendered too); ADD/SUBTRACT took their sources as `operands` minus
`targets`, so a GIVING item read as a source (`ADD A TO B GIVING C` ->
`ADD A, C TO B`) -- sources now come from `source_operands` and
` GIVING ...` is appended (also for `ADD A B GIVING C`, which has no TO
target). PERFORM renders ` VARYING v FROM x BY y` / ` n TIMES` (the UNTIL
guard stays the diff renderer's job, `ast_diff._statement_text`) and
COMPUTE renders `ROUNDED`, so `cobol-parser diff` no longer shows
identical old/new text for those edits.

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

## RecursionRiskAnalyzer (`recursion_risk.py`, 2026-08-16)

```python
report: RecursionRiskReport = RecursionRiskAnalyzer().analyze(ast)
# report.risks: list[RecursionRisk]
# RecursionRisk.mechanism: "PERFORM" | "GOTO" | "MIXED" | "CALL"
# RecursionRisk.severity: "HIGH" | "MEDIUM"
```

Finds recursion-driven infinite-loop risks. Two mechanisms, both surfaced as
`RecursionRisk` entries with a `severity` and a plain-English `explanation`:

- **PERFORM/GO TO cycles** — reuses `ProgramFlowAnalyzer`'s `cycle_details`
  (an optional precomputed `ProgramFlowReport` can be passed via
  `analyze(ast, flow_report=...)` to avoid a second pass). A
  `PERFORM_RECURSION` cycle (out-of-line paragraphs performing each other in
  a loop — invalid re-entrant PERFORM in standard COBOL) is always `HIGH`,
  independent of any UNTIL/TIMES/VARYING clause on the individual PERFORMs.
  A `GOTO_LOOP`/`MIXED` cycle is graded by `_has_escape` over the cycle's
  **strongly connected component** (`_components`, Tarjan over
  `_ESCAPE_EDGE_TYPES`), not the cycle alone: `HIGH` if no paragraph in the
  component has an edge leaving it or a program-terminating statement
  (`has_stop_run`/`has_goback`/`has_exit_program`/`has_cics_exit` on the
  `FlowNode`),
  `MEDIUM` otherwise. Per-cycle checking (before #393) let two cycles that
  share a paragraph each "escape" into the other, so an inescapable
  `P1 -> P2 -> P1` / `P1 -> P3 -> P1` pair read MEDIUM. `has_return` is a
  SORT/MERGE `RETURN sd-file`, **not** a terminator (it was, before #393,
  so every SORT output-procedure loop read MEDIUM) —
  fall-through-only cycles are never reported (fall-through can't actually
  form a cycle).
  A `MIXED` cycle that is a PERFORM of a multi-procedure range (a SECTION
  with its paragraphs, or a THRU span) made from *inside* that range, every
  other hop a fall-through between its members, is reported as
  `mechanism="PERFORM"`, `HIGH` (`_reenters_own_perform_range`, #350): the
  range-level twin of `P. PERFORM P.`. `_closed_by_perform_range_end` (which
  drops the priming-read false positive) ends a SECTION's range at its last
  paragraph (`_perform_range`), not at the header node -- before #350 the
  header's fall-through into its first paragraph read as "leaving the range"
  and `S. S1. PERFORM S.` was reported clean.
- **Self-recursive CALL** — a CALL (static, or dynamic and resolved via
  `DynamicCallAnalyzer`, which this analyzer runs internally) whose target
  equals the program's own `PROGRAM-ID`. `HIGH`, or `LOW` when the
  `PROGRAM-ID` is declared `IS RECURSIVE` (re-entry legal; base case
  unverifiable). Only the unit's *own* statements are walked
  (`_own_statements`: `get_all_statements()` minus every node of
  `contained_programs`) — before issue #274 a contained program's
  `CALL 'OUTER'` was reported as the outer unit calling itself.
- **CALL to an enclosing program** (#274) — a contained program CALLing a
  program it is nested in (any `CobolProgram` up its `.parent` chain). The
  container is necessarily active while the contained program runs, so this
  is indirect recursion: `HIGH`, or `LOW` when that container is `IS
  RECURSIVE`. Reported on the *inner* unit, `program` = the container's name.

Exported from both `cobolparser.analysis` and the top-level `cobolparser`
package, same as `DeadCodeAnalyzer`/`ProgramFlowAnalyzer`. CLI:
`cobol-parser recursion-check <file.cbl>` (see cli.md).

## ComplexityAnalyzer (`complexity.py`, 2026-08-16)

```python
report: ComplexityReport = ComplexityAnalyzer().analyze(ast, flow_report=None)
# report.procedures: list[ProcedureComplexity]
# report.total_complexity / .max_complexity / .mean_complexity / .goto_density (properties)
```

Per-paragraph/section McCabe-style cyclomatic complexity, computed by
walking each paragraph's own statement tree -- not the inter-paragraph CFG
`ProgramFlowAnalyzer` builds, since most COBOL complexity lives *inside* a
paragraph (IF/EVALUATE/SEARCH/loop-PERFORM, exception-handling clauses),
not in how paragraphs call each other. An optional precomputed
`ProgramFlowReport` can be passed via `flow_report=` (same convention as
`RecursionRiskAnalyzer`) to avoid a second pass; `TechnicalDebtAnalyzer`
below always does this.

**Two numbers per procedure**: `cyclomatic_complexity` (1 plus one decision
point per IF, per WHEN arm on EVALUATE/SEARCH excluding WHEN OTHER/default,
per loop-form PERFORM -- TIMES/UNTIL/VARYING, a bare `PERFORM target` is not
a decision point since it always runs exactly once -- per target of a
computed `GO TO ... DEPENDING ON` (an N-way branch plus the out-of-range
fall-through, scored like an N-arm EVALUATE; a plain GO TO adds nothing and
neither changes nesting depth) -- and per *present*
exception-handling clause: AT END, INVALID KEY, AT EOP, ON SIZE ERROR, ON
OVERFLOW, ON EXCEPTION, and their NOT- counterparts, each independently);
`extended_complexity` adds one per boolean AND/OR operator in every
condition tree on top of that (`IF A AND B OR C` has more distinct paths
than a bare `IF A`, even though both are "one IF" for classic McCabe). Also
reports `max_nesting_depth` (only IF/EVALUATE/SEARCH/loop-PERFORM increase
it -- an exception clause's own body does not, a deliberate choice: nesting
depth here tracks control-flow block nesting, not exception-handling
depth), `fan_in`/`fan_out` (distinct PERFORM/GO TO neighbors, from
`flow_report.edges` filtered to `PERFORM_EDGE_TYPES | GOTO_EDGE_TYPES` --
excludes the synthetic IF/EVALUATE branch-node edges and CALL's
external-program targets, neither of which belong in an in-program fan
count), and a LOW/MODERATE/HIGH `rating` from `ComplexityThresholds`
(defaults `moderate=10`/`high=20`, overridable per analysis run).

**Walk mechanics.** The clause-list attribute check
(`at_end_clause`/`invalid_key_clause`/.../`on_exception`/`on_overflow`) is a
local re-derivation of the same set `program_flow/scanner.py`'s
`_CLAUSE_BODY_ATTRS` and `constraints.py`'s `_NESTED_STATEMENT_ATTRS`
establish -- most of these are already reachable via the generic
`.children` walk (every AST statement model wires its clause-list setters
through `_set_clause`/explicit `add_child` calls), *except*
`CallStatement.on_overflow`/`.on_exception`/`.not_on_exception`, which are
never `add_child`ed (confirmed by auditing `models/statements/call.py`) --
the one gap `scanner.py`'s own special-cased `push_sequential` dispatch for
CALL exists to cover. Explicitly walking the full clause-attribute list on
every visited statement (not just the CALL-specific gap) is cheap and
matches established precedent; the `id()`-based visited-set prevents double
counting on statement types where the attribute *is* already wired to
`.children`.

**A bare SECTION reports the trivial complexity of 1** -- a bare `SECTION`
header holds no statements of its own (same observation `dead_code.py` and
`program_flow/scanner.py` make), so there is nothing to walk.

**Same-named paragraphs are measured separately (issue #258):** the
2026-08-16 audit fix summed same-named paragraphs into one row because the
flow node was name-keyed. Flow nodes are now keyed by `ProcedureIndex`
(`"DO-WORK OF SEC-TWO"`), so `_collect_paragraph_map` maps each key to its
own body and each row carries `qualified_name`. Pinned by
`tests/regression/test_audit_2026_08_16_analyzers.py::TestA8SameNamedParagraphs`.

CLI: `cobol-parser complexity <file.cbl>` (see cli.md).

## RedundancyAnalyzer (`redundancy.py`, 2026-08-16)

```python
report: RedundancyReport = RedundancyAnalyzer().analyze(ast, min_clone_statements=3)
# report.dead_items / .unused_items: delegated straight from DeadCodeAnalyzer / UnusedVariableAnalyzer
# report.dead_ratio / .unused_ratio (properties)
# report.clone_groups: list[CloneGroup]
```

Two kinds of "redundant weight, not real work": unreferenced code/data
(delegates directly to `DeadCodeAnalyzer` and `UnusedVariableAnalyzer`,
reporting their items plus ratios) and duplicate (cloned) paragraphs, new in
this module.

**Whole-paragraph structural clones only** -- no sub-paragraph sliding
window, no near-miss/type-3 similarity scoring, matching the design goal of
"exact, no similarity-threshold tuning, no false-positive debate." Two
kinds:

- **Type-1 (exact)**: identical statement types, operands, and condition
  text, verbatim -- and everything else each statement does (#262, below).
- **Type-2 (renamed)**: identical statement-type/control-flow shape with
  identifier-shaped tokens (data-names, paragraph-names) consistently
  substituted with per-paragraph positional placeholders (`ID1`, `ID2`,
  ...) -- `MOVE WS-A TO WS-B` and `MOVE WS-X TO WS-Y` match. A changed
  *literal* never matches (even for Type-2): a literal is behavior, not a
  name, so quoted substrings are protected from substitution before the
  identifier regex runs.

`_Fingerprinter` builds a hashable nested-tuple fingerprint per paragraph
(not a flat token stream -- a flat sequence could conflate two differently-
nested trees that happen to serialize the same way; the nested-tuple shape
encodes tree structure unambiguously). Paragraphs are grouped by exact
fingerprint equality; Type-1 grouping runs first, and any paragraph already
in a Type-1 group of size >= 2 is excluded from the Type-2 pass, so a
paragraph is only ever reported in one clone group. Groups below
`min_clone_statements` (default 3 -- two bare `EXIT.` paragraphs matching
each other isn't meaningful redundancy) are dropped.

**A leaf statement's fingerprint is its whole behaviour, not its operand
list (#262, 2026-10-04).** It used to be `(type, operands)` only, and
`operands` is often just the identifier list (COMPUTE's is `['A']`; the
formula lives in `expression`), so paragraphs differing only in a COMPUTE
formula, ROUNDED, an AT END / INVALID KEY / ON SIZE ERROR / ON EXCEPTION
body, `UPON`, `CORRESPONDING`, a STRING delimiter or the INSPECT phrase were
reported as TYPE_1 clones. A leaf is now `(type, operands, clauses,
details)`: `clauses` fingerprints every present clause body (the
`_CLAUSE_ATTRS` set `complexity.py` uses, recursively through `_fp`, so their
statements also count towards `statement_count`), and `details` is the
statement's `to_dict()` minus `_DETAIL_SKIP_KEYS` (position, node
bookkeeping, what the tuple already holds, and `possible_values` -- a
`DynamicCallAnalyzer` annotation that would make a digest depend on analyzer
order). SEARCH adds its details (table, VARYING) and an inline PERFORM its
TIMES count / VARYING / TEST phrase the same way. Under Type-2, detail
strings are renamed like operands **except reserved words** (`_DETAIL_KEYWORDS`:
`_NON_IDENTIFIER_WORDS` + the lexer's keyword table + enum-like values the
models store, e.g. `LEADING`, `SIZE`, `TIMES`, `INPUT`), so `FOR ALL` vs
`FOR LEADING` is never a "consistent rename"; a dict keyed by data-names
(OPEN's file -> mode map) has its keys renamed too. **No digest version**:
by owner decision the `type1`/`type2` digests changed in place, and digests
stored by earlier scans simply stop matching new ones. Known residual: the
parser stores some literals unquoted (an INSPECT `'X'`, a STRING
`DELIMITED BY 'X'`), so under Type-2 only, two such literals still read as a
consistent rename; Type-1 tells them apart.

**Reuses `unused_variables.py`'s `_NON_IDENTIFIER_WORDS`/quoted-text
handling verbatim** rather than re-deriving a second reserved-word list --
unlike the walking-discipline tuples other analysis modules duplicate
(those differ per module's own traversal needs), "is this token a real
data-name" is a single well-defined question both modules ask, and a second
list would just drift out of sync with the first for no benefit.

### Paragraph fingerprints (cross-file clones, 2026-09-13)

`report.paragraph_fingerprints: list[ParagraphFingerprint]` -- per paragraph:
`name`, `location`, `statement_count`, and both digests (`type1`, `type2`) as
16-hex-character blake2b over a canonical serialization of the same
`_Fingerprinter` tuple the grouping uses.

The reason it exists: `clone_groups` can only answer "which paragraphs in
*this* program duplicate each other". The commoner shape of COBOL
copy-paste is a paragraph cloned into a *different* program, where neither
copy is duplicated inside its own file and no clone group is reported at
all. Answering that needs the fingerprints, not the groups derived from
them, so the digests are reported and the grouping across programs is left
to whoever holds more than one report (`scan.cross_file_clone_groups`).

Computed by `_paragraph_fingerprints`, a pass of its own rather than a
restructuring of `_find_clone_groups` -- that would save one fingerprinting
sweep but rewrite the Type-1/Type-2 precedence logic this module's tests pin
precisely, and fingerprinting is immaterial next to the parse that produced
the AST. Both build through the same `_Fingerprinter` over the same
`_collect_paragraphs` order, so they cannot disagree (pinned by
`test_digests_agree_with_the_within_program_grouping`).

`_canonical` is written out rather than leaning on `repr()`: the digest
travels between processes and between programs, so identical structure must
serialize byte-identically on any interpreter forever, and `repr()` is a
debugging representation with no such guarantee. Strings are
length-prefixed so content cannot forge structure -- without it `("A,B",)`
and `("A", "B")` would collide.

`min_clone_statements` filters the emitted fingerprints as well as the
groups: a paragraph too small to be meaningful redundancy inside one program
is no more meaningful across two, and emitting every three-line paragraph in
a 5,000-file shop would dominate a scan's output.

CLI: `cobol-parser redundancy <file.cbl> [--min-clone-statements N]` for the
full report (the only surface that exposes the fingerprints), and embedded in
`cobol-parser health <file.cbl>`'s `redundancy_summary` as before. Across
files: `cobol-parser scan --clones` (see cli.md and batch.md).

## TechnicalDebtAnalyzer (`technical_debt.py`, 2026-08-16)

```python
report: TechnicalDebtReport = TechnicalDebtAnalyzer(weights=None, size_threshold=50).analyze(ast)
# report.score: float (0-100, higher = more debt); report.grade: "A".."F", or None (see below)
# report.parse_error_count / report.caveats  -- set from analyze(..., parse_error_count=N)
# report.components: list[ComponentBreakdown]  -- one per weighted component, each with its own findings
# report.top_offenders: list[OffenderProcedure]  -- worst procedures, with reasons
```

Composite, explainable debt score combining `ComplexityAnalyzer`,
`RedundancyAnalyzer`, and control-flow smells from `ProgramFlowAnalyzer`/
`RecursionRiskAnalyzer` (all four sub-reports can be passed in precomputed
via keyword args to skip redundant passes). Every point on the score traces
to a named finding in some component's `findings` list -- never a bare,
unexplained number.

**Four weighted components** (`DebtWeights`, defaults sum to 100 but any
positive weights work -- the composite normalizes by the weights' actual
sum): `complexity` (share of procedures rated MODERATE/HIGH, weighted units
`moderate*1 + high*3` over `3*total`), `redundancy` (mean of
`dead_ratio`/`unused_ratio`/cloned-statement ratio), `control_flow` (capped
penalties: GO TO density, `ALTER` usage via `find_all_by_type` on the
unit's own PROCEDURE division -- `ASTNode.find_all_by_type` is a *deep*,
cached subtree search via `traverse_depth_first()`, so called on the
program node it also counted every contained program's ALTERs, charging
them to the container as well (fixed 2026-09-28; a contained program hangs
off the `CobolProgram` node, never off its divisions) -- HIGH-severity `RecursionRiskAnalyzer` risks, unreachable-node
ratio), `size` (share of procedures over `size_threshold`, default 50
statements). Final score is the weighted average of the four 0-100
component scores, clamped to `[0, 100]` and **rounded to the 2 decimals
`to_dict()` serializes before grading** (2026-08-16 audit fix — grading
the raw float let accumulated noise like 10.000000000000002 push a score
the JSON prints as 10.0 across the A/B band edge); grade bands are A <=
10, B <= 25, C <= 45, D <= 70, else F. The complexity/size components
carry a `"no procedures to rate"` finding (rather than an empty findings
list) on a program with no procedures, per the every-point-explained
contract. Pinned by
`tests/regression/test_audit_2026_08_16_analyzers.py::TestA7GradeMatchesSerializedScore`.

**Parse errors withhold the grade (#397, 2026-10-14).** A file that mostly
failed to parse hands over a near-empty AST, which scores 0.0 and used to
grade "A". `analyze(ast, parse_error_count=len(result.errors))` keeps the
score (computed over what was recovered) but sets `grade` to `None` and adds
a `caveats` entry; `to_dict()` always carries `parse_error_count` and
`caveats`. The `health` subcommand passes the count; `scan` does not (it
already flags `parse_error_count` per file, and its grade feeds the
extension's portfolio sort). Pinned by `test_technical_debt.py::
TestParseErrorsWithholdTheGrade` and `test_complexity_health_subcommands.py::
TestHealthWithParseErrors`.

**`top_offenders`** ranks procedures by a severity score built from the
same underlying findings (HIGH complexity +30, MODERATE +10, each GO TO +3,
dead code +20, clone-group membership +15, unreachable +20, no-escape
recursion-cycle membership +25), truncated to `top_n` (default 5). A
paragraph whose only "offense" is a GOTO-to-itself is *not* reported as
dead code -- `DeadCodeAnalyzer` counts a self-referencing GO TO as an
incoming edge (it has no self-reference special case), so such a paragraph
surfaces via its `unreachable`/`no-escape recursion cycle` reasons instead;
confirmed empirically, not assumed, while writing this module's own tests.

CLI: `cobol-parser health <file.cbl>` (see cli.md).

## LintAnalyzer (`lint.py`, 2026-09-07)

```python
report: LintReport = LintAnalyzer().analyze(ast, flow_report=None, copybook_item_names=None)
# LintAnalyzer(rules=None) -- default every rule in RULES; an unknown id raises ValueError
# report.findings: list[LintFinding]  (rule/severity/message/location/symbol/kind)
# report.rules_run / .failed_rules / .caveats
# report.error_count / .warning_count / .info_count / .counts_by_rule() / .worst_severity()
```

The aggregate view for the two callers who want "what is wrong with this
program" rather than one analyzer's answer: a CI gate and an editor. Runs the
selected rules over **one** already-parsed AST and flattens their differently
shaped reports into a single stream of `LintFinding`, ordered by source
position. Re-implements no analysis — each rule is a thin mapping from an
existing analyzer's report, so a fix in (say) `move_type_checker.py` reaches
lint output with no change here.

**Rule ids are the analyzer subcommand names** (`dead-code`,
`unused-variables`, `move-type-check`, `io-sequence`, `linkage-check`,
`recursion-check`, `complexity`, `dclgen-check`) rather than a second private
vocabulary, so
`lint --rule dead-code` and `cobol-parser dead-code` are visibly the same
analyzer. One more id appears in output but not in `RULES`: `parse`, the
error-severity findings `add_parse_errors()` makes from `ParseResult.errors`
(the `lint` CLI adds them; see cli.md, #249). The `sql-cics-check` caveat on a
unit with no PROCEDURE DIVISION says exactly that, instead of counting the
unit's one reason as an "EXEC block" that could not be checked. A rule selection is deduplicated and normalized to `RULES` order, so
flag ordering cannot change the report.

**Severity is per finding, not per rule.** An analyzer that grades itself
keeps its grading: MOVE's ERROR/WARNING kinds map to error/warning,
recursion's HIGH/MEDIUM (HIGH = a cycle with no escape route, i.e. an infinite
loop) to error/warning, complexity's rating to warning (HIGH) / info
(MODERATE), with LOW producing no finding at all. The rest carry a fixed
severity: dead code and I/O `FILE_LEFT_OPEN` warn; every other I/O kind and
every LINKAGE kind but `UNREFERENCED_LINKAGE` are errors. An unused item is a
warning when the program declares it and only info when it came from a
copybook (`copybook_item_names`) — a copybook describes a whole record and no
one program uses every field of it. The `_SEVERITY_*` tables in the module are
the whole of that policy.

**`LintFinding.symbol`** is the *name* the finding is about (paragraph, data
item, file, called program), not a source excerpt. It is what lets a consumer
whose line numbers have shifted — an editor holding the unexpanded file while
the analyzers ran over copybook-expanded text — re-anchor by searching for the
declaration instead of trusting `location` blindly. `kind` preserves the
underlying analyzer's own category (`READ_BEFORE_OPEN`, `WORKING-STORAGE`,
`HIGH`, ...) so a consumer can filter more finely than by rule without parsing
`message`.

**A quiet report is not automatically a clean program**, and the report says
so structurally rather than in prose: `caveats` carries what an analyzer could
not check (MOVE operands whose data category never resolved, most often an
unresolved COPY), and `failed_rules` records a rule that raised — it costs
only its own findings, never the other six. A consumer gating on `findings`
alone must still surface both lists.

Two rules (`recursion-check`, `complexity`) need the CFG; `LintAnalyzer`
builds it at most once per `analyze()` call and accepts a precomputed
`flow_report`. Findings identical in every visible field collapse to one
(`_deduplicate`) — identical findings from one analyzer are two facts about
the graph but one thing to fix, and two identical squiggles in an editor.
(`IOSequenceAnalyzer` itself now reports a violation once per source location
since #371, so it no longer produces these.)

CLI: `cobol-parser lint <file.cbl>` (see cli.md), including `--format text`,
`--min-severity`, and `--fail-on` (exit 3).

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

**Execution-order walk, not source-order (2026-08-16 audit fix).** The
analyzer used to walk the raw AST in declaration order, so the canonical
correct COBOL shape — OPEN/READ in a main paragraph that PERFORMs a
wrap-up paragraph declared *after* it — produced CLOSE_NOT_OPEN +
FILE_LEFT_OPEN (and, for an OPEN living in a PERFORMed init paragraph,
READ_BEFORE_OPEN) false positives. `analyze()` now linearizes the
PROCEDURE DIVISION (sections and top-level paragraphs interleaved by
source line, same observation `dead_code.py` makes) and runs an
execution-order chain from the entry procedure: fall-through, a
paragraph's own top-level unconditional GO TO followed, out-of-line
`PERFORM target [THRU end]` inlined at the call site (section names
resolve to their full paragraph range; a re-entrant PERFORM is skipped
via a range stack; per-chain visited sets keep GO TO cycles finite).
Top-level STOP RUN / GOBACK / EXIT PROGRAM ends the walk. Conditional
branches still share one state (unchanged conservatism); paragraphs
unreachable from the entry procedure are no longer walked at all.

**PERFORM ranges are summarized, not re-inlined (2026-10-14, #371).** Each
PERFORM used to re-walk its target paragraphs through Python recursion, so a
PERFORM chain ~248 deep raised `RecursionError` (and `lint` reported the rule
as failed), and a paragraph PERFORMed twice per nesting level cost 2**depth
walks. The walk is now generators (`_run_paragraph`, `_process_statement`,
`_run_perform`, `_walk_range`) that `yield` the sub-step they would have
called; `_drive` runs them off an explicit stack. The first run of a range
from a given entry state (open files, closed files) is stored as a
`_RangeSummary` (exit state, violations, queued conditional GO TO targets,
whether it terminated) and replayed at later call sites with the same state.
A summary is only reused when the re-entrancy guard would decide the same
way: none of the ranges it `entered` is on the PERFORM stack, and every
enclosing range it skipped (`guarded`) still is. Violations are emitted once
per (kind, file, location, message) -- the walk used to repeat them once per
call path. Output was checked identical (after that dedup) to the old walk
on every sample/NIST program and 3,000 random programs. Pinned by
`tests/unit/analysis/test_io_sequence_perform_summaries.py`.

**`CLOSE f REEL` / `CLOSE f UNIT` keep the file open (2026-09-28).** They
close only the current volume (`close_options[f]["reel"/"unit"]`); treating
them as a file close reported READ_BEFORE_OPEN / DOUBLE_CLOSE on the legal
READ or plain CLOSE that follows.

**Conditional GO TO targets are walked once the chain loops (2026-09-27).**
`READ IN-F AT END GO TO END-P` / `GO TO LOOP-P` -- the textbook sequential
loop -- stopped the walk at the revisit of LOOP-P, so END-P's CLOSE was never
seen and FILE_LEFT_OPEN was reported. GO TO targets met inside a branch or
handler are now queued (`_pending_gotos`) and the chain resumes at the next
unvisited one when it loops back. If it still ends on a loop without reaching
STOP RUN/GOBACK, no FILE_LEFT_OPEN is claimed (`_ended_in_cycle`): the walk
never reached program end. A missing or duplicate CLOSE in the exit
paragraph is still reported. Pinned by
`tests/unit/analysis/test_io_sequence.py::TestGoToReadLoop`.
Contained programs are no longer walked either (single-program scope,
matching every other analyzer). Pinned by
`tests/regression/test_audit_2026_08_16_analyzers.py::TestA1IoSequenceExecutionOrder`.

**Only `STOP RUN` is program termination (2026-08-12 fix, audit A-B1):**
the end-of-program handling (flag still-open files, clear open-file state)
used to fire for ANY `StopStatement`, but `STOP 'literal'` merely pauses for
operator action and execution continues -- so `OPEN, STOP 'literal', READ,
CLOSE` produced spurious FILE_LEFT_OPEN + READ_BEFORE_OPEN violations. Now
gated on `stop_type == "RUN"`, the same distinction `dead_code.py`'s and
`program_flow/scanner.py`'s `_is_terminator` already draw. Pinned by
`tests/regression/test_audit_2026_08_12_analysis.py::TestB1StopLiteralIsNotTermination`.

`_literals.py`'s `quote_literal()` re-emits a decoded literal doubling
each embedded `"`; its inverse `unquote_literal()` (2026-09-27) strips the
delimiters *and* collapses the doubled delimiter. Any consumer reading a
re-emitted literal back must use it: `generators/data/layout.py`
(`_strip_literal_quotes`, VALUE clauses), `analysis/constraints.py`
(`_strip_quotes`, branch witnesses) and `analysis/const_fold.py` (MOVE
sources) each stripped only the delimiters, so `VALUE "A""B"` generated
`A""B` and `MOVE '"'` folded to two quote characters. Pinned by
`tests/regression/test_doubled_quote_literal_values.py`.

## MoveTypeChecker

```python
report: MoveTypeReport = MoveTypeChecker().check(ast)
# report.violations: list[MoveTypeViolation]
# report.unresolved_count: int   -- MOVE operands whose DataCategory could
#                                    not be resolved (undeclared identifier,
#                                    unexpanded copybook, ...); serialized
#                                    in report.to_dict()
# report.unresolved_function_count: int -- the part of unresolved_count no
#                                    copybook can fix: a FUNCTION source with
#                                    a NATIONAL result or an uncatalogued name
# MoveViolationKind: NUMERIC_TO_ALPHANUMERIC, ALPHANUMERIC_TO_NUMERIC, …
```

Detects MOVE statements with type-incompatible sending/receiving fields based on
PICTURE clause categories.

**MOVE CORRESPONDING (2026-10-14, issue #383):** a CORR move was skipped
outright and not counted anywhere, so a type-mismatched one read as a clean
all-clear. It is now expanded into its pairs by the IBM rule (same name path
below the two groups, at least one of the two elementary; FILLER, level
66/77/88, REDEFINES, OCCURS and INDEX/POINTER subordinates -- and what is
under a REDEFINES/OCCURS item -- excluded, mirroring
`field_lineage._corresponding`), and each pair is checked like an ordinary
MOVE. Violations name the pair qualified (`AMT OF GRP-A` → `AMT OF GRP-B`).
An operand that does not resolve to exactly one declared *group* (undeclared,
ambiguous without qualifiers, elementary) adds one to `unresolved_count` per
receiving operand; a paired item with no category this checker models adds
one per pair. Pinned by
`test_move_type_checker.py::TestMoveCorrespondingPairs`.

**Intrinsic FUNCTION sources (2026-10-13, issue #291):** a `MOVE FUNCTION
x(...) TO y` was always skipped into `unresolved_count` (only the argless
`CURRENT-DATE` / `WHEN-COMPILED` were known), and lint's caveat then told the
user to pass `--copybook-path` for a COPY that was never missing. The result
category now comes from `dialects.le_signatures.intrinsic_signature(name).returns`:
`alphanumeric` → ALPHANUMERIC, `integer` → integer NUMERIC, `numeric` →
NUMERIC whose integer-ness is *unknown* (`None`: NUMVAL("12") is an integer,
NUMVAL("1.5") is not). SUM / REM / RANGE / MAX / MIN / ABS take their
integer-ness from their arguments by one rule: non-integer if any argument
is, an integer if all are, unknown otherwise. TRIM / ABS / USUBSTR / MAX /
MIN take their first argument's category;
UPPER-CASE / LOWER-CASE / REVERSE are ALPHANUMERIC only when their argument
resolves (a national argument gives a national result). A reference-modified
result (`FUNCTION CURRENT-DATE(1:8)`) is ALPHANUMERIC. A nested `FUNCTION
x(...)` argument is one argument. So `MOVE FUNCTION NUMVAL(X) TO` a `PIC A`
item is an error, but to a `PIC X` item it is skipped, never a guessed
error. What stays unchecked because of the function itself (NATIONAL-OF, an
uncatalogued name, a numeric result of unknown integer-ness into an
alphanumeric receiver, UPPER-CASE / TRIM / ... of a declared PIC N item) is
also counted in `unresolved_function_count`, and
lint words that caveat separately without the copybook hint; an unresolved
*argument* is still an ordinary unresolved operand. Pinned by
`test_move_type_checker.py::TestIntrinsicFunctionsWithArguments` /
`TestNumericFunctionIntegerness` and `test_lint.py::TestCaveats`.

**Group receivers and `ZERO` → alphabetic (2026-09-27):** a MOVE *into* a
group item is a group move (bytes copied as alphanumeric) and legal from any
sender, so group receivers are exempt from every elementary rule -- `MOVE
WS-AMT TO WS-GROUP` with a `V99` sender was reported as an illegal
non-integer→alphanumeric MOVE. `MOVE ZERO TO` a `PIC A` item is now an error
(ZERO is numeric). Both found by comparing a sender×receiver matrix against
GnuCOBOL's own MOVE legality check; the remaining disagreements are where
IBM is stricter than GnuCOBOL's `-std=ibm` (non-integer → alphanumeric) or a
documented choice here (HIGH/LOW-VALUE, QUOTE → numeric). Pinned by
`tests/unit/analysis/test_move_type_checker.py::TestGroupReceiverAndZeroToAlphabetic`.

**Glued subscripts and reference modification (2026-09-28):** the MOVE
parser folds a *source* as `T-E(2)` / `WS-A(1:3)` (no blanks), which
`base_data_name` does not split, so such a MOVE was silently skipped --
`_reference_name()` recovers the item name locally (value_tracker keeps the
old behaviour, so a substring never propagates whole values). A
reference-modified operand (source or receiver) is ALPHANUMERIC whatever
its base item is: `MOVE WS-A TO WS-N(2:3)` no longer warns, `MOVE
WS-D(1:2) TO WS-A` with a `V99` base is legal. Pinned by
`test_move_type_checker.py::TestSubscriptedAndReferenceModifiedOperands`.

**Picture classification fixes (2026-08-16 audit):** `_PIC_ALPHA_ONLY_RE`
now matches any concatenation of `A`/`A(n)` parts (`AA(3)`, `A(2)A(3)`) —
they previously fell through to ALPHANUMERIC, hiding illegal
numeric→alphabetic MOVEs. A pattern ending in the `CR`/`DB` sign symbol
classifies as NUMERIC_EDITED up front — `9(5)CR` was UNKNOWN (silently
skipped into `unresolved_count`) while `9(5)DB` was NUMERIC_EDITED only
because its 'B' happened to match the blank-insertion edit char. Pinned by
`tests/regression/test_audit_2026_08_16_analyzers.py::TestA5A6MoveTypePictureClassification`.

**Repeat counts are not symbols (2026-10-14, #336):** inside an edited
picture, the `9` / `X` / `A` tests that pick NUMERIC_EDITED vs
ALPHANUMERIC_EDITED run on `pattern_no_reps` (repeat counts stripped), so
the 9 in `X(9)BX(9)` or `A(9)B` no longer reads as a digit position; these
classify ALPHANUMERIC_EDITED like `X(10)BX(10)`. Pinned by
`test_move_type_checker.py::TestPictureVariants::test_nine_in_repeat_count_is_not_a_digit_position`.

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

**`_is_non_integer_picture` reads one canonical field, not two independent
checks (2026-09-10):** it used to also re-derive the leading-`P`-scaled
fraction case (`PPP9`) from the raw pattern string
(`pattern.replace("S", "").startswith("P")`) *in addition to* checking
`decimal_digits > 0` — redundant, since `PictureClause._parse_scaled_pattern`
already sets `decimal_digits = P-count + 9-count` for a leading-`P` picture
(a *trailing*-`P` picture like `9(3)PPP` is a scaled *integer*,
`decimal_digits == 0`, correctly excluded either way). Now just
`decimal_digits > 0`, the same field `generators/data/layout.py`'s
`FieldSpec.stored_digits`/`scaling_positions` and `layout_offsets.py` (the
`data-items` CLI) already key off of — see this doc's own P-scaling note in
[generators.md](generators.md).

## LinkageChecker

```python
report: LinkageReport = LinkageChecker().check(ast)   # note: .check(), not .analyze()
# report.violations: list[LinkageViolation]
# LinkageViolationKind: MISSING_USING_CLAUSE, UNDEFINED_LINKAGE_ITEM, …
# LinkageChecker(include_contained_programs=False).check(ast, interface_scope=root)
#   — one unit only (what LintAnalyzer does per program unit); the default
#   still walks every contained program of a whole file.
```

Validates LINKAGE SECTION items against the PROCEDURE DIVISION USING clause.
`VALUE_TO_LINKAGE` was **removed** on 2026-09-09: COBOL has no rule that a
LINKAGE item must be passed BY REFERENCE — BY VALUE is *required* when the
callee declares `PROCEDURE DIVISION USING BY VALUE` — so the check only ever
produced a false positive (a lint `error`) exactly where it could see the
callee. `UNREFERENCED_LINKAGE` findings now carry the item's declaration
`location` and `LinkageViolation.item_name`, so lint keeps one finding per
program unit instead of collapsing same-text findings from different units.

**`PASSING_MODE_MISMATCH` (replaces the removed rule with a real check):**
a CALL's own BY VALUE/BY REFERENCE (explicit, or COBOL's own BY REFERENCE
default) checked position-by-position against what the *callee's own*
`PROCEDURE DIVISION USING` explicitly declares — never against the LINKAGE
item's own section. Needs `divisions/base.py`'s new `using_parameter_modes`
metadata (name → `"VALUE"`/`"REFERENCE"`, alongside the existing
`using_parameters` name list) to know the callee's declared mode; only
resolvable for a static CALL to a program in the same source whose implicit
entry interface was collected — an `ENTRY` statement's own USING carries no
BY clause in COBOL, so a CALL to one is never checked for this. `BY CONTENT`
call arguments are never flagged either way (no USING counterpart to compare
against).

**CALL argument forms reference their item (2026-09-28).** A CALL
`USING`/`RETURNING` operand is reduced to its data names
(`_argument_names`: `ADDRESS OF` / `LENGTH OF` dropped, subscripts and
reference modifiers removed, every `OF`/`IN` qualifier kept) and a
subordinate item maps to its 01-level owner, so `LK-REC(1:4)`,
`ADDRESS OF LK-REC`, `LK-ITEM OF LK-REC` and `LK-ITEM` no longer report
`LK-REC` as UNREFERENCED_LINKAGE.

**O(units²) → O(units) interface collection (2026-09-10):** `LintAnalyzer`
used to have each of a file's N program units' own `linkage-check` collector
call `LinkageChecker.check()` with no shared state, and `check()`'s own
scope-wide `_collect_interfaces` walk re-visited all N units every time —
O(N²) AST visits for the file. `LinkageChecker.collect_scope_interfaces(ast)`
computes the interface map (and the passing-mode map above) once;
`check(..., entry_interfaces=..., entry_parameter_modes=...)` accepts either
or both precomputed, skipping its own collection loop entirely.
`LintAnalyzer.analyze()` now calls it once per file, not once per unit.

## LanguageEnvironmentAnalyzer

```python
result: LEAnalysisResult = LanguageEnvironmentAnalyzer().analyze(ast)
# result.le_functions: list[LEFunctionUsage]   — CEE* calls
# result.service_calls: list[LEServiceCall]    — IBM LE runtime calls
```

Detects IBM Language Environment function calls (CEEGTST, CEEMGET, etc.) and
LE service calls.

**Quoted string literals are never scanned for `FUNCTION <name>`
(2026-08-16 audit fix):** `_collect_text_fields`'s `_add` skips operands
that are quoted literals — `DISPLAY 'FUNCTION KEYS ARE DISABLED'` used to
report a fictitious intrinsic function `KEYS` and set
`uses_intrinsic_functions` true. Pinned by
`tests/regression/test_audit_2026_08_16_analyzers.py::TestA3FunctionInsideLiteralIsProse`.

**`FUNCTION` must be its own word; conditions and STRING are scanned
(2026-09-28):** the regex matched `FUNCTION` inside a data name --
`WS-FUNCTIONAL`, `DLI-FUNCTIONS`, `FUNCTIONAL-CODE` reported intrinsics
`AL`, `S`, `AL-CODE`. It now needs no name character before it, and the
no-blank form (`FUNCTIONLENGTH`) is accepted only for a known intrinsic.
IF / PERFORM UNTIL conditions (their operands live on the condition tree)
and STRING's split `"FUNCTION"`, `"UPPER-CASE ( X )"` operands used to be
missed. `TestIntrinsicReferenceBoundaries` in
`tests/unit/test_language_env_analyzer.py`.

### Call signatures (`dialects/le_signatures.py`)

The analyzer answers "is this an LE service?"; `le_signatures.py` answers the
next question — **what does the CALL need?**

```python
from cobolparser.dialects.le_signatures import (
    le_service_signature, intrinsic_signature,
    LE_SERVICE_SIGNATURES, INTRINSIC_FUNCTION_SIGNATURES,
    services_without_signature, catalog_to_dict,
)

sig = le_service_signature("CEEDAYS")     # case-insensitive; None when unknown
sig.parameters                            # tuple[LEParameter]: name, direction
                                          # (input/output/input-output), type_id,
                                          # description, optional, repeats
sig.required_parameters                   # the ones that may not be omitted
sig.call_example()                        # 'CALL "CEEDAYS" USING ...'
p.data_type                               # LEDataType: declaration, byte_length,
                                          # snippet (VSTRING / feedback code)
intrinsic_signature("NUMVAL-C").returns   # "numeric"
```

**Coverage is partial and says so.** `services_without_signature()` lists the
LE services `IBM_LE_CALLABLE_SERVICES` recognises but this module cannot
describe exactly — so a consumer can say "known service, signature not
catalogued" rather than guess a parameter list or show nothing. The intrinsic
half *is* complete, pinned by
`tests/unit/test_le_signatures.py::TestIntrinsicSignatures::test_every_ibm_intrinsic_has_a_signature`.

**The intrinsic set is Enterprise COBOL 6.4's, not COBOL-85's
(2026-09-28).** `IBM_INTRINSIC_FUNCTIONS` and the catalogue used to stop at
the 1989 amendment's 42 functions, so `FUNCTION TRIM`, `NUMVAL-F`,
`FORMATTED-DATETIME`, `BYTE-LENGTH`, `DISPLAY-OF`, `ULENGTH`, `UUID4`, ...
were reported `is_ibm_function: false` by `language-env` and unknown by
`le-info`. The 37 later functions (3.x/4.x Unicode, 6.1 date-time / TEST-* /
E / PI / TRIM, 6.3 BIT-/HEX-, 6.4 UUID4) now carry signatures with IBM's
arity (optional trailing operands marked). Pinned by
`test_le_signatures.py::TestEnterpriseSixIntrinsicSignatures` and
`test_language_env_analyzer.py::TestEnterpriseSixIntrinsics`.

**Two service signatures were wrong (2026-09-28), both checked against
SA38-0683:** `CEE3ABD`'s second operand (IBM: `clean-up`) had its values
reversed -- 0 is the abend *without* clean-up, 1 after normal enclave
termination -- and `CEEISEC` was missing `input_milliseconds` (9 operands,
not 8), so a CALL written from `le-info`'s example passed `output_seconds`
where LE reads milliseconds. `TestServiceOperandsMatchIbm`.

**Five more operand lists corrected (issue #270, 2026-10-05), against
SA38-0683:** `CEEGMT` / `CEEUTC` are `(output_GMT_Lilian, output_GMT_seconds,
fc)` -- they carried a third `output_Gregorian` CHAR17 operand that only
`CEELOCT` has, so a CALL copied from `le-info` put the feedback code where LE
reads nothing and left `fc` unset. `CEEFMDA` / `CEEFMDT` / `CEEFMTM` take a
leading `country_code` (CHAR2, input; blanks or `OMITTED` for the current
setting -- positional, so it is *not* `optional`, which in this catalogue means
"may be dropped from the end of the USING list"). `CEE3DMP`'s `options` is a
fixed `PIC X(255)` (new `char255` type; `char2` was added too), not a
halfword-prefixed `vstring`. `CATALOG_VERSION` is unchanged: new type ids,
same dict shape. Consumers that copied the old lists (the COBOL Analyzer
extension's hover) pick the fix up from `le-info`.

`IBMEnterpriseCobol.IBM_LE_SERVICE_INFO` is **derived** from this catalogue
(merged over `_UNCATALOGUED_LE_SERVICE_INFO`, the leftovers), so the dialect's
one-line metadata and the signatures cannot drift. Categories are cross-checked
against `IBM_LE_SERVICE_CATEGORIES` per service by the same test module.

Exposed to non-Python consumers as `cobol-parser le-info` (see `.okf/cli.md`),
which is what the VS Code extension's LE hover reads.

## CRUDMatrixGenerator

> 2026-09-28: `SORT`/`MERGE` now mark their files. `USING` files are read
> (R) and `GIVING` files written (C) -- the sort does the I/O itself, so no
> READ/WRITE statement ever names them and they used to come out `----`.
> `RELEASE` marks its SD file C (via the record's FD/SD) and `RETURN` marks
> it R. Pinned by `test_crud_matrix.py::TestSortMergeFileAccess`.

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

**Record→file resolution is shared, not its own copy (2026-09-10):**
`_collect_record_to_file_mapping`/`_resolve_file_name` now call
`analysis._files.record_to_file_map()`/`resolve_file_name()` -- the same
FILE SECTION `fd_file_name`-metadata walk `io_logger.py` and `io_sequence.py`
already use -- instead of an independent copy of the same walk. `_files`'s
`resolve_file_name()` returns a direct `file_name` argument verbatim
(case preserved, for `io_logger`'s human-readable report); this generator
still upper-cases the result itself since `self._file_entries` is keyed by
upper-case name.

**SQL write statements (2026-09-28):** for INSERT/UPDATE/DELETE/MERGE only
`stmt.tables[0]` (the target -- see [dialects.md](dialects.md)) gets the
write flag; every other table a subquery / `INSERT ... SELECT` / `MERGE ...
USING` names is marked **R**. `DELETE FROM T WHERE X IN (SELECT X FROM S)`
used to mark S deleted. MERGE (previously ignored) marks its target with the
actions its `THEN INSERT|UPDATE|DELETE` clauses take.

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

**`possible_values` is deterministic (2026-08-16 audit fix):**
`CallStatement.set_possible_values` sorts the deduplicated list —
`list(set(...))` made the JSON order vary per process under hash
randomization. The `analyze` CLI also emits the
`possible_values_incomplete` flag now (see cli.md). Pinned by
`tests/regression/test_audit_2026_08_16_analyzers.py::TestA2PossibleValuesDeterministic`.

**Consumers read candidates through `_names.callee_names` (2026-10-12):**
`possible_values` keeps every literal MOVEd to the CALL identifier,
figuratives included (SPACES / LOW-VALUES / HIGH-VALUES as `" "` /
`"\x00"` / `"\xff"`, ZERO as `"0"`) -- the "no program" sentinel a
dispatcher tests before its CALL. `callee_names()` strips those bytes and
quotes, drops anything empty or all-digit, and is the one filter
`field_lineage`, `codebase` (codebase-graph), `recursion_risk` and
`boundary_inventory` share, so none of them invents a `\x00` / `0` / `Ÿ`
callee, and a CALL whose only candidates are sentinels is reported
unresolved. The `possible_values` JSON itself is unchanged.

**A write through a REDEFINES overlay is a write to the CALL variable
(#257).** `_overlapping_names()` -- which decides what counts as "writing
the CALL variable's storage" for `_mark_untracked_writes()` -- follows
`REDEFINES` as well as the group hierarchy: the redefining item, the item it
redefines (matched by name at the same level number) and every subordinate
on either side form one storage cluster (union-find, so several
redefinitions of one area join). `MOVE 'PGMZ' TO WS-AREA` therefore marks a
`CALL WS-PGMN` (`WS-PGMN REDEFINES WS-AREA`) incomplete, as does a group
`MOVE ... TO WS-REC` for a `CALL WS-NM2` inside `WS-REC2 REDEFINES WS-REC`.
No byte-range precision: like the hierarchy rule, any write to the overlay
counts. Pinned by `tests/unit/test_value_tracker.py::TestRedefinesOverlap`.

## IMSSegmentAnalyzer

```python
from cobolparser.analysis import IMSSegmentAnalyzer
result = IMSSegmentAnalyzer().analyze(ast)
```

Analyses IMS DLI segment calls (EXEC DLI GU/GN/ISRT/DLET/REPL).

**Group-SSA segment names merge MOVE-tracked child values (2026-08-16
audit fix):** `_resolve_ssa_segment`'s group branch used to return only
the first child's static VALUE clause — `MOVE 'SEGB' TO SSA1-SEG-NAME`
was ignored, reporting the stale initial VALUE with full confidence. The
child field's MOVE-tracked values are now merged with its VALUE clause,
multi-candidate results using the existing "/" convention. Only values
from an actual MOVE are merged (a separate `_moved_values` dict, not
`_variable_values`): VALUE clauses are keyed by *bare* name, and two SSAs
whose child fields share a name (both `SSA-SEG-NAME`, qualified
differently — the shape `test_multiple_ssas_path_call` pins) would
otherwise cross-contaminate each other's static values. Pinned by
`tests/regression/test_audit_2026_08_16_analyzers.py::TestA4IMSMovedSegmentName`.

**Optional parmcount (2026-09-28):** `CALL 'CBLTDLI' USING parmcount,
function, pcb, ...` (also AIBTDLI; CEETDLI takes none) used to read the count
as the function code and shift PCB / I/O area / SSAs by one. A first operand
that is a numeric literal or a data item with a purely numeric PICTURE
(function codes are always `PIC X(4)`) is now skipped.
`TestParmcountOperand` in `tests/unit/test_ims_segment_analyzer.py`.

**Segment name = first 8 *bytes*, not first child (2026-10-09):** a group
SSA's name used to come from its first child only, so a name split across
leaves (`05 A PIC X(4) VALUE 'CUST'. 05 B PIC X(4) VALUE 'OMER'.`) read
`CUST`, and one inside a nested sub-group read `None`.
`_group_segment_candidates` now walks the leaves in storage order
(`_ssa_leaves`: REDEFINES skipped, a sub-group with its own VALUE/MOVE taken
whole), each leaf contributing VALUE ∪ MOVEs padded/cut to its width
(`calculate_size()`), until 8 bytes are known; candidates combine (capped at
16), and a leaf with unknown content before byte 8 leaves the name `None`
rather than truncated. Qualified MOVEs match against the SSA *and* every
intermediate group name. An elementary SSA with a VALUE now also merges
MOVEs into it. `EXEC DLI ... SEGMENT((area))` (doubled parens = a data area)
resolves through `_resolve_ssa_segment(area)` instead of reporting the text
`(AREA)`; `None` when unknown. Pinned by
`tests/unit/analysis/test_ims_ssa_segment_resolution.py`.

## HostVariableResolver

```python
from cobolparser.analysis import HostVariableResolver
resolved = HostVariableResolver().resolve(ast)   # note: .resolve(), not .analyze()
```

Resolves SQL host variables (`:var-name`) in EXEC SQL blocks against WORKING-STORAGE
definitions.

**Name matching is verbatim.** `_column_index` keys DCLGEN columns by their
own upper-cased name, so `CUST_ID` and the host variable `CUST-ID` DCLGEN
generates for it do *not* pair up here. `DclgenChecker` (below) does that
normalization itself rather than changing this resolver's semantics under its
other consumers.

## DclgenChecker (`dclgen_check.py`, 2026-09-07)

```python
from cobolparser.analysis import DclgenChecker
report: DclgenReport = DclgenChecker().check(ast)   # note: .check(), not .analyze()
# report.violations: list[DclgenViolation]  (kind/severity/host_variable/column/table/
#                                            expected_picture/expected_usage/
#                                            actual_picture/actual_usage/location)
# report.checked / .unchecked / .tables / .ambiguous_columns
# report.has_violations / .worst_severity() / .to_dict()
```

Cross-checks every `:host-var` against the DCLGEN `DECLARE TABLE` column of
its name. Backs `cobol-parser dclgen-check` and the `dclgen-check` lint rule.

**Why it is nearly free:** both halves are already parsed.
`HostVariableResolver` pairs a host variable with its DATA DIVISION item;
`DeclareTableStatement.columns` carries the DB2 side with
`db2_type_to_cobol_pic()` / `db2_type_to_cobol_usage()` already applied. The
checker resolves nothing itself — it only says whether a pair agrees — so a
fix to the type mapping fixes the check too.

**The name normalization is load-bearing.** DB2 columns are underscored
(`CUST_ID`); the host variables DCLGEN generates are hyphenated (`CUST-ID`),
because `_` is not a COBOL data-name character. `_normalize()` (`_` -> `-`,
upper-cased) is applied to both sides via `_column_index()`. Without it the
checker reports that no column matches *any* host variable — i.e. it checks
nothing while looking like it had. That was the first bug found in
development, and `test_an_underscored_column_is_matched_to_its_hyphenated_host_variable`
pins it.

**Null indicators are not host variables here (2026-09-28).** An indicator
(`:X:IND`, `:X INDICATOR :IND`) is picked up by the `:name` scan like any
host variable but binds to no column; names in any statement's
`null_indicators` are dropped from the checked set (unless a column of
that name exists), instead of each being reported as `unchecked`.

| kind | severity | what it costs at runtime |
|------|----------|--------------------------|
| `category` | error | CHAR column into a numeric item (or the reverse); the binding does not mean what it says |
| `scale` | error | `DECIMAL(9,2)` into `PIC S9(7)V9` — the cents are silently rounded away on every fetch, and no status code says so |
| `precision` | error | too few integer digits; SQLCODE -304, but only once a row actually exceeds it |
| `length` | error / info | `CHAR(30)` into `PIC X(20)` truncates every fetch (error); the reverse only wastes space (info) |
| `usage` | warning | DISPLAY where DCLGEN generates COMP-3; DB2 converts every row rather than moving it (IBM synonyms are folded first: `BINARY`/`COMP-4`/`COMP-5` all count as `COMP`, since on z/OS `COMP-5` is the same big-endian storage and is IBM's recommended integer host variable -- #259) |
| `sign` | warning | unsigned host variable; a negative value arrives as its absolute value |
| `null-indicator` | warning | nullable column with no indicator variable; SQLCODE -305 the first time the column is actually null |

**A `category` finding stands alone.** Every later check would be comparing
digits against characters, so `_compare` returns immediately after one rather
than dragging four confusing restatements along with it.

**Indicator pairing is program-wide, and read off the statement text.**
`ExecSQLStatement` keeps the indicator *names* but not which variable each
belongs to, so `_INDICATOR_RE` re-scans `sql_text` for both forms
(`:VAR:IND` and `:VAR INDICATOR :IND`). The whitespace between name and
separator is matched **once, before the alternation** — putting it inside the
`INDICATOR` branch leaves that branch with no space left to match, which is
exactly the bug the first draft had. Program-wide rather than per-statement:
a variable given an indicator on its FETCH and not on its SELECT INTO is a
different (and much rarer) bug than never having one, and flagging the second
statement would bury the finding that matters.
A structure-qualified variable (`:DCLCUST.CUST-VAL:IND`) pairs by its last
component, like the SQL model's host-variable list (2026-09-28; before that
the structure name was the "host variable" and nothing was checked).

**What it declines to check, and says so.** `report.unchecked` is
`name: reason` for every host variable that could not be compared — no
DECLARE TABLE names a column of that name, the program has no DECLARE TABLE
at all, `VARCHAR`/`CLOB` (which bind to a *group* item: a length halfword
plus the text, so one elementary PICTURE is the wrong thing to compare), or
a type with no COBOL PICTURE (`BLOB`, `XML`, ...). A clean report is never
mistaken for a checked one. `ambiguous_columns` names a column two tables
both declare; the first declaration wins the comparison, matching
`HostVariableResolver`'s own rule, and the collision is stated rather than
assumed away.

The lint rule folds `unchecked` and `ambiguous_columns` into
`LintReport.caveats` (one line with a count, not one finding per variable)
rather than emitting findings for them.

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
non-interactive sources filtered, matched on the source's first word so
`FROM DATE YYYYMMDD` / `FROM DAY YYYYDDD` count as `DATE` / `DAY`).
`DISPLAY` is never a boundary (assert-only, out of scope for this phase,
matching mockymock's own `mock_surface`).

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
   "Nth" is the Nth name of the callee's `PROCEDURE DIVISION USING`
   (RETURNING excluded), not the Nth LINKAGE 01 in declaration order --
   those differ whenever LINKAGE is declared in another order or holds
   `SET ADDRESS OF` items (fixed 2026-09-28; the old binding inverted the
   directions). Declaration order is only the fallback for a callee with
   no USING.
3. Caller-side dataflow in the enclosing paragraph's own statement list
   (source order): last write before the CALL with no read after -> **OUT**;
   first read after with no write before -> **IN**; both -> **BIDIRECTIONAL**.
   A write to a *parent group* counts as touching a child field (and vice
   versa), checked via `FieldSpec.path` prefix comparison through the index,
   not bare string equality. "Read" for a write-shaped statement (rung 2's
   list above) comes from a per-type read list (`_write_shaped_read_names`,
   issue #268) and is checked *before* that statement's writes: MOVE's
   `.source`; ADD/SUBTRACT/MULTIPLY/DIVIDE's operands minus the GIVING and
   REMAINDER receivers (without GIVING the TO/FROM/BY/INTO target is read
   *and* written; with GIVING it is read only and is no longer counted as a
   write target either); every name in a COMPUTE expression; STRING's
   sending operands, delimiters and POINTER; UNSTRING's source, delimiters,
   POINTER and TALLYING; SET's value (plus the target for UP/DOWN BY);
   INITIALIZE's REPLACING BY values. POINTER/TALLYING/COUNT IN/DELIMITER IN
   are write targets too. A write-shaped type with no read list whose
   `.operands` names the arg outside its write targets degrades the arg to
   **BIDIRECTIONAL** `assumed-bidirectional`, never OUT. The generic
   `.operands` fallback is reserved for statement types with no write-shape
   at all (DISPLAY, IF conditions, ...) since a write-shaped statement's own
   `.operands` also contains its target, which would otherwise misread a
   write as a read of the same name.
4. Otherwise **BIDIRECTIONAL**, `provenance="assumed-bidirectional"`.

**Rung 3's "read" also covers a branching statement's own condition**
(`_condition_read_names`, 2026-09-09): an `IfStatement`'s condition tree, a
`PerformStatement UNTIL`'s guard, and an `EvaluateStatement`'s subjects and
WHEN selectors don't reach the statement's generic `.operands` bag (an
`IfStatement`'s is empty), so a CALL argument whose only later use is `IF
WS-RC = 'Y'` used to look unread and misclassify as OUT. Two 2026-09-10
follow-ups to that walk: (1) `_condition_field_names` now recurses into a
`ConditionalExpression`/`ArithmeticExpression` operand that is itself an
expression (`A + B = C`) and into a `FunctionCall`'s arguments
(`FUNCTION UPPER-CASE(WS-X)`), not just bare-string operands; (2) an
`EVALUATE` subject that arrives as a `CobolExpression` rather than a plain
string (`EvaluateStatement.subjects: list[str | CobolExpression]`) is walked
the same way instead of silently skipped -- the real parser only ever
produces string subjects today, so this guards the documented type contract
against a future parser change rather than a reachable bug, but the read
scan would otherwise go silently blind the day it changes.

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
The other texts are whitespace-collapsed before the comparison
(2026-10-12): the prefix is joined from split words, while the raw
`sql_text`/`cics_text`/`ims_text` keep their line breaks, so two multi-line
sites agreeing up to a line break (CICSONLN's two `SEND MAP`s, differing
only in `ERASE`/`DATAONLY`) used to get the same truncated key.
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
branch.enclosing             # tuple[(branch_id, arm_id), ...]: the arms that
                              # must ALL be taken for this branch to be
                              # reached at all -- outermost first

witness = solve(field_spec, branch.arms["THEN"])   # Witness | Unsatisfiable
```

**`enclosing`: the path condition (2026-09-04).** Every `BranchConstraints`
records the `(branch_id, arm_id)` chain enclosing it. `_walk_list` threads it
down through `_nested_statement_lists`, which now pairs each nested statement
list with the arm id it sits under (`THEN`/`ELSE` for an IF, `WHEN_n`/
`WHEN_OTHER` for an EVALUATE or SEARCH) -- ids that match the keys registered
in `arms`, by construction, so `ScenarioPlanner` can join on them. A
non-branch nesting (`ON EXCEPTION`, an inline `PERFORM` body) contributes no
entry: it is a path condition in the general sense but is not modeled as a
branch arm here, and inventing an id for one would produce a path entry
nothing could ever join to. **SEARCH's `AT END` is the exception**
(`_ARM_BEARING_ATTRS`): `_extract_search` really does register an
`arms["AT_END"]` entry, so a statement nested under it has an enclosing arm
to join to -- even though the clause reaches `_walk_list` through
`_NESTED_STATEMENT_ATTRS` rather than a `when_clauses` list. Leaving it
untagged made such a statement look top-level, so a scenario for a branch
inside it could be reported verified without its data establishing that the
table search found nothing.

This exists because the planner's v1 simplification -- take only the targeted
arm's own conjuncts -- was the biggest single source of scenarios whose data
never reached their own arm. On `IF INV-QTY > 500 / IF INV-TYPE = "AB"`, the
inner arm's scenario pinned `INV-TYPE` and let `INV-QTY` fall wherever the
value factory put it, so it usually never entered the outer arm at all, and
the scenario's name was a claim its data did not support. See
[generators](generators.md)'s "Path conditions" section for the planner side.

**Extraction sources and op vocabulary** (`FieldConstraint.op`): `eq ne lt le
gt ge in_set not_in_set class_numeric class_alphabetic figurative`.
Relational comparisons (`=`, `>`, `<`, `>=`, `<=`, `NOT =`/`<>`) map directly;
a level-88 bare condition-name (`IF ORDER-VALID`) resolves through
`ProgramLayoutIndex.resolve()` to its *parent* field and becomes `in_set`
over **that one condition name's own** VALUEs (THRU ranges included), read
via `ProgramLayoutIndex.condition_values()` — deliberately NOT
`FieldSpec.condition_values`, which is the *union* of every 88 declared
under the parent field. The union is correct for the value factory ("any
value that could apply to this field") and wrong here: reading it made every
arm of an `EVALUATE TRUE / WHEN <88>` chain produce a byte-identical
constraint, so the solver picked the first 88's value for all of them and the
scenario named for the second arm was seeded with the first arm's value and
never reached the branch it was named for. Both lookups stay available
because they answer different questions. **A negated 88 needs the whole
set** (2026-09-28): `condition_values()` is only a *sample* when a `THRU`
range could not be enumerated (a non-integer range lists its endpoints, an
integer one is capped at 65 values, and any range over a field with
decimals admits values in between). `NOT <88>` over such a name, and the
`WHEN OTHER` after `WHEN <88>`, are reported in `unsupported` rather than
modelled as a `not_in_set` whose witness can sit inside the range
(`layout.condition_values_exhaustive()` over
`ProgramLayoutIndex.condition_raw_values()` decides; a non-exhaustive
positive `in_set` carries `FieldConstraint.exhaustive=False`, not part of
`to_dict()`). An 88 `VALUE ALL 'X'` (2026-09-28) is the `in_set` of the one
value filling the field (`XXX` on `PIC X(3)`, from
`ProgramLayoutIndex.condition_values`); `VALUE ALL SPACES` counts as the
figurative `SPACES`; only a bare `ALL` is still reported unsupported. An 88
whose one VALUE is a figurative constant (`VALUE
SPACES`) becomes the `figurative` constraint `IF X = SPACES` would, instead
of an `in_set` over the word itself (which rendered `"SPA"`);
figurative constants (`SPACES`/`ZEROS`/`LOW-VALUES`/...) become `figurative`
with the symbolic name preserved in `values`, not its literal expansion (the
solver fills an alphanumeric field's whole width with it: `ZEROS` on `PIC
X(3)` is `"000"`, since `"0"` pads to `"0  "`); `LOW-VALUES` / `HIGH-VALUES` / `NULL`
(binary X'00' / X'FF', which generated character data never holds -- both
tables map them to `""`, which rendered as *blanks*) make the positive test
`Unsatisfiable` instead of witnessing spaces, and a numeric field compared
equal to any non-zero figurative (`SPACES`, `QUOTES`, ...) likewise, rather
than no-op'ing to an arbitrary number (2026-09-28,
`tests/regression/test_domains_unrepresentable_figuratives.py`); the negated
forms narrow nothing;
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

**`WHEN OTHER` is the negation of every prior arm, not "unconstrained".**
`_negate_prior_arms` models the shape that dominates real COBOL — an
`EVALUATE` whose every arm is a single `eq`/`in_set` test on the *same*
field — as exactly one `not_in_set` over the union of those arms' values.
Anything else (arms over different fields, conjunctions, relational or class
tests) needs a disjunction the `FieldConstraint` vocabulary cannot express,
so the arm stays unconstrained *and records why* in the branch's
`unsupported` list. Leaving it unconstrained unconditionally (v1) was not the
neutral choice it looks like: an unconstrained level-88 field is generated by
drawing from its own `condition_values` (`generators/data/values.py`), so
every row of the scenario named for the OTHER arm carried one of the very
values that arm excludes — the scenario could not reach its own branch,
deterministically rather than just often.

**Every later `WHEN` arm also negates the earlier ones.** `EVALUATE` is
first-match, so `WHEN_n` runs only when `WHEN_1..n-1` all failed.
`_negate_earlier_whens` conjoins onto each later arm the negation of every
earlier arm that is a single constraint (`gt`<->`le`, `eq`<->`ne`,
exhaustive `in_set`<->`not_in_set`, class/figurative flip). Without it
`WHEN A > 50 / WHEN A > 10` witnessed 51 for the second arm — a value that
takes the first — and a duplicate `WHEN 1 / WHEN 1` reported the unreachable
second arm as satisfiable (now `Unsatisfiable`). An earlier arm that cannot
be negated into one constraint (a `THRU` range, a conjunction, an
unsupported selector) is left out and noted in `unsupported`. `WHEN OTHER`
still negates only each arm's *own* selector constraints.

**A figurative `WHEN` selector is a `figurative` constraint (#313,
2026-10-14).** `_build_selector` marks a single-token selector
`"figurative": True` (`WHEN SPACES` / `ZERO` / `LOW-VALUES`) or
`"quoted": True` (`WHEN 'SPACES'`); before that both were the same
`{"type": "Literal", "value": "SPACES"}`, so gen-fixtures wrote the six
characters `SPACES` for the figurative arm and called it verified, and
`WHEN ZERO` / `WHEN LOW-VALUES` were missed as literals that do not fit.
`_extract_evaluate_selector` now maps a figurative selector the way the IF
path does (`_figurative_name`), and a quoted selector is never looked up as
a data name. `business_rules._literal` renders a quoted selector with its
quotes, so `WHEN 'SPACES'` no longer reads as `= SPACES`.

**The level-88 enum domain is a preference, not the field's domain.**
`solve()` tries `EnumDomain(spec.condition_values)` first whenever a set op is
in play, so `IF NOT TYPE-M` against 88s `"05"`/`"09"` still yields the other
*declared* value `"09"` rather than an arbitrary PICTURE-admissible string.
But a `not_in_set` covering every declared value — exactly what a `WHEN
OTHER` arm negates to — empties that enum, and the answer there is a value
*outside* it, which the PICTURE does admit. An emptied enum therefore falls
back to `_picture_domain()` and re-applies the same constraints, instead of
reporting `Unsatisfiable` for a perfectly reachable branch. `_apply_numeric`
handles `in_set`/`not_in_set` explicitly for that fallback path (excluding
every listed value, or narrowing to the first admissible member) rather than
no-op'ing them, so a witness can never silently violate a set op it was
solved against. A genuine contradiction (`in_set ("A")` AND
`not_in_set ("A")`) is still `Unsatisfiable`.

**An enum pick is re-checked against every conjunct** (2026-10-04, #244).
`EnumDomain` narrows only by set ops; a relational or class conjunct beside
one is a no-op there. `IF NOT HIGH-V AND WS-C > 5` (88s `1`/`9`) used to
return `1` -- it survives `not_in_set ("9")` and fails `> 5`. Now each
surviving declared value is pinned (`eq`) into a fresh `_picture_domain()`
and every conjunct is applied (`_pinned_picture_domain`); the first value
that holds is the witness, rendered through the same post-checks as any
other. None holding falls back to the picture domain, which solves the
relational part itself (`52` for the example) or reports the contradiction
(`HIGH-V AND WS-C < 5` is `Unsatisfiable`).

**AND/OR/NOT via De Morgan.** `IfStatement.condition` is walked once for the
THEN arm (`negate=False`) and once more for the ELSE arm (`negate=True`).
Most negation is baked into concrete operator strings (`NOT_EQUAL`/`IS NOT
NUMERIC`), but `_conditions.py` wraps a negation it cannot fold -- `NOT
FLAG-ON`, `NOT (A = 1 AND B = 2)` -- in a unary `LogicalExpression("NOT")`
whose operand is `left_condition`; `_extract_expr` walks that operand with
`negate` flipped (2026-09-28: it used to reject the wrapper as an
"unsupported logical operator", leaving both arms of `IF NOT <88>`
unmodeled). An AND stays a single conjunct list; a negated AND becomes a
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

**SEARCH WHEN is extracted from a condition tree (issue #348, 2026-10-14).**
`search_parser.py` builds each WHEN condition with the shared
`build_condition_expression` (the IF / PERFORM UNTIL machinery) and stores
it as `when_clauses[i]["condition_tree"]` next to the unchanged raw
`"condition"` string; `SearchStatement.to_dict()` serializes it too.
`_extract_search` walks that tree with `_extract_expr`, so `WHEN A = 'K1' AND
B = 'Z'` is two conjuncts and an OR becomes `WHEN_n#1` / `WHEN_n#2` arms,
exactly like IF. Before, the raw text was split on its first operator and the
whole tail (`K1' AND B = 'Z`) became one made-up literal that gen-fixtures
wrote into every row while reporting the arm targeted. A SEARCH node built
without a tree still falls back to the text parser below.

**`EVALUATE TRUE`'s non-compound selectors use a minimal text parser.**
`EVALUATE TRUE WHEN <selector>` lacks structure for a simple relational
selector: `evaluate_parser.py`'s `_build_selector` never emits an
`"Identifier"` selector type at all -- a bare condition-name like `WHEN
F1-VALID` and a simple comparison like `WHEN F1-QTY = 5` both arrive as
`{"type": "Literal", ...}` / `{"type": "Condition", "text": ...}` with no
`"operator"` key. Those route through `_parse_relational_text`; a compound
`AND`/`OR` selector (`sel["operator"]` present) stays unsupported in v1.
`_parse_relational_text` itself reports any text holding an `AND`/`OR`
outside a quoted literal as unsupported rather than splitting it on its first
operator.
Before matching, `_symbolize_relational_words` spells the word operators
as symbols (`[IS] [NOT] GREATER|LESS [THAN] [OR EQUAL [TO]]`, `EQUAL[S]
[TO]`; quoted literals untouched), so `WHEN X GREATER THAN OR EQUAL TO 1`
yields the same `ge` constraint as `WHEN X >= 1` and its `OR` is not taken
for a connective (#387). `complexity.py`'s `_BOOL_WORD_RE` likewise skips
the OR of `OR EQUAL`.

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
result.known   # dict[qualified_name, str]: the value each field held at
               # the DISPLAY/WRITE sites that observed it
```

**`known` is the value at the observation point** (2026-10-04, #246,
decision (a) from the issue). `_WalkState.observed` records the env value at
every `DISPLAY`/`WRITE` site; a field is reported only when every site saw
the same known value. It used to report the env as it stood at the end of
the walk, so `MOVE 1 TO N3. DISPLAY N3. MOVE 2 TO N3.` claimed `2`. The walk
also **falls through**: after the entry paragraph it continues into every
following paragraph in source order (`_fall_through_chain`) until the walk
stops (`STOP RUN`/`GOBACK`/`EXIT PROGRAM`/`GO TO`), so a program displaying
`1` in `MAIN-PARA` and `2` in the next paragraph gets no `N3` expectation
rather than `1`. Following real control flow re-walks a PERFORMed
paragraph each time control reaches it -- quadratic for a chain of
paragraphs that each PERFORM the next with no STOP RUN -- so the main walk
has a `_MAX_WALK_STEPS` (50,000 statement visits) budget; past it the fold
reports nothing (`_WalkState.exhausted`), never a partial answer. No program
in the first 150 NIST files comes near it. The shamrice corpus's two former
`known` values (`sub.cbl`, `unstring.cbl`) were both multi-site
disagreements and are gone; `test_const_fold_corpus.py`'s non-triviality
check now also folds `tests/samples/file_operations.cbl` and
`enterprise/COMPDIR.cbl`. `bundle_version` is unchanged: only which
expectations are emitted changes, not their shape.

**Every site, and only control flow the walk really follows** (2026-10-13
bug hunt; each case checked against GnuCOBOL 3.2 output):

* **Every DISPLAY/WRITE is a site, walked or not.** A site inside an
  IF/EVALUATE arm, a loop body or a handler is recorded as unknown
  (`_poison_written_names`), and at the end `fold()` vetoes every field
  shown at a site the walk never reached (`_observation_sites` against
  `_WalkState.visited_sites`): code past a `GO TO`, code only a `GO TO`
  reaches, DECLARATIVES, dead paragraphs. `MOVE 1 TO A. DISPLAY A. IF ...
  MOVE 2 TO A DISPLAY A END-IF.` used to claim `A = 1`.
* **`PERFORM` of a SECTION** (and `THRU` a section) walks the section's
  paragraphs, unnamed ones included: `_ordered_paragraphs` keeps a
  `_SECTION_KEY` marker per section and an `_UNNAMED_KEY` key per unnamed
  paragraph, `_procedure_span` resolves both ends. It used to walk nothing,
  as if the PERFORM wrote nothing. A target that resolves to nothing at all
  now clears the env.
* **SEARCH WHEN bodies and SORT/MERGE INPUT/OUTPUT PROCEDUREs** are
  poisoned like a loop body (`_nested_statement_lists`, `_procedure_ranges`);
  both used to be skipped, so a write there survived as a known value.
* **Conditional transfers.** A `GO TO`, `EXIT PARAGRAPH/SECTION/PERFORM` or
  `NEXT SENTENCE` inside an arm / loop / handler (or a main-line `EXIT
  PARAGRAPH`...) sets `_WalkState.uncertain`: from then on every
  MOVE/arithmetic/READ/ACCEPT poisons instead of folding, because the walk
  can no longer tell whether it ran. A `GO TO` also clears the env (it runs
  code the walk never sees). The `IF ... GO TO P1-EXIT` idiom used to fold
  the MOVE the GO TO skips. Conservative: uncertainty lasts to the end of
  the walk. Pinned by
  `tests/unit/analysis/test_const_fold.py::TestControlFlowTheWalkDoesNotFollow`.

**A CALL / INVOKE forgets every GLOBAL and EXTERNAL leaf** (2026-10-13 bug
hunt): a contained program writes a GLOBAL item by name and every program
declaring the same EXTERNAL item shares its bytes, USING list or not, so
`MOVE 1 TO X. CALL 'INNER'. DISPLAY X.` with `X GLOBAL` claimed `1` where
GnuCOBOL shows what INNER stored. `_LayoutFacts.shared` (inherited from a
GLOBAL/EXTERNAL group) is dropped in `_poison_statement_writes`. Pinned by
`tests/unit/analysis/test_const_fold.py::TestCallMayWriteSharedStorage`.

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
  the current call stack. The loop's own `VARYING` / every `AFTER` variable
  is poisoned too (it ends one step past the UNTIL, never at its pre-loop
  value) -- inline, out-of-line, and nested inside an IF arm / loop body
  alike, via `_write_targets(PerformStatement)`. `SEARCH ... VARYING x`
  poisons `x` the same way (`varying_variable`).
* A write through a level-66 `RENAMES a [THRU b]` alias poisons the leaves
  it covers (`_LayoutFacts.renames`, the declaration-order run from `a`'s
  first leaf to `b`'s last; the whole record when that run is ambiguous).
  The alias is written, never seed-restored, by READ INTO / ACCEPT.
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
  verified by multiplying the quotient back **over `Fraction`**
  (`_exact_divide`), so a context-rounded repeating fraction can never
  masquerade as exact. A `REMAINDER` target is always poisoned (it is
  defined via the quotient as truncated to the GIVING target's PICTURE,
  which this module does not model), and `_write_targets` now includes it
  in the IF-arm/handler-body write scan (previously missed). The GIVING
  value stays safe to fold alongside a poisoned REMAINDER: it is only
  recorded when the true quotient fits exactly, i.e. truncation was a
  no-op. A `/` inside a `COMPUTE` expression tree goes through the same
  `_exact_divide` gate, so both spellings of a division hold the same
  contract (divide-by-zero and non-terminating decimals poison, not
  truncate).
  Pinned by `tests/regression/test_bug_review_2026_08_12.py::TestDivideMode`.
* **Writes that live outside `.operands`** (issue #317, 2026-10-14).
  `_write_targets` also collects `InspectStatement.tallying_clauses[*]["counter"]`
  (INSPECT ... TALLYING increments it in place), every string value of
  `ExecCicsStatement.options` (INTO/SET/LENGTH/RESP/RESP2/ITEM/...: the
  command decides which are written, so all are taken as written), and the
  argument of each `KEYWORD(arg)` in `ExecImsStatement.arguments` (EXEC DLI
  INTO/KEYFEEDBACK/...). Both EXEC nodes have an empty `.operands`, so
  before this a field MOVEd before the statement kept its old value and
  gen-fixtures asserted a `field_equals` a real run fails.
  Pinned by `tests/unit/analysis/test_const_fold.py::TestInspectAndExecWrites`.
* **Exactness is decided over `Fraction`, never over `Decimal`** (2026-09-16
  audit). Both halves of the exactness machinery used to decide exactness
  *using inexact decimal arithmetic*, and both let a wrong value through:
  * `_exact_divide` multiplied the quotient back inside the same `prec=80`
    block the division ran in. The rounding error is by construction too
    small for that precision to represent, so the product rounded straight
    back to the dividend and the check passed for *every* inexact quotient
    it was written to catch.
  * `_fits_exactly` — the last gate before a value is stored — scaled with
    `Decimal` operators, which run in the ambient 28-digit context. A value
    carrying more precision than that was silently rounded by the very
    `abs()` and `*` used to test it, so `8.999…9982` arrived already
    rounded to `9` and passed as an exact fit.

  Together: `COMPUTE WS-T = 3 / 0.3333333333333333333333333333334` into
  `PIC S9(9)V9(9)` folded to `9.000000000` where COBOL stores
  `8.999999999` — a wrong integer digit, emitted as a `field_equals`
  expectation. Both now convert to `Fraction`, which has no precision to
  round to. Reachability needed an operand carrying more than ~28
  significant digits (a 29–31 digit literal, which IBM Enterprise COBOL
  permits under `ARITH(EXTEND)`); short-literal expressions were already
  safe. Pinned by `tests/regression/test_audit_2026_09_16.py`.
* **A COMPUTE division is truncated mid-expression the way IBM truncates
  it** (2026-09-28). IBM carries a fixed-point quotient to only
  `max(d1 - d2, dmax)` decimal places ("Intermediate results and arithmetic
  precision"; `dmax` = the most decimal places of any result field or any
  operand other than a divisor or exponent), so `COMPUTE N = 7 / 2 * 2`
  into `PIC 99` stores 6 and `COMPUTE PCT = A / B * 100` stores 0 when
  A < B. The folder divided exactly and emitted 7 / 25. `_dmax_floor`
  computes a lower bound on `dmax` (every leaf under a `/` or `**`
  right-hand side left out -- a smaller bound only poisons more), and
  `_truncation_free_divide` poisons any quotient needing more places.
  Exponentiation follows IBM's three cases (`_fold_power`): an integer
  literal exponent is exact (`d1 * n` places); a negative one is
  `1 / x ** n` under the division rule (`100 * 2 ** -1` into `PIC 9(4)`
  is 0, not 50); an integral data-name/expression exponent carries only
  `dmax` places; an exponent with decimal places means floating point,
  poisoned. Pinned by
  `tests/regression/test_const_fold_intermediate_precision.py`.
* `ROUNDED`, `CORRESPONDING`, and any target that does not resolve to an
  elementary field are poisoned rather than approximated. A numeric
  MOVE/arithmetic result is only ever recorded when it fits its target
  field's PICTURE *exactly* (`_fits_exactly`: no truncated decimal digits,
  no truncated integer digits, no sign coercion into an unsigned field) --
  real COBOL's MOVE truncation rules are well-defined, but replicating them
  exactly is out of scope for v1; an overflowing result is poisoned instead.
  `MOVE ZERO`/`ZEROS`/`ZEROES` folds (0 into a numeric field, `"0"` in every
  position of an alphanumeric one) and `ZERO` is a known arithmetic operand.
  A text MOVE into `PIC N(n)` truncates to n characters (`spec.size` is
  bytes, two per national character; it had kept 2n).
* **ADD/SUBTRACT addends come from `ArithmeticStatement.source_operands`**
  (2026-09-27), the operands written before TO/FROM/GIVING with duplicates
  kept, set by the ADD/SUBTRACT parsers and not serialized.
  `ArithmeticStatement.operands` cannot answer "which names are addends":
  `set_target`/`set_giving` append a name only when it is absent, so
  `ADD A B GIVING B` and `ADD A GIVING B` both leave `[A, B]`. The folder
  used to filter target/GIVING names out of `.operands`, which poisoned
  `ADD X TO X` and -- worse, breaking the exact-or-absent contract --
  silently dropped a real addend in `ADD -6.05 N8 GIVING N8` (folded to
  -6.05) and `ADD X, Y TO X`. Found by fuzzing random straight-line
  programs against GnuCOBOL (~12,000 folded values compared, all now
  matching). A node without `source_operands` is poisoned. `MULTIPLY`'s
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
* **A subscripted/reference-modified READ INTO or ACCEPT target is poisoned,
  never restored (2026-09-10 fix).** `_target_paths()` used to drop the
  `has_suffix` flag `_base_name()` returns and resolve straight to the base
  item's *whole* qualified name, so `READ F INTO WS-BUFFER(1:5)` restored
  all of `WS-BUFFER` to its seed value on the first READ even though only
  bytes 1-5 were actually written — the same `has_suffix` case
  `_apply_move_target`/`_write_numeric` already poison rather than assert a
  value for. `_target_paths()` now returns `(qpath, exact)` pairs; a
  suffixed target's `_reset_under` call always passes `restore=False`
  regardless of whether this is the file/target's first occurrence.
* **Storage shared without a REDEFINES clause** (2026-10-04, #245).
  Every 01 under one FD/SD implicitly redefines the same record area, so
  `_link_file_records` unions the leaves of every
  `index.records_for_file(f)` (`ProgramLayoutIndex.file_names()`) into one
  alias class: `MOVE 1234 TO B. MOVE 'ABCD' TO A. DISPLAY B.` (B in R2, A in
  R1, both under `FD F`) leaves B unknown -- it used to claim `1234`.
  `WRITE rec FROM id` is folded as `MOVE id TO rec` before the WRITE is
  observed (a group record is poisoned whole); `REWRITE ... FROM` takes the
  generic poison path, which already covers the record. A field source
  MOVEd into a `JUSTIFIED RIGHT` receiver is space-padded to its own width
  first (`_text_width`), because `env` stores text unpadded and COBOL sends
  the whole field: `X5 = 'ABCD'` into `PIC X(3) JUST RIGHT` is `'CD '`,
  not `'BCD'`.
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
  folded or observed). A paragraph's end is not a stop: control falls
  through into the next paragraph (#246).

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

## Invocation counts (`invocation_counts.py`)

Backs `gen-fixtures`' tier 1 `call_count` (issue #363; see
`.okf/generators.md`). `count_invocations(ast, report, index)` walks the
entry chain with `const_fold.py`'s own paragraph helpers
(`_entry_paragraph`, `_fall_through_chain`, `_ordered_paragraphs`,
`_perform_body_statements`, `_transfer_kind`) on an explicit frame stack,
and gives each statement it reaches an exact execution count or "unknown":

* main line and SIMPLE PERFORMs (inline, out of line, THRU, SECTION) add
  their multiplier each time reached -- a paragraph PERFORMed and also
  fallen into counts 2; `PERFORM <literal> TIMES` multiplies;
* IF / EVALUATE / SEARCH arms, handler bodies, `PERFORM UNTIL` / `VARYING` /
  variable-`TIMES` bodies and SORT / MERGE procedures are unknown;
* a transfer (GO TO, EXIT PARAGRAPH / SECTION / PERFORM, NEXT SENTENCE,
  STOP RUN, GOBACK, EXIT PROGRAM) inside such a region makes everything
  after it unknown; on the main line, GO TO / STOP ends the walk and a skip
  makes the rest unknown; inside a literal `TIMES` body any transfer
  discards every count (they would be overstated);
* a main-line GO TO is followed forward (`push_chain` at the target) only
  when no statement of the target paragraph was walked yet; a backward jump
  (a GO TO read loop), a GO TO out of a PERFORMed paragraph, GO TO
  DEPENDING ON, an unknown target, or any ALTER in the program discards
  every count;
* **status exemption**: an IF reading only boundary status fields (FILE
  STATUS fields and their level-88s, `SQLCODE`/`SQLSTATE`/`EIBRESP`), an
  INVALID KEY handler, and a CALL's ON EXCEPTION / ON OVERFLOW are decided
  by the scenario's status fixture, so a STOP RUN inside them does not
  blank later counts. Without it, the universal `OPEN` + status-check idiom
  would leave no count after the first OPEN. A FILE STATUS field qualifies
  only while the last boundary that set it (`status_sites`) ran on the
  certain path and is not a READ that can reach end of file: after one, the
  field is '10' in every read-to-EOF scenario and at once for empty input.

`is_plain_eof_loop(ast, perform, index)` backs `_CallCounter`'s EOF rule:
the UNTIL tests exactly one field, and the body (followed through PERFORMs
and SORT procedures) has no transfer -- `UNTIL WS-EOF = 'Y' OR WS-CNT >= 3`
or an EXIT PERFORM can stop before end of file.

`InvocationCounts.for_boundary(ref)` matches a `BoundaryRef` by
(paragraph, line) against statements of a boundary type only, so a MOVE in
an AT END handler on the READ's own line cannot blur the READ's count.
`count_at(line, type)` answers for any statement (used for the EOF loop's
`PERFORM UNTIL`). Unreached statements (GO TO-only targets, DECLARATIVES)
have no count. Tests: `tests/unit/analysis/test_invocation_counts.py`,
`tests/unit/test_program_fixtures.py::TestCallCountFollowsControlFlow`.

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
| `invocation_counts.py` | `count_invocations` -- exact per-statement execution counts for `gen-fixtures`' `call_count` |
| `dclgen_check.py` | `DclgenChecker` — DCLGEN `DECLARE TABLE` vs. host-variable types |
| `unused_variables.py` | `UnusedVariableAnalyzer` |
| `recursion_risk.py` | `RecursionRiskAnalyzer` |
| `complexity.py` | `ComplexityAnalyzer` |
| `redundancy.py` | `RedundancyAnalyzer` |
| `technical_debt.py` | `TechnicalDebtAnalyzer` |
| `business_rules.py` | `BusinessRuleExtractor` — decision / validation / calculation rule catalogue |
| `field_lineage.py` | `FieldFlowAnalyzer` — per-program field-level value flows, ports, key uses |
| `lineage_graph.py` | `LineageGraph` — cross-program field lineage joins and impact queries |
| `lineage_jcl.py` | `bindings_from_jobs` / `load_jobs` — DD bindings from jcl-parser jobs |
| `_sql_flow.py` | `analyze_sql` — embedded SQL host variable <-> column flows |

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

# Folded-reference normalization: `_names.base_data_name` (2026-08-24)

Statement parsers fold `OF`/`IN` qualifier chains and `( subscript )`
groups into single operand strings. `analysis/_names.py::base_data_name`
recovers the referenced item's own name (first word, split off only when
followed by OF/IN or `(` — literals with spaces and `ALL 'X'` pass through
unchanged). Used by `MoveTypeChecker._resolve_category` (catalog lookup)
and `DynamicCallAnalyzer`'s MOVE source/target keying (a bare `CALL
WS-PROG` must find values MOVEd to `WS-PROG OF GRP-1`). Any new analyzer
keying data items by bare name needs it too. Pinned by
`tests/regression/test_folded_reference_analyzers.py`.

# Lint: program units and finding origins (2026-09-07)

Two changes to `LintAnalyzer`, both about a report that was quietly narrower
than it looked.

**Every program unit is linted, not just the outermost.** A source file can
hold several `PROGRAM-ID`s (stacked, or nested inside the enclosing program's
PROCEDURE DIVISION); the parse returns the outermost with the rest on
`CobolProgram.contained_programs`. Every rule here is program-scoped, so
running them on the outer program alone left a contained program *entirely
unexamined* while the report read as clean. `analyze()` now iterates
`ast.program_units()` and merges: `_analyze_unit` runs the rule set over one
unit into a shared `LintReport`, `rules_run` and `failed_rules` carry one
entry per rule however many units it ran on (the reader needs to know the
concern went unexamined, not the arithmetic), caveats are deduplicated, and
the sort + dedup happen once at the end. A caller-supplied `flow_report`
describes the outermost unit only; the others build their own. Passing a
contained unit directly still lints just that unit, which is what the CLI's
`--program` does.

**A finding now says where it really is.** `LintFinding` gained
`origin_file` / `origin_line`, serialized as `"origin": {"file", "line"}` and
emitted only when BOTH are known (a half-filled `{"file": null, "line": 12}`
would read as an answer to a consumer checking for the key). `apply_source_map(report, source_map)` fills them
from `ParseResult.expansion_source_map` (see
[preprocessing.md](preprocessing.md)): analyzer locations count lines in the
copybook-*expanded* text, so a finding after an expanded `COPY` is nowhere
near that line on disk and one *inside* an inlined member is not in that file
at all. A `None` map (nothing expanded) and a line the map does not cover both
leave the finding untouched rather than claiming a line nobody vouched for.
The `lint` CLI applies it whenever `--copybook-path` was given, and its `text`
format prints the origin's own `file:line:column:` prefix so the output stays
clickable after expansion. Pinned by
`tests/regression/test_expansion_source_map_and_comments.py::TestApplySourceMap`
and `tests/regression/test_nested_program_units.py`.
`stamp_report_origins(report_dict, source_map)` (2026-09-27) is its twin for
a serialized analyzer report: every `"location": {"line": N}` mapping gains a
sibling `"origin"`; xref's `"definition"` gains `"definition_origin"` and
program-flow's `"exit_statement_location"` gains `"exit_statement_origin"`
(`_ORIGIN_KEYS`, #367). Used by `scan_one` and every analyzer CLI's
`_emit_report`.

**And at which column (#301, 2026-10-13).** `LintFinding.origin_column`,
serialized as `origin.column` only when known, is the column an editor
shows. `apply_source_map(report, source_map, column_offset)` takes a
`(file, line) -> int | None` and adds its answer to `location.column`;
`fixed_format_column_offset()` holds the per-layout table (7 for a
fixed-format line, whose columns 1-7 never reach the analyzers; 0 for a
free-form member in a fixed listing; 6 for a fixed-format member in a
free-form listing). `LintFinding.column_known` (not serialized) is False for
a parse error that gave only a line; such a finding gets no `origin_column`.
`stamp_report_origins` leaves an existing `origin` alone so the CLI's dict
pass does not erase it. Detail in [cli.md](cli.md).


# Program-type corpus fixes (2026-09-15)

What running every analyzer over `tests/samples/enterprise/` (one program
per IBM Enterprise COBOL program type; `docs/enterprise-program-types.md`)
changed. Each was a false positive on a *kind* of program, not on one
program.

* **DECLARATIVES** (`DECLARE`, `RPTWRTR`): `DeadCodeAnalyzer` and
  `ProgramFlowAnalyzer` take the first procedure that is *not* in a
  declarative section as the entry point (control enters after `END
  DECLARATIVES`), mark every declarative section and paragraph referenced
  (`_collect_declaratives`), and the flow analyzer registers each
  declarative *section* as an entry point after the real one
  (`FlowNode.is_declarative`, serialized when True) so it is never
  "unreachable". `IOSequenceAnalyzer._collect_procedures` skips
  declarative sections entirely: a USE procedure is not on the
  fall-through path and cannot be PERFORMed, so walking it inline reported
  its WRITE against a file state it never runs in.
* **Runtime-invoked handlers** (`XMLJSON`, `CICSONLN`, `CICSLINK`): `XML
  PARSE ... PROCESSING PROCEDURE p [THRU q]` is a reference in
  `DeadCodeAnalyzer._collect_xml_refs` and a PERFORM-shaped edge
  (`FlowEdgeType.XML_PROCESSING_PROCEDURE[_THRU]`,
  `EdgeCollector.process_xml_parse`); `EXEC CICS HANDLE AID|CONDITION|
  ABEND option(paragraph)` is a GO TO-shaped reference
  (`_collect_cics_handle_refs`, `FlowEdgeType.CICS_HANDLE`,
  `process_cics_handle` -- only option values naming a known procedure).
  Both joined `INTERNAL_EDGE_TYPES` and the PERFORM/GOTO sets the cycle
  classifier, complexity and the flowcharts read
  (`flowchart.py`'s label/verbose/perform/goto tables).
* **CICS translator items** (`CICSONLN`, `CICSLINK`): `LinkageChecker`
  marks `DFHEIBLK` and `DFHCOMMAREA` referenced unconditionally
  (`_CICS_TRANSLATOR_ITEMS` -- the translator passes them on the USING it
  generates), plus the `RETURNING` item, every `SET ADDRESS OF x TO p`
  target (`SetStatement.targets_are_address_of`) and any CICS option of
  the form `SET(ADDRESS OF x)` (`_ADDRESS_OF_RE`).
  `UnusedVariableAnalyzer` marks the `DFHEIBLK` subtree used and the
  `DFHCOMMAREA` 01 used (its fields stay assessed) -- the translator
  declares all 30-odd EIB fields and buried the real findings of every
  CICS program.
* **EXEC DLI** (`EXECDLI`): `IMSSegmentAnalyzer._build_exec_dli_calls`
  produces one `IMSDLICall` per `ExecImsStatement` (interface `"EXEC
  DLI"`, `function_code` = command word, `pcb_name` `"PCB(n)"`,
  `io_area_name` from `INTO`/`FROM`, `segment_names` from every
  `SEGMENT(...)`), merged with the `CBLTDLI` calls in source order.
* **IS RECURSIVE** (`SUBPROG`): `RecursionRiskAnalyzer._call_recursion_risks`
  grades a self-CALL `LOW` when `ast.is_recursive`; `lint`'s
  `_SEVERITY_RECURSION` maps `LOW` to `info`.
* **DCLGEN in WORKING-STORAGE** (`DB2BATCH`): `DeclareTableStatement`
  now extracts a qualified `SCHEMA.TABLE` name, so `HostVariableResolver`
  and `DclgenChecker` finally see the DECLARE TABLE block every DCLGEN
  member emits.

`tests/integration/test_enterprise_program_types.py` pins each of these
through the corpus program that exposed it.


## XrefAnalyzer (`xref.py`)

> 2026-09-28: two role fixes. (1) `RELEASE rec FROM x` (record and `x`
> read) and `RETURN sd-file INTO x` (file-operation on the SD, `x` write)
> have dedicated role mappings; before, `FROM`/`INTO` never reached
> `.operands` (the model setters now add them, like READ INTO / WRITE
> FROM), so `x` had no reference at all and `UnusedVariableAnalyzer`
> reported it unused. (2) A reference modifier's offset/length names are
> kept apart from the operand (`_split_operand`) and recorded `read` when
> the operand itself is a `write`: `MOVE A TO WS-B (WS-P:2)` no longer
> lists WS-P as written. `_partition_operand` still folds them into the
> base names for its other callers.

The classic mainframe compiler cross-reference: for every symbol a program
declares — data items, level-88 condition names, files, paragraphs and
sections — where it is *defined* and every place it is *referenced*, each
reference carrying its location, the statement it sits in, the enclosing
paragraph, and the **role** it plays there.

**Arithmetic roles (2026-09-27).** With GIVING, only the GIVING/REMAINDER
items are `write`; the TO/FROM operand is `read` (`SUBTRACT A FROM B GIVING
C` used to record B as written). Without GIVING, the TO/FROM/BY/INTO target
is both `read` and `write` (`ADD 1 TO X` used to be `write` only). Sending
operands come from `ArithmeticStatement.source_operands` (ADD/SUBTRACT) or
the first two operands (MULTIPLY/DIVIDE), so `ADD A B GIVING B` keeps B's
read. `program_signature.py` grades LINKAGE directions from these roles:
an accumulated parameter is now `input-output` (was `output`) and a
`SUBTRACT ... FROM LK-B GIVING` operand `input` (was `output`). Pinned by
`test_xref.py::test_giving_leaves_the_from_operand_unwritten` and friends and
`test_program_signature.py::test_accumulated_and_giving_operands_get_the_right_direction`.

**Counter / pointer / in-place roles (issue #269).** Operands a statement
advances or rewrites from their current value are both `read` and `write`:
an INSPECT TALLYING counter, STRING / UNSTRING `WITH POINTER`, UNSTRING
`TALLYING IN`, and the inspected item of INSPECT REPLACING / CONVERTING /
TALLYING ... REPLACING (the item of a plain INSPECT TALLYING stays `read`;
UNSTRING `COUNT IN` / `DELIMITER IN` stay `write`). They were `write` only,
so `program-signature` graded such a LINKAGE parameter `output` instead of
`input-output`; `business-rules` now lists them as inputs and outputs.
Pinned by `test_xref.py::test_counters_pointers_and_inspect_targets_are_read_write`
and `test_program_signature.py::TestDirection::test_counters_pointers_and_inspected_items_are_input_output`.

This is the natural completion of `unused_variables.py`. That analyzer answers
"is this name referenced at all?" with a flat `set[str]`; this one keeps the
locations and roles that set throws away, so "unused" becomes "fully
cross-referenced". Its reference-collection machinery is *reused*, not
re-derived: `_extract_identifiers`, `_walk_expression_operands`,
`_names_from_value`, `collect_declared_items` and the `_STR_ATTR_EXTRAS` /
`_STR_LIST_EXTRAS` / `_DICT_LIST_EXTRAS` tables all come from there.

```python
from cobolparser.analysis.xref import XrefAnalyzer

report = XrefAnalyzer().analyze(ast)          # XrefReport
report.entries                # list[XrefEntry], data items first (_KIND_ORDER)
report.entry_for("WS-COUNT")  # XrefEntry | None, case-insensitive
report.entries_of_kind("paragraph")
report.total_references
report.undefined              # referenced, never declared
report.caveats                # what could only be recovered approximately
report.duplicate_declarations # declared more than once in one namespace
```

`XrefEntry`: `name`, `kind`, `definition` (`SourceLocation | None`),
`references`, `level`, `section`, plus `reference_count` / `is_referenced`.
`XrefReference`: `location`, `role`, `statement`, `context` (the enclosing
paragraph).

**Kinds** (`KIND_*`): `data-item`, `condition-name`, `paragraph`, `section`,
`file`.

**Roles** (`ROLE_*`): `write`, `read`, `condition`, `subscript`, `perform`,
`goto`, `call-argument`, `host-variable`, `file-operation`, and `reference`
when the role itself could not be determined.

Things worth knowing before trusting a field:

* **Single-program scope**, like `DeadCodeAnalyzer` and
  `UnusedVariableAnalyzer`: only *ast* itself. Contained programs are AST
  children and are skipped in every sweep (`_contained_node_ids`) — otherwise
  a nested program's statements would read as the outer unit's references.
  Call `analyze()` separately per unit.
* **Digit-led paragraph names resolve.** Procedure names (PERFORM / GO TO
  targets) are credited verbatim and `_COBOL_WORD_RE` allows a leading digit
  provided there is at least one letter, so `1000-INIT` is one symbol rather
  than a number and a word.
* **`undefined` excludes special registers.** `_SPECIAL_REGISTERS`
  (RETURN-CODE, SQLCODE, SQLCA, `EIB*`, `DFH*`, `XML-*`/`JSON-*`, TALLY, …)
  are never reported undefined; a caveat names the ones that were seen.
* **STRING operands are inexact** — the parser strips literal quotes, so a
  literal word and a data name are indistinguishable there. Reported, with a
  caveat.
* **`duplicate_declarations` is a correctness warning for consumers.** Every
  reference is attributed to the *first* declaration, so nothing downstream may
  grade *which* declaration was touched. A copybook COPYed into both
  WORKING-STORAGE and LINKAGE is the common shape.
* Nothing is guessed: where a role, location or identifier was only
  approximately recoverable the reference is still reported (role
  `"reference"`) and the approximation is appended to `caveats`.

Backs the `xref` CLI subcommand, which additionally appends the parser's
unexpanded-COPY warnings to `caveats` — a member the parser could not expand
leaves every field it declares looking undeclared. Tests: `tests/unit/analysis/test_xref.py`.


## ProgramSignatureExtractor (`program_signature.py`)

Every other program-scoped analyzer here answers a question about the program
it is given. This one answers a question about the program *someone else* is
calling: given `CALL "SUBPGM" USING ...`, what does SUBPGM actually expect —
how many operands, in what order, of what shape, and which of them it writes
back.

That is why `LinkageChecker` cannot cover it: that analyzer correlates CALL
statements against ENTRY statements *in the same source unit*, and on a real
mainframe a caller and its callee almost never share a file. The answer has to
be extracted from the callee and carried across, which is what this module
produces — a small, serializable, source-file-independent description.

Built from three sources that must agree and often do not:

1. `PROCEDURE DIVISION USING` — the primary (implicit) entry point, read from
   the division's `using_parameters` metadata (same place `LinkageChecker`
   reads).
2. `ENTRY "NAME" USING` statements — alternate entry points, each with its own
   operand list.
3. The LINKAGE SECTION — where those operands are declared, and therefore the
   only place a parameter's *shape* lives (PICTURE, USAGE, byte length, group).

```python
from cobolparser.analysis.program_signature import (
    ProgramSignatureExtractor, extract_signatures,
)

sig = ProgramSignatureExtractor().analyze(ast)      # ProgramSignature
sigs = extract_signatures(ast)                      # one per program_units()

sig.primary                     # the PROCEDURE DIVISION entry — what CALL "PROG"
                                # hits; None when it has no USING clause
sig.entry("ALTENTRY")           # look one up, case-insensitively
sig.entry_points[0].call_example()   # 'CALL "SUBPGM" USING WS-A, WS-B RETURNING WS-RC'
sig.entry_points[0].returning        # PROCEDURE DIVISION ... RETURNING operand
sig.undeclared_parameters       # named by USING, absent from LINKAGE
sig.unreferenced_linkage        # LINKAGE 01-items no USING clause names
sig.unchecked                   # what could not be determined exactly
```

`SignatureParameter` carries `name`, `position`, `declared`, `level`,
`picture`, `usage`, `byte_length`, `is_group`, `occurs`, `direction`,
`by_clause`, `location`, and a `declaration()` rendering the operand as a
caller would have to write it (a group item is described by level and length
rather than a fabricated picture). `EntryPoint.kind` is `"procedure-division"`
or `"entry-statement"`. `by_clause` is the callee's declared passing mode
(`"REFERENCE"` / `"VALUE"`, from the division's `using_parameter_modes`
metadata) on the primary entry, `None` on an ENTRY statement's operands;
`call_example()` writes a `BY VALUE` / `BY REFERENCE` phrase only where the
mode changes (`CALL "E1" USING LK-A, BY VALUE LK-B RETURNING LK-R`). The
RETURNING item counts as named, so it is never `unreferenced_linkage`.

**Direction is graded, never guessed.** It comes from how the PROCEDURE
DIVISION uses each parameter, reusing xref's role vocabulary:

* `write` plus any read → `input-output`.
* A reference as a BY REFERENCE CALL argument or SQL host variable
  (`_AMBIGUOUS_ROLES`), with no write elsewhere → `unknown`, and listed in
  `unchecked`. A `BY CONTENT` / `BY VALUE` CALL argument is not ambiguous:
  the callee gets a copy, so xref records it `read` (2026-09-28; it used to
  be `call-argument`, which graded a parameter only passed on BY CONTENT
  `unknown`). A caller told "input-only" about a
  field the callee overwrites has been told something worse than nothing.
  xref files `ENTRY "X" USING p` itself under the CALL-argument role
  (`statement == "EntryStatement"`); those refs are dropped before grading,
  since naming an entry's own parameter neither reads nor writes it.
* A group whose fields xref reports as duplicated → `unknown`, rather than
  inferred from a same-named WORKING-STORAGE field.

Operand *order* is preserved verbatim from the USING clause and is sorted
nowhere in the module — it is the whole point of `call_example()`.

A parameter named in (1)/(2) but absent from (3) is `undeclared_parameters`
(a caller passing one is passing into nothing); a LINKAGE 01-item named by
neither is `unreferenced_linkage` (not an error on its own — `SET ADDRESS OF`
is legitimate — but the other half of the mismatch picture). ENTRY statements
belonging to *contained* programs are not the outer unit's.

The `program-signature` CLI subcommand reports **every** unit in the file by
default rather than the outermost: a caller may target a contained program as
readily as the outer one, and reporting only the outermost would hide the other
entry points from exactly the consumer that needs them. `--program` still
narrows. Tests: `tests/unit/analysis/test_program_signature.py`.


## CodebaseGraphBuilder / CopybookImpactAnalyzer (`codebase.py`)

The cross-program module. It walks a whole tree of COBOL source, parses every
file through `batch.py` (parallel, per-file fault isolation) and aggregates the
results into one graph with two kinds of edge:

* **Call edges** — `program A calls program B`, from static `CALL "B"` and from
  dynamic `CALL WS-TARGET` resolved through `DynamicCallAnalyzer`. A dynamic
  call whose value set that analyzer could not fully resolve still contributes
  its known targets, each marked `resolved=False`, so the edge set is never
  mistaken for an exhaustive one. `EXEC CICS LINK PROGRAM(...)` and `EXEC
  CICS XCTL PROGRAM(...)` are call edges too (#315), told apart by
  `CallEdge.kind` (`call` / `cics-link` / `cics-xctl`; `to_dict()` carries
  it). `PROGRAM('X')` is static (read off `ExecCicsStatement.literal_options`,
  since `options` holds literals unquoted); `PROGRAM(WS-X)` takes
  `DynamicCallAnalyzer.resolve_variable("WS-X")`, the same values and
  incomplete flag `CALL WS-X` would get, or is reported in `unresolved`.
  `cycles()` skips XCTL edges: XCTL never returns, so a menu loop of XCTLs is
  not recursion; LINK cycles count. Chosen over a separate `transfer_edges`
  list so `callers_of` and impact questions see CICS callers with no change.
* **Copy edges** — `program A copies member X`, and `member X copies member Y`
  for nested copybooks. Collected by **re-scanning** each source with
  `extract_copy_statements()` rather than from an expanded parse, because
  expansion *consumes* the COPY statement and discards exactly the edge we are
  after. Members resolve to real files through the same `PathResolver` the
  expander uses, so a nested chain is followed to its leaves and a circular pair
  (`A COPY B`, `B COPY A`) is reported, not looped on.
  A DB2 `EXEC SQL INCLUDE X END-EXEC` is a copy edge too (the scan passes
  `sql_include=True`), with the same `COPY` label and the same unresolved-member
  reporting as a COPY -- it is how SQLCA and DCLGEN members are normally pulled
  in, and `copybook-impact` on a DCLGEN returned nothing without it (#295).
  Nothing in the JSON/DOT/Mermaid output tells a COPY edge from an INCLUDE
  edge. An INCLUDE of `SQLCA` / `SQLDA` (`_PRECOMPILER_MEMBERS`) that is not on
  the path keeps its edge but adds no `unresolved` note. That is narrower than
  the expander, which skips *every* unresolvable INCLUDE silently: here a COPY
  of either, or an INCLUDE of any other missing member (a DCLGEN), is still
  reported -- once per member and referrer, even when one file both COPYs and
  INCLUDEs it.

```python
from cobolparser.analysis.codebase import CodebaseGraphBuilder, CopybookImpactAnalyzer

builder = CodebaseGraphBuilder(copybook_paths=["./copybooks"])
graph = builder.build_from_directory("./src", extensions=(".cbl", "cob"))
graph = builder.build(["a.cbl", "b.cbl"])       # or an explicit file list

graph.program_ids / graph.members
graph.callers_of("VALIDATE") / graph.callees_of("MAIN")
graph.programs_using("CUSTREC", transitive=True)   # through nested COPY chains
graph.cycles()                                     # CALL cycles
graph.to_dict() / graph.to_dot() / graph.to_mermaid()
graph.unresolved / graph.errors

report = CopybookImpactAnalyzer(graph).analyze("CUSTREC")   # ImpactReport
report.direct_programs / report.transitive_programs
report.chains          # the COPY nesting path to each affected program
report.fields          # data items the member contributes, when its file resolved
report.program_count
```

`ProgramNode` holds `program_id` (uppercased; the **file stem** when the file
would not parse, recorded as such in `unresolved`), `path`, `calls`, `copies`
and `parse_failed` — with `parse_failed` true, `calls` is "empty and unknown",
not "empty and known". `CallEdge` carries `is_dynamic` / `resolved` / `kind`; `CopyEdge`
carries `member`, `path` and `nested`, where for a nested edge `program` is the
*outer member name*, which is what makes a `PROG1 -> OUTER -> INNER` chain
walkable in either direction.

Two rules hold throughout:

1. **A quiet report is never a complete one.** A file that would not parse lands
   in `errors` and still contributes its COPY edges (the COPY scan does not need
   a successful parse); a COPY whose member is off the search path, a dynamic
   CALL with no resolvable target, a duplicate `PROGRAM-ID`, a file holding
   several units — each lands in `unresolved` with a reason.
2. **Determinism.** The same tree produces byte-identical `to_dict()`,
   `to_dot()` and `to_mermaid()`. Files are parsed in sorted order, every
   emitted list is sorted, and no `ProcessPoolExecutor` completion order reaches
   the output.

Paths are keyed by `str(Path(p))` — the spelling `BatchResult.path` returns — so
`./X.cbl` matches its parsed units instead of yielding a phantom program.
Extensions are accepted with or without a leading dot (`extensions` is
keyword-only, defaulting to `DEFAULT_PROGRAM_EXTENSIONS`). `_member_paths` /
`_member_copies` reset per build. `build_from_directory` raises
`NotADirectoryError` for a root that is not a directory — a mistyped root must
not read as "a codebase with no programs".

Backs the `codebase-graph` and `copybook-impact` CLI subcommands. Tests:
`tests/unit/analysis/test_codebase.py`.

**Not yet joined to JCL.** The graph has `ProgramNode` / `CallEdge` / `CopyEdge`
and no job, step or dataset node, while `cobolparser/jcl/` already resolves
DD → dataset and step → program. So "which dataset does this program's INVFILE
resolve to" is answerable and "which job populates the dataset this program
reads" is not. See [jcl.md](jcl.md).


## SqlCicsAnalyzer (`sql_cics_lint.py`)

A COBOL program that talks to DB2 and CICS carries two failure surfaces the
COBOL compiler says nothing about, because neither `EXEC SQL` nor `EXEC CICS`
is COBOL: the precompiler rewrites the block and moves on. Whether the program
then looked at what came back is nobody's job to check. This module makes it
somebody's job.

```python
from cobolparser.analysis.sql_cics_lint import SqlCicsAnalyzer

report = SqlCicsAnalyzer().analyze(ast)      # SqlCicsReport
report.violations                 # source-ordered SqlCicsViolation list
report.worst_severity()           # "error" | "warning" | "info" | None
report.violations_of_kind(KIND_NO_SQLCODE_CHECK)
report.unchecked                  # what this run could not check, and why
report.sql_statements / report.cics_statements
```

| Kind | Why it is a defect, not a style note |
|------|--------------------------------------|
| `SQL_NO_SQLCODE_CHECK` | An executable `EXEC SQL` whose outcome is never looked at: no `SQLCODE`/`SQLSTATE`/`SQLCA` mention in the statements that follow, no `WHENEVER SQLERROR` in effect. DB2 does not raise — it sets a number and returns, and the program commits whatever it was going to commit. The most common real defect in DB2 COBOL and the cheapest to find. |
| `SQL_DYNAMIC_CONCATENATION` | A host variable handed to `PREPARE` / `EXECUTE IMMEDIATE` whose content was assembled by `STRING` or moved in from another item — SQL injection with a mainframe accent. Parameter markers (`EXECUTE ... USING :HV`) are the fix and are never flagged. Writers are counted program-wide, except that a `MOVE` written directly in the PREPARE's paragraph, before it, that overwrites the whole item (no reference modification, not `CORRESPONDING`) cuts off everything before it: then only that MOVE, the writers between it and the PREPARE (conditional ones and those in PERFORMed paragraphs included) and, inside an inline `PERFORM` loop, the loop's later writers count (#395). A `STRING` never cuts the trace — it leaves bytes past what it transfers as they were. |
| `SQL_HARDCODED_CREDENTIALS` | A literal user id or password in `EXEC SQL CONNECT`. It is in the source, the listing, the load library, and every copy anyone took of any of them. |
| `SQL_SELECT_WITHOUT_INTO` | A singleton `SELECT` with no `INTO` and no cursor. The precompiler accepts it; the row goes nowhere. (`into_variables` is populated from parsed source since 2026-09-28; the `INTO\s*:` text check stays as a backstop.) |
| `CICS_NO_RESP_HANDLING` | An `EXEC CICS` command with no `RESP`/`RESP2`, no `NOHANDLE`, no `HANDLE CONDITION` in effect. The default action for most CICS conditions is to abend the task, so the failure mode is a dropped transaction mid-update, not a wrong answer. `IGNORE CONDITION` ("take no action": nothing abends, execution continues) counts as handling, the same as a `HANDLE CONDITION` label; only `ERROR` covers every condition, a narrower set goes to `unchecked`. A bare `HANDLE CONDITION X` restores the abend (#396). |
| `CICS_ABEND_WITHOUT_HANDLER` | `EXEC CICS ABEND` with no `HANDLE ABEND`. **Info** — frequently deliberate, worth seeing rather than worth fixing. |

`SqlCicsViolation` carries `kind`, `severity` (always `SEVERITY_BY_KIND[kind]`),
`message`, `location`, `symbol` (the SQL statement type, the CICS command verb,
or for a dynamic-SQL finding the untrusted host variable) and a machine-readable
`detail` dict — the traced assignment, the option keyword, the active handler.

**It does not guess.** Three things in the parsed form of an EXEC block are
lossy, and each is answered with an entry in `unchecked` rather than a finding —
e.g. a CONNECT operand with neither colon nor quotes that matches a declared
DATA DIVISION item. (Since 2026-09-28 EXEC SQL text keeps a literal's quotes,
so `USING 'S3CRET'` is always a literal and `USING 'WS-KEY'` is no longer
mistaken for the data item WS-KEY; before that the two reduced to the same
tokens.) A quiet report
with a populated `unchecked` is not a clean program, it is an unexamined one.

The search for a status check after an `EXEC SQL` stops at the next
executable `EXEC SQL` written directly in a paragraph (also inside a
PERFORMed one): it resets the SQLCA, so `DELETE` / `COMMIT` / `IF SQLCODE`
reports the DELETE (2026-09-28; before, the one check was credited to both).
SQL inside an IF/EVALUATE body may not run and does not end the search;
neither does a declaration or `WHENEVER`.

`DECLARE GLOBAL TEMPORARY TABLE` is executable and is graded;
DECLARE CURSOR / TABLE / STATEMENT / VARIABLE are not
(`_NON_EXECUTABLE_SQL_TYPES`). A `DECLARE TABLE` or `INCLUDE` in the DATA
DIVISION is not counted in `sql_statements`.

The lint rule id is `sql-cics-check` — the subcommand's own name, per the lint
convention. Tests: `tests/unit/analysis/test_sql_cics_lint.py`.

**Known gaps** (found in the PR review, not yet fixed): a VARCHAR host structure
written through its subordinate `49` item is not traced to `PREPARE ... FROM
:hv`; SQLCODE checked in a `PERFORM UNTIL` guard, or in the calling paragraph
rather than after the statement, is not seen.


## BusinessRuleExtractor (`business_rules.py`, 2026-09-30)

Answers "what are the rules in this program?" -- the question a
modernization or documentation engagement asks first -- as a catalogue of
`BusinessRule`s. Backs `cobol-parser business-rules` ([cli.md](cli.md)).
Feature idea #21 in `docs/feature-ideas.md`.

```python
from cobolparser import BusinessRuleExtractor

report = BusinessRuleExtractor().analyze(ast)      # include_technical=False
report.rules                 # list[BusinessRule], BR-001.. in source order
report.rules[0].branches     # list[RuleBranch]: label, condition, actions
report.condition_names       # level-88 glossary: POL-AUTO -> POL-TYPE = 'A'
report.data_lineage          # {item: {"read_by": [...], "written_by": [...]}}
report.technical_rules_excluded
print(report.to_text())      # IF/THEN/ELSE-shaped catalogue
```

**Rule kinds.** Every IF / EVALUATE / SEARCH is a `decision`, shaped as a
decision table: one `RuleBranch` per arm (THEN, ELSE, each WHEN, WHEN OTHER,
SEARCH AT END) with the condition selecting that arm and its actions. It is
promoted to `validation` when an arm signals rejection (moves or DISPLAYs an
error-like literal, writes/SETs an item whose name has an ERR / ERROR /
INVALID / REJECT / ABEND word, PERFORMs or GOes TO such a procedure, CALLs
CEE3ABD / ILBOABN0) or the condition is a class test. COMPUTE / ADD /
SUBTRACT / MULTIPLY / DIVIDE at paragraph level (not inside an arm) is a
`calculation` with `formula` normalized to `target = expression` (`DIVIDE A
INTO B GIVING C` -> `C = B / A`); inside an arm it is an action of that
decision only, never counted twice. Counters (`ADD 1 TO X`, `COMPUTE X = X +
1`) are not rules at all.

**Stacked WHENs (#314).** `WHEN 'A' WHEN 'B' stmt` is one arm whose
condition is `WS-T = 'A' OR WS-T = 'B'` (via `EvaluateStatement.when_groups()`);
the same grouping numbers program-flow `BranchArm`s (one `WHEN_n` arm, label
`WHEN A / WHEN B`) and constraint arms, where each phrase of a stack is an
OR-split disjunct of that arm (`WHEN_1#1`, `WHEN_1#2`) and later arms /
WHEN OTHER negate every phrase.

**Technical vs business.** A decision whose *own* condition reads only
technical items, or a calculation that writes only technical items, is
`technical` and excluded by default (counted in `technical_rules_excluded`;
`include_technical=True` keeps it). Technical items are found from the
program, not only from names: every SELECT `FILE STATUS` item; everything a
READ / RETURN `AT END` clause writes (the EOF flag, whatever it is called);
the level-88s of those items and the items of those 88s; the xref special
registers (SQLCODE, SQLSTATE, EIB*, RETURN-CODE, ...); plus a narrow name
pattern (`EOF`, `EOJ`, `FS`, `END-OF-FILE`, `FILE-STAT`, `EIB*`, `DFH*`). A
SEARCH is never technical (it is a table lookup). CICS `RESP` fields compared
to `DFHRESP(...)` are deliberately *not* technical: "NOTFND -> CUSTOMER NOT
FOUND" is a business rule.

**Context on every rule.** `guards` are the conditions of the arms the rule
is nested in, within its paragraph (ELSE contributes `NOT (cond)`, WHEN
OTHER the conjunction of the negated WHENs, an exception clause `AT END
(READ ...)` / `ON SIZE ERROR (COMPUTE ...)`). `reached_via` links across
paragraphs: every arm elsewhere that PERFORMs or GOes TO the rule's paragraph
or section, as `"BR-001 ELSE"` / `"BR-004 WHEN POL-TYPE = 'A'"`. A nested
decision is its own rule; the parent arm lists it as an action whose
`rule_id` points at it (dropped to `None` if the nested rule was excluded as
technical, never left dangling). `in_dead_code` comes from
`DeadCodeAnalyzer`.

**Inputs / outputs** reuse `XrefAnalyzer`'s per-statement role mapping
(`_role_assignments` / `_names_for` / `_residual_names`), filtered to
declared names (+ INDEXED BY names, + data-bearing special registers; not
`DFHRESP` / `LENGTH` / `ADDRESS`). A decision's are its condition plus its
*direct* actions (a nested rule's reads/writes are its own). Testing or
SETting a condition name also counts its item.

**Rendering notes.** Conditions come from `program_flow/condition_text.py`
then `_tidy()` (`T-K ( IX )` -> `T-K(IX)`, `NOT =` reads `<>`). EVALUATE
selector literals arrive **unquoted** from the parser, so a non-identifier,
non-numeric, non-figurative selector is re-quoted -- except the space-joined
call shape `DFHRESP ( NORMAL )`, which is an expression. A negated range
selector (`WHEN NOT 0 THRU 17`, a `Condition` dict with `negated` plus
`start`/`end`) reads `NOT (AGE >= 0 AND AGE <= 17)` from those bounds, not
from its raw `THRU` text; only a single negated value reads `AGE <> 6`
(#260). Level-88 values are
also stored unquoted with `THRU` as `"THROUGH:end"`; `_condition_values`
quotes them unless the item's PICTURE / USAGE is numeric. STRING sources
arrive quoted (#330), so they are rendered as is. Actions are
rendered in full here rather than via `program_flow/statement_text.py`
(flowchart summaries, truncated to 48 chars).

**Why not `constraints.py`** (as idea #21 proposed): `ConstraintExtractor`
only models conditions on fields that trace to a mocked boundary (it takes a
`ProgramLayoutIndex` and a `BoundaryReport`), so a rule on a computed
WORKING-STORAGE field -- most rating/pricing logic -- would be missing.

**Known limits** (the always-present caveat says the kinds are heuristic;
`classification` on each rule names the signal that decided it):
single-program scope (like `xref`, contained programs are not walked --
`--program` picks one); `reached_via` matches a PERFORM's first target only,
not every paragraph of a `THRU` range; an arithmetic statement inside an
inline PERFORM *within an arm* is neither a rule nor an action of that arm.

Tests: `tests/unit/analysis/test_business_rules.py`,
`tests/unit/cli/test_business_rules_cli.py`.


## Field lineage (`field_lineage.py`, `lineage_graph.py`, `lineage_jcl.py`, `_sql_flow.py`, 2026-10-08)

Answers "if I change this field, what else changes?" at field granularity,
across programs. Design: `docs/plans/2026-10-08-field-lineage-design.md`.
Backs `cobol-parser lineage` and `cobol-parser field-impact`
([cli.md](cli.md)), and `scan --analyzer lineage` ([batch.md](batch.md)).

**Layer 1 -- one program (`FieldFlowAnalyzer`).** A may-flow,
flow-insensitive value graph. Nodes are data items (qualified name, with
the record-relative byte offset/length `layout_offsets` computes) and
*ports*, where a value enters or leaves the program:

| Port kind | Key | From |
|-----------|-----|------|
| `file` | DD name (`normalize_ddname`: `UT-S-` / `S-` prefixes stripped, the backend's rule) | READ / WRITE / REWRITE / RELEASE / RETURN / SORT-MERGE USING-GIVING, one byte range per record field |
| `call` | `CALLEE#n`, `CALLEE#RETURNING` | CALL USING (BY REFERENCE goes both ways); a dynamic CALL fans out over `DynamicCallAnalyzer`'s candidates (run inside `analyze`; SPACES / LOW-VALUES / HIGH-VALUES / ZERO candidates are the "no program" sentinel and are dropped by `_names.callee_names`), else `?IDENT#n` plus a caveat |
| `linkage` | `PROGRAM#n` / `ENTRY#n`, `PROGRAM#RETURNING` (out only) | PROCEDURE DIVISION USING / RETURNING, via `ProgramSignatureExtractor` |
| `sql` | `[SCHEMA.]TABLE.COLUMN` | `_sql_flow.analyze_sql` (SELECT INTO, FETCH through its DECLARE CURSOR, INSERT, UPDATE SET; MERGE/CTE are caveats) |
| `console` | `SYSIN` / `SYSOUT` (or the ACCEPT's `FROM` source) | ACCEPT / DISPLAY; `ACCEPT FROM DATE` / `DAY` / `DAY-OF-WEEK` / `TIME` (with or without a format qualifier) make no port -- the runtime's clock, not data entering the program |

Edge kinds: `move` (group MOVE is a byte overlay; CORRESPONDING pairs by
name; literal reference modification narrows the range), `arith`,
`string`, `init`, `set`, `aggregate` / `sql-expr` (SQL `SUM(...)` /
expressions), `read`, `write`, `redefines` (two-way, including several 01
records under one FD), `occurrence` (two-way, inexact: a literal-subscript
occurrence node and its table field), `call`, `linkage`, `sql`, `accept`,
`display`, `xml`. `LINEAGE_VERSION` is `"2"` (2026-10-08: occurrence nodes,
`#RETURNING` linkage ports, `#n` item keys). `VALUE_CHANGING_KINDS` (`arith`, `string`, `aggregate`, `sql-expr`)
make a flow *derived*. Each edge carries `line`, `paragraph`, `guarded`
(inside IF/EVALUATE/SEARCH) and `exact` (byte ranges coincide).
`apply_source_map` stamps `origin` on every edge after copybook expansion
-- edges carry a bare `line`, so `lint.stamp_report_origins` does not
reach them. `summary` is every input-port field -> output-port field the
program connects; `key_uses` are items used as READ/START/RECORD KEY or in
a SQL `WHERE col = :hv`.

**Operands** (`_refs`) go through one path for MOVE, arithmetic, STRING,
CALL arguments, DISPLAY/ACCEPT, READ INTO / WRITE FROM: xref's
`_split_operand`, keeping only the base names minus `_qualifier_names`, so
a subscript, a reference-modifier offset/length or an `OF` qualifier is
never a value source (`COMPUTE X = Y(I)` does not flow `I` into `X`;
`LENGTH OF X` / `ADDRESS OF X` flow nothing). A literal reference modifier
narrows the byte range; literal subscripts are kept (`_constant_subscripts`).

**OCCURS tables.** A table field's node (`T.E`) stands for *any*
occurrence. Its bytes are every occurrence's (`_placements`: one range per
occurrence, or a single spanning range past `_PLACEMENT_CAP` = 1024), so a
group MOVE / READ / WRITE / CALL maps each occurrence where it really lies,
and every edge through a table field is **inexact** -- never a wrong exact
field. A reference with literal subscripts (`AMT(3)`, `T(2,1)`, one per
OCCURS level, within bounds) on an elementary field gets its own item node
`R.AMT(3)` at the occurrence's offset, joined both ways to `R.AMT` by
inexact `occurrence` edges, and an exact edge to its own bytes on every port
its record or group reaches (`_PortLink`s, resolved after the walk in
`_link_occurrences`). Nodes order by `LineageNode.sort_key()` (an unknown
offset -- a field after an `OCCURS DEPENDING ON` -- sorts first; such a field
maps to a port with no byte range).

**Item keys** are qualified names, except that the n-th item sharing one
(two `01 FILLER` groups, two same-named subordinates) is keyed `NAME#n`;
`_index_items` splits the layout into record blocks and finds each item's
parent by position (a group follows its children in the layout), so two
FILLER records are two buffers, not one with a spurious redefines.
`MOVE CORRESPONDING` pairs same-path subordinates when at least one of the
two is elementary (a group against an elementary item is a byte overlay),
skipping FILLER, REDEFINES and OCCURS items and what is under them.
`ADD` / `SUBTRACT CORRESPONDING` walk the same pairing
(`_visit_arith_corresponding`) but keep only elementary pairs whose sending
item is numeric and receiving item numeric or numeric-edited (`_Item.category`,
from PICTURE / USAGE), one `arith` edge each; the generic reads-to-writes
path would join every subordinate to every other one (issue #337).

**Alias edges are never chained with one of their own class**
(`overlay_class`; summary BFS and `LineageGraph._trace` both carry the
class of the edge a node was reached over): two `redefines` in a row would
carry one field of a record into every other through an alias covering the
whole record, two `occurrence` edges `T(1)` into `T(3)` through `T`, two
`table-alias` edges `PROD.T.C` into `TEST.T.C` through `T.C`.

**Layer 2 -- across programs (`LineageGraph`).** Takes the reports (objects
or their `to_dict()`, which is what the backend stores) plus
`DatasetBinding`s and `Passthrough`s. Joins: dataset (writer and reader
ports meet on overlapping byte ranges of the same normalized dataset --
GDG `(+1)`/`(0)`/`.GnnnnVnn` fold to the base, `&&TEMP`s are job-scoped);
utility pass-throughs carry ranges both ways to a fixpoint, `SUM FIELDS`
ranges become `aggregate`, a `reformat` stops the flow with a caveat;
datasets nothing in scope writes are seeded from their readers' ranges;
CALL argument *n* meets callee linkage *n* (and `CALLEE#RETURNING` meets
`PROGRAM#RETURNING`); a callee with no report is an
*opaque* pass-through (every argument sent reaches every argument back,
`confidence="opaque"`) unless `_INTERFACE_RE` names it a system interface
(the MQI verbs by name -- not every `MQ*` -- *TDLI, CEE*, DSN*...). DB2:
`SCHEMA.TABLE.COLUMN` and an unqualified `TABLE.COLUMN` join both ways by
`table-alias` edges with `confidence="candidate"`; two schemas never join.
`NULLFILE` / `DUMMY` bindings and pass-throughs are ignored (the DD counts
as unbound). A PROGRAM-ID seen in more than one report keeps the first and
adds a caveat. Queries `impact(field, program, direction,
depth)`, `impact_table` (schema optional), `impact_dataset` run a 0-1 BFS
where *depth* counts entries into a program. `key_relationships()` names
candidate dataset/table key relationships with the program and line as
evidence. Joins iterate ports in sorted order so output is identical on
every run (pinned across `PYTHONHASHSEED`s by hand, 2026-10-08).
`join_edges()` exports every edge the joins added (JSON-shaped); passing
them back as `LineageGraph(reports, join_edges=...)` skips the joins, so
the backend joins once at upload and queries later without the JCL.
Key-relationship labels come from the dataset edges, not the bindings, so
both forms answer the same (pinned in `TestStoredJoinEdges`).
`join_state()` -> `{"edges", "caveats", "unjoined"}` adds the joins' own
caveats (reformat stops, opaque callees; `_join_caveats`) and the unjoined
DDs; `LineageGraph(reports, join_edges=..., join_caveats=...,
unjoined=...)` restores them so the rebuilt graph's `to_dict()` equals the
original's (pinned in `TestStoredJoinState`). Without `join_caveats` only
the opaque-callee caveat is re-derived and `unjoined` is empty. A rebuilt
graph records the edges it loads, so its own `join_edges()` re-exports them.
`ImpactResult.start_found` is False when nothing matched the start.

**Bindings (`lineage_jcl.py`).** `bindings_from_jobs(jobs)` turns
**jcl-parser** `Job`s (duck-typed; imported only in `load_jobs`, through
`importlib`, so cobol-parser keeps no runtime or mypy dependency on it)
into bindings and pass-throughs: DFSORT/ICEMAN/SYNCSORT/ICETOOL (`SORTIN*`
-> `SORTOUT` + `OUTFIL FNAMES`), IEBGENER/ICEGENER, IDCAMS REPRO (operands
in any order, `-` continuations joined), IKJEFT01 `RUN PROGRAM(x)`. A
blank-named DD continues the concatenation of the DD before it (`_named`);
`DD DUMMY` / `DSN=NULLFILE` bind nothing (`_dataset`); `DSN=*.STEP.DD`
referbacks resolve to the earlier step's dataset; quoted literals in
DFSORT/IEBGENER control statements are blanked before keywords are matched
(`INCLUDE COND=(...,C'BUILD')` is not a reformat). A `DFSRRC00` step (the IMS region
controller) binds its DDs to the application program named by the second
`PARM` positional when the region is `DLI` / `DBB` / `BMP` (2026-10-10; they
were bound to `DFSRRC00` itself, so an IMS batch program's files never
joined). `load_jobs(paths, proc_path)` reads a flat PROC
folder (`NAME.prc`) as well as a JCLLIB base -- jcl-parser's own loader
only searches `JCLLIB ORDER=` libraries. `jobs_from_sources(jcl, procs)`
does the same from in-memory text (the backend's stored members). Not built
on `cobolparser/jcl/`.

Tests: `tests/unit/analysis/test_field_lineage.py`, `test_lineage_graph.py`,
`test_lineage_jcl.py`, `test_sql_flow.py`, `tests/unit/cli/test_lineage_cli.py`;
fixtures in `tests/samples/lineage/`.

## ProgramDiffer (`ast_diff.py`)

A line-based `diff` over COBOL answers "what lines moved", which is almost never
the question: COBOL is column-sensitive, so a reformat, a renumbered sequence
area or a re-indented Area B shifts every line without changing anything the
program does. This module answers the other question — *what changed in the
program's behavior* — by comparing two `CobolProgram` ASTs into a flat, sorted
`DiffChange` list.

```python
from cobolparser.analysis.ast_diff import ProgramDiffer

report = ProgramDiffer(rename_threshold=0.8).diff(old_ast, new_ast)
report.changes                  # sorted list[DiffChange]
report.changes_by_category()    # "program" | "file" | "data" | "procedure"
report.counts_by_kind()
report.to_text()                # the +/-/~ summary behind --format text
report.caveats                  # what could not be compared exactly
```

`DiffChange`: `kind`, `category`, `symbol`, `detail`, `old`, `new`,
`old_location`, `new_location`, and a `sign` property (`+` for `*-added`, `-`
for `*-removed`, `~` otherwise).

**What is compared.** Program level (`PROGRAM-ID`, which divisions exist, the
`PROCEDURE DIVISION USING` interface); files (per `SELECT`/`FD` name:
ORGANIZATION, ACCESS MODE, RECORD KEY, ALTERNATE keys, RELATIVE KEY, FILE
STATUS, ASSIGN, OPTIONAL, plus the FD's presence, record size, recording mode
and FD-vs-SD kind); data items keyed by section plus qualified path
(`WORKING-STORAGE:WS-TAB.WS-ENT` — PICTURE/USAGE/level/VALUE/OCCURS/REDEFINES
plus the SIGN / JUSTIFIED / SYNCHRONIZED / BLANK WHEN ZERO / EXTERNAL / GLOBAL
flags and level-88 names and values — an entry with no data-name, which the
parser names `ANONYMOUS-<level>-<line>`, is keyed as a positional `FILLER`
since 2026-09-28, so a line shift no longer reports it removed and re-added);
procedures (added, removed, renamed,
**moved** — reordered without a body change, reported separately so a pure
reshuffle never reads as a rewrite — and body-changed); and statements within
matched paragraphs.

**Matching, in three stages**, each looking only at what the previous left over:

1. **By name**, case-insensitively (`Main-Para` *is* `MAIN-PARA`). Settles the
   overwhelming majority.
2. **By structural similarity.** Each leftover paragraph/section reduces to a
   *fingerprint* — the ordered sequence of statement kinds plus primary
   operands, nested branch bodies flattened in and tagged by branch (`IF/THEN`,
   `EVALUATE/WHEN2`, `READ/AT-END`). Pairs are scored with
   `difflib.SequenceMatcher`, considered best-score-first (ties broken by name,
   so the result never depends on dict or set ordering) and greedily paired at
   or above `rename_threshold` (default 0.8). An identical fingerprint under a
   different name is a **rename**, not an add plus a remove.
3. Whatever is still unmatched is a genuine add or remove.

Two deliberate refusals in stage 2: an **empty body never rename-matches**
(`SequenceMatcher` happily scores two empty sequences 1.0, and two paragraphs
that both contain nothing are evidence of nothing), and a **below-threshold pair
is reported as remove + add, never as a speculative rename** — an add+remove for
a rename is honest and easy to read past, a wrong rename actively misleads. The
near-miss is not discarded: it goes to `caveats` with its score, so a reader can
see the pair was considered and declined.

**Positions are relative order, not line numbers.** Matched procedures from both
sides run through `SequenceMatcher` and only those outside its matching blocks
are reported moved — so inserting one paragraph at the top does not report every
following paragraph as moved, and a pure reformat reports nothing at all.

**Spellings are not changes** (2026-10-14 bug hunt). A PICTURE is compared by
its character positions, repeat factors written out (`_picture_positions`:
`X(2)` = `XX`, `S9(3)V9(2)` = `S999V99`), and a USAGE by its storage format
(`_canonical_usage`, the `_storage.py` synonym sets: `COMP` = `BINARY` =
`COMP-4` = `COMPUTATIONAL`, `COMP-3` = `PACKED-DECIMAL`). `COMP-5` stays
distinct from `COMP` (no truncation to the PICTURE). The change still reports
both strings as coded. A VALUE is still compared as written (`+12` vs `12`,
`'AB'` vs `'AB  '` on `PIC X(4)` read as changes).

Statement comparison has dedicated signatures for MOVE, PERFORM, CALL, GO TO,
IF, EVALUATE, SEARCH, and (review follow-up) OPEN, EXEC SQL, EXEC CICS, COMPUTE,
INSPECT, UNSTRING, ACCEPT and DISPLAY. **Every other statement compares on its
operands, its rendered text *and* its own `to_dict()` fields** (locations and
nested statement bodies stripped — those are compared on their own), so an
unmodelled edit over-reports rather than reading as unchanged. (2026-09-28:
the rendered text is a truncated summary that omits STRING's INTO, READ's
INTO/KEY, WRITE's FROM, ...; before the `to_dict()` fields were added,
`STRING ... INTO A` → `INTO B` diffed as no change.)

Determinism: the same pair always produces byte-identical `to_dict()` — changes
sorted by category, symbol, kind then remaining fields (`_sort_key` is a total
order); caveats deduplicated and sorted; no set iterated without sorting.

Anything not compared exactly goes to `caveats`: a contained program unit, an
unrecognised nested clause, REPORT SECTION group clauses, level-66 RENAMES,
ENVIRONMENT/IDENTIFICATION content beyond the above, a duplicate procedure name,
a near-miss rename. Tests: `tests/unit/analysis/test_ast_diff.py`.

A `WHEN` selector's text carries the parser's markers (#313, 2026-10-14):
`FIG:SPACES` for a figurative constant, `ID:WS-B` for a data name,
`Literal:'SPACES'` for a quoted literal. The values alone are identical
once the lexer strips quotes, so `WHEN SPACES` -> `WHEN 'SPACES'` used to
diff as "No structural changes".

**Known gaps**: statements outside any named paragraph are not compared, and
neither are contained programs (`diff` has no `--program` flag yet) — both are
recorded as caveats rather than silently skipped.


## JCL (`cobolparser/jcl/`)

The `ddname -> dataset` binding a COBOL `SELECT ... ASSIGN TO` resolves
through, read from z/OS JCL by the `jcl-parser` package (optional extra
`cobol-parser[jcl]`); `cobolparser.jcl` is the adapter. It is not an analyzer
and shares no code with the COBOL pipeline; it has its own OKF file:
**[jcl.md](jcl.md)**.


## 2026-10-08 bug hunt (pinned in `tests/regression/test_bug_hunt_2026_10_08.py`)

* **`recursion_risk.py`**: `_has_escape` only counts edges that carry control
  to another paragraph (`_ESCAPE_EDGE_TYPES` = `INTERNAL_EDGE_TYPES` minus
  `IF_BRANCH` / `EVALUATE_BRANCH`). The synthetic branch edges target a
  branch node (`L1__IF_1`) that is never a cycle member, so any GO TO loop
  whose body held an IF read as having "a way out" and was graded MEDIUM;
  HIGH was unreachable for every real loop.
* **`unused_variables.py`**: references it did not see -- `PERFORM P WS-N
  TIMES` (`times_count`), `WRITE ... AFTER ADVANCING WS-N LINES`
  (`advancing_clause["value"]`), `INITIALIZE ... REPLACING ... BY WS-ZERO`
  (`replacing_clauses[].by_value`, via `_DICT_LIST_EXTRAS`), `XML GENERATE
  doc FROM group` / `JSON PARSE doc INTO group` (every subordinate, by name,
  through `_whole_group_references`, which also folds in the CALL USING
  marking), and `MOVE / ADD / SUBTRACT CORRESPONDING A TO B`
  (`_corresponding_pairs` + `_mark_corresponding_used`: only the
  same-named subordinates of the two groups, the others keep their own
  standing). An INITIALIZE target's fields stay assessed, like `MOVE SPACES
  TO group`.
* **`xref.py`**: `WRITE ... ADVANCING WS-N LINES` records a `read` of WS-N.
* **`_names.py`**: `IDENTIFIER_TOKEN_RE` accepts a digit-led user word
  (`1ST-NAME`, IBM-legal as long as a letter is present) and refuses to
  start inside another word or after a decimal point (so `1.5E+3` yields no
  `5E`). The letter-led pattern bit the digit off, so `MOVE 1ST-NAME TO
  2ND-NAME` referenced `ST-NAME` / `ND-NAME`: both items unused, both
  names undefined in xref. Shared with `redundancy.py`'s clone renaming.


## CICS terminators (issue #392, `_cics.py`)

Two rules. `cics_exit_kind(stmt)`: the command is `RETURN`, `XCTL` or
`ABEND`, which leave the program whenever they succeed. `cics_terminator_kind
(stmt)`: the same, minus a `RETURN` / `XCTL` carrying `RESP`, `RESP2` or
`NOHANDLE` (decision (a) on the issue: a failed command then continues at
the next statement); `ABEND` always is one. Both `_is_terminator` copies
(`dead_code.py`, `program_flow/scanner.py`) use `cics_terminator_kind`, so
neither draws fall-through past such a paragraph. The scanner uses
`cics_exit_kind` for `FlowNode.has_cics_exit`, `exit_points` and
`exit_statement_kind` (`"EXEC CICS RETURN"`, ...), and
`RecursionRiskAnalyzer._has_escape` counts `has_cics_exit` as a way out --
so a retry loop ending in `RETURN TRANSID(...) RESP(...)`, the usual shop
form, is `MEDIUM` like the GOBACK equivalent, not a `HIGH` lint error
(review of PR #453: applying the RESP exemption to the escape flag too left
that loop HIGH). Pinned in `tests/unit/analysis/test_cics_terminators.py`.
