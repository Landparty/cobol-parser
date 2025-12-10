      *****************************************************************
      * OCCURS Clause Variations
      * Tests: Fixed OCCURS, DEPENDING ON, INDEXED BY, nested tables
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OCCURTEST.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
      *    Simple Fixed OCCURS
       01  WS-SIMPLE-TABLE.
           05  WS-TABLE-ENTRY      PIC X(10) OCCURS 10 TIMES.
           
      *    OCCURS with DEPENDING ON
       01  WS-VAR-TABLE-SIZE       PIC 99 VALUE 5.
       01  WS-VARIABLE-TABLE.
           05  WS-VAR-ENTRY        PIC X(20) 
               OCCURS 1 TO 100 TIMES DEPENDING ON WS-VAR-TABLE-SIZE.
               
      *    OCCURS with INDEXED BY
       01  WS-INDEXED-TABLE.
           05  WS-IDX-ENTRY        PIC 9(5) 
               OCCURS 50 TIMES INDEXED BY IDX-1.
               
      *    Two-Dimensional Table
       01  WS-2D-TABLE.
           05  WS-ROW              OCCURS 10 TIMES.
               10  WS-COLUMN       PIC 9(3) OCCURS 5 TIMES.
               
      *    Three-Dimensional Table
       01  WS-3D-TABLE.
           05  WS-LAYER            OCCURS 5 TIMES.
               10  WS-ROW-3D       OCCURS 10 TIMES.
                   15  WS-COL-3D   PIC X(2) OCCURS 8 TIMES.
                   
      *    OCCURS with Multiple INDEXED BY
       01  WS-MULTI-INDEX.
           05  WS-OUTER            OCCURS 20 TIMES 
               INDEXED BY IDX-OUTER.
               10  WS-INNER        PIC 9(4) 
                   OCCURS 10 TIMES INDEXED BY IDX-INNER.
                   
      *    Complex Structure with OCCURS
       01  WS-COMPLEX-OCCURS.
           05  WS-RECORD-GROUP     OCCURS 100 TIMES.
               10  WS-RECORD-ID    PIC 9(5).
               10  WS-RECORD-NAME  PIC X(30).
               10  WS-RECORD-AMT   PIC 9(7)V99 COMP-3.
               10  WS-RECORD-FLAGS.
                   15  WS-FLAG     PIC X OCCURS 10 TIMES.
                   
      *    OCCURS with KEY (sorted table)
       01  WS-SORTED-TABLE.
           05  WS-SORT-ENTRY       OCCURS 50 TIMES
               ASCENDING KEY IS WS-SORT-KEY
               INDEXED BY IDX-SORT.
               10  WS-SORT-KEY     PIC 9(5).
               10  WS-SORT-DATA    PIC X(20).
               
       01  WS-COUNTERS.
           05  WS-I                PIC 99.
           05  WS-J                PIC 99.
           05  WS-K                PIC 99.
           
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'Testing OCCURS clauses'
           
      *    Simple table access
           MOVE 'ENTRY-001' TO WS-TABLE-ENTRY(1)
           MOVE 'ENTRY-010' TO WS-TABLE-ENTRY(10)
           DISPLAY 'First: ' WS-TABLE-ENTRY(1)
           DISPLAY 'Last: ' WS-TABLE-ENTRY(10)
           
      *    Loop through table
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 10
               MOVE WS-I TO WS-TABLE-ENTRY(WS-I)
           END-PERFORM
           
      *    2D table access
           MOVE 100 TO WS-COLUMN(5, 3)
           DISPLAY '2D Value: ' WS-COLUMN(5, 3)
           
      *    3D table access
           MOVE 'XY' TO WS-COL-3D(2, 5, 4)
           DISPLAY '3D Value: ' WS-COL-3D(2, 5, 4)
           
      *    Nested loops for 2D table
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 10
               PERFORM VARYING WS-J FROM 1 BY 1 UNTIL WS-J > 5
                   COMPUTE WS-COLUMN(WS-I, WS-J) = WS-I * WS-J
               END-PERFORM
           END-PERFORM
           
      *    Using INDEXED BY
           SET IDX-1 TO 1
           MOVE 12345 TO WS-IDX-ENTRY(IDX-1)
           SET IDX-1 UP BY 1
           MOVE 67890 TO WS-IDX-ENTRY(IDX-1)
           
      *    SEARCH statement with index
           SET IDX-SORT TO 1
           SEARCH WS-SORT-ENTRY
               AT END DISPLAY 'Not found'
               WHEN WS-SORT-KEY(IDX-SORT) = 100
                   DISPLAY 'Found at index: ' IDX-SORT
           END-SEARCH
           
           STOP RUN.
