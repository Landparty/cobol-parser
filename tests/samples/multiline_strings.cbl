      *****************************************************************
      * Multi-line String Literals with Continuation
      * Tests: String continuation across lines, VALUE clause
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MLSTRING.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-SHORT-STRING         PIC X(20) VALUE
      -    "Hello World".
           
       01  WS-LONG-STRING          PIC X(100) VALUE
      -    "This is a very long string that spans multiple lines "
      -    "and needs to be continued across several continuation "
      -    "lines in the COBOL source code for readability".
           
       01  WS-MULTI-QUOTE          PIC X(50) VALUE
      -    "String with ""embedded quotes"" in the middle".
           
       01  WS-APOSTROPHE-STRING    PIC X(30) VALUE
      -    'Using single quotes instead'.
           
       01  WS-COMPLEX-CONTINUATION PIC X(80) VALUE
      -    "Line one "
      -    "line two "
      -    "line three".
           
       01  WS-NUMERIC-STRING       PIC X(30) VALUE
      -    "123456789"
      -    "0".
           
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'Short: ' WS-SHORT-STRING
           DISPLAY 'Long: ' WS-LONG-STRING
           DISPLAY 'Quotes: ' WS-MULTI-QUOTE
           DISPLAY 'Apostrophe: ' WS-APOSTROPHE-STRING
           DISPLAY 'Complex: ' WS-COMPLEX-CONTINUATION
           DISPLAY 'Numeric: ' WS-NUMERIC-STRING
           STOP RUN.
