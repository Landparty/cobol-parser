       IDENTIFICATION DIVISION.
       PROGRAM-ID. WRITER.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INFILE.
           SELECT OUT-FILE ASSIGN TO OUTFILE.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  IN-ACCT    PIC X(10).
           05  IN-AMT     PIC 9(7)V99.
       FD  OUT-FILE.
       01  OUT-REC.
           05  OUT-ACCT   PIC X(10).
           05  OUT-AMT    PIC 9(7)V99.
           05  OUT-FEE    PIC 9(5)V99.
       WORKING-STORAGE SECTION.
       01  WS-REC.
           05  WS-ACCT    PIC X(10).
           05  WS-AMT     PIC 9(7)V99.
       01  WS-ALT REDEFINES WS-REC PIC X(19).
       01  WS-FEE         PIC 9(5)V99.
       01  WS-TOTAL       PIC 9(9)V99.
       01  WS-RATE        PIC 9V99 VALUE 0.10.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE OUTPUT OUT-FILE
           READ IN-FILE INTO WS-REC
           IF WS-AMT > 100
               COMPUTE WS-FEE = WS-AMT * WS-RATE
           END-IF
           ADD WS-AMT TO WS-TOTAL
           MOVE CORRESPONDING WS-REC TO OUT-REC
           MOVE WS-ACCT TO OUT-ACCT
           MOVE WS-AMT TO OUT-AMT
           MOVE WS-FEE TO OUT-FEE
           WRITE OUT-REC
           CALL 'SUBPGM' USING WS-REC WS-FEE
           EXEC SQL
               UPDATE ACCOUNT SET BALANCE = :WS-TOTAL
                WHERE ACCT_NO = :WS-ACCT
           END-EXEC
           DISPLAY WS-TOTAL
           CLOSE IN-FILE OUT-FILE
           STOP RUN.
