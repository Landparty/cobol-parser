---
type: Module
title: Copybook Record Data
description: generators/data/ generation side — copybook parsing and flattening into FieldSpecs, value generation (PICTURE/USAGE/level-88/VALUE/semantic hints), byte widths and offsets (_storage.py, layout/offsets.py, data-items), record-image encoding (zoned, COMP-3, binary, float, edited, hex literals) and fixed vs. variable-length records (ODO trimming, FD RECORD VARYING, RDW).
tags: [generators, copybook, test-data, csv, record-image, encoding, layout-offsets, odo, recfm, values]
timestamp: 2026-10-15T00:00:00Z
---

# Copybook Record Data

The generation half of `cobolparser/generators/data/`, over the record layout
in `cobolparser/layout/` (field specs, offsets, copybook parsing, values,
options; the layout package sits below `analysis` so analyzers can read it
without importing `generators`): a copybook turns
into a flat `list[FieldSpec]` (one column per elementary field), `ValueFactory`
fills one row per record, and `GeneratedDataset` exports it as CSV or as a
real record image (fixed or variable length). CLI: `gen-data` and `data-items`
([cli.md](../cli.md)). Read [Flattening rules](#flattening-rules) and
[Value generation](#value-generation) first; the record-image sections build
on them. The inverse direction (decode, compare) is in
[decode-compare.md](decode-compare.md).

```python
from cobolparser.generators import CopybookDataGenerator, DataGeneratorOptions

generator = CopybookDataGenerator(DataGeneratorOptions(rows=100, seed=7))
dataset = generator.generate_from_file("CUSTOMER.cpy")
dataset.write_csv("customers.csv")
```

## Contents

- [Modules](#modules)
- [Public API](#public-api)
- [Parsing a copybook](#parsing-a-copybook)
- [Flattening rules](#flattening-rules)
- [Value generation](#value-generation)
- [Level-88 `VALUE ALL`](#level-88-value-all)
- [Byte widths and offsets](#byte-widths-and-offsets)
- [Record images](#record-images)
- [Fixed- and variable-length records](#fixed--and-variable-length-records)
- [Tests](#tests)
- [See also](#see-also)

## Modules

- **`options.py`** — `DataGeneratorOptions`: `rows`, `seed`, `include_filler`, `include_condition_filler`, `include_redefines`, `expand_occurs`, `max_occurs`, `respect_values`, `use_condition_values`, `semantic_hints`, `header_style`, `unique_fields`, `blank_rate`, `record_varying`; `for_record_image()` returns the byte-complete variant. A dataset generated with lossy options carries `record_image_gap = (covered, full)` (set by `CopybookDataGenerator.generate_from_record`), and its record-image methods (`to_records`, `write_records`, `to_hex_dump`, `record_length`) then emit `IncompleteRecordImageWarning` (a `UserWarning`, exported from `cobolparser.generators.data`); CSV output never warns.
- **`errors.py`** — `CopybookLayoutError` and `ProgramLayoutError` (both `ValueError` subclasses; `encoding.RecordEncodingError` subclasses `CopybookLayoutError`).
- **`layout.py`** — `FieldCategory`, `FieldSpec`, `flatten_record()`: the rules that turn a nested `CobolDataItem` tree into a flat list of columns. Also `expand_condition_values()`, `condition_ranges()`, `condition_values_exhaustive()`, `OdoControl`, `present_indexes()`, `VaryingLength`.
- **`cobolparser/layout/offsets.py`** — `LayoutItem`, `compute_record_layout()`, `compute_program_data_items()`: record-relative byte offsets/lengths for every data item, each group listed *after* its members (see below). See [Byte widths and offsets](#byte-widths-and-offsets).
- **`values.py`** — `ValueFactory`: synthetic values respecting PICTURE/USAGE/level-88 domain/VALUE/semantic hints. See [Value generation](#value-generation).
- **`storage.py`** — re-export shim for `cobolparser/_storage.py`, the single authority on how many bytes a data item occupies. See [Byte widths and offsets](#byte-widths-and-offsets).
- **`editing.py`** — numeric-edited pictures: `edit_numeric()` (the display form a `MOVE` leaves, `$1,234.56`), `deedit_numeric()` (its inverse), `deedit_float()`, `is_float_picture()`. Used by `encoding.py` and `decoding.py`.
- **`encoding.py`** — record-image encoding at fixed or variable record length. See [Record images](#record-images) and [Fixed- and variable-length records](#fixed--and-variable-length-records).
- **`views.py`** / **`decoding.py`** / **`compare.py`** — the read side; see [decode-compare.md](decode-compare.md).
- **`dataset.py`** — `GeneratedDataset`: rows, fields, seed; `to_csv()` / `write_csv()` / `to_dicts()`, the record-image trio `to_records()` / `write_records()` / `to_hex_dump()`, and the length quartet `record_length()` / `minimum_record_length()` / `record_lengths(opts)` / `is_variable_length`.
- **`copybook.py`** — `parse_copybook_records()` and `CopybookDataGenerator`; also `select_record()` and `fd_record_length()` (see [decode-compare.md](decode-compare.md)).
- **`program_layout.py`** / **`bundle.py`** — `ProgramLayoutIndex` and the `FixtureBundle` shapes (`BUNDLE_VERSION` 2, `SUPPORTED_BUNDLE_VERSIONS`, `expand_shared_fixtures`, re-exported from `generators.data`); see [fixtures.md](fixtures.md).
- **`__init__.py`** — eager package exports of the above (its own `__all__`).

`ValueFactory` + `flatten_record` work against any `CobolDataItem`, not just a
copybook-parsed one; the program-scoped fixture generator reuses them as is.

## Public API

```python
CopybookDataGenerator(options: DataGeneratorOptions | None)
    .generate_from_file(path, *, record=None, copybook_paths=None) -> GeneratedDataset
    .generate_from_source(src, *, filename=..., record=None,
                          copybook_paths=None)  -> GeneratedDataset
    .generate_from_record(item: CobolDataItem)  -> GeneratedDataset

parse_copybook_records(source, *, filename=..., copybook_paths=None,
                       warnings=None)           -> list[CobolDataItem]
flatten_record(record, options=None)            -> list[FieldSpec]

GeneratedDataset:  .record_name .fields .rows .seed .header
                   .varying (VaryingLength | None)
                   .declared_lengths (list[int] | None)
                   .caveats (list[str])
                   .lrecl (int | None — FD LRECL padding, see decode-compare.md)
                   .to_csv(*, line_terminator="\n")
                   .write_csv(path, *, line_terminator="\n")
                   .to_dicts() .to_dict()
                   .record_length()           # max / fixed-length LRECL
                   .minimum_record_length()   # every ODO table at its minimum
                   .record_lengths(opts=None) -> list[int]   # one per row
                   .is_variable_length        # bool: any ODO table at all
                   .to_records(opts=None) -> bytes
                   .write_records(path, opts=None)
                   .to_hex_dump(opts=None) -> str
EncodingOptions:   .charset (Charset.ASCII|EBCDIC)
                   .endian (Endian.AUTO|BIG|LITTLE|NATIVE)
                   .record_separator (bytes)
                   .record_format (RecordFormat.FIXED|VARIABLE
                                   |VARIABLE_BARE|AUTO)
                   .space .resolved_endian
                   .resolved_format(specs, *, varying=False)
RecordFormat:      StrEnum — fixed | variable | variable-bare | auto
                   .is_variable
encode_rdw(body_length) -> bytes        # RDW_SIZE == 4, MAX_VARIABLE_RECORD
encode_record(specs, row, opts, *, data_length=None, pad_to=None)
record_length(specs) / minimum_record_length(specs)
row_record_length(specs, row, opts=None, *, data_length=None, pad_to=None)
present_indexes(specs, row) -> list[int]
occurrence_count(control, cells) -> int
unresolved_odo_counters(specs) -> list[str]
RecordEncodingError(CopybookLayoutError)
FieldSpec:         .name .path .column .level .picture .usage .category
                   .size .integer_digits .decimal_digits .is_signed
                   .value_clause .condition_values .subscripts .redefines
                   .is_filler .sign_clause .synchronized .blank_when_zero
                   .justified .occurs_depending_on
                   .odo_controls .odo_counter_bounds
                   .total_digits .scaling_leading (read straight off the
                       item's own PictureClause at construction)
                   .decimal_point_is_comma .literal_bytes
                   .qualified_name .storage_size .character_positions
                   .scaling_positions .stored_digits .to_dict()
OdoControl:        .depending_on .subscript_index .min_times .max_times
                   .qualifiers
VaryingLength:     .minimum .maximum .depending_on .per_record
                   .from_fd_clauses(clauses, *, record_size)
                   .file_range(minimum, maximum, *, record_size)
                   .build(minimum, maximum, depending_on, record_size)
DataGeneratorOptions:
                   .record_varying ((min, max) | None) — for a copybook
                   with no FD to read the range from
FieldCategory:     StrEnum — alphanumeric | alphabetic | national | numeric
                   | numeric-edited | alphanumeric-edited | float
CopybookLayoutError(ValueError)
```

All importable from `cobolparser.generators.data`; everything except
`encode_record`, `occurrence_count` and `unresolved_odo_counters` is also
re-exported (lazily) from `cobolparser.generators`.

**P-scaling has one canonical parse.** `FieldSpec.scaling_positions` (signed
`P` count: positive trailing, negative leading, zero otherwise) and
`.stored_digits` (digit positions actually stored, `P`s excluded) compute from
`total_digits`/`scaling_leading`, which `flatten_record`'s `_flatten_into`
copies straight off the item's `PictureClause` (the same
`picture.total_digits` `layout_offsets.py` reads). Never re-derive them with a
second regex over the raw picture text; `PictureClause._parse_scaled_pattern`
already decides it while building the AST. See
[ast-models.md](../ast-models.md)'s `scaling_leading` note and
[analysis.md](../analysis.md)'s MoveTypeChecker section (whose
`_is_non_integer_picture` reads `decimal_digits` alone).

## Parsing a copybook

A copybook is a DATA DIVISION *fragment*, not a compilable program, so
`parse_copybook_records` wraps it in a minimal `IDENTIFICATION`/`DATA`/
`PROCEDURE` skeleton before calling `parse_cobol` in `COLLECT_ALL` recovery.
Two shapes are detected first:

* **Whole program** (`IDENTIFICATION DIVISION.` / `PROGRAM-ID.` present) —
  parsed as-is, no wrapper.

`wrap_copybook_fragment(source)` is the same wrapper for the tools that take
*any* source file -- `data-items` and the MCP server's parse (so
`record_layout` on a `.cpy`): it returns the wrapped text, or `None` when the
source names any division or a `PROGRAM-ID`. The fragment's line n is line
`n + WRAPPER_HEAD_LINES` of the result; the MCP workspace maps it back.
Without it both parsed a copybook as a program with no divisions: an empty
`items` list with exit 0, `found: false` (#536).
* **Fragment format** — decided by the one member detector copybook
  expansion uses, `detect_member_fixed_format`
  ([preprocessing.md](../preprocessing.md#fixed-format-detection)): every
  line votes, a valid column-7 indicator is fixed whatever columns 1-6 hold,
  a level number whose name starts in columns 1-7 decides free-form unless a
  line is fixed-only, a tie is fixed. A fixed-format fragment keeps its
  columns with columns 1-6 blanked (a change tag there would otherwise make
  the wrapped program look free-form to the parse); a free-form fragment is
  indented into Area B so the wrapper and the fragment agree. The layout
  package's own `_looks_fixed_format`, which counted every change-tagged
  sequence area (`CGOGP1`, `JR5295`) as a free-form vote and so shifted
  tagged fixed-format members seven columns (commented-out fields became
  junk fields, record sizes changed), was deleted on 2026-11-11.

**`COPY` inside the layout** (#592) — a copybook nesting another (`COPY
INNER.` inside the 01), or a whole program whose FD record is `COPY CUSTREC.`.
With `copybook_paths` the (wrapped) text goes through
`parse_cobol_with_expansion(..., skip_missing_copybooks=True)`, the way
`parse` and `gen-fixtures` expand; a circular COPY (any `PreprocessingError`)
is a `CopybookLayoutError`. A COPY left unexpanded — no paths, or its member
not found there — is blanked by the parser with a "COPY X was not expanded"
warning; `parse_copybook_records` appends each one to the caller's
`warnings` list, `generate_from_source` prepends them to
`GeneratedDataset.caveats`, and `RecordDecoder` keeps them as
`layout_warnings`. Invariant: never drop that warning. The hole makes the
record short, so decode frames every record wrongly and gen-data writes
records of the wrong length, and nothing else says why. The CLI
(`gen-data`, `decode`, `compare`, all with `--copybook-path` and
`project.copybook_path`) prints each one as `warning:` on stderr.

Record roots are the **top-level** data items (`_top_level_items` excludes
anything nested under another item) at level 01/77. A copybook containing
only subordinate items (level 02-49, no 01 — a real idiom for copybooks
meant to be `COPY`d *inside* an existing record, e.g. NIST `K101A.CPY`)
gets a **synthesised** `<STEM>-RECORD` root rather than being rejected.
Anything else — procedure text, `SELECT` clauses, an empty file — raises
`CopybookLayoutError`. A member holding PROCEDURE DIVISION code is caught
before it is wrapped (`procedure_code_start`: the first code line, after
comments, listing directives, `COPY` / `REPLACE` and `EXEC ... END-EXEC`, is
a paragraph or section header or a statement verb): wrapped as data,
`MOVE 8 TO RETURN-CODE` became a level-08 item with no PICTURE and the member
a zero-byte record with a "no PICTURE" warning. `wrap_copybook_fragment`
returns `None` for one, so data-items treats it as a program too.

## Flattening rules

| Construct | Default behaviour |
|-----------|------------------|
| Group item | Not a column; descended through |
| `OCCURS n` | One column per occurrence, `NAME(1)`, `NAME(2)`, … |
| `OCCURS … DEPENDING ON` | Expanded to the **maximum** bound |
| `REDEFINES` | **Excluded** — aliases bytes another column already covers |
| `FILLER` | **Excluded** — names nothing a consumer can address (a FILLER owning a level-88 is kept under `include_condition_filler`, see [fixtures.md](fixtures.md)) |
| Level 66 / 88 | Not storage; 88 VALUEs feed the parent's value domain |
| `COMP-1`/`COMP-2` | No picture → `FieldCategory.FLOAT` |
| Group `USAGE` / `SIGN` | Inherited by every subordinate elementary item with no clause of its own (IBM rule), resolved **in the parser** (`parsers/divisions/data.py` `propagate_group_usage_and_sign`) so `layout.py`, `layout_offsets.py` and `calculate_size` all see it. `CobolDataItem.usage_explicit` marks an entry's own USAGE; an explicit child wins for itself and below. A numeric-only group usage (COMP-3, BINARY, ...) is not pushed onto a non-numeric PICTURE; SIGN only lands on signed numeric items |
| `BLANK WHEN ZERO` | Carried as `FieldSpec.blank_when_zero`; the encoder writes a zero value as all spaces (charset's space), the decoder reads an all-space field as 0 with no error. Not for a VALUE-clause cell (see below) |

`include_redefines` / `include_filler` / `expand_occurs` / `max_occurs`
override the first four. Occurrence expansion is additionally subject to a
hard ceiling, `_MAX_OCCURS_HARD_CAP = 10_000` in `layout/fields.py`
— applied on top of (never widened by) a caller's own `max_occurs`, so a
pathological `OCCURS 5000000 TIMES` in the source cannot materialize
millions of `FieldSpec`s. A second ceiling bounds nested tables
(#376): `_MAX_EXPANDED_OCCURRENCES = 100_000` FieldSpecs per table
across *all* its enclosing tables -- `_flatten_into` carries
`occurs_product` down and `_occurrence_cap(product, weight)` cuts a table to
what the outer ones leave, divided by the elementary items one occurrence
holds (`_occurrence_weight`, each counted once) (`OCCURS 99999999` around
`OCCURS 9999` is 10,000 x 10, not 10,000 x 9,999; `OCCURS 10` around
`OCCURS 2200` of a 47-field group is 10 x 212, not the million FieldSpecs a
per-item count allowed). The weight applies only inside another table: an
outermost table answers to the per-table cap alone, so a single-level
`OCCURS 4000` of 30 fields still expands whole and its record image keeps the
length data-items reports. `occurs_expansion_caveats(record, opts)` walks the
declarations (never the expansion) and names every table either ceiling
cuts; a cut the caller asked for with `max_occurs` is not reported. It feeds
`GeneratedDataset.caveats` (gen-data `warning:` lines),
`ProgramLayoutIndex.unresolved` (so gen-fixtures' `bundle.unresolved`) and
`RecordViews.caveats` (decode, `--list-views`). Field lineage builds its own
byte map from the declared counts (`_PLACEMENT_CAP`), so a cut does not
change its answers. `gen-data --max-occurs` and `gen-fixtures --max-occurs`
both expose the caller-facing cap; the hard ceilings are internal.

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
   interval from the low bound** — a descending `VALUE 4 THRU 2` yields 2, 3
   and 4 (iterating from the written start would drop the low endpoint). A
   non-numeric range (`VALUE 'AA' THRU 'ZZ'`) contributes only its endpoints.

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

**Exact numbers, never float.** `_format_number` (and
`_fit_domain_value`/`render()`'s parse) is Decimal throughout: float64 rounds
any value past ~16 significant digits, so a solver-picked `PIC 9(18)` witness
would render one-off (`...678` → `...680`) and its fixture could never take
the branch it targets. `_format_number` and the P-scaled draw run under the
module's `_EXACT` 100-digit Decimal context (the default 28 digits rounds
29-31 digit fields and VALUE / level-88 literals that wide). A freely drawn
number is built exactly too (see #285): the whole part is an exact `randint`;
the fraction is exactly one `random()` draw (so the RNG stream, and every
later field in the record, is the same as a float build would consume), taken
through its repr up to 15 places and as its exact binary value beyond
(`_FLOAT_FRACTION_DIGITS`). Pinned by
`tests/regression/test_bug_review_2026_08_12.py::TestWideNumericPrecision`.

**`USAGE INDEX`/`POINTER`** short-circuit to `"0"` *without drawing from the
RNG*: they are storage, not data, and reach the factory PICTURE-less, where
the numeric path's 9-digit default would emit a random number that looks like
data. Not drawing keeps the RNG stream of every other field unchanged.

**FILLER draws nothing either** (`values._filler_without_content`): a FILLER
with no VALUE, or a figurative fill (`SPACES`, `LOW-VALUES`, ...), returns
`""` before any draw (`blank_rate` included) -- the record-image encoder
writes its fill whatever the cell holds. A FILLER that owns level-88s is
generated, but from a side stream seeded by `(seed state, row, column)`, and
`encode_field` now writes its cell. Because `for_record_image()` always adds
FILLER while the CSV defaults leave it out, a draw per FILLER used to shift
every later value: the same seed gave different values in the CSV and the
record image (405 of 906 copybooks in one checkout). Only a caller's own
`--max-occurs` cap (which the record image lifts) still changes the stream.

**PICTURE-less elementary items** that no usage sizes (`05 JUNK.` with no
children, usually a misread line) are 0 bytes, `ALPHANUMERIC`, like
`data-items` sizes them; the 9-digit fallback of `_digit_counts` stays only
for `PICTURELESS_USAGES` (`_sized_by_usage`). `pictureless_field_caveats()`
names them in gen-data's `caveats` and decode's, and
`flag_record_layout` (`_flag_pictureless_elementary`) in `data-items`'
`unresolved`. Before 2026-11-11 gen-data / decode sized them 9 bytes.

**Default record:** with no `--record`, gen-data and decode use
`first_generatable_record(records, options)` -- the first 01 that flattens
to at least one field -- not the first 01 outright (an all-FILLER header
failed with "no generatable fields" though later 01s qualified). With none
generatable, gen-data names the records it tried and decode falls back to
the first 01; a named record with no field lists the ones that have some.

`COMP-1`/`COMP-2` do not go through `_format_number` at all — they carry no
PICTURE to fit. `_float_value` draws one uniform over ±10,000 and hands it to
`_render_float(value, single=...)`, which quantises through binary32 for a
COMP-1 and renders to the 7 / 15 significant digits `decoding._decode_float`
uses, so the CSV cell is exactly what the record image gives back (see
[decode-compare.md](decode-compare.md)). A *declared* float value (VALUE
clause, level-88, a solver witness via `render()`) takes the same route from
`_fit_domain_value`, with `quantize=False` so `VALUE 2.5E-07` is not rounded
to the 4-decimal grid. The layout's `integer_digits=9, decimal_digits=0`,
unsigned shape for a float is a placeholder, never a domain: sent through
`_format_number` it wrote `VALUE -2.5E-02` as 0 and `-1.5` as 2 (#551).

`_format_number`'s `allow_random_sign` guards a subtle trap: a signed field
negates a freshly generated magnitude ~25 % of the time so negatives get
exercised, but values the copybook *declared* (levels 1-2 above) must be
formatted with `allow_random_sign=False` — otherwise `88 ST-LOW VALUE 5` on a
`PIC S9(3)` field emits `-5`, a value the copybook never permits. Pinned by
`test_declared_domain_values_are_never_randomly_negated`.

**Literal text.** `_literals.py`'s `quote_literal()` re-emits a decoded
literal doubling each embedded `"`; its inverse `unquote_literal()` strips the
delimiters *and* collapses the doubled delimiter. Every consumer reading a
re-emitted literal back must use it — `layout/fields.py`
(`_strip_literal_quotes`, VALUE clauses), `analysis/constraints.py`
(`_strip_quotes`, branch witnesses), `analysis/const_fold.py` (MOVE sources)
— or `VALUE "A""B"` generates `A""B`. Pinned by
`tests/regression/test_doubled_quote_literal_values.py`.
`_strip_literal_quotes` also decodes a typed literal through
`_literals.typed_literal_content()`: the VALUE clause keeps `X"4142"` as
written, and gen-data renders it `AB`. Latin-1 code points, so an EBCDIC
record image re-encodes the characters, not the original bytes (hex literals
in a record image are handled separately, see [Record images](#record-images);
also [lexer.md](../lexer.md) "Literal round trip").

**Group VALUE.** A VALUE on a group (`05 HDR VALUE 'HDR0001'`, `05 NUMS
VALUE ZEROES`) is carried down by `_flatten_into` / `_apply_group_value`: the
literal is laid over the group's fields by byte offset (space-padded past
its end, repeated for `ALL`) and each field gets its slice as its own
`value_clause` (a hex literal's slice stays `X'..'`); a figurative is given
to every field as is. Only one-byte-per-character DISPLAY fields take a text
slice -- COMP / COMP-3 / national fields keep being generated, a figurative
excepted. A numeric DISPLAY field reads its slice as digits at its own scale
(`'0001'` over `9(2)V99` is 00.01); a slice that is not all digits, or a
P-scaled picture, leaves that field generated. A field with its own VALUE keeps it; `respect_values=False` still
ignores all of it. Before #552 the group's bytes were random.

**Signedness.** `PictureClause.is_signed` only reports an explicit `S`, so
`_is_signed()` additionally treats a numeric-edited picture carrying `+`,
`-`, `CR`, or `DB` as signed — `PIC -ZZ,ZZ9.99` is the canonical signed
display field and would otherwise never generate a negative.

**Edited pictures** contribute their *logical* numeric value to a CSV, not the
edited display form: a CSV is consumed by tooling that wants the value, and
the edit mask is a presentation concern. Likewise `COMP-3` carries the decimal
value, not packed bytes. In a *record image* an edited field holds the edited
bytes a `MOVE` leaves (never the logical value left-justified, e.g.
`9516.07 ` for `PIC $$,$$9.99`, which no COBOL program writes). `editing.py`
implements IBM's editing rules — Z/`*` suppression, floating `$`/`+`/`-`
strings, fixed `+`/`-`/`CR`/`DB`/`$`, `B`/`0`/`/`/`,` insertion, the
all-`Z`/all-`*` zero case — and is tested against two tables in
`tests/unit/generators/data/test_editing.py`: cases checked byte for byte
against GnuCOBOL 3, and the IBM LRM's own editing examples
(`$B*,***,***.**BBDB` holding -12345.67 is `$ ***12,345.67  DB`). The all-`*`
zero case fills *every* position but the decimal point with `*`, a fixed sign
or `CR`/`DB` included (`***.**CR` edits zero as `***.****`, as `***.**-` edits
it `***.***`); before 2026-11 `CR`/`DB` were left as two spaces there. A floating `+`/`-` can land on an insertion position inside its
own string (`PIC +++,+++` edits -514 as `   -514`, the sign where the comma
would be); `deedit_numeric` reads the sign there too.
`deedit_numeric` accepts only text that *is* an edited form: after reading
digits and sign it re-edits the value and requires the result to equal the
input, so a stray byte in an insertion, fixed-sign, `CR`/`DB` or `$`
position, or a space in a `9` position, is an error rather than read past
(`'9999999'` in `ZZ9.99-` once decoded cleanly as 999.99, #587).

**Line terminator.** `to_csv()` and `write_csv()` share
`_DEFAULT_LINE_TERMINATOR = "\n"`, deliberately *not* the `csv` module's
RFC 4180 `"\r\n"`. Both must agree or the byte-identical guarantee breaks
across output paths — `gen-data -o out.csv` (`write_csv`) would write
different bytes than `gen-data > out.csv` (`to_csv`) for the same seed.
Either method accepts `line_terminator="\r\n"` for strict RFC 4180 output. A
test comparing *parsed* rows cannot catch a mismatch — the regression test
compares raw bytes.

**Determinism.** `random.Random(seed)`. The same seed and copybook always
produce byte-identical CSV. When `seed is None` one is drawn and recorded on
`GeneratedDataset.seed`, so an interesting unseeded run is reproducible
after the fact (surfaced by `gen-data --describe`).

**`unique_fields`** retries a field up to 32 times for a distinct value, then
falls back to a deterministic counter — a narrow field (`PIC 9`, ten possible
values) asked for 40 unique rows must terminate, not spin. The counter
(`ValueFactory._sequential`) steps past values already used and builds text
from the right (`ST0`, `ST1` ... `10` on a `PIC X(3)`), so truncation never
cuts the counter off -- cutting it made every fallback value of a narrow
VALUE / level-88 field identical (#526). When the counter runs out of values
the PICTURE holds, the repeat is kept and the column lands in
`ValueFactory.duplicate_columns`; `CopybookDataGenerator` turns that, and a
`unique_fields` name matching no generated column, into dataset `caveats`
(printed by `gen-data` as `warning:` lines on stderr, exit 0).

## Level-88 `VALUE ALL`

The parser stores a level-88 `VALUE ALL 'X'` as the one value `ALL "X"`
(`ALL SPACES` for a figurative operand). `layout.all_literal_operand()`
recognises the form and `layout.fill_all_literal(value, width)` fills it
(`ALL "AB"` at width 5 is `ABABA`). `expand_condition_values(raw, width)`
expands it with a width -- `layout._condition_values` passes the item's
PICTURE size (so `FieldSpec.condition_values` holds `XXX`, which the value
factory and the solver's enum domain use as is) and `ProgramLayoutIndex`
passes the owner field's `spec.size`; without a width (`data-items`) it is
kept as written. `condition_values_exhaustive` counts `ALL "X"` as one exact
value and `ALL <figurative>` as non-exhaustive.

## Byte widths and offsets

**`_storage.py` is the single authority on how many bytes a data item
occupies**: `storage_size()`, `binary_byte_length()`, `packed_byte_length()`,
and the `USAGE` frozensets everything else classifies against. `layout.py`,
`layout_offsets.py`, `encoding.py` and
`models.data_items.CobolDataItem.calculate_size` all defer to it, which is
what stops a record image's field widths drifting from the offsets
`data-items` reports. It lives at `cobolparser/_storage.py` (beside
`_errors.py`, zero internal dependencies) because the models need it too and
sit below `cobolparser.layout`. Two cases any
copy of the arithmetic must handle: `USAGE INDEX` has no PICTURE and must not
be sized as zero bytes (that collapses every later offset), and a DISPLAY
item with `SIGN IS SEPARATE` has a byte its PICTURE's character count does
not include.

**`compute_record_layout()`** (`layout_offsets.py`) lays out one record in
isolation and returns `LayoutItem`s:

* **Slots.** Sibling layout (record root and every group) runs through
  `_layout_siblings()`: a "slot" is a contiguous run of `[base item,
  redefine 1, redefine 2, ...]` (COBOL requires a REDEFINES entry to
  immediately follow what it redefines). Every slot member starts at the same
  offset, the slot's footprint (`slot_footprint`) is the max footprint across
  its members, and the running offset advances past the slot once.
  `_walk_redefines_chain()` resolves a possibly multi-hop chain (A redefines
  B redefines C) within one sibling list, cycle-guarded.
* **Childless root.** A bare 77-level or elementary 01-level record reports
  its own elementary byte length rather than 0.
* **OCCURS multiplies footprint, never `byte_length`.** `_layout_item()`'s
  `one_occurrence_length` is exactly one occurrence's size and is what
  `LayoutItem.byte_length` stores (`CobolDataItem.calculate_size()` never
  applies a *group* item's own OCCURS multiplier, so it cannot be used
  here). `_layout_siblings()` separately computes each member's
  `member_footprint` = `one_occurrence_length * (occurs.max_times or
  occurs.min_times or 1)` and folds *that* into `slot_footprint`/`total`/
  `offset`, so a later sibling's offset advances past every occurrence.
* **An ODO table reserves its maximum** (see #247), the storage IBM
  Enterprise COBOL allocates and the width `encoding.py` writes, so an
  enclosing group's and the record's `byte_length` equal
  `GeneratedDataset.record_length()` and never fall below the table's own
  minimum. `occurs.depending_on` flips `is_ambiguous = True` for every
  sibling laid out after it: those offsets move with the counter.
* **Ambiguity propagates across nesting levels.** `_layout_siblings()` /
  `_layout_item()` return `(footprint, trailing_ambiguous)`: a group whose
  nested sibling list ended ambiguous makes *its* later siblings in the parent
  list ambiguous too, through any depth (elementary items report `False`;
  their own `occurs.depending_on` is handled by the caller's check).
* `_occurs_dict()` populates `occurs` (`{"min": ..., "max": ...}` or `None`)
  on every non-level-88 `LayoutItem`.
* **Level-88s under the record root.** The root's own `LayoutItem` is built on
  a separate path (`out.insert(0, LayoutItem(...))`), so it mirrors
  `_layout_item()`'s condition-children loop itself (offset 0,
  `byte_length=record_length`); skip it and `01 WS-EOF-FLAG PIC X. 88 WS-EOF
  VALUE "Y".`, the most common flag idiom, loses its 88. Both 88 paths go
  through `_condition_item()`.
* **Level 77 is never a child.** The hierarchy builder nests purely by level
  number, so a `77` declared right after an `01` whose deepest item is a `05`
  becomes that `05`'s AST child. `_direct_data_children()` excludes level-77
  items at every call site; counting one would misclassify the `05` as a group
  and discard its own PIC/byte_length.

**Item order.** `compute_record_layout()` lists the record root first (then
its own level-88s), and below it each group *after* its members, with the
group's level-88s right after the group: `REC, REC.HDR.H1, REC.HDR.H2,
REC.HDR, ...`. It is load-bearing: `FieldFlowAnalyzer._index_items` finds an
entry's enclosing group as the next entry of the parent's name, which keeps
same-named groups (FILLER) apart. A consumer that wants source order sorts
by declaration (the MCP server's `_declarations` does).

**`compute_program_data_items(ast) -> {"items": [...], "unresolved": [...]}`**
is the program-wide entry point behind `data-items` (JSON-ready; `unresolved`
always present). It walks every DATA DIVISION section (FILE, WORKING-STORAGE,
LOCAL-STORAGE, LINKAGE), calls `compute_record_layout()` on each top-level
(01/77) record, and adds what one record in isolation cannot know:

* **Top-level REDEFINES.** A top-level 01 that redefines another top-level 01
  in the same section: a `siblings_by_name` dict per section and
  `_walk_redefines_chain()` overwrite that record's root `redefines_chain` in
  place (`compute_record_layout()` itself always reports `[]` for the root).
  Byte offsets are unaffected: each top-level record is record-relative and
  starts at 0.
* **Misnested level-77s.** `_find_misnested_level_77_items()` walks each
  top-level record's raw AST subtree, recovers every 77 the
  `_direct_data_children()` guard hid, and lays each out as its own record
  (resolving its `redefines_chain` against the section's top-level siblings).
  Without it a 77 that was its misnested parent's *only* child vanishes from
  the output entirely and the parent reads as a PIC-less elementary item.
* **Level-66 RENAMES** (#563). After a section's records are laid out,
  `renames_layout(node, placed)` places each `RenamesItem` in the last record
  declared before it: `byte_offset` = its first operand's, `byte_length` = to
  the end of its THRU operand (`OF` qualifiers must name ancestors). The entry
  is `level` 66, `qualified_name` `REC.NAME`, `parent_qualified_name` the
  record; a single-operand RENAMES takes the renamed item's PICTURE / USAGE /
  group-ness, a THRU range is a DISPLAY group; `offset_ambiguous` if either
  end is. One it cannot place (an operand not found or ambiguous, an inverted
  range) gets an `unresolved` line instead. Lineage's `_record_blocks` still
  drops level-66 entries. Pinned by
  `tests/regression/test_issue_563_renames_data_items.py`.
* **`SYNCHRONIZED`** is not modelled (offsets are unaligned throughout), so
  the first `SYNCHRONIZED` binary/float/pointer/index item that is off its
  boundary (2/4/8 bytes, its own width) or inside an `OCCURS` table, and
  every item after it in source order, get `offset_ambiguous: True`, with one
  `unresolved` line naming it. An aligned SYNC item, or SYNC on
  DISPLAY/packed, changes nothing. These flags (and the partial level-88
  lines) come from `flag_record_layout(record, layout)`, which
  `compute_program_data_items` runs per record (and the `OCCURS UNBOUNDED`
  line, below); `compute_record_layout` alone
  does **not** flag -- a caller laying out one record must run it too (MCP
  `record_layout` does, #488).
* **`OCCURS UNBOUNDED`** has no maximum, so the table is sized at its
  minimum (`occurs` `{"min": 1, "max": 1}` -- the shape is kept for the
  backend and the extension) and `flag_record_layout` adds one `unresolved`
  line per such table saying its `occurs.max` and every enclosing group's
  `byte_length` are a lower bound (`LayoutItem.occurs_unbounded`, not
  serialized; #311). gen-data likewise writes the minimum.
* **Level-88 `THRU` ranges: `condition_ranges`** (see #361).
  `condition_values` comes from `expand_condition_values()`, which lists a
  range only in part: an integer range up to `_MAX_RANGE_EXPANSION` (`VALUE 1
  THRU 99999` gives `1`..`65`), any other range just its two endpoints. Every
  item therefore also carries `condition_ranges: [{"from", "to"}]` — each
  range as written, quotes stripped, nothing expanded
  (`layout.condition_ranges()`; empty for a non-88 and an 88 with no range) —
  and an `unresolved` line per level-88 whose list is partial
  (`"<qname>: condition_values lists only part of VALUE 1 THRU 99999;
  condition_ranges holds the full range"`), judged by
  `condition_values_exhaustive()` against the parent's decimal digits, so
  `VALUE 1 THRU 2` on `PIC 9V99` is flagged too, and so is every range under
  a non-numeric parent (a group, or `PIC XX` with `'01' THRU '12'`: the parser
  drops the quotes, so the range *looks* integer, but `PIC XX` admits `'1A'`
  and never holds `'1'`). A typed endpoint is kept as written (`X'00'`, not a
  NUL byte). Not caught: `LOW-VALUE THRU HIGH-VALUE`, whose `THRU` the DATA
  DIVISION parser drops (#468). Only a range triggers it: `VALUE SPACES` is
  listed as its word, which is the value. `LayoutItem.condition_values_complete`
  carries the verdict and is not serialized.

**Test-fixture gotcha.** Fixed-format COBOL only reads columns 8-72; a
one-line `OCCURS 1 TO 10 TIMES DEPENDING ON WS-COUNT.` indented far enough
pushes `ON WS-COUNT.` past column 72, where the lexer drops it silently and
the ODO parses as a fixed `OCCURS 10`. Wrap `DEPENDING ON <var>` onto a
continuation line in test fixtures.

## Record images

Everything above works in **display form** — a CSV cell holds `72436.21`
whether the field behind it is `PIC 9(7)V99` or `PIC S9(7)V99 COMP-3`. That
is the right currency for a CSV, and for mockymock (whose splicer emits `MOVE
<literal> TO <field>` and lets the compiler pack it). It is the wrong currency
for a **record image**: the actual bytes a program would `READ`, or a dataset
uploaded to z/OS. `GeneratedDataset.to_records()` / `.write_records()` /
`.to_hex_dump()` produce that image (`data/encoding.py`); `gen-data --format
record|hex` is the CLI ([cli.md](../cli.md)).

**The layout has to change first.** The CSV-shaped defaults are deliberately
lossy — FILLER skipped, OCCURS capped — and both would put a *hole* in a
record image that still looked plausible. `DataGeneratorOptions
.for_record_image()` returns the byte-complete variant (FILLER in, REDEFINES
out, every occurrence expanded, no cap); the CLI applies it for
`--format record|hex` and prints a note to stderr so the overridden flags
don't look ignored. FILLER encodes as spaces/zeros regardless of its
generated cell — an empty cell falls through every encoder as exactly that,
so no encoder needs to know about FILLER. A FILLER with a `VALUE` keeps that
value, and one whose `VALUE` is `SPACES` / `LOW-VALUES` / `HIGH-VALUES` /
`NULL` (optionally after `ALL`) is filled with that byte (`_filler_fill()`):
the value generator reads those figuratives as "no meaningful content" and
draws random text for the cell, which must not reach the record (the gap
`05 FILLER PIC X(5) VALUE SPACES` between two report columns would read
`QH7KZ`).

**Encodings, all verified against GnuCOBOL** by compiling a probe program
and reading back `LENGTH OF` plus the raw group bytes (the probe and its
output are reproduced in `tests/unit/generators/data/test_encoding.py`'s
module docstring — that suite is the regression guard):

| Storage | Bytes |
|---------|-------|
| DISPLAY alphanumeric / alphanumeric-edited | left-justified, space-padded, truncated; charset's space byte. Under `JUSTIFIED RIGHT` (`FieldSpec.justified`) the mirror image: right-aligned behind leading spaces (`    AB`), an oversized value losing its *leftmost* characters; the decoder strips that leading pad. Hex literals: see below |
| DISPLAY numeric-edited | the edited form a `MOVE` leaves (`$1,234.56`, `- 12.34`, `012CR`, `12/34/56`) — `editing.py`'s `edit_numeric()`; the decoder de-edits it back with `deedit_numeric()`. A `SPECIAL-NAMES. CURRENCY SIGN` symbol is edited like `$` and shows its whole currency string in that one position (`FieldSpec.currency_signs`, read off `PictureClause.currency_signs`, passed as `currency_signs=` to both functions: `PIC ###,##9.99` writes `#17,611.57`; with `'CHF '` and symbol `F`, `PIC FFFF,FF9.99` writes ` CHF 17,611.57` in 14 bytes; a value suppressed to spaces gets the extra positions as spaces, #491). A picture `editing.py` does not model (a `$` mixed with a declared symbol, two declared symbols) keeps the CSV text as is, and `encoding_caveats()` names it ("numeric-edited picture not modelled"). Under `DECIMAL-POINT IS COMMA` (`FieldSpec.decimal_point_is_comma`, read off the `PictureClause`) both functions take `decimal_point_is_comma=True` and exchange `,`/`.` in the picture and the edited text: `Z.ZZ9,99` writes `1.234,56` |
| DISPLAY numeric (zoned) | one byte per digit; sign as an overpunch, or a real `+`/`-` byte under `SIGN IS SEPARATE` |
| `COMP-3` / `PACKED-DECIMAL` | two BCD nibbles per byte, sign nibble `C`/`D` signed, `F` unsigned |
| `COMP` / `COMP-4` / `BINARY` | two's complement, **always big-endian** |
| `COMP-5` | two's complement, **host byte order** — that is what "native binary" means |
| `COMP-1` / `COMP-2` | IEEE 754 binary32/binary64, byte order as `COMP-5` |
| `INDEX` / `POINTER` | binary zeros — an occurrence number and an address are not record content |
| `FLOAT-SHORT` / `FLOAT-LONG` | as `COMP-1` / `COMP-2` (#524) |
| `FLOAT-EXTENDED`, `BINARY-CHAR` / `-SHORT` / `-LONG` / `-DOUBLE` | sized exactly (`FIXED_SIZE_USAGES`: 16 / 1 / 2 / 4 / 8) but **not modelled**: binary zeros, named in an `encoding_caveats()` line (#524) |
| an unknown USAGE word (`USAGE IS COMPX`) | binary zeros of the DISPLAY/PICTURE width, with an `encoding_caveats()` line saying the length is unknown; `data-items` reports it `unresolved` and marks it and every later offset `offset_ambiguous` (`layout_offsets._flag_unknown_usage`) |
| `PIC N` / `USAGE NATIONAL` | **not modelled as UTF-16**: single-byte text in the record charset, space-padded to the (correct, 2-bytes-per-position) width; `encoding_caveats()` says so. A numeric national field (`PIC 9(5) USAGE NATIONAL`, 10 bytes) goes the same way — `encode_field`/`decode_field` route `usage == "NATIONAL"` to text before the zoned branch |
| `PIC U(n)` (UTF-8, fixed character-length) | **not modelled as UTF-8**: n single-byte characters (`FieldSpec.utf8_characters`) space-padded to the 4 x n bytes the field reserves; `encoding_caveats()` names the fields. `PIC U BYTE-LENGTH n` is an n-byte text field (#554) |
| `PIC G` / `USAGE DISPLAY-1` (DBCS) | **not modelled as double-byte EBCDIC**: single-byte text in the record charset, space-padded to the 2-bytes-per-position width, decoded back the same way; `encoding_caveats()` (and so every `DecodeResult`) names the fields in a separate DBCS caveat, and a `PIC N USAGE DISPLAY-1` field is reported there rather than under the national/UTF-16 one (#321) |

**A VALUE-clause cell ignores JUSTIFIED and BLANK WHEN ZERO** (#558):
initialisation by VALUE is not affected by either clause, so `PIC X(5) JUST
VALUE 'AB'` is `AB   ` and `PIC 9(3) BLANK WHEN ZERO VALUE 0` is `000`.
`ValueFactory._declared_value` marks the cell (`layout.InitialValueCell`, or
`initial_value = True` on a hex literal's `LiteralCell`) and `encode_field`
checks `is_initial_value()`. Every other cell -- generated, or a level-88
value, which stands for a SET / MOVE -- is still justified and blanked.
`hex_literal_cell_for` accepts either alignment for that reason.

**Hex literals are written as their own bytes** (see #319): `VALUE X'C1C2'`,
or a level-88 `X'FF'` drawn as the witness, is padded/truncated like text but
never re-encoded through the charset (that would write `3f 3f` in ASCII and
`65 62` in EBCDIC). The cell is a `LiteralCell` (a `str` whose text is the
bytes as Latin-1, carrying them as `.data`), made by `ValueFactory` from the
VALUE clause and by `expand_condition_values` for a level-88; the encoder
writes `.data` and never looks a cell up by its text, so an ordinary value
with the same text (`VALUE SPACE` next to `88 VALUE X'20'`, `'AB'` next to
`X'4142'`, a random `A` next to `X'41'`) stays charset-encoded, and a mixed
concatenation `VALUE 'AB' & X'0102'` (the lexer spells it `"AB" & X'0102'`,
#479) is a `LiteralCell` with `text_runs` -- the basic parts' ranges, which
`encoding.literal_cell_bytes()` writes in the record charset (`C1 C2 01 02`
in EBCDIC) while the hex parts keep their bytes
(`layout.concatenated_literal_cell()`; the decoder's `literal_bytes` key is
that cell, so it round-trips in both charsets), and
`'AB'`/`X'4142'` are both drawn. `FieldSpec.literal_bytes` (stand-in text to
bytes) is the decoder's map: a field holding exactly a hex literal's padded
bytes decodes to its cell (`X'FF'` as `ÿ`, not EBCDIC `\x9f`), so
`decode(encode(row)) == row` in both charsets, unless one of the field's
ordinary declared values encodes to the same bytes (`'AB'` and `X'C1C2'`
under EBCDIC), when the charset reading wins
(`encoding.hex_literal_cell_for`). `VALUE ALL X'FF'` fills the field with the
literal's bytes repeated (`layout.value_clause_hex_bytes`,
`ValueFactory._fill_all`); a plain text cell on that path would be
charset-encoded.

**Overflow is not uniform across those rows, deliberately.** The zoned and
packed encoders run their magnitude through `_digits_string`, which
high-order-truncates to the PICTURE's digit count the way a COBOL numeric
MOVE does, so neither can overflow. Excess *decimal* places are truncated
too, never rounded (`_scaled_integer` and `edit_numeric` both use
`ROUND_DOWN`): `9.999` into `9V99` stores `999` (rounding half-even would give
`1000`, which the high-order truncation turns into `000`). The encoder,
`edit_numeric` and the decoder's `_render_number` all scale through an
**exact** `decimal.Context` rather than the default one, whose 28 significant
digits round a 31-digit `ARITH(EXTEND)` field (`S9(29)V99 COMP-3` holding
`...456789.01` would decode as `...456790.00`). The binary encoder has no such
step: a value that does not fit the field's *byte width* has no
representation at all, so it raises `RecordEncodingError` rather than
silently reshaping the bytes. Nothing this package generates can reach it —
`ValueFactory` respects the PICTURE and a `VALUE` clause is clamped to it —
but a caller handing `encode_record()` a row of its own can.

**Overpunch conventions follow the charset**, not a separate knob: EBCDIC
zones the sign into the `C`/`D` nibbles (`-12345` → `F1F2F3F4D5`), ASCII sets
`0x40` in the signed digit's zone (`-12345` → `1234u`), which is what
GnuCOBOL writes *and* reads. The third convention in the wild — EBCDIC signs
transcoded to ASCII as `{ABC`/`}JKL` — is deliberately **not** written:
there is no compiler available to verify an implementation of it against,
and both real destinations (a z/OS dataset, the local GnuCOBOL runtime) are
already covered. (The decoder does *read* it.)

**Byte order defaults to `Endian.AUTO`**, which reads the charset as a
statement of intent: an EBCDIC record is bound for z/OS and gets big-endian;
an ASCII one is bound for the local runtime and gets host order. `NATIVE`
forces host order, `BIG`/`LITTLE` pin it. `resolved_endian` is always one of
`BIG`/`LITTLE`, and every output path reports which was used rather than
leaving the reader to infer it.

**Known limits, reported not hidden** (`encoding_caveats(specs)` returns
them; the CLI prints them to stderr and the hex dump inlines them in its
header):

* **`SYNCHRONIZED` is not modelled.** Slack bytes before an aligned `COMP`
  item would shift every following offset, and this package's offset model
  (`layout_offsets`, which backs `data-items`) is unaligned throughout. Two
  contradictory offset models in one repo is worse than one documented gap;
  `data-items` marks the affected offsets ambiguous (see
  [Byte widths and offsets](#byte-widths-and-offsets)).
* **`COMP-1`/`COMP-2` are IEEE 754, not z/OS hexadecimal floating point.**
  Matches GnuCOBOL and Enterprise COBOL under `FLOAT(IEEE)`.
* **`OCCURS ... DEPENDING ON` is written at its maximum** under
  `RecordFormat.FIXED` — which is not a gap but what RECFM=F means. Under
  the variable formats the caveat is not emitted at all, because the
  occurrences past the counter's own value are genuinely dropped.

One more thing worth knowing before diffing generated bytes against a
compiler-written record: GnuCOBOL converts a decimal `COMP-2` literal through
its own decimal intermediate and can land **one ULP** off the correctly
rounded double. `-8840.0215` is a worked example — the encoder here writes
the true nearest double, and is the more accurate of the two.

**`--format hex`** is the form that survives being opened in a text editor,
which is exactly where a copybook is being looked at when someone wants to
know what its `COMP-3` field really holds. One line per field: offset,
length, name, PICTURE, USAGE, display value, and the bytes. A layout mistake
shows up as a shifted offset rather than as unexplained garbage further down.
Under a variable-length format the dump also carries the RDW on a row of its
own (`(RDW)`, offset `000000`, length 4), each record's own length in its
`--- record N of M: L bytes ---` header, and a `record length: MIN to MAX`
range instead of a single number. The RDW row is not decoration: without it
every field offset in the dump would sit four bytes below where it really
is in the file.

## Fixed- and variable-length records

A copybook says how long a record *can* be. It does not say whether the file
holding it is **RECFM=F/FB** (every record the layout's full length) or
**RECFM=V/VB** (each record only as long as that record's own data makes it).
`RecordFormat` lets both be generated.

**Two independent mechanisms make a record vary**, and a program may use
either:

1. **`OCCURS ... DEPENDING ON`** inside the record — a table whose occurrence
   count is carried by a counter field. The record's length follows from the
   layout, so it can be derived. Handled by `layout.OdoControl` /
   `present_indexes()`, below.
2. **`FD ... RECORD VARYING FROM min TO max DEPENDING ON item`** on the file —
   the record layout is an ordinary fixed one and *nothing in it* says how
   long any given record is. The length travels in the RDW; the program sets
   the `DEPENDING ON` item before a WRITE and reads it back after a READ.
   Handled by `layout.VaryingLength`, below.

The second is the one an ODO walk cannot see, and it is common: a flat
`01 EMP-RECORD80` under `RECORD VARYING FROM 47 TO 80` is the canonical
shape.

`EncodingOptions.record_format` picks between them; `gen-data
--record-format fixed|variable|variable-bare|auto` is the CLI on top of it.

| Value | Records | Framing |
|-------|---------|---------|
| `fixed` (default) | full length: every occurrence written, no length cut | none |
| `variable` | only the occurrences the row's counter names, cut to its declared length | 4-byte RDW per record |
| `variable-bare` | same trimmed records | none — the consumer already knows where each ends |
| `auto` | `variable` if the record varies by *either* mechanism, else `fixed` | follows the resolved value |

**`fixed` is the default, deliberately.** A record that cannot vary encodes
to byte-identical output under every format bar the RDW, so the default only
matters for the records that *can* — and there, silently changing what
`--format record` has always written would be worse than making the caller
ask for it. `auto` is the opt-in to "do what the source implies". The one
exception: `--record-varying` is itself a statement that records are not
fixed, so passing it alone reaches `auto` rather than writing the
fixed-length file the caller just said this is not; an explicit
`--record-format fixed` still wins over it.

**The RDW** (`encode_rdw`) is `LL LL 00 00`: a big-endian 16-bit total length
**including the four RDW bytes**, then two reserved zero bytes. Big-endian
regardless of `--endian` and of the charset — it is physical file structure
written by the access method, not data written by the program. A record
whose total would exceed `MAX_VARIABLE_RECORD` (0xFFFF) raises
`RecordEncodingError` rather than truncating the length silently: a record
that long needs RECFM=VS (spanned), which is not generated.

### ODO trimming

Three pieces, none of which re-flattens the layout:

1. **`layout.OdoControl`** on every `FieldSpec` inside an ODO table
   (`spec.odo_controls`, outermost first): the counter's name, *which
   subscript position* it governs, and the `OCCURS min TO max` bounds. The
   subscript position is the tuple length at the moment the table is entered,
   so nested ODO tables each contribute one control and the general case
   falls out for free. `max_times` is the number of occurrences actually
   flattened, not the declared maximum — `max_occurs` and the hard cap can
   both stop the walk short, and a counter allowed to name occurrence 50 of a
   table flattened to 10 would describe bytes no `FieldSpec` covers.
2. **`spec.odo_counter_bounds`** on the *counter* field, stamped by a
   post-pass (`_link_odo_counters`) because a counter is normally declared
   *before* the table that depends on it — its spec already exists by the
   time the `DEPENDING ON` phrase is seen. `ValueFactory` draws the counter
   from those bounds rather than from the PICTURE's range, so a `PIC 9(4)`
   counter for a table of at most 50 never generates 8 731. Drawing across
   the range (rather than generating freely and clamping) is also what makes
   a variable-length file actually *vary*: clamping would pin nearly every
   row to the maximum. A declared `VALUE`/level-88 still wins when it names a
   count the table can hold, and is overridden when it does not.
3. **`layout.present_indexes(specs, row)`** — the positions whose bytes that
   row's record contains, in order. The counter governing a given occurrence
   is resolved by *position*, not just by name: it is the counter spec
   sharing that field's enclosing subscripts. That is what makes IBM's
   **complex ODO** (a `DEPENDING ON` table nested inside an ordinary
   `OCCURS`, so each outer occurrence carries its own count) come out right
   rather than trimming every outer occurrence to the last one's count.
   A counter declared *outside* the enclosing fixed table has no subscripts,
   so the exact `(name, outer)` key misses and the counter is looked up by
   name; `decoding._present` mirrors that fallback (otherwise the decoder
   reads the table at full length and mis-aligns the record).
   Dropping an occurrence and concatenating what remains is exactly what a
   real variable-length record looks like: anything declared *after* the
   table shifts up into the space the absent occurrences would have taken,
   which falls out of preserving order rather than needing its own
   arithmetic. A layout with no ODO table short-circuits to "every
   position", so fixed-length copybooks pay nothing for any of this.

**Lengths.** `record_length(specs)` is every occurrence present — the
fixed-length answer *and* the LRECL a RECFM=V dataset is defined with.
`minimum_record_length(specs)` is the same with every table at its declared
minimum, and `row_record_length(specs, row, opts)` is one row's, computed from
the layout rather than by encoding it. `GeneratedDataset` exposes all three
plus `record_lengths(opts)` and `is_variable_length`. `gen-data --format
record` prints the resulting range to stderr, because raw bytes have no
header to state their own LRECL in and a record image whose length nobody
states is a file nobody can read back.

**The counter may live outside the record** — in WORKING-STORAGE, or in a
record this copybook does not define. Nothing generated can set it, so its
table is written at full length and `unresolved_odo_counters(specs)` names
it in the caveats. Same for a counter cell left blank by `blank_rate` or
holding a non-numeric value: reserving the whole table is the one answer that
never claims bytes the layout does not describe.

### FD `RECORD VARYING` (`layout.VaryingLength`)

```cobol
FD  EMPFILE
    RECORD VARYING FROM 47 TO 80 CHARACTERS
           DEPENDING ON EMPREC-LEN
    RECORDING MODE IS V.
01  EMP-RECORD80.
    05  EMP-ID       PIC X(6).
    ...
    05  EMP-COMMENT  PIC X(33).
```

Nothing here is subordinate to a counter — `EMPREC-LEN` is a WORKING-STORAGE
item, not part of the record — so `odo_controls` is empty for every field and
`present_indexes()` keeps them all. What varies is how many of the record's
bytes each *record* carries.

* **Where the range comes from.** `VaryingLength.from_fd_clauses()` reads the
  FD's `record` clause, which `data_file_description.py` already parses into
  `{varying, min, max, depending_on}` and attaches to the 01 as `fd_clauses`
  metadata. So `gen-data` on a **whole program** picks it up with no flag. A
  bare **copybook** has no FD; `DataGeneratorOptions.record_varying` (CLI
  `--record-varying MIN:MAX`) supplies it, and overrides the FD when both
  exist. `FROM` itself is optional (`VARYING IN SIZE 47 TO 80` has a
  minimum of 47, see #402); with neither FROM nor an integer before TO,
  the minimum is None.
* **Only `DEPENDING ON` draws lengths** (see #320). `RECORD CONTAINS 47 TO
  80` (format 2) and `RECORD VARYING` without `DEPENDING ON` make the *file*
  variable, but IBM COBOL writes each record at the length of the 01 it was
  written from, never cut mid-field. `from_fd_clauses()` routes those to
  `VaryingLength.file_range()`: the range is kept unclamped with
  `per_record=False` (so `AUTO` still resolves to variable and LRECL is still
  the declared max), `_draw_lengths()` draws nothing, and each record is the
  layout's full length. A layout outside the range is a caveat, not a cut.
  `GeneratedDataset._resolved_options()` settles `AUTO` against the dataset,
  since the encoder only sees a range through a drawn `data_length`. An
  explicit `record_varying` still opts in to drawn lengths.
* **`maximum` is clamped to the record's own byte length.** An FD promising
  more than its 01 can hold cannot be honoured by padding — those bytes were
  never declared — so the range is cut to what exists. **Never silently**
  (see #274): `VaryingLength.build(..., caveats=)` appends a sentence whenever
  it clamps a bound, or ignores the range outright because nothing of it is
  left (`40:50` on a 28-byte record, or equal bounds) — the record then stays
  fixed-length. The sentence lands on `GeneratedDataset.caveats`, is printed
  as a `* caveat:` line in `to_hex_dump()`'s header (`hex_dump(...,
  extra_caveats=)`), and as `warning:` on stderr by `gen-data` in every
  output format.
* **The length is drawn per row at *generation* time**, uniformly across the
  range, from the same seeded RNG the values came from, and stored on
  `GeneratedDataset.declared_lengths`. Drawing it there rather than in the
  encoder is what keeps `encode_record` a pure function and makes a seed
  reproduce record *lengths* as exactly as it reproduces their contents. The
  draws happen *after* the rows, so a record with no range draws nothing and
  its output is byte-identical to a layout that never had the feature.
* **`encode_record(..., data_length=N)`** cuts the body to N bytes — mid-field
  if that is where the length falls, which is exactly what a program reading
  `EMP-RECORD80(1:EMPREC-LEN)` sees. Passing it also settles
  `RecordFormat.AUTO`, since a declared length is by definition a record that
  varies. `--format hex` shows the fields past the cut as
  `(past record length)` rather than dropping them, so the cut is visible;
  a field the cut falls *inside* shows `(cut N/M bytes)` in the VALUE column
  rather than the whole generated value (most of which is not in the file).
* **The `DEPENDING ON` item is filled in when it *is* in the record.** Usually
  it isn't. When a copybook does put it there, leaving the generated value
  would contradict the record's own length.
* **Decoding agrees.** `RecordDecoder.from_record()` finds the range the same
  way (explicit `options.record_varying` first, else `fd_clauses`) and keeps
  it as `RecordDecoder.varying`; both `resolved_format()` calls in
  `decoding.py` pass `varying=`, so `decode --record-format auto` reads the
  RDW-framed file `gen-data --record-format auto` wrote. Pinned by
  `test_variable_length.py::TestFdRecordVarying::test_decode_auto_reads_what_gen_data_auto_wrote`.
* **Both mechanisms at once**: the table decides, the FD range is not applied
  on top of it, and a caveat says so. Enforced in *three* places, because a
  caveat that the code contradicts is worse than no caveat: the generator
  draws no length for such a record (so `declared_lengths` is `None` and every
  downstream surface agrees for free), `_effective_data_length()` drops a
  `data_length` a direct caller passes anyway, and `minimum_record_length()`
  only prefers the FD floor when a length was actually drawn.

## Tests

* `tests/unit/test_copybook_data_generator.py` — flattening, categories,
  value constraints, option validation, dataset surface
* `tests/unit/cli/test_gen_data_cli.py` — `gen-data` flags, JSON modes, errors;
  `TestRecordImageFormats` covers `--format record|hex`, `--charset`,
  `--record-separator`, and that CSV output is unchanged by any of them;
  `TestRecordFormatFlag` covers `--record-format`, walking the written
  file's RDW chain and asserting it lands exactly on EOF
* `tests/unit/generators/data/test_storage.py` — the byte-width table, incl.
  the two traps (`USAGE INDEX` sized as zero, `SIGN IS SEPARATE`
  under-reported by one)
* `tests/unit/generators/data/test_encoding.py` — every storage class's
  bytes, record assembly at predicted offsets, the caveat list, and the hex
  dump. **Its module docstring holds the GnuCOBOL probe program and its raw
  output** — the ground truth every expected byte string here comes from.
  Re-run that probe before changing an encoding
* `tests/unit/generators/data/test_variable_length.py` — the whole
  fixed-vs-variable story in one file, both mechanisms:
  `TestFdRecordVarying` works the mainframestechhelp.com `EMPVL` example end
  to end (FD clause picked up with no flag, lengths inside the declared
  range, the cut falling mid-field, the RDW carrying it);
  `TestExplicitVaryingRange` covers `record_varying`; plus
  `OdoControl`/`odo_counter_bounds`
  linking, `present_indexes` trimming (including the field *after* the table
  shifting up), counter generation staying inside the table's bounds, RDW
  framing, the length trio, format-dependent caveats, and the invariant that
  ties the two readings together — a full-count variable record is
  byte-for-byte the fixed record
* `tests/integration/test_copybook_csv_generation.py` — parametrized over the
  sample copybooks and the NIST `.CPY` corpus; asserts no copybook crashes the
  generator and that generated cells are assignable to their fields
* `tests/contracts/test_copybook_data_generator_contract.py` — exported names,
  signatures, `to_dict()` key sets, reproducibility guarantee
* `tests/unit/generators/data/test_layout_offsets.py::TestComputeProgramDataItems`
  — `compute_program_data_items()` over a two-record WORKING-STORAGE
  section: both records' items appear in `output["items"]`, `unresolved`
  key present, each record's fields are independently 0-based
* `tests/integration/test_data_item_layout_corpus.py` — `TestRedefinesFixture`
  pins the top-level-REDEFINES handling against
  `tests/samples/redefines_test.cbl`'s real fan-out shape (`WS-REDEF-1`
  and `WS-REDEF-2` both redefine `WS-BASE-AREA` directly, not a 3-way
  chain — each resolves to `redefines_chain == ["WS-BASE-AREA"]`, all
  three at `byte_offset == 0`); `TestShamriceCorpusDoesNotRaise` sweeps
  the same `examples/cobol/shamrice/*.cbl` corpus
  `test_program_layout_corpus.py` uses, purely for "doesn't crash"
  coverage — that corpus was not authored with REDEFINES-chain
  assertions in mind
* `tests/unit/generators/data/test_layout.py` / `test_values.py` — flattening
  internals and `ValueFactory`
* `tests/unit/generators/data/test_editing.py` — numeric-edited
  `edit_numeric`/`deedit_numeric`: a table checked against GnuCOBOL 3, a
  table of the IBM LRM "PICTURE clause editing" worked examples (simple,
  special, fixed and floating insertion, zero suppression), round-trips of
  both, the all-`*` zero case, and record images through the public
  generator/decoder API (signed vs. unsigned value generation)

## See also

* [generators.md](../generators.md) — the generators routing page
* [decode-compare.md](decode-compare.md) — record views, decoding, compare,
  `select_record()`, FD LRECL framing
* [fixtures.md](fixtures.md) — `ProgramLayoutIndex` and the fixture
  generator, which reuse `flatten_record` / `ValueFactory`
* [ast-models.md](../ast-models.md) — `CobolDataItem` / `PictureClause` /
  `OccursClause` / `ConditionNameItem`, the inputs to flattening
* [parser.md](../parser.md) — group USAGE/SIGN propagation, `fd_clauses`
* [cli.md](../cli.md) — `gen-data`, `data-items`
* [history](../history/generators.md) — archived dated notes (layout_offsets
  task log, encoding and value-generation fix write-ups)
