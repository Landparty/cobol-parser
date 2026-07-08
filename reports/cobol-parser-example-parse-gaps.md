# Example-corpus parse gaps surfaced by the mockymock sweep (2026-07-08)

Scope: `cobolparser`, exercised through the sibling **mockymock** tool, which
parses a program and refuses to proceed whenever the parser reports a warning
that it *dropped tokens from the AST* (splicing an AST with missing behavior
would silently drop that behavior from a generated test). Running mockymock's
`generate` over this repo's own example corpus therefore doubles as a
fail-closed audit of where the parser silently under-parses real COBOL.

Method: `mockymock generate` over `examples/cobol/` (459 NIST COBOL-85
programs) and `examples/cobol/shamrice/` (24 real IBM/GnuCOBOL programs),
tallying the "Unparsed tokens starting at 'X' … content dropped from the
AST" warnings. Empirically reproduced at runtime.

## Headline

- **222 of the 459 NIST programs** and **20 of the 24 shamrice programs** are
  parsed with at least one *dropped-content* warning: `errors == 0` but the
  AST is missing statements or clauses.
- The gaps cluster in a small number of very common constructs — figurative
  constants as `DISPLAY` operands, screen positioning, and
  `DISPLAY/ACCEPT … WITH NO ADVANCING`. Because these appear in almost every
  interactive GnuCOBOL program, they block a large fraction of any
  real-world corpus even though each individual gap is small.

## Triggers (counted across the 24 shamrice programs)

| Trigger token | Count | Construct that is dropped |
|---------------|------:|---------------------------|
| `SPACE` / `SPACES` | 56 | figurative constant as a `DISPLAY` operand — `DISPLAY SPACE`, `DISPLAY SPACES` |
| `AT` | 32 | screen positioning — `DISPLAY … AT LINE n COLUMN m`, `ACCEPT … AT …` |
| `WITH` | 13 | `DISPLAY … WITH NO ADVANCING`, `ACCEPT … WITH …` clauses |
| `(` | 6 | expression / subscript inside an unsupported clause |
| `LINE` | 4 | screen positioning (`LINE`/`COL`) |
| `SECURE`, `TIMEOUT`, `AUTO-SKIP`, `NO-ECHO`, `UPPER` | 1 each | extended `ACCEPT` clauses |
| `INITIATE`, `TERMINATE` | 1 each | Report Writer verbs |
| `STATUS`, `NAME`, `YYYYMMDD`, `YYYYDDD` | 1 each | `ACCEPT FROM` environment/date phrases |

Concrete example — `examples/cobol/shamrice/main_app.cbl` (parses with
`errors == 0`) drops four statements:

```
line 23:  display space                     -> 'SPACE' skipped
line 24:  display "..." with no advancing    -> 'WITH' skipped
line 27:  ... with no advancing              -> 'WITH' skipped
line 66:  display space                     -> 'SPACE' skipped
```

## Why it matters

These are not exotic dialects — `DISPLAY SPACE`, `WITH NO ADVANCING`, and
screen-section `ACCEPT`/`DISPLAY … AT LINE … COLUMN` are everyday
GnuCOBOL/IBM interactive I/O. A downstream consumer that trusts `errors == 0`
(as mockymock initially did) will act on an AST that is quietly missing the
program's console interaction. mockymock now treats any dropped-content
warning as a hard refusal; other consumers should be aware the warning list
is load-bearing, not advisory.

## Suggested follow-ups (parser side)

1. Accept figurative constants (`SPACE`/`SPACES`/`ZERO`/`ZEROES`/`QUOTE`/
   `LOW-VALUE`/`HIGH-VALUE`) as `DISPLAY` (and `ACCEPT`) operands.
2. Parse the `WITH NO ADVANCING` phrase on `DISPLAY`.
3. Parse screen-positioning phrases (`AT LINE … COLUMN …`, `LINE`/`COL`) and
   the extended `ACCEPT` clauses (`SECURE`, `TIMEOUT`, `AUTO-SKIP`,
   `NO-ECHO`, `UPPER`, `UPDATE`) at least well enough not to drop the rest of
   the statement.
4. Where a clause genuinely isn't supported yet, prefer recovering to the
   next statement boundary *without* discarding the verb node, so consumers
   see the statement even if a trailing clause is unmodeled.

Full end-to-end context (how these gaps cap mockymock's reach over this
corpus) is in mockymock's `docs/2026-07-08-cobol-parser-corpus-sweep.md`.
