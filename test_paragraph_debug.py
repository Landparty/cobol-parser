from cobolparser.parser import CobolParser

source = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "MAIN".
       SUB-PARA.
           DISPLAY "SUB".
"""

parser = CobolParser()
result = parser.parse(source)

if result.success:
    proc_div = result.ast.get_division("PROCEDURE")
    print(f"Paragraphs: {len(proc_div.paragraphs)}")
    print(f"Sections: {len(proc_div.sections)}")
    
    for section in proc_div.sections:
        print(f"Section: {section.section_name}, division={section.division_name}")
else:
    print("Parse failed")
