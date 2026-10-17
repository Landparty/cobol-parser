---
type: Module
title: Control Flow and Code Quality Analyzers
description: ProgramFlowAnalyzer (the program_flow/ package CFG), DeadCodeAnalyzer, RecursionRiskAnalyzer, ComplexityAnalyzer, RedundancyAnalyzer (clones, paragraph fingerprints) and TechnicalDebtAnalyzer, plus the shared procedure-name index (_procedures.py), CICS terminators (_cics.py) and SQL WHENEVER handlers (_sql_whenever.py).
tags: [analysis, program-flow, dead-code, recursion-risk, complexity, redundancy, technical-debt, cfg]
timestamp: 2026-10-16T00:00:00Z
---

# Control Flow and Code Quality Analyzers

The analyzers that reason about *procedures* (paragraphs and sections) and how
control moves between them: the control-flow graph (`program_flow/`), dead
code, recursion risk, per-paragraph complexity, duplicate paragraphs and the
composite technical-debt score built from all of them. Entry points:
`ProgramFlowAnalyzer().analyze(ast)` and `DeadCodeAnalyzer().analyze(ast)`;
the others reuse their reports. Start with [Procedure roots and
terminators](#procedure-roots-and-terminators), which every analyzer here
shares, then the analyzer you need. Calling conventions shared by every
analyzer are in [../analysis.md](../analysis.md).

## Contents

* [Same-named procedures](#same-named-procedures)
* [Procedure roots and terminators](#procedure-roots-and-terminators)
* [DeadCodeAnalyzer](#deadcodeanalyzer)
* [ProgramFlowAnalyzer](#programflowanalyzer)
* [RecursionRiskAnalyzer](#recursionriskanalyzer)
* [ComplexityAnalyzer](#complexityanalyzer)
* [RedundancyAnalyzer](#redundancyanalyzer)
* [TechnicalDebtAnalyzer](#technicaldebtanalyzer)
* [See also](#see-also)

## Same-named procedures

Two paragraphs may share a name when they sit in different sections
(`X1` in `S1` and `S2`). Analyzers must not key them by bare name (see #258;
the data-item half of the rule is in [data-use.md](data-use.md)).

- **Procedures** — `analysis/_procedures.py`: `ProcedureIndex.build(proc_div)`
  gives every section/paragraph a unique *key*: the bare name when unique,
  `"X1 OF S2"` when the name is shared. `resolve(name, qualifier,
  from_section)` applies the COBOL rule: the `OF`/`IN` qualifier (parser
  metadata `target_qualifier` / `thru_qualifier` on PERFORM and GO TO),
  else the paragraph of that name in the referencing statement's own
  section (`enclosing_section(stmt)` walks `.parent`), else the unique
  name; an ambiguous reference resolves to *every* candidate (keeps code
  alive, never hides it). Used by `program_flow` (scanner + `EdgeCollector`),
  `DeadCodeAnalyzer`, `ComplexityAnalyzer` and `IOSequenceAnalyzer`.
- **Flow output contract** — `FlowNode.name` stays the bare name;
  `FlowNode.qualified_name` is set (and emitted by `to_dict`) only for a
  shared name; `FlowNode.key` is the one every edge `source`/`target`,
  `thru_target`, `range_members`, entry/exit point, cycle,
  `unreachable_nodes` entry and branch `parent_proc` uses. Consumers that
  join edges to nodes must join on `qualified_name ?? name`. Same
  `qualified_name` field on `DeadCodeItem` and `ProcedureComplexity`.

## Procedure roots and terminators

Both `DeadCodeAnalyzer` and `ProgramFlowAnalyzer` (and `IOSequenceAnalyzer`,
`ConstantFolder`) need the same answers to "where does control enter" and
"which statement ends a paragraph". Each has its own `_is_terminator`, kept in
step deliberately.

* **Source order.** Sections and top-level paragraphs are interleaved by
  `location.line` before they are walked: COBOL allows paragraphs before the
  first `SECTION`, and walking all section-owned paragraphs first made a
  section the entry point and reported the real first paragraph dead. With
  interleaving, every registration branch (SECTION header, section-owned
  paragraph, top-level paragraph) needs the `_procedure_names` dedup guard;
  a SECTION header registered over a same-named top-level paragraph keeps the
  `PARAGRAPH` entry, and `_section_paragraphs[name]` is still ensured via
  `.setdefault()`.
* **Entry point.** The first procedure that is *not* in a declarative section
  (control enters after `END DECLARATIVES`), or the leading sentences
  (`LEADING_SENTENCES_NODE`). Every declarative section and paragraph is
  referenced (`_collect_declaratives`); the flow analyzer registers each
  declarative *section* as an entry point after the real one
  (`FlowNode.is_declarative`, serialized when True) so it is never
  "unreachable". `IOSequenceAnalyzer._collect_procedures` skips declarative
  sections entirely: a USE procedure is not on the fall-through path and
  cannot be PERFORMed.
* **Runtime-invoked handlers.** `XML PARSE ... PROCESSING PROCEDURE p [THRU
  q]` is a reference in `DeadCodeAnalyzer._collect_xml_refs` and a
  PERFORM-shaped edge (`FlowEdgeType.XML_PROCESSING_PROCEDURE[_THRU]`,
  `EdgeCollector.process_xml_parse`); `EXEC CICS HANDLE AID|CONDITION|ABEND
  option(paragraph)` is a GO TO-shaped reference (`_collect_cics_handle_refs`,
  `FlowEdgeType.CICS_HANDLE`, `process_cics_handle` -- only option values
  naming a known procedure). Both are in `INTERNAL_EDGE_TYPES` and the
  PERFORM/GOTO sets the cycle classifier, complexity and the flowcharts read
  (`flowchart.py`'s label/verbose/perform/goto tables).
* **SQL WHENEVER handlers** (`_sql_whenever.py`, #349). `EXEC SQL WHENEVER
  SQLERROR|SQLWARNING|NOT FOUND GO TO p` (also `GOTO`, `:p`; the EXEC text
  collector leaves `GOTO:P`) is a precompiler directive, not a statement: it
  puts a `GO TO p` after every *executable* SQL statement that follows it in
  source order (line, column) until a later WHENEVER for the same condition
  replaces it (`CONTINUE` switches it off; DECLARE / INCLUDE / BEGIN|END
  DECLARE SECTION are not covered). `whenever_coverage()` maps each covered
  SQL statement (by `id`) to its targets, once per analysis, and both
  consumers read it so they cannot disagree:
  `DeadCodeAnalyzer._collect_sql_whenever_refs` adds a GO TO-shaped reference
  **from the covered statement** (so it counts only once that statement's
  procedure is reached; WHENEVER is deliberately *not* in `_always_counts`),
  and `EdgeCollector.process_sql_whenever` draws a `FlowEdgeType.SQL_WHENEVER`
  edge from each procedure holding covered SQL (one per procedure/target).
  Drawing the edge from the directive's own paragraph is wrong: a
  never-performed "SQL setup" paragraph would make program flow call the
  handler unreachable while dead-code called it live. Pinned by
  `tests/unit/analysis/test_sql_whenever_references.py`.
* **Terminators.** A paragraph terminates (no fall-through into the next) when
  *any* of its **top-level** statements is a hard terminator -- not just the
  last one, since code after `STOP RUN.` is itself unreachable: `STOP RUN`
  (not `STOP 'literal'`, which only pauses for the operator), `GOBACK`, `EXIT
  PROGRAM`, a CICS terminator (below), any non-`DEPENDING` `GoStatement`
  (including the operand-less alterable `GO TO.`, which always jumps wherever
  an ALTER last pointed it), or `EXIT SECTION`. A terminator nested in one
  IF/EVALUATE arm does not count: a conditional GO TO or STOP RUN still lets
  the paragraph fall through when the condition is false. An **exhaustive**
  branch whose every arm terminates does (`_procedures.branch_terminates`,
  used by both `_is_terminator` copies, recursively): an IF with an ELSE, or
  an EVALUATE with a WHEN OTHER, every arm reaching a terminator -- the
  legacy `IF c GO TO A ELSE GO TO B END-IF` dispatch (#586). An empty WHEN
  shares the next WHEN's statements (`WHEN 1 WHEN 2 STOP RUN`); a trailing
  empty one counts as falling through. Pinned in
  `tests/regression/test_issue_586_exhaustive_branch_terminator.py`. A bare `SECTION` header
  has no statements of its own, so it never terminates. Known boundary: a
  terminator inside an unconditional inline `PERFORM ... END-PERFORM` is not a
  top-level statement and is not seen.
* **`EXIT SECTION`** passes control to the end of its section (outside a
  section the compiler rejects it). What happens after that is what happens
  off the section's last paragraph: dead-code's `_collect_exit_section_ref`
  credits the procedure after the section's last member only when the section
  keeps running (in `_fallthrough_sources` or `_sections_entered_by_jump`), so
  a PERFORMed section returns and credits nothing. In program-flow the scanner
  records the procedure in `exit_section_procedures` and
  `build_fall_through_edges` draws a `FALL_THROUGH` edge to the section's
  successor only when the section is fallen into (an incoming fall-through
  edge, tracked in the same pass) or in `ProgramFlowAnalyzer._sections_entered`
  (entry point / ENTRY, a written GO TO from another section, or the target of
  any other `GOTO_EDGE_TYPES` edge -- ALTER, CICS HANDLE, and any handler
  branch added to that set later -- wherever it is written). That gate is
  stricter than the plain last-paragraph fall-through, which stays an
  over-approximation. Pinned by
  `tests/unit/analysis/test_exit_section_and_alterable_goto.py`.
* **Own statements only.** Procedure names are local to a program unit, and
  `get_all_statements()` also returns every contained program's statements,
  so references (and `ProcedureScanner.collect_entry_points`) read only the
  unit's own statements; otherwise a nested `PERFORM HELPER` keeps the
  container's unrelated `HELPER` alive. Pinned by `TestContainedProgramScope`.

### CICS terminators (`_cics.py`, see #392)

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
`_cics.py` also holds `cics_identifier_options()` (the non-literal options
the data-use sweeps read, #588; see [data-use.md](data-use.md)).

## DeadCodeAnalyzer

```python
report: DeadCodeReport = DeadCodeAnalyzer().analyze(ast)
# report.dead_items: list[DeadCodeItem]   (name/procedure_type/location/qualified_name)
# report.total_procedures / .referenced_procedures
# report.fall_through_edges: set[(from, to)]  -- not in to_dict()
```

`fall_through_edges` holds the procedure-key pairs along which control can
actually run off one procedure into the next: recorded where the analysis
credits a fall-through (`_collect_fallthrough_refs`,
`_collect_exit_section_ref`, the in-section walk of
`_propagate_section_downward`, the in-range walk of `_mark_thru_ranges`).
The MCP `callers_of` keeps a flow-graph `FALL_THROUGH` caller only when its
pair is here (or its source is the flow graph's first entry point, e.g. the
`PROCEDURE DIVISION` leading-sentences node), issue #486.

**What "dead" means: unreachable from a root.** `analyze()` runs a
worklist from the roots -- the entry procedure (the first non-declarative
procedure, or the leading sentences), every DECLARATIVES section and
paragraph, ENTRY paragraphs and CICS HANDLE labels -- and a procedure's
statements count only once the procedure itself is reached, so a paragraph
PERFORMed only from dead code is dead too. A reached procedure references:

* **returning transfers** (`_referenced_names` only): PERFORM / `PERFORM ...
  THRU` targets, SORT/MERGE INPUT/OUTPUT PROCEDUREs, XML PARSE PROCESSING
  PROCEDURE -- control comes back, so they never license a fall-through out
  of their own end;
* **landing transfers** (also `_fallthrough_sources`): GO TO targets
  (incl. `DEPENDING ON`, read from `GoStatement.target_paragraphs`), ALTER
  `TO PROCEED TO` targets (not the ALTER's subject), ENTRY paragraphs, CICS
  HANDLE labels, and SQL `WHENEVER ... GO TO` targets of each covered SQL
  statement (`_sql_whenever.py`);
* **fall-through**: the next procedure in source order after a reached
  fall-through source that does not `_terminate` (any top-level STOP RUN,
  GOBACK, EXIT PROGRAM, `EXEC CICS RETURN/XCTL/ABEND` per `_cics.py`,
  non-DEPENDING GO TO incl. the alterable `GO TO.`, or a top-level EXIT
  SECTION);
* **section and range walks**: a referenced section's paragraphs are walked
  in order up to the first terminator (`_propagate_section_references`); a
  `p THRU q` range is walked the same way (`_mark_thru_ranges`); a GO TO onto
  a THRU range end or a PERFORMed section's last paragraph (`_section_exits`)
  is a reference, not a fall-through source.

`_ordered_procedures` matches source order (see [Procedure roots and
terminators](#procedure-roots-and-terminators)). Each rule below is pinned in
`tests/unit/analysis/test_dead_code.py`; the dated write-ups behind them are in
the [history](../history/analysis.md).

### Rules and their reasons

* **Returning transfers never license a fall-through.** `_fallthrough_sources`
  (procedures control can land in *and keep running from*: the entry point,
  GO TO / ALTER `TO PROCEED TO` / ENTRY / CICS HANDLE / WHENEVER targets, and
  whatever is fallen into from one of those) is strictly smaller than
  `_referenced_names`. A PERFORM returns to its caller at the end of its
  range, so crediting a PERFORM target with a fall-through edge invents a
  path that cannot run and hides all dead code in the most common program
  shape (a `MAIN` of PERFORMs followed by the paragraphs it performs and an
  orphan). Pinned by `TestFallThroughOnlyEscapesReachableRuns`.
* **Fall-through needs a reached predecessor.** `_collect_fallthrough_refs`
  credits a procedure only when the one before it is itself a reached
  fall-through source that does not `_terminate`; without that gate a chain
  of unreached stubs after a `STOP RUN` would credit each other for standing
  next to one another. Pinned by `TestFallThroughReferences`.
* **Reachability is transitive** (#384): a worklist admits a procedure's
  statements to `_collect_references` only once the procedure is reached, so
  a paragraph PERFORMed only from dead code is dead (lint says "can never be
  reached"). THRU range ends and section exits are collected from *every*
  statement up front, which keeps each round monotone. Pinned by
  `TestTransitiveDeadCode`.
* **THRU ranges are walked, not blanket-marked** (#381). Ranges are recorded
  during collection (`_thru_ranges`) and walked by `_mark_thru_ranges` right
  after `_collect_fallthrough_refs`, inside the worklist, in source order: a
  member is reached when the one before it was reached and does not
  `_terminate`, or when control lands in it -- any member in `_jump_targets`
  (every GO TO / ALTER / CICS HANDLE target, *including* range ends and
  section exits), so `GO TO P1-EXIT` inside a `PERFORM P0 THRU P2-EXIT` that
  nests `PERFORM P1 THRU P1-EXIT` still runs on into P2. An `EXIT SECTION`
  member (`_exits_section`) resumes the walk at the next section header in the
  range. Both ends stay referenced unconditionally; an obsolete stub every
  path jumps over is reported. Pinned by `TestThruRangeSkippedMembers` and
  `TestThruRangeNestedAndSectionExits`.
* **Section exits** (#312, the SECTION form of `GO TO nnnn-EXIT`). The last
  paragraph of every section a PERFORM / SORT / MERGE / XML PARSE runs
  (`_section_exits`) is treated like a THRU range end: a GO TO onto it is a
  reference, not a fall-through source, so it does not keep every later
  section alive. Exception: when the section is itself a fall-through source
  (fallen into, or a GO TO target) `_collect_fallthrough_refs` restores the
  exit as a fall-through source, and likewise when the section is entered by a
  jump from outside it (`_sections_entered_by_jump`: a GO TO written in
  another section, an ALTER, a CICS HANDLE, an ENTRY). Pinned by
  `TestSectionExitGoTo`.
* **Section propagation runs downward first.** `_propagate_section_references`
  first walks each *directly* referenced section's paragraphs in order up to
  the first one that `_terminates` (a later paragraph is live only as a
  fall-through source of its own), and only then marks the parent section of
  a referenced paragraph. In the other order, `PERFORM child-paragraph` would
  bootstrap the section into "referenced" and resurrect every sibling.
  Pinned by `TestSectionPropagationDoesNotResurrectSiblings`.
* **ENTRY paragraphs are always referenced.** `_collect_entry_refs` marks the
  ENTRY statement's `section_name` (`CobolParagraph` overrides it to return
  its own paragraph name, so the `.parent` walk lands on the paragraph at any
  nesting depth), skipping a blank/whitespace-only literal exactly as
  `program_flow/scanner.py`'s `collect_entry_points` does. Pinned by
  `TestEntryReferences`.
* **ALTER references only its target.** `ALTER p TO PROCEED TO t` modifies a
  GO TO inside `p`; only `t` is an incoming jump (matching
  `edges.py::process_alter`). Pinned by
  `TestAlterReferences.test_alter_never_called_paragraph_is_dead`.
* **Computed GO TO targets come from `GoStatement.target_paragraphs`**, never
  from `operands` minus the DEPENDING ON variable: operands are deduplicated,
  so a target sharing its name with the variable would vanish. Same rule in
  `ProgramFlowAnalyzer.process_goto`; pinned by
  `test_goto_depending_target_sharing_name_with_variable` in both test files.
* **A self-referencing GO TO counts as an incoming edge** (there is no
  self-reference special case), so a paragraph whose only reference is a GO TO
  to itself is not dead code; `TechnicalDebtAnalyzer` surfaces it as
  unreachable instead.

**Reachability differs from `ProgramFlowAnalyzer` by design.**
`graph.build_fall_through_edges` emits a `FALL_THROUGH` edge between *any* two
adjacent non-terminating procedures, PERFORM targets included, so
`flow_report.unreachable_nodes` under-reports the same way. Changing that is a
CFG-shape question with a much wider blast radius (flowcharts,
`ScenarioPlanner` arm reachability, `TechnicalDebtAnalyzer`'s
unreachable-node smell), so the two modules are allowed to disagree. A
consumer answering "can this paragraph run?" must ask `DeadCodeAnalyzer`:
the MCP tools do (`_reachability()` in `mcp/tools.py`, issue #486).

## ProgramFlowAnalyzer

```python
report: ProgramFlowReport = ProgramFlowAnalyzer().analyze(ast)
# report.nodes: list[FlowNode]   report.edges: list[FlowEdge]
# report.entry_points / .exit_points / .external_calls / .program_cancellations
# report.cycles / .cycle_details / .unreachable_nodes / .branch_nodes
```

Produces a control-flow graph between procedures (paragraphs/sections),
plus synthetic IF/EVALUATE branch nodes. `FlowEdgeType` members:
`PERFORM` / `PERFORM_THRU`, `GOTO` / `GOTO_DEPENDING`, `CALL` /
`CALL_DYNAMIC`, the SORT/MERGE/XML procedure edges
(`SORT_INPUT_PROCEDURE[_THRU]`, `SORT_OUTPUT_PROCEDURE[_THRU]`,
`MERGE_OUTPUT_PROCEDURE[_THRU]`, `XML_PROCESSING_PROCEDURE[_THRU]`),
`CICS_HANDLE`, `SQL_WHENEVER`, `ALTER`, `FALL_THROUGH`, and the branch-node
edges `IF_BRANCH` / `IF_THEN` / `IF_ELSE` / `EVALUATE_BRANCH` /
`EVALUATE_WHEN` / `EVALUATE_WHEN_OTHER`. `edges.py` groups them as
`INTERNAL_EDGE_TYPES` / `PERFORM_EDGE_TYPES` / `GOTO_EDGE_TYPES`.

THRU ranges expand to `FlowEdge.range_members`; cycles are classified in
`cycle_details`. Sentences written before the first paragraph/section
header become the node `LEADING_SENTENCES_NODE` (`"PROCEDURE DIVISION"`,
the program's entry; `scanner.leading_sentences()`, also used by
`ComplexityAnalyzer`).

### Package layout

`cobolparser/analysis/program_flow/` is a package of collaborators --
`models.py` (`FlowNode`/`FlowEdge`/`FlowEdgeType`/`BranchArm`/`BranchNode`/
`ProgramFlowReport`), `condition_text.py` / `statement_text.py` (text
rendering, below), `scanner.py` (`ProcedureScanner`: procedure collection +
the recursive `scan()` statement walk, `_CLAUSE_BODY_ATTRS`), `edges.py`
(`EdgeCollector`: PERFORM/GO TO/CALL/SORT/MERGE/CANCEL/ALTER edge
construction, `INTERNAL_EDGE_TYPES`/`PERFORM_EDGE_TYPES`/`GOTO_EDGE_TYPES`),
`cycles.py` (`detect_cycles`/`classify_cycles`, an explicit-stack DFS),
`graph.py` (`build_fall_through_edges`/`compute_convergence_nodes`/
`find_unreachable_nodes`), and `analyzer.py` (`ProgramFlowAnalyzer`
orchestrator). All public names import from `cobolparser.analysis.program_flow`.

### Graph rules

* **THRU range members are reachable.** `PERFORM A THRU C` (and SORT/MERGE
  procedure ranges) runs every paragraph the range spans, but the graph has
  explicit edges only to the endpoints; the intermediates ride in
  `FlowEdge.range_members`, and `find_unreachable_nodes` adds each member as a
  neighbor of the edge's source in its BFS adjacency. Cycle detection
  deliberately uses explicit edges only -- member hops have no
  `(source, target)` edge record and would misclassify cycles as `MIXED`.
  Pinned by `tests/unit/analysis/test_program_flow_thru_reachability.py`.
* **Fall-through suppression reads `terminating_paragraphs` only.**
  `ProcedureScanner._scan_paragraph_statements` fills it with every paragraph
  holding a top-level terminator (`ProcedureScanner._is_terminator`, mirroring
  `DeadCodeAnalyzer._is_terminator`); `build_fall_through_edges` suppresses
  the edge for exactly those. `FlowNode.has_stop_run` / `has_goback` /
  `has_exit_program` mean "anywhere in the paragraph, nested arms included"
  and are used for flowchart terminal nodes and `is_exit_point`, never for
  suppression. A PERFORM earlier in the paragraph does not matter either:
  `MAIN. PERFORM HELPER. GO TO MAIN.` has no `MAIN -> HELPER` fall-through.
  Pinned by `TestProgramFlowFallThrough` and
  `test_terminator_earlier_in_paragraph_still_suppresses_fall_through` /
  `test_conditional_stop_run_inside_if_does_not_suppress_fall_through`.
* **`RETURN` is not an exit.** It reads the next SORT/MERGE record; the scanner
  never adds its paragraph to `_exit_points` nor records it as an exit
  statement (`node.has_return` is a separate flag).
* **Every clause body is scanned.** Unlike most analyzers (which walk
  `get_all_statements()`), the graph is built by a hand-rolled `scan()` that
  special-cases PERFORM inline blocks, CALL handlers and
  IF/EVALUATE/SEARCH/RETURN, then iterates `_CLAUSE_BODY_ATTRS` (AT END /
  INVALID KEY / AT EOP, ON SIZE ERROR, ON OVERFLOW, `on_exception` /
  `not_on_exception`, ...) in a final `else`; the XML/JSON PARSE/GENERATE
  branch queues its exception bodies too. An `id`-based `visited` set prevents
  double counting. A PERFORM / GO TO / CALL in a body the scan misses draws no
  edge and its target reads as unreachable. Pinned by
  `tests/regression/test_tier6_silent_drop_audit.py` and
  `TestProgramFlowExceptionBodies`.

### Condition and statement text

`program_flow/condition_text.py`'s `render_condition_text(expr: CobolExpression
| None) -> str` walks a `ConditionalExpression`/`LogicalExpression` tree back
into readable COBOL (`"WS-EOF-SW = 'Y'"`, nested `AND`/`OR`/`NOT`
parenthesized), falling back through the node's raw `operands[0]`,
`metadata["raw_condition"]`, then its bare `expression_type` tag, so every
caller gets *something*. `BranchNode.condition_text` and the PERFORM UNTIL
guard carry it; both flowchart generators render it on IF/EVALUATE diamonds
and loop-test nodes.

`FlowNode.exit_statement_kind` / `exit_statement_location` are set by
`scanner.py` when a paragraph reaches `STOP RUN`, `GOBACK`, `EXIT PROGRAM` or a
CICS exit (`"EXEC CICS RETURN"`, ...). `to_dict()` emits them only when both are
set; the flowcharts draw a terminal node per exit (`shape=doublecircle` in DOT,
`(((...)))` + the `terminal` classDef in Mermaid) labeled `"{kind} @ {line}"`
(see generators.md's "Label fidelity"). First write wins
(`_record_exit_statement`).

`program_flow/statement_text.py`'s `summarize_statement(stmt) -> str` is a
compact COBOL-like one-liner (`"MOVE 8 TO RETURN-CODE"`, `"PERFORM
4000-CLEANUP"`, `"IF <rendered condition>"`) with type-specific branches for
MOVE/PERFORM/GO TO/CALL/SET/COMPUTE/ADD/SUBTRACT/MULTIPLY/DIVIDE/DISPLAY/IF/
EVALUATE/STOP/GOBACK/EXIT and a `statement_type + operands` fallback that
never raises, truncated to 48 chars; `summarize_arm(statements)` gives the
first statement's summary (`None` for an empty arm). `BranchArm.summary` holds
it for THEN/ELSE/WHEN/WHEN OTHER (`to_dict()` only when non-None); the
flowcharts render it instead of the bare keyword (see generators.md).
Clause fidelity matters because `cobol-parser diff` compares this text: `SET x
UP BY v` / `DOWN BY v` / `TO FALSE` are rendered as written, ADD/SUBTRACT take
their sources from `source_operands` and append ` GIVING ...`, PERFORM renders
` VARYING v FROM x BY y` / ` n TIMES` (the UNTIL guard is the diff renderer's
job, `ast_diff._statement_text`) and COMPUTE / ADD / SUBTRACT render each
receiver with its own `ROUNDED [MODE IS m]` (`rounding_of`; #274, #517).
An EVALUATE subject is narrowed with `isinstance(s, CobolExpression)` (not
`hasattr`, which mypy cannot narrow on).

## RecursionRiskAnalyzer

```python
report: RecursionRiskReport = RecursionRiskAnalyzer().analyze(ast)
# report.risks: list[RecursionRisk]
# RecursionRisk.mechanism: "PERFORM" | "GOTO" | "MIXED" | "CALL"
# RecursionRisk.severity: "HIGH" | "MEDIUM" | "LOW" (LOW: CALL into an IS RECURSIVE program)
# RecursionRisk: mechanism/severity/explanation/procedures/program/is_dynamic/has_escape
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
  `MEDIUM` otherwise. Grading per SCC rather than per cycle matters: two
  cycles sharing a paragraph would each "escape" into the other, so an
  inescapable `P1 -> P2 -> P1` / `P1 -> P3 -> P1` pair would read MEDIUM
  (see #393). `_has_escape` counts only edges that carry control to another
  paragraph (`_ESCAPE_EDGE_TYPES` = `INTERNAL_EDGE_TYPES` minus `IF_BRANCH` /
  `EVALUATE_BRANCH`): the synthetic branch edges target a branch node
  (`L1__IF_1`) that is never a cycle member, and counting them would make every
  GO TO loop holding an IF look escapable. `has_return` is a SORT/MERGE
  `RETURN sd-file`, **not** a terminator (otherwise every SORT
  output-procedure loop reads MEDIUM). Fall-through-only cycles are never
  reported (fall-through can't actually form a cycle).
  A `MIXED` cycle that is a PERFORM of a multi-procedure range (a SECTION
  with its paragraphs, or a THRU span) made from *inside* that range, every
  other hop a fall-through between its members, is reported as
  `mechanism="PERFORM"`, `HIGH` (`_reenters_own_perform_range`, #350): the
  range-level twin of `P. PERFORM P.`. `_closed_by_perform_range_end` (which
  drops the priming-read false positive) ends a SECTION's range at its last
  paragraph (`_perform_range`), not at the header node -- the header's
  fall-through into its first paragraph is not "leaving the range", so
  `S. S1. PERFORM S.` is reported.
- **Cost is linear per cycle** (#373). `cycle_details` holds one cycle per
  back edge with its full path, so the "GO TO restart" idiom (every
  paragraph may `GO TO 0000-START`) yields N cycles of length ~N. The edge
  maps, node map and PERFORM ranges are built once per report
  (`_FlowIndex`); `_closed_by_perform_range_end` collects the PERFORM-only
  hops' range ends then tests each fall-through-only hop by set lookup;
  `_reenters_own_perform_range` needs exactly one non-fall-through hop; the
  escape test is cached per strongly connected component. 800 paragraphs:
  17 s -> 0.4 s, output unchanged. One risk per cycle is still reported (N
  near-identical risks for that idiom). Pinned by
  `tests/regression/test_issue_373_recursion_check_restart_idiom.py`.
- **Self-recursive CALL** — a CALL (static, or dynamic and resolved via
  `DynamicCallAnalyzer`, which this analyzer runs internally) whose target
  equals the program's own `PROGRAM-ID`. `HIGH`, or `LOW` when the
  `PROGRAM-ID` is declared `IS RECURSIVE` (re-entry legal; base case
  unverifiable). Only the unit's *own* statements are walked
  (`_own_statements`: `get_all_statements()` minus every node of
  `contained_programs`), so a contained program's `CALL 'OUTER'` is not
  reported as the outer unit calling itself (see #274).
- **CALL to an enclosing program** (#274) — a contained program CALLing a
  program it is nested in (any `CobolProgram` up its `.parent` chain). The
  container is necessarily active while the contained program runs, so this
  is indirect recursion: `HIGH`, or `LOW` when that container is `IS
  RECURSIVE`. Reported on the *inner* unit, `program` = the container's name.

Exported from both `cobolparser.analysis` and the top-level `cobolparser`
package, same as `DeadCodeAnalyzer`/`ProgramFlowAnalyzer`. CLI:
`cobol-parser recursion-check <file.cbl>` (see cli.md).

## ComplexityAnalyzer

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
a decision point since it always runs exactly once; each AFTER phrase of a
PERFORM VARYING adds one more decision *and* one more nesting level, being a
nested loop with its own UNTIL, so the AFTER form scores what the nested
inline-PERFORM form does (#514) -- per target of a
computed `GO TO ... DEPENDING ON` (an N-way branch plus the out-of-range
fall-through, scored like an N-arm EVALUATE; a plain GO TO adds nothing and
neither changes nesting depth) -- and per *present* exception-handling
clause **pair** (`_CLAUSE_PAIRS`): AT END / NOT AT END, INVALID KEY / NOT
INVALID KEY, AT EOP / NOT AT EOP, ON SIZE ERROR / NOT ON SIZE ERROR, ON
OVERFLOW / NOT ON OVERFLOW, ON EXCEPTION / NOT ON EXCEPTION add 1 whether
one or both bodies are written -- they are the two outcomes of one test,
as IF ... ELSE is one decision; counting each body scored the recommended
explicit-both-outcomes style worse (#553). SEARCH's AT END adds nothing: a
SEARCH already has its not-found path and is scored one per WHEN);
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

**Walk mechanics.** The clause-pair attribute check (both bodies of a pair
are walked; `at_end_clause`/`not_at_end_clause`/.../`on_exception`) is a
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

**Same-named paragraphs are measured separately.** Flow nodes are keyed by
`ProcedureIndex` (`"DO-WORK OF SEC-TWO"`), so `_collect_paragraph_map` maps
each key to its own body and each row carries `qualified_name` (see #258).
Pinned by
`tests/regression/test_audit_2026_08_16_analyzers.py::TestA8SameNamedParagraphs`.

`_BOOL_WORD_RE` (the AND/OR count behind `extended_complexity`) skips the OR
of a word operator's `OR EQUAL`.

CLI: `cobol-parser complexity <file.cbl>` (see cli.md).

## RedundancyAnalyzer

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
  text -- and everything else each statement does (#262, below). "Identical"
  is up to what COBOL itself ignores (#391): `_normalize_text` collapses
  every whitespace run outside a literal to one space and upper-cases all
  text outside a literal, for *both* types, so a line break inside a
  COMPUTE or condition, or a paragraph written in lowercase, does not hide a
  Type-1 clone. Literal text stays exactly as written:
  `DISPLAY "Done"` vs `display "DONE"` is not a clone.
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
paragraph is only ever reported in one clone group. That exclusion is by
paragraph *identity*, not by name: a paragraph name may repeat across
sections, and keying on the bare name lets one `P1` in a Type-1 group drop
another section's `P1` -- and with it a whole Type-2 group -- from the Type-2
pass (see #353). `CloneMember.name` is still the
bare uppercased paragraph name; a member whose name is shared with a
paragraph in another section also carries `qualified_name` (`"CALC OF
S1"`, the same `ProcedureIndex` key the flow graph and dead-code items use,
in `to_dict()` only when set). Join on `qualified_name or name`: matching
the bare name made every section's `CALC` a clone offender in `health`
when only one of them was a clone (#555). Groups below
`min_clone_statements` (default 3 -- two bare `EXIT.` paragraphs matching
each other isn't meaningful redundancy) are dropped.

**A leaf statement's fingerprint is its whole behaviour, not its operand
list** (see #262). `operands` is often just the identifier list (COMPUTE's is
`['A']`; the formula lives in `expression`), so `(type, operands)` alone would
call paragraphs differing only in a COMPUTE formula, ROUNDED (which receiver,
and its mode -- rounding modes are `_DETAIL_KEYWORDS`, never renamed; #517), an AT END /
INVALID KEY / ON SIZE ERROR / ON EXCEPTION body, `UPON`, `CORRESPONDING`, a
STRING delimiter or the INSPECT phrase Type-1 clones. A leaf is `(type,
operands, clauses, details)`: `clauses` fingerprints every present clause body
(the same attributes `complexity.py`'s `_CLAUSE_PAIRS` pairs up, recursively through `_fp`, so
their statements also count towards `statement_count`), and `details` is the
statement's `to_dict()` minus `_DETAIL_SKIP_KEYS` (position, node
bookkeeping, what the tuple already holds, and `possible_values` -- a
`DynamicCallAnalyzer` annotation that would make a digest depend on analyzer
order). SEARCH adds its details (table, VARYING) and an inline PERFORM its
TIMES count / VARYING / TEST phrase the same way. Under Type-2, detail
strings are renamed like operands **except reserved words** (`_DETAIL_KEYWORDS`:
`_NON_IDENTIFIER_WORDS` + the lexer's keyword table + enum-like values the
models store, e.g. `LEADING`, `SIZE`, `TIMES`, `INPUT`), so `FOR ALL` vs
`FOR LEADING` is never a "consistent rename"; a dict keyed by data-names
(OPEN's file -> mode map) has its keys renamed too. **Digests are not
versioned**: when the fingerprint definition changes, digests stored by
earlier scans simply stop matching new ones. Known residual: the
parser stores some literals unquoted (an INSPECT `'X'`, a STRING
`DELIMITED BY 'X'`), so under Type-2 only, two such literals still read as a
consistent rename. Because case is folded outside quotes (#391),
`_unquoted_literals` and `_selector_text` re-quote the unquoted literals the
AST *marks* as literals (static CALL target, INVOKE method literal, STOP
literal, EVALUATE `WHEN` Literal with `quoted` and Range bounds with
`start_quoted` / `end_quoted`), so a case-only difference there still breaks
Type-1. Where the AST does not mark them -- CANCEL targets, ACCEPT ... FROM
ENVIRONMENT names, EXEC CICS option values, literal arguments inside a COMPUTE
`expression`, XML/JSON `clause_text` -- a case-only literal difference reads as
the same text, so Type-1 can group them.

**Reuses `unused_variables.py`'s `_NON_IDENTIFIER_WORDS`/quoted-text
handling verbatim** rather than re-deriving a second reserved-word list --
unlike the walking-discipline tuples other analysis modules duplicate
(those differ per module's own traversal needs), "is this token a real
data-name" is a single well-defined question both modules ask, and a second
list would just drift out of sync with the first for no benefit.

`_names.IDENTIFIER_TOKEN_RE` (the Type-2 renaming token) accepts a digit-led
user word (`1ST-NAME`); see [data-use.md](data-use.md).

### Paragraph fingerprints (cross-file clones)

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

## TechnicalDebtAnalyzer

```python
report: TechnicalDebtReport = TechnicalDebtAnalyzer(weights=None, size_threshold=50).analyze(ast)
# report.score: float (0-100, higher = more debt); report.grade: "A".."F", or None (see below)
# report.parse_error_count / report.caveats  -- set from analyze(..., parse_error_count=N)
# report.components: list[ComponentBreakdown]  -- one per weighted component, each with its own findings
# report.top_offenders: list[OffenderProcedure]  -- worst procedures, with reasons
# report.complexity_summary / .redundancy_summary / .weights  -- echoed into to_dict()
```

Composite, explainable debt score combining `ComplexityAnalyzer`,
`RedundancyAnalyzer`, and control-flow smells from `ProgramFlowAnalyzer`/
`RecursionRiskAnalyzer` (all four sub-reports can be passed in precomputed
via keyword args to skip redundant passes). Every point on the score traces
to a named finding in some component's `findings` list -- never a bare,
unexplained number.

**Four weighted components** (`DebtWeights`, defaults `complexity=30`,
`redundancy=30`, `control_flow=30`, `size=10` -- sum 100 -- but any
positive weights work -- the composite normalizes by the weights' actual
sum): `complexity` (share of procedures rated MODERATE/HIGH, weighted units
`moderate*1 + high*3` over `3*total`), `redundancy` (mean of
`dead_ratio`/`unused_ratio`/cloned-statement ratio), `control_flow` (capped
penalties: GO TO density, `ALTER` usage via `find_all_by_type` on the
unit's own PROCEDURE division -- `ASTNode.find_all_by_type` is a *deep*,
cached subtree search via `traverse_depth_first()`, so called on the program
node it would also count every contained program's ALTERs against the
container (a contained program hangs off the `CobolProgram` node, never off
its divisions) -- HIGH-severity `RecursionRiskAnalyzer` risks, unreachable-node
ratio), `size` (share of procedures over `size_threshold`, default 50
statements). Final score is the weighted average of the four 0-100
component scores, clamped to `[0, 100]` and **rounded to the 2 decimals
`to_dict()` serializes before grading** (grading the raw float lets
accumulated noise like 10.000000000000002 push a score the JSON prints as
10.0 across the A/B band edge); grade bands are A <=
10, B <= 25, C <= 45, D <= 70, else F. The complexity/size components
carry a `"no procedures to rate"` finding (rather than an empty findings
list) on a program with no procedures, per the every-point-explained
contract. Pinned by
`tests/regression/test_audit_2026_08_16_analyzers.py::TestA7GradeMatchesSerializedScore`.

**Parse errors withhold the grade** (see #397). A file that mostly failed to
parse hands over a near-empty AST, which would score 0.0 and grade "A".
`analyze(ast, parse_error_count=len(result.errors))` keeps the
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

## See also

* [../analysis.md](../analysis.md) -- routing page, calling conventions, module map
* [data-use.md](data-use.md) -- same-named data items, IO sequencing (which
  shares the execution-order walk ideas)
* [lint.md](lint.md) -- `dead-code`, `recursion-check` and `complexity` as lint rules
* [fixtures-support.md](fixtures-support.md) -- `ConstantFolder` and
  invocation counts, which reuse the paragraph ordering rules
* [../generators.md](../generators.md) -- flowcharts and `ScenarioPlanner`,
  which consume `ProgramFlowReport`
* [../cli.md](../cli.md) -- `dead-code`, `program-flow`, `recursion-check`,
  `complexity`, `redundancy`, `health`
* [../batch.md](../batch.md) -- `scan --clones` (`cross_file_clone_groups`)
* [history](../history/analysis.md) -- dated fix write-ups behind these rules
