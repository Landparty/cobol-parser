       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTRD.
      * Reads the customer file through its own copy of the layout.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-FILE ASSIGN TO CUSTIN.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST-FILE.
       01  CUST-REC.
           05  CUST-ID        PIC 9(6).
           05  CUST-NAME      PIC X(20).
           05  CUST-BAL       PIC S9(7)V99 COMP-3.
       WORKING-STORAGE SECTION.
       01  RD-ID              PIC 9(6).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT CUST-FILE
           READ CUST-FILE
           MOVE CUST-ID TO RD-ID
           CLOSE CUST-FILE
           STOP RUN.
