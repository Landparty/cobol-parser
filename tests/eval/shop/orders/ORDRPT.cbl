       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDRPT.
      * ORDER HISTORY REPORT: TOTAL POSTED AMOUNT AND FEES
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT HIST-FILE ASSIGN TO ORDHIST.
           SELECT RPT-FILE  ASSIGN TO RPTOUT.
       DATA DIVISION.
       FILE SECTION.
       FD  HIST-FILE.
           COPY HISTREC.
       FD  RPT-FILE.
       01  RPT-LINE.
           05  RPT-LABEL             PIC X(20).
           05  RPT-TOTAL             PIC Z,ZZZ,ZZZ,ZZ9.99-.
           05  RPT-FEES              PIC ZZZ,ZZ9.99-.
           05  FILLER                PIC X(84).
       WORKING-STORAGE SECTION.
       01  WS-EOF                    PIC X VALUE 'N'.
       01  WS-TOTAL                  PIC S9(11)V99 COMP-3 VALUE 0.
       01  WS-FEES                   PIC S9(7)V99  COMP-3 VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT HIST-FILE OUTPUT RPT-FILE
           PERFORM UNTIL WS-EOF = 'Y'
               READ HIST-FILE
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END
                       ADD HIST-AMT TO WS-TOTAL
                       ADD HIST-FEE TO WS-FEES
               END-READ
           END-PERFORM
           MOVE 'TOTAL POSTED' TO RPT-LABEL
           MOVE WS-TOTAL TO RPT-TOTAL
           MOVE WS-FEES  TO RPT-FEES
           WRITE RPT-LINE
           CLOSE HIST-FILE RPT-FILE
           GOBACK.
