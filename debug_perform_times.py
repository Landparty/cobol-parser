"""Debug PERFORM THRU TIMES parsing."""
from cobolparser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode

source = """
    IDENTIFICATION DIVISION.
    PROGRAM-ID. TEST-THRU-TIMES.
    PROCEDURE DIVISION.
    MAIN-PARA.
        PERFORM PARA-A THRU PARA-B 5 TIMES.
        STOP RUN.
    PARA-A.
        DISPLAY 'A'.
    PARA-B.
        DISPLAY 'B'.
"""

parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
result = parser.parse(source)

print(f"Parse success: {result.success}")
print(f"Errors: {result.errors}")

proc_div = result.ast.get_division("PROCEDURE")
print(f"Procedure division: {proc_div}")

if proc_div:
    # Find the PERFORM statement
    main_para = next((s for s in proc_div.sections if s.section_name == "MAIN-PARA"), None)
    print(f"MAIN-PARA: {main_para}")
    if main_para:
        print(f"MAIN-PARA children: {main_para.children}")
        perform_stmts = [c for c in main_para.children if hasattr(c, 'target_paragraph')]
        print(f"PERFORM statements: {perform_stmts}")
        if perform_stmts:
            perform_stmt = perform_stmts[0]
            print(f"Perform stmt: {perform_stmt}")
            print(f"target_paragraph: {perform_stmt.target_paragraph}")
            print(f"thru_paragraph: {perform_stmt.thru_paragraph}")
            print(f"perform_type: {perform_stmt.perform_type}")
            print(f"times_count: {perform_stmt.times_count}")
            print(f"Perform stmt to_dict: {perform_stmt.to_dict()}")
