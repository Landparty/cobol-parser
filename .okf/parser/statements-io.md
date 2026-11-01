---
type: Module
title: I/O and EXEC statement parsers
description: Per-verb parsing rules for the file and system statements -- OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, UNLOCK, SORT / MERGE, RELEASE / RETURN, EXEC SQL / CICS / IMS DLI, Report Writer (INITIATE / GENERATE / TERMINATE / SUPPRESS) and the Communication Module verbs.
tags: [parser, statement, io, read, write, sort, exec-sql, exec-cics]
timestamp: 2026-10-15T00:00:00Z
---

# I/O and EXEC statement parsers

Rules and gotchas for `open_parser.py`, `close_parser.py`, `read_parser.py`,
`write_parser.py`, `rewrite_parser.py`, `delete_parser.py`, `start_parser.py`,
`unlock_parser.py`, `sort_merge_parsers.py`, the RELEASE / RETURN parsers in
`simple_statement_parsers.py`, `ibm_exec_statements.py`,
`report_writer_parsers.py` and `communication_parsers.py`. IO clause bodies
(`AT END`, `INVALID KEY`, ...) are parsed by the shared `collect_clause_stmts`
described in [statements.md](statements.md#clause-and-handler-bodies), together
with the boundary invariants every parser keeps. Node fields (`IOReadStatement`,
`IOWriteStatement`, ...) are in [ast-models.md](../ast-models.md); EXEC SQL
semantics in [dialects.md](../dialects.md).

## OPEN and CLOSE

- **Multi-mode OPEN.** One OPEN may carry several mode groups (`OPEN INPUT
  FILE-A OUTPUT FILE-B EXTEND FILE-C`); the parser collects every group's files
  into `IOOpenStatement.file_names`, records each file's own mode in
  `file_modes: dict[str, str]` (via `add_file(..., mode=)`), and keeps
  `open_mode` as the **first** group's mode only (back-compat). A consumer that
  reads `open_mode` alone sees every file under the first mode; read
  `file_modes`. Pinned by
  `tests/unit/io_statements/test_open_read_parsers.py::TestOpenParserCoverage`.
- Both file lists accept commas (`OPEN INPUT A, B`, `CLOSE F1, F2`), stop at
  `is_statement_boundary`, and apply the H9 dedent check at every position.
- OPEN options `[WITH] NO REWIND`, `REVERSED`, `[WITH] LOCK`; CLOSE options
  `REEL` / `UNIT` / `[WITH] NO REWIND` / `[WITH] LOCK`, parsed in a loop per file
  so combined options (`CLOSE F REEL WITH NO REWIND`) all survive, across several
  files in one CLOSE.

## READ, WRITE, REWRITE, DELETE

- **READ**: `AT` is optional (`END` / `NOT END`; a bare `END` is an AT END only
  when it does not start `END PROGRAM` / `END FUNCTION` / `END DIVISION`); a separator may precede
  the handler (`READ F ; AT END`). The `INTO` target and `KEY` name fold
  qualifiers / subscripts. `READ F WITH LOCK KEY IS k` is accepted.
- **WRITE**:
  - The record name and `FROM` source fold qualifiers / subscripts; `FROM` also
    takes a literal (an IBM / GnuCOBOL extension), stored re-quoted.
  - `BEFORE|AFTER [ADVANCING] {n [LINE|LINES] | identifier [LINE|LINES] |
    mnemonic-name | PAGE}`: `ADVANCING` is optional, and every form yields an
    `advancing_clause` dict -- `{"type": "AFTER", "value": 1, "unit": "LINES"}`;
    `PAGE` -> `"value": "PAGE", "unit": "CHANNEL"`; an identifier followed by
    `LINE` / `LINES` -> `{"unit": "LINES", "value": <name>}`; an identifier with
    no unit is a SPECIAL-NAMES mnemonic -> `{"unit": "MNEMONIC", "value":
    <name>}` (`IOWriteStatement.set_advancing(identifier=|mnemonic=)`, exclusive
    with `lines=` / `page=`). `ADVANCING ZERO` is accepted. A dangling
    identifier here would be read as a phantom paragraph. Pinned by
    `tests/unit/test_write_advancing.py`.
  - `INVALID KEY` / `NOT INVALID KEY` via `parse_invalid_key_clauses`; `[AT]
    END-OF-PAGE` / `NOT [AT] END-OF-PAGE` via `collect_clause_stmts`
    (`set_at_eop_clause` / `set_not_at_eop_clause`). Both families are attempted
    regardless of file organization -- the parser does not know which SELECT
    governs the record, and the standard makes them mutually exclusive.
- **REWRITE**: `FROM` source (identifier, subscripted reference or literal) is
  stored in `from_clause`, mirroring WRITE.
- **DELETE**: `INVALID KEY` / `NOT INVALID KEY` via `parse_invalid_key_clauses`.

## START and UNLOCK

- **START** (`start_parser.py`): the comparison words lex as dedicated token
  types, not IDENTIFIERs, so they are matched by value -- including the `TO`
  (`TokenType.TO`) after `OR EQUAL`; missing it blocks the key-name and every
  handler after it. Accepted: `KEY IS = / > / >= k`, `KEY [IS] GREATER [THAN] OR
  EQUAL [TO] k`, a separator before `INVALID KEY`. The key data-name is stored in
  `IOStartStatement.key_name` (qualifiers / subscripts folded); `key_condition`
  holds the operator.
- **UNLOCK**: the operand read is guarded by `is_statement_boundary`.

## SORT and MERGE

- The clause loop (`WITH` / `COLLATING` / `USING` / `GIVING` / `INPUT` /
  `OUTPUT` / ...) breaks on `is_statement_boundary` and the H9 dedent check (verb
  column as reference) instead of consuming unknown tokens.
- `_parse_keys` (`{ASCENDING|DESCENDING} KEY [IS] field-1, field-2 ...`) and
  `_parse_file_list` (`USING` / `GIVING` lists) consume commas and continue,
  break on statement boundaries, and take an optional `reference_column` for the
  H9 check. A comma left unconsumed by the key loop would otherwise be eaten by the
  outer loop together with a following USING / GIVING keyword. `KEY IS k`
  (GnuCOBOL spelling) keeps the key; `SEQUENCE` also ends the key list.
- Optional keywords: SORT `[WITH] DUPLICATES`, SORT/MERGE `[COLLATING]
  SEQUENCE [IS] name` (`_parse_collating_sequence`).
- A file SORT (USING / GIVING / INPUT / OUTPUT present) or any MERGE that
  collects no key adds a warning ("no sort keys were recorded"); a table SORT may
  omit keys. `INPUT` / `OUTPUT PROCEDURE ... THRU` names are IDENTIFIER-only.
  Pinned by `tests/regression/test_optional_keyword_forms.py`,
  `tests/unit/test_initialize_sort_arithmetic_comma_gaps.py`.

## RELEASE and RETURN

`simple_statement_parsers.py`: RELEASE `FROM` and RETURN `INTO` operands go
through `consume_optional_qualifiers`, as MOVE's do (`WS-REC OF GRP`,
`TBL ( I )`). RETURN's `AT END` clause accepts a bare `END` (`AT` optional) and
skips statement separators in its body.

## EXEC SQL, CICS and IMS

- **Block text** (`_utils.collect_exec_sql_text`). The only safe end marker is
  the mandatory `END-EXEC`: embedded SQL / CICS / DLI legitimately contains COBOL
  statement words (SET, DELETE, UPDATE, CALL, OPEN, CLOSE), so EXEC parsing is
  deliberately **not** routed through `is_statement_boundary` -- a keyword
  boundary would truncate valid SQL. If the stream ends before `END-EXEC`, a
  non-fatal "Unterminated EXEC block: missing END-EXEC" error is recorded through
  the stream's parse context (`result.success` is `False`); the DATA DIVISION
  caller attaches no context, so it stays silent there.
- **Text fidelity.** Raw-text reconstruction rejoins a lexer-split relational
  operator without a space (`>=`, `<=`, `<>`, `!=`, `¬=` -- `NOT_SIGN` + `ASSIGN`
  -- and `||`, via `_EXEC_SQL_SPLIT_RELOP_PAIRS`), and keeps a qualified name
  together by column adjacency (`_follows_qualifier_period`: `BANK.ACCOUNT` stays
  one word, a period written with a space `T. X` does not join).
  `collect_exec_sql_text(stream, sql=True)` (EXEC SQL callers only) re-quotes
  string literals and drops `--` line comments -- see [dialects.md](../dialects.md)
  "EXEC SQL text: literals and `--` comments".
- **Structure.** `_parse_cics_options` parses the CICS option list into
  `ExecCicsStatement.options: dict[str, str | None]` (keyword -> argument text
  inside parentheses, `None` for flags such as `ERASE` / `NOHANDLE`; nested
  parentheses and quoted literals handled). The CICS command verb is read after
  skipping layout, so `EXEC CICS` / newline / `SEND ...` (the usual layout) keeps
  its verb. `ExecImsStatement` captures the DLI function code plus top-level
  positional arguments (PCB, I/O area, SSAs); its `ims_call_type` is the command
  word when it is in `IBMEnterpriseCobol.EXEC_DLI_COMMANDS`, else `UNKNOWN`
  (`_IMS_CALL_TYPES` is that set, not a copy -- #481). `parse_exec_sql`
  (`models/sql_statements.py`) is a literal/comment-aware tokenizer: statement
  kind, tables (FROM / INTO / UPDATE / JOIN; `_SQL_TABLE_NAME` takes `#`, `@`
  and `$` like a DB2 ordinary identifier, so `T#TAB` is one table, not a
  phantom `T` beside it, #770), host variables including
  `:VAR:IND`, and for SELECTs `select_columns` + `where_present`.
  `DeclareTableStatement` accepts a qualified `DECLARE SCHEMA.TABLE TABLE`
  (spaces around the period tolerated, name normalized).
- `ExecCicsStatement` / `ExecImsStatement` are `CobolStatement` subclasses
  (`statement_type` `"EXEC CICS"` / `"EXEC IMS"`; `node_type` `"EXEC_CICS"` /
  `"EXEC_IMS"`; `cics_command` / `ims_command` are read-write properties), so
  `get_all_statements()` -- where every analyzer starts -- returns them.
  `ExecCicsStatement.to_dict()` adds `possible_values` (and
  `possible_values_incomplete` when True) only once `DynamicCallAnalyzer` has
  set them, on a LINK / XCTL / LOAD with a data-name `PROGRAM(...)` (see
  [../analysis/data-use.md](../analysis/data-use.md#dynamiccallanalyzer));
  every other EXEC CICS node keeps its historical shape.
- Dispatch: the registry cache key includes the first meaningful token after
  `EXEC`, so `EXEC <newline> CICS` and `EXEC <newline> SQL` reach different
  parsers (see [orchestration.md](orchestration.md)).

## Report Writer and Communication verbs

- **Report Writer**: `INITIATE`, `TERMINATE`, `SUPPRESS`
  (`report_writer_parsers.py`) and `GENERATE` (`simple_statement_parsers.py`).
  The REPORT SECTION itself is in [divisions.md](divisions.md).
- **Communication Module** (COBOL-85): `SEND`, `RECEIVE`, `ENABLE`, `DISABLE`,
  `PURGE` (`communication_parsers.py`; `PURGE` matched by value). `END-RECEIVE` is
  in `SCOPE_TERMINATORS` and `STRAY_MARKERS`. RECEIVE's `NO DATA` / `WITH DATA`
  handlers are separate bodies (a MOVE inside the first must not absorb `WITH
  DATA`).
- Operands use `_utils.collect_operands`.

## See also

- [statements.md](statements.md) — table, boundary invariants, shared helpers, clause bodies
- [statements-control.md](statements-control.md) · [statements-data.md](statements-data.md) — the other verb groups
- [../dialects.md](../dialects.md) — EXEC SQL / CICS / IMS node semantics
- [../ast-models.md](../ast-models.md) — the IO statement node classes
- [history](../history/parser.md) — archived dated notes behind these rules
