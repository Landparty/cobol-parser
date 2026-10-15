---
type: Module
title: AST Models
description: ASTNode hierarchy (cobolparser/models/) — CobolProgram and its program units, data items and byte sizing (_storage.py, _data_fast.pyx), SQL and statement nodes, to_dict()/to_json()/from_json() serialisation.
tags: [ast, models, cobol-program, data-items, statements]
timestamp: 2026-10-15T00:00:00Z
---

# Overview

`cobolparser/models/` holds every AST node class the parser builds. Every node
extends `ASTNode` (`ast_base.py`) and implements `to_dict()`; `to_json()` is
`to_dict()` serialized. The root of a parse is a `CobolProgram`
(`ParseResult.ast`), whose tree is divisions -> sections -> paragraphs ->
statements (PROCEDURE DIVISION) or sections -> data items (DATA DIVISION).

| Module | Holds |
|--------|-------|
| `models/ast_base.py` | `SourceLocation`, `ASTNode`, `ASTValidator`, `ValidationResult` |
| `models/program.py` | `CobolProgram`, `CobolDivision`, `CobolSection`, `CobolParagraph`, `CobolFileDescription`, `LossyDeserializationWarning` |
| `models/data_items.py` | `CobolDataItem`, `PictureClause`, `OccursClause`, `ConditionNameItem` (88), `RenamesItem` (66) |
| `models/sql_statements.py` | `ExecSQLStatement` and its subclasses, `parse_exec_sql()` |
| `models/statements/*.py` | every PROCEDURE DIVISION statement node, by category |
| `_storage.py` (package root) | `storage_size()` — the one authority on an item's byte width |
| `_data_fast.pyx` (package root) | optional Cython mirror of the DATA DIVISION clause loop that builds these nodes |

Getting started: `result = parse_cobol(src)`; walk `result.ast` with
`program_units()` / `get_all_statements()` / `get_data_items()` /
`find_all_by_type("MoveStatement")`, or dump it with `to_json()`.
`cobolparser.models` re-exports the commonly used classes (`__all__`: the base
classes, program/division/section, the data-item classes, the core statement
and SQL nodes, `LossyDeserializationWarning`, `parse_exec_sql`); everything
else imports from its own module. The parser builds nodes; to create one by
hand use `ASTNodeFactory` (see below) or the node's constructor.

## Contents

* [Base Classes](#base-classes-modelsast_basepy)
* [Program Structure](#program-structure-modelsprogrampy)
  * [Program units](#program-units)
  * [Serialization: `to_json()` / `from_json()`](#serialization-to_json--from_json)
* [Traversal and query helpers](#traversal-and-query-helpers)
* [ASTNodeFactory](#astnodefactory)
* [Data Items](#data-items-modelsdata_itemspy)
  * [`PictureClause` sizing](#pictureclause-sizing)
  * [Shapes that surprise consumers](#shapes-that-surprise-consumers)
* [`calculate_size()` and `_storage.py`](#calculate_size-and-_storagepy)
* [SQL Statement Nodes](#sql-statement-nodes-modelssql_statementspy)
* [Statement Models](#statement-models-modelsstatements)
  * [Statement field reference](#statement-field-reference)
* [See Also](#see-also)

# Base Classes (`models/ast_base.py`)

```python
@dataclass
class SourceLocation:
    line: int
    column: int
    length: int | None = None   # no filename field — file identity travels on ParseResult

class ASTNode(ABC):
    def __init__(self, node_type: str, location: SourceLocation): ...
    node_type: str              # "Program", "Division", "Statement", "DataItem", ...
    location: SourceLocation
    parent: ASTNode | None
    children: list[ASTNode]
    metadata: dict              # property; get_metadata()/set_metadata()/has_metadata()
    division_name / section_name   # context properties
    def to_dict(self) -> dict: ...          # abstract
    def to_json(self, indent: int | None = None) -> str: ...
    def find_all_by_type(self, node_type: str) -> list[ASTNode]: ...
    def find_first_by_type(self, node_type: str) -> ASTNode | None: ...
    def traverse_depth_first(...) / traverse_breadth_first(...)
    def add_child / remove_child / get_children_by_type / get_root / get_path_from_root
    def equals(self, other: object) -> bool: ...

class ASTValidator:
    def validate(self, node: ASTNode) -> ValidationResult   # .errors / .warnings / .is_valid
```

`ASTNode.equals(other)` is true when both nodes have the same `node_type`, the
same tree of child node types (`_shape()`), and the same `to_dict()` with every
nested `location` key removed (`_comparable_dict()`). Source position never
matters, content always does: a reparse of the same text is equal, a program
differing in one PICTURE or one MOVE literal is not.
`CobolProgram._comparable_dict()` serializes with `include_metadata=False` and
adds back only the program's own `_metadata`, so the derived statistics block
(whose `total_lines` comes from locations) does not take part. (Before issue
#273, 2026-10-05, it compared node types and child counts only, so any two
programs with the same division count were "equal".)

# Program Structure (`models/program.py`)

```python
class CobolProgram(ASTNode):             # CobolProgram(program_name, location); node_type "Program"
    program_name: str                    # the PROGRAM-ID (CLI/JSON reports call it program_id)
    divisions: list[CobolDivision]       # property, from an internal name -> division dict
    identification_division / environment_division / data_division / procedure_division
    contained_programs: list[CobolProgram]
    unit_kind: str                       # "PROGRAM" | "CLASS" | "FACTORY" | "OBJECT" | "METHOD"
    program_attributes: list[str]        # property: INITIAL / COMMON / RECURSIVE subset
    is_recursive: bool                   # property

class CobolDivision(ASTNode):            # CobolDivision(division_name, location)
    division_name: str                   # property
    sections: list[CobolSection | CobolParagraph]  # property; a PROCEDURE DIVISION with no
                                         # sections returns its paragraphs here
    paragraphs: list[CobolParagraph]

class CobolSection(ASTNode):             # CobolSection(section_name, location)
    section_name: str                    # property
    paragraphs: list[CobolParagraph]
    data_items: list[CobolDataItem]
    is_declarative: bool                 # property (metadata "declarative")

class CobolParagraph(ASTNode):           # CobolParagraph(paragraph_name, location)
    paragraph_name: str
    statements: list[CobolStatement]
```

`CobolProgram` method groups: structure (`get_division`, `has_division`,
`get_procedures`, `find_procedures`, `get_data_items`, `find_data_items`,
`get_all_statements`, `find_statements`, `get_statements_in_division`,
`get_nodes_in_division`, `get_entry_statements`); units (`program_units`,
`find_program_unit`, `add_contained_program`); dialect queries (`has_sql` /
`has_cics` / `has_ims`, `get_sql_statements` / `get_cics_statements` /
`get_ims_statements`, `get_ims_interface_calls`, `uses_ims_interface`,
`is_ims_dlitcbl_program`, `get_intrinsic_function_usages`,
`uses_intrinsic_functions`, `get_le_callable_service_calls`,
`uses_language_environment`); `find_statements_using_variable`,
`find_dead_code`, `get_statistics`, `validate`; and
`to_dict(config=None)` / `to_json(config_or_indent=None)` / `from_json()`.

`get_all_statements()` walks contained programs too, and reaches handler
bodies (INVALID KEY, ON EXCEPTION, ...); the result is cached on the program
(invalidated by `add_division`).

Program-unit attributes (from the program-type corpus work, 2026-09-15):

* `unit_kind` -- `"PROGRAM"` (default; not serialized) or, for IBM
  object-oriented COBOL, `"CLASS"` / `"FACTORY"` / `"OBJECT"` / `"METHOD"`
  (serialized as `unit_kind`). A class contains its factory and object units,
  which contain their methods, all via `contained_programs`, so
  `program_units()` enumerates every method. Identification-division metadata
  carries `unit_kind`, `inherits` and `program_attributes`.
* `program_attributes` (`["INITIAL", "COMMON", "RECURSIVE"]` subset, source
  order) and `is_recursive`.
* `CobolSection.is_declarative` (metadata `declarative`) for sections between
  `DECLARATIVES.` and `END DECLARATIVES.`.
* PROCEDURE DIVISION metadata `returning_parameter`.

FD/SD entries are `CobolFileDescription(file_name, location, record_type="FD")`
(`file_name`, `record_type` FD|SD, `data_records`, BLOCK/RECORD CONTAINS,
`record_varying_depending_on`, LABEL/VALUE OF/LINAGE/CODE-SET clauses).

## Program units

```python
ast.program_units()               # [self, *contained, recursively], source order
ast.find_program_unit("INNERP")   # CobolProgram | None, case-insensitive
```

A compilation unit can hold several programs — stacked or nested, delimited by
`END PROGRAM` — and the parse keeps them on `CobolProgram.contained_programs`
(serialized as `contained_programs`). Every analyzer in this package is
program-scoped (it grades a paragraph against the references it can see), so
analyzing a multi-program file means running the analyzer once per unit; these
two methods (2026-09-07) are how to reach the units, and back both
`LintAnalyzer`'s per-unit pass and the CLI's `--program NAME` (see
[cli.md](cli.md)). Pinned by `tests/regression/test_nested_program_units.py`.

## Serialization: `to_json()` / `from_json()`

`CobolProgram.to_json()` exports the full tree as JSON (top-level keys
`node_type`, `program_name`, `divisions`, `contained_programs`, `location`,
`metadata`, plus `unit_kind` when not `"PROGRAM"`). Optional keys across the
node classes are mostly emitted only when non-empty, so adding a field keeps
older dict output byte-identical.

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
  `p.to_dict()` with PROCEDURE DIVISION paragraph `statements` emptied, apart
  from the derived `metadata.statistics`.

Serialized-shape facts (several were in-memory only until the 2026-07-07
fidelity audit):

* `CobolDataItem.to_dict()` serializes level-88 children as `condition_names`;
  `CobolSection.to_dict()` serializes level-66 children as `renames_items`.
* `CallStatement.to_dict()` serializes `not_on_exception`, and CALL handler
  statements are registered as AST children so `find_all_by_type()` agrees
  with `get_all_statements()`.
* `CobolExpression.to_dict()` includes `operands`, so condition/expression
  text (e.g. PERFORM UNTIL conditions) reaches the JSON.

# Traversal and query helpers

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
subcommands rely on. Results are cached per `node_type` on the node, but each
call returns a fresh copy of that cache — mutating the returned list never
corrupts a later lookup.

**Query helpers (2026-09-28).** `has_sql()` / `has_cics()` / `has_ims()`
and `get_sql_statements()` / `get_cics_statements()` /
`get_ims_statements()` classify through `program._exec_kind()`: any
`sql_statements.ExecSQLStatement` (so `FetchStatement`,
`DeclareCursorStatement`, `TransactionControlStatement`, ... too) is SQL, and
`statement_type` `"EXEC CICS"` (parser) or `"EXEC-CICS"` (dialect nodes) is
CICS, likewise IMS. (They used to test `statement_type == "EXEC-CICS"` alone,
a spelling no parsed statement carries, so every real CICS / EXEC DLI program
answered False.) `get_statistics()["statement_count"]` counts `CobolStatement`
instances, `EXEC_CICS` / `EXEC_IMS` included. `find_statements_using_variable(name)`
matches a whole COBOL word, case-insensitively, outside quoted literals (not a
substring: `WS-A` does not match `WS-AMOUNT`). `get_intrinsic_function_usages()`
delegates to `LanguageEnvironmentAnalyzer` (its own former regex had reported
`OF` for `DLI-FUNCTION OF REC` and words inside literals).

# ASTNodeFactory

```python
from cobolparser.core.ast_factory import get_factory, create_node

factory = get_factory()
# create_node(node_class, location, **kwargs): takes the node CLASS (not a
# string); location is passed positionally to the node, kwargs to its __init__.
node = create_node(MoveStatement, loc)   # MoveStatement.__init__(location)
node.set_source("WS-A"); node.add_target("WS-B")
```

Raises `TypeError` for a class that is not an `ASTNode` subclass or whose
`__init__` does not take `location` first (`CobolDataItem`, `CobolSection`,
...: construct those directly), `ValidationError` when the created node has
no location / node_type, `NodeTypeError` from a type check, and
`FieldValidationError` from a validator registered with
`register_validator()`. Keyword arguments go to the node's constructor, so
they must be parameters it actually takes.

# Data Items (`models/data_items.py`)

```python
class CobolDataItem(ASTNode):        # CobolDataItem(name, level, location); node_type "DataItem"
    level: int                       # 01, 02, …, 49, 77 (66 -> RenamesItem, 88 -> ConditionNameItem)
    name: str                        # synthetic ANONYMOUS-<level>-<line> when unnamed
    is_filler: bool; layout_name: str   # property: "FILLER" for every filler, else name
    picture_clause: PictureClause | None
    occurs_clause: OccursClause | None
    usage: str | None; usage_explicit: bool; group_usage: str | None
    redefines, value_clause, sign_clause, synchronized, justified,
    blank_when_zero, is_external, is_global, is_volatile,
    byte_length, is_dynamic_length, dynamic_length_limit, object_class
    def calculate_size(); is_elementary_item(); is_group_item(); get_elementary_items()
    def set_picture_clause / set_usage / set_occurs_clause / set_redefines /
        set_value_clause / set_byte_length / set_dynamic_length / set_object_reference

class PictureClause(ASTNode):        # PictureClause(pattern, location, currency_symbols=None,
                                     #               decimal_point_is_comma=False)
    pattern: str                     # as written, e.g. "9(5)V99"
    size: int | None                 # BYTES, not character positions
    integer_digits / decimal_digits / total_digits: int | None
    is_signed, is_edited, is_numeric_edited, is_alphanumeric_edited,
    is_national, is_national_edited, is_valid: bool
    has_scaling_factor: bool; scaling_factor: int; scaling_leading: bool | None
    currency_symbols: frozenset[str]; decimal_point_is_comma: bool

class OccursClause(ASTNode):         # OccursClause(location)
    min_times: int | None
    max_times: int | None      # == min_times for a fixed OCCURS n; None for UNBOUNDED
    is_unbounded: bool         # OCCURS UNBOUNDED / OCCURS n TO UNBOUNDED (#402)
    depending_on: str | None
    depending_on_qualifiers: list[str]
    indexed_by: str | None     # first index (backward-compatible)
    index_names: list[str]     # all INDEXED BY names (2026-07-09)
    key_clauses: list[dict]    # {"direction": "ASCENDING"|"DESCENDING",
                               #  "keys": [...]} — SEARCH ALL keys (2026-07-09)

class ConditionNameItem(ASTNode):    # level 88: name, values, false_value
class RenamesItem(ASTNode):          # level 66: name, renames_from, renames_through
```

Serialization: `index_names`, `key_clauses` and `depending_on_qualifiers` are
serialized only when non-empty, `is_unbounded` only when True; every data
item's `to_dict()` carries `calculated_size` (below) and `is_elementary_item`.
`is_volatile`, `byte_length` (`set_byte_length` also sizes the PICTURE),
`is_dynamic_length` + `dynamic_length_limit`, `object_class`
(`set_object_reference`; usage `"OBJECT REFERENCE"`) and `group_usage`
(`GROUP-USAGE NATIONAL|UTF-8`) are each serialized only when set.
`usage_explicit` is not serialized. (Before 2026-07-09 `ASCENDING/DESCENDING
KEY` was dropped and `INDEXED BY` kept only its last name; see
[parser.md](parser.md)'s Silent-Drop Audit.)

**Inherited USAGE / SIGN (2026-09-28).** `usage_explicit` is True when the
entry carries its own USAGE (`set_usage` / `set_object_reference`). `usage` /
`sign_clause` of a subordinate with no clause of its own reflect the enclosing
group's (see parser.md, `data.py`), so `calculate_size()` counts packed/binary
children of a `COMP-3`/`BINARY` group correctly. `set_picture_clause` gives an
entry with no USAGE clause the usage its picture implies -- `NATIONAL` for
`N`, `DISPLAY-1` for `G` (IBM default `NSYMBOL(NATIONAL)`); `usage_explicit`
stays False and a later USAGE clause still wins.

**Implicit FILLER (#404, 2026-10-14).** Outside a REPORT SECTION group, an
entry with no data-name (`05 PIC X(3).`, FILLER omitted) keeps the synthetic
`ANONYMOUS-<level>-<line>` `name` but has `is_filler=True`.
`CobolDataItem.layout_name` is `"FILLER"` for every filler item and `name`
otherwise; record layouts (`layout.py`, `layout_offsets.py` / `data-items`,
`program_layout.py`) name and path items by it, so gen-data drops the column
and lineage keys it positionally like `05 FILLER`. Unnamed report-group
entries stay non-filler.

**REPORT SECTION (2026-09-02).** Report groups are ordinary `CobolDataItem`
trees under a `CobolSection("REPORT")`. Each 01-level group carries
`metadata["rd_report_name"]` and `metadata["rd_clauses"]` (the RD's
CODE/CONTROLS/PAGE LIMIT/HEADING/FIRST DETAIL/LAST DETAIL/FOOTING/GLOBAL as a
mapping); every entry carries `metadata["report_clauses"]` for its
TYPE/LINE/NEXT GROUP/COLUMN/SOURCE/SUM/GROUP INDICATE/PRESENT WHEN clauses.
Anonymous entries (`01 TYPE IS DETAIL.`) get the `ANONYMOUS-<level>-<line>`
name. See [parser.md](parser.md).

**`ConditionNameItem.false_value: str | None`** (2026-09-28) -- the literal of
a level-88 `WHEN SET TO FALSE [IS] literal` phrase (a sign folded into a
numeric literal as in `values`: `"-0"`; a figurative constant by name:
`"SPACE"`), `None` when absent. Always present in `to_dict()`.

**OCCURS parsing.** Both OCCURS clause walks that populate `OccursClause` —
the pure-Python `data_clauses._parse_occurs_clause` and its Cython mirror in
`_data_fast.pyx` — handle real-deck line splits (count/`TO`/`BY` starting a
continuation line) and comma-separated `INDEXED BY` / `KEY` name lists
(2026-08-23). The count read is guarded (`_peek_count_token` /
`_peek_count_pos`): a LEVEL_NUMBER reached only by crossing a line break counts
only when the clause visibly continues after it, so a malformed `OCCURS` with
no count cannot swallow the next item's own level number as a fabricated table
size (it used to fabricate a phantom data item while recording
`max_times == 0`). See [parser.md](parser.md).

**`_data_fast.pyx`.** `parse_picture_clause_fast()` /
`parse_data_item_clauses_fast()` re-implement the DATA DIVISION clause
dispatch loop in Cython, calling back into the parser's
`_parse_picture_clause` / `_parse_value_clause` / `_parse_usage_clause`
wrappers. Pure Python is the default: the extension is built only under
`COBOLPARSER_ACCEL=1` and imported by `parsers/divisions/data_clauses.py` only
when `cobolparser._accel.accelerators_enabled()` is true at import time. A
compiled helper that does not match the current source is detected by
`_data_fast_usable()` and disabled with a logged warning (never a
`warnings.warn`, which `-W error` would turn into an import failure), so a
stale binary costs speed, not correctness. Any change to an OCCURS / PICTURE /
clause walk in `data_clauses.py` must be mirrored in `_data_fast.pyx` (and its
checked-in `.c` regenerated). See [lexer.md](lexer.md) for the accelerator
build.

## `PictureClause` sizing

`size` is a **byte** count — it is what `calculate_size()`, `data-items`
offsets and record images are built from.

* `PIC N(n)` (national) and `PIC G(n)` (DBCS) are **2 bytes per character**
  (2026-09-09); `U` (UTF-8) is one byte per symbol.
* P-scaled pictures (`9(3)PPP`, `SVPP9(3)`) are sized by their stored `9`s (3
  bytes) while `integer_digits`/`decimal_digits` include the `P` positions
  (6/0 and 0/5). `scaling_leading: bool | None` (2026-09-10) records the P
  run's direction -- `True` for `PPP9(3)` (leading, a fraction), `False` for
  `9(3)PPP` (trailing, a scaled integer), `None` when not P-scaled -- the one
  place this is decided; `generators/data/layout.py`'s
  `FieldSpec.scaling_positions`/`stored_digits` read it (and `total_digits`)
  directly, and `analysis/move_type_checker.py`'s `_is_non_integer_picture`
  reads `decimal_digits` alone. See [generators.md](generators.md)'s P-scaling
  note and [analysis.md](analysis.md)'s MoveTypeChecker section.
* Floating-insertion strings (`$$$,$$9`, `$Z,ZZ9`) count their leftmost symbol
  as the sign/currency, not a digit.
* Simple insertion `B`/`0` make a picture edited and count one byte each
  (2026-09-27: `999B99` had sized 5, `0009` 1, `XXBXX` 4) -- unless the pattern
  also holds characters no PICTURE may contain, which keeps the lenient
  fallback. An edited picture with a `V` (`Z(3)V99`) is sized by the edited
  path, not the 9s-only `V` split (it had sized 2, not 5).
* Unedited pictures are sized after expanding every repeat factor
  (`_parse_plain_pattern`, 2026-09-27): `X(2)X(3)` had sized 2, `AAX(2)` 1,
  `9(2)9(3)` 2 digits, `NN` 2 bytes instead of 4.
* **National (2026-09-28).** `is_national` (an `N` or national-edited picture)
  and `is_national_edited` (`N` with `B`/`0`/`/`: `N(2)BN` is 8 bytes, not 4,
  and not numeric-edited).
* **`currency_symbols`** (2026-09-28): the non-`$` currency symbols a
  `SPECIAL-NAMES CURRENCY SIGN` declares that occur in the pattern
  (`PIC £££9.99`). The pattern is sized and validated through its `$`
  spelling, then `pattern` is restored as written; the set is also
  `metadata["currency_symbols"]` when non-empty. The DATA DIVISION passes it
  through `DataItemClauseParser._picture_clause` (also handed to the
  `_data_fast` helper in place of the class), from the non-`$` CURRENCY tokens
  `parse_picture_clause` saw. (`£` used to be an invalid PICTURE character.)
* **`decimal_point_is_comma`** (2026-09-28): `SPECIAL-NAMES. DECIMAL-POINT IS
  COMMA` -- `,` is the decimal point and `.` a simple insertion character.
  Sized and validated through the default spelling (`,`/`.` exchanged,
  alongside the currency `$` translation), then `pattern` is restored as
  written: `9(3),99` is size 6, 3 integer + 2 decimal digits; `Z.ZZ9,99` is 4 +
  2. Also `metadata["decimal_point_is_comma"]`.
  `DataItemClauseParser._picture_clause` reads it off the host
  (`CobolParser.decimal_point_is_comma`, set from the lexer).

## Shapes that surprise consumers

Both compensated for in [generators.md](generators.md)'s data generator:

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
  (and bound the expansion — `VALUE 1 THRU 999999` is legal COBOL). A signed
  range end keeps its marker too (`88 X VALUE -5 THRU -1.` →
  `["-5", "THROUGH:-1"]`, distinct from `VALUE -5, -1` → `["-5", "-1"]`).

# `calculate_size()` and `_storage.py`

`CobolDataItem.calculate_size()` reports the bytes an item occupies, every
OCCURS occurrence included. It is published as `calculated_size` on every data
item's `to_dict()` (so it reaches the backend adapter in the AST JSON) and as
the record `size` of `gen-data --list-records`.

It defers to `cobolparser._storage.storage_size(usage, *, picture_size,
total_digits, sign_clause=None, is_signed=False, national_picture=False)` —
the same single authority `generators/data/{layout,encoding,layout_offsets}.py`
use. `_storage.py` also holds `binary_byte_length()`, `packed_byte_length()`,
the usage sets (`PACKED_USAGES`, `BINARY_FIXED_USAGES`, `BINARY_NATIVE_USAGES`,
`BINARY_USAGES`, `SINGLE_FLOAT_USAGES` / `DOUBLE_FLOAT_USAGES` /
`FLOAT_USAGES`, `POINTER_USAGES`, `PICTURELESS_USAGES`) and the fixed widths
(`INDEX_BYTES` 4, `POINTER_BYTES` 4 for `POINTER` / `POINTER-32` /
`FUNCTION-POINTER` / `OBJECT REFERENCE`, `PROCEDURE_POINTER_BYTES` 8 — IBM:
two words, `POINTER_64_BYTES` 8).

Current rules worth knowing:

* `USAGE NATIONAL` on a numeric / numeric-edited picture is 2 bytes per
  position (`PIC 9(5) NATIONAL` = 10). A signed national decimal item always
  pays a separate sign of one national character (2 bytes): it cannot carry an
  overpunched sign, and with the SIGN clause omitted IBM assumes `SIGN IS
  TRAILING SEPARATE CHARACTER`, so `PIC S9(5) USAGE NATIONAL` is 12 (it was 10
  before 2026-10-08, shifting every later offset by 2; pinned in
  `tests/regression/test_bug_hunt_2026_10_08.py`).
* A DISPLAY item with `SIGN IS SEPARATE` gets the extra byte its PICTURE
  character count does not include.
* Group layout follows `layout_offsets._layout_siblings`' **slot** rule (a
  contiguous run of `[base, redefiner, …]` costs its largest member); the
  OCCURS multiplier applies to groups as well as elementary items; level-66
  and level-77 children are excluded. Helpers: `_occurrence_size()` /
  `_occurs_multiplier()` / `_direct_data_children()`.
* **Group vs. elementary (#345, 2026-10-15):** `is_elementary_item()` is True
  for a childless item that has a PICTURE *or* a usage that never takes one
  (`_storage.PICTURELESS_USAGES`: `COMP-1`/`COMP-2` and their
  `COMPUTATIONAL-n` spellings, `INDEX`, the `POINTER` family, `OBJECT
  REFERENCE`), so `get_elementary_items()` and `to_dict()`'s
  `is_elementary_item` include them. A childless item with neither (e.g. a
  group whose subordinates are missing) is neither group nor elementary --
  deliberately not guessed elementary.

**One deliberate residual difference from `layout_offsets`:** under `OCCURS
... DEPENDING ON`, `calculate_size` reserves the **maximum** (matching
`layout.py`/`encoding.py`, and so the record images `gen-data` writes), while
`layout_offsets` reserves **one occurrence** (multiplier unknown at compile
time). Verified across the sample + NIST corpus: 18,121 records, 14
differences, every one of them an ODO table.

**Why `_storage.py` sits at the package root**, next to `_errors.py` and for
the same reason: `cobolparser.generators.data.__init__` eagerly imports
`program_layout`, which imports `cobolparser.models`, so a model importing
`generators.data.storage` directly would close an import cycle.
`generators/data/storage.py` is a re-export shim, so its importers are
untouched.

**History (2026-09-05 rewrite).** `calculate_size()` used to carry its own copy
of the arithmetic and had drifted in several ways, all wrong numbers in a
published API:

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
the `BINARY`/`COMPUTATIONAL`/`COMPUTATIONAL-3` spellings; every usage branch
sat behind an `is_elementary_item()` guard that then *required* a PICTURE, so
the `COMP-1`/`COMP-2` branch was unreachable (and `INDEX` had no branch — a
zero-width item silently collapses every offset after it); the group branch
summed all children, adding a REDEFINES entry to what it redefines; the OCCURS
multiplier was applied only in the elementary branch; and `SIGN IS SEPARATE`
never got its extra byte. Later corrections: `PROCEDURE-POINTER` 4 -> 8 and
`OBJECT REFERENCE` 0 -> 4 (2026-09-28).

# SQL Statement Nodes (`models/sql_statements.py`)

AST nodes for EXEC SQL blocks: `ExecSQLStatement` (extends `CobolStatement`)
and its subclasses `DeclareCursorStatement`, `DeclareTableStatement`,
`FetchStatement`, `DynamicSQLStatement`, `TransactionControlStatement`, plus
`SQLStatementInfo`, `SQLStatementType` (string constants), `DB2ColumnDefinition`
and the factory `parse_exec_sql(sql_text, location)`. The EXEC CICS / EXEC IMS
nodes (`ExecCicsStatement` / `ExecImsStatement`) live with their parsers in
`parsers/statements/ibm_exec_statements.py` (see
[Statement Models](#statement-models-modelsstatements)).

* `ExecSQLStatement.tables` holds full, qualified names (`BANK.ACCOUNT`,
  `LOC.SCHEMA.TABLE`); the FROM/INTO/UPDATE/JOIN regexes match qualified names
  (`_SQL_TABLE_NAME`). (Before 2026-09-23 they stopped at the first `.`, so
  every qualified table also reported its schema as a table.)
* `MERGE INTO tgt USING src ...` has `sql_type == "MERGE"`; `tables` lists the
  target first, then the `USING` source table or the tables its `USING
  (SELECT ...)` subquery reads (a `USING (VALUES ...)` source adds none). A
  statement led by common table expressions (`WITH x AS (...) SELECT ...`)
  takes the type of its main verb, and `tables` lists the base tables the CTE
  bodies and main statement read -- never the CTE names themselves
  (`_split_common_table_expressions()`). (Both were `"UNKNOWN"` with no tables
  before 2026-09-27.)
* `TRUNCATE [TABLE] t [DROP|REUSE STORAGE] ... [IMMEDIATE]` has
  `sql_type == "TRUNCATE"` (`SQLStatementType.TRUNCATE`) and `tables == [t]`
  (`_SQL_TRUNCATE_TABLE_RE`); the CRUD matrix marks `t` D (issue #341,
  2026-10-15).
* `into_variables` / `DynamicSQLStatement.using_variables` list every host
  variable of the INTO / USING list, indicators included (2026-09-28).
* A structure-qualified host variable (`:DCLEMP.EMPNO`) is listed by its last
  component (`EMPNO`).
* `FetchStatement.cursor_name` / `fetch_direction` / `fetch_count` are read
  positionally for DB2 scroll and rowset FETCHes.
* `DeclareTableStatement.table_name` is `"SCHEMA.TABLE"` for a qualified
  declaration.

See [dialects.md](dialects.md) for the SQL details.

# Statement Models (`models/statements/`)

| File | Node Classes |
|------|-------------|
| `base.py` | `CobolStatement`, `CobolExpression`, `ArithmeticExpression`, `ConditionalExpression`, `LogicalExpression`, `FunctionCall` |
| `arithmetic.py` | `ArithmeticStatement`, `AddStatement`, `SubtractStatement`, `MultiplyStatement`, `DivideStatement`, `ComputeStatement` |
| `call.py` | `CallParameter`, `CallStatement`, `EntryStatement` |
| `communication.py` | `SendStatement`, `ReceiveStatement`, `EnableStatement`, `DisableStatement`, `PurgeStatement` (private base `_EnableDisableStatement`) |
| `control.py` | `IfStatement`, `EvaluateStatement`, `WhenClause`, `PerformStatement`, `GoStatement`, `StopStatement`, `SearchStatement`, `RaiseStatement`, `ResumeStatement` |
| `data.py` | `MoveStatement`, `DisplayStatement`, `InitializeStatement`, `InspectStatement`, `SetStatement`, `StringStatement`, `UnstringStatement`, `ValidateStatement` |
| `io.py` | `IOReadStatement`, `IOWriteStatement`, `IOOpenStatement`, `IOCloseStatement`, `IOAcceptStatement`, `IORewriteStatement`, `IODeleteStatement`, `IOStartStatement`, `IOUnlockStatement` (mixins `InvalidKeyClauseMixin`, `LockClauseMixin`, `RetryClauseMixin`) |
| `legacy.py` | `ExhibitStatement`, `ExamineStatement`, `TransformStatement`, `EnterStatement`, `NoteStatement`, `ChainStatement`, `TraceStatement`, `ServiceStatement`, `TitleStatement` |
| `misc.py` | `SelectStatement`, `CopyStatement`, `ContinueStatement`, `NextSentenceStatement`, `EjectStatement`, `SkipStatement`, `ExitStatement`, `GobackStatement`, `CancelStatement`, `AlterStatement`, `GenerateStatement`, `XmlJsonStatement`, `ReleaseStatement`, `ReturnStatement`, `UseStatement`, `SortStatement`, `MergeStatement`, `CommitStatement`, `RollbackStatement`, `InvokeStatement`, `AllocateStatement`, `FreeStatement` |
| `report_writer.py` | `InitiateStatement`, `TerminateStatement`, `SuppressStatement` (private base `_ReportNameListStatement`) |

Every statement node has `statement_type` (e.g. `"MOVE"`) and `operands`
(the data names it touches, appended via `_add_unique_operand()`; identifier
discovery — unused-variables, xref — reads `operands`, which is why most
fields below are also added there). `ExecCicsStatement` / `ExecImsStatement`
(`parsers/statements/ibm_exec_statements.py`) also extend `CobolStatement`
(`statement_type` `"EXEC CICS"` / `"EXEC IMS"`, `node_type` `"EXEC_CICS"` /
`"EXEC_IMS"`, `to_dict()` shape unchanged since 2026-09-02) so
`get_all_statements()` returns them.

The `communication.py` / `legacy.py` / `report_writer.py` modules plus
`RaiseStatement`/`ResumeStatement` and `ValidateStatement` (statement-coverage
audit, 2026-09-02) back the 22 verbs that used to be warned-and-discarded (see
[parser.md](parser.md)'s "Statement-coverage audit" section).
`InvokeStatement`/`AllocateStatement`/`FreeStatement` (2026-08-05) back
`invoke_parser.py`/`allocate_free_parsers.py`.

**`NextSentenceStatement`** (`statement_type` `"NEXT-SENTENCE"`, 2026-08-24)
backs `NEXT SENTENCE`. Deliberately its own node rather than reusing
`ContinueStatement`: NEXT SENTENCE transfers control past the rest of the
current sentence, not a true fall-through no-op.

**Stacked WHENs (2026-10-14, #314).** `WHEN 'A' WHEN 'B' stmt` parses into one
`WhenClause` per WHEN phrase, so `when_clauses[0]` has no statements; the
statements after the last WHEN belong to every WHEN of the stack. The AST
shape is deliberately unchanged. `EvaluateStatement.when_groups()` returns the
arms as they execute -- each clause the parser marked `stacked` joined to the
clause after it, `group[-1].statements` the shared body. `stacked` is decided
from the tokens (nothing but layout between this WHEN and a next, non-OTHER
WHEN, and no unexpanded COPY blanked on those lines --
`TokenStream.omitted_source_lines`), never from an empty `statements`: a body
that was in the source but did not reach the AST is not a stack. Not in
`to_dict()`. Anything that reasons per *arm* (business rules, program-flow
`BranchArm`s, constraints / scenarios) must iterate `when_groups()`, not
`when_clauses`; per-*phrase* walks (xref, unused variables, complexity's
decision count, diff) keep `when_clauses`.

**Expression trees (2026-07-20, M12; additive).**

* `ComputeStatement.expression_tree: CobolExpression | None` — structural
  decomposition of the COMPUTE expression (`set_expression_tree()`); the raw
  `.expression` string is unchanged. In `to_dict()` as `"expression_tree"`
  only when populated.
* `CobolExpression.condition_tree: CobolExpression | None` — structural
  decomposition of a raw condition (`set_condition_tree()`; also registered as
  a child for generic traversal). Used by PERFORM UNTIL: `until_condition`
  remains the `CobolExpression("CONDITION")` with the raw joined string in
  `operands`, and the tree rides alongside. In `to_dict()` as
  `"condition_tree"` only when populated.
* `SearchStatement.when_clauses[i]` holds `condition` text, `statements`, and,
  when one could be built, `condition_tree`, serialized by `to_dict()` (#348).
* Consumers (`ProgramFlowAnalyzer`, `coverage_analyzer`, backend extractors per
  `interface-contract.md`) need no changes — all historical fields/keys are
  untouched.

## Statement field reference

Fields that are easy to miss, grouped by node. Dates mark when a field started
being populated; the "previously" notes explain what consumers of older output
may still see.

**Arithmetic (`arithmetic.py`)**

* `ArithmeticStatement.targets: list[str]` — full ordered list of
  comma/space-separated `TO`/`FROM` targets (`ADD 1 TO a, b, c`); `.target`
  keeps the first (2026-07-22). `.givings: list[str]` likewise for `GIVING`
  (`ADD A TO B GIVING C, D`), `.giving` the first (2026-07-24); applies to
  ADD/SUBTRACT/MULTIPLY/DIVIDE alike.
* `.rounded: bool` (also on `ComputeStatement`) and `.is_corresponding: bool`
  (ADD/SUBTRACT `CORRESPONDING`).
* `MultiplyStatement`/`DivideStatement` format 1 (no `GIVING`) populate
  `.target`/`.targets`: `MULTIPLY x BY id-2, id-3` / `DIVIDE x INTO id-2, id-3`
  overwrite their second operand(s) in place. Format 2 (`GIVING`) deliberately
  does **not** set `.target` — the second operand there is a
  multiplicand/divisor, not a result.
* `DivideStatement.remainder: str | None` — the `REMAINDER r` target.
  `DivideStatement.division_mode: str | None` (2026-08-12) — `"BY"` or
  `"INTO"` as written, in `to_dict()`; the two forms invert dividend/divisor
  order, so this is what lets `const_fold` fold the unambiguous DIVIDE forms
  (see [analysis.md](analysis.md)).
* `ArithmeticStatement.source_operands: list[str] | None` (2026-09-27) -- the
  operands written before TO/FROM/GIVING, duplicates kept, set by the
  ADD/SUBTRACT parsers; `None` on a node built any other way. **Not
  serialized.** `operands` cannot stand in for it: `set_target`/`set_giving`
  append a name only when absent, so `ADD A B GIVING B` and `ADD A GIVING B`
  leave the same `[A, B]`. Read by `analysis/const_fold.py`.
* `on_size_error` / `not_on_size_error` lists can contain any statement type
  (registry-dispatched), all registered as AST children.
* See [parser.md](parser.md) "Statement-Support Verification Sweep" and
  "Follow-up comma-list sweep".

**CALL / ENTRY / INVOKE (`call.py`, `misc.py`)**

* `CallStatement.using_parameters` is a list of `CallParameter` (`name`,
  `passing_mode`); `passing_mode` persists across a comma-separated list
  within one `BY REFERENCE`/`BY CONTENT`/`BY VALUE` group (`CALL 'P' USING BY
  CONTENT a, b` tags both CONTENT; 2026-07-24).
* `EntryStatement.using_parameters` (names) plus a parallel `parameter_modes`
  list (`"REFERENCE"`/`"VALUE"`, serialized; #402).
* `InvokeStatement` — `object_name`, `method_name` + `method_is_literal`,
  `using_parameters` (reuses `CallParameter`), `returning_target`.
  `set_method_name(name, is_literal)` records the method name in `operands`
  unconditionally, matching `CallStatement.set_called_program()`.
* `AllocateStatement` — `is_characters`/`size_expr` (the `identifier-1
  CHARACTERS` form) xor `data_item` (the `BASED` data-item form),
  `initialized`, `returning_target`. `FreeStatement` — `pointer_names:
  list[str]`.

**Control (`control.py`)**

* `GoStatement.target_paragraphs` (all computed-GO-TO targets) alongside
  `target_paragraph` (the first) and `depending_on_variable`.
* `PerformStatement.after_clauses` — the AFTER dimensions of `PERFORM VARYING
  ... AFTER ...`, each `{"variable", "from_value", "by_value",
  "until_condition": CobolExpression | None}`, added by
  `add_after_clause(variable, from_value, by_value, until_condition=None)`
  (which registers the condition as a child); serialized only when non-empty.
* `StopStatement.returning` — `STOP RUN RETURNING x` return code.

**Data (`data.py`)**

* `UnstringStatement.tallying_variable` (`TALLYING IN counter`);
  `.delimiters` collects every `OR`-joined delimiter (2026-07-22).
* `SetStatement.groups` — additional `targets TO/UP/DOWN value` groups of a
  multi-group SET (serialized as `"groups"`); each group dict's
  `"value_is_entry"` key (2026-09-10) is that group's own `SET p TO ENTRY 'X'`
  flag (a later group's flag used to leak into the next group).
  `SetStatement.targets_are_address_of` (`SET ADDRESS OF x TO p`).
* `InitializeStatement.to_value_category: str | None` (`"ALL"` or a category
  name such as `"NUMERIC"`, from Enterprise COBOL 6's `{ALL | category} TO
  VALUE`) and `.to_default: bool` (`[THEN] TO DEFAULT`), both always in
  `to_dict()` (2026-09-28).

**I/O (`io.py`)**

* `IOOpenStatement.file_modes: dict[str, str]` (2026-07-22) — per-file open
  mode for `OPEN INPUT a OUTPUT b`, where `.open_mode` holds only the first
  mode group. `crud_matrix.py`, `io_logger.py` and `ast_diff.py` consult
  `file_modes` first and fall back to `open_mode`. Also `.no_rewind` /
  `.with_lock` / `.reversed_mode` (serialized `"no_rewind"` / `"with_lock"` /
  `"reversed"`).
* `IOWriteStatement.advancing_clause` — e.g. `{"type": "AFTER", "value": 2,
  "unit": "LINES"}` (not just `advancing_mode`). `unit` is `"CHANNEL"` for
  `ADVANCING PAGE` (`value="PAGE"`); `"LINES"` for `ADVANCING identifier
  LINES` (`value` is the data-name); `"MNEMONIC"` for a bare SPECIAL-NAMES
  mnemonic-name (`ADVANCING TOP-OF-PAGE` → `{"type": "AFTER", "value":
  "TOP-OF-PAGE", "unit": "MNEMONIC"}`).
* `IOWriteStatement.at_eop_clause` / `.not_at_eop_clause` (format 1,
  `[NOT] AT END-OF-PAGE`) and `invalid_key_clause` / `not_invalid_key_clause`
  (format 2) are all populated.
* `IORewriteStatement.from_clause` (`REWRITE rec FROM data`) and
  `IOStartStatement.key_name` (`START f KEY IS ... data-name`; `key_condition`
  holds the operator) are both also in `operands`.
* `IOAcceptStatement.environment_name` (`ACCEPT x FROM ENVIRONMENT "name"`);
  `.on_exception` / `.not_on_exception` (serialized only when present; their
  statements are registered as children).
* `ReleaseStatement.set_from_source()` / `ReturnStatement.set_into_target()`
  add the operand to `operands`, like `IOWriteStatement.set_from` /
  `IOReadStatement.set_into` (2026-09-28; an item used only as `RELEASE ...
  FROM x` was otherwise reported unused).

**FILE-CONTROL (`SelectStatement`, `misc.py`)**

* Populated by the ENVIRONMENT DIVISION parser: `alternate_keys`,
  `file_status_vsam`, `reserve_areas`, `padding_character`,
  `record_delimiter`, `password`, `lock_mode`/`lock_on`/`lock_with_rollback`,
  `sharing_mode`, `assign_device_type`.
* `assign_using` (2026-09-28): the data-name of `ASSIGN USING data-name` (also
  in `assign_to`), None for `ASSIGN TO`.
* `record_key_qualifiers` and each `alternate_keys` entry's `qualifiers`: the
  `OF`/`IN` names of `RECORD KEY IS K6 OF R6`, innermost first; `record_key` /
  `key` stay the bare data-name. `set_record_key(key, source=None,
  qualifiers=None)`, `add_alternate_key(key, duplicates_allowed=False,
  password=None, qualifiers=None)`. `file_status_qualifiers`,
  `file_status_vsam_qualifiers` and `relative_key_qualifiers` likewise.

**Other `misc.py` / `communication.py` nodes**

* `XmlJsonStatement` (`XmlJsonStatement(verb, action, location)`) models XML/JSON
  GENERATE/PARSE: `verb`, `action`, `primary_operand`, `from_item`, raw
  `clause_text` (non-handler clauses only), `processing_procedure` /
  `processing_procedure_thru` (XML PARSE's implicit PERFORM target and THRU
  end), `on_exception` / `not_on_exception` (serialized with `omit_empty`), and
  the structured clause names (2026-09-28) `count_in` (GENERATE's `COUNT
  [IN]`), `into_item` (JSON PARSE's receiving item) and `clause_items` (every
  `NAME OF` / `TYPE OF` / `SUPPRESS` / `CONVERTING` subject and `NAMESPACE` /
  `NAMESPACE-PREFIX` / `VALIDATING WITH` identifier) -- all three also in
  `.operands`. xref gives `count_in` / `into_item` role `write`,
  `clause_items` role `read`. `primary_operand` / `from_item` fold a trailing
  OF/IN chain or subscript.
* `UseStatement.report_groups` (`USE BEFORE REPORTING`).
* `ReceiveStatement`'s `no_data_clause` / `with_data_clause` register their
  statements as children, so the generic statement walk reaches them.

# See Also

* [parser.md](parser.md) — produces AST nodes
* [analysis.md](analysis.md) — consumes AST via analyzer interfaces
* [generators.md](generators.md) — record layouts and byte images built on `CobolDataItem` / `_storage.py`
* [dialects.md](dialects.md) — EXEC SQL / CICS / IMS detail
* Flow-model enums referencing these nodes (`FlowEdgeType.XML_PROCESSING_PROCEDURE[_THRU]`, `CICS_HANDLE`, `SQL_WHENEVER`; `FlowNode.is_declarative`) are in [analysis.md](analysis.md)
