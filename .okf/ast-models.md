---
type: Module
title: AST Models
description: ASTNode hierarchy — CobolProgram, data items, statement nodes, to_dict()/to_json() serialisation.
tags: [ast, models, cobol-program, data-items, statements]
timestamp: 2026-07-24T00:00:00Z
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

class ASTValidator: ...
```

# Program Structure (`models/program.py`)

```python
class CobolProgram(ASTNode):
    program_id: str
    divisions: list[CobolDivision]
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
  `omit_empty`).
* REPORT SECTION (2026-09-02): report groups are ordinary `CobolDataItem`
  trees under a `CobolSection("REPORT")`. Each 01-level group carries
  `metadata["rd_report_name"]` and `metadata["rd_clauses"]` (the RD's
  CODE/CONTROLS/PAGE LIMIT/HEADING/FIRST DETAIL/LAST DETAIL/FOOTING/GLOBAL as
  a mapping); every entry carries `metadata["report_clauses"]` for its
  TYPE/LINE/NEXT GROUP/COLUMN/SOURCE/SUM/GROUP INDICATE/PRESENT WHEN
  clauses. Anonymous entries (`01 TYPE IS DETAIL.`) get the existing
  `ANONYMOUS-<level>-<line>` name. See [parser.md](parser.md).
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
    picture_string: str      # e.g. "9(5)V99"
    category: DataCategory

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
  Worse, the marker is emitted **only when the range end is unsigned**:
  `88 X VALUE -5 THRU -1.` arrives as `["-5", "-1"]` with no `THROUGH:` at
  all, which is indistinguishable from two discrete values `VALUE -5, -1`.
  A signed *start* is fine (`VALUE -2 THRU 2` → `["-2", "THROUGH:2"]`), so
  the loss is specific to a signed endpoint. Confirmed 2026-08-02 against
  the DATA DIVISION parser; not fixed here, since correcting it changes an
  established `ConditionNameItem.values` shape that other consumers read.

`index_names` and `key_clauses` are serialized only when non-empty. Before
2026-07-09 `ASCENDING/DESCENDING KEY` was dropped and `INDEXED BY` kept only
its last name (and was lost entirely when a KEY clause preceded it). See
[parser.md](parser.md) Silent-Drop Audit (2026-07-09).

# SQL Statement Nodes (`models/sql_statements.py`)

AST nodes for EXEC SQL, EXEC CICS, and EXEC IMS DLI blocks captured by
`ibm_exec_statements.py`.

# Statement Models (`models/statements/`)

| File | Node Classes |
|------|-------------|
| `base.py` | `CobolStatement`, `CobolExpression`, `ArithmeticExpression`, `ConditionalExpression`, `LogicalExpression`, `FunctionCall` |
| `arithmetic.py` | `ArithmeticStatement`, `AddStatement`, `SubtractStatement`, `MultiplyStatement`, `DivideStatement`, `ComputeStatement` |
| `call.py` | `CallStatement`, `EntryStatement`, `CallParameter` |
| `communication.py` | `SendStatement`, `ReceiveStatement`, `EnableStatement`, `DisableStatement`, `PurgeStatement` (2026-09-02) |
| `control.py` | `IfStatement`, `EvaluateStatement`, `WhenClause`, `PerformStatement`, `GoStatement`, `StopStatement`, `SearchStatement`, `RaiseStatement`, `ResumeStatement` |
| `data.py` | `MoveStatement`, `DisplayStatement`, `InitializeStatement`, `InspectStatement`, `SetStatement`, `StringStatement`, `UnstringStatement`, `ValidateStatement` |
| `io.py` | `IOReadStatement`, `IOWriteStatement`, `IOOpenStatement`, `IOCloseStatement`, `IOAcceptStatement`, `IORewriteStatement`, `IODeleteStatement`, `IOStartStatement`, `IOUnlockStatement` |
| `legacy.py` | `ExhibitStatement`, `ExamineStatement`, `TransformStatement`, `EnterStatement`, `NoteStatement`, `ChainStatement`, `TraceStatement`, `ServiceStatement`, `TitleStatement` (2026-09-02) |
| `misc.py` | `SelectStatement`, `CopyStatement`, `ContinueStatement`, `NextSentenceStatement`, `EjectStatement`, `SkipStatement`, `ExitStatement`, `GobackStatement`, `CancelStatement`, `AlterStatement`, `GenerateStatement`, `ReleaseStatement`, `ReturnStatement`, `UseStatement`, `SortStatement`, `MergeStatement`, `CommitStatement`, `RollbackStatement`, `InvokeStatement`, `AllocateStatement`, `FreeStatement` |
| `report_writer.py` | `InitiateStatement`, `TerminateStatement`, `SuppressStatement` (2026-09-02) |

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
serialized as `"groups"`); `IOOpenStatement.no_rewind` / `.with_lock` /
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
* Arithmetic statements' `on_size_error` / `not_on_size_error` lists can
  contain any statement type (registry-dispatched), all registered as AST
  children (H1).

# ASTNodeFactory

```python
from cobolparser.core.ast_factory import get_factory, create_node

factory = get_factory()
# create_node takes the node CLASS (not a string) and the node's own
# constructor kwargs; location is passed positionally to the node.
node = create_node(MoveStatement, loc, source="WS-A", targets=["WS-B"])
```

Raises `NodeTypeError` for unknown node types, `FieldValidationError` for bad fields.

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
