# Program-Scoped Test-Data Generation — Design Plan

**Date:** 2026-08-02
**Status:** Proposed (no code written yet)
**Scope:** `Landparty/cobol-parser` (bulk) + `samdion1994/mocky-mock` (consumer hook)

---

## 1. The goal

Today you point `gen-data` at a **copybook** and get a CSV of rows for one
record layout. The ask is to point at a **program** and get *everything you
need to run it in isolation*: every value that flows **in** across a boundary
(what a mock hands back) and every value expected **out** (what the program
should produce), for enough scenarios to exercise the program's paths.

Concretely, `cobol-parser gen-fixtures INVUPDT.cbl` should answer:

| Boundary | In-data (mock feeds) | Out-data (assert on) |
|---|---|---|
| `READ INV-FILE` | a sequence of `INV-REC` records, then EOF | — |
| `WRITE RPT-REC` | — | expected record content / call count |
| `CALL "DISCRATE" USING A, B` | values the callee writes back into `B` | values the caller must pass in `A` |
| `EXEC SQL SELECT … INTO :H1,:H2` | result rows for the host variables | — |
| `EXEC SQL UPDATE … WHERE :H3` | `SQLCODE` | host-variable values sent |
| `ACCEPT WS-REPLY` | a value valid for `WS-REPLY`'s picture | — |
| `OPEN`/`CLOSE` | `FILE STATUS` codes (happy + error) | — |

…and it should do it **per scenario**, where a scenario is chosen to drive a
specific branch, not sampled at random.

That last point is the actual "next level". Random rows that merely *fit the
PICTURE* will exercise one path through a program and silently miss the rest.
A `PIC 9(2)` random value has a 1-in-100 chance of tripping `IF WS-CODE = 42`.

---

## 2. Where we are today (verified inventory)

Pieces that already exist and are reusable — this plan builds on them rather
than restarting:

**Generation (`cobolparser/generators/copybook_data.py`, 1264 lines)**
`FieldSpec` / `flatten_record()` / `_ValueFactory` / `DataGeneratorOptions` /
`GeneratedDataset`. Already handles PICTURE categories, digit counts, sign,
`USAGE`, `OCCURS` expansion, `REDEFINES`/`FILLER` exclusion, level-88 domains
(including `THRU` expansion), `VALUE` clauses, semantic name hints,
`unique_fields`, `blank_rate`, and per-`seed` determinism. **This is the value
engine; it does not need to be rewritten, only lifted out of "one copybook,
one CSV".**

**Layout facts already in the AST**
- `CobolFileDescription` (`models/program.py:861`) — FD/SD with record
  lengths, recording mode, `DATA RECORDS`.
- 01-level FILE SECTION records carry `metadata["fd_file_name"]` and
  `metadata["fd_clauses"]` (`parsers/divisions/data.py`) — **the FD → record
  join already exists**.
- `SelectStatement` (`models/statements/misc.py:12`) — `organization`,
  `access_mode`, `record_key`, `alternate_keys`, `file_status`,
  `relative_key`, `assign_to`.
- Data sections keyed `file` / `working_storage` / `local_storage` /
  `linkage` by `DataDivisionParser`.

**Analysis already available**
`IOLogger` (every IO op with `direction` INPUT/OUTPUT/BIDIRECTIONAL, target,
variables, paragraph), `CRUDMatrixGenerator` (per-file/table C/R/U/D + open
modes), `HostVariableResolver` (SQL `:host-var` → WORKING-STORAGE),
`DynamicCallAnalyzer` (possible values of a dynamic CALL identifier),
`LinkageChecker` (LINKAGE 01s vs `PROCEDURE DIVISION USING`),
`ProgramFlowAnalyzer` (typed CFG, branch nodes, cycles, unreachable set),
`IMSSegmentAnalyzer`, `MoveTypeChecker`.
`ExecSQLStatement` exposes `host_variables`, `into_variables`,
`select_columns`, `tables`, `sql_type`, `cursor_name`, `where_present`.

**Downstream consumer (`mockymock`)**
`mock_surface.analyze()` finds every boundary site and keys it exactly the way
the `.cut` DSL does — `(MockCategory, key)`: file name for `OPEN/CLOSE/READ/
DELETE/START/UNLOCK`, **record** name for `WRITE/REWRITE`, quoted program
literal for `CALL`, bare identifier for `DYNCALL`, normalized-text prefix for
`SQL/CICS/DLI`, target data-name for `ACCEPT`. `scaffold_cut()` already emits
one `TESTCASE` per paragraph mocking all of that paragraph's sites — but with
**placeholder bodies** (`MOVE 0 TO RETURN-CODE`, `MOVE SPACES TO <target>`,
empty for file ops). The DSL also already has `PROVIDER`/`HEADER`/`ROW`
parameterized cases, `MOCK SQL … ROWS (…)` cursor sugar, `FILE-STATUS IS`,
tallies (`UT-READ-INV-FILE-TALLY`), and `VERIFY … WAS PERFORMED N TIMES`.

**So the gap is narrow and specific:** nothing today resolves *a boundary* to
*a record layout*, nothing generates *a sequence* of values per boundary, and
nothing chooses values *because a branch needs them*.

---

## 3. Architecture and the repo split

```
                 cobol-parser (static, zero-dependency)
  PROG.cbl ─┬─► ProgramLayoutIndex   (name → layout, FD → record, SELECT facts)
            ├─► BoundaryInventory    (every external touchpoint + direction)
            ├─► ConstraintExtractor  (branch conditions over boundary-fed fields)
            └─► ScenarioPlanner ─► FixtureBundle  (JSON / CSV dir)
                                          │
                 mockymock (dynamic)      ▼
                    scaffold_cut(surface, bundle) ─► populated .cut
                                          │
                              mockymock run ─► pass/fail, --coverage
```

**Why the generation side lives in cobol-parser:** it is pure static analysis
over the AST, it is the repo that already owns the value engine, and it is
reusable by anything (not just mockymock) — a data-migration harness, a
volume-test generator, a DB2 seeder.

**Why we do *not* move `mock_surface` into cobol-parser:** mockymock's OKF
records a deliberate decision that `mock_surface`/`refusal` depend only on the
small set of cobolparser attributes pinned in `interface-contract.md`, not on
cobolparser's own analyzers, so their correctness stays independently
checkable. This plan respects that: the `FixtureBundle` is keyed with the
**same `(category, key)` convention mockymock already uses**, and mockymock
joins its own surface against the bundle by key. Two independent walks that
must agree on keys — and a contract test that asserts they do.

---

## 4. The data model

```python
@dataclass(frozen=True)
class BoundaryRef:
    category: str          # CALL | DYNCALL | OPEN | CLOSE | READ | WRITE | REWRITE
                           # | DELETE | START | UNLOCK | SQL | CICS | DLI | ACCEPT
    key: str               # file name / record name / program literal / text prefix
    paragraph: str | None
    line: int | None

@dataclass
class BoundaryFixture:
    ref: BoundaryRef
    direction: str                 # IN | OUT | BIDIRECTIONAL
    layout: list[FieldSpec]        # resolved record/params — reuses today's FieldSpec
    sequence: list[dict[str, str]] # one dict per invocation (READ #1, #2, …)
    terminal: dict[str, str] | None# AT END / SQLCODE 100 / FILE STATUS 10 …
    status: dict[str, str]         # e.g. {"FILE-STATUS": "00"} or {"SQLCODE": "0"}
    provenance: str                # why these values: "constraint:WS-CODE=42",
                                   # "picture-random", "value-clause", "88-domain"
    unresolved: list[str]          # fail-loud: what could not be resolved

@dataclass
class Scenario:
    name: str                      # "happy path", "INV-QTY below reorder", "EOF first read"
    intent: str                    # branch/paragraph this scenario targets
    entry: str                     # paragraph to PERFORM
    fixtures: list[BoundaryFixture]
    expectations: list[Expectation] # field == value, or call-count
    unconstrained: list[str]        # branches we could not target, with reasons

@dataclass
class FixtureBundle:
    program_name: str
    seed: int
    scenarios: list[Scenario]
    layouts: dict[str, list[FieldSpec]]   # record name → layout, emitted once
    coverage: CoverageSummary             # branches targeted / missed / why
    def to_dict() / to_json() / write_csv_dir(path)
```

`unresolved` / `unconstrained` / `coverage` are load-bearing, not decoration.
This repo has already been burned by a silent all-clear (`MoveTypeChecker`
gained `unresolved_count` for exactly this reason, see `.okf/analysis.md`).
A bundle that quietly emits random values for a field it failed to constrain
looks identical to one that solved every branch. It must not.

---

## 5. Phases

### Phase 0 — Split the value engine out of `copybook_data.py` *(prerequisite)*

`copybook_data.py` is 1264 lines and its internals (`_ValueFactory`,
`_flatten_into`, `_assign_columns`) are private to a copybook-CSV workflow.
Refactor into `cobolparser/generators/data/`:

| Module | Contents |
|---|---|
| `layout.py` | `FieldSpec`, `FieldCategory`, `flatten_record`, `_classify`, `_digit_counts` |
| `values.py` | `_ValueFactory` → public `ValueFactory`, semantic hints, `_fit_text`/`_format_number` |
| `copybook.py` | `parse_copybook_records`, `CopybookDataGenerator`, `GeneratedDataset` |
| `options.py` | `DataGeneratorOptions` |

`cobolparser/generators/copybook_data.py` becomes a re-export shim.
**Every existing name keeps its import path** — `tests/contracts/
test_copybook_data_generator_contract.py` pins the exported names,
signatures, `to_dict()` key sets and the reproducibility guarantee, and must
pass untouched. Also verify byte-identical CSV for a fixed seed before/after
(the contract that already caught the `write_csv` line-terminator bug).

*Deliverable:* pure refactor, zero behavior change, green contract tests.

---

### Phase 1 — `ProgramLayoutIndex`

`cobolparser/generators/program_layout.py`.

```python
index = ProgramLayoutIndex.build(ast)          # or .from_file(path, copybook_paths=[...])
index.record_for_file("INV-FILE")              -> CobolDataItem | None
index.records_for_file("INV-FILE")             -> list[CobolDataItem]   # multi-01 FDs
index.resolve("INV-QTY")                       -> FieldSpec | None
index.resolve("QTY OF INV-REC")                -> FieldSpec | None      # qualified
index.section_of("WS-EOF")                     -> "working_storage"
index.file_facts("INV-FILE")                   -> FileFacts             # from SELECT + FD
index.linkage_records()                        -> list[CobolDataItem]
```

Mechanics:
- FD → record via the existing `metadata["fd_file_name"]` tag on 01 items;
  fall back to `DATA RECORDS` names, then to "the 01s between this FD and the
  next" (order-based) for FDs the tag missed.
- `FileFacts` = organization, access mode, record key, alternate keys,
  relative key, `file_status` field name, optional-ness, record length.
- Name resolution builds a `name → [paths]` multimap over all four sections;
  ambiguous unqualified names return `None` **and are recorded**, not guessed.
- Multi-01 FDs (record variants) are all indexed; scenario generation picks
  one per scenario and can be asked to cover each.

*Tests:* unit over `tests/samples/file_operations.cbl`,
`complex_data_structures.cbl`, `redefines_test.cbl`, `occurs_variations.cbl`,
`database_interface.cbl`; integration over `examples/cobol/shamrice/` — every
program indexes without raising and every FD resolves to ≥1 record or reports
why not.

---

### Phase 2 — `BoundaryInventory`

`cobolparser/analysis/boundary_inventory.py`. Walks the PROCEDURE DIVISION and
emits `BoundaryRef`s **using mockymock's key convention**, then attaches the
layout from Phase 1 and a direction:

| Site | Key | Direction | Layout source |
|---|---|---|---|
| `READ f [INTO x]` | `f` | IN | FD record, or `x` if `INTO` |
| `WRITE r [FROM x]` | `r` (record!) | OUT | the 01 record `r` |
| `REWRITE r` | `r` | OUT | record |
| `OPEN`/`CLOSE`/`START`/`DELETE`/`UNLOCK` | file | status-only | `FILE STATUS` field |
| `CALL "P" USING a, b` | `"P"` | per-arg (Phase 2b) | each arg's layout |
| dynamic `CALL id` | `id` | per-arg | `DynamicCallAnalyzer` for targets |
| `EXEC SQL SELECT … INTO :h` | text prefix | IN | `into_variables` layouts |
| `EXEC SQL INSERT/UPDATE/DELETE` | text prefix | OUT | `host_variables` layouts |
| `EXEC SQL FETCH` (+ `DECLARE CURSOR`) | text prefix | IN, multi-row | cursor's `into_variables` |
| `EXEC CICS` / `EXEC DLI` | text prefix | both | `INTO`/`FROM` operand layout |
| `ACCEPT x` (console only) | `x` | IN | `x`'s layout |
| `DISPLAY` | — | OUT (assert-only) | operand layouts |

SQL keys use the **shortest unique word-prefix** among same-category sites —
mirroring `generator._unique_prefix` in mockymock, so a generated key never
produces an `AMBIGUOUS_MOCK` at splice time.

**Phase 2b — CALL argument direction.** The hard sub-problem. A `BY REFERENCE`
argument may be in, out, or both. Resolution order:
1. **Callee source available** (`--callee-path`): use its LINKAGE 01s and
   whether the callee MOVEs *to* each linkage item (→ it is an output, so we
   generate in-data for it) or only reads it (→ input, generate out-data
   expectation).
2. **Caller-side dataflow**: last write before the CALL in the same paragraph
   ⇒ the caller supplies it (OUT). First read after the CALL with no
   intervening write ⇒ the callee supplies it (IN). Both ⇒ BIDIRECTIONAL.
3. **`BY CONTENT` / `BY VALUE`** ⇒ input-only by language rule.
4. Otherwise **BIDIRECTIONAL** and recorded in `unresolved` — generate a value
   *and* an expectation stub, flagged.

*Tests:* the `call_*.cbl` sample family (20 files) is exactly the corpus for
this; `subprogram_demo.cbl` gives a caller/callee pair.

---

### Phase 3 — `ProgramFixtureGenerator` (random baseline) + CLI

`cobolparser/generators/program_fixtures.py`, plus
`cobol-parser gen-fixtures`:

```
cobol-parser gen-fixtures PROG.cbl
    [--copybook-path DIR]...   [--callee-path DIR]...
    [--rows N] [--seed N] [--scenarios happy|branches|all]
    [--format json|csv-dir|cut] [-o PATH]
    [--list-boundaries] [--describe] [--strict]
```

Output at this phase: one `Scenario` ("happy path"), every boundary populated
with layout-valid values from the Phase 0 engine, sequences of length `--rows`
for READ/FETCH with a terminal EOF/`SQLCODE 100`, success statuses everywhere
(`FILE STATUS "00"`, `SQLCODE 0`, `RETURN-CODE 0`).

`--strict` exits non-zero if anything landed in `unresolved` — the CI-friendly
"no silent gaps" switch. `--list-boundaries` is the cheap debugging view and
the natural cross-check against `mockymock`'s own site list.

*Acceptance:* for every program in `tests/samples/` and
`examples/cobol/shamrice/`, `gen-fixtures --format json` produces a bundle
whose every generated cell is assignable to its field (the same property
`tests/integration/test_copybook_csv_generation.py` already asserts), and no
program crashes the generator.

---

### Phase 4 — `ConstraintExtractor` + solver: the "fully test" part

`cobolparser/analysis/constraints.py`.

**Extract.** Walk every `IfStatement.condition`, `EvaluateStatement`
subject/`WhenClause`s, `SearchStatement … WHEN`, and PERFORM `UNTIL` for
`ConditionalExpression`s whose operand resolves (via Phase 1) to a field fed
by a boundary. Supported forms in v1:

| Form | Constraint |
|---|---|
| `WS-X = 42` / `NOT = 42` | `eq/ne` |
| `WS-X > 5`, `<`, `>=`, `<=` | numeric interval |
| `WS-X = "ABC"` | literal set |
| level-88 `IF ORDER-VALID` | the 88's `VALUE`s (already parsed, incl. `THRU`) |
| `WS-X = SPACES / ZEROS / LOW-VALUES` | figurative |
| class tests `IF WS-X NUMERIC / ALPHABETIC` | category |
| `A AND B` / `A OR B` / `NOT A` | conjunction / branch split / negation |
| `IF WS-EOF = "Y"` on a mock-set flag | sequence-length constraint (see below) |

Unsupported in v1 and explicitly reported, never silently dropped: arithmetic
in conditions (`IF A + B > C`), reference modification, comparisons between
two boundary-fed fields, `ALTER`, sign/`SIZE ERROR` conditions.

**Solve.** No external dependency (core library is zero-dependency, and that
stays true). A small domain-propagation engine over `FieldSpec`:
- numeric → interval `[lo, hi]` clipped to the picture's digit range and sign,
  plus an excluded-value set;
- alphanumeric → an allow-set / deny-set of literals, else "any of size n";
- 88-backed → the enumerated domain minus exclusions.
Pick a witness from the domain (midpoint / first allowed literal), then run it
through the **existing** `_fit_text`/`_format_number` so a solved value can
never violate the layout — the same invariant the copybook generator already
guarantees. Empty domain ⇒ branch is unsatisfiable-as-modeled ⇒ reported.

**Loop/EOF constraints.** A `READ … AT END MOVE "Y" TO WS-EOF` plus
`PERFORM UNTIL WS-EOF = "Y"` means the *sequence length* is the knob, not a
field value. Model `sequence_length` as a first-class constraint so scenarios
can request "3 records then EOF", "EOF on the first read", "exactly 1 record".
This is what makes the mockymock tally idiom
(`IF UT-READ-INV-FILE-TALLY > 2 …`) generatable rather than hand-written.

*Tests:* new `tests/unit/analysis/test_constraints.py` with hand-built
programs per condition form; property test that a solved value always
satisfies its own constraint *and* is layout-valid.

---

### Phase 5 — `ScenarioPlanner`

`cobolparser/generators/scenarios.py`. Turns constraints + the CFG into a
scenario set:

1. Take `ProgramFlowAnalyzer`'s branch nodes; for each arm, collect the path
   condition from entry (conjunction of the constraints along the way).
2. Solve per arm ⇒ one scenario per reachable arm; merge arms whose
   constraint sets are compatible and disjoint in fields (fewer, richer
   scenarios instead of one per arm).
3. Add fixed scenario families regardless of branches:
   - **empty input** — EOF on first `READ`, `SQLCODE 100` on first `FETCH`;
   - **error statuses** — `FILE STATUS "35"` (not found) on `OPEN`, `"23"` on
     random `READ`, `SQLCODE -911` (deadlock), non-zero `RETURN-CODE` on
     `CALL` — one per declared error-handling path found
     (`INVALID KEY` / `AT END` / `ON EXCEPTION` clause bodies are the ground
     truth for which errors the program actually handles);
   - **boundary values** — min/max of each numeric field's picture range.
4. Emit `CoverageSummary`: arms targeted, arms missed with a reason string
   (`"unsupported condition form: arithmetic"`, `"unreachable"`,
   `"field not boundary-fed"`). `--strict` fails on any miss.

`--scenarios happy` (Phase 3 behavior) / `branches` (arm coverage) / `all`
(+ error and boundary families).

---

### Phase 6 — Emitters

**`--format json`** — the `FixtureBundle` (stable, versioned key set, contract
tested; this is the machine interface other tools consume).

**`--format csv-dir`** — one CSV per file boundary per scenario:
`out/happy-path/INV-FILE.csv`. Reuses `GeneratedDataset.write_csv`, including
its `_DEFAULT_LINE_TERMINATOR` agreement between `to_csv`/`write_csv`.

**`--format cut`** — a `.cut` suite:

```
TESTSUITE "INVUPDT generated"

PROVIDER QtyCases
    HEADER InvQty, ExpectedTotal
    ROW 5, 10
    ROW 0, 0

TESTCASE "MAIN-PROCESS: qty below reorder" USING PROVIDER QtyCases
    MOCK OPEN INV-FILE
    END-MOCK
    MOCK READ INV-FILE
        IF UT-READ-INV-FILE-TALLY > 2
            MOVE "Y" TO WS-EOF
        ELSE
            MOVE {InvQty} TO INV-QTY
        END-IF
    END-MOCK
    MOCK SQL "UPDATE INVENTORY"
        MOVE 0 TO SQLCODE
    END-MOCK
    PERFORM MAIN-PROCESS
    EXPECT WS-TOTAL-QTY TO BE {ExpectedTotal}
    VERIFY READ INV-FILE WAS PERFORMED 3 TIMES
```

Mapping rules: sequence ⇒ tally-branching body; SQL multi-row ⇒ the existing
`MOCK SQL … ROWS (…)` sugar; non-zero statuses ⇒ `FILE-STATUS IS`; scenarios
that differ only in field values ⇒ one `TESTCASE … USING PROVIDER` instead of
N cases (this is precisely what `PROVIDER` was built for); shared mocks ⇒
`BEFORE-EACH`.

Every emitted `.cut` must **parse and lint clean** — a CI test that runs
`mockymock lint` over the generated suites for the mockymock examples corpus.
A generator that emits refusable `.cut` is worse than no generator.

---

### Phase 7 — Expectations: what we can honestly assert

Static analysis knows the *inputs*; it does not know the program's *outputs*
without running it. Three tiers, in decreasing confidence:

1. **Structural — always safe.** `VERIFY <op> <key> WAS PERFORMED N TIMES`
   derived from the scenario's own sequence lengths and the loop structure.
2. **Traceable — emit when derivable.** A field reached from mock-provided
   input through a chain of `MOVE`/`ADD`/`COMPUTE` with literal operands can
   be evaluated statically (`WS-TOTAL = 5 + 5 = 10`). Implement a small
   constant-folding walk; emit `EXPECT` only when every operand in the chain
   is known, otherwise skip.
3. **Everything else — never guess.** Emit as a commented stub:
   `*> EXPECT WS-DISCOUNT TO BE <fill in>` with a note naming the paragraph
   that computes it. A wrong `EXPECT` in a generated suite is a false failure
   that trains people to ignore the tool.

**Optional Phase 7b — golden/characterization mode** (mockymock side):
`mockymock run --record-expectations` runs the generated suite once and writes
the observed values back as real `EXPECT` lines. That converts tier 3 into
approval tests: the first run defines the baseline, later runs catch drift.
This is the only sound way to get full output assertions, and it belongs in
the repo that actually executes COBOL.

---

### Phase 8 — mockymock integration

- `mockymock generate PROG.cbl --with-data [--seed N] [--scenarios all]`
  calls `cobolparser.generators.generate_program_fixtures()`, joins the bundle
  to its own `MockSurface` by `(category, key)`, and fills bodies from the
  bundle instead of `_PLACEHOLDER_BODIES`. Unmatched keys on either side are a
  **loud** warning listing both sets — that mismatch is the integration's main
  failure mode and must never be silent.
- Contract test in mockymock: for each `examples/*/` program, the key set from
  `mock_surface.analyze()` equals the key set from the cobolparser bundle.
- Update `interface-contract.md` (cobol-parser) and `.okf/integration.md`
  (mockymock) with the new public surface.
- Pin the cobolparser dependency bump in mockymock's `pyproject.toml`.

---

### Phase 9 — Docs and knowledge base

- `.okf/generators.md` — new "Program fixtures" section (layout index,
  boundary inventory, scenarios, emitters, the fail-loud fields).
- `.okf/analysis.md` — `BoundaryInventory`, `ConstraintExtractor`.
- `.okf/cli.md` + `CLAUDE.md` — `gen-fixtures`.
- `CHANGELOG.md` Unreleased.
- `docs/plans/` — this document, updated as phases land.
- Worked example: a new `examples/fixtures/` program exercising file + SQL +
  CALL + ACCEPT, with its generated bundle and `.cut` checked in as a golden.

---

## 6. Sequencing and effort

| Phase | Depends on | Rough size | Ships value on its own? |
|---|---|---|---|
| 0 Refactor value engine | — | S | No (enabler) |
| 1 `ProgramLayoutIndex` | 0 | M | Yes — `--list-boundaries`, layout dumps |
| 2 `BoundaryInventory` (+2b CALL direction) | 1 | M–L | Yes |
| 3 `gen-fixtures` random baseline | 1,2 | M | **Yes — first usable release** |
| 4 Constraints + solver | 1,2 | L | No (feeds 5) |
| 5 `ScenarioPlanner` | 3,4 | M | **Yes — the "fully test" claim** |
| 6 Emitters (json/csv/cut) | 3,5 | M | Yes |
| 7 Expectations tiers 1–2 | 5,6 | M | Yes |
| 7b Golden mode (mockymock) | 6 | M | Yes |
| 8 mockymock `--with-data` | 6 | S–M | **Yes — the end-to-end story** |
| 9 Docs/OKF | all | S | — |

**Recommended cut line for a first release: Phases 0–3 + 6(json/csv) + 8.**
That already delivers "point at a program, get every boundary's data, get a
runnable `.cut`". Phases 4–5 are the larger investment and are what turn
"runnable" into "actually covers the program".

---

## 7. Limits to state up front

- **We generate inputs, not truth.** Without executing, out-data is
  structural or constant-folded only (§7). Say so in the docs; do not let the
  CLI imply otherwise.
- **Unexpanded copybooks poison layouts.** If a `COPY` cannot be resolved,
  the record layout is wrong, not merely incomplete. `gen-fixtures` must refuse
  (fail-closed, matching mockymock's `UNRESOLVED_COPYBOOK`) rather than emit a
  partial record.
- **`REDEFINES` is a genuine ambiguity.** Which alternative is live is a
  runtime fact. Default to the base definition, offer `--redefines-as NAME`,
  and record the choice in `provenance`.
- **`OCCURS DEPENDING ON`** — generate at the max bound (today's behavior) but
  set the depending-on field consistently, otherwise the program reads garbage
  past the live length.
- **DECLARATIVES / `ALTER` / `SORT`-`MERGE`** — mockymock refuses these
  outright; `gen-fixtures` should mark affected paragraphs `unconstrained`
  rather than generate data for a suite that will be refused anyway.
- **Determinism is a contract.** Same program + same seed ⇒ byte-identical
  bundle, `.cut`, and CSVs. Pin it with a byte-comparison test, not a parsed
  comparison — the exact failure mode the `write_csv` line-terminator bug
  demonstrated.

---

## 8. Open decisions for you

1. **Cut line** — ship 0–3+6+8 first (usable in weeks, random data), or hold
   the release until 4–5 land (branch-directed data)? Recommendation: ship
   early; scenario coverage is additive and the bundle schema absorbs it.
2. **Callee sources** — is `--callee-path` (parse the called programs to type
   their LINKAGE) in scope for v1, or is caller-side dataflow good enough?
3. **`.cut` emission home** — cobol-parser emitting `.cut` text couples it to
   mockymock's grammar. The alternative is cobol-parser emitting only JSON and
   mockymock owning all `.cut` text (it already is the only text producer, via
   `scaffold_cut`). Recommendation: **the latter** — cobol-parser stays
   grammar-agnostic, `--format cut` lives in mockymock as `generate --with-data`.
4. **Golden/characterization mode (7b)** — worth the extra surface, or keep
   generated suites input-only and let people write their own `EXPECT`s?
