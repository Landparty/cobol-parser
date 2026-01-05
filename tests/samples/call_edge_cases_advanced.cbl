      *****************************************************************
      * Real-World COBOL Example: CALL Edge Cases & Special Patterns
      * Demonstrates: Recursive calls, nested calls, unusual parameter
      * Use Case: Complex transaction processing with special scenarios
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ADVANCED-CALL-PATTERNS.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RECURSION-CONTROL.
           05  WS-DEPTH-COUNTER    PIC 99 VALUE 0.
           05  WS-MAX-DEPTH        PIC 99 VALUE 10.
           05  WS-CURRENT-LEVEL    PIC 99.
           
       01  WS-TRANSACTION-DATA.
           05  WS-TRANS-ID         PIC X(12).
           05  WS-AMOUNT           PIC 9(10)V99 COMP-3.
           05  WS-RESULT           PIC 9(10)V99 COMP-3.
           05  WS-CALC-RESULT      PIC 9(10)V99 COMP-3.
           
       01  WS-NESTED-CALL-DATA.
           05  WS-PARENT-PROG      PIC X(20).
           05  WS-CHILD-PROG       PIC X(20).
           05  WS-GRANDCHILD-PROG  PIC X(20).
           05  WS-CALL-CHAIN       PIC X(60).
           
       01  WS-PARAMETER-VARIATIONS.
           05  WS-LITERAL-STRING   PIC X(20) VALUE 'LITERAL-VALUE'.
           05  WS-VARIABLE-STRING  PIC X(20).
           05  WS-NUMERIC-VALUE    PIC 9(6) COMP-3 VALUE 12345.
           05  WS-POINTER-VALUE    PIC X(10).
           
       01  WS-EXCEPTION-DATA.
           05  WS-EXCEPTION-FLAG   PIC X VALUE 'N'.
           05  WS-RETRY-COUNT      PIC 9.
           05  WS-RECOVERY-CODE    PIC 999.
           
       01  WS-SERVICE-REGISTRY.
           05  WS-RECURSIVE-CALC   PIC X(20) VALUE 'FACTORIAL'.
           05  WS-TREE-TRAVERSAL   PIC X(20) VALUE 'TRAVERSE-TREE'.
           05  WS-CHAIN-PROCESSOR  PIC X(20) VALUE 'PROCESS-CHAIN'.
           05  WS-FALLBACK-SVC     PIC X(20) VALUE 'FALLBACK-HANDLER'.
           
       PROCEDURE DIVISION.
       MAIN-ADVANCED-CALLS.
           DISPLAY 'Advanced CALL Patterns Demonstration'
           PERFORM EXAMPLE-SIMPLE-CALL
           PERFORM EXAMPLE-DYNAMIC-CALL
           PERFORM EXAMPLE-CONDITIONAL-CALL
           PERFORM EXAMPLE-CALL-IN-LOOP
           PERFORM EXAMPLE-CALL-WITH-EXCEPTION
           PERFORM EXAMPLE-CALL-CHAIN
           PERFORM EXAMPLE-CALL-WITH-RETURNING
           DISPLAY 'All Examples Complete'
           STOP RUN.
           
       EXAMPLE-SIMPLE-CALL.
           DISPLAY '--- Example 1: Simple CALL ---'
           MOVE 'SIMPLE-CALC' TO WS-CHILD-PROG
           MOVE 1000.00 TO WS-AMOUNT
           
           CALL 'SIMPLE-CALC' USING WS-AMOUNT
                                    BY REFERENCE WS-RESULT.
           
       EXAMPLE-DYNAMIC-CALL.
           DISPLAY '--- Example 2: Dynamic Program Name ---'
           MOVE 'DYNAMIC-PROCESSOR' TO WS-CHILD-PROG
           MOVE 2500.50 TO WS-AMOUNT
           
      *    CALL with variable program name
           CALL WS-CHILD-PROG USING BY VALUE WS-AMOUNT
                                     BY REFERENCE WS-RESULT
               ON EXCEPTION
                   DISPLAY 'Dynamic call failed'
               NOT ON EXCEPTION
                   DISPLAY 'Dynamic call succeeded'.
           
       EXAMPLE-CONDITIONAL-CALL.
           DISPLAY '--- Example 3: Conditional CALL ---'
           MOVE 'CONDITIONAL-PROCESSOR' TO WS-CHILD-PROG
           MOVE 100.00 TO WS-AMOUNT
           
      *    CALL only if amount exceeds threshold
           IF WS-AMOUNT > 50.00
               CALL WS-CHILD-PROG USING WS-AMOUNT
                                        BY REFERENCE WS-RESULT
                   RETURNING WS-RECOVERY-CODE
           ELSE
               DISPLAY 'Amount below threshold, skipping call'
           END-IF.
           
       EXAMPLE-CALL-IN-LOOP.
           DISPLAY '--- Example 4: CALL Inside Loop ---'
           
      *    CALL same service multiple times with different parameters
           PERFORM VARYING WS-CURRENT-LEVEL FROM 1 BY 1
               UNTIL WS-CURRENT-LEVEL > 5
               
               MOVE WS-CURRENT-LEVEL TO WS-NUMERIC-VALUE
               MULTIPLY WS-NUMERIC-LEVEL BY 100 GIVING WS-AMOUNT
               
               CALL 'BATCH-PROCESSOR' USING BY REFERENCE WS-AMOUNT
                                              WS-CURRENT-LEVEL
                                         BY REFERENCE WS-RESULT
                   RETURNING WS-CALC-RESULT
                   ON EXCEPTION
                       ADD 1 TO WS-RETRY-COUNT
           END-PERFORM.
           
       EXAMPLE-CALL-WITH-EXCEPTION.
           DISPLAY '--- Example 5: CALL with Exception Handling ---'
           MOVE 'RISKY-OPERATION' TO WS-CHILD-PROG
           MOVE 5000.00 TO WS-AMOUNT
           
      *    CALL with detailed exception handling
           CALL WS-CHILD-PROG USING WS-AMOUNT
                                    BY REFERENCE WS-RESULT
               ON EXCEPTION
                   MOVE 'Y' TO WS-EXCEPTION-FLAG
                   MOVE 001 TO WS-RECOVERY-CODE
                   CALL WS-FALLBACK-SVC USING BY REFERENCE WS-AMOUNT
                                                WS-RESULT
                   DISPLAY 'Called fallback handler'
               NOT ON EXCEPTION
                   MOVE 'N' TO WS-EXCEPTION-FLAG.
           
       EXAMPLE-CALL-CHAIN.
           DISPLAY '--- Example 6: Call Chain (Nested Calls) ---'
           MOVE 'LEVEL-1-PROCESSOR' TO WS-PARENT-PROG
           MOVE 'LEVEL-2-PROCESSOR' TO WS-CHILD-PROG
           MOVE 'LEVEL-3-PROCESSOR' TO WS-GRANDCHILD-PROG
           
      *    Call level 1, which internally calls level 2, which calls level 3
           CALL WS-PARENT-PROG USING BY REFERENCE WS-AMOUNT
                                         WS-RESULT
           
      *    Direct call to level 2 with different context
           CALL WS-CHILD-PROG USING BY VALUE WS-AMOUNT
                                     BY REFERENCE WS-RESULT
           
      *    Direct call to level 3
           CALL WS-GRANDCHILD-PROG USING WS-AMOUNT
                                         BY REFERENCE WS-RESULT.
           
       EXAMPLE-CALL-WITH-RETURNING.
           DISPLAY '--- Example 7: CALL with RETURNING ---'
           
      *    CALL with RETURNING integer
           CALL 'GET-STATUS' USING WS-TRANS-ID
               RETURNING WS-RECOVERY-CODE
           
      *    CALL with RETURNING numeric
           CALL 'CALCULATE-VALUE' USING 100.00
               RETURNING WS-CALC-RESULT
           
      *    CALL with RETURNING string
           CALL 'GET-MESSAGE' USING WS-TRANS-ID
               RETURNING WS-VARIABLE-STRING.
           
       END PROGRAM ADVANCED-CALL-PATTERNS.
       
      *****************************************************************
      * Subprogram Examples - Called from above
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SIMPLE-CALC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       LINKAGE SECTION.
       01  LS-INPUT-VALUE          PIC 9(10)V99 COMP-3.
       01  LS-OUTPUT-VALUE         PIC 9(10)V99 COMP-3.
       PROCEDURE DIVISION USING LS-INPUT-VALUE LS-OUTPUT-VALUE.
           MULTIPLY LS-INPUT-VALUE BY 1.1 GIVING LS-OUTPUT-VALUE.
           STOP RUN.
       END PROGRAM SIMPLE-CALC.
       
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYNAMIC-PROCESSOR.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LS-AMOUNT               PIC 9(10)V99 COMP-3.
       01  LS-RESULT               PIC 9(10)V99 COMP-3.
       PROCEDURE DIVISION USING LS-AMOUNT LS-RESULT.
           COMPUTE LS-RESULT = LS-AMOUNT * 2.
           STOP RUN.
       END PROGRAM DYNAMIC-PROCESSOR.
