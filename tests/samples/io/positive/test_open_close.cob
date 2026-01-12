       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-OPEN-CLOSE.
       
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MASTER-FILE ASSIGN TO EXTERNAL MASTER-DAT
               ORGANIZATION IS SEQUENTIAL.
           SELECT INDEX-FILE ASSIGN TO EXTERNAL INDEX-DAT
               ORGANIZATION IS INDEXED.
           SELECT REL-FILE ASSIGN TO EXTERNAL REL-DAT
               ORGANIZATION IS RELATIVE.
       
       DATA DIVISION.
       FILE SECTION.
       FD  MASTER-FILE.
       01  MASTER-REC                PIC X(100).
       
       FD  INDEX-FILE.
       01  INDEX-REC                 PIC X(100).
       
       FD  REL-FILE.
       01  REL-REC                   PIC X(100).
       
       WORKING-STORAGE SECTION.
       01  WS-EOF                    PIC X VALUE 'N'.
       01  WS-REC-KEY                PIC 9(5) COMP.
       
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN INPUT MASTER-FILE.
           OPEN OUTPUT INDEX-FILE.
           OPEN I-O REL-FILE.
           
           PERFORM UNTIL WS-EOF = 'Y'
               READ MASTER-FILE
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END WRITE INDEX-REC FROM MASTER-REC
               END-READ
           END-PERFORM.
           
           CLOSE MASTER-FILE.
           CLOSE INDEX-FILE.
           CLOSE REL-FILE.
           
           STOP RUN.
