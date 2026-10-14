---
type: Module
title: Generators
description: Output generators — flowcharts from a program-flow report, synthetic CSV test data from a copybook record layout, and the gen-fixtures program-scoped test-data initiative (layout index, program fixture bundles, scenario planning, all wired into the CLI).
tags: [generators, flowchart, copybook, test-data, csv, mermaid, dot, program-layout, fixtures, scenarios, layout-offsets]
timestamp: 2026-10-13T00:00:00Z
---

# Overview

`cobolparser/generators/` — modules that turn parsed COBOL into an output
artefact rather than an analysis report.

| File | Produces |
|------|----------|
| `flowchart.py` | Mermaid / Graphviz DOT flowcharts from a `ProgramFlowReport` |
| `copybook_data.py` | Backwards-compatible re-export shim for copybook → CSV; implementation in `data/` |
| `data/` | Copybook test data generation — modular internal implementation |
| `program_fixtures.py` | `ProgramFixtureGenerator` — whole-program `FixtureBundle`s (Phase 3/6) |
| `scenarios.py` | `ScenarioPlanner` — constraints + CFG -> named scenarios (Phase 5) |
| `verification.py` | `verify_scenario` — does a scenario's own generated data satisfy the branch it is named for? |

**Import architecture: `__init__.py` is lazy (`__getattr__`-based), not
eager.** `program_fixtures.py` genuinely depends at runtime on
`cobolparser.analysis.constraints`/`.domains`/`.program_flow` (Phase 6 added
the first two), which are themselves reachable from other
`cobolparser.analysis` modules that need `generators.data.*` utilities
(`FieldSpec`, `ValueFactory`, `ProgramLayoutIndex`). Eagerly importing every
submodule at package-init time — the original shape — meant the *first*
touch of either package from anywhere in the process could fail with
"partially initialized module", depending on unrelated import order
elsewhere. This surfaced three separate times as the initiative grew
(`bundle.py` ↔ `boundary_inventory.py` in Phase 4, `constraints.py` ↔
`program_fixtures.py` and `domains.py` ↔ `scenarios.py` both in Phase 6)
before the third occurrence prompted fixing the actual root cause instead of
patching each edge individually: `__init__.py` now resolves every public name
through `__getattr__` on first access (mirroring
`cobolparser.analysis.__init__`'s already-established pattern), so importing
`cobolparser.generators` itself never touches `program_fixtures.py` (or
anything else) until a caller actually asks for
`ProgramFixtureGenerator`/`FixtureBundle`/etc. `__all__` is unchanged — same
21 public names as before; `__getattr__` does not change `dir()` output, only
what resolves on attribute access.

# Flowcharts (`flowchart.py`)

`MermaidFlowchartGenerator` / `DotFlowchartGenerator` consume a
`ProgramFlowReport` (see [analysis.md](analysis.md)) and emit a diagram
string. `FlowchartOptions` controls statement counts, edge labels,
fall-through edges, unreachable nodes, and synthetic external-CALL nodes.
Driven by `cobol-parser program-flow --format mermaid|dot`. Node ids and
labels come from `FlowNode.key` (the `qualified_name` when two paragraphs
share a name, issue #258), so `X1 OF S1` and `X1 OF S2` are drawn as two
nodes (`X1_OF_S1`, `X1_OF_S2`) and edges, which name nodes by key, attach.

**Black reformat (2026-08-13, no behavior change):** `_escape_mermaid_label`
and `_is_empty_if_arm` were reformatted to match the CI-pinned
`black==26.3.0` (a local newer black had already reformatted them
differently) — whitespace-only, no logic change.

**External-call nodes read the analyzer's real shape (2026-08-12 fix, audit
A-A2).** Both generators used to read `ext.get("target", "")` off
`report.external_calls`, but `EdgeCollector.process_call`
(`analysis/program_flow/edges.py`) emits the called program under the
`"program"` key -- so `EXT_*` nodes NEVER rendered from a real
`ProgramFlowAnalyzer` report, only from hand-built dicts. There was also a
case mismatch: `FlowEdge.target` is uppercased by the collector while
`call_info["program"]` keeps the source's original case, so a lowercase
`CALL 'subpgm'` literal produced a CALL edge pointing at an `EXT_` id no
node declared. Module-level `_external_call_target()` now reads
`"program"` (keeping `"target"` as a fallback for hand-built legacy dicts)
and uppercases the name so node ids agree with edge endpoints. Pinned by
`tests/unit/test_flowchart_generator.py::TestExternalCallEndToEnd` (real
COBOL through the analyzer into both renderers, plus the legacy-dict
fallback).

**Recursion/GO TO edge styling, terminal exit nodes, THRU badges
(2026-08-11):** both generators now render three things identically in
substance, differing only in each target format's own attribute syntax:

- **Recursion / GO TO edge distinction.** Module-level
  `_recursion_pairs(report)` returns every `(source, target)` pair that
  closes a `PERFORM_RECURSION` cycle (from `report.cycle_details`);
  `_PERFORM_EDGE_TYPE_VALUES` / `_GOTO_EDGE_TYPE_VALUES` (also
  module-level, shared by both generator classes) classify an edge's
  `.value` string. A PERFORM-family edge closing a recursion cycle gets
  gold-dashed styling; any GO TO-family edge (`GOTO`, `GOTO_DEPENDING`,
  `ALTER`) gets magenta-dashed styling — **Mermaid** via a `linkStyle N
  <css>` line per styled edge (`_RECURSION_LINK_STYLE` /
  `_GOTO_LINK_STYLE` constants; `N` counts every `-->`/`==>`/`-.->` link
  Mermaid will see, in the order `generate()` writes them to `lines` —
  which includes the exit-statement terminal-node links emitted *before*
  the edges loop, not just the edges loop's own emitted (non-skipped)
  edges. `link_index` is seeded with `terminal_link_count` (the number of
  `{nid} --> {exit_id}` lines the terminal-node loop actually wrote) before
  the edges loop starts counting; a hidden fall-through edge still does not
  consume an index of its own. **Bug fixed 2026-08-11:** `link_index` used
  to start at 0 regardless of the terminal-node loop, so in any program with
  both a terminal node and a styled edge, every `linkStyle N` line pointed
  at the wrong arrow, off by the terminal-link count. DOT has no analogous
  bug — its `color`/`style` are set as attributes directly on each `->`
  edge statement, with no global, order-dependent index to get out of sync.
- **Terminal exit nodes.** One extra node per `FlowNode` carrying
  `exit_statement_kind`/`exit_statement_location` (see
  [analysis.md](analysis.md)'s `ProgramFlowAnalyzer` section), labeled
  `"{kind} @ {line}"` (ASCII `@` since 2026-08-12 — see "Label fidelity"
  below), positioned right after the main node loop and
  before external-call nodes in both generators — Mermaid emits `(((...)))`
  triple-circle syntax plus a `terminal` classDef
  (`fill:#1b1b1b,stroke:#c1121f`); DOT emits `shape=doublecircle` with
  matching `fillcolor`/`fontcolor`. Both respect `show_unreachable`
  identically to the main node loop. The terminal id is normally
  `f"{nid}_EXIT"` (`nid` = the paragraph's own allocated id), but the
  chart's `_IdAllocator` (see "One id allocator per chart" below) falls
  back to `{nid}_FLOWEXIT`, then an incrementing numeric suffix, whenever
  that id is already taken (e.g. by a real paragraph's sanitized id). **Bug fixed
  2026-08-11:** `PERFORM X THRU X-EXIT` is a common COBOL range idiom, so a
  program can legitimately contain a paragraph literally named e.g.
  `9000-TERM-EXIT`; before the fix, that paragraph's own node id
  (`N_9000_TERM_EXIT`) silently collided with paragraph `9000-TERM`'s
  synthetic terminal-node id, merging two distinct nodes into one in both
  renderers.
- **`[THRU n]` edge-label badges.** A `FlowEdge` carrying `thru_target` +
  `range_members` (a `PERFORM ... THRU ...` / SORT|MERGE procedure range)
  renders as a single arrow from the range's start to its *first* member,
  badged `[THRU n]` (`n = len(range_members)`) — not as a second,
  redundant arrow spanning the whole range. Both generators' edges loops
  skip any edge whose `.value` ends in `"_THRU"` (the second, would-be
  duplicate arrow) unconditionally, regardless of `show_fall_through`. This
  requires the *base* (non-`_THRU`) edge to itself carry `thru_target`/
  `range_members` — `EdgeCollector.process_perform` (`edges.py`) has always
  done this; `process_sort`/`process_merge` did not (**bug fixed
  2026-08-11**: the base `SORT_INPUT_PROCEDURE`/`SORT_OUTPUT_PROCEDURE`/
  `MERGE_OUTPUT_PROCEDURE` edge had `thru_target=None, range_members=[]`,
  so a SORT/MERGE THRU range rendered neither the second arrow (correctly
  skipped) nor the badge (nothing to badge) — the range vanished from the
  diagram entirely). All three `process_*` methods now compute the range
  once and pass it to both the base edge and its `*_THRU` sibling.

- **Quoted edge labels.** `MermaidFlowchartGenerator` wraps every non-empty
  edge label in double quotes (`-->|"label text"|`), reusing the `#quot;`
  entity escape already used for branch/arm condition text. **Bug fixed
  2026-08-11:** labels were previously written unquoted between the `|...|`
  pipes; Mermaid's flowchart lexer reads an unquoted `(` or `[` there as the
  start of a node shape (`PS`/`SQS` tokens), not literal text, so a loop
  annotation (`... (loop)`), `CALL_DYNAMIC`'s `"CALL (dynamic)"` label, or a
  `[THRU n]` badge broke parsing entirely — e.g. a `PERFORM UNTIL` loop edge
  in `legacy-application/cobol/DEPTBMP.cbl`. DOT is unaffected — `_dot_str`
  already quotes every DOT label.

**Label fidelity (2026-08-12):** three fixes driven by how the VS Code
Program Flow webview (Mermaid v11, `htmlLabels:false`,
`securityLevel:'strict'`) actually renders the emitted text:

- **ASCII-only output.** Both generators' emitted labels are pure ASCII:
  the exit-terminal separator is `@` (was U+00B7 `·`) and
  `GOTO_DEPENDING`'s short label is `GO TO ... DEPENDING` (was U+2026
  `…`). On Windows the CLI writes stdout in the console's locale encoding
  (cp1252) while consumers decode UTF-8, so any non-ASCII label character
  rendered as U+FFFD (`GOBACK � 118` in the webview). Pinned by the
  `test_output_is_ascii_only` tests (`out.encode("ascii")`).
- **`"`/`<`/`>` escaped in every Mermaid label.** Module-level
  `_escape_mermaid_label()` maps `<`/`>` to `#lt;`/`#gt;` and `"` to a
  plain apostrophe in branch conditions, arm labels, and edge labels.
  Mermaid v11 with `htmlLabels:false` silently swallows a bare `>` from
  label text (`WS-PURGE-ERRORS > ZERO` rendered as `WS-PURGE-ERRORS
  ZERO`, `>=` as `=`) while `<`/`<>` happen to survive; the `#name;`
  entity form renders correctly through both the lexer and the sanitizer
  for `<`/`>` only — `#62;`-style *numeric* entities and `#quot;` both
  come out as literal `&#62;`/`&quot;` text in SVG-text label mode
  (verified empirically against Mermaid 11.12), which is why `"` is
  substituted rather than entity-escaped: display-only text, and `'Y'`
  is how the COBOL literal read anyway. This supersedes the earlier
  bare `.replace('"', "#quot;")` used since the 2026-08-11 quoted-edge-
  label fix. DOT labels are not escaped — Graphviz has no such mangling.
- **DOT string escaping (2026-09-28).** Edge attribute values now go
  through `_dot_str` like node labels: a PERFORM UNTIL / IF condition with
  a `"` inside an apostrophe literal was emitted raw into `label="..."`,
  ending the DOT string early. And the node label's `\n (N stmts)` break is
  appended *after* `_dot_str` -- passed through it, the `\n` became `\\n`,
  which Graphviz renders as a literal backslash-n.
- **DOT keyword ids (2026-09-28).** `_sanitize_id` output is a valid bare
  DOT ID *except* for the reserved words `node`/`edge`/`graph`/`digraph`/
  `subgraph`/`strict` (case-independent in Graphviz). A paragraph named
  `NODE` was emitted as `NODE [label=...]` -- the default-node attribute
  statement -- and `MAIN -> STRICT;` was a Graphviz syntax error (verified
  with `@hpcc-js/wasm-graphviz`). `_dot_id()` quotes exactly those ids at
  every DOT node/edge emission site. Mermaid is unaffected: its flowchart
  keywords (`end`, `style`, `class`, `click`, ...) only bite in lower case,
  and every id here is upper case (verified with mermaid 11 `parse()`).
- **One id allocator per chart (#266, 2026-10-05).** `_sanitize_id` is
  lossy: paragraphs `A-B` and `A_B` both sanitize to `A_B`, and an external
  program `SUBPGM` (`EXT_SUBPGM`) meets a paragraph named `EXT-SUBPGM` --
  the colliding nodes were silently merged and every edge into either
  landed on the merged box. Each `generate()` builds one
  `_IdAllocator.for_report(report)`, mapping `(kind, name)` -> a unique id
  (kinds `node` = paragraph/section/branch/arm keyed by raw name, `ext` =
  called program, `exit` = terminal). Paragraphs are allocated first so
  they keep the plain id; a later collision gets a numeric suffix
  (`A_B_2`, `EXT_SUBPGM_2`). Every node declaration and edge endpoint goes
  through it; `_hidden_ids()` and the skipped-empty-arm set hold *raw*
  names. A chart without collisions is byte-identical to before.
- **`show_unreachable=False` hides what the paragraph owns (2026-09-28).**
  Only the paragraph's own node line (and its terminal node) was skipped;
  its outgoing PERFORM/GO TO/CALL edges, its IF/EVALUATE decision and arm
  boxes, and external nodes called only from it were still emitted, and
  both renderers re-create an undeclared edge endpoint as a bare box -- the
  hidden paragraph came back unstyled. `_hidden_ids()` (paragraph + its
  branch/arm ids) and `_external_targets()` (drops a CALL made only from a
  hidden paragraph) are shared by both generators.
- **Arm boxes show statement summaries.** `BranchArm.summary` (see
  [analysis.md](analysis.md)'s statement_text section) renders instead of
  the bare `THEN`/`ELSE`/`WHEN x` keyword, which duplicated the edge label
  and said nothing about the arm's behavior: Mermaid emits
  `["MOVE 8 TO RETURN-CODE\n+2 more"]` (in-label `\n` line break, count
  from `statement_count`), DOT emits `label="MOVE 8 TO RETURN-CODE (+2
  more)"` (single-line — a `\n` would collide with `_dot_str`'s backslash
  escaping). Arms without a summary (hand-built reports) keep the keyword
  label. Additionally, module-level `_is_empty_if_arm()` drops the empty
  ELSE arm the scanner synthesizes for every IF with no ELSE clause (and
  its `IF_ELSE` edge — otherwise Mermaid/DOT would auto-recreate the node
  from the dangling edge). EVALUATE arms are never dropped. Stacked WHENs
  (`WHEN 'A' WHEN 'B' stmt`) already arrive as one arm labelled
  `WHEN A / WHEN B` (the scanner groups them, #314), so an EVALUATE arm that
  is still empty is a WHEN deliberately left with no action.

Reference tests: `tests/unit/test_flowchart_generator.py` —
`TestMermaidFlowchartGenerator` (linkStyle/terminal-node/THRU-badge
sections, plus `test_linkstyle_index_accounts_for_terminal_node_links` and
`test_terminal_id_does_not_collide_with_real_exit_paragraph` pinning the
two composition-bug fixes above), `TestDotFlowchartParity` (the DOT-side
mirror), `TestSortThruEndToEnd` (real-COBOL-through-the-analyzer proof
that a SORT OUTPUT PROCEDURE THRU range now reaches both renderers), and
`TestMermaidLabelFidelity`/`TestDotLabelFidelity`/`TestLabelFidelityEndToEnd`
(ASCII-only output, `#lt;`/`#gt;` escaping, arm summaries, empty-IF-arm
dropping).

# Copybook Test Data (`data/` package, shimmed via `copybook_data.py`)

Turns a copybook into a CSV: **one column per elementary field, one row per
generated record**. Driven by `cobol-parser gen-data` (see
[cli.md](cli.md)).

The implementation is modular in `cobolparser/generators/data/` (internal
refactor; `copybook_data.py` is a backwards-compatible re-export shim with
zero API change).

```python
from cobolparser.generators import CopybookDataGenerator, DataGeneratorOptions

generator = CopybookDataGenerator(DataGeneratorOptions(rows=100, seed=7))
dataset = generator.generate_from_file("CUSTOMER.cpy")
dataset.write_csv("customers.csv")
```

## Internal Implementation Modules

`cobolparser/generators/data/` decomposes the copybook-data generation logic
into focused, reusable modules:

- **`options.py`** — `DataGeneratorOptions` configuration (rows, seed, include/exclude flags, value hints).
- **`errors.py`** — `CopybookLayoutError` exception for layout validation failures.
- **`layout.py`** — `FieldCategory` enum, `FieldSpec` dataclass, `flatten_record()` function; the record flattening rules that turn a nested `CobolDataItem` tree into a flat list of columns. Also exports `expand_condition_values()` for condition-name value expansion.
- **`layout_offsets.py`** — `LayoutItem` dataclass, `compute_record_layout()` function; byte-offset and byte-length computation for individual records, used by data-item hover details and offset-based lookups (Task 2-6: initial implementation + nested group recursion + REDEFINES-chain slot sharing + OCCURS footprint multiplication + cross-level OCCURS DEPENDING ON ambiguity propagation). Sibling layout (record root and every group) runs through a shared `_layout_siblings()` helper: a "slot" is a contiguous run of `[base item, redefine 1, redefine 2, ...]` — COBOL requires a REDEFINES entry to immediately follow what it redefines — every slot member starts at the same offset, the slot's footprint (`slot_footprint`) is the max footprint across its members, and the running offset advances past the slot once. `_walk_redefines_chain()` resolves a possibly multi-hop REDEFINES chain (A redefines B redefines C) within one sibling list, cycle-guarded. A childless record root (bare 77-level or elementary 01-level) is still special-cased to report its own elementary byte length rather than 0. **Task 5: OCCURS multiplies footprint, never `byte_length`.** `_layout_item()`'s return value (`one_occurrence_length`) is always exactly one occurrence's size and is what gets stored as the emitted `LayoutItem.byte_length` — this fixes a real gap in `CobolDataItem.calculate_size()`, which never applies a *group* item's own OCCURS multiplier. `_layout_siblings()` separately computes each member's `member_footprint` (`one_occurrence_length * (occurs.max_times or occurs.min_times or 1)` for every OCCURS, fixed or `DEPENDING ON` — an ODO table reserves its **maximum**, the storage IBM Enterprise COBOL allocates and the width `encoding.py` writes, so an enclosing group's and the record's `byte_length` equal `GeneratedDataset.record_length()`; until issue #247 (2026-10-04) an ODO table reserved one occurrence only, so a group holding `OCCURS 2 TO 5` reported less than its own minimum. `occurs.depending_on` is also what flips `is_ambiguous = True` for every sibling laid out after it: those offsets move with the counter, the maximum is only the allocation) and folds *that* into `slot_footprint`/`total`/`offset`, so a later sibling's offset correctly advances past every occurrence. `_occurs_dict()` populates the `occurs` field (`{"min": ..., "max": ...}` or `None`) on every non-level-88 `LayoutItem`, elementary or group.

  **Task 8: `compute_program_data_items(ast: CobolProgram) -> dict[str, Any]`** —
  the program-wide entry point, returning `{"items": [...], "unresolved":
  [...]}` (JSON-ready; `unresolved` always present for forward
  compatibility, though nothing populates it yet). Walks every DATA
  DIVISION section (FILE, WORKING-STORAGE, LOCAL-STORAGE, LINKAGE) and
  calls `compute_record_layout()` on each section's top-level (01/77)
  records. Also closes a gap `compute_record_layout()` leaves by design:
  that function lays out one record in total isolation (no knowledge of
  its section siblings), so its record-root `LayoutItem` always hardcodes
  `redefines_chain=[]` — correct for a record with no REDEFINES, wrong for
  a top-level 01 that redefines a *different* top-level 01 in the same
  section (nested REDEFINES, inside a group, was already handled — see
  Task 4 above — via that group's own `_layout_siblings()` sibling list).
  `compute_program_data_items` builds a `siblings_by_name` dict from each
  section's top-level records and, for any record with `.redefines` set,
  reuses `_walk_redefines_chain()` (same helper `_layout_siblings()`
  already uses, generic over whatever sibling dict it's given) to
  overwrite that record's root `redefines_chain` in place before
  appending its flattened layout to the output. `compute_record_layout()`
  itself is untouched — same signature, same behavior, still used
  directly by Tasks 2-7's unit tests with no siblings context. Byte
  offsets are unaffected either way: each top-level record is
  independently record-relative and correctly starts at byte 0 whether or
  not it redefines a section sibling.

  **Final-review fix: root-level level-88s were silently dropped.**
  `compute_record_layout()` builds the record's own root `LayoutItem` on
  a separate inline construction path (the `out.insert(0, LayoutItem(...))`
  above), which bypassed `_layout_item()`'s condition-children loop
  entirely — so a level-88 declared directly under a 01/77 record root
  with no intervening group level (COBOL's most common flag idiom, e.g.
  `01 WS-EOF-FLAG PIC X. 88 WS-EOF VALUE "Y".`) never made it into the
  output. A level-88 nested under a 05+ group always worked, since those
  go through `_layout_item()`. Fixed by mirroring `_layout_item()`'s
  condition-children loop for the root itself right after the root
  `LayoutItem` is inserted, reusing the root's own `byte_offset=0`,
  `byte_length=record_length`, and `offset_ambiguous=False`.

  **Final-review fix: a misnested level-77 could corrupt an unrelated
  preceding record's byte_length.** This is a pre-existing parser
  behavior, not a parser bug fix: the hierarchy builder nests items
  purely by level-number comparison, so a `77`-level item declared
  immediately after an `01` record (whose deepest preceding item is, say,
  a `05`) becomes that `05`'s AST *child* (77 > 05), not a section-level
  sibling. Since `_direct_data_children()` previously counted that
  misnested 77 as a real data child, `_layout_item()`'s `if
  data_children:` branch misclassified the `05` as a GROUP item and
  discarded its own elementary PIC/byte_length. Fixed with a guard in
  `_direct_data_children()` itself (not in `compute_program_data_items`):
  a level-77 item is, by COBOL's own level-number rules, never
  legitimately subordinate to anything, so it's excluded from every
  `_direct_data_children()` call site — the lower-risk fix location,
  since it doesn't require duplicating tree-walking logic in the
  program-wide entry point.

  **Follow-up fix: the excluded 77 was silently dropped when it was its
  misnested parent's *only* child.** The guard above stops corruption but
  doesn't put the 77 anywhere — when the parent had other real children
  (the `05 WS-A` case) that's invisible, but when the 77 was the
  misnested parent's *only* AST child (`01 WS-REC. 77 WS-CTR ...`, no
  intervening `05`), `_direct_data_children()` now returns empty for
  `WS-REC` too, so `compute_record_layout()` falls into its childless-root
  branch and treats `WS-REC` as if it were itself elementary with no
  PICTURE (`is_group=False, byte_length=0`) — and `WS-CTR` never appears
  anywhere in `compute_program_data_items()`'s output, `section.data_items`
  never having contained it to begin with. Fixed in
  `compute_program_data_items()` (not by touching the shared
  `_direct_data_children()` guard again): a new `_find_misnested_level_77_items()`
  helper walks each top-level record's *raw*, unfiltered AST subtree to
  recover every level-77 item hidden by the guard, and each one is
  re-rooted as its own independent record via `compute_record_layout()`
  — same as a genuine section-level 77 — including resolving its own
  `redefines_chain` against the section's top-level siblings, exactly
  like the top-level-record path just above it does. This recovers the
  77 in *both* shapes (only-child and has-siblings), not just the
  previously-unhandled one.

  **Task 6: ambiguity propagates across nesting levels, not just within one sibling list.** Task 5's `is_ambiguous` flag was local to each `_layout_siblings()` call — an OCCURS ... DEPENDING ON table nested *inside* a group only made that group's own children ambiguous; the group's own sibling in the *parent* list still got a concrete, wrong offset. `_layout_siblings()`/`_layout_item()` now both return `tuple[int, bool]` (`footprint, trailing_ambiguous`) instead of a bare `int`: a group's nested `_layout_siblings()` call reports whether *it* ended ambiguous, `_layout_item()` passes that straight through for group items (elementary items always report `False` here — their own direct `occurs.depending_on` is already handled by the caller's existing check), and the calling `_layout_siblings()` folds a `True` nested signal into its own `is_ambiguous`, exactly like a direct ODO child would. Propagates through arbitrarily many nesting levels for free (each level only needs its own direct child's signal) — confirmed with a two-level nesting test, not just by inspection. `compute_record_layout()`'s public contract (the `LayoutItem` list and every field on it) is unchanged; only the two private helpers' internal return shape changed. Root cause of the two brief-derived tests initially failing during development: unrelated to this propagation gap — fixed-format COBOL only recognizes columns 8-72 as the code area, and the brief's literal one-line `OCCURS 1 TO 10 TIMES DEPENDING ON WS-COUNT.` fixture at that indentation pushed `ON WS-COUNT.` past column 72, where the lexer silently drops it with no error, so the ODO parsed as a fixed `OCCURS 10` with `depending_on = None`. Test fixtures now wrap `DEPENDING ON <var>` onto a continuation line to stay inside the code area.
- **`values.py`** — `ValueFactory` class; generates synthetic values for a field, respecting PICTURE/USAGE/level-88 domain/VALUE/semantic hints. `USAGE INDEX`/`POINTER` short-circuit to `"0"` *without drawing from the RNG* — they are storage, not data, and reach the factory PICTURE-less, where they used to fall through to the numeric path's 9-digit default and emit a random number that looked like data. Not drawing is what keeps a copybook with no such field byte-identical for a given seed. A freely drawn number is built exactly, never through float (issue #285): `whole + random()` used to make a `PIC 9(18)` value a float64 and drop every digit past ~15, so most rows ended in `00`. The whole part is an exact `randint`; the fraction is still exactly one `random()` draw (so the RNG stream, and every later field in the record, is unchanged), taken through its repr up to 15 places and as its exact binary value beyond (`_FLOAT_FRACTION_DIGITS`). A field of 11 or fewer total digits is byte-identical for a seed; 12-15 digits can differ, rarely, in the last decimal place, where float was already rounding (0.01% of `9(9)V9(3)` rows, ~3.5% of `9(13)V99`); past 15 digits most rows change (~96% of `9(18)`). `_format_number` and the P-scaled draw run under the module's `_EXACT` 100-digit Decimal context: the default 28 digits rounded 29-31 digit fields, and VALUE / level-88 literals that wide, on the first `abs()` or subtraction.
- **`storage.py`** — a re-export shim (2026-09-05) for **`cobolparser/_storage.py`**, which the implementation moved to so `cobolparser.models.data_items.CobolDataItem.calculate_size` could defer to it as well: this package's `__init__` eagerly imports `program_layout`, which imports `cobolparser.models`, so a model importing this module directly would close an import cycle. `_storage.py` sits beside `_errors.py` and, like it, has zero internal dependencies. Every existing importer of `storage.py` is unchanged. It remains the package's single authority on **how many bytes a data item occupies**: `storage_size()`, `binary_byte_length()`, `packed_byte_length()`, and the `USAGE` frozensets everything else classifies against. Zero dependencies beyond the stdlib, deliberately — `layout.py`, `layout_offsets.py` and `encoding.py` all import it, which is what stops a record image's field widths from drifting apart from the offsets `data-items` reports. Two cases the older per-module copies of the arithmetic got wrong and this fixes for every caller at once: `USAGE INDEX` (no PICTURE, so it was sized as **zero bytes**, silently collapsing every offset after it) and a DISPLAY item with `SIGN IS SEPARATE` (a byte the PICTURE's character count does not include).
- **`encoding.py`** — record-image encoding: the display value from `values.py` rendered into the bytes a COBOL program would actually read, at fixed or variable record length. See "Record images" and "Fixed- and variable-length records" below.
- **`views.py`** — `PlacedField` / `RecordView` / `RecordViews` / `build_record_views()`: the offset-annotated byte map the *decoder* reads a record through. See "Record views and decoding" below.
- **`decoding.py`** — the inverse of `encoding.py`: `RecordDecoder`, `decode_field()`, `decode_record()`, `DecodedField` / `DecodedRecord` / `DecodeResult`, `decoded_hex_dump()`. Backs the `decode` CLI subcommand. See "Record views and decoding" below.
- **`compare.py`** — `compare_records()` / `compare_files()`, `CompareResult`, `RecordDifference`, `FieldDifference`, `CompareError`: two decoded files through one view, compared field by field, paired by key or by position. Backs the `compare` CLI subcommand. See "Record compare" below.
- **`dataset.py`** — `GeneratedDataset` class; holds rows, fields, seed, and `to_csv()` / `write_csv()` / `to_dicts()` export methods, plus the record-image trio `to_records()` / `write_records()` / `to_hex_dump()` and the length quartet `record_length()` / `minimum_record_length()` / `record_lengths(opts)` / `is_variable_length`.
- **`copybook.py`** — `parse_copybook_records()` function and `CopybookDataGenerator` class; the public entry points for copybook parsing and CSV generation.
- **`__init__.py`** — Package exports of the above plus re-exports for backwards compatibility.

All modules are importable from `cobolparser.generators.data`, and
`ValueFactory` + `flatten_record` are usable directly against any
`CobolDataItem` (not just a copybook-parsed one), supporting future
program-data-generation initiatives that build on the same value/layout logic.

## Public API

```python
CopybookDataGenerator(options: DataGeneratorOptions | None)
    .generate_from_file(path, *, record=None)   -> GeneratedDataset
    .generate_from_source(src, *, filename=..., record=None) -> GeneratedDataset
    .generate_from_record(item: CobolDataItem)  -> GeneratedDataset

parse_copybook_records(source, *, filename=...) -> list[CobolDataItem]
flatten_record(record, options=None)            -> list[FieldSpec]

GeneratedDataset:  .record_name .fields .rows .seed .header
                   .varying (VaryingLength | None)
                   .declared_lengths (list[int] | None)
                   .to_csv(*, line_terminator="\n")
                   .write_csv(path, *, line_terminator="\n")
                   .to_dicts() .to_dict()
                   .record_length()           # max / fixed-length LRECL
                   .minimum_record_length()   # every ODO table at its minimum
                   .record_lengths(opts=None) -> list[int]   # one per row
                   .is_variable_length        # bool: any ODO table at all
                   .to_records(opts=None) -> bytes
                   .write_records(path, opts=None)
                   .to_hex_dump(opts=None) -> str
EncodingOptions:   .charset (Charset.ASCII|EBCDIC)
                   .endian (Endian.AUTO|BIG|LITTLE|NATIVE)
                   .record_separator (bytes)
                   .record_format (RecordFormat.FIXED|VARIABLE
                                   |VARIABLE_BARE|AUTO)
                   .space .resolved_endian
                   .resolved_format(specs, *, varying=False)
RecordFormat:      StrEnum — fixed | variable | variable-bare | auto
                   .is_variable
encode_rdw(body_length) -> bytes        # RDW_SIZE == 4, MAX_VARIABLE_RECORD
encode_record(specs, row, opts, *, data_length=None)
record_length(specs) / minimum_record_length(specs)
row_record_length(specs, row, opts=None, *, data_length=None)
present_indexes(specs, row) -> list[int]
occurrence_count(control, cells) -> int
unresolved_odo_counters(specs) -> list[str]
RecordEncodingError(CopybookLayoutError)
FieldSpec:         .name .path .column .level .picture .usage .category
                   .size .integer_digits .decimal_digits .is_signed
                   .value_clause .condition_values .subscripts .redefines
                   .sign_clause .synchronized .occurs_depending_on
                   .odo_controls .odo_counter_bounds
                   .total_digits .scaling_leading (2026-09-10; read straight
                       off the item's own PictureClause at construction --
                       see below)
                   .qualified_name .storage_size .scaling_positions
                   .stored_digits .to_dict()
OdoControl:        .depending_on .subscript_index .min_times .max_times
```

**P-scaling: one canonical parse, not a second regex over the raw picture
string (2026-09-10).** `FieldSpec.scaling_positions` (signed `P` count:
positive trailing, negative leading, zero otherwise) and `.stored_digits`
(digit positions actually stored, `P`s excluded) used to come from a
module-level `scaling_positions(picture: str)` function that re-parsed the
raw picture text with its own regex — a second implementation of exactly
what `models.data_items.PictureClause._parse_scaled_pattern` already
decides while building the AST. `flatten_record`'s `_flatten_into` now
copies `picture.total_digits`/`picture.scaling_leading` straight onto the
`FieldSpec` at construction time (the same `picture.total_digits`
`generators/data/layout_offsets.py`, the `data-items` CLI, already reads
directly), and the two properties compute from those instead of re-deriving
anything. See [ast-models.md](ast-models.md)'s `scaling_leading` note and
[analysis.md](analysis.md)'s MoveTypeChecker section (`_is_non_integer_picture`
was the third independent P-scaling check; now reads `decimal_digits`
alone).

```python
VaryingLength:     .minimum .maximum .depending_on
                   .from_fd_clauses(clauses, *, record_size)
                   .build(minimum, maximum, depending_on, record_size)
DataGeneratorOptions:
                   .record_varying ((min, max) | None) — for a copybook
                   with no FD to read the range from
FieldCategory:     StrEnum — alphanumeric | alphabetic | national | numeric
                   | numeric-edited | alphanumeric-edited | float
CopybookLayoutError(ValueError)
```

All exported from `cobolparser.generators`.

## Parsing a copybook

A copybook is a DATA DIVISION *fragment*, not a compilable program, so
`parse_copybook_records` wraps it in a minimal `IDENTIFICATION`/`DATA`/
`PROCEDURE` skeleton before calling `parse_cobol` in `COLLECT_ALL` recovery.
Two shapes are detected first:

* **Whole program** (`IDENTIFICATION DIVISION.` / `PROGRAM-ID.` present) —
  parsed as-is, no wrapper.
* **Free-form fragment** — `_looks_fixed_format` decides the column
  convention; a free-form fragment is indented into Area B so the wrapper and
  the fragment agree. Without this, `normalize_fixed_format` would chop the
  first 7 characters off a copybook whose level numbers start in column 1.

  The verdict is **decisively free-form** when any line matches
  `_FREE_FORM_LEVEL_RE` (`^ {0,5}\d{1,2}[ .]`) — a one- or two-digit level
  number inside the sequence area. That cannot be a six-digit sequence
  number, and fixed-format code cannot start before column 8. One such line
  is enough, deliberately: a copybook that puts its `01` in column 1 but
  indents subordinate items past column 8 is common, and majority-scoring it
  would slice the `01` line away and lose the record root.

  Otherwise each non-blank line is scored on its **sequence area**
  (`line[:6]`): blank (indented code) or all-digit (a real sequence number,
  the NIST convention) is fixed-shaped; anything else is code starting too
  early to be fixed format. Ties resolve to **fixed** — mis-indenting a
  fixed-format copybook pushes real code past column 72 and truncates it,
  which is worse than leaving an already-indented free-form copybook alone.

Record roots are the **top-level** data items (`_top_level_items` excludes
anything nested under another item) at level 01/77. A copybook containing
only subordinate items (level 02-49, no 01 — a real idiom for copybooks
meant to be `COPY`d *inside* an existing record, e.g. NIST `K101A.CPY`)
gets a **synthesised** `<STEM>-RECORD` root rather than being rejected.
Anything else — procedure text, `SELECT` clauses, an empty file — raises
`CopybookLayoutError`.

## Flattening rules

| Construct | Default behaviour |
|-----------|------------------|
| Group item | Not a column; descended through |
| `OCCURS n` | One column per occurrence, `NAME(1)`, `NAME(2)`, … |
| `OCCURS … DEPENDING ON` | Expanded to the **maximum** bound |
| `REDEFINES` | **Excluded** — aliases bytes another column already covers |
| `FILLER` | **Excluded** — names nothing a consumer can address |
| Level 66 / 88 | Not storage; 88 VALUEs feed the parent's value domain |
| `COMP-1`/`COMP-2` | No picture → `FieldCategory.FLOAT` |
| Group `USAGE` / `SIGN` | Inherited by every subordinate elementary item with no clause of its own (IBM rule), resolved **in the parser** (`parsers/divisions/data.py` `propagate_group_usage_and_sign`, 2026-09-28) so `layout.py`, `layout_offsets.py` and `calculate_size` all see it. `CobolDataItem.usage_explicit` marks an entry's own USAGE; an explicit child wins for itself and below. A numeric-only group usage (COMP-3, BINARY, ...) is not pushed onto a non-numeric PICTURE; SIGN only lands on signed numeric items |
| `BLANK WHEN ZERO` | Carried as `FieldSpec.blank_when_zero`; the encoder writes a zero value as all spaces (charset's space), the decoder reads an all-space field as 0 with no error |

`include_redefines` / `include_filler` / `expand_occurs` / `max_occurs`
override the first four. Occurrence expansion is additionally subject to a
hard ceiling, `_MAX_OCCURS_HARD_CAP = 10_000` in `generators/data/layout.py`
— applied on top of (never widened by) a caller's own `max_occurs`, so a
pathological `OCCURS 5000000 TIMES` in the source cannot materialize
millions of `FieldSpec`s. `gen-data --max-occurs` and `gen-fixtures
--max-occurs` both expose the caller-facing cap; only the hard ceiling is
internal.

**Column naming.** Short field name by default; falls back to the dotted
qualified path when the *same name appears at more than one path* (COBOL
allows this, disambiguated by `OF`). Repeats from a single `OCCURS` table are
deliberately **not** treated as a collision — the subscript suffix already
distinguishes them, so `ITEM-CODE(1)` stays short instead of becoming
`REC.TAB.ITEM-CODE(1)`. Any residual duplicate gets a `_2` suffix; headers
are guaranteed unique.

## Value generation

Precedence, highest first:

1. **Level-88 condition values** — the field's declared domain. `VALUE 2
   THRU 4` is recorded by the parser as `["2", "THROUGH:4"]` and expanded
   here to `2,3,4` (capped at `_MAX_RANGE_EXPANSION = 64` so a six-digit
   range cannot blow up memory).

   Both endpoints are tested with `_INTEGER_LITERAL_RE` (`^[+-]?\d+$`), so a
   sign is accepted on either side, and the expansion iterates the **closed
   interval from the low bound** — a descending `VALUE 4 THRU 2` therefore
   yields 2 as well as 3 and 4 (iterating from `start` silently dropped the
   low endpoint). A non-numeric range (`VALUE 'AA' THRU 'ZZ'`) contributes
   only its endpoints.

   **Parser-level limitation:** when a range's *end* carries a sign, the
   parser does not emit the `THROUGH:` marker at all — `88 X VALUE -5 THRU
   -1.` arrives as `["-5", "-1"]`, indistinguishable from two discrete
   values. Such a range yields its endpoints only; there is nothing the
   generator can do about it from here. `VALUE -2 THRU 2` (signed *start*,
   unsigned end) is unaffected and expands normally.
2. **`VALUE` clause** — a constant for that column. Figurative constants
   (`SPACES`, `LOW-VALUES`, …) mean "no meaningful initial content" and fall
   through to generation instead of filling the column with blanks;
   `ZERO`/`ZEROS` yields `0`.
3. **Field-name heuristics** (`semantic_hints`, on by default) — NAME, CITY,
   STATE, ZIP, STREET, EMAIL, PHONE, DATE, TIME, AMT/BAL/SALARY, CNT/QTY,
   ID/KEY, FLAG/IND, CODE, DESC. Matched against hyphen/underscore-separated
   **whole words**, so `CUST-ZIP-CODE` matches `ZIP` but `ZIPPER` does not.
4. **PICTURE-driven random** — the fallback.

**Every path funnels through `_fit_text` / `_format_number`**, so a semantic
value can never violate the layout: the heuristics improve readability, the
PICTURE is the contract. Numeric values respect `integer_digits`,
`decimal_digits`, and sign; text is truncated to `size` and never padded (a
CSV cell carries the value; COBOL pads on the MOVE). Random alphanumeric
filler is additionally capped at `_MAX_RANDOM_TEXT = 32` characters — a
`PIC X(200)` comment field is more useful as a short readable token than as
200 characters of noise, and a short value is still valid for the field.
Semantic and declared values are not capped (they are already short).

`_format_number` (and `_fit_domain_value`/`render()`'s parse) is Decimal
throughout (2026-08-12 bug review): the old float64 internals silently
rounded any exact value past ~16 significant digits, so a solver-picked
`PIC 9(18)` witness rendered one-off (`...678` → `...680`) and the fixture
could never take the branch it targeted. Randomly generated floats are
unaffected (`Decimal(str(float))` round-trips); declared VALUEs, level-88
literals, and solved witnesses now render digit-for-digit. Pinned by
`tests/regression/test_bug_review_2026_08_12.py::TestWideNumericPrecision`.

`COMP-1`/`COMP-2` do not go through `_format_number` at all — they carry no
PICTURE to fit. `_float_value` draws one uniform over ±10,000 and hands it to
`_render_float(value, single=...)`, which quantises through binary32 for a
COMP-1 and renders to the 7 / 15 significant digits `decoding._decode_float`
uses, so the CSV cell is exactly what the record image gives back. See the
round-trip note under "Reading a record back".

`_format_number`'s `allow_random_sign` guards a subtle trap: a signed field
negates a freshly generated magnitude ~25 % of the time so negatives get
exercised, but values the copybook *declared* (levels 1-2 above) must be
formatted with `allow_random_sign=False` — otherwise `88 ST-LOW VALUE 5` on a
`PIC S9(3)` field emits `-5`, a value the copybook never permits. Pinned by
`test_declared_domain_values_are_never_randomly_negated`.

`_literals.py`'s `quote_literal()` re-emits a decoded literal doubling
each embedded `"`; its inverse `unquote_literal()` (2026-09-27) strips the
delimiters *and* collapses the doubled delimiter. Any consumer reading a
re-emitted literal back must use it: `generators/data/layout.py`
(`_strip_literal_quotes`, VALUE clauses), `analysis/constraints.py`
(`_strip_quotes`, branch witnesses) and `analysis/const_fold.py` (MOVE
sources) each stripped only the delimiters, so `VALUE "A""B"` generated
`A""B` and `MOVE '"'` folded to two quote characters. Pinned by
`tests/regression/test_doubled_quote_literal_values.py`.

`_strip_literal_quotes` also decodes a typed literal through
`_literals.typed_literal_content()` (2026-09-27, audit 2.1): the VALUE clause
now keeps `X"4142"` as written, and gen-data renders it `AB` rather than the
old `41`. Latin-1 code points, so an EBCDIC record image re-encodes the
characters, not the original bytes -- see `lexer.md` "Literal round trip".

**Signedness.** `PictureClause.is_signed` only reports an explicit `S`, so
`_is_signed()` additionally treats a numeric-edited picture carrying `+`,
`-`, `CR`, or `DB` as signed — `PIC -ZZ,ZZ9.99` is the canonical signed
display field and would otherwise never generate a negative.

**Edited pictures** contribute their *logical* numeric value, not the edited
display form: a CSV is consumed by tooling that wants the value, and the
edit mask is a presentation concern of the COBOL program. Likewise `COMP-3`
carries the decimal value, not packed bytes.  The *record image* is the other
side: there an edited field holds the edited bytes (2026-09-27; it used to
hold the CSV's logical value left-justified, e.g. `9516.07 ` for
`PIC $$,$$9.99`, which no COBOL program writes). `editing.py` implements
IBM's editing rules -- Z/`*` suppression, floating `$`/`+`/`-` strings,
fixed `+`/`-`/`CR`/`DB`/`$`, `B`/`0`/`/`/`,` insertion, the all-`Z`/all-`*`
zero case -- and every case in `tests/unit/generators/data/test_editing.py`
was checked byte for byte against GnuCOBOL 3. A floating `+`/`-` can land on
an insertion position inside its own string (`PIC +++,+++` edits -514 as
`   -514`, the sign where the comma would be); `deedit_numeric` reads the sign
there too (2026-09-28: it skipped insertion positions and decoded +514).

**Line terminator.** `to_csv()` and `write_csv()` share
`_DEFAULT_LINE_TERMINATOR = "\n"`, deliberately *not* the `csv` module's
RFC 4180 `"\r\n"`. Both must agree or the byte-identical guarantee breaks
across output paths — `gen-data -o out.csv` (which goes through
`write_csv`) would write different bytes than `gen-data > out.csv` (which
goes through `to_csv`) for the same seed. `write_csv` originally took the
`csv` default and did exactly that. Either method accepts
`line_terminator="\r\n"` for strict RFC 4180 output. Note that a test
comparing *parsed* rows cannot catch this — the regression test compares
raw bytes.

**Determinism.** `random.Random(seed)`. The same seed and copybook always
produce byte-identical CSV. When `seed is None` one is drawn and recorded on
`GeneratedDataset.seed`, so an interesting unseeded run is reproducible
after the fact (surfaced by `gen-data --describe`).

**`unique_fields`** retries a field up to 32 times for a distinct value, then
falls back to a deterministic counter — a narrow field (`PIC 9`, ten possible
values) asked for 40 unique rows must terminate, not spin.

## Record images (`data/encoding.py` + `data/storage.py`)

Everything above this point works in **display form** — a CSV cell holds
`72436.21` whether the field behind it is `PIC 9(7)V99` or
`PIC S9(7)V99 COMP-3`. That is the right currency for a CSV, and for
mockymock (whose splicer emits `MOVE <literal> TO <field>` and lets the
compiler pack it). It is the wrong currency for a **record image**: the
actual bytes a program would `READ`, or a dataset uploaded to z/OS.

`GeneratedDataset.to_records()` / `.write_records()` / `.to_hex_dump()`
produce that image; `gen-data --format record|hex` is the CLI on top of it
(see [cli.md](cli.md)).

**The layout has to change first.** The CSV-shaped defaults are deliberately
lossy — FILLER skipped, OCCURS capped — and both would put a *hole* in a
record image that still looked plausible. `DataGeneratorOptions
.for_record_image()` returns the byte-complete variant (FILLER in, REDEFINES
out, every occurrence expanded, no cap); the CLI applies it for
`--format record|hex` and prints a note to stderr so the overridden flags
don't look ignored. FILLER encodes as spaces/zeros regardless of its
generated cell — an empty cell falls through every encoder as exactly that,
so no encoder needs to know about FILLER. A FILLER with a `VALUE` keeps
that value, and one whose `VALUE` is `SPACES` / `LOW-VALUES` /
`HIGH-VALUES` / `NULL` (optionally after `ALL`) is filled with that byte
(`_filler_fill()`, 2026-10-12). The value generator reads those
figuratives as "no meaningful content" and draws random text for the cell,
which the encoder used to write into the record -- so the report-line gap
`05 FILLER PIC X(5) VALUE SPACES` between two columns came out as `QH7KZ`.

**Encodings, all verified against GnuCOBOL** by compiling a probe program
and reading back `LENGTH OF` plus the raw group bytes (the probe and its
output are reproduced in `tests/unit/generators/data/test_encoding.py`'s
module docstring — that suite is the regression guard):

| Storage | Bytes |
|---------|-------|
| DISPLAY alphanumeric / alphanumeric-edited | left-justified, space-padded, truncated; charset's space byte. Under `JUSTIFIED RIGHT` (`FieldSpec.justified`, 2026-09-28) the mirror image: right-aligned behind leading spaces, an oversized value losing its *leftmost* characters; the decoder strips that leading pad (it used to write `AB    ` where the MOVE leaves `    AB`) |
| DISPLAY numeric-edited | the edited form a `MOVE` leaves (`$1,234.56`, `- 12.34`, `012CR`, `12/34/56`) -- `editing.py`'s `edit_numeric()`; the decoder de-edits it back to the logical value with `deedit_numeric()`. A picture using a symbol `editing.py` does not model (`P`, a non-default currency sign) keeps the CSV text as is. Under `DECIMAL-POINT IS COMMA` (`FieldSpec.decimal_point_is_comma`, read off the `PictureClause`) both functions take `decimal_point_is_comma=True` and exchange `,`/`.` in the picture and the edited text: `Z.ZZ9,99` writes `1.234,56` (2026-09-28) |
| DISPLAY numeric (zoned) | one byte per digit; sign as an overpunch, or a real `+`/`-` byte under `SIGN IS SEPARATE` |
| `COMP-3` / `PACKED-DECIMAL` | two BCD nibbles per byte, sign nibble `C`/`D` signed, `F` unsigned |
| `COMP` / `COMP-4` / `BINARY` | two's complement, **always big-endian** |
| `COMP-5` | two's complement, **host byte order** — that is what "native binary" means |
| `COMP-1` / `COMP-2` | IEEE 754 binary32/binary64, byte order as `COMP-5` |
| `INDEX` / `POINTER` | binary zeros — an occurrence number and an address are not record content |
| `PIC N` / `USAGE NATIONAL` | **not modelled as UTF-16**: single-byte text in the record charset, space-padded to the (correct, 2-bytes-per-position) width; `encoding_caveats()` says so. A numeric national field (`PIC 9(5) USAGE NATIONAL`, 10 bytes since 2026-09-28) goes the same way -- `encode_field`/`decode_field` route `usage == "NATIONAL"` to text before the zoned branch |

**Overflow is not uniform across those rows, deliberately.** The zoned and
packed encoders run their magnitude through `_digits_string`, which
high-order-truncates to the PICTURE's digit count the way a COBOL numeric
MOVE does, so neither can overflow. Excess *decimal* places are truncated
too, never rounded (`_scaled_integer` and `edit_numeric` both use
`ROUND_DOWN`, 2026-09-28): `9.999` into `9V99` stores `999`. It used to round
half-even to `1000`, which the high-order truncation then turned into `000`.
The encoder, `edit_numeric` and the decoder's `_render_number` all scale
through an **exact** `decimal.Context` rather than the default one, whose 28
significant digits silently rounded a 31-digit `ARITH(EXTEND)` field
(`S9(29)V99 COMP-3` holding `...456789.01` decoded as `...456790.00`). The binary encoder has no such step: a
value that does not fit the field's *byte width* has no representation at
all, so it raises `RecordEncodingError` rather than silently reshaping the
bytes. Nothing this package generates can reach it — `ValueFactory` respects
the PICTURE and a `VALUE` clause is clamped to it — but a caller handing
`encode_record()` a row of its own can. (A `# pragma: no cover` on that
branch used to claim `_digits_string` guarded it; it never ran there.)

**Overpunch conventions follow the charset**, not a separate knob: EBCDIC
zones the sign into the `C`/`D` nibbles (`-12345` → `F1F2F3F4D5`), ASCII sets
`0x40` in the signed digit's zone (`-12345` → `1234u`), which is what
GnuCOBOL writes *and* reads. The third convention in the wild — EBCDIC signs
transcoded to ASCII as `{ABC`/`}JKL` — is deliberately **not** offered:
there is no compiler available to verify an implementation of it against,
and both real destinations (a z/OS dataset, the local GnuCOBOL runtime) are
already covered.

**Byte order defaults to `Endian.AUTO`**, which reads the charset as a
statement of intent: an EBCDIC record is bound for z/OS and gets big-endian;
an ASCII one is bound for the local runtime and gets host order. `NATIVE`
forces host order, `BIG`/`LITTLE` pin it. `resolved_endian` is always one of
`BIG`/`LITTLE`, and every output path reports which was used rather than
leaving the reader to infer it.

**Known limits, reported not hidden** (`encoding_caveats(specs)` returns
them; the CLI prints them to stderr and the hex dump inlines them in its
header):

* **`SYNCHRONIZED` is not modelled.** Slack bytes before an aligned `COMP`
  item would shift every following offset, and this package's offset model
  (`layout_offsets.compute_record_layout`, which backs `data-items`) is
  unaligned throughout. Two contradictory offset models in one repo is worse
  than one documented gap. `compute_program_data_items` (2026-09-27) no longer
  reports those unaligned offsets as exact: the first `SYNCHRONIZED`
  binary/float/pointer/index item that is off its boundary (2/4/8 bytes, its
  own width) or inside an `OCCURS` table, and every item after it in source
  order, get `offset_ambiguous: True`, with one `unresolved` line naming it.
  An aligned SYNC item, or SYNC on DISPLAY/packed, changes nothing.
* **`COMP-1`/`COMP-2` are IEEE 754, not z/OS hexadecimal floating point.**
  Matches GnuCOBOL and Enterprise COBOL under `FLOAT(IEEE)`.
* **`OCCURS ... DEPENDING ON` is written at its maximum** under
  `RecordFormat.FIXED` — which is not a gap but what RECFM=F means. Under
  the variable formats the caveat is not emitted at all, because the
  occurrences past the counter's own value are genuinely dropped. See
  "Fixed- and variable-length records" below.

One more thing worth knowing before diffing generated bytes against a
compiler-written record: GnuCOBOL converts a decimal `COMP-2` literal through
its own decimal intermediate and can land **one ULP** off the correctly
rounded double. `-8840.0215` is a worked example — the encoder here writes
the true nearest double, and is the more accurate of the two.

**`--format hex`** is the form that survives being opened in a text editor,
which is exactly where a copybook is being looked at when someone wants to
know what its `COMP-3` field really holds. One line per field: offset,
length, name, PICTURE, USAGE, display value, and the bytes. A layout mistake
shows up as a shifted offset rather than as unexplained garbage further down.

Under a variable-length format the dump also carries the RDW on a row of its
own (`(RDW)`, offset `000000`, length 4), each record's own length in its
`--- record N of M: L bytes ---` header, and a `record length: MIN to MAX`
range instead of a single number. The RDW row is not decoration: without it
every field offset in the dump would sit four bytes below where it really
is in the file.


## Record views and decoding (`data/views.py` + `data/decoding.py`, 2026-09-07)

The other direction: **bytes somebody else wrote, plus a copybook, back into
a table.** "Open this VSAM extract / EBCDIC flat file with this copybook and
show me the records" — the inverse of `encoding.py`, and the half people
actually have a file for. Backs `cobol-parser decode`.

### Why a *view* exists at all

Everywhere else a layout is a flat `list[FieldSpec]` whose widths,
concatenated, are the record. That is all an encoder needs, because it is
writing the bytes and therefore knows where it is. A decoder needs two more
things:

* **Where each field starts.** A running sum of `FieldSpec.storage_size` —
  the same arithmetic `encode_record()` performs implicitly when it
  concatenates. Computing offsets from the same widths is *the* invariant
  here: a decoded offset and an encoded byte position cannot drift, because
  neither has its own copy of the arithmetic. `test_views.py`'s
  `test_base_offsets_match_the_encoded_record` checks that against real
  encoded bytes rather than a second hand-written offset table.
* **Which layout the bytes are being read through.** `REDEFINES` means one
  run of bytes has several meanings and only the program knows which applies
  to the record in front of you. A generator can duck that (it picks one and
  writes it — `include_redefines=False`); a decoder cannot.

So `build_record_views(record, options) -> RecordViews`:

| | |
|---|---|
| `RecordViews.base` | the record as declared, redefinitions excluded. Its `length` is the record's own length — the LRECL of a fixed-length file |
| `RecordViews.overlays` | one `RecordView` per `REDEFINES` item anywhere in the tree, in source order. Since #296 (2026-10-13) each is the **whole record with that overlay swapped in** for the item it redefines (`flatten_record(..., substitutions={id(redefined): overlay})`), plus every enclosing overlay for a nested one. So an overlay inside `OCCURS` is read at every occurrence (`T-ALT(1)`, `T-ALT(2)`), and `compare --view X --key K` works for a key outside the redefined area. A shorter overlay is padded with a `FILLER` so later fields keep their offsets. Fields outside the overlay keep the base view's column names (`_align_columns`). An overlay that covers a table's `DEPENDING ON` counter records it as a `HiddenCounter` (from `layout.flatten_overlay_view`), and `decode_record` reads the counter from those bytes when it reaches the overlay. Overlay views are `_LazyOverlayView`s, flattened on first read of `fields`, so a decode through one view does not pay for all of them. A lazy view still takes `RecordView`'s own fields as constructor arguments, so `dataclasses.replace()` works on it. `RecordDecoder._caveats` passes the hidden counters to `encoding_caveats` too, so a covered counter is not reported as missing from the record. `RecordView.offset` is where the overlay itself starts (first occurrence) and `overlay_length` its own span; the fields always start at 0 |
| `RecordViews.get(name)` | by full name (`CUST-REC.ADDR-OVERSEAS`) or the redefining item's own short name (`ADDR-OVERSEAS`), case-insensitively — a user reading the copybook has the short one in front of them |
| `RecordView.fields` | `list[PlacedField]` = `(spec, offset)`, contiguous: `placed[n].offset + placed[n].length == placed[n+1].offset` |
| `RecordView.offset_ambiguous` | base view: the record has an `OCCURS ... DEPENDING ON` table; overlay: one sits before or inside the overlay, so its static offset holds only for a full-length record (the decoder resolves offsets per record). Enclosing fixed `OCCURS` no longer sets it (#296). Set on the **base** view too as of 2026-09-07 — it used to default False there, so `--list-views` presented a maximum-length guess as a fact for the fields `data-items` reports as `byte_offset: null` |
| `RecordViews.framing_length` | the stride a fixed-length file is actually cut at: `max(base.length, end of every widening overlay view)` -- for `A X(4)` / `A-R REDEFINES A X(8)` / `B X(2)` that is 10, matching `data-items` (B at 8); it was 8 before #296, which decoded B as `''`. Equal to `base.length` for every conforming layout, and larger only for a `REDEFINES` wider than what it redefines — which COBOL forbids below level 01 but compilers accept, growing the record. `RecordDecoder` frames on this; framing on `base.length` shredded every record after the first. `to_dict()` reports **both** numbers (2026-09-07, Copilot review on #208: reporting only `record_length` left a consumer framing on a number the decoder does not use) |

`options` are normalised through `for_record_image()` inside
`build_record_views`, so passing CSV-shaped generation options cannot
silently produce a byte map with holes in it.

**`flatten_record(..., ignore_root_redefines=True)`** (new keyword) is what
makes an overlay flattenable: ordinarily a record that itself carries
`REDEFINES` flattens to *nothing*, which is right for generation and useless
for decoding. Only the root's own clause is exempted — a `REDEFINES` nested
inside the subtree still excludes its fields, so a view stays a contiguous
run of bytes. Internally: `_flatten_into(..., ignore_own_redefines=True,
redefines_label=...)`, neither of which is inherited by the recursive calls;
`redefines_label` still reaches every spec's `FieldSpec.redefines` so a field
says which redefinition it belongs to.

The overlay scan (`_scan_overlays`) mirrors `layout_offsets._layout_siblings`'
slot bookkeeping (a run of mutually-redefining siblings shares one slot; the
slot's footprint is its widest member) but emits placed `FieldSpec`s and
recurses *into* redefining children, so a redefinition of a redefinition gets
its own view. Each member's footprint comes from `_footprint()` =
`sum(storage_size for flatten_record(child, ...))`, i.e. the same widths
again rather than a parallel size model.

### Decoding

`RecordDecoder(views, opts, record_length=None)`, or
`.from_copybook_source()` / `.from_copybook_file()` / `.from_record()`.
`decode_bytes(data, view=..., max_records=..., skip=...) -> DecodeResult`;
`decode_file(path, ...)` is the same in binary mode (a COMP field routinely
contains 0x0A, which a text-mode read would translate).

Per storage class, each the exact inverse of `encoding.py`'s encoder and
dispatched on the same `USAGE`-then-category ladder:

| Storage | Read back as |
|---|---|
| DISPLAY text | the charset's characters (ASCII decoded as **latin-1**, so a byte the encoder could not have written is still shown), trailing spaces/NULs stripped |
| zoned DISPLAY | one digit per byte, sign overpunched or `SIGN IS SEPARATE` |
| `COMP-3` | two BCD nibbles per byte, sign in the final low nibble. With an even digit count the first byte's high nibble is pad, not a digit: a non-zero pad is an `error` and is left out of the value (2026-09-28: it was read as a digit, so `S9(2)V99` x'12345C' decoded as `123.45`, more digits than the PICTURE holds) |
| `COMP`/`COMP-4`/`COMP-5` | two's-complement, big-endian except COMP-5 which follows `EncodingOptions.endian` |
| `COMP-1`/`COMP-2` | IEEE 754, rendered to 7 / 15 significant digits |
| `INDEX`/`POINTER` | **hex** (`0x00000007`) — a compiler-managed occurrence number and an address mean nothing in a file another run wrote |

**Numbers render exactly as `ValueFactory._format_number` renders them** (no
leading zeros, the field's own `decimal_digits` places, a leading `-` only on
a non-zero negative) — `_render_number()` exists solely to keep that
equality, which is what makes `decode(encode(row)) == row` a property the
suite can assert rather than a hope. **Floats are held to the same equality**
by `values._render_float()`, which quantises a drawn value through the
field's own storage and renders it to the digit count the decoder uses. Two
things used to break it: a COMP-1 value drawn to four decimals over
±10,000 needs nine significant digits and binary32 holds about seven
(`-9419.8954` read back `-9419.896`), and the decoder's `%g` drops the
trailing zero `%.4f` had added to a COMP-2 (`-7960.5120` read back
`-7960.512`, roughly one row in ten). One column is still exempt **by
construction**: `FILLER` comes back empty because `encode_field()`
deliberately writes spaces there rather than the generated cell.

The decoder's COMP-1 caveat (`result.caveats`) still stands and is about a
*foreign* file: an arbitrary binary32 written by some other program carries
more than the seven digits shown. It says nothing about a value this
generator wrote, which is a fixed point of the round trip.

**Sign conventions are read more widely than they are written.** The encoder
writes one convention per charset; real files carry several, so `_zoned_digit`
accepts every EBCDIC sign nibble (`A`/`C`/`E`/`F` positive, `B`/`D`
negative), GnuCOBOL's ASCII zone (0x70), *and* the `{ABC…`/`}JKL…`
overpunches an EBCDIC file picks up when a transfer transcodes it. That last
one is deliberately never *written* by `encoding.py` (no compiler here to
verify it against) but a decoder that choked on it would be useless on half
the files in the wild. A sign is only honoured **in the position the encoder
would have put one** — a `D` zone mid-field is a corrupt digit, not a
negative number, and calling it a sign would flip a value that is merely
unreadable.

**Bad bytes are reported, not zeroed.** `DecodedField.error` names the
problem and the value is best-effort; `DecodedRecord.errors` and
`DecodeResult.error_count` roll them up. A copybook applied to the wrong file
shows up as a wall of these, which is the single most useful thing the
module can say (`test_the_wrong_copybook_shows_up_as_a_wall_of_errors`).

Invalid data that is still *readable* counts too (issue #248, 2026-10-04):

* an `OCCURS ... DEPENDING ON` counter outside its table's `min..max` is an
  error on the counter (`DEPENDING ON value 7 outside 2..5`); the table is
  still read at the clamped count (`_counter_value`), the best guess at where
  the following fields are;
* an RDW-framed record whose body holds bytes past the last field the base
  view reads gets a record-level error in `DecodedRecord.record_errors`
  (rolled into `errors`, `to_dict()["errors"]`, `error_count`, and a `!` line
  in the hex pane) -- previously those bytes vanished with `trailing == b""`;
* a `B`/`D` sign nibble on an **unsigned** packed field is an error and does
  not negate, mirroring the zoned decoder's sign-zone rule;
* a `COMP`/`COMP-4`/`BINARY` value with more digits than its PICTURE (65535
  in `PIC 9(4) COMP`) is a **caveat**, not an error: legal under
  `TRUNC(BIN)`, invalid under `TRUNC(STD)`, and the decoder has no TRUNC
  option. `COMP-5` is exempt (native binary, its whole width is legal).

### Framing, and the two things that decide it

* **Framing always uses the `base` view**, whichever view the caller reads
  through: where a record ends is a property of the *file*, not of the
  overlay somebody chose. A 200-byte record read through a 20-byte
  redefinition is still 200 bytes; framing on the overlay would walk the
  file at the wrong stride.
* **`trim_tables` is decided by the record format, not by the counter.**
  Under `RecordFormat.FIXED` an ODO table reserves all of its occurrences
  whatever the counter says, so trimming would skip bytes that *are* in the
  record and mis-align every field after the table. `decode_bytes` resolves
  the format once from the base view and passes `trim_tables=fmt.is_variable`
  to `decode_record`. (This was a real bug caught by the round-trip test:
  fixed-format records decoded with trimming on produced silent garbage from
  the table onward.)

| Format | How the next record is found |
|---|---|
| `FIXED` | `record_length` override, else `base.length` |
| `VARIABLE` | the 4-byte RDW; an RDW longer than the file raises `RecordDecodingError` rather than being guessed at |
| `VARIABLE_BARE` | the layout's own ODO counters — decoding consumes exactly what this record holds, so the next starts where this stopped. A tail shorter than the record its own counters describe is `trailing`, not one more truncated row (`_ran_short`, 2026-09-27 — RECFM=F already did this). With a `record_separator` set, the layout still frames first (2026-09-28: a `0x0A` inside COMP/COMP-3 data used to split the record); the layout's length is taken when a separator or end-of-data follows it and every separator inside it falls in binary/packed/float bytes, else it falls back to `find(separator)` (text lines shorter than the layout) |

`EncodingOptions.record_separator` is consumed after each record when it is
actually there. Fields past the end of a short record come back
`present=False` (the column stays, so a table has the same shape for every
row); a record cut mid-field comes back `truncated=True`, decoded from what
was there. Bytes left after the last whole record are `DecodeResult.trailing`
— never dropped silently, because a tail that is not a whole record almost
always means the record length is wrong. `max_records`/`skip` page a large
file, and a run stopped by `max_records` reports `trailing == b""` rather
than calling the rest of the file a broken tail.

### Output shapes

* `DecodeResult.to_csv()` — the exact inverse of `GeneratedDataset.to_csv()`:
  same column names, same value rendering, same `"\n"` terminator. The CLI
  test asserts `gen-data | decode` reproduces the generated CSV byte for byte.
* `DecodeResult.to_dict()` — every field's `offset`, `length`, `hex`,
  `present`, `truncated`, `error`. This is what a UI hex pane binds to.
* `decoded_hex_dump(result, opts)` — the same shape `encoding.hex_dump()`
  produces for a generated record, built from bytes somebody else wrote:
  every line ties an offset and a length to the field that owns those bytes
  and to the value read out of them, with `! field: error` lines under the
  bad ones.

### Record compare (`data/compare.py`, 2026-09-27)

Phase 1 of the test-data-environments initiative (design:
`backend/docs/superpowers/specs/2026-09-27-test-data-environments-design.md`):
the check that closes an integration test -- the dataset a batch run wrote
against the baseline it should match. Built entirely on the decoder above; it
adds pairing and field comparison, and decodes nothing itself.

* **Pairing.** With `key=[...]`, records pair on the tuple of key-field
  values: an inserted or deleted record is reported once, as `extra` /
  `missing`, instead of shifting every later record into `changed` (the
  failure of a byte compare / IEBCOMPR). Duplicate keys pair in file order and
  are named in `caveats` (the first ten; the rest counted). Without a key,
  records pair by position.
* **Field comparison is by decoded value** -- a `C` and an `F` sign nibble on
  the same packed number are equal, as they are to the program.
  `compare_bytes=True` compares raw bytes, and additionally reports a
  `(unmapped bytes)` pseudo-field when two records agree field by field but
  not byte by byte (slack past the layout under `record_length`). Bytes of an
  *ignored* field are blanked on both sides before that image check
  (2026-09-27: `--compare-bytes --ignore UPD-TS` had reported the ignored
  timestamp's bytes as `(unmapped bytes)`, so the ignore did nothing).
  **LOW-VALUES padding is a difference** (2026-10-13, #287): the decoder
  strips trailing spaces *and* NULs from DISPLAY text (display output keeps
  doing so), so `'ALICE'` + 5 x `x'00'` and `'ALICE     '` decode alike, yet
  the program tells them apart (`IF A-NAME = SPACES`) and an uninitialised
  output field is what the check exists to catch. `_same()` therefore also
  requires a text field's (alphanumeric / alphabetic / alphanumeric-edited /
  national) NUL byte positions to match once the values agree. Before, only
  `--compare-bytes` caught it, and that also flags C/F sign nibbles and
  filler. Numeric-edited fields are checked too (an unmodelled picture reads
  as plain text and was otherwise blind to it). **FILLER is exempt** (round
  2 review): uninitialised FILLER in an FD record is common and harmless, so
  making it a difference would fail compares that passed before; only
  `compare_bytes` reports it. The text report appends `(bytes x'..' vs x'..')` to a difference
  whose two values print the same, so the reader can see what differs. A field that
  did not decode cleanly on *either* side is always compared by bytes: its
  best-effort value is not evidence.
* **Absent fields** (a shorter VB record, an `OCCURS DEPENDING ON` occurrence
  its counter excludes) compare as absent: `FieldDifference.expected` /
  `.actual` is `None`, rendered `(absent)` in the text report.
* **Truncated fields** (#357, 2026-10-14): a field the record ended part-way
  through (`DecodedField.truncated`) differs from one of another length, even
  when what is left decodes to the same value (`'ABC '` cut to `'ABC'`,
  `'0000'` cut to `'0'`). `_same()` compares `length` before values. Before,
  a shorter actual record compared equal and `compare` exited 0; only
  `--compare-bytes` caught it. Two fields cut at the same place stay equal.
* **Name resolution is against the `RecordView`, not the records**, so a
  typo is caught even when both files are empty. A key token resolves, in
  order, as a column (`QTY(2)`), a qualified name, or a field's own name, and
  must hit exactly one elementary column (a group, a table name, or a name
  two groups share is an error). An ignore token matches a column, a field
  name (every occurrence), a qualified name, or any group on the path
  (everything under it); `CompareResult.ignored` lists what was *actually*
  skipped. A name that is not in the layout, or a key that is also ignored,
  raises `CompareError` -- never a silent no-op that hides a real difference.
* **Counts are exact, the list is capped.** `max_differences` bounds
  `differences`; `changed_count` / `missing_count` / `extra_count` never are,
  and `truncated` says when the list stopped short.
* **Everything the decode was unsure of carries over**: decode caveats from
  both sides (de-duplicated), per-side decode-error counts, per-side trailing
  bytes.
* **Trailing partial records can make files unequal** (2026-10-04, #250).
  `CompareResult.trailing_differs` (in `to_dict()`, and a `trailing bytes
  differ` line in `to_text()`) is set, and `equal` is False, when both files
  end in a partial record and the two tails differ -- or, under
  `compare_bytes`, when only one file has a tail (the image is longer).
  Comparing values, a one-sided tail stays a caveat only. Before, `equal`
  ignored `trailing` entirely, so `XYZ` vs `QQQ` tails reported "files are
  equal" and `compare` exited 0 even with `--compare-bytes`. Option (b) of
  the issue; `_trailing_differs()` is the whole policy.
* **Memory.** The first cut decodes both files fully and builds an in-memory
  key index. A streaming, key-sorted merge for files that do not fit is a
  planned follow-up (design doc, Risks).

### `select_record()` (`data/copybook.py`)

`CopybookDataGenerator._select_record` moved to a module-level
`select_record(records, record, filename)` and the method now delegates to
it. Both halves of the package need it and they need it to *agree*:
generating from `--record CUST-REC` and decoding through `--record CUST-REC`
must land on the same 01, or a round trip through the record image silently
changes layout.


## Fixed- and variable-length records (`RecordFormat`)

A copybook says how long a record *can* be. It does not say whether the file
holding it is **RECFM=F/FB** (every record the layout's full length) or
**RECFM=V/VB** (each record only as long as that record's own data makes it).
Before this existed, only the fixed reading was generatable — a copybook with
an ODO table got a caveat on stderr saying the table was written at its
maximum and that a real record would be shorter.

**Two independent mechanisms make a record vary**, and a program may use
either:

1. **`OCCURS ... DEPENDING ON`** inside the record — a table whose occurrence
   count is carried by a counter field. The record's length follows from the
   layout, so it can be derived. Handled by `layout.OdoControl` /
   `present_indexes()`, below.
2. **`FD ... RECORD VARYING FROM min TO max DEPENDING ON item`** on the file —
   the record layout is an ordinary fixed one and *nothing in it* says how
   long any given record is. The length travels in the RDW; the program sets
   the `DEPENDING ON` item before a WRITE and reads it back after a READ.
   Handled by `layout.VaryingLength`, below.

The second is the one an ODO walk cannot see, and it is common: a flat
`01 EMP-RECORD80` under `RECORD VARYING FROM 47 TO 80` is the canonical
shape.

`EncodingOptions.record_format` picks between them; `gen-data
--record-format fixed|variable|variable-bare|auto` is the CLI on top of it.

| Value | Records | Framing |
|-------|---------|---------|
| `fixed` (default) | full length: every occurrence written, no length cut | none |
| `variable` | only the occurrences the row's counter names, cut to its declared length | 4-byte RDW per record |
| `variable-bare` | same trimmed records | none — the consumer already knows where each ends |
| `auto` | `variable` if the record varies by *either* mechanism, else `fixed` | follows the resolved value |

**`fixed` is the default, deliberately.** A record that cannot vary encodes
to byte-identical output under every format bar the RDW, so the default only
matters for the records that *can* — and there, silently changing what
`--format record` has always written would be worse than making the caller
ask for it. `auto` is the opt-in to "do what the source implies". The one
exception: `--record-varying` is itself a statement that records are not
fixed, so passing it alone reaches `auto` rather than writing the
fixed-length file the caller just said this is not; an explicit
`--record-format fixed` still wins over it.

**The RDW** (`encode_rdw`) is `LL LL 00 00`: a big-endian 16-bit total length
**including the four RDW bytes**, then two reserved zero bytes. Big-endian
regardless of `--endian` and of the charset — it is physical file structure
written by the access method, not data written by the program. A record
whose total would exceed `MAX_VARIABLE_RECORD` (0xFFFF) raises
`RecordEncodingError` rather than truncating the length silently: a record
that long needs RECFM=VS (spanned), which is not generated.

**How trimming works, end to end** — three pieces, none of which re-flattens
the layout:

1. **`layout.OdoControl`** on every `FieldSpec` inside an ODO table
   (`spec.odo_controls`, outermost first): the counter's name, *which
   subscript position* it governs, and the `OCCURS min TO max` bounds. The
   subscript position is the tuple length at the moment the table is entered,
   so nested ODO tables each contribute one control and the general case
   falls out for free. `max_times` is the number of occurrences actually
   flattened, not the declared maximum — `max_occurs` and the hard cap can
   both stop the walk short, and a counter allowed to name occurrence 50 of a
   table flattened to 10 would describe bytes no `FieldSpec` covers.
2. **`spec.odo_counter_bounds`** on the *counter* field, stamped by a
   post-pass (`_link_odo_counters`) because a counter is normally declared
   *before* the table that depends on it — its spec already exists by the
   time the `DEPENDING ON` phrase is seen. `ValueFactory` draws the counter
   from those bounds rather than from the PICTURE's range, so a `PIC 9(4)`
   counter for a table of at most 50 can no longer generate 8 731. Drawing
   across the range (rather than generating freely and clamping) is also what
   makes a variable-length file actually *vary*: clamping would pin nearly
   every row to the maximum. A declared `VALUE`/level-88 still wins when it
   names a count the table can hold, and is overridden when it does not.
3. **`layout.present_indexes(specs, row)`** — the positions whose bytes that
   row's record contains, in order. The counter governing a given occurrence
   is resolved by *position*, not just by name: it is the counter spec
   sharing that field's enclosing subscripts. That is what makes IBM's
   **complex ODO** (a `DEPENDING ON` table nested inside an ordinary
   `OCCURS`, so each outer occurrence carries its own count) come out right
   rather than trimming every outer occurrence to the last one's count.
   A counter declared *outside* the enclosing fixed table has no subscripts,
   so the exact `(name, outer)` key misses and the counter is looked up by
   name; `decoding._present` mirrors that fallback (2026-09-28 — it used to
   read the table at full length and mis-align the record).
   Dropping an occurrence and concatenating
   what remains is exactly what a real variable-length record looks like:
   anything declared *after* the table shifts up into the space the absent
   occurrences would have taken, which falls out of preserving order rather
   than needing its own arithmetic. A layout with no ODO table short-circuits
   to "every position", so fixed-length copybooks pay nothing for any of this.

**Lengths.** `record_length(specs)` is unchanged — every occurrence present,
which is the fixed-length answer *and* the LRECL a RECFM=V dataset is defined
with. `minimum_record_length(specs)` is the same with every table at its
declared minimum, and `row_record_length(specs, row, opts)` is one row's,
computed from the layout rather than by encoding it. `GeneratedDataset`
exposes all three plus `record_lengths(opts)` and `is_variable_length`.
`gen-data --format record` prints the resulting range to stderr, because raw
bytes have no header to state their own LRECL in and a record image whose
length nobody states is a file nobody can read back.

### FD `RECORD VARYING` (`layout.VaryingLength`)

```cobol
FD  EMPFILE
    RECORD VARYING FROM 47 TO 80 CHARACTERS
           DEPENDING ON EMPREC-LEN
    RECORDING MODE IS V.
01  EMP-RECORD80.
    05  EMP-ID       PIC X(6).
    ...
    05  EMP-COMMENT  PIC X(33).
```

Nothing here is subordinate to a counter — `EMPREC-LEN` is a WORKING-STORAGE
item, not part of the record — so `odo_controls` is empty for every field and
`present_indexes()` keeps them all. What varies is how many of the record's
bytes each *record* carries.

* **Where the range comes from.** `VaryingLength.from_fd_clauses()` reads the
  FD's `record` clause, which `data_file_description.py` already parses into
  `{varying, min, max, depending_on}` and attaches to the 01 as `fd_clauses`
  metadata. So `gen-data` on a **whole program** picks it up with no flag. A
  bare **copybook** has no FD; `DataGeneratorOptions.record_varying` (CLI
  `--record-varying MIN:MAX`) supplies it, and overrides the FD when both
  exist. `RECORD CONTAINS 47 TO 80` declares the same thing without the
  `VARYING` keyword and parses identically.
* **`maximum` is clamped to the record's own byte length.** An FD promising
  more than its 01 can hold cannot be honoured by padding — those bytes were
  never declared — so the range is cut to what exists. **Never silently**
  (#274, 2026-10-05): `VaryingLength.build(..., caveats=)` appends a sentence
  whenever it clamps a bound, or ignores the range outright because nothing
  of it is left (`40:50` on a 28-byte record, or equal bounds) — the record
  then stays fixed-length. The sentence lands on `GeneratedDataset.caveats`,
  is printed as a `* caveat:` line in `to_hex_dump()`'s header
  (`hex_dump(..., extra_caveats=)`), and as `warning:` on stderr by
  `gen-data` in every output format.
* **The length is drawn per row at *generation* time**, uniformly across the
  range, from the same seeded RNG the values came from, and stored on
  `GeneratedDataset.declared_lengths`. Drawing it there rather than in the
  encoder is what keeps `encode_record` a pure function and makes a seed
  reproduce record *lengths* as exactly as it reproduces their contents. The
  draws happen *after* the rows, so a record with no range draws nothing and
  generates byte-identical output to before this existed.
* **`encode_record(..., data_length=N)`** cuts the body to N bytes — mid-field
  if that is where the length falls, which is exactly what a program reading
  `EMP-RECORD80(1:EMPREC-LEN)` sees. Passing it also settles
  `RecordFormat.AUTO`, since a declared length is by definition a record that
  varies. `--format hex` shows the fields past the cut as
  `(past record length)` rather than dropping them, so the cut is visible;
  a field the cut falls *inside* shows `(cut N/M bytes)` in the VALUE column
  rather than the whole generated value (most of which is not in the file).
* **The `DEPENDING ON` item is filled in when it *is* in the record.** Usually
  it isn't. When a copybook does put it there, leaving the generated value
  would contradict the record's own length.
* **Decoding agrees.** `RecordDecoder.from_record()` finds the range the same
  way (explicit `options.record_varying` first, else `fd_clauses`) and keeps
  it as `RecordDecoder.varying`; both `resolved_format()` calls in
  `decoding.py` pass `varying=`, so `decode --record-format auto` reads the
  RDW-framed file `gen-data --record-format auto` wrote (2026-09-28; it used
  to frame it fixed-length). Pinned by
  `test_variable_length.py::TestFdRecordVarying::test_decode_auto_reads_what_gen_data_auto_wrote`.
* **Both mechanisms at once**: the table decides, the FD range is not applied
  on top of it, and a caveat says so. Enforced in *two* places, because a
  caveat that the code contradicts is worse than no caveat: the generator
  draws no length for such a record (so `declared_lengths` is `None` and every
  downstream surface agrees for free), and `_effective_data_length()` drops a
  `data_length` a direct caller passes anyway. `minimum_record_length()`
  likewise only prefers the FD floor when a length was actually drawn — a
  Copilot review on PR #204 caught all three of those disagreeing.

### Odds and ends

**The counter may live outside the record** — in WORKING-STORAGE, or in a
record this copybook does not define. Nothing generated can set it, so its
table is written at full length and `unresolved_odo_counters(specs)` names
it in the caveats. Same for a counter cell left blank by `blank_rate` or
holding a non-numeric value: reserving the whole table is the one answer that
never claims bytes the layout does not describe.


# Program Layout Index (`data/program_layout.py`)

Phase 1 of program-scoped test-data generation (the `gen-fixtures` initiative
— see `docs/plans/2026-08-02-program-data-generation-design.md` and its
per-phase implementation plan). Resolves a whole program's FD/record/field
names into layout facts a later boundary walker (Phase 2) can join against.
Reuses `FieldSpec`/`flatten_record` directly — no parallel value engine.

```python
from cobolparser.generators import ProgramLayoutIndex

index = ProgramLayoutIndex.build(ast)              # from an already-parsed CobolProgram
index = ProgramLayoutIndex.from_file("PROG.cbl")   # parses for you

index.record_for_file("INV-FILE")      -> CobolDataItem | None
index.records_for_file("INV-FILE")     -> list[CobolDataItem]   # multi-01 FDs
index.file_names()                     -> list[str]   # every FD/SD file owning a record
index.file_facts("INV-FILE")           -> FileFacts | None
index.resolve("INV-QTY")               -> ResolvedField | None
index.resolve("INV-QTY OF INV-REC")    -> ResolvedField | None  # qualified
index.resolve("INV-REC.INV-QTY")       -> ResolvedField | None  # dotted, same meaning
index.record_named("INV-REC")          -> CobolDataItem | None  # whole record/group, any section
index.section_of("WS-EOF")             -> "working_storage"
index.linkage_records()                -> list[CobolDataItem]
index.working_storage_records()        -> list[CobolDataItem]
index.ambiguities                      # name -> qualified paths it maps to
index.unresolved                       # human-readable reasons, never silently dropped
```

## FD -> record resolution

The DATA DIVISION parser tags every level-01 FILE SECTION item with
`fd_file_name` (`parsers/divisions/data.py`) while scanning under an FD/SD —
that tag is the *only* source of truth this index uses (no positional
fallback: an untagged FILE SECTION record is reported in `unresolved`, never
guessed from source order). An FD with more than one 01-level record (a
legal "record redefinition" idiom) tags all of them, so `records_for_file`
naturally returns every variant.

**FD vs SD.** The parser now also tags `fd_record_type` (`"FD"` or `"SD"`) —
previously untracked, since nothing needed the distinction before this
index. An SD is a SORT/MERGE work file, not a file a program `OPEN`s;
`FileFacts.record_type` surfaces it so a later phase can mark it
`unconstrained` instead of mock-eligible (mockymock refuses SORT/MERGE
outright).

**`FileFacts`** merges two independent parses by uppercased file name: the
ENVIRONMENT DIVISION's `SelectStatement` (organization, access mode, keys,
`FILE STATUS` field, `OPTIONAL`) and the FILE SECTION's `fd_clauses` metadata
dict (`RECORD CONTAINS`, `RECORDING MODE`) that `FileDescriptionClauseParser`
already captures. Either side may be missing — a `SELECT` with no matching
FD/SD, or vice versa — and that gap goes to `unresolved` rather than
producing a half-true `FileFacts`. `record_contains` is a plain int for a
fixed-length record; a variable-length record (`RECORD IS VARYING` or a bare
`min TO max` range with no `VARYING` keyword) populates
`record_contains_min`/`_max` instead and leaves `record_contains` `None`.

## Name resolution

Every section's top-level records are flattened once via `flatten_record(...,
DataGeneratorOptions(include_filler=True, include_redefines=True))` — the
index must see *all* storage (FILLER, REDEFINES included); which fields are
generation-eligible is a later phase's concern, not an indexing one. A bare
name unique across the program resolves directly; one that exists at more
than one path returns `None` and is recorded in `ambiguities` instead of
guessed. Two qualified forms disambiguate it, and they read in **opposite**
segment orders for the same concept:

* `"A OF B"` / `"A IN B"` — COBOL's own syntax; the field name comes first,
  qualifiers follow.
* `"B.A"` — mirrors `FieldSpec.qualified_name` (root-first, field-last), so
  here the field name is the *last* segment and the qualifier(s) precede it.
  Treating both forms as "first segment is the field" was an actual bug
  caught by `test_dotted_qualifier_form_also_disambiguates` during
  development.

A level-88 condition name resolves to its *parent* field's `ResolvedField`
(a separate recursive walk over each record's raw `CobolDataItem` tree, keyed
by qualified path, since `flatten_record` does not emit a `FieldSpec` for
level-88/66 items). **Duplicate 88 names refuse to guess (2026-08-12 fix,
audit A-B4):** the same condition name declared under parent fields in more
than one record used to overwrite last-one-wins with no `ambiguities` entry;
`_condition_index` now keeps every parent, and a lookup mapping to more than
one distinct parent field returns `None` and records the parents in
`ambiguities` -- the same policy `resolve()`/`record_named()` already apply
to bare names. Pinned by
`tests/regression/test_audit_2026_08_12_analysis.py::TestB4DuplicateConditionNamesAreAmbiguous`.
**Qualified 88 names (#272, 2026-10-05).** `IS-OK OF REC-A` (or `IN`, or
dotted `REC-A.IS-OK`) filters the 88's declarations by its qualifiers with
the same rule the field branch uses (each qualifier names the record or a
group on the parent field's path) before the one-parent check, so a
qualified reference to a duplicated 88 resolves instead of being given up
on. `condition_values()` / `condition_raw_values()` split the name with
`split_qualified_name` and filter the same way (they used to look up the raw
text, so any qualified name returned `None` and `gen-fixtures --scenarios`
missed every arm testing it). A *bare* duplicated 88 still refuses to guess.

**`record_named(name)` — whole records, not fields.** `resolve()` only ever
finds *elementary* fields, because `flatten_record` never emits a `FieldSpec`
for a group item (it descends through groups to their leaves). A WRITE/
REWRITE target, a READ `INTO` target, and an SQL/ACCEPT/CICS/DLI operand can
all legally name a *whole record* instead of a field — `resolve("INV-REC")`
returns `None` for exactly this reason. `record_named()` fills that gap: it
indexes every top-level (01/77) record by its own name, across all four
sections, independent of `flatten_record`. Same ambiguity policy as
`resolve()` (a name shared by records in more than one section returns `None`
and is recorded in `ambiguities`, never guessed). Found via direct
reproduction while building Phase 2's `BoundaryInventoryAnalyzer` — a
REWRITE's record target came back `None` from `resolve()` even though
`records_for_file()` proved the record was indexed; not theorized.

## Multi-program compilation units

`build()` indexes exactly the `CobolProgram` node it is given — for a file
with stacked/nested programs (`CobolProgram.contained_programs`, e.g.
`tests/samples/subprogram_demo.cbl`'s caller + two callees), build a separate
index per program unit rather than expecting one index to see all of them.
This composes cleanly with Phase 2's planned `--callee-path` resolution rung,
whether the callee comes from a separate file or a contained program in the
same one.

## `from_file`

Raises `ProgramLayoutError` (not a bare `FileNotFoundError`/`ParseError`) for
every failure mode this module owns: a nonexistent path (checked explicitly
— `parse_cobol()` otherwise falls back to treating a bad path string as
literal, unparseable source text), a program that does not parse to an AST
at all, or — in the default `strict_copybooks=True` mode — a COPY member
`copybook_paths` cannot resolve (a layout with a hole in it is wrong, not
partial). `strict_copybooks=False` downgrades the last case to an
`unresolved` entry and falls back to parsing without expansion.

`build()`/`from_file()` also stamp `index.ast` with the `CobolProgram` the
index was built from, so a caller that only kept the index (typically after
`from_file()`) can still reach the AST without re-parsing — the capability
`ProgramFixtureGenerator.generate_from_file` (below) depends on.

# Program Fixtures (`program_fixtures.py`, `data/bundle.py`)

Phase 3 of the `gen-fixtures` initiative — the first shippable release per
the parent plan. `ProgramFixtureGenerator` turns a program's
`ProgramLayoutIndex` (Phase 1) and `BoundaryReport` (Phase 2,
`.okf/analysis.md`) into a `FixtureBundle`: layout-valid random values for
every boundary, assembled into one "happy path" `Scenario`. Backs the
`cobol-parser gen-fixtures` CLI subcommand (`.okf/cli.md`).

```python
from cobolparser.generators import ProgramFixtureGenerator

generator = ProgramFixtureGenerator()                  # or pass DataGeneratorOptions
bundle = generator.generate_from_file(
    "INVUPDT.cbl", copybook_paths=[...], callee_paths=[...], seed=7,
)
bundle.scenarios[0].fixtures       # list[BoundaryFixture]: mock in-data
bundle.scenarios[0].expectations   # list[Expectation]: assert-on stubs
bundle.coverage                    # CoverageSummary (boundary-level, v1)
bundle.unresolved                  # every gap from Phases 1-2-3, merged
bundle.to_json()                   # bundle_version, program_name, seed, ...
bundle.write_csv_dir("out/")       # out/<scenario-slug>/<KEY>.csv + MANIFEST.json
```

## Scenario-mode generation (`generate_with_scenarios`, Phase 6)

`generate_with_scenarios(ast, index, report, mode="happy"|"branches"|"all",
seed=...)` (and its `_from_file` counterpart) is the Phase 5→6 wiring: it
routes `mode="happy"` straight to `generate()` (byte-identical output, same
seed — pinned by
`test_fixture_bundle_contract.py::TestScenarioModeContract::test_happy_mode_is_byte_identical_to_generate`),
and for `"branches"`/`"all"` runs `ConstraintExtractor` + `ProgramFlowAnalyzer`
+ `ScenarioPlanner` internally and turns every `PlannedScenario` into a real
`Scenario` with populated fixtures — not just a name and an intent string.
The happy-path scenario from `generate()` (same seed) is always prepended,
so these modes add scenarios on top of it and a program with no targetable
arm gets one scenario rather than an empty bundle (2026-10-05; before, 5 of
mockymock's 12 examples got zero scenarios under `branches`/`all` and
`mockymock generate --with-data` exited 1).

```python
bundle = generator.generate_with_scenarios_from_file(
    "INVUPDT.cbl", mode="all", seed=7,
)
bundle.scenario_coverage   # ScenarioCoverage.to_dict(), None in mode="happy"
```

**Every scenario still gets a complete fixture for every boundary** — the
program under test touches all of them regardless of which branch arm a
scenario targets. Only the specific field(s) a `PlannedScenario` constrains
are pinned to their solved witness; everything else is generated by the same
`ValueFactory` path the happy-path scenario already uses. This is threaded
through via an optional `override: PlannedScenario | None` parameter on the
internal `_build_fixture`/`_build_call_fixture`/`_status_dict` helpers:

* **Witnesses** — `override.witnesses` is keyed by `FieldSpec.qualified_name`;
  a matching field's generated value is replaced by the witness verbatim
  (already PICTURE-valid from `domains.solve()`), everything else still comes
  from `ValueFactory.value_for()`. This pins one value to **every** row of a
  multi-row sequence.
* **Per-row witnesses** — `override.row_witnesses` (0-based row index →
  `{qualified name: value}`) overrides `witnesses` for one row only, and
  `_sequence_length` raises the generated row count so a pinned row always
  exists (a witness pinned past the end of the sequence would silently do
  nothing). Groundwork, not yet wired: `ScenarioPlanner` populates it nowhere,
  so every bundle is byte-identical to before. It exists because the flat
  `witnesses` dict made a whole class of branch *inexpressible*, not merely
  underivable — one reachable only when a prior record correlates with a
  following one ("a prior `'05'` record sharing a key with a following `'09'`
  record"), which is a property of the sequence rather than of any single
  record. Reachability in `ScenarioPlanner` is CFG-shaped
  (`flow_report.unreachable_nodes`), never data-shaped, so such an arm is
  counted `targeted` and gets a scenario named for it that never reaches it.
  Design + remaining work:
  [docs/plans/2026-09-04-cross-record-correlation-design.md](../docs/plans/2026-09-04-cross-record-correlation-design.md).
* **Sequence length** — `override.sequence_constraints` (matched by
  `(category, key)`) overrides a READ boundary's row count, e.g. the "empty
  input" family's `length=0`. Falls back to `--rows` (READ) / `1` (everything
  else) exactly like the happy path when no override applies.
* **Status** — `override.status_overrides` (keyed by `"<CATEGORY>:<KEY>"`)
  replaces the default status value (`"00"`/`"0"`) for the fixed
  error-status family and any future status-targeting scenario.

`FixtureBundle.scenario_coverage` (new, additive field —
`bundle_version` stays `1`) carries `ScenarioPlan.coverage.to_dict()`
verbatim, `None` for a `mode="happy"` bundle since that mode never attempts
branch targeting. Full key-by-key shape:
[`docs/fixture-bundle-schema.md`](../docs/fixture-bundle-schema.md).

## Self-verification: `Scenario.verification` (2026-09-04)

A scenario's *name* is a claim. Until this existed, nothing checked it: the
planner pinned witnesses, the generator emitted rows, and whether those rows
actually satisfied the branch the scenario was named for could only be found
out by running each case under a tracer. `generators/verification.py` closes
that — `verify_scenario(planned, scenario)` re-reads the scenario's OWN
emitted fixture data and re-checks every planned conjunct against it, and
`generate_with_scenarios` stores the verdict on `Scenario.verification`
(`{"status", "fields", "gaps"}`; additive, `bundle_version` stays `1`;
`None` for a `mode="happy"` scenario, which targets no branch and so has
nothing to verify).

The check is deliberately **independent of the solver**: it evaluates
constraints against the concrete rendered strings a mock will actually move
into the program, so a solver bug, a rendering bug, and a witness that never
reached any fixture all surface as findings rather than as a green label.
Per-field verdicts are `satisfied` (some generated row meets every conjunct),
`violated` (the field is there and no row does), `absent` (no fixture
generates the field at all, so nothing pins the branch), or `unknown`.

**`unknown` is a real answer, not a failure mode.** A conjunct that cannot be
decided from a rendered string is never silently "satisfied" — `IF WS-INPUT >
0` on a `PIC X(10)` field is the routine case (IBM COBOL only allows an
alphanumeric-to-numeric ordering comparison when the alphanumeric operand is
integer-like, so answering it lexically would stamp "verified" on a
comparison nobody can evaluate). Equality survives the mixed case: a value
that is not a number cannot equal a numeric literal either way.

**A `violated` verdict demotes the scenario's arms to `missed`** (2026-10-04,
#244). `generate_with_scenarios` passes each verdict to
`_demote_violated_arms`: every `targeted`/`merged` arm of a scenario with a
`violated` field is re-counted as `missed` in `scenario_coverage` (reason
`"witness failed verification: ..."`, counts kept exact) and gets one
`bundle.unresolved` entry, so `gen-fixtures --strict` exits 2 instead of
passing a coverage claim its own data contradicts. `absent`/`unknown` do
not demote -- they are "could not tell", which `unverified` already says.

`cli/parse.py`'s `gen-fixtures` prints an unverified summary on **stderr**
(stdout stays JSON-only — mockymock's `fixtures` contract), and mockymock's
`generate --with-data` renders the same reasons as a `*> UNVERIFIED:` comment
above the affected TESTCASE.

## Path conditions: `BranchConstraints.enclosing` (2026-09-04)

The planner's v1 simplification — "a scenario targets *one* arm and takes
only that arm's own conjuncts; enclosing branches on the path to it are not
accumulated" — was the single biggest source of scenarios whose data did not
reach their own arm. On a nested `IF INV-QTY > 500 / IF INV-TYPE = "AB"`, the
scenario named for the inner arm pinned `INV-TYPE` and left `INV-QTY`
wherever the value generator happened to put it, so it usually never entered
the outer arm at all.

`ConstraintExtractor` now records, on every `BranchConstraints`, the
`(branch_id, arm_id)` chain whose arms must all be taken for that decision
point to be reached (`_walk_list` threads it down through
`_nested_statement_lists`, which pairs each nested statement list with the
arm id it sits under). `ScenarioPlanner._path_constraints` joins on those
pairs and folds the enclosing conjuncts into the targeted arm's own before
solving, so the witness set pins the whole path. Consequences worth knowing:

* An arm that becomes unsatisfiable once its path condition is added (outer
  `X > 5`, inner `X < 3`) is now correctly `missed` with
  `"unsatisfiable with its own path condition: ..."` rather than targeted
  with data that could never reach it.
* An enclosing arm the constraint report never modeled contributes a
  `PlannedScenario.path_gaps` entry instead of silence, and that alone makes
  the scenario `unverified` — the arm may still not be reached, and saying so
  beats an optimistic label.
* **An OR-split enclosing arm is a disjunction, and is folded as
  alternatives** (`_path_options` + `_solve_with_path`, review fix on PR
  #198). `_register_variants` registers `THEN#1`/`THEN#2`/... and NO bare
  `THEN` for a condition containing an OR, while `enclosing` names the base
  arm id -- so a plain `arms_by_key[(branch_id, "THEN")]` lookup misses
  every such arm and silently leaves the path unfolded. Each `#N` variant is
  one way to satisfy the same arm, so the planner tries them in order and
  keeps the first that stays satisfiable alongside the targeted arm's own
  conjuncts. Fixing on the first disjunct would be wrong, not just
  suboptimal: for `IF A = 100 OR A = 200 / IF A = 200` it makes the set
  unsatisfiable and reports the inner arm unreachable when `A = 200` reaches
  it. `_MAX_PATH_COMBINATIONS` caps the cross product a deep chain of
  disjunctive arms would otherwise produce.
* **`_merge_candidates` carries `path_gaps` across a merge.** A merged-in
  candidate brings its own unpinned enclosing arms with it; dropping them
  let the merged scenario report `verified` while an arm it now claims was
  not in fact pinned -- the silent false positive `path_gaps` exists to
  prevent.
* IF/EVALUATE/SEARCH arms join the chain, including **SEARCH's `AT END`**
  (`_ARM_BEARING_ATTRS`): `_extract_search` registers an `arms["AT_END"]`
  entry, so a statement nested under it does have an enclosing arm to join
  to, even though the clause reaches the walk through
  `_NESTED_STATEMENT_ATTRS` rather than a `when_clauses` list. It carries no
  conjuncts (the real precondition, "the table search found nothing", is not
  a field constraint), so it lands in `path_gaps` -- which is the point:
  untagged, a branch inside it looked top-level and could be reported
  `verified` without its data establishing the search fell through. A
  genuinely non-branch nesting (`ON EXCEPTION`, an inline `PERFORM` body)
  still contributes nothing: inventing an id for one would produce a path
  entry nothing could join to.

## Expectations: tiers 1-2 (Phase 7)

Every scenario's `expectations` (in both `generate()` and
`generate_with_scenarios()`) now carries structural and computed assertions
alongside Phase 3's OUT-boundary stubs, via two small helpers in
`program_fixtures.py`:

* **Tier 1 — `_call_count_expectation`.** For every boundary that gets an
  actual fixture (an OUT-only boundary has nothing mocked to count, so it
  gets none), `Expectation(kind="call_count", ref="<CATEGORY>:<KEY>",
  value=times)` where `times = len(sequence) + (1 if has_terminal_invocation
  else 0)` -- except a `STATUS_ONLY` fixture, always `1` (its `sequence` is
  empty by design, not because zero invocations happened).
  `has_terminal_invocation` is `"AT_END" in boundary.handlers`, checked
  directly rather than derived from whether `terminal` resolved to a dict
  (bug fixed 2026-08-04: a READ with an `AT END` handler but no resolvable
  status field still genuinely invokes the boundary one more time to hit
  end-of-file -- "does exhaustion happen" and "do we know a field name to
  report it in" are independent questions; `call_count` must not go stale
  just because `terminal` came back `None`). Derivable exactly from the
  scenario's own already-generated sequence -- never a guess.
* **Tier 2 — `_tier2_expectations`, backed by
  `cobolparser.analysis.const_fold.ConstantFolder`** (see `.okf/analysis.md`
  for the folder's own extensive "exact by construction, or absent" rules).
  Builds a seed dict from every `BoundaryFixture` in the scenario with
  *exactly one* generated row -- a multi-row READ sequence has no single
  representative value to seed with, keyed by `spec.qualified_name` from
  `fixture.layout`/`fixture.sequence[0]` -- then folds the program's entry
  paragraph chain seeded with those values, turning every field still
  knowable at a `DISPLAY`/`WRITE` into `Expectation(kind="field_equals",
  ref=qualified_name, value=folded_value)`.

Both run once per scenario, after that scenario's `fixtures` list is fully
populated (so Tier 2 sees the *actual* generated/witness-pinned values for
that specific scenario, not the happy path's). `mode="happy"`'s byte-
identity guarantee with `generate()` is unaffected -- both tiers run inside
`generate()` itself, so `generate_with_scenarios(mode="happy")` (which
delegates to `generate()` unchanged) carries the exact same expectations.

Reuses the Phase 0 value engine directly: each boundary's field list —
however it was resolved (`ProgramLayoutIndex.resolve()` for an elementary
field, `.record_named()` for a whole record) — is generated with a
`ValueFactory` exactly like `CopybookDataGenerator` uses, no parallel engine.

## Per-category generation rules

| Category / direction | What gets generated |
|---|---|
| `READ` (IN) | `options.rows` rows; when `"AT_END"` is in the boundary's `handlers`, `terminal` is set to `{resolved_field: "10"}` if `_resolve_status_field` finds a real field name (`boundary.status_field`, else `index.file_facts(key).file_status_field`), or stays `None` -- never a placeholder string -- if neither resolves (bug fixed 2026-08-04: previously fell back to a literal `"FILE-STATUS"` key that is not a real data-name in the target program) |
| `WRITE`/`REWRITE` (OUT) | No fixture (nothing to mock) — one `Expectation(kind="stub")` noting the program produces this value |
| `OPEN`/`CLOSE`/`DELETE`/`START`/`UNLOCK` (`STATUS_ONLY`) | A fixture with `status` only (e.g. `{"WS-FS": "00"}`), no `layout`/`sequence` |
| `SQL`, `sql_type` SELECT/FETCH (IN) | One generated row; `status={"SQLCODE": "0"}` |
| `SQL`, INSERT/UPDATE/DELETE (OUT) | Expectation stub, like WRITE |
| `CICS`/`DLI` (`BIDIRECTIONAL`, best-effort) | Whatever fields resolved get generated values *and* an expectation stub — Phase 2's own layout resolution here is already best-effort (no fixed INTO/FROM attributes), so this phase does not pretend otherwise |
| `ACCEPT` (IN) | One generated value |
| `CALL`/`DYNCALL` | Per-argument: IN/BIDIRECTIONAL args' fields are generated into **one combined row** (one CALL invocation, all its IN arguments at once); OUT args get an expectation stub reading "value supplied by the program under test, not mock-generated"; BIDIRECTIONAL args get both a generated value **and** a stub noting the OUT aspect isn't asserted yet; `RETURNING`/`GIVING` parameters always get a generated value (`provenance="giving-parameter"`) |

A name may resolve to either an elementary field or a whole record
(`_fields_for_name`/`_fields_for_names`, private helpers using the same
`resolve()`-then-`record_named()` fallback `BoundaryInventoryAnalyzer` uses)
— a CALL argument or SQL host variable can legally be either.

## Determinism: per-boundary sub-seeds

One `bundle.seed`. Each boundary derives its own
`zlib.crc32(f"{scenario}|{category}|{key}".encode()) ^ bundle_seed`, feeding
a fresh `random.Random`/`ValueFactory`. Deliberate: a single shared RNG
consumed in iteration order would reshuffle every later boundary's values
the moment an earlier one changed shape (a new field, a resized OCCURS) —
sub-seeding keeps a bundle stable under unrelated additions. `zlib` is
stdlib; the zero-dependency rule holds. Pinned by
`test_program_fixtures.py::TestDeterminism` and the corpus-wide
`test_gen_fixtures_corpus.py::test_determinism_across_the_corpus`.

## `unresolved` propagation

`bundle.unresolved` is the union of three layers, because a consumer must
never have to separately check Phase 1/2/3's own gap lists to get the full
picture: `ProgramLayoutIndex.unresolved` (Phase 1 — merged into
`BoundaryReport.unresolved` by `BoundaryInventoryAnalyzer.analyze()` itself,
see `.okf/analysis.md`), `Boundary.unresolved` (Phase 2, per boundary), and
anything Phase 3's own field resolution additionally fails to pin down (an
argument name that resolves to nothing generatable). Found and fixed during
Phase 3 development: the Phase 1→2 merge did not exist until a `--strict`
CLI smoke test against a program with a known Phase-1-level gap
(`report_test.cbl`'s Report Writer FD) exited 0 instead of 2.

## `--callee-path` resolution

`ProgramFixtureGenerator._resolve_callees` builds `callee_indexes`/
`callee_asts` for `BoundaryInventoryAnalyzer`'s Phase 2b "callee source"
rung two ways, merged: every `CobolProgram.contained_programs` entry (free —
no file search, e.g. `subprogram_demo.cbl`'s bundled caller + callees), then
— for any remaining statically-CALLed program name — a search across
`callee_paths` directories trying `NAME`/`name` × `""`/`.cbl`/`.CBL`/`.cob`/
`.COB`. A callee that fails to parse is skipped (falls through to the
caller-dataflow rung), not a hard error — one bad `--callee-path` entry
should not sink the whole bundle.

## `write_csv_dir`

One `GeneratedDataset`-shaped CSV per fixture whose `layout`/`sequence` are
both non-empty (file-shaped boundaries only — `STATUS_ONLY`/OUT/expectation
-only fixtures produce nothing to write), under
`<path>/<scenario-slug>/<KEY>.csv`. A `MANIFEST.json` at the root is the
full bundle with each fixture's `sequence` emptied to `[]` (never replaced
with a pointer string — a consumer that ran the manifest through the same
deserializer as a real bundle would silently iterate a string character-
by-character instead of hitting a type error) plus a new `csv_path` key
(the relative CSV path, or `null` if this fixture got no CSV), so a
consumer can discover what scenarios/fixtures exist — and where each one's
CSV lives — without walking the directory tree first. **Names are made
unique** (2026-09-28): scenario names used to repeat (two IFs in one
paragraph both planned `"<PARA>: THEN"`; the planner names them uniquely
since #267, but a hand-built bundle still can), and both used to slug to one directory, the later
scenario's CSV overwriting the earlier one's with both manifest entries
pointing at the survivor. `_unique_names` suffixes a repeated slug `-2`,
`-3`, ... (first keeps its plain slug, case-insensitive), and `_csv_names`
does the same for a `<KEY>.csv` two fixtures would write with *different*
rows (identical same-key fixtures still share one file). Both passes use the
one precomputed name list, so `csv_path` always names the file written. See
`docs/fixture-bundle-schema.md`'s own "write_csv_dir" section for the full
manifest shape.

# Scenario Planning (`scenarios.py`)

Phase 5 of the `gen-fixtures` program-scoped test-data initiative. Turns
Phase 4's `ConstraintReport` and `ProgramFlowAnalyzer`'s control-flow graph
into a set of named `PlannedScenario`s -- one (or a merge of several) per
reachable, satisfiable branch arm -- with exact coverage accounting.

```python
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.generators import ProgramLayoutIndex
from cobolparser.generators.scenarios import ScenarioPlanner

index = ProgramLayoutIndex.build(ast)
boundary_report = BoundaryInventoryAnalyzer().analyze(ast, index)
constraint_report = ConstraintExtractor().extract(ast, index, boundary_report)
flow_report = ProgramFlowAnalyzer().analyze(ast)

plan = ScenarioPlanner().plan(
    constraint_report, flow_report, boundary_report, mode="all"
)
plan.scenarios           # list[PlannedScenario]: field_constraints, witnesses,
                         # sequence_constraints, status_overrides, arm_keys
plan.coverage            # ScenarioCoverage: total_arms == targeted + merged + missed
plan.coverage.details    # list[ArmOutcome]: one per arm, with a reason on every miss
```

**v1 path-condition simplification** (stated up front in the module
docstring, not discovered later): a scenario targets *one* arm and takes
only that arm's own conjuncts; enclosing branches on the path to it are not
accumulated. `ArmOutcome` records "targeted" the same way regardless, so
this is arm coverage, not full path coverage -- a v2 item.

**Joining a `BranchConstraints` to its `BranchNode`.** Not by string-matching
`branch_id` to `BranchNode.node_id` (Phase 4's own docstring already flags
why: replicating `program_flow/scanner.py`'s sequential counter would
couple this module to that scanner's exact traversal order) and *not* by
comparing `parent_proc` strings either -- `scanner.py` uppercases its own
`parent_proc` (`pname.upper()`) while `ConstraintExtractor` preserves the
source's original casing, so the two are not directly comparable even when
they name the same paragraph. The actual join is `(line, column)`, both
derived from the identical statement's `SourceLocation` in both walks.
`BranchConstraints.column` (new field, additive) exists specifically for
this join.

**OR-split arms and the flow graph.** `BranchNode` always has exactly one
`BranchArm` per THEN/ELSE/WHEN/WHEN_OTHER slot, but Phase 4 may have
OR-split one of those into several arm-ids (`"ELSE#1"`, `"ELSE#2"`, ...) --
see constraints.py's own De Morgan section. A base arm-id with *any*
representation in `BranchConstraints.arms` (bare or `#N`-suffixed) counts as
covered; only a base arm-id with **zero** representation at all is a
genuine `"missed: ..."` gap. Found and fixed writing this module's own
tests: the first draft treated a bare `"ELSE"` lookup as missing whenever
Phase 4 had split it into `"ELSE#1"`/`"ELSE#2"`, double-reporting an already
-covered arm as also missed.

**Merging.** Two candidate scenarios merge when their constraint sets touch
disjoint fields *and* their sequence constraints agree on every shared
boundary (same length, or one side doesn't mention it) -- greedy,
deterministic: candidates are processed in `(line, column, arm_id)` order,
each merging into the first open scenario it is compatible with. "Fewer,
richer scenarios" rather than one per arm.

**Naming** (#267, 2026-10-05). One arm's name is
`"<proc>: <VERB>@<line> <arm label>"` -- `"MAIN-PARA: IF@11 THEN"`,
`"P: EVALUATE@90 WHEN 'A'"` -- with the verb read off a conjunct's
`origin` (else the flow graph's `branch_type`). An OR-split arm
(`THEN#2`) appends its own disjunct, rendered from its conjuncts
(`"... THEN [WS-A = 'Z']"`), or `[alt N]` when it has none. After merging,
a scenario is renamed for *every* arm it targets (later arms in the same
paragraph drop the repeated `"<proc>: "`), joined with `" + "`, or the
first arm's name plus `" (+N more arms)"` past 120 characters; then
`bundle._unique_names` suffixes any repeat `-2`, `-3`, ... -- so names are
unique within a plan. `ArmOutcome.merged_into` carries the *final* name.
Before this, two IFs in one paragraph both planned `"<PARA>: THEN"`.
`name` stays free text (no `bundle_version` bump).

**Unsatisfiable arms.** Every distinct field an arm's conjuncts touch is
solved independently via `domains.solve()`; if *any* field's constraint set
is `Unsatisfiable`, the whole arm is unsatisfiable (all of an arm's
conjuncts must hold simultaneously) and lands in `coverage.missed` with
`"unsatisfiable: <domains.py's own reason>"`.

**Fixed families (`mode="all"` only):**

* **empty input** — one combined scenario: every `IN`-direction READ
  boundary gets a `SequenceConstraint(length=0)`; every `IN`-direction SQL
  boundary gets a `status_overrides` entry of `"100"` (SQLCODE not found).
* **error status** — one scenario per *declared* handler, never a status
  the program has no path for: `INVALID_KEY` in `Boundary.handlers` ->
  `"23"`; a CALL's `ON_EXCEPTION` -> `"12"`; an OPEN with a `status_field`
  -> `"35"`.
* **boundary values** — two combined scenarios (`"minimum"`/`"maximum"`),
  every numeric field any constraint touches pinned to its picture's true
  extreme (`-ceiling` for a signed field, `0` otherwise, vs. `ceiling`).
  Pinned via an `eq` constraint, not `ge`/`le` -- found writing this
  family's own test: `domains.solve()`'s witness is always the interval's
  (grid) *midpoint*, so a `ge("0")` constraint alone produced a mid-range
  witness, not `0`.

**Wired into `gen-fixtures` as of Phase 6.** The CLI's `--scenarios
branches|all` now drive real scenario selection via
`ProgramFixtureGenerator.generate_with_scenarios_from_file` (see "Scenario-mode
generation" under "Program Fixtures" above) -- each `PlannedScenario` becomes
an actual `BoundaryFixture`-populated `bundle.Scenario`, and
`FixtureBundle.scenario_coverage` carries this module's own
`ScenarioCoverage.to_dict()` verbatim.

# Tests

* `tests/unit/test_copybook_data_generator.py` — flattening, categories,
  value constraints, option validation, dataset surface
* `tests/unit/cli/test_gen_data_cli.py` — `gen-data` flags, JSON modes, errors;
  `TestRecordImageFormats` covers `--format record|hex`, `--charset`,
  `--record-separator`, and that CSV output is unchanged by any of them;
  `TestRecordFormatFlag` covers `--record-format`, walking the written
  file's RDW chain and asserting it lands exactly on EOF
* `tests/unit/generators/data/test_storage.py` — the byte-width table, incl.
  the two regressions (`USAGE INDEX` sized as zero, `SIGN IS SEPARATE`
  under-reported by one)
* `tests/unit/generators/data/test_encoding.py` — every storage class's
  bytes, record assembly at predicted offsets, the caveat list, and the hex
  dump. **Its module docstring holds the GnuCOBOL probe program and its raw
  output** — the ground truth every expected byte string here comes from.
  Re-run that probe before changing an encoding
* `tests/unit/generators/data/test_variable_length.py` — the whole
  fixed-vs-variable story in one file, both mechanisms:
  `TestFdRecordVarying` works the mainframestechhelp.com `EMPVL` example end
  to end (FD clause picked up with no flag, lengths inside the declared
  range, the cut falling mid-field, the RDW carrying it);
  `TestExplicitVaryingRange` covers `record_varying`; plus
  `OdoControl`/`odo_counter_bounds`
  linking, `present_indexes` trimming (including the field *after* the table
  shifting up), counter generation staying inside the table's bounds, RDW
  framing, the length trio, format-dependent caveats, and the invariant that
  ties the two readings together — a full-count variable record is
  byte-for-byte the fixed record
* `tests/integration/test_copybook_csv_generation.py` — parametrized over the
  sample copybooks and the NIST `.CPY` corpus; asserts no copybook crashes the
  generator and that generated cells are assignable to their fields
* `tests/contracts/test_copybook_data_generator_contract.py` — exported names,
  signatures, `to_dict()` key sets, reproducibility guarantee
* `tests/unit/generators/data/test_layout_offsets.py::TestComputeProgramDataItems`
  — `compute_program_data_items()` over a two-record WORKING-STORAGE
  section: both records' items appear in `output["items"]`, `unresolved`
  key present, each record's fields are independently 0-based
* `tests/integration/test_data_item_layout_corpus.py` — `TestRedefinesFixture`
  pins the Task 8 top-level-REDEFINES fix against
  `tests/samples/redefines_test.cbl`'s real fan-out shape (`WS-REDEF-1`
  and `WS-REDEF-2` both redefine `WS-BASE-AREA` directly, not a 3-way
  chain — each resolves to `redefines_chain == ["WS-BASE-AREA"]`, all
  three at `byte_offset == 0`); `TestShamriceCorpusDoesNotRaise` sweeps
  the same `examples/cobol/shamrice/*.cbl` corpus
  `test_program_layout_corpus.py` uses, purely for "doesn't crash"
  coverage — that corpus was not authored with REDEFINES-chain
  assertions in mind
* `tests/unit/test_flowchart_generator.py` — flowchart generators
* `tests/unit/test_program_layout_index.py` — FD/record resolution, FD-vs-SD
  tagging, `FileFacts` merging, bare/qualified/level-88 name resolution,
  `record_named()` (whole-record lookup + cross-section ambiguity),
  multi-program compilation units, `from_file` error modes
* `tests/integration/test_program_layout_corpus.py` — every
  `examples/cobol/shamrice/*.cbl` indexes without raising; zero unexpected
  `unresolved`/`ambiguities` entries (`report_test.cbl`'s Report Writer FD is
  the one expected, documented exception)
* `tests/unit/test_program_fixtures.py` — bundle assembly, CALL-argument
  fixtures (IN/OUT/BIDIRECTIONAL expectation notes), SQL fixtures
  (SQLCODE stub), determinism, `write_csv_dir` (including
  `TestScenarioModes`: witness pinning, empty-input zero-length sequences,
  boundary-value min/max, `scenario_coverage` presence; and
  `test_csv_dir_round_trips_byte_for_cell_against_the_json` / the
  multi-scenario-directory test, both Phase 6)
* `tests/unit/cli/test_gen_fixtures_cli.py` — `gen-fixtures` flags,
  `--list-boundaries`, `--format json|csv-dir`, `--strict` exit codes
* `tests/integration/test_gen_fixtures_corpus.py` — every
  `examples/cobol/shamrice/*.cbl` generates a bundle without raising; every
  generated cell fits its field's category; determinism across the corpus
* `tests/contracts/test_fixture_bundle_contract.py` — exported names,
  `bundle_version`, generator signatures, `to_dict()` key sets across
  `FixtureBundle`/`Scenario`/`BoundaryFixture`/`Expectation`/`CoverageSummary`,
  reproducibility guarantee; `TestScenarioModeContract` (Phase 6) — signature
  pins for `generate_with_scenarios`/`_from_file`, happy-mode byte-identity
  with `generate`, `scenario_coverage` population/absence, seed
  reproducibility across `branches`/`all`, unknown-mode `ValueError`
* `tests/unit/test_scenario_planner.py` — single-IF THEN/ELSE targeting with
  differing witnesses, disjoint-field merging, unsatisfiable-arm handling,
  the three fixed families (`mode="all"`), exact coverage accounting
* `tests/integration/test_scenario_planner_corpus.py` — every
  `examples/cobol/shamrice/*.cbl` plans (both `branches` and `all` modes)
  without raising; coverage accounting sums to the arm count for every
  program; every miss/merge carries a reason/target

# See Also

* [ast-models.md](ast-models.md) — `CobolDataItem` / `PictureClause` /
  `OccursClause` / `ConditionNameItem`, the inputs to flattening
* [cli.md](cli.md) — `gen-data` and `gen-fixtures` (Phases 1-3, 5-6) and
  `program-flow` subcommands
* [analysis.md](analysis.md) — `ProgramFlowReport` feeding the flowcharts and
  joined against by `scenarios.py`; `BoundaryInventoryAnalyzer` (Phase 2),
  the input `report` this file's `ProgramFixtureGenerator` (Phase 3) and
  `ScenarioPlanner` (Phase 5) both consume; `ConstraintExtractor` /
  `domains.solve()` (Phase 4), which `scenarios.py` consumes directly
* [parser.md](parser.md) — the DATA DIVISION parser's `fd_file_name` /
  `fd_clauses` / `fd_record_type` metadata tags this index reads
* [`docs/fixture-bundle-schema.md`](../docs/fixture-bundle-schema.md) — the
  full `FixtureBundle` JSON shape, key by key, with a worked example (Phase 6)
* `docs/plans/2026-08-02-program-data-generation-design.md` and
  `docs/plans/2026-08-02-program-data-generation-implementation.md` — the
  full 9-phase plan this file documents Phases 1, 3, 5, and 6 of

# Level-88 `VALUE ALL` (2026-09-28)

The parser stores a level-88 `VALUE ALL 'X'` as the one value `ALL "X"`
(`ALL SPACES` for a figurative operand). `layout.all_literal_operand()`
recognises the form and `layout.fill_all_literal(value, width)` fills it
(`ALL "AB"` at width 5 is `ABABA`). `expand_condition_values(raw, width)`
expands it with a width -- `layout._condition_values` passes the item's
PICTURE size (so `FieldSpec.condition_values` holds `XXX`, which the value
factory and the solver's enum domain use as is) and `ProgramLayoutIndex`
passes the owner field's `spec.size`; without a width (`data-items`) it is
kept as written. `condition_values_exhaustive` counts `ALL "X"` as one exact
value and `ALL <figurative>` as non-exhaustive.
