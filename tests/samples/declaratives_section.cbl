      *****************************************************************
      * DECLARATIVES Section
      * Tests: USE AFTER ERROR, USE BEFORE REPORTING, Exception handling
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DECLTEST.
       
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INPUT-FILE ASSIGN TO 'INPUT.DAT'
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-FILE-STATUS.
               
           SELECT OUTPUT-FILE ASSIGN TO 'OUTPUT.DAT'
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS OUT-KEY
               FILE STATUS IS WS-OUT-STATUS.
               
           SELECT MASTER-FILE ASSIGN TO 'MASTER.DAT'
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-MASTER-STATUS.
               
       DATA DIVISION.
       FILE SECTION.
       FD  INPUT-FILE.
       01  INPUT-RECORD            PIC X(80).
       
       FD  OUTPUT-FILE.
       01  OUTPUT-RECORD.
           05  OUT-KEY             PIC X(10).
           05  OUT-DATA            PIC X(70).
           
       FD  MASTER-FILE.
       01  MASTER-RECORD           PIC X(100).
       
       WORKING-STORAGE SECTION.
       01  WS-FILE-STATUS          PIC XX.
       01  WS-OUT-STATUS           PIC XX.
       01  WS-MASTER-STATUS        PIC XX.
       
       01  WS-ERROR-COUNT          PIC 9(5) VALUE ZERO.
       01  WS-RECORD-COUNT         PIC 9(7) VALUE ZERO.
       01  WS-EOF-FLAG             PIC X VALUE 'N'.
           88  EOF-REACHED         VALUE 'Y'.
           
       PROCEDURE DIVISION.
       
       DECLARATIVES.
       
      *    Error handler for INPUT-FILE
       INPUT-ERROR SECTION.
           USE AFTER ERROR PROCEDURE ON INPUT-FILE.
       INPUT-ERROR-PARA.
           ADD 1 TO WS-ERROR-COUNT
           DISPLAY 'Error on INPUT-FILE'
           DISPLAY 'File Status: ' WS-FILE-STATUS
           EVALUATE WS-FILE-STATUS
               WHEN '10'
                   DISPLAY 'End of file reached'
               WHEN '23'
                   DISPLAY 'Record not found'
               WHEN '30'
                   DISPLAY 'Permanent I/O error'
               WHEN '35'
                   DISPLAY 'File not found'
               WHEN '39'
                   DISPLAY 'File attributes conflict'
               WHEN '47'
                   DISPLAY 'READ after successful READ NEXT'
               WHEN OTHER
                   DISPLAY 'Other error: ' WS-FILE-STATUS
           END-EVALUATE
           IF WS-ERROR-COUNT > 100
               DISPLAY 'Too many errors, terminating'
               STOP RUN
           END-IF.
           
      *    Error handler for OUTPUT-FILE
       OUTPUT-ERROR SECTION.
           USE AFTER ERROR PROCEDURE ON OUTPUT-FILE.
       OUTPUT-ERROR-PARA.
           DISPLAY 'Error on OUTPUT-FILE'
           DISPLAY 'File Status: ' WS-OUT-STATUS
           EVALUATE WS-OUT-STATUS
               WHEN '21'
                   DISPLAY 'Invalid key - sequence error'
               WHEN '22'
                   DISPLAY 'Duplicate key'
               WHEN '24'
                   DISPLAY 'Boundary violation'
               WHEN '30'
                   DISPLAY 'Permanent I/O error'
               WHEN '34'
                   DISPLAY 'Boundary violation on sequential write'
               WHEN '37'
                   DISPLAY 'File not open for I/O operation'
               WHEN '38'
                   DISPLAY 'File closed with lock'
               WHEN '41'
                   DISPLAY 'File already open'
               WHEN '42'
                   DISPLAY 'File not open'
               WHEN OTHER
                   DISPLAY 'Other error: ' WS-OUT-STATUS
           END-EVALUATE.
           
      *    General error handler for all other files
       GENERAL-ERROR SECTION.
           USE AFTER ERROR PROCEDURE ON MASTER-FILE.
       GENERAL-ERROR-PARA.
           DISPLAY 'Error on MASTER-FILE'
           DISPLAY 'File Status: ' WS-MASTER-STATUS
           ADD 1 TO WS-ERROR-COUNT.
           
      *    USE for all I/O files (alternative approach)
       ALL-FILES-ERROR SECTION.
           USE AFTER STANDARD ERROR PROCEDURE ON INPUT.
       ALL-FILES-ERROR-PARA.
           DISPLAY 'Standard error handler invoked'
           DISPLAY 'Error count: ' WS-ERROR-COUNT
           IF WS-ERROR-COUNT > 50
               DISPLAY 'Critical error threshold reached'
           END-IF.
           
       END DECLARATIVES.
       
      *    Main procedure division starts here
       MAIN-LOGIC SECTION.
       000-MAIN.
           PERFORM OPEN-FILES
           PERFORM PROCESS-FILES
           PERFORM CLOSE-FILES
           DISPLAY 'Processing completed'
           DISPLAY 'Total records: ' WS-RECORD-COUNT
           DISPLAY 'Total errors: ' WS-ERROR-COUNT
           STOP RUN.
           
       OPEN-FILES.
           OPEN INPUT INPUT-FILE
           OPEN I-O OUTPUT-FILE
           OPEN INPUT MASTER-FILE
           DISPLAY 'Files opened'
           DISPLAY 'INPUT-FILE status: ' WS-FILE-STATUS
           DISPLAY 'OUTPUT-FILE status: ' WS-OUT-STATUS
           DISPLAY 'MASTER-FILE status: ' WS-MASTER-STATUS.
           
       PROCESS-FILES.
           MOVE 'N' TO WS-EOF-FLAG
           PERFORM UNTIL EOF-REACHED
               READ INPUT-FILE
                   AT END
                       SET EOF-REACHED TO TRUE
                   NOT AT END
                       PERFORM PROCESS-RECORD
               END-READ
           END-PERFORM.
           
       PROCESS-RECORD.
           ADD 1 TO WS-RECORD-COUNT
           MOVE INPUT-RECORD TO OUTPUT-RECORD
           
      *    This WRITE may trigger OUTPUT-ERROR declarative
           WRITE OUTPUT-RECORD
               INVALID KEY
                   DISPLAY 'Invalid key in WRITE'
               NOT INVALID KEY
                   DISPLAY 'Record written successfully'
           END-WRITE
           
      *    Attempt to read from master file
           READ MASTER-FILE
               AT END
                   DISPLAY 'Master file EOF'
               NOT AT END
                   DISPLAY 'Master record read'
           END-READ.
           
       CLOSE-FILES.
           CLOSE INPUT-FILE
           CLOSE OUTPUT-FILE
           CLOSE MASTER-FILE
           DISPLAY 'All files closed'.
