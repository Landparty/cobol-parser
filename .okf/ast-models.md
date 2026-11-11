---
type: Module
title: AST Models
description: ASTNode hierarchy (cobolparser/models/) — CobolProgram and its program units, data items and byte sizing (_storage.py), SQL and statement nodes, to_dict()/to_json()/from_json() serialisation.
tags: [ast, models, cobol-program, data-items, statements]
timestamp: 2026-10-15T00:00:00Z
---

# AST Models

`cobolparser/models/` holds every AST node class the parser builds. Every node
extends `ASTNode` (`ast_base.py`) and implements `to_dict()`; `to_json()` is
`to_dict()` serialized. The root of a parse is a `CobolProgram`
(`ParseResult.ast`), whose tree is divisions -> sections -> paragraphs ->
statements (PROCEDURE DIVISION) or sections -> data items (DATA DIVISION).
Start with [Traversal and query helpers](#traversal-and-query-helpers) to walk a
tree, or [Data items](#data-items-modelsdata_itemspy) for byte layout.

| Module | Holds |
|--------|-------|
| `models/ast_base.py` | `SourceLocation`, `ASTNode`, `ASTValidator`, `ValidationResult` |
| `models/program.py` | `CobolProgram`, `CobolDivision`, `CobolSection`, `CobolParagraph`, `LossyDeserializationWarning` |
| `models/data_items.py` | `CobolDataItem`, `PictureClause`, `OccursClause`, `ConditionNameItem` (88), `RenamesItem` (66) |
| `models/sql_statements.py` | `ExecSQLStatement` and its subclasses, `parse_exec_sql()` |
| `models/statements/*.py` | every PROCEDURE DIVISION statement node, by category |
| `_storage.py` (package root) | `storage_size()` — the one authority on an item's byte width |

Getting started: `result = parse_cobol(src)`; walk `result.ast` with
`program_units()` / `get_all_statements()` / `get_data_items()` /
`find_all_by_type("MoveStatement")`, or dump it with `to_json()`.
`cobolparser.models` re-exports the commonly used classes (`__all__`: the base
classes, program/division/section, the data-item classes, the core statement
and SQL nodes, `LossyDeserializationWarning`, `parse_exec_sql`); everything
else imports from its own module. The parser builds nodes; to create one by
hand use `ASTNodeFactory` (see below) or the node's constructor.

## Contents

* [Base classes](#base-classes-modelsast_basepy)
* [Program structure](#program-structure-modelsprogrampy)
  * [Program-unit attributes](#program-unit-attributes)
  * [Program units](#program-units)
* [Serialization: `to_json()` / `from_json()`](#serialization-to_json--from_json)
* [Traversal and query helpers](#traversal-and-query-helpers)
* [ASTNodeFactory](#astnodefactory)
* [Data items](#data-items-modelsdata_itemspy)
  * [`PictureClause` sizing](#pictureclause-sizing)
  * [Shapes that surprise consumers](#shapes-that-surprise-consumers)
* [`calculate_size()` and `_storage.py`](#calculate_size-and-_storagepy)
* [SQL statement nodes](#sql-statement-nodes-modelssql_statementspy)
* [Statement models](#statement-models-modelsstatements)
  * [Nested statement bodies](#nested-statement-bodies)
  * [Stacked WHENs](#stacked-whens)
  * [Expression trees](#expression-trees)
  * [Statement field reference](#statement-field-reference)
* [See also](#see-also)

## Base classes (`models/ast_base.py`)

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
(whose `total_lines` comes from locations) does not take part. Comparing node
types and child counts alone is not enough: any two programs with the same
division count would be "equal" (see #273).

## Program structure (`models/program.py`)

```python
class CobolProgram(ASTNode):             # CobolProgram(program_name, location); node_type "Program"
    program_name: str                    # the PROGRAM-ID (CLI/JSON reports call it program_id)
    divisions: list[CobolDivision]       # property, from an internal name -> division dict
    identification_division / environment_division / data_division / procedure_division
    contained_programs: list[CobolProgram]
    unit_kind: str                       # "PROGRAM" | "CLASS" | "FACTORY" | "OBJECT" | "METHOD" | "FUNCTION"
    program_attributes: list[str]        # property: INITIAL / COMMON / RECURSIVE subset
    is_recursive: bool                   # property
    omitted_copy_lines: tuple[tuple[int, int], ...]  # (first, last) lines of COPY
                                         # statements left unexpanded; not serialized

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
`is_ims_dlitcbl_program`); `find_statements_using_variable`,
`get_statistics`, `validate`; and
`to_dict(config=None)` / `to_json(config_or_indent=None)` / `from_json()`.

`get_all_statements()` walks contained programs too, and reaches handler
bodies (INVALID KEY, ON EXCEPTION, ...) through `.children` plus the
canonical `NESTED_BODY_ATTRS` ([Nested statement bodies](#nested-statement-bodies));
the result is cached on the program (invalidated by `add_division`).

FD/SD entries have no node class of their own: each level-01 record under an
FD/SD carries `fd_file_name`, `fd_clauses` and `fd_record_type` metadata (see
[parser/divisions.md](parser/divisions.md#fd--sd-entries)).

### Program-unit attributes

* `unit_kind` -- `"PROGRAM"` (default; not serialized) or, for IBM
  object-oriented COBOL, `"CLASS"` / `"FACTORY"` / `"OBJECT"` / `"METHOD"`
  (serialized as `unit_kind`). A class contains its factory and object units,
  which contain their methods, all via `contained_programs`, so
  `program_units()` enumerates every method. `"FUNCTION"` is a user-defined
  function (`FUNCTION-ID`, Enterprise COBOL 6.4), a separately compiled unit
  like a stacked program. Identification-division metadata carries
  `unit_kind`, `inherits` and `program_attributes` (and `external_name` on a
  FUNCTION unit).
* `repository()` -- the CONFIGURATION SECTION `REPOSITORY` paragraph as a dict
  (`functions` / `intrinsic` / `all_intrinsic` / `classes`, see
  [parser/divisions.md](parser/divisions.md)), or None; `user_function_names()`
  lists the declared user-defined functions, uppercased.
* `program_attributes` (`["INITIAL", "COMMON", "RECURSIVE"]` subset, source
  order) and `is_recursive`.
* `CobolSection.is_declarative` (metadata `declarative`) for sections between
  `DECLARATIVES.` and `END DECLARATIVES.`.
* PROCEDURE DIVISION metadata `returning_parameter`.

### Program units

```python
ast.program_units()               # [self, *contained, recursively], source order
ast.find_program_unit("INNERP")   # CobolProgram | None, case-insensitive
```

A compilation unit can hold several programs — stacked or nested, delimited by
`END PROGRAM` — and the parse keeps them on `CobolProgram.contained_programs`
(serialized as `contained_programs`). Every analyzer in this package is
program-scoped (it grades a paragraph against the references it can see), so
analyzing a multi-program file means running the analyzer once per unit; these
two methods are how to reach the units, and back both
`LintAnalyzer`'s per-unit pass and the CLI's `--program NAME` (see
[cli.md](cli.md)). Pinned by `tests/regression/test_nested_program_units.py`.

The tree does not say how the units nest (every PROGRAM unit hangs off the
first); `enclosing_program` does (#532): the unit it is nested in, or None
for an outermost or *stacked* unit. `add_contained_program` defaults it to the
containing unit; the parser corrects it. `is_nested`, `nesting_depth`,
`is_common` (`PROGRAM-ID ... IS COMMON`) and `nested_program_called(name)`
(the nested unit a `CALL 'name'` in this unit reaches by COBOL scope: directly
nested, a COMMON one nested in an enclosing unit, or a nested unit's own name;
None = a separately compiled program) build on it. `to_dict()` writes
`enclosing_program` (a name, or null for stacked) only on a contained unit
whose nesting differs from the tree, and `from_json()` restores it
(`_restore_nesting()`, the nearest preceding unit of that name).

## Serialization: `to_json()` / `from_json()`

`CobolProgram.to_json()` exports the full tree as JSON (top-level keys
`node_type`, `program_name`, `divisions`, `contained_programs`, `location`,
`metadata`, plus `unit_kind` when not `"PROGRAM"`). Optional keys across the
node classes are mostly emitted only when non-empty, so adding a field keeps
older dict output byte-identical.

`CobolProgram.from_json()` is **not** its full inverse -- it restores a
structural skeleton (see #273):

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
  a round-tripped program matches the original. SELECTs are ENVIRONMENT
  DIVISION nodes: they are neither dropped nor counted as PROCEDURE DIVISION
  statements in the warning (see #346).
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

Serialized-shape facts:

* `CobolDataItem.to_dict()` serializes level-88 children as `condition_names`;
  `CobolSection.to_dict()` serializes level-66 children as `renames_items`.
* `CallStatement.to_dict()` serializes `not_on_exception`, and CALL handler
  statements are registered as AST children so `find_all_by_type()` agrees
  with `get_all_statements()`.
* `CobolExpression.to_dict()` includes `operands`, so condition/expression
  text (e.g. PERFORM UNTIL conditions) reaches the JSON.

## Traversal and query helpers

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

**Dialect query helpers.** `has_sql()` / `has_cics()` / `has_ims()`
and `get_sql_statements()` / `get_cics_statements()` /
`get_ims_statements()` classify through `program._exec_kind()`: any
`sql_statements.ExecSQLStatement` (so `FetchStatement`,
`DeclareCursorStatement`, `TransactionControlStatement`, ... too) is SQL, and
`statement_type` `"EXEC CICS"` (parser) or `"EXEC-CICS"` (dialect nodes) is
CICS, likewise IMS. Both spellings must be accepted: parsed statements carry
the spaced one, so testing `"EXEC-CICS"` alone answers False for every real
CICS / EXEC DLI program. `get_statistics()["statement_count"]` counts `CobolStatement`
instances, `EXEC_CICS` / `EXEC_IMS` included; `procedure_count` counts only
PROCEDURE DIVISION sections and paragraphs (a node whose `division_name` is
another division -- WORKING-STORAGE, LINKAGE, ... -- is not one, #508).
`to_dict()["metadata"]["parser_version"]` is `cobolparser.__version__`, and
there is no `created_at`: the JSON of one input is byte-identical run to run
(`from_json` still skips a `created_at` from older output). `find_statements_using_variable(name)`
matches a whole COBOL word, case-insensitively, outside quoted literals (not a
substring: `WS-A` does not match `WS-AMOUNT`). Intrinsic-function and LE
usage is `LanguageEnvironmentAnalyzer`'s job; `CobolProgram` no longer
imports any analyzer, so `models` stays below `analysis`.

**`models/walk.py`** -- the shared traversal API: `all_paragraphs(division)`
(every PROCEDURE DIVISION paragraph, top-level and in sections, each once, in
source order; the unnamed leading paragraph included; `None` -> `[]`),
`section_paragraphs(division)` (the same, paired with the owning section's
upper-cased name or `None`), `own_statements(unit)` (a unit's statements
without its contained programs', #274), and re-exports of `walk_statements` /
`iter_clause_bodies`. Analyzers, generators and the MCP server use these
instead of private copies. `RedundancyAnalyzer._collect_paragraphs` keeps
its own sections-first order on purpose: clone-group membership order is
pinned by its tests.

## ASTNodeFactory

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
no location / node_type. Keyword arguments go to the node's constructor, so
they must be parameters it actually takes.

## Data items (`models/data_items.py`)

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
                                     #               decimal_point_is_comma=False,
                                     #               currency_signs=None)
    pattern: str                     # as written, e.g. "9(5)V99"
    size: int | None                 # BYTES, not character positions
    integer_digits / decimal_digits / total_digits: int | None
    is_signed, is_edited, is_numeric_edited, is_alphanumeric_edited,
    is_national, is_national_edited, is_valid: bool
    has_scaling_factor: bool; scaling_factor: int; scaling_leading: bool | None
    currency_symbols: frozenset[str]; decimal_point_is_comma: bool
    currency_signs: dict[str, str]   # symbol -> its CURRENCY SIGN string

class OccursClause(ASTNode):         # OccursClause(location)
    min_times: int | None
    max_times: int | None      # == min_times for a fixed OCCURS n; None for UNBOUNDED
    is_unbounded: bool         # OCCURS UNBOUNDED / OCCURS n TO UNBOUNDED (#402)
    depending_on: str | None
    depending_on_qualifiers: list[str]
    indexed_by: str | None     # first index (backward-compatible)
    index_names: list[str]     # all INDEXED BY names
    key_clauses: list[dict]    # {"direction": "ASCENDING"|"DESCENDING",
                               #  "keys": [...]} — SEARCH ALL keys

class ConditionNameItem(ASTNode):    # level 88: name, values, false_value,
                                     # value_kinds ("string"/"numeric"/"figurative"/
                                     # "all" per values entry; not serialized)
class RenamesItem(ASTNode):          # level 66: name, renames_from, renames_through
```

`index_names` / `key_clauses` are filled whichever order the source writes
the INDEXED BY and KEY phrases in (#542).

Serialization: `index_names`, `key_clauses` and `depending_on_qualifiers` are
serialized only when non-empty, `is_unbounded` only when True; every data
item's `to_dict()` carries `calculated_size` (below) and `is_elementary_item`.
`is_volatile`, `byte_length` (`set_byte_length` also sizes the PICTURE),
`is_dynamic_length` + `dynamic_length_limit`, `object_class`
(`set_object_reference`; usage `"OBJECT REFERENCE"`) and `group_usage`
(`GROUP-USAGE NATIONAL|UTF-8`) are each serialized only when set.
`usage_explicit` is not serialized.

**Inherited USAGE / SIGN.** `usage_explicit` is True when the
entry carries its own USAGE (`set_usage` / `set_object_reference`). `usage` /
`sign_clause` of a subordinate with no clause of its own reflect the enclosing
group's (see parser.md, `data.py`), so `calculate_size()` counts packed/binary
children of a `COMP-3`/`BINARY` group correctly. `set_picture_clause` gives an
entry with no USAGE clause the usage its picture implies -- `NATIONAL` for
`N`, `DISPLAY-1` for `G` (IBM default `NSYMBOL(NATIONAL)`); `usage_explicit`
stays False and a later USAGE clause still wins.

**Implicit FILLER (#404).** Outside a REPORT SECTION group, an
entry with no data-name (`05 PIC X(3).`, FILLER omitted) keeps the synthetic
`ANONYMOUS-<level>-<line>` `name` but has `is_filler=True`.
`CobolDataItem.layout_name` is `"FILLER"` for every filler item and `name`
otherwise; record layouts (`layout/fields.py`, `layout/offsets.py` / `data-items`,
`program_layout.py`) name and path items by it, so gen-data drops the column
and lineage keys it positionally like `05 FILLER`. Unnamed report-group
entries stay non-filler.

**REPORT SECTION.** Report groups are ordinary `CobolDataItem`
trees under a `CobolSection("REPORT")`. Each 01-level group carries
`metadata["rd_report_name"]` and `metadata["rd_clauses"]` (the RD's
CODE/CONTROLS/PAGE LIMIT/HEADING/FIRST DETAIL/LAST DETAIL/FOOTING/GLOBAL as a
mapping); every entry carries `metadata["report_clauses"]` for its
TYPE/LINE/NEXT GROUP/COLUMN/SOURCE/SUM/GROUP INDICATE/PRESENT WHEN clauses.
Anonymous entries (`01 TYPE IS DETAIL.`) get the `ANONYMOUS-<level>-<line>`
name. See [parser.md](parser.md).

**`ConditionNameItem.false_value: str | None`** -- the literal of
a level-88 `WHEN SET TO FALSE [IS] literal` phrase (a sign folded into a
numeric literal as in `values`: `"-0"`; a figurative constant by name:
`"SPACE"`), `None` when absent. Always present in `to_dict()`.

**OCCURS parsing.** The OCCURS clause walk that populates `OccursClause`
(`data_clauses._parse_occurs_clause`) handles real-deck line splits (count/`TO`/`BY` starting a
continuation line) and comma-separated `INDEXED BY` / `KEY` name lists.
The count read is guarded (`_peek_count_token`): a LEVEL_NUMBER reached only by crossing a line break counts
only when the clause visibly continues after it, so a malformed `OCCURS` with
no count cannot swallow the next item's own level number as a fabricated table
size (an unguarded read fabricates a phantom data item while recording
`max_times == 0`). See [parser.md](parser.md).

### `PictureClause` sizing

`size` is a **byte** count — it is what `calculate_size()`, `data-items`
offsets and record images are built from.

* `PIC N(n)` (national) and `PIC G(n)` (DBCS) are **2 bytes per character**.
* `PIC U(n)` (UTF-8, fixed character-length) is **4 bytes per character**:
  `size == 4n`, and `utf8_characters == n` keeps the character count
  (`FieldSpec.character_positions` reads it). `PIC U BYTE-LENGTH n` (fixed
  byte-length) is `size == n`, `utf8_characters is None`. Sizing `U(n)` at n
  bytes put every later offset 3n short (#554).
* P-scaled pictures (`9(3)PPP`, `SVPP9(3)`) are sized by their stored `9`s (3
  bytes) while `integer_digits`/`decimal_digits` include the `P` positions
  (6/0 and 0/5). `scaling_leading: bool | None` records the P
  run's direction -- `True` for `PPP9(3)` (leading, a fraction), `False` for
  `9(3)PPP` (trailing, a scaled integer), `None` when not P-scaled -- the one
  place this is decided; `layout/fields.py`'s
  `FieldSpec.scaling_positions`/`stored_digits` read it (and `total_digits`)
  directly, and `analysis/move_type_checker.py`'s `_is_non_integer_picture`
  reads `decimal_digits` alone. See [generators.md](generators.md)'s P-scaling
  note and [analysis.md](analysis.md)'s MoveTypeChecker section.
* Floating-insertion strings (`$$$,$$9`, `$Z,ZZ9`) count their leftmost symbol
  as the sign/currency, not a digit.
* Simple insertion `B`/`0` make a picture edited and count one byte each
  (`999B99` is 6, `0009` 4, `XXBXX` 5) -- unless the pattern
  also holds characters no PICTURE may contain, which keeps the lenient
  fallback. An edited picture with a `V` (`Z(3)V99`, 5 bytes) is sized by the
  edited path, not the 9s-only `V` split.
* Unedited pictures are sized after expanding every repeat factor
  (`_parse_plain_pattern`): `X(2)X(3)` is 5, `AAX(2)` 4, `9(2)9(3)` 5 digits,
  `NN` 4 bytes. Counting only the last repeat factor undersizes them.
* **National.** `is_national` (an `N` or national-edited picture)
  and `is_national_edited` (`N` with `B`/`0`/`/`: `N(2)BN` is 8 bytes, not 4,
  and not numeric-edited).
* **`currency_symbols`**: the non-`$` currency symbols a
  `SPECIAL-NAMES CURRENCY SIGN` declares that occur in the pattern
  (`PIC £££9.99`). The pattern is sized and validated through its `$`
  spelling, then `pattern` is restored as written; the set is also
  `metadata["currency_symbols"]` when non-empty. The DATA DIVISION passes it
  through `DataItemClauseParser._picture_clause`, from the non-`$` CURRENCY tokens
  `parse_picture_clause` saw; without them `£` is an invalid PICTURE character.
  **`currency_signs`** maps each of them to its declared currency string
  (`{"#": "EUR"}`, from `parser.currency_signs`), so the record-image editor
  knows what the position shows; `metadata["currency_signs"]` when non-empty,
  restored by `from_json` (#491). A string of n characters fills the one
  position that shows it, so `size` is n - 1 more than the `$` spelling's
  (`'CHF '` with `PIC FFFF,FF9.99`: 14, not 11). A letter symbol is added by
  `_picture_clause` from the pattern itself (it is not a CURRENCY token).
* **`decimal_point_is_comma`**: `SPECIAL-NAMES. DECIMAL-POINT IS
  COMMA` -- `,` is the decimal point and `.` a simple insertion character.
  Sized and validated through the default spelling (`,`/`.` exchanged,
  alongside the currency `$` translation), then `pattern` is restored as
  written: `9(3),99` is size 6, 3 integer + 2 decimal digits; `Z.ZZ9,99` is 4 +
  2. Also `metadata["decimal_point_is_comma"]`.
  `DataItemClauseParser._picture_clause` reads it off the host
  (`CobolParser.decimal_point_is_comma`, set from the lexer).

### Shapes that surprise consumers

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
  `["-5", "THROUGH:-1"]`, distinct from `VALUE -5, -1` → `["-5", "-1"]`),
  and so does a figurative end (`VALUE LOW-VALUE THRU HIGH-VALUE` →
  `["LOW-VALUE", "THROUGH:HIGH-VALUE"]`; before #468 the marker was dropped
  and the range read as two values). `ALL` is never a range end.

## `calculate_size()` and `_storage.py`

`CobolDataItem.calculate_size()` reports the bytes an item occupies, every
OCCURS occurrence included. It is published as `calculated_size` on every data
item's `to_dict()` (so it reaches the backend adapter in the AST JSON) and as
the record `size` of `gen-data --list-records`.

It defers to `cobolparser._storage.storage_size(usage, *, picture_size,
total_digits, sign_clause=None, is_signed=False, national_picture=False)` —
the same single authority `layout/{fields,offsets}.py` and `generators/data/encoding.py`
use. `_storage.py` also holds `binary_byte_length()`, `packed_byte_length()`,
the usage sets (`PACKED_USAGES`, `BINARY_FIXED_USAGES`, `BINARY_NATIVE_USAGES`,
`BINARY_USAGES`, `SINGLE_FLOAT_USAGES` / `DOUBLE_FLOAT_USAGES` /
`FLOAT_USAGES`, `POINTER_USAGES`, `PICTURELESS_USAGES`) and the fixed widths
(`INDEX_BYTES` 4, `POINTER_BYTES` 4 for `POINTER` / `POINTER-32` /
`FUNCTION-POINTER` / `OBJECT REFERENCE`, `PROCEDURE_POINTER_BYTES` 8 — IBM:
two words, `POINTER_64_BYTES` 8). COBOL 2002 words (#524): `FLOAT-SHORT` /
`FLOAT-LONG` are in the single / double float sets; `FIXED_SIZE_USAGES` sizes
`FLOAT-EXTENDED` 16, `BINARY-CHAR` 1, `BINARY-SHORT` 2, `BINARY-LONG` 4,
`BINARY-DOUBLE` 8. `KNOWN_USAGES` / `is_known_usage()` name every USAGE
word the package can size; any other word is warned about by the parser and
reported by the layout paths (an unknown word still falls through to the
DISPLAY/PICTURE arithmetic).

Never give `calculate_size()` its own copy of the byte arithmetic: a private
copy drifts (usage spellings such as `BINARY` / `COMPUTATIONAL-3` missed,
PICTURE-less `COMP-1`/`COMP-2`/`INDEX` sized 0, a REDEFINES added to what it
redefines, OCCURS ignored on groups, `SIGN IS SEPARATE` without its byte), and
every wrong number lands in a published API.

Rules worth knowing:

* `USAGE NATIONAL` on a numeric / numeric-edited picture is 2 bytes per
  position (`PIC 9(5) NATIONAL` = 10). A signed national decimal item always
  pays a separate sign of one national character (2 bytes): it cannot carry an
  overpunched sign, and with the SIGN clause omitted IBM assumes `SIGN IS
  TRAILING SEPARATE CHARACTER`, so `PIC S9(5) USAGE NATIONAL` is 12; pinned in
  `tests/regression/test_bug_hunt_2026_10_08.py`.
* A DISPLAY item with `SIGN IS SEPARATE` gets the extra byte its PICTURE
  character count does not include.
* Group layout follows `layout.offsets._layout_siblings`' **slot** rule (a
  contiguous run of `[base, redefiner, …]` costs its largest member); the
  OCCURS multiplier applies to groups as well as elementary items; level-66
  and level-77 children are excluded. Helpers: `_occurrence_size()` /
  `_occurs_multiplier()` / `_direct_data_children()`.
* **Group vs. elementary (#345):** `is_elementary_item()` is True
  for a childless item that has a PICTURE *or* a usage that never takes one
  (`_storage.PICTURELESS_USAGES`: `COMP-1`/`COMP-2` and their
  `COMPUTATIONAL-n` spellings, `INDEX`, the `POINTER` family, `OBJECT
  REFERENCE`), so `get_elementary_items()` and `to_dict()`'s
  `is_elementary_item` include them. A childless item with neither (e.g. a
  group whose subordinates are missing) is neither group nor elementary --
  deliberately not guessed elementary.

Under `OCCURS ... DEPENDING ON`, `calculate_size` and `layout.offsets`
both reserve the **maximum** (what IBM allocates and what `gen-data`'s
record images hold); every offset after the table is `offset_ambiguous`.

**Why `_storage.py` sits at the package root**, next to `_errors.py` and for
the same reason: the models (layer 2) need it as well as
`cobolparser.layout` and the record encoders above it, so it must import
nothing from the package.

## SQL statement nodes (`models/sql_statements.py`)

AST nodes for EXEC SQL blocks: `ExecSQLStatement` (extends `CobolStatement`)
and its subclasses `DeclareCursorStatement`, `DeclareTableStatement`,
`FetchStatement`, `DynamicSQLStatement`, `TransactionControlStatement`, plus
`SQLStatementInfo`, `SQLStatementType` (string constants), `DB2ColumnDefinition`
and the factory `parse_exec_sql(sql_text, location)`. The EXEC CICS / EXEC IMS
nodes (`ExecCicsStatement` / `ExecImsStatement`) live with their parsers in
`parsers/statements/ibm_exec_statements.py` (see
[Statement models](#statement-models-modelsstatements)).

* `ExecSQLStatement.tables` holds full, qualified names (`BANK.ACCOUNT`,
  `LOC.SCHEMA.TABLE`); the FROM/INTO/UPDATE/JOIN regexes match qualified names
  (`_SQL_TABLE_NAME`). A regex stopping at the first `.` would report every
  qualified table's schema as a table too. `#`, `@` and `$` are name
  characters there, first one included (`T#TAB`, `SCH#.T@B`): a regex
  stopping at them added a truncated phantom table, listed first (#770). A DB2 delimited identifier
  (`FROM "PROD"."CUST"`) is listed unquoted, verbatim (`PROD.CUST`); see
  [dialects.md](dialects.md#delimited-identifiers) (#597).
* `MERGE INTO tgt USING src ...` has `sql_type == "MERGE"`; `tables` lists the
  target first, then the `USING` source table or the tables its `USING
  (SELECT ...)` subquery reads (a `USING (VALUES ...)` source adds none). A
  statement led by common table expressions (`WITH x AS (...) SELECT ...`)
  takes the type of its main verb, and `tables` lists the base tables the CTE
  bodies and main statement read -- never the CTE names themselves
  (`_split_common_table_expressions()`).
* `TRUNCATE [TABLE] t [DROP|REUSE STORAGE] ... [IMMEDIATE]` has
  `sql_type == "TRUNCATE"` (`SQLStatementType.TRUNCATE`) and `tables == [t]`
  (`_SQL_TRUNCATE_TABLE_RE`); the CRUD matrix marks `t` D (see #341).
* `into_variables` / `DynamicSQLStatement.using_variables` list every host
  variable of the INTO / USING list, indicators included.
* A structure-qualified host variable (`:DCLEMP.EMPNO`) is listed by its last
  component (`EMPNO`).
* `FetchStatement.cursor_name` / `fetch_direction` / `fetch_count` are read
  positionally for DB2 scroll and rowset FETCHes.
* `DeclareTableStatement.table_name` is `"SCHEMA.TABLE"` for a qualified
  declaration.

See [dialects.md](dialects.md) for the SQL details.

## Statement models (`models/statements/`)

| File | Node Classes |
|------|-------------|
| `base.py` | `CobolStatement`, `CobolExpression`, `ArithmeticExpression`, `ConditionalExpression`, `LogicalExpression`, `FunctionCall`; `ClauseBody`, `iter_clause_bodies`, `walk_statements` and the nested-body attribute lists |
| `arithmetic.py` | `ArithmeticStatement`, `AddStatement`, `SubtractStatement`, `MultiplyStatement`, `DivideStatement`, `ComputeStatement` |
| `call.py` | `CallParameter`, `CallStatement`, `EntryStatement` |
| `communication.py` | `SendStatement`, `ReceiveStatement`, `EnableStatement`, `DisableStatement`, `PurgeStatement` (private base `_EnableDisableStatement`) |
| `control.py` | `IfStatement` (`ended_by_end_if`, `period_after_end_if`: how it ended, not serialized), `EvaluateStatement`, `WhenClause`, `PerformStatement`, `GoStatement`, `StopStatement`, `SearchStatement`, `RaiseStatement`, `ResumeStatement` |
| `data.py` | `MoveStatement`, `DisplayStatement`, `InitializeStatement`, `InspectStatement`, `SetStatement`, `StringStatement`, `UnstringStatement`, `ValidateStatement` |
| `io.py` | `IOReadStatement`, `IOWriteStatement`, `IOOpenStatement`, `IOCloseStatement`, `IOAcceptStatement`, `IORewriteStatement`, `IODeleteStatement`, `IOStartStatement`, `IOUnlockStatement` (mixin `InvalidKeyClauseMixin`) |
| `legacy.py` | `ExhibitStatement`, `ExamineStatement`, `TransformStatement`, `EnterStatement`, `NoteStatement`, `ChainStatement`, `TraceStatement`, `ServiceStatement`, `TitleStatement` |
| `misc.py` | `SelectStatement`, `CopyStatement`, `ContinueStatement`, `NextSentenceStatement`, `EjectStatement`, `SkipStatement`, `ExitStatement`, `GobackStatement`, `CancelStatement`, `AlterStatement`, `GenerateStatement`, `XmlJsonStatement`, `ReleaseStatement`, `ReturnStatement`, `UseStatement`, `SortStatement`, `MergeStatement`, `CommitStatement`, `RollbackStatement`, `InvokeStatement`, `AllocateStatement`, `FreeStatement` |
| `report_writer.py` | `InitiateStatement`, `TerminateStatement`, `SuppressStatement` (private base `_ReportNameListStatement`) |

Every statement node has `statement_type` (e.g. `"MOVE"`) and `operands`
(the data names it touches, appended via `_add_unique_operand()`; identifier
discovery — unused-variables, xref — reads `operands`, which is why most
fields below are also added there). `ExecCicsStatement` / `ExecImsStatement`
(`parsers/statements/ibm_exec_statements.py`) also extend `CobolStatement`
(`statement_type` `"EXEC CICS"` / `"EXEC IMS"`, `node_type` `"EXEC_CICS"` /
`"EXEC_IMS"`) so `get_all_statements()` returns them.

### Nested statement bodies

`models/statements/base.py` owns the **one** list of attributes that hold a
nested statement body; no analyzer keeps its own (ten private copies had
drifted -- RECEIVE's `NO DATA` / `WITH DATA`, `NOT AT END-OF-PAGE` and SEARCH
WHEN bodies were each missed somewhere -- the same drift behind the old
paragraph-swallow bugs; audit 2026-09-27 §3.5). Exported from
`cobolparser.models.statements`:

| Name | Holds |
|------|-------|
| `BRANCH_BODY_ATTRS` | `then_statements`, `else_statements` |
| `LOOP_BODY_ATTRS` | `inline_statements` |
| `HANDLER_CLAUSE_PAIRS` | (positive, negative) handler pairs: AT END, INVALID KEY, AT END-OF-PAGE, ON SIZE ERROR, ON OVERFLOW, ON EXCEPTION, NO DATA / WITH DATA |
| `HANDLER_CLAUSE_ATTRS` / `HANDLER_CLAUSE_PHRASES` | the pairs flattened / attribute -> COBOL phrase (`"AT END-OF-PAGE"`) |
| `WHEN_ARM_ATTRS` | `when_clauses`, `default_when` (EVALUATE `WhenClause` nodes, SEARCH `{"condition", "statements"}` dicts) |
| `STATEMENT_LIST_ATTRS` / `NESTED_BODY_ATTRS` | every `list[CobolStatement]` attribute / those plus the WHEN arms |

`iter_clause_bodies(stmt, *, include_handlers=True, include_loops=True,
include_empty=False)` (also `CobolStatement.iter_clause_bodies()`) yields
`ClauseBody(attr, kind, statements, position, clause)` in source order: IF
arms, inline PERFORM, handlers, WHEN arms (`position` 1-based, `clause` the
`WhenClause` / dict), WHEN OTHER. `kind` is `"branch"`, `"loop"` or
`"handler"`. Empty lists are skipped unless `include_empty`; a None
attribute never yields. `CobolStatement.iter_child_statements()` flattens
one level; `walk_statements(statements, *, include_handlers=True,
include_loops=True)` is the iterative depth-first walk (each node once).
A walker that needs more context (constraints' arm chain, ast_diff's paths,
complexity's pair counting) iterates `iter_clause_bodies` itself rather than
copying the list. A new clause body is a one-line change here;
`tests/unit/test_statement_bodies.py` fails until a statement node's
statement-list attribute is listed (static annotation scan plus every
statement the sample corpus parses into).

The `communication.py` / `legacy.py` / `report_writer.py` modules plus
`RaiseStatement`/`ResumeStatement` and `ValidateStatement` back the
COBOL-85 Communication, legacy, Report Writer and COBOL 2002 exception verbs;
`InvokeStatement`/`AllocateStatement`/`FreeStatement` back
`invoke_parser.py`/`allocate_free_parsers.py` (see [parser.md](parser.md)).

**`NextSentenceStatement`** (`statement_type` `"NEXT-SENTENCE"`)
backs `NEXT SENTENCE`. Deliberately its own node rather than reusing
`ContinueStatement`: NEXT SENTENCE transfers control past the rest of the
current sentence, not a true fall-through no-op.

### `WhenClause.condition_trees`

Parallel to `selectors`: for a `Condition` selector (`WHEN A > 1 AND B =
'X'`), the structural tree the IF machinery builds from its tokens, else
None. Not part of `to_dict()` (the selector dict keeps its documented
shape); the constraint extractor reads a compound `EVALUATE TRUE` WHEN
from it.

### Stacked WHENs

`WHEN 'A' WHEN 'B' stmt` parses into one
`WhenClause` per WHEN phrase, so `when_clauses[0]` has no statements; the
statements after the last WHEN belong to every WHEN of the stack (see #314). The AST
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

### Expression trees

Additive to the raw strings:

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

### Statement field reference

Fields that are easy to miss, grouped by node.

**Arithmetic (`arithmetic.py`)**

* `ArithmeticStatement.targets: list[str]` — full ordered list of
  comma/space-separated `TO`/`FROM` targets (`ADD 1 TO a, b, c`); `.target`
  keeps the first. `.givings: list[str]` likewise for `GIVING`
  (`ADD A TO B GIVING C, D`), `.giving` the first; applies to
  ADD/SUBTRACT/MULTIPLY/DIVIDE alike.
* `.rounded: bool` (also on `ComputeStatement`) and `.is_corresponding: bool`
  (ADD/SUBTRACT `CORRESPONDING`). `.rounded` is the back-compat "ROUNDED on
  some receiver" flag; `.rounded_targets: list[str]` names the receivers that
  carry it and `.rounding_modes: dict[str, str]` their `ROUNDED MODE IS`
  mode (both in `to_dict()` only when non-empty). `rounding_of(receiver)`
  answers `""` / `"ROUNDED"` / `"ROUNDED MODE IS m"` -- every receiver for a
  node built with only `rounded` set. Shared mixin `_Rounding` (#517):
  `COMPUTE B ROUNDED C` and `COMPUTE B C ROUNDED` store different values.
* `MultiplyStatement`/`DivideStatement` format 1 (no `GIVING`) populate
  `.target`/`.targets`: `MULTIPLY x BY id-2, id-3` / `DIVIDE x INTO id-2, id-3`
  overwrite their second operand(s) in place. Format 2 (`GIVING`) deliberately
  does **not** set `.target` — the second operand there is a
  multiplicand/divisor, not a result.
* `DivideStatement.remainder: str | None` — the `REMAINDER r` target.
  `DivideStatement.division_mode: str | None` — `"BY"` or
  `"INTO"` as written, in `to_dict()`; the two forms invert dividend/divisor
  order, so this is what lets `const_fold` fold the unambiguous DIVIDE forms
  (see [analysis.md](analysis.md)).
* `ArithmeticStatement.source_operands: list[str] | None` -- the
  operands written before TO/FROM/GIVING, duplicates kept, set by the
  ADD/SUBTRACT parsers and by MULTIPLY/DIVIDE's GIVING form (both operands,
  #495); `None` for MULTIPLY/DIVIDE format 1 and on a node built any other way. **Not
  serialized.** `operands` cannot stand in for it: `set_target`/`set_giving`
  append a name only when absent, so `ADD A B GIVING B` and `ADD A GIVING B`
  leave the same `[A, B]`. Read by `analysis/const_fold.py`.
* `on_size_error` / `not_on_size_error` lists can contain any statement type
  (registry-dispatched), all registered as AST children.
* Parsing details: [parser.md](parser.md).

**CALL / ENTRY / INVOKE (`call.py`, `misc.py`)**

* `CallStatement.using_parameters` is a list of `CallParameter` (`name`,
  `passing_mode`); `passing_mode` persists across a comma-separated list
  within one `BY REFERENCE`/`BY CONTENT`/`BY VALUE` group (`CALL 'P' USING BY
  CONTENT a, b` tags both CONTENT).
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
* `ContinueStatement` — `delay_expression` (text of `CONTINUE AFTER expr
  SECONDS`, else `None`; in `to_dict()` only when set) and
  `delay_expression_tree` (not serialized), #578.
* `CancelStatement` — `program_names` and the parallel
  `program_names_literal: list[bool]` (`CANCEL 'X'` vs `CANCEL X`, #479;
  serialized only when some name is a literal).

**Control (`control.py`)**

* `GoStatement.target_paragraphs` (all computed-GO-TO targets) alongside
  `target_paragraph` (the first) and `depending_on_variable`.
* `PerformStatement.after_clauses` — the AFTER dimensions of `PERFORM VARYING
  ... AFTER ...`, each `{"variable", "from_value", "by_value",
  "until_condition": CobolExpression | None}`, added by
  `add_after_clause(variable, from_value, by_value, until_condition=None)`
  (which registers the condition as a child); serialized only when non-empty.
  BY is optional (COBOL 2002, GnuCOBOL): omitted, `by_value` is `"1"` and the
  phrase's clause dict (`varying_clause` or that `after_clauses` entry)
  carries `"by_implied": True`.
* `StopStatement.returning` — `STOP RUN RETURNING x` return code.

**Data (`data.py`)**

* `UnstringStatement.tallying_variable` (`TALLYING IN counter`);
  `.delimiters` collects every `OR`-joined delimiter.
* `StringStatement.groups` — `[{"sources": [...], "delimiter": d}]`, which
  sources each `DELIMITED BY` applies to (serialized as `"groups"`, #576);
  the flat `operands` / `delimiters` stay for compatibility.
* `SetStatement.groups` — additional `targets TO/UP/DOWN value` groups of a
  multi-group SET (serialized as `"groups"`); each group dict's
  `"value_is_entry"` key is that group's own `SET p TO ENTRY 'X'`
  flag (kept per group so one group's flag cannot leak into the next).
  `SetStatement.targets_are_address_of` (`SET ADDRESS OF x TO p`).
* `InitializeStatement.to_value_category: str | None` (`"ALL"` or a category
  name such as `"NUMERIC"`, from Enterprise COBOL 6's `{ALL | category} TO
  VALUE`) and `.to_default: bool` (`[THEN] TO DEFAULT`), both always in
  `to_dict()`.

**I/O (`io.py`)**

* `IOOpenStatement.file_modes: dict[str, str]` — per-file open
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
  `IOReadStatement.set_into`, so an item used only as `RELEASE ... FROM x` is
  not reported unused.

**FILE-CONTROL (`SelectStatement`, `misc.py`)**

* Populated by the ENVIRONMENT DIVISION parser: `alternate_keys`,
  `file_status_vsam`, `reserve_areas`, `padding_character`,
  `record_delimiter`, `password`, `lock_mode`/`lock_on`/`lock_with_rollback`,
  `sharing_mode`, `assign_device_type`.
* `assign_using`: the data-name of `ASSIGN USING data-name` (also
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
  the structured clause names `count_in` (GENERATE's `COUNT
  [IN]`), `into_item` (JSON PARSE's receiving item) and `clause_items` (every
  `NAME OF` / `TYPE OF` / `SUPPRESS` / `CONVERTING` subject and `NAMESPACE` /
  `NAMESPACE-PREFIX` / `VALIDATING WITH` identifier) -- all three also in
  `.operands`. xref gives `count_in` / `into_item` role `write`,
  `clause_items` role `read`. `primary_operand` / `from_item` fold a trailing
  OF/IN chain or subscript.
* `UseStatement.report_groups` (`USE BEFORE REPORTING`).
* `ReceiveStatement`'s `no_data_clause` / `with_data_clause` register their
  statements as children, so the generic statement walk reaches them.

## See also

* [parser.md](parser.md) — produces AST nodes
* [analysis.md](analysis.md) — consumes AST via analyzer interfaces
* [generators.md](generators.md) — record layouts and byte images built on `CobolDataItem` / `_storage.py`
* [dialects.md](dialects.md) — EXEC SQL / CICS / IMS detail
* Flow-model enums referencing these nodes (`FlowEdgeType.XML_PROCESSING_PROCEDURE[_THRU]`, `CICS_HANDLE`, `SQL_WHENEVER`; `FlowNode.is_declarative`) are in [analysis.md](analysis.md)
* [history](history/ast-models.md) — archived dated notes (field introduction dates, the `calculate_size()` rewrite, audit write-ups)
