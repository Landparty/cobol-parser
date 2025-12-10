      *****************************************************************
      * Special Names and Configuration
      * Tests: SPECIAL-NAMES, CURRENCY SIGN, DECIMAL-POINT, ALPHABET
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SPECNAMES.
       
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. IBM-370.
       OBJECT-COMPUTER. IBM-370
           PROGRAM COLLATING SEQUENCE IS EBCDIC-SEQUENCE
           MEMORY SIZE 1024 WORDS.
           
       SPECIAL-NAMES.
      *    Currency sign customization
           CURRENCY SIGN IS '$'
           CURRENCY SIGN IS 'EUR' WITH PICTURE SYMBOL 'E'
           
      *    Decimal point is comma (European format)
           DECIMAL-POINT IS COMMA
           
      *    Alphabet definitions
           ALPHABET EBCDIC-SEQUENCE IS EBCDIC
           ALPHABET ASCII-SEQUENCE IS ASCII
           ALPHABET CUSTOM-ALPHA IS
               'A' THRU 'Z'
               'a' THRU 'z'
               '0' THRU '9'
               SPACE
           
      *    Class definitions
           CLASS ALPHABETIC-LOWER IS 'a' THRU 'z'
           CLASS ALPHABETIC-UPPER IS 'A' THRU 'Z'
           CLASS NUMERIC-ONLY IS '0' THRU '9'
           CLASS VALID-CHARS IS 
               'A' THRU 'Z'
               'a' THRU 'z'
               '0' THRU '9'
               SPACE '-' '/'
           
      *    Symbolic character definitions
           SYMBOLIC CHARACTERS
               DEGREE-SIGN IS 176
               COPYRIGHT-SIGN IS 169
               TRADEMARK-SIGN IS 153
               EURO-SIGN IS 128
               
      *    Console is CRT
           CONSOLE IS CRT
           
      *    Switch status names
           C01 IS SWITCH-1 ON STATUS IS SW-1-ON OFF STATUS IS SW-1-OFF
           C02 IS SWITCH-2 ON STATUS IS SW-2-ON OFF STATUS IS SW-2-OFF
           C03 IS SWITCH-3
           C11 IS DEBUG-MODE
           
      *    Function key definitions
           CRT STATUS IS WS-CRT-STATUS
           CURSOR IS WS-CURSOR-POS.
           
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CURRENCY-FILE ASSIGN TO 'CURR.DAT'
               ORGANIZATION IS SEQUENTIAL.
               
       DATA DIVISION.
       FILE SECTION.
       FD  CURRENCY-FILE.
       01  CURRENCY-RECORD.
           05  CURR-AMOUNT         PIC $$$,$$9.99.
           05  CURR-EUR-AMOUNT     PIC EEE.EE9,99.
           05  CURR-DESCRIPTION    PIC X(30).
           
       WORKING-STORAGE SECTION.
       01  WS-CURRENCY-AMOUNTS.
           05  WS-DOLLAR-AMT       PIC $$,$$9.99 VALUE $1,234.56.
           05  WS-EURO-AMT         PIC EEE,EE9.99 VALUE EUR1.234,56.
           05  WS-YEN-AMT          PIC ¥¥¥,¥¥9 VALUE ¥123,456.
           
       01  WS-DECIMAL-TESTS.
           05  WS-EURO-NUMBER      PIC 9(5),99 VALUE 12345,67.
           05  WS-US-NUMBER        PIC 9(5).99 VALUE 12345.67.
           
       01  WS-CLASS-TEST-FIELDS.
           05  WS-ALPHA-LOWER      PIC X(10) VALUE 'lowercase'.
           05  WS-ALPHA-UPPER      PIC X(10) VALUE 'UPPERCASE'.
           05  WS-NUMERIC-FIELD    PIC X(10) VALUE '1234567890'.
           05  WS-MIXED-FIELD      PIC X(20) VALUE 'Mixed123-With/Chars'.
           
       01  WS-SYMBOLIC-CHARS.
           05  WS-DEGREE           PIC X VALUE DEGREE-SIGN.
           05  WS-COPYRIGHT        PIC X VALUE COPYRIGHT-SIGN.
           05  WS-TRADEMARK        PIC X VALUE TRADEMARK-SIGN.
           05  WS-EURO             PIC X VALUE EURO-SIGN.
           
       01  WS-SWITCH-STATUS.
           05  WS-SW1-STATE        PIC X VALUE 'N'.
               88  SW-1-ON         VALUE 'Y'.
               88  SW-1-OFF        VALUE 'N'.
           05  WS-SW2-STATE        PIC X VALUE 'N'.
               88  SW-2-ON         VALUE 'Y'.
               88  SW-2-OFF        VALUE 'N'.
               
       01  WS-CRT-STATUS           PIC 9(4).
       01  WS-CURSOR-POS.
           05  WS-CURSOR-ROW       PIC 9(2).
           05  WS-CURSOR-COL       PIC 9(2).
           
       01  WS-ALPHABET-TEST        PIC X(50).
       
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM CURRENCY-TESTS
           PERFORM CLASS-TESTS
           PERFORM SWITCH-TESTS
           PERFORM ALPHABET-TESTS
           STOP RUN.
           
       CURRENCY-TESTS.
           DISPLAY 'Currency Symbol Tests:'
           DISPLAY '  Dollar amount: ' WS-DOLLAR-AMT
           DISPLAY '  Euro amount: ' WS-EURO-AMT
           DISPLAY '  Yen amount: ' WS-YEN-AMT
           
           DISPLAY 'Decimal Point Tests:'
           DISPLAY '  European format: ' WS-EURO-NUMBER
           DISPLAY '  US format: ' WS-US-NUMBER
           
           MOVE 2345,67 TO WS-EURO-NUMBER
           DISPLAY '  After MOVE: ' WS-EURO-NUMBER
           
           OPEN INPUT CURRENCY-FILE
           READ CURRENCY-FILE
               AT END
                   DISPLAY 'Currency file empty'
               NOT AT END
                   DISPLAY 'Amount: ' CURR-AMOUNT
                   DISPLAY 'Euro: ' CURR-EUR-AMOUNT
           END-READ
           CLOSE CURRENCY-FILE.
           
       CLASS-TESTS.
           DISPLAY 'Class Test Results:'
           
           IF WS-ALPHA-LOWER IS ALPHABETIC-LOWER
               DISPLAY '  lowercase passed lower test'
           END-IF
           
           IF WS-ALPHA-UPPER IS ALPHABETIC-UPPER
               DISPLAY '  UPPERCASE passed upper test'
           END-IF
           
           IF WS-NUMERIC-FIELD IS NUMERIC-ONLY
               DISPLAY '  Numeric field passed numeric test'
           END-IF
           
           IF WS-MIXED-FIELD IS VALID-CHARS
               DISPLAY '  Mixed field has valid characters'
           ELSE
               DISPLAY '  Mixed field has invalid characters'
           END-IF
           
           IF WS-NUMERIC-FIELD IS NOT ALPHABETIC-LOWER
               DISPLAY '  Numeric field correctly NOT lowercase'
           END-IF.
           
       SWITCH-TESTS.
           DISPLAY 'Switch Status Tests:'
           
           IF SW-1-OFF
               DISPLAY '  Switch 1 is OFF'
               SET SW-1-ON TO TRUE
           END-IF
           
           IF SW-1-ON
               DISPLAY '  Switch 1 is now ON'
           END-IF
           
           SET SW-2-ON TO TRUE
           IF SW-2-ON
               DISPLAY '  Switch 2 is ON'
           END-IF
           
           DISPLAY '  CRT Status: ' WS-CRT-STATUS
           DISPLAY '  Cursor Row: ' WS-CURSOR-ROW
           DISPLAY '  Cursor Col: ' WS-CURSOR-COL.
           
       ALPHABET-TESTS.
           DISPLAY 'Alphabet and Symbolic Character Tests:'
           
           MOVE 'ABC123xyz' TO WS-ALPHABET-TEST
           DISPLAY '  Test string: ' WS-ALPHABET-TEST
           
           DISPLAY '  Special symbols:'
           DISPLAY '    Degree: ' WS-DEGREE
           DISPLAY '    Copyright: ' WS-COPYRIGHT
           DISPLAY '    Trademark: ' WS-TRADEMARK
           DISPLAY '    Euro: ' WS-EURO
           
           INSPECT WS-ALPHABET-TEST
               CONVERTING 'abc' TO 'ABC'
               
           DISPLAY '  After conversion: ' WS-ALPHABET-TEST.
