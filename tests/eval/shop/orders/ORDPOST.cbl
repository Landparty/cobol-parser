       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDPOST.
      * POST SORTED GOOD ORDERS TO ORDER HISTORY
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT GOOD-FILE ASSIGN TO ORDGOOD.
           SELECT HIST-FILE ASSIGN TO ORDHIST.
       DATA DIVISION.
       FILE SECTION.
       FD  GOOD-FILE.
           COPY ORDREC.
       FD  HIST-FILE.
           COPY HISTREC.
       WORKING-STORAGE SECTION.
       01  WS-EOF                    PIC X VALUE 'N'.
       01  WS-POST-PGM               PIC X(8).
       01  WS-FEE                    PIC S9(5)V99 COMP-3.
       01  WS-REGION                 PIC X(4).
       01  WS-RUN-DATE               PIC 9(8).
       01  WS-OLD-RATE               PIC 9V9999 VALUE 0.0125.
       01  WS-AUDIT-FLAG             PIC X VALUE SPACE.
       PROCEDURE DIVISION.
       0000-MAIN.
           ACCEPT WS-RUN-DATE FROM DATE YYYYMMDD
           OPEN INPUT GOOD-FILE OUTPUT HIST-FILE
           PERFORM 1000-NEXT
           PERFORM 2000-POST UNTIL WS-EOF = 'Y'
           CLOSE GOOD-FILE HIST-FILE
           GOBACK.
       1000-NEXT.
           READ GOOD-FILE AT END MOVE 'Y' TO WS-EOF END-READ.
       2000-POST.
           IF ORD-HELD
               PERFORM 1000-NEXT
           ELSE
               IF ADDR-FOREIGN
                   MOVE 'POSTINTL' TO WS-POST-PGM
               ELSE
                   MOVE 'POSTDOM' TO WS-POST-PGM
               END-IF
               CALL WS-POST-PGM USING ORD-REC WS-FEE WS-REGION
               PERFORM 3000-WRITE-HIST
               PERFORM 1000-NEXT
           END-IF.
       3000-WRITE-HIST.
           MOVE ORD-ID      TO HIST-ORD-ID
           MOVE ORD-CUST-ID TO HIST-CUST-ID
           MOVE ORD-AMT     TO HIST-AMT
           MOVE WS-FEE      TO HIST-FEE
           MOVE WS-RUN-DATE TO HIST-POST-DATE
           MOVE WS-REGION   TO HIST-REGION
           WRITE HIST-REC.
       9000-OLD-RECALC.
           COMPUTE WS-FEE = ORD-AMT * WS-OLD-RATE.
       9100-OLD-AUDIT.
           MOVE 'Y' TO WS-AUDIT-FLAG
           DISPLAY 'AUDIT ' ORD-ID.
