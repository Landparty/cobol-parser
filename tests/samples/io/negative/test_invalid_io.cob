       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-NEGATIVE-IO.
       
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT BAD-FILE ASSIGN TO EXTERNAL BAD-DAT
               ORGANIZATION IS SEQUENTIAL.
       
       DATA DIVISION.
       FILE SECTION.
       FD  BAD-FILE.
       01  BAD-REC                   PIC X(100).
       
       WORKING-STORAGE SECTION.
       01  WS-KEY                    PIC 9(5).
       
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN INPUT BAD-FILE.
           
           READ BAD-FILE
               WITH LOCK
               INVALID KEY DISPLAY 'Should not have WITH LOCK on sequential'
           END-READ.
           
           DELETE BAD-FILE
               INVALID KEY DISPLAY 'Sequential DELETE with INVALID KEY unsupported'
           END-DELETE.
           
           START BAD-FILE
               KEY IS WS-KEY
               INVALID KEY DISPLAY 'START unsupported on sequential'
           END-START.
           
           CLOSE BAD-FILE.
           STOP RUN.
