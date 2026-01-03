import sys
sys.path.insert(0, r'c:\Users\sam94\workspace\cobol-parser')

from cobolparser import CobolParser
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

cobol_code = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 COUNTER PIC 9(2).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM VARYING COUNTER FROM 1 BY 1
               UNTIL COUNTER > 10
               CALL "INNER-PROG" USING COUNTER
           END-PERFORM.
           STOP RUN.
"""

# Add instrumentation to the parser
original_parse_statement = CobolParser.parse_statement
original_parse_call = CobolParser.parse_call_statement

def logged_parse_statement(self):
    result = original_parse_statement(self)
    if result:
        result_type = result.node_type if hasattr(result, 'node_type') else type(result).__name__
        print(f"  parse_statement() returned: {result_type}, nested_flag={self.parsing_nested_statement}")
    return result

def logged_parse_call(self):
    print(f"  parse_call_statement() called, nested_flag={self.parsing_nested_statement}")
    result = original_parse_call(self)
    if result:
        print(f"    -> Created CALL to {result.called_program}")
    return result

CobolParser.parse_statement = logged_parse_statement
CobolParser.parse_call_statement = logged_parse_call

parser = CobolParser()
print("Starting parse...")
result = parser.parse(cobol_code)

print(f"\nParse success: {result.success}")

# Check procedure division
proc_div = None
for div in result.ast.divisions:
    if div.division_name == 'PROCEDURE':
        proc_div = div
        break

if proc_div:
    print(f"\nPROCEDURE division sections: {[s.section_name for s in proc_div.sections]}")
    
    for section in proc_div.sections:
        print(f"\nSection '{section.section_name}':")
        print(f"  Children: {len(section.children)}")
        for i, child in enumerate(section.children):
            child_type = child.node_type if hasattr(child, 'node_type') else type(child).__name__
            print(f"    {i+1}. {child_type}")
            if hasattr(child, 'inline_statements'):
                inline = child.inline_statements
                print(f"       inline_statements: {len(inline) if inline else 0} items")
                if inline:
                    for j, stmt in enumerate(inline):
                        stmt_type = stmt.node_type if hasattr(stmt, 'node_type') else type(stmt).__name__
                        print(f"         {j+1}. {stmt_type}")
