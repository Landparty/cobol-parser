# Cross-record correlation in scenario planning

**Status:** built (2026-10-29) for the carrier shape below: carrier
detection (`analysis/constraints.py`, `_Carriers`, `CorrelationConstraint`),
two-row planning (`generators/scenarios.py`, `_solve_correlations`) and
verification (`generators/verification.py`). Items 1 and 2 of "What is
still missing" are done for an unconditional carrier MOVE in the comparing
paragraph; a carrier written in another paragraph, or only on some arms
(the `'05'`-then-`'09'` case in "The gap", where row *n-1* must itself take
an arm), is still refused and stays unsupported.
**Scope:** `generators/scenarios.py` (`ScenarioPlanner`),
`generators/program_fixtures.py`, `analysis/constraints.py`.

## The gap

A scenario that `ScenarioPlanner` names for a branch arm is not guaranteed to
*reach* that arm. Reported from a real run: a scenario named for
`221000-TRAITER-P-BAL-F-AVEC-M` traced into `222000-...-SANS-M` instead. The
paragraph is reachable only when a prior *manual* (`'05'`) record shares its
guichet number and date with a following *forced* (`'09'`) record — a property
of the record *sequence*, not of any single record. The fixture had to be
hand-crafted: rows 1 and 2 pinned to the same `GUICHET`/date, typed `'05'`
then `'09'`.

Two independent things make this class of arm unreachable, and both had to be
true for the failure to be silent:

1. **Witnesses are per-field, not per-row.** `PlannedScenario.witnesses` is a
   flat `dict[qualified_name, str]`, and `program_fixtures._value_for` ignored
   its own `row` argument whenever a witness existed. One value was pinned to
   *every* row, so "row 1 is '05' and row 2 is '09'" was not expressible at
   all — not merely underivable.
2. **Reachability is CFG-shaped, not data-shaped.** `ScenarioPlanner.plan`
   gates arms on `flow_report.unreachable_nodes`: is this paragraph the target
   of any PERFORM/GO TO. It never asks whether *this scenario's own data*
   drives execution into the arm. A CFG-reachable but data-unreachable arm is
   counted `targeted`, and a scenario is emitted and named for it.

Note the interaction with the v1 path-condition simplification already stated
in `scenarios.py`'s module docstring: a scenario takes only its target arm's
own conjuncts, and does not accumulate the enclosing branches on the path to
it. Cross-record correlation is the same problem one level further out — the
enclosing condition is not merely un-accumulated, it is not expressible.

## What landed now (groundwork)

`PlannedScenario.row_witnesses: dict[int, dict[str, str]]` — 0-based row index
→ `{qualified field name: witness value}` — overriding `witnesses` for that one
row. `_value_for` consults it before the scenario-wide `witnesses`, and
`_sequence_length` raises the generated row count so a pinned row always
actually exists (a witness pinned to a row the sequence never reaches would
silently do nothing).

Nothing populates it. `ScenarioPlanner` emits no `row_witnesses` today, so
every existing bundle is byte-identical. What changed is that the *pinning
path* is no longer the blocker: a correlated scenario can now be expressed,
including by a caller assembling one by hand. Covered by
`tests/unit/generators/test_row_witnesses.py`.

`FixtureBundle` is untouched, so `BUNDLE_VERSION` does not move and
mockymock's `bundle_version` gate is unaffected. `PlannedScenario` is internal
to the planner and not part of that contract.

## What is still missing

### 1. Recognizing the correlation

`ConstraintExtractor` refuses field-to-field comparisons outright:

    IF@54/THEN: comparison between two resolved fields not supported in v1:
    F1-REC.F1-GUICHET vs WS-PREV-GUICHET

That refusal is correct as a *constraint* — `WS-PREV-GUICHET` is
working-storage, not boundary-fed, so there is no value to solve for. But it
throws away the fact worth keeping: `WS-PREV-GUICHET` is a **carried copy** of
a boundary-fed field, written by `MOVE F1-GUICHET TO WS-PREV-GUICHET` on an
earlier iteration of the read loop. The condition is not unsatisfiable; it is a
statement about two different *iterations*.

Sketch of the analysis:

- Identify **carrier fields**: a working-storage field whose only writes are
  `MOVE <boundary-fed field> TO <it>`, inside the body of the loop that drives
  the boundary's READ. `ConstantFolder`'s forward walk already models MOVE
  chains and could be extended rather than duplicated.
- Rewrite a comparison `<boundary field> = <carrier of the same field>` into a
  new constraint kind — call it `SequenceCorrelation(field, offset=-1, op="eq")`
  — meaning "row *n* equals row *n-1* in this field". The offset comes from
  where in the loop body the carrier is written relative to the READ.
- Guard hard against the cases that make a carrier *not* a carrier: a
  conditional write (the carrier only updates on some arms), a write after the
  comparison rather than before, more than one writer, a write outside the
  loop. Any of these ⇒ no correlation, and an `unsupported` reason, per the
  project's "exact by construction, or absent" rule.

### 2. Planning a correlated scenario

Given `SequenceCorrelation` plus the arm's ordinary conjuncts, the planner
would emit `row_witnesses` for at least two adjacent rows: the correlated field
solved once and pinned identically across both, and each row's *own* discriminating
field solved from that row's own constraints (row *n-1* satisfying the
paragraph that writes the carrier, row *n* satisfying the target arm).

This is where a correlation becomes a **path** constraint: reaching
`221000` needs row *n-1* to have gone through `220000-TRAITER-P-BAL-M` at all.
Doing this properly probably wants the accumulated path conditions the v1
simplification defers — which argues for doing both together rather than
bolting correlation onto arm-local planning.

### 3. Honest accounting in the meantime

Independent of the above, and cheaper: when an arm's condition mentions a field
that is neither boundary-fed nor a recognized carrier, the arm is not
confidently `targeted`. Today the *branch* records an `unsupported` reason but
the planner may still emit and name a scenario. Options, in increasing cost:

- Mark such an arm `missed` with the extractor's own reason, so
  `ScenarioCoverage` stops over-reporting coverage. Changes counts, not data.
- Keep the scenario but flag it on the `Scenario` (e.g. an
  `Expectation(kind="stub", note=...)`) so a generated `.cut` carries a visible
  "this scenario is not verified to reach its arm" marker.

The second is the smaller behavior change and the more useful one downstream:
mockymock's generated `VERIFY <cat> <key> WAS CALLED n TIMES` lines are
boundary-keyed and cannot distinguish which branch fired, which is exactly why
this failure needed a `--trace` run to find. The DSL *does* support
`VERIFY PARAGRAPH <name> WAS PERFORMED n TIMES` (`PARAGRAPH`/`SECTION` are
`MockCategory` members in mockymock's `dsl/model.py`); emitting one per
scenario for its own target paragraph would turn "this scenario silently tests
the wrong branch" into a hard test failure. That belongs in mockymock's
scaffold, not here, but it is the natural consumer of an arm's target-paragraph
name — which `ScenarioPlanner` already knows (`ArmOutcome.parent_proc`).

## Recommended order

1. Target-paragraph reporting + honest coverage (item 3) — small, no new
   analysis, and it converts a silent wrong answer into a visible one.
2. Carrier detection (item 1) — self-contained, testable against
   `ConstantFolder`'s existing machinery.
3. Correlated planning (item 2) — do alongside path-condition accumulation,
   not before it.
