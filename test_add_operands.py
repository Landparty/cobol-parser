from cobolparser import CobolParser

src = """IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
PROCEDURE DIVISION.
    ADD 1 TO A.
    ADD A B TO C.
    ADD A TO B GIVING C.
    ADD A TO B ROUNDED.
"""

result = CobolParser().parse(src)
proc_div = result.ast.procedure_division

# Navigate the structure
if hasattr(proc_div, 'sections') and proc_div.sections:
    section = proc_div.sections[0]
    if hasattr(section, 'paragraphs') and section.paragraphs:
        para = section.paragraphs[0]
        stmts = para.statements if hasattr(para, 'statements') else []
    elif hasattr(section, 'statements'):
        stmts = section.statements
    else:
        stmts = []
else:
    stmts = []

print(f'Statement count: {len(stmts)}')
for i, stmt in enumerate(stmts):
    print(f'{i}: {stmt.statement_type} - operands={stmt.operands}, target={stmt.target if hasattr(stmt,"target") else "N/A"}, giving={stmt.giving if hasattr(stmt,"giving") else "N/A"}')

