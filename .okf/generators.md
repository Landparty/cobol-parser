---
type: Module
title: Generators
description: Routing page for cobolparser/generators/ — flowcharts, copybook test data and record images, record decode/compare, and the gen-fixtures program fixture stack; says which generators/*.md file to load and maps each module to it.
tags: [generators, flowchart, copybook, test-data, csv, mermaid, dot, program-layout, fixtures, scenarios, layout-offsets]
timestamp: 2026-10-15T00:00:00Z
---

# Generators

`cobolparser/generators/` turns parsed COBOL into an output artefact rather
than an analysis report: diagrams, synthetic test data, real record images
(and the decoder/comparer that reads them back), and program-scoped fixture
bundles for `gen-fixtures`. Everything is stdlib-only and deterministic per
`seed`. This page only routes: pick the file for your task below and load
that one. CLI flags for every subcommand live in [cli.md](cli.md).

## Which file?

| Task | Load |
|------|------|
| Mermaid / DOT flowcharts (`program-flow --format mermaid\|dot`) | [generators/flowchart.md](generators/flowchart.md) |
| Copybook → CSV / record image, `FieldSpec` flattening, `ValueFactory`, byte widths/offsets (`data-items`), encodings, RECFM=F/V, ODO, `RECORD VARYING` (`gen-data`) | [generators/record-data.md](generators/record-data.md) |
| Reading a record image back, REDEFINES views, framing, expected-vs-actual compare (`decode`, `compare`) | [generators/decode-compare.md](generators/decode-compare.md) |
| `ProgramLayoutIndex`, `ProgramFixtureGenerator`, `FixtureBundle`, scenarios, verification, expectations (`gen-fixtures`) | [generators/fixtures.md](generators/fixtures.md) |

## Entry points

| Task | API | CLI |
|------|-----|-----|
| Flowchart | `MermaidFlowchartGenerator` / `DotFlowchartGenerator` | `program-flow --format mermaid\|dot` |
| Copybook → CSV / record image | `CopybookDataGenerator(DataGeneratorOptions(...)).generate_from_file()` → `GeneratedDataset` | `gen-data` |
| Record image → table | `RecordDecoder.from_copybook_file(...).decode_file()` → `DecodeResult` | `decode` |
| Expected vs actual file | `compare_files(decoder, expected, actual, key=[...])` → `CompareResult` | `compare` |
| Byte offsets of every data item | `data.layout_offsets.compute_program_data_items(ast)` | `data-items` |
| Whole-program fixtures | `ProgramFixtureGenerator().generate_with_scenarios_from_file(path, mode=...)` → `FixtureBundle` | `gen-fixtures` |

## Module map

| Source | Topic file |
|--------|-----------|
| `generators/flowchart.py` | [flowchart.md](generators/flowchart.md) |
| `generators/copybook_data.py` (re-export shim) | [record-data.md](generators/record-data.md) |
| `generators/data/options.py`, `errors.py`, `layout.py`, `layout_offsets.py`, `values.py`, `storage.py` (→ `cobolparser/_storage.py`), `editing.py`, `encoding.py`, `dataset.py`, `copybook.py`, `__init__.py` | [record-data.md](generators/record-data.md) |
| `generators/data/views.py`, `decoding.py`, `compare.py` (+ `copybook.select_record` / `fd_record_length`) | [decode-compare.md](generators/decode-compare.md) |
| `generators/data/program_layout.py`, `bundle.py` | [fixtures.md](generators/fixtures.md) |
| `generators/program_fixtures.py`, `scenarios.py`, `verification.py` | [fixtures.md](generators/fixtures.md) |
| `generators/__init__.py` (lazy exports) | this page |

## Import architecture

`cobolparser.generators.__init__` is **lazy** (`__getattr__`-based, mirroring
`cobolparser.analysis.__init__`): importing the package touches no submodule;
each public name resolves on first attribute access. `__all__` lists **54**
names (copybook data, record encoding/decoding/views/compare, layout index,
bundle shapes, flowcharts, `ProgramFixtureGenerator`). Several helpers live
only in `cobolparser.generators.data` (its own `__all__`, 61 names):
`encode_record`, `encode_field`, `hex_dump`, `decode_field`, `decode_record`,
`occurrence_count`, `unresolved_odo_counters`, `select_record`,
`ValueFactory`, `binary_byte_length`, `packed_byte_length`.

Keep it lazy: `program_fixtures.py` depends at runtime on
`cobolparser.analysis.constraints` / `.domains` / `.program_flow`, which are
reachable from `cobolparser.analysis` modules that need `generators.data.*`
(`FieldSpec`, `ValueFactory`, `ProgramLayoutIndex`). Eager package-init
imports make the first touch of either package fail with "partially
initialized module" depending on unrelated import order.
(`generators.data.__init__` itself is eager.)

## See also

* [cli.md](cli.md) — `gen-data`, `decode`, `compare`, `data-items`,
  `gen-fixtures` and `program-flow` subcommands
* [analysis.md](analysis.md) — `ProgramFlowReport` (flowcharts, scenario
  joins), `BoundaryInventoryAnalyzer`, `ConstraintExtractor` /
  `domains.solve()`, `ConstantFolder`, `invocation_counts`
* [ast-models.md](ast-models.md) — `CobolDataItem` / `PictureClause` /
  `OccursClause`, the inputs to flattening
* [parser.md](parser.md) — `fd_file_name` / `fd_clauses` / `fd_record_type`
* [`docs/fixture-bundle-schema.md`](../docs/fixture-bundle-schema.md) — the
  full `FixtureBundle` JSON shape
* [history](history/generators.md) — archived dated notes moved out of this
  topic on 2026-10-15
