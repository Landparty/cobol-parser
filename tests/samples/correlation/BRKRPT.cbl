       IDENTIFICATION DIVISION.
       PROGRAM-ID. BRKRPT.
      * A control break: a forced ('09') transaction for the same branch
      * as the record before it is handled apart. Reaching
      * SAME-BRANCH-FORCED needs two consecutive records with one
      * TXN-BRANCH, which no single record can say.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TXN-FILE ASSIGN TO TXNIN.
       DATA DIVISION.
       FILE SECTION.
       FD  TXN-FILE.
       01  TXN-REC.
           05  TXN-BRANCH     PIC X(4).
           05  TXN-TYPE       PIC X(2).
           05  TXN-AMT        PIC 9(5).
       WORKING-STORAGE SECTION.
       01  WS-EOF             PIC X VALUE 'N'.
           88  END-OF-FILE    VALUE 'Y'.
       01  WS-PREV-BRANCH     PIC X(4) VALUE SPACES.
       01  WS-PREV-AMT        PIC 9(5) VALUE 0.
       01  WS-COUNT           PIC 9(5) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT TXN-FILE
           READ TXN-FILE AT END SET END-OF-FILE TO TRUE END-READ
           PERFORM PROCESS-REC UNTIL END-OF-FILE
           CLOSE TXN-FILE
           STOP RUN.
       PROCESS-REC.
           IF TXN-BRANCH = WS-PREV-BRANCH AND TXN-TYPE = '09'
               PERFORM SAME-BRANCH-FORCED
           ELSE
               ADD 1 TO WS-COUNT
           END-IF
           IF TXN-AMT > WS-PREV-AMT
               DISPLAY 'RISING ' TXN-AMT
           END-IF
           MOVE TXN-BRANCH TO WS-PREV-BRANCH
           MOVE TXN-AMT TO WS-PREV-AMT
           READ TXN-FILE AT END SET END-OF-FILE TO TRUE END-READ.
       SAME-BRANCH-FORCED.
           DISPLAY 'FORCED ' TXN-BRANCH.
