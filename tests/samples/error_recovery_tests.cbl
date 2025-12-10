      *****************************************************************
      * Error Recovery Test Cases
      * Tests: Missing periods, invalid syntax, boundary conditions
      * Note: These are intentionally malformed for parser testing
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ERRORTEST
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
      *    Missing period after line number
       01  WS-NORMAL-FIELD         PIC X(10) VALUE 'NORMAL'
       
      *    Invalid PICTURE clause
       01  WS-INVALID-PIC          PIC Z(10)9(5)V99.
       
      *    Missing level number
           WS-NO-LEVEL             PIC X(5).
       
      *    Invalid level number
       100 WS-INVALID-LEVEL        PIC 9(3).
       
      *    Incomplete field definition
       01  WS-INCOMPLETE-FIELD
       
      *    Missing VALUE keyword
       01  WS-VALUE-TEST           PIC X(5) 'HELLO'.
       
      *    Empty PICTURE clause
       01  WS-EMPTY-PIC            PIC .
       
      *    Mismatched parentheses in PICTURE
       01  WS-MISMATCH-PIC         PIC X(10.
       
      *    Zero-length PICTURE
       01  WS-ZERO-PIC             PIC X(0).
       
      *    Negative PICTURE length
       01  WS-NEG-PIC              PIC X(-5).
       
      *    Very large PICTURE (boundary test - max is usually 9999)
       01  WS-LARGE-PIC            PIC X(10000).
       
      *    REDEFINES without original field
       01  WS-REDEF-ERROR REDEFINES WS-NONEXISTENT PIC X(10).
       
      *    Multiple VALUE clauses
       01  WS-DOUBLE-VALUE         PIC X(5) 
           VALUE 'FIRST' VALUE 'SECOND'.
       
      *    OCCURS with invalid range
       01  WS-OCCURS-ERROR OCCURS 0 TIMES PIC X(5).
       
      *    OCCURS DEPENDING ON with wrong data type
       01  WS-OCCURS-DEP-ERROR OCCURS 1 TO 10 TIMES
           DEPENDING ON WS-NORMAL-FIELD PIC X(5).
           
       PROCEDURE DIVISION.
       MAIN-LOGIC
      *    Missing period after paragraph name
           DISPLAY 'Starting error tests'
           
      *    Incomplete statement
           MOVE WS-NORMAL-FIELD TO
           
      *    Missing TO in MOVE
           MOVE WS-NORMAL-FIELD WS-INVALID-PIC
           
      *    Invalid PERFORM range
           PERFORM PARA-START THRU PARA-END
           
      *    PERFORM with undefined paragraph
           PERFORM NONEXISTENT-PARA
           
      *    Missing END-IF
           IF WS-NORMAL-FIELD = 'TEST'
               DISPLAY 'Test condition'
           
      *    Unmatched END-IF
           END-IF
           
      *    Missing END-PERFORM
           PERFORM VARYING WS-NORMAL-FIELD FROM 1 BY 1
               UNTIL WS-NORMAL-FIELD > 10
               DISPLAY WS-NORMAL-FIELD
           
      *    Invalid EVALUATE
           EVALUATE WS-NORMAL-FIELD
               DISPLAY 'Missing WHEN'
           END-EVALUATE
           
      *    Empty WHEN clause
           EVALUATE WS-NORMAL-FIELD
               WHEN
                   DISPLAY 'Empty when'
           END-EVALUATE
           
      *    Missing END-EVALUATE
           EVALUATE WS-NORMAL-FIELD
               WHEN 'TEST'
                   DISPLAY 'Test'
           
      *    GO TO undefined paragraph
           GO TO NOWHERE-PARA
           
      *    ALTER with undefined paragraphs
           ALTER PARA-1 TO PROCEED TO PARA-2
           
      *    READ without file
           READ
           
      *    WRITE without record
           WRITE
           
      *    Missing AT END
           READ INPUT-FILE
           
      *    Invalid OPEN mode
           OPEN INVALID INPUT-FILE
           
      *    Multiple STOP RUN (boundary test)
           STOP RUN
           STOP RUN
           
      *    Code after STOP RUN
           DISPLAY 'This should not execute'
           
      *    Missing required division
      *    (ENVIRONMENT DIVISION is missing from this program)
           
      *    Unterminated string
           DISPLAY 'This string has no end
           
      *    Invalid numeric literal
           MOVE 123.45.67 TO WS-NORMAL-FIELD
           
      *    Division by zero
           DIVIDE WS-NORMAL-FIELD BY 0 GIVING WS-INVALID-PIC
           
      *    Circular REDEFINES (should be caught by semantic analysis)
      *    (Not shown here as it requires valid syntax first)
           
      *    Reserved word as identifier
           MOVE 'TEST' TO MOVE
           
      *    Empty paragraph
       EMPTY-PARA.
       
      *    Paragraph with only comment
       COMMENT-ONLY-PARA.
      *    This paragraph has only a comment
       
      *    Multiple paragraphs with same name (duplicate definition)
       DUPLICATE-PARA.
           DISPLAY 'First definition'.
           
       DUPLICATE-PARA.
           DISPLAY 'Second definition'.
           
      *    SECTION without paragraphs
       EMPTY-SECTION SECTION.
       
      *    Invalid section name
       123-SECTION SECTION.
           DISPLAY 'Invalid section name'.
