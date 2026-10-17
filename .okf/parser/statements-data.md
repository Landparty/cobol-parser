---
type: Module
title: Data-manipulation statement parsers
description: Per-verb parsing rules for the data statements -- MOVE, ADD / SUBTRACT / MULTIPLY / DIVIDE, COMPUTE (expression precedence), SET, INITIALIZE, INSPECT, STRING, UNSTRING, DISPLAY, ACCEPT, XML / JSON GENERATE and PARSE, ALLOCATE / FREE.
tags: [parser, statement, move, arithmetic, compute, set, display, accept, string]
timestamp: 2026-10-15T00:00:00Z
---

# Data-manipulation statement parsers

Rules and gotchas for `move_parser.py`, `arithmetic_parsers.py`,
`set_parser.py`, `initialize_inspect_parsers.py`, `string_unstring_parsers.py`,
`display_parser.py`, `accept_parser.py`, `xml_json_parser.py` and
`allocate_free_parsers.py`. The invariants they all keep (boundaries, the H9
paragraph check, separators, layout, literal re-quoting) and the shared operand
helpers (`consume_optional_qualifiers`, `consume_signed_numeric`,
`consume_value_operand`, ...) are in [statements.md](statements.md); read that
first. Node fields are in [ast-models.md](../ast-models.md).

## Contents

- [MOVE](#move)
- [ADD, SUBTRACT, MULTIPLY, DIVIDE](#add-subtract-multiply-divide)
- [COMPUTE](#compute)
- [SET](#set)
- [INITIALIZE and INSPECT](#initialize-and-inspect)
- [STRING and UNSTRING](#string-and-unstring)
- [DISPLAY](#display)
- [ACCEPT](#accept)
- [XML / JSON](#xml--json)
- [ALLOCATE and FREE](#allocate-and-free)
- [See also](#see-also)

## MOVE

- **Targets.** The target loop stops on the shared `STATEMENT_TOKEN_TYPES` /
  `STATEMENT_KEYWORDS` (`_utils.py`) unioned with its own clause-boundary extras
  (`GO`, `ELSE` / `WHEN` / `END-*`, and the IO-clause `NOT` / `INVALID` / `AT`
  tokens) -- never a hand-rolled local verb list (one that omitted `EXEC` let
  `MOVE X TO Y` swallow a following `EXEC SQL` block). It skips only `,` / `;`
  and stops on any other non-identifier token (skipping arbitrary tokens folded
  `WITH DATA` of a RECEIVE into the MOVE). Each target goes through
  `consume_optional_qualifiers` (`MOVE X TO QUAL OF GROUP-A` is one target, not
  two), and the H9 dedent check applies to every target position.
- **Source.** `_parse_source` collects every token and renders them with
  `join_source_parts` (`_utils.py`, shared with CALL's `FUNCTION` arguments): words space-separated, no space around parens or before
  commas (`TBL(1, 2)`), a leading unary `-` / `+` attached to its digits
  (`MOVE -5` -> `"-5"`, relied on by `analysis/const_fold.py`), and a
  reference-modification colon tight on both sides (`WS-X(2:3)`). A plain
  `"".join` corrupts every multi-token source (`WS-AOFWS-GRP`). A typed literal
  keeps its prefix (`raw_value`, `X"41"`); a plain literal is re-quoted. A
  separator `,` / `;` outside parentheses is skipped like a space (`MOVE 'ABC',
  TO X` -> `"ABC"`, #569); inside them it separates function arguments and is
  kept.
- **Malformed input.** `MOVE A TO.`, `MOVE A` (no `TO`) and a stream ending at
  `MOVE A TO` report an error via `report_parse_error` and keep the node; a
  missing source is not flagged (see
  [statements.md](statements.md#boundary-invariants), rule 8). Pinned by
  `tests/unit/test_move_malformed_diagnostics.py`,
  `tests/regression/test_move_qualifier_chain.py`.

## ADD, SUBTRACT, MULTIPLY, DIVIDE

- **Operands.** `parse_arithmetic_operands` (ADD/SUBTRACT addends before `TO` /
  `FROM`) folds qualifier chains (`ADD QUAL OF GROUP-A TO Y` has one addend,
  `"QUAL OF GROUP-A"` -- a spurious `"GROUP-A"` addend poisons
  `ConstantFolder`), composes signs via `consume_signed_numeric` (`-1` stays
  `-1`), and accepts figurative constants (`MULTIPLY A BY ZERO GIVING B`).
  MULTIPLY/DIVIDE's `BY` / `INTO` operand (`_consume_arithmetic_operand`) folds
  qualifiers and signs the same way. ADD/SUBTRACT record `source_operands` (the
  operand list before TO/FROM/GIVING, duplicates kept) so a consumer can tell an
  addend from a target of the same name (`.operands` dedups).
- **Targets.** `_consume_arithmetic_target` (ADD `TO`, SUBTRACT `FROM`, and
  MULTIPLY/DIVIDE format 1) folds `(subscript)` groups and `OF` / `IN` chains
  (`"Y OF Z"`, `"NAME ( SUB1 , SUB2 )"`). `ArithmeticStatement.target` is the
  first target (back-compat) and `.targets` the full ordered list (`ADD 1 TO a,
  b, c`); `set_target()` appends to both. `ROUNDED` is recorded per statement
  (`set_rounded()`). `CORRESPONDING` / `CORR` is a keyword
  (`is_corresponding`), not an operand. `_consume_additional_arithmetic_targets`
  continues the list across commas / spaces / ROUNDED and stops at
  `_ADDITIONAL_TARGET_STOP_KEYWORDS` (includes `REMAINDER` and `SIZE`), at a
  statement boundary and at the H9 paragraph check.
- **GIVING.** `consume_keyword_and_operand` reads the first GIVING target
  (skipping layout before and after the keyword, so a GIVING on its own
  continuation line is found; folding subscripts and qualifiers);
  `_consume_additional_giving_targets` continues the list into
  `ArithmeticStatement.givings` (`.giving` keeps the first). SUBTRACT's `FROM`
  branch checks for a trailing GIVING exactly as ADD's `TO` branch does
  (otherwise `SUBTRACT a FROM b GIVING c` stores into `b`).
- **MULTIPLY / DIVIDE format 1 vs 2.** In the shared `_parse_binary_arithmetic`,
  only the no-GIVING branch (format 1, which overwrites its second operand) calls
  `stmt.set_target(second_operand)` and continues the target list; format 2's
  second operand is a multiplicand / divisor and must not become a `.target`.
  `DivideStatement.division_mode` (`"BY"` / `"INTO"`) is set where the separator
  is consumed; `DIVIDE ... REMAINDER r` sets `.remainder`. The
  `_BinaryArithmeticNode` protocol types the helper against both node classes.
- **Ending.** All five arithmetic verbs end with `parse_size_error_clauses(...,
  end_keyword=...)` (`"END-ADD"`, `"END-SUBTRACT"`, `f"END-{verb}"`,
  `"END-COMPUTE"`): ON SIZE ERROR handling plus consumption of the statement's own
  terminator, which otherwise reads as a phantom `END-ADD` paragraph. `SIZE` is in
  every target / GIVING stop set because `ON` is optional (`ADD ... SIZE ERROR`).
  Pinned by `tests/regression/test_tier8_arithmetic_scope_terminator.py`,
  `tests/regression/test_arithmetic_qualifier_chain.py`,
  `tests/unit/test_initialize_sort_arithmetic_comma_gaps.py`.

## COMPUTE

- **Expression collection.** At `paren_depth == 0` the loop stops at a period,
  `ON` / `NOT` / `SIZE`, and any `STATEMENT_KEYWORDS` /
  `CONTROL_FLOW_BOUNDARIES` / `SCOPE_TERMINATORS` value (an enclosing `END-READ`
  must end the clause, not join the expression). At non-zero depth it still
  breaks on `is_statement_boundary`, and an unclosed parenthesis is reported
  ("COMPUTE statement has unbalanced parentheses in expression") -- a depth that
  never returns to zero must not swallow the rest of the program. Bare
  separators outside parentheses are skipped; the H9 dedent check applies.
- **`expression` text.** NEWLINE tokens are consumed without entering the text
  (a two-line COMPUTE serializes like the one-line form, which keeps clone
  detection exact); `**`'s two lexed `*` tokens are re-merged (`2 ** 3`).
- **Targets.** `COMPUTE id-1 [ROUNDED], id-2 [ROUNDED] = expr`: commas between
  targets are skipped (stopping there left the comma for the `=` check and failed
  the whole statement). `ComputeStatement.rounded` is recorded.
- **`expression_tree`** is a precedence parse of the collected tokens (literals,
  subscripted identifiers, FUNCTION calls, parentheses); a failed build degrades
  to `None`, never an error. Grammar, tightest-binding first: `_parse_primary`
  → `_parse_unary` (leading `+` / `-`) → `_parse_power` (`**`,
  left-associative: `2 ** 3 ** 2` is `(2 ** 3) ** 2 == 64`) → `_parse_term`
  (`*` / `/`) → `_parse_expression` (`+` / `-`). This is IBM's hierarchy (unary,
  then exponentiation, ...), which differs from the mathematical convention: `- A
  ** 2` is `(-A) ** 2`, so `COMPUTE X = - 2 ** 2 + 10` folds to 14. Every `**`
  operand is a `_parse_unary` (`2 ** -3 ** 2` is `(2 ** -3) ** 2`). Pinned by
  `tests/regression/test_open_findings_m12_regression.py` and
  `tests/regression/test_review_2026_09_09_generators.py::TestFinding9PowerAssociativity`;
  folding rules in [analysis.md](../analysis.md) (ConstantFolder).

## SET

- **Targets** (`_collect_targets`) fold qualifiers / subscripts
  (`consume_optional_qualifiers`), accept a comma list (`SET ix1, ix2 UP BY 1`),
  and recognize `ADDRESS OF x` (`OF` lexes as `TokenType.OF`, not IDENTIFIER):
  `SET ADDRESS OF x TO p` sets `targets_are_address_of`.
- **Values** (`_consume_set_value` wraps `consume_value_operand`): signed
  (`DOWN BY -1`), subscripted (`TO TABLE-ITEM(5)`) and qualified (`TO WS-VAL OF
  WS-CTL`) values are one value in every branch (`TO`, `UP BY`, `DOWN BY`). `TO
  ADDRESS OF identifier` stores the identifier as `value` with
  `value_is_address_of`; a value introduced by `ENTRY` sets `value_is_entry`.
- **Multi-group SET** (`SET SW-1 TO ON SW-2 TO OFF`, `SET A; B TO 3`) records each
  group in `SetStatement.groups`. `_entry_form` is reset before *each* group's
  `_parse_action` and recorded per group via `add_group(..., is_entry=...)`
  (`"value_is_entry"` group key), so one group's `TO ENTRY` does not leak into
  the next. Pinned by `tests/regression/test_set_qualifier_chain.py`.

## INITIALIZE and INSPECT

- **INITIALIZE** targets are a comma list; targets and the `REPLACING ... BY`
  value fold subscripts / qualifiers (`"TBL ( 1 )"`, `"B OF C"`). The target
  loop also stops at `ALL` / `THEN` / `TO` / a category word / `FILLER`
  (`_INITIALIZE_PHRASE_STARTS`). Enterprise COBOL 6 phrases: `[[WITH] FILLER]`
  (`with_filler`; WITH optional, #402), `[{ALL | category} TO VALUE]`
  (`to_value_category`), `[THEN] REPLACING ...`, `[THEN] TO DEFAULT`
  (`to_default`); `THEN` is optional (`_match_then`). Every phrase lookahead
  uses `peek_past_noise`, so a line break inside `ALL TO VALUE` / `THEN
  REPLACING` / `THEN TO DEFAULT` keeps the phrase (a raw `peek(1)` saw the
  NEWLINE and dropped it, silently for `TO DEFAULT`; #575). Pinned by
  `tests/regression/test_level88_false_and_initialize_phrases.py` and
  `test_initialize_phrase_line_breaks.py` (every form split at every gap).
- **Separators (#569).** A `,` / `;` is a space in COBOL: every gap in
  INSPECT (target, TALLYING, REPLACING, CONVERTING, BEFORE/AFTER) and in
  INITIALIZE's REPLACING list is skipped with `skip_statement_separators`, and
  `_by_follows_value` looks past one. Stopping at it dropped every later
  counter / pair with no warning. Pinned by
  `tests/regression/test_separator_comma_operands.py`.
- **INSPECT.** `_parse_tallying`'s counter-clause loop (`counter-1 FOR
  {CHARACTERS|ALL|LEADING} [value] ...`) checks `is_statement_boundary` and the H9
  check before treating an IDENTIFIER as a new counter; a subscripted counter
  (`CNT(2) FOR ...`) is folded. One `FOR` takes any number of `CHARACTERS` /
  `ALL` / `LEADING` phrases, matched by value (`ALL` lexes as a figurative
  constant), each a clause of the same counter; `ALL` / `LEADING` take one or
  more operands, and a later identifier is the next counter only when `FOR`
  follows it (`_starts_further_operand`, `_keyword_follows_value`; #332 --
  `FOR ALL 'A' LEADING 'C'` had invented a counter named LEADING). `_parse_before_after` (shared by TALLYING and
  REPLACING) loops until neither qualifier matches, so `BEFORE` and `AFTER
  INITIAL` may both appear in either order (each at most once); its delimiter is
  read by `_consume_inspect_value`, so `BEFORE INITIAL SPACE` (figurative) and
  `AFTER INITIAL ENT(2)` are taken whole. `CONVERTING` takes subscripted /
  figurative operands and keeps its BEFORE/AFTER phrase as `converting_before` /
  `converting_after` (in `to_dict()` only when present). The outer "consume to
  period" trailer in `parse()` breaks on a statement boundary and owns the H9
  warning -- it is also the guard for REPLACING, whose clause loop stops safely
  on an unrecognized token.

## STRING and UNSTRING

- Both main loops break (without consuming) on `is_statement_boundary` and the
  H9 check instead of consuming unknown tokens. `BY` after `DELIMITED` is
  optional (`DELIMITED SIZE`, `DELIMITED "," OR ALL SPACE`); a delimiter is taken
  only when the next token is operand-shaped (`_next_is_delimiter`), so
  `DELIMITED INTO X` leaves INTO for its own clause. Operands and delimiters are
  re-quoted literals (`literal_operand_text`).
- **UNSTRING.** `DELIMITED BY d1 OR d2 ...` collects every delimiter
  (`delimiters`), with `delimiter_all` a parallel bool list emitted by `to_dict()`
  only when some delimiter is `ALL`. `_parse_into_targets` accepts a comma list
  and stops at `POINTER`, `OVERFLOW` and statement boundaries (it only breaks; the
  outer clause loop records the H9 warning). `ON` (before `OVERFLOW`), `WITH`
  (before `POINTER`) and `IN` (after `TALLYING`) are optional, as in STRING; a
  bare `OVERFLOW` opens `on_overflow`; `TALLYING [IN] C` sets
  `tallying_variable`. Pinned by `tests/unit/test_unstring_gaps.py`.

## DISPLAY

- Items: `STRING_LITERAL` / `IDENTIFIER` / `NUMERIC_LITERAL` /
  `FIGURATIVE_CONSTANT` (`DISPLAY SPACE`), comma-separated, with
  `is_statement_boundary` and the H9 check before each identifier.
  `_consume_subscript` folds a following `( ... )` -- found past a line break via
  `peek_past_noise` -- into the preceding item, keeping nested parens literally
  (`TAB(FUNCTION MOD(3 2))`); `ELEM OF GRP` folds too. `FUNCTION name[(args)][(refmod)]`
  is one item rendered as MOVE renders it (`"FUNCTION TRIM(A)"`). Literals are
  re-quoted; typed literals keep `raw_value`.
- `[WITH] NO ADVANCING` sets `with_no_advancing` (`WITH` / `NO` / `ADVANCING`
  lex as dedicated token types, so they need their own branch). `UPON device`
  continues the clause loop afterwards (`DISPLAY x UPON CONSOLE WITH NO
  ADVANCING`; breaking out left the period for a phantom `"."` paragraph). `AT`
  positioning: the combined numeric form `AT 0330` (line 3, column 30, via
  `divmod(value, 100)`) and the keyword form `AT LINE n COLUMN m`
  (`_parse_at_clause`). Screen-section extensions (`LINE` / `COLUMN` / `BLANK
  SCREEN` / `WITH BELL` / colours) are not modeled and warn.

## ACCEPT

- Operand: qualified / subscripted (`ACCEPT X OF Y`, `ACCEPT T (2)`), guarded by
  `is_statement_boundary` so a missing operand does not eat the next verb;
  `ACCEPT cd MESSAGE COUNT` is accepted. A separator after the operand is a
  space (`ACCEPT X, FROM DATE`, #569).
- `FROM DATE` / `TIME` / ... with a trailing format (`YYYYMMDD`, `YYYYDDD`) is
  folded into `from_source` (left in the stream it became a phantom paragraph).
  `FROM ENVIRONMENT "name"` stores the name via `set_environment_name()`.
- Extended clauses (shamrice corpus shapes): `AT nnnn` (numeric form only), `WITH`
  optional before `SECURE`, `NO-ECHO`, `TIMEOUT n`, `AUTO-SKIP`, `UPPER`.
  `SECURE` (masks with `*`) and `NO-ECHO` (shows nothing) are distinct flags
  (`secure` vs `with_no_echo`); `timeout_value`, `auto_skip`, `upper`. Not
  implemented: `CURSOR`, `BEEP` / `BELL`, `COLOR` / `FOREGROUND-COLOR` /
  `BACKGROUND-COLOR`, `UPDATE`.
- `[ON] EXCEPTION` / `NOT [ON] EXCEPTION` bodies go to
  `IOAcceptStatement.on_exception` / `.not_on_exception`; `END-ACCEPT` is consumed.

## XML / JSON

- `XmlJsonStatementParser` matches bare `XML` / `JSON` by value. Its clause loop
  keeps its own clause words even where they are verbs elsewhere (`SUPPRESS`,
  `NOT`, `ON`, and `WHEN` once a SUPPRESS was seen -- `XML GENERATE ... SUPPRESS
  WHEN SPACES` is one statement), and keeps `JSON` when the next word is
  `BOOLEAN` / `DECIMAL` (`CONVERTING x [TO|FROM] JSON BOOLEAN|DECIMAL`,
  `_is_json_type_word`). Keyed on the word *after* JSON because TO / FROM are
  optional: keying on a preceding `TO` cut JSON PARSE's `FROM JSON BOOLEAN`
  and the bare forms at JSON, dropping `ON EXCEPTION` and hoisting its
  handler into the paragraph (#574). Clause data names are structured into `count_in` /
  `into_item` / `clause_items` (`_record_clause_items`).
- `_consume_processing_procedure` reads `[PROCESSING] PROCEDURE [IS] p
  [THRU|THROUGH q]` starting at either word (`XML PARSE x PROCEDURE IS p` sets
  `processing_procedure`), looking past line breaks (`peek_past_noise`) for `IS`
  and `THRU` (#394, #405).

## ALLOCATE and FREE

`allocate_free_parsers.py` -> `AllocateStatement` / `FreeStatement`, registered in
the minimal/rare group after `UseStatementParser`, matched by value (no
`TokenType`, see [statements.md](statements.md#registration-and-matching)).
`ALLOCATE {identifier-1 CHARACTERS | identifier-2} [INITIALIZED] [RETURNING
identifier-3]` -> `is_characters` / `size_expr` (identifier or numeric literal),
`data_item` (the BASED item form), `initialized`, `returning_target`; a missing
first operand is reported. `FREE identifier-1 [identifier-2] ...` ->
`pointer_names`; zero pointers is reported after the loop (`FREE.` errors, `FREE
WS-PTR.` does not).

## See also

- [statements.md](statements.md) — table, boundary invariants, shared helpers, conditions, literal re-quoting
- [statements-control.md](statements-control.md) · [statements-io.md](statements-io.md) — the other verb groups
- [../ast-models.md](../ast-models.md) — `MoveStatement`, `ArithmeticStatement`, `SetStatement`, `IOAcceptStatement` fields
- [../analysis.md](../analysis.md) — ConstantFolder, MoveTypeChecker and other consumers
- [history](../history/parser.md) — archived dated notes behind these rules
