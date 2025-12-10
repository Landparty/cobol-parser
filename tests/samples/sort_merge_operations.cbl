      *****************************************************************
      * SORT and MERGE Operations
      * Tests: SORT, MERGE, INPUT/OUTPUT PROCEDURE, SD, RELEASE, RETURN
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SORTMERGE.
       
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INPUT-FILE ASSIGN TO 'INPUT.DAT'
               ORGANIZATION IS SEQUENTIAL.
               
           SELECT OUTPUT-FILE ASSIGN TO 'OUTPUT.DAT'
               ORGANIZATION IS SEQUENTIAL.
               
           SELECT SORT-FILE ASSIGN TO 'SORTWRK'
               ORGANIZATION IS SEQUENTIAL.
               
           SELECT MERGE-FILE ASSIGN TO 'MERGEWRK'
               ORGANIZATION IS SEQUENTIAL.
               
           SELECT MERGE-INPUT-1 ASSIGN TO 'MERGE1.DAT'
               ORGANIZATION IS SEQUENTIAL.
               
           SELECT MERGE-INPUT-2 ASSIGN TO 'MERGE2.DAT'
               ORGANIZATION IS SEQUENTIAL.
               
       DATA DIVISION.
       FILE SECTION.
       FD  INPUT-FILE.
       01  INPUT-RECORD.
           05  IN-KEY-1            PIC X(10).
           05  IN-KEY-2            PIC 9(5).
           05  IN-DATA             PIC X(50).
           
       FD  OUTPUT-FILE.
       01  OUTPUT-RECORD.
           05  OUT-KEY-1           PIC X(10).
           05  OUT-KEY-2           PIC 9(5).
           05  OUT-DATA            PIC X(50).
           
       SD  SORT-FILE.
       01  SORT-RECORD.
           05  SORT-KEY-1          PIC X(10).
           05  SORT-KEY-2          PIC 9(5).
           05  SORT-DATA           PIC X(50).
           
       SD  MERGE-FILE.
       01  MERGE-RECORD.
           05  MERGE-KEY           PIC X(10).
           05  MERGE-DATA          PIC X(60).
           
       FD  MERGE-INPUT-1.
       01  MERGE-IN-1.
           05  M1-KEY              PIC X(10).
           05  M1-DATA             PIC X(60).
           
       FD  MERGE-INPUT-2.
       01  MERGE-IN-2.
           05  M2-KEY              PIC X(10).
           05  M2-DATA             PIC X(60).
           
       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG             PIC X VALUE 'N'.
           88  EOF-REACHED         VALUE 'Y'.
           
       01  WS-RECORD-COUNT         PIC 9(7) VALUE ZERO.
       01  WS-TEMP-RECORD          PIC X(65).
       
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM SIMPLE-SORT
           PERFORM SORT-WITH-PROCEDURES
           PERFORM MULTIPLE-KEY-SORT
           PERFORM MERGE-OPERATION
           STOP RUN.
           
       SIMPLE-SORT.
      *    Basic SORT - USING GIVING
           SORT SORT-FILE
               ON ASCENDING KEY SORT-KEY-1
               USING INPUT-FILE
               GIVING OUTPUT-FILE
               
           DISPLAY 'Simple sort completed'.
           
       SORT-WITH-PROCEDURES.
      *    SORT with INPUT and OUTPUT PROCEDURE
           SORT SORT-FILE
               ON ASCENDING KEY SORT-KEY-1
               ON DESCENDING KEY SORT-KEY-2
               INPUT PROCEDURE IS SORT-INPUT-PROC
               OUTPUT PROCEDURE IS SORT-OUTPUT-PROC
               
           DISPLAY 'Sort with procedures completed'.
           
       MULTIPLE-KEY-SORT.
      *    SORT with multiple keys and COLLATING SEQUENCE
           SORT SORT-FILE
               ON ASCENDING KEY SORT-KEY-1
               ON ASCENDING KEY SORT-KEY-2
               COLLATING SEQUENCE IS ASCII
               USING INPUT-FILE
               GIVING OUTPUT-FILE
               
           DISPLAY 'Multiple key sort completed'.
           
       SORT-INPUT-PROC SECTION.
       SIP-000.
           OPEN INPUT INPUT-FILE
           MOVE 'N' TO WS-EOF-FLAG
           PERFORM UNTIL EOF-REACHED
               READ INPUT-FILE
                   AT END
                       SET EOF-REACHED TO TRUE
                   NOT AT END
                       PERFORM FILTER-AND-RELEASE
               END-READ
           END-PERFORM
           CLOSE INPUT-FILE
           GO TO SIP-EXIT.
           
       FILTER-AND-RELEASE.
      *    Filter records before sorting
           IF IN-KEY-2 > 1000
               MOVE INPUT-RECORD TO SORT-RECORD
               ADD 1 TO WS-RECORD-COUNT
               RELEASE SORT-RECORD
           END-IF.
           
       SIP-EXIT.
           EXIT.
           
       SORT-OUTPUT-PROC SECTION.
       SOP-000.
           OPEN OUTPUT OUTPUT-FILE
           PERFORM RETURN-SORTED-RECORDS
           CLOSE OUTPUT-FILE
           GO TO SOP-EXIT.
           
       RETURN-SORTED-RECORDS.
      *    RETURN sorted records and write to output
           RETURN SORT-FILE
               AT END
                   DISPLAY 'All records returned'
               NOT AT END
                   PERFORM PROCESS-SORTED-RECORD
                   PERFORM RETURN-SORTED-RECORDS
           END-RETURN.
           
       PROCESS-SORTED-RECORD.
      *    Process each sorted record
           MOVE SORT-RECORD TO OUTPUT-RECORD
           WRITE OUTPUT-RECORD
           DISPLAY 'Wrote: ' OUT-KEY-1 ' - ' OUT-KEY-2.
           
       SOP-EXIT.
           EXIT.
           
       MERGE-OPERATION.
      *    MERGE multiple sorted files
           MERGE MERGE-FILE
               ON ASCENDING KEY MERGE-KEY
               USING MERGE-INPUT-1
                     MERGE-INPUT-2
               GIVING OUTPUT-FILE
               
           DISPLAY 'Merge completed'.
           
      *    MERGE with OUTPUT PROCEDURE
           MERGE MERGE-FILE
               ON ASCENDING KEY MERGE-KEY
               USING MERGE-INPUT-1
                     MERGE-INPUT-2
               OUTPUT PROCEDURE IS MERGE-OUTPUT-PROC
               
           DISPLAY 'Merge with procedure completed'.
           
       MERGE-OUTPUT-PROC SECTION.
       MOP-000.
           OPEN OUTPUT OUTPUT-FILE
           PERFORM RETURN-MERGED-RECORDS
           CLOSE OUTPUT-FILE
           GO TO MOP-EXIT.
           
       RETURN-MERGED-RECORDS.
           RETURN MERGE-FILE
               AT END
                   DISPLAY 'All merged records returned'
               NOT AT END
                   MOVE MERGE-RECORD TO OUTPUT-RECORD
                   WRITE OUTPUT-RECORD
                   PERFORM RETURN-MERGED-RECORDS
           END-RETURN.
           
       MOP-EXIT.
           EXIT.
