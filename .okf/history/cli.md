---
type: History
title: CLI history
description: Archived dated notes moved out of cli.md; not loaded by default.
tags: [history, cli]
timestamp: 2026-10-15T00:00:00Z
---

# CLI history

An archive of dated notes moved out of [cli.md](../cli.md) on 2026-10-15: its
former `# Recent changes` section and the point-in-time narratives ("before
2026-09-28 ...", "used to ...", issue-by-issue fix notes) that sat inside the
per-subcommand reference. Paragraphs are kept verbatim, grouped under the
heading they came from; the topic file states the current behaviour and keeps
the rationale as present-tense invariants. Newest first where dates allow.

## Recent changes

### 2026-10-15

* `jcl` without the `[jcl]` extra prints the install hint as a one-line
  `error:` and exits 1, instead of an `ImportError` traceback (#326).
* `gen-fixtures --rows -1` / `--max-occurs 0` / `data.rows: -5` in
  `cobol.yml` print a one-line `error:` and exit 1 instead of a
  `ValueError` traceback (#327).
* `--profile-output` (and a non-default `--profile-top-n`) now imply
  `--profile` on every subcommand that takes them (they were silently
  ignored without it), and a single-file `--profile-output` naming a
  directory -- or a batch one naming a regular file -- is a one-line
  `error:` instead of a traceback (#328).

### 2026-10-08

* `jcl --dd-map --program NAME` now honours `--program` (it listed every
  step's DDs); the filter is the same step set `--bindings --program` uses.
* `cobolparser/cli/parse.py` has a `__main__` guard, so `python -m
  cobolparser.cli.parse ...` runs the CLI (it was a silent no-op; only the
  `cobol-parser` console script worked).

## Dated notes moved from the subcommand reference

### Output Identification

* **`tokenize`** — `{"source_file": ..., "tokens": [...]}` (previously a bare
  token list).

### Project config file (`cobol.yml`)

* **`--config FILE` / `--no-config`** — stripped from argv by
  `extract_config_flags()` *before* argparse and before `main()`'s legacy
  "first positional isn't a subcommand, so prepend parse" rewrite. Two
  reasons: they work on either side of the subcommand, and the rewrite would
  otherwise take `--config`'s argument for the source file. They are declared
  on the top-level parser for `--help` only; argparse never sees them.
  Only the exact spellings are stripped, so `extract_config_flags()` also
  rejects (exit 1, a `ConfigError`) any `--X` / `--X=...` where X is a proper
  prefix of `config` or `no-config` -- `--no-conf`, `--no`, `--conf=FILE`,
  `--co` -- on either side of the subcommand (issue #323, 2026-10-14).
  Otherwise argparse's prefix matching swallowed them at the top level, or
  after the subcommand read them as one of its own options (`--no` for a
  `--no-...` flag), and the discovered `cobol.yml` silently stayed in force.
  Done on the raw argv rather than with `allow_abbrev=False` on every
  subparser, so abbreviations that cannot mean these two still work.

* **The YAML subset** — stdlib only (this package has no runtime
  dependencies). Nested mappings, block/flow sequences (a block sequence
  may sit at its key's own column -- the indentless form), flow mappings,
  quoted/plain scalars (`''` in single quotes; YAML 1.2's full double-quoted
  escape set, `\xXX`/`\uXXXX`/`\UXXXXXXXX` with exactly that many hex digits,
  `\e`/`\N`/`\_`/`\L`/`\P` included since 2026-09-28), `#` comments, one optional
  leading `---`, an optional trailing `...` (anything significant after it is
  a second document and rejected), a leading UTF-8 BOM (ignored). Anchors,
  aliases, tags, block scalars, merge keys, multiple documents, tabs in
  indentation and duplicate keys are **rejected with a line number**. Two
  deliberate YAML 1.2-core departures from 1.1: `yes`/`no`/`on`/`off` stay
  strings, and a duplicate key is an error rather than last-one-wins.
* **Comment stripping tracks quote state, and a backslash escape consumes
  the character after it.** `_strip_comment` runs before the parser, so it
  has to know which `#` is inside a string: `msg: "a \" # b"` keeps its
  whole value. (Until 2026-09-16 it advanced one character past a `\`
  instead of two, so an odd number of escaped quotes left a later `#` looking
  unquoted; pinned by `tests/regression/test_audit_2026_09_16.py`.)
* **A quote only opens a quoted span at the start of a scalar** (line start,
  or after `:`, `- `, `[`, `{`, `,`) -- `_opens_quote()`, shared by
  `_strip_comment`, `_split_key` and `_is_mapping_entry`. Mid-word it is a
  plain character: `owner: Sam's shop  # note` had kept `# note` in the value
  and `don't: 1` failed to parse. Fixed 2026-09-27.
* **Stricter where YAML is stricter** (2026-09-27, round 2): numbers resolve
  only for the YAML 1.2 core spellings (`1_000`, `\u0663`, `0x1F` stay strings;
  Python's `int()` had taken the first two); a plain value holding `: `
  (`key: a: b`) is rejected -- quote it; `- - x` is a nested sequence, not the
  string `"- x"`; and line numbers count `\n`/`\r\n`/`\r` records only
  (`split_source_lines`), not the form feeds / NEL / U+2028 `splitlines()`
  also broke on.
* **A sequence entry where a scalar belongs is rejected** (2026-09-28):
  `copybook_path: - copybooks` (and `[- x]`, `{k: - x}`, `key: -`) had come
  back as the *string* `"- copybooks"` -- a list the user wrote, silently
  turned into one directory name. YAML rejects it ("sequence entries are not
  allowed here"); so does `_is_sequence_indicator()` now. `-x` / `-1` are
  still plain scalars.

### Parse

Parses a COBOL file and prints the AST as JSON. `json-path` (dotted) extracts
a specific subtree. `--errors` shows parse errors only. `--stats` appends
`ParseStatistics`. `--find-type` finds all AST nodes of the given type (e.g.
`MoveStatement`), equivalent to `ast.find_all_by_type()`. `--profile` /
`--profile-top-n` / `--profile-output` wrap the parse in a `ProfilerContext`
(see [parser.md](../parser.md)) and embed timing/memory metrics in the output, or
write a binary `.prof` to `PATH`. `--profile-output` (or a `--profile-top-n`
other than the default 20) implies `--profile` -- on its own it used to be
silently ignored (#328) -- and a `--profile-output` that is an existing
directory is a one-line `error:` (exit 1) before the parse, not an
`IsADirectoryError` traceback after it.

**Nested profilers (issue #274, 2026-10-05).** A `ProfilerContext` entered
while another profiler is active (an outer `ProfilerContext`, a bare
`cProfile`, anything on `sys.setprofile` or `sys.monitoring`'s PROFILER_ID)
skips cProfile: its result has `function_profile_available: false`, empty
`top_functions`, no `.prof` file, and a `caveats` entry, while wall-clock,
CPU and memory are still measured. Before, on 3.11 the inner cProfile
silently replaced the outer one (whose `top_functions` then held only
`__enter__`/`enable`), and on 3.12+ `enable()` raised after tracemalloc had
started, leaking the session. An inner context never stops a tracemalloc
session it did not start.

**Exit codes** (`_exit_if_partial_parse`): `0` clean parse; `1` hard
failure (`ast is None`, unreadable file); `2` recovered-but-errored parse —
the JSON is still printed, a summary goes to stderr (also argparse's own exit
code for bad arguments). `--find-type` follows the same rule (it exited `0` on
a partial parse until 2026-10-10). `batch` likewise exits `2` when any file
has a `read_error` or `success=false`. Analyzer subcommands exit `0` on a
partial parse (`_parse_result_or_fail`) but print `warning: <file> parsed with
N error(s); analysis may be incomplete` to stderr; `ast is None` is exit 1
there too. Rationale: before 2026-07-07 the CLI exited `0` whenever an AST
existed, so scripts gating on `$?` saw every partial parse as success.

### Preprocess

Runs fixed-format normalisation and conditional compilation; prints the resulting
free-form text. `--define` sets compiler flags for conditional blocks.
`--strip-directives` runs `strip_compiler_directives()` (PROCESS/CBL cards)
before anything else.
Under `auto` (the default) normalisation runs only when `detect_fixed_format` (`preprocess/source_format.py`)
classifies the source as fixed (it used to run unconditionally, silently
slicing columns off genuine free-form input); `--source-format=fixed` forces
it; `--source-format=free` skips it entirely.
Records are split with `_lines.split_source_lines` (\n / \r\n / \r only),
the same splitter the parser uses. Before 2026-09-28 `preprocess` used
`str.splitlines()`, so a form feed / NEL / U+2028 inside a comment record
split it in two and the comment's tail came out as code.
Normalisation goes through `source_format.normalize_with_recovery()`, like
`parse` and `tokenize`: an unterminated literal at end of file (a truncated
upload) prints `warning: Unterminated string literal ...` on stderr and the
recovered text on stdout, exit 0. Before #372 it escaped as a `ValueError`
traceback.

### Source layout (`--source-format`)

`--debug-lines` / `--no-debug-lines` (`BooleanOptionalAction`, default off)
ride along in `_add_source_format_args`: compile fixed-format `D` lines as
code instead of dropping them (see [preprocessing.md](../preprocessing.md);
issue 334). `_source_format_kwargs()` adds `debug_lines=True` to its dict only
when set; `scan` forwards it as `ScanOptions.debug_lines`; `preprocess`
passes it to `normalize_fixed_format` directly. cobol.yml
`project.debug_lines: true|false` (strictly a boolean) fills it, and
`--no-debug-lines` is the way to override a `true` there. The subcommands
without `--source-format` that still parse COBOL (`batch`, `expand`,
`gen-fixtures`, `codebase-graph`, `copybook-impact`, `field-impact`) take it
through `_add_debug_lines_arg()` (2026-10-15): without the dest, the config
key was silently ignored by them. `gen-data` / `decode` / `compare` / `jcl` /
`le-info` / `config` have none (pinned by
`test_only_record_layout_subcommands_lack_debug_lines`).

`preprocess`, and `parse` / every analyzer given `--define` without
`--copybook-path` (the CLI-side `preprocess_conditional_compilation` pass in
`_do_parse`), print conditional-compilation diagnostics
(unknown `>>IF` conditions, stray `>>ELSE`/`>>END-IF`, malformed
`>>DEFINE`, unclosed `>>IF` — audit 2026-07-07 H7) to **stderr** as
`warning: ...` lines, so deleted guarded blocks are not silent. With
`--copybook-path` the expander runs that pass instead, and `expand` reports
them in its JSON's `statistics.warnings`.
`preprocess` evaluates `>>IF` / `>>EVALUATE` / `>>DEFINE` **whether or
not `--define` is given** (issue #271, 2026-10-05): it used to run the
conditional pass only under `--define`, so without it every `>>IF ... >>ELSE`
came out with both arms and an in-source `>>DEFINE` was ignored.
`preprocess` (fixed-format branch only) additionally prints
`normalize_fixed_format`'s column-72 overflow diagnostics the same way
(2026-08-14 — see [preprocessing.md](../preprocessing.md)'s "Column 73+
overflow warning" section): a non-comment line whose real content ran past
column 72 and was silently truncated.

### Expand

`--keep-comments` (2026-09-07) puts every comment line's original text back
into the listing, in the program and in each inlined member. Expansion always
blanks comments first — a `COPY` written inside one must not be expanded — so
without this the output keeps their line numbers and loses their text, which
for a listing meant to be *read* is most of what was wanted. Restoration
happens after every substitution and changes no line of code and no line
number. See [preprocessing.md](../preprocessing.md).

`--source-map` (2026-09-07) adds `source_location_map` to the JSON: one entry
per expanded line, `{"<expanded line>": {"file": ..., "line": ...}}`, naming
the file and line that line came from — the program itself, or the copybook it
was inlined from. This is what lets a consumer move a line number reported
against the expansion back onto a file a human edits; the `lint` subcommand
applies it for its own findings automatically (see below).

### `--format record` / `--format hex`: real record bytes

* `record` writes raw bytes — through `sys.stdout.buffer` on stdout and in
  binary mode to `--output`, since a `COMP` field routinely contains `0x0A`
  and a text-mode write would corrupt it. The image is encoded **once** and
  the same bytes go to whichever destination applies; the `--output` branch
  deliberately does *not* call `GeneratedDataset.write_records()`, which
  would encode the whole dataset a second time and hold both copies at once
  (a real ceiling on a large `--rows`, and a review finding on PR #200).
  `write_records()` itself is unchanged and still right for a caller that
  has not already encoded. `hex` is the same image annotated
  field by field (offset, length, name, PICTURE, USAGE, value, bytes), which
  is the form that survives being opened in an editor.

### `--record-format`: fixed- vs variable-length files

2. `FD ... RECORD VARYING FROM min TO max DEPENDING ON item` on the file —
   the record layout is flat and the length is simply how many of its bytes
   each record carries. Given a **whole COBOL program**, the FD clause is read
   off the record with no flag at all. Given a bare **copybook**, which has no
   FD, `--record-varying MIN:MAX` supplies the range (`MIN-MAX` is accepted
   too, since that is how it reads in the FD). The cut can fall mid-field —
   which is exactly what a program reading `REC(1:LEN)` sees — and
   `--format hex` marks the fields past it as `(past record length)` and the
   field it falls inside as `(cut N/M bytes)`. A range reaching past the
   record's own bytes is clamped to them, and one with nothing left
   (`40:50` on a 28-byte record, or equal bounds) is ignored -- both with a
   `warning:` on stderr (every format) and a `* caveat:` in the hex header
   (#274); previously both happened silently.

### Gen-Fixtures

* `--strict` exits **2** (not 1 -- that stays "could not run at all") when
  `bundle.unresolved` is non-empty: anything Phase 1's index, Phase 2's
  inventory, or Phase 3's own field resolution could not pin down -- and
  (since #244) any branch arm whose scenario's own data *violates* it. The
  CI-friendly "no silent gaps" switch.

### Selecting a program unit (`--program`)

A source file can hold several `PROGRAM-ID`s — stacked, or nested inside the
enclosing program's PROCEDURE DIVISION — and every analyzer here is
program-scoped: it grades a paragraph against the references it can see, so a
report is about ONE unit. It has always been the outermost, silently; a
contained program came back "clean" because it was never examined.

`--program NAME` (2026-09-07; on every subcommand built by
`_build_analyzer_parser`, plus `unused-variables`, `program-flow`,
`redundancy`, `lint`, `business-rules` and `lineage`) selects the unit to report on,
case-insensitively, via `CobolProgram.find_program_unit`. An unknown name
fails with the list of units that are there rather than falling back to a
report about a different program.

### Analyze

Runs `DynamicCallAnalyzer` and prints a JSON summary of dynamic `CALL`
targets only (`called_program`, `is_dynamic`, and `possible_values` when
dynamic; a dynamic entry also carries `"possible_values_incomplete": true`
when the analyzer flagged the value set as not fully resolvable — see
`.okf/analysis.md`'s DynamicCallAnalyzer section — so the list is never
silently presented as exhaustive; added in the 2026-08-16 audit). Despite
the generic name, this is *not* an all-analyzers summary —
dead code, IO, MOVE-type, linkage, and LE checks each have their own
dedicated subcommand below.

### Unused-Variables

Runs `UnusedVariableAnalyzer` (see `.okf/analysis.md`) and lists DATA
DIVISION items never referenced in the PROCEDURE DIVISION.
`--exclude-copybook-variables` filters out unused items that came from an
expanded COPY; it only has an effect together with `--copybook-path`
(otherwise a stderr warning notes the no-op) since copybook provenance is
determined by parsing the source a second time *without* expansion
(`_parse_without_copybook_expansion`) and diffing declared item names
against the expanded AST — `expand_copybooks`'s own line-tracking
(`preserve_source_locations`) doesn't work (see `.okf/analysis.md`).
With `--copybook-path`, each unused item also carries
`"origin": {"file", "line"}` from `ParseResult.expansion_source_map`
(`analysis.lint.stamp_report_origins`, 2026-09-27): `location.line` counts
lines of the expanded text, so past the first `COPY` it was not the line on
disk. `location` is left as it was.
**Origin stamping applies to every analyzer, not just this one:** since
2026-09-28 it is done once, in `_emit_report`, for every
analyzer subcommand that takes `--copybook-path` (dead-code, complexity,
health, move-type-check, xref, ...): `_parse_result_or_fail` remembers the
map on `args._expansion_source_map`. Previously only lint and
unused-variables said where an expanded-listing line really is. Additive:
no map (no `--copybook-path`), no `origin`. Locations not under a
`location` key get a sibling of their own name (2026-10-14, #367): xref's
`definition` gains `definition_origin`, program-flow's
`exit_statement_location` gains `exit_statement_origin`
(`analysis.lint._ORIGIN_KEYS`). `gen-fixtures` is *not* stamped
(its bundle uses bare `line` keys under `bundle_version`).

### Program-Flow

Runs `ProgramFlowAnalyzer` and emits the control-flow graph. `--format`
selects the output: `json` (default, raw `report.to_dict()` edges), `mermaid`
(via `generators/flowchart.py`'s `MermaidFlowchartGenerator`), or `dot`
(Graphviz DOT via `DotFlowchartGenerator`). Also accepts the shared
profiling flags (`--profile`, `--profile-top-n`, `--profile-output`);
`--profile` metrics can only be embedded in `json` output, so combining it
with `mermaid`/`dot` prints a stderr warning instead of silently
discarding the profiler result (2026-08-16 audit).

### Lint

**Columns are on-disk columns (#301, 2026-10-13).** Analyzer locations count
columns in the *normalized* text, which for a fixed-format line is columns
8-72 -- so they are 7 short of what an editor shows. `_lint_column_offset`
returns a `(file, line) -> offset` function: the program itself is judged
the way `CobolParser` decides (`--source-format`, else `detect_fixed_format`),
each copybook the way the expander judged it (`_looks_fixed_format`), and
within a fixed-format file a line after `>>SOURCE FORMAT FREE`
(`preprocess.source_format.free_format_flags`) gets no shift. The per-file table lives in
`analysis.lint.fixed_format_column_offset`: fixed listing + fixed file 7,
fixed listing + free member 0 (the expander re-pads it by exactly 7), free
listing + fixed member 6 (the expander cuts only the sequence area), free
throughout 0. Lint now **always** stamps `origin` -- without
`--copybook-path` it is the file itself, same line -- so JSON carries the
on-disk column as `origin.column` in both cases and text prints it;
`location.column` stays the analyzer's own count. Text prints only a
column it can vouch for: a parse error that reported no column
(`LintFinding.column_known` False), a copybook that cannot be re-read, or a
line the source map does not cover prints `file:line:` and has no
`origin.column`, rather than the analyzer column (7 short on a fixed line).
Known gap (predates #301): a `>>SOURCE FORMAT IS FREE` *inside a copybook*
leaves the expanded listing a column off, so those columns are off by one.
`stamp_report_origins` no longer overwrites an `origin` already present, or
`_emit_report` would drop that column again.

**Parse errors are findings** (2026-10-04, #249). A file that parses *with
errors* still yields a partial AST, and a partial AST lints quietly: a file
that was not COBOL at all used to print `0 finding(s)` and exit `0` even
under `--fail-on info`. `_cmd_lint` now runs `add_parse_errors()` (in
`analysis/lint.py`) over `result.errors` before the source map and the
severity filter: each becomes a `rule: "parse"`, `severity: "error"` finding
at the error's line/column (`kind` = the error's code or class name). So
`--fail-on` (any level) exits `3` on such a file, and the JSON and text
report say why; without `--fail-on` the run still exits `0` and the partial
findings stay usable -- option (b) of the issue, rather than a hard exit
`1`. `parse` is not in `RULES`, so `--rule` neither selects nor drops it.

`--copybook-path` does triple duty here: it expands COPY members so MOVE
operands resolve, it lets lint tell a copybook-sourced unused item (info)
from one the program declares itself (warning) via the same unexpanded-parse
set difference `unused-variables` uses, *and* (2026-09-07) it turns on
finding origins. With expansion, every analyzer location counts lines in the
expanded text; the expander's own source map turns each one back into a real
file and line, emitted per finding as `"origin": {"file", "line"}` and used
by `--format text` for its `file:line:column:` prefix. A finding inside an
inlined member therefore names the *copybook*, not the program. Findings the
map cannot place carry no `origin` key rather than a guess. Since #301
(2026-10-13) a run with no expansion **does** carry `origin` on every located
finding -- the file itself, the same line, plus the on-disk `column` -- so
"`origin` present" no longer means "copybooks were expanded"; compare
`origin.file` with `source_file` for that.

### Data-Items

Runs `compute_program_data_items()` (see [generators.md](../generators.md)'s
`layout_offsets.py` entry) and reports `{"items": [...], "unresolved":
[...]}` — byte offset, byte length, REDEFINES chain, OCCURS min/max, and
level-88 condition values for every data item across every DATA DIVISION
section (FILE/WORKING-STORAGE/LOCAL-STORAGE/LINKAGE) of the program.
Registered via `_build_analyzer_parser(..., profiling=True)`, so it takes
the standard analyzer flags plus the profiling flags (added 2026-08-14 as the
final wiring step of the data-item-layout plan).

### Decode

* **`--charset`/`--endian`/`--record-format`/`--record-separator`** mean
  exactly what they mean on `gen-data`, and are the same `EncodingOptions`.
  `--record-format auto` resolves the same way on both sides for the same
  source: variable when the layout has a DEPENDING ON table **or** the
  `--copybook` is a whole program whose FD declares `RECORD VARYING`
  (`RecordDecoder.varying`, read off `fd_clauses` in `from_record()`).
  Before 2026-09-28 decode's auto only looked at the layout, so the
  RDW-framed file `gen-data v.cbl --record-format auto` wrote was read back
  fixed-length and garbled, exit 0.
  `--record-length` is decode-only: an LRECL to cut fixed-length records at
  when the file's records are longer than the copybook describes (trailing
  slack, or a copybook covering only a prefix). With no `--record-length`
  and a whole-program source, it defaults to the FD's LRECL (the largest 01
  under the FD, or a larger `RECORD CONTAINS n`), so `--record HDR-REC` on a
  shorter 01 still frames the file right (#362); `gen-data --format
  record|hex` pads that 01 out to the same LRECL with spaces.
* **`--max-records`/`--skip`** page a large file. A run stopped by
  `--max-records` does *not* report the rest of the file as trailing bytes.
  A negative `--max-records`/`--skip`, or a `--record-length` that is not
  positive, is an error (exit 1; exit 2 on `compare`) -- 2026-09-27: a
  negative length had claimed the layout was zero bytes long, `0` was
  silently replaced by the layout length, and `--max-records -1` printed
  only a header.

### Compare

* **Exit status follows `cmp`/`diff`**: 0 equal, 1 different (including
  differing trailing partial records -- `CompareResult.trailing_differs`,
  see generators.md, #250), 2 the
  comparison could not be made (unknown key/ignore name, unreadable file,
  layout error, unwritable `-o`). `_cmd_compare` therefore uses its own
  `_compare_fail()` (exit 2) and its own output writer rather than `_fail()` /
  `_verbatim_out()`, both of which exit 1 -- which here would read as "the
  files differ". Two failures happen before `_cmd_compare` runs or outside
  its expected exceptions and used to exit 1 (2026-09-28): a `--config` /
  `cobol.yml` error (`main()` now routes it through `_config_fail()`, which
  exits 2 when the subcommand is `compare`), and a copybook that is not text
  (a `UnicodeDecodeError` traceback; now caught).

### Scan

`--analyzer` takes both the repeated and the comma-separated spelling
(`parse_analyzer_list`); one of `health`, `redundancy`, `complexity`,
`dead-code`, `unused-variables`, `lineage` (2026-10-08; the
`FieldFlowReport` `field-impact` joins), defaulting to `health,redundancy`. An
unknown name exits 1 naming the known set -- argparse `choices` would reject
the comma spelling, so the check lives in `scan_files` instead.

`--source-format auto|fixed|free` (and `--free-form`, and cobol.yml's
`project.source_format`) reach the parse through `ScanOptions.free_form` +
`ScanOptions.preprocess_fixed`, the same pair `_source_format_kwargs()`
hands every single-file subcommand. Before 2026-09-28 only `free_form` was
forwarded, so `--source-format fixed` still auto-detected and a member with
a spaced tag in columns 1-6 scanned as an `UNKNOWN` program with no
paragraphs.

### Lineage / Field-Impact

Exit codes (2026-10-08): `0` when the start was found, hits or not; `1`
when no source produced a lineage report (each problem is printed to stderr
first), when the start (FIELD / `--table` / `--dataset`) matches nothing --
the report is still printed, with `"start_found": false`, and the error
goes to stderr -- or on an argument error. Files that failed while others
parsed stay in `problems` and do not change the exit code.

### Cross-reference, signatures, codebase graph, SQL/CICS lint, diff, JCL

Seven subcommands landed together in PR #212 (`_cmd_xref`,
`_cmd_program_signature`, `_cmd_codebase_graph`, `_cmd_copybook_impact`,
`_cmd_sql_cics_check`, `_cmd_diff`, `_cmd_jcl` in `cli/parse.py`). Three
(`xref`, `program-signature`, `sql-cics-check`) are ordinary single-file
analyzers built through `_build_analyzer_parser(..., profiling=True)` and so
take the standard set (A) plus profiling; four (`diff`, `codebase-graph`,
`copybook-impact`, `jcl`) build their own parser because their arguments do
not fit that shape.

### IO coverage tools (`cobolparser/cli/coverage.py`)

`main()` returns the command's int status (no command: help, exit 1).
`status` falls back to `./io-coverage.json` only when the requested artifact
is missing *and* is not already that path (printing a `Note:`), so a stale
default artifact is never served silently. A malformed or non-object
artifact (`status`) or pytest-results file (`generate`) is a clean error with
exit 1, not a traceback (audits M10, 2026-07-08). Tests:
`tests/unit/cli/test_coverage_cli.py`, `test_coverage_cli_extra.py`.
