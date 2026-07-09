      *****************************************************************
      * Arithmetic Operations - All Variants
      * Tests: ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITHOPS.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NUM-1                PIC 9(5)V99 VALUE 100.50.
       01  WS-NUM-2                PIC 9(5)V99 VALUE 50.25.
       01  WS-NUM-3                PIC 9(5)V99 VALUE 25.00.
       01  WS-RESULT               PIC 9(7)V99.
       01  WS-QUOTIENT             PIC 9(5)V99.
       01  WS-REMAINDER            PIC 9(5)V99.
       
       01  WS-ROUNDED              PIC 9(5)V9.
       01  WS-SIZE-ERROR-FLAG      PIC X VALUE 'N'.
           88  SIZE-ERROR          VALUE 'Y'.
       
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM ADD-TESTS
           PERFORM SUBTRACT-TESTS
           PERFORM MULTIPLY-TESTS
           PERFORM DIVIDE-TESTS
           PERFORM COMPUTE-TESTS
           STOP RUN.
           
       ADD-TESTS.
      *    Simple ADD TO
           ADD WS-NUM-1 TO WS-RESULT
           DISPLAY 'Add to result: ' WS-RESULT
           
      *    ADD GIVING
           ADD WS-NUM-1 WS-NUM-2 GIVING WS-RESULT
           DISPLAY 'Add giving: ' WS-RESULT
           
      *    ADD multiple TO
           MOVE ZERO TO WS-RESULT
           ADD WS-NUM-1 WS-NUM-2 WS-NUM-3 TO WS-RESULT
           DISPLAY 'Add multiple: ' WS-RESULT
           
      *    ADD with ROUNDED
           ADD WS-NUM-1 TO WS-ROUNDED ROUNDED
           DISPLAY 'Add rounded: ' WS-ROUNDED
           
      *    ADD with ON SIZE ERROR
           ADD 99999.99 TO WS-RESULT
               ON SIZE ERROR
                   SET SIZE-ERROR TO TRUE
                   DISPLAY 'Size error in ADD'
               NOT ON SIZE ERROR
                   DISPLAY 'ADD successful'
           END-ADD
           
      *    ADD CORRESPONDING
           ADD CORRESPONDING WS-NUM-1 TO WS-NUM-2.
           
       SUBTRACT-TESTS.
      *    Simple SUBTRACT FROM
           MOVE 200 TO WS-RESULT
           SUBTRACT WS-NUM-1 FROM WS-RESULT
           DISPLAY 'Subtract from: ' WS-RESULT
           
      *    SUBTRACT GIVING
           SUBTRACT WS-NUM-2 FROM WS-NUM-1 GIVING WS-RESULT
           DISPLAY 'Subtract giving: ' WS-RESULT
           
      *    SUBTRACT multiple FROM
           MOVE 300 TO WS-RESULT
           SUBTRACT WS-NUM-1 WS-NUM-2 WS-NUM-3 FROM WS-RESULT
           DISPLAY 'Subtract multiple: ' WS-RESULT
           
      *    SUBTRACT with ROUNDED
           MOVE 100 TO WS-ROUNDED
           SUBTRACT 50.55 FROM WS-ROUNDED ROUNDED
           DISPLAY 'Subtract rounded: ' WS-ROUNDED
           
      *    SUBTRACT with ON SIZE ERROR
           MOVE 10 TO WS-RESULT
           SUBTRACT 20 FROM WS-RESULT
               ON SIZE ERROR
                   DISPLAY 'Size error in SUBTRACT'
               NOT ON SIZE ERROR
                   DISPLAY 'SUBTRACT successful'
           END-SUBTRACT.
           
       MULTIPLY-TESTS.
      *    Simple MULTIPLY BY
           MOVE 10 TO WS-RESULT
           MULTIPLY WS-NUM-1 BY WS-RESULT
           DISPLAY 'Multiply by: ' WS-RESULT
           
      *    MULTIPLY GIVING
           MULTIPLY WS-NUM-1 BY WS-NUM-2 GIVING WS-RESULT
           DISPLAY 'Multiply giving: ' WS-RESULT
           
      *    MULTIPLY with ROUNDED
           MULTIPLY 3.333 BY 2.5 GIVING WS-ROUNDED ROUNDED
           DISPLAY 'Multiply rounded: ' WS-ROUNDED
           
      *    MULTIPLY with ON SIZE ERROR
           MULTIPLY 99999 BY 99999 GIVING WS-RESULT
               ON SIZE ERROR
                   DISPLAY 'Size error in MULTIPLY'
               NOT ON SIZE ERROR
                   DISPLAY 'MULTIPLY successful'
           END-MULTIPLY.
           
       DIVIDE-TESTS.
      *    Simple DIVIDE INTO
           MOVE 100 TO WS-RESULT
           DIVIDE WS-NUM-1 INTO WS-RESULT
           DISPLAY 'Divide into: ' WS-RESULT
           
      *    DIVIDE BY GIVING
           DIVIDE WS-NUM-1 BY WS-NUM-2 GIVING WS-RESULT
           DISPLAY 'Divide by giving: ' WS-RESULT
           
      *    DIVIDE with REMAINDER
           DIVIDE WS-NUM-1 BY WS-NUM-3 
               GIVING WS-QUOTIENT
               REMAINDER WS-REMAINDER
           DISPLAY 'Quotient: ' WS-QUOTIENT
           DISPLAY 'Remainder: ' WS-REMAINDER
           
      *    DIVIDE with ROUNDED
           DIVIDE 10 BY 3 GIVING WS-ROUNDED ROUNDED
           DISPLAY 'Divide rounded: ' WS-ROUNDED
           
      *    DIVIDE with ON SIZE ERROR
           DIVIDE WS-NUM-1 BY ZERO GIVING WS-RESULT
               ON SIZE ERROR
                   DISPLAY 'Division by zero error'
               NOT ON SIZE ERROR
                   DISPLAY 'DIVIDE successful'
           END-DIVIDE
           
      *    DIVIDE INTO GIVING
           DIVIDE WS-NUM-2 INTO WS-NUM-1 GIVING WS-RESULT
           DISPLAY 'Divide into giving: ' WS-RESULT.
           
       COMPUTE-TESTS.
      *    Simple COMPUTE
           COMPUTE WS-RESULT = WS-NUM-1 + WS-NUM-2
           DISPLAY 'Compute add: ' WS-RESULT
           
      *    COMPUTE with all operators
           COMPUTE WS-RESULT = WS-NUM-1 + WS-NUM-2 - WS-NUM-3
           DISPLAY 'Compute mixed: ' WS-RESULT
           
           COMPUTE WS-RESULT = WS-NUM-1 * WS-NUM-2
           DISPLAY 'Compute multiply: ' WS-RESULT
           
           COMPUTE WS-RESULT = WS-NUM-1 / WS-NUM-2
           DISPLAY 'Compute divide: ' WS-RESULT
           
      *    COMPUTE with parentheses
           COMPUTE WS-RESULT = (WS-NUM-1 + WS-NUM-2) * WS-NUM-3
           DISPLAY 'Compute with parens: ' WS-RESULT
           
      *    COMPUTE with exponentiation
           COMPUTE WS-RESULT = WS-NUM-1 ** 2
           DISPLAY 'Compute power: ' WS-RESULT
           
      *    Complex COMPUTE expression
           COMPUTE WS-RESULT = 
               ((WS-NUM-1 + WS-NUM-2) * WS-NUM-3) / 
               (WS-NUM-1 - WS-NUM-2)
           DISPLAY 'Complex compute: ' WS-RESULT
           
      *    COMPUTE with ROUNDED
           COMPUTE WS-ROUNDED ROUNDED = WS-NUM-1 / 3
           DISPLAY 'Compute rounded: ' WS-ROUNDED
           
      *    COMPUTE with ON SIZE ERROR
           COMPUTE WS-RESULT = 99999.99 * 99999.99
               ON SIZE ERROR
                   DISPLAY 'Size error in COMPUTE'
               NOT ON SIZE ERROR
                   DISPLAY 'COMPUTE successful'
           END-COMPUTE
           
      *    COMPUTE with intrinsic functions
           COMPUTE WS-RESULT = FUNCTION MAX(WS-NUM-1,WS-NUM-2,WS-NUM-3)
           DISPLAY 'Max value: ' WS-RESULT

           COMPUTE WS-RESULT = FUNCTION MIN(WS-NUM-1,WS-NUM-2,WS-NUM-3)
           DISPLAY 'Min value: ' WS-RESULT

           COMPUTE WS-RESULT = FUNCTION SUM(WS-NUM-1,WS-NUM-2,WS-NUM-3)
           DISPLAY 'Sum: ' WS-RESULT
           
           COMPUTE WS-RESULT = FUNCTION SQRT(WS-NUM-1)
           DISPLAY 'Square root: ' WS-RESULT
           
           COMPUTE WS-RESULT = FUNCTION LOG(WS-NUM-1)
           DISPLAY 'Log: ' WS-RESULT
           
           COMPUTE WS-RESULT = FUNCTION EXP(WS-NUM-2)
           DISPLAY 'Exponent: ' WS-RESULT.
