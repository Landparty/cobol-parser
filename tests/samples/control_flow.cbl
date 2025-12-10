      *****************************************************************
      * Control Flow Statements - All Variants
      * Tests: IF, EVALUATE, PERFORM, GO TO, SEARCH
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CTRLFLOW.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TEST-VALUE           PIC 9(3) VALUE 50.
       01  WS-GRADE                PIC X VALUE 'B'.
       01  WS-COUNTER              PIC 99 VALUE 1.
       01  WS-MAX                  PIC 99 VALUE 10.
       
       01  WS-TABLE.
           05  WS-ENTRY            PIC X(10) OCCURS 20 TIMES
               INDEXED BY IDX-1.
               
       01  WS-SEARCH-KEY           PIC X(10).
       
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM IF-TESTS
           PERFORM EVALUATE-TESTS
           PERFORM PERFORM-TESTS
           PERFORM GOTO-TESTS
           PERFORM SEARCH-TESTS
           STOP RUN.
           
       IF-TESTS.
      *    Simple IF
           IF WS-TEST-VALUE > 100
               DISPLAY 'Greater than 100'
           END-IF
           
      *    IF with ELSE
           IF WS-TEST-VALUE = 50
               DISPLAY 'Equal to 50'
           ELSE
               DISPLAY 'Not equal to 50'
           END-IF
           
      *    Nested IF
           IF WS-TEST-VALUE > 0
               IF WS-TEST-VALUE < 100
                   DISPLAY 'Between 0 and 100'
               ELSE
                   DISPLAY 'Greater than or equal to 100'
               END-IF
           ELSE
               DISPLAY 'Less than or equal to 0'
           END-IF
           
      *    IF with compound conditions
           IF WS-TEST-VALUE > 10 AND WS-TEST-VALUE < 90
               DISPLAY 'Between 10 and 90'
           END-IF
           
           IF WS-TEST-VALUE = 50 OR WS-TEST-VALUE = 100
               DISPLAY 'Equals 50 or 100'
           END-IF
           
           IF NOT WS-TEST-VALUE = 0
               DISPLAY 'Not zero'
           END-IF
           
      *    IF with multiple conditions
           IF WS-TEST-VALUE > 10
              AND (WS-TEST-VALUE < 100 OR WS-TEST-VALUE = 200)
               DISPLAY 'Complex condition true'
           END-IF
           
      *    IF THEN (explicit THEN)
           IF WS-TEST-VALUE > 25 THEN
               DISPLAY 'Greater than 25'
           ELSE
               DISPLAY 'Less than or equal to 25'
           END-IF
           
      *    Multiple statements in IF
           IF WS-TEST-VALUE = 50
               DISPLAY 'First statement'
               DISPLAY 'Second statement'
               COMPUTE WS-TEST-VALUE = WS-TEST-VALUE + 1
               DISPLAY 'Third statement'
           END-IF.
           
       EVALUATE-TESTS.
      *    Simple EVALUATE
           EVALUATE WS-GRADE
               WHEN 'A'
                   DISPLAY 'Excellent'
               WHEN 'B'
                   DISPLAY 'Good'
               WHEN 'C'
                   DISPLAY 'Average'
               WHEN OTHER
                   DISPLAY 'Unknown grade'
           END-EVALUATE
           
      *    EVALUATE with ranges
           EVALUATE WS-TEST-VALUE
               WHEN 0 THRU 30
                   DISPLAY 'Low range'
               WHEN 31 THRU 70
                   DISPLAY 'Medium range'
               WHEN 71 THRU 100
                   DISPLAY 'High range'
               WHEN OTHER
                   DISPLAY 'Out of range'
           END-EVALUATE
           
      *    EVALUATE TRUE (case statement)
           EVALUATE TRUE
               WHEN WS-TEST-VALUE < 25
                   DISPLAY 'Less than 25'
               WHEN WS-TEST-VALUE >= 25 AND WS-TEST-VALUE < 75
                   DISPLAY 'Between 25 and 75'
               WHEN WS-TEST-VALUE >= 75
                   DISPLAY 'Greater than or equal to 75'
           END-EVALUATE
           
      *    EVALUATE with multiple subjects
           EVALUATE WS-GRADE ALSO WS-TEST-VALUE
               WHEN 'A' ALSO 90 THRU 100
                   DISPLAY 'A with high score'
               WHEN 'B' ALSO 80 THRU 89
                   DISPLAY 'B with good score'
               WHEN ANY ALSO 0 THRU 59
                   DISPLAY 'Failing score'
               WHEN OTHER
                   DISPLAY 'Other combination'
           END-EVALUATE
           
      *    EVALUATE with ALSO and conditions
           EVALUATE WS-TEST-VALUE ALSO WS-COUNTER
               WHEN 50 ALSO 1
                   DISPLAY 'Exact match'
               WHEN ANY ALSO 1 THRU 5
                   DISPLAY 'Counter in range'
               WHEN OTHER
                   DISPLAY 'No match'
           END-EVALUATE.
           
       PERFORM-TESTS.
      *    Simple PERFORM
           PERFORM SIMPLE-PARA
           
      *    PERFORM n TIMES
           PERFORM SIMPLE-PARA 5 TIMES
           
      *    PERFORM UNTIL
           PERFORM UNTIL WS-COUNTER > WS-MAX
               DISPLAY 'Counter: ' WS-COUNTER
               ADD 1 TO WS-COUNTER
           END-PERFORM
           
      *    PERFORM VARYING
           PERFORM VARYING WS-COUNTER FROM 1 BY 1
               UNTIL WS-COUNTER > 10
               DISPLAY 'Varying counter: ' WS-COUNTER
           END-PERFORM
           
      *    PERFORM with TEST AFTER
           MOVE 1 TO WS-COUNTER
           PERFORM WITH TEST AFTER
               UNTIL WS-COUNTER > 5
               DISPLAY 'Test after: ' WS-COUNTER
               ADD 1 TO WS-COUNTER
           END-PERFORM
           
      *    Nested PERFORM VARYING
           PERFORM VARYING WS-COUNTER FROM 1 BY 1
               UNTIL WS-COUNTER > 3
               PERFORM VARYING WS-MAX FROM 1 BY 1
                   UNTIL WS-MAX > 3
                   DISPLAY 'Nested: ' WS-COUNTER ' x ' WS-MAX
               END-PERFORM
           END-PERFORM
           
      *    PERFORM THRU
           PERFORM PARA-START THRU PARA-END.
           
       SIMPLE-PARA.
           DISPLAY 'Simple paragraph executed'.
           
       PARA-START.
           DISPLAY 'Start paragraph'.
           
       PARA-MIDDLE.
           DISPLAY 'Middle paragraph'.
           
       PARA-END.
           DISPLAY 'End paragraph'.
           
       GOTO-TESTS.
      *    Simple GO TO
           GO TO GOTO-TARGET.
           
       GOTO-SKIP.
           DISPLAY 'This is skipped'.
           GO TO GOTO-END.
           
       GOTO-TARGET.
           DISPLAY 'Reached target'.
           
      *    GO TO DEPENDING ON
           MOVE 2 TO WS-COUNTER
           GO TO GOTO-OPTION-1
                 GOTO-OPTION-2
                 GOTO-OPTION-3
               DEPENDING ON WS-COUNTER.
           
       GOTO-OPTION-1.
           DISPLAY 'Option 1'
           GO TO GOTO-END.
           
       GOTO-OPTION-2.
           DISPLAY 'Option 2'
           GO TO GOTO-END.
           
       GOTO-OPTION-3.
           DISPLAY 'Option 3'.
           
       GOTO-END.
           DISPLAY 'GO TO tests complete'.
           
       SEARCH-TESTS.
      *    Load table
           PERFORM VARYING WS-COUNTER FROM 1 BY 1
               UNTIL WS-COUNTER > 20
               MOVE 'ENTRY' TO WS-ENTRY(WS-COUNTER)
           END-PERFORM
           
      *    Linear SEARCH
           MOVE 'ENTRY' TO WS-SEARCH-KEY
           SET IDX-1 TO 1
           SEARCH WS-ENTRY
               AT END DISPLAY 'Not found (linear)'
               WHEN WS-ENTRY(IDX-1) = WS-SEARCH-KEY
                   DISPLAY 'Found at index: ' IDX-1
           END-SEARCH
           
      *    Multiple WHEN conditions
           SET IDX-1 TO 1
           SEARCH WS-ENTRY
               WHEN WS-ENTRY(IDX-1) = 'TARGET1'
                   DISPLAY 'Found TARGET1'
               WHEN WS-ENTRY(IDX-1) = 'TARGET2'
                   DISPLAY 'Found TARGET2'
               WHEN WS-ENTRY(IDX-1) = 'ENTRY'
                   DISPLAY 'Found ENTRY'
           END-SEARCH.
