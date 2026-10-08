       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-WORK        PIC 9(7)V99.
       LINKAGE SECTION.
       01  LK-REC.
           05  LK-ACCT    PIC X(10).
           05  LK-AMT     PIC 9(7)V99.
       01  LK-FEE         PIC 9(5)V99.
       PROCEDURE DIVISION USING LK-REC LK-FEE.
       MAIN-PARA.
           MOVE LK-AMT TO WS-WORK
           COMPUTE LK-FEE = WS-WORK / 100
           GOBACK.
