# Changelog

All notable changes to the COBOL parser project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

* **Cross-reference, program signatures, codebase graph, SQL/CICS lint,
  semantic diff, JCL** (PR #212, work in progress): `cobol-parser xref`
  (`analysis/xref.py`, every symbol's declaration and every reference with
  its role), `program-signature` (`analysis/program_signature.py`, the
  callee's calling interface from `PROCEDURE DIVISION USING` / `ENTRY` /
  LINKAGE with graded operand directions), `codebase-graph` and
  `copybook-impact` (`analysis/codebase.py`, whole-checkout CALL and COPY
  graph), `sql-cics-check` (`analysis/sql_cics_lint.py`, also the
  `sql-cics-check` lint rule: unchecked SQLCODE / CICS RESP, dynamic SQL
  built by concatenation), `diff` (`analysis/ast_diff.py`, structural diff
  of two program versions) and `jcl` (`cobolparser/jcl/`, DD-to-dataset
  and step-to-program resolution). Review follow-ups on the same PR:
  digit-led paragraph names (`1000-INIT`) are credited by `xref` rather
  than split; a contained program's statements, SELECTs and ENTRYs no
  longer read as the outer unit's undefined symbols or entry points;
  STRING literal words and IBM special registers (`RETURN-CODE`,
  `SQLCODE`, `EIBCALEN`, ...) are excluded from `undefined` (the latter
  with a caveat); `XrefReport.duplicate_declarations` names symbols
  declared more than once; `program-signature` reports `returning`,
  grades an operand referenced only as a CALL argument or SQL host
  variable `unknown` (never `input`), and degrades a group whose fields
  are declared in two sections to `unknown`; `codebase-graph` keys files
  by their normalized path (`./PROG.cbl` no longer yields a phantom
  program), accepts `--extension cbl` without the dot and resets its
  per-build member caches; `xref` carries unexpanded-COPY parse warnings
  as caveats; `diff` compares COMPUTE expressions, INSPECT/UNSTRING
  clauses, OPEN modes, ACCEPT sources, DISPLAY targets and EXEC SQL/CICS
  text (previously read as unchanged) and any unmodelled statement on
  its rendered text; `sql-cics-check` grades `DECLARE GLOBAL TEMPORARY
  TABLE` as executable; the JCL parser accepts an unnamed `// PROC`
  header (its keywords become the symbolic defaults, and the JOB-less
  body is a note, not an error).

* **Enterprise COBOL program-type corpus.** `tests/samples/enterprise/`
  holds one representative program per *kind* of program an Enterprise
  COBOL shop compiles -- QSAM batch with SORT, VSAM maintenance, CICS
  pseudo-conversational / channel-container / translated LINK server,
  IMS DL/I batch, IMS MPP, EXEC DLI, DB2 batch, a DB2 stored procedure,
  MQ, a called subprogram, nested programs, Report Writer, an OO class and
  its client, XML/JSON, DECLARATIVES, LE services, compiler directives, the
  6.x data clauses and a copybook-heavy program -- and
  `tests/integration/test_enterprise_program_types.py` runs every one
  through a FAIL_FAST parse with **no errors and no warnings**, every
  analyzer, the fixture generator, the whole-checkout scanner, and
  per-type trait assertions. `docs/enterprise-program-types.md` is the
  matrix. Everything below is what that corpus surfaced.
* **Object-oriented COBOL units.** `CLASS-ID ... INHERITS`, the `FACTORY.`
  and `OBJECT.` paragraphs, `METHOD-ID` (literal or bare name, with or
  without its own IDENTIFICATION DIVISION header) and `END METHOD` /
  `END FACTORY` / `END OBJECT` / `END CLASS` parse into nested
  `CobolProgram` units: `CobolProgram.unit_kind` is `"CLASS"` /
  `"FACTORY"` / `"OBJECT"` / `"METHOD"` (`"PROGRAM"` otherwise, and the
  key is only serialized when it is not), a class contains its factory and
  object units, and those contain their methods -- so `program_units()`
  enumerates every method like every nested program, and every analyzer
  runs over each. A class definition used to fail with "PROGRAM-ID is
  mandatory". `[USAGE] OBJECT REFERENCE [class-name]` is a usage
  (`CobolDataItem.object_class`) instead of two dropped tokens.
* **PROGRAM-ID attributes.** `[IS] INITIAL | COMMON | RECURSIVE`, in any
  order and number, followed by the optional word `PROGRAM`, are consumed
  and recorded (`CobolProgram.program_attributes`, `is_recursive`;
  identification-division metadata `program_attributes`). `RECURSIVE` and
  the `PROGRAM` word used to leave a "missing period" warning. The period
  after the `PROGRAM-ID` keyword is optional, as in Enterprise COBOL.
* **`PROCEDURE DIVISION ... RETURNING item`** is recorded as metadata
  `returning_parameter` instead of being appended to `using_parameters`.
* **Enterprise COBOL 6.x data clauses.** `PIC U` / `PIC U(n)` (UTF-8,
  sized in bytes), `PIC U BYTE-LENGTH n` (`CobolDataItem.byte_length`,
  also the PICTURE's size), `DYNAMIC LENGTH [LIMIT n]`
  (`is_dynamic_length`, `dynamic_length_limit`), `VOLATILE`
  (`is_volatile`) and `OCCURS UNBOUNDED DEPENDING ON`
  (`OccursClause.is_unbounded`, `max_times` None). `VOLATILE` and
  `BYTE-LENGTH` after a PICTURE used to be glued into the pattern
  (`X(8)VOLATILE`), the rest were dropped with a warning.
* **DECLARATIVES are modelled.** Every section between `DECLARATIVES.`
  and `END DECLARATIVES.` carries `CobolSection.is_declarative`
  (metadata `declarative`); the two marker lines no longer produce
  pseudo-paragraphs named `DECLARATIVES`. `USE BEFORE REPORTING group`
  records `UseStatement.report_groups`. Consumers: the dead-code analyzer
  and the program-flow analyzer take the first procedure *after* `END
  DECLARATIVES` as the entry point and treat every declarative section as
  a runtime entry (never dead, never unreachable; `FlowNode.is_declarative`),
  and `IOSequenceAnalyzer` no longer walks a USE procedure inline (a WRITE
  inside an error handler was reported as "WRITE before OPEN").
* **Out-of-line handlers the runtime invokes are references.** `XML PARSE
  ... PROCESSING PROCEDURE p [THRU q]` (new flow edge types
  `XML_PROCESSING_PROCEDURE[_THRU]`, PERFORM-shaped) and `EXEC CICS HANDLE
  AID | CONDITION | ABEND option(paragraph)` (new `CICS_HANDLE`,
  GO TO-shaped) count for dead-code, program-flow, complexity and the
  flowcharts; the handler paragraph used to be reported dead.
* **`IMSSegmentAnalyzer` reports `EXEC DLI` statements** (interface
  `"EXEC DLI"`, function code from the command word, `USING PCB(n)`,
  `INTO`/`FROM` I/O area, every `SEGMENT(...)` on the path), interleaved
  with the `CBLTDLI` calls in source order. Command-level IMS programs
  used to produce an empty report.
* **Copybook expansion inlines `EXEC SQL INCLUDE member END-EXEC`** from
  the same search path as `COPY` -- the DB2 precompiler resolves both from
  SYSLIB. A member that cannot be found (`SQLCA`, `SQLDA` -- supplied by
  the precompiler) is left as written, so the parser still sees the EXEC
  SQL statement. `CopyStatementLexer(sql_include=True)` /
  `CopyStatement.sql_include`; the un-expanding parse path is unchanged.

### Changed

* **Conditional compilation runs by default.** `>>DEFINE` / `>>IF` /
  `>>ELSE` / `>>END-IF` / `>>EVALUATE` / `>>WHEN` are evaluated in every
  parse (`parse_cobol`, `CobolParser.parse`, and after expansion), not only
  under `expand_copybooks(process_conditionals=True)`; a `>>IF` block
  used to reach the parser as unparsed content. Hyphenated symbols
  (`>>DEFINE MAX-ROWS`) are accepted -- `\w+` rejected every such name as
  malformed. Any other `>>` directive (`>>CALLINTERFACE`, `>>INLINE`, ...)
  is blanked with a warning instead of being passed to the lexer as a
  stray `>>` token pair. Directive lines ahead of the IDENTIFICATION
  DIVISION survive the pre-header skip, since IBM allows `>>DEFINE`
  anywhere.
* **`REPLACE` supports IBM partial-word pseudo-text**: `REPLACE ==:TAG:==
  BY ==WS==.` rewrites `:TAG:-ROWS` to `WS-ROWS`, the way `COPY ...
  REPLACING ==:TAG:==` does; literals are never partially replaced.
* **`JSON GENERATE ... CONVERTING item TO JSON DECIMAL | BOOLEAN`** (6.3)
  no longer ends the statement at the word `JSON`.
* **`DECLARE schema.TABLE TABLE`** (every DCLGEN member qualifies the
  table) now yields `DeclareTableStatement.table_name == "SCHEMA.TABLE"`;
  the unqualified-only pattern left it None, so `HostVariableResolver` and
  `dclgen-check` never saw a DCLGEN block placed in WORKING-STORAGE.
* **`linkage-check`** treats `DFHEIBLK` and `DFHCOMMAREA` as referenced
  (the CICS translator passes them on the USING it generates), a `SET
  ADDRESS OF item TO pointer` target and a CICS `SET(ADDRESS OF item)`
  option as references (a based LINKAGE item is addressed, not passed),
  and the `RETURNING` item as referenced.
* **`unused-variables`** never reports the fields of `DFHEIBLK` (the
  translator declares all 30-odd EIB fields; the runtime fills them) nor
  `DFHCOMMAREA` itself; its fields stay assessed.
* **`recursion-check`**: a self-CALL in a program declared `IS RECURSIVE`
  is graded `LOW` (lint `info`) with an explanation that re-entry is legal,
  not `HIGH`.
* **`SetStatement.targets_are_address_of`** marks the `SET ADDRESS OF
  target TO pointer` form (the targets are based, not assigned).
* The "Compilation unit contains N program units" warning counts every
  unit, nested ones included, instead of the primary program's direct
  children only.

* **analysis/cli:** clone detection now works **across programs**, not only
  within one. `RedundancyAnalyzer` already fingerprinted every paragraph to
  find duplicates inside a single file and then threw the fingerprints away,
  so the commoner shape of COBOL copy-paste -- a paragraph cloned into a
  *different* program, neither copy duplicated inside its own file -- was
  invisible. `RedundancyReport` gained `paragraph_fingerprints`: per
  paragraph, its Type-1 (exact) and Type-2 (renamed-identifier) digests, over
  a canonical serialization written out rather than `repr()` because the
  digest travels between processes and must be stable forever.
* **cli:** new `cobol-parser redundancy <file.cbl>` subcommand -- the full
  redundancy report (dead code, unused variables, clone groups, and the
  fingerprints nothing else exposes). Previously `RedundancyAnalyzer` was
  reachable only folded into `health`'s score and `redundancy_summary`.
* **scan/cli:** new `cobolparser/scan.py` and `cobol-parser scan FILE...` --
  run analyzers over a whole checkout in **one process**, with per-file fault
  isolation, every program unit reported (contained programs included), and
  `--clones` for cross-file clone grouping. The parse and the analysis both
  happen inside the worker and only the report dicts come back, so a worker's
  peak memory is one file's AST rather than the whole shop's. `scan_files`,
  `ScanOptions`, `ScanReport` and `cross_file_clone_groups` are exported from
  the top-level package. `--files-from` reads the file list from a file (a
  Windows command line caps at 8191 characters, so a workspace scan cannot
  put its paths on argv at all). Backs the COBOL Analyzer extension's
  Analyze Workspace.

* **preprocess/cli:** copybook expansion now reports **where every expanded
  line came from**. `expand_copybooks(preserve_source_locations=True)` builds
  a real `source_location_map` -- one `(file, original line)` per expanded
  line -- instead of the always-empty dict the flag returned before, carrying
  the origin through continuation merging (which removes lines), the COPY
  splice (which inserts them) and the re-pad's width wrap (which splits one
  into several). Exposed as `ParseResult.expansion_source_map` from
  `parse_cobol_with_expansion`, and as `cobol-parser expand --source-map`.
  A cached (diamond-dependency) member carries its origins with it, so the
  fast path and the slow path produce the same map.
* **analysis/cli:** `lint` findings say where they really are.
  `LintFinding` gained `origin_file` / `origin_line` (serialized as
  `"origin": {"file", "line"}`), filled by `lint.apply_source_map()` from the
  expander's map whenever `--copybook-path` was given -- so a finding inside
  an inlined member names the *copybook* and its line, and `--format text`
  stays clickable after expansion instead of pointing at whatever sits at
  that line number of the program. Findings the map cannot place carry no
  `origin` key rather than a guess.
* **preprocess/cli:** `cobol-parser expand --keep-comments` keeps every
  comment line's original text in the listing, in the program and in each
  inlined member. Expansion still blanks comments before it expands anything
  (a `COPY` written inside a comment must not be expanded); the text is
  restored afterwards through the same source map, only where the line is
  blank in the expansion and its origin really is a comment -- so no line of
  code and no line number changes.
* **models/analysis/cli:** program units in a multi-`PROGRAM-ID` file are
  reachable at last. `CobolProgram.program_units()` /
  `find_program_unit()` list and look them up; `--program NAME` on every
  analyzer subcommand (and `lint`) selects which unit a report covers,
  defaulting to the outermost as before; a report on such a file also carries
  `program_units` in its identification header, so it can say what it did not
  cover. **`LintAnalyzer` now lints every unit** rather than the outermost
  only -- a contained program left unexamined used to read as a clean one.
  Single-program output is unchanged, key for key.

* **dialects/cli:** a **call-signature catalogue for IBM Language Environment
  services and COBOL intrinsic functions**, and `cobol-parser le-info` to read
  it. The question it answers is the one a developer has in front of a
  `CALL "CEEDAYS"`: what has to be declared, in what order, and which operands
  may be left out.
  * New `cobolparser/dialects/le_signatures.py`: `LE_SERVICE_SIGNATURES` (33
    LE callable services) and `INTRINSIC_FUNCTION_SIGNATURES` (all 44 IBM
    intrinsics), with `le_service_signature()` / `intrinsic_signature()`
    lookups. Every operand carries its direction (input / output /
    input-output), its exact COBOL declaration, whether it may be omitted, and
    whether it repeats — plus a full WORKING-STORAGE snippet for the two
    shapes people get wrong, the halfword-prefixed string and the 12-byte
    feedback code.
  * **Coverage is partial and says so**: `services_without_signature()` lists
    the services the dialect recognises but the catalogue cannot describe
    exactly, so a consumer can distinguish "no signature catalogued" from "not
    an LE service".
  * New `cobol-parser le-info [NAME...] [--kind service|function|all]` — the
    only subcommand that reads no source file, since it dumps static dialect
    knowledge rather than analyzing a program (and therefore emits no
    `source_file` header). Backs the COBOL Analyzer VS Code extension's LE
    hover.
  * `IBMEnterpriseCobol.IBM_LE_SERVICE_INFO` is now **derived** from the
    catalogue rather than hand-maintained beside it, so the two cannot drift;
    `get_le_service_info()` keeps its shape and now answers for 37 services
    instead of 12.
  * 18 real LE services the dialect did not recognise are now detected:
    `CEEDAYS`, `CEECBLDY`, `CEEUTC`, `CEEISEC`, `CEESECI`, `CEEQCEN`,
    `CEESCEN`, `CEEFMDA`, `CEEFMDT`, `CEEFMTM`, `CEEFRST`, `CEEHDLU`,
    `CEEMOUT`, `CEE3DMP`, `CEE3ABD`, `CEE3PRM`, `CEE3GRC`, `CEE3SRC`.

* **generators/cli:** `cobol-parser decode` reads a **record image file back
  through a copybook** -- the inverse of `gen-data --format record`, and the
  half people actually have a file for. A VSAM extract, an EBCDIC flat file,
  a tape image someone FTP'd off z/OS: bytes with no self-description
  whatsoever, whose only key is the copybook that was compiled against them.
  Point the two at each other and you get a table.
  * New `cobolparser/generators/data/decoding.py`: `RecordDecoder`
    (`from_copybook_file`/`from_copybook_source`/`from_record`,
    `decode_bytes`/`decode_file`), `decode_field()` / `decode_record()`,
    `DecodedField` / `DecodedRecord` / `DecodeResult`, `decoded_hex_dump()`.
    Reads COMP-3 packed nibbles, COMP/COMP-4 big-endian binary, COMP-5 and
    the floats in the configured order, and zoned DISPLAY with the sign
    overpunched or `SIGN IS SEPARATE`, each through the same
    `storage.storage_size()` width the encoder used -- so
    `decode(encode(row)) == row`, checked against the generator cell for cell
    and CSV for CSV.
  * New `cobolparser/generators/data/views.py`: `build_record_views()`,
    `RecordViews` / `RecordView` / `PlacedField` -- the offset-annotated byte
    map, with **one view per `REDEFINES`** so an overlay can be switched
    without re-parsing the copybook (`decode --view`, `decode --list-views`).
    Offsets are a running sum of the same field widths `encode_record()`
    concatenates, so a decoded offset and an encoded byte position cannot
    drift apart.
  * Sign conventions are read more widely than they are written: every EBCDIC
    sign nibble (`A`/`C`/`E`/`F` positive, `B`/`D` negative), GnuCOBOL's
    ASCII zone, and the `{ABC`/`}JKL` overpunches an EBCDIC file picks up
    when a transfer transcodes it to ASCII.
  * Bytes that are not what the PICTURE says are **reported, not zeroed**
    (`DecodedField.error`, `DecodeResult.error_count`), as are trailing bytes
    that are not a whole record. `decode --strict` turns either into exit 1 --
    the CI form of "does this copybook actually describe this file?".
  * `--format hex` is a byte pane whose lines are the field boundaries;
    `--format json` carries every field's offset, length and raw bytes;
    `--max-records`/`--skip` page a large file; `--record-length` handles a
    file whose records carry trailing slack.
* **analysis/cli:** `cobol-parser dclgen-check` cross-checks every EXEC SQL
  host variable against the DCLGEN `DECLARE TABLE` column it binds to, and
  the same check is available as the `dclgen-check` rule of `lint`. New
  `cobolparser/analysis/dclgen_check.py` (`DclgenChecker`, `DclgenReport`,
  `DclgenViolation`), exported from `cobolparser` and
  `cobolparser.analysis`. Catches the mismatches a DB2 precompiler accepts
  and a runtime quietly acts on: a `DECIMAL(9,2)` column fetched into
  `PIC S9(7)V9` (the cents silently rounded away on every row), a `CHAR(30)`
  column truncated into `PIC X(20)`, too few integer digits for the column's
  range (SQLCODE -304, but only once a row exceeds it), a character column
  bound to a numeric item, an unsigned host variable for a signed column, and
  a nullable column fetched with no indicator variable (SQLCODE -305). What
  it cannot check it says so about, per variable, so a quiet report is never
  mistaken for a checked one.


* **analysis/cli:** `cobol-parser lint` runs several analyzers over a **single**
  parse and reports everything they found as one severity-graded list --
  previously "what is wrong with this program?" meant seven subcommands, seven
  re-parses of the same file, and seven different JSON shapes to merge. New
  `LintAnalyzer` / `LintReport` / `LintFinding` (`cobolparser.analysis.lint`,
  exported from the top-level package) re-implement no analysis: each rule is a
  mapping from an existing analyzer's report, and rule ids are the analyzer
  subcommand names themselves (`dead-code`, `unused-variables`,
  `move-type-check`, `io-sequence`, `linkage-check`, `recursion-check`,
  `complexity`). Severity is graded per finding, keeping the underlying
  analyzer's own judgement where it has one (MOVE ERROR/WARNING, recursion
  HIGH/MEDIUM, complexity rating). `--format text` emits one
  `file:line:column: severity [rule] message` line per finding -- the prefix an
  editor or build log already parses -- and `--fail-on error|warning|info`
  exits **3** when a finding at or above that severity was reported, kept
  distinct from exit 1 ("the run failed") so a CI gate can tell the two apart.
  `--rule` and `--min-severity` narrow the run and the output. The report also
  carries `caveats` (what could not be checked, e.g. MOVE operands left
  unresolved by a missing copybook) and `failed_rules` (a rule that raised
  costs only its own findings), so a quiet report is never mistaken for a
  clean program.

* **generators:** `gen-data` now also honours the *other* way a COBOL record
  varies: `FD ... RECORD VARYING FROM min TO max DEPENDING ON item`, where the
  record layout is an ordinary flat one and nothing in it says how long any
  given record is (the length travels in the RDW; the program sets the
  `DEPENDING ON` item before a WRITE and reads it back after a READ). Given a
  **whole COBOL program** the clause is read off the record with no flag at
  all -- `data_file_description.py` already parsed it, nothing consumed it.
  Given a bare **copybook**, which carries no FD, `--record-varying MIN:MAX`
  (`DataGeneratorOptions.record_varying`) supplies the range and overrides the
  FD when both exist; passing it alone reaches `--record-format auto`, since
  it is itself a statement that records are not fixed. One length per row is
  drawn uniformly across the range at *generation* time, from the same seeded
  RNG the values came from, so a seed reproduces record lengths as exactly as
  it reproduces their contents -- and so `encode_record` stays pure. The cut
  can fall mid-field, which is exactly what a program reading `REC(1:LEN)`
  sees; `--format hex` marks the fields past it as `(past record length)`
  rather than dropping them. `RECORD CONTAINS 47 TO 80` declares the same
  thing without the `VARYING` keyword and is treated identically. New API:
  `VaryingLength`, `DataGeneratorOptions.record_varying`,
  `GeneratedDataset.varying` / `.declared_lengths`, `data_length=` on
  `encode_record()` / `row_record_length()`, and `varying=` on
  `EncodingOptions.resolved_format()` / `encoding_caveats()` / `hex_dump()`.
  When a record has *both* a DEPENDING ON table and an FD range, the table
  decides and a caveat says so -- enforced both at generation (no length is
  drawn for such a record) and in the encoder (`data_length` passed directly
  is dropped), so the caveat is true on every surface rather than only on the
  generated path.

* **generators:** `gen-data --record-format fixed|variable|variable-bare|auto`
  generates **variable-length record files**, not just fixed-length ones. A
  copybook with an `OCCURS ... DEPENDING ON` table describes a record whose
  length varies with its counter; until now that table was always written at
  its maximum (RECFM=F), with a caveat on stderr saying a real record would
  be shorter. `variable` writes only the occurrences each record's own
  counter names, behind the 4-byte RDW (`LL LL 00 00`, big-endian, length
  inclusive) that RECFM=V/VB uses to delimit records; `variable-bare` writes
  the same trimmed records unframed; `auto` picks `variable` exactly when the
  layout has a DEPENDING ON table. `fixed` stays the default, so a copybook
  that cannot vary writes byte-identical output to before. The resulting
  LRECL (or range) is reported -- on stderr for `--format record`, in the
  header for `--format hex`, which also gains a `(RDW)` row per record so
  field offsets stay true. New API: `RecordFormat`,
  `EncodingOptions.record_format` / `.resolved_format()`, `encode_rdw()`,
  `minimum_record_length()`, `row_record_length()`,
  `GeneratedDataset.minimum_record_length()` / `.record_lengths()` /
  `.is_variable_length`, and `layout.OdoControl` / `present_indexes()` /
  `occurrence_count()` / `unresolved_odo_counters()`.

* **generators:** `FieldSpec` gained `odo_controls` (every `OCCURS ...
  DEPENDING ON` dimension a field sits inside -- the counter, which subscript
  position it governs, and the bounds) and `odo_counter_bounds` (the counts a
  field *controls*, when it is itself a counter). Both are additive keys in
  `to_dict()` and therefore in the fixture bundle, so `bundle_version` stays
  `1` -- see `docs/fixture-bundle-schema.md`.
  `examples/fixtures/FIXTUREDEMO.bundle.json` was regenerated for the two new
  keys; no generated value changed.

* **generators:** `gen-data --format record|hex` emits the **real record
  image** for a copybook -- the bytes a COBOL program would actually read,
  rather than the display text every existing output path produces.
  `COMP-3`/`PACKED-DECIMAL` packs into BCD nibbles with a `C`/`D`/`F` sign
  nibble, `COMP`/`COMP-4`/`BINARY` writes big-endian two's complement,
  `COMP-5` writes host byte order (that is what "native binary" means),
  `COMP-1`/`COMP-2` write IEEE 754 binary32/binary64, signed DISPLAY gets an
  overpunch or a real `SIGN IS SEPARATE` byte, and `INDEX`/`POINTER` get
  binary zeros. `--charset ebcdic` encodes DISPLAY bytes as cp037 and
  switches the sign convention with it; `--endian` (default `auto`, which
  reads the charset as intent) pins `COMP-5` and float byte order;
  `--record-separator newline` trades RECFM=F fidelity for readability.
  `--format hex` is the same image annotated field by field -- offset,
  length, name, PICTURE, USAGE, value, bytes -- which is the form that
  survives being opened in an editor. Every encoding was verified against
  GnuCOBOL by compiling a probe program and reading back its raw storage;
  the probe and its output are reproduced in the new
  `tests/unit/generators/data/test_encoding.py`. New API:
  `GeneratedDataset.to_records()` / `.write_records()` / `.to_hex_dump()` /
  `.record_length()`, `EncodingOptions`, `Charset`, `Endian`,
  `RecordEncodingError`, and `DataGeneratorOptions.for_record_image()`.

* **generators:** `FieldSpec` gained `storage_size` (the bytes an item really
  occupies, as opposed to `size`, which counts PICTURE character positions --
  they differ for every non-DISPLAY `USAGE`), plus `sign_clause`,
  `synchronized`, and `occurs_depending_on`. All four are additive keys in
  `to_dict()` and therefore in the fixture bundle, so `bundle_version` stays
  `1` and mockymock's loader reads an unchanged v1 bundle -- see
  `docs/fixture-bundle-schema.md`.

* **generators:** `Scenario.verification` -- every `"branches"`/`"all"`
  scenario now carries cobol-parser's own verdict on whether the data it
  generated actually satisfies the branch it is named for. A scenario's name
  was previously a claim nothing checked: the only way to find out was to run
  each case under a tracer. `generators/verification.py`'s
  `verify_scenario()` re-reads the scenario's OWN emitted fixture rows and
  re-checks every planned conjunct against them, independently of the solver
  that chose the values -- so a solver bug, a rendering bug, and a witness
  that never reached any fixture all surface as findings instead of a green
  label. Per-field verdicts are `satisfied` / `violated` / `absent` (no
  fixture generates the field at all, so nothing pins the branch) / `unknown`
  (a conjunct that cannot be decided from a rendered string is never silently
  reported as satisfied). `gen-fixtures` prints an unverified summary on
  stderr (stdout stays JSON-only). Additive: `bundle_version` stays `1` and
  the key is absent in `mode="happy"`.

* **parser:** REPORT SECTION is parsed instead of skipped with a warning.
  `RD report-name` clauses (`CODE`, `CONTROL(S)`, `PAGE LIMIT`, `HEADING`,
  `FIRST DETAIL`, `LAST DETAIL`, `FOOTING`, `GLOBAL`) are captured by the
  new `cobolparser.parsers.divisions.data_report_description` module onto
  every 01-level report group's `metadata["rd_clauses"]` (with the report
  name in `metadata["rd_report_name"]`); report groups are ordinary
  `CobolDataItem` trees whose `TYPE` / `LINE` / `NEXT GROUP` / `COLUMN` /
  `SOURCE` / `SUM ... UPON ... RESET ON` / `GROUP INDICATE` / `PRESENT WHEN`
  clauses land in `metadata["report_clauses"]`; an entry whose level is
  followed by a clause word (`01 TYPE IS DETAIL.`) is anonymous. A Report
  Writer program therefore parses warning-free, which the sibling
  mocky-mock repo's fail-closed gate requires before it can mock
  `INITIATE` / `GENERATE` / `TERMINATE`.
* **models:** `XmlJsonStatement.processing_procedure` /
  `processing_procedure_thru` (`XML PARSE ... PROCESSING PROCEDURE [IS] p
  [THRU q]`) and `on_exception` / `not_on_exception` statement lists (the
  same shape as `CallStatement` / `IOAcceptStatement`), all additive to
  `to_dict()`.

* **generators:** `PlannedScenario.row_witnesses` (0-based row index ->
  `{qualified field name: value}`) pins a witness to one row of a multi-row
  sequence, overriding the scenario-wide `witnesses` that applies to every
  row; `_sequence_length` grows the sequence so a pinned row always exists.
  Groundwork only -- `ScenarioPlanner` populates it nowhere, so every bundle
  is byte-identical and `BUNDLE_VERSION` is unchanged. It makes expressible a
  class of branch that was previously *inexpressible*: one reachable only
  when a prior record correlates with a following one. See
  `docs/plans/2026-09-04-cross-record-correlation-design.md`.

### Changed

* **generators:** `flatten_record()` takes `ignore_root_redefines=` (default
  `False`, so nothing existing changes). A record that itself carries
  `REDEFINES` ordinarily flattens to nothing -- right for generation, useless
  for decoding, where a redefinition is exactly the layout being asked for.
  Only the root's own clause is exempted; a `REDEFINES` nested inside the
  subtree is still excluded, so the result stays a contiguous run of bytes.
* **generators:** `CopybookDataGenerator._select_record` is now the
  module-level `select_record()` in `generators/data/copybook.py` (the method
  delegates to it and is unchanged for existing callers). Both halves of the
  package need it and they need it to agree: generating from
  `--record CUST-REC` and decoding through `--record CUST-REC` must land on
  the same 01, or a round trip through the record image silently changes
  layout.
* **analysis/generators:** scenario planning is now path-sensitive over the
  syntactic enclosing chain. `BranchConstraints.enclosing` records the
  `(branch_id, arm_id)` chain whose arms must all be taken for a decision
  point to be reached, and `ScenarioPlanner` folds those enclosing conjuncts
  into a targeted arm's own before solving. The v1 simplification -- take
  only the targeted arm's conjuncts -- was the biggest single source of
  scenarios whose data never reached their own arm: on a nested
  `IF INV-QTY > 500 / IF INV-TYPE = "AB"`, the inner arm's scenario pinned
  `INV-TYPE` and left `INV-QTY` wherever the value factory put it, so it
  usually never entered the outer arm and the scenario's name was a claim its
  data did not support. Two visible consequences: an arm that becomes
  unsatisfiable once its path condition is added is now correctly `missed`
  with that reason rather than targeted with unreachable data, and an
  enclosing arm the extractor never modeled is recorded in
  `PlannedScenario.path_gaps` (which alone makes the scenario `unverified`)
  instead of passing silently. An enclosing arm split by an `OR` is folded
  as alternatives rather than a single set -- `_register_variants` records
  `THEN#1`/`THEN#2`/... and no bare `THEN` for such a condition, so the
  planner tries each disjunct and keeps the first that stays satisfiable
  alongside the targeted arm's own conjuncts.

* **parser:** `XmlJsonStatement.clause_text` no longer includes the text of
  `[ON] EXCEPTION` / `NOT [ON] EXCEPTION` handler bodies -- those are parsed
  into the new statement lists above (a `CALL` inside `XML PARSE ... ON
  EXCEPTION` was previously invisible to `get_all_statements()` and to
  every nested-body walk). The other trailing clauses, `PROCESSING
  PROCEDURE ...` included, are still preserved verbatim in `clause_text`.
  `END-XML` / `END-JSON` are recognised as scope terminators by statements
  nested inside those handlers.

* **parser:** every COBOL verb now has a statement parser. New parsers and
  AST nodes for Report Writer `INITIATE` / `TERMINATE` / `SUPPRESS`, the
  COBOL-85 Communication Module `SEND` / `RECEIVE` / `ENABLE` / `DISABLE` /
  `PURGE`, the OS/VS legacy verbs `EXHIBIT` / `EXAMINE` / `TRANSFORM`,
  `ENTER`, COBOL-74 `NOTE`, Micro Focus `CHAIN`, the IBM compiler-directing
  statements `READY TRACE` / `RESET TRACE` / `SERVICE LABEL` / `SERVICE
  RELOAD` / `TITLE`, and COBOL 2002 `RAISE` / `RESUME` / `VALIDATE`
  (`cobolparser.parsers.statements.report_writer_parsers` /
  `communication_parsers` / `legacy_verb_parsers` / `exception_parsers`;
  nodes in `cobolparser.models.statements.report_writer` / `communication`
  / `legacy` plus `RaiseStatement`, `ResumeStatement`, `ValidateStatement`).
  Each used to be discarded with an "unsupported statement" warning; the
  warn-and-discard path now only covers the non-verbs `EXECUTE`, `GOTO`,
  `RECOVER`.
* **models:** `SetStatement.groups` (additional target/value groups of a
  multi-group `SET`), `IOOpenStatement.no_rewind` / `with_lock` /
  `reversed_mode`, `IOAcceptStatement.on_exception` / `not_on_exception`;
  `PerformStatement` / `GoStatement` / `AlterStatement` record a
  section-qualified target's qualifier in `metadata["target_qualifier"]`;
  a subscripted dynamic `CALL WS-PGM (IDX)` keeps the bare name in
  `called_program` and the full reference in
  `metadata["called_program_reference"]`. All additive to `to_dict()`.

### Fixed

* **preprocess:** `suggest_similar_copybooks`'s did-you-mean pool no longer
  includes non-copybook files. It called `get_available_copybooks` with
  `CopybookSearchPath`'s own `extensions` default, which is deliberately
  broad for *resolution* (`.cpy`/`.cbl`/`.cob`, plus a trailing `""`
  meaning "any extension") -- but wrong for a *suggestion*: a program
  referencing a missing copybook in its own directory would get its own
  `.cbl` file suggested back as a "did you mean." A new
  `suggestion_extensions` parameter (default `.cpy`/`.CPY` only) narrows
  the candidate pool for suggestions specifically; actual copybook
  resolution is unaffected, and the old broad pool is still available by
  passing `suggestion_extensions=search_config.extensions` explicitly.
  Reported from mocky-mock's own examples (`ACCTMNT.cbl` referencing a
  missing `ACCTMAST` copybook suggested `ACCTMNT`); see
  mocky-mock's `docs/2026-09-15-copybook-discovery-defaults-design.md`.
* **preprocess:** `validate_copybook_content`'s "may be missing terminating
  period" check no longer fires on a data-description entry written across
  several lines. The check matched one *physical* line ending in a `PICTURE`
  clause, but an entry is one COBOL sentence and routinely spans lines --
  `05 WS-B PIC X(30)` followed by `VALUE 'TEXT'.` is correct, terminated
  source. Every such pair was reported as unterminated, so a copybook of
  legal `PIC`/`VALUE` entries read as a copybook of errors (8 spurious
  warnings on one sample member, and these warnings are rendered into the
  header of the expanded listing by downstream consumers). The unit examined
  is now the whole entry -- its first line through to the line that starts
  the next one -- so a genuinely unterminated entry is still flagged,
  including one that spans lines and ends without a period. Blank lines do
  not close an entry, since `remove_comment_lines` has already blanked any
  comment sitting inside one. Entry-start detection and the
  is-this-a-PICTURE-entry predicate share one definition of an entry head,
  so a single-digit level (`5 FIELD-B`, legal COBOL) is both able to close
  the entry above it and checked for its own missing period.
* **preprocess:** continuation lines no longer collapse the line count.
  `normalize_fixed_format` merged N physical records into one logical line
  and emitted nothing for the other N-1, so every location after the first
  continued literal in a program -- tokens, statements, data items, lint
  findings, parse errors -- was off by the number of continuation records
  seen so far. It now emits one empty placeholder per absorbed record after
  the logical line, so the output always has exactly as many lines as the
  input; the logical line keeps its first record's number. The same
  mechanism lets a comment or blank line interrupt an open continued literal
  without severing it (the next `-` record rejoins it, as IBM specifies).
  `*>` inline comments are skipped by the quote-state scan (an apostrophe in
  one used to raise "Unterminated string literal"), `keep_comments` COMMENT
  tokens carry physical line numbers, `normalize_fixed_format` accepts a
  single string, and an unterminated `X"..."` literal warns like a plain
  one. Cython mirror regenerated; pure-vs-Cython parity verified.
* **preprocess:** copybook expansion handles free-form programs (it sliced
  columns 8-72 off every line, chopping `IDENTIFICATION` to `FICATION`) and
  tab-indented members (no tab expansion, so `\t01 REC.` became `AB-REC.`
  with zero errors). A continued literal through the expansion path kept its
  trailing blanks and its quote parity (a `"` inside a `'...'` literal no
  longer flips the state; CRLF sources no longer lose the literal's tail).
  A `COPY` (or `REPLACE`) inside a `*>` inline comment is no longer
  expanded. `COPY ... REPLACING` text containing a backslash is inserted
  literally instead of being read as a regex template (`\T` raised
  `re.error`). The module-level file cache re-reads a copybook whose
  mtime/size changed instead of serving stale content to a long-lived
  process. `>>IF`/`>>DEFINE` directives are recognised in a
  sequence-numbered program, and `>>DEFINE X AS 2 OVERRIDE` / `AS OFF` /
  `AS PARAMETER` are evaluated instead of storing `"2 OVERRIDE"` as the
  value. `CobolParser().parse()` on free-form source no longer fails with
  "No recognizable COBOL division found near 'ICATION'".
* **parsers:** a level-77 item that followed an 01 group was nested under
  the group's deepest open item (149 of 459 NIST programs); 01 and 77 now
  always start a new top-level entry. `RETURN ... AT END stmt.` swallowed
  every following statement into `at_end_clause`. `88 X VALUES [ARE] ...`
  dropped every value. `USAGE [IS] DISPLAY` warned "content dropped".
  `PIC S999 LEADING SEPARATE` (no `SIGN` word) was glued into the picture
  string. `INSPECT` on a subscripted or reference-modified target dropped
  its whole TALLYING/REPLACING clause; figurative operands
  (`REPLACING LEADING SPACES BY ZEROS`) came out empty and a second
  `x BY y` pair under one `ALL` was lost. `STRING`/`UNSTRING` truncated
  subscripted and reference-modified operands and read a bare `POINTER` as
  an operand. `IF NOT (A = 1 AND B = 2)`, `IF NOT A = 1` and abbreviated
  combined conditions (`IF A = 1 OR 2 OR 3`) built corrupt condition trees
  (a unary `NOT` node and subject/operator expansion now exist).
  `CLOSE F1 REEL FOR REMOVAL` fabricated files named `FOR` and `REMOVAL`.
  `SEARCH ... WHEN` conditions re-quote literals; an `EVALUATE WHEN`
  selector that is a bare identifier carries `"identifier": true`. A data
  name on the line after its level number and `,`/`;` separators between
  clauses (`OCCURS 15 TIMES, INDEXED BY IN1`) are accepted.
  `SET p TO ENTRY 'X'` keeps the literal; `PERFORM P1 THRU P2 OF S1` keeps
  the THRU qualifier. `COMPUTE X = 2 ** 3 ** 2` parses left-associatively
  (64, as IBM evaluates same-level operators), not as `2 ** (3 ** 2)`.
* **models:** `PIC N(n)` and `PIC G(n)` occupy 2 bytes per character;
  P-scaled pictures (`9(3)PPP`, `SVPP9(3)`) are sized by their stored
  digits with the `P` positions reflected in the digit counts; floating
  insertion strings (`$$$,$$9`, `$Z,ZZ9`) no longer count their leftmost
  symbol as a digit, so generated values fit the picture. `88 X VALUE -9
  THRU -1` keeps the range (the `THROUGH:` marker was dropped after a signed
  end).
* **analysis:** `recursion-check` reported the canonical priming-read loop
  (`MAIN` performs `1000-READ` and `2000-PROCESS`, which performs
  `1000-READ` again) as an unconditional infinite loop -- a lint `error` --
  because the CFG's fall-through edge out of a PERFORM range end closed a
  cycle that cannot execute. `DeadCodeAnalyzer` credited everything after
  an `xxx-EXIT` paragraph as reached whenever that paragraph was a `GO TO`
  target inside its `PERFORM ... THRU` range. `IOSequenceAnalyzer` could
  never report `WRITE_BEFORE_OPEN`/`REWRITE_BEFORE_OPEN` (WRITE carries a
  record name, never a file name; it now resolves the record through the
  FD) and never walked SORT/MERGE INPUT/OUTPUT PROCEDUREs. `IOLogger`
  logged the first OPEN mode for every file of a multi-file OPEN and `None`
  as every WRITE/REWRITE target. `UnusedVariableAnalyzer` reported items
  referenced only by `FILE STATUS`, `RECORD KEY`, `ALTERNATE RECORD KEY`,
  `RELATIVE KEY`, `PASSWORD`, `RECORD VARYING ... DEPENDING ON` or `LINAGE`.
  `MoveTypeChecker` now applies IBM's integer/non-integer distinction: a
  non-integer numeric item moved to an alphanumeric or alphanumeric-edited
  item is an error, as is alphanumeric-edited to numeric. Same-named
  paragraphs in different sections no longer shield each other in the
  dead-code report. `LintAnalyzer` keeps one located finding per program
  unit for `UNREFERENCED_LINKAGE`. The unary `NOT` condition renders as
  `NOT (...)` in program-flow condition text.
* **analysis (gen-fixtures):** a signed literal in a condition
  (`IF X = -5`, `WHEN -9 THRU -1`) was stored as `- 5` and silently dropped
  by the solver, which then returned the picture midpoint as a witness and
  counted the arm targeted; the sign is reattached and a literal a numeric
  field cannot hold is `Unsatisfiable` with a reason. `ConstantFolder` kept
  stale values across group-level writes (`MOVE ... TO group`,
  `INITIALIZE`, `MOVE CORR`, `READ INTO group`, `ACCEPT group`,
  `CALL USING group`), through statements that overwrite their target
  (READ record fields, ACCEPT, `EXEC SQL ... INTO`, STRING/UNSTRING INTO,
  a reference-modified MOVE target), through a `REDEFINES` alias, and
  ignored `JUSTIFIED RIGHT`. A text witness truncated to the field width
  was returned as satisfying (`IF X1 = 'AB'` on `PIC X` is Unsatisfiable).
  A CALL argument read only in an IF/EVALUATE/PERFORM UNTIL condition is
  now seen as a read (`IN`, `caller-dataflow`).
* **generators:** `VALUE ALL '-'` generated the text `ALL ` instead of
  `----`.
* **cli:** `unused-variables` and `program-flow` accept `--program NAME`
  like every other analyzer subcommand (the VS Code extension passed it and,
  on the "unrecognized arguments" error, silently re-ran without it, so the
  inner unit's report was really the outer's). `parse --stats` and
  `batch --stats` reported `lines_processed: 0` for every file (the parser
  only ever set `lines_parsed`). `parse` on a multi-`PROGRAM-ID` file now
  carries `program_units` like the analyzers. `batch --workers 0` is a clean
  usage error instead of a traceback; so is `coverage render` on a JSON
  array. `lint --format text --profile` warns that the profile has nowhere to
  go instead of dropping it. `CobolParser(serialization_config=...)` is
  honoured by `to_dict()`/`to_json()` (it was stored and never read),
  `compact_format=True` produces one line, and
  `include_source_locations=False` strips every nested `location`, not
  just the program's. `IBMEnterpriseCobol.get_intrinsic_function_signature`
  knows all 44 intrinsics (it had a five-entry table; the historical
  `return_type`/`parameters`/`description` keys are kept). A copybook that
  cannot be found (or expands circularly) under `--copybook-path` is a
  one-line `error:` on stderr with exit 1, not a traceback -- the VS Code
  extension reads that line to say why lint could not run. `--version`
  reports the released version (`__version__` had been left at 1.8.0; it is
  now a release-please extra-file so it cannot drift again).

* **preprocess:** the COPY splice no longer indents a member's first line by
  the `COPY` statement's own indentation. A member's lines are whole source
  records in the columns its author wrote; splicing at the `COPY` keyword
  prepended that statement's leading blanks to the first of them, so a
  copybook that puts its `01` in Area A came out with it in Area B -- and a
  far-right `COPY` pushed the line past column 72, where the re-pad's width
  fitter squeezed its interior blanks out (emitting text that differed from
  the member's, character for character) or wrapped it onto an extra physical
  line, shifting every following line number in the expansion. The splice now
  reclaims the whole record whenever the `COPY` owns it alone, and still
  starts at the keyword when the parent has real text before it on that line.
  Affects `cobol-parser expand` (and the COBOL Analyzer extension's
  "Show Expanded Source" / "Save Expanded Source As...", whose whole value is
  being a listing a compiler would accept); the parse itself was unaffected
  except where the width fitter's wrap had shifted line numbers.

* **dialects:** `CEECZST` is categorised as a `storage` service (it
  reallocates heap storage, per the LE reference), not a `string` one.

* **analysis:** `ConstraintExtractor` no longer treats a **non-literal
  comparison operand as a literal value**. `IF WS-IN = WS-E (IDX)` became
  `WS-IN eq 'WS-E ( IDX )'` -- a constraint on the operand's own source text,
  which the program never expressed. The layout index cannot resolve a
  subscripted reference, so the extractor fell through to its "the right side
  is a literal" branch; the sibling case where *both* operands resolve was
  already refused. Consequences, all silent: nothing landed in `unsupported`,
  `ScenarioCoverage` counted the arm **targeted**, and because the negated arm
  reduced to "any value != that text", `generators/verification.py` stamped it
  **`verified`** -- it re-checks the same fabricated constraint, so it is
  downstream of the defect rather than independent of it. Operands are now
  whitelisted (quoted or numeric), and everything else is reported as
  unsupported, putting the arm in coverage as `missed` with a reason. The same
  hole in the `EVALUATE` selector path is closed too: the lexer unquotes a
  selector before it reaches the extractor, so `WHEN "AB"` and `WHEN WS-OTHER`
  arrive indistinguishable, and whether the value names a real data item is
  now the discriminator. `SEARCH WHEN` / `EVALUATE TRUE` selector *text* is
  already unquoted by the lexer, so it keeps a looser test (a bare word may be
  a literal; a subscript or expression may not). Found by a repo audit; see
  `reports/audit-2026-09-07.md` (H1) and
  `tests/regression/test_audit_2026_09_07.py`.

* **analysis:** `domains.solve()` no longer returns a **witness that does not
  satisfy the constraint it was solved for**. `_apply_text` ended in
  `return True` for every op it did not model, which reads as "domain still
  satisfiable", so `solve()` went on to pick a value: `IF WS-TXT IS NUMERIC`
  over a `PIC X(10)` field returned `'XXXXXXXX'` -- for the `THEN` arm, which
  it fails, *and* for the `ELSE` arm, which it passes. Two scenarios that the
  field's value is the only thing distinguishing got byte-identical data.
  Class conditions are now modelled properly (an alphanumeric field can hold
  digits, so `THEN` gets a digit string and `ELSE` letters), and ordering ops
  on a text domain -- which an allow/deny set genuinely cannot express --
  return `Unsatisfiable` with a reason that reaches `ScenarioCoverage`. A
  rendered witness is re-checked against the class test before it escapes,
  mirroring the existing numeric guard. See `reports/audit-2026-09-07.md`
  (H2).

* **analysis:** `UnusedVariableAnalyzer` no longer reports four kinds of
  *referenced* data item as unused -- false positives on correct code, in both
  the `unused-variables` subcommand and the `unused-variables` lint rule:
  * `STRING` / `UNSTRING ... DELIMITED BY <identifier>`: both statements keep
    the delimiter in a `delimiters` list that never reaches `.operands`, so a
    delimiter held in a variable looked unreferenced.
  * `CALL 'SUB' USING <group>`: the group is consumed field by field by code
    this analyzer cannot see, so its children are used. Propagation ran child
    -> parent only. Deliberately scoped to CALL arguments: `MOVE SPACES TO
    WS-GRP` really does leave `WS-CHILD` never individually referenced, and
    that finding is kept.
  * REPORT SECTION `SOURCE` / `SUM` / `CONTROL`: a Report Writer program names
    these fields in its report groups, never in its PROCEDURE DIVISION, so
    scanning only the PROCEDURE DIVISION reported *every field of every such
    program* dead. Those clauses became parseable in #196; the analyzer had
    not caught up. See `reports/audit-2026-09-07.md` (M1).

* **analysis:** `ConstraintReport.unsupported` now carries branch-level gaps
  as well as program-level ones. It is documented -- in `CLAUDE.md`, in the
  module docstring and in the public examples -- as the place gaps are never
  silently dropped, but anything a *branch* could not model lived only on
  `BranchConstraints.unsupported`, so a caller following the documented API
  saw a clean list for a program with unmodelled branches. Entries stay on
  their branch too, and duplicates are collapsed. (M2)

* **generators:** `RecordDecoder` frames fixed-length records at
  `RecordViews.framing_length` rather than the base view's own length. A
  `REDEFINES` entry wider than what it redefines -- which COBOL forbids below
  level 01 but compilers accept, growing the record -- left the decoder
  cutting at the base length and shredding every record after the first;
  `data-items` already reserved the widest slot member, so the two disagreed
  in a case both modules' docstrings claim they cannot. `build_record_views`
  now says so in `RecordViews.caveats`. In the same area, a record with an
  `OCCURS ... DEPENDING ON` table now sets `offset_ambiguous` on the **base**
  view: the flag existed but only overlays could ever carry it, so
  `decode --list-views` reported a maximum-length guess as a fact for exactly
  the fields `data-items` reports as `byte_offset: null`. (M4)

* **ci:** the test suite now runs on every PR. `build` installed `.[dev,fast]`
  -- pytest included -- and never invoked it, so 9,400 tests and the
  `--cov-fail-under=90` floor were unenforced on every push and PR alike
  (`.okf/tests.md` described a `test` job gated on `workflow_dispatch`; no
  such job was ever in `ci.yml`). pytest runs in `build` after `build_ext`,
  so CI exercises the Cython extensions it was building and never running a
  line through, and a new `coverage` job enforces the 90% floor on a
  pure-Python install -- coverage.py cannot see into a compiled extension, so
  the same suite reports 54.32% with them built and 91.76% without. (M3)

* **tests/ci:** the two absolute nodes/sec assertions in
  `tests/performance/test_factory_performance.py` now skip when a tracer is
  active. Wiring the suite into CI surfaced them immediately: under
  coverage.py's tracer the same suite takes 950 s instead of 94 s, and
  `test_factory_throughput` measured 64,243 nodes/sec against its 100,000
  floor -- a number describing the tracer, not the factory. Not a
  quarantine: the `build` matrix runs the file uninstrumented on 3.11, 3.12
  and 3.13 for every PR, which is the only condition where an absolute
  throughput floor means anything, and it passes there. The ratio-based
  overhead assertion is unaffected and still runs under coverage.

* **generators:** `RecordViews.to_dict()` (and therefore
  `decode --list-views`) now reports `framing_length` alongside
  `record_length`. It carried only the base view's span, so for the one
  layout `framing_length` exists for -- a `REDEFINES` wider than what it
  redefines -- a consumer reading the serialized form framed records on a
  number the decoder itself does not use. The same mismatch the property was
  added to remove, one surface over. Found by Copilot review on #208.

* **generators:** `verification._values_for` no longer lets an unrelated
  boundary's same-named field satisfy a scenario's verdict. It matched on
  bare `spec.name` across every fixture and pooled the values; a qualified
  match now wins, and the bare-name fallback is taken only when the name is
  unambiguous across the whole scenario. The failure direction was a false
  `satisfied`, which is the one verdict this module exists not to produce.

* **generators:** a generated `OCCURS ... DEPENDING ON` counter is now drawn
  from the table's own `OCCURS min TO max` bounds instead of from its
  PICTURE's full range. A `PIC 9(4)` counter for a table of at most 50 could
  previously generate a value like 8 731 -- a record no COBOL program could
  read, in the fixed-length output too. A declared `VALUE` or level-88 value
  still wins when it names a count the table can hold, and is overridden when
  it does not. This changes the generated values (and so the bytes) for any
  copybook containing a DEPENDING ON table, at a given seed.
* **models:** `CobolDataItem.calculate_size()` reported the wrong byte width
  for six kinds of data item, and now defers to `storage_size` -- the same
  single authority `generators/data/{layout,encoding,layout_offsets}.py`
  already used. `PIC S9(9) BINARY` and `... COMPUTATIONAL` reported 9 bytes
  instead of 4 and `PIC S9(7)V99 COMPUTATIONAL-3` reported 9 instead of 5
  (the usage branches knew only the `COMP`/`COMP-4`/`COMP-3` spellings);
  `COMP-1`, `COMP-2` and `USAGE INDEX` all reported **0** (every usage branch
  sat behind an `is_elementary_item()` guard, which requires a PICTURE that
  none of those three carries -- and a zero-width item silently collapses
  every byte offset after it); a group added its `REDEFINES` children on top
  of what they redefine instead of sharing one slot (`05 A PIC X(10)` plus
  `05 B REDEFINES A` came back as 20 bytes, not 10); and a group's own
  `OCCURS` multiplier was never applied (`05 ROW OCCURS 5 TIMES` of a 4-byte
  group came back as 4 bytes, not 20). The value is published as
  `calculated_size` on every data item's `to_dict()` and as the record `size`
  of `gen-data --list-records`, so each of these was a wrong number in a
  consumer-visible API. The implementation moved to `cobolparser/_storage.py`
  (beside `_errors.py`, and dependency-free for the same reason -- importing
  `generators.data.storage` from a model would close an import cycle);
  `generators/data/storage.py` is now a re-export shim and its existing
  importers are unaffected.

* **analysis:** `DeadCodeAnalyzer` reported **no dead code at all** for the
  most common COBOL program shape -- a `MAIN` paragraph of `PERFORM`s
  followed by the paragraphs it performs. The fall-through pass credited an
  implicit edge out of any procedure in `_referenced_names`, which includes
  `PERFORM`, `PERFORM ... THRU` and SORT/MERGE procedure targets; a `PERFORM`
  returns to its caller at the end of its range rather than running on into
  the next paragraph, so every unreferenced paragraph sitting after a
  performed one was kept alive by an edge that cannot happen at runtime.
  Fall-through now propagates only out of a *fall-through source* -- the
  entry point, an `ENTRY` paragraph, a `GO TO`/`ALTER` target, or something
  already reached by falling in -- tracked separately from plain reference
  marking. `PERFORM A THRU C` still marks its whole range referenced, and
  still does not escape past C.

* **tests:** `tests/test_all_samples.py` collected zero tests despite being
  the documented smoke test for the COBOL sample corpus -- it held only
  helper functions, none named `test_*`. With nothing checking the corpus,
  32 lines across 13 sample programs had drifted past column 72, the end of
  Area B in fixed-format COBOL, 30 of them carrying real code or comment
  text. Columns 73+ are discarded before lexing
  exactly as a compiler discards them, so the truncation was silent: the
  parser saw `WS-EXCEPTION-MSG` as `WS-EXCEPTION-M`, data items lost their
  terminating period, and `complex_data_structures.cbl` was left with an
  unterminated literal that failed to parse outright. Those samples are
  inputs to the wider suite, so a large number of tests were asserting
  against programs that were not the programs on disk. All 32 lines are
  fixed without changing a token, and `TestSampleCorpus` now pins both the
  column rule (failing only on non-whitespace past column 72, and reporting
  the discarded text) and a clean parse for every sample.


* **generators:** `USAGE INDEX` was sized as **zero bytes** in
  `layout_offsets` (it carries no PICTURE, so it fell through to a
  picture-derived width), silently collapsing the byte offset of every item
  after it in the record -- visible in `cobol-parser data-items` and in
  anything built on it. A DISPLAY item with `SIGN IS SEPARATE` was likewise
  under-reported by one byte. Both are fixed by the new
  `generators/data/storage.py`, which is now the single authority on storage
  width for the whole package: `layout.py`, `layout_offsets.py`, and the new
  `encoding.py` all defer to it, so a record image's field widths cannot
  drift apart from the offsets `data-items` reports.

* **generators:** `gen-data` emitted a random 9-digit number for a
  `USAGE INDEX` or `USAGE POINTER` field, which looked like data but is an
  occurrence number and an address respectively. They now generate `"0"`,
  without drawing from the RNG -- so a copybook containing neither still
  produces byte-identical output for a given seed.

* **analysis:** a level-88 bare condition-name constraint is now scoped to
  *that* condition name's own VALUEs, via the new
  `ProgramLayoutIndex.condition_values()`. It previously used
  `FieldSpec.condition_values` -- the union of every 88 declared under the
  parent field -- so every arm of an `EVALUATE TRUE / WHEN <88>` chain
  produced a byte-identical `in_set` constraint, the solver picked the first
  88's value for all of them, and the scenario `gen-fixtures` named for the
  second arm was seeded with the first arm's value and never reached the
  branch it was named for.
* **analysis:** `EVALUATE`'s `WHEN OTHER` arm is now constrained as the
  negation of every prior arm (one `not_in_set`) when every arm is a single
  `eq`/`in_set` test on the same field, instead of always being left
  unconstrained. Unconstrained was not neutral: an unconstrained level-88
  field is generated by drawing from its own `condition_values`, so every row
  of the OTHER scenario carried one of the values that arm excludes and could
  never reach its own branch. Shapes that need a real disjunction still stay
  unconstrained, but now record why in the branch's `unsupported` list.
* **analysis:** `domains.solve()` treats the level-88 enum as a *preference*
  rather than the field's domain. A `not_in_set` covering every declared 88
  value (what a `WHEN OTHER` arm negates to) used to empty the enum and
  report `Unsatisfiable` for a perfectly reachable branch; it now falls back
  to the PICTURE-derived domain and re-applies the constraints. `in_set` /
  `not_in_set` are enforced explicitly on a numeric domain for that fallback
  path rather than no-op'd, so a witness can never silently violate a set op.
  A genuine contradiction is still `Unsatisfiable`.

* **parser:** `ExecCicsStatement` and `ExecImsStatement` are now
  `CobolStatement` subclasses, so `CobolProgram.get_all_statements()`
  returns EXEC CICS / EXEC DLI statements (they were silently omitted from
  that walk). `node_type` (`EXEC_CICS` / `EXEC_IMS`) and `to_dict()` are
  unchanged.
* **parser:** silent statement drops -- `GO TO` with its target on the next
  line lost the target; the optional `ON` / `AT` of `SIZE ERROR`,
  `EXCEPTION`, `OVERFLOW`, `AT END`, `END-OF-PAGE` phrases was not
  recognised, so the handler body escaped to the enclosing paragraph;
  `MOVE` silently consumed any non-identifier token after its targets;
  `ACCEPT ... [ON] EXCEPTION` bodies escaped the same way.
* **parser:** a string literal spelled like a verb (`IF X = "IF"`,
  `STRING "IF" ...`, `WHEN "ELSE"`, `FUNCTION LENGTH("IF")`) no longer
  truncates the condition or operand list; CALL handler bodies stop at the
  enclosing `ELSE` / `END-IF` / `END-PERFORM`; `,` / `;` statement
  separators are skipped instead of reported as dropped content; `XML
  GENERATE ... SUPPRESS WHEN ...` keeps its SUPPRESS clause; `IF A EQUAL
  TO B` records `right_operand` `B` (not `TO B`) and `GREATER [THAN] OR
  EQUAL [TO]` is one operator.
* **parser:** clause forms from the NIST suite that were reported as
  unparsed: multi-group `SET`, `OPEN`/`CLOSE` `[WITH] NO REWIND` / `LOCK` /
  `REVERSED`, `PERFORM id TIMES`, `PERFORM WITH TEST AFTER VARYING`, bare
  `TEST BEFORE`, subscripted `VARYING` variable, `START ... KEY IS = / >=`
  and `KEY GREATER OR EQUAL`, `DISPLAY` of qualified and 1-2 digit numeric
  items, `GO TO ... DEPENDING ON` subscripted, `PERFORM` / `GO TO` /
  `ALTER` section-qualified targets, `READ ... WITH LOCK KEY IS`, `ACCEPT`
  qualified / subscripted targets and `MESSAGE COUNT`, `CALL ... USING`
  numeric literals / `ADDRESS OF` / subscripted arguments, `STOP ZERO`,
  `WRITE ... ADVANCING ZERO`, multi-group `ALTER`, `OPEN INPUT A, B`.

* **cli:** `--source-format {auto,fixed,free}` (default `auto`) on the
  subcommands that parse or lex a program directly — `parse`, `tokenize`,
  `preprocess`, the analyzer subcommands (`analyze`, `dead-code`,
  `complexity`, `health`, ...), `unused-variables`, and `program-flow` —
  as an explicit override for layouts the detector cannot infer in either
  direction: `fixed` always normalizes (stripping columns 1-6 whatever
  they hold), `free` never does. `batch`, `expand`, `gen-data`, and
  `gen-fixtures` do not take the flag (their underlying APIs expose no
  layout override yet) and always auto-detect. The pre-existing
  `--free-form` flag keeps its historical, weaker semantics — a hint that
  auto-detection may still override by normalizing source it classifies
  as fixed-format — rather than becoming an alias for the new hard
  override; the two flags are mutually exclusive. `_tokenize_source` and
  `CobolParser` gained matching `preprocess_fixed` parameters so
  `tokenize` and `parse` agree under a forced layout, including on the
  unterminated-literal recovery path (the forced-fixed decision survives
  deferral instead of being re-detected away) and under an explicit
  `preprocess_fixed=False` with `free_form` unset. `preprocess` under
  `auto` now actually detects instead of normalizing unconditionally, so
  genuine free-form input is no longer mangled by default.
* **analysis/cli:** `RecursionRiskAnalyzer` (`cobolparser.analysis.recursion_risk`)
  detects recursion-driven infinite-loop risks: out-of-line PERFORM cycles
  and GO TO cycles (reusing `ProgramFlowAnalyzer`'s `cycle_details`, graded
  `HIGH`/`MEDIUM` by whether any paragraph in the cycle has an escape route
  — a branch outside the loop or a program-terminating statement), and
  self-recursive CALL statements (static or dynamic, resolved via
  `DynamicCallAnalyzer`, targeting the program's own PROGRAM-ID). Backed by
  the new `recursion-check` CLI subcommand and exported from both
  `cobolparser.analysis` and the top-level `cobolparser` package.
* **analysis/cli:** `ComplexityAnalyzer` (`cobolparser.analysis.complexity`)
  computes per-paragraph/section McCabe cyclomatic complexity from a
  dedicated statement-tree walk, plus an AND/OR-aware `extended_complexity`,
  max nesting depth, fan-in/fan-out (from `ProgramFlowAnalyzer`'s edges),
  and LOW/MODERATE/HIGH ratings via overridable `ComplexityThresholds`.
  Backed by the new `complexity` CLI subcommand.
* **analysis/cli:** `RedundancyAnalyzer` (`cobolparser.analysis.redundancy`)
  combines `DeadCodeAnalyzer`/`UnusedVariableAnalyzer` ratios with new
  whole-paragraph duplicate-code (clone) detection — Type-1 (exact) and
  Type-2 (renamed-identifier) matches via a structural statement
  fingerprint, with no sub-paragraph or near-miss similarity scoring.
* **analysis/cli:** `TechnicalDebtAnalyzer`
  (`cobolparser.analysis.technical_debt`) computes a composite 0-100
  technical-debt score (A–F grade) combining complexity, redundancy,
  control-flow smells (GO TO density, ALTER usage, no-escape recursion
  cycles, unreachable nodes), and procedure size, as a
  `DebtWeights`-weighted, fully explainable rollup with a `top_offenders`
  list naming the worst procedures and why. Backed by the new `health` CLI
  subcommand. All three new analyzers/subcommands are exported from both
  `cobolparser.analysis` and the top-level `cobolparser` package,
  single-program scope only (matching every other analyzer).
* **analysis/cli:** `UnusedVariableAnalyzer` (`cobolparser.analysis.unused_variables`)
  detects DATA DIVISION items (FILE/WORKING-STORAGE/LOCAL-STORAGE/LINKAGE)
  never referenced anywhere in the PROCEDURE DIVISION, including group
  items (used-if-any-descendant-used), level-88 condition names, REDEFINES
  propagation, and OCCURS ... DEPENDING ON. Backed by the `unused-variables`
  CLI subcommand, whose `--exclude-copybook-variables` flag filters out
  items that came from an expanded COPY (`--copybook-path`) — determined
  by diffing declared items against an unexpanded parse of the same
  source, since `expand_copybooks`'s own `preserve_source_locations`
  line-tracking is not implemented upstream.
* **api:** `CobolParseError` is exported as a backward-compatible alias of
  `ParseError` — the backend integration contract historically referred to
  the canonical parse exception by that name, which never resolved.
* **tooling:** the `.claude/settings.json` `PostToolUse` OKF-reminder hook
  documented in CLAUDE.md is now actually checked in (`.gitignore` gained a
  scoped exception), and `.githooks/pre-commit` is committed with its
  executable bit so git runs the OKF staleness check instead of silently
  skipping a non-executable hook.
* **ci:** ruff/black/mypy versions in the lint and typecheck jobs are
  pinned to match `.pre-commit-config.yaml`, so a new formatter release
  can no longer break CI without a deliberate version bump.

### Fixed

* **tests/generators:** the closed-source release wheels (Linux, macOS,
  Windows) failed `cibuildwheel`'s post-install test step across all three
  platforms, blocking `publish`/`publish-pypi`. Two independent bugs, both
  only visible under `cibuildwheel`'s test-command (never under
  `pytest tests/` from the repo root, which is why the normal dev/CI loop
  never caught either):
  * `tests/unit/test_program_fixtures.py`'s `FILE_OPERATIONS`/
    `SUBPROGRAM_DEMO`/`IBM_EXTENSIONS` constants were `cwd`-relative
    strings (`"tests/samples/....cbl"`). `cibuildwheel` runs its
    test-command against the installed wheel from a directory that isn't
    the repo root (deliberately, per the `--import-mode=importlib` note
    below, to avoid the source tree shadowing the installed package), so
    every test built on those constants failed with
    `ProgramLayoutError: ...: no such file` on all three platforms. Fixed
    by resolving them against `Path(__file__).resolve().parent.parent /
    "samples"` instead.
  * `ProgramFixtureGenerator._find_callee_file`'s exact-name attempt used
    `os.path.isfile()`, which matches case-insensitively on macOS and
    Windows — so probing for `EXTCALC.cob` against an on-disk
    `extcalc.cob` reported success and returned the wrong-case path
    instead of falling through to the explicit lowercase candidate,
    failing `test_find_callee_file_falls_back_to_lowercase_and_alt_extensions`
    on those two platforms (Linux's case-sensitive filesystem was
    unaffected). Fixed by matching candidates against the directory's own
    `os.listdir()` entries, which is case-sensitive on every platform.
* **generators:** `BoundaryInventoryAnalyzer._classify()` raised
  `TypeError: Expected type, got ABCMeta` on every statement, in the
  published closed-source PyPI wheel only -- an editable/pure-Python
  install was unaffected. `_FILE_OP_SPECS`'s
  `tuple[tuple[type, str], ...]` variable annotation is a non-binding
  hint in ordinary Python, but Cython's closed-source build
  (`COBOLPARSER_CLOSED_SOURCE=1`) enforces it as a runtime C-level type
  check on every element -- and every AST node class is `ABCMeta`-based
  (`ASTNode(ABC)`), not exactly `type`, so the very first iteration of
  the tuple failed regardless of what statement was being classified.
  This broke `ProgramFixtureGenerator.generate_from_file`/
  `generate_with_scenarios_from_file` -- the entire `gen-fixtures` CLI
  subcommand and the "Generators Surface (mocky-mock)" documented in
  `interface-contract.md` -- for every PyPI install of `cobol-parser`
  (no sdist or pure-Python wheel is published to fall back to). The
  existing `annotation_typing: False` compiler directive does not cover
  this: it only protects function-parameter annotations (confirmed by
  isolating and Cython-compiling `core/ast_factory.py`, whose
  `type[ASTNode]`-annotated parameters worked correctly), not
  module-level PEP 526 variable annotations. Fixed by dropping the
  annotation (mypy still infers a precise type from the tuple literal).
  Verified by isolating `boundary_inventory.py`, Cython-compiling it
  with the same directives as the real closed-source build, and
  reproducing both the failure and the fix against the compiled
  extension directly -- the ordinary pure-Python test suite cannot
  catch this class of bug by itself. Also widened `cibuildwheel`'s
  `test-command` fast post-install subset to include
  `tests/unit/test_program_fixtures.py` (0.5s, 42 tests) so this class
  of regression is caught on future releases -- the previous subset
  (`test_lexer.py` + `test_all_samples.py`) never exercised the
  generators package at all.
* **parser:** a decoded alphanumeric literal containing a double quote was
  re-emitted with that quote **undoubled**, producing an unterminated COBOL
  literal. CICS's own `DFHAID` copybook declares exactly this shape --
  `DFHTRIG PIC X VALUE IS '"'`, a single-quote-delimited literal whose content
  is one `"` character -- and it came back as three quote characters. A
  consumer re-emitting the clause as COBOL source (mockymock's generated
  `UT-RESET-WORKING-STORAGE` paragraph is the case that surfaced this) then
  desynchronized GnuCOBOL's tokenizer for the rest of the program, reported
  as a bogus `invalid symbol '%'` two lines further on. Every re-quoting site
  now routes through the new zero-dependency
  `cobolparser/_literals.py::quote_literal()`, which doubles embedded quotes
  the way COBOL requires: `parse_value_clause` (both the plain-literal and
  the `VALUE ALL <literal>` branches), MOVE/DISPLAY/WRITE operands, and
  SELECT's `ASSIGN TO` literal. Round-trip verified -- re-parsing an emitted
  clause yields the identical clause -- and the emitted form verified to
  compile and run under real GnuCOBOL 4.0. Pinned by
  `tests/regression/test_embedded_quote_literals.py`.
* **core:** `ASTNode.find_all_by_type()` returned its internal per-type
  cache list by reference; a caller mutating the result silently corrupted
  every later lookup for that node_type on the same AST. Now returns a
  copy on every call. Pinned by
  `test_find_all_by_type_mutation_does_not_corrupt_cache` in
  `tests/unit/test_ast_base.py`.
* **core:** `ASTNodeFactory.register_validator()` stored its config but
  `create()` never consulted it, so a registered required-field/field-type
  check was silently never enforced; `_node_validators` was also
  class-level shared state, leaking registrations across factory
  instances. `create()` now applies a matching registered validator after
  node construction, and the registry is per-instance. Pinned by new tests
  in `tests/unit/test_ast_factory.py`.

* **parser:** fixed-format source whose sequence area (columns 1-6) holds a
  change-tracking tag (`SAPR24`, `28486`, `GART`, `JSINT` — a common
  mainframe convention) is no longer misclassified as free-form.
  `_detect_fixed_format` counted a line as fixed-format evidence only when
  columns 1-6 were blank or all digits, so a tagged program fell below the
  60% threshold, `normalize_fixed_format` never ran, and the tag text
  reached the lexer as code — surfacing as `No recognizable COBOL division
  found near 'SAPR24'`, or as stray identifier/number tokens once copybook
  content shifted which lines the detector sampled. Detection now also
  counts a tag-like sequence area, gated on an Area A division header to
  corroborate, so genuine free-form source (which never puts a division
  header at column 8) is unaffected. Pinned by
  `tests/regression/test_tagged_sequence_area_detection.py`.
* **preprocessing:** `strip_sequence_area` unconditionally stripped columns
  1-6 from every full-width line, but a PROCESS/CBL compiler-directing
  statement must start in column 1 per the COBOL standard, even inside an
  otherwise strictly fixed-format program with real sequence numbers
  elsewhere. A flush-left directive like `PROCESS &CICS-31&
  &HAUTE-PERFORM-DB2&` was mangled into `S &CICS-31& &HAUTE-PERFORM-DB2&`
  before any later PROCESS-stripping pass ever saw it intact, surfacing
  downstream as a missing PROGRAM-ID header. A full-width line is now
  exempted from the strip when its own columns 1-6 do not already look
  like a real sequence area (blank or all-digit) and the line is a
  PROCESS/CBL directive; ordinary numbered/tagged source is unaffected.
  Pinned by `TestFlushLeftCompilerDirective` in
  `tests/regression/test_expansion_width_and_tags.py`.

* **parser:** `NEXT SENTENCE` is now a recognized statement (new
  `NextSentenceStatement` AST node) instead of being silently swallowed
  into the enclosing IF/EVALUATE/SEARCH condition's text -- `IF WS-A = "Y"
  NEXT SENTENCE` previously parsed as a comparison against `"'Y' NEXT
  SENTENCE"` with an empty THEN branch. Pinned by
  `tests/regression/test_corpus_residual_findings.py`.
* **parser:** `PERFORM ... WITH TEST BEFORE/AFTER` now tolerates WITH,
  TEST, and BEFORE/AFTER each landing on their own continuation line, in
  all three PERFORM forms (inline UNTIL, out-of-line, and VARYING) --
  previously the clause was left partially unconsumed ("Unparsed tokens
  starting at 'TEST'") and `perform_type` silently fell back to `SIMPLE`.
* **parser:** DISPLAY's subscript fold tolerates a subscript wrapped onto
  its own continuation line (`DISPLAY WS-ITEM\n    (WS-IDX).`) -- the
  bare `(` was previously left unconsumed and aborted the display-item
  list ("Unparsed tokens starting at '('").
* **parser:** WRITE's record-name/FROM source, READ's INTO target/KEY
  name, and START's KEY name now fold a trailing `OF`/`IN` qualifier chain
  or subscript via the shared `consume_optional_qualifiers` helper
  (previously only wired into MOVE/arithmetic/SET) -- e.g. `WRITE OUT-REC
  FROM WS-LINE OF WS-GROUP` stranded `OF WS-GROUP` as unparsed tokens.
* **preprocessing:** the column-72 mid-token overflow warning no longer
  fires when the entire dropped tail is just the statement-terminating
  period -- a banner-style `VALUE` literal whose closing quote lands
  exactly on column 72 (`VALUE '**** TITLE ****'.`) closed cleanly, and a
  lone dropped period costs nothing (every statement parser already
  tolerates a missing terminator). Both the pure-Python and Cython
  normalizers. Pinned by `TestBareTerminalPeriodDoesNotWarn` in
  `tests/regression/test_normalize_column_overflow_warning.py`.
* **parser:** the H9 dedent guard treats a paragraph-header-shaped token
  at the SAME column as the statement's verb as a boundary again (with the
  missing-period warning), not as a trailing operand -- the strict
  less-than comparison silently swallowed the next paragraph out of the
  AST for decks that write statements flush in Area A alongside their
  headers. Only a strictly deeper token (the normal continuation-line
  layout) is read as an operand.
* **parser:** ADD/SUBTRACT addend lists recompose a sign-prefixed numeric
  (`ADD -1 TO WS-X`) via the shared `consume_signed_numeric` -- the
  fall-through consume was silently dropping the sign, recording a
  sign-inverted operand, while MULTIPLY/DIVIDE/SET/PERFORM already
  recomposed it.
* **preprocessing:** `strip_sequence_area`'s short-line change-tag
  blanking now exempts every COBOL reserved word (lazily imported from
  the lexer's keyword table), not just EJECT/SKIP1-3 -- a flush-left
  `GOBACK`/`EXIT`/`STOP`/`MOVE` line under 7 characters was silently
  deleted during copybook expansion. Shop tags (`P2P`, `M1005`) are never
  reserved words and are still blanked. All three pinned by
  `tests/regression/test_diff_scan_findings.py`.
* **parser:** SET now folds `OF`/`IN` qualifier chains into its targets and
  values via the shared `consume_optional_qualifiers`/`consume_value_operand`
  helpers, matching MOVE/arithmetic/PERFORM. Previously `SET WS-IDX TO
  WS-VAL OF WS-CTL` stranded `OF WS-CTL` in the stream (dropped as
  "Unparsed tokens") and `SET FLAG-ON OF WS-REC TO TRUE` silently recorded
  two spurious targets with the `OF` discarded. Pinned by
  `tests/regression/test_set_qualifier_chain.py`.
* **analysis:** `MoveTypeChecker` and `DynamicCallAnalyzer` now resolve
  folded qualified/subscripted reference strings (`"WS-NUM OF GRP-1"`,
  `"WS-TAB ( 3 )"`) by their base data name (new shared
  `analysis._names.base_data_name`). The qualifier-folding parser series
  had silently broken both: a qualified MOVE target missed every catalog
  lookup (zero move-type violations where the bare form flagged one) and a
  dynamic CALL's possible values came back empty when the value arrived
  via a qualified MOVE target. Pinned by
  `tests/regression/test_folded_reference_analyzers.py`.
* **lexer:** `'!'`/`'|'`/`'¬'` outside an `EXEC ... END-EXEC` block are
  hard "Invalid character" lexer errors again (a linear
  `_flag_stray_sql_chars` post-pass shared by the Cython fast path). The
  BANG/PIPE/NOT_SIGN tokens added for embedded SQL (`!=`, `||`, `¬=`)
  accepted these characters *everywhere*, silently turning garbage COBOL
  into a successful parse with zero diagnostics. Inside EXEC blocks they
  still round-trip. Pinned by `tests/regression/test_stray_sql_chars.py`.
* **preprocessing:** the numeric identification-stamp gate on the
  column-72 mid-token truncation warning now requires the all-digit tail
  to fill columns 73-80 exactly (the real ISPF/Z Open Editor auto-number
  shape), instead of accepting any all-digit tail that fits under column
  80 — a split data name whose trailing digits spilled a few columns past
  72 was truncated with no warning at all. Both the pure-Python and Cython
  normalizers.
* **parser/preprocessing/lexer (maintenance):** consolidated per-file
  copies behind shared homes so they cannot drift: the noise-token
  lookahead set (`_NOISE_TOKEN_TYPES` + `peek_past_noise` in
  `parsers/statements/_utils.py`), the H9 dedent guard's
  `token_column` accessor (replacing 16 hand-rolled `getattr` chains
  across 10 parser files), the value-operand reader
  (`consume_value_operand`, shared by PERFORM FROM/BY and SET), and the
  column-7 comment-indicator sets (`COMMENT_INDICATORS` /
  `DEBUG_INDICATORS` / `VERSION_TAG_INDICATORS` in
  `preprocess/_normalize.py`, used by `normalize_fixed_format`,
  `is_comment_line`, `_detect_fixed_format`, and
  `_fixed_format_comment_tokens`). Also: the digit-led-identifier scan in
  both lexers stops at the first letter found and drops a dead
  dash-then-letter disjunct; the copybook expander's wrap loop scans only
  up to column 72 per iteration (`_rightmost_safe_blank`) instead of
  rescanning the whole remaining line; `UnusedVariableAnalyzer`'s EXEC
  CICS/IMS sweep is one traversal instead of two; EVALUATE subject
  collection and the SKIP1/2/3 dispatch table lost redundant
  intermediates. No behavior change.

* **parser/preprocessing:** review-pass hardening of the corpus-retry
  fixes below (each gap reproduced before fixing): the OCCURS count read's
  newline-skip no longer swallows the *next data item's level number* as
  the count when a malformed `OCCURS` has no count at all (guarded
  `_peek_count_token`/`_peek_count_pos`, both paths); `DEPENDING ON` and
  `SIGN IS` split across a 72-column line break now parse (SIGN's
  direction read is also restricted to LEADING/TRAILING — it used to
  record a raw newline as the sign clause); signed values were
  consolidated into a shared `consume_signed_numeric` helper that also
  fixes `SET ... DOWN BY -1` (recorded `"-"` before) and a sign/digits
  pair straddling a line break, with PERFORM's FROM/BY values now folding
  subscripts/qualifiers too; `strip_sequence_area`'s short-line blanking
  was narrowed to tag-shaped content only (blanking every short line
  silently deleted `01 A.`-style code from flush-left copybooks); the
  expander wrap pass allows a break at exactly column 72 (off-by-one left
  a token ending there unsplittable) and `ExpansionStatistics.total_lines`
  is recounted after wrapping; the `_data_fast` comma checks compare the
  COMMA token type (a `','` string literal no longer matches). Pinned by
  new classes in the three regression files below.

* **parser:** the OCCURS clause walk (pure-Python and Cython `_data_fast`
  paths, fixed identically; `.c` regenerated) now handles real-deck line
  splits and separators: a count on the line after `OCCURS` (previously a
  two-digit count — a LEVEL_NUMBER token — was misread as a *new data
  item's level number*, fabricating a phantom item while the real item
  recorded a table size of 0), `TO`/max-count and `INDEXED`/`BY` straddling
  a line break, and comma-separated `INDEXED BY` index names and
  `ASCENDING`/`DESCENDING KEY` name lists. Also recognizes the bare
  `INDEX` usage clause (`05 X [USAGE [IS]] INDEX.` — USAGE and IS are both
  optional; only the `USAGE`-prefixed spelling worked before). Pinned by
  `tests/regression/test_occurs_clause_line_splits.py`.

* **parser:** `PERFORM ... VARYING` dropped its whole clause on a signed
  `FROM`/`BY` value — `BY -1` (every countdown loop) lexes as two tokens
  (MINUS then the number) and each value read consumed a single token, so
  the BY value captured only `"-"`, the leftover digits broke the UNTIL
  lookahead, and the VARYING clause vanished from the AST with a
  "FROM/BY/UNTIL not fully recognized" warning. Fixed by a shared
  `_consume_from_by_value` helper composing the sign and number, wired
  into the VARYING header and every AFTER dimension. Pinned by
  `tests/regression/test_perform_varying_signed_values.py`.

* **preprocessing:** two `expand_copybooks` output defects (raw inputs
  valid in both cases): (1) a `COPY ... REPLACING` whose replacement text
  is longer than what it replaces pushed the line's tail — typically the
  data item's terminating period — past column 72 of the re-padded output,
  where the final parse's fixed-format slice silently dropped it; new
  `_fit_fixed_format_width` squeezes interior multi-blank runs (outside
  quoted literals, rightmost first, line count unchanged) and falls back
  to a word-boundary wrap onto a fresh Area-B line. (2) shop change-tag
  lines stamped into columns 1-6 of their own line (`P2P`, `M1005`, ... —
  any prefix) leaked through `strip_sequence_area`'s short-line
  passthrough and were shifted into the indicator column by the 6-space
  re-pad, surfacing as "Unparsed tokens" or silently swallowed garbage;
  short (sub-7-character) lines are now blanked — their every character
  lies within the sequence area the function exists to strip. Pinned by
  `tests/regression/test_expansion_width_and_tags.py`.

* **parser:** `ADD ... TO`/`SUBTRACT ... FROM` targets and MULTIPLY/DIVIDE
  operands silently dropped a trailing `OF`/`IN` qualifier chain —
  `_consume_arithmetic_target` never consumed one at all (leaving `OF Z` in
  `ADD X TO Y OF Z` unconsumed in the token stream, including when the
  chain wrapped onto its own continuation line, e.g. `ADD X TO Y\n    OF
  Z`), and `_consume_arithmetic_operand` consumed but never composed one
  into its returned value (`ADD 1 TO QUAL OF GROUP-A` reported a target of
  just `"QUAL"`). Fixed by a new shared `consume_optional_qualifiers`
  helper (`_utils.py`) that folds an optional `(subscript)` group and/or an
  `OF`/`IN` chain of any length into the caller's result string, wired into
  both functions. A `/code-review` pass on this fix caught two more call
  sites sharing the same responsibility that were left unfixed:
  `consume_keyword_and_operand` (the `GIVING` clause shared by all four
  verbs, and DIVIDE's `REMAINDER` clause) still called only
  `consume_optional_subscript`, dropping the same qualifier chain (`ADD X
  TO Y GIVING QUAL OF GROUP-A` reported a giving of just `"QUAL"`); and
  `parse_arithmetic_operands` (ADD's/SUBTRACT's leading addend list before
  `TO`/`FROM`) didn't fold a chain at all, instead silently splitting a
  qualified addend into two spurious separate addends (`ADD QUAL OF
  GROUP-A TO Y` produced addends `"QUAL"` and `"GROUP-A"`). Both now route
  through the same shared helper. A second review pass caught one more
  gap: `consume_optional_qualifiers` skipped only `NEWLINE` between hops,
  not the `CONTINUATION` token a genuine fixed-format continuation line
  carries (column-7 `-`) — switched to the broader `skip_whitespace`,
  matching `consume_keyword_and_operand`'s existing precedent. Further
  review passes fixed four more gaps: (1) MOVE's target-collection loop
  (`move_parser.py`) had the identical bug — no `OF`/`IN` handling at all
  — left unfixed since MOVE is a different statement parser the arithmetic
  fix never touched; wired to the same shared helper. (2)
  `consume_optional_qualifiers` consumed a dangling `OF`/`IN` (no
  identifier following, e.g. `ADD A OF 5 TO B.`) unconditionally before
  checking, discarding it with no trace; now confirms an identifier is
  present via non-destructive lookahead before consuming the keyword. (3)
  `consume_optional_subscript`'s paren-depth loop had no bound but
  end-of-stream, so an unclosed `(` (e.g. `ADD TBL (IDX TO C.\n STOP
  RUN.`) devoured every following statement hunting for a `)` that was
  never there; now stops at the first token that can never legally appear
  inside a subscript (period, scope terminator, or statement/control-flow
  keyword). (4) Simplified `consume_optional_qualifiers`'s signature from
  `(stream, parts: list[str]) -> None` to `(stream, value: str) -> str`,
  collapsing the identical three-line glue that had been copy-pasted at
  all four call sites. Pinned by
  `tests/regression/test_arithmetic_qualifier_chain.py` and
  `tests/regression/test_move_qualifier_chain.py`.

* **preprocessing:** `normalize_fixed_format` now treats `'V'`/`'v'` in the
  fixed-format indicator column (column 7) as a comment line, mirroring the
  existing `'D'`/`'d'` debug-line handling — new
  `version_tag_lines_as_comments: bool = True` parameter (both the
  pure-Python and Cython `_preprocess_fast` paths; `.c` regenerated), and
  `copy_statement_parser.is_comment_line()` / `parser._detect_fixed_format`
  updated to match. Found via a shop-specific change-control convention that
  stamps a short version tag (e.g. `V97`, `TFEC`) into Area A with `V` in
  column 7 of its own line — standard fixed-format COBOL never puts live
  code there, so the un-normalized tag text previously reached the lexer and
  surfaced as "Unparsed tokens" errors. Pass
  `version_tag_lines_as_comments=False` to compile V-lines as live code
  instead. Also fixes a follow-on gap caught in PR review:
  `lexer.py`'s `_fixed_format_comment_tokens` (backs
  `tokenize_cobol(..., keep_comments=True)`) re-scans physical lines to
  reconstruct `COMMENT` tokens for lines `normalize_fixed_format` blanks
  out, but only recognized `*`/`D`/`d` (plus `/` for page breaks) — a
  V-line's blank placeholder had no matching re-scan entry, desyncing every
  later comment/blank pairing by one and misattributing the next real
  comment to the V-line's own line number. Pinned by
  `tests/regression/test_version_tag_line_handling.py`.
* **parser:** `SKIP1`/`SKIP2`/`SKIP3` (the compiler-directing listing no-ops,
  the same class of statement as `EJECT`) were missing from the shared
  `STATEMENT_TOKEN_TYPES`/`STATEMENT_KEYWORDS` sets in
  `parsers/statements/_utils.py` that every operand/parameter-collection
  loop (`CALL ... USING`, `MOVE`, `PERFORM`, `SET`, etc.) and the
  PROCEDURE DIVISION paragraph-boundary scanner consult to recognize
  "this token starts a new statement." `SKIP1`/`SKIP2`/`SKIP3` already had
  their own `TokenType` and a dedicated `SkipStatementParser` ->
  `SkipStatement` no-op node, so no incorrect parse was observed in
  testing, but the gap left them one refactor away from the exact
  misparse `EJECT` was fixed for (`test_eject_statement.py`) — a
  boundary-token type not in these sets can be swallowed as an operand by
  a preceding statement's argument-collection loop. Added alongside
  `EJECT`'s existing entries for parity; new regression coverage in
  `tests/regression/test_skip_statement.py` mirrors
  `test_eject_statement.py`'s scenarios (trailing-period paragraph-split
  guard, no-period marker survival, back-to-back directives, AST node
  shape, COPY-expansion) for `SKIP1`/`SKIP2`/`SKIP3`.
* **parser/analysis:** review follow-up on the `EVALUATE`-subject fix
  below. `evaluate_parser.py` now routes subjects through
  `EvaluateStatement.add_subject()` (the root cause: it appended straight
  to `stmt.subjects`, so `stmt.operands` stayed empty and every generic
  `.operands` consumer — `find_statements_using_variable`,
  intrinsic-function detection, `LanguageEnvironmentAnalyzer`,
  `BoundaryInventoryAnalyzer`'s caller-dataflow rung — missed a variable
  referenced only as an `EVALUATE` subject). `UnusedVariableAnalyzer`
  additionally no longer falsely reports a variable referenced only as a
  plain `WHEN` selector: `_build_selector` classifies a bare data-name
  (or level-88 condition-name) selector as `{"type": "Literal"}` and
  never emits `"Identifier"`, so `_selector_identifiers` now scans
  `Literal` values too. The analyzer's opaque-expression fallback also
  scans every `expr.operands` entry instead of only the first. The
  analyzer keeps its explicit subjects walk because `add_subject()` sends
  a `CobolExpression` subject to `add_child()`, never `add_operand()` —
  the entry below's parenthetical ("the setter that would otherwise reach
  `.operands`") is accurate only for string subjects.
* **analysis:** `UnusedVariableAnalyzer` no longer falsely reports a data
  item as unused when it is referenced only as an `EVALUATE` subject
  (`EVALUATE WS-CODE` / `EVALUATE WS-A ALSO WS-B`). `evaluate_parser.py`
  appends subjects straight to `EvaluateStatement.subjects`, bypassing
  `add_subject()` (the setter that would otherwise reach `.operands`), so
  subjects never showed up in the flat operand bag the analyzer's base
  case scans; only `WHEN` selectors were already special-cased. The
  `EvaluateStatement` branch in `_collect_referenced_names` now also walks
  `stmt.subjects` directly.
* **analysis:** `IOSequenceAnalyzer` now walks statements in (approximate)
  *execution* order — entry procedure, fall-through, unconditional GO TO,
  and out-of-line `PERFORM`/`PERFORM THRU` targets inlined at their call
  sites — instead of raw AST declaration order. The canonical correct
  COBOL shape (OPEN/READ in a main paragraph that PERFORMs a wrap-up
  paragraph declared after it) used to produce CLOSE_NOT_OPEN,
  FILE_LEFT_OPEN, and READ_BEFORE_OPEN false positives; paragraphs
  unreachable from the entry procedure are no longer walked at all
  (2026-08-16 analyzer-subcommand audit).
* **analysis:** `CallStatement.set_possible_values` sorts the deduplicated
  value list — `list(set(...))` made `analyze`'s JSON `possible_values`
  order vary per process under hash randomization (2026-08-16 audit).
* **analysis:** `LanguageEnvironmentAnalyzer` no longer scans quoted string
  literals for `FUNCTION <name>` — `DISPLAY 'FUNCTION KEYS ARE DISABLED'`
  used to report a fictitious intrinsic function `KEYS` and flip
  `uses_intrinsic_functions` to true (2026-08-16 audit).
* **analysis:** `IMSSegmentAnalyzer` merges MOVE-tracked values on a group
  SSA's segment-name child field with its static VALUE clause (multi-
  candidate "/" convention) — `MOVE 'SEGB' TO SSA1-SEG-NAME` was ignored
  and the stale initial VALUE reported with full confidence (2026-08-16
  audit).
* **analysis:** `MoveTypeChecker` classifies multi-part alphabetic
  PICTUREs (`AA(3)`, `A(2)A(3)`) as ALPHABETIC — they fell through to
  ALPHANUMERIC, hiding illegal numeric→alphabetic MOVEs — and treats a
  trailing `CR`/`DB` sign symbol as NUMERIC_EDITED (`9(5)CR` was UNKNOWN
  while the equivalent `9(5)DB` was NUMERIC_EDITED only by accident, via
  the 'B' insertion character) (2026-08-16 audit).
* **analysis:** `TechnicalDebtAnalyzer` rounds the composite score to the
  2 decimals `to_dict()` serializes *before* grading, so the emitted
  score and grade always agree (a JSON score of 10.0 could carry grade
  "B" against the documented A<=10 band); the complexity/size components
  now carry a "no procedures to rate" finding instead of an empty
  findings list on a program with no procedures (2026-08-16 audit).
* **analysis:** `ComplexityAnalyzer` aggregates decision counts across
  same-named paragraphs in different sections (legal COBOL) — the
  name-keyed flow node already merged both bodies' statement counts, but
  only the first body's complexity was analyzed, silently dropping the
  second (2026-08-16 audit).
* **generators:** `compute_program_data_items` (the `data-items`
  subcommand) reports the usage of a PIC-less USAGE-only record root
  (`77 X USAGE COMP-1.`) instead of `null` — the byte length was already
  derived from that very usage (2026-08-16 audit).
* **cli:** `analyze` now emits `"possible_values_incomplete": true` on a
  dynamic CALL entry whenever `DynamicCallAnalyzer` marked the value set
  as not fully resolvable (an untracked identifier-shaped MOVE source
  feeding the target variable) — before this, the JSON presented a
  known-incomplete `possible_values` list as if it were exhaustive
  (2026-08-16 analyzer-subcommand audit).
* **cli:** `program-flow --format mermaid|dot` combined with `--profile`
  now prints a stderr warning that the profiling metrics are only
  included in `--format json` output — previously the profiler ran and
  its result was silently discarded, making `--profile` look like a
  no-op (2026-08-16 analyzer-subcommand audit).

* **analysis:** `DeadCodeAnalyzer` no longer resurrects genuinely dead
  paragraphs that share a section with a PERFORMed/GONE-TO sibling.
  `_propagate_section_references` used to mark a paragraph's parent
  section "referenced" and then broadcast that to every paragraph in the
  section, even when the section itself was never PERFORMed/GONE TO — only
  one of its paragraphs was. Downward propagation now runs before upward
  propagation, so it only cascades from sections that are themselves
  directly referenced (matching real COBOL semantics: `PERFORM
  section-name` runs every paragraph in it, but `PERFORM
  child-paragraph` does not).
* **generators/analysis:** the `gen-fixtures` witness pipeline no longer
  loses precision on wide numeric literals. `domains.py`'s solver and
  `ValueFactory.render()`/`_format_number` carried values through float64,
  so any literal past ~16 significant digits (PIC 9(17)/9(18) account
  keys) was silently rounded — `IF ACCT-ID = 123456789012345678` produced
  a fixture row of `123456789012345680` while `ScenarioCoverage` still
  reported the arm as targeted, violating the "no silent gaps" guarantee.
  Bounds, exclusions, and exact-value rendering are now `Decimal`
  end-to-end (wide-precision contexts guard the largest PICTUREs), and
  `scenarios._picture_ceiling` no longer emits scientific notation
  (`1e+18`) for 18-digit fields.
* **analysis:** `ConstantFolder` now folds unambiguous DIVIDE forms
  (`BY`/`INTO` with GIVING, `INTO` in place) instead of poisoning every
  DIVIDE, using the new `DivideStatement.division_mode`; ROUNDED,
  REMAINDER targets, non-exact quotients, divide-by-zero, and the
  nonstandard `DIVIDE a BY b` without GIVING still poison. A DIVIDE's
  REMAINDER target is now also poisoned by the IF-arm/handler-body write
  scan (it was previously missed).
* **parser:** `COMPUTE` expression text re-merges the two lexed `*` tokens
  of `**` — `COMPUTE X = 2 ** 3` serializes as `2 ** 3`, not the invalid
  `2 * * 3` (the structural `expression_tree` was already correct).
* **parser:** MOVE/DISPLAY statement text preserves typed-literal
  prefixes: `MOVE X"41" TO WS-X` keeps `X"41"` (one byte) instead of
  collapsing to the two-character text literal `"41"`; same for
  `Z"…"`/`N"…"`/`G"…"`.
* **parser:** reference modification joins tight in MOVE source text —
  `WS-X(2:3)`, not `WS-X(2 : 3)` (same fidelity class as the earlier
  negative-subscript fix).

### Added

* **models:** `DivideStatement.division_mode` (`"BY"` | `"INTO"`, emitted
  by `to_dict()`) records which separator the source used — the two forms
  invert dividend/divisor order, so without it no consumer could evaluate
  a DIVIDE from the AST.

### Fixed (previous audit round)

* **parser:** restored the EVALUATE WHEN selector contract regressed by
  commit `17fa400`: non-blank string-literal selectors keep their
  unquoted representation; only blank/whitespace-only literals are
  re-quoted. (This had turned the full test suite red at HEAD.)
* **parser:** MOVE statements no longer corrupt multi-word sources —
  qualified names (`WS-A OF WS-GRP`), `FUNCTION` calls, and subscripted
  references are joined with correct spacing instead of concatenated.
* **parser:** `TokenStream.expect()` raises `TokenMismatch` instead of
  silently matching any expected value against an empty-valued (EOF)
  token, so a missing terminating period at end-of-file is diagnosed.
* **parser:** `ParseResult.statistics` is an independent snapshot;
  reusing one `CobolParser` no longer clobbers earlier results.
* **parser:** IDENTIFICATION DIVISION detection recognizes
  sequence-numbered fixed-format headers (`000100 IDENTIFICATION
  DIVISION.`) when skipping leading non-COBOL text.
* **lexer:** the compiled `_lexer_fast` lexer resets its warnings on each
  `tokenize()` call, matching the pure-Python lexer instead of
  duplicating warnings across calls (checked-in `.c` regenerated).
* **preprocess:** copybook resolution is consistently
  first-configured-directory-wins across the resolver's indexed (Tier-2)
  and filesystem-search (Tier-3) paths.
* **preprocess:** `expand_copybooks()` honors a caller-supplied
  `path_resolver` instead of unconditionally replacing it.
* **preprocess:** removed the unused exported `COPY_PATTERN` regex, which
  exhibited exponential backtracking (ReDoS) on unterminated
  `COPY ... REPLACING` input.
* **analysis:** `ConstantFolder` poisons fields written in AT END /
  INVALID KEY / ON SIZE ERROR / ON OVERFLOW / ON EXCEPTION / AT EOP
  handler bodies instead of emitting stale `field_equals` expectations,
  and orders paragraphs by source line so PERFORM THRU ranges spanning
  top-level paragraphs and sections fold correctly.
* **analysis:** boundary inventory and constraint extraction descend into
  ON SIZE ERROR / NOT ON OVERFLOW / NOT AT EOP clause bodies (a CALL
  inside ON SIZE ERROR is now inventoried).
* **analysis:** OPEN/CLOSE boundaries carry the declared FILE STATUS
  field, enabling the gen-fixtures "OPEN → FILE STATUS 35" error-status
  scenario family that previously could never fire.
* **analysis:** SQL/CICS/DLI boundary keys are order-independent unique
  prefixes computed against every other same-category site's full text.
* **analysis:** `domains.solve()` picks numeric witnesses on the field's
  decimal grid and re-verifies the rendered form, so a witness can no
  longer round onto an excluded value (e.g. PIC 9 with `ne 4` yielding
  `"4"`).
* **analysis:** `IOSequenceAnalyzer` treats only STOP RUN (not
  `STOP 'literal'`) as program termination.
* **analysis:** `CRUDMatrixGenerator` records each file's own mode for
  multi-mode `OPEN INPUT A OUTPUT B` statements via
  `IOOpenStatement.file_modes`.
* **analysis:** `DynamicCallAnalyzer` no longer records an untracked
  identifier-shaped MOVE source as a possible CALL value; such CALLs are
  flagged `possible_values_incomplete` instead.
* **generators:** flowchart generators render external-CALL nodes from
  real `ProgramFlowAnalyzer` reports (the analyzer emits `"program"`,
  not `"target"`; `EXT_*` ids are uppercase-normalized).
* **generators:** `ProgramLayoutIndex` records an ambiguity for duplicate
  level-88 condition names instead of silently keeping the last one.
* **tests:** `contract`/`integration`/`io` pytest markers are applied
  structurally by per-directory conftest hooks — `-m contract` selects
  386 tests (was 66), `-m io` 183 (was 69), and 36 previously-missed
  integration tests are covered.
* **tests:** the 12 permanently-skipped "Implementation pending -
  Phase 6/7" copybook-expansion placeholders are real tests now, and
  ~30 assert-free or tautological real-world parsing tests assert parse
  success and AST content.

### Removed

* Dead code identified by the 2026-08-12 audit: unreachable multi-word
  lexer `KEYWORDS` entries, a discarded expansion cache-key call, the
  unused batch file-content cache, and a no-op empty-SECTION branch in
  the program-flow scanner.

* **analysis:** `DeadCodeAnalyzer` had no concept of fall-through at all --
  unlike `ProgramFlowAnalyzer` (which has `graph.build_fall_through_edges`),
  `_collect_references` only looked at PERFORM/GO TO/SORT/MERGE/ALTER/ENTRY
  references, so any paragraph reached purely by falling off the end of the
  previous one (the default shape of a straight-line COBOL program with no
  explicit control transfer between paragraphs) was reported dead. Fixed by
  adding `_collect_fallthrough_refs`, which marks a procedure referenced
  when the one immediately before it in source order is itself already
  reachable and does not terminate (any of its own top-level statements --
  not just the last one -- is a hard terminator -- `STOP RUN`, `GOBACK`,
  `EXIT PROGRAM` -- or an unconditional, non-`DEPENDING` `GO TO`). Pinned by
  `tests/unit/analysis/test_dead_code.py::TestFallThroughReferences`.

* **analysis:** `ProgramFlowAnalyzer.build_fall_through_edges` suppressed a
  paragraph's fall-through edge whenever *any* `GOTO`-type edge originated
  from it, or whenever `node.has_stop_run`/`has_goback`/`has_exit_program`
  was set for a STOP RUN/GOBACK/EXIT PROGRAM *anywhere* in the paragraph --
  neither check required the statement to be the paragraph's own
  unconditional top-level statement, so one nested inside an `IF` (no
  `ELSE`) or other conditional arm incorrectly suppressed fall-through even
  though the paragraph still falls through whenever that branch isn't
  taken. Fixed by having `ProcedureScanner` check every one of a
  paragraph's own top-level statements (not just the last, and never
  nested ones) for an unconditional terminator (`STOP RUN`/`GOBACK`/
  `EXIT PROGRAM`/bare non-`DEPENDING` `GO TO`) via a single
  `_is_terminator` predicate, replacing both prior checks; also dropped a
  stale `node.perform_count == 0` conjunct (a PERFORM before the
  paragraph's own terminator cannot create a path back to a fall-through).
  Pinned by `TestProgramFlowFallThrough::
  test_conditional_goto_inside_if_does_not_suppress_fall_through`,
  `::test_unconditional_trailing_goto_still_suppresses_fall_through`,
  `::test_terminator_earlier_in_paragraph_still_suppresses_fall_through`,
  and `::test_conditional_stop_run_inside_if_does_not_suppress_fall_through`
  in `tests/unit/analysis/test_program_flow.py`.

* **analysis:** `DeadCodeAnalyzer._collect_alter_refs` wrongly marked an
  `ALTER paragraph-name TO PROCEED TO target-name` statement's *subject*
  (`paragraph-name` -- the paragraph whose internal GO TO gets modified) as
  referenced, alongside the real jump target (`target-name`). Being named
  as the ALTER's subject is not an incoming jump, so this hid genuinely
  dead paragraphs from `DeadCodeAnalyzer` that `ProgramFlowAnalyzer`'s
  `unreachable_nodes` (whose ALTER edge already only flows target-ward)
  correctly reported as unreachable. Fixed by only adding the ALTER's
  `to_paragraph` to the reference set. Pinned by
  `TestAlterReferences.test_alter_never_called_paragraph_is_dead` in
  `tests/unit/analysis/test_dead_code.py`.

* **dead code / program flow:** `DeadCodeAnalyzer._collect_procedures`
  (`cobolparser/analysis/dead_code.py`) and `ProcedureScanner.
  collect_procedures` (`cobolparser/analysis/program_flow/scanner.py`)
  appended all section-owned paragraphs to `_ordered_procedures` before
  top-level paragraphs, even though COBOL legally allows paragraphs before
  the first `SECTION` header. A program mixing the two ended up with an
  `_ordered_procedures` list that no longer matched source order,
  corrupting entry-point detection (a section became `entry_points[0]`
  instead of the true first paragraph), falsely flagging the real first
  paragraph as dead/unreachable, and fabricating a bogus fall-through edge
  between physically non-adjacent paragraphs while dropping the real one.
  Fixed both collectors by interleaving sections and top-level paragraphs
  by `location.line` before walking them; the pre-existing name-collision
  dedup guard (previously top-level-paragraph-branch-only, safe only when
  sections were always walked first) was extended to the section-owned-
  paragraph branch and the SECTION-registration branch in both files to
  stay correct under the new interleaved order. Pinned by
  `tests/unit/analysis/test_dead_code.py::TestDeadCodeIntegration` and
  `tests/unit/analysis/test_program_flow.py::TestProgramFlowRealCobolIntegration`.

* **analysis:** `DeadCodeAnalyzer._collect_goto_refs` and
  `ProgramFlowAnalyzer.process_goto` reconstructed a computed
  `GO TO ... DEPENDING ON` statement's targets by filtering `stmt.operands`
  against `stmt.depending_on_variable`, instead of reading the AST's own
  `GoStatement.target_paragraphs`. Operand dedup collapses a target
  paragraph that happens to share its name with the DEPENDING ON variable
  (`GO TO PARA-A RUN-FLAG DEPENDING ON RUN-FLAG.`) into one operand entry,
  which the filter then drops entirely, so the shared-name target was
  reported dead and missing a `GOTO_DEPENDING` edge despite being a live
  target. Both sites now read `target_paragraphs` directly, which
  `go_parser.py` already populates correctly. Pinned by
  `test_goto_depending_target_sharing_name_with_variable` in
  `tests/unit/analysis/test_dead_code.py` and
  `tests/unit/analysis/test_program_flow.py`.

* **preprocessing:** `normalize_fixed_format` silently dropped a physical
  line whose extracted program-text (columns 8-72) was entirely blank but
  which was neither a short/blank line nor a `*`/`/`/debug comment line
  (indicator column itself blank) -- `flush_parts()`'s `if combined:` guard
  only emitted a result entry for a logical line's merged text when that
  text was non-empty, so this line shape vanished with no placeholder at
  all instead of the empty-string placeholder used everywhere else,
  shifting every subsequent line number. This never occurs in a plain
  fixed-format parse (blank lines are always short; comment lines always
  have a non-blank indicator), but it is exactly what
  `copy_statement_parser.remove_comment_lines` turns a `*`-comment line
  into ahead of `CobolParser._parse_core`'s second `normalize_fixed_format`
  pass over copybook-expanded source -- reported as `program-flow`
  `location.line` drifting backward by one per full-line comment anywhere
  earlier in the file, but only when a `COPY` statement preceded it
  (issue #123). Fixed in both the pure-Python implementation and the
  Cython `_preprocess_fast.pyx` mirror by tracking whether a logical line
  was actually started (`has_line`) instead of inferring it from whether
  the merged text happens to be non-empty. Pinned by
  `tests/regression/test_normalize_line_number_preservation.py`.

* **procedure division:** a bare unsupported verb with no dedicated lexer
  `TokenType` (`PURGE`, `RAISE`, `RESUME`) immediately followed by its own
  terminating period could hang `parse_cobol()` forever, and any
  unsupported verb with a bare trailing identifier operand (`PURGE WS-X.`)
  could truncate the enclosing paragraph and invent a spurious paragraph
  named after the operand (2026-08-10). Both traced to
  `is_paragraph_or_section_start()`
  (`cobolparser/parsers/divisions/procedure_boundaries.py`) misreading a
  token that is part of the statement currently being discarded as a new
  paragraph header -- the same class of ambiguity H9 fixed for individual
  statement parsers' own operand loops, but never applied to the PROCEDURE
  DIVISION's own generic recovery path
  (`StatementRecoveryHandler.skip_to_next_statement`). See
  `reports/open-findings.md` H11. Pinned by
  `tests/regression/test_procedure_recovery_boundary_misfire.py`.

* **lexer:** free-form `*>` inline comments are now stripped (2026-08-07).
  `*>` (legal anywhere on a line, in both fixed- and free-form source) was
  previously recognized nowhere in the pipeline: `normalize_fixed_format`
  only strips whole comment lines, and the lexer read `*` as `MULTIPLY_OP`
  and tokenized the comment's words as ordinary identifiers/keywords. A
  comment word colliding with a COBOL verb could produce a real, bogus AST
  node -- confirmed via `examples/cobol/shamrice/unstring.cbl:243`, whose
  `*> start at 2 ...` comment lexed "start" as `START` and produced a
  phantom `IOStartStatement` with no actual START verb in the source.
  `tokenize_program_text` (pure-Python `lexer.py` and the Cython
  `_lexer_fast.pyx` mirror) now emits `*>` through end-of-line as a single
  `COMMENT` token, which every statement parser already skips via
  `skip_whitespace()`. Pinned by
  `tests/regression/test_inline_comment_stripping.py`.

### Removed

* **CobolCheck test generation** (2026-07-09): the `cobol-parser generate-tests`
  CLI subcommand, the `generate_cobolcheck_tests()` Python API, and the
  `CoverageAnalyzer` / `TestPlanGenerator` / `CobolCheckGenerator` classes have
  been removed. Equivalent test-generation functionality now lives in the
  mockymock framework.

### Added

* **analysis/generators:** `ConstantFolder` and `Expectation` tiers 1-2 --
  structural and computed assertions, not just stubs
  (`cobolparser/analysis/const_fold.py`, `cobolparser/generators/program_fixtures.py`,
  2026-08-04). Phase 7 ("Expectations tiers 1-2") of the `gen-fixtures`
  program-scoped test-data initiative (see
  `docs/plans/2026-08-02-program-data-generation-design.md`).

  **Tier 1 (`call_count`)**: every boundary that gets an actual fixture in a
  scenario now also gets `Expectation(kind="call_count", ref="<CATEGORY>:<KEY>",
  value=times)`, `times` derived exactly from that fixture's own generated
  sequence (`len(sequence) + 1` when a `terminal`/`AT END` is present, else
  `len(sequence)`; always `1` for a `STATUS_ONLY` fixture) -- never a guess,
  since the scenario itself defines the sequence.

  **Tier 2 (`field_equals`)**: `ConstantFolder` performs a single forward
  walk of a program's entry paragraph chain -- following non-looping
  `PERFORM`s (including `THRU` ranges) inline, exactly like a subroutine
  call executed once -- tracking which data items hold a knowable literal
  value after a MOVE or a simple ADD/SUBTRACT/MULTIPLY/COMPUTE. Wired via a
  new `_tier2_expectations` helper that seeds the walk from every
  `BoundaryFixture` in the scenario with *exactly one* generated row (a
  multi-row READ sequence has no single representative value to seed with),
  and turns every field still knowable at a `DISPLAY`/`WRITE` into
  `Expectation(kind="field_equals", ref=qualified_name, value=folded_value)`.

  "Exact by construction, or absent" throughout, never a guess:
  - A `PERFORM ... UNTIL`/`VARYING`/`TIMES` loop, or an `IF`/`EVALUATE`
    branch, poisons every field its body could write (including through a
    nested `PERFORM`) rather than assume which arm runs or how many
    iterations occur; the walk continues past it, since it still executes.
  - `DIVIDE` is poisoned unconditionally: `DivideStatement` does not record
    whether `BY` or `INTO` was used, and the two invert dividend/divisor
    order, so the correct value cannot be computed from the AST node alone.
    A `/` inside a `COMPUTE` expression tree has no such ambiguity (both
    operands are structurally explicit) and folds normally.
  - `ROUNDED`, `CORRESPONDING`, and any numeric result that would need
    rounding/truncation/sign-coercion to fit its target field's PICTURE are
    all poisoned rather than approximated.
  - A well-formed ADD/SUBTRACT self-reference (`ADD X TO X`, doubling X) is
    poisoned rather than silently under-computed as a no-op: `.operands` is
    a deduplicated union of the real addend tokens and the target/giving
    names (both populated via the same `_add_unique_operand`), so a genuine
    self-reference and "the target was never a separate addend at all"
    produce an identical shape, unrecoverable from the final AST. Since a
    well-formed ADD/SUBTRACT always has >= 1 real addend, filtering
    target/giving names out of `.operands` and finding nothing left proves
    total self-overlap -- the one shape this can safely detect. A blanket
    "poison on any operand/target overlap" was tried and rejected during
    development: a target's own name always ends up in `.operands`
    regardless of any genuine overlap, so it fired on every ordinary
    `ADD 1 TO WS-X` -- found via this module's own tests before it reached
    the corpus sweep.
  - ACCEPT/READ are a deliberate no-op rather than poisoned: they are
    exactly the boundary categories the seed dict is built from, so treating
    them as an "unmodeled write" would poison the seed the instant the walk
    reached the very statement it represents. CALL/EXEC SQL/CICS/DLI are not
    given the same treatment (their operand lists mix genuinely-unknowable
    OUT values with seedable IN ones, and the raw AST does not carry
    resolved argument direction) -- deferred to a later version.
  - Only a `DISPLAY`/`WRITE` operand resolving directly to an elementary
    field is an observation point; a whole-record `WRITE`'s individual
    member fields are not (yet) walked -- narrower than possible, never wrong.

  Also fixes a crash found via a full 459-file NIST COBOL-85 corpus smoke
  sweep (beyond this initiative's usual 24-file shamrice corpus, given the
  correctness stakes of arithmetic folding): `ProgramLayoutIndex.resolve()`
  raised `IndexError` on an all-punctuation name (`"."`, a stray token that
  leaks into some statement's `.operands` for at least one real-world
  program) -- both the dotted-name and `OF`/`IN` branches could strip every
  segment to nothing and then index into the resulting empty list; both now
  return `None` instead. `const_fold.py` additionally hardens its own call
  site (`_safe_resolve`) as a second line of defense. Also caught by the
  same review pass: `_eval_expr`'s `COMPUTE`-expression arithmetic caught
  only `InvalidOperation`/the builtin `OverflowError`/`ValueError`, but
  `decimal.Overflow` and `decimal.DivisionByZero` are not subclasses of
  `OverflowError` -- an extreme exponent (`2 ** 99999`) could crash the
  whole walk instead of poisoning its target; widened to catch
  `ArithmeticError` (the common base of every `decimal` signal exception).

  New `ConstantFoldResult` / `ConstantFolder` public API in
  `cobolparser.analysis.const_fold`. Documented in `.okf/analysis.md` (new
  "ConstantFolder" section), `.okf/generators.md` (new "Expectations: tiers
  1-2" section), `CLAUDE.md`, and `docs/fixture-bundle-schema.md` (updated
  Expectation tier descriptions + worked example). Covered by 104 new tests:
  `tests/unit/analysis/test_const_fold.py` (44), a full-corpus
  `tests/integration/test_const_fold_corpus.py` (50, parametrized over the
  shamrice corpus, plus an ad-hoc sweep of the full 459-file NIST corpus),
  and 10 new tests in `tests/unit/test_program_fixtures.py` covering the
  `ProgramFixtureGenerator` wiring end-to-end.
* **generators:** `--scenarios branches|all` wiring, `scenario_coverage`, and
  a hand-written fixture-bundle schema doc (`cobolparser/generators/program_fixtures.py`,
  `cobolparser/generators/data/bundle.py`, `docs/fixture-bundle-schema.md`,
  2026-08-04). Phase 6 ("Emitters hardening") of the `gen-fixtures`
  program-scoped test-data initiative: turns Phase 5's `ScenarioPlanner`
  output into an actual multi-scenario `FixtureBundle` instead of the
  happy-path-only bundle every mode produced through Phase 5.

  New `ProgramFixtureGenerator.generate_with_scenarios(ast, index, report,
  mode="happy"|"branches"|"all", seed=...)` and its `_from_file` counterpart.
  `mode="happy"` delegates to the existing `generate()` unchanged — byte-
  identical output for the same seed, pinned by a contract test, since this
  is an additive capability, not a change to `generate`'s existing one. For
  `"branches"`/`"all"`, every `PlannedScenario` becomes a real `Scenario`
  with a complete fixture for *every* boundary the program touches (the
  program under test still hits all of them regardless of which arm is
  targeted); only the fields/sequence-lengths/status values a scenario
  actually constrains are pinned to their solved witness via a new optional
  `override: PlannedScenario` parameter threaded through the existing
  `_build_fixture`/`_build_call_fixture`/`_status_dict` helpers — everything
  else still comes from the same `ValueFactory` path the happy path always
  used. `FixtureBundle` gained one new field, `scenario_coverage: dict |
  None` (Phase 5's `ScenarioCoverage.to_dict()` verbatim, `None` in
  `mode="happy"`) — additive, `bundle_version` stays `1`.

  `--scenarios` on the `gen-fixtures` CLI now accepts and genuinely acts on
  `branches`/`all` (previously accepted but silently behaved like `happy`).

  Also fixes two gaps found closing out this phase: (1) `ArmOutcome.parent_proc`
  was always `None` on a "merged" outcome — recovered from `arm_key`
  (`"<paragraph>@<line>:<column>/<arm_id>"`) instead of hardcoding it; (2) a
  third occurrence of the circular-import shape first seen in Phase 4
  (`constraints.py`'s newly-added top-level `ProgramLayoutIndex`/
  `ResolvedField` import now collided with `program_fixtures.py`'s new
  top-level `ConstraintExtractor` import; a fourth edge then surfaced between
  `domains.py` and `scenarios.py` via `generators/__init__.py`'s own import
  chain) — fixed at the root this time instead of with another one-off
  `TYPE_CHECKING` patch: `cobolparser/generators/__init__.py` is now
  `__getattr__`-based lazy loading, mirroring `cobolparser/analysis/__init__.py`'s
  already-established pattern, so importing the package no longer eagerly
  pulls in every submodule's own transitive dependencies. `__all__` is
  unchanged (same 21 public names).

  `write_csv_dir` gained an explicit round-trip guarantee test: reading a
  written `<KEY>.csv` back with `csv.reader` and zipping it against the same
  fixture's `sequence` in the JSON output produces byte-identical cells, and
  a multi-scenario bundle produces one CSV directory per scenario slug.

  Documented in `docs/fixture-bundle-schema.md` (new — the full bundle JSON
  shape key by key, hand-written prose per the zero-dependency/no-JSON-Schema
  convention, with a worked example), `.okf/generators.md` (scenario-mode
  generation, the override mechanism, the import-architecture fix),
  `.okf/cli.md`, and `CLAUDE.md`. Also documents a pre-existing, not
  previously written down v1 solver limitation surfaced while building the
  schema doc's worked example: `domains.py` treats `class_numeric`/
  `class_alphabetic` constraints as a no-op when picking a witness, so an
  `IS NUMERIC`/`IS ALPHABETIC`-gated arm is correctly targeted/covered but its
  pinned value is not yet guaranteed to satisfy that specific test (every
  other constraint form is fully solved). Covered by new tests in
  `tests/unit/test_program_fixtures.py` (`TestScenarioModes`, the csv-dir
  round-trip test) and `tests/contracts/test_fixture_bundle_contract.py`
  (`TestScenarioModeContract`).
* **generators:** `ScenarioPlanner` — constraints + control flow -> a named
  scenario set (`cobolparser/generators/scenarios.py`, 2026-08-04). Phase 5
  of the `gen-fixtures` program-scoped test-data initiative (see
  `docs/plans/2026-08-02-program-data-generation-design.md`): turns Phase
  4's `ConstraintReport` and `ProgramFlowAnalyzer`'s control-flow graph into
  a set of named `PlannedScenario`s — one (or a merge of several) per
  reachable, satisfiable branch arm — with exact arm-coverage accounting.

  Joins a `BranchConstraints` to its `BranchNode` via `(line, column)` only
  (`BranchConstraints` gained a new `column` field for this) — not by
  comparing `parent_proc` strings, since `program_flow/scanner.py`
  uppercases its own `parent_proc` while `ConstraintExtractor` preserves the
  source's casing, so the two are not directly comparable even for the same
  paragraph (found writing this phase's own tests). An OR-split arm
  (`"ELSE#1"`/`"ELSE#2"`) counts as full coverage of its base arm (`"ELSE"`)
  for coverage purposes; only a base arm with zero representation at all —
  bare or split — is a genuine miss (also found and fixed writing this
  phase's tests, which had double-reported an already-covered split arm as
  also missing).

  Two candidate scenarios merge when their constraints touch disjoint
  fields and their sequence constraints agree on every shared boundary
  (greedy, deterministic: `(line, column, arm_id)` order) — "fewer, richer
  scenarios" instead of one per arm. An arm is unsatisfiable (and lands in
  `coverage.missed`) when any field its conjuncts touch fails to solve via
  Phase 4's `domains.solve()` — every conjunct in an arm must hold
  simultaneously.

  `mode="all"` adds three fixed scenario families regardless of branching:
  empty input (every `IN` READ boundary at sequence length 0, every `IN`
  SQL boundary at SQLCODE 100), error status (one scenario per *declared*
  handler — `INVALID KEY` -> FILE STATUS 23, a CALL's `ON EXCEPTION` ->
  RETURN-CODE 12, an OPEN with a status field -> FILE STATUS 35 — never a
  status the program has no path for), and boundary values (every
  constrained numeric field pinned to its picture's true minimum/maximum).
  The boundary-values family pins via an `eq` constraint, not `ge`/`le` —
  found writing its own test: `domains.solve()`'s witness is always the
  interval's *midpoint*, so a bare `ge("0")` constraint produced a
  mid-range value, not `0`.

  v1 path-condition simplification, stated up front in the module
  docstring: a scenario targets one arm and takes only that arm's own
  conjuncts; enclosing branches on the path to it are not accumulated —
  full path-sensitivity is a v2 item.

  New `ArmOutcome` / `ScenarioCoverage` / `PlannedScenario` / `ScenarioPlan`
  / `ScenarioPlanner` public API in `cobolparser.generators.scenarios`.
  **Not yet wired into the `gen-fixtures` CLI**: `--scenarios branches|all`
  are still accepted but produce the same happy-path-only bundle as
  `happy` — turning a `PlannedScenario` into an actual `BoundaryFixture`
  -populated `bundle.Scenario` is deferred to Phase 6, matching Phase 3's
  own stated deferral of this flag's real behavior.

  Documented in `.okf/generators.md` (new "Scenario Planning" section),
  `.okf/analysis.md` (corrected `BranchConstraints` join guidance), and
  `.okf/cli.md`. Covered by `tests/unit/test_scenario_planner.py` and
  `tests/integration/test_scenario_planner_corpus.py` (parametrized over
  the shamrice corpus x `{branches, all}` modes: coverage accounting sums
  to the arm count for every program).
* **analysis:** `ConstraintExtractor` and the `domains.py` constraint solver —
  what a program's branches require of boundary data
  (`cobolparser/analysis/constraints.py`, `cobolparser/analysis/domains.py`,
  2026-08-04). Phase 4 of the `gen-fixtures` program-scoped test-data
  initiative (see `docs/plans/2026-08-02-program-data-generation-design.md`):
  walks IF/EVALUATE/SEARCH conditions and PERFORM UNTIL loop guards and, for
  every operand that resolves (via Phase 1's `ProgramLayoutIndex`) to a field
  a boundary actually feeds (per Phase 2's `BoundaryReport`), emits a
  `FieldConstraint` — relational comparisons, level-88 domains (`in_set`/
  `not_in_set` over the 88's already-parsed `condition_values`, THRU ranges
  included), figurative constants, class tests (`IS NUMERIC`/`ALPHABETIC`),
  and sign/zero tests (folded directly into the relational vocabulary rather
  than a separate domain branch). AND/OR/NOT compose via De Morgan — an IF's
  THEN and ELSE arms are the same expression tree walked with `negate=False`/
  `True`; a conjunction drops the whole variant if either side fails to
  extract (unsafe to narrow), a disjunction safely keeps whichever side(s)
  did (narrowing to fewer alternatives is still sound for witness
  generation). A READ's `AT END` flag tested by an enclosing `PERFORM UNTIL`
  becomes a `SequenceConstraint` instead — the "how many records before EOF"
  knob mockymock's own tally idiom needs, not a field value — cross-referenced
  against Phase 2's own `BoundaryReport` rather than a freshly synthesized
  reference.

  `domains.py`'s solver picks a deterministic witness (midpoint for a numeric
  interval, first allowed literal in sorted order for text, first remaining
  value for an enumerated level-88 domain) over a small zero-dependency
  domain lattice (`NumericDomain`/`TextDomain`/`EnumDomain`), always rendered
  through a new public `ValueFactory.render()` wrapper so a solved value can
  never violate the field's PICTURE — the same invariant the copybook
  generator's own value providers already guarantee. An unsatisfiable
  constraint set returns `Unsatisfiable(reason)`, never a value.

  New `FieldConstraint` / `SequenceConstraint` / `BranchConstraints` /
  `ConstraintReport` / `ConstraintExtractor` public API in
  `cobolparser.analysis.constraints`; `Witness` / `Unsatisfiable` / `solve()`
  in `cobolparser.analysis.domains`.

  Also fixes two issues found writing this phase's own tests: (1) a
  circular import between `cobolparser.generators.data.bundle` and
  `cobolparser.analysis.boundary_inventory` that only avoided surfacing by
  luck of import order (both edges were type-annotation-only or resolvable
  via `TYPE_CHECKING`, so no runtime behavior changes); (2) `>=`/`<=`/`<>`
  were silently mis-parsed as `>`/`<`/`<` with a garbled right-hand operand
  in *every* IF/PERFORM UNTIL condition — see Bug Fixes below.

  Documented in `.okf/analysis.md` (new `ConstraintExtractor` section) and
  `.okf/parser.md`; covered by `tests/unit/analysis/test_constraints.py`,
  `tests/unit/analysis/test_domains.py`, and
  `tests/integration/test_constraint_extractor_corpus.py` (parametrized over
  the shamrice corpus: every branch/loop either produces constraints or a
  reason in `unsupported`, and every solved witness is layout-valid).
* **generators:** `ProgramFixtureGenerator` and the `cobol-parser gen-fixtures`
  CLI subcommand — whole-program mock-data + expectation-stub generation
  (`cobolparser/generators/program_fixtures.py`,
  `cobolparser/generators/data/bundle.py`, 2026-08-04). Phase 3 of the
  `gen-fixtures` program-scoped test-data initiative (see
  `docs/plans/2026-08-02-program-data-generation-design.md`) — the first
  shippable release of the initiative: combines a Phase 1 `ProgramLayoutIndex`
  and a Phase 2 `BoundaryReport` into a `FixtureBundle` containing one "happy
  path" `Scenario` per program, with a `BoundaryFixture` (generated rows) for
  every IN/BIDIRECTIONAL boundary and an `Expectation` stub for every OUT
  boundary.

  Reuses the Phase 0 value engine (`ValueFactory`/`flatten_record`/`FieldSpec`)
  directly against arbitrary `CobolDataItem`s resolved through the layout
  index — the capability Phase 0 was built to unlock. Each boundary gets its
  own deterministic sub-seed (`zlib.crc32("scenario|category|key") ^ seed`),
  so adding or removing an unrelated boundary never reshuffles another
  boundary's already-generated values. `bundle.to_json()` is byte-identical
  for the same `(program, seed)` across runs and across unrelated corpus
  changes. CALL/DYNCALL fixtures generate one row per IN/BIDIRECTIONAL
  argument and an expectation stub per OUT/BIDIRECTIONAL argument (an OUT
  argument's note correctly reads "supplied by the program under test, not
  mock-generated" — the reverse of an IN argument's note). SQL fixtures stub
  `SQLCODE=0`; other status-bearing boundaries stub `"00"`. READ boundaries
  generate `--rows` rows per sequence; every other IN boundary (SQL
  SELECT/FETCH, ACCEPT, a CALL argument) generates exactly one value, matching
  one invocation in the happy-path scenario. `--callee-path` resolves a
  statically-CALLed program's own source (tried across `NAME`/`name` ×
  `""`/`.cbl`/`.CBL`/`.cob`/`.COB`) to feed Phase 2's callee-source rung; a
  compilation unit's own `contained_programs` need no path search at all.

  `report.unresolved`/`bundle.unresolved` now merge Phase 1's index-level
  gaps forward (previously dropped between phases — found via a `--strict`
  CLI smoke test against `report_test.cbl`'s known Report-Writer-FD gap
  incorrectly exiting 0 instead of 2). `--strict` exits 2 (not 1, which stays
  "could not run at all") when anything from Phase 1, 2, or 3 could not be
  pinned down. `--format csv-dir` writes one CSV per file-shaped fixture
  under `<dir>/<scenario-slug>/<KEY>.csv` plus a `MANIFEST.json` covering the
  full bundle. `--list-boundaries` runs Phases 1-2 only, for a cheap
  boundary-walk cross-check against a downstream consumer's own.

  New `BUNDLE_VERSION` / `FixtureBundle` / `Scenario` / `BoundaryFixture` /
  `Expectation` / `CoverageSummary` / `ProgramFixtureGenerator` public API,
  exported from `cobolparser.generators`. `bundle_version` is a schema
  version pinned for mockymock's Phase 8 `generate --with-data` consumer
  across the repo boundary.

  Documented in `.okf/generators.md` (new "Program Fixtures" section) and
  `.okf/cli.md` (new "Gen-Fixtures" section); covered by
  `tests/unit/test_program_fixtures.py`,
  `tests/unit/cli/test_gen_fixtures_cli.py`,
  `tests/integration/test_gen_fixtures_corpus.py` (parametrized over the
  shamrice corpus), and `tests/contracts/test_fixture_bundle_contract.py`
  (key-set and reproducibility pins for the cross-repo consumer).
* **analysis:** `BoundaryInventoryAnalyzer` — whole-program boundary inventory
  (`cobolparser/analysis/boundary_inventory.py`, 2026-08-04). Phase 2 of the
  `gen-fixtures` program-scoped test-data initiative (see
  `docs/plans/2026-08-02-program-data-generation-design.md`): walks the
  PROCEDURE DIVISION and emits one `Boundary` per mockable statement
  (CALL/DYNCALL, the eight file-op verbs, EXEC SQL/CICS/DLI, console ACCEPT),
  keyed the same way mockymock's own `mock_surface` module keys them (two
  independent walks over the same AST, re-deriving mockymock's unique-prefix
  key algorithm and non-interactive-ACCEPT-sources list rather than
  importing them — the dependency direction is mockymock -> cobol-parser,
  never the reverse). Each boundary's record/field layout resolves through
  a Phase 1 `ProgramLayoutIndex` built for the same program.

  CALL/DYNCALL arguments resolve through a 4-rung direction ladder
  (`CallArg.direction`/`.provenance`): `BY CONTENT`/`BY VALUE` is always OUT;
  a known callee's LINKAGE write (checked generically across MOVE,
  ADD/SUBTRACT/MULTIPLY/DIVIDE, COMPUTE, INITIALIZE, and SET — not just
  MOVE, which would miss a `COMPUTE LK-RESULT = ...` subprogram entirely) is
  IN; caller-side dataflow in the enclosing paragraph (last write
  before/first read after, in source order) is OUT/IN/BIDIRECTIONAL; the
  remaining fallback is BIDIRECTIONAL with `provenance="assumed-bidirectional"`.
  `RETURNING`/`GIVING` parameters are always IN. WRITE/REWRITE and READ
  `INTO` resolve through `ProgramLayoutIndex.record_named()` (new, see
  below) rather than `.resolve()`, since both name a whole record, not a
  field. SQL direction comes from `sql_type` over `host_variables` (the
  parent plan's assumed `into_variables`/`host_variables` split does not
  hold in practice — verified empirically, an inline `SELECT ... INTO`
  places every host variable in `host_variables`). CICS/DLI layout
  resolution is best-effort in v1 (no fixed INTO/FROM-shaped attributes to
  key off) and reports the limitation on the boundary rather than claiming
  false precision. `ACCEPT OMITTED` (waits for input, stores nothing) is
  recognized as a real idiom, not an unresolved gap.

  New `BoundaryInventoryAnalyzer` / `BoundaryRef` / `Boundary` / `CallArg` /
  `BoundaryReport` public API. Also adds `ProgramLayoutIndex.record_named()`
  — finds a whole record/group by name across all sections, filling a real
  gap `resolve()` cannot (it only ever indexes elementary fields, since
  `flatten_record` emits no `FieldSpec` for a group item), found via direct
  reproduction against `tests/samples/file_operations.cbl`'s REWRITE
  statement while building this analyzer.

  Documented in `.okf/analysis.md` (new `BoundaryInventoryAnalyzer` section)
  and `.okf/generators.md` (`record_named()`); covered by
  `tests/unit/analysis/test_boundary_inventory.py`,
  `tests/integration/test_boundary_inventory_corpus.py` (parametrized over
  the shamrice corpus), plus new `record_named()` cases in
  `tests/unit/test_program_layout_index.py`.
* **generators:** `ProgramLayoutIndex` — whole-program FD/record/field layout
  resolution (`cobolparser/generators/data/program_layout.py`, 2026-08-04).
  Phase 1 of the `gen-fixtures` program-scoped test-data initiative (see
  `docs/plans/2026-08-02-program-data-generation-design.md`): resolves a
  program's FILE SECTION FDs to their owning records, merges FD clauses with
  the matching `SelectStatement` into a `FileFacts` summary (organization,
  access mode, keys, `FILE STATUS` field, record size, FD-vs-SD), and
  resolves data-names (bare, `A OF B`, dotted `B.A`, and level-88 condition
  names) to a `ResolvedField` across all four DATA DIVISION sections. New
  `ProgramLayoutIndex` / `FileFacts` / `ResolvedField` / `ProgramLayoutError`
  public API, exported from `cobolparser.generators`.

  `ProgramLayoutIndex.build(ast)` indexes an already-parsed program;
  `.from_file(path, copybook_paths=..., strict_copybooks=...)` parses first,
  raising `ProgramLayoutError` on a missing file, a program that fails to
  parse, or (by default) an unresolved COPY member — a layout with a hole in
  it is wrong, not partial. Nothing is silently dropped or guessed: an
  ambiguous bare name (the same name at more than one path) is recorded on
  `.ambiguities`, and an unownable FILE SECTION record or a `SELECT` with no
  matching FD is recorded on `.unresolved`. A file with stacked/nested
  program units (`CobolProgram.contained_programs`) is indexed one program at
  a time — `build()` covers exactly the node it is given.

  The DATA DIVISION parser also gained a small, purely additive metadata tag:
  every FILE SECTION 01-item is now tagged `fd_record_type` (`"FD"` or
  `"SD"`) alongside the existing `fd_file_name`/`fd_clauses` tags, so an SD
  (sort/merge work file) can be told apart from a real file. Documented in
  `.okf/generators.md` and `.okf/parser.md`; covered by
  `tests/unit/test_program_layout_index.py` and
  `tests/integration/test_program_layout_corpus.py` (parametrized over the
  shamrice corpus).
* **generators:** copybook → CSV synthetic test-data generation
  (`cobolparser/generators/copybook_data.py`, 2026-08-02). New
  `CopybookDataGenerator` / `DataGeneratorOptions` / `GeneratedDataset` /
  `FieldSpec` / `FieldCategory` / `CopybookLayoutError` public API, exported
  from `cobolparser.generators`, plus a `cobol-parser gen-data` CLI
  subcommand that writes CSV to stdout or `--output`.

  Flattens a copybook record into one CSV column per elementary field and
  generates N rows of values that are always assignable to the field they
  came from: PICTURE category, size, digit counts and sign are enforced
  after every value provider. Level-88 `VALUE`s (including `THRU` ranges)
  bound a field's domain, `VALUE` clauses become constants, and optional
  field-name heuristics (NAME, CITY, ZIP, DATE, AMT, FLAG, …) make the data
  readable. `OCCURS` expands to one column per occurrence (`ITEM-CODE(1)`);
  `REDEFINES` and `FILLER` are excluded by default — a redefining item
  aliases bytes another column already covers, so emitting both would put
  contradictory values in one row.

  Generation is deterministic per `seed`: the same seed and copybook produce
  byte-identical CSV. An unseeded run records the seed it drew on
  `GeneratedDataset.seed` (surfaced by `gen-data --describe`) so it can be
  replayed. Copybook fragments are parsed by wrapping them in a program
  skeleton, with free-form fragments shifted into Area B first; a copybook
  holding only level-02+ items (meant to be `COPY`d inside an existing 01)
  gets a synthesised record root rather than being rejected. Documented in
  `.okf/generators.md`; covered by
  `tests/unit/test_copybook_data_generator.py`,
  `tests/unit/cli/test_gen_data_cli.py`,
  `tests/integration/test_copybook_csv_generation.py` (parametrized over the
  sample and NIST `.CPY` corpora), and
  `tests/contracts/test_copybook_data_generator_contract.py`.
* **parser:** SPECIAL-NAMES mnemonic-name clauses (`implementor-name IS
  mnemonic-name [ON STATUS IS cond] [OFF STATUS IS cond]`, e.g. `C01 IS
  TOP-OF-PAGE`, `CONSOLE IS CRT`, `UPSI-0 IS SWITCH-1 ON STATUS IS ...`)
  are now parsed into `special_names["mnemonic_definitions"]` instead of
  being silently discarded by the SPECIAL-NAMES paragraph's unknown-clause
  fallback. `WriteStatementParser`'s `BEFORE`/`AFTER ADVANCING` clause now
  also accepts an identifier target: a data-name holding a line count
  (followed by `LINE`/`LINES`, e.g. `ADVANCING WS-LINE-COUNT LINES`) is
  recorded as `{"unit": "LINES", "value": "WS-LINE-COUNT"}`, and a bare
  mnemonic-name (no `LINE`/`LINES` suffix, e.g. `AFTER ADVANCING
  TOP-OF-PAGE`) as `{"unit": "MNEMONIC", "value": "TOP-OF-PAGE"}`.
  Previously the identifier was left unconsumed and the procedure division
  scanner mis-parsed it as a bogus paragraph header. Pinned by
  `tests/unit/test_special_names.py` and `tests/unit/test_write_advancing.py`.
* **parser:** all-digit procedure names are supported (2026-07-20), closing
  the `PERFORM 1000 THRU 1999` numbering gap common in THRU-style COBOL.
  Numeric paragraph headers (`1000.`) are recognized as paragraphs
  (`procedure_boundaries.py` accepts all-digit NUMERIC_LITERAL /
  LEVEL_NUMBER tokens as procedure names), and the PERFORM parser accepts
  all-digit names as both the target and the THRU/THROUGH end. The inline
  `PERFORM n TIMES` form now decides via lookahead *before* consuming the
  numeric, so a numeric target is no longer swallowed as a failed TIMES
  count (previously `PERFORM 1000 THRU 1999` misparsed with
  `target_paragraph = "THRU"` and the numeric paragraphs were skipped as
  unsupported statements). Pinned by
  `tests/unit/test_perform_thru_numeric.py`.
* **preprocess:** conditional compilation is now functionally complete
  (open-findings M10). `>>IF` evaluates real conditions — comparisons
  (`=`, `<>`, `>`, `<`, `>=`, `<=`) against symbol values, `DEFINED(sym)` /
  `sym IS [NOT] DEFINED`, and `AND`/`OR`/`NOT` with parentheses — and
  `>>EVALUATE sym` / `>>EVALUATE TRUE` with `>>WHEN` / `>>WHEN OTHER` /
  `>>END-EVALUATE` block selection is implemented. Defined symbols may now
  carry values (`dict[str, str | int | float | bool]` accepted alongside
  the legacy name-only forms), so values supplied via the CLI's existing
  `--define NAME=VALUE` form now take effect in comparisons. An
  undefined symbol in a comparison warns and evaluates false; directive
  lines are still blanked in place so line numbers stay stable. Pinned by
  `tests/regression/test_open_findings_m10_regression.py`.
* **parser:** EXEC blocks now produce structured data (open-findings M11):
  `ExecCicsStatement.options` maps each CICS option keyword to its
  parenthesized argument (`None` for flag options like `ERASE`);
  `ExecImsStatement` captures the DLI function code and positional
  arguments (PCB, I/O area, SSAs); `parse_exec_sql` upgraded from regex
  scraping to a literal/comment-aware tokenizer adding `select_columns`
  and `where_present` plus better table/host-variable extraction
  (including `:VAR:IND` indicator form). All previous fields and
  `to_dict()` keys preserved. Pinned by
  `tests/regression/test_open_findings_m11_regression.py`.
* **parser:** structural expression trees (open-findings M12).
  `ComputeStatement.expression_tree` holds a precedence-parsed
  `ArithmeticExpression` tree (`**`, unary sign, subscripts, FUNCTION
  calls) while `.expression` stays byte-identical; `PERFORM UNTIL`
  conditions gain a `condition_tree` built by the IF parser's condition
  machinery, now factored into the shared
  `parsers/statements/_conditions.py`; the IF fallback path (class/sign/
  condition-name conditions) produces structured nodes with
  `metadata.raw_condition` still populated. New dict keys are emitted
  only when populated, so pre-existing output shapes are unchanged.
  Pinned by `tests/regression/test_open_findings_m12_regression.py`.
* **lexer:** `tokenize_cobol()` and CLI `tokenize` now run the same
  fixed-format pipeline as `parse_cobol()` (open-findings M6):
  `normalize_fixed_format` + free-form lexing, with comment lines
  re-emitted as `COMMENT` tokens at their original line numbers. The two
  paths now agree on every non-COMMENT token. Pinned by
  `tests/regression/test_open_findings_m6_regression.py`.

### Bug Fixes

* **cli:** two issues found by GitHub Copilot's automated review of PR #108
  (2026-08-04), both fixed rather than dismissed since verifying against the
  actual code confirmed both were real:
  - `gen-fixtures --describe` was registered on the argument parser but
    never read anywhere in `_cmd_gen_fixtures` -- a silent no-op with
    misleading help text ("Emit the resolved bundle as JSON (implied by
    --format json)", acknowledging its own redundancy with the already-
    default `--format json`). Removed the flag rather than implementing
    behavior for it, since there was nothing distinct left for it to do.
    Not previously documented in `CLAUDE.md`'s own `gen-fixtures` command
    line and not exercised by any test, consistent with it having been an
    unintentional carry-over from `gen-data`'s own (real, still-working)
    `--describe` flag.
  - `FixtureBundle.write_csv_dir()`'s `MANIFEST.json` replaced every
    fixture's `"sequence"` (normally `list[dict[str, str]]`) with a hint
    string (`"see <scenario-slug>/"`), silently changing its type. A
    consumer that ran `MANIFEST.json` through the same deserializer as a
    real bundle JSON -- reasonable, since every other key matches the
    normal schema -- would iterate the string character-by-character in
    place of real rows rather than hit a clean type error. Fixed:
    `sequence` now stays `[]` in the manifest; a new `csv_path` key (the
    CSV's path relative to the output directory, or `null` for a fixture
    that got no CSV written) carries the same "where are the rows"
    information the removed hint string carried, without the type
    mismatch. New test:
    `test_program_fixtures.py::TestWriteCsvDir::test_manifest_sequence_stays_a_list_not_a_hint_string`.
    Documented in `docs/fixture-bundle-schema.md` and `.okf/generators.md`.
* **generators:** `ProgramFixtureGenerator`'s READ `terminal` (the `AT END`
  status dict) fell back to a literal placeholder field name, `"FILE-STATUS"`,
  when a READ boundary had no declared `FILE STATUS` clause and no file-level
  default either (2026-08-04, found empirically integrating mockymock's
  `generate --with-data` against a real bundle — INVUPDT's `INV-FILE` has no
  status field at all). That placeholder is not a real data item in the
  program, so a `MOVE "10" TO FILE-STATUS` mock body would either target a
  nonexistent field or, worse, a coincidentally-real one with an unrelated
  meaning. Fixed by `_resolve_status_field` returning `None` (not a string)
  when neither `Boundary.status_field` nor `ProgramLayoutIndex.file_facts(...)
  .file_status_field` resolves, and `terminal`/`status` staying `None`/`{}`
  rather than synthesizing a name — mirroring this initiative's own established
  "exact by construction, or absent" rule (see `ConstantFolder` above) instead
  of guessing. A second, related bug in the same code path was fixed in the
  same commit: the READ fixture's `call_count` expectation derived "does this
  boundary have an AT-END invocation" from whether `terminal` was non-`None`,
  which after this fix conflates "the sequence exhausts" with "the exhaustion
  has a nameable status field" — the two are now tracked independently
  (`has_terminal_invocation` vs. the resolved field name), so `call_count`
  stays correct (`len(sequence) + 1`) even when the terminal status itself
  can't be named. `tests/unit/test_program_fixtures.py` gained
  `TestTerminalStatusFieldResolution` (both the no-field and the
  real-field-resolves cases) and an updated assertion in
  `test_empty_input_scenario_call_count_is_one_not_zero`. See
  [.okf/log.md](.okf/log.md) and mocky-mock's own
  `tests/unit/test_fixture_bundle_contract.py`, which surfaced this via its
  Phase 8 `generate --with-data` integration.
* **parser:** `>=`, `<=`, and `<>` in an IF condition or a `PERFORM ...
  UNTIL` loop guard were silently mis-parsed as `>`, `<`, and `<` with a
  garbled right-hand operand (2026-08-04, found writing Phase 4 of
  `gen-fixtures`, see Added above). The lexer emits these as two separate
  single-character tokens — confirmed empirically, not assumed — and
  `parsers/statements/_conditions.py`'s token-cleaning pass only recombined
  `NOT`-prefixed pairs (`NOT EQUAL`, `NOT <`, ...), so the comparison scan
  matched the bare `>`/`<` first and left the trailing `=`/`>` dangling in
  the operand text: `IF WS-X >= 5` parsed as `operator="GREATER",
  right_operand="= 5"` instead of `operator="GREATER_OR_EQUAL",
  right_operand="5"`. Affected every consumer of
  `build_condition_expression` (IF and PERFORM UNTIL both) for as long as
  the M12 structural-condition machinery has existed — not a regression
  from this fix, a pre-existing gap it closes. Fixed by recombining the
  pair (`_COMPOUND_SYMBOL_OPS`) during the same cleaning pass, before the
  scan runs. Zero regressions across the existing 783 IF/PERFORM/
  shamrice/NIST tests re-run after the fix. See
  [.okf/parser.md](.okf/parser.md).
* **preprocess:** copybook content's sequence-number (columns 1-6) and
  identification (columns 73-80) areas are now stripped immediately after a
  copybook is read from disk, before `REPLACING`, `>>IF` conditional
  compilation, or content/level-number validation ever see the text
  (2026-07-21). Previously those columns were only stripped *after*
  `apply_replacing_clauses` ran, so a length-changing `REPLACING` clause
  shifted every character after its match point on the raw 80-column line:
  a shrinking replacement (e.g. `==LONGNAME==` by `==X==`) pulled
  identification-area text into the kept code window, silently inserting
  garbage into the parsed program, while a growing replacement pushed real
  code past column 72 and truncated it — including, in the worst case, its
  terminating period, which would silently merge two statements. Separately,
  a copybook using real (non-blank) numeric sequence numbers defeated
  `>>IF`/`>>END-IF` recognition entirely (the directive check saw the
  sequence-number digits before `>>`), so conditional blocks inside such
  copybooks were never evaluated. `apply_replacing_clauses` gained an
  `indicator_position` parameter (mirroring `normalize_continuation_lines`)
  so it can correctly locate the indicator column in already-stripped text,
  and `_expand_source_recursive` gained an `already_stripped` parameter so
  the same content isn't stripped twice. Pinned by
  `tests/regression/test_copybook_sequence_area_before_replacing.py`.
* **parser:** a `PICTURE` clause with no terminating period, immediately
  followed by what looks like the next data item's own `level-number
  data-name` header, no longer silently absorbs that header into its
  pattern and drops the next item (and all of its children) from the AST
  (2026-07-21). The picture-pattern loop treats a NEWLINE as "more pattern
  may follow" for legitimate multi-line PICTURE clauses; since the lexer
  types every 1-2 digit integer as `LEVEL_NUMBER` regardless of context and
  `LEVEL_NUMBER` is a collected picture-pattern token type, a bare level
  number belonging to the *next* entry (`05  BARIABLE`) was appended to the
  previous item's pattern (`"9(08)05bariable"`) with `result.success ==
  True` and `result.warnings == []` — no signal at all. The most common
  real-world trigger is fixed-format column-72 truncation:
  `normalize_fixed_format` extracts only columns 8-72 (confirmed empirically
  to match GnuCOBOL 3.2's own column-72 truncation semantics — GnuCOBOL
  hard-errors on the same truncated shape rather than accepting it), so a
  terminating period placed at column 73+ vanishes from the normalized text.
  The loop's NEWLINE branch now looks ahead past the newline for a
  LEVEL_NUMBER that cannot legally be more picture pattern: either its
  value contains a digit other than `0`/`9` (the only two digit-shaped
  PICTURE symbols — e.g. the `5` in `05`, which also catches an
  *anonymous* next item with no data-name at all, such as a bare
  `05  REDEFINES ...`), or it's immediately followed by an IDENTIFIER (a
  named or `FILLER` data item). When found, the clause stops there instead
  of consuming the newline, and a `ParseResult.warnings` entry is recorded.
  Applies to both the pure-Python and `_data_fast` Cython-accelerated paths
  (both delegate PICTURE parsing to the same `parse_picture_clause`).
  Pinned by `tests/regression/test_picture_clause_missing_terminator.py`,
  including explicit parent/child re-attachment assertions (the original
  defect didn't just drop the next item — its children were misattached to
  the preceding sibling).
* **parser:** `ADD ... TO` no longer drops a subscripted target's subscript
  (2026-07-21). `ADD 1 TO TABLE-ITEM (I, J, K)` previously captured only
  `TABLE-ITEM` as the target and left `( I , J , K )` unconsumed as an
  "Unparsed tokens" content-drop warning; in a two-statement paragraph the
  resulting recovery could drop a *following* subscripted `ADD` statement
  from the AST entirely. `AddStatementParser` now consumes its target via
  the same subscript-aware helper `COMPUTE` already uses, so
  `AddStatement.target` is `"TABLE-ITEM ( I , J , K )"`, the same shape
  COMPUTE produces for subscripted targets. Pinned by
  `tests/unit/test_arithmetic_migration.py::test_add_statement_with_subscripted_target`
  and `::test_add_statement_with_subscripted_target_and_giving`.
* **parser:** `SUBTRACT ... FROM` and the shared arithmetic `GIVING` clause
  (ADD/SUBTRACT/MULTIPLY/DIVIDE) also dropped a subscripted target's
  subscript (2026-07-21) — the same bug class as the `ADD ... TO` fix
  above. `SUBTRACT 1 FROM VARIABLE (H, I, 1)` captured only `VARIABLE`, and
  `ADD 1 TO A GIVING RESULT (H, I, 1)` captured only `RESULT`, each
  leaving `( ... )` unconsumed as an "Unparsed tokens" content-drop
  warning. `SubtractStatementParser`'s `FROM` branch now routes identifier
  targets through the same `_consume_arithmetic_target` helper as ADD/
  COMPUTE, and `_utils.consume_keyword_and_operand` (used by every
  arithmetic statement's `GIVING` clause) now folds a trailing
  `(subscript[, subscript]...)` group into its returned value. Pinned by
  `tests/unit/test_arithmetic_migration.py::test_subtract_statement_with_subscripted_target`,
  `::test_add_statement_with_subscripted_giving_target`, and
  `tests/unit/test_utils_clause_collection.py::TestConsumeKeywordAndOperand::test_consumes_subscripted_target`.
* **analysis:** program-flow reachability honors THRU ranges (2026-07-20).
  `find_unreachable_nodes` now treats every `FlowEdge.range_members` entry
  (PERFORM/SORT/MERGE ... THRU) as a neighbor of the edge's source, so an
  intermediate paragraph of a performed range is no longer falsely listed
  in `unreachable_nodes` when its incoming fall-through edge is suppressed
  (e.g. the preceding member contains a GO TO). Cycle detection still uses
  only explicit edges. Pinned by
  `tests/unit/analysis/test_program_flow_thru_reachability.py`.
* **parser:** a `REDEFINES` clause whose target data-name sits on the next
  line (`01 WS-B REDEFINES` / newline / `WS-A PIC 9(10).`) no longer
  silently drops the redefines target: both the pure-Python clause loop
  (`DataItemClauseParser`) and the `_data_fast` Cython fast path now skip
  NEWLINE tokens between the `REDEFINES` keyword and its target, matching
  the multi-line handling the OCCURS clause already had. Pinned by the
  multi-line cases in `tests/unit/test_data_division_branches.py::TestRedefinesClause`.
* **parser:** the `ADVANCING` keyword in WRITE's `BEFORE`/`AFTER` phrase is
  now optional, matching the standard grammar (2026-07-20). `WRITE rec
  AFTER 1`, `AFTER 1 LINE`, `AFTER 2 LINES`, and `BEFORE PAGE` previously
  consumed the `BEFORE`/`AFTER` token but required a literal `ADVANCING`
  before recording anything — the clause was silently dropped
  (`advancing_clause=None`), and a trailing `LINE`/`LINES` was left in the
  stream to surface as an "Unparsed tokens" content-drop warning. The
  count/`LINES`/`LINE`/`PAGE` parsing now runs whether or not `ADVANCING`
  is present, producing the same `advancing_clause` dict as the explicit
  form. Pinned by `tests/unit/test_write_advancing.py`.
* **preprocess:** COPY `REPLACING` is now context-aware (open-findings
  M13): substitution never rewrites fixed-format comment lines or text
  inside string literals (doubled-quote escapes handled; a clause whose
  own search text contains a quote still targets literals deliberately),
  and `:ABC:` pseudo-text delimiters are recognized and stripped so
  colon-delimited operands actually substitute instead of silently
  no-opping. Pinned by
  `tests/regression/test_open_findings_m13_regression.py`.
* **preprocess:** copybook encoding detection and decode strictness
  (open-findings M15): `detect_encoding` now compares ASCII-vs-EBCDIC
  plausibility scores over a bounded 64 KiB prefix (BOM/strict-UTF-8
  checks first; COBOL charset proportion, EBCDIC newline conventions,
  keyword tiebreaker) instead of the fragile 0x40-byte-ratio heuristic,
  and a new `encoding_errors` option (`CopybookSearchPath` /
  `expand_copybooks`) selects `"replace"` (default; warns with a
  replacement count) or `"strict"` (raises `EncodingError` with
  file/offset context) for undecodable bytes. Pinned by
  `tests/regression/test_open_findings_m15_regression.py`.
* **parser:** `VALUE ALL <literal>` data-item clauses are now parsed instead
  of being dropped with an "Unparsed token" content-drop warning. `ALL`
  lexes as a figurative constant, so `parse_value_clause` previously
  consumed it as a complete value and left the repeated literal behind —
  `05 FILLER PIC X(133) VALUE ALL '='.` (the common report-separator idiom)
  produced `value_clause="ALL"` plus a `PARSE_WARNING` that made mockymock
  refuse the whole program. Now `VALUE ALL '='` → `value_clause='ALL "="'`
  and `VALUE ALL ZEROS` → `'ALL ZEROS'`, both round-tripping as legal
  COBOL for downstream `MOVE <value> TO <item>` splicing. Pinned by
  `tests/regression/test_value_all_clause.py`.
* **parser:** IDENTIFICATION DIVISION boundary checks are now comment-entry
  aware. COBOL-74 comment-entries (AUTHOR, SECURITY, REMARKS, ...) end only
  at the next Area A entry, and `normalize_fixed_format` preserves Area A/B
  as indentation — so a phony program embedded in Area B inside a
  comment-entry (NIST `OBNC1M`) no longer terminates the division early or
  spawns a bogus second program unit. The relative-column check
  self-calibrates for free-form sources. Per COBOL-74, *any* line-starting
  Area A token — not just recognized clause keywords — ends an active
  comment-entry, in both the clause-value loop and the main clause loop.
  Pinned by `tests/regression/test_comment_entry_area_b.py`. With this and the
  pseudo-text fixes below, **all 459 NIST COBOL-85 programs now parse
  error-free** (`KNOWN_ISSUES` is empty; `SM101A` is parsed through the
  copybook-expansion pipeline it requires by design, via
  `REQUIRES_COPYBOOK_EXPANSION`).

* **preprocess:** implement COBOL source-text pseudo-text substitution before
  lexing (`cobolparser/preprocess/replace_statement.py`), wired into
  `CobolParser._parse_core`. Two NIST COBOL-85 programs now parse error-free
  and were removed from `KNOWN_ISSUES`:
  * `apply_replace_statements` applies the `REPLACE ==a== BY ==b== [==c== BY
    ==d== ...] .` compiler-directing statement (one or more operand pairs) and
    cancels the active set at `REPLACE OFF.`. Matching is on the COBOL
    *text-word* stream — whitespace-, comma-, and semicolon-insensitive between
    words, with a separator period treated as its own text word and literals
    compared exactly — so multi-word / multi-line pseudo-text (including a
    pseudo-text operand that itself contains a period or a statement keyword)
    matches regardless of layout. Fixes `SM208A.CBL` (30x `REPLACE`), where the
    raw pseudo-text (`MOVE "*" AO WRK-XN-00001`, `==MOVE "FAIL" TO==`) had been
    leaking into the statement stream as malformed MOVEs.
  * `strip_unexpanded_copy_statements` blanks `COPY` statements the standalone
    pipeline is not going to expand — reusing the pseudo-text-aware
    `CopyStatementLexer` — so a `COPY ... REPLACING ==pseudo-text==` operand
    that legally contains a bare `MOVE` token (`SM206A.CBL`'s `BY MOVE
    ==DELETE==`) no longer leaks as a `MOVE` with no `TO`. In the
    copybook-expansion pipeline COPY is already inlined before this point, so
    the strip is a no-op there.
  Both passes preserve the physical line count of their input. Pinned by
  `tests/regression/test_replace_and_copy_pseudo_text.py`.
* **parser:** exclude clause-continuation keywords (`DELIMITED`, `TALLYING`,
  `POINTER`, ...) and SQL special registers (`SQLCODE`/`SQLSTATE`) from
  `looks_like_paragraph_boundary`. Fixes real-world layouts — a multi-source
  `STRING` with each `DELIMITED BY SIZE` clause on its own continuation
  line, and a period-less `DISPLAY` before a bare `SQLCODE` — that were
  silently truncating the AST. The period/`SECTION` lookahead is kept:
  dropping it misreads continuation-line operands named by *unexpanded*
  COPY members as boundaries (caught by mocky-mock's copybook fixtures).
  Pinned by `tests/regression/test_clause_continuation_boundary.py`.
* **analysis (2026-08-06): `ConstantFolder` no longer crashes with an
  uncaught `RecursionError` on an ordinary large program.** `_walk_perform`
  followed a chain of out-of-line `PERFORM`s (`P1` performs `P2` performs
  `P3` ... `PN`) by recursing through Python's own call stack, one frame per
  paragraph — a few hundred chained paragraphs (well under
  `sys.getrecursionlimit()`'s default of 1000) was enough to crash, and
  every `gen-fixtures` call reaches this path unconditionally.
  `_poison_written_names` had the identical defect for a
  `PERFORM`-to-paragraph chain reached from inside a poisoned loop/branch
  body. Both now follow the chain via an explicit frame stack instead of
  recursion — the same fix `program_flow/cycles.py` already applies to its
  own paragraph-graph traversal — while genuinely nested statement lists
  (bounded by real source nesting, not paragraph-chain length) still use
  ordinary recursion. Pinned by
  `tests/unit/analysis/test_const_fold.py::TestPerformChaining` (2000-chain
  tests for both paths, plus a sequential-re-PERFORM regression test).

### Fixed

* **parser (2026-08-07): `SYNCHRONIZED IS LEFT` and `JUSTIFIED IS RIGHT` dropped
  both the `IS` and the `LEFT`/`RIGHT` direction as two separate "unparsed
  token" warnings on a clean, standards-compliant parse.**
  `DataItemClauseParser`'s `SYNCHRONIZED`/`JUSTIFIED` branches
  (`cobolparser/parsers/divisions/data_clauses.py`) consumed the clause
  keyword but never checked for a following optional `IS`, so it fell
  through to the generic drop-with-warning branch, and the `LEFT`/`RIGHT`
  token after it doesn't match any dispatch branch on its own either — two
  warnings for one clause. (This is the same family of bug as the leading
  `IS` before `[IS] EXTERNAL`/`[IS] GLOBAL`/bare `POINTER`-family usage,
  fixed independently the same day in the same dispatch loop — see the `IS`
  branch above `REDEFINES` in `data_clauses.py`.) Added `IS` consumption to
  both branches, mirroring the existing `SIGN` clause's `[IS]` handling.
  Pinned by the new
  `TestSynchronizedJustifiedIsClause` class in
  `tests/regression/test_parser_completeness.py`.
* **parser (2026-08-07): `SET pointer-var TO ADDRESS OF identifier` was
  misparsed, silently corrupting the surrounding PROCEDURE DIVISION.**
  `SetStatementParser`'s `TO` branch (`cobolparser/parsers/statements/set_parser.py`)
  captured only the single token immediately after `TO` as the statement's
  value; for `ADDRESS OF identifier`, that consumed just the `ADDRESS`
  token, leaving `value: "ADDRESS"` and the trailing `OF identifier` tokens
  unconsumed on the stream. Those leftover tokens were then silently
  reinterpreted by the enclosing PROCEDURE DIVISION parser as spurious
  paragraph headers (`OF` and the identifier each became an empty
  paragraph) — `result.success` stayed `True` with zero errors/warnings.
  This is the mirror image of H1 (`reports/open-findings.md`), which fixed
  the same `ADDRESS OF` construct on the *target* side
  (`SET ADDRESS OF x TO y`); the value-side form was never covered by that
  fix or its regression tests. The `TO` branch now recognizes a leading
  `ADDRESS OF` prefix on the value, consumes both keywords, and stores the
  underlying identifier as `value` with a new `SetStatement.value_is_address_of`
  boolean flag so downstream consumers can distinguish a pointer/address
  assignment from a plain `SET x TO y`. Pinned by
  `tests/regression/test_open_findings_high_regressions.py::TestH1bSetToAddressOf`.
* **parser (2026-08-05): INVOKE, ALLOCATE, and FREE are now parsed instead of
  silently discarded.** All three are real, valid IBM Enterprise COBOL verbs
  (`INVOKE` for Object-Oriented method calls; `ALLOCATE`/`FREE` for dynamic
  storage) that previously had no registered statement parser: they hit
  `ProcedureDivisionParser`'s "unsupported statement" recovery path, which
  discards the statement's tokens up to the next boundary and records only a
  warning, leaving `result.success` `True` with an incomplete AST. Added
  `InvokeStatementParser` -> `InvokeStatement` (object identifier, literal or
  identifier-held method name, `USING [BY REFERENCE|CONTENT|VALUE]`
  parameters, `RETURNING`) and `AllocateStatementParser`/
  `FreeStatementParser` -> `AllocateStatement`/`FreeStatement` (byte-count
  `CHARACTERS` form or `BASED` data-item form, `INITIALIZED`, `RETURNING`;
  one or more pointer names). `ALLOCATE`/`FREE` deliberately have no
  dedicated lexer `TokenType` — they are matched by value only at a genuine
  statement-start position, so a data item legitimately named `ALLOCATE` or
  `FREE` is unaffected everywhere else. See
  [.okf/parser.md](.okf/parser.md). Pinned by
  `tests/regression/test_invoke_allocate_free_statements.py`.
* **lexer (2026-08-05): seven `KEYWORDS` entries reserved words that never
  matched real syntax, silently corrupting legitimately-named data items,
  paragraphs, and condition names.** `FILE-STATUS`, `RECORD-DELIMITER`, and
  `READ-ONLY` were mapped as single hyphenated tokens, but real COBOL syntax
  always writes them as two separate words (`FILE STATUS`, `RECORD
  DELIMITER`, `READ ONLY`) — every clause parser that recognizes them
  (`environment_select.py`) already dispatches on the leading word and
  consumes the second as plain text, so the fused-word entry never matched
  genuine syntax. `END-SET` and `OTHERWISE` are not COBOL reserved words at
  all (`SET` has no scope terminator; EVALUATE's default branch is `WHEN
  OTHER`, not `OTHERWISE`). `END-OF-FILE`/`EOF` are not reserved words either
  — they are exactly the condition-name real IBM programs conventionally
  give their end-of-file level-88 flag (confirmed by the project's own
  `parsers/statements/_conditions.py` docstring, which already cited `IF
  END-OF-FILE` as the canonical bare condition-name example this bug broke).
  Verified via a full sweep of all 194 `KEYWORDS` entries: these seven were
  the only ones with zero non-lexer consumers anywhere in the codebase.
  Removed from `KEYWORDS` so all seven now lex as plain `IDENTIFIER`; the
  two-word clauses they were named after are unaffected. See
  [.okf/lexer.md](.okf/lexer.md). Pinned by
  `tests/regression/test_dead_keyword_removal.py`.
* **parser (2026-08-05): EJECT compiler-directing statements were misparsed
  as bogus paragraphs, or warned about as unsupported.** `EJECT` (the
  page-eject listing directive) had no `TokenType`/keyword entry and no
  statement parser, so `EJECT.` — written between two real paragraphs, the
  common real-world style — was indistinguishable from a paragraph name to
  the PROCEDURE DIVISION's boundary scanner (a bare `IDENTIFIER` token
  followed by a period) and silently split the enclosing paragraph in two,
  inserting an empty `EJECT` paragraph into the AST. Written without a
  trailing period, it instead fell through to the "unsupported statement"
  recovery path and emitted a spurious `"Unparsed tokens starting at
  'EJECT' ... clause or statement not fully supported"` warning. Both
  failure modes reproduced identically through COPY-expanded copybook text,
  since expansion flattens the copybook into the surrounding source before
  the lexer ever sees it. Fixed by giving EJECT its own `TokenType` (so it
  can never be mistaken for an `IDENTIFIER`-typed paragraph name) and a real
  `EjectStatementParser` -> `EjectStatement` no-op node, mirroring
  `ContinueStatementParser`/`ContinueStatement`. See
  [.okf/parser.md](.okf/parser.md). Pinned by
  `tests/regression/test_eject_statement.py`.
* **lexer (2026-08-05):** `NULL`/`NULLS` are now recognized as figurative
  constants (`TokenType.FIGURATIVE_CONSTANT`), matching the COBOL standard's
  use of `VALUE IS NULL` for `USAGE POINTER`/`PROCEDURE-POINTER`/
  `FUNCTION-POINTER` data items in WORKING-STORAGE, and `SET ptr TO NULL` /
  `IF ptr = NULL` in the PROCEDURE DIVISION. Previously the word fell through
  to a generic `IDENTIFIER` token, indistinguishable from a real data-name —
  several analysis modules already carried private `NULL`/`NULLS`
  figurative-constant lists in anticipation of this, but the lexer itself had
  never been updated to match. See
  [.okf/lexer.md](.okf/lexer.md#null--nulls-figurative-constants-2026-08-05).
  Pinned by `tests/regression/test_null_pointer_value_clause.py`.
* **parser (2026-07-24 targeted follow-up round):** two more bugs found by
  checking the remaining known list-collecting loops for the same
  comma-handling property — see [.okf/parser.md](.okf/parser.md) "Follow-up
  comma-list sweep" targeted round. `CALL ... USING BY REFERENCE|CONTENT|
  VALUE`'s passing mode didn't persist across a comma-separated parameter
  list within one BY-phrase group (`BY CONTENT a, b` silently mode-tagged
  `b` back to REFERENCE) — a silent semantic corruption, not a data-drop.
  `COMPUTE id-1, id-2 = expr` (comma-separated multi-target) was a **hard
  parse failure** ("COMPUTE statement missing '=' operator", no AST node
  produced) — worse than every other fix in this bug class. SEARCH's
  WHEN-condition collector and READ/WRITE's INTO/FROM clauses were checked
  and confirmed to need no fix (neither takes a list). Pinned by 7 new
  tests in `tests/unit/test_initialize_sort_arithmetic_comma_gaps.py`
  (29 total).
* **parser (2026-07-24 follow-up comma-list sweep):** five more instances
  of the comma-separated-list truncation bug class below, found by
  re-verifying the parsers the 2026-07-22/23 sweep didn't cover — see
  [.okf/parser.md](.okf/parser.md) "Follow-up comma-list sweep
  (2026-07-24)". `INITIALIZE id-1, id-2, ...` (warned drop).
  `SORT`/`MERGE` `{ASCENDING|DESCENDING} KEY field-1, field-2 ...` —
  **fully silent** (`errors=[], warnings=[]`), the worst instance of this
  bug class found so far. `SORT`/`MERGE` `USING`/`GIVING file-1, file-2
  ...` — also fully silent (same shared file-list helper).
  `ADD`/`SUBTRACT`/`MULTIPLY`/`DIVIDE ... GIVING id-3, id-4 ...`
  (multi-target `GIVING`, symmetric with the `TO`/`FROM` multi-target fix
  below, which didn't extend to `GIVING`; new
  `ArithmeticStatement.givings: list[str]` field). `MULTIPLY x BY id-2,
  id-3` / `DIVIDE x INTO id-2, id-3` — format 1 (no `GIVING`) has the same
  gap on its own second-operand target list, which is distinct from
  `GIVING`'s (found via second-opinion review rather than the repro sweep
  itself); `MultiplyStatement`/`DivideStatement` now populate
  `.target`/`.targets` for this form (previously only `.operands`), while
  format 2 (`GIVING`) deliberately does not gain a spurious `.target`.
  Pinned by `tests/unit/test_initialize_sort_arithmetic_comma_gaps.py`
  (22 tests).
* **parser (2026-07-22/23 statement-support verification sweep):** nine
  silent-drop/gap fixes found by re-verifying statement parsers against
  real COBOL grammar shapes — see [.okf/parser.md](.okf/parser.md)
  "Statement-Support Verification Sweep (2026-07-22/23)" for full detail
  per fix. Summary:
  * Comma-separated operand lists previously truncated at the first comma
    (dropping every later item, and often leaking the abandoned names as
    phantom paragraphs): `CALL ... USING a, b, c` (also fixed: `OMITTED`
    as a USING parameter dropped every parameter from the first `OMITTED`
    onward), `SET ix1, ix2 UP BY 1`, `UNSTRING ... INTO a, b, c`,
    `DISPLAY a, b, c`, `GO TO a, b, c DEPENDING ON x`,
    `CANCEL prog-a, prog-b`, `ENTRY 'X' USING a, b` (the last one worse
    than a drop — the literal `","` token was captured as a parameter
    name, corrupting arity).
  * `UNSTRING ... DELIMITED BY d1 OR d2 ...` now collects every delimiter
    (previously only the first survived); `TALLYING IN counter`
    (documented, never implemented) now works.
  * `EXEC CICS` lost its command verb when written on the line after
    `EXEC CICS` (the idiomatic layout); EXEC SQL/DLI text reconstruction
    inserted a spurious space when rejoining a lexer-split `>=`/`<=`/`<>`
    operator.
  * `INSPECT TALLYING`/`REPLACING` `BEFORE`/`AFTER INITIAL` now accepts
    both qualifiers on one phrase, in either order (previously: one
    qualifier, fixed order only).
  * `PIC N(n)` (national/DBCS) sized as 1 regardless of `n`; now sized
    correctly. `USAGE IS <keyword>` (and bare `USAGE DISPLAY-1`) silently
    downgraded to plain `DISPLAY` — the optional `IS` (and the
    `DISPLAY-1` token type) weren't recognized.
  * `START ... KEY IS GREATER THAN OR EQUAL TO key-name` never consumed
    the trailing `TO`, which blocked the key-name and `INVALID
    KEY`/`NOT INVALID KEY` parsing entirely.
  * `WRITE ... AT END-OF-PAGE` / `NOT AT END-OF-PAGE` (format-1,
    sequential files) was entirely unimplemented — only format-2's
    `INVALID KEY` worked.
  * `OPEN INPUT a OUTPUT b`-style multi-mode-group statements collapsed
    every file onto the first group's mode; added a per-file
    `IOOpenStatement.file_modes` map (`.open_mode` alone is ambiguous for
    later files). Known follow-up, not yet done:
    `analysis/crud_matrix.py`/`io_logger.py` still read `.open_mode`
    alone.
  * `ADD`/`SUBTRACT` never checked `ROUNDED`; only captured a single
    target (COBOL allows a comma/space-separated list, losing extra
    targets' values and `ROUNDED` flags); misparsed `CORRESPONDING` as a
    literal operand named `"CORRESPONDING"`. `DIVIDE ... REMAINDER` was
    entirely unimplemented. All four now supported
    (`ArithmeticStatement.targets`/`.rounded`/`.is_corresponding`,
    `DivideStatement.remainder`). Self-review follow-up in the same PR:
    the new multi-target loop could itself swallow a following paragraph
    header as a bogus target when the period was missing — now guarded
    the same way `MOVE` is (H9 pattern).
  * `DISPLAY ... UPON device-name` dropped any following clause (e.g.
    `WITH NO ADVANCING`) and left the sentence period unconsumed, which
    the procedure scanner misread as a phantom `"."` paragraph.
  * `ACCEPT ... FROM ENVIRONMENT "name"` dropped the variable name (the
    model field existed; nothing populated it).
  * `STOP` (`STOP RUN.` and all other forms) never consumed its sentence
    period, producing a phantom empty `"."` paragraph after every STOP —
    the same symptom class as the DISPLAY UPON fix above, and as the next
    item.
  * The PROCEDURE DIVISION scanner's EOF sentinel token (empty value,
    not in the keyword-exclusion set) fell through the "unknown token →
    new paragraph" fallback and manufactured a phantom empty-named,
    zero-statement trailing paragraph on **every** program lacking a
    final named paragraph header — inflating `total_lines`/
    `procedure_count` by one on nearly all real-world input. Found via a
    backend integration test outside this repo, not by this repo's own
    suite.

### Changed

* **generators:** internal restructure — `copybook_data.py`'s implementation
  has been decomposed into a modular package `cobolparser/generators/data/`
  with focused modules: `options.py` (DataGeneratorOptions),
  `errors.py` (CopybookLayoutError), `layout.py` (FieldCategory, FieldSpec,
  flatten_record), `values.py` (ValueFactory), `dataset.py` (GeneratedDataset),
  and `copybook.py` (parse_copybook_records, CopybookDataGenerator).
  `copybook_data.py` is now a backwards-compatible re-export shim; every
  existing import path (`from cobolparser.generators import
  CopybookDataGenerator`) and the `cobol-parser gen-data` CLI subcommand are
  unaffected. `ValueFactory` and `flatten_record` are newly usable directly
  against any `CobolDataItem`, not just a copybook-parsed one, supporting
  future program-data-generation initiatives.
* **parser:** internal refactor — `DataDivisionParser`
  (`cobolparser/parsers/divisions/data.py`, ~1,467 lines) decomposed into
  focused collaborators: `data_clauses.py` (`DataItemClauseParser` — data-item
  entries and their PICTURE/VALUE/USAGE/OCCURS/... clauses, including the
  optional `_data_fast` Cython fast path), `data_file_description.py`
  (`FileDescriptionClauseParser` — FD/SD clause capture), and
  `data_special_entries.py` (`SpecialEntryParser` — level-88 condition names,
  level-66 RENAMES, data-division EXEC SQL blocks). `DataDivisionParser` stays
  at its original import path, keeps the section scan / hierarchy build / AST
  creation, and delegates entry parsing; `_parse_picture_clause`,
  `_parse_value_clause`, and `_parse_usage_clause` remain on the class with
  their exact signatures because the compiled `_data_fast` extension calls
  them back by name. No behavior or public API changes.
* **parser:** internal refactor — `EnvironmentDivisionParser`
  (`cobolparser/parsers/divisions/environment.py`, ~1,133 lines) decomposed
  into focused collaborators: `environment_sections.py`
  (`ConfigurationSectionParser` — CONFIGURATION SECTION + SPECIAL-NAMES;
  `InputOutputSectionParser` — INPUT-OUTPUT SECTION + FILE-CONTROL) and
  `environment_select.py` (`SelectClauseParser` — SELECT statements, all
  clause parsers, and `SelectStatement` AST node construction).
  `EnvironmentDivisionParser` stays at its original import path, keeps the
  division scan loop and AST creation, and delegates section/SELECT parsing.
  No behavior or public API changes.
* **parser:** internal refactor — `ProcedureDivisionParser`
  (`cobolparser/parsers/divisions/procedure.py`, ~912 lines) decomposed into
  focused collaborator modules: `procedure_registry.py`
  (`create_statement_registry()` — builds the shared
  `StatementParserRegistry` with all 40+ statement parsers),
  `procedure_boundaries.py` (paragraph/section/statement boundary lookahead
  predicates), and `procedure_recovery.py` (`StatementRecoveryHandler` —
  unsupported-statement warnings, FAIL_FAST/COLLECT_ALL error recording, and
  stream resynchronization; also hosts the `STRAY_MARKERS` /
  `UNSUPPORTED_VERBS` sets, aliased on the class for introspection).
  `ProcedureDivisionParser` stays at its original import path, keeps the
  paragraph/section dispatch loop, ParseContext attachment, and AST
  creation, and delegates the rest. No behavior or public API changes.
* **analysis:** internal refactor — `cobolparser/analysis/program_flow.py` (a ~987-line god class) is now the package `cobolparser/analysis/program_flow/` with focused collaborators: `models.py` (report dataclasses), `scanner.py` (procedure collection + statement scanning), `edges.py` (edge construction + edge-type categories), `cycles.py` (cycle detection/classification), `graph.py` (fall-through, convergence, reachability post-passes), and `analyzer.py` (the `ProgramFlowAnalyzer` orchestrator). No behavior or public API changes: all imports from `cobolparser`, `cobolparser.analysis`, and `cobolparser.analysis.program_flow` keep working, and `to_dict()` output is byte-identical.

## [1.9.0](https://github.com/Landparty/cobol-parser/compare/v1.8.4...v1.9.0) (2026-09-04)


### Features

* **generators:** make a scenario verify that its own data reaches the branch it names ([b66e836](https://github.com/Landparty/cobol-parser/commit/b66e8362099b87ee830db916d6e5087bb282cd41))
* **generators:** per-row witness pinning for cross-record correlation ([f8a9662](https://github.com/Landparty/cobol-parser/commit/f8a9662b2091eb1dd83a755c7da85f5061d1e2c2))
* **generators:** scenarios verify that their own data reaches the branch they name ([d8a25e4](https://github.com/Landparty/cobol-parser/commit/d8a25e4eb54ef0414e6880908b4760976d6b7c06))
* **parser:** parse REPORT SECTION; structured XML/JSON handler and PROCESSING PROCEDURE clauses ([d06a372](https://github.com/Landparty/cobol-parser/commit/d06a37267a2c59e73ad0798e4444e30f62f5b17e))
* **parser:** support every COBOL verb and close silent statement drops ([ebd055d](https://github.com/Landparty/cobol-parser/commit/ebd055d6c5d7eb01627c2dda2d4e582bb99ceb84))


### Bug Fixes

* **analysis:** make numeric set-op enforcement reachable in _apply_numeric ([cc98c95](https://github.com/Landparty/cobol-parser/commit/cc98c959da92c656b334cb4ceed8a64ada8385eb))
* **analysis:** seed level-88 branch scenarios with the arm's own values ([17e7f33](https://github.com/Landparty/cobol-parser/commit/17e7f33eca8cc7deaa6855c4512e5fe1d0075e8f))
* **generators:** fold disjunctive enclosing arms, and stop losing path gaps ([256bb14](https://github.com/Landparty/cobol-parser/commit/256bb1411ca65b82c4aca85be244da6f1007c43e))

## [1.8.4](https://github.com/Landparty/cobol-parser/compare/v1.8.3...v1.8.4) (2026-09-01)


### Bug Fixes

* closed-source release wheels fail cibuildwheel's post-install tests ([3314262](https://github.com/Landparty/cobol-parser/commit/3314262fd64d857630daccaa04d855e20df3dfc0))
* closed-source release wheels fail cibuildwheel's post-install tests ([d1a0704](https://github.com/Landparty/cobol-parser/commit/d1a0704cdf80ed6600d30960c6933a109224ca5e))

## [1.8.3](https://github.com/Landparty/cobol-parser/compare/v1.8.2...v1.8.3) (2026-09-01)


### Bug Fixes

* **generators:** closed-source build raised TypeError on every classified statement ([b896692](https://github.com/Landparty/cobol-parser/commit/b89669253346d935d7a86505ce87ce80dcd5d68f))


### Documentation

* fix interface-contract.md drift from actual code ([9aee63f](https://github.com/Landparty/cobol-parser/commit/9aee63f5c2ddfb8fe8c8844a01b14eaacab980f8))

## [1.8.2](https://github.com/Landparty/cobol-parser/compare/v1.8.1...v1.8.2) (2026-08-30)


### Bug Fixes

* avoid Cython compiler crash on (x or default).method() pattern ([5b0dbd3](https://github.com/Landparty/cobol-parser/commit/5b0dbd3b89e630801bda897079e2a7ac1ee9baf6))
* avoid Cython compiler crash on (x or default).method() pattern ([6c389b4](https://github.com/Landparty/cobol-parser/commit/6c389b4422388579d769b5e53358e3cd52fed2ac))

## [1.8.1](https://github.com/Landparty/cobol-parser/compare/v1.8.0...v1.8.1) (2026-08-28)


### Bug Fixes

* address /code-review findings on the corpus-hardening series ([365e7c4](https://github.com/Landparty/cobol-parser/commit/365e7c4a89d06fbcc01cae4832a62a3ed7ed973d))
* ALTER and computed GO TO accept all-digit paragraph names ([9ee1be6](https://github.com/Landparty/cobol-parser/commit/9ee1be6eb358084cf3c7ca6f51906f8cee83fa04))
* **core:** stop find_all_by_type cache aliasing and wire up ASTNodeFactory validators ([82db123](https://github.com/Landparty/cobol-parser/commit/82db1235d6844b5fcd257191abd8410ff35ef50f))
* **core:** stop find_all_by_type cache aliasing and wire up ASTNodeFactory validators ([5ec1433](https://github.com/Landparty/cobol-parser/commit/5ec143348ee68ac5b51870327c89118a993fa855))
* five real-corpus parser bugs (MOVE continuation targets, EXEC SQL operators, PROGRAM-ID period, SET subscripts, SKIP1-3) ([e8ac0ea](https://github.com/Landparty/cobol-parser/commit/e8ac0ea61b016b643c303b23612c580ef2b0129d))
* five real-corpus parser bugs (MOVE continuation targets, EXEC SQL operators, PROGRAM-ID period, SET subscripts, SKIP1-3) ([50a928c](https://github.com/Landparty/cobol-parser/commit/50a928cf6a7a1324879b0818451b726cd2258faf))
* five residual findings from a follow-up 105-program corpus sweep ([1409e05](https://github.com/Landparty/cobol-parser/commit/1409e05726a573fbdb5d5b6f2584b4521ce7dda3))
* harden corpus-retry fixes per review findings ([096cd4f](https://github.com/Landparty/cobol-parser/commit/096cd4f6af3c9ae7ab9a9e5e0a2b871802d56870))
* **lexer:** reconstruct COMMENT tokens for V/v lines too ([c2c6d1c](https://github.com/Landparty/cobol-parser/commit/c2c6d1c21852924dde1ba554e906fc92c0c6959d))
* **parser,cli:** harden tagged-sequence-area detection and forced-layout plumbing ([1ce22f2](https://github.com/Landparty/cobol-parser/commit/1ce22f2e4bff8662ee67632a164837a9526609ce))
* **parser:** close SKIP1/SKIP2/SKIP3 boundary-detection gap vs EJECT ([d037ec8](https://github.com/Landparty/cobol-parser/commit/d037ec8de56570bc38071c402a28f855efdec4ec))
* **parser:** consume explicit scope terminator on arithmetic statements ([b2c7097](https://github.com/Landparty/cobol-parser/commit/b2c70976a419eacd3dbe83ef4b609a787fd3bd0e))
* **parser:** detect fixed-format source with change-tracking tags in cols 1-6 ([a39f37d](https://github.com/Landparty/cobol-parser/commit/a39f37d54c8c5f925816f3e8c7f55e77d47342d6))
* **parser:** double embedded quotes when re-emitting a decoded literal ([5e5b992](https://github.com/Landparty/cobol-parser/commit/5e5b9926a78e83909b19dea94b124f580f2d36f1))
* **parser:** fix MOVE qualifier chain, dangling OF/IN, unbalanced paren ([a937851](https://github.com/Landparty/cobol-parser/commit/a937851e9decf06318b885c6107550e4f3ee611a))
* **parser:** fold ADD/SUBTRACT/MULTIPLY/DIVIDE OF/IN qualifier chains into operands/targets ([965a8e5](https://github.com/Landparty/cobol-parser/commit/965a8e563308f2f418f6e63ae39406f7853b3fd4))
* **parser:** fold GIVING/REMAINDER and addend-list OF/IN qualifiers too ([df6c507](https://github.com/Landparty/cobol-parser/commit/df6c507849503c7ca8c2851734f2faecf974f111))
* **parser:** skip CONTINUATION tokens in qualifier chains, fix test realism ([99c4dcc](https://github.com/Landparty/cobol-parser/commit/99c4dcc76f97457934d0f2f1f9a5e1b88065d6f0))
* **preprocess:** don't warn on numeric identification-area stamps past column 72 ([9d660b5](https://github.com/Landparty/cobol-parser/commit/9d660b56e7cc9ba3604e57659db29b6a18786314))
* **preprocessing:** stop strip_sequence_area mangling flush-left PROCESS/CBL directives ([ea2c214](https://github.com/Landparty/cobol-parser/commit/ea2c214ff018d2d75d802c753c817b253a1932e9))
* **preprocessing:** treat V/v in column 7 as a comment line ([c55c4f5](https://github.com/Landparty/cobol-parser/commit/c55c4f514b745083b49d5346e2339ef64306fbf7))
* resolve the corpus retry's four remaining warning buckets ([8546d1b](https://github.com/Landparty/cobol-parser/commit/8546d1b64f15966ee645ae06231a25b6767714a8))
* resolve the corpus retry's four remaining warning buckets (OCCURS splits, signed VARYING, REPLACING overflow, change tags) ([40ecf3f](https://github.com/Landparty/cobol-parser/commit/40ecf3fed7fe916fc2a9eb2d0f65bcf48a095f05))
* review-driven corrections to real-corpus parser fixes ([1a9eea4](https://github.com/Landparty/cobol-parser/commit/1a9eea450e4f5ab2365013bad400736b27b74eb1))
* second controlled re-probe fixes - operand-list drops, digit-led names, SET values, SQL not-sign ([9e74d36](https://github.com/Landparty/cobol-parser/commit/9e74d36cff5d21b258a5da6554a2a09100bf69aa))
* three more verified diff-scan findings on the corpus series ([fbefe84](https://github.com/Landparty/cobol-parser/commit/fbefe84a9c4d4f548de2e62dd159cbeddbbaec56))

## [1.8.0](https://github.com/Landparty/cobol-parser/compare/v1.7.8...v1.8.0) (2026-08-20)


### Features

* implement closed-source verification checks and enhance build process ([ba102c6](https://github.com/Landparty/cobol-parser/commit/ba102c6b3052f08df2bd755838433b77726820ed))
* **parser:** enhance CLI help with examples for subcommands ([b64e26a](https://github.com/Landparty/cobol-parser/commit/b64e26a27df6193fd7c11db8f9ffc6ebcbe419a7))


### Bug Fixes

* prevent closed-source build segfault on free-form COBOL parsing ([d549531](https://github.com/Landparty/cobol-parser/commit/d549531ab9386a0a242265832e9eabd7473a7ccb))

## [1.7.8](https://github.com/Landparty/cobol-parser/compare/v1.7.7...v1.7.8) (2026-08-18)


### Bug Fixes

* **analysis:** 2026-08-16 analyzer-subcommand audit — 9 confirmed bugs ([a1678b0](https://github.com/Landparty/cobol-parser/commit/a1678b0b6997535d0f419a7ecab6bc8aed5eb95c))
* **analysis:** merge only MOVE-tracked values into group-SSA segment names ([8c43778](https://github.com/Landparty/cobol-parser/commit/8c437789fc2455dfef476e537a45263966f88836))
* **analysis:** UnusedVariableAnalyzer misses EVALUATE subject usage ([7b9be42](https://github.com/Landparty/cobol-parser/commit/7b9be421226e8a13c84ac4756d6f34064320647d))
* **analysis:** UnusedVariableAnalyzer misses EVALUATE subject usage ([486cb08](https://github.com/Landparty/cobol-parser/commit/486cb08234aea41d6c7d09a07db0e76ceda6b963))
* **cli:** surface incomplete dynamic-call values and ignored --profile; add analyzer CLI gap tests ([7e0c2dd](https://github.com/Landparty/cobol-parser/commit/7e0c2ddcde2c8cf20ad79655834c13faee7be48f))
* **cobolparser:** EVALUATE subjects reach .operands; WHEN Literal selectors scanned ([9b35521](https://github.com/Landparty/cobol-parser/commit/9b355216277d3c6bd4f9f569c34957b2f79e8ff4))
* **cobolparser:** EVALUATE subjects reach .operands; WHEN Literal selectors scanned ([4eb21bb](https://github.com/Landparty/cobol-parser/commit/4eb21bbc6f95c2ad78c462a6a2737ccc9e594d55))


### Documentation

* **analysis:** tag UnusedVariableAnalyzer's documented gaps as TODOs ([270da6f](https://github.com/Landparty/cobol-parser/commit/270da6fcc45ca3ffdaa8edb14352eddd392d1ce0))
* **okf:** reword awkward parenthetical in analyze subcommand description ([0105f16](https://github.com/Landparty/cobol-parser/commit/0105f1643a6abd59acbcd7598c323dfb100f0a56))
* update CLAUDE.md to match current repo state ([c9d7086](https://github.com/Landparty/cobol-parser/commit/c9d7086f33e3526a0dc1e822265d51eca71b00b4))

## [1.7.7](https://github.com/Landparty/cobol-parser/compare/v1.7.6...v1.7.7) (2026-08-16)


### Bug Fixes

* sync release-please package-name with pyproject.toml project name ([0ba507c](https://github.com/Landparty/cobol-parser/commit/0ba507c19f0c00e77804a05ae96f07090d11a754))

## [1.7.6](https://github.com/Landparty/cobol-parser/compare/v1.7.5...v1.7.6) (2026-08-16)


### Bug Fixes

* update project name from "cobolparser" to "cobol-parser" in configuration and documentation ([7db246a](https://github.com/Landparty/cobol-parser/commit/7db246a65ec53139fa5db8b680d6463ab5e5d447))

## [1.7.5](https://github.com/Landparty/cobol-parser/compare/v1.7.4...v1.7.5) (2026-08-15)


### Bug Fixes

* correct project name from "cobolparser" to "cobol-parser" in configuration files ([12215f5](https://github.com/Landparty/cobol-parser/commit/12215f52a9f36d9cd70c840b29a0599437978b8c))

## [1.7.4](https://github.com/Landparty/cobol-parser/compare/v1.7.3...v1.7.4) (2026-08-15)


### Bug Fixes

* clarify comments on test job gating and execution conditions ([515f8ba](https://github.com/Landparty/cobol-parser/commit/515f8baa8d205669021d7aba14dfb3b48287c35b))
* update CI conditions for build and test jobs to run on PRs and manual dispatch only ([9a7173a](https://github.com/Landparty/cobol-parser/commit/9a7173ac08ee341500ffa4b4bf845a0a2cb8b0d4))

## [1.7.3](https://github.com/Landparty/cobol-parser/compare/v1.7.2...v1.7.3) (2026-08-15)


### Bug Fixes

* streamline cibuildwheel targets and skip musllinux for closed-source builds ([6a77d9c](https://github.com/Landparty/cobol-parser/commit/6a77d9c18f5341f543b47f1f936f19a86366fac9))

## [1.7.2](https://github.com/Landparty/cobol-parser/compare/v1.7.1...v1.7.2) (2026-08-15)


### Bug Fixes

* update version to 1.7.1 and enhance release workflow for closed-source builds ([138ea2d](https://github.com/Landparty/cobol-parser/commit/138ea2dcdd299df00a2f384edc0b4040cbc16db6))

## [1.7.1](https://github.com/Landparty/cobol-parser/compare/v1.7.0...v1.7.1) (2026-08-15)


### Bug Fixes

* enhance CI configuration for pytest parallelization and caching ([a66b99f](https://github.com/Landparty/cobol-parser/commit/a66b99f4dd6b74be47c4d41dcb1e977474c3c869))
* enhance CI configuration for pytest parallelization and caching ([c4b8bc3](https://github.com/Landparty/cobol-parser/commit/c4b8bc36a5df056fdd3ad1f78a697539337f1a20))

## [1.7.0](https://github.com/Landparty/cobol-parser/compare/v1.6.0...v1.7.0) (2026-08-14)


### Features

* add closed-source Cythonized build mode ([851b0ed](https://github.com/Landparty/cobol-parser/commit/851b0ed77070e7c310bd3c681c3cedfa2ddc7817))
* add data-items CLI subcommand ([f539e7b](https://github.com/Landparty/cobol-parser/commit/f539e7b7273a7753f1e1fc07bc46e6c331b5df6e))
* compute per-record byte offsets for flat data items ([bae53f4](https://github.com/Landparty/cobol-parser/commit/bae53f4fbed2a7b8ad189bf2521535e88adf741e))
* compute_program_data_items walks all DATA DIVISION sections ([41a2fda](https://github.com/Landparty/cobol-parser/commit/41a2fda296d275b66109f0b20702f9eae17ebcbc))
* data-items analyzer — byte offset, REDEFINES chains, level-88 values ([ab04245](https://github.com/Landparty/cobol-parser/commit/ab0424533f2c58747f257d471b2f564a5dbbaa67))
* multiply OCCURS footprint for offset advancement ([acff4c9](https://github.com/Landparty/cobol-parser/commit/acff4c9de49af6d9ef1a3a543b3d90eea02c40f0))
* recurse into nested group items for offset computation ([eb382ba](https://github.com/Landparty/cobol-parser/commit/eb382ba35c0bc684e00e4775e43ef12fe8314921))
* resolve REDEFINES chains as contiguous offset-sharing slots ([72efcd1](https://github.com/Landparty/cobol-parser/commit/72efcd1b24ffbe6a2f66dee6ec269d29c144132e))


### Bug Fixes

* add pytest-cov to cibuildwheel test-requires for --no-cov flag ([b563f0e](https://github.com/Landparty/cobol-parser/commit/b563f0e0a2715bc7f5176791769e052441484ad3))
* address Copilot PR review findings ([c1181e6](https://github.com/Landparty/cobol-parser/commit/c1181e64afee15600fb0f58745c4449ee1397d5d))
* consume CobolParser initial_warnings after the first parse() call ([c75e9fe](https://github.com/Landparty/cobol-parser/commit/c75e9fe825b71bc400d67e29b6a8b5da802368ac))
* final-review fixes for data-item layout (root-level 88s, misnested 77) ([83b3745](https://github.com/Landparty/cobol-parser/commit/83b37455debeb8aa77ed6ad26875d07ac85c9dd6))
* keep fixed-format column constants on cobolparser.preprocess ([e0d3f1a](https://github.com/Landparty/cobol-parser/commit/e0d3f1a092a1cdb7e01cb15ddb973b1a542de569))
* propagate OCCURS DEPENDING ON ambiguity across nested groups ([6ebc28d](https://github.com/Landparty/cobol-parser/commit/6ebc28d317d9c5de95c1b20fa52cfd012cdc67ee))
* recover misnested level-77 items dropped as a group's only child ([1500925](https://github.com/Landparty/cobol-parser/commit/1500925fa38c1f7a0fd74a96222807e7dd899c30))
* recover misnested level-77 items dropped as a group's only child ([0ae4e67](https://github.com/Landparty/cobol-parser/commit/0ae4e67a79aca055dd3e112b50fccbfdefa8e2dc))
* satisfy lint gates on closed-source build mode ([9a70e07](https://github.com/Landparty/cobol-parser/commit/9a70e07bd37b24beb82cb85fd0a9d790149cccc2))
* satisfy ruff import-sort line-length on test_layout_offsets.py ([555248d](https://github.com/Landparty/cobol-parser/commit/555248dd5fb910cd5704fb976da6f3638dab87f6))
* stop closed-source wheels from leaking readable source ([b5f2dee](https://github.com/Landparty/cobol-parser/commit/b5f2deeadcc8d92e064934abf26278b0f5e82ad5))
* surface fixed-format column-72 overflow warnings, close word-boundary gap ([d59e635](https://github.com/Landparty/cobol-parser/commit/d59e635b2a4da78b5288401f5b9be93920a61aaf))
* surface fixed-format column-72 overflow warnings, close word-boundary gap ([affeb7a](https://github.com/Landparty/cobol-parser/commit/affeb7afcebbb596f7b514cc80fb8e88c23df9ae))


### Documentation

* add design spec for closed-source PyPI release ([5529a30](https://github.com/Landparty/cobol-parser/commit/5529a3000ff3fc96291c86e184b5adc6a957d4eb))
* add implementation plan for closed-source PyPI release ([0739d80](https://github.com/Landparty/cobol-parser/commit/0739d80ba09fb6db9881a066b2dbf2c4deff8b6a))
* restore explanatory comments in expand_condition_values ([ac82cd7](https://github.com/Landparty/cobol-parser/commit/ac82cd764b87c4a9613427631c4a0b43d8ad722a))

## [1.6.0](https://github.com/Landparty/cobol-parser/compare/v1.5.6...v1.6.0) (2026-08-14)


### Features

* add UnusedVariableAnalyzer and unused-variables CLI subcommand ([b5ca723](https://github.com/Landparty/cobol-parser/commit/b5ca723dfdc7e20737b93ec7d73ae1ee874c406d))
* add UnusedVariableAnalyzer and unused-variables CLI subcommand ([d525fc2](https://github.com/Landparty/cobol-parser/commit/d525fc27f07a076b45197b2e1d7ad28b0cc6e570))


### Bug Fixes

* DeadCodeAnalyzer no longer resurrects dead siblings via section propagation ([b3b5c6f](https://github.com/Landparty/cobol-parser/commit/b3b5c6ffb970ad64ef52da67854e39d461227dd6))
* DeadCodeAnalyzer no longer resurrects dead siblings via section propagation ([74e6150](https://github.com/Landparty/cobol-parser/commit/74e6150eead83c778019a37c765445b28971882e))
* extract identifiers from operand text instead of treating it as one name ([799741e](https://github.com/Landparty/cobol-parser/commit/799741e398f9934bd995467d6819e423e89fc9a0))
* recognize SCREEN/REPORT/COMMUNICATION SECTION headers in DATA DIVISION ([71839d7](https://github.com/Landparty/cobol-parser/commit/71839d73ff62cd21afa3674cba6f18039e55b420))
* recognize SCREEN/REPORT/COMMUNICATION SECTION headers in DATA DIVISION ([a0c44b3](https://github.com/Landparty/cobol-parser/commit/a0c44b3489197d3de7506d93998f0f7bd69d37a7))
* unblock CI — mypy narrowing + black formatting drift on main ([916ffe8](https://github.com/Landparty/cobol-parser/commit/916ffe8682b86713b8721260c81249f80b908789))

## [1.5.6](https://github.com/Landparty/cobol-parser/compare/v1.5.5...v1.5.6) (2026-08-13)


### Bug Fixes

* correct COPY-under-equal-level structural bugs; add regression test ([471e4d3](https://github.com/Landparty/cobol-parser/commit/471e4d36fbb2207372a91d3bd24e16ee6c11fe8f))

## [1.5.5](https://github.com/Landparty/cobol-parser/compare/v1.5.4...v1.5.5) (2026-08-13)


### Bug Fixes

* program-flow label fidelity (ASCII, &lt;/&gt; escaping, arm statement summaries) ([c086c20](https://github.com/Landparty/cobol-parser/commit/c086c205cab9a7ba532339409bdbb3ff8640ef55))
* program-flow label fidelity (ASCII, &lt;/&gt; escaping, arm summaries) ([94490a2](https://github.com/Landparty/cobol-parser/commit/94490a2a2996168c6e64cab910f8361ac4e9ef50))
* render double quotes in mermaid labels as apostrophes, not #quot; ([5600be5](https://github.com/Landparty/cobol-parser/commit/5600be5bb774c5643eef6b8742ff916aacbbb1fe))

## [1.5.4](https://github.com/Landparty/cobol-parser/compare/v1.5.3...v1.5.4) (2026-08-12)


### Bug Fixes

* Decimal witness pipeline, DIVIDE mode, and statement-text fidelity ([42ad49e](https://github.com/Landparty/cobol-parser/commit/42ad49efbf75af4cb0e8c33377b23b26f756b1e6))
* Decimal witness pipeline, DIVIDE mode, and statement-text fidelity ([daa16e6](https://github.com/Landparty/cobol-parser/commit/daa16e681c6624b4937560f6da7b4e06d1e6fcb8))
* move CobolParseError alias below imports to satisfy ruff E402 ([4d71636](https://github.com/Landparty/cobol-parser/commit/4d71636c06664e4ae8b555cba512baad98123d5d))
* quote Mermaid edge labels to survive parens/brackets ([05609ef](https://github.com/Landparty/cobol-parser/commit/05609ef870a505edb6eb14f41cbb7b58061a4761))
* repair integration/tooling gaps from the 2026-08-12 audit ([2ad01e3](https://github.com/Landparty/cobol-parser/commit/2ad01e36f45fd385e12b0dae442b9d1c1adb5e6c))
* resolve 12 analysis/generator audit findings ([2dc1e15](https://github.com/Landparty/cobol-parser/commit/2dc1e1590add395b199bf7210350ef8e9b57a46a))
* resolve core parsing pipeline audit findings ([13087eb](https://github.com/Landparty/cobol-parser/commit/13087ebb9497914f9f362ec9a26082c9fd01f884))
* resolve findings from the 2026-08-12 follow-up audit ([b495f26](https://github.com/Landparty/cobol-parser/commit/b495f26047554b57eea441363d156d5d64df07bb))


### Performance Improvements

* cache ASTNodeFactory's constructor-shape check per node class ([024214d](https://github.com/Landparty/cobol-parser/commit/024214d25bea86d37e39a7f1dddecb7637ea50c0))


### Documentation

* add 2026-08-12 full-repo audit report ([3044277](https://github.com/Landparty/cobol-parser/commit/304427786861ef357999437ebcbfe71bd33092ad))
* add follow-up repo audit — new bugs and gaps post-PR[#137](https://github.com/Landparty/cobol-parser/issues/137) ([26a9f91](https://github.com/Landparty/cobol-parser/commit/26a9f91b92b2807ce41114b827f3724af279615f))
* clarify Mermaid #quot wording comment ([4d76c6c](https://github.com/Landparty/cobol-parser/commit/4d76c6c11ab9abc910d24c9d0a37d4bff5afe183))
* refresh counts/versions, changelog the audit fixes, track open items ([7433e1c](https://github.com/Landparty/cobol-parser/commit/7433e1cac7da18e4f5e48e4bab18d1b96db48dd5))

## [1.5.3](https://github.com/Landparty/cobol-parser/compare/v1.5.2...v1.5.3) (2026-08-11)


### Bug Fixes

* address PR [#127](https://github.com/Landparty/cobol-parser/issues/127) review feedback on flow conditions and stop handling ([17fa400](https://github.com/Landparty/cobol-parser/commit/17fa40033b7de6c45423e42fb016e7281270cc51))

## [1.5.2](https://github.com/Landparty/cobol-parser/compare/v1.5.1...v1.5.2) (2026-08-11)


### Bug Fixes

* paragraphs holding ENTRY statements never treated as reachable roots ([9267ce6](https://github.com/Landparty/cobol-parser/commit/9267ce640568de2021d23c52e7f9835c8f86a655))

## [1.5.1](https://github.com/Landparty/cobol-parser/compare/v1.5.0...v1.5.1) (2026-08-10)


### Bug Fixes

* update string compression method and path separator in _lexer_fast.c ([8197d5e](https://github.com/Landparty/cobol-parser/commit/8197d5ec7d9418443f85f30034762fb6c0791cb7))

## [1.5.0](https://github.com/Landparty/cobol-parser/compare/v1.4.0...v1.5.0) (2026-08-10)


### Features

* **bundle:** sanitize boundary keys to prevent directory traversal attacks ([1761898](https://github.com/Landparty/cobol-parser/commit/17618983f584f13032952c15b47c585ade9eda00))


### Bug Fixes

* **data-division:** stop dropping content on IS-prefixed clauses and EXEC SQL after a missing period ([621705a](https://github.com/Landparty/cobol-parser/commit/621705aa0e072caa598485d3096e810d475535ae))
* **data-division:** stop dropping content on IS-prefixed clauses and EXEC SQL after a missing period ([46e1e0a](https://github.com/Landparty/cobol-parser/commit/46e1e0a7d043999453fd30c3f03e6af33c0326a4))
* **data-division:** tolerate line breaks in the IS/EXEC-SQL clause lookaheads ([c7731df](https://github.com/Landparty/cobol-parser/commit/c7731dfb7b1bf440e8f4dcd09b9d23d6f0de01c2))
* **lexer:** strip free-form *&gt; inline comments before parsing ([e1eba54](https://github.com/Landparty/cobol-parser/commit/e1eba54c7fdac014387fb8f2901b47181656794a))
* **lexer:** strip free-form *&gt; inline comments before parsing ([a2a6f3b](https://github.com/Landparty/cobol-parser/commit/a2a6f3b26ddc9f2c361af33b3feb43a27d57185c))
* **parser:** SET var TO ADDRESS OF x was misparsed, corrupting following paragraphs ([c64deb1](https://github.com/Landparty/cobol-parser/commit/c64deb11c75fd9716264fe4203afbe07068bf2c8))
* SET var TO ADDRESS OF x was misparsed, corrupting following paragraphs ([6885637](https://github.com/Landparty/cobol-parser/commit/6885637eba2e26a930c8d19e8b19975636e4590b))
* **tests:** use pytest.skip for missing Cython extension in parity test ([961715d](https://github.com/Landparty/cobol-parser/commit/961715df7601b07abeda8a8e1a57d3911bcba3de))

## [1.4.0](https://github.com/Landparty/cobol-parser/compare/v1.3.0...v1.4.0) (2026-08-07)


### Features

* **analysis:** BoundaryInventoryAnalyzer -- Phase 2 of program-scoped fixture generation ([f9532c1](https://github.com/Landparty/cobol-parser/commit/f9532c1b746016abac1b94b08901e10508a3c61f))
* **analysis:** ConstraintExtractor + domains.py solver -- Phase 4 of program-scoped fixture generation ([022b262](https://github.com/Landparty/cobol-parser/commit/022b2621d70f8639ae6968247e50316c4d503633))
* **generators:** ProgramFixtureGenerator + gen-fixtures CLI -- Phase 3 of program-scoped fixture generation ([b4c71ad](https://github.com/Landparty/cobol-parser/commit/b4c71adea20ca53bc289ca2c1f5488169e12c7cd))
* **generators:** ProgramLayoutIndex -- Phase 1 of program-scoped fixture generation ([565b764](https://github.com/Landparty/cobol-parser/commit/565b7641ff327afb53c2c5f578ac62c95889f7f4))
* **generators:** ProgramLayoutIndex -- Phase 1 of program-scoped fixture generation ([fe5ce8f](https://github.com/Landparty/cobol-parser/commit/fe5ce8f114d4ec4c7e1aa9b0fee562aba449dc6e))
* **generators:** ScenarioPlanner -- Phase 5 of program-scoped fixture generation ([1d68b34](https://github.com/Landparty/cobol-parser/commit/1d68b3457d63701f103a917564327fe4ee6d4105))
* **generators:** wire --scenarios branches|all into FixtureBundle -- Phase 6 of program-scoped fixture generation ([03dca60](https://github.com/Landparty/cobol-parser/commit/03dca6025a2ed915dd3978697af9216d654b2991))


### Bug Fixes

* **cli:** remove dead gen-fixtures --describe flag; fix write_csv_dir manifest type ([33b984e](https://github.com/Landparty/cobol-parser/commit/33b984e8b366d6767166fc707ef4b9ad32211a84))
* **generators:** hard-cap OCCURS expansion to prevent memory blowup ([1631219](https://github.com/Landparty/cobol-parser/commit/1631219fe93dbe02352badf604e46217bcb141e8))
* **generators:** restore csv_path info in write_csv_dir manifest ([2a56db0](https://github.com/Landparty/cobol-parser/commit/2a56db0a95b4ed1cdbc70b081569edf9f1d62f3b))
* **lexer:** recognize NULL/NULLS as figurative constants ([0a09fd1](https://github.com/Landparty/cobol-parser/commit/0a09fd1a7b0f47a6562019fbb49031493da36c8d))
* **parser:** recognize EJECT so it can't be misparsed as a paragraph or copybook boundary ([e41dff9](https://github.com/Landparty/cobol-parser/commit/e41dff95c68d597a9e70eb8a7210fe9483e0ca22))


### Documentation

* CHANGELOG.md, .okf/generators.md, .okf/cli.md, docs/fixture-bundle-schema.md, .okf/log.md. ([33b984e](https://github.com/Landparty/cobol-parser/commit/33b984e8b366d6767166fc707ef4b9ad32211a84))
* **interface-contract:** pin the mocky-mock generators surface ([bd30781](https://github.com/Landparty/cobol-parser/commit/bd30781fc8aa5a89f00a7037825af1e4a78b88c1))

## [1.3.0](https://github.com/Landparty/cobol-parser/compare/v1.2.0...v1.3.0) (2026-08-04)


### Features

* **generators:** generate synthetic CSV test data from a copybook ([e03c6ba](https://github.com/Landparty/cobol-parser/commit/e03c6ba839b4da8a4f386d78d49fedffe9d9e44c))
* **parser:** close PERFORM THRU gaps — numeric procedure names and range reachability ([ea57842](https://github.com/Landparty/cobol-parser/commit/ea57842602d225ee1187e3e848828051794c94cb))
* **parser:** structural expression trees for COMPUTE and condition parsing ([968c705](https://github.com/Landparty/cobol-parser/commit/968c705837725ee45bd94d7feb4fb59cbb41d9fa))
* **parser:** structured EXEC CICS/IMS parsing and tokenizer-based EXEC SQL ([b6b40b6](https://github.com/Landparty/cobol-parser/commit/b6b40b62f8595be67ecf53c5045ae11e9c9ab3ef))
* **preprocess:** evaluate &gt;&gt;IF conditions and implement &gt;&gt;EVALUATE ([c00fd7f](https://github.com/Landparty/cobol-parser/commit/c00fd7f7245fc94b67dd13ca77971340f67d6903))


### Bug Fixes

* address PR [#89](https://github.com/Landparty/cobol-parser/issues/89) review findings ([b3e81ed](https://github.com/Landparty/cobol-parser/commit/b3e81ede60c76d8d5dfec8e28c6954793670aa0e))
* **arithmetic:** consume ROUNDED after DIVIDE/MULTIPLY GIVING ([4db8394](https://github.com/Landparty/cobol-parser/commit/4db83941dccefbf3d185d02a518378c37c392d46))
* **arithmetic:** ROUNDED, REMAINDER, multi-target, CORRESPONDING ([82a82ec](https://github.com/Landparty/cobol-parser/commit/82a82ec8ea79e09f307781780785506eb1c513dd))
* **data:** PIC N sizing and USAGE IS keyword recognition ([64ff7b9](https://github.com/Landparty/cobol-parser/commit/64ff7b9f607e7cf1443b9a49bb5fa5a733778cca))
* **generators:** cleanup unused imports and formatting in copybook_data.py ([cf5eb08](https://github.com/Landparty/cobol-parser/commit/cf5eb08675acbf55556d8036c9af86649b2a3050))
* **generators:** keep both endpoints of a level-88 THRU range ([12e1ac4](https://github.com/Landparty/cobol-parser/commit/12e1ac439221b68b5c50f5f9d10ce0145434391d))
* **generators:** share one CSV line terminator across output paths ([2736ae4](https://github.com/Landparty/cobol-parser/commit/2736ae41d5907761fe694cb6036701591e9118b2))
* **io:** START KEY OR EQUAL TO, WRITE AT END-OF-PAGE, OPEN per-file mode ([316f0ce](https://github.com/Landparty/cobol-parser/commit/316f0ce39ca48fcf68863ea9d4a10116f274cba5))
* **lexer:** unify tokenize_cobol and CLI tokenize with the parse pipeline ([5de2306](https://github.com/Landparty/cobol-parser/commit/5de230693861cf68ca92437d7827e6c4655a623f))
* **move:** preserve subscript on MOVE targets ([2c45838](https://github.com/Landparty/cobol-parser/commit/2c45838d86220d39e8b397135ec27ca6936c55f7))
* **okf:** add missing generators/ entry to staleness-check OKF_MAP ([500026d](https://github.com/Landparty/cobol-parser/commit/500026da5be06376b5ac0a38dd15c53e542dba02))
* **parser:** comment-entry aware division boundaries; all 459 NIST programs parse error-free ([af08deb](https://github.com/Landparty/cobol-parser/commit/af08deb8c2debea84b7d24b5bebed389e93d01b0))
* **parser:** DISPLAY UPON/comma, computed GO TO comma, CANCEL comma ([ddbc688](https://github.com/Landparty/cobol-parser/commit/ddbc688fd42461b0060efb6ee92e2a0ecc3206c8))
* **parser:** ENTRY comma params, ACCEPT ENVIRONMENT name, STOP period ([50b6028](https://github.com/Landparty/cobol-parser/commit/50b6028e25e844efd9b65776745e0eed8d56ff50))
* **parser:** exclude clause-continuation keywords & SQL registers from paragraph-boundary detection ([3a3b304](https://github.com/Landparty/cobol-parser/commit/3a3b3040d7fb4efdd9f4f0eab545e10e5e4b467b))
* **parser:** EXEC CICS command loss and INSPECT BEFORE+AFTER ([824f654](https://github.com/Landparty/cobol-parser/commit/824f6547a2ec8cc5534da0dc17d26143d76911ba))
* **parser:** fix silent data loss in PICTURE and arithmetic clauses ([4917576](https://github.com/Landparty/cobol-parser/commit/4917576a2354878ddcd945924defb3ce8bf469d1))
* **parser:** handle PIC newline IS continuation ([d9f700e](https://github.com/Landparty/cobol-parser/commit/d9f700e27b3bb68b9e9af92ea48ffdfef9b1275b))
* **parser:** parse VALUE ALL &lt;literal&gt; instead of dropping the literal ([56e86b4](https://github.com/Landparty/cobol-parser/commit/56e86b4c628d65a1747d7c5f8971d38dfe85215c))
* **parser:** parse VALUE ALL &lt;literal&gt; instead of dropping the literal ([392f8ce](https://github.com/Landparty/cobol-parser/commit/392f8ce82b183243b4faba2b0b7a523526e6abf3))
* **parser:** preserve comma-separated lists in CALL/SET/UNSTRING ([5492c40](https://github.com/Landparty/cobol-parser/commit/5492c4001053f4ece9909f288486890b6c945116))
* **parser:** resolve comma-separated list truncation and semantic bugs ([5d5fd11](https://github.com/Landparty/cobol-parser/commit/5d5fd11dcdd347cfbc375050d70a3ac00b4d0afd))
* **parser:** restore period/SECTION lookahead in paragraph-boundary detection ([b130ec8](https://github.com/Landparty/cobol-parser/commit/b130ec8887acd8ebf33b4821c8aa3b13046b38c9))
* **parser:** stop EOF sentinel from manufacturing a phantom trailing paragraph ([4a8daa3](https://github.com/Landparty/cobol-parser/commit/4a8daa38cfa5000181ba3418f940af83878a67bc))
* **parser:** support REDEFINES clause split across multiple lines ([7c13bfd](https://github.com/Landparty/cobol-parser/commit/7c13bfd1fb6d1997927eade677b649f49cef7532))
* **parser:** VALUE/PICTURE clause operand may start on the next physical line ([d2bc7c2](https://github.com/Landparty/cobol-parser/commit/d2bc7c2093f71e13789da29f0a39b92d203f90c6))
* **parser:** VALUE/PICTURE clause operand may start on the next physical line ([662b347](https://github.com/Landparty/cobol-parser/commit/662b347461f814d3a18cacbaacb55abd1ec90174))
* **preprocess,parser:** copybook REPLACING sequence-area leak/truncation; PICTURE anonymous-item edge case ([3eaf120](https://github.com/Landparty/cobol-parser/commit/3eaf1207f95856327e57a55c01a3821185ca31a9))
* **preprocess:** correct missing-period regex and comment-only misreport in validate_copybook_content ([a68c69d](https://github.com/Landparty/cobol-parser/commit/a68c69dc0ace9960e401f89fe13f5f9a67324027))
* **preprocess:** correct missing-period regex and comment-only misreport in validate_copybook_content ([52a5f8a](https://github.com/Landparty/cobol-parser/commit/52a5f8a40e4724785c220d768fe08c54827f11f6))
* **preprocess:** make COPY REPLACING context-aware and support :...: delimiters ([2f4b2fb](https://github.com/Landparty/cobol-parser/commit/2f4b2fb52f9f8ec522fe2875301730b7ad86f253))
* **preprocess:** plausibility-scored encoding detection and strict decode mode ([6dcad8c](https://github.com/Landparty/cobol-parser/commit/6dcad8c298dfd5c88c3d401b349c39ff4dbf7ad1))
* **preprocess:** warn on mid-token truncation past column 72 ([76d1c12](https://github.com/Landparty/cobol-parser/commit/76d1c122150f811b9009f98e9bf3c7b0e5b8ee8b))
* **preprocess:** warn on mid-token truncation past column 72 ([49f880f](https://github.com/Landparty/cobol-parser/commit/49f880f7b651ec1ebf5782788af64c6928056a30))
* **review:** paragraph-swallow guard and INSPECT qualifier order ([68f68c0](https://github.com/Landparty/cobol-parser/commit/68f68c0b054411aefc7898492294bcdad818c889))


### Documentation

* fix final whole-branch-review gaps in generators/data/ split ([ec87e99](https://github.com/Landparty/cobol-parser/commit/ec87e997d83f4c8ee4f3263a19a55203cfbfa996))
* mark open findings M6/M10-M13/M15 fixed; update CHANGELOG and OKF ([6382cc8](https://github.com/Landparty/cobol-parser/commit/6382cc86545436ef319fd607759889837eca501b))
* **plans:** design plan for program-scoped test-data generation ([b953d61](https://github.com/Landparty/cobol-parser/commit/b953d615374307602eb6d879923f78fc9ea8affc))
* **plans:** design plan for program-scoped test-data generation ([79469fb](https://github.com/Landparty/cobol-parser/commit/79469fb3b28de434f7b4db42eeba21648774e2a0))
* **plans:** detailed implementation plans for Phases 1-9 ([c7eaa9b](https://github.com/Landparty/cobol-parser/commit/c7eaa9b110bc0481a7168e55b5a250602ac21786))
* **plans:** implementation plan for Phase 0 value-engine refactor ([8f8412d](https://github.com/Landparty/cobol-parser/commit/8f8412da0ee47305cc028adf75c7e8fef57af413))
* **plans:** resolve .cut ownership contradiction, define direction ([a9f90cb](https://github.com/Landparty/cobol-parser/commit/a9f90cbdb36ea19464228e3e31a144b8da02fc3f))
* reflect generators/data/ package split in OKF, CLAUDE.md, CHANGELOG ([701d485](https://github.com/Landparty/cobol-parser/commit/701d485ba9d62f7d9ad0c665aa5f917d84e67902))

## [1.2.0](https://github.com/Landparty/cobol-parser/compare/v1.1.0...v1.2.0) (2026-07-09)


### Features

* Add integration contract documentation for backend API ([cad4db6](https://github.com/Landparty/cobol-parser/commit/cad4db6b83e891496885b4dc6edc676dcab9c81c))
* **cli:** identify every CLI output with source_file and program_id ([94b1e98](https://github.com/Landparty/cobol-parser/commit/94b1e9844c5e3164a910200a4cca09674651bf3c))
* Create OKF knowledge bundle with lexer, parser, preprocessing, AST models, analysis, CLI, and tests documentation ([b2f8eeb](https://github.com/Landparty/cobol-parser/commit/b2f8eeb3b387bbaae3e1d1d186931c146e0c66e1))
* enhance copybook path resolution and numeric VALUE clause handling ([5111096](https://github.com/Landparty/cobol-parser/commit/511109675d9f48911f81c4c401a6e6ff9cb5aa4c))
* Initialize OKF v0.1 bundle with comprehensive documentation ([741a3f0](https://github.com/Landparty/cobol-parser/commit/741a3f0ceb335cd1ba5294d70b307cbf4e7c5bc2))
* **logging:** add detailed logging for parsing and error handling in COBOL parser ([6343f18](https://github.com/Landparty/cobol-parser/commit/6343f18fed1dc76097a2aa0db70557bacc688ae3))


### Bug Fixes

* address review — quote-parity tracking in copybook validator, CHANGELOG consistency ([b8267b1](https://github.com/Landparty/cobol-parser/commit/b8267b1b32b4f645735c6f666fcdb8f04b686040))
* address review feedback on H5 unterminated-literal recovery ([4c67876](https://github.com/Landparty/cobol-parser/commit/4c67876f50d58085b772047f2bfd66712717de28))
* **docs:** update test count and examples in CLAUDE.md ([150f2c3](https://github.com/Landparty/cobol-parser/commit/150f2c3497e9ee8b99ebd75055661a654d505051))
* honour COBOL AND/OR precedence in IF condition trees ([031b492](https://github.com/Landparty/cobol-parser/commit/031b492170d004427712c4d2c48d37c08d079a47))
* honour COBOL AND/OR precedence in IF condition trees (H4) ([5ebc346](https://github.com/Landparty/cobol-parser/commit/5ebc346a90fdc7b325b59c3ca2781e8e156066c6))
* join fixed-format numeric-literal continuation lines without a space ([f4dc2b3](https://github.com/Landparty/cobol-parser/commit/f4dc2b35e2eaf48546aab1d95c9afbd0e777c128))
* join fixed-format numeric-literal continuation lines without a space ([0bcf0cf](https://github.com/Landparty/cobol-parser/commit/0bcf0cf4fc00e3119017ebd7233d58d15cea16e5))
* **models:** match statement class names in find_all_by_type so CALL/SQL/IO statements are identifiable ([92e50c8](https://github.com/Landparty/cobol-parser/commit/92e50c80631855187801dbf5048bf20dc35b1f96))
* OPEN parser captures file names from every mode group ([f7b39b6](https://github.com/Landparty/cobol-parser/commit/f7b39b662da5b33017c2610590d14da7a0e2d23e))
* OPEN parser captures file names from every mode group ([b9f7595](https://github.com/Landparty/cobol-parser/commit/b9f7595fa704c4fa0d8cf7809f106493555bc87a))
* parse blank string-literal WHEN selectors (EVALUATE ... WHEN '  ') ([d8ad880](https://github.com/Landparty/cobol-parser/commit/d8ad880f4c7106d215ed65dd89f1ceadad3ea4a4))
* parse IO-statement clause bodies into the AST ([4a04b4e](https://github.com/Landparty/cobol-parser/commit/4a04b4ec8f83dc5330ae28b8f64452bfbca08eab))
* parse IO-statement clause bodies into the AST ([28f1de8](https://github.com/Landparty/cobol-parser/commit/28f1de8b7ab0a726228e079a44aa30580f65cd56))
* **parser:** resolve H9 issue where missing period absorbs following paragraph header ([7405700](https://github.com/Landparty/cobol-parser/commit/7405700748e54d23d03536d726298c11717639bd))
* prevent COMPUTE from swallowing following statements and improve expression boundary checks ([3e0493f](https://github.com/Landparty/cobol-parser/commit/3e0493f22862daa2c3e129ca2622059bf127a9cc))
* prevent MOVE/SUBTRACT/MULTIPLY/DIVIDE from swallowing following statements and improve size error clause handling ([c68a8ff](https://github.com/Landparty/cobol-parser/commit/c68a8ff9f45e2304d2dfb5aed49bed4437814622))
* recover from unterminated literal instead of aborting whole parse (H5) ([bf057e5](https://github.com/Landparty/cobol-parser/commit/bf057e526339ecd2085ff74bd05ccbac8c935754))
* register EVALUATE WHEN clauses as AST children ([f8f7877](https://github.com/Landparty/cobol-parser/commit/f8f787706dcbcf07d3f9fd9dd08ebb4f98d9768a))
* register EVALUATE WHEN clauses as AST children ([d37cec5](https://github.com/Landparty/cobol-parser/commit/d37cec57d47ce06dcdb06fee2c5b2f07ee0b33bc))
* report errors for malformed MOVE statements (audit H3) ([1b9886c](https://github.com/Landparty/cobol-parser/commit/1b9886c9fdfa3938498df9962120099a1359ac1a))
* report errors for malformed MOVE statements (audit H3) ([38ea9c6](https://github.com/Landparty/cobol-parser/commit/38ea9c6e538f123df3c9b8dfa22d3b78c152670b))
* resolve NIST corpus known issues — split headers, comment-entries, COMPUTE receivers, literal periods, COPY OF libraries ([6e2e33c](https://github.com/Landparty/cobol-parser/commit/6e2e33c478237fadd8933c9373de3be10ec360ba))
* reuse default clause on duplicate WHEN OTHER in EVALUATE ([2f597c2](https://github.com/Landparty/cobol-parser/commit/2f597c222a00c8bc344c154c1061bf40c403cf77))
* stop INSPECT/STRING/UNSTRING/EXEC-* from swallowing the next statement ([c6e030e](https://github.com/Landparty/cobol-parser/commit/c6e030e5bad4960b5cefed15b76dc1e2955d4368))
* stop INSPECT/STRING/UNSTRING/EXEC-* from swallowing the next statement ([066230a](https://github.com/Landparty/cobol-parser/commit/066230a9c1f2c3866a52bdd36ca464b189f777c8))
* strip layout tokens from IF condition before building the tree ([56e52c6](https://github.com/Landparty/cobol-parser/commit/56e52c6de8155083f231ecf71dc02388abf4aed8))
* type-safe source_id default in ProgramFlowAnalyzer.scan ([e676066](https://github.com/Landparty/cobol-parser/commit/e6760668dfdc51ee5b9a10c53f759ca1a3eae3da))
* unterminated literal no longer aborts whole parse, defeating COLLECT_ALL (H5) ([b87a654](https://github.com/Landparty/cobol-parser/commit/b87a6547bccac8ca450c23dab090b99b5f884320))
* Update timestamps in cli.md, integration.md, and lexer.md to reflect accurate commit dates ([177ac45](https://github.com/Landparty/cobol-parser/commit/177ac4511fe086f7996af0bf0a266f56f8424fca))


### Documentation

* add cobolparser gap-analysis audit report ([abbb3d1](https://github.com/Landparty/cobol-parser/commit/abbb3d18ecdf45801a2108133761e54f1f1602c4))
* add OKF docs, drift-prevention hooks, and homogenize README ([d178448](https://github.com/Landparty/cobol-parser/commit/d178448388246e60faf50d8467715a5ff85ca3c1))
* cobolparser gap-analysis audit ([2d88c83](https://github.com/Landparty/cobol-parser/commit/2d88c83d9f5cc1c08f1f33dff94a9a943101e1e6))
* **okf:** add analysis subsystem file ([3275545](https://github.com/Landparty/cobol-parser/commit/32755451ce7ce9e035781a5e1874dc6f05ccef62))
* **okf:** add ast-models subsystem file ([9222125](https://github.com/Landparty/cobol-parser/commit/922212538f8f5b3f638f1f454b8b0bd236acbde3))
* **okf:** add batch and profiling subsystem file ([7e23d7e](https://github.com/Landparty/cobol-parser/commit/7e23d7e80968255783c3e2eebbd9672a3c3c9807))
* **okf:** add CLI subsystem file ([c518d12](https://github.com/Landparty/cobol-parser/commit/c518d122a56a5aa078b2996bb2ba827622587dd8))
* **okf:** add conventions subsystem file ([f7c0921](https://github.com/Landparty/cobol-parser/commit/f7c0921b14f5681e14fb0f6b1ebe6c97f41fe845))
* **okf:** add dialects and configuration subsystem file ([6d3bec2](https://github.com/Landparty/cobol-parser/commit/6d3bec22605100c51b19f726bfd8307dc19daa1b))
* **okf:** add lexer subsystem file ([20482f7](https://github.com/Landparty/cobol-parser/commit/20482f796c1d6a91705c5ac8ee460d7262e56d5c))
* **okf:** add OKF design spec ([dab92e8](https://github.com/Landparty/cobol-parser/commit/dab92e8e721be6f7dea96a1b127193469e3bde97))
* **okf:** add OKF implementation plan ([6d7599d](https://github.com/Landparty/cobol-parser/commit/6d7599ddaef3e56a95583842a01b9f9e31169883))
* **okf:** add OKF master index ([a9d364f](https://github.com/Landparty/cobol-parser/commit/a9d364f0329a84e4387b51a082459668697a2cf3))
* **okf:** add parser subsystem file ([fcacac2](https://github.com/Landparty/cobol-parser/commit/fcacac2e44b810d9e20685d396770e5294f65d9c))
* **okf:** add preprocessing subsystem file ([c5bb598](https://github.com/Landparty/cobol-parser/commit/c5bb598dbf89dfba9d9a20a2fdc41baf7cdf2263))
* **okf:** add tests subsystem file ([531b112](https://github.com/Landparty/cobol-parser/commit/531b1123717c7d480310a37f842f2a3718cdb2c2))
* **okf:** apply final review fixes — export bucket, counts, dual LexerError, minor ([9eba638](https://github.com/Landparty/cobol-parser/commit/9eba6389f50f968b1ad0bdf09e0e829464b6d9e3))
* **okf:** fix analysis.md — correct FlowEdgeType enum and HostVariableResolver API ([e95fdb3](https://github.com/Landparty/cobol-parser/commit/e95fdb3a38185e4fafd8b7e66dfc0ef5611f6975))
* **okf:** fix Files section, Ruff ignores, dev deps in conventions.md ([8a9d1c7](https://github.com/Landparty/cobol-parser/commit/8a9d1c752c963291dd68d4674e1281c4cdc446d1))
* **okf:** fix minor field-name inaccuracies in lexer.md ([e7277ed](https://github.com/Landparty/cobol-parser/commit/e7277ed81f3d600d85b000c46dfac8f2f54c8a98))
* **okf:** fix ParseStatistics fields in dialects.md ([815d1e4](https://github.com/Landparty/cobol-parser/commit/815d1e4a627dc432d04f16d21e35b6c63d7232e2))
* **okf:** remove outdated OKF design spec — no longer needed ([b091747](https://github.com/Landparty/cobol-parser/commit/b09174736c1af244cccaeb6c3fd0b36807d6224b))

### Added

* **OCCURS `ASCENDING/DESCENDING KEY` and multi-index `INDEXED BY` capture**
  (audit 2026-07-09). `OccursClause` gained `key_clauses` (a list of
  `{"direction", "keys"}`, serialized when present) and `index_names` (all
  `INDEXED BY` names; `indexed_by` still holds the first for backward
  compatibility). Previously the `ASCENDING/DESCENDING KEY` clause was dropped
  entirely — and, because it sits before `INDEXED BY` in standard COBOL, its
  presence also caused the following `INDEXED BY` to be silently consumed and
  lost. `INDEXED BY a b` also kept only the last index. Mirrored in the Cython
  `_data_fast` fast-path.

* **`REWRITE ... FROM`, `START ... KEY IS <data-name>`, `STOP RUN RETURNING
  <x>` operands, and the `ACCEPT ... FROM DATE/TIME <format>` phrase are now
  captured** (audit 2026-07-09). New fields: `IORewriteStatement.from_clause`,
  `IOStartStatement.key_name`, `StopStatement.returning`; the ACCEPT format
  phrase folds into `from_source`. All were previously consumed and discarded
  with `errors=[]`/`warnings=[]`; the ACCEPT format word was additionally
  re-parsed as a phantom paragraph.

* **DATA division drop warnings** (audit 2026-07-09). Unrecognized data-item
  clause tokens (GROUP-USAGE, VOLATILE, DYNAMIC LENGTH, ...) now emit an
  "Unparsed token ... in data item" warning instead of being consumed
  silently — symmetric with the ENVIRONMENT division's SELECT handling.

* **`PERFORM VARYING ... AFTER ...` multi-dimension support** (audit
  2026-07-07 H2). The `AFTER var FROM x BY y [UNTIL cond]` dimensions of a
  2-D/3-D table loop are parsed into `PerformStatement.after_clauses`
  (serialized as `after_clauses` when present). Previously the whole AFTER
  phrase was absorbed into the first UNTIL condition string (with token-type
  names leaking into it) and the second dimension was lost.

* **SELECT clause capture: `ALTERNATE RECORD KEY` (with `WITH DUPLICATES`),
  `PADDING CHARACTER`, `RESERVE n AREAS`, `SHARING WITH`, `LOCK MODE`
  (with `LOCK ON` / `WITH ROLLBACK`), `PASSWORD`, `RECORD DELIMITER`, and
  the second (VSAM) `FILE STATUS` variable** (audit 2026-07-07 H5). The
  `SelectStatement` model already had the fields; the parser now populates
  them. `assign_device_type` is populated for recognizable device words
  (`DISK`, `PRINTER`, ...) and IBM `UT-S-`/`UR-`/`DA-` prefixed assignment
  names. Unknown SELECT clause tokens now produce an "Unparsed token ... in
  SELECT" warning instead of being silently consumed.

* **Conditional-compilation diagnostics** (audit 2026-07-07 H7).
  `preprocess_conditional_compilation()` accepts a `warnings` list and
  reports: unsupported `>>IF` conditions (which delete the guarded block),
  malformed `>>DEFINE`, stray `>>ELSE`/`>>END-IF`, unknown `>>` directives
  passed through, and unclosed `>>IF` at end of input. The copybook
  expansion path routes these into `ExpansionStatistics.warnings` (and from
  there into `ParseResult.warnings` via `parse_cobol_with_expansion`); the
  CLI prints them to stderr. Previously all of these were completely silent.

* **Dropped-COPY diagnostics** (audit 2026-07-07 H6a/H6c). A `COPY` whose
  clause scan never reaches a terminating period (e.g. `COPY FOO` with no
  `.`, or `COPY FOO BAR.`) is never expanded — this now produces a "COPY
  ... was NOT expanded" warning on `ExpansionStatistics.warnings` instead
  of the copybook's content silently not existing. An unterminated
  `==pseudo-text==` REPLACING operand likewise warns instead of silently
  abandoning the clause. `extract_copy_statements()` accepts an optional
  `warnings` list. The COPY scanner also gained a left-side word-boundary
  check so `GOODCOPY.` is no longer probed as a COPY statement.

### Changed

* **`ON SIZE ERROR` / `NOT ON SIZE ERROR` bodies now parse every verb**
  (audit 2026-07-07 H1). The handler-body parser dispatches through the
  statement registry (same mechanism as IF/EVALUATE/IO clause bodies), so
  `ON SIZE ERROR PERFORM ERR-PARA` (or CALL, IF, ADD, ...) is captured,
  serialized, and visible to `find_all_by_type`. Previously only DISPLAY
  and MOVE were mini-parsed and every other verb was skipped token-by-token
  — the handler vanished with `errors=0`. Affects
  ADD/SUBTRACT/MULTIPLY/DIVIDE/COMPUTE.

* **`DECIMAL-POINT IS COMMA` now warns** (audit 2026-07-07 H4). The clause
  is recorded in division metadata but the lexer does not honor it (comma
  decimal literals misparse), so parsing a program that declares it now
  produces an explicit `ParseResult.warnings` entry instead of silent
  misparsing. (Actually honoring the clause remains open.)

* **`CobolExpression.to_dict()` now includes `operands`** — condition/
  expression text (e.g. PERFORM UNTIL conditions) previously vanished at
  the JSON boundary.

* **`MemoryConfiguration` documents its no-op fields** (audit 2026-07-07
  M5): `max_memory_mb`, `enable_streaming` and `chunk_size_kb` are
  validated but not enforced; `max_error_count` is enforced.
  `interface-contract.md` now states the real `success`/`ast` semantics
  (audit 2026-07-07 M8): `ast` can be non-None while `success` is False.

* **`cobol-parser coverage status` handles malformed artifacts** (audit
  2026-07-07 M10): invalid JSON or a non-object artifact reports a clean
  error and exit code 1 instead of an uncaught traceback.

### Added (2026-07-07 C1-C8 remediation)

* **Multi-program compilation units are now parsed** (audit 2026-07-07 C1).
  Stacked or nested programs delimited by `END PROGRAM` are each parsed into
  their own `CobolProgram`; the first is `ParseResult.ast` and the rest are
  attached to `ast.contained_programs` (serialized as `contained_programs`,
  included in `get_all_statements()`), with a summary warning. Previously
  everything after the first program was silently dropped with `errors=0`
  (NIST `IC228A` retained ~3% of its statements).

* **XML/JSON GENERATE/PARSE statement support** (audit 2026-07-07 C3). New
  `XmlJsonStatementParser` + `XmlJsonStatement` AST node capture verb,
  action, primary operands, and raw trailing-clause text. Previously the
  `XML`/`JSON` keyword was silently skipped and the remainder mis-parsed as
  a Report Writer `GENERATE`.

* **Unsupported-statement and unparsed-token warnings** (audit 2026-07-07
  C2). When no statement parser matches, the skip is now recorded on
  `ParseResult.warnings` with the token and line instead of only
  `logger.debug`: known unsupported verbs (`INVOKE`, `EXHIBIT`, `SEND`,
  `ENABLE`, ...) get an "Unsupported statement" warning; leftover clause
  tokens from partially-supported statements get an "Unparsed tokens"
  warning. `ALLOCATE`, `FREE`, `EXHIBIT`, `INVOKE`, `XML`, and `JSON` were
  added to `STATEMENT_KEYWORDS` so they are treated as statement starts
  rather than becoming phantom paragraph names. Note: programs that
  previously parsed with `warnings == []` may now carry warnings — that is
  the fix working, not a regression; each warning marks content that was
  already being dropped silently.

### Fixed

* **Eight HIGH-severity findings from `reports/open-findings.md` (2026-07-08
  re-verification pass), all pinned by
  `tests/regression/test_open_findings_high_regressions.py`:**
  - **H1** — `SET ADDRESS OF x TO y` produced an empty `SetStatement`
    (`targets: []`, `set_type: null`, `value: null`) because the
    target-collection loop only accepted `IDENTIFIER`/`STRING_LITERAL`
    tokens; `OF` lexes as its own dedicated `TokenType.OF`, not
    `IDENTIFIER`, so the loop broke immediately on it. `OF` is now
    recognized and skipped so the pointer/`TO`/target tokens are reached.
  - **H2** — `COMPUTE` with unbalanced parentheses was silently accepted,
    and once `paren_depth` was left non-zero by a stray `(` the
    statement-boundary check (gated on `paren_depth == 0`) never re-armed,
    silently folding a well-formed following statement into the
    expression string. A boundary check now fires regardless of
    `paren_depth`, and a final `paren_depth != 0` check now reports
    "COMPUTE statement has unbalanced parentheses in expression" instead
    of accepting silently.
  - **H3** — `PERFORM para-name JUNK-TOKEN.` speculatively consumed a
    trailing `IDENTIFIER` as a candidate TIMES value and discarded it with
    **no warning at all** when `TIMES`/`TIME` didn't follow
    (`errors=[], warnings=[]`, `times_count: null`). The TIMES-clause
    lookahead now peeks past the candidate token before committing to
    consuming it, and emits a warning identifying the discarded token when
    it isn't a valid TIMES clause.
  - **H4** — `perform_parser.py` had 5 bare `except ParseError: pass`
    sites (VARYING/UNTIL/inline-body parsing) with no logging at all, not
    even DEBUG — a nested-parse failure could vanish completely
    untraceable. All 5 sites now log the suppressed exception at DEBUG.
  - **H5** — `MoveTypeChecker` silently skipped every MOVE whose source or
    target category couldn't be resolved (`UNKNOWN`/`FIGURATIVE`), with no
    counter anywhere on `MoveTypeReport` — 3 MOVEs on undeclared
    identifiers (e.g. an unexpanded copybook) produced
    `violations: [], error_count: 0, warning_count: 0`, a false all-clear.
    `MoveTypeReport` gained an `unresolved_count` field (serialized in
    `to_dict()`) that counts every operand the checker couldn't resolve.
  - **H6** — the Tier-2 (directory-index) copybook resolver fast path in
    `PathResolver.resolve()` returned an indexed path after only an
    `os.path.getsize()` check, never calling `validate_path_within_directory()`
    (which the Tier-3 path does call). Since the index is built via
    `os.scandir()` + `entry.is_file()` (which follows symlinks), a symlink
    inside a search directory pointing outside it would be served with no
    containment check. Both Tier-2 fast-path hits (exact and
    extension-suffixed) now validate containment before returning.
    Separately, the `".." in file_path` guard was naive substring
    matching, false-flagging filenames like `weird..name.cpy`; it's now a
    path-segment check (`.. ` as a whole segment only).
  - **H7** — an unterminated string literal in the default parse path was
    fully silent: the lexer's error was gated on `if not self.free_form`,
    and `parse_cobol()` always lexes with `free_form=True` after
    normalization, so `DISPLAY "UNCLOSED` followed by a well-formed
    statement parsed clean with the literal silently closed at the line
    boundary. The lexer (both the pure-Python path and the `_lexer_fast`
    Cython path) now records a warning — surfaced via
    `ParseResult.warnings` — instead of staying silent, without promoting
    it to a hard error (a lone quote can legitimately appear in a
    free-form comment). Separately investigated the report's "unclosed
    `IF`s with no bodies" sub-claim: confirmed this is legal, correctly
    scope-nested COBOL (period-terminated or nesting-closed IFs need no
    `END-IF`), not a bug — no change made for that sub-case.
  - **H8** — `CLOSE` used an if/elif chain across `REEL`/`UNIT`/`WITH`
    (one branch per file, applied only once), and the outer per-file loop
    required the next token to be a plain `IDENTIFIER` to continue, so
    `CLOSE F REEL WITH NO REWIND.` kept only `reel: true` and dropped
    `no_rewind` (only warn-masked via the generic "unparsed tokens"
    fallback). The per-file option parse is now a loop that keeps applying
    options until none match, so combined options on one file (and across
    multiple files in one CLOSE) all survive.

  Also fixed while verifying H2: `tests/samples/arithmetic_operations.cbl`
  had a `FUNCTION MAX(WS-NUM-1, WS-NUM-2, WS-NUM-3)` line that overflowed
  fixed-format column 72 (the closing `)` landed in column 73 and was
  silently truncated by `normalize_fixed_format`) — previously masked by
  the very H2 bug (the truncated, unbalanced expression silently absorbed
  the next statement); now correctly surfaced by the H2 fix and corrected
  in the sample by removing the space after each comma.

  Noted but intentionally not fixed in that pass (out of scope of the 8
  listed findings, and higher blast-radius core-parser surgery): a
  statement with no terminating period, immediately followed by what
  should be a new paragraph header, caused the paragraph-name identifier
  to be absorbed as a trailing operand of the preceding statement instead
  of starting a new paragraph. Flagged as H9 and fixed in a follow-up
  pass — see below.

* **H9 — a statement missing its terminating period could absorb the
  following paragraph/section header as a trailing operand** (follow-up to
  the H1-H8 pass above; pinned by
  `tests/regression/test_open_findings_high_regressions.py::TestH9MissingPeriodParagraphBoundary`).
  Operand-collection loops with no boundary awareness (`DISPLAY`'s item
  list, `MOVE`'s target list, `COMPUTE`'s expression capture, `STRING`'s
  operand list) had no way to tell a legitimate trailing operand from a
  following paragraph name once the statement's own period was missing —
  both are just "`IDENTIFIER` then `PERIOD`" to the grammar, and
  `is_statement_boundary()` only catches *known* verbs lexed as plain
  identifiers, not ordinary user-defined paragraph names. Fixed via a new
  `looks_like_paragraph_boundary()` helper (`parsers/statements/_utils.py`)
  that mirrors COBOL's own disambiguator instead of guessing from grammar
  shape alone: the candidate identifier only counts as a paragraph boundary
  when it starts its own source line, is immediately followed by a period
  or `SECTION`, and is not a name declared in the DATA DIVISION (excluded
  so a genuinely wrapped continuation-line operand, e.g. `DISPLAY\n
  WS-X.`, is not misread just because it opens its line). The DATA DIVISION
  cross-check is threaded through `ParseContext.known_data_names`, computed
  once per PROCEDURE DIVISION parse. Recovery now warns instead of silently
  re-interpreting, per the H7/H8 precedent. Applied to the six statement
  parsers confirmed (by direct repro) to swallow the following paragraph:
  `DISPLAY`, `MOVE`, `COMPUTE`, `STRING`, `UNSTRING` (its `INTO` target
  list), and `INSPECT` (both its `TALLYING` counter-name loop and its
  outer "consume to period" trailer, which is what actually swallowed the
  paragraph name for `INSPECT ... REPLACING`, since the `REPLACING`
  clause loop itself already stopped safely). Not probed / not fixed:
  other statement parsers with a similarly open-ended list/text-collection
  loop may share this gap; only the six demonstrated cases were fixed here,
  per the report's own "needs its own scoped investigation" framing for
  this finding.

* **H10 — out-of-line `PERFORM procedure-name VARYING ...` was not parsed at
  all, and left `perform_type` mistagged `"SIMPLE"`** (found 2026-07-09,
  follow-up to the H1-H9 pass; pinned by `TestPerformVaryingOutOfLine` in
  `tests/regression/test_perform_backward_compat.py`, plus a strengthened
  assertion in `test_perform_variable_times_count_not_breaking` in the same
  file, `TestPerformVaryingMissingUntil` in
  `tests/unit/test_perform_edge_cases.py`, and
  `test_out_of_line_perform_varying_is_loop` in
  `tests/unit/analysis/test_program_flow.py` — the actual downstream payoff:
  `ProgramFlowAnalyzer`'s loop-edge classification now correctly flips to
  `is_loop=True` for this shape). `perform_parser.py`'s
  out-of-line branch (target paragraph already consumed) checked for
  `TIMES`, `WITH TEST`, and `UNTIL` after the paragraph name, but never for
  `VARYING` — so `PERFORM MY-LOOP VARYING I FROM 1 BY 1 UNTIL I > 10.` left
  the entire `VARYING ... UNTIL ...` clause unconsumed for the generic
  "unparsed tokens" recovery path to discard, and `PerformStatement.
  perform_type` stayed the default `"SIMPLE"` — indistinguishable from a
  genuine plain `PERFORM MY-LOOP.` to any caller that branches on
  `perform_type` (e.g. `ProgramFlowAnalyzer`'s loop-edge classification).
  The only thing that made this non-silent before the fix was the
  generic dropped-clause warning tripping unrelated downstream recovery —
  an accidental side effect, not a real safety net: had the out-of-line
  VARYING shape ever been parsed (even partially) without also fixing the
  tagging, the mistag would have become fully silent again.

  Fixed by extracting the inline VARYING clause's `id FROM x BY y [WITH
  TEST ...] UNTIL cond [AFTER ...]` parsing into a shared
  `_parse_varying_header()`, now called from both the inline dispatch
  (`PERFORM VARYING ...`, no target paragraph) and a new out-of-line
  dispatch (`PERFORM procedure-name [THRU ...] VARYING ...`) hooked in
  right where the paragraph-name branch already checks for `UNTIL`. Root
  cause of the mistagging itself: `perform_type` only became `"VARYING"`
  as a side effect of `set_varying_clause()`, which requires a fully
  parsed `until_condition` — so even a malformed clause (missing
  `FROM`/`BY`/`UNTIL`) silently reported `"SIMPLE"`. `PerformStatement`
  gained `mark_varying()`, called the instant the `VARYING` keyword is
  consumed, before any sub-clause is attempted, so the tag reflects the
  keyword's unambiguous presence rather than a successful sub-parse. This
  also fixes the identical latent bug on the *inline* form: `PERFORM
  VARYING I FROM 1 BY 1 DISPLAY I END-PERFORM` (no `UNTIL`) previously
  mistagged `"SIMPLE"` with `errors=[], warnings=[]` — fully silent, no
  accidental recovery-path warning to mask it. A malformed VARYING clause
  (keyword present, `FROM`/`BY`/`UNTIL` not fully parsed) now also emits an
  explicit warning via the new `_warn_incomplete_varying_clause()` instead
  of leaving `varying_clause: null` indistinguishable from "no VARYING
  clause was ever present."

* **ENVIRONMENT/DATA division sections reported the wrong source line**
  (found 2026-07-09, user-reported while testing the parser; pinned by new
  `tests/regression/test_section_location_tracking.py`).
  `BaseDivisionParser.parse()` captures one `start_location` from the
  division keyword token and threads it through to `_create_ast_node()`;
  `environment.py`'s and `data.py`'s `_create_ast_node` implementations both
  reused that single location for **every** `CobolSection` (and, in
  ENVIRONMENT's case, the `FILE-CONTROL` `CobolParagraph`) they built,
  instead of each section's own header token location. Concretely, an
  `ENVIRONMENT DIVISION` on line 3 with `INPUT-OUTPUT SECTION` on line 6
  reported `line: 3` for both nodes. `procedure.py` already tracked each
  section's own location correctly (`section_info.get("location",
  start_location)`) — only these two division parsers had the bug. Fixed by
  having `_parse_configuration_section`, `_parse_input_output_section`,
  `_parse_file_control_paragraph` (environment.py), and `_parse_section`
  (data.py) each capture their own leading keyword token's location and
  return it in their result dict; `_create_ast_node` in both files now reads
  the per-section location instead of hard-coding `start_location`.
  Statement/data-item-level locations were already accurate; this fix is
  scoped to the `Division`/`Section`/`Paragraph` container nodes.

* **Ten MEDIUM-severity findings from `reports/open-findings.md` (2026-07-09
  batch), all pinned by
  `tests/regression/test_open_findings_medium_regressions.py`:**
  - **M1** — `DISPLAY SPACE`/`DISPLAY SPACES` (and other figurative
    constants) produced an empty `display_items` list and an "Unparsed
    tokens" warning: the display-item loop accepted `STRING_LITERAL`/
    `IDENTIFIER`/`NUMERIC_LITERAL` but not `TokenType.FIGURATIVE_CONSTANT`.
    Per the mockymock corpus sweep this was the single most common
    trigger (56 hits across 24 shamrice programs). Now accepted.
  - **M2** — `DISPLAY ... WITH NO ADVANCING` was silently dropped: `WITH`/
    `NO`/`ADVANCING` lex as dedicated `TokenType`s, so the item loop's
    final "unknown token → stop" branch ended the statement without
    consuming the clause. `DisplayStatement` gained a `with_no_advancing`
    flag, now set by a new WITH/NO/ADVANCING branch in the parse loop.
  - **M3** — `DISPLAY`/`ACCEPT` `AT` positioning and ACCEPT's extended
    clauses (`SECURE`, `NO-ECHO`, `TIMEOUT`, `AUTO-SKIP`, `UPPER`) were
    dropped entirely. A corpus grep of `examples/cobol/shamrice/*.cbl`
    (the corpus the audit's hit counts came from) found 34 real `AT`
    clauses, 100% using the bare combined-numeric form (`AT 0330` → line
    3, column 30, decoded via `divmod(value, 100)`) with zero uses of the
    `AT LINE n COLUMN m` keyword form — both are now supported on
    `DISPLAY`; `ACCEPT` supports the corpus-confirmed numeric form.
    `SECURE` and `NO-ECHO` are modeled as distinct flags (per
    `accept-secure.cbl`'s own comment, `SECURE` masks input with `*` per
    character where `NO-ECHO` shows nothing — collapsing them would have
    lost that distinction). `IOAcceptStatement` gained `secure`,
    `timeout_value`, `auto_skip`, and `upper` fields alongside the
    already-scaffolded `at_line`/`at_column`/`with_no_echo`, which were
    previously never wired up by the parser. `CURSOR`, `BEEP`/`BELL`,
    `COLOR` (`FOREGROUND-COLOR`/`BACKGROUND-COLOR`), `UPDATE`, and `WITH
    BLANK SCREEN` remain unimplemented — zero-to-one corpus hits, and for
    `COLOR` especially the real grammar is a two-part clause the finding
    text didn't specify with enough confidence to implement correctly.
  - **M4** — `D`/`d` in column 7 fell through `normalize_fixed_format` as
    live code, disagreeing with `copy_statement_parser.is_comment_line()`
    (which already treats `D`/`d` as a comment) — two pipelines, two
    answers, neither configurable. `normalize_fixed_format` (pure-Python
    and the `_preprocess_fast` Cython path) gained a
    `debug_lines_as_comments` keyword (default `True`, matching
    `is_comment_line()`) so both pipelines now agree by default, with an
    explicit opt-out for callers that need debug lines compiled as code.
  - **M5** — a continued alphanumeric literal lost trailing blanks that
    are part of its value: `rstrip()` was applied to a line's text before
    it was known whether the literal remained open (continuing to the
    next line, where fixed-format continuation rules make those trailing
    blanks significant) or closed (where they're just padding).
    `normalize_fixed_format` now determines quote state first and only
    strips trailing blanks once a literal is confirmed closed, in both
    the opening-line and literal-continuation branches, pure-Python and
    Cython.
  - **M7** — typed `X'..'`/`NX'..'` literals had no hex-validity or
    even-length check; `X'ABC'` (odd length) and `X'ZZ'` (invalid hex
    digits) were accepted with no diagnostic. The lexer now emits a
    warning for both cases (via `self.warnings`, surfaced through
    `ParseResult.warnings`). `G'..'`/`N'..'` literals are untouched —
    they have codepage-dependent validity rules out of scope here.
  - **M8** — no tab-expansion logic existed in `normalize_fixed_format`;
    a leading tab shifted every subsequent column, since fixed-format
    parsing is column-index based. Lines are now tab-expanded (8-column
    stops, `str.expandtabs(8)`) before any column-sensitive slicing, in
    both the pure-Python and Cython paths.
  - **M9** — `try_parse_nested_statement`'s bare `except Exception` logged
    at DEBUG only; an exception that bypassed `report_or_raise` (e.g.
    `TokenMismatch`/`UnexpectedEndOfInput` raised directly by
    `token_stream.expect()`) vanished completely — no entry in
    `ParseResult.errors` or `.warnings`. Now recorded as a warning unless
    the exception is already tagged `_already_recorded = True` by
    `report_or_raise` (avoiding double-reporting).
  - **M14** — copybook cache hits (diamond dependency: the same member
    `COPY`d multiple times within one expansion) bypassed
    `context.total_bytes` accounting entirely — only a cache *miss*
    incremented it, so `max_total_size` was never enforced against the
    true expanded content size. Cache hits now add their content's byte
    length to `total_bytes` and re-check the limit, same as a miss does.
  - **M16** — `PIC 99/99/99` (and any other slash- or asterisk-edited
    picture, e.g. `PIC $***,**9.99`) corrupted DATA DIVISION structure:
    `_PICTURE_SYMBOL_TOKEN_TYPES` used `TokenType.DIVIDE`/`MULTIPLY` (the
    DIVIDE/MULTIPLY *statement* keyword tokens) instead of
    `TokenType.DIVIDE_OP`/`MULTIPLY_OP` (what `/` and `*` actually lex
    to), so picture pattern collection stopped at the first edit symbol
    and the remainder was misparsed as phantom level-99 data items. Now
    uses the correct operator token types.

  Explicitly out of scope for this batch (each close to its own
  subsystem, deferred to separate plans): M6 (`parse_cobol()` vs.
  `tokenize_cobol()`/CLI `tokenize` running different fixed-format
  logic), M10 (conditional compilation beyond `symbol IS [NOT] DEFINED`,
  and `>>EVALUATE`), M11 (EXEC CICS/IMS raw-text stubs), M12 (arithmetic/
  loop expressions as raw strings, not trees), M13 (context-blind
  REPLACING substitution), M15 (EBCDIC autodetection heuristic and lossy
  decode fallback). M17 (branch-coverage debt) is test-coverage debt, not
  a bug, and was not attempted.

* **A period-less statement could silently swallow an unsupported (or even a
  fully-supported) following verb** (residual of audit 2026-07-07 C2). C2
  taught the top-level PROCEDURE DIVISION dispatch loop to warn when it
  directly encounters a verb with no registered parser — but that loop only
  sees the verb directly when a period separates it from the previous
  statement. Without a period, the previous statement's own trailing-token
  loop (MOVE's target list, the arithmetic operand collector, ...) decides
  for itself whether to stop, via `STATEMENT_TOKEN_TYPES`/
  `STATEMENT_KEYWORDS` (`_utils.py`). Those sets were missing several verbs
  `_UNSUPPORTED_VERBS` already labeled (`DISABLE`, `ENABLE`, `PURGE`,
  `RAISE`, `READY`, `RECEIVE`, `RESET`, `RESUME`, `SEND`, `SERVICE`,
  `TRANSFORM`), missing the `TokenType` (though not the string) for
  `EXECUTE`/`EXHIBIT`/`INVOKE`, and were completely missing two verbs with
  **registered parsers** (`COMMIT`, `ROLLBACK` — the worse case: a fully
  supported statement vanished) plus several more real, previously
  unlabeled verbs (`CHAIN`, `ENTER`, `EXAMINE`, `GOTO` fused spelling,
  `INITIATE`, `NOTE`, `RECOVER`, `SUPPRESS`, `TERMINATE`). All are now in
  `STATEMENT_TOKEN_TYPES`/`STATEMENT_KEYWORDS`, and the newly-recognized
  unsupported verbs were added to `_UNSUPPORTED_VERBS` for a specific
  warning message. Separately, `PURGE`/`RAISE`/`RESUME` have no dedicated
  lexer `TokenType` at all (they lex as plain `IDENTIFIER`), so the
  `STATEMENT_KEYWORDS` fix alone didn't reach ten *other* list-collecting
  loops that never consulted `STATEMENT_KEYWORDS`/`is_statement_boundary`
  at all: `DISPLAY`'s item list, `CANCEL`'s program-name list, `SET`'s
  target list, `OPEN`/`CLOSE`'s file-name lists, `INITIALIZE`'s target
  list, `UNSTRING`'s `INTO` target list, `SORT`/`MERGE`'s shared
  `_parse_keys`/`_parse_file_list` helpers, and `INSPECT`'s
  `_parse_tallying` counter-name loop (separate nested loops with their own
  hand-rolled boundary keyword list — or, for `_parse_tallying`, no
  boundary check at all — bypassing the `is_statement_boundary()` check
  their statement's outer loop already had). Each of those ten loops now
  also breaks on `is_statement_boundary()` before accepting a bare
  `IDENTIFIER` as a list item. A related, more severe pre-existing bug in
  `PerformStatementParser._parse_until_condition_only` (the out-of-line
  `PERFORM paragraph-name UNTIL condition` form) had **no boundary check at
  all** — a period-less `PERFORM ... UNTIL cond` swallowed every remaining
  token in the program into the condition string, including entire
  well-formed statements, not just unsupported verbs; it now stops at the
  same `STATEMENT_TOKEN_TYPES`/`STATEMENT_KEYWORDS` boundary the sibling
  `_collect_until_condition_tokens` helper already used. A fourth finding,
  in `EvaluateStatementParser`: `_parse_subjects` (the subject list before
  the first `WHEN`) had no boundary check, same shape as the ten
  list-collecting loops above. Worse, the outer clause-scan loop treated
  any non-`WHEN`/`END-EVALUATE` token as noise to skip past, so a malformed
  (missing-`WHEN`) `EVALUATE` could consume forward past an entire
  intervening statement — verified with a trailing `MOVE` immediately
  followed by a second, well-formed `EVALUATE`: the first EVALUATE annexed
  the *second* EVALUATE's `WHEN` clause as its own, silently erasing the
  MOVE and merging two EVALUATEs into one, with zero errors and zero
  warnings. Both loops now stop at the same boundary check. `IfStatement
  Parser`'s condition collector was probed and confirmed already safe.
  Pinned by `tests/regression/test_tier7_unsupported_verb_boundary.py`.

* **`ProgramFlowAnalyzer` missed control-flow edges nested in clause bodies**
  (audit 2026-07-09). PERFORM/GO TO/CALL statements inside a `READ ... AT END`,
  `WRITE ... INVALID KEY`, `... ON SIZE ERROR`, or `STRING ... ON OVERFLOW`
  clause produced no edge, cascading into false `unreachable_nodes` reports and
  missing arrows in generated flowcharts. `scan()` now recurses into those
  clause bodies (matching `coverage_analyzer`). `ACCEPT`/`UNLOCK` with a
  missing operand no longer swallow the following statement's verb.

* **`EVALUATE ... WHEN '  '` (blank string-literal selector) parses again.**
  The lexer strips quotes off string literals, so a blank literal's token
  value is whitespace-only; the WHEN selector builder filtered it out as an
  empty artifact and reported "WHEN clause must have at least one selector"
  on valid programs. Blank literals are now re-quoted (`selector value
  "'  '"`) so they survive; non-blank literals are unchanged. This is the
  standard IMS DL/I status-code idiom and blocked 5/17 programs in the
  legacy-application corpus. Pinned by
  `tests/regression/test_evaluate_space_literal_when.py`.

* **Three real-world parse-content-drop bugs found by mockymock's refreshed
  corpus sweep against `legacy-application`** (all 26 corpus programs now
  parse and generate clean, zero refusals — up from 3 `PARSE_WARNING`s):
  - `SUBTRACT a FROM b GIVING c` silently dropped the `GIVING c` clause
    whenever it appeared (the 3-operand form's target was always `b`,
    never `c`) — the `FROM` branch never checked for a trailing `GIVING`
    the way the `ADD ... TO` branch already did. Fixed by mirroring that
    check. Also fixed the more general root cause in
    `consume_keyword_and_operand`: it only skipped `NEWLINE` tokens
    *between* a keyword and its operand, not *before* checking whether the
    keyword was even present, so `GIVING` (or any such optional clause) on
    its own continuation line — ordinary free-form COBOL layout — was
    missed entirely. This also fixes the same class of bug for `ADD ... TO
    ... GIVING` when `GIVING` is on a continuation line.
  - `DISPLAY` stopped at a subscripted operand like `SQLERRD(3)`: the item
    loop only accepted `STRING_LITERAL`/`IDENTIFIER`/`NUMERIC_LITERAL`
    tokens, so the bare `(` token after the identifier fell through to the
    "unknown token, stop parsing" branch, dropping the subscript and
    everything after it. Subscripted identifiers are now folded into a
    single display item (`SQLERRD(3)`).
  - `WRITE record FROM 'literal'` (an IBM/GnuCOBOL extension for writing a
    fixed message record) wasn't recognized — the `FROM` source only
    accepted `IDENTIFIER`; a string literal was left unconsumed. Now
    accepted and stored quoted, matching how other operand literals are
    serialized.
  Pinned by `tests/unit/test_arithmetic_size_error_branches.py`,
  `tests/unit/test_display_parser.py`, and
  `tests/unit/io_statements/test_write_close_parsers.py`.

* **`GO TO a b c DEPENDING ON x` no longer collapses to `GO TO a`** (audit
  2026-07-07 C4). All targets are kept (`GoStatement.target_paragraphs`)
  and the `DEPENDING ON` variable is captured. The extra targets are only
  consumed when a `DEPENDING` clause actually follows (peek-ahead), so an
  identifier after a missing sentence period is still treated as the next
  paragraph rather than swallowed. Previously the extra targets and the
  variable were silently skipped — and the variable could become a phantom
  paragraph.

* **Level-88 condition names and level-66 RENAMES survive `to_dict()`**
  (audit 2026-07-07 C5). `CobolDataItem.to_dict()` emits `condition_names`;
  `CobolSection.to_dict()` emits `renames_items`. Both node types were
  parsed in-memory but dropped from every JSON export.

* **`CALL ... NOT ON EXCEPTION` handler serialization and traversal** (audit
  2026-07-07 C6). `CallStatement.to_dict()` now includes
  `not_on_exception`, and all CALL handler statements are registered as AST
  children so `find_all_by_type()` agrees with `get_all_statements()`.

* **CLI exit codes are honest** (audit 2026-07-07 C7). `cobol-parser parse`
  exits `2` (with a stderr summary) when the parse completed with collected
  errors; `batch` exits `2` when any file has a `read_error` or
  `success=false`; analyzer subcommands print a stderr warning when
  analyzing a partial AST. Previously every command exited `0` as long as
  an AST existed.

* **A poisoned file no longer aborts an entire batch** (audit 2026-07-07
  C8). Batch workers catch parse-time exceptions (and `UnicodeDecodeError`
  under `errors="strict"`) and record them as per-file
  `BatchResult.read_error` instead of propagating out of the pool and
  losing every other file's result.

* **`WRITE ... ADVANCING n LINES/PAGE` keeps the count and unit** (audit
  2026-07-07 H3). The WRITE parser now populates
  `IOWriteStatement.advancing_clause`; previously the count/unit tokens
  were consumed and dropped.

* **Copybook expansion warnings propagate** (audit 2026-07-07 H6).
  `parse_cobol_with_expansion` copies `expansion.statistics.warnings`
  (lossy encoding decodes, content validation, level-number mismatches)
  onto `ParseResult.warnings`; they were previously discarded with the
  `CopybookExpansion` object.

### Added (pre-2026-07-07)

* Strict support tests for the real-life NIST COBOL-85 corpus
  (`tests/integration/test_nist_cobol85_support.py`). All 459 `.CBL`
  programs in `examples/cobol/` must now parse **error-free** (the
  pre-existing corpus test only checked that parsing does not crash).
  455/459 currently pass. The 4 remaining are pinned
  as strict-xfail `KNOWN_ISSUES` with documented causes, so any parser
  improvement must remove the entry and the list only ever shrinks:
  `OBNC1M` (a COBOL-74 obsolete-feature test that embeds a phony program in
  a comment-entry, requiring Area A/B-aware parsing), `SM101A` (requires
  copybook expansion by design), and `SM206A`/`SM208A` (need `COPY REPLACING` /
  `REPLACE` pseudo-text substitution — uncovered by the H3 MOVE fix, see
  *Fixed* below). (`NC205A`, also uncovered by the H3 fix, was a
  continuation-line bug that shattered a split numeric literal and is now
  fixed — see *Fixed* below.) `SM101A` and `SM207A` must additionally
  parse clean with copybook expansion against the suite's own copybooks,
  and all 51 `.CPY` copybooks must pass `validate_copybook_content`.

* All CLI outputs are now properly identified. Every JSON document emitted by
  the `cobol-parser` CLI starts with a `source_file` key (the input path as
  given on the command line) and, for subcommands that parse the source, a
  `program_id` key (the PROGRAM-ID from the IDENTIFICATION DIVISION, or
  `null` when the program has none). This covers `analyze`, `dead-code`,
  `program-flow` (JSON format), `io-sequence`, `move-type-check`,
  `linkage-check`, `language-env`, `ims-dli`, `expand`, and `parse`
  (`--errors`/`--stats` wrapper). `batch` entries additionally carry
  `program_id` next to the existing `path`. Mermaid flowcharts from
  `program-flow --format mermaid` now start with a `%% Program: <name>`
  comment header (DOT output already named the digraph after the program).
  The contract is pinned by `tests/unit/cli/test_output_identification.py`.

### Changed

* **CLI output shapes for list-style results** (part of the output
  identification change above; library APIs are unchanged). `tokenize` now
  emits `{"source_file": ..., "tokens": [...]}` instead of a bare token
  list. `parse --find-type` emits `{"source_file", "program_id",
  "node_type", "matches"}` instead of a bare node list, and dotted-path
  extraction (`parse <file> <path>`) emits `{"source_file", "program_id",
  "path", "result"}` instead of the bare subtree; with `--errors`/`--stats`
  a path extraction now carries those keys directly instead of being wrapped
  under an `"ast"` key.

* `PictureClause` now validates the PICTURE pattern and exposes `is_valid` and
  `validation_errors` (also surfaced in `to_dict()`). Validation is
  conservative -- it flags only unambiguously illegal pictures (empty pattern,
  illegal characters, malformed/empty/zero repeat factors, unbalanced
  parentheses, more than one `V`, both `V` and a decimal point, multiple
  decimal points, and a misplaced or duplicated `S`) so valid pictures are
  never rejected. Pattern parsing remains lenient: an invalid picture is
  flagged but never aborts the surrounding parse.

### Changed

* Internal code-review cleanup removing dead code and consolidating
  duplication (no public-API or behaviour changes; full test suite unchanged).
  Removed unreferenced symbols (`ParserHost` protocol, `TokenStream.match_value`,
  four unused `CobolFileDescription` builder methods, the orphaned
  `TestReference` dataclass, a stray `TypeVar`, and ten dead fixed-format column
  constants in the lexer that duplicated the preprocessor's). Consolidated
  copy-pasted logic behind shared helpers: per-subcommand parse/emit/parser
  boilerplate in the CLI (`_parse_or_fail`, `_emit_report`,
  `_build_analyzer_parser`, `_stats_dict`); clause-list serialization and
  clause/operand setters in the statement AST models
  (`CobolStatement._serialize_clauses` / `_add_unique_operand` and IO clause
  mixins); IO statement-parser preamble and INVALID KEY / KEY-IS handling
  (`create_statement`, `consume_key_is`, `try_consume_keyword`, and reuse of
  `parse_invalid_key_clauses`); and the duplicated unescaped-quote scan in the
  copybook preprocessor.
* Silent `except Exception` handlers that swallowed failures without a trace
  now emit diagnostics instead. `batch.parse_files_with_copybooks()` logs a
  `WARNING` (logger `cobolparser.batch`) when copybook expansion fails and it
  falls back to parsing raw source, and the statement-parser probe helpers
  `peek_token()` / `try_parse_nested()` log at `DEBUG` when their "never raise"
  contract suppresses an exception. The fall-back behaviour itself is
  unchanged. The dead broad-`except` around `CobolProgram.get_division()` in
  the CRUD matrix generator (a plain dict lookup that cannot raise) was
  removed.

### Fixed

* **`INSPECT`, `STRING`, and `UNSTRING` no longer swallow the following
  statement**, and a **missing `END-EXEC` on `EXEC SQL`/`CICS`/`IMS` blocks is
  now reported instead of silently consuming the rest of the program** (audit
  2026-07-06 H2 — the last four verbs in the "swallow the next statement"
  class after MOVE/arithmetic/COMPUTE). A COBOL sentence may legally contain
  several statements with no separating period; previously an un-punctuated
  `INSPECT`/`STRING`/`UNSTRING` immediately followed by another statement (e.g.
  `INSPECT WS-X TALLYING WS-C FOR ALL 'A'  DISPLAY 'X'`) consumed that
  statement — INSPECT's trailing "consume to period" loop and the
  STRING/UNSTRING main-loop `else: consume()` fall-throughs never checked a
  statement boundary. A new shared `is_statement_boundary()` predicate
  (`parsers/statements/_utils.py`, unioning `STATEMENT_TOKEN_TYPES` /
  `STATEMENT_KEYWORDS` / `SCOPE_TERMINATORS` / `CONTROL_FLOW_BOUNDARIES`) now
  stops all three at the boundary; behavior stays `errors=0`. `EXEC` blocks
  can't use a content boundary (embedded SQL legitimately contains
  SET/DELETE/UPDATE/CALL/OPEN/CLOSE), so `collect_exec_sql_text` instead
  detects a missing `END-EXEC` and records an "Unterminated EXEC block" parse
  error, changing that malformed case from a silent `errors=0`,
  `success=True` swallow to a reported error (`success=False`); well-formed
  blocks are unchanged. Pinned by `TestInspectDoesNotSwallowFollowingStatement`,
  `TestStringDoesNotSwallowFollowingStatement`,
  `TestUnstringDoesNotSwallowFollowingStatement`, and
  `TestExecMissingEndExecReportsError` in
  `tests/regression/test_tier2_silent_drop_regressions.py`.

* `IF` condition trees now honour COBOL AND/OR precedence (audit finding H4).
  `IfStatementParser._build_condition_expression` split on the first of
  `("AND", "OR")` it found, making `AND` the tree root — so
  `IF A = 1 OR B = 2 AND C = 3` parsed as `(A OR B) AND C` instead of the
  correct `A OR (B AND C)`, silently inverting the logic for any analyzer that
  reads the condition tree. The split now runs `OR` before `AND` (OR binds
  loosest, so it becomes the root and `AND` nests beneath it) and is
  parenthesis-aware: it strips a fully-enclosing `( ... )` wrapper and only
  splits on operators at the top paren level, so explicit grouping such as
  `IF (A = 1 OR B = 2) AND C = 3` correctly keeps `AND` as the root. As a
  side effect, parenthesised operands no longer leak stray `(`/`)` tokens into
  the comparison strings. The split now picks the rightmost top-level operator,
  making repeated same-precedence chains (`A OR B OR C`) left-associative to
  match COBOL's left-to-right evaluation. Layout tokens (whitespace, end-of-line,
  continuation, comments) are now stripped from the condition token list before
  the tree is built, so a fully-parenthesised condition such as
  `IF (A = 1 OR B = 2)` is no longer defeated by the trailing end-of-line token
  (which previously left `tokens[-1] != ")"`, blocking the enclosing-paren strip
  and collapsing the whole condition into a bogus comparison); multi-line
  conditions are handled more robustly for the same reason. Pinned by
  `tests/unit/test_if_parser_comprehensive.py::TestIfConditionPrecedence`.

* An unterminated string literal at end of input no longer aborts the whole
  parse under `ErrorRecoveryMode.COLLECT_ALL` (audit finding H5). Fixed-format
  normalization (`normalize_fixed_format`) raises `ValueError` on a literal
  still open at EOF; that raise was reached before error recovery was active,
  so a single bad literal collapsed the entire program to `ast=None` — in
  `CobolParser._parse_core` (via the generic exception safety net) and in the
  `parse_cobol` convenience function (which caught it but returned `ast=None`
  regardless of mode). `_parse_core` now records the unterminated-literal error
  and, unless in `FAIL_FAST`, re-normalizes with `merge_continued_literals=False`
  (a non-raising best-effort path the lexer already tokenizes permissively) so a
  partial AST survives; `parse_cobol` defers to the parser for this recovery.
  `FAIL_FAST` still aborts with the error, and calling `normalize_fixed_format`
  directly still raises by default. Pinned by
  `tests/unit/test_critical_fixes.py::TestUnterminatedLiteralDoesNotAbortParse`.
* **Malformed `MOVE` statements no longer parse silently (audit finding H3).**
  The MOVE parser accepted incomplete input and produced a plausible-but-wrong
  node with `errors == 0`: `MOVE A TO.` yielded a `MoveStatement` with
  `targets: []`, `MOVE A` (no `TO`) and a stream truncated at `MOVE A TO` were
  likewise accepted. The parser now reports a diagnostic (via the parse
  context, the same path GO/CALL use) when `TO` is missing or when no receiving
  field follows `TO`; well-formed MOVEs — including multi-target
  (`MOVE A TO B C`), subscripted targets (`MOVE A TO B(I)`), literals, figurative
  constants, and `MOVE CORRESPONDING` — stay error-free. A missing *source*
  (`MOVE TO X`) is intentionally not flagged, because it is indistinguishable
  from stray `*>`-comment / pseudo-text the preprocessor does not yet strip and
  flagging it faulted otherwise-valid programs. Pinned by
  `tests/unit/test_move_malformed_diagnostics.py`. This surfaced that three NIST
  programs were previously passing the error-free guarantee *only* by way of
  this silent acceptance — `SM206A`/`SM208A` (need `COPY REPLACING` /`REPLACE`
  pseudo-text substitution) and `NC205A` (the continuation-line bug fixed
  below); `SM206A`/`SM208A` are now pinned as strict-xfail `KNOWN_ISSUES`,
  while `NC205A` is fixed in this same release.

* `normalize_fixed_format` now joins **non-literal fixed-format continuation
  lines** (indicator `-` in column 7) with no intervening space, matching the
  COBOL rule that the first non-blank character of a continuation line is the
  successor of the last non-blank character of the continued line. Previously a
  space was injected before every such chunk, so a numeric literal split across
  continuation lines (one character per line, as in NIST `NC205A.CBL`'s
  `-999.777`) normalised to `- 9  9  9  .  7  7  7` — spaced-out digits plus a
  free-standing `.` that the lexer treated as a statement terminator, silently
  truncating the enclosing `MOVE` (the AST lost the `MOVE -999.777 TO CONT-B`
  entirely, yet `result.success` stayed `True`). Words split mid-token rejoin
  correctly for the same reason; alphanumeric literals split with `-` were
  already handled via the open-quote continuation path. The fix is applied to
  both the pure-Python implementation and the Cython `_preprocess_fast`
  fast-path (the checked-in `.c` is regenerated). Because the H3 MOVE fix
  (above) had just pinned `NC205A` as strict-xfail for exactly this defect,
  that `KNOWN_ISSUES` entry is removed here — NC205A parses error-free again.
  Pinned by `tests/regression/test_continued_literal_normalization.py`, which
  exercises both code paths and the real `NC205A.CBL`.

* `EVALUATE` WHEN-branch statements are now reachable via the public tree-walk
  API. `EvaluateStatementParser` attached WHEN clauses by mutating the model
  directly (`stmt.when_clauses.append(...)` and `stmt.default_when = ...`),
  bypassing `add_when_clause` / `set_default_when` and so never registering the
  `WhenClause` nodes as AST children. Because `find_all_by_type`,
  `find_first_by_type`, and `traverse_depth_first` only descend `node.children`,
  every statement nested in a `WHEN` or `WHEN OTHER` branch was invisible to
  them (e.g. `ast.find_all_by_type("MoveStatement")` returned `0` for a MOVE
  that lived only inside an EVALUATE), even though the data was present in the
  `when_clauses` attribute and reachable via the separate `get_all_statements`
  traversal. The parser now routes both paths through the model methods so the
  clauses are real children; `get_all_statements` dedupes by `id` (visited set)
  so the now-registered children are not double-counted, and `to_dict()` output
  is unchanged (it serializes attributes, not `children`). Pinned by
  `tests/regression/test_evaluate_traversal_regression.py`.

* IO-statement conditional clause bodies are now parsed into the AST instead
  of being silently discarded. `collect_clause_stmts` (shared by READ,
  WRITE, REWRITE, DELETE, and START) previously consumed the tokens of
  `AT END` / `NOT AT END` / `INVALID KEY` / `NOT INVALID KEY` bodies and
  always returned `[]`, so an inner statement such as
  `READ F AT END CALL "EOFH" USING WS-AMT END-READ.` vanished from the AST
  entirely — `at_end_clause` was `[]` and the CALL appeared nowhere
  (breaking downstream boundary-statement detection, e.g. mockymock's
  mock-surface analysis). Clause bodies are now dispatched through the
  statement registry (the same nesting mechanism IF/PERFORM/EVALUATE use),
  attached to the owning IO node's clause lists with correct
  `SourceLocation`s, added as AST children (visible to `find_all_by_type`
  and `to_dict()`), and terminated correctly at periods, the next clause
  keyword, and `END-xxx` scope terminators. Supporting fixes:
  `WriteStatementParser` now parses `INVALID KEY` / `NOT INVALID KEY`
  (previously unsupported); `StartStatementParser` matches `KEY IS`
  comparison keywords by value (they lex as dedicated token types, not
  IDENTIFIERs) and consumes the trailing key data-name; the MOVE-target,
  DISPLAY-item, and CALL-USING collection loops stop at scope terminators
  (`END-READ` etc.) instead of capturing them as operands. Pinned by
  `tests/unit/io_statements/test_clause_bodies.py`.

* `find_copybook_file()` now reports copybook paths with their **on-disk
  basename casing**. On case-insensitive filesystems (Windows/macOS) the
  extension probe order (`.cpy` before `.CPY`) could match a file whose
  on-disk casing differs (disk: `MEM.CPY`, probe: `MEM.cpy`), and the
  probe-cased path leaked into `CopybookExpansion.included_copybooks` and
  warning messages, making reported paths platform-dependent. The found
  path's basename is now canonicalised against `os.scandir` entry names.
  The `PathResolver` directory index (tier 2) already used scandir names
  and was unaffected. Pinned by
  `tests/unit/test_path_resolver_gaps.py::TestOnDiskCasing`; the
  library-qualified COPY regression tests now compare paths exactly
  instead of via `os.path.normcase`.

* Numeric `VALUE` clause literals that lex as `LEVEL_NUMBER` are no longer
  silently dropped. The lexer types every 1-2 digit integer as
  `TokenType.LEVEL_NUMBER` regardless of context, and
  `DataDivisionParser._parse_value_clause` only accepted `NUMERIC_LITERAL` —
  so `VALUE 5` / `VALUE 42` produced `value_clause=None` and the orphaned
  token then spawned a bogus anonymous data item at that level. `VALUE IS
  <literal>` (the `IS` was never consumed) and signed literals (`VALUE -5`,
  `VALUE +2.5` — sign lexed as a separate `MINUS`/`PLUS` token) were dropped
  the same way. Level-88 condition names had the parallel bug: their value
  collector broke on `LEVEL_NUMBER`, so `88 FLAG-ON VALUE 1.` yielded
  `values == []` plus a spurious top-level item. All forms now parse
  correctly; pinned by `tests/regression/test_numeric_value_clause.py`.

* `PerformStatementParser` now recognises `THROUGH` as a synonym for `THRU` in
  `PERFORM paragraph THRU/THROUGH paragraph` ranges. Previously only the
  literal `THRU` token set `PerformStatement.thru_paragraph`; `THROUGH` fell
  through unmatched, leaving `thru_paragraph` unset and the ending paragraph
  name misparsed as a spurious extra paragraph in the AST.

* Division headers split across source lines (`DATA` at the end of one
  line, `DIVISION.` on the next — legal COBOL word separation) are now
  recognised, both at the header parser (`BaseDivisionParser.parse`) and in
  the DATA DIVISION section scanner, which previously consumed a split
  `PROCEDURE DIVISION` header as noise and silently dropped the entire
  procedure division. Found via NIST `NC113M.CBL`, which now parses
  error-free with all four divisions and 111 statements.

* IDENTIFICATION DIVISION comment-entries (AUTHOR, INSTALLATION, ...)
  containing a bare division keyword (e.g. `AUTOMATIC DATA AND
  TELECOMMUNICATION SERVICE`) are no longer mistaken for a division
  boundary: a bare keyword only ends the division when the next significant
  token is `DIVISION`. Shared helper `at_division_boundary()` in
  `parsers/divisions/base.py`. Found via NIST `OBNC1M.CBL`.

* COMPUTE now accepts the full receiver list syntax
  `COMPUTE {identifier [ROUNDED]}... = expression`, including subscripted
  receivers (`T (2, 2, 2)`). Previously only a single receiver with one
  optional ROUNDED was parsed and anything more reported "missing '='
  operator". Found via NIST `NC252A.CBL`, which now parses error-free.

* A period after a numeric literal is now treated as a decimal point only
  when followed by a digit (a COBOL numeric literal cannot end with a
  decimal point). Previously `COMPUTE A = 174 / 16.` lexed `16.` as one
  literal, so the sentence never terminated and the following statement was
  silently swallowed into the COMPUTE expression. Fixed in both the pure-
  Python lexer and the Cython fast path (`_lexer_fast.pyx`, regenerated
  `.c` checked in).

* `validate_copybook_content()` no longer flags copybooks that continue a
  string literal across lines (fixed-format `-` in column 7 re-opens the
  literal with an extra quote) as having unbalanced quotes. Found via NIST
  `K1WKA.CPY` / `K1WKY.CPY`; genuinely unbalanced quotes are still flagged.

* Library-qualified `COPY member OF library` now falls back to the plain
  copybook search path when the library has no matching subdirectory
  (previously an unhandled `CopybookNotFoundError` — NIST `SM207A.CBL`
  crashed expansion even though `ALTLB.CPY` sat in the search path). A
  `<search-dir>/<library>/` subdirectory still takes precedence when it
  exists.

* `ASTNode.find_all_by_type()` / `find_first_by_type()` now also match a
  node's concrete class name (e.g. `"MoveStatement"`, `"CallStatement"`,
  `"ExecSQLStatement"`, `"IOReadStatement"`) in addition to the `node_type`
  attribute. All statement subclasses share the generic `node_type`
  `"Statement"`, so lookups by statement class name silently returned nothing
  — which meant the `analyze` CLI subcommand always printed an empty
  `"calls"` list and `parse --find-type` could never select a specific
  statement kind (both are documented to work this way). Lookups by
  `node_type` (`"Statement"`, `"DataItem"`, `"ConditionNameItem"`, ...) are
  unchanged, and serialized output is unaffected.

* Lexer now recognises typed-literal prefixes (`X"1F"` hexadecimal, `N"..."`
  national, `NX"..."` national-hex, `G"..."` DBCS/graphic, `Z"..."`
  null-terminated, `U"..."` UTF-8, `B"..."` boolean). Previously a prefixed
  literal was split into a separate identifier token plus a string literal
  (e.g. `MOVE X"1F" TO WS` parsed `X` as its own operand), corrupting
  statement operands. Such literals now produce a single `STRING_LITERAL`
  token whose `raw_value` preserves the original prefixed source text. The
  Cython-accelerated lexer (`_lexer_fast`) was updated to match.

## [1.1.0](https://github.com/Landparty/cobol-parser/compare/v1.0.0...v1.1.0) (2026-06-19)


### Features

* add shamrice/COBOL-Examples corpus with parse verification tests ([cd0b7c4](https://github.com/Landparty/cobol-parser/commit/cd0b7c40e1e5881b2f3e634bb36fff0333d5362e))
* **ims:** add IMSEntryPoint class and integrate ENTRY 'DLITCBL' detection ([b41104c](https://github.com/Landparty/cobol-parser/commit/b41104c54b7ddddeec348f7467c483adc20b0d50))
* **lexer:** support typed-literal prefixes (X/N/NX/G/Z/U/B) ([b3d428a](https://github.com/Landparty/cobol-parser/commit/b3d428ae7844b4441357dc0c20733946bbc1a81b))
* **models:** validate PICTURE clause patterns ([6c9a414](https://github.com/Landparty/cobol-parser/commit/6c9a414aaa43c292d7e6181747fac7f49117ed53))


### Bug Fixes

* **docs:** update test count and success metrics in README and CLAUDE.md ([bfad610](https://github.com/Landparty/cobol-parser/commit/bfad61032d1d6d320cb24f7f11bb8e8bed295cdf))
* **lexer:** keep unterminated typed literals lenient in free-form ([401aa4f](https://github.com/Landparty/cobol-parser/commit/401aa4f60c2616978a3af71739a91bcd1fa4e63c))
* **logging:** include tracebacks in suppressed-exception logs; correct test docstring ([f4959c5](https://github.com/Landparty/cobol-parser/commit/f4959c569df1ed5d07df15fe8c452b8db91ef366))
* **parser:** improve real-world COBOL parse success to 99.1% on NIST-85 corpus ([7a1a387](https://github.com/Landparty/cobol-parser/commit/7a1a3876e2e2fb87648f59a2b8aa8b3710b93e2a))


### Documentation

* add design spec for shamrice COBOL examples corpus ([98bb00b](https://github.com/Landparty/cobol-parser/commit/98bb00bbbd4659f914e866905290ef542c785489))

## 1.0.0 (2026-06-16)


### Features

* add --profile, --profile-top-n, --profile-output CLI flags ([13a3f1f](https://github.com/Landparty/cobol-parser/commit/13a3f1f1b9b0690105eaed738601d9730abd76fa))
* add --profile/--profile-top-n/--profile-output CLI flags to cobol-parser ([5f2468c](https://github.com/Landparty/cobol-parser/commit/5f2468c61fc1fd61f2099fe550aff4646c02181c))
* add advanced configuration options for ignored memory patterns and language server settings ([4808304](https://github.com/Landparty/cobol-parser/commit/4808304ddf6262dc7797c45410d4ca194492891b))
* add batch.py with BatchResult, _parse_one worker, and parse_files() ([6680e5d](https://github.com/Landparty/cobol-parser/commit/6680e5d829c6344f418a28feb044a470d4231467))
* Add comprehensive COBOL CALL statement parsing, samples, and validation utilities. ([9c4d75f](https://github.com/Landparty/cobol-parser/commit/9c4d75f6b6b5f5689de5aa501ff7558640eb5006))
* Add comprehensive COBOL examples demonstrating CALL statements and exception handling ([52e5f14](https://github.com/Landparty/cobol-parser/commit/52e5f1447077d3facce33e9c9848c8f04fda5220))
* Add comprehensive test cases and samples for COBOL CALL and ENTRY statement parsing. ([c07e94b](https://github.com/Landparty/cobol-parser/commit/c07e94bb22bd6314ccdb573f724b05682bcd2a74))
* add convergence node tracking for branch decisions in program flow analysis ([b7e0787](https://github.com/Landparty/cobol-parser/commit/b7e07871882ff2ee3b68cfcdba3228958c99e191))
* add CRUDMatrixGenerator for mainframe modernization analysis ([79f2a28](https://github.com/Landparty/cobol-parser/commit/79f2a282cc7794eb7f9589fd037c92ac8f997707))
* Add examples for COBOL parser testing and demonstration ([8df3f9f](https://github.com/Landparty/cobol-parser/commit/8df3f9ffeb8a36657b531964508e628e6ce23a12))
* add IO statement parsers for OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START ([63ae8c2](https://github.com/Landparty/cobol-parser/commit/63ae8c2d44963f154362bb81642040606368364c))
* Add macOS compatibility verification script and update README ([18e724c](https://github.com/Landparty/cobol-parser/commit/18e724c3dfea79327bc6ef83c948c2fd06f828f6))
* add profiling module with ProfilerContext, ProfilingResult, FunctionProfile ([01ab5d2](https://github.com/Landparty/cobol-parser/commit/01ab5d299046c7ba1d6d1c60d230721936912279))
* add profiling overloads to CobolParser.parse() ([27a0dd8](https://github.com/Landparty/cobol-parser/commit/27a0dd8e02a6180328308932cafe07c39e2f7044))
* add profiling overloads to parse_cobol() ([1e17ef0](https://github.com/Landparty/cobol-parser/commit/1e17ef0e029fc9cafbbb6bf9abf68cbf9a5fa6ce))
* add profiling support to batch parsing functions ([1ac0f4f](https://github.com/Landparty/cobol-parser/commit/1ac0f4f08fe78382fcae884cb9c3f338ad35f055))
* add profiling support to BatchResult and parse_files() ([b3332e0](https://github.com/Landparty/cobol-parser/commit/b3332e0902f9fda206bedf5f41e968b19034ab07))
* add psutil optional dependency for profiling extra ([33774c2](https://github.com/Landparty/cobol-parser/commit/33774c20342200403eeea1ea8fedf513ebace362))
* complete ProgramFlowAnalyzer with cycle detection, unreachable nodes, and missing statement coverage ([5ac379e](https://github.com/Landparty/cobol-parser/commit/5ac379ea97766255e4a743b1f7b1b0480c4874d0))
* **docs:** Revise documentation structure and add cookbook for practical usage examples ([f0b6e1c](https://github.com/Landparty/cobol-parser/commit/f0b6e1c2db0f9fb3c3e31a3accb03a050666b9f3))
* Enhance COBOL parser to support nested PERFORM and IF statements with inline handling ([b7cf7ef](https://github.com/Landparty/cobol-parser/commit/b7cf7ef20badf742816403248f204856df0dc1c1))
* enhance COBOL parser with batch processing optimizations and reusable components ([851b348](https://github.com/Landparty/cobol-parser/commit/851b348e44e414f7d772ca9c4dfec668d3ec10f0))
* Enhance COBOL parser with fixed-format auto-detection and multi-line string support ([48375e6](https://github.com/Landparty/cobol-parser/commit/48375e6f093e21eb1bb6c0b1436e37cd13854888))
* Enhance COPY statement parser with comment and string literal handling ([6c5a97b](https://github.com/Landparty/cobol-parser/commit/6c5a97b46cc1032112bd3b29ea8c5cfc839c8900))
* Enhance dynamic CALL statement support in COBOL parser ([744d0ca](https://github.com/Landparty/cobol-parser/commit/744d0ca0ba049ca8f63c00cf8515869599164f4d))
* **evaluate-coverage:** Add specification and quality checklist for COBOL Fixed-Format EVALUATE coverage ([74f480f](https://github.com/Landparty/cobol-parser/commit/74f480f29325d44e90ca07045290f83ed3f3aeac))
* export parse_files and BatchResult from cobolparser package ([1a3a9e6](https://github.com/Landparty/cobol-parser/commit/1a3a9e61cc4d0c6d15d804c72ab04209f04fab1a))
* export ProfilingResult and FunctionProfile from cobolparser public API ([b0803c3](https://github.com/Landparty/cobol-parser/commit/b0803c3ce9739367c7c10babdd767dac010e1080))
* Implement copybook preprocessing, expand documentation with new guides, and archive historical reports and metrics. ([3790f39](https://github.com/Landparty/cobol-parser/commit/3790f3991e5b89b17375a8b2e9502a6bae319597))
* implemented parser to return IMS, CICS and DB2 instructions ([11771af](https://github.com/Landparty/cobol-parser/commit/11771af1e8cfefb3b4573b5aa0bc6d077bc33223))
* **io-statements:** Implement comprehensive support for IO statements ([39b1881](https://github.com/Landparty/cobol-parser/commit/39b1881c0d77d185c21352328c2fb3510f2edab2))
* **lexer:** Add support for figurative constants in VALUE clause parsing ([d7526e5](https://github.com/Landparty/cobol-parser/commit/d7526e592d382daeb18d872b3574b7345f57f1da))
* optimize statement retrieval in CobolProgram with caching mechanism ([6257308](https://github.com/Landparty/cobol-parser/commit/625730870b49f817d1ce79ffd69ee0e37d9d4b23))
* **parser:** Implement inline parsing for EVALUATE statement with diagnostics ([aef8eda](https://github.com/Landparty/cobol-parser/commit/aef8edabdb5254519154cc6ab3ccca285f598c63))
* **parser:** surface statement errors and honor ErrorRecoveryMode ([aa87b88](https://github.com/Landparty/cobol-parser/commit/aa87b8827590b97179534926a36d71b81a9c1c09))
* **program-flow:** model THRU ranges and classify circular dependencies ([da89832](https://github.com/Landparty/cobol-parser/commit/da8983225c237e9c8173662f774bf5c2787ce8e2))
* **program-flow:** model THRU ranges and classify cycles ([e166594](https://github.com/Landparty/cobol-parser/commit/e1665947b4e9dd12c62b4c0e4ee34320f62fdffc))
* **T015-T021:** Complete Phase 2 test suites and contracts ([c1aea81](https://github.com/Landparty/cobol-parser/commit/c1aea81c06bf06100a51d05a38d3ebbe76afa409))
* update project dependencies and enhance CLAUDE.md documentation ([2a5d200](https://github.com/Landparty/cobol-parser/commit/2a5d20019213c0784e1adb748450371bd04d56ba))


### Bug Fixes

* address review feedback on parser/lexer optimizations ([fc781c2](https://github.com/Landparty/cobol-parser/commit/fc781c2614705138cfc8f91093950bb2857ee0ef))
* apply review feedback on T3 profiling overloads ([911834d](https://github.com/Landparty/cobol-parser/commit/911834da87b848194d7498f89230384d90068884))
* catch parse_cobol exceptions in worker to prevent batch abort ([f7d8fde](https://github.com/Landparty/cobol-parser/commit/f7d8fde28afe0d59ee62acd3cd4a5bbba7d9572e))
* clean up profiling module per code review ([9eec0ce](https://github.com/Landparty/cobol-parser/commit/9eec0ce5b428fd32472890ab33d13a5353893d72))
* **copy_statement_parser:** handle \r and \r\n line endings in source_location ([b6f4822](https://github.com/Landparty/cobol-parser/commit/b6f48225c40ff087e909efaf3ca5a5c500f7280d))
* **data:** drop dead branches in _parse_data_item fallback ([e641b7c](https://github.com/Landparty/cobol-parser/commit/e641b7cd686af285604ffe2e2a1ac59aa7dd51e6))
* **data:** mirror SIGN/SYNC/JUSTIFIED/BLANK/POINTER clauses in Cython fast path ([4acb0b1](https://github.com/Landparty/cobol-parser/commit/4acb0b1433a837a40e179a69b5271522cce061e4))
* **lexer,preprocess:** scientific notation crash, configurable cache, encoding warnings ([740d725](https://github.com/Landparty/cobol-parser/commit/740d72510a109dc87cd70936219d896cd6337dbb))
* **parser,preprocess:** address Copilot review on PR [#49](https://github.com/Landparty/cobol-parser/issues/49) ([a69033e](https://github.com/Landparty/cobol-parser/commit/a69033e0ce994d94b326a365093a1820990c1dec))
* remove over-broad parse exception catch; parity test uses workers=2 for pickle coverage ([a54b31d](https://github.com/Landparty/cobol-parser/commit/a54b31d89a0531ae28214be06825420759186919))
* remove unused pytest imports flagged by ruff ([9d9c0ac](https://github.com/Landparty/cobol-parser/commit/9d9c0acf5d4c1e5f2c1b40f2f0eb3026bb0b8cd4))
* resolve 6 critical parser edge cases causing silent data loss or crashes ([88f97c6](https://github.com/Landparty/cobol-parser/commit/88f97c6113bf088e472335ca7c611dd84de55a0f))
* **setup:** drop unused zip(), satisfy ruff B905 ([2964649](https://github.com/Landparty/cobol-parser/commit/2964649fae357ce3138dfeeb4bfa5b7a6aee62dd))


### Performance Improvements

* always build Cython extensions; tighten TokenStream ([0b33ae9](https://github.com/Landparty/cobol-parser/commit/0b33ae91026807d2cd4b35b74b33fda93e6d7ae3))
* **build,parser:** always build Cython extensions; tighten TokenStream ([1739e40](https://github.com/Landparty/cobol-parser/commit/1739e409f318f1aa7f4db8fc33ce37bd58d3f04c))
* **copy_statement_parser:** pre-build newline index for O(log n) line lookups ([26c1dd3](https://github.com/Landparty/cobol-parser/commit/26c1dd33f306c199ca61f023976fec2252293b85))
* **data:** Cythonize _parse_picture_clause and _parse_data_item loops ([430e1bb](https://github.com/Landparty/cobol-parser/commit/430e1bb2e08001b1d0162fc9a654c5aeb27d479e))
* **data:** hoist _parse_section literals; cache token attrs per iteration ([c263a8c](https://github.com/Landparty/cobol-parser/commit/c263a8c15465d48782e519960645e03db6a97233))
* **data:** use shared _DIVISION_TOKEN_TYPES set; drop hasattr/list-literal cruft ([21125fa](https://github.com/Landparty/cobol-parser/commit/21125fa788652b0cd233c8020a6f1d1aa2e4c497))
* **lexer,data:** Token __slots__; hoist allocations out of data-item loop ([a933512](https://github.com/Landparty/cobol-parser/commit/a933512593d556578c413d4a7500931d971b0135))
* **lexer,models,arith:** IntEnum TokenType; PIC first-char dispatch; COMPUTE inner loop ([773cd02](https://github.com/Landparty/cobol-parser/commit/773cd02d9c952af54edc872c0d26ca51b78bb220))
* **lexer,registry:** cythonize read_number_from_text; share registry across parses ([f0400d3](https://github.com/Landparty/cobol-parser/commit/f0400d3a402dfbe16e86774b646693833999ce32))
* **lexer:** Cythonize _try_single_line_string ([a99f2e2](https://github.com/Landparty/cobol-parser/commit/a99f2e2cb32524192c22a991dc0eb6eeef184ff9))
* **lexer:** Cythonize the outer tokenize() per-line loop ([6cc4128](https://github.com/Landparty/cobol-parser/commit/6cc41282ecbd467b385deb9670de90006e8f9191))
* **move_parser:** hoist stop_token_types and keywords to module-level frozensets ([616eced](https://github.com/Landparty/cobol-parser/commit/616ecedd9e8ea295d78d04dbeb67415cb1b2da47))


### Documentation

* Add comprehensive project completion summary ([ad3471b](https://github.com/Landparty/cobol-parser/commit/ad3471b2e32b1234b81e5ab98c8f4681cc0c1ede))
* add documentation audit design spec (2026-03-30) ([2e3d39a](https://github.com/Landparty/cobol-parser/commit/2e3d39a41ec071f1119e912dcd1debc84677d77a))
* add documentation audit implementation plan (2026-03-30) ([22ce72f](https://github.com/Landparty/cobol-parser/commit/22ce72f22336bd7517ede3248880eae654f8be98))
* Add final status report - project complete and production-ready ([6e028e6](https://github.com/Landparty/cobol-parser/commit/6e028e6a52628d663a1f642506175d37dff7d0ba))
* add framework baseline analysis and fill in plan.md with technical context ([65d576d](https://github.com/Landparty/cobol-parser/commit/65d576d2a7565941258a13ea0b8a95bedc2261e9))
* add full project audit report (2026-03-29) ([69f8d0d](https://github.com/Landparty/cobol-parser/commit/69f8d0d8507b9220f1a86a8ac959898691aadd7c))
* add performance profiling design spec ([b4ba714](https://github.com/Landparty/cobol-parser/commit/b4ba714c654a01953febf69d22abd14941c78a5d))
* add performance profiling implementation plan ([f084773](https://github.com/Landparty/cobol-parser/commit/f0847735f7542e66ae84d5d00a9a0c2634db7176))
* **changelog:** note Cython data-clause drop fix ([8021401](https://github.com/Landparty/cobol-parser/commit/8021401a23188b20a07acc71493f0f64360d0987))
* **claude:** refresh CLAUDE.md to match current code state ([b7c6036](https://github.com/Landparty/cobol-parser/commit/b7c6036278d7925c819a3ce789120db253984649))
* **claude:** refresh CLAUDE.md to match current code state ([931e692](https://github.com/Landparty/cobol-parser/commit/931e69234448db1bb5ce4bbdba5b7a0a634072fe))
* correct license references from MIT to proprietary EULA ([ea2254f](https://github.com/Landparty/cobol-parser/commit/ea2254fe0ab081786d6cf6e7bcada093588a32c0))
* document all analysis features and update CLI reference ([62e3475](https://github.com/Landparty/cobol-parser/commit/62e3475ff55355c34056a1ba00a705a606797569))
* fix BatchResult example — use r.path and guard r.result nullable ([4ee44ae](https://github.com/Landparty/cobol-parser/commit/4ee44ae63297fec76a153b6a4aa43c23cc86b356))
* fix duplicate section, stale file path, and vague BC-4-6 entries ([5f36c09](https://github.com/Landparty/cobol-parser/commit/5f36c09ed761a8f4075e416134965878a4a356a4))
* fix SQL example metadata fields and DECLARE CURSOR sql_type value ([a4520ee](https://github.com/Landparty/cobol-parser/commit/a4520ee2d17bd4b56309cc9a3eb7893982df9559))
* fix stale API reference in data-items.md ([cc4ae82](https://github.com/Landparty/cobol-parser/commit/cc4ae825a645ac223e7bcca8dd5b5b584645c822))
* refresh CLAUDE.md counts (tests, files, TokenTypes, analyzers) ([44af908](https://github.com/Landparty/cobol-parser/commit/44af9083e02e3589d54b0ae25b515f46d811a828))
* **T026-T027:** Add success criteria validation and mark Phase 3 complete ([1a53991](https://github.com/Landparty/cobol-parser/commit/1a53991d01b2349ed5c2218db3c2d033b10e935a))
* update CLAUDE.md to reflect current codebase ([de6c392](https://github.com/Landparty/cobol-parser/commit/de6c39290d8d5d0fb00844cd87fc4411d49afef2))
* update CLAUDE.md to reflect current codebase state ([d2873cf](https://github.com/Landparty/cobol-parser/commit/d2873cf34dc2f451fe9ab056e436bc6848cf6e9c))
* update docs hub — fix metrics, remove dead links, add batch parsing ([363c36a](https://github.com/Landparty/cobol-parser/commit/363c36a9bb11714f83e23440ebb9f6bf153df1c8))
* update documentation and examples for COBOL parser features and fixes ([344ce35](https://github.com/Landparty/cobol-parser/commit/344ce3578d12fbcfe3fc6d62652fc8063809da6e))
* update README badges/counts and add CHANGELOG entries for v1.3.0 and v2.0.0 ([1b403e3](https://github.com/Landparty/cobol-parser/commit/1b403e35cbdecdb526a010c68b8e40a05a60049c))
* update README with correct Python version, test count, and all features ([aad07d4](https://github.com/Landparty/cobol-parser/commit/aad07d42837212480b479665bdc2258259fe7cb0))
* update statement guides — fix AST field names and removed API references ([4994a4e](https://github.com/Landparty/cobol-parser/commit/4994a4eaac7ec15ee27a673f403d93fcedb22a25))
* Update tasks.md - mark all 27 tasks complete + add implementation status report ([bc8a7b3](https://github.com/Landparty/cobol-parser/commit/bc8a7b398779cb8e21fa1e16ff2e190c02831a02))

## [Unreleased]

### Added

- **DATA DIVISION completeness**:
  - `EXTERNAL` and `GLOBAL` data-item clauses are now recorded on
    `CobolDataItem` (`is_external` / `is_global`, serialized in `to_dict()`)
    instead of being silently consumed
  - FD/SD file-description clauses are captured rather than discarded: the
    file's `01` record carries an `fd_clauses` metadata mapping with
    `block_contains`, `record` (fixed and `RECORD VARYING ... DEPENDING ON`),
    `recording_mode`, `label_records`, `code_set`, `data_records`, `linage`,
    and `value_of`
  - Edited `PICTURE` clauses are extracted and classified correctly, including
    embedded decimal points and currency / sign / check-protect / stroke
    insertion symbols (`$$$,$$9.99`, `ZZ,ZZ9.99-`, `**,**9.99`, `XXX/XXX`);
    `PictureClause` now exposes `is_numeric_edited` / `is_alphanumeric_edited`
    and computes the displayed character size

### Fixed

- The Cython-accelerated data-item clause loop (`_data_fast`) had drifted out
  of sync with the pure-Python parser and silently dropped the `SIGN`,
  `SYNCHRONIZED`, `JUSTIFIED`, `BLANK WHEN ZERO`, and bare-`POINTER` clauses in
  compiled builds. The fast loop now hands those clauses back to the
  pure-Python path, which is the single source of truth, so the two
  implementations can no longer diverge. Picture extraction is likewise
  centralized in the Python `_parse_picture_clause`.

- **Analysis toolkit**: comprehensive static and dynamic analyzers exposed via `cobolparser.analysis` and the top-level package:
  - `DeadCodeAnalyzer` — unreferenced paragraphs and sections
  - `ProgramFlowAnalyzer` — control-flow graph with typed PERFORM / GO TO / CALL / fall-through edges (also wired to the `cobol-parser program-flow` CLI). PERFORM/SORT/MERGE `... THRU ...` edges now carry `thru_target` and the ordered `range_members` of every paragraph the range spans, and detected cycles are classified in `cycle_details` by kind (`PERFORM_RECURSION` / `GOTO_LOOP` / `FALL_THROUGH` / `MIXED`) so genuine recursive dependencies are distinguishable from sequential-fall-through artifacts
  - `IOLogger` — structured report of every CALL / SQL / FILE-IO / CONSOLE-IO / ENTRY operation with direction (INPUT / OUTPUT / BIDIRECTIONAL)
  - `IOSequenceAnalyzer` — detects READ/WRITE/REWRITE/DELETE/START before OPEN, double open/close, files left open at program exit
  - `MoveTypeChecker` — flags category-incompatible MOVE statements (numeric ↔ alphabetic, etc.)
  - `LinkageChecker` — cross-references CALL arguments with ENTRY declarations and LINKAGE SECTION 01-items
  - `LanguageEnvironmentAnalyzer` — IBM LE intrinsic functions and service calls
  - `CRUDMatrixGenerator` — program × file/table Create/Read/Update/Delete matrix with CSV and JSON export
  - `IMSSegmentAnalyzer` — resolves IMS DLI segment names for CBLTDLI / AIBTDLI / CEETDLI calls (all 16 DLI function codes)
  - `HostVariableResolver` — resolves `:host-var` references in EXEC SQL to DATA DIVISION data items and DCLGEN DECLARE TABLE columns
- **CobolCheck test generation**: `cobol-parser generate-tests` CLI and `generate_cobolcheck_tests()` Python API, powered by `CoverageAnalyzer` + `TestPlanGenerator` + `CobolCheckGenerator`; supports `paragraph`, `branch`, and `boundary` strategies across 18 branch types
- CLI subcommands grew from 7 to 9 (`program-flow`, `generate-tests`)
- `docs/analysis.md` — comprehensive reference for every analyzer
- Test suite expanded to 3,456 tests across `unit/`, `integration/`, `contract/`, `regression/`, `performance/`

### Fixed

- **DATA DIVISION clause drop in the Cython fast path**: the compiled
  `_data_fast.parse_data_item_clauses_fast` hot path did not handle the
  `SIGN`, `SYNCHRONIZED`/`SYNC`, `JUSTIFIED`/`JUST`, `BLANK WHEN ZERO`, and
  `POINTER` clauses (added to the pure-Python parser later), so when the
  extension was compiled those clauses were silently dropped (e.g.
  `blank_when_zero` stayed `False`). The fast path now mirrors the
  pure-Python branches exactly.

## [1.0.0] - 2026-03-31

### Added

- COBOL parser for Python 3.13+ with full two-stage pipeline: preprocessing → lexing → parsing → AST
- IBM Enterprise COBOL dialect support: COMP-3, EXEC SQL, EXEC CICS, 75+ verbs, IBM intrinsic functions
- Fixed-format and free-form COBOL support with auto-detection; automatic column normalization and comment stripping
- Multi-line string continuation handling with doubled-quote escape sequences
- Statement parsers: CALL, PERFORM, MOVE, DISPLAY, ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE, IF, EVALUATE, OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, COPY, and more
- Embedded SQL/CICS/IMS statement parsing (EXEC blocks)
- FD/SD file description and FILE-CONTROL SELECT parsing (including multi-line ASSIGN, ORGANIZATION, ACCESS clauses)
- Copybook expansion via `expand_copybooks()`
- JSON serialization of all AST nodes with optional source location and metadata
- Error recovery modes: `FAIL_FAST` (default) and `COLLECT_ALL`
- Configurable memory management: 64MB–8GB limits, chunk-based streaming for large files
- `parse_files(paths)` for parallel multi-file batch parsing using multiprocessing
- `ParseResult` with AST, errors, warnings, and `ParseStatistics` (timings, counts, peak memory)
- Plugin architecture (`cobolparser/plugins/core.py`) for memory config, dialect, and serialization config
- `ASTNodeFactory` for validated, consistent AST node construction
- `StatementParserRegistry` for dynamic statement parser dispatch
- `DynamicCallAnalyzer` — tracks possible values of variables used in dynamic `CALL` statements
- IO coverage reporter and CLI (`python -m cobolparser.cli.coverage`)
- 2,975 unit, integration, and contract tests; 81%+ line coverage enforced

### Design

- All AST nodes extend `ASTNode` with mandatory `to_dict()` for JSON serialization
- `TokenStream` wraps `List[Token]` with `peek()`, `consume()`, `expect()`
- Division parsers (`IdentificationDivisionParser`, `DataDivisionParser`, `ProcedureDivisionParser`, etc.) are each independently testable
- Statement parsers live in `cobolparser/parsers/statements/`, one file per verb or verb group
- Proprietary license — copyright © 2026 Samuel Dion, all rights reserved
