       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-WRITE-DISPLAY.
       
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUTPUT-FILE ASSIGN TO EXTERNAL OUTPUT-DAT
               ORGANIZATION IS SEQUENTIAL.
       
       DATA DIVISION.
       FILE SECTION.
       FD  OUTPUT-FILE
           RECORD VARYING IN SIZE FROM 50 TO 100 CHARACTERS.
       01  OUTPUT-REC                PIC X(100).
       
       WORKING-STORAGE SECTION.
       01  WS-MESSAGE                PIC X(50).
       01  WS-COUNTER                PIC 9(3) VALUE ZERO.
       01  WS-PAGE                   PIC 9(2) VALUE ZERO.
       
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN OUTPUT OUTPUT-FILE.
           
           PERFORM WRITE-RECORDS.
           PERFORM WRITE-WITH-ADVANCING.
           PERFORM DISPLAY-STATEMENTS.
           
           CLOSE OUTPUT-FILE.
           STOP RUN.
       
       WRITE-RECORDS.
           MOVE 'Hello World' TO OUTPUT-REC.
           WRITE OUTPUT-REC
               INVALID KEY DISPLAY 'Write error'
           END-WRITE.
       
       WRITE-WITH-ADVANCING.
           MOVE 'Data Line' TO OUTPUT-REC.
           WRITE OUTPUT-REC
               AFTER ADVANCING 1 LINE
               INVALID KEY DISPLAY 'Write with advance failed'
           END-WRITE.
           
           WRITE OUTPUT-REC
               BEFORE ADVANCING PAGE
               AT END-OF-PAGE 
                   ADD 1 TO WS-PAGE
                   DISPLAY 'Page ' WS-PAGE
           END-WRITE.
       
       DISPLAY-STATEMENTS.
           DISPLAY 'Starting display tests'.
           DISPLAY 'Message: ' UPON CONSOLE NO ADVANCING.
           DISPLAY 'Line continued' WITH NO ADVANCING.
           DISPLAY 'Final line'.
