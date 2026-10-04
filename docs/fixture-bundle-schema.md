# Fixture Bundle Schema

**Produced by:** `cobolparser.generators.ProgramFixtureGenerator` (`generate`,
`generate_with_scenarios`, and their `_from_file` counterparts) — backs the
`cobol-parser gen-fixtures` CLI subcommand.
**Consumed by:** mockymock's `generate --with-data` (Phase 8 of the
`gen-fixtures` program-scoped test-data initiative; see
[`docs/plans/2026-08-02-program-data-generation-design.md`](plans/2026-08-02-program-data-generation-design.md)).
**Current `bundle_version`:** `1`.

This is hand-written prose, not a JSON-Schema document — the repo has a
zero-runtime-dependency rule for the core library, and a schema validator is
one more thing a consumer would need to install. Every shape below is a
Python `dataclass` with a `to_dict()` method in
`cobolparser/generators/data/bundle.py` (bundle-level types) or
`cobolparser/generators/scenarios.py` (`scenario_coverage`); that source is
the actual contract, this document is a guide to reading it.
`tests/contracts/test_fixture_bundle_contract.py` pins every key set named
below — a key added or removed there without a matching edit here is a bug in
one of the two.

## Getting a bundle

```python
from cobolparser.generators import ProgramFixtureGenerator

generator = ProgramFixtureGenerator()

# "happy path" only -- one scenario, no branch targeting
bundle = generator.generate_from_file("DOCEX.cbl", seed=7)

# Phase 5/6: branch-targeted scenarios plus fixed families
bundle = generator.generate_with_scenarios_from_file(
    "DOCEX.cbl", mode="all", seed=7,   # mode: "happy" | "branches" | "all"
)

bundle.to_json()          # str -- what gen-fixtures --format json prints
bundle.write_csv_dir(...) # one CSV per file-shaped fixture -- see below
```

`mode="happy"` and `generate()`/`generate_from_file()` are exactly the same
bundle (`generate_with_scenarios(..., mode="happy")` delegates to `generate()`
unchanged, byte-for-byte) — `scenario_coverage` is `None` and there is always
exactly one scenario. `mode="branches"`/`"all"` route through Phase 5's
`ScenarioPlanner` instead; every field described below exists in both modes,
`scenario_coverage` is the only key that is `None` in happy mode and populated
otherwise.

## Top level: `FixtureBundle`

| Key | Type | Notes |
|---|---|---|
| `bundle_version` | `int` | Currently `1`. Bumped only on a breaking change to this shape — see "Versioning" below. |
| `program_name` | `str \| null` | The `PROGRAM-ID`, or `null` if the program has none. |
| `seed` | `int` | The RNG seed that produced this bundle. If you didn't pass one, this is the one that was drawn — replay with `seed=bundle["seed"]`. |
| `scenarios` | `list[Scenario]` | One entry per scenario (see below). Always at least one. |
| `layouts` | `dict[str, list[FieldSpec]]` | Record name → its resolved field layout, emitted **once per record** — scenarios reference a layout by name rather than repeating it inline. |
| `coverage` | `CoverageSummary` | Boundary-level counts (Phase 3, present in every bundle). |
| `unresolved` | `list[str]` | Program-level gaps not tied to one scenario/boundary — an unresolved COPY member, a dynamic CALL with no traceable target, etc. Merges Phase 1 (`ProgramLayoutIndex.unresolved`), Phase 2 (`Boundary.unresolved`), and Phase 3's own field-resolution gaps. |
| `scenario_coverage` | `ScenarioCoverage \| null` | Phase 5/6 arm-coverage accounting. `null` in `mode="happy"`, populated in `"branches"`/`"all"`. See below. |

## `Scenario`

| Key | Type | Notes |
|---|---|---|
| `name` | `str` | E.g. `"happy path"`, `"CHECK-QTY: THEN"`, `"empty input"`, `"boundary values: minimum"`. Human-readable, not a stable identifier — don't parse it; `scenario_coverage.details[].arm_key` is the stable per-arm key. |
| `intent` | `str` | One sentence: what this scenario is for. |
| `entry` | `str \| null` | The program's first PROCEDURE DIVISION paragraph, if any. |
| `fixtures` | `list[BoundaryFixture]` | Mock in-data for every boundary the scenario touches. |
| `expectations` | `list[Expectation]` | Assert-on stubs (see below). |
| `unconstrained` | `list[str]` | Reserved for a future phase; always `[]` today (a happy-path scenario doesn't attempt branch coverage, and Phase 5/6 record misses in `scenario_coverage` instead, not here). |
| `verification` | `ScenarioVerification` | Present only for a `"branches"`/`"all"` scenario (absent in `mode="happy"`, which targets no branch). See below. |

### `ScenarioVerification`

Does this scenario's OWN generated data actually satisfy the branch it is
named for? A scenario's name is a claim; before this key existed the only way
to check it was to run each case under a tracer.

| Key | Type | Notes |
|---|---|---|
| `status` | `"verified" \| "unverified"` | `"verified"` iff every constrained field is `satisfied` **and** there are no `gaps`. |
| `fields` | `list[FieldVerdict]` | One per field the scenario's arm (and its accumulated path condition) constrains. |
| `gaps` | `list[str]` | Enclosing arms on this scenario's path whose own conditions were never modeled, so reaching the arm is not pinned by the data. |

| `FieldVerdict` key | Type | Notes |
|---|---|---|
| `field` | `str` | Qualified field name. |
| `status` | `"satisfied" \| "violated" \| "absent" \| "unknown"` | `absent` = no fixture generates the field at all, so nothing pins the branch. `unknown` = a conjunct could not be decided from the rendered value — deliberately never reported as `satisfied`. |
| `detail` | `str` | Human-readable reason. |
| `rows` | `list[int]` | 0-based indices of the generated rows meeting every conjunct (`satisfied` only). |

The check evaluates constraints against the concrete rendered strings a mock
will actually move into the program, independently of the solver that chose
them — so a solver bug, a rendering bug, and a witness that never reached any
fixture all surface here rather than as a green label.

**Every scenario carries a fixture for every boundary the program touches**,
not just the ones its targeted branch arm constrains. A `mode="all"` bundle
for a program with 3 boundaries and 6 branch-arm-derived scenarios has 6
complete, independently runnable fixture sets — the arm's own witness pins
whichever field(s) that arm's condition touches, and every other field is
generated exactly the way the happy-path scenario would generate it. This is
deliberate: a scenario is meant to be handed to a mock runner as a complete
input, not a diff against some baseline.

## `BoundaryFixture`

One entry per boundary the scenario resolved.

| Key | Type | Notes |
|---|---|---|
| `category` | `str` | `"READ"`, `"WRITE"`, `"OPEN"`, `"CLOSE"`, `"DELETE"`, `"START"`, `"UNLOCK"`, `"REWRITE"`, `"SQL"`, `"CICS"`, `"DLI"`, `"ACCEPT"`, `"CALL"`, or `"DYNCALL"` — the same category vocabulary as `BoundaryInventoryAnalyzer` (`.okf/analysis.md`). |
| `key` | `str` | The file/program/host-variable name identifying this boundary — same `key` mockymock's own `mock_surface` uses. |
| `paragraph` | `str \| null` | Where in PROCEDURE DIVISION this boundary is invoked. |
| `line` | `int \| null` | Source line of the invoking statement. |
| `direction` | `str` | `"IN"`, `"OUT"`, `"BIDIRECTIONAL"`, or `"STATUS_ONLY"` (OPEN/CLOSE/DELETE/START/UNLOCK: nothing to generate, only a status code). |
| `layout` | `list[FieldSpec]` | Empty for `STATUS_ONLY` and for an OUT boundary (no fixture is generated for those — see `direction` rules below). |
| `sequence` | `list[dict[str, str]]` | One dict per invocation, each a column-name → generated-value mapping aligned to `layout` — the same string-cell convention `GeneratedDataset.rows` uses. A READ gets `--rows` entries; every other IN/BIDIRECTIONAL boundary gets exactly one. |
| `terminal` | `dict[str, str] \| null` | What happens after `sequence` is exhausted — e.g. `{"FILE-STATUS": "10"}` when the boundary has an `AT END` handler. `null` when there's no such handler. |
| `status` | `dict[str, str]` | E.g. `{"SQLCODE": "0"}` or `{"WS-FILE-STATUS": "00"}`. Present on every fixture with a status concept, not just `STATUS_ONLY` ones. Empty `{}` when the boundary has no status field at all. |
| `provenance` | `str` | Why these values: `"picture-random"` (no constraint touched this field) or `"constraint:<field>=<value>"` / `"88-domain"` once Phase 4's witnesses are wired into fixture provenance tracking (that tagging is a Phase 7 item — today every fixture reports `"picture-random"` regardless of whether a scenario pinned one of its fields; the *value itself* is still correctly pinned via `witnesses`, only the provenance label lags). |
| `unresolved` | `list[str]` | Names/reasons this specific fixture could not fully resolve. |

**No fixture at all** is emitted (the boundary contributes only to
`expectations`) for an OUT-direction boundary — a WRITE/REWRITE, an SQL
INSERT/UPDATE/DELETE, an OUT-direction CALL argument. There is nothing to
mock; the program produces that value, so it becomes a
`kind="stub"` expectation instead (see below).

## `FieldSpec` (inside `layout` and the top-level `layouts` map)

Identical to the copybook generator's own field-spec shape (see
[generators.md](../.okf/generators.md)) — `gen-fixtures` reuses the Phase 0
value engine directly, no parallel type:

```
name, column, qualified_name, level, picture, usage, category,
size, storage_size, integer_digits, decimal_digits, is_signed,
value_clause, condition_values, subscripts, redefines,
sign_clause, synchronized, occurs_depending_on,
odo_controls, odo_counter_bounds
```

`category` is one of `alphanumeric | alphabetic | national | numeric |
numeric-edited | alphanumeric-edited | float`.

**`size` vs `storage_size`.** `size` counts PICTURE *character positions* —
what a display rendering of the field is wide. `storage_size` counts the
*bytes* the item really occupies, which for a non-DISPLAY `USAGE` is a
different number: `PIC S9(7)V99 COMP-3` has `size: 9` and `storage_size: 5`,
`PIC S9(4) COMP` has `size: 4` and `storage_size: 2`, and `USAGE INDEX` has
no PICTURE at all but still occupies a fullword. Read `size` for anything
CSV-shaped and `storage_size` for anything that lays out or writes a record.

**`sign_clause`** is the raw `SIGN IS` clause (`"LEADING SEPARATE"`) or
`null`; `SEPARATE` is the one case where a DISPLAY field's `storage_size`
exceeds its `size`, because the sign gets a byte the PICTURE does not count.
**`synchronized`** and **`occurs_depending_on`** are recorded rather than
acted on — they mark the two places a record layout makes an assumption
(alignment slack is not modelled; an ODO table is *laid out* at its maximum,
which is what these `FieldSpec`s always describe).

**`odo_controls`** is the machine-readable form of `occurs_depending_on`:
one object per `OCCURS ... DEPENDING ON` dimension the field sits inside,
outermost first, each `{depending_on, subscript_index, min_times,
max_times}`. `subscript_index` is the position in this field's `subscripts`
that the counter governs, so a reader can decide whether a given occurrence
is present in a given record: it is, iff `subscripts[subscript_index] <=`
the counter's value. `max_times` is the number of occurrences actually
flattened, which a `max_occurs` cap can make smaller than the declared
maximum. `[]` for a field outside any such table.

**`odo_counter_bounds`** is `[min, max]` on a field that *is* some table's
`DEPENDING ON` counter, and `null` on every other field. It is what bounds
the generated count, so a `PIC 9(4)` counter for a table of at most 50 never
holds 8 731.

These six keys were **added**, not changed: every key that existed before
kept its name and meaning, which is why they did not require a
`bundle_version` bump. A reader written against the earlier shape keeps
working; see "Versioning and compatibility policy" below.

## `Expectation`

| Key | Type | Notes |
|---|---|---|
| `kind` | `str` | `"call_count"`, `"field_equals"`, or `"stub"` (see the three-tier note below). |
| `ref` | `str` | What this expectation is about — a boundary key (`"CATEGORY:KEY"`) or a CALL argument name. |
| `value` | `str \| int \| null` | The asserted value, when known. Always `null` for `kind="stub"`. |
| `note` | `str \| null` | Human-readable explanation, e.g. `"value produced by the program under test"` or `"bidirectional: OUT aspect not asserted in v1"`. |

**Three confidence tiers** (tiers 1–2 wired as of Phase 7; every bundle
carries all three kinds that apply):

1. `"call_count"` — structural, always safe: a mocked boundary was invoked
   exactly `value` times. Derivable directly from the scenario's own sequence
   length (`len(sequence) + 1` when a `terminal` is present, else
   `len(sequence)`; always `1` for a `STATUS_ONLY` fixture). Emitted for
   every boundary that actually got a fixture — an OUT-only boundary has
   nothing mocked to count, so it gets no `call_count` entry.
2. `"field_equals"` — a field's value is knowable by constant-folding a
   straight-line chain of MOVE/arithmetic statements from the scenario's own
   mock-supplied inputs (`cobolparser.analysis.const_fold.ConstantFolder`).
   Only a boundary fixture with *exactly one* generated row seeds the fold
   (ACCEPT, a single SQL row, a CALL's combined IN row) — a multi-row READ
   sequence has no single representative value to seed with, and in
   practice a READ's own fields are usually written inside the very
   `PERFORM UNTIL`/`VARYING` loop the folder already refuses to see inside
   of. The walk starts at the program's entry paragraph and follows
   non-looping `PERFORM`s (including `THRU` ranges) inline; a looping
   `PERFORM`, an `IF`/`EVALUATE`, `DIVIDE` (the AST does not record `BY` vs
   `INTO`, and the two invert dividend/divisor order), `ROUNDED`,
   `CORRESPONDING`, and any numeric result that would need rounding or
   truncation to fit its target field's PICTURE all leave the affected
   field(s) unknown rather than guess. Only a `DISPLAY`/`WRITE` operand that
   resolves directly to an elementary field is an observation point — never
   wrong, just narrower than a full interpreter would be. `ref` is the
   field's qualified name (not a `"CATEGORY:KEY"` pair).
3. `"stub"` — everything else: a placeholder note (e.g. "value produced by
   the program under test"), never a live assertion. This is what a
   happy-path/branch-targeted bundle's OUT-direction boundaries and any
   field tier 2 could not fold down to a value both fall back to.

## `CoverageSummary`

Boundary-level counts, present in every bundle regardless of mode:

```
total_boundaries, resolved_boundaries, unresolved_boundaries
```

`resolved_boundaries + unresolved_boundaries == total_boundaries` always.
This predates scenario planning (Phase 3) and does not change shape between
modes — it counts *boundaries*, not *branch arms*. For arm-level accounting,
see `scenario_coverage` below.

## `scenario_coverage` (Phase 5/6, `"branches"`/`"all"` only)

`null` in `mode="happy"`. Otherwise a `ScenarioCoverage.to_dict()`:

| Key | Type | Notes |
|---|---|---|
| `total_arms` | `int` | Every branch arm the control-flow graph knows about. |
| `targeted` | `int` | Arms that got their own scenario. |
| `merged` | `int` | Arms folded into another (disjoint-field) scenario instead of getting their own. |
| `missed` | `int` | Arms that could not be covered at all — see `details[].reason`. |
| `details` | `list[ArmOutcome]` | One entry per arm. |

**`total_arms == targeted + merged + missed`, always** — this is the whole
point of the accounting: every arm the CFG sees is accounted for, none silently
dropped. Each `ArmOutcome`:

```
arm_key       "<paragraph>@<line>:<column>/<arm-id>", e.g. "CHECK-QTY@31:5/THEN"
parent_proc   the enclosing paragraph name, or null
status        "targeted" | "merged" | "missed"
merged_into   the scenario name it was folded into, when status == "merged"
reason        why, when status == "missed" -- e.g. "unreachable",
              "unsatisfiable: <domain reason>", an extraction gap
              carried over from Phase 4's ConstraintReport.unsupported, or
              "witness failed verification: ..." when the scenario's own
              generated data violates the arm (the arm is also listed in
              the bundle's `unresolved`)
```

A `reason` is **never** blank when `status == "missed"` — a silent miss with
no explanation is treated as a bug in the planner, not an acceptable output.

**v1 path-condition simplification**: a targeted scenario constrains only its
*own* arm's conditions, not the conjunction of every enclosing branch on the
path to it. Two arms nested inside each other each get independently solved,
single-arm witnesses — full path-sensitivity is a later-version item. See
[generators.md](../.okf/generators.md)'s "Scenario Planning" section for the
merge/unsatisfiable/fixed-family rules that produced these scenarios.

**Known v1 limitation worth knowing before you read a witness**: a class
test (`IS NUMERIC`/`IS ALPHABETIC`) produces a real `FieldConstraint` and a
correctly `"targeted"` (or `"merged"`) arm, but `domains.py`'s solver treats
`class_numeric`/`class_alphabetic` as a no-op when picking a witness value —
it does not currently narrow the generated value to something that actually
*is* (or isn't) numeric-looking. The arm accounting is exact; the pinned
*value* for a class-tested field is not yet guaranteed to satisfy that
specific test. Every other constraint form (relational, level-88 `in_set`,
figurative, sign/zero) is fully solved.

## Worked example

`DOCEX.cbl` (an OPEN/READ-loop/CLOSE program with one `IF ORDER-QTY > 100`
branch in `CHECK-QTY`) run through `generate_with_scenarios_from_file(...,
mode="all", seed=7)` produces five scenarios: `"CHECK-QTY: ELSE"`,
`"CHECK-QTY: THEN"`, `"empty input"`, `"boundary values: minimum"`, and
`"boundary values: maximum"` (the `"error status"` family emits nothing here
— the program declares no `INVALID KEY`/`ON EXCEPTION`/status-checked `OPEN`
handler for the planner to target). Trimmed to two scenarios plus the
bundle-level keys:

```json
{
  "bundle_version": 1,
  "program_name": "DOCEX",
  "seed": 7,
  "scenarios": [
    {
      "name": "CHECK-QTY: ELSE",
      "intent": "targets branch arm CHECK-QTY@31:5/ELSE",
      "entry": "MAIN-PARA",
      "fixtures": [
        {
          "category": "OPEN", "key": "ORDER-FILE", "paragraph": "MAIN-PARA",
          "line": 20, "direction": "STATUS_ONLY", "layout": [], "sequence": [],
          "terminal": null, "status": {"WS-ORDER-STATUS": "00"},
          "provenance": "picture-random", "unresolved": []
        },
        {
          "category": "READ", "key": "ORDER-FILE", "paragraph": "MAIN-PARA",
          "line": 22, "direction": "IN",
          "layout": [{
            "name": "ORDER-QTY", "column": "ORDER-QTY",
            "qualified_name": "ORDER-RECORD.ORDER-QTY", "level": 5,
            "picture": "9(3)", "usage": "DISPLAY", "category": "numeric",
            "size": 3, "storage_size": 3,
            "integer_digits": 3, "decimal_digits": 0,
            "is_signed": false, "value_clause": null, "condition_values": [],
            "subscripts": [], "redefines": null,
            "sign_clause": null, "synchronized": false,
            "occurs_depending_on": null,
            "odo_controls": [], "odo_counter_bounds": null
          }],
          "sequence": [{"ORDER-QTY": "50"}, {"ORDER-QTY": "50"}, "... x10"],
          "terminal": {"WS-ORDER-STATUS": "10"},
          "status": {"WS-ORDER-STATUS": "00"},
          "provenance": "picture-random", "unresolved": []
        },
        {
          "category": "CLOSE", "key": "ORDER-FILE", "paragraph": "MAIN-PARA",
          "line": 27, "direction": "STATUS_ONLY", "layout": [], "sequence": [],
          "terminal": null, "status": {"WS-ORDER-STATUS": "00"},
          "provenance": "picture-random", "unresolved": []
        }
      ],
      "expectations": [
        {"kind": "call_count", "ref": "OPEN:ORDER-FILE", "value": 1,
         "note": "derived from this scenario's own generated sequence length"},
        {"kind": "call_count", "ref": "READ:ORDER-FILE", "value": 11,
         "note": "derived from this scenario's own generated sequence length"},
        {"kind": "call_count", "ref": "CLOSE:ORDER-FILE", "value": 1,
         "note": "derived from this scenario's own generated sequence length"}
      ],
      "unconstrained": []
    },
    {
      "name": "CHECK-QTY: THEN",
      "intent": "targets branch arm CHECK-QTY@31:5/THEN",
      "entry": "MAIN-PARA",
      "fixtures": [
        "... same OPEN/CLOSE STATUS_ONLY fixtures ...",
        {
          "category": "READ", "key": "ORDER-FILE", "paragraph": "MAIN-PARA",
          "line": 22, "direction": "IN",
          "layout": ["... same FieldSpec as above ..."],
          "sequence": [{"ORDER-QTY": "550"}, "... x10"],
          "terminal": {"WS-ORDER-STATUS": "10"},
          "status": {"WS-ORDER-STATUS": "00"},
          "provenance": "picture-random", "unresolved": []
        }
      ],
      "expectations": [
        "... the same three call_count entries as CHECK-QTY: ELSE above ..."
      ],
      "unconstrained": []
    }
  ],
  "layouts": {
    "ORDER-RECORD": ["... the same ORDER-QTY FieldSpec ..."]
  },
  "coverage": {
    "total_boundaries": 3, "resolved_boundaries": 3, "unresolved_boundaries": 0
  },
  "unresolved": [],
  "scenario_coverage": {
    "total_arms": 2, "targeted": 2, "merged": 0, "missed": 0,
    "details": [
      {"arm_key": "CHECK-QTY@31:5/ELSE", "parent_proc": "CHECK-QTY",
       "status": "targeted", "merged_into": null, "reason": null},
      {"arm_key": "CHECK-QTY@31:5/THEN", "parent_proc": "CHECK-QTY",
       "status": "targeted", "merged_into": null, "reason": null}
    ]
  }
}
```

`ORDER-QTY` is `PIC 9(3)` (0-999, unsigned) with a branch at `> 100`: the
`ELSE` scenario pins every generated row to `"50"` (a witness in `[0, 100]`),
the `THEN` scenario pins to `"550"` (the domain solver's midpoint of
`[101, 999]`) — both scenarios still generate a full 10-row READ sequence
(`--rows` default) because only the *value*, not the row count, is
constrained by this particular arm. The two `"boundary values"` scenarios
(elided above) pin the same field to `"0"` and `"999"` respectively — the
picture's true extremes, not `domains.solve()`'s usual interval midpoint (see
generators.md's "Scenario Planning" section for why an `eq` constraint is
used to pin those specifically).

Every scenario's `expectations` carries tier 1's three `call_count` entries
(`READ:ORDER-FILE`'s `11` is the 10-row default sequence plus one more call
for the `AT END` that stops the loop); none carries a `field_equals`. That
absence is correct, not a gap: `CHECK-QTY`'s two `DISPLAY` statements sit
inside the very `PERFORM UNTIL END-OF-FILE` loop tier 2's folder refuses to
see inside of (`ORDER-QTY`'s value changes every iteration, so no single
value is "the" value it displayed), and nothing outside that loop displays
or writes a computed field. A program that instead did
`ACCEPT WS-QTY. MULTIPLY WS-QTY BY 2 GIVING WS-DOUBLE. DISPLAY WS-DOUBLE.` —
straight-line, no loop — would get:

```json
{"kind": "field_equals", "ref": "WS-DOUBLE", "value": "1244",
 "note": "constant-folded from this scenario's own mock-supplied inputs"}
```

with `"1244"` computed from whatever value that scenario's own mocked
`ACCEPT WS-QTY` fixture happened to generate (here, `622`).

## `write_csv_dir` (the `--format csv-dir` layout)

```
<path>/
  MANIFEST.json                       # the full bundle, minus row data
  <scenario-slug>/
    <KEY>.csv                         # one per file-shaped fixture
```

* **Scenario slugging** (`_slugify` in `bundle.py`): lowercase, everything
  that isn't alphanumeric collapses to a single `-`, leading/trailing `-`
  stripped. `"CHECK-QTY: THEN"` → `check-qty-then`. Deterministic and
  filesystem-safe by construction. Scenario names are not unique (two IFs in
  one paragraph both plan a `"CHECK-QTY: THEN"`), so a repeated slug gets
  `-2`, `-3`, ... in bundle order (compared case-insensitively); the first
  keeps the plain slug. Likewise a `<KEY>.csv` two fixtures of one scenario
  would both write with *different* rows becomes `<KEY>-2.csv` for the
  later one -- same-key fixtures with identical rows still share one file.
  Always read the path from the manifest's `csv_path`.
* **Which fixtures get a CSV**: only those with both a non-empty `layout` and
  a non-empty `sequence` — `STATUS_ONLY` fixtures and OUT-direction
  expectation-only boundaries produce nothing to write (there are no rows).
* **CSV shape**: header row is `[f.column for f in fixture.layout]`; each
  data row looks up every header column in that invocation's `sequence[i]`
  dict (missing keys become `""`). Written with `\n` line endings via the
  stdlib `csv` module — the same `_DEFAULT_LINE_TERMINATOR` convention
  `gen-data`'s `GeneratedDataset.write_csv` uses, so both CLI paths agree
  byte-for-byte on newline style.
* **`MANIFEST.json`**: `bundle.to_dict()` with every fixture's `"sequence"`
  emptied to `[]` and a new `"csv_path"` key added: the CSV's path relative
  to `<path>/` (`"<scenario-slug>/<KEY>.csv"`) for a fixture that got one
  written, else `null`. `sequence` stays a list rather than being replaced
  with a hint string (an earlier version did this) so the manifest's
  per-fixture shape stays type-compatible with a normal bundle — a consumer
  that runs `MANIFEST.json` through the same deserializer as a real bundle
  JSON (reasonable, since every other key matches) would otherwise silently
  iterate a string character-by-character in place of real rows instead of
  hitting a clean type error. Everything else (layouts, coverage,
  scenario_coverage, expectations) is unchanged, so a consumer can discover
  what scenarios/fixtures/expectations exist — and where each fixture's own
  CSV lives, if it has one — by reading one small file, without walking the
  directory tree or parsing every CSV first.
* **Round-trip guarantee**: reading a `<KEY>.csv` back with `csv.reader` and
  zipping its rows against the same fixture's `sequence` in the JSON output
  produces byte-identical cells — pinned by
  `test_program_fixtures.py::TestWriteCsvDir::test_csv_dir_round_trips_byte_for_cell_against_the_json`.

## Versioning and compatibility policy

`bundle_version` bumps **only** on a breaking change — a key removed, a key's
type changed, or a key's meaning changed under an unchanged name. Every
change so far, including this document's own Phase 6 (`scenario_coverage`),
has been **additive**: a new key that is `None`/absent-equivalent unless a
new capability (a new `mode=`, a new CLI flag) is actually used. The same
holds for `Scenario.verification` (2026-09-04), which is absent entirely in
`mode="happy"`. A consumer
that only reads keys it knows about is unaffected by a bundle produced by a
newer `cobolparser` gaining one more key. Phase 8 (mockymock integration)
checks `bundle_version` before consuming a bundle and fails closed on an
unrecognized value rather than guessing at a schema that changed underneath
it — this is the reason the field exists at all rather than being inferred
from key presence.

## Determinism

Every bundle is reproducible: the same `(program source, seed, mode)` always
produces byte-identical `to_json()` output, including `scenario_coverage` and
scenario ordering. Each boundary derives its own sub-seed
(`zlib.crc32(f"{scenario}|{category}|{key}") ^ bundle_seed`) so that adding an
unrelated boundary never reshuffles another boundary's already-generated
values — see generators.md's "Determinism: per-boundary sub-seeds" section.
An unseeded call draws a seed and reports it on `bundle.seed`, so an
interesting unseeded run is always replayable after the fact.

## See also

* [`.okf/generators.md`](../.okf/generators.md) — the generators that produce
  this bundle (`ProgramFixtureGenerator`, `ScenarioPlanner`), and the value
  engine (`ValueFactory`/`FieldSpec`/`flatten_record`) it reuses.
* [`.okf/analysis.md`](../.okf/analysis.md) — `BoundaryInventoryAnalyzer`
  (Phase 2, produces the boundaries this bundle covers), `ConstraintExtractor`
  / `domains.py` (Phase 4, produce the witnesses scenarios pin), and
  `ConstantFolder` (Phase 7, produces `field_equals` expectations).
* [`.okf/cli.md`](../.okf/cli.md) — the `gen-fixtures` CLI subcommand's flags.
* [`docs/plans/2026-08-02-program-data-generation-design.md`](plans/2026-08-02-program-data-generation-design.md)
  and
  [`docs/plans/2026-08-02-program-data-generation-implementation.md`](plans/2026-08-02-program-data-generation-implementation.md)
  — the full 9-phase plan this bundle is Phase 3/5/6/7's deliverable of.
