       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-READ-STATEMENTS.
       
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MASTER-FILE ASSIGN TO EXTERNAL MASTER-DAT
               ORGANIZATION IS INDEXED
               RECORD KEY IS MASTER-KEY.
       
       DATA DIVISION.
       FILE SECTION.
       FD  MASTER-FILE.
       01  MASTER-REC.
           05  MASTER-KEY            PIC 9(5).
           05  MASTER-DATA           PIC X(95).
       
       WORKING-STORAGE SECTION.
       01  WS-KEY                    PIC 9(5).
       01  WS-EOF                    PIC X VALUE 'N'.
       
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN INPUT MASTER-FILE.
           
           PERFORM READ-NEXT-RECORD.
           PERFORM READ-BY-KEY.
           PERFORM READ-WITH-LOCK.
           
           CLOSE MASTER-FILE.
           STOP RUN.
       
       READ-NEXT-RECORD.
           READ MASTER-FILE
               AT END MOVE 'Y' TO WS-EOF
               NOT AT END DISPLAY MASTER-DATA
           END-READ.
       
       READ-BY-KEY.
           MOVE 12345 TO WS-KEY.
           READ MASTER-FILE
               KEY IS WS-KEY
               INVALID KEY DISPLAY 'Key not found'
               NOT INVALID KEY DISPLAY 'Found: ' MASTER-DATA
           END-READ.
       
       READ-WITH-LOCK.
           READ MASTER-FILE
               WITH LOCK
               KEY IS WS-KEY
               INVALID KEY DISPLAY 'Not found'
           END-READ.
