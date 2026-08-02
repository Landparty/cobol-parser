---
type: Module
title: Generators
description: Output generators — flowcharts from a program-flow report, and synthetic CSV test data from a copybook record layout.
tags: [generators, flowchart, copybook, test-data, csv, mermaid, dot]
timestamp: 2026-08-02T00:00:00Z
---

# Overview

`cobolparser/generators/` — modules that turn parsed COBOL into an output
artefact rather than an analysis report.

| File | Produces |
|------|----------|
| `flowchart.py` | Mermaid / Graphviz DOT flowcharts from a `ProgramFlowReport` |
| `copybook_data.py` | Backwards-compatible re-export shim for copybook → CSV; implementation in `data/` |
| `data/` | Copybook test data generation — modular internal implementation |

# Flowcharts (`flowchart.py`)

`MermaidFlowchartGenerator` / `DotFlowchartGenerator` consume a
`ProgramFlowReport` (see [analysis.md](analysis.md)) and emit a diagram
string. `FlowchartOptions` controls statement counts, edge labels,
fall-through edges, unreachable nodes, and synthetic external-CALL nodes.
Driven by `cobol-parser program-flow --format mermaid|dot`.

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
- **`layout.py`** — `FieldCategory` enum, `FieldSpec` namedtuple, `flatten_record()` function; the record flattening rules that turn a nested `CobolDataItem` tree into a flat list of columns.
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
override the first four.

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

# See Also

* [ast-models.md](ast-models.md) — `CobolDataItem` / `PictureClause` /
  `OccursClause` / `ConditionNameItem`, the inputs to flattening
* [cli.md](cli.md) — `gen-data` and `program-flow` subcommands
* [analysis.md](analysis.md) — `ProgramFlowReport` feeding the flowcharts
