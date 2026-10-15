---
type: History
title: AST Models history
description: Archived dated notes moved out of ast-models.md; not loaded by default.
tags: [history, ast-models]
timestamp: 2026-10-15T00:00:00Z
---

# AST Models history

Archive of dated notes moved verbatim from [ast-models.md](../ast-models.md) on
2026-10-15, when the topic file was restructured to describe only the current
state. Every still-valid fact in these notes is stated in present tense in the
topic file; what remains here is the when, the before/after and the audit
narrative. Newest first.

## Dated remarks removed from running text

Sentences and parentheticals cut out of otherwise current paragraphs, quoted as
they stood, newest first.

* `from_json()` restored list (2026-10-15): "-- a SELECT dict is flat, so
  `_select_from()` rebuilds it whole and `ProgramLayoutIndex.file_facts()` of
  a round-tripped program matches the original (#346, 2026-10-15; SELECTs
  used to be dropped *and* counted as PROCEDURE DIVISION statements in the
  warning)."
* Group vs. elementary: "**Group vs. elementary (#345, 2026-10-15):**"
* TRUNCATE: "(`_SQL_TRUNCATE_TABLE_RE`); the CRUD matrix marks `t` D (issue #341,
  2026-10-15)."
* Implicit FILLER: "**Implicit FILLER (#404, 2026-10-14).**"
* Stacked WHENs: "**Stacked WHENs (2026-10-14, #314).**"
* National sign: "so `PIC S9(5) USAGE NATIONAL` is 12 (it was 10
  before 2026-10-08, shifting every later offset by 2; pinned in
  `tests/regression/test_bug_hunt_2026_10_08.py`)."
* `ASTNode.equals` / `from_json` (issue #273): "(Before issue
  #273, 2026-10-05, it compared node types and child counts only, so any two
  programs with the same division count were "equal".)" and "`CobolProgram.from_json()` is **not** its full inverse -- it restores a
  structural skeleton (issue #273, 2026-10-05):"
* Dated 2026-09-28 additions: "**Query helpers (2026-09-28).**"; "(They used to test `statement_type == "EXEC-CICS"` alone,
  a spelling no parsed statement carries, so every real CICS / EXEC DLI program
  answered False.)"; "`get_intrinsic_function_usages()`
  delegates to `LanguageEnvironmentAnalyzer` (its own former regex had reported
  `OF` for `DLI-FUNCTION OF REC` and words inside literals)."; "**Inherited USAGE / SIGN (2026-09-28).**";
  "**`ConditionNameItem.false_value: str | None`** (2026-09-28)"; "* **National (2026-09-28).**";
  "* **`currency_symbols`** (2026-09-28)" ... "`parse_picture_clause` saw. (`£` used to be an invalid PICTURE character.)";
  "* **`decimal_point_is_comma`** (2026-09-28)"; "`into_variables` / `DynamicSQLStatement.using_variables` list every host
  variable of the INTO / USING list, indicators included (2026-09-28)."; "`InitializeStatement.to_value_category` ... both always in
  `to_dict()` (2026-09-28)."; "`ReleaseStatement.set_from_source()` / `ReturnStatement.set_into_target()`
  add the operand to `operands`, like `IOWriteStatement.set_from` /
  `IOReadStatement.set_into` (2026-09-28; an item used only as `RELEASE ...
  FROM x` was otherwise reported unused)."; "`assign_using` (2026-09-28)"; "the structured clause names (2026-09-28) `count_in`".
* PICTURE sizing (2026-09-27): "Simple insertion `B`/`0` make a picture edited and count one byte each
  (2026-09-27: `999B99` had sized 5, `0009` 1, `XXBXX` 4) -- unless the pattern
  also holds characters no PICTURE may contain, which keeps the lenient
  fallback. An edited picture with a `V` (`Z(3)V99`) is sized by the edited
  path, not the 9s-only `V` split (it had sized 2, not 5)." and "Unedited pictures are sized after expanding every repeat factor
  (`_parse_plain_pattern`, 2026-09-27): `X(2)X(3)` had sized 2, `AAX(2)` 1,
  `9(2)9(3)` 2 digits, `NN` 2 bytes instead of 4."
* SQL (2026-09-27): "(`_split_common_table_expressions()`). (Both were `"UNKNOWN"` with no tables
  before 2026-09-27.)"; `ArithmeticStatement.source_operands: list[str] | None` "(2026-09-27)".
* SQL (2026-09-23): "(`_SQL_TABLE_NAME`). (Before 2026-09-23 they stopped at the first `.`, so
  every qualified table also reported its schema as a table.)"
* Program-unit attributes: "Program-unit attributes (from the program-type corpus work, 2026-09-15):"
* P-scaling: "`scaling_leading: bool | None` (2026-09-10) records the P
  run's direction"; `SetStatement.groups`: "`"value_is_entry"` key (2026-09-10) is that group's own `SET p TO ENTRY 'X'`
  flag (a later group's flag used to leak into the next group)."
* National/DBCS pictures: "`PIC N(n)` (national) and `PIC G(n)` (DBCS) are **2 bytes per character**
  (2026-09-09)".
* Program units: "these two methods (2026-09-07) are how to reach the units".
* Calculate-size: "Current rules worth knowing:"
* REPORT SECTION: "**REPORT SECTION (2026-09-02).**"; EXEC nodes: "`"EXEC_IMS"`, `to_dict()` shape unchanged since 2026-09-02) so
  `get_all_statements()` returns them."
* Statement-coverage audit (2026-09-02): "The `communication.py` / `legacy.py` / `report_writer.py` modules plus
  `RaiseStatement`/`ResumeStatement` and `ValidateStatement` (statement-coverage
  audit, 2026-09-02) back the 22 verbs that used to be warned-and-discarded (see
  [parser.md](../parser.md)'s "Statement-coverage audit" section)."
* `NextSentenceStatement` "(`statement_type` `"NEXT-SENTENCE"`, 2026-08-24)".
* OCCURS parsing: "and comma-separated `INDEXED BY` / `KEY` name lists
  (2026-08-23)." and "size (it used to fabricate a phantom data item while recording
  `max_times == 0`)."
* `DivideStatement.division_mode: str | None` "(2026-08-12)".
* "`InvokeStatement`/`AllocateStatement`/`FreeStatement` (2026-08-05) back
  `invoke_parser.py`/`allocate_free_parsers.py`."
* Arithmetic: "`.givings: list[str]` likewise for `GIVING`
  (`ADD A TO B GIVING C, D`), `.giving` the first (2026-07-24)"; CALL: "(`CALL 'P' USING BY
  CONTENT a, b` tags both CONTENT; 2026-07-24)."
* 2026-07-22: "`.target` keeps the first (2026-07-22)"; "`.delimiters` collects every `OR`-joined delimiter (2026-07-22)."; "`IOOpenStatement.file_modes: dict[str, str]` (2026-07-22)".
* Arithmetic cross-reference: "* See [parser.md](../parser.md) "Statement-Support Verification Sweep" and
  "Follow-up comma-list sweep"."
* "**Expression trees (2026-07-20, M12; additive).**"
* OCCURS fields (2026-07-09): "`index_names: list[str]     # all INDEXED BY names (2026-07-09)`",
  "`#  "keys": [...]} — SEARCH ALL keys (2026-07-09)`", and "(Before 2026-07-09 `ASCENDING/DESCENDING
  KEY` was dropped and `INDEXED BY` kept only its last name; see
  [parser.md](../parser.md)'s Silent-Drop Audit.)"
* Serialized shapes: "Serialized-shape facts (several were in-memory only until the 2026-07-07
  fidelity audit):"
* Statement field reference intro: "Fields that are easy to miss, grouped by node. Dates mark when a field started
  being populated; the "previously" notes explain what consumers of older output
  may still see."

## `calculate_size()` rewrite (2026-09-05)

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
