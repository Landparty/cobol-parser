---
type: Module
title: AST Models
description: ASTNode hierarchy — CobolProgram, data items, statement nodes, to_dict()/to_json() serialisation.
tags: [ast, models, cobol-program, data-items, statements]
timestamp: 2026-10-15T00:00:00Z
---

# Overview

`cobolparser/models/` — all AST node classes. Every node extends `ASTNode`
from `ast_base.py` and must implement `to_dict()`. Instantiate nodes via
`ASTNodeFactory` (`core/ast_factory.py`), not directly.

# Base Classes (`models/ast_base.py`)

```python
@dataclass
class SourceLocation:
    line: int
    column: int
    length: int | None = None   # no filename field — file identity travels on ParseResult

class ASTNode:
    location: SourceLocation | None
    def to_dict(self) -> dict: ...
    def to_json(self) -> str: ...
    def find_all_by_type(self, type_name: str) -> list[ASTNode]: ...
    def equals(self, other: object) -> bool: ...

class ASTValidator: ...
```

`ASTNode.equals(other)` (issue #273, 2026-10-05) is true when both nodes have
the same `node_type`, the same tree of child node types (`_shape()`), and the
same `to_dict()` with every nested `location` key removed
(`_comparable_dict()`). Source position never matters, content always does: a
reparse of the same text is equal, a program differing in one PICTURE or one
MOVE literal is not. `CobolProgram._comparable_dict()` serializes with
`include_metadata=False` and adds back only the program's own `_metadata`, so
the derived statistics block (whose `total_lines` comes from locations) does
not take part. Before #273 it compared node types and child counts only, so
any two programs with the same division count were "equal".

# Program Structure (`models/program.py`)

```python
class CobolProgram(ASTNode):
    program_name: str        # the PROGRAM-ID (CLI/JSON reports call it program_id)
    divisions: list[CobolDivision]
    contained_programs: list[CobolProgram]
    unit_kind: str           # "PROGRAM" | "CLASS" | "FACTORY" | "OBJECT" | "METHOD"
    # ...

class CobolDivision(ASTNode):
    name: str
    sections: list[CobolSection]

class CobolSection(ASTNode):
    name: str
    paragraphs: list[CobolParagraph]

class CobolParagraph(ASTNode):
    name: str
    statements: list[CobolStatement]
```

`CobolProgram.to_json()` exports the full tree as JSON for cross-platform
interoperability.

`CobolProgram.from_json()` is **not** its full inverse -- it restores a
structural skeleton (issue #273, 2026-10-05):

* **Restored** (with locations and per-node metadata): program name,
  `unit_kind`, own metadata, contained units (recursively); every division and
  section; every paragraph's name; every data item with all its serialized
  clauses (PICTURE -- fields restored verbatim from the dict, currency /
  DECIMAL-POINT IS COMMA from its metadata --, USAGE, VALUE, OCCURS incl.
  keys / indexes / DEPENDING ON qualifiers, REDEFINES, SIGN, SYNC, JUST, BWZ,
  EXTERNAL/GLOBAL/VOLATILE, BYTE-LENGTH, DYNAMIC LENGTH, OBJECT REFERENCE,
  GROUP-USAGE), subordinate items, level-88 `condition_names` (placed before a
  group's subordinate items, where a group's 88s sit in source) and each
  section's level-66 `renames_items`; every FILE-CONTROL `SelectStatement`
  with all its clauses (organization, access mode, record / alternate /
  relative keys, FILE STATUS, ...) -- a SELECT dict is flat, so
  `_select_from()` rebuilds it whole and `ProgramLayoutIndex.file_facts()` of
  a round-tripped program matches the original (#346, 2026-10-15; SELECTs
  used to be dropped *and* counted as PROCEDURE DIVISION statements in the
  warning).
* **Dropped:** every PROCEDURE DIVISION statement -- there is no generic way to
  rebuild ~100 statement node types from their dicts -- so restored paragraphs
  are empty. Whenever any were dropped, `from_json` emits
  `LossyDeserializationWarning` (a `UserWarning`, exported from
  `cobolparser.models`) naming the program and the statement / paragraph
  counts. Never silent. Anything `to_dict()` never writes (FD/SD entries,
  `usage_explicit` -- inferred as "usage is neither DISPLAY nor what the
  PICTURE implies") cannot come back.
* Verified over 294 corpus programs: `from_json(p.to_json()).to_dict()` equals
  `p.to_dict()` with PROCEDURE DIVISION paragraph `statements` emptied, apart from the derived
  `metadata.statistics`.

Serialization fidelity notes (2026-07-07):

* `CobolProgram.contained_programs` holds additional program units from the
  same compilation unit (stacked/nested programs); serialized as
  `contained_programs` and included in `get_all_statements()`.
* `CobolDataItem.to_dict()` serializes level-88 children as
  `condition_names`; `CobolSection.to_dict()` serializes level-66 children as
  `renames_items`. Both were previously captured in-memory but dropped at the
  JSON boundary.
* `CallStatement.to_dict()` serializes `not_on_exception` (previously
  omitted), and CALL handler statements are registered as AST children so
  `find_all_by_type()` agrees with `get_all_statements()`.
* `CallStatement.using_parameters`' `CallParameter.passing_mode` now
  persists correctly across a comma-separated parameter list within one
  `BY REFERENCE`/`BY CONTENT`/`BY VALUE` group (2026-07-24) — `CALL 'P'
  USING BY CONTENT a, b` previously mode-tagged `b` back to the REFERENCE
  default instead of CONTENT (both parameter names survived; only the
  mode was silently wrong). See [parser.md](parser.md) "Follow-up
  comma-list sweep" targeted round.
* `GoStatement` carries `target_paragraphs` (all computed-GO-TO targets) in
  addition to `target_paragraph` (the first).
* `XmlJsonStatement` (`models/statements/misc.py`) models XML/JSON
  GENERATE/PARSE with `verb`, `action`, `primary_operand`, `from_item`, raw
  `clause_text` (non-handler clauses only since 2026-09-02),
  `processing_procedure` / `processing_procedure_thru` (XML PARSE's implicit
  PERFORM target and THRU end), and `on_exception` / `not_on_exception`
  statement lists (the CALL/ACCEPT handler shape; serialized with
  `omit_empty`). Since 2026-09-28 the clause region's data names are
  structured too: `count_in` (GENERATE's `COUNT [IN]`), `into_item` (JSON
  PARSE's receiving item) and `clause_items` (every `NAME OF` / `TYPE OF` /
  `SUPPRESS` / `CONVERTING` subject and `NAMESPACE` / `NAMESPACE-PREFIX` /
  `VALIDATING WITH` identifier, qualifiers and subscripts folded in), all
  three also reaching `.operands` -- before, they lived only in
  `clause_text`, so unused-variables flagged each and xref saw none. xref
  gives `count_in` / `into_item` role `write`, `clause_items` role `read`.
  `primary_operand` / `from_item` fold a trailing OF/IN chain or subscript.
* REPORT SECTION (2026-09-02): report groups are ordinary `CobolDataItem`
  trees under a `CobolSection("REPORT")`. Each 01-level group carries
  `metadata["rd_report_name"]` and `metadata["rd_clauses"]` (the RD's
  CODE/CONTROLS/PAGE LIMIT/HEADING/FIRST DETAIL/LAST DETAIL/FOOTING/GLOBAL as
  a mapping); every entry carries `metadata["report_clauses"]` for its
  TYPE/LINE/NEXT GROUP/COLUMN/SOURCE/SUM/GROUP INDICATE/PRESENT WHEN
  clauses. Anonymous entries (`01 TYPE IS DETAIL.`) get the existing
  `ANONYMOUS-<level>-<line>` name. See [parser.md](parser.md).
* Implicit FILLER (#404, 2026-10-14): outside a REPORT SECTION group, an
  entry with no data-name (`05 PIC X(3).`, FILLER omitted) keeps the
  synthetic `ANONYMOUS-<level>-<line>` `name` but has `is_filler=True`.
  `CobolDataItem.layout_name` is `"FILLER"` for every filler item and `name`
  otherwise; record layouts (`layout.py`, `layout_offsets.py` /
  `data-items`, `program_layout.py`) name and path items by it, so gen-data
  drops the column and lineage keys it positionally like `05 FILLER`.
  Unnamed report-group entries stay non-filler.
* `IOWriteStatement.advancing_clause` is populated by the WRITE parser
  (`{"type": "AFTER", "value": 2, "unit": "LINES"}`), not just
  `advancing_mode`. `unit` is also `"CHANNEL"` for `ADVANCING PAGE`
  (`value="PAGE"`); `"LINES"` for `ADVANCING identifier LINES` (a
  data-name holding a line count — `value` is the data-name, not an int);
  and `"MNEMONIC"` for a bare SPECIAL-NAMES mnemonic-name target with no
  `LINE`/`LINES` suffix (`value` is the mnemonic-name, e.g.
  `ADVANCING TOP-OF-PAGE` → `{"type": "AFTER", "value": "TOP-OF-PAGE",
  "unit": "MNEMONIC"}`) (2026-07-20).
* `IORewriteStatement.from_clause` (2026-07-09) — the `REWRITE rec FROM data`
  source (previously consumed and discarded). Also added to `operands` via
  `_add_unique_operand`, matching `IOWriteStatement.set_from`, so
  identifier-discovery consumers that read `operands` see it.
* `ReleaseStatement.set_from_source()` / `ReturnStatement.set_into_target()`
  (2026-09-28) now also add the operand to `operands` via
  `_add_unique_operand`, the same as `IOWriteStatement.set_from` /
  `IOReadStatement.set_into`; an item used only as `RELEASE ... FROM x` or
  `RETURN ... INTO x` was otherwise reported unused.
* `IOStartStatement.key_name` (2026-07-09) — the `START f KEY IS ... data-name`
  key (previously discarded; `key_condition` kept only the operator). Also
  tracked in `operands` for the same reason.
* `StopStatement.returning` (2026-07-09) — `STOP RUN RETURNING x` return code
  (previously dropped).
* `ArithmeticStatement.targets: list[str]` (2026-07-22) — full ordered list
  of comma/space-separated `TO`/`FROM` targets (`ADD 1 TO a, b, c`);
  `.target` keeps the first for backward compatibility. `.rounded: bool`
  (also on `ComputeStatement`) and `.is_corresponding: bool` (ADD/SUBTRACT
  `CORRESPONDING`) were previously discarded or misparsed as literal
  operands. `DivideStatement.remainder: str | None` — the `REMAINDER r`
  target (was entirely unimplemented). See [parser.md](parser.md)
  "Statement-Support Verification Sweep (2026-07-22/23)".
  `DivideStatement.division_mode: str | None` (2026-08-12 bug review) —
  `"BY"` or `"INTO"` as the source wrote it, emitted by `to_dict()`; the
  two forms invert dividend/divisor order, so without this no consumer
  could evaluate a DIVIDE from the AST (const_fold poisoned all of them —
  it now folds the unambiguous forms, see [analysis.md](analysis.md)).
* `UnstringStatement.tallying_variable: str | None` (2026-07-22) —
  `TALLYING IN counter`, documented but never implemented; `.delimiters`
  now collects every `OR`-joined delimiter (`DELIMITED BY d1 OR d2`),
  previously only the first survived.
* `IOOpenStatement.file_modes: dict[str, str]` (2026-07-22) — per-file
  open mode keyed by file name, for `OPEN INPUT a OUTPUT b`-style
  statements where `.open_mode` alone (first mode group only) can't
  distinguish `b`'s real mode. `crud_matrix.py`/`io_logger.py` still read
  `.open_mode` alone — not yet updated to consult this map.
* `IOWriteStatement.not_at_eop_clause` (2026-07-22) — `NOT AT
  END-OF-PAGE`; `.at_eop_clause`/`.not_at_eop_clause` (format-1,
  sequential files) are now actually populated by the WRITE parser
  (previously `AT END-OF-PAGE` was entirely unimplemented; only format-2's
  `INVALID KEY`/`NOT INVALID KEY` worked).
* `IOAcceptStatement.environment_name` (2026-07-22) — `ACCEPT x FROM
  ENVIRONMENT "name"`'s variable name; the field existed but the parser
  never called its setter.
* `PictureClause` sizes `PIC N(n)` (national) and `PIC G(n)` (DBCS) at
  **2 bytes per character** (2026-09-09; the 2026-07-22 fix had counted one
  byte per `N`, and `G` fell through to size 1). `size` is a byte count —
  it is what `calculate_size()`, `data-items` offsets and record images are
  built from. P-scaled pictures (`9(3)PPP`, `SVPP9(3)`) are sized by their
  stored `9`s (3 bytes) while `integer_digits`/`decimal_digits` include the
  `P` positions (6/0 and 0/5). Floating-insertion strings (`$$$,$$9`,
  `$Z,ZZ9`) count their leftmost symbol as the sign/currency, not a digit.
  Simple insertion `B`/`0` make a picture edited and count one byte each
  (2026-09-27: `999B99` had sized 5, `0009` 1, `XXBXX` 4) -- unless the
  pattern also holds characters no PICTURE may contain, which keeps the
  lenient fallback. An edited picture with a `V` (`Z(3)V99`) is sized by the
  edited path, not the 9s-only `V` split (it had sized 2, not 5).
  Unedited pictures are sized after expanding every repeat factor
  (`_parse_plain_pattern`, 2026-09-27): `X(2)X(3)` had sized 2, `AAX(2)` 1,
  `9(2)9(3)` 2 digits, `NN` 2 bytes instead of 4 -- the single-run regexes
  missed them and the fallback ignored `(n)` and national doubling.
  `scaling_leading: bool | None` (2026-09-10) records the P run's direction
  -- `True` for `PPP9(3)` (leading, a fraction), `False` for `9(3)PPP`
  (trailing, a scaled integer), `None` when not P-scaled at all -- the one
  place this is decided; `generators/data/layout.py`'s
  `FieldSpec.scaling_positions`/`stored_digits` read it (and `total_digits`)
  directly instead of re-deriving the P run from the raw picture string, and
  `analysis/move_type_checker.py`'s `_is_non_integer_picture` reads
  `decimal_digits` alone rather than a second heuristic. See
  [generators.md](generators.md)'s P-scaling note and [analysis.md](analysis.md)'s
  MoveTypeChecker section.
* `ArithmeticStatement.source_operands: list[str] | None` (2026-09-27) --
  the operands written before TO/FROM/GIVING, duplicates kept, set by the
  ADD/SUBTRACT parsers; `None` on a node built any other way. **Not
  serialized** (`to_dict()` is unchanged). `operands` cannot stand in for it:
  `set_target`/`set_giving` append a name only when absent, so
  `ADD A B GIVING B` and `ADD A GIVING B` leave the same `[A, B]`. Read by
  `analysis/const_fold.py`; see `analysis.md`.
* `ArithmeticStatement.givings: list[str]` (2026-07-24) — full ordered
  list of comma/space-separated `GIVING` result targets (`ADD A TO B
  GIVING C, D`); `.giving` keeps the first for backward compatibility,
  mirroring the `target`/`targets` split above. Applies to
  `AddStatement`/`SubtractStatement`/`MultiplyStatement`/`DivideStatement`
  alike. See [parser.md](parser.md) "Follow-up comma-list sweep
  (2026-07-24)".
* `MultiplyStatement`/`DivideStatement` now populate `.target`/`.targets`
  (2026-07-24) for format 1 (no `GIVING`) — `MULTIPLY x BY id-2, id-3` /
  `DIVIDE x INTO id-2, id-3` overwrite their second operand(s) in place,
  so they're result targets like ADD/SUBTRACT's `TO`/`FROM`, not just
  `.operands` entries (previously only `.operands` was populated, and
  anything past the first comma was dropped). Format 2 (`GIVING`)
  deliberately does **not** set `.target` — the second operand there is a
  multiplicand/divisor, not a result.

# Data Items (`models/data_items.py`)

```python
class CobolDataItem(ASTNode):
    level: int               # 01, 02, …, 49, 66, 77, 88
    name: str
    picture: PictureClause | None
    occurs: OccursClause | None
    # REDEFINES, VALUE, USAGE, …

class PictureClause(ASTNode):
    pattern: str             # e.g. "9(5)V99" (DECIMAL-POINT IS COMMA normalized)
    size: int | None
    integer_digits / decimal_digits / total_digits: int | None
    is_signed, is_edited, is_numeric_edited, is_alphanumeric_edited,
    is_national, is_national_edited: bool
    scaling_factor: int; scaling_leading: bool | None

class OccursClause(ASTNode):
    min_times: int
    max_times: int | None      # None = fixed-size OCCURS
    depending_on: str | None
    indexed_by: str | None     # first index (backward-compatible)
    index_names: list[str]     # all INDEXED BY names (2026-07-09)
    key_clauses: list[dict]    # {"direction": "ASCENDING"|"DESCENDING",
                               #  "keys": [...]} — SEARCH ALL keys (2026-07-09)
```

Both OCCURS clause walks that populate this node — the pure-Python
`data_clauses._parse_occurs_clause` and its Cython mirror in
`_data_fast.pyx` — were hardened 2026-08-23 against real-deck line splits
(count/`TO`/`BY` starting a continuation line) and comma-separated
`INDEXED BY` / `KEY` name lists; before that, a count on the line after
`OCCURS` could fabricate a phantom data item while this node recorded
`max_times == 0`. A same-day review pass then guarded the count read
(`_peek_count_token` / `_peek_count_pos`): a LEVEL_NUMBER reached only by
crossing a line break counts only when the clause visibly continues after
it, so a malformed `OCCURS` with no count can no longer swallow the next
item's own level number as a fabricated table size. See
[parser.md](parser.md).

## `calculate_size()` — byte width (2026-09-05 rewrite, repo audit)

`CobolDataItem.calculate_size()` reports the bytes an item occupies, every
OCCURS occurrence included. It is published as `calculated_size` on every
data item's `to_dict()` (so it reaches the backend adapter in the AST JSON)
and as the record `size` of `gen-data --list-records`.

It now defers to `cobolparser._storage.storage_size` — the same single
authority `generators/data/{layout,encoding,layout_offsets}.py` use. It used
to carry its own copy of that arithmetic and had drifted in **six** ways,
all wrong numbers in a published API:

| Input | Old | Correct |
|-------|-----|---------|
| `PIC S9(9) BINARY` / `COMPUTATIONAL` | 9 | 4 |
| `PIC S9(7)V99 COMPUTATIONAL-3` | 9 | 5 |
| `COMP-1` / `COMP-2` (no PICTURE) | 0 | 4 / 8 |
| `USAGE INDEX` | 0 | 4 |
| group with `05 B REDEFINES A PIC X(10)` | 20 | 10 |
| `05 ROW OCCURS 5` of a 4-byte group | 4 | 20 |
| `PIC S9(5)` with `SIGN IS LEADING SEPARATE` | 5 | 6 |

Causes, in order: the usage branches listed `COMP`/`COMP-4`/`COMP-3` but not
the `BINARY`/`COMPUTATIONAL`/`COMPUTATIONAL-3` spellings of the same
usages; every usage branch sat behind an `is_elementary_item()` guard, which
*requires* a PICTURE, so the `COMP-1`/`COMP-2` branch was unreachable for the
only items that can ever use it (and `INDEX` had no branch at all — a
zero-width item silently collapses every offset after it); the group branch
summed all children, so a REDEFINES entry was added to what it redefines
rather than sharing its storage; the OCCURS multiplier was applied only
in the elementary branch, never to a group; and a DISPLAY item with
`SIGN IS SEPARATE` never got the extra byte its PICTURE character count
does not include.

`_occurrence_size()` / `_occurs_multiplier()` / `_direct_data_children()` are
the new helpers. Group layout follows `layout_offsets._layout_siblings`'
**slot** rule (a contiguous run of `[base, redefiner, …]` costs its largest
member); level-66 and level-77 children are excluded for the same reasons
that module excludes them.

**Group vs. elementary (#345, 2026-10-15):** `is_elementary_item()` is True
for a childless item that has a PICTURE *or* a usage that never takes one
(`_storage.PICTURELESS_USAGES`: `COMP-1`/`COMP-2` and their
`COMPUTATIONAL-n` spellings, `INDEX`, the `POINTER` family, `OBJECT
REFERENCE`). It used to require a PICTURE, so those items were neither
group nor elementary and `get_elementary_items()` (and `to_dict()`'s
`is_elementary_item`) left them out. A childless item with neither (e.g. a
group whose subordinates are missing) is still neither -- deliberately not
guessed elementary.

`_storage.py` sits at the package root, next to `_errors.py` and for the same
reason: `cobolparser.generators.data.__init__` eagerly imports
`program_layout`, which imports `cobolparser.models`, so a model importing
`generators.data.storage` directly would close an import cycle.
`generators/data/storage.py` is now a re-export shim, so its existing
importers are untouched.

**One deliberate residual difference from `layout_offsets`:** under
`OCCURS ... DEPENDING ON`, `calculate_size` reserves the **maximum**
(matching `layout.py`/`encoding.py`, and so the record images `gen-data`
writes), while `layout_offsets` reserves **one occurrence** (multiplier
unknown at compile time). Verified across the sample + NIST corpus: 18,121
records, 14 differences, every one of them an ODO table.

Two shapes here regularly surprise consumers (both confirmed against source
2026-08-02, and both compensated for in
[generators.md](generators.md)'s data generator):

* **`PictureClause.is_signed` reports only an explicit `S`.** A
  numeric-edited picture whose sign lives in an insertion symbol —
  `PIC -ZZ,ZZ9.99`, `PIC +999`, `PIC 999CR`, `PIC 999DB` — can hold a
  negative value but reports `is_signed=False`. Code deciding "may this
  field be negative?" must also test `is_numeric_edited` plus the presence
  of `-`/`+`/`CR`/`DB` in the pattern.
* **Level-88 `THRU` ranges are marked, not expanded.**
  `ConditionNameItem.values` for `88 ST-OK VALUE 2 THRU 4.` is
  `["2", "THROUGH:4"]` — the second entry is the range *end*, tagged with a
  `THROUGH:` prefix, and the intermediate values are not enumerated. A
  consumer wanting the field's full domain has to expand the range itself
  (and bound the expansion — `VALUE 1 THRU 999999` is legal COBOL).
  A signed range end keeps its marker too (`88 X VALUE -5 THRU -1.` →
  `["-5", "THROUGH:-1"]`, distinct from `VALUE -5, -1` → `["-5", "-1"]`);
  re-checked 2026-09-28 -- an earlier note here said a signed end lost the
  marker, which is no longer true.

**National data and address usages (2026-09-28).**
`PictureClause.is_national` (an `N` or national-edited picture; `size`
already counts bytes) and `is_national_edited` (`N` with `B`/`0`/`/`:
`N(2)BN` is 8 bytes, not 4, and no longer numeric-edited).
`CobolDataItem.set_picture_clause` gives an entry with no USAGE clause the
usage its picture implies -- `NATIONAL` for `N`, `DISPLAY-1` for `G`
(IBM default `NSYMBOL(NATIONAL)`); `usage_explicit` stays False and a
later USAGE clause still wins. `CobolDataItem.group_usage` records
`GROUP-USAGE NATIONAL|UTF-8` (serialized as `group_usage`).
`OccursClause.depending_on_qualifiers` (serialized only when non-empty).
`_storage.storage_size(..., national_picture=)`: `USAGE NATIONAL` on a
numeric / numeric-edited picture is 2 bytes per position (`PIC 9(5)
NATIONAL` = 10, a separate sign is one more national character);
`PROCEDURE-POINTER` is 8 bytes (IBM: two words; was 4) and
`OBJECT REFERENCE` joined `POINTER_USAGES` (4 bytes; was 0). The encoder /
decoder write and read a numeric national field as text padded to its
width, like `PIC N` (see generators.md).

`index_names` and `key_clauses` are serialized only when non-empty. Before
2026-07-09 `ASCENDING/DESCENDING KEY` was dropped and `INDEXED BY` kept only
its last name (and was lost entirely when a KEY clause preceded it). See
[parser.md](parser.md) Silent-Drop Audit (2026-07-09).

Level-66 entries are `RenamesItem` (`name`, `renames_from`,
`renames_through`), not `CobolDataItem`s. FD/SD entries are
`CobolFileDescription` (`models/program.py`: `file_name`, `record_type`
FD|SD, `data_records`, BLOCK/RECORD CONTAINS, `record_varying_depending_on`,
LABEL/VALUE OF/LINAGE/CODE-SET clauses).

# SQL Statement Nodes (`models/sql_statements.py`)

AST nodes for EXEC SQL, EXEC CICS, and EXEC IMS DLI blocks captured by
`ibm_exec_statements.py`.

`ExecSQLStatement.tables` holds full, qualified names (`BANK.ACCOUNT`,
`LOC.SCHEMA.TABLE`); the FROM/INTO/UPDATE/JOIN regexes match qualified names
(`_SQL_TABLE_NAME`). Before 2026-09-23 they stopped at the first `.`, so every
qualified table also reported its schema (`BANK`, `SYSIBM`) as a table.

`MERGE INTO tgt USING src ...` has `sql_type == "MERGE"`; `tables` lists the
target first, then the `USING` source table or the tables its `USING
(SELECT ...)` subquery reads (a `USING (VALUES ...)` source adds none). A
statement led by common table expressions (`WITH x AS (...) SELECT ...`)
takes the type of its main verb, and `tables` lists the base tables the CTE
bodies and main statement read -- never the CTE names themselves
(`_split_common_table_expressions()`). Before 2026-09-27 both were
`"UNKNOWN"` with no tables.

`TRUNCATE [TABLE] t [DROP|REUSE STORAGE] ... [IMMEDIATE]` has
`sql_type == "TRUNCATE"` (`SQLStatementType.TRUNCATE`) and `tables == [t]`
(`_SQL_TRUNCATE_TABLE_RE`); the CRUD matrix marks `t` D. Before issue #341
(2026-10-15) it was `"UNKNOWN"` with no tables.

`into_variables` / `DynamicSQLStatement.using_variables` list every host
variable of the INTO / USING list, indicators included; before 2026-09-28
both were empty for any statement parsed from source. See
[dialects.md](dialects.md).

A structure-qualified host variable (`:DCLEMP.EMPNO`) is listed by its last
component (`EMPNO`) since 2026-09-28 (see [dialects.md](dialects.md)).

`FetchStatement.cursor_name` / `fetch_direction` / `fetch_count` are read
positionally for DB2 scroll and rowset FETCHes (2026-09-28; see
[dialects.md](dialects.md)).

# Statement Models (`models/statements/`)

| File | Node Classes |
|------|-------------|
| `base.py` | `CobolStatement`, `CobolExpression`, `ArithmeticExpression`, `ConditionalExpression`, `LogicalExpression`, `FunctionCall` |
| `arithmetic.py` | `ArithmeticStatement`, `AddStatement`, `SubtractStatement`, `MultiplyStatement`, `DivideStatement`, `ComputeStatement` |
| `call.py` | `CallStatement`, `EntryStatement` (`using_parameters` names plus a parallel `parameter_modes` list, `"REFERENCE"`/`"VALUE"`, serialized; #402), `CallParameter` |
| `communication.py` | `SendStatement`, `ReceiveStatement`, `EnableStatement`, `DisableStatement`, `PurgeStatement` (2026-09-02) |
| `control.py` | `IfStatement`, `EvaluateStatement`, `WhenClause`, `PerformStatement`, `GoStatement`, `StopStatement`, `SearchStatement` (`when_clauses[i]` holds `condition` text, `statements`, and, when one could be built, `condition_tree`, serialized by `to_dict()`; #348), `RaiseStatement`, `ResumeStatement` |
| `data.py` | `MoveStatement`, `DisplayStatement`, `InitializeStatement`, `InspectStatement`, `SetStatement`, `StringStatement`, `UnstringStatement`, `ValidateStatement` |
| `io.py` | `IOReadStatement`, `IOWriteStatement`, `IOOpenStatement`, `IOCloseStatement`, `IOAcceptStatement`, `IORewriteStatement`, `IODeleteStatement`, `IOStartStatement`, `IOUnlockStatement` |
| `legacy.py` | `ExhibitStatement`, `ExamineStatement`, `TransformStatement`, `EnterStatement`, `NoteStatement`, `ChainStatement`, `TraceStatement`, `ServiceStatement`, `TitleStatement` (2026-09-02) |
| `misc.py` | `SelectStatement`, `CopyStatement`, `ContinueStatement`, `NextSentenceStatement`, `EjectStatement`, `SkipStatement`, `ExitStatement`, `GobackStatement`, `CancelStatement`, `AlterStatement`, `GenerateStatement`, `ReleaseStatement`, `ReturnStatement`, `UseStatement`, `SortStatement`, `MergeStatement`, `CommitStatement`, `RollbackStatement`, `InvokeStatement`, `AllocateStatement`, `FreeStatement` |
| `report_writer.py` | `InitiateStatement`, `TerminateStatement`, `SuppressStatement` (2026-09-02) |

**Stacked WHENs (2026-10-14, #314):** `WHEN 'A' WHEN 'B' stmt` parses into
one `WhenClause` per WHEN phrase, so `when_clauses[0]` has no statements; the
statements after the last WHEN belong to every WHEN of the stack. The AST
shape is deliberately unchanged. `EvaluateStatement.when_groups()` returns
the arms as they execute -- each clause the parser marked `stacked` joined
to the clause after it, `group[-1].statements` the shared body. `stacked` is
decided from the tokens (nothing but layout between this WHEN and a next,
non-OTHER WHEN, and no unexpanded COPY blanked on those lines --
`TokenStream.omitted_source_lines`), never from an empty `statements`: a body
that was in the source but did not reach the AST is not a stack. Not in
`to_dict()`. Anything that reasons per *arm*
(business rules, program-flow `BranchArm`s, constraints / scenarios) must
iterate `when_groups()`, not `when_clauses`; per-*phrase* walks (xref,
unused variables, complexity's decision count, diff) keep `when_clauses`.

**Statement-coverage audit nodes (2026-09-02):** the three new modules
above plus `RaiseStatement`/`ResumeStatement` (`control.py`) and
`ValidateStatement` (`data.py`) back the 22 verbs that used to be
warned-and-discarded (see [parser.md](parser.md)'s "Statement-coverage
audit" section). Also from that audit: `ExecCicsStatement` /
`ExecImsStatement` (`parsers/statements/ibm_exec_statements.py`) now extend
`CobolStatement` (`statement_type` `"EXEC CICS"` / `"EXEC IMS"`, `node_type`
still `"EXEC_CICS"` / `"EXEC_IMS"`, `to_dict()` shape unchanged) so
`CobolProgram.get_all_statements()` returns them; `SetStatement.groups`
(additional `targets TO/UP/DOWN value` groups of a multi-group SET, also
serialized as `"groups"`; each group dict's `"value_is_entry"` key
(2026-09-10, additive) mirrors the top-level statement's own
`value_is_entry` metadata for that group specifically -- a later group's
own `SET p TO ENTRY 'X'` used to leak into a following group's flag since
`SetStatementParser._entry_form` was reset only before the first group's
`_parse_action` call); `IOOpenStatement.no_rewind` / `.with_lock` /
`.reversed_mode` (`"no_rewind"` / `"with_lock"` / `"reversed"`);
`IOAcceptStatement.on_exception` / `.not_on_exception` (serialized only when
present). `ReceiveStatement`'s `no_data_clause` / `with_data_clause` and
`IOAcceptStatement`'s handlers register their statements as children, so
the generic statement walk reaches them.

**`InvokeStatement`/`AllocateStatement`/`FreeStatement` (2026-08-05, `misc.py`):**
back the new `invoke_parser.py`/`allocate_free_parsers.py` statement parsers
(see [parser.md](parser.md)) for three previously-unsupported IBM Enterprise
verbs. `InvokeStatement` — `object_name`, `method_name` +
`method_is_literal`, `using_parameters` (reuses `call.py`'s `CallParameter`
— same `{name, passing_mode}` shape CALL's USING clause already produces),
`returning_target`. `AllocateStatement` — `is_characters`/`size_expr` (the
`identifier-1 CHARACTERS` byte-count form) xor `data_item` (the `BASED`
data-item form), `initialized`, `returning_target`. `FreeStatement` —
`pointer_names: list[str]`. All three follow the established
`to_dict()`/`_add_unique_operand()` pattern every other statement node in
this file uses; no new AST plumbing.

`InvokeStatement.set_method_name()` records the method name in `operands`
unconditionally (Copilot review on PR #113 caught that it originally skipped
this for a literal method name — inconsistent with
`CallStatement.set_called_program()` in `call.py`, which records its program
name regardless of static vs. dynamic CALL).

Notes (2026-07-07 audit remediation):

* `PerformStatement.after_clauses` — list of AFTER dimensions of a
  `PERFORM VARYING ... AFTER ...` loop, each
  `{"variable", "from_value", "by_value", "until_condition":
  CobolExpression | None}`; populated via `add_after_clause()` (which also
  registers the condition as a child) and serialized as `after_clauses`
  only when non-empty (H2).
* `CobolExpression.to_dict()` includes `operands` — condition/expression
  text (e.g. PERFORM UNTIL conditions) previously vanished at the JSON
  boundary.
* `SelectStatement`'s long-standing fields (`alternate_keys`,
  `file_status_vsam`, `reserve_areas`, `padding_character`,
  `record_delimiter`, `password`, `lock_mode`/`lock_on`/
  `lock_with_rollback`, `sharing_mode`, `assign_device_type`) are now
  actually populated by the ENVIRONMENT division parser (H5).
* `SelectStatement.assign_using` (2026-09-28): the data-name of `ASSIGN
  USING data-name` (also in `assign_to`), None for `ASSIGN TO`; in
  `to_dict()` as `assign_using`.
* `PictureClause(pattern, location, currency_symbols=None)` (2026-09-28):
  the non-`$` currency symbols a `SPECIAL-NAMES CURRENCY SIGN` declares
  that occur in the pattern (`PIC £££9.99`). The pattern is sized and
  validated through its `$` spelling, then `pattern` is restored as
  written; the set is `currency_symbols` and, when non-empty,
  `metadata["currency_symbols"]`. The DATA DIVISION passes it through
  `DataItemClauseParser._picture_clause` (also handed to the `_data_fast`
  helper in place of the class), from the non-`$` CURRENCY tokens
  `parse_picture_clause` saw. Previously `£` was an invalid PICTURE
  character and the floating string was mis-sized.
* `PictureClause(..., decimal_point_is_comma=False)` (2026-09-28):
  `SPECIAL-NAMES. DECIMAL-POINT IS COMMA` -- `,` is the decimal point and
  `.` a simple insertion character. Sized and validated through the
  default spelling (`,`/`.` exchanged, alongside the currency `$`
  translation), then `pattern` is restored as written: `9(3),99` is size 6,
  3 integer + 2 decimal digits; `Z.ZZ9,99` is 4 + 2. Kept as
  `decimal_point_is_comma` and `metadata["decimal_point_is_comma"]`.
  `DataItemClauseParser._picture_clause` reads it off the host
  (`CobolParser.decimal_point_is_comma`, set from the lexer).
* `SelectStatement.record_key_qualifiers` and each `alternate_keys` entry's
  `qualifiers` (2026-09-28): the `OF`/`IN` names of `RECORD KEY IS K6 OF
  R6`, innermost first; `record_key` / `key` stay the bare data-name.
  `set_record_key(key, source=None, qualifiers=None)`,
  `add_alternate_key(..., qualifiers=None)`; `to_dict()` gains
  `record_key_qualifiers`.
* Arithmetic statements' `on_size_error` / `not_on_size_error` lists can
  contain any statement type (registry-dispatched), all registered as AST
  children (H1).

# ASTNodeFactory

```python
from cobolparser.core.ast_factory import get_factory, create_node

factory = get_factory()
# create_node takes the node CLASS (not a string) and the node's own
# constructor kwargs; location is passed positionally to the node.
node = create_node(MoveStatement, loc)   # MoveStatement.__init__(location)
node.set_source("WS-A"); node.add_target("WS-B")
```

Raises `TypeError` for a class that is not an `ASTNode` subclass or whose
`__init__` does not take `location` first (`CobolDataItem`, `CobolSection`,
...: construct those directly), `ValidationError` when the created node has
no location / node_type, and `FieldValidationError` from a validator
registered with `register_validator()`. Keyword arguments go to the node's
constructor, so they must be parameters it actually takes.

# Traversal

```python
ast: CobolProgram = result.ast
move_stmts = ast.find_all_by_type("MoveStatement")
```

`find_all_by_type()` / `find_first_by_type()` match either the node's
`node_type` attribute (`"Statement"`, `"DataItem"`, ...) or its concrete
class name (`"MoveStatement"`, `"CallStatement"`, `"ExecSQLStatement"`,
`"IOReadStatement"`, ...). All statement subclasses share the generic
`node_type` `"Statement"` (their `to_dict()` distinguishes them via
`statement_type`), so the class name is the only way to select a specific
statement kind — this is what the CLI `analyze` and `parse --find-type`
subcommands rely on.

**Query helpers (2026-09-28).** `has_sql()` / `has_cics()` / `has_ims()`
and `get_sql_statements()` / `get_cics_statements()` /
`get_ims_statements()` classify through `program._exec_kind()`: any
`sql_statements.ExecSQLStatement` (so `FetchStatement`,
`DeclareCursorStatement`, `TransactionControlStatement`, ... too) is SQL, and
`statement_type` `"EXEC CICS"` (parser) or `"EXEC-CICS"` (dialect nodes) is
CICS, likewise IMS. They used to test `statement_type == "EXEC-CICS"` alone,
a spelling no parsed statement carries, so every real CICS / EXEC DLI
program answered False. `get_statistics()["statement_count"]` counts
`CobolStatement` instances (it had skipped `EXEC_CICS` / `EXEC_IMS`
node_types). `find_statements_using_variable(name)` matches a whole COBOL
word, case-insensitively, outside quoted literals (was a substring test:
`WS-A` matched `WS-AMOUNT`). `get_intrinsic_function_usages()` delegates to
`LanguageEnvironmentAnalyzer` (its own regex had reported `OF` for
`DLI-FUNCTION OF REC` and words inside literals).

`find_all_by_type()` results are cached per `node_type` on the node, but
each call returns a fresh copy of that cache — mutating the returned list
never corrupts a later lookup.

# Additive expression-tree fields (2026-07-20, M12)

* `ComputeStatement.expression_tree: CobolExpression | None` — structural
  decomposition of the COMPUTE expression (`set_expression_tree()`); the
  raw `.expression` string is unchanged. Emitted in `to_dict()` under
  `"expression_tree"` only when populated, so pre-M12 dict output is
  byte-identical.
* `CobolExpression.condition_tree: CobolExpression | None` — structural
  decomposition of a raw condition (`set_condition_tree()`; also
  registered as a child for generic traversal). Used by PERFORM UNTIL:
  `until_condition` remains the historical `CobolExpression("CONDITION")`
  with the raw joined string in `operands`, and the tree rides alongside.
  Emitted in `to_dict()` under `"condition_tree"` only when populated.
* Consumers (`ProgramFlowAnalyzer`, `coverage_analyzer`,
  backend extractors per `interface-contract.md`) need no changes — all
  historical fields/keys are untouched.

# New node: NextSentenceStatement (2026-08-24)

`NextSentenceStatement` (`statement_type` `"NEXT-SENTENCE"`) backs `NEXT
SENTENCE`, previously unparsed entirely (see [parser.md](parser.md)'s
"Residual corpus findings" section). Deliberately its own node rather than
reusing `ContinueStatement`: NEXT SENTENCE transfers control past the rest
of the current sentence, not a true fall-through no-op, even at the depth
this parser models control flow.


# Program units (`program_units` / `find_program_unit`, 2026-09-07)

```python
ast.program_units()          # [self, *contained, recursively], source order
ast.find_program_unit("INNERP")   # CobolProgram | None, case-insensitive
```

A compilation unit can hold several programs — stacked or nested, delimited by
`END PROGRAM` — and the parse has always kept them on
`CobolProgram.contained_programs`. What was missing was the *list*: every
analyzer in this package is program-scoped (it grades a paragraph against the
references it can see), so analyzing a multi-program file means running the
analyzer once per unit, and nothing said so or offered a way to reach the
others. These two methods are that, and back both `LintAnalyzer`'s per-unit
pass and the CLI's `--program NAME` (see [cli.md](cli.md)). Pinned by
`tests/regression/test_nested_program_units.py`.

# See Also

* [parser.md](parser.md) — produces AST nodes
* [analysis.md](analysis.md) — consumes AST via analyzer interfaces


# Program-type corpus additions (2026-09-15)

* `CobolProgram.unit_kind` -- `"PROGRAM"` (default; not serialized) or,
  for IBM object-oriented COBOL, `"CLASS"` / `"FACTORY"` / `"OBJECT"` /
  `"METHOD"` (serialized as `unit_kind`). A class contains its factory and
  object units, which contain their methods, all via
  `contained_programs`, so `program_units()` enumerates every method.
  Identification-division metadata carries `unit_kind`, `inherits` and
  `program_attributes`.
* `CobolProgram.program_attributes` (`["INITIAL", "COMMON", "RECURSIVE"]`
  subset, source order) and `is_recursive`.
* `CobolSection.is_declarative` (metadata `declarative`) for sections
  between `DECLARATIVES.` and `END DECLARATIVES.`.
* PROCEDURE DIVISION metadata `returning_parameter`.
* `CobolDataItem.is_volatile`, `byte_length` (`set_byte_length` also sizes
  the PICTURE), `is_dynamic_length` + `dynamic_length_limit`
  (`set_dynamic_length`), `object_class` (`set_object_reference`; usage
  `"OBJECT REFERENCE"`) -- each serialized only when set.
  `OccursClause.is_unbounded` (`max_times` None; serialized when True), set
  by both `OCCURS UNBOUNDED` and `OCCURS n TO UNBOUNDED` (#402).
  `PictureClause` accepts `U` (UTF-8, one byte per symbol).
* `CobolDataItem.usage_explicit` (2026-09-28): True when the entry carries
  its own USAGE (`set_usage` / `set_object_reference`); not serialized.
  `usage` / `sign_clause` of a subordinate with no clause of its own now
  reflect the enclosing group's (see parser.md, `data.py`), so
  `calculate_size()` / `to_dict()["calculated_size"]` count packed/binary
  children of a `COMP-3`/`BINARY` group correctly.
* `UseStatement.report_groups` (`USE BEFORE REPORTING`).
* `SetStatement.targets_are_address_of` (`SET ADDRESS OF x TO p`).
* `DeclareTableStatement.table_name` is `"SCHEMA.TABLE"` for a qualified
  declaration.
* Flow model: `FlowEdgeType.XML_PROCESSING_PROCEDURE[_THRU]`,
  `FlowEdgeType.CICS_HANDLE`, `FlowEdgeType.SQL_WHENEVER` (#349);
  `FlowNode.is_declarative`.

# `ConditionNameItem.false_value`, `InitializeStatement.to_value_category` / `.to_default` (2026-09-28)

* `ConditionNameItem.false_value: str | None` -- the literal of a level-88
  `WHEN SET TO FALSE [IS] literal` phrase (a sign folded into a numeric
  literal as in `values`: `"-0"`; a figurative constant by name: `"SPACE"`),
  `None` when absent. Always present in `to_dict()`.
* `InitializeStatement.to_value_category: str | None` (`"ALL"` or a category
  name such as `"NUMERIC"`, from Enterprise COBOL 6's `{ALL | category} TO
  VALUE`) and `.to_default: bool` (`[THEN] TO DEFAULT`). Both always present
  in `to_dict()`.


# `_storage.py`: signed NATIONAL sign width (2026-10-08)

A national decimal item cannot carry an overpunched sign; when the SIGN
clause is omitted IBM assumes `SIGN IS TRAILING SEPARATE CHARACTER`, so
`storage_size` charges the sign one national character (2 bytes) whenever
`is_signed` under `NATIONAL`. `PIC S9(5) USAGE NATIONAL` was 10 bytes (12
only with an explicit SEPARATE), shifting every later offset by 2. Pinned in
`tests/regression/test_bug_hunt_2026_10_08.py`.
