---
type: History
title: Analysis history
description: Archived dated notes moved out of analysis.md; not loaded by default.
tags: [history, analysis]
timestamp: 2026-10-15T00:00:00Z
---

# Analysis history

An archive of the dated notes (fix write-ups, audit findings, bug-hunt rounds,
review passes) moved verbatim out of [analysis.md](../analysis.md) on
2026-10-15, when that file was split into the per-family files under
[analysis/](../analysis/). The topic files state the current behaviour and the
invariants these notes established; read this only for why something was done
or when. Dated sections come first, newest first; the per-analyzer note
collections that span many dates follow, each in its original order. Anchors
inside the quoted text point at the old single-file layout.

## 2026-10-08 bug hunt

*(Originally headed "2026-10-08 bug hunt (pinned in `tests/regression/test_bug_hunt_2026_10_08.py`)".)*

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

## Doubled-quote literals (2026-09-27)

`_literals.py`'s `quote_literal()` re-emits a decoded literal doubling
each embedded `"`; its inverse `unquote_literal()` (2026-09-27) strips the
delimiters *and* collapses the doubled delimiter. Any consumer reading a
re-emitted literal back must use it: `generators/data/layout.py`
(`_strip_literal_quotes`, VALUE clauses), `analysis/constraints.py`
(`_strip_quotes`, branch witnesses) and `analysis/const_fold.py` (MOVE
sources) each stripped only the delimiters, so `VALUE "A""B"` generated
`A""B` and `MOVE '"'` folded to two quote characters. Pinned by
`tests/regression/test_doubled_quote_literal_values.py`.

## Program-type corpus fixes (2026-09-15)

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
* **SQL WHENEVER handlers** (#349): `EXEC SQL WHENEVER SQLERROR|SQLWARNING|
  NOT FOUND GO TO p` (also `GOTO`, `:p`; the EXEC text collector leaves
  `GOTO:P`) is a precompiler directive, not a statement: it puts a `GO TO p`
  after every *executable* SQL statement that follows it in source order
  (line, column) until a later WHENEVER for the same condition replaces it
  (`CONTINUE` switches it off; DECLARE / INCLUDE / BEGIN|END DECLARE SECTION
  are not covered). `analysis/_sql_whenever.py`'s `whenever_coverage()`
  maps each covered SQL statement (by `id`) to its targets, once per
  analysis, and both consumers read it so they cannot disagree:
  `DeadCodeAnalyzer._collect_sql_whenever_refs` adds a GO TO-shaped
  reference **from the covered statement** (so it counts only once that
  statement's procedure is admitted by the #384 worklist; WHENEVER is
  deliberately *not* in `_always_counts`), and
  `EdgeCollector.process_sql_whenever` draws a `FlowEdgeType.SQL_WHENEVER`
  edge from each procedure holding covered SQL (one per procedure/target).
  The first cut drew the edge from the directive's paragraph; review of #461
  showed a never-performed "SQL setup" paragraph then made program flow
  call the handler unreachable while dead-code called it live. Joined the
  INTERNAL/GOTO sets and flowchart tables like `CICS_HANDLE`. Pinned by `tests/unit/analysis/test_sql_whenever_references.py`.
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

## Silent-Failure Audit (2026-07-08)

`IOCoverageReporter.load_pytest_results` (`io_coverage_reporter.py`) called
`json.load()` on the pytest-results file and then unconditionally
`data.get("tests", [])` — a syntactically valid JSON file whose root wasn't
an object (e.g. a bare list) raised an uncaught `AttributeError` deep inside
the loader instead of a clean error. Now raises `ValueError` immediately
after the `json.load()` if `data` isn't a `dict`, matching the "artifact
must be a JSON object" check `IOCoverageReporter`'s CLI callers already
apply elsewhere (see [cli.md](../cli.md) M10). Pinned by
`tests/unit/analysis/test_io_coverage_reporter.py::test_load_pytest_results_non_object_json_raises_value_error`.

## DeadCodeAnalyzer notes

Only the unit's own statements are read (contained programs are skipped).
`_ordered_procedures` matches source order even when top-level paragraphs
precede the first SECTION. Each rule below is pinned in
`tests/unit/analysis/test_dead_code.py`; the dated notes give the reason
for it.

**Recent change notes:**

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

**Earlier fixes** that shaped the rules above (2026-08 onward):

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
RETURN` / `XCTL` / `ABEND`, see [CICS terminators](../analysis/flow.md)) or an
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
edge out of their own end. A `PERFORM A THRU C` range's end C still does
not escape. Pinned by
`tests/unit/analysis/test_dead_code.py::TestFallThroughOnlyEscapesReachableRuns`.

**THRU ranges are walked, not blanket-marked (issue #381, 2026-10-14).**
`_mark_thru_range` used to mark every procedure between the two ends of a
`p THRU q` range referenced, so an obsolete stub inside `PERFORM 1000-PROC
THRU 1000-EXIT` that every path jumps over with `GO TO 1000-EXIT` was never
reported. Ranges are now recorded during collection (`_thru_ranges`) and
walked by `_mark_thru_ranges` *after* `_collect_fallthrough_refs`, in source
order like the section walk: a member is reached when the one before it was
reached and does not `_terminate`, or when it is a fall-through source (a
GO TO / ALTER / ENTRY landing) or a section-exit jump target. Sections in the
range are walked through, since their paragraphs follow the header in
`_ordered_procedures`. Both ends stay referenced unconditionally. Pinned by
`tests/unit/analysis/test_dead_code.py::TestThruRangeSkippedMembers`.
Two refinements from review: "landing in it" means any member in
`_jump_targets` (every GO TO / ALTER / CICS HANDLE target, *including*
range ends and section exits, which are not fall-through sources) -- so
`GO TO P1-EXIT` inside a `PERFORM P0 THRU P2-EXIT` that also nests
`PERFORM P1 THRU P1-EXIT` still runs on into P2; and an `EXIT SECTION`
member (`_exits_section`) resumes the walk at the next section header in the
range, since it leaves only its own section. `_mark_thru_ranges` runs
*inside* the #384 worklist right after `_collect_fallthrough_refs`, so a
reached range member's statements are admitted the next round (after the
loop, a PERFORM in a range member would never be collected). Pinned by
`TestThruRangeNestedAndSectionExits`.

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

**Alterable `GO TO.` and `EXIT SECTION` are terminators too (issue #382,
2026-10-14).** Both `_is_terminator`s (here and `program_flow/scanner.py`)
required `stmt.target_paragraph`, so the operand-less alterable `GO TO.`
(always jumps wherever an ALTER last pointed it) read as falling through;
now any non-`DEPENDING` `GoStatement` terminates. `EXIT SECTION` passes
control to the end of its section, so a paragraph whose first top-level
transfer is `EXIT SECTION` (and that sits in a section -- outside one the
compiler rejects it) never falls into the next paragraph
(`_exited_section`, folded into `_terminates`). What happens after the end
of the section is what happens off its last paragraph: in dead-code,
`_collect_exit_section_ref` credits the procedure after the section's last
member only when the section keeps running (in `_fallthrough_sources` or
`_sections_entered_by_jump`), so a PERFORMed section returns and credits
nothing. In program-flow the scanner records the procedure in
`exit_section_procedures` and `build_fall_through_edges` draws a
`FALL_THROUGH` edge to the section's successor only when the section is
fallen into (an incoming fall-through edge, tracked in the same pass) or
in `ProgramFlowAnalyzer._sections_entered` (entry point / ENTRY, a written
GO TO from another section, or the target of any other `GOTO_EDGE_TYPES`
edge -- ALTER, CICS HANDLE, and any handler branch added to that set later
-- wherever it is written). That gate is
stricter than the plain last-paragraph fall-through, which stays an
over-approximation. Pinned by
`tests/unit/analysis/test_exit_section_and_alterable_goto.py`.

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

## UnusedVariableAnalyzer notes

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
[parser.md](../parser.md). This module's explicit subjects walk is KEPT: an
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

**Copybook provenance is set-difference, not line-tracking.** `analyze()`
takes an optional `copybook_item_names: set[str]` the caller computes by
diffing `collect_declared_items()` on an *unexpanded* parse against the
expanded one -- see the `unused-variables` CLI subcommand
(`_parse_without_copybook_expansion` in `cli/parse.py`; `lint` reuses it via
`_lint_copybook_item_names`) for the reference implementation. Rationale:
when this analyzer was written, `expand_copybooks(...,
preserve_source_locations=True)` never populated its source map. That map
now exists (`CopybookExpansion.source_location_map` /
`ParseResult.expansion_source_map`, see [preprocessing.md](../preprocessing.md)),
but the analyzer and CLI were not switched over; the set difference still
works. `include_copybook_variables=False` then excludes any
unused item in that set from `report.unused_items` (tallied instead in
`report.skipped_copybook_count`); the flag is a documented no-op when
`copybook_item_names` is None.

**SCREEN / REPORT / COMMUNICATION SECTION items are out of scope.**
`collect_declared_items` reads only FILE / WORKING-STORAGE / LOCAL-STORAGE /
LINKAGE (`_DATA_SECTION_NAMES`). The DATA DIVISION parser skips SCREEN and
COMMUNICATION SECTION content (`_skip_section`) and, since 2026-09-02, parses
REPORT SECTION RDs and report groups into a `REPORT` section -- which this
analyzer still ignores, so report-group items are never reported unused.
History: the analyzer originally surfaced a parser bug (SCREEN SECTION
clauses mis-parsed as WORKING-STORAGE items, e.g. an item named `COLUMN` in
`tests/samples/screen_section_io.cbl`); that was fixed in the parser, not
here (see [parser.md](../parser.md) / [log.md](../log.md)).

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

**EXEC CICS/DLI arguments are swept explicitly.** `ExecCicsStatement.
options` (option keyword -> parenthesized argument text) and
`ExecImsStatement.arguments` (positional list) are raw text the operand loop
cannot decompose, so a sweep after that loop (one `traverse_depth_first()`
of the unit, skipping contained programs' nodes, matching by type *name* to
avoid an analysis -> parsers import) extracts identifiers from them. History:
the sweep was added (2026-08-19) because neither class then extended
`CobolStatement`, so neither reached `get_all_statements()`. Both are
`CobolStatement`s now, so the per-statement loop also visits them and the
sweep is a harmless set union -- a new analyzer does not need to reproduce
it. See `TestExecCicsAndImsArguments` in `test_unused_variables.py`.

**OO FACTORY / OBJECT data is shared with its METHODs (issue #379,
2026-10-14).** A contained unit's references normally count only for the
container's GLOBAL items. In IBM OO COBOL, though, the data of a FACTORY or
OBJECT paragraph is visible to every METHOD in it with no GLOBAL clause, so
when `ast.unit_kind` is in `_OO_DATA_OWNERS` every item is matched against
`_nested_referenced_names(ast)` too. Instance data that only methods touch
(all of it, in practice) is no longer reported unused. Factory and object
scopes stay separate: an OBJECT method's reference does not use a FACTORY
item of the same name. The whole-group rules (`_whole_group_references`:
CALL USING, XML/JSON GENERATE/PARSE) and `_corresponding_pairs` read the
methods' statements too (`_all_contained_units`), since the FACTORY/OBJECT
unit has none of its own. Known gap, shared with the GLOBAL path: a
method-local item that shadows an instance item still credits the instance
item. See `TestObjectOrientedUnitData`.

## ProgramFlowAnalyzer notes

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
`BranchNode`/`ProgramFlowReport`), `condition_text.py` / `statement_text.py`
(text rendering, below), `scanner.py` (`ProcedureScanner`: procedure
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
see [generators.md](../generators.md).

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
2026-10-15: that list missed `on_exception` / `not_on_exception`, and the
XML/JSON PARSE/GENERATE branch (special-cased for its PROCESSING PROCEDURE
edge) never reached the `else` at all, so a PERFORM / GO TO in an XML/JSON
or ACCEPT/DISPLAY `ON EXCEPTION` body drew no edge and its target read as
unreachable (`CICSCHNL`'s `1000-CHECK-CREDIT`, PERFORMed from `JSON PARSE
... NOT ON EXCEPTION`, once the CICS RETURN/XCTL terminator change removed
the fall-through that had masked it). Both now queue those bodies. Pinned by
`tests/unit/analysis/test_program_flow.py::TestProgramFlowExceptionBodies`.

## RecursionRiskAnalyzer notes

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
  `contained_programs`) — before issue #274 a contained program's
  `CALL 'OUTER'` was reported as the outer unit calling itself.

## ComplexityAnalyzer notes

**Same-named paragraphs are measured separately (issue #258):** the
2026-08-16 audit fix summed same-named paragraphs into one row because the
flow node was name-keyed. Flow nodes are now keyed by `ProcedureIndex`
(`"DO-WORK OF SEC-TWO"`), so `_collect_paragraph_map` maps each key to its
own body and each row carries `qualified_name`. Pinned by
`tests/regression/test_audit_2026_08_16_analyzers.py::TestA8SameNamedParagraphs`.

## RedundancyAnalyzer notes

- **Type-1 (exact)**: identical statement types, operands, and condition
  text -- and everything else each statement does (#262, below). "Identical"
  is up to what COBOL itself ignores (#391): `_normalize_text` collapses
  every whitespace run outside a literal to one space and upper-cases all
  text outside a literal, for *both* types, so a line break inside a
  COMPUTE or condition, or a paragraph written in lowercase, no longer hides
  a Type-1 clone (lowercase used to drop to Type-2; a line break used to
  lose the match entirely). Literal text stays exactly as written:
  `DISPLAY "Done"` vs `display "DONE"` is not a clone.

`_Fingerprinter` builds a hashable nested-tuple fingerprint per paragraph
(not a flat token stream -- a flat sequence could conflate two differently-
nested trees that happen to serialize the same way; the nested-tuple shape
encodes tree structure unambiguously). Paragraphs are grouped by exact
fingerprint equality; Type-1 grouping runs first, and any paragraph already
in a Type-1 group of size >= 2 is excluded from the Type-2 pass, so a
paragraph is only ever reported in one clone group. That exclusion is by
paragraph *identity*, not by name (#353, 2026-10-15): a paragraph name may
repeat across sections, and keying it on the bare name used to let one `P1`
in a Type-1 group silently drop another section's `P1` -- and with it a
whole Type-2 group -- from the Type-2 pass. `CloneMember.name` is still the
bare uppercased paragraph name (callers join on it); its `location` tells
two same-named members apart. Groups below
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
consistent rename. Since #391 folds case outside quotes, `_unquoted_literals`
and `_selector_text` re-quote the unquoted literals the AST *marks* as
literals (static CALL target, INVOKE method literal, STOP literal, EVALUATE
`WHEN` Literal with `quoted` and Range bounds with `start_quoted` /
`end_quoted`), so a case-only difference there still breaks Type-1. Where the
AST does not mark them -- CANCEL targets, ACCEPT ... FROM ENVIRONMENT names,
EXEC CICS option values, literal arguments inside a COMPUTE `expression`,
XML/JSON `clause_text` -- a case-only literal difference reads as the same
text, so Type-1 can group them (it could not before #391).

## TechnicalDebtAnalyzer notes

**Four weighted components** (`DebtWeights`, defaults `complexity=30`,
`redundancy=30`, `control_flow=30`, `size=10` -- sum 100 -- but any
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

## LintAnalyzer notes

(`IOSequenceAnalyzer` itself now reports a violation once per source location
since #371, so it no longer produces these.)

### Program units and finding origins (2026-09-07)

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
[preprocessing.md](../preprocessing.md)): analyzer locations count lines in the
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
pass does not erase it. Detail in [cli.md](../cli.md).

## IOSequenceAnalyzer notes

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
Top-level STOP RUN / GOBACK / EXIT PROGRAM ends the walk. Paragraphs
unreachable from the entry procedure are no longer walked at all.

**GO TO / PERFORM targets resolve section-first (2026-10-14, issue #335).**
The walk's name -> paragraph-index maps (`_name_first` / `_name_last`) are
keyed by `ProcedureIndex` keys, and `_resolve()` applies its rule from the
section of the paragraph being walked (`_current_section`, restored after
each PERFORM) plus the `target_qualifier` / `thru_qualifier` metadata. With
a `SEC-EXIT` in every section, `GO TO SEC-EXIT` used to land on the first
section's exit -- outside the PERFORMed range, so the PERFORM ended there,
the real exit's CLOSE was never seen, and FILE_LEFT_OPEN was reported.
Conditional GO TO targets are resolved when queued. Pinned by
`tests/unit/analysis/test_io_sequence.py::TestSectionLocalParagraphNames`.

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

**IF / EVALUATE arms are forked and merged (2026-10-14, issue #380).** The
arms used to share one open-file state, so `IF .. OPEN OUTPUT f ELSE OPEN
EXTEND f` was a DOUBLE_OPEN and the `IF bad-status CLOSE f STOP RUN` guard
closed `f` for the normal path too (DOUBLE_CLOSE, WRITE_BEFORE_OPEN) -- all
`error` in lint. State is now `_status: dict[file, frozenset]` of possible
states (`open` / `closed` / `unopened`). `_fork` runs each arm (an IF's THEN
and ELSE, an EVALUATE's `when_groups()` bodies and WHEN OTHER; a missing
ELSE / WHEN OTHER is an empty arm) from the branch's state and unions the
arms that do not end the program. An arm whose own top level hits STOP RUN /
GOBACK / EXIT PROGRAM, or that PERFORMs a paragraph that does, is left out of
the merge, and no FILE_LEFT_OPEN is claimed at that STOP RUN (a `_fork_depth`
check in `_terminate_program`, also part of the PERFORM-summary key). An arm
ending in an unconditional GO TO stays *in* the merge: dropping it lost its
state at the target (`PERFORM A THRU A-EXIT` with `IF .. OPEN f GO TO
A-EXIT`, NIST DB104A's `IF .. CLOSE f GO TO ..` guards). A top-level IF whose
arms all end the program ends the paragraph walk (`_ENDS`). Violations need to hold on every merged path (READ of a file open on
no path, OPEN of a file open on every path); FILE_LEFT_OPEN is the exception
and fires for a file open on any path. AT END / INVALID KEY handlers are not
forked. The PERFORM-summary key (#371) is the whole `_status` map, so a range
is re-walked from a new set of possible states. Pinned by
`tests/unit/analysis/test_io_sequence_branches.py`.

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

## MoveTypeChecker notes

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
[generators.md](../generators.md).

## LinkageChecker notes

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
entry interface was collected. A CALL to an `ENTRY` statement is never checked
for this, even though `EntryStatement.parameter_modes` now records an ENTRY's
own `USING [BY] VALUE/REFERENCE` modes (issue #402). `BY CONTENT`
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

## LanguageEnvironmentAnalyzer notes

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

## CRUDMatrixGenerator notes

> 2026-09-28: `SORT`/`MERGE` now mark their files. `USING` files are read
> (R) and `GIVING` files written (C) -- the sort does the I/O itself, so no
> READ/WRITE statement ever names them and they used to come out `----`.
> `RELEASE` marks its SD file C (via the record's FD/SD) and `RETURN` marks
> it R. Pinned by `test_crud_matrix.py::TestSortMergeFileAccess`.

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

**TRUNCATE (issue #341):** `EXEC SQL TRUNCATE [TABLE] t` marks `t` D, like a
DELETE (`SQLStatementType.TRUNCATE` is in `_WRITE_SQL_TYPES`). It parsed as
`UNKNOWN` before and the table got no row. Pinned by
`tests/unit/test_issue_341_dialect_crud.py::TestTruncateTable`.

**SQL write statements (2026-09-28):** for INSERT/UPDATE/DELETE/MERGE only
`stmt.tables[0]` (the target -- see [dialects.md](../dialects.md)) gets the
write flag; every other table a subquery / `INSERT ... SELECT` / `MERGE ...
USING` names is marked **R**. `DELETE FROM T WHERE X IN (SELECT X FROM S)`
used to mark S deleted. MERGE (previously ignored) marks its target with the
actions its `THEN INSERT|UPDATE|DELETE` clauses take.

## DynamicCallAnalyzer notes

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

## IMSSegmentAnalyzer notes

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

**`primary_segment` is the target segment (issue #398):** in DL/I the
**last** SSA (or `SEGMENT(...)` option of `EXEC DLI`) names the segment
retrieved / inserted / replaced; the earlier ones only qualify the path. The
property used to return the first resolved name (a parent). It now returns
`segment_names[-1]`, and `None` when that last one is unresolved -- a
resolved parent is never reported in the target's place.
`TestPrimarySegmentIsTarget` in `tests/unit/test_ims_segment_analyzer.py`.

## HostVariableResolver and DclgenChecker notes

**Null indicators are not host variables here (2026-09-28).** An indicator
(`:X:IND`, `:X INDICATOR :IND`) is picked up by the `:name` scan like any
host variable but binds to no column; names in any statement's
`null_indicators` are dropped from the checked set (unless a column of
that name exists), instead of each being reported as `unchecked`.

A structure-qualified variable (`:DCLCUST.CUST-VAL:IND`) pairs by its last
component, like the SQL model's host-variable list (2026-09-28; before that
the structure name was the "host variable" and nothing was checked).

## SqlCicsAnalyzer notes

| `SQL_SELECT_WITHOUT_INTO` | A singleton `SELECT` with no `INTO` and no cursor. The precompiler accepts it; the row goes nowhere. (`into_variables` is populated from parsed source since 2026-09-28; the `INTO\s*:` text check stays as a backstop.) |

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

**Known gaps** (found in the PR review, not yet fixed): a VARCHAR host structure
written through its subordinate `49` item is not traced to `PREPARE ... FROM
:hv`; SQLCODE checked in a `PERFORM UNTIL` guard, or in the calling paragraph
rather than after the statement, is not seen.

## XrefAnalyzer notes

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

## ProgramSignatureExtractor and codebase graph notes

or `"entry-statement"`. `by_clause` is the callee's declared passing mode
(`"REFERENCE"` / `"VALUE"`, from the division's `using_parameter_modes`
metadata) on the primary entry, and from `EntryStatement.parameter_modes` on
an ENTRY statement's operands (issue #402; it used to be `None` there);
`call_example()` writes a `BY VALUE` / `BY REFERENCE` phrase only where the
mode changes (`CALL "E1" USING LK-A, BY VALUE LK-B RETURNING LK-R`). The
RETURNING item counts as named, so it is never `unreferenced_linkage`.

* A reference as a BY REFERENCE CALL argument or SQL host variable
  (`_AMBIGUOUS_ROLES`), with no write elsewhere → `unknown`, and listed in
  `unchecked`. A `BY CONTENT` / `BY VALUE` CALL argument is not ambiguous:
  the callee gets a copy, so xref records it `read` (2026-09-28; it used to
  be `call-argument`, which graded a parameter only passed on BY CONTENT
  `unknown`). A caller told "input-only" about a
  field the callee overwrites has been told something worse than nothing.

(the qualifier as written, case kept) and, for a nested edge, `parent_path` --
the outer member's file. `programs_using()` and `CopybookImpactAnalyzer` walk
up *edge by edge* (`CopyEdge._is_parent`: same name, and same file whenever the nested
edge has a `parent_path`), so `LIBB/REC -> INNER` reaches only the programs
whose `REC` resolved to `LIBB/REC.cpy` -- never a program whose `REC` did not
resolve at all. A hand-built nested edge with no `parent_path` matches by name
alone (the pre-#351 behaviour). `ImpactReport.paths`

## Field lineage notes

expressions), `read`, `write`, `redefines` (two-way, including several 01
records under one FD), `occurrence` (two-way, inexact: a literal-subscript
occurrence node and its table field), `call`, `linkage`, `sql`, `accept`,
`display`, `xml`. `LINEAGE_VERSION` is `"2"` (2026-10-08: occurrence nodes,
`#RETURNING` linkage ports, `#n` item keys). `VALUE_CHANGING_KINDS` (`arith`, `string`, `aggregate`, `sql-expr`)
make a flow *derived*. Each edge carries `line`, `paragraph`, `guarded`
(inside IF/EVALUATE/SEARCH) and `exact` (byte ranges coincide).

depth)`, `impact_table` (schema optional), `impact_dataset` run a 0-1 BFS
where *depth* counts entries into a program. `key_relationships()` names
candidate dataset/table key relationships with the program and line as
evidence. Joins iterate ports in sorted order so output is identical on
every run (pinned across `PYTHONHASHSEED`s by hand, 2026-10-08).

`DD DUMMY` / `DSN=NULLFILE` bind nothing (`_dataset`); `DSN=*.STEP.DD`
referbacks resolve to the earlier step's dataset; quoted literals in
DFSORT/IEBGENER control statements are blanked before keywords are matched
(`INCLUDE COND=(...,C'BUILD')` is not a reformat). A `DFSRRC00` step (the IMS region
controller) binds its DDs to the application program named by the second
`PARM` positional when the region is `DLI` / `DBB` / `BMP` (2026-10-10; they
were bound to `DFSRRC00` itself, so an IMS batch program's files never
joined). `load_jobs(paths, proc_path)` reads a flat PROC

## ProgramDiffer notes

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

A `WHEN` selector's text carries the parser's markers (#313, 2026-10-14):
`FIG:SPACES` for a figurative constant, `ID:WS-B` for a data name,
`Literal:'SPACES'` for a quoted literal. The values alone are identical
once the lexer strips quotes, so `WHEN SPACES` -> `WHEN 'SPACES'` used to
diff as "No structural changes".

## BoundaryInventoryAnalyzer notes

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

   "Nth" is the Nth name of the callee's `PROCEDURE DIVISION USING`
   (RETURNING excluded), not the Nth LINKAGE 01 in declaration order --
   those differ whenever LINKAGE is declared in another order or holds
   `SET ADDRESS OF` items (fixed 2026-09-28; the old binding inverted the
   directions). Declaration order is only the fallback for a callee with
   no USING.

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

## ConstraintExtractor and domains notes

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
[parser.md](../parser.md)).

## ConstantFolder notes

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
the recursive version did -- the same explicit-stack DFS
`program_flow/cycles.py`'s `detect_cycles` uses, for the identical reason. Recursion is still
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
