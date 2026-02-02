# QUICK REFERENCE: Parser Refactoring State

## ✅ Completed Work

- **3 parsers extracted:** DISPLAY, MOVE, Arithmetic (ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE)
- **Registry system:** Implemented and 7 parsers registered
- **Infrastructure:** TokenStream, StatementParser protocol, ParseContext

## ❌ Failing Tests: 116 (4.9% of 2,349)

**By Category:**
- EVALUATE: 8+ failures (selector mismatch, END-EVALUATE validation)
- IF: 5+ failures (THEN/ELSE termination)
- Preprocessing: 15+ failures (line continuation)
- Other: 80+ failures (division context, IO coverage, real-world patterns)

---

## Parser Methods to Extract - Line Counts

```
┌─────────────────┬───────────┬────────────────────────┬──────────┐
│ Statement       │ Main Loc  │ Scope (primary + inline│ Effort   │
├─────────────────┼───────────┼────────────────────────┼──────────┤
│ CALL            │ 6617      │ 317 + 200 + helpers    │ HARD     │
│ IF              │ 6478      │ 137 + 100 + nesting    │ MEDIUM   │
│ PERFORM         │ 5552      │ 319 + 200 + (x5 variants)│ V.HARD   │
│ EVALUATE        │ 6041      │ 157 + 270 + selector   │ HARD     │
├─────────────────┼───────────┼────────────────────────┼──────────┤
│ TOTAL           │ —         │ ~930 + ~800 helpers    │ (2,000+ lines)│
└─────────────────┴───────────┴────────────────────────┴──────────┘
```

---

## AST Freezing Impact

**Current:** Mutable nodes with `set_*()` and `add_*()` methods
**Required:** Frozen dataclasses with immutable construction

**Affected Nodes:** ~80 AST classes
**Parser Code Changes Needed:** ~2,500 lines
**When:** After extraction (Phase 4)

---

## Parser Extraction Priority

| Rank | Parser    | Reason | Fix Tests? | Duration |
|------|-----------|--------|-----------|----------|
| 1    | EVALUATE  | 8+ tests fail, high value | YES | 3 hrs |
| 2    | CALL      | Clear scope, proven pattern | YES | 4 hrs |
| 3    | IF        | Medium complexity, 5+ tests | YES | 2 hrs |
| 4    | PERFORM   | Most complex (6 variants) | YES | 6 hrs |

---

## Registry Registration Pattern

**File:** `parser.py` __init__ @ line 192

**Current:**
```python
self.registry.register(DisplayStatementParser())     # ✅
self.registry.register(MoveStatementParser())        # ✅
# ... 5 arithmetic parsers
```

**New (Add 4):**
```python
self.registry.register(EvaluateStatementParser())    # Add
self.registry.register(CallStatementParser())        # Add
self.registry.register(IfStatementParser())          # Add
self.registry.register(PerformStatementParser())     # Add
```

---

## Parser Implementation Template

```python
# File: cobolparser/parsers/<statement>_parser.py
from ..core.interfaces import StatementParser, ParseContext
from ..core.token_stream import TokenStream
from ..models.statements import <Statement>Node

class <Statement>StatementParser(StatementParser):
    def can_parse(self, stream: TokenStream) -> bool:
        token = stream.peek()
        return (token and (token.type == TokenType.<KEYWORD> or
                (token.type == TokenType.IDENTIFIER and 
                 token.value.upper() == "<KEYWORD>")))
    
    def parse(self, stream: TokenStream, context: ParseContext) -> <Statement>Node:
        # Extract method from parser.py
        # Follows pattern: token detection → option parsing loops → terminator handling
        pass
```

---

## Frozen Dataclass Conversion Pattern

**Before (Current):**
```python
class MoveStatement(CobolStatement):
    def __init__(self, location):
        super().__init__("MOVE", location)
        self.source = None
        self.targets = []
    
    def set_source(self, source):
        self.source = source
    
    def add_target(self, target):
        self.targets.append(target)
```

**After (Required):**
```python
@dataclass(frozen=True)
class MoveStatement(CobolStatement):
    source: Optional[str] = None
    targets: tuple[str, ...] = field(default_factory=tuple)  # Immutable
    
    # No setters, use dataclass.replace() in parser
```

**Parser Usage:**
```python
# Before: stmt.add_target(target)
# After: stmt = dataclass.replace(stmt, targets=(*stmt.targets, target))
```

---

## Files to Create/Modify

| File | Action | Lines | Priority |
|------|--------|-------|----------|
| `cobolparser/parsers/evaluate_parser.py` | CREATE | ~280 | 1 |
| `cobolparser/parsers/call_parser.py` | CREATE | ~380 | 2 |
| `cobolparser/parsers/if_parser.py` | CREATE | ~200 | 3 |
| `cobolparser/parsers/perform_parser.py` | CREATE | ~400 | 4 |
| `cobolparser/parser.py` | MODIFY | -930 (methods extracted) | ALL |
| `cobolparser/models/statements.py` | MODIFY | +200 (frozen conversions) | Later |

---

## Key Success Criteria

- ✅ All 116 tests passing
- ✅ Parser.py reduced to < 6,200 lines (from 8,113)
- ✅ No method complexity > 15 in new parsers
- ✅ 100% branch coverage in new parsers
- ✅ AST nodes frozen and immutable
- ✅ Registry integration complete

---

## Detailed Research Output

- **Full Report:** `plans/research_report.md` (comprehensive analysis)
- **Summary:** `plans/research_summary.md` (structured findings)
- **Audit Trail:** `plans/undone.md` (existing phase status)
