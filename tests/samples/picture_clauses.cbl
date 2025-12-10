      *****************************************************************
      * Complex Picture Clauses - All Variations
      * Tests: Numeric, alphanumeric, edited, signed, decimal
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PICTEST.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
      *    Basic Picture Clauses
       01  WS-BASIC-PICS.
           05  WS-ALPHA            PIC A(10).
           05  WS-ALPHANUMERIC     PIC X(20).
           05  WS-NUMERIC          PIC 9(5).
           05  WS-NUMERIC-DECIMAL  PIC 9(5)V99.
           
      *    Signed Numbers
       01  WS-SIGNED-PICS.
           05  WS-SIGNED-LEADING   PIC S9(5).
           05  WS-SIGNED-TRAILING  PIC 9(5)S.
           05  WS-SIGNED-DECIMAL   PIC S9(5)V99.
           
      *    Edited Pictures
       01  WS-EDITED-PICS.
           05  WS-ZERO-SUPPRESS    PIC Z,ZZZ,ZZ9.
           05  WS-ZERO-SUPP-DEC    PIC Z,ZZZ,ZZ9.99.
           05  WS-ASTERISK-FILL    PIC ***,**9.99.
           05  WS-FLOAT-DOLLAR     PIC $$$,$$9.99.
           05  WS-FIXED-DOLLAR     PIC $ZZ,ZZ9.99.
           05  WS-CREDIT-DEBIT     PIC ZZ,ZZ9.99CR.
           05  WS-DEBIT-BALANCE    PIC ZZ,ZZ9.99DB.
           05  WS-SIGNED-DISPLAY   PIC +Z,ZZZ,ZZ9.99.
           05  WS-SIGNED-TRAIL     PIC Z,ZZZ,ZZ9.99+.
           05  WS-SIGNED-MINUS     PIC -Z,ZZZ,ZZ9.99.
           
      *    Complex Edited Pictures
       01  WS-COMPLEX-PICS.
           05  WS-PHONE-NUMBER     PIC 9(3)B9(3)B9(4).
           05  WS-DATE-SLASH       PIC 99/99/9999.
           05  WS-DATE-DASH        PIC 99-99-9999.
           05  WS-FLOAT-INSERT     PIC $**,**9.99.
           05  WS-CHECK-PROTECT    PIC ***,***,**9.99.
           
      *    Scientific Notation (COBOL 2014)
       01  WS-SCIENTIFIC-PICS.
           05  WS-EXPONENT-POS     PIC 9V999E+99.
           05  WS-EXPONENT-NEG     PIC 9V999E-99.
           
      *    Picture with Parentheses Repetition
       01  WS-REPEAT-PICS.
           05  WS-REPEAT-X         PIC X(50).
           05  WS-REPEAT-9         PIC 9(10).
           05  WS-REPEAT-COMPLEX   PIC 9(5)V9(2).
           05  WS-REPEAT-EDIT      PIC Z(5).9(2).
           
      *    Leading Decimal Pictures
       01  WS-DECIMAL-PICS.
           05  WS-LEADING-DEC      PIC V999.
           05  WS-SIGNED-LEAD-DEC  PIC SV999.
           05  WS-DISPLAY-LEAD-DEC PIC .999.
           
      *    Scaling Factor (rare but valid)
       01  WS-SCALED-PICS.
           05  WS-SCALE-UP         PIC 99P(3).
           05  WS-SCALE-DOWN       PIC P(3)999.
           
      *    Blank When Zero
       01  WS-BLANK-PICS.
           05  WS-BLANK-ZERO       PIC Z(5) BLANK WHEN ZERO.
           
      *    Justified Right
       01  WS-JUSTIFIED-PICS.
           05  WS-JUST-RIGHT       PIC X(20) JUSTIFIED RIGHT.
           05  WS-JUST-ABBREV      PIC X(20) JUST RIGHT.
           
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE 12345.67 TO WS-ZERO-SUPPRESS
           DISPLAY 'Zero Suppress: ' WS-ZERO-SUPPRESS
           
           MOVE -12345.67 TO WS-SIGNED-DISPLAY
           DISPLAY 'Signed: ' WS-SIGNED-DISPLAY
           
           MOVE 12345.67 TO WS-FLOAT-DOLLAR
           DISPLAY 'Float Dollar: ' WS-FLOAT-DOLLAR
           
           MOVE 1234567890 TO WS-PHONE-NUMBER
           DISPLAY 'Phone: ' WS-PHONE-NUMBER
           
           MOVE 12092025 TO WS-DATE-SLASH
           DISPLAY 'Date: ' WS-DATE-SLASH
           
           STOP RUN.
