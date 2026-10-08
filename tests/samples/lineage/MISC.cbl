       IDENTIFICATION DIVISION.
       PROGRAM-ID. MISC.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO UT-S-INFILE.
           SELECT OUT-FILE ASSIGN TO OUTFILE.
           SELECT SRT-FILE ASSIGN TO SORTWK01.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC         PIC X(20).
       FD  OUT-FILE.
       01  OUT-REC        PIC X(30).
       SD  SRT-FILE.
       01  SRT-REC        PIC X(20).
       WORKING-STORAGE SECTION.
       01  WS-A.
           05  ACCT       PIC X(10).
           05  AMT        PIC 9(8)V99.
       01  WS-B.
           05  AMT        PIC 9(8)V99.
           05  ACCT       PIC X(10).
       01  WS-LINE        PIC X(30).
       01  WS-CODE        PIC X(4).
       01  WS-PARM        PIC X(8).
       01  WS-PGM         PIC X(8) VALUE 'SUBA'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE OUTPUT OUT-FILE
           READ IN-FILE INTO WS-A
           MOVE CORRESPONDING WS-A TO WS-B
           MOVE WS-A TO WS-LINE
           MOVE WS-LINE(3:4) TO WS-CODE
           STRING WS-CODE DELIMITED BY SIZE INTO WS-PARM
           ACCEPT WS-PARM
           WRITE OUT-REC FROM WS-LINE
           CALL WS-PGM USING WS-B
           SORT SRT-FILE ON ASCENDING KEY SRT-REC
               USING IN-FILE GIVING OUT-FILE
           CLOSE IN-FILE OUT-FILE
           STOP RUN.
