---
type: Module
title: Data Use, IO and Call Analyzers
description: How a program uses its data, files and CALL targets -- UnusedVariableAnalyzer, XrefAnalyzer, MoveTypeChecker, LinkageChecker, IOLogger, IOSequenceAnalyzer, CRUDMatrixGenerator, DynamicCallAnalyzer (value_tracker.py), the IO coverage/diagnostics helpers, and the shared name helpers (_names.py, _files.py).
tags: [analysis, unused-variables, xref, move-type, linkage, io, io-sequence, crud, dynamic-call, value-tracker]
timestamp: 2026-10-16T00:00:00Z
---

# Data Use, IO and Call Analyzers

The analyzers that answer questions about *data items, files and CALL
targets*: which items are never referenced, where each symbol is read or
written (xref), illegal MOVEs, CALL/LINKAGE mismatches, file-operation
sequencing, the CRUD matrix, and the possible values of a dynamic CALL target.
Most share one reference-collection machinery that lives in
`unused_variables.py` and the name helpers in `_names.py`; start with [Data
names and references](#data-names-and-references), then the analyzer you need.
Calling conventions shared by every analyzer are in
[../analysis.md](../analysis.md).

## Contents

* [Data names and references](#data-names-and-references)
* [UnusedVariableAnalyzer](#unusedvariableanalyzer)
* [XrefAnalyzer](#xrefanalyzer)
* [MoveTypeChecker](#movetypechecker)
* [LinkageChecker](#linkagechecker)
* [IOLogger](#iologger)
* [IOSequenceAnalyzer](#iosequenceanalyzer)
* [CRUDMatrixGenerator](#crudmatrixgenerator)
* [DynamicCallAnalyzer](#dynamiccallanalyzer)
* [IO coverage and diagnostics helpers](#io-coverage-and-diagnostics-helpers)
* [See also](#see-also)

## Data names and references

### Same-named data items (see #258)

Two records routinely carry the same field names (`CUST-ID OF IN-REC` /
`CUST-ID OF OUT-REC`); analyzers must not key them by bare name (the
procedure half of the rule is in [flow.md](flow.md)).

- **Data items** — `_extract_identifiers` (unused_variables.py) returns
  references with their qualifiers, spelled `"AMT OF IN-REC"` (`IN` is
  normalized to `OF`), plus each qualifier as its own reference
  (`_names.qualified_references`; `_names.bare_names` recovers plain
  tokens). `_NameMatcher` resolves them: qualifiers must name enclosing
  items in ascending order (levels may be skipped); an unqualified
  reference to a shared name, or qualifiers matching no candidate (a
  file-name qualifier), count for every candidate. REDEFINES resolves to
  the same-named *sibling* first. `UnusedVariableItem.qualified_name`
  (`"AMT OF OUT-REC"`, full enclosing chain) is set for shared names.
  `XrefAnalyzer` gives each same-named item in a *different* record its
  own `XrefEntry` with `qualified_name` (`entry_for` accepts it); the same
  chain declared twice (a copybook COPYed into two sections) is still a
  `duplicate_declarations` entry. `ProgramSignatureExtractor` keys field
  directions by `qualified_name` where xref set one. Procedure xref
  entries are still name-keyed.

### Folded-reference normalization: `_names.base_data_name`

Statement parsers fold `OF`/`IN` qualifier chains and `( subscript )`
groups into single operand strings. `analysis/_names.py::base_data_name`
recovers the referenced item's own name (first word, split off only when
followed by OF/IN or `(` — literals with spaces and `ALL 'X'` pass through
unchanged). Used by `MoveTypeChecker._resolve_category` (catalog lookup)
and `DynamicCallAnalyzer`'s MOVE source/target keying (a bare `CALL
WS-PROG` must find values MOVEd to `WS-PROG OF GRP-1`). Any new analyzer
keying data items by bare name needs it too. Pinned by
`tests/regression/test_folded_reference_analyzers.py`.

### Identifier tokens: `_names.IDENTIFIER_TOKEN_RE`

`IDENTIFIER_TOKEN_RE` accepts a digit-led user word (`1ST-NAME`, IBM-legal as
long as a letter is present) and refuses to start inside another word or after
a decimal point (so `1.5E+3` yields no `5E`). A letter-led pattern bites the
digit off, so `MOVE 1ST-NAME TO 2ND-NAME` would reference `ST-NAME` /
`ND-NAME`. It takes **whole words**: a token may not start right after a
hyphen either, and a digit run may be followed by a hyphen, so `1000-INIT`
is one token (a paragraph name, matching no data item) -- the old
pattern could not match it from its first character and took the tail
`INIT`, so `PERFORM 1000-INIT` "used" data item `INIT` in unused-variables,
lint and xref (#487). unused-variables also skips a statement's
procedure-name operands (`_procedure_operands`: PERFORM target / THRU, GO TO
targets, ALTER, SORT/MERGE procedures), so `PERFORM INIT` does not use a data
item `INIT` either; xref already resolves those by role. Pinned by
`tests/regression/test_digit_led_paragraph_tail_issue_487.py`.
Shared with `redundancy.py`'s clone renaming; the sibling
`RELAXED_IDENTIFIER_TOKEN_RE` (used by `boundary_inventory.py`'s `EVALUATE
TRUE` selector scan) also accepts a token starting with a digit.

### CALL candidates: `_names.callee_names`

`DynamicCallAnalyzer`'s `possible_values` keeps every literal MOVEd to the CALL
identifier, figuratives included (SPACES / LOW-VALUES / HIGH-VALUES as `" "` /
`"\x00"` / `"\xff"`, ZERO as `"0"`) -- the "no program" sentinel a dispatcher
tests before its CALL. `callee_names()` strips those bytes and quotes, drops
anything empty or all-digit, and is the one filter `field_lineage`, `codebase`
(codebase-graph), `recursion_risk` and `boundary_inventory` share, so none of
them invents a `\x00` / `0` / `Ÿ` callee, and a CALL whose only candidates are
sentinels is reported unresolved. The `possible_values` JSON itself keeps the
sentinels.

### FD record to file: `_files.py`

`record_to_file_map()` / `resolve_file_name()` are the one FILE SECTION
`fd_file_name`-metadata walk that `crud_matrix.py`, `io_logger.py` and
`io_sequence.py` all use. `resolve_file_name()` returns a direct `file_name`
argument verbatim (case preserved, for `io_logger`'s human-readable report);
`CRUDMatrixGenerator` upper-cases the result itself since its entries are keyed
by upper-case name.

`same_record_area_groups(ast)` reads the INPUT-OUTPUT section's
`io_control` metadata and returns the files of each `SAME RECORD AREA`
clause (upper-cased, groups sharing a file merged). Their records share one
storage area across FDs, so `const_fold._link_file_records` and
`FieldFlowAnalyzer._redefines_edges` alias them like the records of one FD
(#497). Plain `SAME AREA` / `SAME SORT[-MERGE] AREA` share no records and are
not returned.

## UnusedVariableAnalyzer

```python
report: UnusedVariableReport = UnusedVariableAnalyzer().analyze(ast)
# report.unused_items: list[UnusedVariableItem]  (name/level/section/location/from_copybook)
```

Detects DATA DIVISION items (FILE/WORKING-STORAGE/LOCAL-STORAGE/LINKAGE,
any level, FILLER and synthetic `ANONYMOUS-<level>-<line>` names always
excluded) never referenced anywhere in the PROCEDURE DIVISION. Reports the
items of the unit it is given only (it does not report a contained
program's items); a contained program's references still count, but only
for the container's `GLOBAL` items (`_nested_referenced_names`) -- or for
every item of an OO FACTORY/OBJECT unit, see below.

**Reference collection is `.operands`-first, with per-statement-type
extras.** Every `CobolStatement` already accumulates most of its own
identifier/literal tokens into `.operands` via `_add_unique_operand`/
`add_operand`, but an empirical audit (grepping every statement model's
setters) found real gaps where a setter never reaches `.operands` at all:
`ExecSQLStatement.host_variables`/`.null_indicators` (SQL statements don't
touch `.operands` at all), `UnstringStatement.source_operand`/
`.into_targets`/`.pointer_variable`/`.tallying_variable`,
`StringStatement.into_target`/`.pointer_variable`,
`InspectStatement.tallying_clauses`/`.replacing_clauses`/
`.converting_from`/`.converting_to`, `SearchStatement.table_name`/
`.varying_variable`, `SortStatement.keys`/`MergeStatement.keys` (the
`"field"` key), and `PerformStatement.varying_clause`/`.after_clauses`
(`"variable"`/`"from_value"`/`"by_value"`). All handled via the module-level
`_STR_ATTR_EXTRAS`/`_DICT_LIST_EXTRAS` lookup tables plus explicit
per-type branches in `_collect_referenced_names`, rather than trusting
`.operands` alone. The tables are looked up by walking `type(stmt).__mro__`,
not exact type — an exact-type lookup would silently lose a keyed
statement class's extras the moment any real subclass of it existed (none
do today, but the failure mode is exactly the "used field reported
unused" bug this module exists to avoid), pinned by
`TestExtrasLookupIsMroAware` in `tests/unit/analysis/test_unused_variables.py`.

**An operand string is tokenized, not treated as one opaque name.** Statement
parsers routinely join a whole qualified reference, subscript, special
register, or intrinsic function call into a *single* operand string
(`MoveStatement.source` for `MOVE WS-A OF WS-GRP TO ...` is `"WS-A OF
WS-GRP"`; `"FUNCTION UPPER-CASE(WS-X)"` and `"LENGTH OF WS-X"` are the same
shape), so adding the operand verbatim would leave `WS-A` / `WS-GRP` / `WS-X`
falsely unused. `_extract_identifiers` is the single extraction path for every
operand/extra-field/condition-fallback value:
it strips quoted substrings, regex-extracts every identifier-shaped token
(`_names.IDENTIFIER_TOKEN_RE`, shared with `redundancy.py`'s clone-detection
renaming and `boundary_inventory.py`'s `EVALUATE TRUE` selector-text read
scan -- the latter uses the sibling `RELAXED_IDENTIFIER_TOKEN_RE`, which
also accepts a token starting with a digit, harmless there since a match is
only ever looked up against a name map), and filters `_NON_IDENTIFIER_WORDS` (figurative constants merged with
qualification/special-register/intrinsic-function keywords `OF`/`IN`/
`FUNCTION`/`LENGTH`/`ADDRESS` and the raw-condition-text stopwords). A
bare numeric literal never matches at all since a token must contain a
letter, so no separate numeric/quoted-literal pre-check is needed. Deliberately
over-inclusive in the same direction as the condition-text fallback
below: a stray token (an intrinsic function name, say) only risks
coincidentally matching an unrelated declared item, never causes a used
item to be reported unused. Pinned by `TestQualifiedAndFunctionOperands`
in `tests/unit/analysis/test_unused_variables.py`.

**Condition/expression trees are walked separately from `.operands`.**
`IfStatement.condition`, `PerformStatement.until_condition`/
`after_clauses[].until_condition`, and `ComputeStatement.expression_tree`
never reach `.operands` (confirmed: `IfStatement.set_condition` only calls
`add_child`, matching `program_flow/condition_text.py`'s note that the raw
condition text/tree lives entirely off the statement). `_walk_expression_operands`
mirrors `render_condition_text`'s dispatch (`LogicalExpression` ->
recurse both sides; `ConditionalExpression`/`ArithmeticExpression` ->
`left_operand`/`right_operand`; `FunctionCall` -> `arguments`) but collects
leaf identifiers instead of rendering text, falling back to a best-effort
regex over `operands[0]`/`raw_condition` for a node shape it can't
decompose structurally (`EVALUATE TRUE` Condition-type selectors, and
SEARCH WHEN conditions that carry no `condition_tree`, per `constraints.py`'s same documented gap — see
[ConstraintExtractor](fixtures-support.md)). The fallback is deliberately
over-inclusive: a false positive there only makes the analyzer *miss* an
unused variable, never wrongly flag a used one. A node carrying a
`condition_tree` (a PERFORM UNTIL guard, whose `operands` hold only the raw
joined text) is walked through the tree, so a SPECIAL-NAMES class-name in
`UNTIL X IS NOT VALID-CODE` is not read as a data item (#539). A condition node the builder could not decompose (no operands, only
`metadata.raw_condition`, e.g. `X EXCEEDS Y`) is read from that raw text, so
walking the tree loses no field the guard names.

**EVALUATE subjects and `Literal`-typed WHEN selectors.** `evaluate_parser.py`
routes each subject through `add_subject()`, so string subjects reach
`.operands` and every generic `.operands` consumer sees them (see
[../parser.md](../parser.md)). This module still walks `stmt.subjects`
explicitly: `add_subject()` sends a `CobolExpression` subject to `add_child()`,
never `add_operand()` (models/statements/control.py), so the explicit walk (via
the shared `_names_from_value` dispatch helper, also used for `FunctionCall`
arguments and `ConditionalExpression`/`ArithmeticExpression` operands) is the
only coverage for expression-shaped subjects; the string double-count is a
harmless set union. `_build_selector` classifies a bare data-name (or level-88
condition-name) WHEN selector as `{"type": "Literal"}` -- it never emits
`"Identifier"`, a fact constraints.py's EVALUATE handling also relies on -- so
`_selector_identifiers` scans `Literal` values too. Caveat (documented in
`_selector_identifiers`'s TODO): selector values arrive with string-literal
quotes already stripped (the unquoted shape is pinned -- see parser.md's
blank-literal passage), so literal contents that coincidentally match a
declared name mark it used -- the accepted over-inclusive direction.
`_walk_expression_operands`'s opaque-shape fallback scans every
`expr.operands` entry, not just `operands[0]`. All pinned by
`TestEvaluateSubjects` in `tests/unit/analysis/test_unused_variables.py`
(each parsed-source test carries a deliberately-unused positive-control
item so the negative assertions can never pass vacuously).

**References held outside `.operands`** are read explicitly: `PERFORM P WS-N
TIMES` (`times_count`), `WRITE ... AFTER ADVANCING WS-N LINES`
(`advancing_clause["value"]`), `INITIALIZE ... REPLACING ... BY WS-ZERO`
(`replacing_clauses[].by_value`, via `_DICT_LIST_EXTRAS`), `XML GENERATE doc
FROM group` / `JSON PARSE doc INTO group` (every subordinate, by name, through
`_whole_group_references`, which also folds in the CALL USING marking), EXEC
SQL host variables and null indicators (`_sql_host_variable_names`, #531: DB2
reads/writes a host structure one column per field and a VARCHAR group
through both 49-levels, so the whole subtree is used; the program's own DATA
DIVISION EXEC SQL, e.g. a WORKING-STORAGE DECLARE CURSOR, is read too, #378.
Pinned by `tests/regression/test_sql_host_structure_unused_issue_531.py`), and
`MOVE / ADD / SUBTRACT CORRESPONDING A TO B` (`_corresponding_pairs` +
`_mark_corresponding_used`: only the same-named subordinates of the two groups;
the others keep their own standing). An INITIALIZE target's fields stay
assessed, like `MOVE SPACES TO group`. Pinned by
`tests/regression/test_bug_hunt_2026_10_08.py`.

**Group items, level-88s, REDEFINES, and OCCURS DEPENDING ON are
structural, not textual, dependencies.** A group item counts as used if
any descendant field is used (post-order `is_used()` over `item.children`);
a level-88 `ConditionNameItem` child being referenced (`IF ORDER-VALID`)
marks its parent elementary item used too. `X REDEFINES Y` marks `Y` used
whenever `X` is used (propagated to a fixpoint for REDEFINES chains,
resolved by uppercased name via a `by_name` index — not structural item
identity, a documented limitation for the rare case of duplicate
same-named items at different qualification scopes). An `OCCURS ...
DEPENDING ON` variable is unconditionally marked used via
`_collect_data_division_references`, since it's a real runtime dependency
even when never touched procedurally. Level-66 RENAMES targets
(`renames_from`/`renames_through`) are marked used the same
unconditional way.

**Copybook provenance is set-difference, not line-tracking.** `analyze()`
takes an optional `copybook_item_names: set[str]` the caller computes by
diffing `collect_declared_items()` on an *unexpanded* parse against the
expanded one -- see the `unused-variables` CLI subcommand
(`_parse_without_copybook_expansion` in `cli/parse.py`; `lint` reuses it via
`_lint_copybook_item_names`) for the reference implementation. The expansion
source map (`CopybookExpansion.source_location_map` /
`ParseResult.expansion_source_map`, see
[../preprocessing.md](../preprocessing.md)) could answer the same question,
but the analyzer and CLI use the set difference, which works.
`include_copybook_variables=False` then excludes any
unused item in that set from `report.unused_items` (tallied instead in
`report.skipped_copybook_count`); the flag is a documented no-op when
`copybook_item_names` is None.

**SCREEN / REPORT / COMMUNICATION SECTION items are out of scope.**
`collect_declared_items` reads only FILE / WORKING-STORAGE / LOCAL-STORAGE /
LINKAGE (`_DATA_SECTION_NAMES`). The DATA DIVISION parser skips SCREEN and
COMMUNICATION SECTION content (`_skip_section`) and parses REPORT SECTION RDs
and report groups into a `REPORT` section, which this analyzer ignores, so
report-group items are never reported unused. The fields a report group
names (`SOURCE`, `SUM`, the RD's `CONTROL(S)`) *are* references:
`UnusedVariableAnalyzer.report_entry_operands(data_div)` lists each entry
with its operand texts, and both this analyzer and xref read it (xref records
each at its entry with statement `"REPORT SECTION"`, #571). The RD is no node
-- the parser copies its clauses onto every 01 group it owns -- so its
CONTROLS are taken once per report, at the first group.

**Known limitations are tagged inline.** Each limitation called out in the
class docstring carries a `TODO(known limitation)` comment so a `grep` sweep
finds it: `_DATA_SECTION_NAMES` (SCREEN/REPORT/COMMUNICATION out of scope),
the `SearchStatement` branch and `_selector_identifiers`'s `"Condition"` case
(SEARCH WHEN / EVALUATE TRUE regex-only fallback), and the `redefines_edges`
comment in `analyze()` (REDEFINES/OCCURS-DEPENDING-ON/RENAMES resolved by
name, not structural identity; REDEFINES prefers the same-named sibling).

**EXEC CICS/DLI arguments are swept explicitly.** `ExecCicsStatement.options`
(option keyword -> parenthesized argument text) and
`ExecImsStatement.arguments` (positional list) are raw text the operand loop
cannot decompose, so a sweep after that loop (one `traverse_depth_first()` of
the unit, skipping contained programs' nodes, matching by type *name* to avoid
an analysis -> parsers import) extracts identifiers from them. Both classes
are `CobolStatement`s, so the per-statement loop also visits them and the
sweep is a harmless set union -- a new analyzer does not need to reproduce it.
See `TestExecCicsAndImsArguments` in `test_unused_variables.py`.
The CICS sweeps here, in xref and in `LinkageChecker` read options through
`_cics.cics_identifier_options()`, which drops every option the parser put in
`literal_options`: the quotes are stripped from `options`, so
`FILE('CUSTFIL')` would otherwise reference a data item named `CUSTFIL`
(#588, `tests/regression/test_issue_588_cics_literal_options.py`).

**CICS translator items.** The `DFHEIBLK` subtree is marked used and the
`DFHCOMMAREA` 01 is used (its fields stay assessed): the translator declares
all 30-odd EIB fields, which would bury the real findings of every CICS
program.

**OO FACTORY / OBJECT data is shared with its METHODs** (see #379). A
contained unit's references normally count only for the container's GLOBAL
items. In IBM OO COBOL, though, the data of a FACTORY or OBJECT paragraph is
visible to every METHOD in it with no GLOBAL clause, so when `ast.unit_kind`
is in `_OO_DATA_OWNERS` every item is matched against
`_nested_referenced_names(ast)` too; instance data only methods touch is not
reported unused. Factory and object scopes stay separate: an OBJECT method's
reference does not use a FACTORY item of the same name. The whole-group rules
(`_whole_group_references`: CALL USING, XML/JSON GENERATE/PARSE, SQL host
variables) and
`_corresponding_pairs` read the methods' statements too
(`_all_contained_units`), since the FACTORY/OBJECT unit has none of its own.
Known gap, shared with the GLOBAL path: a method-local item that shadows an
instance item still credits the instance item. See
`TestObjectOrientedUnitData`.

CLI: `unused-variables` subcommand — see [cli.md](../cli.md).

## XrefAnalyzer

The classic mainframe compiler cross-reference: for every symbol a program
declares — data items, level-88 condition names, files, paragraphs and
sections — where it is *defined* and every place it is *referenced*, each
reference carrying its location, the statement it sits in, the enclosing
paragraph, and the **role** it plays there.

**Roles by statement.** Each mapping below gives the operand its real
read/write role; `program_signature.py` grades LINKAGE directions and
`business-rules` lists inputs/outputs from them.

* **Arithmetic.** With GIVING, only the GIVING/REMAINDER items are `write`; the
  TO/FROM operand is `read` (`SUBTRACT A FROM B GIVING C` does not write B).
  Without GIVING, the TO/FROM/BY/INTO target is both `read` and `write`
  (`ADD 1 TO X`). Sending operands come from
  `ArithmeticStatement.source_operands` (ADD/SUBTRACT) or the first two
  operands (MULTIPLY/DIVIDE with GIVING), so `ADD A B GIVING B` keeps B's
  read. MULTIPLY/DIVIDE without GIVING read the first operand plus *every*
  BY/INTO receiver (`MULTIPLY 3 BY A B` is `A = A * 3; B = B * 3`; reading
  only `operands[:2]` graded B write-only -- #534, pinned by
  `tests/regression/test_multiply_divide_receivers.py`). Pinned by
  `test_xref.py::test_giving_leaves_the_from_operand_unwritten` and
  `test_program_signature.py::test_accumulated_and_giving_operands_get_the_right_direction`.
* **Counters, pointers, in-place targets** (see #269). Operands a statement
  advances or rewrites from their current value are both `read` and `write`:
  an INSPECT TALLYING counter, STRING / UNSTRING `WITH POINTER`, UNSTRING
  `TALLYING IN`, and the inspected item of INSPECT REPLACING / CONVERTING /
  TALLYING ... REPLACING (the item of a plain INSPECT TALLYING stays `read`;
  UNSTRING `COUNT IN` / `DELIMITER IN` stay `write`). Pinned by
  `test_xref.py::test_counters_pointers_and_inspect_targets_are_read_write` and
  `test_program_signature.py::TestDirection::test_counters_pointers_and_inspected_items_are_input_output`.
* **RELEASE / RETURN.** `RELEASE rec FROM x` (record and `x` read) and `RETURN
  sd-file INTO x` (file-operation on the SD, `x` write) have dedicated role
  mappings; the model setters add `FROM`/`INTO` to `.operands` like READ INTO /
  WRITE FROM, so `UnusedVariableAnalyzer` sees `x` too.
* **ALLOCATE / FREE** (#570). `ALLOCATE item [INITIALIZED] RETURNING p`
  records `item` as `reference` (its address is set, not its bytes) and `p`
  as `write`; the `ALLOCATE n CHARACTERS` size is `read`; every `FREE p`
  pointer is `write` (set to NULL). Pinned by
  `tests/regression/test_issue_570_allocate_based_linkage.py`.
* **CONTINUE AFTER n SECONDS** (#578). The delay's operands are `read`
  (from `ContinueStatement.delay_expression_tree`, or the text inexactly);
  `UnusedVariableAnalyzer` reads `delay_expression` via `_STR_ATTR_EXTRAS`.
* **Reference modifiers.** A reference modifier's offset/length names are kept
  apart from the operand (`_split_operand`) and recorded `read` when the
  operand itself is a `write`: `MOVE A TO WS-B (WS-P:2)` does not write WS-P.
  `_partition_operand` still folds them into the base names for its other
  callers.
* `WRITE ... ADVANCING WS-N LINES` records a `read` of WS-N.

This is the natural completion of `unused_variables.py`. That analyzer answers
"is this name referenced at all?" with a flat `set[str]`; this one keeps the
locations and roles that set throws away, so "unused" becomes "fully
cross-referenced". Its reference-collection machinery is *reused*, not
re-derived: `_extract_identifiers`, `_walk_expression_operands`,
`_names_from_value`, `collect_declared_items` and the `_STR_ATTR_EXTRAS` /
`_STR_LIST_EXTRAS` / `_DICT_LIST_EXTRAS` tables all come from there.

```python
from cobolparser.analysis.xref import XrefAnalyzer

report = XrefAnalyzer().analyze(ast)          # XrefReport
report.entries                # list[XrefEntry], data items first (_KIND_ORDER)
report.entry_for("WS-COUNT")  # XrefEntry | None, case-insensitive
report.entries_of_kind("paragraph")
report.total_references
report.undefined              # referenced, never declared
report.caveats                # what could only be recovered approximately
report.duplicate_declarations # declared more than once in one namespace
```

`XrefEntry`: `name`, `kind`, `definition` (`SourceLocation | None`),
`references`, `level`, `section`, `qualified_name` (set only for a name
declared in more than one record, issue #258), plus `reference_count` / `is_referenced`.
`XrefReference`: `location`, `role`, `statement`, `context` (the enclosing
paragraph).

**Kinds** (`KIND_*`): `data-item`, `condition-name`, `paragraph`, `section`,
`file`.

**Roles** (`ROLE_*`): `write`, `read`, `condition`, `subscript`, `perform`,
`goto`, `call-argument`, `host-variable`, `file-operation`, and `reference`
when the role itself could not be determined.

Things worth knowing before trusting a field:

* **Single-program scope**, like `DeadCodeAnalyzer` and
  `UnusedVariableAnalyzer`: only *ast* itself. Contained programs are AST
  children and are skipped in every sweep (`_contained_node_ids`) — otherwise
  a nested program's statements would read as the outer unit's references.
  Call `analyze()` separately per unit.
* **GLOBAL items cross the unit boundary** (#504). A contained unit also
  defines the records its containers make visible --
  `unused_variables.inherited_data_records(ast)`: each enclosing program's
  `GLOBAL` 01/77 records (all of a FACTORY / OBJECT unit's data for its
  METHODs), innermost first, a name the unit or a nearer container declares
  hiding a farther one -- at their own declaration line, so `DISPLAY A` in
  the inner unit resolves instead of reading as `undefined`. The outer unit
  folds in its contained programs' references to its *own* items
  (`_collect_contained_references`: each direct child cross-referenced on
  its own, its entries matched to the outer's by item identity), so `A`
  lists the inner read too. The same helper scopes lineage
  ([lineage.md](lineage.md)) and MoveTypeChecker; `collect_declared_items`
  itself stays the unit's own items (it is what unused-variables reports).
  Pinned by `tests/regression/test_issue_504_global_items_in_contained_programs.py`.
* **Level-88s under a FILLER and level-66 RENAMES items are declared**
  (#485). `collect_declared_items` drops every FILLER, but
  `_collect_data_definitions` still walks a FILLER for its `ConditionNameItem`
  children (the `05 FILLER PIC X. 88 SW-ON ...` switch idiom) and its
  `INDEXED BY` names, and declares each section's `RenamesItem` children as
  `data-item`, level 66. All in source order, so the first declaration of a
  name still wins. Before, they read as `undefined` in `xref`, as
  `declared: false` / `found: false` in MCP `explain_symbol`, and as "not
  declared ... not traced" in the `lineage` caveats.
* **SELECT clause items are references at the SELECT** (#549, #556).
  `_visit_select_clauses` records FILE STATUS (both items), RECORD KEY (and
  its `SOURCE IS`), each ALTERNATE RECORD KEY and its PASSWORD, RELATIVE
  KEY, PASSWORD, ASSIGN USING and PADDING CHARACTER items with role
  `reference`, the same set `UnusedVariableAnalyzer._file_control_references`
  counts as used (a literal `PADDING CHARACTER IS '*'` names nothing). The
  roles a READ / START gives the keys are unchanged. Pinned by
  `tests/regression/test_issue_549_556_select_clause_references.py`.
* **Digit-led paragraph names resolve.** Procedure names (PERFORM / GO TO
  targets) are credited verbatim and `_COBOL_WORD_RE` allows a leading digit
  provided there is at least one letter, so `1000-INIT` is one symbol rather
  than a number and a word.
* **`undefined` excludes special registers.** `_SPECIAL_REGISTERS`
  (RETURN-CODE, SQLCODE, SQLCA, `EIB*`, `DFH*`, `XML-*`/`JSON-*`, TALLY,
  the Report Writer PAGE-COUNTER / LINE-COUNTER a `SOURCE` names, …)
  are never reported undefined; a caveat names the ones that were seen.
  `is_special_register(name)` is the public test (the MCP `explain_symbol`
  answers a not-found special register with it).
* **STRING operands are inexact** — the parser strips literal quotes, so a
  literal word and a data name are indistinguishable there. Reported, with a
  caveat.
* **`duplicate_declarations` is a correctness warning for consumers.** Every
  reference is attributed to the *first* declaration, so nothing downstream may
  grade *which* declaration was touched. A copybook COPYed into both
  WORKING-STORAGE and LINKAGE is the common shape.
* Nothing is guessed: where a role, location or identifier was only
  approximately recoverable the reference is still reported (role
  `"reference"`) and the approximation is appended to `caveats`.

Backs the `xref` CLI subcommand, which additionally appends the parser's
unexpanded-COPY warnings to `caveats` — a member the parser could not expand
leaves every field it declares looking undeclared. Tests: `tests/unit/analysis/test_xref.py`.

## MoveTypeChecker

```python
report: MoveTypeReport = MoveTypeChecker().check(ast)
# report.violations: list[MoveTypeViolation]
# report.unresolved_count: int   -- MOVE operands whose DataCategory could
#                                    not be resolved (undeclared identifier,
#                                    unexpanded copybook, ...); serialized
#                                    in report.to_dict()
# report.unresolved_function_count: int -- the part of unresolved_count no
#                                    copybook can fix: a FUNCTION source with
#                                    a NATIONAL result or an uncatalogued name
# MoveTypeViolation: kind/source_name/target_name/source_category/
#                    target_category/location/message
# MoveViolationKind: ERROR | WARNING   (the severity; what is wrong is the
#                    DataCategory pair: NUMERIC, NUMERIC_EDITED, ALPHABETIC,
#                    ALPHANUMERIC, ALPHANUMERIC_EDITED, FIGURATIVE, UNKNOWN)
```

Detects MOVE statements with type-incompatible sending/receiving fields based on
PICTURE clause categories.

**One unit's catalog and MOVEs** (#504). `_build_catalog` and `_check_moves`
stop at a contained `CobolProgram`: walking into one let an inner namesake
(`01 WS-X PIC X(3)`) make the outer `WS-X PIC 9(3)` ambiguous, so the outer
MOVE went unresolved, and the outer report carried the inner unit's MOVEs.
The catalog also takes the GLOBAL records of the enclosing programs
(`inherited_data_records`), so a MOVE to a container's GLOBAL field is
checked in the contained unit. lint checks every unit, so nothing is lost.

**MOVE CORRESPONDING is expanded into its pairs** (see #383) by the IBM rule
(same name path below the two groups, at least one of the two elementary;
FILLER, level 66/77/88, REDEFINES, OCCURS and INDEX/POINTER subordinates --
and what is under a REDEFINES/OCCURS item -- excluded, mirroring
`field_lineage._corresponding`), and each pair is checked like an ordinary
MOVE; skipping CORR moves would read as a clean all-clear. Violations name the
pair qualified (`AMT OF GRP-A` → `AMT OF GRP-B`). An operand that does not
resolve to exactly one declared *group* (undeclared, ambiguous without
qualifiers, elementary) adds one to `unresolved_count` per receiving operand;
a paired item with no category this checker models adds one per pair. Pinned
by `test_move_type_checker.py::TestMoveCorrespondingPairs`.

**Intrinsic FUNCTION sources** (see #291). The result category comes from
`dialects.le_signatures.intrinsic_signature(name).returns`:
`alphanumeric` → ALPHANUMERIC, `integer` → integer NUMERIC, `numeric` →
NUMERIC whose integer-ness is *unknown* (`None`: NUMVAL("12") is an integer,
NUMVAL("1.5") is not). SUM / REM / RANGE / MAX / MIN / ABS take their
integer-ness from their arguments by one rule: non-integer if any argument
is, an integer if all are, unknown otherwise. TRIM / ABS / USUBSTR / MAX /
MIN take their first argument's category;
UPPER-CASE / LOWER-CASE / REVERSE are ALPHANUMERIC only when their argument
resolves (a national argument gives a national result). A reference-modified
result (`FUNCTION CURRENT-DATE(1:8)`) is ALPHANUMERIC. A nested `FUNCTION
x(...)` argument is one argument. So `MOVE FUNCTION NUMVAL(X) TO` a `PIC A`
item is an error, but to a `PIC X` item it is skipped, never a guessed
error. What stays unchecked because of the function itself (NATIONAL-OF, an
uncatalogued name, a numeric result of unknown integer-ness into an
alphanumeric receiver, UPPER-CASE / TRIM / ... of a declared PIC N item) is
also counted in `unresolved_function_count`, and lint words that caveat
separately without the `--copybook-path` hint (the COPY was never missing); an
unresolved *argument* is still an ordinary unresolved operand. Pinned by
`test_move_type_checker.py::TestIntrinsicFunctionsWithArguments` /
`TestNumericFunctionIntegerness` and `test_lint.py::TestCaveats`.

**Special registers** (see #520). Their category is fixed by the language,
and none is ever a DATA DIVISION item, so `_resolve_category` knows them by
name after the catalog lookup (a declared item of the same name still wins):
`_NUMERIC_SPECIAL_REGISTERS` (RETURN-CODE, TALLY, LINAGE-COUNTER,
SORT-RETURN, SORT-CORE-SIZE, SORT-FILE-SIZE, SORT-MODE-SIZE, XML-CODE,
JSON-CODE) are integer NUMERIC, `_ALPHANUMERIC_SPECIAL_REGISTERS`
(WHEN-COMPILED, SORT-CONTROL, SORT-MESSAGE) ALPHANUMERIC, and any `LENGTH OF
x` operand integer NUMERIC. Unknown, they went unchecked and counted in
`unresolved_count`, so lint told a program with no COPY to fix its copybook
path. Pinned by `tests/regression/test_move_special_registers_issue_520.py`.

**Group receivers and `ZERO` → alphabetic.** A MOVE *into* a group item is a
group move (bytes copied as alphanumeric) and legal from any sender, so group
receivers are exempt from every elementary rule. `MOVE ZERO TO` a `PIC A` item
is an error (ZERO is numeric). Both were found by comparing a sender×receiver
matrix against GnuCOBOL's own MOVE legality check; the remaining disagreements
are where IBM is stricter than GnuCOBOL's `-std=ibm` (non-integer →
alphanumeric) or a documented choice here (HIGH/LOW-VALUE, QUOTE → numeric).
Pinned by
`tests/unit/analysis/test_move_type_checker.py::TestGroupReceiverAndZeroToAlphabetic`.

**Glued subscripts and reference modification.** The MOVE parser folds a
*source* as `T-E(2)` / `WS-A(1:3)` (no blanks), which `base_data_name` does
not split, so `_reference_name()` recovers the item name locally
(value_tracker keeps `base_data_name`, so a substring never propagates whole
values). A reference-modified operand (source or receiver) is ALPHANUMERIC
whatever its base item is: `MOVE WS-A TO WS-N(2:3)` does not warn, `MOVE
WS-D(1:2) TO WS-A` with a `V99` base is legal. Pinned by
`test_move_type_checker.py::TestSubscriptedAndReferenceModifiedOperands`.

**Picture classification.** `_PIC_ALPHA_ONLY_RE` matches any concatenation of
`A`/`A(n)` parts (`AA(3)`, `A(2)A(3)`). A pattern ending in the `CR`/`DB` sign
symbol classifies as NUMERIC_EDITED up front (otherwise `9(5)CR` is UNKNOWN
and `9(5)DB` NUMERIC_EDITED only because its 'B' matches the blank-insertion
edit char). Inside an edited picture, the `9` / `X` / `A` tests that pick
NUMERIC_EDITED vs ALPHANUMERIC_EDITED run on `pattern_no_reps` (repeat counts
stripped, see #336), so the 9 in `X(9)BX(9)` or `A(9)B` is not a digit
position. Pinned by
`tests/regression/test_audit_2026_08_16_analyzers.py::TestA5A6MoveTypePictureClassification`
and `test_move_type_checker.py::TestPictureVariants::test_nine_in_repeat_count_is_not_a_digit_position`.

**`unresolved_count` is part of the answer.** Every point where
`_validate_move` gives up on an operand (source or target category `UNKNOWN` /
`FIGURATIVE`) increments it; a caller that wants a real all-clear must check
`not violations and unresolved_count == 0`, since MOVEs on undeclared
identifiers (an unexpanded copybook) otherwise read exactly like checked,
compatible ones. Pinned by
`tests/regression/test_open_findings_high_regressions.py::TestH5MoveTypeCheckerUnresolvedCount`.

**`_is_non_integer_picture` is `decimal_digits > 0`**, the one canonical field:
`PictureClause._parse_scaled_pattern` already sets `decimal_digits = P-count +
9-count` for a leading-`P` picture (a *trailing*-`P` picture like `9(3)PPP` is
a scaled *integer*, `decimal_digits == 0`). The same field
`generators/data/layout.py`'s `FieldSpec.stored_digits`/`scaling_positions` and
`layout_offsets.py` (the `data-items` CLI) key off -- see the P-scaling note in
[../generators.md](../generators.md).

## LinkageChecker

```python
report: LinkageReport = LinkageChecker().check(ast)   # note: .check(), not .analyze()
# report.violations: list[LinkageViolation]
# report.entry_interfaces / .linkage_items
# LinkageViolation: kind/call_target/location/message/item_name
# LinkageViolationKind: TOO_MANY_ARGS, TOO_FEW_ARGS, UNREFERENCED_LINKAGE,
#                       UNKNOWN_ENTRY, PASSING_MODE_MISMATCH
# LinkageChecker(include_contained_programs=False).check(ast, interface_scope=root)
#   — one unit only (what LintAnalyzer does per program unit); the default
#   still walks every contained program of a whole file.
```

Validates LINKAGE SECTION items against the PROCEDURE DIVISION USING clause.
There is no rule that a LINKAGE item must be passed BY REFERENCE: BY VALUE is
*required* when the callee declares `PROCEDURE DIVISION USING BY VALUE`, so
such a check could only produce false positives. `UNREFERENCED_LINKAGE`
findings carry the item's declaration `location` and
`LinkageViolation.item_name`, so lint keeps one finding per program unit
instead of collapsing same-text findings from different units.

**`PASSING_MODE_MISMATCH`:** a CALL's own BY VALUE/BY REFERENCE (explicit, or
COBOL's own BY REFERENCE default) checked position-by-position against what
the *callee's own* `PROCEDURE DIVISION USING` explicitly declares -- never
against the LINKAGE item's own section. The callee's declared mode comes from
`divisions/base.py`'s `using_parameter_modes` metadata (name →
`"VALUE"`/`"REFERENCE"`, alongside the `using_parameters` name list); only
resolvable for a static CALL to a program in the same source whose implicit
entry interface was collected. A CALL to an `ENTRY` statement is never checked
for this, even though `EntryStatement.parameter_modes` records an ENTRY's own
`USING [BY] VALUE/REFERENCE` modes (see #402). `BY CONTENT` call arguments are
never flagged either way (no USING counterpart to compare against).

**CALL argument forms reference their item.** A CALL `USING`/`RETURNING`
operand is reduced to its data names (`_argument_names`: `ADDRESS OF` /
`LENGTH OF` dropped, subscripts and reference modifiers removed, every
`OF`/`IN` qualifier kept) and a subordinate item maps to its 01-level owner, so
`LK-REC(1:4)`, `ADDRESS OF LK-REC`, `LK-ITEM OF LK-REC` and `LK-ITEM` all
reference `LK-REC`.

**CICS translator items and address-only use.** `DFHEIBLK` and `DFHCOMMAREA`
are referenced unconditionally (`_CICS_TRANSLATOR_ITEMS` -- the translator
passes them on the USING it generates), plus the `RETURNING` item, every `SET
ADDRESS OF x TO p` target (`SetStatement.targets_are_address_of`), every
`ALLOCATE x` item (`AllocateStatement.data_item`, the same based-item idiom,
#570) and any CICS option of the form `SET(ADDRESS OF x)` (`_ADDRESS_OF_RE`).

**A REDEFINES group is referenced as one.** A level-01 LINKAGE item that
REDEFINES another (directly or through a chain, `_linkage_redefines` /
`_redefines_root`) shares its storage, so when any member of the group is
referenced -- the USING base or an overlay of it -- none is reported
`UNREFERENCED_LINKAGE` (#596).

**Interface collection is O(units).** `LinkageChecker.collect_scope_interfaces(ast)`
computes the interface map (and the passing-mode map above) once;
`check(..., entry_interfaces=..., entry_parameter_modes=...)` accepts either or
both precomputed and skips its own scope-wide `_collect_interfaces` walk.
`LintAnalyzer.analyze()` calls it once per file, not once per unit (per-unit
collection is O(N²) AST visits).

## IOLogger

```python
report: IOLogReport = IOLogger().analyze(ast)
# report.operations: list[IOOperation]   report.program_name
```

Lists every input/output operation the program performs, one `IOOperation`
(`category`/`operation`/`direction`/`variables`/`target`/`line`/`details`)
each. Categories: `FILE-IO` (OPEN, CLOSE, READ, WRITE, REWRITE, DELETE,
START, UNLOCK; file names resolved through `_files.py`), `CONSOLE-IO`
(ACCEPT, DISPLAY), `SQL` (EXEC SQL), `CALL` and `ENTRY` (program linkage);
`direction` is `INPUT` / `OUTPUT` / `BIDIRECTIONAL`. `variables` for WRITE
and REWRITE is the `FROM` item when there is one, else the record; for READ
it is the `INTO` item, else every 01 record under the file's FD (they share
the record area the READ fills; #573).

## IOSequenceAnalyzer

```python
report: IOSequenceReport = IOSequenceAnalyzer().analyze(ast)
# report.violations: list[IOSequenceViolation]  (kind/file_name/location/message)
# IOViolationKind: READ_BEFORE_OPEN, WRITE_BEFORE_OPEN, REWRITE_BEFORE_OPEN,
#                  DELETE_BEFORE_OPEN, START_BEFORE_OPEN, DOUBLE_OPEN,
#                  CLOSE_NOT_OPEN, DOUBLE_CLOSE, FILE_LEFT_OPEN,
#                  READ_WRONG_MODE, START_WRONG_MODE, WRITE_WRONG_MODE,
#                  REWRITE_WRONG_MODE, DELETE_WRONG_MODE, OPEN_AFTER_LOCK
```

Validates that IO operations follow legal COBOL sequencing rules (file must be
opened before read/write, etc.).

**Execution order, not source order.** `analyze()` linearizes the PROCEDURE
DIVISION (sections and top-level paragraphs interleaved by source line) and
runs an execution-order chain from the entry procedure: fall-through, a
paragraph's own top-level unconditional GO TO followed, out-of-line `PERFORM
target [THRU end]` inlined at the call site (section names resolve to their
full paragraph range; a re-entrant PERFORM is skipped via a range stack;
per-chain visited sets keep GO TO cycles finite). Top-level STOP RUN / GOBACK /
EXIT PROGRAM ends the walk; `STOP 'literal'` does not (it only pauses for the
operator; gated on `stop_type == "RUN"`). Paragraphs unreachable from the
entry procedure are not walked, declarative sections are skipped (see
[flow.md](flow.md)), and contained programs are not walked (single-program
scope). A source-order walk reports false CLOSE_NOT_OPEN / FILE_LEFT_OPEN /
READ_BEFORE_OPEN on the canonical "main PERFORMs a later wrap-up paragraph"
shape. Pinned by
`tests/regression/test_audit_2026_08_16_analyzers.py::TestA1IoSequenceExecutionOrder`
and `tests/regression/test_audit_2026_08_12_analysis.py::TestB1StopLiteralIsNotTermination`.

**GO TO / PERFORM targets resolve section-first** (see #335). The walk's
name -> paragraph-index maps (`_name_first` / `_name_last`) are keyed by
`ProcedureIndex` keys, and `_resolve()` applies its rule from the section of
the paragraph being walked (`_current_section`, restored after each PERFORM)
plus the `target_qualifier` / `thru_qualifier` metadata, so with a `SEC-EXIT`
in every section `GO TO SEC-EXIT` stays inside the PERFORMed range.
Conditional GO TO targets are resolved when queued. Pinned by
`tests/unit/analysis/test_io_sequence.py::TestSectionLocalParagraphNames`.

**PERFORM ranges are summarized, not re-inlined** (see #371). The walk is
generators (`_run_paragraph`, `_process_statement`, `_run_perform`,
`_walk_range`) that `yield` the sub-step they would have called; `_drive` runs
them off an explicit stack, so a PERFORM chain hundreds deep cannot raise
`RecursionError`. The first run of a range from a given entry state is stored
as a `_RangeSummary` (exit state, violations, queued conditional GO TO
targets, whether it terminated) and replayed at later call sites with the same
state, which keeps a paragraph PERFORMed twice per nesting level from costing
2**depth walks. A summary is only reused when the re-entrancy guard would
decide the same way: none of the ranges it `entered` is on the PERFORM stack,
and every enclosing range it skipped (`guarded`) still is. Violations are
emitted once per (kind, file, location, message), not once per call path.
Pinned by `tests/unit/analysis/test_io_sequence_perform_summaries.py`.

**IF / EVALUATE arms are forked and merged** (see #380). State is
`_status: dict[file, frozenset]` of possible states (`open:<MODE>` /
`closed` / `locked` / `unopened`; see the open-mode paragraph below). `_fork` runs each arm (an IF's THEN and ELSE, an EVALUATE's
`when_groups()` bodies and WHEN OTHER; a missing ELSE / WHEN OTHER is an empty
arm) from the branch's state and unions the arms that do not end the program,
so `IF .. OPEN OUTPUT f ELSE OPEN EXTEND f` is not a DOUBLE_OPEN and an `IF
bad-status CLOSE f STOP RUN` guard does not close `f` for the normal path. An
arm whose own top level hits STOP RUN / GOBACK / EXIT PROGRAM, or that
PERFORMs a paragraph that does, is left out of the merge, and no
FILE_LEFT_OPEN is claimed at that STOP RUN (a `_fork_depth` check in
`_terminate_program`, also part of the PERFORM-summary key). An arm ending in
an unconditional GO TO stays *in* the merge: dropping it loses its state at
the target (`PERFORM A THRU A-EXIT` with `IF .. OPEN f GO TO A-EXIT`, NIST
DB104A's `IF .. CLOSE f GO TO ..` guards). A top-level IF whose arms all end
the program ends the paragraph walk (`_ENDS`). Violations need to hold on
every merged path (READ of a file open on no path, OPEN of a file open on
every path); FILE_LEFT_OPEN is the exception and fires for a file open on any
path. AT END / INVALID KEY handlers are not forked. The PERFORM-summary key is
the whole `_status` map, so a range is re-walked from a new set of possible
states. Pinned by `tests/unit/analysis/test_io_sequence_branches.py`.

**Each verb is checked against the OPEN mode** (#548). An open state carries
the mode from `IOOpenStatement.file_modes` (`open:` when unknown). READ /
START need INPUT or I-O (else status 47, `READ_WRONG_MODE` /
`START_WRONG_MODE`); WRITE needs OUTPUT, EXTEND or -- on a non-sequential
SELECT `ORGANIZATION`, or a file whose SELECT is not in the AST (an
unexpanded COPY member) -- I-O (48, `WRITE_WRONG_MODE`); REWRITE / DELETE need
I-O (49). `CLOSE f WITH LOCK` leaves `f` `locked`; an OPEN of a file locked
on every path is `OPEN_AFTER_LOCK` (38) and leaves it closed, so no
FILE_LEFT_OPEN follows. Like every other kind, a mode error needs every
merged path open in a known mode that refuses the verb: a mode that differs
between arms (`IF .. OPEN INPUT f ELSE OPEN OUTPUT f`) is no error. All six
are lint errors. Limit: an EXTERNAL file opened by a CALLed program (NIST
IC227A) is invisible to the walk, as for the `*_BEFORE_OPEN` kinds. Pinned by
`tests/regression/test_issue_548_io_open_mode.py`.

**`CLOSE f REEL` / `CLOSE f UNIT` keep the file open.** They close only the
current volume (`close_options[f]["reel"/"unit"]`).

**Conditional GO TO targets are walked once the chain loops.** In the textbook
sequential loop (`READ IN-F AT END GO TO END-P` / `GO TO LOOP-P`), GO TO
targets met inside a branch or handler are queued (`_pending_gotos`) and the
chain resumes at the next unvisited one when it loops back, so END-P's CLOSE
is seen. The file states at the GO TO(s) that queued a target
(`_pending_states`, carried through PERFORM summaries as well) are merged
into the walk's state there: by the time the walk resumes, a later paragraph
may have reopened the file in another mode (NIST IX103A's DELETE, #548). If it still ends on a loop without reaching STOP RUN/GOBACK, no
FILE_LEFT_OPEN is claimed (`_ended_in_cycle`): the walk never reached program
end. A missing or duplicate CLOSE in the exit paragraph is still reported.
Pinned by `tests/unit/analysis/test_io_sequence.py::TestGoToReadLoop`.

## CRUDMatrixGenerator

```python
matrix: CRUDMatrix = CRUDMatrixGenerator().analyze(ast)
# matrix.file_entries: list[FileEntry]   (file_name/crud/open_modes/organization/access_mode)
# matrix.table_entries: list[TableEntry] (table_name/crud/cursors) -- EXEC SQL tables
# matrix.entries: both lists (property); .crud is CRUDFlags(create/read/update/delete)
# matrix.caveats: list[str] -- accesses it could not attribute (also in to_dict())
matrix.to_csv()
matrix.to_json()
```

Generates a program-level CRUD matrix (Create/Read/Update/Delete): one row
per file and one per DB2 table the program touches.

* **Open modes are per file.** `_collect_open_modes` reads
  `IOOpenStatement.file_modes` (the per-file dict the parser fills per mode
  group), falling back to `open_mode` only for a file with no entry; `OPEN
  INPUT IN-FILE OUTPUT OUT-FILE` gives each file its own mode. Pinned by
  `tests/regression/test_audit_2026_08_12_analysis.py::TestA3OpenModesPerFile`.
* **SORT / MERGE mark their files.** `USING` files are read (R) and `GIVING`
  files written (C) -- the sort does the I/O itself, so no READ/WRITE names
  them. `RELEASE` marks its SD file C (via the record's FD/SD) and `RETURN`
  marks it R. Pinned by `test_crud_matrix.py::TestSortMergeFileAccess`.
* **EXEC CICS file control marks files.** `READ` / `READNEXT` /
  `READPREV` / `STARTBR` give R, `WRITE` C, `REWRITE` U, `DELETE` D, on the
  file its `FILE(...)` (or older `DATASET(...)`) names -- how every CICS
  program reaches its VSAM data (`_mark_cics_file_crud`,
  `_CICS_FILE_ACCESS`). Organization / access mode stay None (they live in
  the CICS file definition). A command without FILE/DATASET (`WRITEQ`,
  `WRITE OPERATOR`) adds nothing; one naming its file through a data item
  (`FILE(WS-FNAME)`, not in `literal_options`) adds no row and a line to
  `CRUDMatrix.caveats`, which MCP `program_brief` reports as
  `incomplete-analysis`. Pinned by
  `tests/regression/test_crud_cics_file_control_issue_538.py` (#538).
* **Report Writer writes its file.** `INITIATE` / `GENERATE` / `TERMINATE`
  mark C on the file whose `FD ... REPORT IS` names the report (or the
  report-group's report): `_files.report_to_file_map()` (FILE SECTION
  `report_files` metadata + each REPORT SECTION 01's `rd_report_name`) and
  `report_writer_files()`. The same helpers make IOLogger log each as a
  `WRITE` (`details["verb"]`) and io-sequence check the file is open
  (`WRITE_BEFORE_OPEN`, message naming the verb). Pinned by
  `tests/regression/test_report_writer_file_output_issue_499.py` (#499).
* **Record → file resolution** goes through `_files.py` (see [Data names and
  references](#data-names-and-references)).
* **SQL writes.** For INSERT/UPDATE/DELETE/MERGE only `stmt.tables[0]` (the
  target -- see [../dialects.md](../dialects.md)) gets the write flag; every
  other table a subquery / `INSERT ... SELECT` / `MERGE ... USING` names is
  marked **R** (`DELETE FROM T WHERE X IN (SELECT X FROM S)` deletes from T
  only). MERGE marks its target with the actions its `THEN
  INSERT|UPDATE|DELETE` clauses take. `EXEC SQL TRUNCATE [TABLE] t` marks `t`
  D, like a DELETE (`SQLStatementType.TRUNCATE` is in `_WRITE_SQL_TYPES`, see
  #341). Pinned by `tests/unit/test_issue_341_dialect_crud.py::TestTruncateTable`.
* **SQL in the DATA DIVISION counts.** `get_all_statements()` walks the
  PROCEDURE DIVISION only, so the SQL passes also read the program's own
  DATA DIVISION EXEC SQL nodes (`_data_division_sql()`, ahead of the
  procedure statements): a `DECLARE c CURSOR` in WORKING-STORAGE marks its
  tables R with the cursor name, and a `FETCH c` / `WHERE CURRENT OF c`
  resolves through it. A contained program's DATA DIVISION is its own.
  Pinned by `tests/regression/test_crud_ws_cursor_issue_518.py` (#518).

## DynamicCallAnalyzer

```python
from cobolparser.analysis import DynamicCallAnalyzer
DynamicCallAnalyzer().analyze(ast)   # mutates ast, annotating dynamic CALL targets
```

Tracks possible values for variables used in dynamic CALL statements via MOVE
and VALUE clause analysis.

**Only a definite literal is a value.** Value recording is gated on
`_is_definite_literal` (quoted string / numeric literal / figurative constant);
the parser keeps quotes on `MoveStatement.source`, so an unquoted hyphenated
token is always a reference, never a program name. An untracked identifier
source (no VALUE clause, no tracked MOVE) instead marks the target's value set
INCOMPLETE, propagated through variable-to-variable MOVEs, and any dynamic CALL
on such a variable gets `get_metadata("possible_values_incomplete") == True`,
so a consumer knows `possible_values` (even when non-empty) is not exhaustive.
The `analyze` CLI emits the flag. Pinned by
`tests/regression/test_audit_2026_08_12_analysis.py::TestB3UntrackedIdentifierSourceIsNotAValue`.

**`possible_values` is deterministic**: `CallStatement.set_possible_values`
sorts the deduplicated list (a bare `list(set(...))` varies per process under
hash randomization). Pinned by
`tests/regression/test_audit_2026_08_16_analyzers.py::TestA2PossibleValuesDeterministic`.
Consumers read the candidates through `_names.callee_names` (see [Data names
and references](#data-names-and-references)).

**A write through a REDEFINES overlay is a write to the CALL variable
(#257).** `_overlapping_names()` -- which decides what counts as "writing
the CALL variable's storage" for `_mark_untracked_writes()` -- follows
`REDEFINES` as well as the group hierarchy: the redefining item, the item it
redefines (matched by name at the same level number) and every subordinate
on either side form one storage cluster (union-find, so several
redefinitions of one area join). `MOVE 'PGMZ' TO WS-AREA` therefore marks a
`CALL WS-PGMN` (`WS-PGMN REDEFINES WS-AREA`) incomplete, as does a group
`MOVE ... TO WS-REC` for a `CALL WS-NM2` inside `WS-REC2 REDEFINES WS-REC`.
No byte-range precision: like the hierarchy rule, any write to the overlay
counts. Pinned by `tests/unit/test_value_tracker.py::TestRedefinesOverlap`.

**Storage the program does not fill itself is incomplete (#564).**
`_mark_externally_supplied()` runs *before* the MOVE pass and marks
incomplete every item overlapping (via `_overlapping_names()`) a LINKAGE
item (the caller supplies it), a record under the FD/SD of a file the unit
READs (with or without INTO) or RETURNs (`fd_file_name` metadata), an EXEC
SQL receiver (`into_variables`, `SET :hv =` / `GET DIAGNOSTICS :hv =`, every
host variable of an SQL `CALL`), or an EXEC CICS receiver (`INTO`, `SET`,
`RESP`, `RESP2`, every option of `ASSIGN`; `literal_options` skipped). Seeding
before the MOVE pass is what carries the flag through `MOVE LK-PGM TO
WS-PGM`. A WHERE-clause input host variable or a CICS input option
(`LINK PROGRAM(x)`) is not a write.

**The MOVE pass runs to a fixpoint.** `_track_move_statements()` walks in
source order, and a MOVE in a paragraph PERFORMed earlier may be written
later (`MOVE WS-DEFAULT TO WS-PGM` before the `MOVE 'PGMB' TO WS-DEFAULT`
that executes first). `_analyze_unit()` repeats the pass until
`_tracked_size()` (total values, incomplete names; both only grow) stops
changing, so the analysis is flow-insensitive: every MOVE copies its source's
complete value set. Pinned by
`tests/unit/test_issue_564_dynamic_call_incomplete.py`.

**`SET cond TO TRUE` and MOVE sources (#511).** Level-88s are
`ConditionNameItem`s, so the data-item overlap never saw them: now
`SET cond TO TRUE` adds the condition's *first* VALUE literal (the low end of
a THRU range, as the compiler moves it) to its parent item, and `TO FALSE`
the `WHEN SET TO FALSE` literal; no such value, a group parent, or a 88 name
declared twice marks the parent incomplete, and a SET whose parent overlaps a
tracked item marks that item incomplete. `_mark_untracked_writes()` checks
not just the CALL variables but every item whose value reaches one through
MOVEs (`_value_sources()`, a fixpoint), and `_propagate_incomplete()` then
carries that incompleteness forward along the MOVEs -- `ACCEPT WS-DEFAULT`
then `MOVE WS-DEFAULT TO WS-PGM` is incomplete. A literal MOVE to a tracked
item's group adds the slice of the space-padded literal at the item's offset
(`_literal_group_slices()`, offsets from `compute_record_layout`) as an exact
value; under an OCCURS, at an ambiguous offset, non-DISPLAY or with a
duplicated name it marks the item incomplete instead. Values are still
collected flow-insensitively (the VALUE clause stays a candidate after a
SET). Pinned by
`tests/unit/test_value_tracker.py::TestConditionSetAndMoveSources`.

**`SET pointer TO ENTRY` is a value (#593).** `_track_pointer_set()` reads
every `SET ... TO` group (`_set_groups()`, the first group plus
`SetStatement.groups`): `SET p TO ENTRY 'SUBPGM'` adds `SUBPGM` to `p`,
`SET p TO [ENTRY] identifier` copies the identifier's value set like a MOVE
(and joins `_identifier_moves()`, so `_value_sources()` /
`_propagate_incomplete()` follow it), `TO NULL` adds nothing, and any other
SET to the item (`UP BY`, `ADDRESS OF`, a non-ENTRY literal, `SET ADDRESS OF
p`) marks it incomplete. `_mark_untracked_writes()` therefore skips xref's
`SetStatement` writes to the CALL variable itself; a SET to an overlapping
item still marks it incomplete. Pinned by
`tests/unit/test_issue_593_set_entry_dynamic_call.py` (also the
codebase-graph edge).

## IO coverage and diagnostics helpers

`io_coverage_reporter.py` (`IOCoverageReporter`, `CoverageStatus`, `TestType`,
`IoCoverageArtifact`) builds machine-readable IO coverage reports, driven by
`tools/io_coverage/`; `io_diagnostics.py` (`IOErrorCode`,
`IODiagnosticHelper`) holds IO operation diagnostics. Neither is a program
analyzer. `IOCoverageReporter.load_pytest_results` raises `ValueError` when the
pytest-results JSON root is not an object (the same "artifact must be a JSON
object" check its CLI callers apply, see [../cli.md](../cli.md)), rather than
failing later with an `AttributeError`. Pinned by
`tests/unit/analysis/test_io_coverage_reporter.py::test_load_pytest_results_non_object_json_raises_value_error`.

## See also

* [../analysis.md](../analysis.md) -- routing page, calling conventions, module map
* [flow.md](flow.md) -- procedure roots, terminators, same-named procedures
* [sql-cics-ims.md](sql-cics-ims.md) -- SQL host variables and DCLGEN checks
* [codebase.md](codebase.md) -- `ProgramSignatureExtractor`, which grades
  LINKAGE directions from xref roles
* [lint.md](lint.md) -- these analyzers as lint rules
* [../parser.md](../parser.md) -- where operands, subjects and selectors are built
* [../cli.md](../cli.md) -- `unused-variables`, `xref`, `move-type-check`,
  `linkage-check`, `io-sequence`, `analyze`
* [history](../history/analysis.md) -- dated fix write-ups behind these rules
