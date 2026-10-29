# Program-Scoped Data Generation — Per-Phase Implementation Plans

**Date:** 2026-08-02
**Status:** Done. See the parent design for where each part landed.
**Parent design:** [`2026-08-02-program-data-generation-design.md`](2026-08-02-program-data-generation-design.md)
**Phase 0 (value-engine refactor)** has its own detailed plan:
[`2026-08-02-phase0-value-engine-refactor.md`](2026-08-02-phase0-value-engine-refactor.md).
This document covers Phases 1–9 at the same level of detail.

Every AST attribute named below was verified against the current source —
these are the real names, not paraphrases. Where a detail still needs
confirming at implementation time, it is marked **[confirm]**.

---

## Phase 1 — `ProgramLayoutIndex`

**New file:** `cobolparser/generators/data/program_layout.py`
(inside the Phase 0 package — it imports `FieldSpec`/`flatten_record` from
`data.layout` and adds `ProgramLayoutError` to `data.errors.py`, the slot the
Phase 0 plan reserved for it). Re-exported from `cobolparser.generators`.

### Public surface

```python
@dataclass(frozen=True)
class FileFacts:
    file_name: str
    organization: str | None       # SelectStatement.organization
    access_mode: str | None        # SelectStatement.access_mode
    record_key: str | None         # SelectStatement.record_key
    alternate_keys: list[dict]     # SelectStatement.alternate_keys (as parsed)
    relative_key: str | None
    file_status_field: str | None  # SelectStatement.file_status
    is_optional: bool
    record_contains: int | None            # CobolFileDescription.record_contains
    record_contains_min: int | None
    record_contains_max: int | None
    recording_mode: str | None
    record_names: list[str]        # resolved record roots, in FD order

@dataclass(frozen=True)
class ResolvedField:
    spec: FieldSpec                # from flatten_record over the owning record
    section: str                   # "file" | "working_storage" | "local_storage" | "linkage"
    record: CobolDataItem          # the 01/77 root that owns it

class ProgramLayoutError(ValueError): ...   # lives in data/errors.py

class ProgramLayoutIndex:
    @classmethod
    def build(cls, ast: CobolProgram) -> "ProgramLayoutIndex": ...
    @classmethod
    def from_file(cls, path, *, copybook_paths: list[str] | None = None,
                  strict_copybooks: bool = True) -> "ProgramLayoutIndex": ...

    def records_for_file(self, file_name: str) -> list[CobolDataItem]: ...
    def record_for_file(self, file_name: str) -> CobolDataItem | None: ...
    def file_facts(self, file_name: str) -> FileFacts | None: ...
    def resolve(self, name: str) -> ResolvedField | None: ...
    def section_of(self, name: str) -> str | None: ...
    def linkage_records(self) -> list[CobolDataItem]: ...
    def working_storage_records(self) -> list[CobolDataItem]: ...

    ambiguities: dict[str, list[str]]   # name -> the qualified paths it maps to
    unresolved: list[str]               # names/files that failed to index, with reasons
```

### Build mechanics

1. **Section enumeration.** Walk the DATA DIVISION's sections; each
   `CobolSection` carries `data_items` (`models/program.py:34`). Key sections
   by their normalized name (`file`, `working_storage`, `local_storage`,
   `linkage`). **[confirm]** exactly how `DataDivisionParser`'s section dicts
   land on the `CobolProgram` — the parser builds
   `{"type": section_name.lower().replace("-","_"), ...}` dicts
   (`parsers/divisions/data.py:300`); if the division node stores dicts rather
   than `CobolSection` nodes for some sections, normalize both shapes here,
   in one place, so no later phase ever touches that difference.
2. **FD → record join**, three strategies in order:
   a. the `metadata["fd_file_name"]` tag stamped on FILE SECTION 01s
      (`parsers/divisions/data.py:287`) — primary;
   b. `CobolFileDescription.data_record_names` (the `DATA RECORDS` clause,
      captured into `fd_clauses["data_records"]`,
      `data_file_description.py:201`);
   c. positional — the 01s between this FD and the next, in source order.
   Record which strategy matched (feeds `provenance` in later phases). A file
   with no resolvable record goes in `unresolved`, never silently skipped.
3. **SELECT facts.** `SelectStatement` nodes live in the ENVIRONMENT
   DIVISION's FILE-CONTROL; collect via
   `ast.find_all_by_type("SELECT")`-equivalent and key by uppercased
   `file_name`. Merge with the FD clauses into `FileFacts`.
4. **Name multimap.** Flatten every record root once
   (`flatten_record(root, DataGeneratorOptions(include_filler=True,
   include_redefines=True))` — the index must know about *all* storage, the
   emit-time exclusions are a generation concern, not an indexing concern).
   Build `name -> [(section, record, FieldSpec)]`. `resolve()` accepts:
   - bare name — unique hit returns it; multiple hits record the name in
     `ambiguities` and return `None`;
   - `A OF B` / `A IN B` / dotted `B.A` — matched against `FieldSpec.path`
     suffixes.
5. **Level-88 index.** Also map each condition name to its parent field's
   `ResolvedField` — Phase 4 needs `IF ORDER-VALID` to resolve to the parent
   field plus the 88's value set, and `FieldSpec.condition_values` already
   carries the expanded values.

### Edge cases to handle (each gets a test)

- Multi-01 FD (record variants): all indexed, `record_for_file` returns the
  first, `records_for_file` all.
- `SD` sort files: indexed but flagged (`record_type == "SD"` on
  `CobolFileDescription`) — mockymock refuses SORT/MERGE, later phases mark
  these `unconstrained`.
- Same name at multiple paths (legal COBOL) → `ambiguities`, not a guess.
- LINKAGE 01s with no `PROCEDURE DIVISION USING` mention — indexed anyway;
  the linkage/USING join is Phase 2's job (via what `LinkageChecker` already
  reads: `proc_div.get_metadata("using_parameters")`).
- Copybooks: `from_file` runs `parse_cobol_with_expansion` when
  `copybook_paths` given; with `strict_copybooks=True` (default) an
  unresolved COPY raises `ProgramLayoutError` — a layout with a hole in it
  is wrong, not partial (parent plan §7).

### Tests

- `tests/unit/generators/test_program_layout_index.py` — build over
  `tests/samples/file_operations.cbl`, `complex_data_structures.cbl`,
  `redefines_test.cbl`, `occurs_variations.cbl`, `database_interface.cbl`,
  `subprogram_demo.cbl` (linkage); ambiguity and qualified-name resolution
  with a hand-built two-`CUST-ID` program.
- `tests/integration/test_program_layout_corpus.py` — every
  `examples/cobol/shamrice/*.cbl` builds without raising; every FD resolves
  ≥1 record or appears in `unresolved` with a reason.

**Exit criteria:** index builds over the full corpus; `resolve()` round-trips
every elementary field name that is unique in its program; zero silent skips.

---

## Phase 2 — `BoundaryInventory`

**New file:** `cobolparser/analysis/boundary_inventory.py` (analysis, not
generators — it produces a report from an AST, same shape as the other 13
analyzers: `BoundaryInventoryAnalyzer().analyze(ast, index) -> BoundaryReport`).

### Model

```python
@dataclass(frozen=True)
class BoundaryRef:
    category: str        # CALL DYNCALL OPEN CLOSE READ WRITE REWRITE DELETE
                         # START UNLOCK SQL CICS DLI ACCEPT
    key: str             # mockymock key convention (see table)
    paragraph: str | None
    line: int | None

@dataclass
class Boundary:
    ref: BoundaryRef
    direction: str               # IN | OUT | STATUS_ONLY | BIDIRECTIONAL
                                 # (perspective: the program under test;
                                 #  IN = mock supplies, OUT = assert on)
    record_names: list[str]      # layout roots involved (resolved via index)
    status_field: str | None     # FILE STATUS field / "SQLCODE" / "RETURN-CODE"
    handlers: list[str]          # which error clauses exist: "AT_END",
                                 # "INVALID_KEY", "ON_EXCEPTION", "ON_OVERFLOW"
    call_args: list[CallArg]     # CALL/DYNCALL only
    unresolved: list[str]

@dataclass
class CallArg:
    name: str
    passing_mode: str            # CallParameter.passing_mode: REFERENCE/CONTENT/VALUE
    direction: str               # IN | OUT | BIDIRECTIONAL
    provenance: str              # "by-content-rule" | "callee-source" |
                                 # "caller-dataflow" | "assumed-bidirectional"

@dataclass
class BoundaryReport:
    program_name: str | None
    boundaries: list[Boundary]
    unresolved: list[str]
    def to_dict(self) -> dict: ...
```

### Statement walk

Reuse the walking discipline `mock_surface` and `IOLogger` both converged on:
recurse a fixed nested-body attribute tuple — `then_statements`,
`else_statements`, `inline_statements`, `at_end_clause`, `not_at_end_clause`,
`invalid_key_clause`, `not_invalid_key_clause`, `at_eop_clause`,
`on_exception`, `not_on_exception`, `on_overflow` — plus the two shapes that
need special-casing: `EvaluateStatement.when_clauses[].statements`
(`WhenClause` nodes) and `SearchStatement.when_clauses` (**list of dicts**
with a `"statements"` key — a different shape; mockymock's audit finding 1.3
documents the trap). An `id()`-based visited set prevents double-count.

### Key and layout resolution (mockymock's convention, exactly)

| Statement | Key | Layout | Direction |
|---|---|---|---|
| `IOReadStatement` | `.file_name` | `into_target` if set, else `index.records_for_file` | IN |
| `IOWriteStatement`/`IORewriteStatement` | `.record_name` (**record**, not FD) | that record | OUT |
| `IOOpenStatement`/`IOCloseStatement` | each of `.file_names` | — | STATUS_ONLY |
| `IODeleteStatement`/`IOStartStatement`/`IOUnlockStatement` | `.file_name` | key field via `FileFacts.record_key` | STATUS_ONLY |
| `CallStatement`, `called_program` literal, not `_is_dynamic` | the literal | per-arg | per-arg |
| `CallStatement`, `_is_dynamic` | uppercased identifier | per-arg; `DynamicCallAnalyzer` fills possible targets into `details` | per-arg |
| `ExecSQLStatement`, `sql_type == "SELECT"` / `FETCH` | unique text prefix | `into_variables` resolved via index (+`HostVariableResolver` for `:v` forms) | IN |
| `ExecSQLStatement`, INSERT/UPDATE/DELETE | unique text prefix | `host_variables` | OUT |
| `ExecCicsStatement`/`ExecImsStatement` | unique text prefix | INTO/FROM operand **[confirm attr names]** | per-command |
| `IOAcceptStatement`, console source | target data-name | that field | IN |
| `DisplayStatement` | — (not a mock key) | operands | OUT (assert-only) |

SQL/CICS/DLI prefixes: normalize (uppercase, collapse whitespace — same as
mockymock's `normalize_exec_text`), then shortest word-prefix unique among
same-category sites in this program; fall back to full text. Port the
algorithm from mockymock's `generator._unique_prefix` **by re-implementing
it against the spec above, not by importing mockymock** — the dependency
direction is mockymock → cobolparser, never the reverse. The Phase 8
contract test is what keeps the two implementations agreeing.

Non-interactive ACCEPT sources (DATE/DAY/TIME/ENVIRONMENT/…) are not
boundaries — mirror mockymock's `_NON_INTERACTIVE_ACCEPT_SOURCES` list.

### CALL argument direction (Phase 2b — the hard part)

Resolution ladder, first hit wins, `provenance` records which rung:

1. `passing_mode` in (`CONTENT`, `VALUE`) → **OUT** (caller supplies; callee
   cannot write back). Language rule, always safe.
2. Callee source available (`--callee-path`): parse the callee, take its
   LINKAGE 01s positionally against our `using_parameters`; if the callee's
   PROCEDURE DIVISION contains a `MoveStatement` (or arithmetic
   `GIVING`/`COMPUTE` target) writing **to** that linkage item or any of its
   children → the callee writes it → **IN** (possibly BIDIRECTIONAL if the
   callee also reads it before writing — v1 simplification: writes-at-all ⇒
   IN, reads-only ⇒ OUT, and say so in `provenance`).
3. Caller-side dataflow within the enclosing paragraph's statement list
   (source order): a `MoveStatement` with the arg in `.targets` *before* the
   CALL and no read after ⇒ **OUT**; first use after the CALL is a read
   (MOVE `.source`, DISPLAY operand, IF condition operand) with no write in
   between ⇒ **IN**; both ⇒ **BIDIRECTIONAL**. "Read/write" checks must
   consult the index so a write to a *parent group* counts as a write to the
   child.
4. Otherwise **BIDIRECTIONAL**, `provenance="assumed-bidirectional"`, and the
   arg name goes in `Boundary.unresolved`.

`returning_parameter` / `giving_parameter` are always IN (callee produces).

### Tests

- `tests/unit/analysis/test_boundary_inventory.py` — one class per category;
  nested-body reachability (a READ inside `EVALUATE … WHEN` and inside an
  `ON SIZE ERROR` body must both appear — the exact holes the 2026-07-09
  silent-drop audit found in `program_flow`).
- Direction ladder: `call_parameter_modes_complete.cbl` (passing modes),
  `subprogram_demo.cbl` (callee-source rung), hand-built programs for the
  dataflow rung.
- Cross-check: for `tests/samples/io/positive/*`, the inventory's file-op
  set equals `IOLogger`'s `file_operations()` set (two walks, one truth).

**Exit criteria:** every boundary in the sample+shamrice corpus is either
inventoried with a layout or listed in `unresolved` with a reason. No third
state.

---

## Phase 3 — `ProgramFixtureGenerator` + `gen-fixtures` CLI

**New files:** `cobolparser/generators/data/bundle.py` (models),
`cobolparser/generators/program_fixtures.py` (orchestrator),
CLI additions in `cobolparser/cli/parse.py`.

### Bundle model (`data/bundle.py`)

The parent plan's `FixtureBundle`/`Scenario`/`BoundaryFixture` dataclasses,
plus:

- `bundle_version: int = 1` at the top level — Phase 8 consumes this JSON
  across a repo boundary; version it from day one and pin the key sets in a
  contract test (`tests/contracts/test_fixture_bundle_contract.py`).
- `BoundaryFixture.sequence` cells are **strings** (same convention as
  `GeneratedDataset.rows` — the CSV/COBOL text form, not Python types).
- `write_csv_dir(path)` emits `<out>/<scenario-slug>/<KEY>.csv` by building a
  `GeneratedDataset` per file boundary (record_name, fields, rows already
  align) and calling its `write_csv` — the line-terminator agreement comes
  for free.

### Determinism design (decide now, not later)

One bundle seed. Each `(scenario, category, key)` gets a derived sub-seed:
`zlib.crc32(f"{scenario}|{category}|{key}".encode()) ^ bundle_seed`, feeding
its own `random.Random` and `ValueFactory`. Rationale: with a single shared
RNG in iteration order, adding one boundary would reshuffle every value after
it — bundles must be stable under unrelated additions, or every golden test
downstream churns. (`zlib` is stdlib; the zero-dependency rule holds.)

### Generation algorithm (happy path, Phase 3 scope)

```
parse (with copybooks; refuse on unresolved COPY)
index = ProgramLayoutIndex.build(ast)
report = BoundaryInventoryAnalyzer().analyze(ast, index)
for each boundary:
    IN file boundary   -> rows = opts.rows records via ValueFactory;
                          terminal = AT_END if "AT_END" in handlers
    IN SQL SELECT      -> one row per into-variable set; FETCH -> rows rows
                          + terminal SQLCODE 100
    IN ACCEPT          -> one value per invocation-count guess (v1: 1)
    CALL args          -> IN args get values; OUT args get expectation stubs
    STATUS_ONLY        -> {"FILE-STATUS": "00"} (or SQLCODE 0 / RETURN-CODE 0)
    OUT                -> expectation stub only (Phase 7 fills tiers)
assemble one Scenario("happy path"), CoverageSummary, unresolved rollup
```

### CLI

Follow the `gen-data` pattern exactly (`_build_gen_data_parser` /
`_cmd_gen_data`, lazy import inside the command function, registered in the
subparser block at `cli/parse.py:1215`):

```
cobol-parser gen-fixtures PROG.cbl
    [--copybook-path DIR]... [--callee-path DIR]...
    [--rows N] [--seed N] [--scenarios happy]        # branches|all arrive in Phase 5
    [--format json|csv-dir] [-o PATH]
    [--list-boundaries] [--describe] [--strict]
```

`--strict`: exit 2 if `unresolved`/`unconstrained` is non-empty (exit 1 stays
"could not run at all", matching existing CLI conventions **[confirm]**).
`--list-boundaries`: table of `category key paragraph line direction` — the
debugging view and the Phase 8 cross-check input.

### Tests

- `tests/unit/generators/test_program_fixtures.py` — bundle assembly per
  category; determinism (same seed ⇒ byte-identical `to_json()`; adding a
  boundary leaves other boundaries' values unchanged — pins the sub-seed
  scheme).
- `tests/unit/cli/test_gen_fixtures_cli.py` — flags, exit codes, `--strict`.
- `tests/integration/test_gen_fixtures_corpus.py` — every sample + shamrice
  program generates; every generated cell assignable to its field (reuse the
  assertion helpers from `test_copybook_csv_generation.py`).
- Contract: `tests/contracts/test_fixture_bundle_contract.py` — key sets,
  `bundle_version`, reproducibility.

**Exit criteria: this is the first shippable release.** Update
`CHANGELOG.md`, `.okf/generators.md`, `.okf/cli.md`, `CLAUDE.md` in the same
PR (the OKF staleness hook enforces it anyway).

---

## Phase 4 — `ConstraintExtractor` + solver

**New file:** `cobolparser/analysis/constraints.py`.

### Model

```python
@dataclass(frozen=True)
class FieldConstraint:
    field: ResolvedField
    op: str            # eq ne lt le gt ge in_set not_in_set class_numeric
                       # class_alphabetic figurative
    values: tuple[str, ...]
    origin: str        # "IF@line" / "EVALUATE@line/WHEN#2" / "PERFORM-UNTIL@line"
    negated: bool

@dataclass(frozen=True)
class SequenceConstraint:      # the EOF/loop knob
    boundary: BoundaryRef
    length: int | None         # None = "at least the flag pattern exists"
    origin: str

@dataclass
class BranchConstraints:
    branch_id: str             # joinable to ProgramFlowReport.branch_nodes
                               # via (parent_proc, location) — BranchNode has
                               # node_id, branch_type, condition_text, arms
    arms: dict[str, list[FieldConstraint]]   # arm_id -> conjuncts
    unsupported: list[str]     # reason strings, never silently dropped

@dataclass
class ConstraintReport:
    branches: list[BranchConstraints]
    sequence_constraints: list[SequenceConstraint]
    unsupported: list[str]
```

### Extraction sources (verified node shapes)

- **IF**: `IfStatement.condition` is a `CobolExpression`; walk
  `ConditionalExpression` (`operator`, `left_operand`, `right_operand`, each
  `str | CobolExpression`) and `LogicalExpression` trees. AND distributes into
  one arm's conjunct list; OR splits an arm into alternatives (represent as
  multiple satisfiable variants of the same arm); NOT flips `negated`.
- **EVALUATE**: `subjects` + `when_clauses[].selectors`, each selector a dict
  with `type` in `{"Literal","Identifier","Any","Range","Condition"}` and
  `value` / `start`,`end`. `EVALUATE TRUE` + `WHEN <88-name>` is the common
  idiom — route through the Phase 1 level-88 index. `WHEN OTHER` = negation
  of all prior arms' constraints (v1: mark unsupported if any prior arm was
  itself unsupported — a wrong "other" is worse than a skipped one).
- **PERFORM UNTIL**: `PerformStatement.until_condition` (plus
  `varying_clause`/`after_clauses` bounds for VARYING). This is where
  `SequenceConstraint` comes from: pattern-match "condition tests a field
  that an `at_end_clause` body MOVEs to" — i.e. find `MoveStatement`s inside
  each READ's `at_end_clause` whose target resolves to the conditioned field.
  That triple (READ boundary, flag field, flag value) ⇒ sequence length is
  the free variable.
- **Level-88 in any condition**: bare identifier operand that resolves to a
  condition name ⇒ `in_set(parent, condition_values)`.
- **Class tests / figurative**: `IS NUMERIC`/`ALPHABETIC`, `= SPACES/ZEROS`.

Operand classification: try literal first (quoted string, or matches the
numeric-literal regex), else `index.resolve()`. An operand that is neither ⇒
that condition goes to `unsupported` with `"unresolvable operand: X"`.
Two boundary-fed fields compared to each other ⇒ unsupported in v1 (parent
plan §5 Phase 4 list).

### Solver (`cobolparser/analysis/domains.py`, same PR)

Domain lattice per `FieldSpec`, no external deps:

- `NumericDomain(lo, hi, excluded: set, scale)` — initialized from
  `integer_digits`/`decimal_digits`/`is_signed` (the picture range), then
  intersected per constraint.
- `TextDomain(allowed: set | None, forbidden: set, size)` — `allowed=None`
  means "any of size ≤ n".
- `EnumDomain(values)` — 88-backed fields start here, not at TextDomain.

`solve(constraints) -> Witness | Unsatisfiable(reason)`. Witness picking is
deterministic (midpoint for intervals, first allowed literal in sorted
order) and **always** rendered through the Phase 0 engine — expose
`ValueFactory.render(spec, value)` as a thin public wrapper over
`_format_number(..., allow_random_sign=False)` / `_fit_text` so a solved
value can never violate the layout (the same invariant the 88-domain path
already guarantees).

### Tests

- `tests/unit/analysis/test_constraints.py` — one hand-built program per
  condition form in the parent plan's table; AND/OR/NOT composition;
  EVALUATE TRUE + 88s; WHEN OTHER; the READ/AT END/UNTIL triple producing a
  `SequenceConstraint`.
- `tests/unit/analysis/test_domains.py` — property-style: for each solved
  witness, (a) re-checking the constraint set against the witness passes,
  (b) the rendered value is assignable to the field. Empty-domain cases
  return `Unsatisfiable` with a reason, never a value.

**Exit criteria:** every condition in the corpus is either extracted or in
`unsupported` with a reason; solver never emits a layout-violating witness.

---

## Phase 5 — `ScenarioPlanner`

**New file:** `cobolparser/generators/scenarios.py`.

### Algorithm

1. Inputs: `BoundaryReport`, `ConstraintReport`,
   `ProgramFlowAnalyzer().analyze(ast)` (its `branch_nodes` carry
   `node_id`, `parent_proc`, `condition_text`, `arms[]` with `arm_id` —
   join to `BranchConstraints.branch_id`).
2. **v1 path-condition simplification (state it in the docstring):** a
   scenario targets *one* arm and takes that arm's conjuncts only; enclosing
   branches on the path are not accumulated. Full path-sensitivity is a v2
   item; the `CoverageSummary` distinguishes "arm targeted" from "arm
   targeted with full path condition" so nobody mistakes v1 coverage for
   path coverage.
3. Solve per arm ⇒ candidate scenario. **Merge** scenarios whose constraint
   sets touch disjoint fields and whose sequence constraints agree (greedy,
   deterministic order: sort by `branch_id`).
4. Add the fixed families (`--scenarios all`):
   - **empty-input** — every IN file/cursor boundary at sequence length 0;
   - **error-status** — one scenario per *declared* handler: `INVALID KEY`
     present ⇒ FILE STATUS "23" on that op; `AT END` ⇒ covered by
     empty-input; `ON EXCEPTION` on CALL ⇒ RETURN-CODE 12; OPEN with a
     FILE STATUS field ⇒ "35". Handlers list comes from
     `Boundary.handlers` — never generate an error the program has no path
     for;
   - **boundary-values** — min/max witnesses for each numeric field that any
     constraint touches.
5. Emit `CoverageSummary`: per arm — `targeted` / `merged-into:<scenario>` /
   `missed:<reason>` (reason strings come straight from
   `ConstraintReport.unsupported` or `Unsatisfiable`).

### Scenario naming

Deterministic and human-readable: `"<parent_proc>: <condition_text> is
true"` (condition_text already exists on `BranchNode`), slugified for
`write_csv_dir` paths. Collisions get `-2` suffixes (same policy as CSV
column dedup).

### Tests

`tests/unit/generators/test_scenario_planner.py` — a program with one IF
yields ≥2 scenarios whose witnesses differ on the conditioned field; merge
behavior; unsatisfiable arm lands in `CoverageSummary.missed`; the EOF triple
yields empty-input + N-records scenarios; `--strict` semantics.
Integration: corpus sweep asserting `scenarios ≥ 1` and coverage accounting
sums to the arm count (`targeted + merged + missed == total`).

**Exit criteria:** the "fully test" claim is measurable — coverage accounting
is exact, and every miss carries a reason a human can act on.

---

## Phase 6 — Emitters

Mostly already built by Phases 3–5; this phase hardens the surfaces.

- **JSON**: freeze `bundle_version: 1`; the contract test from Phase 3 grows
  scenario/coverage keys. Document the schema in
  `docs/fixture-bundle-schema.md` (hand-written prose + example, not
  JSON-Schema — zero-dep rule and repo precedent both point that way).
- **csv-dir**: one directory per scenario slug; `MANIFEST.json` at the root
  (bundle minus rows) so a consumer can discover scenarios without listing
  directories.
- **`.cut`**: lives in mockymock (parent plan open decision #3, taken as
  recommended). The mapping spec stays in the parent plan §6; Phase 8
  implements it. Nothing to build in cobol-parser here.

**Exit criteria:** schema doc exists; `gen-fixtures --format csv-dir` output
round-trips through `csv.reader` and matches the JSON rows byte-for-cell.

---

## Phase 7 — Expectations (tiers 1–2), and 7b golden mode

### In cobol-parser (`generators/program_fixtures.py` growth)

- **Tier 1 (structural)**: for each mocked boundary in a scenario,
  `Expectation(kind="call_count", ref, times=len(sequence)+terminal)`.
  Derivable exactly — the scenario *defines* the sequence.
- **Tier 2 (constant folding)**: `cobolparser/analysis/const_fold.py`. A
  single forward walk over the entry paragraph chain (statement lists in
  order; no loops — any `PERFORM UNTIL`/`VARYING` on the path aborts folding
  for fields written inside it):
  - `MoveStatement`: literal source ⇒ env[target] = literal; known-env
    source ⇒ copy; else ⇒ env[target] = ⊥ (unknown poisons).
  - `AddStatement`/`SubtractStatement`/`MultiplyStatement`/`DivideStatement`/
    `ComputeStatement`: fold only when every operand is a literal or known;
    honor `GIVING`. **[confirm]** operand attribute names on the arithmetic
    nodes at implementation time.
  - Mock-supplied inputs seed the env: the scenario's own IN values are
    known constants for the fold.
  - Any field still non-⊥ at the end that the program DISPLAYs or WRITEs ⇒
    `Expectation(kind="field_equals")`.
- **Tier 3**: everything else becomes
  `Expectation(kind="stub", note="computed in <paragraph>")` — emitted by
  Phase 8 as a `*>` comment, never as a live assertion.

### 7b — mockymock `run --record-expectations`

Separate design doc **in the mockymock repo** (`docs/2026-XX-record-
expectations-design.md`) before implementing; sketch: run the suite, parse
the `__MOCKYMOCK__` stdout protocol's observed values for each stub, rewrite
the `.cut` replacing stub comments with real `EXPECT` lines, refuse to
overwrite a hand-edited `EXPECT`. Keep it out of cobol-parser entirely.

### Tests

`tests/unit/analysis/test_const_fold.py` — chains that fold, chains poisoned
by an unknown, loop-write aborts, GIVING forms. Tier-1 counts pinned in the
Phase 5 planner tests (they own scenarios).

**Exit criteria:** no generated `EXPECT` can be wrong: a tier-2 expectation
is exact by construction or absent.

---

## Phase 8 — mockymock `generate --with-data`

All work in `samdion1994/mocky-mock`.

### Changes

1. **Dependency**: bump the pinned-git `cobolparser` ref in `pyproject.toml`
   to the release carrying Phases 1–3 (minimum) — mockymock calls the
   Python API directly (`generate_program_fixtures(...)`), no subprocess.
   Also accept `--fixtures bundle.json` to consume a pre-generated bundle
   (CI use, and it keeps the JSON schema honest).
2. **Loader**: `mockymock/dsl/fixture_bundle.py` — parse/validate the JSON
   (check `bundle_version == 1`, fail closed on unknown version), producing
   lightweight local dataclasses. mockymock never imports cobol-parser's
   bundle *classes* — only the JSON shape. That keeps the
   independently-checkable-attributes principle from `.okf/analysis.md`
   intact: the contract is the serialized form.
3. **Scaffolder**: `scaffold_cut(suite_name, surface, bundle=None)`
   (`dsl/generator.py:43`). With a bundle:
   - one `TESTCASE` per scenario (not per paragraph) named from the
     scenario name, `PERFORM <scenario.entry>`;
   - body builder replaces `_PLACEHOLDER_BODIES`:
     `sequence` ⇒ tally-branching `IF UT-<op>-<key>-TALLY > n … ELSE …`
     chain with per-invocation MOVEs; SQL multi-row ⇒ `ROWS (…)` sugar;
     non-"00" status ⇒ `FILE-STATUS IS` sugar; ACCEPT ⇒ MOVE of the
     scenario's value;
   - tier-1 expectations ⇒ `VERIFY … WAS PERFORMED n TIMES`; tier-2 ⇒
     `EXPECT`; tier-3 ⇒ `*>` stub comments;
   - scenarios differing only in field values on the same mock/entry shape
     collapse into one `TESTCASE … USING PROVIDER` with a `ROW` per
     scenario (`_expand_providers` already handles the rest).
4. **The join**: match `bundle` fixtures to `surface.boundary_sites` by
   `(category, key)`. Any key on either side without a partner ⇒ a **loud**
   stderr warning listing both sets in full, and the site falls back to the
   placeholder body. Never silent — this mismatch is the integration's
   primary failure mode.
5. **Contract test** (`tests/unit/test_fixture_bundle_contract.py` +
   integration over `examples/*/`): for each example program, the
   `(category, key)` set from `mock_surface.analyze()` equals the set from
   the cobol-parser bundle. This single test is what licenses the two
   independent walks.
6. **Gate**: every generated `.cut` for the examples corpus passes
   `mockymock lint` (no Docker needed). A generator that emits refusable
   `.cut` is worse than none.

### Docs

`interface-contract.md` (cobol-parser) gains the bundle JSON as a consumed
surface; mockymock's `.okf/integration.md`, `.okf/dsl.md` (generator
section), `.okf/cli.md` updated; both repos' CHANGELOGs.

**Exit criteria:** `mockymock generate INVUPDT.cbl --with-data --seed 7`
produces a `.cut` that lints clean and runs green against the real example.

---

## Phase 9 — Docs and knowledge base

Checklist (most items land inside their phase's PR; this phase is the sweep
that verifies nothing was skipped under `--no-verify`):

- `.okf/generators.md` — "Program fixtures" section (index, inventory,
  scenarios, emitters, fail-loud fields, determinism/sub-seed scheme).
- `.okf/analysis.md` — `BoundaryInventoryAnalyzer`, `ConstraintExtractor`,
  const-fold; `.okf/cli.md` — `gen-fixtures`; `.okf/log.md` dated entries.
- `CLAUDE.md` command list + generators/analysis sections; `CHANGELOG.md`.
- `docs/fixture-bundle-schema.md` (Phase 6).
- Worked example `examples/fixtures/`: one program exercising file + SQL +
  CALL + ACCEPT, its bundle JSON, and (in mockymock) the generated `.cut` —
  all checked in as goldens with a regression test comparing bytes.

---

## Sequencing, PR slicing, and gates

| PR | Contents | Repo | Gate |
|---|---|---|---|
| 1 | Phase 0 (7 commits per its own plan) | cobol-parser | CSV golden hash |
| 2 | Phase 1 | cobol-parser | corpus index sweep |
| 3 | Phase 2 (+2b may split out) | cobol-parser | IOLogger cross-check |
| 4 | Phase 3 + bundle contract + docs | cobol-parser | **first release**; determinism test |
| 5 | Phase 8 (against release from PR 4) | mocky-mock | key-set contract + lint gate |
| 6 | Phase 4 (extractor + domains) | cobol-parser | witness property tests |
| 7 | Phase 5 + `--scenarios branches\|all` | cobol-parser | coverage accounting exact |
| 8 | Phase 6 hardening + schema doc | cobol-parser | round-trip test |
| 9 | Phase 7 tiers 1–2 | cobol-parser | no-wrong-EXPECT property |
| 10 | Phase 7b (own design doc first) | mocky-mock | golden re-run drift test |
| 11 | Phase 9 sweep + worked example | both | goldens byte-stable |

PR 5 lands **before** the constraint work on purpose: it proves the
end-to-end pipe (program → bundle → `.cut` → green run) while the data is
still random, so Phases 4–7 improve a working system instead of integrating
at the end.

Standing rules for every PR: OKF updated in the same commit as source (the
pre-commit hook enforces it); `black`/`ruff`/`mypy` clean; the 81% coverage
floor holds; determinism pinned by byte comparison, not parsed comparison.
