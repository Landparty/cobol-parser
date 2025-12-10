      *****************************************************************
      * String Manipulation Operations
      * Tests: STRING, UNSTRING, INSPECT, MOVE CORRESPONDING
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STRMANIP.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-STRING-FIELDS.
           05  WS-FIRST-NAME       PIC X(15) VALUE 'John'.
           05  WS-LAST-NAME        PIC X(20) VALUE 'Doe'.
           05  WS-FULL-NAME        PIC X(40).
           05  WS-DELIMITER        PIC X VALUE ' '.
           05  WS-POINTER          PIC 99.
           
       01  WS-INPUT-STRING         PIC X(50) 
           VALUE 'Field1,Field2,Field3,Field4'.
       01  WS-OUTPUT-FIELDS.
           05  WS-FIELD-1          PIC X(10).
           05  WS-FIELD-2          PIC X(10).
           05  WS-FIELD-3          PIC X(10).
           05  WS-FIELD-4          PIC X(10).
           05  WS-FIELD-COUNT      PIC 99.
           
       01  WS-INSPECT-FIELD        PIC X(30) 
           VALUE 'HELLO WORLD TEST'.
       01  WS-TALLY               PIC 999.
       
       01  WS-SOURCE-REC.
           05  WS-SRC-ID           PIC 9(5).
           05  WS-SRC-NAME         PIC X(20).
           05  WS-SRC-AMOUNT       PIC 9(7)V99.
           05  FILLER              PIC X(10).
           
       01  WS-TARGET-REC.
           05  WS-TGT-ID           PIC 9(5).
           05  WS-TGT-NAME         PIC X(20).
           05  WS-TGT-AMOUNT       PIC 9(7)V99.
           05  FILLER              PIC X(15).
           
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM STRING-TESTS
           PERFORM UNSTRING-TESTS
           PERFORM INSPECT-TESTS
           PERFORM CORRESPONDING-TESTS
           STOP RUN.
           
       STRING-TESTS.
      *    Simple STRING
           STRING WS-FIRST-NAME DELIMITED BY SIZE
                  WS-DELIMITER DELIMITED BY SIZE
                  WS-LAST-NAME DELIMITED BY SIZE
               INTO WS-FULL-NAME
           END-STRING
           DISPLAY 'Full name: ' WS-FULL-NAME
           
      *    STRING with POINTER
           MOVE 1 TO WS-POINTER
           STRING WS-FIRST-NAME DELIMITED BY SPACE
                  ' ' DELIMITED BY SIZE
                  WS-LAST-NAME DELIMITED BY SPACE
               INTO WS-FULL-NAME
               WITH POINTER WS-POINTER
           END-STRING
           DISPLAY 'String with pointer: ' WS-FULL-NAME
           DISPLAY 'Final pointer: ' WS-POINTER
           
      *    STRING with ON OVERFLOW
           STRING 'Very long text that might overflow'
                  DELIMITED BY SIZE
               INTO WS-FULL-NAME
               ON OVERFLOW
                   DISPLAY 'String overflow occurred'
               NOT ON OVERFLOW
                   DISPLAY 'String successful'
           END-STRING
           
      *    Multiple sources
           STRING 'Mr. ' DELIMITED BY SIZE
                  WS-FIRST-NAME DELIMITED BY SPACE
                  ' ' DELIMITED BY SIZE
                  WS-LAST-NAME DELIMITED BY SPACE
               INTO WS-FULL-NAME
           END-STRING
           DISPLAY 'Formatted name: ' WS-FULL-NAME.
           
       UNSTRING-TESTS.
      *    Simple UNSTRING with DELIMITED BY
           UNSTRING WS-INPUT-STRING
               DELIMITED BY ','
               INTO WS-FIELD-1
                    WS-FIELD-2
                    WS-FIELD-3
                    WS-FIELD-4
           END-UNSTRING
           DISPLAY 'Field 1: ' WS-FIELD-1
           DISPLAY 'Field 2: ' WS-FIELD-2
           DISPLAY 'Field 3: ' WS-FIELD-3
           DISPLAY 'Field 4: ' WS-FIELD-4
           
      *    UNSTRING with POINTER
           MOVE 1 TO WS-POINTER
           UNSTRING WS-INPUT-STRING
               DELIMITED BY ','
               INTO WS-FIELD-1
                    WS-FIELD-2
               WITH POINTER WS-POINTER
           END-UNSTRING
           DISPLAY 'Pointer after unstring: ' WS-POINTER
           
      *    UNSTRING with TALLYING
           MOVE ZERO TO WS-FIELD-COUNT
           UNSTRING WS-INPUT-STRING
               DELIMITED BY ','
               INTO WS-FIELD-1
                    WS-FIELD-2
                    WS-FIELD-3
                    WS-FIELD-4
               TALLYING IN WS-FIELD-COUNT
           END-UNSTRING
           DISPLAY 'Number of fields: ' WS-FIELD-COUNT
           
      *    UNSTRING with DELIMITER IN
           UNSTRING WS-INPUT-STRING
               DELIMITED BY ',' OR ';' OR '|'
               INTO WS-FIELD-1 DELIMITER IN WS-DELIMITER
                    WS-FIELD-2
           END-UNSTRING
           DISPLAY 'Delimiter found: ' WS-DELIMITER
           
      *    UNSTRING with ON OVERFLOW
           UNSTRING WS-INPUT-STRING
               DELIMITED BY ','
               INTO WS-FIELD-1
                    WS-FIELD-2
               ON OVERFLOW
                   DISPLAY 'More fields than targets'
               NOT ON OVERFLOW
                   DISPLAY 'All fields processed'
           END-UNSTRING.
           
       INSPECT-TESTS.
      *    INSPECT TALLYING
           MOVE ZERO TO WS-TALLY
           INSPECT WS-INSPECT-FIELD
               TALLYING WS-TALLY FOR ALL 'L'
           END-INSPECT
           DISPLAY 'Count of L: ' WS-TALLY
           
      *    INSPECT TALLYING with BEFORE/AFTER
           MOVE ZERO TO WS-TALLY
           INSPECT WS-INSPECT-FIELD
               TALLYING WS-TALLY FOR ALL 'L'
                   BEFORE INITIAL SPACE
           END-INSPECT
           DISPLAY 'L before space: ' WS-TALLY
           
      *    INSPECT REPLACING ALL
           INSPECT WS-INSPECT-FIELD
               REPLACING ALL 'L' BY 'X'
           END-INSPECT
           DISPLAY 'After replace: ' WS-INSPECT-FIELD
           
      *    INSPECT REPLACING LEADING
           MOVE 'AAA123BBB' TO WS-INSPECT-FIELD
           INSPECT WS-INSPECT-FIELD
               REPLACING LEADING 'A' BY 'X'
           END-INSPECT
           DISPLAY 'Replace leading: ' WS-INSPECT-FIELD
           
      *    INSPECT REPLACING FIRST
           MOVE 'HELLO HELLO' TO WS-INSPECT-FIELD
           INSPECT WS-INSPECT-FIELD
               REPLACING FIRST 'HELLO' BY 'WORLD'
           END-INSPECT
           DISPLAY 'Replace first: ' WS-INSPECT-FIELD
           
      *    INSPECT CONVERTING
           MOVE 'ABCDEF' TO WS-INSPECT-FIELD
           INSPECT WS-INSPECT-FIELD
               CONVERTING 'ABCDEF' TO '123456'
           END-INSPECT
           DISPLAY 'After convert: ' WS-INSPECT-FIELD
           
      *    Complex INSPECT with multiple operations
           MOVE 'TEST DATA' TO WS-INSPECT-FIELD
           INSPECT WS-INSPECT-FIELD
               TALLYING WS-TALLY FOR ALL 'T'
               REPLACING ALL 'A' BY 'X'
                        FIRST 'E' BY 'Y'
           END-INSPECT
           DISPLAY 'Complex inspect: ' WS-INSPECT-FIELD
           DISPLAY 'Tally: ' WS-TALLY.
           
       CORRESPONDING-TESTS.
      *    MOVE CORRESPONDING
           MOVE 12345 TO WS-SRC-ID
           MOVE 'Test Name' TO WS-SRC-NAME
           MOVE 1234567.89 TO WS-SRC-AMOUNT
           
           MOVE CORRESPONDING WS-SOURCE-REC TO WS-TARGET-REC
           
           DISPLAY 'Target ID: ' WS-TGT-ID
           DISPLAY 'Target Name: ' WS-TGT-NAME
           DISPLAY 'Target Amount: ' WS-TGT-AMOUNT
           
      *    ADD CORRESPONDING
           ADD CORRESPONDING WS-SOURCE-REC TO WS-TARGET-REC
           DISPLAY 'After ADD CORR Amount: ' WS-TGT-AMOUNT
           
      *    SUBTRACT CORRESPONDING
           SUBTRACT CORRESPONDING WS-SOURCE-REC FROM WS-TARGET-REC
           DISPLAY 'After SUBTRACT CORR Amount: ' WS-TGT-AMOUNT.
