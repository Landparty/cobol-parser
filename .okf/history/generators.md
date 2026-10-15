---
type: History
title: Generators history
description: Archived dated notes moved out of generators.md; not loaded by default.
tags: [history, generators]
timestamp: 2026-10-15T00:00:00Z
---

# Generators history

An archive of the dated notes (fix write-ups, audit findings, bug-hunt rounds,
review passes, the layout_offsets task log) moved verbatim out of
[generators.md](../generators.md) on 2026-10-15, when that file was split into
[generators/](../generators/flowchart.md) topic files. The topic files state the
current behaviour and the invariants these notes established; read this only
for why something was done or when. Sections keep their original headings and
are ordered newest first by their latest date; within a section, fragments
keep source order and are separated by `* * *`. Relative link paths inside the
fragments were re-pointed from `.okf/` to this folder; in-page anchors were not.

## Record images (`data/encoding.py` + `data/storage.py`)

*(2026-09-27 to 2026-10-15.)*

so no encoder needs to know about FILLER. A FILLER with a `VALUE` keeps
that value, and one whose `VALUE` is `SPACES` / `LOW-VALUES` /
`HIGH-VALUES` / `NULL` (optionally after `ALL`) is filled with that byte
(`_filler_fill()`, 2026-10-12). The value generator reads those
figuratives as "no meaningful content" and draws random text for the cell,
which the encoder used to write into the record -- so the report-line gap
`05 FILLER PIC X(5) VALUE SPACES` between two columns came out as `QH7KZ`.

* * *

| Storage | Bytes |
|---------|-------|
| DISPLAY alphanumeric / alphanumeric-edited | left-justified, space-padded, truncated; charset's space byte. Under `JUSTIFIED RIGHT` (`FieldSpec.justified`, 2026-09-28) the mirror image: right-aligned behind leading spaces, an oversized value losing its *leftmost* characters; the decoder strips that leading pad (it used to write `AB    ` where the MOVE leaves `    AB`). A hex literal (`VALUE X'C1C2'`, or a level-88 `X'FF'` drawn as the witness) is written as its own bytes, padded/truncated the same way, in either charset (issue #319; re-encoding the text used to write `3f 3f` in ASCII and `65 62` in EBCDIC). The cell is a `LiteralCell` (a `str` whose text is the bytes as Latin-1, carrying them as `.data`), made by `ValueFactory` from the VALUE clause and by `expand_condition_values` for a level-88; the encoder writes `.data` and never looks a cell up by its text, so an ordinary value with the same text (`VALUE SPACE` next to `88 VALUE X'20'`, `'AB'` next to `X'4142'`, a random `A` next to `X'41'`) stays charset-encoded, and `'AB'`/`X'4142'` are both drawn. `FieldSpec.literal_bytes` (stand-in text to bytes) is the decoder's map: a field holding exactly a hex literal's padded bytes decodes to its cell (`X'FF'` as `ÿ`, not EBCDIC `\x9f`), so `decode(encode(row)) == row` in both charsets, unless one of the field's ordinary declared values encodes to the same bytes (`'AB'` and `X'C1C2'` under EBCDIC), when the charset reading wins (`encoding.hex_literal_cell_for`). `VALUE ALL X'FF'` fills the field with the literal's bytes repeated (`layout.value_clause_hex_bytes`, `ValueFactory._fill_all`; 2026-10-15 bug hunt -- the ALL path built a plain text cell, so `ALL X'FF'` was written `3f 3f` in ASCII and `df df` in EBCDIC) |
| DISPLAY numeric-edited | the edited form a `MOVE` leaves (`$1,234.56`, `- 12.34`, `012CR`, `12/34/56`) -- `editing.py`'s `edit_numeric()`; the decoder de-edits it back to the logical value with `deedit_numeric()`. A picture using a symbol `editing.py` does not model (`P`, a non-default currency sign) keeps the CSV text as is. Under `DECIMAL-POINT IS COMMA` (`FieldSpec.decimal_point_is_comma`, read off the `PictureClause`) both functions take `decimal_point_is_comma=True` and exchange `,`/`.` in the picture and the edited text: `Z.ZZ9,99` writes `1.234,56` (2026-09-28) |

* * *

| `PIC N` / `USAGE NATIONAL` | **not modelled as UTF-16**: single-byte text in the record charset, space-padded to the (correct, 2-bytes-per-position) width; `encoding_caveats()` says so. A numeric national field (`PIC 9(5) USAGE NATIONAL`, 10 bytes since 2026-09-28) goes the same way -- `encode_field`/`decode_field` route `usage == "NATIONAL"` to text before the zoned branch |

* * *

**Overflow is not uniform across those rows, deliberately.** The zoned and
packed encoders run their magnitude through `_digits_string`, which
high-order-truncates to the PICTURE's digit count the way a COBOL numeric
MOVE does, so neither can overflow. Excess *decimal* places are truncated
too, never rounded (`_scaled_integer` and `edit_numeric` both use
`ROUND_DOWN`, 2026-09-28): `9.999` into `9V99` stores `999`. It used to round
half-even to `1000`, which the high-order truncation then turned into `000`.
The encoder, `edit_numeric` and the decoder's `_render_number` all scale
through an **exact** `decimal.Context` rather than the default one, whose 28
significant digits silently rounded a 31-digit `ARITH(EXTEND)` field
(`S9(29)V99 COMP-3` holding `...456789.01` decoded as `...456790.00`). The binary encoder has no such step: a
value that does not fit the field's *byte width* has no representation at
all, so it raises `RecordEncodingError` rather than silently reshaping the
bytes. Nothing this package generates can reach it — `ValueFactory` respects
the PICTURE and a `VALUE` clause is clamped to it — but a caller handing
`encode_record()` a row of its own can. (A `# pragma: no cover` on that
branch used to claim `_digits_string` guarded it; it never ran there.)

* * *

* **`SYNCHRONIZED` is not modelled.** Slack bytes before an aligned `COMP`
  item would shift every following offset, and this package's offset model
  (`layout_offsets.compute_record_layout`, which backs `data-items`) is
  unaligned throughout. Two contradictory offset models in one repo is worse
  than one documented gap. `compute_program_data_items` (2026-09-27) no longer
  reports those unaligned offsets as exact: the first `SYNCHRONIZED`
  binary/float/pointer/index item that is off its boundary (2/4/8 bytes, its
  own width) or inside an `OCCURS` table, and every item after it in source
  order, get `offset_ambiguous: True`, with one `unresolved` line naming it.
  An aligned SYNC item, or SYNC on DISPLAY/packed, changes nothing.

## Internal Implementation Modules: `layout_offsets.py`, `values.py`, `storage.py`

*(Task log for layout_offsets (Tasks 2-8, final-review fixes), #247 (2026-10-04), #361 (2026-10-14), #285, 2026-09-05.)*

- **`layout_offsets.py`** — `LayoutItem` dataclass, `compute_record_layout()` function; byte-offset and byte-length computation for individual records, used by data-item hover details and offset-based lookups (Task 2-6: initial implementation + nested group recursion + REDEFINES-chain slot sharing + OCCURS footprint multiplication + cross-level OCCURS DEPENDING ON ambiguity propagation). Sibling layout (record root and every group) runs through a shared `_layout_siblings()` helper: a "slot" is a contiguous run of `[base item, redefine 1, redefine 2, ...]` — COBOL requires a REDEFINES entry to immediately follow what it redefines — every slot member starts at the same offset, the slot's footprint (`slot_footprint`) is the max footprint across its members, and the running offset advances past the slot once. `_walk_redefines_chain()` resolves a possibly multi-hop REDEFINES chain (A redefines B redefines C) within one sibling list, cycle-guarded. A childless record root (bare 77-level or elementary 01-level) is still special-cased to report its own elementary byte length rather than 0. **Task 5: OCCURS multiplies footprint, never `byte_length`.** `_layout_item()`'s return value (`one_occurrence_length`) is always exactly one occurrence's size and is what gets stored as the emitted `LayoutItem.byte_length` — this fixes a real gap in `CobolDataItem.calculate_size()`, which never applies a *group* item's own OCCURS multiplier. `_layout_siblings()` separately computes each member's `member_footprint` (`one_occurrence_length * (occurs.max_times or occurs.min_times or 1)` for every OCCURS, fixed or `DEPENDING ON` — an ODO table reserves its **maximum**, the storage IBM Enterprise COBOL allocates and the width `encoding.py` writes, so an enclosing group's and the record's `byte_length` equal `GeneratedDataset.record_length()`; until issue #247 (2026-10-04) an ODO table reserved one occurrence only, so a group holding `OCCURS 2 TO 5` reported less than its own minimum. `occurs.depending_on` is also what flips `is_ambiguous = True` for every sibling laid out after it: those offsets move with the counter, the maximum is only the allocation) and folds *that* into `slot_footprint`/`total`/`offset`, so a later sibling's offset correctly advances past every occurrence. `_occurs_dict()` populates the `occurs` field (`{"min": ..., "max": ...}` or `None`) on every non-level-88 `LayoutItem`, elementary or group.

  **Task 8: `compute_program_data_items(ast: CobolProgram) -> dict[str, Any]`** —
  the program-wide entry point, returning `{"items": [...], "unresolved":
  [...]}` (JSON-ready; `unresolved` always present -- it names SYNCHRONIZED
  slack and partial level-88 value lists, see below). Walks every DATA
  DIVISION section (FILE, WORKING-STORAGE, LOCAL-STORAGE, LINKAGE) and
  calls `compute_record_layout()` on each section's top-level (01/77)
  records. Also closes a gap `compute_record_layout()` leaves by design:
  that function lays out one record in total isolation (no knowledge of
  its section siblings), so its record-root `LayoutItem` always hardcodes
  `redefines_chain=[]` — correct for a record with no REDEFINES, wrong for
  a top-level 01 that redefines a *different* top-level 01 in the same
  section (nested REDEFINES, inside a group, was already handled — see
  Task 4 above — via that group's own `_layout_siblings()` sibling list).
  `compute_program_data_items` builds a `siblings_by_name` dict from each
  section's top-level records and, for any record with `.redefines` set,
  reuses `_walk_redefines_chain()` (same helper `_layout_siblings()`
  already uses, generic over whatever sibling dict it's given) to
  overwrite that record's root `redefines_chain` in place before
  appending its flattened layout to the output. `compute_record_layout()`
  itself is untouched — same signature, same behavior, still used
  directly by Tasks 2-7's unit tests with no siblings context. Byte
  offsets are unaffected either way: each top-level record is
  independently record-relative and correctly starts at byte 0 whether or
  not it redefines a section sibling.

  **Level-88 `THRU` ranges: `condition_ranges` (issue #361, 2026-10-14).**
  `condition_values` comes from `expand_condition_values()`, which lists a
  range only in part: an integer range up to `_MAX_RANGE_EXPANSION` (`VALUE
  1 THRU 99999` gave `1`..`65`), any other range just its two endpoints
  (`'A' THRU 'Z'` gave `A`, `Z`). Read as the whole domain, that told a hover
  66 or `M` were not values of the condition. Every item now also carries
  `condition_ranges: [{"from", "to"}]` -- each range as written, quotes
  stripped, nothing expanded (`layout.condition_ranges()`; empty for a
  non-88 and an 88 with no range) -- and `compute_program_data_items` adds
  one `unresolved` line per level-88 whose list is partial
  (`"<qname>: condition_values lists only part of VALUE 1 THRU 99999;
  condition_ranges holds the full range"`), judged by
  `condition_values_exhaustive()` against the parent's decimal digits, so
  `VALUE 1 THRU 2` on `PIC 9V99` is flagged too, and so is every range
  under a non-numeric parent (a group, or `PIC XX` with `'01' THRU '12'`:
  the parser drops the quotes, so the range *looks* integer, but `PIC XX`
  admits `'1A'` and never holds `'1'`). A typed endpoint is kept as written
  (`X'00'`, not a NUL byte). Not caught: `LOW-VALUE THRU HIGH-VALUE`, whose
  `THRU` the DATA DIVISION parser drops (issue #468). Only a range triggers it:
  `VALUE SPACES` is listed as its word, which is the value. `condition_values`
  itself is unchanged (additive change; consumers keep working).
  `LayoutItem.condition_values_complete` carries the verdict and is not
  serialized. Both 88 construction paths (nested and record-root) go through
  `_condition_item()` now.

  **Final-review fix: root-level level-88s were silently dropped.**
  `compute_record_layout()` builds the record's own root `LayoutItem` on
  a separate inline construction path (the `out.insert(0, LayoutItem(...))`
  above), which bypassed `_layout_item()`'s condition-children loop
  entirely — so a level-88 declared directly under a 01/77 record root
  with no intervening group level (COBOL's most common flag idiom, e.g.
  `01 WS-EOF-FLAG PIC X. 88 WS-EOF VALUE "Y".`) never made it into the
  output. A level-88 nested under a 05+ group always worked, since those
  go through `_layout_item()`. Fixed by mirroring `_layout_item()`'s
  condition-children loop for the root itself right after the root
  `LayoutItem` is inserted, reusing the root's own `byte_offset=0`,
  `byte_length=record_length`, and `offset_ambiguous=False`.

  **Final-review fix: a misnested level-77 could corrupt an unrelated
  preceding record's byte_length.** This is a pre-existing parser
  behavior, not a parser bug fix: the hierarchy builder nests items
  purely by level-number comparison, so a `77`-level item declared
  immediately after an `01` record (whose deepest preceding item is, say,
  a `05`) becomes that `05`'s AST *child* (77 > 05), not a section-level
  sibling. Since `_direct_data_children()` previously counted that
  misnested 77 as a real data child, `_layout_item()`'s `if
  data_children:` branch misclassified the `05` as a GROUP item and
  discarded its own elementary PIC/byte_length. Fixed with a guard in
  `_direct_data_children()` itself (not in `compute_program_data_items`):
  a level-77 item is, by COBOL's own level-number rules, never
  legitimately subordinate to anything, so it's excluded from every
  `_direct_data_children()` call site — the lower-risk fix location,
  since it doesn't require duplicating tree-walking logic in the
  program-wide entry point.

  **Follow-up fix: the excluded 77 was silently dropped when it was its
  misnested parent's *only* child.** The guard above stops corruption but
  doesn't put the 77 anywhere — when the parent had other real children
  (the `05 WS-A` case) that's invisible, but when the 77 was the
  misnested parent's *only* AST child (`01 WS-REC. 77 WS-CTR ...`, no
  intervening `05`), `_direct_data_children()` now returns empty for
  `WS-REC` too, so `compute_record_layout()` falls into its childless-root
  branch and treats `WS-REC` as if it were itself elementary with no
  PICTURE (`is_group=False, byte_length=0`) — and `WS-CTR` never appears
  anywhere in `compute_program_data_items()`'s output, `section.data_items`
  never having contained it to begin with. Fixed in
  `compute_program_data_items()` (not by touching the shared
  `_direct_data_children()` guard again): a new `_find_misnested_level_77_items()`
  helper walks each top-level record's *raw*, unfiltered AST subtree to
  recover every level-77 item hidden by the guard, and each one is
  re-rooted as its own independent record via `compute_record_layout()`
  — same as a genuine section-level 77 — including resolving its own
  `redefines_chain` against the section's top-level siblings, exactly
  like the top-level-record path just above it does. This recovers the
  77 in *both* shapes (only-child and has-siblings), not just the
  previously-unhandled one.

  **Task 6: ambiguity propagates across nesting levels, not just within one sibling list.** Task 5's `is_ambiguous` flag was local to each `_layout_siblings()` call — an OCCURS ... DEPENDING ON table nested *inside* a group only made that group's own children ambiguous; the group's own sibling in the *parent* list still got a concrete, wrong offset. `_layout_siblings()`/`_layout_item()` now both return `tuple[int, bool]` (`footprint, trailing_ambiguous`) instead of a bare `int`: a group's nested `_layout_siblings()` call reports whether *it* ended ambiguous, `_layout_item()` passes that straight through for group items (elementary items always report `False` here — their own direct `occurs.depending_on` is already handled by the caller's existing check), and the calling `_layout_siblings()` folds a `True` nested signal into its own `is_ambiguous`, exactly like a direct ODO child would. Propagates through arbitrarily many nesting levels for free (each level only needs its own direct child's signal) — confirmed with a two-level nesting test, not just by inspection. `compute_record_layout()`'s public contract (the `LayoutItem` list and every field on it) is unchanged; only the two private helpers' internal return shape changed. Root cause of the two brief-derived tests initially failing during development: unrelated to this propagation gap — fixed-format COBOL only recognizes columns 8-72 as the code area, and the brief's literal one-line `OCCURS 1 TO 10 TIMES DEPENDING ON WS-COUNT.` fixture at that indentation pushed `ON WS-COUNT.` past column 72, where the lexer silently drops it with no error, so the ODO parsed as a fixed `OCCURS 10` with `depending_on = None`. Test fixtures now wrap `DEPENDING ON <var>` onto a continuation line to stay inside the code area.
- **`values.py`** — `ValueFactory` class; generates synthetic values for a field, respecting PICTURE/USAGE/level-88 domain/VALUE/semantic hints. `USAGE INDEX`/`POINTER` short-circuit to `"0"` *without drawing from the RNG* — they are storage, not data, and reach the factory PICTURE-less, where they used to fall through to the numeric path's 9-digit default and emit a random number that looked like data. Not drawing is what keeps a copybook with no such field byte-identical for a given seed. A freely drawn number is built exactly, never through float (issue #285): `whole + random()` used to make a `PIC 9(18)` value a float64 and drop every digit past ~15, so most rows ended in `00`. The whole part is an exact `randint`; the fraction is still exactly one `random()` draw (so the RNG stream, and every later field in the record, is unchanged), taken through its repr up to 15 places and as its exact binary value beyond (`_FLOAT_FRACTION_DIGITS`). A field of 11 or fewer total digits is byte-identical for a seed; 12-15 digits can differ, rarely, in the last decimal place, where float was already rounding (0.01% of `9(9)V9(3)` rows, ~3.5% of `9(13)V99`); past 15 digits most rows change (~96% of `9(18)`). `_format_number` and the P-scaled draw run under the module's `_EXACT` 100-digit Decimal context: the default 28 digits rounded 29-31 digit fields, and VALUE / level-88 literals that wide, on the first `abs()` or subtraction.
- **`storage.py`** — a re-export shim (2026-09-05) for **`cobolparser/_storage.py`**, which the implementation moved to so `cobolparser.models.data_items.CobolDataItem.calculate_size` could defer to it as well: this package's `__init__` eagerly imports `program_layout`, which imports `cobolparser.models`, so a model importing this module directly would close an import cycle. `_storage.py` sits beside `_errors.py` and, like it, has zero internal dependencies. Every existing importer of `storage.py` is unchanged. It remains the package's single authority on **how many bytes a data item occupies**: `storage_size()`, `binary_byte_length()`, `packed_byte_length()`, and the `USAGE` frozensets everything else classifies against. Zero dependencies beyond the stdlib, deliberately — `layout.py`, `layout_offsets.py` and `encoding.py` all import it, which is what stops a record image's field widths from drifting apart from the offsets `data-items` reports. Two cases the older per-module copies of the arithmetic got wrong and this fixes for every caller at once: `USAGE INDEX` (no PICTURE, so it was sized as **zero bytes**, silently collapsing every offset after it) and a DISPLAY item with `SIGN IS SEPARATE` (a byte the PICTURE's character count does not include).

## Record views and decoding (`data/views.py` + `data/decoding.py`, 2026-09-07)

*(2026-09-07 to 2026-10-14.)*

| | |
|---|---|

* * *

| `RecordViews.overlays` | one `RecordView` per `REDEFINES` item anywhere in the tree, in source order. Since #296 (2026-10-13) each is the **whole record with that overlay swapped in** for the item it redefines (`layout.flatten_overlay_view(record, substitutions={id(redefined): overlay})`), plus every enclosing overlay for a nested one. So an overlay inside `OCCURS` is read at every occurrence (`T-ALT(1)`, `T-ALT(2)`), and `compare --view X --key K` works for a key outside the redefined area. A shorter overlay is padded with a `FILLER` so later fields keep their offsets. Fields outside the overlay keep the base view's column names (`_align_columns`). An overlay that covers a table's `DEPENDING ON` counter records it as a `HiddenCounter` (also returned by `flatten_overlay_view`), and `decode_record` reads the counter from those bytes when it reaches the overlay. Overlay views are `_LazyOverlayView`s, flattened on first read of `fields`, so a decode through one view does not pay for all of them. A lazy view still takes `RecordView`'s own fields as constructor arguments, so `dataclasses.replace()` works on it. `RecordDecoder._caveats` passes the hidden counters to `encoding_caveats` too, so a covered counter is not reported as missing from the record. `RecordView.offset` is where the overlay itself starts (first occurrence) and `overlay_length` its own span; the fields always start at 0 |

* * *

| `RecordView.offset_ambiguous` | base view: the record has an `OCCURS ... DEPENDING ON` table; overlay: one sits before or inside the overlay, so its static offset holds only for a full-length record (the decoder resolves offsets per record). Enclosing fixed `OCCURS` no longer sets it (#296). Set on the **base** view too as of 2026-09-07 — it used to default False there, so `--list-views` presented a maximum-length guess as a fact for the fields `data-items` reports as `byte_offset: null` |
| `RecordViews.framing_length` | the stride a fixed-length file is actually cut at: `max(base.length, end of every widening overlay view)` -- for `A X(4)` / `A-R REDEFINES A X(8)` / `B X(2)` that is 10, matching `data-items` (B at 8); it was 8 before #296, which decoded B as `''`. Equal to `base.length` for every conforming layout, and larger only for a `REDEFINES` wider than what it redefines — which COBOL forbids below level 01 but compilers accept, growing the record. `RecordDecoder` frames on this; framing on `base.length` shredded every record after the first. `to_dict()` reports **both** numbers (2026-09-07, Copilot review on #208: reporting only `record_length` left a consumer framing on a number the decoder does not use) |

* * *

**Fixed framing of a whole program is the FD's LRECL, not the chosen 01's
length** (#362, 2026-10-14). Every 01 under one FD shares the record area,
so a RECFM=F file of that FD holds LRECL-byte records whichever 01
`--record` picks. `copybook.fd_record_length(records, chosen, options)`
returns that LRECL -- the largest sibling 01's `framing_length`, or the FD's
fixed `RECORD CONTAINS n` when that is larger (a smaller one does not shrink
the area, so every 01 of one FD gets the same LRECL) -- or `None` when it is
not longer than `chosen` (no FD/SD, a bare copybook, or `chosen` is the
longest). `from_copybook_source()` uses it as the default `record_length`
(`--record-length` still overrides; `from_record()` alone has no siblings to
look at). `CopybookDataGenerator.generate_from_source()` stores the same
number as `GeneratedDataset.lrecl`, and under `RecordFormat.FIXED`
`to_records()` / `record_lengths()` / `to_hex_dump()` pad each record out to it
with the charset's space (`encode_record(..., pad_to=)`), the dump showing an
`(FD LRECL slack)` row -- so `gen-data --record HDR-REC --format record`
writes the file `decode --record HDR-REC` reads. Variable formats are not
padded. Before, a 9-byte header read off a 16-byte file shredded every
record after the first, and with an all-text layout and a file length
divisible by both sizes, silently.

* * *

| Storage | Read back as |
|---|---|

* * *

| zoned DISPLAY | one digit per byte, sign overpunched or `SIGN IS SEPARATE`. Under `SEPARATE` only the sign byte carries the sign and it must be `+` or `-`: every digit is unsigned, so a sign zone on one is an `error` (never a negation), and a blank sign byte is an `error` too (2026-10-14, #360: x'F1F2D34E' read `-123` clean, and x'F1F2F340' read `123` clean) |
| `COMP-3` | two BCD nibbles per byte, sign in the final low nibble. With an even digit count the first byte's high nibble is pad, not a digit: a non-zero pad is an `error` and is left out of the value (2026-09-28: it was read as a digit, so `S9(2)V99` x'12345C' decoded as `123.45`, more digits than the PICTURE holds) |

* * *

**Numbers render exactly as `ValueFactory._format_number` renders them** (no
leading zeros, the field's own `decimal_digits` places, a leading `-` only on
a non-zero negative) — `_render_number()` exists solely to keep that
equality, which is what makes `decode(encode(row)) == row` a property the
suite can assert rather than a hope. **Floats are held to the same equality**
by `values._render_float()`, which quantises a drawn value through the
field's own storage and renders it to the digit count the decoder uses. Two
things used to break it: a COMP-1 value drawn to four decimals over
±10,000 needs nine significant digits and binary32 holds about seven
(`-9419.8954` read back `-9419.896`), and the decoder's `%g` drops the
trailing zero `%.4f` had added to a COMP-2 (`-7960.5120` read back
`-7960.512`, roughly one row in ten). One column is still exempt **by
construction**: `FILLER` comes back empty because `encode_field()`
deliberately writes spaces there rather than the generated cell.

* * *

**Bad bytes are reported, not zeroed.** `DecodedField.error` names the
problem and the value is best-effort; `DecodedRecord.errors` and
`DecodeResult.error_count` roll them up. A copybook applied to the wrong file
shows up as a wall of these, which is the single most useful thing the
module can say (`test_the_wrong_copybook_shows_up_as_a_wall_of_errors`).

Invalid data that is still *readable* counts too (issue #248, 2026-10-04):

* an `OCCURS ... DEPENDING ON` counter outside its table's `min..max` is an
  error on the counter (`DEPENDING ON value 7 outside 2..5`); the table is
  still read at the clamped count (`_counter_value`), the best guess at where
  the following fields are;
* an RDW-framed record whose body holds bytes past the last field the base
  view reads gets a record-level error in `DecodedRecord.record_errors`
  (rolled into `errors`, `to_dict()["errors"]`, `error_count`, and a `!` line
  in the hex pane) -- previously those bytes vanished with `trailing == b""`;
* a `B`/`D` sign nibble on an **unsigned** packed field is an error and does
  not negate, mirroring the zoned decoder's sign-zone rule;
* a `COMP`/`COMP-4`/`BINARY` value with more digits than its PICTURE (65535
  in `PIC 9(4) COMP`) is a **caveat**, not an error: legal under
  `TRUNC(BIN)`, invalid under `TRUNC(STD)`, and the decoder has no TRUNC
  option. `COMP-5` is exempt (native binary, its whole width is legal).

* * *

* **`trim_tables` is decided by the record format, not by the counter.**
  Under `RecordFormat.FIXED` an ODO table reserves all of its occurrences
  whatever the counter says, so trimming would skip bytes that *are* in the
  record and mis-align every field after the table. `decode_bytes` resolves
  the format once from the base view and passes `trim_tables=fmt.is_variable`
  to `decode_record`. (This was a real bug caught by the round-trip test:
  fixed-format records decoded with trimming on produced silent garbage from
  the table onward.)

* * *

| Format | How the next record is found |
|---|---|
| `FIXED` | `record_length` override, else `base.length`. With a `record_separator` set, the separator is *checked*, not just skipped (#359, 2026-10-14): a record not followed by it (and not at end of data), or one with a separator inside non-binary bytes (`_separators_only_in_binary`, judged on the base view), gets a `record_errors` entry -- lines that are not LRECL bytes long used to decode silently misframed |
| `VARIABLE` | the 4-byte RDW; an RDW longer than the file raises `RecordDecodingError` rather than being guessed at |
| `VARIABLE_BARE` | the layout's own ODO counters — decoding consumes exactly what this record holds, so the next starts where this stopped. A tail shorter than the record its own counters describe is `trailing`, not one more truncated row (`_ran_short`, 2026-09-27 — RECFM=F already did this). With a `record_separator` set, the layout still frames first (2026-09-28: a `0x0A` inside COMP/COMP-3 data used to split the record); the layout's length is taken when a separator or end-of-data follows it and every separator inside it falls in binary/packed/float bytes, else it falls back to `find(separator)` (text lines shorter than the layout) |

* * *

`EncodingOptions.record_separator` is consumed after each record when it is
actually there. Fields past the end of a short record come back
`present=False` (the column stays, so a table has the same shape for every
row); a record cut mid-field comes back `truncated=True` **with an `error`**
(`"3 of 4 bytes: record ends inside the field"`, #358, 2026-10-14), so it
counts in `error_count` and fails `decode --strict`: text keeps the characters
that were there, every other value is `""` (three of `PIC 9(4)`'s digits,
`001`, are not the value `1`). The one exemption is a record whose end the
file states -- an RDW, or a `variable-bare` record separator -- read through
a per-record range (`VaryingLength.per_record`: `RECORD VARYING ... DEPENDING
ON`, or an explicit `record_varying`) with its body length inside `n..m`: it
ends mid-field by design (`decode_record(cut_ok=True)`, via
`RecordDecoder._cut_by_design`), still flagged `truncated`, no error. A range
without `DEPENDING ON` bounds the file, not each record, so a cut there is
still an error. Bytes left after the last whole record are `DecodeResult.trailing`
— never dropped silently, because a tail that is not a whole record almost
always means the record length is wrong. `max_records`/`skip` page a large
file, and a run stopped by `max_records` reports `trailing == b""` rather
than calling the rest of the file a broken tail.

## Record compare (`data/compare.py`, 2026-09-27)

*(2026-09-27 to 2026-10-14.)*

* **Field comparison is by decoded value** -- a `C` and an `F` sign nibble on
  the same packed number are equal, as they are to the program.
  `compare_bytes=True` compares raw bytes, and additionally reports a
  `(unmapped bytes)` pseudo-field when two records agree field by field but
  not byte by byte (slack past the layout under `record_length`). Bytes of an
  *ignored* field are blanked on both sides before that image check
  (2026-09-27: `--compare-bytes --ignore UPD-TS` had reported the ignored
  timestamp's bytes as `(unmapped bytes)`, so the ignore did nothing).
  **LOW-VALUES padding is a difference** (2026-10-13, #287): the decoder
  strips trailing spaces *and* NULs from DISPLAY text (display output keeps
  doing so), so `'ALICE'` + 5 x `x'00'` and `'ALICE     '` decode alike, yet
  the program tells them apart (`IF A-NAME = SPACES`) and an uninitialised
  output field is what the check exists to catch. `_same()` therefore also
  requires a text field's (alphanumeric / alphabetic / alphanumeric-edited /
  national) NUL byte positions to match once the values agree. Before, only
  `--compare-bytes` caught it, and that also flags C/F sign nibbles and
  filler. Numeric-edited fields are checked too (an unmodelled picture reads
  as plain text and was otherwise blind to it). **FILLER is exempt** (round
  2 review): uninitialised FILLER in an FD record is common and harmless, so
  making it a difference would fail compares that passed before; only
  `compare_bytes` reports it. The text report appends `(bytes x'..' vs x'..')` to a difference
  whose two values print the same, so the reader can see what differs. A field that
  did not decode cleanly on *either* side is always compared by bytes: its
  best-effort value is not evidence.
* **Absent fields** (a shorter VB record, an `OCCURS DEPENDING ON` occurrence
  its counter excludes) compare as absent: `FieldDifference.expected` /
  `.actual` is `None`, rendered `(absent)` in the text report.
* **Truncated fields** (#357, 2026-10-14): a field the record ended part-way
  through (`DecodedField.truncated`) differs from one of another length, even
  when what is left decodes to the same value (`'ABC '` cut to `'ABC'`,
  `'0000'` cut to `'0'`). `_same()` compares `length` before values. Before,
  a shorter actual record compared equal and `compare` exited 0; only
  `--compare-bytes` caught it. Two fields cut at the same place stay equal.

* * *

* **Trailing partial records can make files unequal** (2026-10-04, #250).
  `CompareResult.trailing_differs` (in `to_dict()`, and a `trailing bytes
  differ` line in `to_text()`) is set, and `equal` is False, when both files
  end in a partial record and the two tails differ -- or, under
  `compare_bytes`, when only one file has a tail (the image is longer).
  Comparing values, a one-sided tail stays a caveat only. Before, `equal`
  ignored `trailing` entirely, so `XYZ` vs `QQQ` tails reported "files are
  equal" and `compare` exited 0 even with `--compare-bytes`. Option (b) of
  the issue; `_trailing_differs()` is the whole policy.
* **Memory.** The first cut decodes both files fully and builds an in-memory
  key index. A streaming, key-sorted merge for files that do not fit is a
  planned follow-up (design doc, Risks).

## Fixed- and variable-length records (`RecordFormat`)

*(2026-09-28 to 2026-10-14.)*

A copybook says how long a record *can* be. It does not say whether the file
holding it is **RECFM=F/FB** (every record the layout's full length) or
**RECFM=V/VB** (each record only as long as that record's own data makes it).
Before this existed, only the fixed reading was generatable — a copybook with
an ODO table got a caveat on stderr saying the table was written at its
maximum and that a real record would be shorter.

* * *

   **complex ODO** (a `DEPENDING ON` table nested inside an ordinary
   `OCCURS`, so each outer occurrence carries its own count) come out right
   rather than trimming every outer occurrence to the last one's count.
   A counter declared *outside* the enclosing fixed table has no subscripts,
   so the exact `(name, outer)` key misses and the counter is looked up by
   name; `decoding._present` mirrors that fallback (2026-09-28 — it used to
   read the table at full length and mis-align the record).

* * *

* **Where the range comes from.** `VaryingLength.from_fd_clauses()` reads the
  FD's `record` clause, which `data_file_description.py` already parses into
  `{varying, min, max, depending_on}` and attaches to the 01 as `fd_clauses`
  metadata. So `gen-data` on a **whole program** picks it up with no flag. A
  bare **copybook** has no FD; `DataGeneratorOptions.record_varying` (CLI
  `--record-varying MIN:MAX`) supplies it, and overrides the FD when both
  exist. `FROM` itself is optional (`VARYING IN SIZE 47 TO 80` has a
  minimum of 47, issue #402); with neither FROM nor an integer before TO,
  the minimum is None.
* **Only `DEPENDING ON` draws lengths** (#320, 2026-10-14). `RECORD CONTAINS
  47 TO 80` (format 2) and `RECORD VARYING` without `DEPENDING ON` make the
  *file* variable, but IBM COBOL writes each record at the length of the 01
  it was written from, never cut mid-field. `from_fd_clauses()` routes those
  to `VaryingLength.file_range()`: the range is kept unclamped with
  `per_record=False` (so `AUTO` still resolves to variable and LRECL is still
  the declared max), `_draw_lengths()` draws nothing, and each record is the
  layout's full length. A layout outside the range is a caveat, not a cut.
  `GeneratedDataset._resolved_options()` settles `AUTO` against the dataset,
  since the encoder only sees a range through a drawn `data_length`. An
  explicit `record_varying` still opts in to drawn lengths.
* **`maximum` is clamped to the record's own byte length.** An FD promising
  more than its 01 can hold cannot be honoured by padding — those bytes were
  never declared — so the range is cut to what exists. **Never silently**
  (#274, 2026-10-05): `VaryingLength.build(..., caveats=)` appends a sentence
  whenever it clamps a bound, or ignores the range outright because nothing
  of it is left (`40:50` on a 28-byte record, or equal bounds) — the record
  then stays fixed-length. The sentence lands on `GeneratedDataset.caveats`,
  is printed as a `* caveat:` line in `to_hex_dump()`'s header
  (`hex_dump(..., extra_caveats=)`), and as `warning:` on stderr by
  `gen-data` in every output format.
* **The length is drawn per row at *generation* time**, uniformly across the
  range, from the same seeded RNG the values came from, and stored on
  `GeneratedDataset.declared_lengths`. Drawing it there rather than in the
  encoder is what keeps `encode_record` a pure function and makes a seed
  reproduce record *lengths* as exactly as it reproduces their contents. The
  draws happen *after* the rows, so a record with no range draws nothing and
  generates byte-identical output to before this existed.

* * *

* **Decoding agrees.** `RecordDecoder.from_record()` finds the range the same
  way (explicit `options.record_varying` first, else `fd_clauses`) and keeps
  it as `RecordDecoder.varying`; both `resolved_format()` calls in
  `decoding.py` pass `varying=`, so `decode --record-format auto` reads the
  RDW-framed file `gen-data --record-format auto` wrote (2026-09-28; it used
  to frame it fixed-length). Pinned by
  `test_variable_length.py::TestFdRecordVarying::test_decode_auto_reads_what_gen_data_auto_wrote`.
* **Both mechanisms at once**: the table decides, the FD range is not applied
  on top of it, and a caveat says so. Enforced in *two* places, because a
  caveat that the code contradicts is worse than no caveat: the generator
  draws no length for such a record (so `declared_lengths` is `None` and every
  downstream surface agrees for free), and `_effective_data_length()` drops a
  `data_length` a direct caller passes anyway. `minimum_record_length()`
  likewise only prefers the FD floor when a length was actually drawn — a
  Copilot review on PR #204 caught all three of those disagreeing.

## Program Fixtures (`program_fixtures.py`, `data/bundle.py`)

*(2026-08-04 to 2026-10-15.)*

**Columns are unique across a fixture's records (#365, 2026-10-14).** A
fixture can draw fields from several records: a CALL's `USING` arguments, or
a READ boundary's alternate FD records. `flatten_record()` only makes columns
unique *within* one record, so `REC-A.AMT` and `REC-B.AMT` both arrived as
`AMT`, and since a row is keyed by `spec.column` they shared one value (the
`ELSE` witness for `REC-B.AMT` also landed on `REC-A.AMT`; the CSV header
read `AMT,CODE-A,AMT,CODE-B`). `_unique_columns()` now de-duplicates the
combined list on `(qualified_name, subscripts)` (the same argument passed
twice is one set of fields) and, only on a collision, re-runs
`layout._assign_columns` over *copies* of the whole list, so the colliding
names become `REC-A.AMT` / `REC-B.AMT` and every other column keeps its short
header. Copies, because a spec from `ProgramLayoutIndex.resolve()` is the
index's own. A fixture with no collision is byte-identical to before.

* * *

`generate_with_scenarios(ast, index, report, mode="happy"|"branches"|"all",
seed=...)` (and its `_from_file` counterpart) is the Phase 5→6 wiring: it
routes `mode="happy"` straight to `generate()` (byte-identical output, same
seed — pinned by
`test_fixture_bundle_contract.py::TestScenarioModeContract::test_happy_mode_is_byte_identical_to_generate`),
and for `"branches"`/`"all"` runs `ConstraintExtractor` + `ProgramFlowAnalyzer`
+ `ScenarioPlanner` internally and turns every `PlannedScenario` into a real
`Scenario` with populated fixtures — not just a name and an intent string.
The happy-path scenario from `generate()` (same seed) is always prepended,
so these modes add scenarios on top of it and a program with no targetable
arm gets one scenario rather than an empty bundle (2026-10-05; before, 5 of
mockymock's 12 examples got zero scenarios under `branches`/`all` and
`mockymock generate --with-data` exited 1).

* * *

* **Keyed READ key** (issue #322, every scenario including the happy path)
  — a successful keyed READ of an INDEXED file (RANDOM access, or DYNAMIC
  without NEXT/PREVIOUS/FIRST/LAST; `const_fold.keyed_read_key`) returns the
  record whose key the program set, so `_pin_read_keys` writes the key's
  value at that READ (`ConstantFoldResult.read_keys`, matched by
  `(file, line)`; folded from literals plus the scenario's other
  single-row mocked inputs, never the READ's own record) into every row of
  its fixture, overriding generated values and witnesses alike. When the key
  is not known there (set in a branch or loop, never set, or a READ INTO
  whose rows do not carry the FD key) the key stays generated and the happy
  path adds one `unresolved` note for that READ. Two READs of one file can
  now write different rows, so `write_csv_dir` names the second
  `<KEY>-2.csv` (its existing `_csv_names` rule).

* * *

### Expectations: tiers 1-2 (Phase 7)

Every scenario's `expectations` (in both `generate()` and
`generate_with_scenarios()`) now carries structural and computed assertions
alongside Phase 3's OUT-boundary stubs, via two small helpers in
`program_fixtures.py`:

* **Failure-path scenarios (#318, option A).** A `PlannedScenario` with any
  `status_overrides` (the error-status family, and "empty input" when it
  overrides SQL to 100) runs the program's error path, which the generated
  sequences do not describe. `_drop_failure_path_counts` keeps only the
  overridden boundary's own `call_count`, and only when it is not a READ;
  every other count is dropped, because `report.boundaries` is source order,
  not execution order, so no boundary is provably *before* the failure.
  Tier 2 is skipped for these scenarios entirely: the fold walks the normal
  path, so even a literal-only `field_equals` may observe a site the failure
  path never reaches (review on #418).

* **Tier 1 — `_CallCounter`** (issue #363). One
  `Expectation(kind="call_count", ref="<CATEGORY>:<KEY>", value=times)` per
  mocked `(category, key)` -- every statement invoking the same boundary
  merged into one count -- and only when that count is exact; otherwise
  none. A group whose boundaries got no fixture (OUT-only, nothing
  generatable) has nothing mocked to count and gets none. `times` comes from
  `cobolparser.analysis.invocation_counts.count_invocations` (see
  `.okf/analysis.md`): the sum of each invoking statement's static execution
  count along the entry chain -- main line and SIMPLE PERFORMs count once per
  time reached, `PERFORM <literal> TIMES` multiplies, and anything inside an
  IF/EVALUATE/SEARCH arm, a handler, a `PERFORM UNTIL`/`VARYING` body, a
  SORT procedure, or after a branch that could transfer control has no count.
  The one data-dependent exception is the read-until-EOF idiom: a READ file
  with a `SequenceConstraint` whose `PERFORM UNTIL` itself runs exactly once,
  tests only the EOF flag and has no transfer in its body
  (`is_plain_eof_loop`), is invoked `len(sequence) + 1` times (every row, plus the READ that hits
  end of file), whichever READ statements share the work -- a priming READ
  and the loop's READ are one count. A straight-line READ with an AT END
  handler is invoked once, not `rows + 1`: the old formula
  (`len(sequence) + AT END`, `1` for STATUS_ONLY and CALL, one expectation
  per statement) ignored branches and loops entirely. Each count is inserted
  where the group's first fixture's expectations start and keeps the old
  `note`, so bundles whose counts were already right are byte-identical
  (`FIXTUREDEMO.bundle.json` unchanged). Error-status scenarios' counts
  (which take a status-check arm this walk assumes is not taken) are
  trimmed by `_drop_failure_path_counts` (#318, first bullet above).

* * *

| Category / direction | What gets generated |
|---|---|
| `READ` (IN) | `options.rows` rows; when `"AT_END"` is in the boundary's `handlers`, `terminal` is set to `{resolved_field: "10"}` if `_resolve_status_field` finds a real field name (`boundary.status_field`, else `index.file_facts(key).file_status_field`), or stays `None` -- never a placeholder string -- if neither resolves (bug fixed 2026-08-04: previously fell back to a literal `"FILE-STATUS"` key that is not a real data-name in the target program) |

* * *

**Several 01 records under one FD (issue #364, 2026-10-14).** A READ with no
INTO gets every record of its FD in `Boundary.record_names` (Phase 4's
`ConstraintExtractor` relies on that to know every field the READ feeds), but
those records are views of ONE record area -- an implicit REDEFINES. The
generator used to join all their fields into one row, so `HDR-TYPE` and
`DTL-TYPE` (both offset 0) got two different values, the record grew to the
sum of the records' lengths, and a field name repeated in the second record
(the `REC-TYPE` idiom) was dropped by the column de-dup. `_record_view()` now
picks exactly one record per scenario: the one holding the most of that
scenario's pinned fields (`witnesses` + every `row_witnesses` row), the first
in source order on a tie or with no scenario. `bundle.layouts` is keyed by the
chosen record, so a scenario that picks the second record adds its own key.
`bundle.unresolved` carries one note per such READ, naming the records no
scenario generated ("alternate view(s) not generated: ..."), computed after
generation from the records actually used (the happy path always uses the
first). Only `READ` boundaries are narrowed: an SQL boundary's several names
are distinct host variables.
Pinned by `tests/unit/test_program_fixtures.py::TestMultipleRecordsUnderOneFd`.

Fields of two such records have different names but share bytes, so
`ScenarioPlanner` (`_shared_record_areas()` / `_record_areas()`) never merges
an arm pinning one record into a scenario pinning another, and an arm whose
own path pins both is `missed` ("pins fields of several 01 records of one
FD"). As a guard, a scenario that still pins two views (hand-built, or a
future planner path) has every arm counted `missed` with that reason, the
way a violated witness demotes (#244), since its dropped pins are never
generated. Pinned by `TestArmsOnTwoRecordsOfOneFd` (2026-10-15).

**A FILLER that owns a level-88 (2026-10-15).** `05 PIC X. 88 FLAG-ON VALUE
'Y'.` (or `05 FILLER PIC X. 88 ...`) is a flag the program branches on.
`ProgramFixtureGenerator` sets `DataGeneratorOptions.include_condition_filler`,
so `flatten_record` keeps such a FILLER even with `include_filler` off (plain
gen-data still drops it). Its path segment is `FILLER#<n>` (`layout_segment()`,
*n* its 1-based position among its group's FILLERs), so two flag FILLERs in
one group have distinct qualified names, witnesses and columns, and
`ProgramLayoutIndex` maps each 88 to its own FILLER rather than the group's
first. Plain FILLERs keep `FILLER`. Pinned by `TestFillerOwningConditionName`.

* * *

### `unresolved` propagation

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

* * *

### `write_csv_dir`

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
CSV lives — without walking the directory tree first. **Names are made
unique** (2026-09-28): scenario names used to repeat (two IFs in one
paragraph both planned `"<PARA>: THEN"`; the planner names them uniquely
since #267, but a hand-built bundle still can), and both used to slug to one directory, the later
scenario's CSV overwriting the earlier one's with both manifest entries
pointing at the survivor. `_unique_names` suffixes a repeated slug `-2`,
`-3`, ... (first keeps its plain slug, case-insensitive), and `_csv_names`
does the same for a `<KEY>.csv` two fixtures would write with *different*
rows (identical same-key fixtures still share one file). Both passes use the
one precomputed name list, so `csv_path` always names the file written. See
`docs/fixture-bundle-schema.md`'s own "write_csv_dir" section for the full
manifest shape.

## Flowcharts (`flowchart.py`)

*(2026-08-11 to 2026-10-05.)*

Driven by `cobol-parser program-flow --format mermaid|dot`. Node ids and
labels come from `FlowNode.key` (the `qualified_name` when two paragraphs
share a name, issue #258), so `X1 OF S1` and `X1 OF S2` are drawn as two
nodes (`X1_OF_S1`, `X1_OF_S2`) and edges, which name nodes by key, attach.

`SQL_WHENEVER` edges (#349, `EXEC SQL WHENEVER ... GO TO p`) are drawn like
`CICS_HANDLE`: in the internal-edge set, the GO TO-family set, and labelled
`SQL WHENEVER`.

**External-call nodes.** Module-level `_external_call_target()` reads the
called program from `report.external_calls[i]["program"]` (falling back to
`"target"` for hand-built legacy dicts) and uppercases it, so `EXT_*` node ids
agree with `FlowEdge.target`. Rationale (2026-08-12 fix, audit A-A2): both
generators used to read `ext.get("target", "")` off
`report.external_calls`, but `EdgeCollector.process_call`
(`analysis/program_flow/edges.py`) emits the called program under the
`"program"` key -- so `EXT_*` nodes NEVER rendered from a real
`ProgramFlowAnalyzer` report, only from hand-built dicts. There was also a
case mismatch: `FlowEdge.target` is uppercased by the collector while
`call_info["program"]` keeps the source's original case, so a lowercase
`CALL 'subpgm'` literal produced a CALL edge pointing at an `EXT_` id no
node declared. Pinned by
`tests/unit/test_flowchart_generator.py::TestExternalCallEndToEnd` (real
COBOL through the analyzer into both renderers, plus the legacy-dict
fallback).

* * *

**Recursion/GO TO edge styling, terminal exit nodes, THRU badges,
quoted labels:** both generators render these identically in substance,
differing only in each target format's own attribute syntax:

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
  [analysis.md](../analysis.md)'s `ProgramFlowAnalyzer` section), labeled
  `"{kind} @ {line}"` (ASCII `@` since 2026-08-12 — see "Label fidelity"
  below), positioned right after the main node loop and
  before external-call nodes in both generators — Mermaid emits `(((...)))`
  triple-circle syntax plus a `terminal` classDef
  (`fill:#1b1b1b,stroke:#c1121f`); DOT emits `shape=doublecircle` with
  matching `fillcolor`/`fontcolor`. Both respect `show_unreachable`
  identically to the main node loop. The terminal id is normally
  `f"{nid}_EXIT"` (`nid` = the paragraph's own allocated id), but the
  chart's `_IdAllocator` (see "One id allocator per chart" below) falls
  back to `{nid}_FLOWEXIT`, then an incrementing numeric suffix, whenever
  that id is already taken (e.g. by a real paragraph's sanitized id). **Bug fixed
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

- **Quoted edge labels.** `MermaidFlowchartGenerator` wraps every non-empty
  edge label in double quotes (`-->|"label text"|`), reusing the `#quot;`
  entity escape already used for branch/arm condition text. **Bug fixed
  2026-08-11:** labels were previously written unquoted between the `|...|`
  pipes; Mermaid's flowchart lexer reads an unquoted `(` or `[` there as the
  start of a node shape (`PS`/`SQS` tokens), not literal text, so a loop
  annotation (`... (loop)`), `CALL_DYNAMIC`'s `"CALL (dynamic)"` label, or a
  `[THRU n]` badge broke parsing entirely — e.g. a `PERFORM UNTIL` loop edge
  in `legacy-application/cobol/DEPTBMP.cbl`. DOT is unaffected — `_dot_str`
  already quotes every DOT label.

* * *

**Label fidelity and id safety:** rules driven by how the VS Code
Program Flow webview (Mermaid v11, `htmlLabels:false`,
`securityLevel:'strict'`) actually renders the emitted text:

- **ASCII-only output.** Both generators' emitted labels are pure ASCII:
  the exit-terminal separator is `@` (was U+00B7 `·`) and
  `GOTO_DEPENDING`'s short label is `GO TO ... DEPENDING` (was U+2026
  `…`). On Windows the CLI writes stdout in the console's locale encoding
  (cp1252) while consumers decode UTF-8, so any non-ASCII label character
  rendered as U+FFFD (`GOBACK � 118` in the webview). Pinned by the
  `test_output_is_ascii_only` tests (`out.encode("ascii")`).
- **`"`/`<`/`>` escaped in every Mermaid label.** Module-level
  `_escape_mermaid_label()` maps `<`/`>` to `#lt;`/`#gt;` and `"` to a
  plain apostrophe in branch conditions, arm labels, and edge labels.
  Mermaid v11 with `htmlLabels:false` silently swallows a bare `>` from
  label text (`WS-PURGE-ERRORS > ZERO` rendered as `WS-PURGE-ERRORS
  ZERO`, `>=` as `=`) while `<`/`<>` happen to survive; the `#name;`
  entity form renders correctly through both the lexer and the sanitizer
  for `<`/`>` only — `#62;`-style *numeric* entities and `#quot;` both
  come out as literal `&#62;`/`&quot;` text in SVG-text label mode
  (verified empirically against Mermaid 11.12), which is why `"` is
  substituted rather than entity-escaped: display-only text, and `'Y'`
  is how the COBOL literal read anyway. This supersedes the earlier
  bare `.replace('"', "#quot;")` used since the 2026-08-11 quoted-edge-
  label fix. DOT labels are not escaped — Graphviz has no such mangling.
- **DOT string escaping (2026-09-28).** Edge attribute values now go
  through `_dot_str` like node labels: a PERFORM UNTIL / IF condition with
  a `"` inside an apostrophe literal was emitted raw into `label="..."`,
  ending the DOT string early. And the node label's `\n (N stmts)` break is
  appended *after* `_dot_str` -- passed through it, the `\n` became `\\n`,
  which Graphviz renders as a literal backslash-n.
- **DOT keyword ids (2026-09-28).** `_sanitize_id` output is a valid bare
  DOT ID *except* for the reserved words `node`/`edge`/`graph`/`digraph`/
  `subgraph`/`strict` (case-independent in Graphviz). A paragraph named
  `NODE` was emitted as `NODE [label=...]` -- the default-node attribute
  statement -- and `MAIN -> STRICT;` was a Graphviz syntax error (verified
  with `@hpcc-js/wasm-graphviz`). `_dot_id()` quotes exactly those ids at
  every DOT node/edge emission site. Mermaid is unaffected: its flowchart
  keywords (`end`, `style`, `class`, `click`, ...) only bite in lower case,
  and every id here is upper case (verified with mermaid 11 `parse()`).
- **One id allocator per chart (#266, 2026-10-05).** `_sanitize_id` is
  lossy: paragraphs `A-B` and `A_B` both sanitize to `A_B`, and an external
  program `SUBPGM` (`EXT_SUBPGM`) meets a paragraph named `EXT-SUBPGM` --
  the colliding nodes were silently merged and every edge into either
  landed on the merged box. Each `generate()` builds one
  `_IdAllocator.for_report(report)`, mapping `(kind, name)` -> a unique id
  (kinds `node` = paragraph/section/branch/arm keyed by raw name, `ext` =
  called program, `exit` = terminal). Paragraphs are allocated first so
  they keep the plain id; a later collision gets a numeric suffix
  (`A_B_2`, `EXT_SUBPGM_2`). Every node declaration and edge endpoint goes
  through it; `_hidden_ids()` and the skipped-empty-arm set hold *raw*
  names. A chart without collisions is byte-identical to before.
- **`show_unreachable=False` hides what the paragraph owns (2026-09-28).**
  Only the paragraph's own node line (and its terminal node) was skipped;
  its outgoing PERFORM/GO TO/CALL edges, its IF/EVALUATE decision and arm
  boxes, and external nodes called only from it were still emitted, and
  both renderers re-create an undeclared edge endpoint as a bare box -- the
  hidden paragraph came back unstyled. `_hidden_ids()` (paragraph + its
  branch/arm ids) and `_external_targets()` (drops a CALL made only from a
  hidden paragraph) are shared by both generators.

* * *

Reference tests: `tests/unit/test_flowchart_generator.py` —
`TestMermaidFlowchartGenerator` (linkStyle/terminal-node/THRU-badge
sections, plus `test_linkstyle_index_accounts_for_terminal_node_links` and
`test_terminal_id_does_not_collide_with_real_exit_paragraph` pinning the
two composition-bug fixes above), `TestDotFlowchartParity` (the DOT-side
mirror), `TestSortThruEndToEnd` (real-COBOL-through-the-analyzer proof
that a SORT OUTPUT PROCEDURE THRU range now reaches both renderers), and
`TestMermaidLabelFidelity`/`TestDotLabelFidelity`/`TestLabelFidelityEndToEnd`
(ASCII-only output, `#lt;`/`#gt;` escaping, arm summaries, empty-IF-arm
dropping).

## Scenario Planning (`scenarios.py`)

*(2026-10-05 and earlier.)*

`plan(..., *, mode="branches")` — the planner's own default is `"branches"`
(`ProgramFixtureGenerator.generate_with_scenarios`'s is `"happy"`).

**Path conditions are folded in.** A targeted arm's witness set includes
the conjuncts of every enclosing arm on its path (`BranchConstraints.enclosing`,
`_path_constraints`); an enclosing arm the constraint report never modelled
becomes a `PlannedScenario.path_gaps` entry. Coverage is still *arm*
coverage, CFG-shaped rather than data-shaped. Full detail in
[Path conditions](#path-conditions-branchconstraintsenclosing-2026-09-04)
under Program Fixtures. (The v1 planner took only the arm's own conjuncts;
that was the largest source of scenarios that never reached their arm.)

* * *

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

* * *

**Naming** (#267, 2026-10-05). One arm's name is
`"<proc>: <VERB>@<line> <arm label>"` -- `"MAIN-PARA: IF@11 THEN"`,
`"P: EVALUATE@90 WHEN 'A'"` -- with the verb read off a conjunct's
`origin` (else the flow graph's `branch_type`). An OR-split arm
(`THEN#2`) appends its own disjunct, rendered from its conjuncts
(`"... THEN [WS-A = 'Z']"`), or `[alt N]` when it has none. After merging,
a scenario is renamed for *every* arm it targets (later arms in the same
paragraph drop the repeated `"<proc>: "`), joined with `" + "`, or the
first arm's name plus `" (+N more arms)"` past 120 characters; then
`bundle._unique_names` suffixes any repeat `-2`, `-3`, ... -- so names are
unique within a plan. `ArmOutcome.merged_into` carries the *final* name.
Before this, two IFs in one paragraph both planned `"<PARA>: THEN"`.
`name` stays free text (no `bundle_version` bump).

* * *

**Wired into `gen-fixtures` as of Phase 6.** The CLI's `--scenarios
branches|all` now drive real scenario selection via
`ProgramFixtureGenerator.generate_with_scenarios_from_file` (see "Scenario-mode
generation" under "Program Fixtures" above) -- each `PlannedScenario` becomes
an actual `BoundaryFixture`-populated `bundle.Scenario`, and
`FixtureBundle.scenario_coverage` carries this module's own
`ScenarioCoverage.to_dict()` verbatim.

## Program Layout Index (`data/program_layout.py`)

*(2026-08-12 to 2026-10-05.)*

**FD vs SD.** The parser now also tags `fd_record_type` (`"FD"` or `"SD"`) —
previously untracked, since nothing needed the distinction before this
index. An SD is a SORT/MERGE work file, not a file a program `OPEN`s;
`FileFacts.record_type` surfaces it so a later phase can mark it
`unconstrained` instead of mock-eligible (mockymock refuses SORT/MERGE
outright).

* * *

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
**Qualified 88 names (#272, 2026-10-05).** `IS-OK OF REC-A` (or `IN`, or
dotted `REC-A.IS-OK`) filters the 88's declarations by its qualifiers with
the same rule the field branch uses (each qualifier names the record or a
group on the parent field's path) before the one-parent check, so a
qualified reference to a duplicated 88 resolves instead of being given up
on. `condition_values()` / `condition_raw_values()` split the name with
`split_qualified_name` and filter the same way (they used to look up the raw
text, so any qualified name returned `None` and `gen-fixtures --scenarios`
missed every arm testing it). A *bare* duplicated 88 still refuses to guess.

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

### Multi-program compilation units

`build()` indexes exactly the `CobolProgram` node it is given — for a file
with stacked/nested programs (`CobolProgram.contained_programs`, e.g.
`tests/samples/subprogram_demo.cbl`'s caller + two callees), build a separate
index per program unit rather than expecting one index to see all of them.
This composes cleanly with Phase 2's planned `--callee-path` resolution rung,
whether the callee comes from a separate file or a contained program in the
same one.

## Self-verification: `Scenario.verification` (2026-09-04)

*(2026-09-04, #244 2026-10-04.)*

A scenario's *name* is a claim. Until this existed, nothing checked it: the
planner pinned witnesses, the generator emitted rows, and whether those rows
actually satisfied the branch the scenario was named for could only be found
out by running each case under a tracer. `generators/verification.py` closes
that — `verify_scenario(planned, scenario)` re-reads the scenario's OWN
emitted fixture data and re-checks every planned conjunct against it, and
`generate_with_scenarios` stores the verdict (a `ScenarioVerification`:
`status` `"verified"`/`"unverified"`, `fields: list[FieldVerdict]` of
`field`/`status`/`detail`/`rows`, `gaps`) on `Scenario.verification`
(serialized `{"status", "fields", "gaps"}`; additive, `bundle_version` stays `1`;
`None` for a `mode="happy"` scenario, which targets no branch and so has
nothing to verify).

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

**A `violated` verdict demotes the scenario's arms to `missed`** (2026-10-04,
#244). `generate_with_scenarios` passes each verdict to
`_demote_violated_arms`: every `targeted`/`merged` arm of a scenario with a
`violated` field is re-counted as `missed` in `scenario_coverage` (reason
`"witness failed verification: ..."`, counts kept exact) and gets one
`bundle.unresolved` entry, so `gen-fixtures --strict` exits 2 instead of
passing a coverage claim its own data contradicts. `absent`/`unknown` do
not demote -- they are "could not tell", which `unverified` already says.

`cli/parse.py`'s `gen-fixtures` prints an unverified summary on **stderr**
(stdout stays JSON-only — mockymock's `fixtures` contract), and mockymock's
`generate --with-data` renders the same reasons as a `*> UNVERIFIED:` comment
above the affected TESTCASE.

## Value generation, Public API P-scaling, Flattening rules

*(2026-08-12 to 2026-09-28.)*

                   .total_digits .scaling_leading (2026-09-10; read straight
                       off the item's own PictureClause at construction --
                       see below)

* * *

**P-scaling: one canonical parse, not a second regex over the raw picture
string (2026-09-10).** `FieldSpec.scaling_positions` (signed `P` count:
positive trailing, negative leading, zero otherwise) and `.stored_digits`
(digit positions actually stored, `P`s excluded) used to come from a
module-level `scaling_positions(picture: str)` function that re-parsed the
raw picture text with its own regex — a second implementation of exactly
what `models.data_items.PictureClause._parse_scaled_pattern` already
decides while building the AST. `flatten_record`'s `_flatten_into` now
copies `picture.total_digits`/`picture.scaling_leading` straight onto the
`FieldSpec` at construction time (the same `picture.total_digits`
`generators/data/layout_offsets.py`, the `data-items` CLI, already reads
directly), and the two properties compute from those instead of re-deriving
anything. See [ast-models.md](../ast-models.md)'s `scaling_leading` note and
[analysis.md](../analysis.md)'s MoveTypeChecker section (`_is_non_integer_picture`
was the third independent P-scaling check; now reads `decimal_digits`
alone).

* * *

| Group `USAGE` / `SIGN` | Inherited by every subordinate elementary item with no clause of its own (IBM rule), resolved **in the parser** (`parsers/divisions/data.py` `propagate_group_usage_and_sign`, 2026-09-28) so `layout.py`, `layout_offsets.py` and `calculate_size` all see it. `CobolDataItem.usage_explicit` marks an entry's own USAGE; an explicit child wins for itself and below. A numeric-only group usage (COMP-3, BINARY, ...) is not pushed onto a non-numeric PICTURE; SIGN only lands on signed numeric items |

* * *

   Both endpoints are tested with `_INTEGER_LITERAL_RE` (`^[+-]?\d+$`), so a
   sign is accepted on either side, and the expansion iterates the **closed
   interval from the low bound** — a descending `VALUE 4 THRU 2` therefore
   yields 2 as well as 3 and 4 (iterating from `start` silently dropped the
   low endpoint). A non-numeric range (`VALUE 'AA' THRU 'ZZ'`) contributes
   only its endpoints.

* * *

`_format_number` (and `_fit_domain_value`/`render()`'s parse) is Decimal
throughout (2026-08-12 bug review): the old float64 internals silently
rounded any exact value past ~16 significant digits, so a solver-picked
`PIC 9(18)` witness rendered one-off (`...678` → `...680`) and the fixture
could never take the branch it targeted. Randomly generated floats are
unaffected (`Decimal(str(float))` round-trips); declared VALUEs, level-88
literals, and solved witnesses now render digit-for-digit. Pinned by
`tests/regression/test_bug_review_2026_08_12.py::TestWideNumericPrecision`.

* * *

`_literals.py`'s `quote_literal()` re-emits a decoded literal doubling
each embedded `"`; its inverse `unquote_literal()` (2026-09-27) strips the
delimiters *and* collapses the doubled delimiter. Any consumer reading a
re-emitted literal back must use it: `generators/data/layout.py`
(`_strip_literal_quotes`, VALUE clauses), `analysis/constraints.py`
(`_strip_quotes`, branch witnesses) and `analysis/const_fold.py` (MOVE
sources) each stripped only the delimiters, so `VALUE "A""B"` generated
`A""B` and `MOVE '"'` folded to two quote characters. Pinned by
`tests/regression/test_doubled_quote_literal_values.py`.

`_strip_literal_quotes` also decodes a typed literal through
`_literals.typed_literal_content()` (2026-09-27, audit 2.1): the VALUE clause
now keeps `X"4142"` as written, and gen-data renders it `AB` rather than the
old `41`. Latin-1 code points, so an EBCDIC record image re-encodes the
characters, not the original bytes -- see `lexer.md` "Literal round trip".

**Signedness.** `PictureClause.is_signed` only reports an explicit `S`, so
`_is_signed()` additionally treats a numeric-edited picture carrying `+`,
`-`, `CR`, or `DB` as signed — `PIC -ZZ,ZZ9.99` is the canonical signed
display field and would otherwise never generate a negative.

**Edited pictures** contribute their *logical* numeric value, not the edited
display form: a CSV is consumed by tooling that wants the value, and the
edit mask is a presentation concern of the COBOL program. Likewise `COMP-3`
carries the decimal value, not packed bytes.  The *record image* is the other
side: there an edited field holds the edited bytes (2026-09-27; it used to
hold the CSV's logical value left-justified, e.g. `9516.07 ` for
`PIC $$,$$9.99`, which no COBOL program writes). `editing.py` implements
IBM's editing rules -- Z/`*` suppression, floating `$`/`+`/`-` strings,
fixed `+`/`-`/`CR`/`DB`/`$`, `B`/`0`/`/`/`,` insertion, the all-`Z`/all-`*`
zero case -- and every case in `tests/unit/generators/data/test_editing.py`
was checked byte for byte against GnuCOBOL 3. A floating `+`/`-` can land on
an insertion position inside its own string (`PIC +++,+++` edits -514 as
`   -514`, the sign where the comma would be); `deedit_numeric` reads the sign
there too (2026-09-28: it skipped insertion positions and decoded +514).

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

## Path conditions: `BranchConstraints.enclosing` (2026-09-04)

*(2026-09-04.)*

The planner's v1 simplification — "a scenario targets *one* arm and takes
only that arm's own conjuncts; enclosing branches on the path to it are not
accumulated" — was the single biggest source of scenarios whose data did not
reach their own arm. On a nested `IF INV-QTY > 500 / IF INV-TYPE = "AB"`, the
scenario named for the inner arm pinned `INV-TYPE` and left `INV-QTY`
wherever the value generator happened to put it, so it usually never entered
the outer arm at all.

`ConstraintExtractor` now records, on every `BranchConstraints`, the
`(branch_id, arm_id)` chain whose arms must all be taken for that decision
point to be reached (`_walk_list` threads it down through
`_nested_statement_lists`, which pairs each nested statement list with the
arm id it sits under). `ScenarioPlanner._path_constraints` joins on those
pairs and folds the enclosing conjuncts into the targeted arm's own before
solving, so the witness set pins the whole path. Consequences worth knowing:

* An arm that becomes unsatisfiable once its path condition is added (outer
  `X > 5`, inner `X < 3`) is now correctly `missed` with
  `"unsatisfiable with its own path condition: ..."` rather than targeted
  with data that could never reach it.
* An enclosing arm the constraint report never modeled contributes a
  `PlannedScenario.path_gaps` entry instead of silence, and that alone makes
  the scenario `unverified` — the arm may still not be reached, and saying so
  beats an optimistic label.
* **An OR-split enclosing arm is a disjunction, and is folded as
  alternatives** (`_path_options` + `_solve_with_path`, review fix on PR
  #198). `_register_variants` registers `THEN#1`/`THEN#2`/... and NO bare
  `THEN` for a condition containing an OR, while `enclosing` names the base
  arm id -- so a plain `arms_by_key[(branch_id, "THEN")]` lookup misses
  every such arm and silently leaves the path unfolded. Each `#N` variant is
  one way to satisfy the same arm, so the planner tries them in order and
  keeps the first that stays satisfiable alongside the targeted arm's own
  conjuncts. Fixing on the first disjunct would be wrong, not just
  suboptimal: for `IF A = 100 OR A = 200 / IF A = 200` it makes the set
  unsatisfiable and reports the inner arm unreachable when `A = 200` reaches
  it. `_MAX_PATH_COMBINATIONS` caps the cross product a deep chain of
  disjunctive arms would otherwise produce.
* **`_merge_candidates` carries `path_gaps` across a merge.** A merged-in
  candidate brings its own unpinned enclosing arms with it; dropping them
  let the merged scenario report `verified` while an arm it now claims was
  not in fact pinned -- the silent false positive `path_gaps` exists to
  prevent.
* IF/EVALUATE/SEARCH arms join the chain, including **SEARCH's `AT END`**
  (`_ARM_BEARING_ATTRS`): `_extract_search` registers an `arms["AT_END"]`
  entry, so a statement nested under it does have an enclosing arm to join
  to, even though the clause reaches the walk through
  `_NESTED_STATEMENT_ATTRS` rather than a `when_clauses` list. It carries no
  conjuncts (the real precondition, "the table search found nothing", is not
  a field constraint), so it lands in `path_gaps` -- which is the point:
  untagged, a branch inside it looked top-level and could be reported
  `verified` without its data establishing the search fell through. A
  genuinely non-branch nesting (`ON EXCEPTION`, an inline `PERFORM` body)
  still contributes nothing: inventing an id for one would produce a path
  entry nothing could join to.

## `select_record()` (`data/copybook.py`)

*(undated.)*

`CopybookDataGenerator._select_record` moved to a module-level
`select_record(records, record, filename)` and the method now delegates to
it. Both halves of the package need it and they need it to *agree*:
generating from `--record CUST-REC` and decoding through `--record CUST-REC`
must land on the same 01, or a round trip through the record image silently
changes layout.

## Overview: lazy import architecture

*(undated.)*

**Import architecture: `__init__.py` is lazy (`__getattr__`-based), not
eager.** Importing `cobolparser.generators` touches no submodule; each public
name is resolved on first attribute access (mirroring
`cobolparser.analysis.__init__`). `__all__` lists **54** names (copybook
data, record encoding/decoding/views/compare, layout index, bundle shapes,
flowcharts, `ProgramFixtureGenerator`). Several helpers live only in
`cobolparser.generators.data` (its own `__all__`, 61 names): `encode_record`,
`encode_field`, `hex_dump`, `decode_field`, `decode_record`,
`occurrence_count`, `unresolved_odo_counters`, `select_record`,
`ValueFactory`, `binary_byte_length`, `packed_byte_length`. Rationale:
`program_fixtures.py` depends at runtime on
`cobolparser.analysis.constraints`/`.domains`/`.program_flow`, which are
reachable from `cobolparser.analysis` modules that need `generators.data.*`
(`FieldSpec`, `ValueFactory`, `ProgramLayoutIndex`). Eager package-init
imports made the first touch of either package fail with "partially
initialized module" depending on unrelated import order — three times
(`bundle.py` ↔ `boundary_inventory.py`, `constraints.py` ↔
`program_fixtures.py`, `domains.py` ↔ `scenarios.py`) before the root cause
was fixed. (`generators.data.__init__` itself is still eager.)

## See also

* [generators.md](../generators.md) — the routing page and its topic files
