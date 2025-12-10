      *****************************************************************
      * Figurative Constants Test Program
      * Tests: ALL, ZERO, SPACE, HIGH-VALUE, LOW-VALUE, QUOTE
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FIGCONST.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TEST-FIELDS.
           05  WS-ALPHA-FIELD      PIC X(20).
           05  WS-NUM-FIELD        PIC 9(5).
           05  WS-QUOTE-FIELD      PIC X(10).
           05  WS-COMPARE-FIELD    PIC X(5).
       
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'Testing Figurative Constants'
           
      *    Test ALL constant
           MOVE ALL 'X' TO WS-ALPHA-FIELD
           DISPLAY 'ALL X: ' WS-ALPHA-FIELD
           
           MOVE ALL '9' TO WS-NUM-FIELD
           DISPLAY 'ALL 9: ' WS-NUM-FIELD
           
      *    Test ZERO/ZEROS/ZEROES
           MOVE ZERO TO WS-NUM-FIELD
           DISPLAY 'ZERO: ' WS-NUM-FIELD
           
           MOVE ZEROS TO WS-NUM-FIELD
           DISPLAY 'ZEROS: ' WS-NUM-FIELD
           
           MOVE ZEROES TO WS-NUM-FIELD
           DISPLAY 'ZEROES: ' WS-NUM-FIELD
           
      *    Test SPACE/SPACES
           MOVE SPACE TO WS-ALPHA-FIELD
           DISPLAY 'SPACE: [' WS-ALPHA-FIELD ']'
           
           MOVE SPACES TO WS-ALPHA-FIELD
           DISPLAY 'SPACES: [' WS-ALPHA-FIELD ']'
           
      *    Test HIGH-VALUE/HIGH-VALUES
           MOVE HIGH-VALUE TO WS-ALPHA-FIELD
           DISPLAY 'HIGH-VALUE set'
           
           MOVE HIGH-VALUES TO WS-ALPHA-FIELD
           DISPLAY 'HIGH-VALUES set'
           
      *    Test LOW-VALUE/LOW-VALUES
           MOVE LOW-VALUE TO WS-ALPHA-FIELD
           DISPLAY 'LOW-VALUE set'
           
           MOVE LOW-VALUES TO WS-ALPHA-FIELD
           DISPLAY 'LOW-VALUES set'
           
      *    Test QUOTE/QUOTES
           MOVE QUOTE TO WS-QUOTE-FIELD
           DISPLAY 'QUOTE: ' WS-QUOTE-FIELD
           
           MOVE QUOTES TO WS-QUOTE-FIELD
           DISPLAY 'QUOTES: ' WS-QUOTE-FIELD
           
      *    Test in conditionals
           IF WS-ALPHA-FIELD = SPACES
               DISPLAY 'Field is spaces'
           END-IF
           
           IF WS-NUM-FIELD = ZERO
               DISPLAY 'Number is zero'
           END-IF
           
           STOP RUN.
