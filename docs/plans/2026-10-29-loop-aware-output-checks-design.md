# Loop-aware output checks for generated tests

**Status:** proposed (2026-10-29). Follows PR #769.
**Scope:** `analysis/const_fold.py`, `generators/program_fixtures.py`,
`generators/data/bundle.py` (one additive expectation kind), and in
mocky-mock `dsl/generator.py` plus the WRITE mock splice.

## The gap

`gen-fixtures` bundles become tests through `mockymock generate --with-data`:
one TESTCASE per scenario, mocks built from the scenario's rows, and an
`EXPECT` for each `field_equals`. Those tests barely check outputs. Over the
45 enterprise and shamrice samples (`--scenarios all`), 1,267 expectations
are 256 `call_count`, 4 `field_equals` and 1,007 stubs. 142 of the stubs are
WRITE records ("value produced by the program under test"), which are the
outputs a test exists to check.

PR #769 made the fold decide IF/EVALUATE branches, observe every field of a
written group record, and only claim values that still hold where mocky-mock
checks them. That added nothing on the samples. Only 1 of 148 main-line
branches could be decided, and seeding file and SQL statuses (as an
experiment) raised it to 32 with still no new `field_equals`. In real batch
programs the outputs are unknowable to the current fold for four reasons,
usually all at once:

1. **They are written inside a read-until-end loop.** The fold poisons every
   field a `PERFORM UNTIL` body writes, and the READ's fixture has several
   rows, so it is not seeded either (`_single_row_seeds`).
2. **Statuses are never set.** `IF NOT TRAN-OK ... STOP RUN` after an OPEN
   is undecidable because the fold never learns the FILE STATUS the mock
   supplies. The same goes for SQLCODE after EXEC SQL.
3. **Output lines start from VALUE clauses.** Headers, labels and
   separators are FILLERs with VALUEs; the fold starts from an empty env.
4. **Records are built with group MOVEs.** `WRITE REPORT-REC FROM
   WS-PRINT-LINE` and `MOVE WS-DETAIL TO OUT-REC` poison the whole target
   (`_apply_move_target` on a group).

## What mocky-mock already guarantees

The design leans on facts about how mocky-mock runs a generated test, so
each one was checked in `Landparty/mocky-mock`:

* **WORKING-STORAGE is reset between test cases** (`splicer/reset.py`):
  every item goes back to its VALUE clause, or to ZERO / SPACES when it has
  none. So the state at the start of a TESTCASE is known exactly, which a
  real first run of the program also matches for items with a VALUE.
* **A multi-row READ mock is a tally-branching `EVALUATE TRUE`**
  (`dsl/generator.py`, `_read_sequence_body` area): call k moves row k into
  the record, and the call after the last row takes the TERMINAL (AT END,
  status `"10"`). Row k is the bundle's `sequence[k-1]`, so the fold can
  replay it.
* **A mocked WRITE keeps its implicit MOVE** (`WRITE r FROM y` still moves
  y to r), and the record area afterwards holds the last record written.
* **`EXPECT` runs after the PERFORM of the entry paragraph**, wherever it
  is written (`dsl/parser.py`), which is why PR #769 requires a value to
  hold there.
* **`CAPTURE ARG` exists for CALLs only** and keeps the last call
  (`docs/2026-08-11-argument-capture-design.md`). It has no per-call
  history and nothing for WRITE.

## Proposal

Four fold changes in cobol-parser, one new expectation kind, and one
mocky-mock feature. Each step is shippable alone, in this order.

### Step 1: statuses after each I/O statement (S)

Pass the scenario's per-boundary statuses into the fold
(`fold(..., statuses={(category, key, line): {"WS-FS": "00"}})`, built from
`BoundaryFixture.status`). After the walk folds an OPEN/CLOSE/READ/WRITE/
EXEC SQL whose boundary has a status, it sets those fields. A READ's status
is per call: `"00"` while rows remain, the TERMINAL value after the last.
Only scenarios without `status_overrides` use it (failure paths still skip
tier 2). This is what makes the ubiquitous `IF NOT FILE-OK ... STOP RUN`
decidable, which PR #769 then walks past.

### Step 2: start from the VALUE clauses (S)

Seed the env with every WORKING-STORAGE and LOCAL-STORAGE elementary item
whose VALUE is a plain literal or figurative constant the fold already
models, including FILLERs (they matter as parts of a group, step 3). Items
without a VALUE stay unknown: mocky-mock's ZERO/SPACES default is a
mocky-mock convention, not COBOL, and a bundle should not bake it in. A
REDEFINES alias of a seeded item is not seeded. Tables (OCCURS) are left
unknown, since the fold does not model elements.

### Step 3: group MOVEs as byte copies (M)

Model `MOVE group TO group`, `MOVE group TO elementary`, `WRITE r FROM
group` and `READ ... INTO group` as what COBOL does: an alphanumeric move of
the source's bytes. When every leaf of the source is known and has a
DISPLAY representation the fold can render exactly (alphanumeric, unsigned
zoned decimal, signed zoned with SIGN SEPARATE), build the source's bytes,
pad or truncate them to the target length, and split them into the
target's leaves by offset (`ProgramLayoutIndex` already has byte offsets).
A leaf whose bytes are not a valid value for its PICTURE (text landing in a
numeric field) is left unknown. COMP, COMP-3, overpunched signs and edited
fields make the whole move unknown in v1. This is the step that turns
`WRITE REPORT-REC FROM WS-PRINT-LINE` into known fields.

### Step 4: replay a plain read-until-end loop row by row (M)

When a `PERFORM UNTIL` is a plain EOF loop (`invocation_counts.is_plain_eof_loop`,
the same test `call_count` already trusts), the READ inside it has a
fixture with n rows, and nothing else in the body is a loop or an
undecided transfer, walk the body n+1 times instead of poisoning it:

* call k of the READ restores the record from `sequence[k-1]` (and its
  INTO target), then sets the status for a successful read;
* call n+1 takes the AT END handler (now known to fire) and sets the
  TERMINAL status, and the UNTIL condition is evaluated with `_decide`; if
  it does not come out true exactly then, the loop falls back to today's
  poisoning;
* a priming READ before the loop counts as call 1, the same way
  `count_invocations` shares the count.

Anything the replay cannot decide inside the body (an undecided IF, a
nested loop) poisons only what it writes, as today. The step budget
(`_MAX_WALK_STEPS`) still applies; a fixture is at most `options.rows`
rows, so the replay is bounded.

After step 4 a WRITE inside the loop is observed n times with different
values. `field_equals` still cannot express "the k-th record", so a field
written per row is reported only when every write saw the same value. That
is fine for constants (a record type code, a literal) but misses the point.
Step 5 adds the expectation that can express it.

### Step 5: `record_sequence` expectations (M, both repos)

A new additive `Expectation` kind, `kind="record_sequence"`:

```json
{"kind": "record_sequence", "ref": "WRITE:REPORT-REC",
 "value": [{"PL-ACCT": "00012", "PL-TYPE": "D", "PL-AMOUNT": "000150"},
           {"PL-ACCT": "00034", "PL-TYPE": "C", "PL-AMOUNT": "000075"}],
 "note": "every record the program writes, in order"}
```

It is emitted only when the fold knows the exact number of writes (the
same rule `call_count` uses) and every listed field at every write. A field
it cannot know is left out of each row rather than guessed, and when no
field is known for some write the expectation is not emitted. One per
written file record, `ref` in the existing `"CATEGORY:KEY"` form.

`bundle_version` does not change: a new `kind` value is additive, and
mocky-mock's loader must already treat an unknown kind as a stub. Its
current `_render_expectation` falls through to the stub branch for anything
but `call_count` / `field_equals`, which this change should confirm with a
test before relying on it.

On the mocky-mock side this needs a per-write capture: the WRITE mock body
copies the record into the k-th entry of a generated `OCCURS` table (the
"per-call history" the argument-capture design deferred), and the
generated TESTCASE gets one `EXPECT` per field per row against that table.
The DSL could spell it as a new `CAPTURE RECORD INTO <table>` in a WRITE
mock, plus generator support. That is mocky-mock's own design to write;
this document only fixes the bundle shape it consumes.

## Exact or absent

Every step keeps the fold's rule. Concretely:

* A status is set only from the scenario's own fixture, after the
  statement that produces it.
* VALUE seeding uses only literals the fold renders today.
* A group MOVE is modelled only for DISPLAY leaves whose bytes the fold can
  produce exactly; anything else unknowns the whole target.
* The loop replay only runs when `is_plain_eof_loop` holds and the UNTIL
  becomes true exactly at the AT END call; otherwise it is today's poison.
* Each step gets a GnuCOBOL check like the earlier fold work: run the
  program with the fixture rows and compare every claimed value with what
  it really wrote (a small harness under `tests/` behind the existing
  `slow` marker, skipped when `cobc` is absent).

## How we will know it worked

Re-run the measurement from "The gap" after each step: `field_equals` and
`record_sequence` counts per program on the 45 samples, plus the share of
WRITE stubs replaced. BATCHSEQ is the reference case: after step 4 its
header line (1000-INIT) and, after step 5, every detail line in
3100-PRINT-LINE should be checked. If step 4 still leaves most samples
without knowable output, stop and re-measure which construct is blocking
before building step 5.

## Not in scope

* Loops that are not plain EOF loops (`PERFORM VARYING` over a table,
  `UNTIL` with a counter), SORT INPUT/OUTPUT PROCEDUREs (BATCHSEQ's detail
  lines are written from a RETURN loop, which step 4 handles only if
  RETURN is treated like READ; listed as a follow-up), and GO TO loops.
* COMP / COMP-3 / edited field rendering in group moves.
* REWRITE, RELEASE and SQL INSERT outputs; the same `record_sequence`
  shape can carry them later.
