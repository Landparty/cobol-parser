       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTWRT.
      * Writes the customer file; CUST-ID is the field the tests widen.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-FILE ASSIGN TO CUSTOUT.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST-FILE.
       01  CUST-REC.
           05  CUST-ID        PIC 9(6).
           05  CUST-NAME      PIC X(20).
           05  CUST-BAL       PIC S9(7)V99 COMP-3.
       WORKING-STORAGE SECTION.
       01  WS-CUST.
           05  WS-ID          PIC 9(6).
           05  WS-NAME        PIC X(20).
       01  WS-ID-TEXT         PIC X(6).
       01  WS-ID-WIDE         PIC 9(9).
       01  WS-ID-SHORT        PIC 9(4).
       01  WS-BAL-SHORT       PIC S9(7)V9.
       01  WS-BAL-COPY        PIC S9(7)V99.
       01  WS-COUNT           PIC 9(9) COMP.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN OUTPUT CUST-FILE
           MOVE CUST-ID TO WS-ID-TEXT
           MOVE CUST-ID TO WS-ID-WIDE
           MOVE CUST-ID TO WS-ID-SHORT
           MOVE CUST-BAL TO WS-BAL-SHORT
           MOVE CUST-BAL TO WS-BAL-COPY
           ADD CUST-ID TO WS-COUNT
           MOVE CUST-REC TO WS-CUST
           CALL 'CUSTSUB' USING WS-CUST
           WRITE CUST-REC
           CLOSE CUST-FILE
           STOP RUN.
