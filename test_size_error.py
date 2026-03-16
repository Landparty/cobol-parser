#!/usr/bin/env python
"""Test Size Error clause parsing."""

from cobolparser import CobolParser

src = """IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
PROCEDURE DIVISION.
    ADD A TO B
        ON SIZE ERROR
            DISPLAY \"Error\"
            MOVE X TO Y.
"""

result = CobolParser().parse(src)

# Check for errors
if result.errors:
    print("Parse errors:")
    for err in result.errors:
        print(f"  - {err}")
else:
    print("No parse errors")

proc_div = result.ast.procedure_division

# Navigate the structure - procedure division contains paragraphs
print(f"Procedure division: {proc_div}")
print(f"  - Has sections: {bool(proc_div.sections)}")
print(f"  - Has paragraphs: {bool(proc_div.paragraphs)}")

stmts = []
if proc_div.paragraphs:
    # Procedure division can have implicit paragraphs
    for i, para in enumerate(proc_div.paragraphs):
        print(f"Para {i}: {para}")
        if hasattr(para, 'statements'):
            print(f"  - Statements: {para.statements}")
            stmts.extend(para.statements)
elif proc_div.sections:
    # Or it can have sections with paragraphs
    for section in proc_div.sections:
        if hasattr(section, 'paragraphs'):
            for para in section.paragraphs:
                if hasattr(para, 'statements'):
                    stmts.extend(para.statements)

print(f"\\nTotal statements found: {len(stmts)}")
if stmts:
    stmt = stmts[0]
    print(f'Statement type: {stmt.statement_type}')
    print(f'On size error: {stmt.on_size_error}')
    if stmt.on_size_error:
        print(f'Nested statements count: {len(stmt.on_size_error)}')
        for s in stmt.on_size_error:
            print(f'  - {s.statement_type}')
    else:
        print('ERROR: on_size_error is None!')
else:
    print("ERROR: No statements found!")



