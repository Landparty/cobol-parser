      *****************************************************************
      * Real-World COBOL Example: CALL RETURNING Variations
      * Demonstrates: All RETURNING clause patterns
      * Use Case: Function-style service calls with return values
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALL-RETURNING-VARIATIONS.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NUMERIC-RETURNS.
           05  WS-RETURN-INT       PIC 9(5).
           05  WS-RETURN-DECIMAL   PIC 9(7)V99 COMP-3.
           05  WS-RETURN-CODE      PIC 99.
           05  WS-RETURN-STATUS    PIC 9.
           
       01  WS-ALPHA-RETURNS.
           05  WS-RETURN-STRING    PIC X(50).
           05  WS-RETURN-MESSAGE   PIC X(100).
           05  WS-RETURN-FLAG      PIC X.
           
       01  WS-INPUT-DATA.
           05  WS-INPUT-NUM1       PIC 9(5).
           05  WS-INPUT-NUM2       PIC 9(5).
           05  WS-INPUT-STRING     PIC X(30).
           
       PROCEDURE DIVISION.
       MAIN-RETURNING-DEMO.
           DISPLAY 'RETURNING Clause Demonstration'.
           PERFORM SIMPLE-RETURNING.
           PERFORM RETURNING-WITH-USING.
           PERFORM RETURNING-WITH-EXCEPTIONS.
           PERFORM RETURNING-VARIATIONS.
           STOP RUN.
           
       SIMPLE-RETURNING.
      *    CALL with RETURNING numeric variable
           CALL 'GET-STATUS-CODE'
               RETURNING WS-RETURN-CODE.
           
      *    CALL with RETURNING integer
           CALL 'GET-COUNT'
               RETURNING WS-RETURN-INT.
           
      *    CALL with RETURNING decimal
           CALL 'CALCULATE-AMOUNT'
               RETURNING WS-RETURN-DECIMAL.
           
      *    CALL with RETURNING alphanumeric variable
           CALL 'GET-MESSAGE'
               RETURNING WS-RETURN-STRING.
           
      *    CALL with RETURNING flag
           CALL 'CHECK-VALIDITY'
               RETURNING WS-RETURN-FLAG.
           
       RETURNING-WITH-USING.
      *    CALL with USING and RETURNING
           CALL 'ADD-NUMBERS' USING WS-INPUT-NUM1
                                    WS-INPUT-NUM2
               RETURNING WS-RETURN-INT.
           
      *    CALL with multiple USING and RETURNING
           CALL 'COMPLEX-CALCULATION' USING WS-INPUT-NUM1
                                            WS-INPUT-NUM2
                                            WS-INPUT-STRING
               RETURNING WS-RETURN-DECIMAL.
           
      *    CALL with BY VALUE and RETURNING
           CALL 'CALCULATE-TAX' USING BY VALUE WS-INPUT-NUM1
               RETURNING WS-RETURN-DECIMAL.
           
      *    CALL with BY REFERENCE and RETURNING
           CALL 'PROCESS-DATA' USING BY REFERENCE WS-INPUT-STRING
               RETURNING WS-RETURN-CODE.
           
      *    CALL with mixed modes and RETURNING
           CALL 'MIXED-PROCESSING' USING BY VALUE WS-INPUT-NUM1
                                         BY REFERENCE WS-INPUT-STRING
               RETURNING WS-RETURN-STATUS.
           
      *    CALL with RETURNING on separate line
           CALL 'FORMATTED-CALL'
                USING WS-INPUT-NUM1
                      WS-INPUT-NUM2
                RETURNING WS-RETURN-INT.
           
       RETURNING-WITH-EXCEPTIONS.
      *    CALL with RETURNING and ON EXCEPTION
           CALL 'RISKY-CALCULATION' USING WS-INPUT-NUM1
               RETURNING WS-RETURN-CODE
               ON EXCEPTION
                   MOVE 99 TO WS-RETURN-CODE
               END-CALL.
           
      *    CALL with RETURNING and NOT ON EXCEPTION
           CALL 'SAFE-CALCULATION' USING WS-INPUT-NUM1
               RETURNING WS-RETURN-CODE
               NOT ON EXCEPTION
                   DISPLAY 'Calculation succeeded: ' WS-RETURN-CODE
               END-CALL.
           
      *    CALL with RETURNING and both exception handlers
           CALL 'DUAL-HANDLER-CALC' USING WS-INPUT-NUM1
                                          WS-INPUT-NUM2
               RETURNING WS-RETURN-CODE
               ON EXCEPTION
                   MOVE 99 TO WS-RETURN-CODE
                   DISPLAY 'Calculation failed'
               NOT ON EXCEPTION
                   DISPLAY 'Calculation result: ' WS-RETURN-CODE
               END-CALL.
           
      *    CALL with RETURNING and END-CALL
           CALL 'EXPLICIT-TERMINATOR-CALC' USING WS-INPUT-NUM1
               RETURNING WS-RETURN-INT
               ON EXCEPTION
                   MOVE 0 TO WS-RETURN-INT
               END-CALL.
           
       RETURNING-VARIATIONS.
      *    Function-style CALL with RETURNING
           CALL 'FUNCTION-STYLE'
               RETURNING WS-RETURN-INT.
           
      *    CALL with RETURNING string result
           CALL 'GET-DESCRIPTION' USING WS-INPUT-NUM1
               RETURNING WS-RETURN-MESSAGE.
           
      *    CALL with RETURNING in IF block
           IF WS-INPUT-NUM1 > 100
               CALL 'HIGH-VALUE-CALC' USING WS-INPUT-NUM1
                   RETURNING WS-RETURN-DECIMAL
           END-IF.
           
      *    CALL with RETURNING in PERFORM
           PERFORM VARYING WS-INPUT-NUM1 FROM 1 BY 1
               UNTIL WS-INPUT-NUM1 > 5
               CALL 'ITERATIVE-CALC' USING WS-INPUT-NUM1
                   RETURNING WS-RETURN-INT
           END-PERFORM.
           
      *    CALL with RETURNING in EVALUATE
           EVALUATE WS-RETURN-CODE
               WHEN 0
                   CALL 'SUCCESS-PROCESSOR'
                       RETURNING WS-RETURN-STATUS
               WHEN OTHER
                   CALL 'ERROR-PROCESSOR'
                       RETURNING WS-RETURN-STATUS
           END-EVALUATE.
           
      *    Nested CALL with RETURNING
           CALL 'OUTER-FUNCTION' USING WS-INPUT-NUM1
               RETURNING WS-RETURN-INT
               ON EXCEPTION
                   CALL 'FALLBACK-FUNCTION'
                       RETURNING WS-RETURN-INT
               END-CALL.
           
       END PROGRAM CALL-RETURNING-VARIATIONS.
