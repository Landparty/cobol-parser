       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-FD-BINDING.
       
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INDEXED-MASTER ASSIGN TO EXTERNAL MASTER-IDX
               ORGANIZATION IS INDEXED
               RECORD KEY IS MASTER-PRIMARY-KEY
               ALTERNATE RECORD KEY IS MASTER-ALT-KEY WITH DUPLICATES.
           
           SELECT RELATIVE-FILE ASSIGN TO EXTERNAL REL-DATA
               ORGANIZATION IS RELATIVE.
       
       DATA DIVISION.
       FILE SECTION.
       FD  INDEXED-MASTER
           RECORD VARYING IN SIZE FROM 100 TO 500 CHARACTERS
           BLOCK CONTAINS 5 RECORDS.
       01  MASTER-REC.
           05  MASTER-PRIMARY-KEY    PIC 9(8).
           05  MASTER-ALT-KEY        PIC 9(4).
           05  MASTER-DATA           PIC X(88).
       
       FD  RELATIVE-FILE
           RECORD VARYING IN SIZE FROM 50 TO 250 CHARACTERS
           BLOCK CONTAINS 10 RECORDS.
       01  RELATIVE-REC.
           05  REL-KEY               PIC 9(5) COMP.
           05  REL-DATA              PIC X(45).
       
       WORKING-STORAGE SECTION.
       01  WS-PRIMARY-KEY            PIC 9(8).
       01  WS-ALT-KEY                PIC 9(4).
       01  WS-REL-KEY                PIC 9(5) COMP.
       01  WS-EOF                    PIC X VALUE 'N'.
       
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN INPUT INDEXED-MASTER.
           OPEN I-O RELATIVE-FILE.
           
           PERFORM ACCESS-BY-PRIMARY-KEY.
           PERFORM ACCESS-BY-ALT-KEY.
           PERFORM ACCESS-RELATIVE-FILE.
           
           CLOSE INDEXED-MASTER.
           CLOSE RELATIVE-FILE.
           STOP RUN.
       
       ACCESS-BY-PRIMARY-KEY.
           MOVE 12345678 TO WS-PRIMARY-KEY.
           READ INDEXED-MASTER
               KEY IS WS-PRIMARY-KEY
               INVALID KEY 
                   DISPLAY 'Primary key not found'
               NOT INVALID KEY 
                   DISPLAY 'Found: ' MASTER-DATA
           END-READ.
       
       ACCESS-BY-ALT-KEY.
           MOVE 9999 TO WS-ALT-KEY.
           READ INDEXED-MASTER
               KEY IS WS-ALT-KEY
               INVALID KEY DISPLAY 'Alt key not found'
           END-READ.
       
       ACCESS-RELATIVE-FILE.
           MOVE 1 TO WS-REL-KEY.
           READ RELATIVE-FILE
               KEY IS WS-REL-KEY
               INVALID KEY DISPLAY 'Relative record not found'
               NOT INVALID KEY
                   REWRITE RELATIVE-REC
                       INVALID KEY DISPLAY 'Rewrite failed'
                   END-REWRITE
           END-READ.
           
           DELETE RELATIVE-FILE
               INVALID KEY DISPLAY 'Delete failed'
           END-DELETE.
