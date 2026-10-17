---
type: Module
title: Record Decoding and Compare
description: generators/data/ read side — record views (views.py, REDEFINES overlays, framing length), RecordDecoder (decoding.py, per-storage-class decode, framing, bad-byte reporting, FD LRECL), record compare (compare.py, key pairing, field-by-field diff) and select_record().
tags: [generators, decode, compare, record-image, redefines, views, framing, ebcdic]
timestamp: 2026-10-15T00:00:00Z
---

# Record Decoding and Compare

The other direction from [record-data.md](record-data.md): **bytes somebody
else wrote, plus a copybook, back into a table** ("open this VSAM extract /
EBCDIC flat file with this copybook and show me the records"), then two such
files compared field by field. `views.py` builds the offset-annotated byte map,
`decoding.py` (`RecordDecoder`) reads records through it, `compare.py`
(`compare_files`) pairs and diffs them. CLI: `decode` and `compare`
([cli.md](../cli.md)). Start with [Record views](#record-views).

## Contents

- [Record views](#record-views)
- [Decoding](#decoding)
- [Framing](#framing)
- [Output shapes](#output-shapes)
- [Record compare](#record-compare)
- [`select_record()`](#select_record)
- [Tests](#tests)
- [See also](#see-also)

## Record views

Everywhere else a layout is a flat `list[FieldSpec]` whose widths,
concatenated, are the record. That is all an encoder needs, because it is
writing the bytes and therefore knows where it is. A decoder needs two more
things:

* **Where each field starts.** A running sum of `FieldSpec.storage_size` —
  the same arithmetic `encode_record()` performs implicitly when it
  concatenates. Computing offsets from the same widths is *the* invariant
  here: a decoded offset and an encoded byte position cannot drift, because
  neither has its own copy of the arithmetic. `test_views.py`'s
  `test_base_offsets_match_the_encoded_record` checks that against real
  encoded bytes rather than a second hand-written offset table.
* **Which layout the bytes are being read through.** `REDEFINES` means one
  run of bytes has several meanings and only the program knows which applies
  to the record in front of you. A generator can duck that (it picks one and
  writes it — `include_redefines=False`); a decoder cannot.

So `build_record_views(record, options) -> RecordViews`:

| | |
|---|---|
| `RecordViews.base` | the record as declared, redefinitions excluded. Its `length` is the record's own length — the LRECL of a fixed-length file |
| `RecordViews.overlays` | one `RecordView` per `REDEFINES` item anywhere in the tree, in source order. Each is the **whole record with that overlay swapped in** for the item it redefines (`layout.flatten_overlay_view(record, substitutions={id(redefined): overlay})`), plus every enclosing overlay for a nested one (see #296). So an overlay inside `OCCURS` is read at every occurrence (`T-ALT(1)`, `T-ALT(2)`), and `compare --view X --key K` works for a key outside the redefined area. A shorter overlay is padded with a `FILLER` so later fields keep their offsets. Fields outside the overlay keep the base view's column names (`_align_columns`). An overlay that covers a table's `DEPENDING ON` counter records it as a `HiddenCounter` (also returned by `flatten_overlay_view`), and `decode_record` reads the counter from those bytes when it reaches the overlay. Overlay views are `_LazyOverlayView`s, flattened on first read of `fields`, so a decode through one view does not pay for all of them. A lazy view still takes `RecordView`'s own fields as constructor arguments, so `dataclasses.replace()` works on it. `RecordDecoder._caveats` passes the hidden counters to `encoding_caveats` too, so a covered counter is not reported as missing from the record. `RecordView.offset` is where the overlay itself starts (first occurrence) and `overlay_length` its own span; the fields always start at 0 |
| `RecordViews.get(name)` | by full name (`CUST-REC.ADDR-OVERSEAS`) or the redefining item's own short name (`ADDR-OVERSEAS`), case-insensitively — a user reading the copybook has the short one in front of them |
| `RecordView.fields` | `list[PlacedField]` = `(spec, offset)`, contiguous: `placed[n].offset + placed[n].length == placed[n+1].offset` |
| `RecordView.offset_ambiguous` | base view: the record has an `OCCURS ... DEPENDING ON` table, so its offsets are a maximum-length guess (the fields `data-items` reports as `byte_offset: null`); overlay: one sits before or inside the overlay, so its static offset holds only for a full-length record (the decoder resolves offsets per record). An enclosing fixed `OCCURS` does not set it |
| `RecordViews.framing_length` | the stride a fixed-length file is actually cut at: `max(base.length, end of every widening overlay view)` — for `A X(4)` / `A-R REDEFINES A X(8)` / `B X(2)` that is 10, matching `data-items` (B at 8). Equal to `base.length` for every conforming layout, and larger only for a `REDEFINES` wider than what it redefines — which COBOL forbids below level 01 but compilers accept, growing the record. `RecordDecoder` frames on this; framing on `base.length` shreds every record after the first. `to_dict()` reports **both** numbers, so a consumer never frames on a number the decoder does not use |

`options` are normalised through `for_record_image()` inside
`build_record_views`, so passing CSV-shaped generation options cannot
silently produce a byte map with holes in it.

**`flatten_record(..., ignore_root_redefines=True)`** is what makes an overlay
flattenable: ordinarily a record that itself carries `REDEFINES` flattens to
*nothing*, which is right for generation and useless for decoding. Only the
root's own clause is exempted — a `REDEFINES` nested inside the subtree still
excludes its fields, so a view stays a contiguous run of bytes. Internally:
`_flatten_into(..., ignore_own_redefines=True, redefines_label=...)`, neither
of which is inherited by the recursive calls; `redefines_label` still reaches
every spec's `FieldSpec.redefines` so a field says which redefinition it
belongs to.

The overlay scan (`_scan_overlays`) mirrors `layout_offsets._layout_siblings`'
slot bookkeeping (a run of mutually-redefining siblings shares one slot; the
slot's footprint is its widest member) but emits placed `FieldSpec`s and
recurses *into* redefining children, so a redefinition of a redefinition gets
its own view. Each member's footprint comes from `_footprint()` =
`sum(storage_size for flatten_record(child, ...))`, i.e. the same widths
again rather than a parallel size model.

## Decoding

(A bare copybook is wrapped in a program skeleton before parsing, see
[record-data.md](record-data.md#parsing-a-copybook); `data-items` and the
MCP server wrap the same way through `wrap_copybook_fragment`, #536.)

`RecordDecoder(views, opts=None, *, record_length=None, varying=None,
layout_warnings=None)`, or `.from_copybook_source()` / `.from_copybook_file()`
(both take `copybook_paths=` to expand a `COPY` in the layout; see
[record-data.md](record-data.md#parsing-a-copybook)) / `.from_record()`.
`layout_warnings` names each `COPY` left unexpanded, and is the first entry
of every `DecodeResult.caveats` (and so of compare's); the CLI prints them
once as `warning:` and skips them in decode's `note:` loop.
`RecordViews.caveats` (also in every `DecodeResult.caveats`) opens with
`layout.occurs_expansion_caveats()`: a table the expansion caps cut short
leaves the view shorter than the real record, so every offset after it is
wrong for a real file (#376).
`decode_bytes(data, view=..., max_records=..., skip=...) -> DecodeResult`;
`decode_file(path, ...)` is the same in binary mode (a COMP field routinely
contains 0x0A, which a text-mode read would translate).

**Fixed framing of a whole program is the FD's LRECL, not the chosen 01's
length** (see #362). Every 01 under one FD shares the record area, so a
RECFM=F file of that FD holds LRECL-byte records whichever 01 `--record`
picks. `copybook.fd_record_length(records, chosen, options)` returns that
LRECL — the largest sibling 01's `framing_length`, or the FD's fixed `RECORD
CONTAINS n` when that is larger (a smaller one does not shrink the area, so
every 01 of one FD gets the same LRECL) — or `None` when it is not longer
than `chosen` (no FD/SD, a bare copybook, or `chosen` is the longest).
`from_copybook_source()` uses it as the default `record_length`
(`--record-length` still overrides; `from_record()` alone has no siblings to
look at). `CopybookDataGenerator.generate_from_source()` stores the same
number as `GeneratedDataset.lrecl`, and under `RecordFormat.FIXED`
`to_records()` / `record_lengths()` / `to_hex_dump()` pad each record out to
it with the charset's space (`encode_record(..., pad_to=)`), the dump showing
an `(FD LRECL slack)` row — so `gen-data --record HDR-REC --format record`
writes the file `decode --record HDR-REC` reads. Variable formats are not
padded. Framing a 16-byte-LRECL file at a 9-byte header's length shreds every
record after the first — silently, with an all-text layout and a file length
divisible by both sizes.

Per storage class, each the exact inverse of `encoding.py`'s encoder and
dispatched on the same `USAGE`-then-category ladder (a numeric-edited field
is de-edited with the field's own `currency_signs`, as the encoder edits it,
#491):

| Storage | Read back as |
|---|---|
| DISPLAY text | the charset's characters (ASCII decoded as **latin-1**, so a byte the encoder could not have written is still shown), trailing spaces/NULs stripped |
| zoned DISPLAY | one digit per byte, sign overpunched or `SIGN IS SEPARATE`. Under `SEPARATE` only the sign byte carries the sign and it must be `+` or `-`: every digit is unsigned, so a sign zone on one is an `error` (never a negation), and a blank sign byte is an `error` too (see #360: x'F1F2D34E' must not read `-123` clean, nor x'F1F2F340' `123`) |
| `COMP-3` | two BCD nibbles per byte, sign in the final low nibble. With an even digit count the first byte's high nibble is pad, not a digit: a non-zero pad is an `error` and is left out of the value (read as a digit, `S9(2)V99` x'12345C' would decode as `123.45`, more digits than the PICTURE holds) |
| `COMP`/`COMP-4`/`COMP-5` | two's-complement, big-endian except COMP-5 which follows `EncodingOptions.endian` |
| `COMP-1`/`COMP-2` | IEEE 754, rendered to 7 / 15 significant digits |
| `INDEX`/`POINTER` | **hex** (`0x00000007`) — a compiler-managed occurrence number and an address mean nothing in a file another run wrote |

**Numbers render exactly as `ValueFactory._format_number` renders them** (no
leading zeros, the field's own `decimal_digits` places, a leading `-` only on
a non-zero negative) — `_render_number()` exists solely to keep that
equality, which is what makes `decode(encode(row)) == row` a property the
suite can assert rather than a hope. **Floats are held to the same equality**
by `values._render_float()`, which quantises a drawn value through the
field's own storage and renders it to the digit count the decoder uses: a
COMP-1 value drawn to four decimals over ±10,000 needs nine significant
digits and binary32 holds about seven (`-9419.8954` would read back
`-9419.896`), and the decoder's `%g` drops a trailing zero `%.4f` would add
to a COMP-2 (`-7960.5120` vs `-7960.512`). One column is exempt **by
construction**: `FILLER` comes back empty because `encode_field()`
deliberately writes spaces there rather than the generated cell.

The decoder's COMP-1 caveat (`result.caveats`) is about a *foreign* file: an
arbitrary binary32 written by some other program carries more than the seven
digits shown. It says nothing about a value this generator wrote, which is a
fixed point of the round trip.

**Sign conventions are read more widely than they are written.** The encoder
writes one convention per charset; real files carry several, so `_zoned_digit`
accepts every EBCDIC sign nibble (`A`/`C`/`E`/`F` positive, `B`/`D`
negative), GnuCOBOL's ASCII zone (0x70), *and* the `{ABC…`/`}JKL…`
overpunches an EBCDIC file picks up when a transfer transcodes it. That last
one is deliberately never *written* by `encoding.py` (no compiler here to
verify it against) but a decoder that choked on it would be useless on half
the files in the wild. A sign is only honoured **in the position the encoder
would have put one** — a `D` zone mid-field is a corrupt digit, not a
negative number, and calling it a sign would flip a value that is merely
unreadable.

**Bad bytes are reported, not zeroed.** `DecodedField.error` names the
problem and the value is best-effort; `DecodedRecord.errors` and
`DecodeResult.error_count` roll them up. A copybook applied to the wrong file
shows up as a wall of these, which is the single most useful thing the
module can say (`test_the_wrong_copybook_shows_up_as_a_wall_of_errors`).

Invalid data that is still *readable* counts too (see #248):

* an `OCCURS ... DEPENDING ON` counter outside its table's `min..max` is an
  error on the counter (`DEPENDING ON value 7 outside 2..5`); the table is
  still read at the clamped count (`_counter_value`), the best guess at where
  the following fields are;
* an RDW-framed record whose body holds bytes past the last field the base
  view reads gets a record-level error in `DecodedRecord.record_errors`
  (rolled into `errors`, `to_dict()["errors"]`, `error_count`, and a `!` line
  in the hex pane), so those bytes never vanish with `trailing == b""`;
* a `B`/`D` sign nibble on an **unsigned** packed field is an error and does
  not negate, mirroring the zoned decoder's sign-zone rule;
* a `COMP`/`COMP-4`/`BINARY` value with more digits than its PICTURE (65535
  in `PIC 9(4) COMP`) is a **caveat**, not an error: legal under
  `TRUNC(BIN)`, invalid under `TRUNC(STD)`, and the decoder has no TRUNC
  option. `COMP-5` is exempt (native binary, its whole width is legal).

## Framing

* **Framing always uses the `base` view**, whichever view the caller reads
  through: where a record ends is a property of the *file*, not of the
  overlay somebody chose. A 200-byte record read through a 20-byte
  redefinition is still 200 bytes; framing on the overlay would walk the
  file at the wrong stride.
* **`trim_tables` is decided by the record format, not by the counter.**
  Under `RecordFormat.FIXED` an ODO table reserves all of its occurrences
  whatever the counter says, so trimming would skip bytes that *are* in the
  record and mis-align every field after the table (silent garbage from the
  table onward). `decode_bytes` resolves the format once from the base view
  and passes `trim_tables=fmt.is_variable` to `decode_record`.

| Format | How the next record is found |
|---|---|
| `FIXED` | `record_length` override, else `base.length`. With a `record_separator` set, the separator is *checked*, not just skipped (see #359): a record not followed by it (and not at end of data), or one with a separator inside non-binary bytes (`_separators_only_in_binary`, judged on the base view), gets a `record_errors` entry, so lines that are not LRECL bytes long never decode silently misframed |
| `VARIABLE` | the 4-byte RDW; an RDW longer than the file raises `RecordDecodingError` rather than being guessed at |
| `VARIABLE_BARE` | the layout's own ODO counters — decoding consumes exactly what this record holds, so the next starts where this stopped. A tail shorter than the record its own counters describe is `trailing`, not one more truncated row (`_ran_short`, as RECFM=F does). With a `record_separator` set, the layout still frames first (a `0x0A` inside COMP/COMP-3 data must not split the record); the layout's length is taken when a separator or end-of-data follows it and every separator inside it falls in binary/packed/float bytes, else it falls back to `find(separator)` (text lines shorter than the layout) |

`EncodingOptions.record_separator` is consumed after each record when it is
actually there. Fields past the end of a short record come back
`present=False` (the column stays, so a table has the same shape for every
row); a record cut mid-field comes back `truncated=True` **with an `error`**
(`"3 of 4 bytes: record ends inside the field"`, see #358), so it counts in
`error_count` and fails `decode --strict`: text keeps the characters that
were there, every other value is `""` (three of `PIC 9(4)`'s digits, `001`,
are not the value `1`). The one exemption is a record whose end the file
states — an RDW, or a `variable-bare` record separator — read through a
per-record range (`VaryingLength.per_record`: `RECORD VARYING ... DEPENDING
ON`, or an explicit `record_varying`) with its body length inside `n..m`: it
ends mid-field by design (`decode_record(cut_ok=True)`, via
`RecordDecoder._cut_by_design`), still flagged `truncated`, no error. A range
without `DEPENDING ON` bounds the file, not each record, so a cut there is
still an error. Bytes left after the last whole record are
`DecodeResult.trailing` — never dropped silently, because a tail that is not
a whole record almost always means the record length is wrong.
`max_records`/`skip` page a large file, and a run stopped by `max_records`
reports `trailing == b""` rather than calling the rest of the file a broken
tail.

## Output shapes

* `DecodeResult.to_csv()` — the exact inverse of `GeneratedDataset.to_csv()`:
  same column names, same value rendering, same `"\n"` terminator. The CLI
  test asserts `gen-data | decode` reproduces the generated CSV byte for byte.
* `DecodeResult.to_dict()` — every field's `offset`, `length`, `hex`,
  `present`, `truncated`, `error`. This is what a UI hex pane binds to.
* `decoded_hex_dump(result, opts)` — the same shape `encoding.hex_dump()`
  produces for a generated record, built from bytes somebody else wrote:
  every line ties an offset and a length to the field that owns those bytes
  and to the value read out of them, with `! field: error` lines under the
  bad ones.

## Record compare

`data/compare.py`, Phase 1 of the test-data-environments initiative (design:
`backend/docs/superpowers/specs/2026-09-27-test-data-environments-design.md`):
the check that closes an integration test — the dataset a batch run wrote
against the baseline it should match. Built entirely on the decoder above; it
adds pairing and field comparison, and decodes nothing itself.
`compare_records()` / `compare_files()` → `CompareResult` (`RecordDifference`,
`FieldDifference`, `CompareError`).

* **Pairing.** With `key=[...]`, records pair on the tuple of key-field
  values: an inserted or deleted record is reported once, as `extra` /
  `missing`, instead of shifting every later record into `changed` (the
  failure of a byte compare / IEBCOMPR). Duplicate keys pair in file order and
  are named in `caveats` (the first ten; the rest counted). Without a key,
  records pair by position.
* **Field comparison is by decoded value** — a `C` and an `F` sign nibble on
  the same packed number are equal, as they are to the program.
  `compare_bytes=True` compares raw bytes, and additionally reports a
  `(unmapped bytes)` pseudo-field when two records agree field by field but
  not byte by byte (slack past the layout under `record_length`). Bytes of an
  *ignored* field are blanked on both sides before that image check, so
  `--compare-bytes --ignore UPD-TS` does not resurface the ignored bytes as
  `(unmapped bytes)`.
* **LOW-VALUES padding is a difference** (see #287). The decoder strips
  trailing spaces *and* NULs from DISPLAY text (display output keeps doing
  so), so `'ALICE'` + 5 x `x'00'` and `'ALICE     '` decode alike, yet the
  program tells them apart (`IF A-NAME = SPACES`) and an uninitialised output
  field is what the check exists to catch. `_same()` therefore also requires a
  text field's (alphanumeric / alphabetic / alphanumeric-edited / national)
  NUL byte positions to match once the values agree; numeric-edited fields
  too (an unmodelled picture reads as plain text). **FILLER is exempt**:
  uninitialised FILLER in an FD record is common and harmless; only
  `compare_bytes` reports it. The text report appends `(bytes x'..' vs
  x'..')` to a difference whose two values print the same, so the reader can
  see what differs. A field that did not decode cleanly on *either* side is
  always compared by bytes: its best-effort value is not evidence.
* **Absent fields** (a shorter VB record, an `OCCURS DEPENDING ON` occurrence
  its counter excludes) compare as absent: `FieldDifference.expected` /
  `.actual` is `None`, rendered `(absent)` in the text report.
* **Truncated fields** (see #357): a field the record ended part-way through
  (`DecodedField.truncated`) differs from one of another length, even when
  what is left decodes to the same value (`'ABC '` cut to `'ABC'`, `'0000'`
  cut to `'0'`). `_same()` compares `length` before values, so a shorter
  actual record never compares equal. Two fields cut at the same place stay
  equal.
* **Name resolution is against the `RecordView`, not the records**, so a
  typo is caught even when both files are empty. A key token resolves, in
  order, as a column (`QTY(2)`), a qualified name, or a field's own name, and
  must hit exactly one elementary column (a group, a table name, or a name
  two groups share is an error). An ignore token matches a column, a field
  name (every occurrence), a qualified name, or any group on the path
  (everything under it); `CompareResult.ignored` lists what was *actually*
  skipped. A name that is not in the layout, or a key that is also ignored,
  raises `CompareError` — never a silent no-op that hides a real difference.
* **Counts are exact, the list is capped.** `max_differences` bounds
  `differences`; `changed_count` / `missing_count` / `extra_count` never are,
  and `truncated` says when the list stopped short.
* **Everything the decode was unsure of carries over**: decode caveats from
  both sides (de-duplicated), per-side decode-error counts, per-side trailing
  bytes.
* **Trailing partial records can make files unequal** (see #250).
  `CompareResult.trailing_differs` (in `to_dict()`, and a `trailing bytes
  differ` line in `to_text()`) is set, and `equal` is False, when both files
  end in a partial record and the two tails differ — or, under
  `compare_bytes`, when only one file has a tail (the image is longer).
  Comparing values, a one-sided tail stays a caveat only.
  `_trailing_differs()` is the whole policy.
* **Memory.** Both files are decoded fully and an in-memory key index is
  built. A streaming, key-sorted merge for files that do not fit is a
  planned follow-up (design doc, Risks).

## `select_record()`

`select_record(records, record, filename)` (module-level in
`data/copybook.py`; `CopybookDataGenerator._select_record` delegates to it)
picks the 01 a `--record` name means. Both halves of the package use it and
must *agree*: generating from `--record CUST-REC` and decoding through
`--record CUST-REC` must land on the same 01, or a round trip through the
record image silently changes layout.
The rest of `copybook.py` is generation-only (value drawing, `unique_fields`
caveats, #526) and never reaches the decoder.

## Tests

* `tests/unit/generators/data/test_views.py` / `test_decoding.py` /
  `test_compare.py` — record views (offsets match the encoded bytes),
  decoding per storage class and framing, field-by-field compare
* `tests/unit/cli/test_decode_cli.py` / `test_compare_cli.py` — the CLI side
* `tests/unit/generators/data/test_variable_length.py` — RDW/variable-bare
  framing round trips (see [record-data.md](record-data.md))

## See also

* [generators.md](../generators.md) — the generators routing page
* [record-data.md](record-data.md) — the encoder, layouts, value rendering
  and variable-length records this reads back
* [cli.md](../cli.md) — `decode`, `compare` (exit codes) and `--list-views`
* [history](../history/generators.md) — archived dated notes (decoder and
  compare fix write-ups)
