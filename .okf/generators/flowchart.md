---
type: Module
title: Flowcharts
description: generators/flowchart.py — Mermaid and Graphviz DOT flowcharts rendered from a ProgramFlowReport; edge styling, terminal exit nodes, THRU badges, label escaping, id allocation, unreachable-node hiding.
tags: [generators, flowchart, mermaid, dot, program-flow]
timestamp: 2026-10-15T00:00:00Z
---

# Flowcharts

`cobolparser/generators/flowchart.py`: `MermaidFlowchartGenerator` /
`DotFlowchartGenerator` consume a `ProgramFlowReport` (see
[analysis.md](../analysis.md)) and emit a diagram string. `FlowchartOptions`
controls statement counts, edge labels, fall-through edges, unreachable nodes,
and synthetic external-CALL nodes. CLI: `cobol-parser program-flow --format
mermaid|dot` ([cli.md](../cli.md)). Both generators render the same things,
differing only in each target format's attribute syntax. Start with
[Nodes and ids](#nodes-and-ids), then [Edges](#edges).

## Contents

- [Nodes and ids](#nodes-and-ids)
- [Edges](#edges)
- [Label fidelity](#label-fidelity)
- [Tests](#tests)
- [See also](#see-also)

## Nodes and ids

Node ids and labels come from `FlowNode.key` (the `qualified_name` when two
paragraphs share a name, see #258), so `X1 OF S1` and `X1 OF S2` are drawn as
two nodes (`X1_OF_S1`, `X1_OF_S2`) and edges, which name nodes by key, attach.

**External-call nodes.** Module-level `_external_call_target()` reads the
called program from `report.external_calls[i]["program"]` (falling back to
`"target"` for hand-built legacy dicts) and uppercases it, so `EXT_*` node ids
agree with `FlowEdge.target`. `EdgeCollector.process_call`
(`analysis/program_flow/edges.py`) emits the called program under `"program"`
(reading only `"target"` renders no `EXT_*` node from a real report), and
keeps the source's case while `FlowEdge.target` is uppercased, so a
lowercase `CALL 'subpgm'` needs the uppercasing to land on a declared node.

**Terminal exit nodes.** One extra node per `FlowNode` carrying
`exit_statement_kind`/`exit_statement_location` (see
[analysis.md](../analysis.md)'s `ProgramFlowAnalyzer` section), labelled
`"{kind} @ {line}"`, emitted right after the main node loop and before
external-call nodes. Mermaid emits `(((...)))` triple-circle syntax plus a
`terminal` classDef (`fill:#1b1b1b,stroke:#c1121f`); DOT emits
`shape=doublecircle` with matching `fillcolor`/`fontcolor`. Both respect
`show_unreachable` like the main node loop. The terminal id is normally
`f"{nid}_EXIT"`, but the chart's id allocator falls back to `{nid}_FLOWEXIT`,
then a numeric suffix, when that id is taken: `PERFORM X THRU X-EXIT` is a
common idiom, so a real paragraph named `9000-TERM-EXIT` sanitizes to exactly
the terminal id of `9000-TERM`.

**One id allocator per chart (see #266).** `_sanitize_id` is lossy:
paragraphs `A-B` and `A_B` both sanitize to `A_B`, and an external program
`SUBPGM` (`EXT_SUBPGM`) meets a paragraph named `EXT-SUBPGM`. Each
`generate()` builds one `_IdAllocator.for_report(report)`, mapping
`(kind, name)` -> a unique id (kinds `node` = paragraph/section/branch/arm
keyed by raw name, `ext` = called program, `exit` = terminal). Paragraphs are
allocated first so they keep the plain id; a later collision gets a numeric
suffix (`A_B_2`, `EXT_SUBPGM_2`). Every node declaration and edge endpoint
goes through it; `_hidden_ids()` and the skipped-empty-arm set hold *raw*
names. A chart without collisions gets the plain sanitized ids.

**DOT keyword ids.** `_sanitize_id` output is a valid bare DOT ID *except*
for the reserved words `node`/`edge`/`graph`/`digraph`/`subgraph`/`strict`
(case-independent in Graphviz): a paragraph named `NODE` would be read as the
default-node attribute statement, and `MAIN -> STRICT;` is a syntax error.
`_dot_id()` quotes exactly those ids at every DOT node/edge emission site.
Mermaid needs no equivalent: its flowchart keywords (`end`, `style`,
`class`, `click`, ...) only bite in lower case, and every id here is upper
case (verified with mermaid 11 `parse()`).

**`show_unreachable=False` hides what the paragraph owns.** Not just the
paragraph's node line and terminal node, but its outgoing PERFORM/GO TO/CALL
edges, its IF/EVALUATE decision and arm boxes, and external nodes called only
from it: both renderers re-create an undeclared edge endpoint as a bare box,
so a leftover edge brings the hidden paragraph back unstyled. `_hidden_ids()`
(paragraph + its branch/arm ids) and `_external_targets()` (drops a CALL made
only from a hidden paragraph) are shared by both generators.

**Arm boxes show statement summaries.** `BranchArm.summary` (see
[analysis.md](../analysis.md)'s statement_text section) renders instead of
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

## Edges

`SQL_WHENEVER` edges (#349, `EXEC SQL WHENEVER ... GO TO p`) are drawn like
`CICS_HANDLE`: in the internal-edge set, the GO TO-family set, and labelled
`SQL WHENEVER`.

**Recursion / GO TO edge distinction.** Module-level `_recursion_pairs(report)`
returns every `(source, target)` pair that closes a `PERFORM_RECURSION` cycle
(from `report.cycle_details`); `_PERFORM_EDGE_TYPE_VALUES` /
`_GOTO_EDGE_TYPE_VALUES` (module-level, shared by both generator classes)
classify an edge's `.value` string. A PERFORM-family edge closing a recursion
cycle gets gold-dashed styling; any GO TO-family edge (`GOTO`,
`GOTO_DEPENDING`, `ALTER`) gets magenta-dashed styling.

- **Mermaid** uses a `linkStyle N <css>` line per styled edge
  (`_RECURSION_LINK_STYLE` / `_GOTO_LINK_STYLE`). `N` counts every
  `-->`/`==>`/`-.->` link Mermaid sees, in the order `generate()` writes them
  — including the exit-statement terminal-node links emitted *before* the
  edges loop. So `link_index` is seeded with `terminal_link_count` (the
  number of `{nid} --> {exit_id}` lines actually written) before the edges
  loop starts counting; starting at 0 points every `linkStyle` at the wrong
  arrow in any chart with a terminal node. A hidden fall-through edge does
  not consume an index.
- **DOT** sets `color`/`style` directly on each `->` edge statement; there is
  no global, order-dependent index to get out of sync.

**`[THRU n]` edge-label badges.** A `FlowEdge` carrying `thru_target` +
`range_members` (a `PERFORM ... THRU ...` / SORT|MERGE procedure range)
renders as a single arrow from the range's start to its *first* member,
badged `[THRU n]` (`n = len(range_members)`), not as a second arrow spanning
the range. Both edges loops skip any edge whose `.value` ends in `"_THRU"`
unconditionally, regardless of `show_fall_through`. This requires the *base*
(non-`_THRU`) edge to carry `thru_target`/`range_members` itself: 
`EdgeCollector.process_perform`, `process_sort` and `process_merge`
(`edges.py`) each compute the range once and pass it to both the base edge
and its `*_THRU` sibling. A base edge without it renders neither arrow nor
badge, and the range vanishes from the diagram.

**Quoted edge labels.** `MermaidFlowchartGenerator` wraps every non-empty
edge label in double quotes (`-->|"label text"|`). Mermaid's flowchart lexer
reads an unquoted `(` or `[` between the `|...|` pipes as the start of a node
shape (`PS`/`SQS` tokens), so a loop annotation (`... (loop)`),
`CALL_DYNAMIC`'s `"CALL (dynamic)"` label, or a `[THRU n]` badge would break
parsing (e.g. a `PERFORM UNTIL` loop edge in
`legacy-application/cobol/DEPTBMP.cbl`). DOT is unaffected — `_dot_str`
quotes every DOT label.

## Label fidelity

Rules driven by how the VS Code Program Flow webview (Mermaid v11,
`htmlLabels:false`, `securityLevel:'strict'`) actually renders the text:

- **ASCII-only output.** Both generators' labels are pure ASCII: the
  exit-terminal separator is `@` (not `·`) and `GOTO_DEPENDING`'s short label
  is `GO TO ... DEPENDING` (not `…`). On Windows the CLI writes stdout in the
  console's locale encoding (cp1252) while consumers decode UTF-8, so any
  non-ASCII label character renders as U+FFFD (`GOBACK � 118` in the
  webview). Pinned by the `test_output_is_ascii_only` tests
  (`out.encode("ascii")`).
- **`"`/`<`/`>` escaped in every Mermaid label.** Module-level
  `_escape_mermaid_label()` maps `<`/`>` to `#lt;`/`#gt;` and `"` to a plain
  apostrophe in branch conditions, arm labels, and edge labels. Mermaid v11
  with `htmlLabels:false` silently swallows a bare `>` from label text
  (`WS-PURGE-ERRORS > ZERO` rendered as `WS-PURGE-ERRORS ZERO`, `>=` as `=`)
  while `<`/`<>` happen to survive; the `#name;` entity form renders
  correctly through both the lexer and the sanitizer for `<`/`>` only —
  `#62;`-style *numeric* entities and `#quot;` both come out as literal
  `&#62;`/`&quot;` text in SVG-text label mode (verified against Mermaid
  11.12), which is why `"` is substituted rather than entity-escaped:
  display-only text, and `'Y'` is how the COBOL literal reads anyway. DOT
  labels are not escaped this way — Graphviz has no such mangling.
- **DOT string escaping.** Edge attribute values go through `_dot_str` like
  node labels (a PERFORM UNTIL / IF condition with a `"` inside an apostrophe
  literal would otherwise end the DOT string early). The node label's
  `\n (N stmts)` break is appended *after* `_dot_str`: passed through it, the
  `\n` becomes `\\n`, which Graphviz renders as a literal backslash-n.

## Tests

`tests/unit/test_flowchart_generator.py` — `TestMermaidFlowchartGenerator`
(linkStyle/terminal-node/THRU-badge sections, plus
`test_linkstyle_index_accounts_for_terminal_node_links` and
`test_terminal_id_does_not_collide_with_real_exit_paragraph`),
`TestDotFlowchartParity` (the DOT-side mirror), `TestSortThruEndToEnd`
(real COBOL through the analyzer: a SORT OUTPUT PROCEDURE THRU range reaches
both renderers), `TestExternalCallEndToEnd` (real COBOL into both renderers,
plus the legacy-dict fallback), and
`TestMermaidLabelFidelity`/`TestDotLabelFidelity`/`TestLabelFidelityEndToEnd`
(ASCII-only output, `#lt;`/`#gt;` escaping, arm summaries, empty-IF-arm
dropping).

## See also

* [generators.md](../generators.md) — the generators routing page
* [analysis.md](../analysis.md) — `ProgramFlowAnalyzer` / `ProgramFlowReport`,
  `EdgeCollector`, statement summaries
* [cli.md](../cli.md) — `program-flow --format mermaid|dot`
* [history](../history/generators.md) — archived dated notes (the
  label/id/linkStyle fixes behind the rules above)
