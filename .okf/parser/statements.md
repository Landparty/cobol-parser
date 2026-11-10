---
type: Module
title: Statement parsers
description: The PROCEDURE DIVISION statement layer -- the verb-to-parser table, first-match registration, the statement-boundary invariants every parser must keep (no silent swallowing), the shared helpers in parsers/statements/_utils.py, literal re-quoting (_literals.py), condition trees (_conditions.py), handler/clause bodies, and how to add a new statement parser.
tags: [parser, statement, registry, boundary, conditions, utils]
timestamp: 2026-10-15T00:00:00Z
---

# Statement parsers

`cobolparser/parsers/statements/` holds 33 verb-parser files plus two shared
helpers (`_utils.py`, `_conditions.py`); every class is an `IStatementParser`
(`matches()` + `parse()`), and all 72 are registered by
`create_statement_registry()` (`parsers/divisions/procedure_registry.py`) and
dispatched first-match by `StatementParserRegistry`. This file holds what applies
to every verb: the table, the [boundary invariants](#boundary-invariants) (the
parser's most-repeated bug class), the [shared helpers](#shared-helpers-_utilspy),
[conditions](#condition-trees-_conditionspy) and
[adding a parser](#adding-a-new-statement-parser). Per-verb rules are in
[statements-control.md](statements-control.md) (IF / EVALUATE / PERFORM / GO /
SEARCH / CALL / ...), [statements-data.md](statements-data.md) (MOVE /
arithmetic / COMPUTE / SET / STRING / DISPLAY / ...) and
[statements-io.md](statements-io.md) (file I/O, SORT/MERGE, EXEC blocks, Report
Writer, communication).

## Contents

- [Statement parser table](#statement-parser-table)
- [Registration and matching](#registration-and-matching)
- [Boundary invariants](#boundary-invariants)
- [Shared helpers (`_utils.py`)](#shared-helpers-_utilspy)
- [Clause and handler bodies](#clause-and-handler-bodies)
- [Literal re-quoting (`_literals.py`)](#literal-re-quoting-_literalspy)
- [Condition trees (`_conditions.py`)](#condition-trees-_conditionspy)
- [Adding a new statement parser](#adding-a-new-statement-parser)
- [Swallow-sweep regression harness](#swallow-sweep-regression-harness)
- [See also](#see-also)

## Statement parser table

| File | COBOL Verbs | Rules in |
|------|------------|----------|
| `accept_parser.py` | ACCEPT | data |
| `allocate_free_parsers.py` | ALLOCATE, FREE (`AllocateStatementParser` / `FreeStatementParser`) | data |
| `arithmetic_parsers.py` | ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE | data |
| `call_parser.py` | CALL | control |
| `close_parser.py` | CLOSE | io |
| `communication_parsers.py` | SEND, RECEIVE, ENABLE, DISABLE, PURGE (COBOL-85 Communication Module) | io |
| `delete_parser.py` | DELETE | io |
| `display_parser.py` | DISPLAY | data |
| `entry_parser.py` | ENTRY | control |
| `evaluate_parser.py` | EVALUATE | control |
| `exception_parsers.py` | RAISE, RESUME, VALIDATE (COBOL 2002) | control |
| `go_parser.py` | GO TO | control |
| `ibm_exec_statements.py` | EXEC SQL / SQLIMS, EXEC CICS, EXEC IMS DLI | io |
| `if_parser.py` | IF | control |
| `initialize_inspect_parsers.py` | INITIALIZE, INSPECT | data |
| `invoke_parser.py` | INVOKE (OO method invocation) | control |
| `legacy_verb_parsers.py` | EXHIBIT, EXAMINE, TRANSFORM (OS/VS), ENTER, NOTE (COBOL-74), CHAIN (Micro Focus), READY TRACE / RESET TRACE, SERVICE LABEL / SERVICE RELOAD, TITLE (IBM compiler-directing) | control |
| `move_parser.py` | MOVE | data |
| `open_parser.py` | OPEN | io |
| `perform_parser.py` | PERFORM | control |
| `read_parser.py` | READ | io |
| `report_writer_parsers.py` | INITIATE, TERMINATE, SUPPRESS (Report Writer; GENERATE is in `simple_statement_parsers.py`) | io |
| `rewrite_parser.py` | REWRITE | io |
| `search_parser.py` | SEARCH | control |
| `set_parser.py` | SET | data |
| `simple_statement_parsers.py` | ALTER, CANCEL, COMMIT, CONTINUE, NEXT SENTENCE (`NextSentenceStatementParser`), EJECT, SKIP1/SKIP2/SKIP3 (`SkipStatementParser`), EXIT, GENERATE, GOBACK, RELEASE, RETURN, ROLLBACK, USE | control / io |
| `sort_merge_parsers.py` | SORT, MERGE | io |
| `start_parser.py` | START | io |
| `stop_parser.py` | STOP | control |
| `string_unstring_parsers.py` | STRING, UNSTRING | data |
| `unlock_parser.py` | UNLOCK | io |
| `xml_json_parser.py` | XML GENERATE, XML PARSE, JSON GENERATE, JSON PARSE | data |
| `write_parser.py` | WRITE | io |
| `_utils.py` | Shared clause-collection and operand utilities (`collect_clause_stmts`, `consume_optional_qualifiers`, `consume_value_operand`, `consume_signed_numeric`, `skip_whitespace`, `peek_past_noise`, `looks_dedented_relative_to`, ...) | this file |
| `_conditions.py` | `build_condition_expression` -- structured condition trees shared by IF, PERFORM UNTIL, EVALUATE and SEARCH WHEN | this file |

AST node classes for these verbs are listed in [ast-models.md](../ast-models.md).
`ExecCicsStatement` / `ExecImsStatement` are `CobolStatement`s, so
`get_all_statements()` returns them like every other statement.

## Registration and matching

- `create_statement_registry()` registers parsers in first-match priority order
  (more specific before general). The order is pinned by
  `tests/unit/test_procedure_registry_dispatch_order.py` (`EXPECTED_ORDER`,
  `DISPATCH_CASES`).
- **Words with no `TokenType` are matched by value, never by type.** `PURGE` /
  `RAISE` / `RESUME` / `VALIDATE` / `TITLE` lex as plain IDENTIFIERs and match
  through `_utils.matches_word`; `ALLOCATE` / `FREE` through
  `allocate_free_parsers._matches_bare_verb` (as `XmlJsonStatementParser` matches
  bare `XML` / `JSON`). Never `matches_keyword(stream, TokenType.IDENTIFIER, ...)`,
  which claims every identifier. Keeping them out of the lexer's `KEYWORDS` keeps a
  data item named `FREE` usable everywhere but a statement start.
- **Context-gated matches** for words that are not reserved everywhere: `TITLE`
  only when a string literal follows; `VALIDATE` only when a data-name follows
  (a paragraph named `VALIDATE.` stays a paragraph); `READY` / `RESET` only before
  `TRACE` (RESET also appears in Report Writer `SUM ... RESET ON`); `SERVICE`
  only before `LABEL` / `RELOAD`; `NEXT` only before `SENTENCE` (via
  `peek_past_noise`).
- Compiler-directing no-ops (`EJECT`, `SKIP1/2/3`) have a dedicated `TokenType`
  and `KEYWORDS` entry, so `EJECT.` can never be read as a paragraph header (it
  would split the enclosing paragraph), and a registered parser producing a no-op
  node, so a period-less `EJECT` gets no "Unparsed tokens" warning. Copybook text
  behaves the same, since expansion flattens it before lexing.

## Boundary invariants

The recurring defect in this layer is a statement with no trailing period that
**swallows what follows it** -- the next statement, the enclosing `ELSE` /
`END-IF`, or a paragraph header -- into its own operand list, with
`success == True` and no warning. Every loop that collects an open-ended list
must stop at a boundary *without consuming it*. The rules:

1. **Every verb is a boundary.** Each verb word must be in
   `_utils.STATEMENT_TOKEN_TYPES` (its `TokenType`, when it has one; `GO TO`
   lexes as `GO` then `TO`, so `GO` is there besides `GOTO`) **and**
   `STATEMENT_KEYWORDS` (its string, including verbs with no `TokenType` such as
   `PURGE` / `RAISE` / `RESUME`, which only a value check can catch). The
   legacy verbs CHAIN / NOTE / EXHIBIT / EXAMINE / TRANSFORM are the
   exception: type only, since a declared data name of that spelling lexes as
   IDENTIFIER and must not read as a boundary (#525). Includes
   no-op and handler-only verbs (`COMMIT`, `ROLLBACK`, `EJECT`, `SKIP1-3`,
   `NEXT`, ...). Pure clause words that never start a statement (`ON`,
   `OTHERWISE`, `THEN`, `END-*` terminators) are deliberately left out.
2. **Every list loop calls `is_statement_boundary(token)`** (the four-way check:
   `STATEMENT_TOKEN_TYPES` / `STATEMENT_KEYWORDS` / `SCOPE_TERMINATORS` /
   `CONTROL_FLOW_BOUNDARIES`) before accepting an IDENTIFIER as a list item --
   including nested helper loops with their own stop lists (UNSTRING `INTO`,
   SORT/MERGE keys and file lists, INSPECT TALLYING). A loop that only checks
   token *types* is safe for keyword-typed verbs but not for value-only ones; a
   loop whose fallback branch silently skips "non-identifier noise" must not skip
   keyword-typed tokens. New parsers and new helper loops must call the shared
   predicate rather than re-derive a boundary list.
3. **Literals are never keywords.** A string literal spelled like a verb or a
   clause word (`IF X = "IF"`, `WHEN "ELSE"`, `UNTIL X = "END-IF"`, `VARYING ...
   UNTIL X = "AFTER"`) must not end the statement: `is_statement_boundary`,
   `_looks_like_statement_boundary`, `parse_arithmetic_operands` and the
   condition / operand loops of IF, EVALUATE, SEARCH, PERFORM UNTIL, RETURN and
   USE exempt `LITERAL_TOKEN_TYPES`, and read clause words through
   `_utils.keyword_upper()` (`""` for a literal). Pinned by
   `tests/regression/test_keyword_spelled_literal_conditions.py`.
4. **Enclosing scope terminators are boundaries.** `END-ADD` / `END-SUBTRACT` /
   `END-MULTIPLY` / `END-DIVIDE` / `END-COMPUTE` have no `TokenType` (plain
   IDENTIFIERs, recognized by value in `SCOPE_TERMINATORS`); a parser must stop
   at *any* scope terminator it does not own (COMPUTE inside `READ ... AT END
   ... END-READ`; an out-of-line `PERFORM p UNTIL d` inside `IF ... END-IF`) and
   consume its own (see `parse_size_error_clauses(end_keyword=)`). An unconsumed
   own terminator followed by a period is read as a phantom paragraph.
5. **Paragraph headers are boundaries (H9).** An ordinary paragraph name is not a
   verb, and `IDENTIFIER .` is grammatically both "last operand of an
   unterminated statement" and "next paragraph header".
   `looks_like_paragraph_boundary()` decides like COBOL does: the identifier
   (a) starts its own source line (via `previous_meaningful_token`'s
   `.location.line`), (b) is followed by a period or `SECTION`, (c) is not a
   DATA DIVISION name (`ParseContext.known_data_names`, so a wrapped operand
   `DISPLAY\n    WS-X.` stays an operand), and is not in `SPECIAL_REGISTERS`
   (`RETURN-CODE`, `TALLY`, `SORT-RETURN`, `WHEN-COMPILED`, the `XML-` / `JSON-`
   registers -- never declared) or `NON_PARAGRAPH_RESERVED_WORDS` (`RUN`,
   `TRUE`, `SENTENCE`, ...; `DECLARATIVES` / `FACTORY` / `OBJECT` deliberately
   left out), and, when the source was normalized from fixed format
   (`CobolParser.source_is_fixed_format`), is not in Area B (normalized column
   >= `NORMALIZED_AREA_B_COLUMN` = 5, original column 12). It is ANDed with
   `looks_dedented_relative_to(token_column(tok), reference_column)` at every
   operand position, where the reference is the statement's verb column: a token
   at a column `<=` the verb's is a boundary (at equal columns the indentation
   cannot decide, and the operand reading would silently swallow the paragraph);
   only strictly deeper tokens are operands. When it fires,
   `warn_paragraph_boundary_swallowed()` records a warning and the loop breaks;
   the division loop then starts the paragraph normally. Applied in MOVE,
   DISPLAY, COMPUTE, STRING, UNSTRING, INSPECT, OPEN, CLOSE, SET, CANCEL,
   SORT/MERGE, INITIALIZE and the ADD/SUBTRACT/MULTIPLY/DIVIDE target and GIVING
   lists (helpers take an optional `reference_column`). Loops that collect a
   condition, an argument list or a clause body call
   `ends_at_paragraph_header(stream, reference_column=None)` (the same test,
   plus the warning, which is recorded once per header): the IF condition,
   PERFORM UNTIL (inline, out-of-line, VARYING/AFTER), CALL USING, INITIALIZE
   (with the verb column), and the EVALUATE WHEN body and `collect_clause_stmts`
   / size-error bodies (no column; the enclosing statement ends there as at
   a period). INSPECT's TALLYING loop
   and UNSTRING's `_parse_into_targets` only break; the outer loop records the
   warning. `is_statement_boundary()` itself does not include this check. Known
   residual: an undeclared identifier (unexpanded COPY) alone on its own line at
   or left of the verb column reads as a paragraph (with a warning).
6. **Separators are skipped, not stopped at.** `_utils.skip_statement_separators`
   (whitespace + `SEPARATOR_TOKEN_TYPES`) runs at the top of every statement-list
   loop (paragraph bodies, IF/ELSE, inline PERFORM, EVALUATE WHEN, SEARCH WHEN,
   `collect_clause_stmts`, size-error / invalid-key / CALL-handler bodies, RETURN
   clauses) and before the handler clauses of CALL, READ, WRITE and
   `parse_invalid_key_clauses`. Every comma-separated operand list (CALL USING,
   SET, UNSTRING INTO, DISPLAY, GO TO, CANCEL, ENTRY USING, INITIALIZE,
   SORT/MERGE keys and files, ADD/SUBTRACT targets, GIVING lists, COMPUTE
   targets, OPEN / CLOSE files, ALTER clauses) consumes `,` / `;` and continues;
   stopping at a comma drops every later item. Condition and expression
   collectors skip a bare separator only outside parentheses
   (`_utils.is_bare_separator(token, paren_depth)` / `paren_depth_after()`), so
   the comma in `FUNCTION MAX(A, B)` is kept. Pinned by
   `tests/regression/test_condition_expression_separators.py`.
7. **Look past layout before reading the next word.** A lookahead for a word
   must step over WHITESPACE / NEWLINE / CONTINUATION / COMMENT tokens
   (`peek_past_noise` non-destructively, `skip_whitespace` before consuming): a
   bare `peek()` / `peek(1)` sees the line break when the next word starts a new
   line, and the parse silently changes. `skip_whitespace` (not `_skip_newlines`)
   is the right skip because a fixed-format continuation carries a
   `CONTINUATION` token. Pinned by `tests/regression/test_keyword_line_breaks.py`.
8. **Report malformed input instead of guessing.** A statement missing a
   required part records a non-fatal error via `get_parse_context(stream)` +
   `report_parse_error` (lands in `ParseResult.errors` under both modes without
   dropping the node): MOVE without `TO` or with no receiving field, INVOKE
   without object or method, ALLOCATE without an operand, FREE without a pointer
   (checked after the collection loop), COMPUTE with unbalanced parentheses,
   EXEC without `END-EXEC`. MOVE's missing **source** is deliberately not
   flagged: `REPLACE` / `COPY ... REPLACING` pseudo-text can leak a bare `MOVE`
   token (NIST `SM206A` / `SM208A`).
9. **Never consume speculatively and discard.** Peek first (PERFORM's TIMES
   lookahead, ACCEPT FROM DATE format, OF/IN qualifier hops); if what follows is
   not the expected clause, leave it in the stream or warn naming the dropped
   token (`_warn_stray_trailing_token`).

## Shared helpers (`_utils.py`)

| Helper | Contract |
|--------|----------|
| `is_statement_boundary(token)` | the four-way boundary check above; literal tokens are never boundaries |
| `looks_like_paragraph_boundary` / `warn_paragraph_boundary_swallowed` / `looks_dedented_relative_to` / `token_column` | the H9 check; `token_column` is the one accessor for a token's column |
| `ends_at_paragraph_header(stream, reference_column=None)` | H9 for condition, argument-list and clause-body loops: the check plus its warning, in one call |
| `keyword_upper(token)` | upper-cased value for keyword comparison, `""` for a literal |
| `skip_whitespace` / `peek_past_noise(stream, offset)` / `_NOISE_TOKEN_TYPES` | skip / look past WHITESPACE, COMMENT, NEWLINE, CONTINUATION |
| `skip_statement_separators`, `is_bare_separator`, `paren_depth_after` | separator handling (rule 6) |
| `previous_meaningful_token` | last consumed non-layout token -- used to detect that a nested parser already consumed the sentence period, and for H9 line checks |
| `consume_optional_subscript(stream, parts)` | folds `( ... )` into `parts`, tracking paren depth (nested subscripts / function calls keep their inner parens); at depth > 0 stops without consuming at a period, an arithmetic scope terminator or a statement / control-flow keyword, so an unbalanced `(` cannot eat the rest of the program |
| `consume_optional_qualifiers(stream, value) -> str` | folds any number of `(subscript)` groups and `OF` / `IN` hops (layout skipped between hops) into the returned reference: `"Y OF Z"`, `"TBL ( I )"`. Confirms an identifier follows `OF` / `IN` by lookahead *before* consuming the keyword, so a malformed `OF 5` is left in the stream |
| `join_source_parts(parts) -> str` | renders collected operand tokens as COBOL text: words space-separated, tight parens / ref-mod colon, a leading sign glued to its digits (`FUNCTION UPPER-CASE(WS-X)`, `TBL(1, 2)`). MOVE's source and CALL's `FUNCTION` arguments (#579) |
| `consume_signed_numeric` | composes a MINUS/PLUS token and the following NUMERIC_LITERAL / LEVEL_NUMBER (a signed literal lexes as two tokens) into one value, looking past layout (`BY -` / newline / `1`) |
| `consume_value_operand(stream)` | one value operand: signed numeric, else literal (`literal_operand_text`) or identifier with qualifiers folded. Used by PERFORM VARYING / AFTER `FROM` / `BY` and SET's `TO` / `UP BY` / `DOWN BY` |
| `consume_keyword_and_operand` | optional keyword + operand (GIVING, REMAINDER); skips layout before *and* after the keyword check, folds qualifiers / subscripts |
| `parse_arithmetic_operands` / `ARITHMETIC_OPERAND_TOKEN_TYPES` | ADD/SUBTRACT leading operand list; figurative constants are operands; qualifiers and signs folded |
| `collect_operands` | the generic operand collector of the newer verb parsers (subscripts/qualifiers folded, literals re-quoted, separators skipped, statement- and H9-boundary aware) |
| `literal_operand_text(token)` | `raw_value` for a typed literal, `quote_literal(value)` for any other string literal |
| `is_procedure_name_token` | an identifier or an all-digit NUMERIC_LITERAL / LEVEL_NUMBER (procedure names may be all digits); used by PERFORM, GO TO, ALTER |
| `bare_end_starts_at_end_clause` | a bare `END` is an `AT END` only when it does not start `END PROGRAM` / `END FUNCTION` / `END DIVISION` |
| `matches_word` | value-based match for verbs with no `TokenType` |
| `collect_clause_stmts`, `parse_invalid_key_clauses`, `parse_size_error_clauses` | handler bodies, see below |
| `try_parse_nested_statement` | parses one nested statement; an exception not already recorded (`_already_recorded`, set by `report_or_raise`) becomes a warning "Nested statement parse failed and was skipped: ..." -- except `RecursionError` (nesting hundreds deep), re-raised so the statement loop records "Statement nested too deeply to parse ..." as an **error** and `success` is False (#375; it used to be a warning with statements missing) |
| `get_parse_context` / `report_parse_error` | record-and-continue error reporting |
| `collect_exec_sql_text(stream, sql=...)` | EXEC block text, see [statements-io.md](statements-io.md); with `sql=True` a literal keeps the delimiter it was written with (`Token.quote`), so a `"..."` delimited identifier stays one (#597, [dialects.md](../dialects.md)) |

**Folded references reach analyzers.** Operand strings carry the full
qualified / subscripted reference (`"WS-NUM OF GRP-1"`, `"WS-TAB ( 3 )"`). An
analyzer keying data items by bare name must normalize via
`analysis._names` (`base_data_name`, `bare_item_name`, ...; as `MoveTypeChecker._resolve_category` and
`DynamicCallAnalyzer` do; pinned by
`tests/regression/test_folded_reference_analyzers.py`); a raw `name in catalog`
lookup silently misses qualified references.

## Clause and handler bodies

- **IO clause bodies** (`AT END` / `NOT AT END` / `INVALID KEY` / `NOT INVALID
  KEY` / `AT END-OF-PAGE`) are parsed by `collect_clause_stmts`, which dispatches
  through the statement registry attached to the token stream (as IF / PERFORM /
  EVALUATE nesting does). The statements go on the node's clause list
  (`at_end_clause`, `invalid_key_clause`, ...) **and** are added as AST children,
  so `find_all_by_type` and `to_dict()` see them (mocky-mock's boundary detection
  depends on an inner `CALL` being visible). Collection stops at a period,
  `NOT` / `INVALID` (next clause), a caller-supplied stop value (`END-READ`), any
  `SCOPE_TERMINATORS` / `CONTROL_FLOW_BOUNDARIES` value, or when a nested parser
  consumed the sentence period (`previous_meaningful_token` check). Pinned by
  `tests/unit/io_statements/test_clause_bodies.py`.
- **ON SIZE ERROR / NOT ON SIZE ERROR** (`parse_size_error_clauses` /
  `_parse_size_error_stmts`): bodies dispatch through the registry, so any verb is
  captured and registered as a child via the model's `_set_clause`. `ON` is
  optional (`SIZE ERROR`, `NOT SIZE ERROR`). A `NOT` is consumed only when it
  opens `NOT [ON] SIZE ERROR` -- otherwise it belongs to an enclosing handler (an
  ADD inside a CALL handler must leave the CALL's `NOT ON EXCEPTION`). Body
  termination: period (consumed), `NOT` / scope terminators / control-flow
  boundaries (not consumed), or a nested parser consuming the period. The
  optional `end_keyword` parameter consumes the statement's own terminator (and
  a trailing period); ON SIZE ERROR and an explicit terminator compose. Never
  replace this with a skip-to-period helper: EXEC SQL text has no period and a
  qualified table name (`BANK.ACCOUNT`) does.
- **CALL exception handlers** and other handler-bodied verbs follow the same
  pattern (see [statements-control.md](statements-control.md)).
- **Paragraph-level vs nested.** The PROCEDURE DIVISION loop calls
  `mark_top_level_statement(stream)` before each statement it dispatches
  itself; a parser that saved `stream.position` at its first token asks
  `is_top_level_statement(stream, start)`. XML/JSON uses it to decide whether
  a lone `NOT ON EXCEPTION` is its own (paragraph level, or closed by its own
  END-XML/END-JSON) or the enclosing handler's.

## Literal re-quoting (`_literals.py`)

The lexer hands every `STRING_LITERAL` over **decoded**: delimiters stripped and
a doubled delimiter collapsed (`'IT''S'` and `"IT'S"` both arrive as `IT'S`).
Anything that re-emits such a value as COBOL source must re-apply COBOL's only
escape: `_literals.quote_literal(value)` = `"` + value with every `"` doubled +
`"`. Without it, `DFHTRIG PIC X VALUE IS '"'` (CICS `DFHAID`) re-emits as an
unterminated three-quote literal that breaks `cobc` two lines later in
generated code. The module has zero internal dependencies (same rationale as
`_errors.py`) because callers span `divisions/` and `statements/`.

| Site | Clause |
|---|---|
| `divisions/data_clauses.py::parse_value_clause` | `VALUE <literal>` and `VALUE ALL <literal>` (typed literals keep `raw_value`, via `literal_source()`) |
| `divisions/environment_select.py` | SELECT's `ASSIGN TO <literal>` |
| `statements/move_parser.py` | MOVE's literal source |
| `statements/display_parser.py` | DISPLAY items and function-call operands |
| `statements/write_parser.py` | WRITE's `FROM <literal>` |
| `statements/_utils.py::literal_operand_text` | STRING / UNSTRING operands and delimiters, CALL `USING` arguments, INSPECT TALLYING / REPLACING / CONVERTING / BEFORE / AFTER values, SET's value (and PERFORM VARYING's `FROM` / `BY`, via `consume_value_operand`), INITIALIZE `REPLACING ... BY` |

Statement operands store the quoted spelling (`"A"`), so a literal `'A'` and the
data item `A` produce different AST values and `X'00'` keeps its prefix; every
consumer that already skips quoted text (unused-variables, lineage, xref) relies
on that rather than on a per-operand `is_literal` flag (#330). MOVE source and
DISPLAY items prefer `Token.raw_value` for typed literals (`X"41"`). Condition
tokens (IF, PERFORM UNTIL, SEARCH WHEN, EVALUATE `Condition` text) keep the
prefix too: `_conditions.condition_token_text` re-quotes a typed literal as
`X'0000'` (`typed_literal_prefix`), and `_is_literal_leg` accepts one as an
abbreviated leg (#331; `tests/regression/test_issue_331_typed_literal_conditions.py`). Level-88
values are the exception: stored undelimited (see [divisions.md](divisions.md)).
Round-tripping is the property that matters -- re-parsing an emitted clause
yields the identical clause. Pinned by
`tests/regression/test_embedded_quote_literals.py` and
`tests/regression/test_literal_operand_quotes.py`.

## Condition trees (`_conditions.py`)

`build_condition_expression` builds the structured condition tree shared by IF,
PERFORM UNTIL (`condition_tree`), EVALUATE and SEARCH WHEN (`condition_tree` next
to the raw `condition` text; #348). Class / sign / condition-name conditions
(`A IS NUMERIC`) get a structured node while `metadata.raw_condition` stays
populated. An AND / OR chain is split at every top-level operator in one
pass (`find_top_level_operators`; there is no single-operator variant) and the legs folded from the left
(`_fold_logical`): up to `_MAX_LEFT_DEEP_LEGS` (64) legs the tree is the
left-deep one it always was; a longer chain is paired neighbour by neighbour so
its depth stays O(log n) for every recursive walker (`to_dict`, rendering, the
analyzers). Recursing once per operator overflowed Python's stack at ~1,000
terms and was O(n^2) (#375). Its token-cleaning pass:

- Recombines `>=` / `<=` / `<>`, which the lexer emits as two single-character
  tokens (`_COMPOUND_SYMBOL_OPS`); otherwise `IF X >= 5` reads as `GREATER` with
  right operand `"= 5"`.
- Joins each operand with `join_operand()`, which folds a leading `+` / `-`
  (at the start or after `(`) into the unsigned number after it: `IF A = -7`
  has right operand `-7`, not `- 7`. `evaluate_parser.py` uses it for
  selector values and range bounds too (#747).
- Drops the `TO` / `THAN` connective after a relational word (`EQUAL TO B` ->
  right operand `B`) and folds `GREATER [THAN] OR EQUAL [TO]` into
  `GREATER_OR_EQUAL` / `LESS_OR_EQUAL` (not an OR of two conditions).
- After `NOT`, resolves the whole relational operator
  (`_match_relational_operator`) before negating via `_NEGATED_RELATIONAL`, so
  `NOT GREATER THAN OR EQUAL TO` / `NOT >=` / `NOT > =` is LESS and the `<=`
  family negates to GREATER.
- **Abbreviated combined conditions.** The implied subject is threaded through
  `build_condition_expression(..., subject=)` and expanded at the *leaf*: each
  leg's subject is the rightmost relation of the leg to its left, falling back to
  the one handed in. `A = 1 OR 2 AND NOT 3` is `A = 1 OR (A = 2 AND A NOT = 3)`;
  `A > 1 AND < 5 OR = 9` and `A = 1 OR (2 AND 3)` expand likewise. A leg may open
  with the optional `IS` of its operator (`A > 1 AND IS < 5`, `A = 1 OR IS
  EQUAL TO 2`; #403) -- `_expand_abbreviated_condition` drops a leading `IS` when
  an operator or `NOT` follows. Pinned by
  `tests/regression/test_review_2026_09_09_parser.py` (`TestFinding08ConditionTrees`)
  and `tests/regression/test_issue_403_abbreviated_leading_is.py`.
- **A leading NOT negates only its own relation** (#329): IBM reads `NOT A = 1
  OR 2` as `(NOT A = 1) OR (A = 2)`. `_negate_condition` folds the NOT into the
  relation's operator in place, so it records the operator as written on the
  node (`_abbreviation_operator`) and `_expand_abbreviated_condition` repeats
  that one; `A NOT = 1 OR 2` (NOT inside the operator) still carries NOT to the
  leg. Pinned by `tests/regression/test_issue_329_leading_not_abbreviated.py`.
- **A bare data-name leg** (`IF A = 'X' OR WS-B`, `A NOT < B OR C`, `WS-T (1)`,
  `X OF G`, `NOT WS-B`) expands like a literal leg (`A = WS-B`) when the
  already-parsed DATA DIVISION declares it as an ordinary item that is not also
  a level-88 name (#562). `ProcedureDivisionParser` threads
  `ParseContext.known_data_names` / `.condition_names` to the builder as a
  `ConditionSymbols` (`condition_symbols(context)`; IF, PERFORM UNTIL, SEARCH
  WHEN). A real 88, or a name the parse cannot see (unexpanded COPY, a
  SPECIAL-NAMES switch condition, a standalone `build_condition_expression`
  call with no `symbols=`), keeps the CONDITION_NAME reading. Pinned by
  `tests/regression/test_issue_562_abbreviated_data_name_leg.py`.
- **User class and OMITTED tests** (#539): `operand IS [NOT] word` -- `word` a
  SPECIAL-NAMES class-name, recognised by shape since the builder cannot see
  SPECIAL-NAMES -- and `operand [IS] [NOT] OMITTED` build `IS [NOT] <word>`
  nodes with the tested field as `left_operand`
  (`_build_user_class_or_omitted`), like `IS NUMERIC`. The operand must be one
  data reference; the class form needs its `IS` (`IF X VALID-CODE` stays a raw
  COMPARISON). Pinned by
  `tests/regression/test_issue_539_user_class_and_omitted_conditions.py`.
- Condition collectors drop layout tokens and bare separators (rule 6); a
  condition ending at a line break must not keep a trailing `"\n"`, or a bare
  condition-name / `NOT cond` / class test / `( ... )` falls back to a raw
  COMPARISON with `left_operand=None`.

## Adding a new statement parser

1. Create `cobolparser/parsers/statements/foo_parser.py` implementing `IStatementParser` (`parse()` + `matches()`)
2. Register it in `create_statement_registry()` (`parsers/divisions/procedure_registry.py` — the builder `ProcedureDivisionParser` uses), in the right first-match priority slot (more specific before general)
3. Add a `TokenType` entry in `lexer.py` if the verb is not yet a keyword
4. Add AST node(s) in the appropriate `cobolparser/models/statements/<category>.py` with `to_dict()`; use `ASTNodeFactory` from `core/ast_factory.py`
5. Export from `cobolparser/parsers/statements/__init__.py` and `cobolparser/models/statements/__init__.py`
6. Update `EXPECTED_ORDER` and `DISPATCH_CASES` in `tests/unit/test_procedure_registry_dispatch_order.py` — this pins the registration order and asserts the new parser dispatches for its own keyword(s); the suite fails loudly if the new registration is missing or misplaced
7. Add a fixture to `FIXTURES` in `tests/regression/test_swallow_sweep.py` (see [Swallow-sweep regression harness](#swallow-sweep-regression-harness)) — both this and step 6 fail the suite automatically if skipped, so neither strictly requires remembering to do it, but a real fixture snippet still needs a human to write it

Also: add the verb to `STATEMENT_TOKEN_TYPES` / `STATEMENT_KEYWORDS` (rule 1),
call `is_statement_boundary` and the H9 check in every list loop, and report a
missing required operand (rule 8).

## Swallow-sweep regression harness

`tests/regression/test_swallow_sweep.py` is the permanent form of the "period-less
statement X followed by a marker statement -- does the marker survive?" probe:

- One `Fixture(node_type, snippet, needs_file)` per class registered in
  `create_statement_registry()`, keyed by parser class name; each snippet is a
  minimal period-less statement (with an explicit `END-IF` / `END-EVALUATE` /
  `END-SEARCH` for scope-taking statements).
  `test_fixture_table_covers_every_registered_parser` diffs the table against
  `get_all_parsers()`, so a new parser without a fixture fails the suite.
- `test_marker_survives_after` asserts against **`CobolParagraph.statements`**
  (the flat, source-order list the PROCEDURE DIVISION parser appends to), not
  `CobolProgram.get_all_statements()`: a swallowed marker is not deleted but
  absorbed as a *child* of the statement under test, and `get_all_statements()`
  recurses into exactly those bodies, so it would report a false pass. The canary
  `TestHarnessDetectsSwallowing` reproduces that false-pass mode.
- **A fixture must exercise a loop or boundary check**, not a single
  unconditionally consumed token: the arithmetic fixtures use a subscripted
  `GIVING` target (`ADD 1 TO WS-A GIVING WS-C (WS-IDX)`) to route through
  `consume_optional_subscript`, because a bare scalar target stays green under
  mutation. Check a new fixture by mutating the parser's boundary check and
  confirming the fixture fails.

## See also

- [../parser.md](../parser.md) — routing page for the parser files
- [statements-control.md](statements-control.md) · [statements-data.md](statements-data.md) · [statements-io.md](statements-io.md) — per-verb rules
- [divisions.md](divisions.md) — the PROCEDURE DIVISION loop, paragraph boundaries, recovery
- [orchestration.md](orchestration.md) — `TokenStream`, registry, `ParseContext`
- [../ast-models.md](../ast-models.md) — the statement node classes and their fields
- [history](../history/parser.md) — archived dated notes behind these rules
