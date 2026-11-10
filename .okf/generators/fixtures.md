---
type: Module
title: Program Fixtures
description: The gen-fixtures program-scoped test-data stack in generators/ — ProgramLayoutIndex (data/program_layout.py), ProgramFixtureGenerator and the FixtureBundle shapes (program_fixtures.py, data/bundle.py), scenario-mode generation, self-verification (verification.py), path conditions, call_count/field_equals expectations, and ScenarioPlanner (scenarios.py).
tags: [generators, fixtures, gen-fixtures, program-layout, scenarios, verification, expectations, bundle, mockymock]
timestamp: 2026-10-15T00:00:00Z
---

# Program Fixtures

The `gen-fixtures` initiative's generator side (design:
`docs/plans/2026-08-02-program-data-generation-design.md`). Phase 1
`ProgramLayoutIndex` resolves a program's FD/record/field names to layout
facts; Phase 3 `ProgramFixtureGenerator` turns it plus Phase 2's
`BoundaryReport` ([analysis.md](../analysis.md)) into a `FixtureBundle`;
Phase 5 `ScenarioPlanner` turns Phase 4's constraints and the CFG into named
scenarios; Phase 6 wires them together; Phase 7 adds expectations. CLI:
`gen-fixtures` ([cli.md](../cli.md)); JSON shape:
[`docs/fixture-bundle-schema.md`](../../docs/fixture-bundle-schema.md). Start
with [Program fixtures](#program-fixtures).

## Contents

- [Program layout index](#program-layout-index)
- [Program fixtures](#program-fixtures)
- [Scenario-mode generation](#scenario-mode-generation)
- [Entry parameters](#entry-parameters)
- [Self-verification](#self-verification)
- [Path conditions](#path-conditions)
- [Expectations: tiers 1-2](#expectations-tiers-1-2)
- [Per-category generation rules](#per-category-generation-rules)
- [Determinism, `unresolved`, callees, `write_csv_dir`](#determinism-unresolved-callees-write_csv_dir)
- [Scenario planning](#scenario-planning)
- [Tests](#tests)
- [See also](#see-also)

## Program layout index

`data/program_layout.py`, Phase 1. Resolves a whole program's FD/record/field
names into layout facts the Phase 2 boundary walker joins against. Reuses
`FieldSpec`/`flatten_record` directly — no parallel value engine.

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
index.condition_values("WS-EOF")       -> tuple[str, ...] | None  # this 88's own values (not the parent's union)
index.condition_raw_values("WS-EOF")   -> tuple[str, ...] | None  # unexpanded ("THROUGH:<end>")
index.records()                        -> list[CobolDataItem]   # every top-level record, by section
index.linkage_records()                -> list[CobolDataItem]
index.working_storage_records()        -> list[CobolDataItem]
index.ambiguities                      # name -> qualified paths it maps to
index.unresolved                       # human-readable reasons, never silently dropped
```

### FD -> record resolution

The DATA DIVISION parser tags every level-01 FILE SECTION item with
`fd_file_name` (`parsers/divisions/data.py`) while scanning under an FD/SD —
that tag is the *only* source of truth this index uses (no positional
fallback: an untagged FILE SECTION record is reported in `unresolved`, never
guessed from source order). A table the OCCURS expansion caps cut short
is named in `unresolved` too (`layout.occurs_expansion_caveats`, #376), so a
fixture built from a partly-expanded record never looks complete. An FD
with more than one 01-level record (a
legal "record redefinition" idiom) tags all of them, so `records_for_file`
naturally returns every variant.

**FD vs SD.** The parser also tags `fd_record_type` (`"FD"` or `"SD"`). An SD
is a SORT/MERGE work file, not a file a program `OPEN`s;
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

### Name resolution

Every section's top-level records are flattened once via `flatten_record(...,
DataGeneratorOptions(include_filler=True, include_redefines=True))` — the
index must see *all* storage (FILLER, REDEFINES included); which fields are
generation-eligible is a later phase's concern, not an indexing one. A bare
name unique across the program resolves directly; one that exists at more
than one path returns `None` and is recorded in `ambiguities` instead of
guessed. Two qualified forms disambiguate it, and they read in **opposite**
segment orders for the same concept — never treat both as "first segment is
the field" (pinned by `test_dotted_qualifier_form_also_disambiguates`):

* `"A OF B"` / `"A IN B"` — COBOL's own syntax; the field name comes first,
  qualifiers follow.
* `"B.A"` — mirrors `FieldSpec.qualified_name` (root-first, field-last), so
  here the field name is the *last* segment and the qualifier(s) precede it.

**Level-88 names** resolve to their *parent* field's `ResolvedField` (a
separate recursive walk over each record's raw `CobolDataItem` tree, keyed by
qualified path, since `flatten_record` emits no `FieldSpec` for level-88/66
items). The same 88 name under parent fields in more than one record is
ambiguous: `_condition_index` keeps every parent, and a lookup mapping to more
than one distinct parent returns `None` and records the parents in
`ambiguities` — the same policy `resolve()`/`record_named()` apply to bare
names (pinned by
`tests/regression/test_audit_2026_08_12_analysis.py::TestB4DuplicateConditionNamesAreAmbiguous`).
A **qualified** 88 (`IS-OK OF REC-A`, `IN`, or dotted `REC-A.IS-OK`, see
#272) filters the declarations by its qualifiers with the field branch's rule
(each qualifier names the record or a group on the parent field's path)
before the one-parent check. `condition_values()` / `condition_raw_values()`
split the name with `split_qualified_name` and filter the same way (looking
up the raw text would miss every qualified name, and `gen-fixtures
--scenarios` every arm testing one). A *bare* duplicated 88 still refuses to
guess.

**`record_named(name)` — whole records, not fields.** `resolve()` only finds
*elementary* fields, because `flatten_record` never emits a `FieldSpec` for a
group item. A WRITE/REWRITE target, a READ `INTO` target, and an
SQL/ACCEPT/CICS/DLI operand can all legally name a *whole record* —
`resolve("INV-REC")` returns `None` for exactly this reason.
`record_named()` indexes every top-level (01/77) record by its own name,
across all four sections, independent of `flatten_record`. Same ambiguity
policy as `resolve()` (a name shared by records in more than one section
returns `None` and is recorded in `ambiguities`).

### Multi-program units and `from_file`

`build()` indexes exactly the `CobolProgram` node it is given — for a file
with stacked/nested programs (`CobolProgram.contained_programs`, e.g.
`tests/samples/subprogram_demo.cbl`'s caller + two callees), build a separate
index per program unit. This composes with `--callee-path` resolution,
whether the callee comes from a separate file or a contained program.

`from_file` raises `ProgramLayoutError` (not a bare
`FileNotFoundError`/`ParseError`) for every failure mode this module owns: a
nonexistent path (checked explicitly — `parse_cobol()` otherwise treats a bad
path string as literal, unparseable source text), a program that does not
parse to an AST at all, or — in the default `strict_copybooks=True` mode — a
COPY member `copybook_paths` cannot resolve (a layout with a hole in it is
wrong, not partial). `strict_copybooks=False` downgrades the last case to an
`unresolved` entry and falls back to parsing without expansion.
`build()`/`from_file()` also stamp `index.ast` with the `CobolProgram` the
index was built from, so a caller that kept only the index can reach the AST
without re-parsing (`ProgramFixtureGenerator.generate_from_file` depends on
it).

## Program fixtures

`program_fixtures.py` + `data/bundle.py`, Phase 3. `ProgramFixtureGenerator`
turns a program's `ProgramLayoutIndex` and `BoundaryReport` into a
`FixtureBundle`: layout-valid random values for every boundary, assembled into
one "happy path" `Scenario`. `bundle.py` holds `BUNDLE_VERSION` (currently
`1`), `Expectation`, `BoundaryFixture`, `CoverageSummary`, `Scenario`,
`FixtureBundle`.

```python
from cobolparser.generators import ProgramFixtureGenerator

generator = ProgramFixtureGenerator()                  # or pass DataGeneratorOptions
bundle = generator.generate_from_file(
    "INVUPDT.cbl", copybook_paths=[...], callee_paths=[...], seed=7,
)
bundle.scenarios[0].fixtures       # list[BoundaryFixture]: mock in-data
bundle.scenarios[0].expectations   # list[Expectation]: assert-on stubs
bundle.coverage                    # CoverageSummary (boundary-level, v1)
bundle.unresolved                  # every gap from Phases 1-2-3, merged (each once:
                                   # a boundary gap also in report.unresolved is
                                   # not repeated, #505)
bundle.to_json()                   # bundle_version, program_name, seed, ...
bundle.write_csv_dir("out/")       # out/<scenario-slug>/<KEY>.csv + MANIFEST.json
```

Reuses the value engine directly: each boundary's field list — however it
was resolved (`ProgramLayoutIndex.resolve()` for an elementary field,
`.record_named()` for a whole record) — is generated with a `ValueFactory`
exactly like `CopybookDataGenerator` uses ([record-data.md](record-data.md)).

**Columns are unique across a fixture's records** (see #365). A fixture can
draw fields from several records (a CALL's `USING` arguments, a READ's
alternate FD records), but `flatten_record()` only makes columns unique
*within* one record, and a row is keyed by `spec.column` — so `REC-A.AMT` and
`REC-B.AMT` would share one value and one header. `_unique_columns()`
de-duplicates the combined list on `(qualified_name, subscripts)` (the same
argument passed twice is one set of fields) and, only on a collision, re-runs
`layout.assign_columns` over *copies* of the whole list (a spec from
`ProgramLayoutIndex.resolve()` is the index's own), so the colliding names
become `REC-A.AMT` / `REC-B.AMT` and every other column keeps its short
header.

## Scenario-mode generation

`generate_with_scenarios(ast, index, report, mode="happy"|"branches"|"all",
seed=...)` (and `_from_file`), Phase 6: `mode="happy"` routes straight to
`generate()` (byte-identical output, same seed — pinned by
`test_fixture_bundle_contract.py::TestScenarioModeContract::test_happy_mode_is_byte_identical_to_generate`);
`"branches"`/`"all"` run `ConstraintExtractor` + `ProgramFlowAnalyzer` +
`ScenarioPlanner` internally and turn every `PlannedScenario` into a real
`Scenario` with populated fixtures. The happy-path scenario from `generate()`
(same seed) is always prepended, so a program with no targetable arm still
gets one scenario rather than an empty bundle (mockymock `generate
--with-data` fails on an empty one).

```python
bundle = generator.generate_with_scenarios_from_file(
    "INVUPDT.cbl", mode="all", seed=7,
)
bundle.scenario_coverage   # ScenarioCoverage.to_dict(), None in mode="happy"
```

**Every scenario still gets a complete fixture for every boundary** — the
program under test touches all of them regardless of which branch arm a
scenario targets. Only the field(s) a `PlannedScenario` constrains are pinned;
everything else is generated by the happy path's `ValueFactory` path. This is
threaded through an optional `override: PlannedScenario | None` parameter on
the internal `_build_fixture`/`_build_call_fixture`/`_status_dict` helpers:

* **Witnesses** — `override.witnesses` is keyed by `FieldSpec.qualified_name`;
  a matching field's generated value is replaced by the witness verbatim
  (already PICTURE-valid from `domains.solve()`). This pins one value to
  **every** row of a multi-row sequence.
* **Per-row witnesses** — `override.row_witnesses` (0-based row index →
  `{qualified name: value}`) overrides `witnesses` for one row only, and
  `_sequence_length` raises the generated row count so a pinned row always
  exists. The flat `witnesses` dict cannot express a branch reachable only
  when a record correlates with the one before it; `ScenarioPlanner` fills
  `row_witnesses` for such an arm (see [Cross-record
  correlation](#cross-record-correlation)). Design:
  [docs/plans/2026-09-04-cross-record-correlation-design.md](../../docs/plans/2026-09-04-cross-record-correlation-design.md).
* **Sequence length** — `override.sequence_constraints` (matched by
  `(category, key)`) overrides a READ boundary's row count, e.g. the "empty
  input" family's `length=0`. Falls back to `--rows` (READ) / `1` (everything
  else) like the happy path when no override applies.
* **Status** — `override.status_overrides` (keyed by `"<CATEGORY>:<KEY>"`,
  or `"<CATEGORY>:<KEY>@<line>"` for one statement only; the per-line key
  wins) replaces the default status value (`"00"`/`"0"`) for the
  error-status and file-status families and any status-targeting scenario.
  An OUT boundary (WRITE/REWRITE) whose override is a failure comes out
  `STATUS_ONLY` with that status: nothing was written.
* **Keyed READ key** (see #322; every scenario including the happy path) — a
  successful keyed READ of an INDEXED file (RANDOM access, or DYNAMIC without
  NEXT/PREVIOUS/FIRST/LAST; `const_fold.keyed_read_key`) returns the record
  whose key the program set, so `_pin_read_keys` writes the key's value at
  that READ (`ConstantFoldResult.read_keys`, matched by `(file, line)`; folded
  from literals plus the scenario's other single-row mocked inputs, never the
  READ's own record) into every row of its fixture, overriding generated
  values and witnesses alike. When the key is not known there (set in a
  branch or loop, never set, or a READ INTO whose rows do not carry the FD
  key) it stays generated and the happy path adds one `unresolved` note for
  that READ. Two READs of one file can write different rows, so
  `write_csv_dir` names the second `<KEY>-2.csv` (its `_csv_names` rule).

`FixtureBundle.scenario_coverage` (additive field — `bundle_version` stays
`1`) carries `ScenarioPlan.coverage.to_dict()` verbatim, `None` for a
`mode="happy"` bundle since that mode never attempts branch targeting.

## Cross-record correlation

An arm whose condition compares a boundary-fed field with the *previous*
record's value (`IF TXN-BRANCH = WS-PREV-BRANCH`, `MOVE TXN-BRANCH TO
WS-PREV-BRANCH` later in the paragraph) carries a
`BranchConstraints.correlations[arm_id]` list of `CorrelationConstraint`s
(the extractor side: [../analysis/fixtures-support.md](../analysis/fixtures-support.md)).
`ScenarioPlanner.plan()` gathers the arm's own plus its exact enclosing
arms' (`_path_correlations`; an OR-split enclosing arm with one is a
`path_gaps` entry) and `_solve_correlations()` pins two rows: row 1 gets the
compared field's value (its scenario witness, else `solve(spec, own)`), row 0
a value of the carried field meeting the flipped operator against it. Both
fields must belong to one READ boundary's records, else the arm is `missed`
("not read by one READ sequence"); an unsatisfiable pair is `missed` too
("unsatisfiable: no value of X in the record before ..."). The scenario
keeps `correlations` (in `PlannedScenario.to_dict()` only when non-empty),
says so in its `intent`, is never merged, and an OR-split disjunct is named
for its comparison (`[F1-KEY <> previous F1-KEY]`).
`verification.verify_scenario` adds one verdict per correlation, labelled
`"<field> vs the previous record's <source>"`: `satisfied` when some row
n >= 1 of a fixture holding both fields meets it against row n - 1. Bundles
of programs with no correlation are unchanged (`BUNDLE_VERSION` stays).
Pinned by `tests/unit/generators/test_cross_record_correlation.py`, incl. a
GnuCOBOL run of `tests/samples/correlation/BRKRPT.cbl` (skipped without
`cobc`) showing only the correlated scenario reaches its paragraph.

## Entry parameters

`ProgramFixtureGenerator(options, entry_parameters=True)` (2026-10-21,
mocky-mock#275) treats the program's own PROCEDURE DIVISION USING items
(`procedure.get_metadata("using_parameters")`, DFHEIBLK left out) as one
more boundary, for a called subprogram whose whole interface they are.
`_attach_entry_parameters` sets `Scenario.entry_parameters`: a
`BoundaryFixture` with ref `ENTRY:<PROGRAM-ID>`, layout over the items'
elementary fields (`_fields_for_names`), one row from a
`_sub_seed(seed, scenario, "ENTRY", program)` `ValueFactory`, witnesses
pinned through `_value_for` like any fixture; and a `stub` expectation per
field whose path includes a LINKAGE name xref gives role `write`, plus the
RETURNING item. `generate_with_scenarios` passes the names to
`ConstraintExtractor.extract(..., extra_fed_names=...)`, so branches on the
parameters are planned; `verify_scenario` and `_single_row_seeds` read the
row too. Off by default: no `entry_parameters` key, identical values.
Layout registered under `layouts["ENTRY:<PROGRAM-ID>"]`. Tests:
`tests/unit/generators/test_entry_parameters.py`.

**CICS programs (2026-11-02).** With `entry_parameters=True` and a CICS
boundary, `_add_cics_interface` calls `ProgramLayoutIndex.add_cics_interface()`
(a synthetic LINKAGE `01 DFHEIBLK`, the translator's layout, when the program
declares none; `index.synthetic_eib`), and `_entry_parameter_names(ast,
index)` adds `DFHCOMMAREA` (when declared and not already in USING) and
`DFHEIBLK`: CICS passes both. Only the EIB fields a scenario's witnesses pin
go into the row (`IF EIBCALEN = 0` / `IF EIBAID = X'F3'` on the path to an
arm), so the happy path keeps CICS's start values. Tests:
`tests/unit/test_cics_entry_scenarios.py`.

**Edge scenarios (2026-11-02).** `ScenarioPlanner.plan` adds, after the
merged branch scenarios, each targeted arm again once per numeric `<`, `<=`,
`>`, `>=` conjunct of its own with that field pinned to the edge the arm
still takes (`_edge_scenarios`; named `<arm> at <FIELD> = <value>`). They are
never merged and add no `ArmOutcome`. A change to a limit then moves a case
from one arm to the other.

## Self-verification

A scenario's *name* is a claim. `generators/verification.py`'s
`verify_scenario(planned, scenario)` re-reads the scenario's OWN emitted
fixture data and re-checks every planned conjunct against it;
`generate_with_scenarios` stores the verdict (a `ScenarioVerification`:
`status` `"verified"`/`"unverified"`, `fields: list[FieldVerdict]` of
`field`/`status`/`detail`/`rows`, `gaps`) on `Scenario.verification`
(serialized `{"status", "fields", "gaps"}`; additive, `bundle_version` stays
`1`; `None` for a `mode="happy"` scenario, which targets no branch).

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

**A `violated` verdict demotes the scenario's arms to `missed`** (see #244).
`generate_with_scenarios` passes each verdict to `_demote_violated_arms`:
every `targeted`/`merged` arm of a scenario with a `violated` field is
re-counted as `missed` in `scenario_coverage` (reason `"witness failed
verification: ..."`, counts kept exact) and gets one `bundle.unresolved`
entry, so `gen-fixtures --strict` exits 2 rather than passing a coverage claim
its own data contradicts. `absent`/`unknown` do not demote — they are "could
not tell", which `unverified` already says.

`cli/commands/data.py`'s `gen-fixtures` prints an unverified summary on **stderr**
(stdout stays JSON-only — mockymock's `fixtures` contract), and mockymock's
`generate --with-data` renders the same reasons as a `*> UNVERIFIED:` comment
above the affected TESTCASE.

## Path conditions

A scenario must pin its arm's whole path, not just the arm's own conjuncts: on
a nested `IF INV-QTY > 500 / IF INV-TYPE = "AB"`, pinning only `INV-TYPE`
leaves `INV-QTY` wherever the value generator put it, so the data usually
never enters the outer arm. `ConstraintExtractor` records on every
`BranchConstraints` the `enclosing` `(branch_id, arm_id)` chain whose arms
must all be taken for that decision point to be reached (`_walk_list` threads
it down through `_nested_statement_lists`, which pairs each nested statement
list with the arm id it sits under; an earlier early-exit guard in the same
list -- `IF RC NOT = 'V' ... GO TO EXIT-PARA END-IF` -- joins the chain with
its staying arm, see `_guard_arm` in
[../analysis/fixtures-support.md](../analysis/fixtures-support.md)).
The "boundary values" family takes an OCCURS DEPENDING ON counter's extremes
from its table's bounds, not its picture. `scenarios._path_options()` joins
on those pairs (offering each OR-split `#N` variant as an alternative, picked by
`_solve_with_path()`) and `ScenarioPlanner.plan()` folds the enclosing conjuncts into the targeted arm's own
before solving. Consequences:

* An arm that becomes unsatisfiable once its path condition is added (outer
  `X > 5`, inner `X < 3`) is `missed` with `"unsatisfiable with its own path
  condition: ..."`, not targeted with data that could never reach it.
* An enclosing arm the constraint report never modeled contributes a
  `PlannedScenario.path_gaps` entry instead of silence, and that alone makes
  the scenario `unverified` — the arm may still not be reached, and saying so
  beats an optimistic label.
* **An OR-split enclosing arm is a disjunction, and is folded as
  alternatives** (`_path_options` + `_solve_with_path`). `_register_variants`
  registers `THEN#1`/`THEN#2`/... and NO bare `THEN` for a condition
  containing an OR, while `enclosing` names the base arm id — so a plain
  `arms_by_key[(branch_id, "THEN")]` lookup misses every such arm and
  silently leaves the path unfolded. Each `#N` variant is one way to satisfy
  the same arm, so the planner tries them in order and keeps the first that
  stays satisfiable alongside the targeted arm's own conjuncts. Fixing on the
  first disjunct would be wrong, not just suboptimal: for `IF A = 100 OR A =
  200 / IF A = 200` it makes the set unsatisfiable and reports the inner arm
  unreachable when `A = 200` reaches it. `_MAX_PATH_COMBINATIONS` caps the
  cross product a deep chain of disjunctive arms would otherwise produce.
* **The path crosses paragraphs** (#310). `enclosing` stops at the top of
  the branch's own paragraph, so a branch in a paragraph PERFORMed from
  inside another paragraph's arm (`IF IN-CODE = 'QQ' PERFORM DEEP-PARA`)
  used to get a `verified` scenario whose data never ran it.
  `_ParagraphReach.path_to(parent_proc)` prepends the arms that must be
  taken for the paragraph to run at all, from `ConstraintReport.
  transfer_sites` (each `PERFORM p` / `GO TO p` with its own `enclosing`)
  and the CFG's incoming edges: the entry paragraph, or any one
  unconditional site, needs nothing; exactly one site folds that site's
  arms (and, recursively, its paragraph's); several guarded sites, `GO TO
  ... DEPENDING ON`, a SORT / XML / handler / ALTER transfer or a cycle add
  a `path_gaps` reason instead. A CFG fall-through out of a paragraph only
  counts as a way in when control can run off its end (`_falls_off`): a
  paragraph entered only by a plain `PERFORM` returns there. Sections are
  procedures too: a section header always runs into its first paragraph
  (which is reached exactly when the section is), a paragraph run as part
  of its section runs on to the next one, and the last paragraph falls off
  into the next section only when its own section can (a `PERFORM S`
  returns at S's end). Membership comes from `flow_report.nodes`' source
  order.
* **`_merge_candidates` carries `path_gaps` across a merge.** A merged-in
  candidate brings its own unpinned enclosing arms with it; dropping them
  would let the merged scenario report `verified` while an arm it claims is
  not pinned — the silent false positive `path_gaps` exists to prevent.
* **`_merge_candidates` never merges an `ends_run` scenario** (its arm is in
  `BranchConstraints.ending_arms`: STOP RUN / GOBACK, or a write to an item a
  `PERFORM ... UNTIL` tests), in either direction: what the other arm needs
  comes after the run or the loop ended.
* A guard arm id joining several staying arms (`WHEN_1|WHEN_2`,
  `GUARD_ALTERNATIVES`) gives `_path_options` one alternative per modeled
  staying arm.
* IF/EVALUATE/SEARCH arms join the chain, including **SEARCH's `AT END`**
  (`_ARM_BEARING_ATTRS`): `_extract_search` registers an `arms["AT_END"]`
  entry, so a statement nested under it has an enclosing arm to join to, even
  though the clause reaches the walk as a handler body rather than a
  `when_clauses` arm. It carries no conjuncts (the real precondition,
  "the table search found nothing", is not a field constraint), so it lands in
  `path_gaps` — which is the point: untagged, a branch inside it would look
  top-level and could be reported `verified` without its data establishing
  the search fell through. A genuinely non-branch nesting (`ON EXCEPTION`, an
  inline `PERFORM` body) contributes nothing: inventing an id for one would
  produce a path entry nothing could join to.

## Expectations: tiers 1-2

Every scenario's `expectations` (in both `generate()` and
`generate_with_scenarios()`) carries structural and computed assertions
alongside the OUT-boundary stubs, via two helpers in `program_fixtures.py`.
Both run once per scenario, after that scenario's `fixtures` list is fully
populated (so Tier 2 sees the *actual* values for that scenario). Both run
inside `generate()` itself, so `generate_with_scenarios(mode="happy")`
carries the exact same expectations.

* **Tier 1 — `_CallCounter`** (see #363). One
  `Expectation(kind="call_count", ref="<CATEGORY>:<KEY>", value=times)` per
  mocked `(category, key)` — every statement invoking the same boundary merged
  into one count — and only when that count is exact; otherwise none. A group
  whose boundaries got no fixture (OUT-only, nothing generatable) has nothing
  mocked to count and gets none. `times` comes from
  `cobolparser.analysis.invocation_counts.count_invocations` (see
  [analysis.md](../analysis.md)): the sum of each invoking statement's static
  execution count along the entry chain — main line and SIMPLE PERFORMs count
  once per time reached, `PERFORM <literal> TIMES` multiplies, and anything
  inside an IF/EVALUATE/SEARCH arm, a handler, a `PERFORM UNTIL`/`VARYING`
  body, a SORT procedure, or after a branch that could transfer control has no
  count. The one data-dependent exception is the read-until-EOF idiom: a READ
  file with a `SequenceConstraint` whose `PERFORM UNTIL` itself runs exactly
  once, tests only the EOF flag and has no transfer in its body
  (`is_plain_eof_loop`), is invoked `len(sequence) + 1` times (every row, plus
  the READ that hits end of file), whichever READ statements share the work —
  a priming READ and the loop's READ are one count. A straight-line READ with
  an AT END handler is invoked once, not `rows + 1`. Each count is inserted
  where the group's first fixture's expectations start and keeps the stub's
  `note`.
* **Failure-path scenarios** (see #318). A `PlannedScenario` with any
  `status_overrides` (the error-status family, and "empty input" when it
  overrides SQL to 100) runs the program's error path, which the generated
  sequences do not describe. `_drop_failure_path_counts` keeps only the
  overridden boundary's own `call_count`, and only when it is not a READ;
  every other count is dropped, because `report.boundaries` is source order,
  not execution order, so no boundary is provably *before* the failure. Tier
  2 is skipped for these scenarios entirely: the fold walks the normal path,
  so even a literal-only `field_equals` may observe a site the failure path
  never reaches.
* **Tier 2 — `_tier2_expectations`, backed by
  `cobolparser.analysis.const_fold.ConstantFolder`** (see
  [analysis.md](../analysis.md) for the folder's "exact by construction, or
  absent" rules). Builds a seed dict from every `BoundaryFixture` in the
  scenario with *exactly one* generated row — a multi-row READ sequence has
  no single representative value — keyed by `spec.qualified_name` from
  `fixture.layout`/`fixture.sequence[0]`, then folds the program's entry
  paragraph chain seeded with those values, turning every field still
  knowable at a `DISPLAY`/`WRITE` (and still holding that value when the
  entry paragraph returns, where mockymock's `EXPECT` checks it) into
  `Expectation(kind="field_equals", ref=qualified_name,
  value=folded_value)`. The seeds also decide IF/EVALUATE branches the
  scenario's own data settles (see the fold's rules in
  [analysis/fixtures-support.md](../analysis/fixtures-support.md)). The fold (and `_pin_read_keys`'
  folds) get the Tier 1 counter's `InvocationCounts.success_skipped`, so a
  STOP RUN / GOBACK in a status check's failure arm does not blank the
  happy path's expectations while one in any other arm does (#591).

## Per-category generation rules

| Category / direction | What gets generated |
|---|---|
| `READ` (IN) | `options.rows` rows; when `"AT_END"` is in the boundary's `handlers`, `terminal` is set to `{resolved_field: "10"}` if `_resolve_status_field` finds a real field name (`boundary.status_field`, else `index.file_facts(key).file_status_field`), or stays `None` if neither resolves — never a placeholder key such as `"FILE-STATUS"`, which is not a real data-name in the target program |
| `WRITE`/`REWRITE` (OUT) | No fixture (nothing to mock) — one `Expectation(kind="stub")` noting the program produces this value |
| `OPEN`/`CLOSE`/`DELETE`/`START`/`UNLOCK` (`STATUS_ONLY`) | A fixture with `status` only (e.g. `{"WS-FS": "00"}`), no `layout`/`sequence` |
| `SQL`, `sql_type` SELECT/FETCH (IN) | One generated row; `status={"SQLCODE": "0"}`, or the scenario's SQLCODE witness when a branch tests the SQLCODE this statement leaves (synthetic field `SQL@<line>.SQLCODE` / `FETCH@<line>.SQLCODE`, #840) |
| `SQL`, INSERT/UPDATE/DELETE (OUT) | Expectation stub, like WRITE |
| `CICS`/`DLI` (`BIDIRECTIONAL`, best-effort) | Whatever fields resolved get generated values *and* an expectation stub — Phase 2's own layout resolution here is already best-effort (no fixed INTO/FROM attributes), so this phase does not pretend otherwise |
| `ACCEPT` (IN) | One generated value |
| `CALL`/`DYNCALL` | Per-argument: IN/BIDIRECTIONAL args' fields are generated into **one combined row** (one CALL invocation, all its IN arguments at once); OUT args get an expectation stub reading "value supplied by the program under test, not mock-generated"; BIDIRECTIONAL args get both a generated value **and** a stub noting the OUT aspect isn't asserted yet; `RETURNING`/`GIVING` parameters always get a generated value (`provenance="giving-parameter"`). A quoted / numeric literal, figurative constant, `LENGTH OF x` or `FUNCTION ...` argument is a value the caller supplies and `OMITTED` is an empty position: skipped, never a resolution gap (#579, #582); `ADDRESS OF x` resolves against `x`. When a branch tests the CALL's `RETURN-CODE` (#831), the combined row also carries a `RETURN-CODE` column (synthetic field `CALL@<line>.RETURN-CODE`): the scenario's witness, else `0`. A subscripted or reference-modified argument (`WS-CODE(WS-I)`, `WS-KEY(1:4)`) passes only part of an item: no value is generated and its `unresolved` note says so. The fixture's own `direction` is its arguments' (`program_fixtures._call_direction`: all-IN arguments or none (only RETURN-CODE) give IN, any OUT or BIDIRECTIONAL argument gives BIDIRECTIONAL: the fixture always supplies a value, so it is never OUT); `boundary_inventory` leaves a CALL boundary's statement-level direction empty, and that `""` used to reach the bundle |

A name may resolve to either an elementary field or a whole record
(`_fields_for_name`/`_fields_for_names`, private helpers using the same
`resolve()`-then-`record_named()` fallback `BoundaryInventoryAnalyzer` uses)
— a CALL argument or SQL host variable can legally be either.

**Several 01 records under one FD** (see #364). A READ with no INTO gets every
record of its FD in `Boundary.record_names` (Phase 4's `ConstraintExtractor`
relies on that to know every field the READ feeds), but those records are
views of ONE record area — an implicit REDEFINES. Joining their fields into
one row would give `HDR-TYPE` and `DTL-TYPE` (both offset 0) two different
values, grow the record to the sum of the records' lengths, and drop a
repeated field name (the `REC-TYPE` idiom) in the column de-dup. So
`_record_view()` picks exactly one record per scenario: the one holding the
most of that scenario's pinned fields (`witnesses` + every `row_witnesses`
row), the first in source order on a tie or with no scenario. `bundle.layouts`
is keyed by the chosen record, so a scenario that picks the second record adds
its own key. `bundle.unresolved` carries one note per such READ, naming the
records no scenario generated ("alternate view(s) not generated: ..."),
computed after generation from the records actually used (the happy path
always uses the first). Only `READ` boundaries are narrowed: an SQL
boundary's several names are distinct host variables. Pinned by
`tests/unit/test_program_fixtures.py::TestMultipleRecordsUnderOneFd`.

Fields of two such records have different names but share bytes, so
`ScenarioPlanner` (`_shared_record_areas()` / `_record_areas()`) never merges
an arm pinning one record into a scenario pinning another, and an arm whose
own path pins both is `missed` ("pins fields of several 01 records of one
FD"). As a guard, a scenario that still pins two views (hand-built, or a
future planner path) has every arm counted `missed` with that reason, the
way a violated witness demotes, since its dropped pins are never generated.
Pinned by `TestArmsOnTwoRecordsOfOneFd`.

**A FILLER that owns a level-88.** `05 PIC X. 88 FLAG-ON VALUE 'Y'.` (or `05
FILLER PIC X. 88 ...`) is a flag the program branches on.
`ProgramFixtureGenerator` sets `DataGeneratorOptions.include_condition_filler`,
so `flatten_record` keeps such a FILLER even with `include_filler` off (plain
gen-data still drops it). Its path segment is `FILLER#<n>`
(`layout_segment()`, *n* its 1-based position among its group's FILLERs), so
two flag FILLERs in one group have distinct qualified names, witnesses and
columns, and `ProgramLayoutIndex` maps each 88 to its own FILLER rather than
the group's first. Plain FILLERs keep `FILLER`. Pinned by
`TestFillerOwningConditionName`.

## Determinism, `unresolved`, callees, `write_csv_dir`

**Per-boundary sub-seeds.** One `bundle.seed`. Each boundary derives its own
`zlib.crc32(f"{scenario}|{category}|{key}".encode()) ^ bundle_seed`, feeding
a fresh `random.Random`/`ValueFactory`. Deliberate: a single shared RNG
consumed in iteration order would reshuffle every later boundary's values
the moment an earlier one changed shape (a new field, a resized OCCURS) —
sub-seeding keeps a bundle stable under unrelated additions. `zlib` is
stdlib; the zero-dependency rule holds. Pinned by
`test_program_fixtures.py::TestDeterminism` and the corpus-wide
`test_gen_fixtures_corpus.py::test_determinism_across_the_corpus`.

**`bundle.unresolved`** is the union of three layers, because a consumer must
never have to check Phase 1/2/3's own gap lists separately:
`ProgramLayoutIndex.unresolved` (Phase 1 — merged into
`BoundaryReport.unresolved` by `BoundaryInventoryAnalyzer.analyze()` itself,
see [analysis.md](../analysis.md)), `Boundary.unresolved` (Phase 2, per
boundary), and anything Phase 3's own field resolution fails to pin down (an
argument name that resolves to nothing generatable). Without the Phase 1→2
merge, `--strict` on a program with a Phase-1-level gap (`report_test.cbl`'s
Report Writer FD) exits 0 instead of 2.

**`--callee-path` resolution.** `ProgramFixtureGenerator._resolve_callees`
builds `callee_indexes`/`callee_asts` for `BoundaryInventoryAnalyzer`'s
Phase 2b "callee source" rung two ways, merged: every
`CobolProgram.contained_programs` entry (free — no file search, e.g.
`subprogram_demo.cbl`'s bundled caller + callees), then — for any remaining
statically-CALLed program name — a search across `callee_paths` directories
trying `NAME`/`name` × `""`/`.cbl`/`.CBL`/`.cob`/`.COB`. A callee that fails
to parse is skipped (falls through to the caller-dataflow rung), not a hard
error — one bad `--callee-path` entry should not sink the whole bundle.
An optional `accept(path) -> bool` vets each file found before it is
opened (the MCP server passes `Workspace.under_root`, so a symlink out of
the root is never read); a refused file is treated as not found.

**`write_csv_dir`.** One `GeneratedDataset`-shaped CSV per fixture whose
`layout`/`sequence` are both non-empty, or whose `layout` is non-empty with
an empty `sequence` and direction IN/BIDIRECTIONAL (`_writes_csv`): that is
the "empty input" scenario's READ, written **header-only** so its
`csv_path` is not `null` like a STATUS_ONLY boundary's (#568).
`STATUS_ONLY`/OUT/expectation-only fixtures produce nothing to write. Under
`<path>/<scenario-slug>/<KEY>.csv`. A `MANIFEST.json` at the root is the full
bundle with each fixture's `sequence` emptied to `[]` (never replaced with a
pointer string — a consumer running the manifest through the same
deserializer as a real bundle would silently iterate a string
character-by-character instead of hitting a type error) plus a `csv_path` key
(the relative CSV path, or `null` if this fixture got no CSV), so a consumer
can discover what scenarios/fixtures exist — and where each one's CSV lives —
without walking the directory tree. **Names are made unique**: the planner
names scenarios uniquely, but a hand-built bundle can repeat one, and two
names slugging to one directory would let the later scenario's CSV overwrite
the earlier one's with both manifest entries pointing at the survivor.
`_unique_names` suffixes a repeated slug `-2`, `-3`, ... (first keeps its
plain slug, case-insensitive), and `_csv_names` does the same for a
`<KEY>.csv` two fixtures would write with *different* rows (identical
same-key fixtures share one file). Both passes use the one precomputed name
list, so `csv_path` always names the file written. See
`docs/fixture-bundle-schema.md`'s "write_csv_dir" section for the full
manifest shape.

## Scenario planning

`scenarios.py`, Phase 5. Turns Phase 4's `ConstraintReport` and
`ProgramFlowAnalyzer`'s control-flow graph into a set of named
`PlannedScenario`s — one (or a merge of several) per reachable, satisfiable
branch arm — with exact coverage accounting. Driven by `gen-fixtures
--scenarios branches|all` through `generate_with_scenarios` (above);
`FixtureBundle.scenario_coverage` carries `ScenarioCoverage.to_dict()`
verbatim.

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
# generate_with_scenarios does the same through one ProgramContext, so the
# xref and flow graph are built once per bundle (not per step and scenario)

plan = ScenarioPlanner().plan(
    constraint_report, flow_report, boundary_report, mode="all"
)
plan.scenarios           # list[PlannedScenario]: name, intent, field_constraints,
                         # witnesses, row_witnesses, sequence_constraints,
                         # status_overrides, arm_keys, path_gaps
plan.coverage            # ScenarioCoverage: total_arms == targeted + merged + missed
plan.coverage.details    # list[ArmOutcome]: arm_key, parent_proc, status,
                         # merged_into, reason, origin -- a reason on every miss
```

`plan(..., *, mode="branches")` — the planner's own default is `"branches"`
(`ProgramFixtureGenerator.generate_with_scenarios`'s is `"happy"`).

**Path conditions are folded in** (see [Path conditions](#path-conditions)):
a targeted arm's witness set includes the conjuncts of every enclosing arm on
its path; an unmodelled enclosing arm becomes a `path_gaps` entry. Coverage is
still *arm* coverage, CFG-shaped rather than data-shaped.

**Joining a `BranchConstraints` to its `BranchNode`** is by `(line, column)`,
both derived from the identical statement's `SourceLocation` in both walks
(`BranchConstraints.column` exists for this join). Not by string-matching
`branch_id` to `BranchNode.node_id` (replicating `program_flow/scanner.py`'s
sequential counter would couple this module to that scanner's traversal
order), and not by comparing `parent_proc` strings: `scanner.py` uppercases
its `parent_proc` (`pname.upper()`) while `ConstraintExtractor` preserves the
source's casing.

**OR-split arms and the flow graph.** `BranchNode` always has exactly one
`BranchArm` per THEN/ELSE/WHEN/WHEN_OTHER slot, but Phase 4 may have OR-split
one of those into several arm-ids (`"ELSE#1"`, `"ELSE#2"`, ...) — see
constraints.py's De Morgan section in [analysis.md](../analysis.md). A base
arm-id with *any* representation in `BranchConstraints.arms` (bare or
`#N`-suffixed) counts as covered; only a base arm-id with **zero**
representation is a genuine `"missed: ..."` gap (a bare `"ELSE"` lookup alone
would double-report a split arm as also missed).

**Merging.** Two candidate scenarios merge when their constraint sets touch
disjoint fields *and* their sequence constraints agree on every shared
boundary (same length, or one side doesn't mention it) — greedy,
deterministic: candidates are processed in `(line, column, arm_id)` order,
each merging into the first open scenario it is compatible with. "Fewer,
richer scenarios" rather than one per arm. Arms on different 01 records of
one FD never merge (see [Per-category generation
rules](#per-category-generation-rules)).

**Naming** (see #267). One arm's name is `"<proc>: <VERB>@<line> <arm
label>"` — `"MAIN-PARA: IF@11 THEN"`, `"P: EVALUATE@90 WHEN 'A'"` — with the
verb read off a conjunct's `origin` (else the flow graph's `branch_type`). An
OR-split arm (`THEN#2`) appends its own disjunct, rendered from its conjuncts
(`"... THEN [WS-A = 'Z']"`), or `[alt N]` when it has none. After merging, a
scenario is renamed for *every* arm it targets (later arms in the same
paragraph drop the repeated `"<proc>: "`), joined with `" + "`, or the first
arm's name plus `" (+N more arms)"` past 120 characters; then
`bundle._unique_names` suffixes any repeat `-2`, `-3`, ... — so names are
unique within a plan (two IFs in one paragraph get distinct names).
`ArmOutcome.merged_into` carries the *final* name. `name` stays free text (no
`bundle_version` bump).

**Unmodeled arms** (see #509). An arm listed in `BranchConstraints.
unmodeled_arms` -- a `WHEN OTHER` whose earlier arms do not negate to one
`not_in_set`, every SEARCH `AT_END` -- carries `[]` meaning "precondition
unknown", not "anything goes". The planner counts it `missed` with reason
`"precondition not modeled: <extractor's reason>"` before any solving, and
adds a note to `ScenarioPlan.unresolved`, which `generate_with_scenarios`
copies into `FixtureBundle.unresolved` so `--strict` exits 2. Solving the
`[]` instead targeted the arm with random rows that ran an earlier WHEN
(always, for a level-88 field), and verification of zero conjuncts said
`verified`. Unreachable/unsatisfiable misses are facts about the program
and do not go to `unresolved`; an unmodeled arm is a gap in the tool. A
`WHEN OTHER` after an unsupported WHEN (e.g. a working-storage subject no
boundary feeds) is not in `unmodeled_arms` and not in `arms` at all: it is
missed for that WHEN's reason (`_reason_for_missing_arm`) and, like it,
adds no `unresolved` note.

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
  `"23"` (`"22"`, duplicate key, on a WRITE); a CALL's `ON_EXCEPTION` ->
  `"12"`; an OPEN INPUT / I-O / EXTEND with a `status_field` -> `"35"`
  (never an OPEN OUTPUT, which creates the file). File statements are
  failed one at a time (`site_status_key`: `"READ:F@99"`), so a READ NEXT
  loop elsewhere on the same file still reaches its AT END.
* **file status** — `_file_status_scenarios`: one scenario per file
  statement and FILE STATUS code the program tests that statement's status
  field for (`ConstraintReport.status_tests`: literals compared with it,
  `EVALUATE ... WHEN '02'`, its 88s), limited to the codes the operation
  can return (`_STATUS_CODES_BY_OPERATION`). A program that only tests for
  `"00"` gets the operation's typical failure (`_TYPICAL_FAILURE`; on a
  sequential file `_TYPICAL_SEQUENTIAL_FAILURE`: `"34"` for a WRITE, as an
  ESDS or QSAM file gives when full, `"44"` for a REWRITE). Codes the
  file's organization never returns are dropped
  (`_IMPOSSIBLE_BY_ORGANIZATION`: no `"02"`/`"2x"` on a sequential file, no
  `"34"` on an indexed or relative one). A sequential READ never gets
  `"23"`; any statement gets `"02"` only when `StatementSite.duplicate_key`
  says it can; an OPEN OUTPUT never gets `"35"`. At most
  `_MAX_FILE_STATUS_SCENARIOS` (40); a (statement, code) the error-status
  family already covers is skipped.
* **Both status families pin the path** to the statement they fail
  (`_StatusPath.pin`, from `ConstraintReport.statement_sites`): the arms
  that reach its paragraph (`_ParagraphReach`) and enclose it there are
  solved into the scenario's `field_constraints`/`witnesses` like a branch
  scenario's path, and each INVALID KEY clause it sits in fails that outer
  statement too (a WRITE in a READ's INVALID KEY gets the READ's `"23"`).
  What cannot be pinned goes to `path_gaps`. Without this a READ in a
  paragraph run only for transaction code 'C' was failed on rows that
  never ran it.
* **boundary values** — two combined scenarios (`"minimum"`/`"maximum"`),
  every numeric field any constraint touches pinned to its picture's true
  extreme (`-ceiling` for a signed field, `0` otherwise, vs. `ceiling`). A
  COMP-1/COMP-2 field has no picture: its extremes are the solver's float
  bound, `-/+domains.FLOAT_LIMIT` (#551).
  Pinned via an `eq` constraint, not `ge`/`le`: `domains.solve()`'s witness
  is always the interval's (grid) *midpoint*, so a `ge("0")` constraint alone
  produces a mid-range witness, not `0`.

## Tests

* `tests/unit/test_program_layout_index.py` — FD/record resolution, FD-vs-SD
  tagging, `FileFacts` merging, bare/qualified/level-88 name resolution,
  `record_named()` (whole-record lookup + cross-section ambiguity),
  multi-program compilation units, `from_file` error modes
* `tests/unit/generators/data/test_program_layout_conditions.py` — the
  index's level-88 lookups (`condition_values`, qualified 88 names)
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
  multi-scenario-directory test)
* `tests/unit/cli/test_gen_fixtures_cli.py` — `gen-fixtures` flags,
  `--list-boundaries`, `--format json|csv-dir`, `--strict` exit codes
* `tests/integration/test_gen_fixtures_corpus.py` — every
  `examples/cobol/shamrice/*.cbl` generates a bundle without raising; every
  generated cell fits its field's category; determinism across the corpus
* `tests/contracts/test_fixture_bundle_contract.py` — exported names,
  `bundle_version`, generator signatures, `to_dict()` key sets across
  `FixtureBundle`/`Scenario`/`BoundaryFixture`/`Expectation`/`CoverageSummary`,
  reproducibility guarantee; `TestScenarioModeContract` — signature pins for
  `generate_with_scenarios`/`_from_file`, happy-mode byte-identity with
  `generate`, `scenario_coverage` population/absence, seed reproducibility
  across `branches`/`all`, unknown-mode `ValueError`
* `tests/unit/generators/test_scenario_verification.py` — `verify_scenario`
  verdicts (satisfied/violated/absent/unknown); `test_row_witnesses.py` —
  `PlannedScenario.row_witnesses` plumbing; `test_cross_record_correlation.py`
  — carrier detection and its refusals, two-row planning, correlation
  verdicts, the BRKRPT bundle (and its GnuCOBOL run)
* `tests/regression/test_fixturedemo_golden.py` — `examples/fixtures/FIXTUREDEMO.cbl`
  at seed 42 must keep producing the exact golden `FixtureBundle` JSON
* `tests/unit/test_scenario_planner.py` — single-IF THEN/ELSE targeting with
  differing witnesses, disjoint-field merging, unsatisfiable-arm handling,
  the three fixed families (`mode="all"`), exact coverage accounting
* `tests/integration/test_scenario_planner_corpus.py` — every
  `examples/cobol/shamrice/*.cbl` plans (both `branches` and `all` modes)
  without raising; coverage accounting sums to the arm count for every
  program; every miss/merge carries a reason/target

## See also

* [generators.md](../generators.md) — the generators routing page
* [record-data.md](record-data.md) — `FieldSpec`, `flatten_record`,
  `ValueFactory`, which the index and the fixture generator reuse
* [analysis.md](../analysis.md) — `BoundaryInventoryAnalyzer` (Phase 2),
  `ConstraintExtractor` / `domains.solve()` (Phase 4), `ConstantFolder` and
  `invocation_counts` (Phase 7), `ProgramFlowAnalyzer`
* [parser.md](../parser.md) — `fd_file_name` / `fd_clauses` /
  `fd_record_type` metadata tags the index reads
* [cli.md](../cli.md) — `gen-fixtures`
* [`docs/fixture-bundle-schema.md`](../../docs/fixture-bundle-schema.md) —
  the full `FixtureBundle` JSON shape, key by key, with a worked example
* `docs/plans/2026-08-02-program-data-generation-design.md` and
  `docs/plans/2026-08-02-program-data-generation-implementation.md` — the
  9-phase plan (Phases 2 and 4 live in [analysis.md](../analysis.md))
* [history](../history/generators.md) — archived dated notes
