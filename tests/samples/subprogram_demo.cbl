      *****************************************************************
      * IBM Enterprise COBOL Sample - Subprogram Demonstration
      * Demonstrates: CALL statement, USING clause, parameter passing
      * Features: Modular programming, BY REFERENCE/VALUE
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAIN-PROGRAM.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CALCULATION-INPUTS.
           05  WS-INPUT-NUM1       PIC 9(5)V99 COMP-3 VALUE 125.75.
           05  WS-INPUT-NUM2       PIC 9(5)V99 COMP-3 VALUE 87.25.
           05  WS-OPERATION        PIC X VALUE 'A'.
               88  ADD-OPERATION   VALUE 'A'.
               88  SUB-OPERATION   VALUE 'S'. 
               88  MULT-OPERATION  VALUE 'M'.
               88  DIV-OPERATION   VALUE 'D'.
               
       01  WS-CALCULATION-OUTPUTS.
           05  WS-RESULT           PIC 9(8)V99 COMP-3.
           05  WS-RETURN-CODE      PIC 99.
               88  CALC-SUCCESS    VALUE 00.
               88  CALC-ERROR      VALUE 01 THRU 99.
               
       01  WS-STRING-INPUTS.
           05  WS-INPUT-STRING     PIC X(50) VALUE 'Hello COBOL World'.
           05  WS-STRING-LENGTH    PIC 99 COMP.
           
       01  WS-STRING-OUTPUTS.  
           05  WS-OUTPUT-STRING    PIC X(100).
           05  WS-WORD-COUNT       PIC 99.
           
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'Subprogram Demonstration Starting'
           PERFORM TEST-CALCULATOR-SUBPROGRAM
           PERFORM TEST-STRING-PROCESSOR-SUBPROGRAM
           DISPLAY 'Subprogram Demonstration Complete'
           STOP RUN.
           
       TEST-CALCULATOR-SUBPROGRAM.
           DISPLAY 'Testing Calculator Subprogram:'
           
      * Test Addition
           MOVE 'A' TO WS-OPERATION
           CALL 'CALCULATOR' USING BY REFERENCE WS-INPUT-NUM1
                                               WS-INPUT-NUM2  
                                               WS-OPERATION
                                               WS-RESULT
                                               WS-RETURN-CODE
           IF CALC-SUCCESS
               DISPLAY 'Addition Result: ' WS-RESULT
           ELSE
               DISPLAY 'Addition Error: ' WS-RETURN-CODE
           END-IF
           
      * Test Multiplication
           MOVE 'M' TO WS-OPERATION
           CALL 'CALCULATOR' USING WS-INPUT-NUM1
                                   WS-INPUT-NUM2
                                   WS-OPERATION  
                                   WS-RESULT
                                   WS-RETURN-CODE
           IF CALC-SUCCESS
               DISPLAY 'Multiplication Result: ' WS-RESULT
           ELSE  
               DISPLAY 'Multiplication Error: ' WS-RETURN-CODE
           END-IF
           
      * Test Division by zero (error condition)
           MOVE ZERO TO WS-INPUT-NUM2  
           MOVE 'D' TO WS-OPERATION
           CALL 'CALCULATOR' USING WS-INPUT-NUM1
                                   WS-INPUT-NUM2
                                   WS-OPERATION
                                   WS-RESULT
                                   WS-RETURN-CODE
           IF CALC-ERROR
               DISPLAY 'Expected Division Error Caught: ' WS-RETURN-CODE
           END-IF.
           
       TEST-STRING-PROCESSOR-SUBPROGRAM.
           DISPLAY 'Testing String Processor Subprogram:'
           
           MOVE LENGTH OF WS-INPUT-STRING TO WS-STRING-LENGTH
           
           CALL 'STRINGPROC' USING BY REFERENCE WS-INPUT-STRING
                                  BY VALUE WS-STRING-LENGTH
                                  BY REFERENCE WS-OUTPUT-STRING
                                                WS-WORD-COUNT
                                                
           DISPLAY 'Input String: ' WS-INPUT-STRING
           DISPLAY 'Processed String: ' WS-OUTPUT-STRING  
           DISPLAY 'Word Count: ' WS-WORD-COUNT.
           
       END PROGRAM MAIN-PROGRAM.
       
      *****************************************************************
      * Calculator Subprogram
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALCULATOR.
       
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-NUM1                 PIC 9(5)V99 COMP-3.
       01  LK-NUM2                 PIC 9(5)V99 COMP-3.
       01  LK-OPERATION            PIC X.
           88  LK-ADD              VALUE 'A'.
           88  LK-SUBTRACT         VALUE 'S'.  
           88  LK-MULTIPLY         VALUE 'M'.
           88  LK-DIVIDE           VALUE 'D'.
       01  LK-RESULT               PIC 9(8)V99 COMP-3.
       01  LK-RETURN-CODE          PIC 99.
       
       PROCEDURE DIVISION USING LK-NUM1 LK-NUM2 LK-OPERATION 
                               LK-RESULT LK-RETURN-CODE.
       CALC-MAIN.
           INITIALIZE LK-RESULT LK-RETURN-CODE
           
           EVALUATE TRUE
               WHEN LK-ADD
                   COMPUTE LK-RESULT = LK-NUM1 + LK-NUM2
               WHEN LK-SUBTRACT  
                   COMPUTE LK-RESULT = LK-NUM1 - LK-NUM2
               WHEN LK-MULTIPLY
                   COMPUTE LK-RESULT = LK-NUM1 * LK-NUM2
               WHEN LK-DIVIDE
                   IF LK-NUM2 = ZERO
                       MOVE 10 TO LK-RETURN-CODE
                   ELSE
                       COMPUTE LK-RESULT = LK-NUM1 / LK-NUM2
                   END-IF
               WHEN OTHER
                   MOVE 20 TO LK-RETURN-CODE
           END-EVALUATE
           
           EXIT PROGRAM.
           
       END PROGRAM CALCULATOR.
       
      *****************************************************************
      * String Processor Subprogram  
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STRINGPROC.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.  
       01  WS-WORK-AREAS.
           05  WS-CHAR-POS         PIC 99 COMP.
           05  WS-CURRENT-CHAR     PIC X.
           05  WS-IN-WORD          PIC X.
               88  IN-WORD         VALUE 'Y'.
           05  WS-OUTPUT-POS       PIC 99 COMP VALUE 1.
           
       LINKAGE SECTION.
       01  LK-INPUT-STRING         PIC X(50).
       01  LK-STRING-LENGTH        PIC 99 COMP.
       01  LK-OUTPUT-STRING        PIC X(100).  
       01  LK-WORD-COUNT           PIC 99.
       
       PROCEDURE DIVISION USING LK-INPUT-STRING LK-STRING-LENGTH
                               LK-OUTPUT-STRING LK-WORD-COUNT.
       STRING-PROC-MAIN.
           INITIALIZE LK-OUTPUT-STRING LK-WORD-COUNT
           MOVE 'N' TO WS-IN-WORD
           MOVE 1 TO WS-OUTPUT-POS
           
           PERFORM VARYING WS-CHAR-POS FROM 1 BY 1  
               UNTIL WS-CHAR-POS > LK-STRING-LENGTH
               
               MOVE LK-INPUT-STRING(WS-CHAR-POS:1) TO WS-CURRENT-CHAR
               
               IF WS-CURRENT-CHAR = SPACE
                   IF IN-WORD
                       MOVE 'N' TO WS-IN-WORD
                       MOVE ' | ' TO 
                           LK-OUTPUT-STRING(WS-OUTPUT-POS:3)
                       ADD 3 TO WS-OUTPUT-POS
                   END-IF
               ELSE
                   IF NOT IN-WORD  
                       MOVE 'Y' TO WS-IN-WORD
                       ADD 1 TO LK-WORD-COUNT
                   END-IF
                   MOVE WS-CURRENT-CHAR TO
                       LK-OUTPUT-STRING(WS-OUTPUT-POS:1)
                   ADD 1 TO WS-OUTPUT-POS
               END-IF
           END-PERFORM
           
           EXIT PROGRAM.
           
       END PROGRAM STRINGPROC.