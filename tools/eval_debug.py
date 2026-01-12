from cobolparser import CobolParser

source = """
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-GRADE PIC 9.
PROCEDURE DIVISION.
    EVALUATE WS-GRADE
        WHEN 1
            DISPLAY 'ONE'
        WHEN 2 THRU 3
            DISPLAY 'LOW'
        WHEN OTHER
            DISPLAY 'OTHER'
    END-EVALUATE.
"""
parser = CobolParser()
res = parser.parse(source)
print("ast:", res.ast)
print("errors:")
for e in res.errors:
    print(e)
