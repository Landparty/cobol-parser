      *****************************************************************
      * REDEFINES Clause Test
      * Tests: Simple redefines, multiple redefines, complex overlays
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. REDEFTEST.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
      *    Simple REDEFINES
       01  WS-ORIGINAL-DATA        PIC X(20) VALUE 'ORIGINAL'.
       01  WS-REDEF-NUMERIC        REDEFINES WS-ORIGINAL-DATA
           PIC 9(20).
           
      *    Multiple REDEFINEs of same area
       01  WS-BASE-AREA            PIC X(10).
       01  WS-REDEF-1              REDEFINES WS-BASE-AREA
           PIC 9(10).
       01  WS-REDEF-2              REDEFINES WS-BASE-AREA.
           05  WS-REDEF-2-PART1    PIC X(5).
           05  WS-REDEF-2-PART2    PIC X(5).
           
      *    Complex Structure with REDEFINES
       01  WS-COMPLEX-RECORD.
           05  WS-RECORD-TYPE      PIC X.
               88  TYPE-A          VALUE 'A'.
               88  TYPE-B          VALUE 'B'.
           05  WS-RECORD-DATA      PIC X(99).
           
       01  WS-TYPE-A-RECORD        REDEFINES WS-COMPLEX-RECORD.
           05  FILLER              PIC X.
           05  WS-A-CODE           PIC X(5).
           05  WS-A-AMOUNT         PIC 9(7)V99.
           05  WS-A-DATE           PIC 9(8).
           05  FILLER              PIC X(79).
           
       01  WS-TYPE-B-RECORD        REDEFINES WS-COMPLEX-RECORD.
           05  FILLER              PIC X.
           05  WS-B-NAME           PIC X(30).
           05  WS-B-ADDRESS        PIC X(40).
           05  WS-B-CITY           PIC X(20).
           05  FILLER              PIC X(9).
           
      *    Union-like structure
       01  WS-UNION-AREA.
           05  WS-UNION-LENGTH     PIC 9(4) COMP.
           05  WS-UNION-DATA       PIC X(100).
           
       01  WS-UNION-AS-NUMERIC     REDEFINES WS-UNION-AREA.
           05  FILLER              PIC XX.
           05  WS-NUMERIC-ARRAY    PIC 9(4) OCCURS 25 TIMES.
           
       01  WS-UNION-AS-STRUCT      REDEFINES WS-UNION-AREA.
           05  FILLER              PIC XX.
           05  WS-STRUCT-ITEMS     OCCURS 10 TIMES.
               10  WS-ITEM-ID      PIC 9(5).
               10  WS-ITEM-DESC    PIC X(5).
               
      *    Date/Time overlay
       01  WS-DATE-TIME-NUMERIC    PIC 9(14).
       01  WS-DATE-TIME-STRUCT     REDEFINES WS-DATE-TIME-NUMERIC.
           05  WS-YEAR             PIC 9(4).
           05  WS-MONTH            PIC 99.
           05  WS-DAY              PIC 99.
           05  WS-HOUR             PIC 99.
           05  WS-MINUTE           PIC 99.
           05  WS-SECOND           PIC 99.
           
      *    Binary/character overlay
       01  WS-BINARY-WORD          PIC 9(4) COMP.
       01  WS-BINARY-BYTES         REDEFINES WS-BINARY-WORD.
           05  WS-HIGH-BYTE        PIC X.
           05  WS-LOW-BYTE         PIC X.
           
      *    Nested REDEFINES
       01  WS-NESTED-BASE.
           05  WS-NEST-AREA1       PIC X(50).
           05  WS-NEST-AREA2       PIC X(50).
           
       01  WS-NESTED-REDEF         REDEFINES WS-NESTED-BASE.
           05  WS-NEST-FULL        PIC X(100).
           
       01  WS-NESTED-REDEF2        REDEFINES WS-NESTED-BASE.
           05  WS-NEST-GROUPS      OCCURS 10 TIMES.
               10  WS-NEST-ITEM    PIC X(10).
               
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'Testing REDEFINES'
           
      *    Test simple redefines
           MOVE '12345678901234567890' TO WS-ORIGINAL-DATA
           DISPLAY 'Numeric view: ' WS-REDEF-NUMERIC
           
      *    Test multiple redefines
           MOVE 'ABCDE12345' TO WS-BASE-AREA
           DISPLAY 'Part 1: ' WS-REDEF-2-PART1
           DISPLAY 'Part 2: ' WS-REDEF-2-PART2
           
      *    Test conditional structure
           MOVE 'A' TO WS-RECORD-TYPE
           IF TYPE-A
               MOVE 'CODE1' TO WS-A-CODE
               MOVE 1234567.89 TO WS-A-AMOUNT
               DISPLAY 'Type A Code: ' WS-A-CODE
               DISPLAY 'Type A Amount: ' WS-A-AMOUNT
           END-IF
           
           MOVE 'B' TO WS-RECORD-TYPE
           IF TYPE-B
               MOVE 'John Doe' TO WS-B-NAME
               MOVE '123 Main St' TO WS-B-ADDRESS
               DISPLAY 'Type B Name: ' WS-B-NAME
               DISPLAY 'Type B Address: ' WS-B-ADDRESS
           END-IF
           
      *    Test date/time overlay
           MOVE 20251209143045 TO WS-DATE-TIME-NUMERIC
           DISPLAY 'Year: ' WS-YEAR
           DISPLAY 'Month: ' WS-MONTH
           DISPLAY 'Day: ' WS-DAY
           DISPLAY 'Hour: ' WS-HOUR
           DISPLAY 'Minute: ' WS-MINUTE
           DISPLAY 'Second: ' WS-SECOND
           
           STOP RUN.
