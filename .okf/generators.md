---
type: Module
title: Generators
description: Output generators — flowcharts from a program-flow report, synthetic CSV test data from a copybook record layout, and the gen-fixtures program-scoped test-data initiative (layout index, program fixture bundles, scenario planning, all wired into the CLI).
tags: [generators, flowchart, copybook, test-data, csv, mermaid, dot, program-layout, fixtures, scenarios]
timestamp: 2026-08-12T12:00:00Z
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
Driven by `cobol-parser program-flow --format mermaid|dot`.

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
  `"{kind} · {line}"`, positioned right after the main node loop and
  before external-call nodes in both generators — Mermaid emits `(((...)))`
  triple-circle syntax plus a `terminal` classDef
  (`fill:#1b1b1b,stroke:#c1121f`); DOT emits `shape=doublecircle` with
  matching `fillcolor`/`fontcolor`. Both respect `show_unreachable`
  identically to the main node loop. The terminal id is normally
  `f"{nid}_EXIT"` (`nid = _sanitize_id(node.name)`), but module-level
  `_unique_exit_id(nid, paragraph_ids)` (shared by both generators) falls
  back to `{nid}_FLOWEXIT`, then an incrementing numeric suffix, whenever
  that id collides with a real paragraph's own sanitized id. **Bug fixed
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

Reference tests: `tests/unit/test_flowchart_generator.py` —
`TestMermaidFlowchartGenerator` (linkStyle/terminal-node/THRU-badge
sections, plus `test_linkstyle_index_accounts_for_terminal_node_links` and
`test_terminal_id_does_not_collide_with_real_exit_paragraph` pinning the
two composition-bug fixes above), `TestDotFlowchartParity` (the DOT-side
mirror), and `TestSortThruEndToEnd` (real-COBOL-through-the-analyzer proof
that a SORT OUTPUT PROCEDURE THRU range now reaches both renderers).

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
- **`layout.py`** — `FieldCategory` enum, `FieldSpec` dataclass, `flatten_record()` function; the record flattening rules that turn a nested `CobolDataItem` tree into a flat list of columns.
- **`values.py`** — `ValueFactory` class; generates synthetic values for a field, respecting PICTURE/USAGE/level-88 domain/VALUE/semantic hints.
- **`dataset.py`** — `GeneratedDataset` class; holds rows, fields, seed, and `to_csv()` / `write_csv()` / `to_dicts()` export methods.
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
                   .to_csv(*, line_terminator="\n")
                   .write_csv(path, *, line_terminator="\n")
                   .to_dicts() .to_dict()
FieldSpec:         .name .path .column .level .picture .usage .category
                   .size .integer_digits .decimal_digits .is_signed
                   .value_clause .condition_values .subscripts .redefines
                   .qualified_name .to_dict()
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

`_format_number`'s `allow_random_sign` guards a subtle trap: a signed field
negates a freshly generated magnitude ~25 % of the time so negatives get
exercised, but values the copybook *declared* (levels 1-2 above) must be
formatted with `allow_random_sign=False` — otherwise `88 ST-LOW VALUE 5` on a
`PIC S9(3)` field emits `-5`, a value the copybook never permits. Pinned by
`test_declared_domain_values_are_never_randomly_negated`.

**Signedness.** `PictureClause.is_signed` only reports an explicit `S`, so
`_is_signed()` additionally treats a numeric-edited picture carrying `+`,
`-`, `CR`, or `DB` as signed — `PIC -ZZ,ZZ9.99` is the canonical signed
display field and would otherwise never generate a negative.

**Edited pictures** contribute their *logical* numeric value, not the edited
display form: a CSV is consumed by tooling that wants the value, and the
edit mask is a presentation concern of the COBOL program. Likewise `COMP-3`
carries the decimal value, not packed bytes.

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
  from `ValueFactory.value_for()`.
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
CSV lives — without walking the directory tree first. See
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
* `tests/unit/cli/test_gen_data_cli.py` — `gen-data` flags, JSON modes, errors
* `tests/integration/test_copybook_csv_generation.py` — parametrized over the
  sample copybooks and the NIST `.CPY` corpus; asserts no copybook crashes the
  generator and that generated cells are assignable to their fields
* `tests/contracts/test_copybook_data_generator_contract.py` — exported names,
  signatures, `to_dict()` key sets, reproducibility guarantee
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
