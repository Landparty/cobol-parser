---
type: Integration Contract
title: Backend Integration Contract
description: Dict shape returned by the cobol-parser and consumed by the backend adapter
tags: [integration, backend, contract, cobol-parser]
timestamp: 2026-06-28T00:00:00Z
resource: ../interface-contract.md
---
# Backend Integration Contract

This concept documents the exact API that `cobolparser` exposes and that the backend adapter (`backend/src/parsers/cobol/parser.py`) consumes.

> Full canonical contract: `interface-contract.md` (repo root — see `resource` field in frontmatter)

**Integration method:** `cobol-parser` is **vendored** into `backend/_vendor/cobol-parser/`. Changes must be manually synced:
```bash
cp -r cobolparser/ ../backend/_vendor/cobol-parser/cobolparser/
```

**Import path in backend:**
```python
from ..dependencies import CobolParser, CobolProgram, DialectType, ErrorRecoveryMode, \
    DynamicCallAnalyzer, ProgramFlowAnalyzer, CobolParseError
```

---

## Entry Points

### Parser construction + parse
```python
parser = CobolParser(
    dialect=DialectType.IBM_ENTERPRISE,
    error_recovery=ErrorRecoveryMode.COLLECT_ALL,
)
parse_result = parser.parse(cleaned_content)           # no filename
parse_result = parser.parse(cleaned_content, filename) # with filename str
```

### Optional analyzers (fault-isolated)
```python
# Mutates AST nodes in-place; silently skipped if DynamicCallAnalyzer absent
DynamicCallAnalyzer().analyze(parse_result.ast)

# Returns dict via flow_report.to_dict(); stored in metadata["program_flow_data"]
flow_report = ProgramFlowAnalyzer().analyze(parse_result.ast)
```

### Exception
```python
from cobolparser import CobolParseError  # caught specifically by the adapter
```

---

## ParseResult Attributes

| Attribute | Type | Notes |
|-----------|------|-------|
| `result.success` | `bool` | `True` = AST was built |
| `result.ast` | `CobolProgram \| None` | `None` when `success` is `False` |
| `result.errors` | `list` | Each item has `.line_number` (`int \| None`) and `.message` (`str`) |
| `result.warnings` | `list` | Items stringified with `str()` |
| `result.statistics` | object \| None | Must have `.to_dict() -> dict` if not `None` |

## CobolProgram Attributes

| Attribute | Expected |
|-----------|----------|
| `program.program_name` | `str \| None` |
| `program.get_statistics()` | `dict` with at least `"total_lines": int` |

---

## Output: program_structure Dict

```json
{
  "program_info": {
    "name": "<str>",
    "type": "COBOL",
    "language_version": "IBM Enterprise COBOL",
    "encoding": "utf-8",
    "line_count": 1200,
    "complexity_score": 12.5,
    "uses_cics": true,
    "uses_ims": false,
    "uses_mq": false,
    "is_transactional_likely": true,
    "is_batch_likely": false,
    "is_bmp_program": false
  },
  "structure": {
    "sections": [{"name": "MAIN", "type": "section", "start_line": 10, "end_line": 50}],
    "variables": [{"name": "WS-COUNTER", "type": "PIC 9(4)", "definition_line": 20}],
    "procedures": [{"name": "MAIN-PARA", "start_line": 100, "end_line": 150, "calls": [], "called_by": []}]
  },
  "dependencies": {
    "includes": ["COPYBOOK-A"],
    "calls": ["SUBPROG1"],
    "databases": [{"name": "MYDB", "type": "DB2", "tables": ["ACCOUNTS"]}],
    "copy_statements": [],
    "file_io": [],
    "cics_commands": [],
    "mq_operations": []
  },
  "analysis": {
    "metrics": {},
    "issues": [],
    "modernization_hints": [],
    "classification_hints": {},
    "cics_indicators": {},
    "ims_indicators": {},
    "mq_indicators": {}
  }
}
```

## Critical Paths for Relationship Extraction

| Path | Neo4j Relationship |
|------|--------------------|
| `dependencies.calls` | `CALLS` |
| `dependencies.includes` | `COPYBOOK` |
| `dependencies.databases` | `USES_DB2` |
| `dependencies.cics_commands` | `USES_CICS` |
| `dependencies.mq_operations` | `USES_MQ` |
| `program_info.name` | canonical name in DB |

---

## ParserResult Container (backend)

```python
@dataclass
class ParserResult:
    success: bool
    program_structure: dict | None
    error_message: str | None   # prefixes: EMPTY_CONTENT, COBOL_PARSE_ERROR, SYNTAX_ERROR,
                                #           PARSE_FAILED, PARSER_INTERNAL_ERROR, INTERNAL_ERROR
    metadata: dict              # parse timing, dialect, version, injection stats
```

## File Extensions Handled

`.cbl`, `.cob`, `.cobol`, `.cpy`, `.copy` (and uppercase variants). `.cpy`/`.copy` files are treated as copybooks.

---

# Citations
- `interface-contract.md` (repo root)
- [../../backend/.okf/services/](../../backend/.okf/services/)
