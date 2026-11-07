---
type: Module
title: Parser
description: Routing page for the parser reference -- CobolParser / ParseResult, the division parsers, the 72 statement parsers and their shared helpers, core/ infrastructure, plugins/core.py configuration and profiling.py. Says which file under parser/ to load for a task.
tags: [parser, ast, division, statement, registry]
timestamp: 2026-10-15T00:00:00Z
---

# Parser

`cobolparser/parser.py`'s `CobolParser` turns COBOL source into a `ParseResult`:
line-count-preserving source passes, lexing into a `TokenStream`, then one
division parser per division (`DivisionParserFactory`); the PROCEDURE DIVISION
dispatches every statement first-match through a `StatementParserRegistry` of 72
statement parsers. Entry points are `parse_cobol(...)` and
`CobolParser(...).parse(source)` / `.parse_file(path)`. The reference is split
under [parser/](parser/) -- load only the file the table below names.

## Which file?

| Task / class | Load |
|---|---|
| `parse_cobol`, `CobolParser`, `ParseResult`, statistics, errors vs warnings | [parser/orchestration.md](parser/orchestration.md) |
| Source passes before lexing (header skip, `CBL`/`PROCESS`, format detection, `REPLACE`, debug lines) | [parser/orchestration.md](parser/orchestration.md) |
| Multi-program members, nested programs, OO `CLASS-ID` / `METHOD-ID` units | [parser/orchestration.md](parser/orchestration.md) |
| `core/` (`TokenStream`, `StatementParserRegistry`, `ASTNodeFactory`, `ParseContext`, exceptions), `_errors.py` | [parser/orchestration.md](parser/orchestration.md) |
| `plugins/core.py` (`ErrorRecoveryMode`, `MemoryConfiguration`, `ParseStatistics`, ...), `profiling.py` | [parser/orchestration.md](parser/orchestration.md) |
| IDENTIFICATION / ENVIRONMENT division, SELECT, SPECIAL-NAMES | [parser/divisions.md](parser/divisions.md) |
| DATA DIVISION: PICTURE / VALUE / USAGE / OCCURS, FD / SD / RD, REPORT SECTION, level-88/66 | [parser/divisions.md](parser/divisions.md) |
| PROCEDURE DIVISION loop, paragraph / section boundaries, DECLARATIVES, `UNSUPPORTED_VERBS` recovery | [parser/divisions.md](parser/divisions.md) |
| Verb -> parser table, registration order, boundary invariants (statement swallowing, H9), `_utils.py` helpers, `_literals.py`, `_conditions.py`, adding a statement parser | [parser/statements.md](parser/statements.md) |
| IF, EVALUATE, PERFORM, GO TO, ALTER, SEARCH, CALL, ENTRY, INVOKE, STOP, NEXT SENTENCE, legacy verbs | [parser/statements-control.md](parser/statements-control.md) |
| MOVE, ADD / SUBTRACT / MULTIPLY / DIVIDE, COMPUTE, SET, INITIALIZE, INSPECT, STRING / UNSTRING, DISPLAY, ACCEPT, XML / JSON, ALLOCATE / FREE | [parser/statements-data.md](parser/statements-data.md) |
| OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, SORT / MERGE, RELEASE / RETURN, EXEC SQL / CICS / IMS, Report Writer, Communication | [parser/statements-io.md](parser/statements-io.md) |
| Why a rule exists (audits, sweeps, issue write-ups) | [history/parser.md](history/parser.md) |

## Pipeline at a glance

```
CobolParser.parse(source) -> _parse_core()
  ├─ _preprocess_source()     skip to header, strip CBL/PROCESS, detect + normalize
  │                           fixed format, >>IF/>>DEFINE, strip unexpanded COPY, REPLACE
  ├─ _tokenize()              CobolLexer -> TokenStream (COMMENT tokens excluded)
  └─ parse_program()          DivisionParserFactory, one unit at a time
       ├─ IdentificationDivisionParser
       ├─ EnvironmentDivisionParser
       ├─ DataDivisionParser
       └─ ProcedureDivisionParser -> StatementParserRegistry (first match, 72 parsers)
```

Two invariants run through every file: **`errors == []` and `warnings == []`
mean a complete AST** (anything recognized but not represented leaves a warning),
and **a statement never swallows what follows it** (every operand loop stops at
statement, scope-terminator and paragraph boundaries without consuming them).

## Public API

```python
from cobolparser import CobolParser, ParseResult, parse_cobol
from cobolparser import ErrorRecoveryMode, MemoryConfiguration

result: ParseResult = parse_cobol(source, filename="prog.cob")  # FAIL_FAST default
parser = CobolParser(
    memory_config=MemoryConfiguration(max_error_count=100),  # memory fields: not enforced
    error_recovery=ErrorRecoveryMode.COLLECT_ALL,               # the CLI default
)
result = parser.parse(source)

result.ast            # CobolProgram | None (contained_programs for extra units)
result.errors         # list[ParseError]
result.warnings       # list[str] -- "recognized but degraded"
result.statistics     # ParseStatistics snapshot
result.success        # ast is not None and no errors
```

Full signatures: [parser/orchestration.md](parser/orchestration.md#public-api).

## See also

- [lexer.md](lexer.md) — upstream tokenisation, `TokenType`, the lexer's
  warnings channel
- [preprocessing.md](preprocessing.md) — `normalize_fixed_format`, format
  detection, copybook expansion and the source map
- [ast-models.md](ast-models.md) — what `ParseResult.ast` contains
- [analysis.md](analysis.md) — consumers of the AST
- [history](history/parser.md) — archived dated notes moved out of this file
