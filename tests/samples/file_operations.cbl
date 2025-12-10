      *****************************************************************
      * File Operations - All Variants
      * Tests: Sequential, indexed, relative, line sequential
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILETEST.
       
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
      *    Sequential file with all clauses
           SELECT SEQ-FILE
               ASSIGN TO 'SEQFILE.DAT'
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-SEQ-STATUS
               RESERVE 3 AREAS
               LOCK MODE IS MANUAL WITH LOCK ON RECORD
               SHARING WITH ALL OTHER.
               
      *    Indexed file with multiple keys
           SELECT IDX-FILE
               ASSIGN TO EXTERNAL IDX-FILE-NAME
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS IDX-RECORD-KEY
               ALTERNATE RECORD KEY IS IDX-ALT-KEY-1 
                   WITH DUPLICATES
               ALTERNATE RECORD KEY IS IDX-ALT-KEY-2
               RELATIVE KEY IS WS-REL-KEY
               FILE STATUS IS WS-IDX-STATUS
               LOCK MODE IS AUTOMATIC WITH LOCK ON MULTIPLE RECORDS
               RESERVE 5 AREAS.
               
      *    Relative file
           SELECT REL-FILE
               ASSIGN TO 'RELFILE.DAT'
               ORGANIZATION IS RELATIVE
               ACCESS MODE IS RANDOM
               RELATIVE KEY IS WS-REL-REC-NUM
               FILE STATUS IS WS-REL-STATUS
               SHARING WITH NO OTHER
               LOCK MODE IS EXCLUSIVE.
               
      *    Line Sequential (text file)
           SELECT LINE-SEQ-FILE
               ASSIGN TO 'TEXTFILE.TXT'
               ORGANIZATION IS LINE SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-LINE-STATUS.
               
      *    Optional file
           SELECT OPT-FILE
               ASSIGN TO 'OPTFILE.DAT'
               OPTIONAL
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-OPT-STATUS.
               
       DATA DIVISION.
       FILE SECTION.
      *    Sequential file descriptor with all clauses
       FD  SEQ-FILE
           EXTERNAL
           GLOBAL
           BLOCK CONTAINS 0 RECORDS
           RECORD CONTAINS 100 CHARACTERS
           LABEL RECORDS ARE STANDARD
           VALUE OF FILE-ID IS 'SEQFILE'
           DATA RECORDS ARE SEQ-RECORD SEQ-ALTERNATE
           LINAGE IS 60 LINES
               WITH FOOTING AT 55
               LINES AT TOP 5
               LINES AT BOTTOM 5
           CODE-SET IS ASCII
           RECORDING MODE IS F.
           
       01  SEQ-RECORD              PIC X(100).
       01  SEQ-ALTERNATE           PIC X(100).
       
      *    Indexed file descriptor
       FD  IDX-FILE
           BLOCK CONTAINS 10 TO 50 RECORDS
           RECORD IS VARYING IN SIZE FROM 50 TO 200 CHARACTERS
               DEPENDING ON WS-IDX-REC-SIZE
           LABEL RECORDS ARE STANDARD
           DATA RECORD IS IDX-RECORD.
           
       01  IDX-RECORD.
           05  IDX-RECORD-KEY      PIC X(10).
           05  IDX-ALT-KEY-1       PIC X(5).
           05  IDX-ALT-KEY-2       PIC 9(8).
           05  IDX-DATA            PIC X(177).
           
      *    Relative file descriptor
       FD  REL-FILE
           RECORD CONTAINS 80 CHARACTERS
           LABEL RECORDS ARE OMITTED.
           
       01  REL-RECORD              PIC X(80).
       
      *    Line Sequential descriptor
       FD  LINE-SEQ-FILE
           RECORD CONTAINS 120 CHARACTERS.
           
       01  LINE-SEQ-RECORD         PIC X(120).
       
      *    Sort description
       SD  SORT-FILE
           RECORD CONTAINS 50 CHARACTERS.
           
       01  SORT-RECORD.
           05  SORT-KEY            PIC X(10).
           05  SORT-DATA           PIC X(40).
           
       WORKING-STORAGE SECTION.
       01  WS-FILE-STATUSES.
           05  WS-SEQ-STATUS       PIC XX.
           05  WS-IDX-STATUS       PIC XX.
           05  WS-REL-STATUS       PIC XX.
           05  WS-LINE-STATUS      PIC XX.
           05  WS-OPT-STATUS       PIC XX.
           
       01  WS-FILE-CONTROLS.
           05  WS-REL-KEY          PIC 9(5).
           05  WS-REL-REC-NUM      PIC 9(6).
           05  WS-IDX-REC-SIZE     PIC 999.
           05  IDX-FILE-NAME       PIC X(30) VALUE 'IDXFILE.DAT'.
           
       01  WS-END-OF-FILE-FLAG     PIC X VALUE 'N'.
           88  END-OF-FILE         VALUE 'Y'.
           
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'File Operations Test'
           PERFORM SEQUENTIAL-OPS
           PERFORM INDEXED-OPS
           PERFORM RELATIVE-OPS
           STOP RUN.
           
       SEQUENTIAL-OPS.
      *    Open files
           OPEN INPUT SEQ-FILE
           IF WS-SEQ-STATUS NOT = '00'
               DISPLAY 'Error opening SEQ-FILE: ' WS-SEQ-STATUS
               STOP RUN
           END-IF
           
      *    Read sequential
           READ SEQ-FILE
               AT END SET END-OF-FILE TO TRUE
               NOT AT END DISPLAY 'Record: ' SEQ-RECORD
           END-READ
           
           CLOSE SEQ-FILE
           
      *    Write sequential
           OPEN OUTPUT SEQ-FILE
           MOVE 'Test Record' TO SEQ-RECORD
           WRITE SEQ-RECORD
           CLOSE SEQ-FILE.
           
       INDEXED-OPS.
           OPEN I-O IDX-FILE
           
      *    Random read
           MOVE 'KEY0000001' TO IDX-RECORD-KEY
           READ IDX-FILE KEY IS IDX-RECORD-KEY
               INVALID KEY DISPLAY 'Key not found'
               NOT INVALID KEY DISPLAY 'Record found: ' IDX-DATA
           END-READ
           
      *    Start/Read Next
           MOVE 'KEY' TO IDX-RECORD-KEY
           START IDX-FILE KEY >= IDX-RECORD-KEY
               INVALID KEY DISPLAY 'No records found'
           END-START
           
           READ IDX-FILE NEXT RECORD
               AT END DISPLAY 'End of file'
           END-READ
           
      *    Rewrite
           REWRITE IDX-RECORD
               INVALID KEY DISPLAY 'Rewrite failed'
           END-REWRITE
           
      *    Delete
           DELETE IDX-FILE RECORD
               INVALID KEY DISPLAY 'Delete failed'
           END-DELETE
           
           CLOSE IDX-FILE.
           
       RELATIVE-OPS.
           OPEN I-O REL-FILE
           
      *    Write relative by key
           MOVE 100 TO WS-REL-REC-NUM
           MOVE 'Record 100' TO REL-RECORD
           WRITE REL-RECORD
               INVALID KEY DISPLAY 'Write failed'
           END-WRITE
           
      *    Read relative by key
           MOVE 100 TO WS-REL-REC-NUM
           READ REL-FILE
               INVALID KEY DISPLAY 'Read failed'
               NOT INVALID KEY DISPLAY 'Relative: ' REL-RECORD
           END-READ
           
           CLOSE REL-FILE.
