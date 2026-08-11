# Design: Mermaid program-flow fidelity (recursion, GO TO, STOP RUN, conditions)

Date: 2026-08-11
Status: approved (brainstormed in-session)
Scope: `cobol-parser` only.
Companion doc (consumer): `mocky-mock-vscode-extension`'s
`docs/superpowers/specs/2026-08-11-program-flow-webview-design.md` — a new
"Program Flow" webview that renders this repo's `program-flow --format
mermaid` output. That doc depends on this one; this one has no dependency on
it.

## Overview

`ProgramFlowAnalyzer` (`cobolparser/analysis/program_flow/`) already builds a
fairly complete control-flow graph — cycle detection and classification
(`PERFORM_RECURSION` / `GOTO_LOOP` / `FALL_THROUGH` / `MIXED`), exit-point
tracking, IF/EVALUATE branch nodes. `MermaidFlowchartGenerator`
(`cobolparser/generators/flowchart.py`) renders it, but doesn't use most of
that richness today, and one real bug ships condition placeholders instead
of real text. This pass fixes the bug and makes the Mermaid output visually
distinguish the things it already knows about.

## A. Correctness bug: condition text

`edges.py:121` (PERFORM UNTIL) and `scanner.py:224,297` (IF, EVALUATE
subjects) all resolve condition text via:

```python
cond_dict = stmt.until_condition.to_dict()
condition = cond_dict.get("expression_type", str(cond_dict))
```

`expression_type` is the AST node's type tag (`"CONDITION"`, `"COMPARISON"`,
`"LOGICAL"`) — never the actual condition. A diamond that should read
`WS-EOF-SW = 'Y'` instead reads `COMPARISON`.

The real text is available but not read:

- **PERFORM UNTIL**: `_make_until_condition_expression()`
  (`parsers/statements/perform_parser.py`) already stores the raw joined
  condition string at `condition_expr.operands[0]`. Fix: read `operands[0]`
  instead of `expression_type`.
- **IF / EVALUATE**: `stmt.condition` is a structural
  `ConditionalExpression`/`LogicalExpression` tree
  (`parsers/statements/_conditions.py`'s `build_condition_expression`) with
  no raw string preserved. Needs a new recursive renderer.

### New helper: `render_condition_text()`

New module `cobolparser/analysis/program_flow/condition_text.py`,
`render_condition_text(expr: CobolExpression) -> str`:

- `ConditionalExpression`: map `operator` back to a symbol
  (`EQUAL`→`=`, `GREATER`→`>`, `LESS`→`<`, `GREATER_OR_EQUAL`→`>=`,
  `LESS_OR_EQUAL`→`<=`, `NOT_EQUAL`→`<>`) and render
  `f"{left_operand} {symbol} {right_operand}"`. For the class/sign-condition
  form (`operator` is literally `"IS NUMERIC"` / `"IS NOT POSITIVE"` /
  etc.), render `f"{left_operand} {operator}"`. For `CONDITION_NAME`, render
  `left_operand` alone. For the `"COMPARISON"` fallback (no structured
  operands), use `metadata.get("raw_condition")` if present.
- `LogicalExpression`: recursively render `left_condition`/`right_condition`
  joined by `operator` (`AND`/`OR`).
- Anything else (including the bare test-double `CobolExpression` some unit
  tests construct with no `operands`/`left_operand`/`metadata` at all):
  fall back to `operands[0]` if non-empty, else `metadata.get("raw_condition")`,
  else `expression_type` — **exactly today's behavior**. This keeps
  `test_program_flow.py::TestBranchNodes::test_if_with_else_creates_one_branch_node`
  (which pins `bn.condition_text == "COMPARISON"` against a bare
  `CobolExpression("COMPARISON", LOC)` test double) passing unmodified; only
  real parsed COBOL — which always produces a `ConditionalExpression`/
  `LogicalExpression` — gets real text.

Call sites updated: `edges.py`'s `process_perform` (loop condition on the
PERFORM edge), `scanner.py`'s IF handling (`BranchNode.condition_text`) and
EVALUATE handling (subject text, same placeholder bug at `scanner.py:297`
for `subjects`).

## B. Visual gaps: the data exists, the generator doesn't use it

None of the following require new analysis — `cycles.py`, `edges.py`, and
`scanner.py` already compute everything needed. Only
`MermaidFlowchartGenerator` (and `DotFlowchartGenerator`, kept at parity)
change.

### B1. Recursion edges

`report.cycle_details` already classifies every cycle's `kind`. Thread it
into the generator: build a `set[tuple[source, target]]` of edges that close
a `PERFORM_RECURSION` cycle, and give those edges a distinct arrow —
dashed, `classDef recursion` gold stroke — instead of the plain `-->` a
recursive PERFORM gets today. A self-recursive paragraph (`length == 1`)
additionally gets a self-loop annotation on the node itself.

`GOTO_LOOP` and `MIXED` cycles get their own equally distinct treatment so
"this loop closes via GO TO" isn't visually confused with "this loop closes
via PERFORM recursion."

### B2. GO TO distinction

Today `GOTO`/`GOTO_DEPENDING`/`ALTER` share the same `==>` arrow as
recursion loop-backs — no color/dash distinction. Give GO TO-family edges
their own `classDef`/edge style (magenta dashed, per the reference mockup),
separate from B1's recursion styling, so the two "this isn't a normal
PERFORM" signals don't collide.

### B3. Exit points as terminal nodes

`FlowNode.has_stop_run` / `has_goback` / `has_exit_program` / `has_return`
are booleans with no location — today the whole paragraph box is just
tinted red, with no indication of *why* or *where*. Add location tracking
for the actual exit statement (small, additive `FlowNode` field, e.g.
`exit_statement_location: SourceLocation | None` — first exit statement
found in the paragraph) and have the generator emit a small synthetic
terminal node (double-circle shape) per exit point, labeled with the
statement kind and line number (`STOP RUN · 340`), connected from its
containing paragraph — rather than only tinting the paragraph box.

### B4. THRU-range badges

`PERFORM ... THRU` currently draws as two full, separately-labeled arrows
(`PERFORM` then `PERFORM THRU`) — `edges.py` already carries
`thru_target`/`range_members` on the base edge, so the second arrow is
redundant information drawn as a duplicate line. Collapse it into a compact
inline badge on the base edge/node (e.g. `[THRU n]` where `n` =
`len(range_members)`) instead of a second arrow.

## Testing

- `condition_text.py`: new unit tests covering each `ConditionalExpression`
  operator, `LogicalExpression` AND/OR (including nested), the class/sign
  form, `CONDITION_NAME`, the `metadata.raw_condition` fallback, and the
  final `expression_type` fallback (bare test double, unchanged behavior).
- `edges.py`/`scanner.py`: update existing condition-text assertions in
  `tests/unit/analysis/test_program_flow.py` to real parsed-COBOL fixtures
  (via `parse_cobol`, not the bare synthetic `CobolExpression` builders) for
  the *new* real-text cases; the existing synthetic-fixture tests
  (`test_if_with_else_creates_one_branch_node`, etc.) are left as-is per the
  fallback-compatibility guarantee above.
- `flowchart.py`: extend `tests/unit/generators/test_flowchart*.py` (or
  create it if it doesn't exist yet — confirm during implementation) with
  fixtures for: a self-recursive PERFORM, a multi-paragraph PERFORM-cycle,
  a GOTO_LOOP, a STOP RUN/GOBACK/EXIT PROGRAM mix, and a PERFORM ... THRU —
  asserting the Mermaid text contains the expected distinct classDef/arrow
  markers and terminal nodes.
- Existing `examples/cobol/shamrice/` and NIST suite smoke tests
  (`test_all_samples.py`, `test_shamrice_examples.py`) continue to exercise
  `--format mermaid` end-to-end against real programs without change.

## Out of scope

- No new CLI flags — `program-flow --format mermaid` already exists and is
  the only entry point this changes.
- No JSON schema changes beyond the additive `exit_statement_location`
  field on `FlowNode`/its `to_dict()` output (backward compatible — new key
  only present when non-null, same convention every other optional field on
  `FlowNode` already uses).
- No Mermaid "legend" block emitted by this repo — the consuming webview
  draws its own static legend in HTML/CSS around the rendered diagram (see
  the companion doc). This repo's job stops at emitting correctly
  color/shape-differentiated Mermaid syntax.
- `DotFlowchartGenerator` gets the same B1–B4 treatment for parity (it
  shares `FlowchartOptions` and much of the same per-edge logic today), but
  is not the primary target — Graphviz DOT has no active consumer in this
  request.
