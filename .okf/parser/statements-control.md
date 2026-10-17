---
type: Module
title: Control-flow statement parsers
description: Per-verb parsing rules for the control-flow statements -- IF, EVALUATE, PERFORM, GO TO, ALTER, SEARCH, CALL, ENTRY, INVOKE, STOP, EXIT, NEXT SENTENCE, CANCEL, USE, and the legacy / COBOL 2002 verbs (NOTE, TITLE, RAISE, RESUME, VALIDATE, ...).
tags: [parser, statement, if, evaluate, perform, call, go-to, search]
timestamp: 2026-10-15T00:00:00Z
---

# Control-flow statement parsers

Rules and gotchas for the statement parsers that branch, loop, call or end:
`if_parser.py`, `evaluate_parser.py`, `perform_parser.py`, `go_parser.py`,
`search_parser.py`, `call_parser.py`, `entry_parser.py`, `invoke_parser.py`,
`stop_parser.py`, `exception_parsers.py`, `legacy_verb_parsers.py` and the
control verbs of `simple_statement_parsers.py`. The invariants every parser keeps
(boundaries, separators, layout, literals) are in [statements.md](statements.md);
read that first. Condition trees are built by `_conditions.py`
([statements.md](statements.md#condition-trees-_conditionspy)); IF, PERFORM
UNTIL and SEARCH WHEN pass it `condition_symbols(context)` so a bare data-name
leg of an abbreviated relation expands (#562).

## Contents

- [IF](#if)
- [EVALUATE](#evaluate)
- [PERFORM](#perform)
- [Procedure names, GO TO and ALTER](#procedure-names-go-to-and-alter)
- [SEARCH](#search)
- [CALL](#call)
- [ENTRY and INVOKE](#entry-and-invoke)
- [STOP, EXIT, NEXT SENTENCE, CONTINUE](#stop-exit-next-sentence-continue)
- [USE, CANCEL and the legacy / COBOL 2002 verbs](#use-cancel-and-the-legacy--cobol-2002-verbs)
- [See also](#see-also)

## IF

- The condition collector stops at any statement boundary (including value-only
  verbs such as `PURGE`) and reads `THEN` / `ELSE` / `END-IF` through
  `keyword_upper()`, so `IF X = "ELSE"` keeps its THEN body and `IF X =
  "END-IF"` keeps its full condition.
- The THEN / ELSE statement lists skip statement separators (`... GO TO X;
  ELSE ...`) and stop when a nested parser has consumed the sentence period
  (`previous_meaningful_token`).
- Separators and layout are dropped from the condition (`IF X = 1,` ->
  `right_operand == "1"`; `IF X-ON;` stays a condition-name).

## EVALUATE

**EVALUATE stacked WHENs (`evaluate_parser.py`, #314):** after a WHEN's
selectors, `_at_stacked_when` sets `WhenClause.stacked` when the next
meaningful token is another WHEN (not WHEN OTHER) and no unexpanded COPY was
blanked on the lines between (`TokenStream.omitted_source_lines`, filled by
`CobolParser` from `strip_unexpanded_copy_statements`).
`EvaluateStatement.when_groups()` groups on that flag; the AST keeps one
`WhenClause` per phrase. Deciding it from an empty `statements` instead would
merge a WHEN whose body was dropped (unexpanded COPY, recovery) into the next
arm.

- **Blank literal selectors.** The lexer strips quotes, so `WHEN '  '` (the IMS
  DL/I status-code idiom) arrives whitespace-only; `_parse_selectors` re-quotes
  whitespace-only `STRING_LITERAL` tokens (selector value `"'  '"`) so
  `_build_selector` does not filter it out and report "WHEN clause must have at
  least one selector". Non-blank literals keep their unquoted form -- do not route
  selector tokens through `condition_token_text()`, which quotes every literal.
  Subjects (`_parse_subjects`) do use `condition_token_text()` (`EVALUATE 'X'` ->
  `'X'`); the flow scanner's `WHEN <value>` edge labels follow the unquoted
  selector shape. Pinned by `tests/regression/test_evaluate_space_literal_when.py`.
- **Classify on `(token, TokenType)` pairs, not joined text.** `ANY`,
  `THRU` / `THROUGH` and the condition words (`AND OR NOT = < > <= >= <>`) are
  keywords only when not a `STRING_LITERAL`, so `WHEN "ANY"` / `"THRU"` / `"AND"`
  stay literals. Pinned by `tests/regression/test_evaluate_keyword_literal_when.py`.
- **Single-token selectors say what they were** (#313): a one-token `Literal`
  carries `"identifier": True`, `"figurative": True` (`WHEN SPACES`) or
  `"quoted": True` (`WHEN 'SPACES'`); a `Range` carries `"start_quoted"` /
  `"end_quoted"` when that bound is one STRING_LITERAL (#391). Additive markers;
  `type` stays `"Literal"` / `"Range"`. Pinned by
  `tests/regression/test_evaluate_figurative_when.py`,
  `tests/unit/test_evaluate_variants.py::TestRangeQuotedMarkers`.
- **Word-form operators and class / sign tests are conditions** (#387): a WHEN
  phrase holding a relational word (`GREATER LESS EQUAL EQUALS`) or a class test
  (`NUMERIC ALPHABETIC ALPHABETIC-LOWER ALPHABETIC-UPPER DBCS KANJI`), or a sign
  test (`POSITIVE NEGATIVE ZERO`) after its first word, is a `Condition`; a lone
  `WHEN ZERO` stays the figurative `Literal`. `operator: "OR"` is set only for a
  logical OR, never the OR of `OR EQUAL` (`_has_logical_or`). Pinned by
  `tests/regression/test_evaluate_word_operator_when.py`.
- **Subjects reach `.operands`.** `_parse_subjects` calls
  `EvaluateStatement.add_subject()`, which also calls `add_operand()`, so
  `find_statements_using_variable`, intrinsic-function detection,
  `LanguageEnvironmentAnalyzer` and `BoundaryInventoryAnalyzer` see subject-only
  variables; `stmt.subjects` keeps its strings and order.
- **WHEN clauses are AST children.** Attach them with `add_when_clause` /
  `set_default_when` (both call `add_child`), never by mutating
  `when_clauses` / `default_when` directly -- the tree-walk APIs
  (`find_all_by_type`, `traverse_depth_first`) only follow `children`.
  `get_all_statements` dedupes by `id`, so nothing is double-counted;
  `to_dict()` serializes `when_clauses`. A second `WHEN OTHER` reuses the
  existing default clause (still reporting the error) so no orphaned clause is
  walked but not serialized. Pinned by
  `tests/regression/test_evaluate_traversal_regression.py`.
- **Both scan loops are boundary-guarded.** `_parse_subjects` and the outer
  clause-scan loop (between the subjects and the WHEN dispatch) break on
  `_is_statement_keyword()`, as `_parse_selectors` does; an unguarded outer loop
  lets a malformed EVALUATE annex a later EVALUATE's `WHEN` with no error.
  `WHEN` / `END-EVALUATE` / `ALSO` are read through `keyword_upper()`, and `WHEN
  OTHER` is detected past a line break.

## PERFORM

- **Forms.** Inline (`PERFORM [WITH TEST ...] [UNTIL ... | VARYING ... | n
  TIMES] ... END-PERFORM`) and out-of-line (`PERFORM p [THRU q] [n TIMES | [WITH
  TEST ...] UNTIL ... | VARYING ...]`). `PERFORM id TIMES` and `PERFORM P id
  (sub) TIMES` are accepted; `PERFORM P OF SECTION` keeps the qualifier in
  `metadata["target_qualifier"]` (target stays the bare name).
- **VARYING.** `_parse_varying_header()` parses `id FROM x BY y [WITH TEST ...]
  UNTIL cond` and is shared by the inline form and the out-of-line form
  (`_parse_out_of_line_varying_clause`, hooked where the paragraph-name branch
  checks for `UNTIL`). `PerformStatement.mark_varying()` is called as soon as the
  `VARYING` keyword is consumed, so `perform_type == "VARYING"` reflects the
  keyword even when the sub-clause is malformed (flow analysis keys loop edges
  off `perform_type`); a degraded clause also gets
  `_warn_incomplete_varying_clause()`. Each `AFTER var FROM x BY y [UNTIL cond]`
  dimension goes to `PerformStatement.after_clauses` (`_parse_after_clauses`).
  The VARYING variable may be subscripted; `FROM` / `BY` values go through
  `consume_value_operand` (signed literals such as `BY -1`, which lex as two
  tokens, and subscripted / qualified references such as `FROM WS-TBL (2)`).
- **UNTIL collection.** `_collect_until_condition_tokens` stops (without
  consuming) at `AFTER` only when `for_varying=True` -- a plain `PERFORM UNTIL`
  condition may contain an `AFTER` token. Both UNTIL loops
  (`_collect_until_condition_tokens`, `_parse_until_condition_only`) stop at
  `STATEMENT_TOKEN_TYPES` / `STATEMENT_KEYWORDS` and at any `SCOPE_TERMINATORS`
  word (an out-of-line PERFORM owns none: in `IF c PERFORM p UNTIL d END-IF STOP
  RUN.` the `END-IF` belongs to the IF), read `AFTER` and terminators through
  `keyword_upper()`, and drop WHITESPACE / NEWLINE / CONTINUATION / COMMENT
  tokens (`_make_until_condition_expression` also drops whitespace-only strings).
  Pinned by `tests/unit/test_perform_until_scope_terminator.py`,
  `tests/unit/test_perform_until_newline.py`.
- **WITH TEST.** `WITH`, `TEST` and `BEFORE` / `AFTER` may sit on separate lines;
  all three call sites (inline form, out-of-line form, inside
  `_parse_varying_header`) `skip_whitespace` before each peek. Bare `TEST
  BEFORE` (no WITH) and `WITH TEST AFTER VARYING ...` inline are accepted.
- **TIMES lookahead.** After a target paragraph, a following IDENTIFIER /
  NUMERIC_LITERAL is a TIMES count only if `TIMES` / `TIME` follows
  (`peek_past_noise`); otherwise `_warn_stray_trailing_token()` names it. In the
  inline `PERFORM n TIMES` branch the numeric is checked for TIMES *before* being
  consumed, so `PERFORM 1000 THRU 1999` takes `1000` as a procedure name.
- Suppressed `ParseError`s in VARYING / UNTIL / inline-body parsing are logged at
  DEBUG, never dropped silently.

## Procedure names, GO TO and ALTER

- **All-digit procedure names** (`PERFORM 1000 THRU 1999`) lex as
  `NUMERIC_LITERAL` / `LEVEL_NUMBER`. `_utils.is_procedure_name_token` (an
  identifier, or an all-digit numeric token) is the single predicate wherever a
  statement targets a paragraph: PERFORM targets and THRU ends, GO TO's
  computed-target scan, ALTER's from-paragraph. SORT/MERGE `THRU` procedure names
  remain IDENTIFIER-only. Pinned by `tests/unit/test_perform_thru_numeric.py`,
  `tests/regression/test_real_corpus_parse_failures.py`.
- **GO TO** skips layout after `GO` and after `TO` (target on the next line).
  Computed form `GO TO a, b, c DEPENDING [ON] x`: targets are a comma / space
  list, `ON` is optional (NIST NC102A) and consumed only when present, and the
  variable may be subscripted (`DEPENDING ON X (7)`). Losing the variable turns a
  jump table into an unconditional GO TO and misleads dead-code, program-flow,
  unused-variables and complexity. `GO TO P IN SECTION` keeps the qualifier in
  `metadata["target_qualifier"]`. Pinned by
  `tests/regression/test_go_depending_without_on.py`.
- **ALTER** (`simple_statement_parsers.py::AlterStatementParser`): the
  from-paragraph may be all-digit (`ALTER 1000 TO PROCEED TO 2000`); several
  clauses separated by commas (`ALTER a TO ..., b TO ...`); `ALTER P IN S TO ...`
  keeps the qualifier as metadata.

## SEARCH

- The AT END / WHEN loop ends the SEARCH at any token other than AT / END / WHEN
  / END-SEARCH / a separator, so a SEARCH without END-SEARCH nested in an IF does
  not eat `ELSE ... END-IF`. `AT` is optional before `END` (a bare `END` that does
  not start `END PROGRAM` / `END DIVISION`). SEARCH has no `NOT AT END`; one is
  left for the procedure parser's unparsed-token warning rather than overwriting
  the AT END body.
- The WHEN condition collector reads `WHEN` / `END-SEARCH` / `AT` through
  `keyword_upper()` (`WHEN K = "WHEN"` is one WHEN) and skips bare separators.
  Each WHEN takes exactly one condition and gets a `condition_tree` next to its
  raw `condition` text (#348).

## CALL

- **Handler bodies** (`ON EXCEPTION` / `NOT ON EXCEPTION` / `ON OVERFLOW`, `ON`
  optional; the `ON` lookahead crosses line breaks) are parsed by
  `_parse_nested_stmts` through the registry. Termination: a `NOT` / `END-CALL`
  value, the *next* `ON` / `NOT` clause (so `ON OVERFLOW ... ON EXCEPTION ...`
  yields both handlers), any `CONTROL_FLOW_BOUNDARIES` / `SCOPE_TERMINATORS`
  value (an enclosing `ELSE` / `END-IF` / `END-PERFORM`), a period between
  statements, or a nested parser having consumed the period
  (`previous_meaningful_token`). A verb with no parser inside a handler gets
  `_warn_and_skip_handler_statement` (one warning per dropped statement, tokens
  skipped to the next boundary), mirroring the top-level recovery. Pinned by
  `tests/regression/test_call_handler_body_termination.py`.
- **USING list** (`_parse_using_clause`): stops at `SCOPE_TERMINATORS` (never
  captures `END-CALL`) and at the handler words; commas are separators;
  `OMITTED` is an argument; a figurative constant (`BY CONTENT ZERO`) or a signed
  literal (`BY VALUE -7`) is one argument named by its text; `BY VALUE 100`,
  `ADDRESS OF x`, `LENGTH OF x` and subscripted / qualified data names are one
  argument each. `FUNCTION name [(args)] [(refmod)]` is one argument, spelled
  as MOVE spells its source (`FUNCTION UPPER-CASE(WS-NAME)`, via the shared
  `join_source_parts`; #579) -- left to the identifier path, `FUNCTION` became
  an argument of its own and every later one moved a position right.
  mocky-mock's `CAPTURE ARG n` counts depend on this list's arity.
- **Passing mode persists** across a comma / space separated group: it is set
  once before the loop and changes only on a `BY` keyword or a bare `REFERENCE` /
  `CONTENT` / `VALUE` (`BY` is optional in IBM; #388): `USING BY CONTENT a, b`
  passes both by content. Pinned by `tests/unit/test_call_using_mode_without_by.py`.
- A subscripted dynamic `CALL WS-PGM (IDX)` keeps the bare name as
  `called_program` and the full reference in
  `metadata["called_program_reference"]`.

## ENTRY and INVOKE

- **ENTRY** (`entry_parser.py`): the name may sit on the next line; the USING
  list skips commas (never records `","` as a parameter) and checks
  `is_statement_boundary()` before its catch-all branch.
- **INVOKE** (`invoke_parser.py` -> `InvokeStatement`): `INVOKE
  object-identifier-1 {identifier-2 | literal-1} [USING [BY
  REFERENCE|CONTENT|VALUE] {identifier-3 | literal-2} ...] [RETURNING
  identifier-4] [END-INVOKE]`. Fields: `object_name`, `method_name` +
  `method_is_literal`, `using_parameters` (`CallParameter`, same mode persistence
  as CALL), `returning_target`. No exception handlers (INVOKE's grammar has
  none). Registered right after `EntryStatementParser`. The USING loop takes
  CALL's argument forms (qualifier / subscript folding, `LENGTH OF` / `ADDRESS
  OF`, `OMITTED`, figurative constants); RETURNING target and object reference
  fold qualifiers too. A missing object or method name is reported via
  `report_parse_error`; `set_method_name()` records the method name as an operand
  whether literal or identifier (as `CallStatement.set_called_program()` does).
  Pinned by `tests/regression/test_invoke_allocate_free_statements.py`.

## STOP, EXIT, NEXT SENTENCE, CONTINUE

- **STOP** consumes its sentence period (an unconsumed period becomes a phantom
  `"."` paragraph). `STOP RUN RETURNING x` -> `StopStatement.returning`; a bare
  numeric operand is `stop_type`; `STOP ZERO` / `STOP QUOTE` are accepted; the
  operand may be on the next line.
- **EXIT**: `EXIT SECTION.` is a statement, never a section header (see
  [divisions.md](divisions.md)).
- **NEXT SENTENCE** has its own parser (`NextSentenceStatementParser`, registered
  right after `ContinueStatementParser`, `matches()` requires `SENTENCE` via
  `peek_past_noise`) and its own node `NextSentenceStatement` (not
  `ContinueStatement`: it transfers control past the sentence). `NEXT` is in the
  boundary sets, so `IF A = "Y" NEXT SENTENCE` does not fold the words into the
  condition.
- **CONTINUE**, **EJECT**, **SKIP1/2/3** are no-op nodes (see
  [statements.md](statements.md#registration-and-matching)).

## USE, CANCEL and the legacy / COBOL 2002 verbs

- **USE** (`UseStatementParser`): `USE [GLOBAL] BEFORE REPORTING group...`
  (`use_type "REPORTING"`, `report_groups`); the word `FOR` is skipped.
- **CANCEL**: program-name list with commas, boundary and H9 checks.
- **NOTE** (COBOL-74 comment statement) runs to the sentence period but stops
  early at a following line that starts with a verb, so a period-less NOTE cannot
  eat the rest of the program.
- **CHAIN / NOTE / EXHIBIT / EXAMINE / TRANSFORM** match by their dedicated
  TokenType only (`_matches_legacy_verb`), and are not in `STATEMENT_KEYWORDS`:
  where the program declares one as a data name the lexer retypes it to
  IDENTIFIER, and it is then an ordinary operand (`MOVE 'ACME' TO CHAIN`,
  #525). Pinned by `tests/regression/test_legacy_verb_data_names.py`.
- `TITLE`, `VALIDATE`, `READY` / `RESET TRACE`, `SERVICE LABEL` / `RELOAD`,
  `RAISE`, `RESUME`, `PURGE` are matched by value under the conditions in
  [statements.md](statements.md#registration-and-matching). Node classes are in
  [ast-models.md](../ast-models.md) (`legacy.py`, `control.py`).

## See also

- [statements.md](statements.md) — table, boundary invariants, shared helpers, conditions
- [statements-data.md](statements-data.md) · [statements-io.md](statements-io.md) — the other verb groups
- [divisions.md](divisions.md) — paragraph boundaries and the PROCEDURE DIVISION loop
- [../analysis.md](../analysis.md) — program-flow / dead-code consumers of these nodes
- [history](../history/parser.md) — archived dated notes behind these rules
