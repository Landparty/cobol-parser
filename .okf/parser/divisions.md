---
type: Module
title: Division parsers
description: The IDENTIFICATION / ENVIRONMENT / DATA / PROCEDURE division parsers in cobolparser/parsers/divisions/ and their collaborators -- SELECT and SPECIAL-NAMES, data-item clauses (PICTURE/VALUE/USAGE/OCCURS/...), FD/SD/RD entries, level-88/66, the _data_fast callback contract, and the PROCEDURE DIVISION dispatch loop, paragraph boundaries and unsupported-verb recovery.
tags: [parser, division, data-division, procedure-division, select, occurs, picture]
timestamp: 2026-10-15T00:00:00Z
---

# Division parsers

`cobolparser/parsers/divisions/` holds one parser per COBOL division, created by
`DivisionParserFactory` and driven by `CobolParser.parse_program()` (see
[orchestration.md](orchestration.md)). Each extends `BaseDivisionParser`; the big
ones delegate to collaborator modules (`environment_*.py`, `data_*.py`,
`procedure_*.py`). Start with the [file table](#files); data-item clause rules are
under [DATA DIVISION](#data-division), the paragraph/section loop and
unsupported-verb recovery under [PROCEDURE DIVISION](#procedure-division).
Individual statement parsers are in [statements.md](statements.md).

## Contents

- [Files](#files)
- [Shared division behaviour](#shared-division-behaviour)
- [IDENTIFICATION DIVISION](#identification-division)
- [ENVIRONMENT DIVISION](#environment-division)
- [DATA DIVISION](#data-division)
- [The `_data_fast` contract](#the-_data_fast-contract)
- [PROCEDURE DIVISION](#procedure-division)
- [See also](#see-also)

## Files

| File | Division |
|------|---------|
| `factory.py` | `DivisionParserFactory`, `DivisionType` enum (IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE) |
| `base.py` | Base division parser with error recovery |
| `identification.py` | IDENTIFICATION DIVISION |
| `environment.py` | ENVIRONMENT DIVISION — division scan + AST node; section/SELECT parsing delegated to the two `environment_*.py` collaborators below |
| `environment_sections.py` | `ConfigurationSectionParser` (CONFIGURATION SECTION + SPECIAL-NAMES) and `InputOutputSectionParser` (INPUT-OUTPUT SECTION + FILE-CONTROL) |
| `environment_select.py` | `SelectClauseParser` — SELECT statement + all clause parsers (ASSIGN/ORGANIZATION/ACCESS/KEY/STATUS/ALTERNATE/PADDING/RESERVE/SHARING/LOCK/PASSWORD) and `SelectStatement` node construction |
| `data.py` | DATA DIVISION — section scan, level-number hierarchy, AST node; entry parsing delegated to the three `data_*.py` collaborators below. `_build_data_hierarchy` ends with `propagate_group_usage_and_sign()`: a group's USAGE / SIGN is pushed onto subordinates with none of their own (IBM rule). Explicitness is `CobolDataItem.usage_explicit`, set by `set_usage()` — which both the pure-Python and `_data_fast` clause loops call |
| `data_clauses.py` | `DataItemClauseParser` — data-item entries + PICTURE/VALUE/USAGE/OCCURS/... clauses; owns the optional `_data_fast` Cython fast-path invocation |
| `data_file_description.py` | `FileDescriptionClauseParser` — FD/SD file-description clause capture (BLOCK/RECORD/LABEL/...) |
| `data_report_description.py` | `ReportDescriptionClauseParser` — REPORT SECTION `RD` clause capture (CODE/CONTROLS/PAGE LIMIT/HEADING/FIRST-LAST DETAIL/FOOTING/GLOBAL) |
| `data_special_entries.py` | `SpecialEntryParser` — level-88 condition names, level-66 RENAMES, data-division EXEC SQL blocks |
| `procedure.py` | PROCEDURE DIVISION — paragraph/section dispatch loop, ParseContext attachment, AST node; hosts the shared `StatementParserRegistry` cache; supporting logic delegated to the three `procedure_*.py` collaborators below |
| `procedure_registry.py` | `create_statement_registry()` — registers all 72 statement parsers in first-match priority order (new statement parsers register here); order invariant pinned by `tests/unit/test_procedure_registry_dispatch_order.py`; every registered parser also needs a fixture in `tests/regression/test_swallow_sweep.py` |
| `procedure_boundaries.py` | `is_paragraph_or_section_start` / `is_section_marker` / `is_statement_keyword` lookahead predicates |
| `procedure_recovery.py` | `StatementRecoveryHandler` — unsupported-statement warnings, FAIL_FAST/COLLECT_ALL error recording, stream resynchronization; owns `STRAY_MARKERS` / `UNSUPPORTED_VERBS` (aliased as `ProcedureDivisionParser._STRAY_MARKERS` / `._UNSUPPORTED_VERBS`) |

## Shared division behaviour

- **Warnings.** `BaseDivisionParser.host` is set by the division loop
  (`parser.py`), so every division parser can reach the host warning channel.
  The DATA clause loop's fallback emits "Unparsed token ... in data item" for any
  meaningful token it drops (NEWLINE / WHITESPACE / COMMENT / CONTINUATION are
  skipped silently), symmetric with the ENVIRONMENT parser's
  `_warn_dropped_select_token`.
- **Container locations.** Each `CobolSection` / `CobolParagraph` carries the
  location of its *own* header token, never the division's `start_location`:
  `environment.py`'s `_parse_configuration_section`,
  `_parse_input_output_section` and `_parse_file_control_paragraph` capture
  `token_stream.peek(0)` before consuming their keyword and return it as
  `"location"` (FILE-CONTROL's as `"file_control_location"` inside the
  INPUT-OUTPUT dict); `data.py`'s `_parse_section` does the same;
  `procedure.py` reads `section_info.get("location", start_location)`.
  `_create_ast_node` reads each per-section location. Pinned by
  `tests/regression/test_section_location_tracking.py`.
- **`PROCEDURE DIVISION USING` / `RETURNING`.** `BaseDivisionParser.parse()`
  walks the header clause tokens to the period: bare parameter names go to
  metadata `using_parameters` (what makes the entry interface visible to
  `LinkageChecker`), and `using_parameter_modes: dict[str, str]` (name upper ->
  `"VALUE"` / `"REFERENCE"`) tracks a mode that starts at `"REFERENCE"` and flips
  on each `VALUE` / `REFERENCE` keyword (`BY` is a pure connector), carrying
  forward: `USING BY REFERENCE LK-A BY VALUE LK-B LK-C` -> `{"LK-A":
  "REFERENCE", "LK-B": "VALUE", "LK-C": "VALUE"}` (backs `LinkageChecker`'s
  `PASSING_MODE_MISMATCH`, see [analysis.md](../analysis.md)). `RETURNING x` is
  recorded as metadata `returning_parameter`, not as a USING parameter.
- **OO unit markers.** Every division loop stops at the OO unit markers
  `CobolParser` handles (see [orchestration.md](orchestration.md)): the
  identification loop (`_at_oo_unit_start`), the ENVIRONMENT loop and
  `ConfigurationSectionParser._at_stop` (a class's REPOSITORY paragraph is the
  last thing before `FACTORY.`), and `ProcedureDivisionParser` (a factory's or
  object's PROCEDURE DIVISION is usually empty and followed by `METHOD-ID`;
  `END METHOD` etc. are in `_OO_UNIT_END_WORDS`).
- **Layout between keywords.** A lookahead for the *next word* must step over
  NEWLINE tokens (`_skip_newlines`, `peek_past_noise`); a bare `peek(1)` sees the
  line break and silently changes the parse. Division-level sites that rely on
  this: 88/66 names, `VALUES ARE`, FD/SD/RD names, EXEC SQL in the DATA
  DIVISION, `END DECLARATIVES`, every SPECIAL-NAMES word lookahead (`_word(n)`
  counts meaningful tokens), `OBJECT REFERENCE`. Pinned by
  `tests/regression/test_keyword_line_breaks.py` (each case parsed joined and
  broken; ASTs must be identical).

## IDENTIFICATION DIVISION

- **Comment-entries verbatim.** `_parse_clause_value` first takes the
  consecutive `COMMENT_ENTRY` tokens the lexer emits (see
  [lexer.md](../lexer.md)), joins the lines with one space and drops only the
  entry's own closing period (`AUTHOR. J. SMITH, O'NEIL.` ->
  `"J. SMITH, O'NEIL"`). An unterminated entry from a paragraph name that is not
  in Area A falls through to the token-collection loop, so the loosely indented
  `AUTHOR. SOMEONE` / `DATA DIVISION.` shape still ends at the division header.
  Hand-built token lists (no `COMMENT_ENTRY`) use the token loop.
- **PROGRAM-ID.** `_parse_program_id` consumes `[IS] INITIAL | COMMON |
  RECURSIVE` (repeatable) and the optional trailing word `PROGRAM`; the period
  after the `PROGRAM-ID` keyword is optional (IBM). Attributes land in
  identification metadata `program_attributes` and on
  `CobolProgram.program_attributes` / `is_recursive`.
- **CLASS-ID / METHOD-ID.** `CLASS-ID[.] name [INHERITS [FROM] name]` and
  `METHOD-ID[.] name` are accepted in the PROGRAM-ID position (metadata
  `unit_kind` = `"CLASS"` / `"METHOD"`, `inherits`; `program_id` carries the
  class/method name so the "mandatory" check and the program-name plumbing are
  unchanged). `parse_class_id_clause` / `parse_method_id_clause` are static so
  `CobolParser._handle_oo_unit_marker` can reuse them for header-less units.

## ENVIRONMENT DIVISION

### SELECT (`environment_select.py`)

- Captures ALTERNATE RECORD KEY (repeatable, WITH DUPLICATES), PADDING
  CHARACTER, RESERVE n AREAS, SHARING WITH, LOCK MODE (LOCK ON / WITH ROLLBACK),
  PASSWORD, RECORD DELIMITER (disambiguated from RECORD KEY), and a second FILE
  STATUS (VSAM) variable, onto the existing `SelectStatement` fields.
  `assign_device_type` is populated for device words and IBM `UT-` / `UR-` /
  `DA-` prefixed names. An unknown SELECT clause token produces an
  "Unparsed token ... in SELECT" warning, never a silent `consume()`.
- **ASSIGN stops at `_SELECT_CLAUSE_KEYWORDS`.** Otherwise it swallows following
  clauses into `assign_to`. The set includes `STATUS` (the FILE of `FILE STATUS`
  is optional in IBM: a bare `STATUS [IS] x [y]` starts the same clause),
  `SEQUENTIAL` and `INDEXED` (`ORGANIZATION IS` is optional: a bare `INDEXED` /
  `SEQUENTIAL` is the organization, not more ASSIGN text); `LINE SEQUENTIAL`
  ends ASSIGN by lookahead, and `RELATIVE` is the key clause only when `KEY`
  follows (`_next_word`).
- `ASSIGN USING data-name` (dynamic file name) stores the data-name in
  `assign_to` *and* `SelectStatement.assign_using`, which
  `UnusedVariableAnalyzer._file_control_references` counts as a use.
- `RECORD KEY IS K6 OF R6` / `ALTERNATE RECORD KEY IS A6 IN R6`:
  `_consume_qualifiers` reads the `OF` / `IN` chain into
  `record_key_qualifiers` / the alternate key's `qualifiers` (innermost first);
  the key stays the bare name, and a following `WITH DUPLICATES` is still seen.
- The ORGANIZATION / ACCESS / RECORD KEY / RELATIVE KEY / FILE STATUS
  sub-parsers skip line breaks between their own words (`_try_consume_word`).
- **Separators.** A separator comma / semicolon is skipped (`_is_separator`)
  inside the ASSIGN collector, and `_skip_select_separators` skips one before
  the second (VSAM) FILE STATUS variable. Keeping it gave `assign_to ==
  "INDD ,"` (the lineage DD port read `file:,`) and took `,` as
  `file_status_vsam`.
- Tests: `tests/regression/test_select_optional_organization_word.py`,
  `tests/unit/test_environment_division_parser.py`.

### SPECIAL-NAMES (`environment_sections.py`)

- IBM writes SPECIAL-NAMES as *one sentence* with a single closing period, so a
  clause ends where the next one starts: every operand collection stops at
  `_at_clause_start()` (a clause word in `_SPECIAL_NAMES_CLAUSES`, a `name IS` /
  `name ON|OFF STATUS` mnemonic start, a period), and the paragraph ends at any
  CONFIGURATION SECTION paragraph header (`_CONFIGURATION_PARAGRAPHS`) -- a
  following `REPOSITORY.` paragraph's `CLASS X IS 'java.X'` entries are not
  SPECIAL-NAMES class conditions.
- **Mnemonic names.** `implementor-name IS mnemonic-name [ON STATUS IS cond]
  [OFF STATUS IS cond]` is collected into `special_names["mnemonic_definitions"]`
  as `{"environment_name": "C01", "mnemonic_name": "TOP-OF-PAGE"}` (plus
  `on_status` / `off_status` for the UPSI switch form; the name-less
  `UPSI-0 ON STATUS IS x` form is accepted). `IS` may be omitted only after a
  known IBM environment-name (`_ENVIRONMENT_NAMES`: C01-C12, CSP, S01-S05,
  SYSIN/SYSIPT, SYSOUT/SYSLIST/SYSLST, SYSPUNCH/SYSPCH, CONSOLE, UPSI-0..7,
  AFP-5A) -- otherwise an entry's start cannot be told from an operand;
  `UPSI-0 ON x` without STATUS/IS likewise.
- Other metadata: `symbolic_characters` (`[{name, ordinal, alphabet}]`; IS/ARE
  optional -- the first integer ends a group's names), `currency_signs`
  (`[{sign, picture_symbol}]`, every CURRENCY clause; `currency_sign` keeps its
  last-wins value). `CLASS` / `ALPHABET ... FOR ALPHANUMERIC|NATIONAL` is
  accepted. Separator `,` / `;` (`TokenType.COMMA` / `SEMICOLON`) are in
  `_NOISE_TYPES` and skipped by `_skip_noise()`: `CLASS VOWEL IS 'A', 'E'` ->
  `ranges == ["A", "E"]`; `SYMBOLIC CHARACTERS NUL, SOH ARE 1, 2` keeps both names.
- `DECIMAL-POINT IS COMMA` is honoured (comma-decimal literals, `,`/`.`
  exchanged in PICTURE -- see [lexer.md](../lexer.md)); no warning.
- Tests: `tests/regression/test_special_names_clause_boundaries.py`,
  `tests/unit/test_special_names.py`,
  `tests/regression/test_optional_keyword_forms.py`.

## DATA DIVISION

### Sections

`DataDivisionParser` parses FILE, WORKING-STORAGE, LOCAL-STORAGE, LINKAGE and
REPORT as real sections. SCREEN SECTION and COMMUNICATION SECTION have grammars
that are not modeled; their headers are still section *boundaries*
(`_SECTION_BREAK_HEADERS` / `_UNSUPPORTED_SECTION_HEADERS` in `parse_division`'s
dispatch and `_parse_section`'s break check), so a WORKING-STORAGE scan stops
there instead of absorbing the header and misparsing the following content as
nested data items (a SCREEN `COLUMN 5` clause became a `CobolDataItem` named
`COLUMN`). `_skip_section()` consumes the header (`NAME [SECTION] [.]`), discards
the body up to the next section/division boundary, registers an empty
`CobolSection` (`SCREEN` / `COMMUNICATION`) plus a `has_screen` /
`has_communication` division-metadata flag, and records a warning naming the
section. Known tradeoff: a data item inside or directly after such a section
with no section header of its own (a CD's record, a bare `01`) is discarded with
the body -- the warning is what keeps that from being silent.

`REPORT`, `SCREEN` and `COMMUNICATION` double as ordinary clause words (an FD's
`REPORT IS report-name.`, `examples/cobol/shamrice/report_test.cbl`).
`parse_division` routes to `_parse_section("REPORT")` / `_skip_section` only when
the *next* token is literally `SECTION` (`_next_is_section_keyword`); otherwise
the bare word falls through to the unknown-token skip, so it cannot discard the
source after it. Pinned by
`tests/regression/test_screen_report_communication_sections.py`.

### FD / SD entries

- While scanning under an `FD` / `SD` header, every level-01 item is tagged with
  `fd_file_name`, `fd_clauses` (the `FileDescriptionClauseParser` dict --
  `record`, `recording_mode`, `label_records`, `data_records`, ...) when present,
  and `fd_record_type` (`"FD"` or `"SD"`), which `ProgramLayoutIndex`
  ([generators.md](../generators.md)) uses to treat SORT/MERGE work files as
  non-mockable. Pinned by
  `tests/unit/test_program_layout_index.py::TestFdRecordTypeMetadata`.
- **The second RECORD word.** `RECORD` is both a clause start (RECORD CONTAINS /
  VARYING) and the second word of `LABEL RECORD(S)` / `DATA RECORD(S)`.
  `parse_fd_clauses` treats it as that second word only while the LABEL/DATA
  clause has captured nothing yet; any later `RECORD` starts its own clause, so
  `LABEL RECORDS ARE STANDARD RECORD CONTAINS 30` keeps the record length.
  Pinned by `tests/regression/test_fd_record_after_label_data.py` (#401).

### REPORT SECTION

Parsed for real and warning-free (`data.py` + `data_report_description.py` +
`data_clauses.py`), so a Report Writer program is not refused by warning-gated
consumers. Inside `_parse_section("REPORT")`, an `RD report-name` entry is
consumed and `ReportDescriptionClauseParser.parse_rd_clauses` captures `CODE`,
`CONTROL(S) [ARE] {FINAL | name ...}`, `PAGE [LIMIT] n [LINES]`, `HEADING n`,
`FIRST DETAIL n`, `LAST DETAIL n`, `FOOTING n`, `GLOBAL` into
`{"code", "controls", "page_limit", "heading", "first_detail", "last_detail",
"footing", "is_global", "raw"}` (unclaimed tokens go to `raw`). Every following
01-level report group carries that mapping as `metadata["rd_clauses"]` and the
report name as `metadata["rd_report_name"]`. `parse_rd_clauses` stops at a
LEVEL_NUMBER that begins a group (`_level_starts_group`) so a missing RD period
cannot swallow the first group.

Report groups are ordinary `CobolDataItem` trees parsed by
`DataItemClauseParser.parse_data_item(..., report_group=True)`: an entry whose
level is followed by a clause word (`01 TYPE IS PAGE HEADING.`, `05 LINE NUMBER
IS 1.`, `10 COLUMN 1 PIC X(20)`) is anonymous (`ANONYMOUS-<level>-<line>`), and
the report-group clauses -- `TYPE [IS] ...`, `LINE [NUMBER] [IS] {n | PLUS n |
NEXT PAGE}...`, `NEXT GROUP [IS] ...`, `COLUMN|COL [NUMBER] [IS] n...`,
`SOURCE [IS] id`, `SUM id... [UPON id...] [RESET [ON] {id | FINAL}]`, `GROUP
[INDICATE]`, `PRESENT WHEN cond` -- land in `metadata["report_clauses"]`
(`type`, `line` (list), `next_group`, `column` (list), `source`, `sum` (list of
`{operands, upon?, reset_on?}`), `group_indicate`, `present_when`). PICTURE /
VALUE / JUSTIFIED / BLANK WHEN ZERO / USAGE use the ordinary clause branches.

- The report clause words are in `_PICTURE_TERMINATOR_KEYWORDS` so `PIC ZZ9
  SOURCE WS-X` stops the picture at `SOURCE` (none is a valid picture string).
  The fast path bails back to the pure-Python loop on every report clause word,
  so `_parse_report_clause` is the single implementation.
- `NEXT` is position-shaped only when followed by `PAGE` (`_report_position`):
  `LINE PLUS 1 NEXT GROUP NEXT PAGE` must not fold `NEXT GROUP` into the LINE
  list. COBOL-85 `LINE integer ON NEXT PAGE` is recorded as `"5 ON NEXT PAGE"`.
- `_report_operands` stops at a LEVEL_NUMBER token only outside parentheses and
  not after an operator word (`_REPORT_OPERATOR_WORDS`): a one-/two-digit integer
  lexes as LEVEL_NUMBER whatever it means, so `SUM WS-AMT (1)` and `PRESENT WHEN
  WS-I > 1` must not end the clause and open a phantom item. String literals in
  operands are re-quoted (`PRESENT WHEN WS-FLAG = 'Y'`), and SUM operands are
  grouped per operand (`_group_report_operands`: `WS-AMT OF WS-GRP ( 3 )` is one
  entry).
- Pinned by `tests/unit/test_report_section.py`,
  `tests/regression/test_oo_report_xml_operand_drops.py`; `tests/samples/report_writer.cbl`
  is in `test_sample_programs.py`'s list.

### Data-item clauses (`data_clauses.py`)

**LEVEL_NUMBER-as-literal gotcha (`data.py`):** the lexer types every 1-2
digit integer as `TokenType.LEVEL_NUMBER` regardless of context (even inside
`PIC 9(4)` or after `VALUE`). Any data-division clause that consumes a numeric
must therefore accept `LEVEL_NUMBER` alongside `NUMERIC_LITERAL` —
`_parse_value_clause`, the level-88 value collector, and the OCCURS handlers
all do. `_parse_value_clause` also consumes an optional `IS` and a
`MINUS`/`PLUS` sign token before the literal (`VALUE IS -5`). Regression
suite: `tests/regression/test_numeric_value_clause.py`.

**Multi-line clauses (`data_clauses.py` + `_data_fast.pyx`):** the lexer
emits NEWLINE tokens, so any clause reader that peeks for an operand after
consuming a keyword must skip NEWLINEs first or a line break between keyword
and operand silently drops the operand. REDEFINES does this via
`_skip_newlines` (pure Python) and an inline newline-skip loop (Cython) —
the same pattern the OCCURS sub-clauses (TIMES/DEPENDING/KEY/INDEXED) use.
Remember both implementations must change together, and the checked-in
`_data_fast.c` must be regenerated (Cython 3.2.4). Regression cases:
`tests/unit/test_data_division_branches.py::TestRedefinesClause`
(multi-line + forced pure-Python-loop variants).

**PICTURE.**
- The pattern loop collects symbol tokens including `DIVIDE_OP` / `MULTIPLY_OP`
  (what `/` and `*` lex to) -- not the `DIVIDE` / `MULTIPLY` *statement* token
  types, which would stop `PIC 99/99/99` at `"99"` and `PIC $***,**9.99` at `"$"`
  and spawn phantom level-99 items.
- It stops at `_PICTURE_TERMINATOR_KEYWORDS` (report clause words, `VOLATILE`,
  `BYTE-LENGTH`, `DYNAMIC`, `OBJECT`, `NATIONAL`, `UTF-8`, ...; the Cython path
  receives the same frozenset) and at a word that sits on the pattern's line
  *after a gap* (`_follows_gap`, column arithmetic on the previous pattern
  token): a character-string has no embedded spaces, so `PIC X(3) VALUES ARE
  'ABC'` / `PIC X(3) FOO` must not become `X(3)VALUES` / `X(3)FOO`. The stray
  word then surfaces as the clause loop's "Unparsed token" warning. A pattern
  continued on the next line is unaffected (the line break resets the previous
  token).
- **Missing terminating period.** A NEWLINE inside the pattern means "more
  pattern may follow" (`PIC 9\n99.` is legal), so the loop looks past the
  newline for a LEVEL_NUMBER that cannot be PICTURE content: (a) its value has a
  digit other than `0` / `9` (the only digit-shaped PICTURE symbols -- the `5` of
  `05`), or (b) it is immediately followed by an `IDENTIFIER` (a named or
  `FILLER` item). Either signal stops the clause there and records a warning via
  `host.add_warning`. Signal (a) is what catches an anonymous next item (`05
  REDEFINES ...`). Without the guard the next item (and its children) silently
  merged into the previous pattern (`"9(08)05bariable"`). The common trigger is
  a period in column 73+ cut off by fixed-format extraction -- a hard compile
  error in GnuCOBOL too, so the column-8-72 extraction is right and the warning
  is the fix. The `_data_fast` path calls back into this Python method, so both
  builds behave the same. Pinned by
  `tests/regression/test_picture_clause_missing_terminator.py`.
- Sizing (`models/data_items.py::PictureClause`): `N` / `N(n)` counts one
  position per `N` (no DBCS byte-doubling); `U` (`_PIC_UTF8_RE`) is one byte per
  symbol. See [ast-models.md](../ast-models.md).

**VALUE.**

**VALUE ALL (`data_clauses.py`):** `ALL` lexes as a `FIGURATIVE_CONSTANT`, so
`parse_value_clause` special-cases it before the plain-literal branch:
`VALUE ALL '='` → `value_clause='ALL "="'`, `VALUE ALL ZEROS` →
`'ALL ZEROS'` (a bare trailing `ALL` still returns `"ALL"`). The returned
string round-trips as legal COBOL — downstream consumers (mockymock's
working-storage reset) splice it into `MOVE <value> TO <item>`. Regression
suite: `tests/regression/test_value_all_clause.py`.

- Both the plain and the `VALUE ALL` branch render a STRING_LITERAL through
  `data_clauses.literal_source()`: `raw_value` for a typed literal (`X"..."`,
  `Z"..."`, `N"..."`, ...; `VALUE X"4142"` stays `X"4142"`) and
  `_literals.quote_literal(value)` otherwise (doubling an embedded delimiter, see
  [statements.md](statements.md)). The `_data_fast` path delegates VALUE to this
  helper.

**USAGE.**
- `USAGE` consumes an optional `IS` before the usage word (`USAGE IS NATIONAL`
  / `INDEX` / `DISPLAY-1`); `DISPLAY-1` lexes as its own `TokenType`, which the
  keyword set must include.
- USAGE and IS are both optional: bare `INDEX` (`05 X INDEX.`; INDEX is
  reserved, so it can never be a data-name) and the bare words in
  `_BARE_USAGE_WORDS` (`NATIONAL` / `DISPLAY-1` / `UTF-8`, with or without a
  leading `IS`) are the item's usage. `NATIONAL` / `UTF-8` lex as IDENTIFIERs,
  hence their place in `_PICTURE_TERMINATOR_KEYWORDS` (`PIC N(5) NATIONAL`).
- `GROUP-USAGE [IS] NATIONAL | UTF-8` sets `CobolDataItem.group_usage`;
  `propagate_group_usage_and_sign` relabels the group and pushes the usage onto
  subordinates without a USAGE of their own.
- `[USAGE] [IS] OBJECT REFERENCE [[FACTORY OF] class]` (`_at_object_reference`,
  `_parse_object_reference`).

**OCCURS (`_parse_occurs_clause`, mirrored in `_data_fast.pyx`).**
- Parses `{ASCENDING|DESCENDING} KEY [IS] k1 [k2 ...]` (repeatable) *before*
  `INDEXED BY`, and `INDEXED BY` collects every index name
  (`OccursClause.key_clauses` / `index_names`, see
  [ast-models.md](../ast-models.md)). Commas in both name lists are separators;
  the `.pyx` compares the COMMA token *type* (`comma_type` parameter), never the
  value `","`, which a `','` literal would match. Qualified KEY names (`KEY IS K1
  OF T`) keep the bare name.
- Line splits: NEWLINEs are skipped before the count, before `TO`, before the
  max, between `INDEXED` and `BY`, and before `ON` and the variable of
  `DEPENDING ON` (the variable must be an IDENTIFIER, so crossing a line can
  never swallow a level number).
- **Count guard** (`_peek_count_token` / `_peek_count_pos` in `.pyx`): a
  NUMERIC_LITERAL is always the count; a LEVEL_NUMBER on the same line is the
  count; a LEVEL_NUMBER reached only by crossing a line break counts only when
  the token after it continues the OCCURS clause
  (TIMES/TO/DEPENDING/INDEXED/ASCENDING/DESCENDING/PIC). Otherwise a malformed
  `OCCURS` with no count would take the next item's level number as the table
  size and delete that item. Applies to the first count and the `TO` max.
- `DEPENDING ON CNT OF CTL [IN ...]`: `_consume_qualifiers` (pure and Cython)
  reads the chain into `OccursClause.depending_on_qualifiers`; `depending_on`
  stays the bare name (generators match counters by bare name).
- `OCCURS UNBOUNDED DEPENDING ON` (peeked with `_peek_next_meaningful(offset=0)`
  so the count guard keeps working; `min_times` 1, `max_times` None,
  `OccursClause.is_unbounded`) and `OCCURS n TO UNBOUNDED [TIMES] DEPENDING ON`
  (Enterprise COBOL 6.x, #402: `UNBOUNDED` is the maximum, `min_times` n).

**Other clauses.**
- `[IS] EXTERNAL` / `[IS] GLOBAL`: the `IS` comes *before* the keyword, so the
  dispatch loop has a peek-ahead branch on `TokenType.IS` that consumes it when
  `EXTERNAL` / `GLOBAL` (or `INDEX`, a bare usage word) follows.
  `SYNCHRONIZED IS LEFT` / `JUSTIFIED IS RIGHT` consume the `IS` after the
  keyword, like `SIGN`. Pinned by `tests/regression/test_parser_completeness.py`.
- `SIGN [IS] LEADING|TRAILING [SEPARATE]`: the direction must be LEADING or
  TRAILING, with newline skips between the clause's words (a bare truthiness
  check recorded `"\n"` as the sign).
- `VOLATILE`, `BYTE-LENGTH n`, `DYNAMIC LENGTH [LIMIT [IS] n]`
  (`_consume_integer`), `BASED` (`metadata["based"]`).

### Level-88 and level-66 (`data_special_entries.py`)

- Level-88 values are stored undelimited (`item.add_value(t.value)`) -- not
  COBOL source text, unlike VALUE clauses. `VALUE ALL 'X'` is one value spelled
  `'ALL "X"'` (`ALL SPACES` for a figurative operand), not `['ALL', 'X']`;
  consumers that know the field's width expand it (`expand_condition_values(raw,
  width)` in [generators.md](../generators.md)). Pinned by
  `tests/regression/test_level88_value_all.py`.
- A semicolon separates values exactly as a comma does (`VALUES 'A', 'B'; 'C'`
  -> `['A', 'B', 'C']`; ranges survive). Pinned by
  `tests/regression/test_level_88_semicolon_separator.py`.
- `88 name VALUE ... WHEN SET TO FALSE [IS] literal` (IBM):
  `_parse_when_set_to_false` accepts `WHEN [SET] [TO] FALSE [IS]` + a (signed)
  literal or figurative constant into `ConditionNameItem.false_value`; anything
  else after `WHEN` is skipped to the period. Pinned by
  `tests/regression/test_level88_false_and_initialize_phrases.py`.

### EXEC SQL in the DATA DIVISION

`data.py::_parse_exec_sql_in_data` reads the block with `collect_exec_sql_text`
but attaches no parse context, so a missing `END-EXEC` there is not reported (the
PROCEDURE DIVISION caller reports it -- see [statements-io.md](statements-io.md)).

## The `_data_fast` contract

- **Callback surface.** `DataDivisionParser` keeps `_parse_picture_clause` /
  `_parse_value_clause` / `_parse_usage_clause` (and `_parse_data_item`) as
  delegating wrappers with their historical names and signatures — the compiled
  `_data_fast` extension receives the division parser as `parser_self` and calls
  those three back by name. New clause logic goes in `DataItemClauseParser`; the
  wrappers must stay.
- **Arity guard.** The other half of the contract is the 20-argument positional
  call (`_DATA_FAST_ARG_COUNT = 20`) `parse_data_item` makes into
  `parse_data_item_clauses_fast`. A stale *build* (in-place `.so` older than the
  tree, cached `build/`, an installed wheel shadowing the source) still imports
  fine, then raises `TypeError` in every data-description entry, which the broad
  `except Exception` in `parser.py` turns into the loss of the DATA *and*
  PROCEDURE divisions. `_data_fast_usable()` probes the helper once at import
  (empty token list -> it returns `pos` untouched) and, on mismatch, sets
  `_HAS_DATA_FAST = False` and names the rebuild via `logger.warning` (never
  `warnings.warn` — at import time that breaks `import cobolparser` under
  `-W error`). **Adding a parameter to `parse_data_item_clauses_fast` means
  updating `_DATA_FAST_ARG_COUNT` alongside the call site.** Full mechanics in
  [lexer.md](../lexer.md) ("Signature-drift guard");
  `tests/regression/test_data_fast_signature_drift.py`.
- **Opt-in only.** The extension is looked for only under `COBOLPARSER_ACCEL=1`
  ([orchestration.md](orchestration.md)), so the probe and its warning run only
  then. The drift tests reload `data_clauses` with the variable set
  (`_accel_opted_in()`), and `test_extension_is_ignored_without_the_opt_in` pins
  that a default import never touches the binary.
- **Both loops change together.** A clause rule implemented in both the pure
  loop and `_data_fast.pyx` must change in both, with the checked-in `.c`
  regenerated. The Cython loop hands unknown clauses, report clause words, bare
  usage words, `SIGN`, `OCCURS UNBOUNDED` / `n TO UNBOUNDED`, and `USAGE [IS]
  OBJECT` back to the pure-Python loop, which is the single implementation for
  them. The CI coverage job runs pure Python only; a fast-path-only bug shows up
  only in the extension-built matrix.

## PROCEDURE DIVISION

### Dispatch loop (`procedure.py`)

- Each token is either a paragraph/section header
  (`procedure_boundaries.is_paragraph_or_section_start`), a statement (the
  registry finds a parser), or recovery (`procedure_recovery.py`).
- An EOF token ends the loop explicitly. The "unknown token -> new paragraph
  name" fallback must never see EOF (its value is `""`), or every program gains a
  phantom empty trailing paragraph.
- **Phantom-paragraph fingerprint.** A bogus zero-statement paragraph named `.`
  or `""` at the end of the AST (`procedure_count` one too high) means some
  parser left a period or EOF unconsumed; `STOP`, `DISPLAY ... UPON` and the EOF
  check above have each been a cause.
- **DECLARATIVES.** `DECLARATIVES.` and `END DECLARATIVES.` are consumed as
  markers (no pseudo-paragraphs), and every section opened in between is flagged:
  section dict key `declarative` -> `CobolSection` metadata `declarative` /
  property `is_declarative`.
- `_collect_known_data_names` computes the DATA DIVISION name set once per
  parse and threads it to statement parsers via `ParseContext.known_data_names`
  (used by the H9 paragraph-boundary check in [statements.md](statements.md)).

### Paragraph and section boundaries (`procedure_boundaries.py`)

- `is_paragraph_or_section_start` accepts all-digit procedure names (`1000.`),
  which lex as `NUMERIC_LITERAL` / `LEVEL_NUMBER`, via its own
  `_is_procedure_name_token` (works on `token.type.name` strings, unlike the
  statement-level `_utils.is_procedure_name_token`).
- `is_section_marker` treats a token followed by `SECTION` as a section header
  -- except `EXIT` (reserved), so `EXIT SECTION.` right after a section header is
  a statement, not an empty section that swallows the paragraphs after it (#382).
- An unreserved verb word with no `TokenType` followed by a period
  (`FREE.` / `ALLOCATE.`) is resolved in favour of the statement reading
  (`is_statement_keyword` consults `STATEMENT_KEYWORDS`); the statement parser
  then reports the missing operand, so the parse is flagged rather than silent.
  Verbs with a dedicated `TokenType` (`EJECT`, `SKIP1-3`) can never be read as
  paragraph names.

### Unsupported verbs and recovery (`procedure_recovery.py`)

- Every COBOL verb has a registered parser. `UNSUPPORTED_VERBS` (the
  warn-and-discard path) holds only `EXECUTE`, `GOTO`, `RECOVER` -- verb-shaped
  reserved words with no statement behind them in any dialect -- and produces the
  specific "Unsupported statement 'X'" warning; any other unparsed token gets the
  generic "Unparsed tokens starting at 'X' ... content dropped from the AST up to
  the next statement boundary" warning. Either way the tokens are skipped up to
  the next statement boundary in one pass, with one warning per dropped statement.
- `STRAY_MARKERS` lists the control-flow words and scope terminators (`ELSE`,
  `WHEN`, `THEN`, `END-IF`, `END-PERFORM`, ..., `END-RECEIVE`) that may be left
  over at statement level; they are skipped without a warning.
- A verb word must also be in `_utils.STATEMENT_TOKEN_TYPES` /
  `STATEMENT_KEYWORDS`, or a period-less predecessor's operand loop swallows it
  before recovery ever sees it -- see [statements.md](statements.md).

## See also

- [../parser.md](../parser.md) — routing page for the parser files
- [orchestration.md](orchestration.md) — `CobolParser`, the pipeline, multi-unit programs
- [statements.md](statements.md) — statement dispatch, shared helpers, boundary invariants
- [../ast-models.md](../ast-models.md) — `CobolDataItem`, `OccursClause`, `SelectStatement` fields
- [../lexer.md](../lexer.md) — `LEVEL_NUMBER`, `COMMENT_ENTRY`, `_data_fast` drift guard
- [history](../history/parser.md) — archived dated notes behind these rules
