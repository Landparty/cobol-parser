       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTSUB.
      * Called with the customer record; keeps the old layout.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  SUB-ID             PIC 9(6).
       LINKAGE SECTION.
       01  LK-CUST.
           05  LK-ID          PIC 9(6).
           05  LK-NAME        PIC X(20).
       PROCEDURE DIVISION USING LK-CUST.
       MAIN-PARA.
           MOVE LK-ID TO SUB-ID
           GOBACK.
