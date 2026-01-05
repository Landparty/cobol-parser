      *****************************************************************
      * Real-World COBOL Example: Manufacturing Production System
      * Demonstrates: CALL in loops, complex exception handling
      * Use Case: Production line management and quality control
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PRODUCTION-SCHEDULER.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PRODUCTION-ORDER.
           05  WS-ORDER-NUMBER     PIC X(10).
           05  WS-PRODUCT-CODE     PIC X(8).
           05  WS-PRODUCT-NAME     PIC X(40).
           05  WS-ORDER-QUANTITY   PIC 9(8) COMP-3.
           05  WS-PRIORITY         PIC 9.
           05  WS-DUE-DATE         PIC 9(8).
           05  WS-STATUS           PIC X(2).
               88  SCHEDULED        VALUE '01'.
               88  IN-PROGRESS      VALUE '02'.
               88  QA-CHECK         VALUE '03'.
               88  COMPLETE         VALUE '04'.
               88  FAILED           VALUE '99'.
           
       01  WS-MACHINE-DATA.
           05  WS-MACHINE-ID       PIC X(5).
           05  WS-MACHINE-NAME     PIC X(30).
           05  WS-STATION-NUMBER   PIC 99.
           05  WS-AVAILABILITY     PIC X VALUE 'N'.
           05  WS-UTILIZATION      PIC 999V9 COMP-3.
           
       01  WS-BATCH-PROCESSING.
           05  WS-BATCH-ID         PIC X(8).
           05  WS-BATCH-SIZE       PIC 9(6) COMP-3.
           05  WS-UNITS-PRODUCED   PIC 9(6) COMP-3.
           05  WS-UNITS-REJECTED   PIC 9(6) COMP-3.
           05  WS-DEFECT-RATE      PIC 9V9(3).
           05  WS-QUALITY-SCORE    PIC 9(3).
           
       01  WS-MATERIAL-TRACKING.
           05  WS-MATERIAL-ID      PIC X(8).
           05  WS-MATERIAL-NAME    PIC X(30).
           05  WS-QUANTITY-USED    PIC 9(8)V99 COMP-3.
           05  WS-UNIT-COST        PIC 9(6)V99 COMP-3.
           05  WS-MATERIAL-COST    PIC 9(10)V99 COMP-3.
           05  WS-VARIANCE         PIC S9(8)V99 COMP-3.
           
       01  WS-PROCESSING-COUNTERS.
           05  WS-STATION-IDX      PIC 99 COMP.
           05  WS-STATION-COUNT    PIC 99 VALUE 5.
           05  WS-BATCH-IDX        PIC 9(4) COMP.
           05  WS-BATCH-COUNT      PIC 9(4) COMP.
           05  WS-ERROR-COUNT      PIC 999 VALUE 0.
           
       01  WS-RESULTS.
           05  WS-TOTAL-UNITS      PIC 9(8) COMP-3.
           05  WS-TOTAL-COST       PIC 9(12)V99 COMP-3.
           05  WS-PRODUCTION-TIME  PIC 9(5) COMP-3.
           05  WS-OVERALL-QUALITY  PIC 9(3).
           
       01  WS-SERVICE-CATALOG.
           05  WS-SCHEDULER-SVC    PIC X(20) VALUE 'SCHEDULE-ORDER'.
           05  WS-MACHINE-ALLOC    PIC X(20) VALUE 'ALLOCATE-MACHINE'.
           05  WS-MATERIAL-REQ     PIC X(20) VALUE 'REQUEST-MATERIAL'.
           05  WS-PRODUCTION-RUN   PIC X(20) VALUE 'RUN-PRODUCTION'.
           05  WS-QA-INSPECTION    PIC X(20) VALUE 'INSPECT-QUALITY'.
           05  WS-REJECT-HANDLER   PIC X(20) VALUE 'PROCESS-REJECTS'.
           05  WS-COST-CALCULATOR  PIC X(20) VALUE 'CALC-PRODUCTION'.
           05  WS-REPORTING-SVC    PIC X(20) VALUE 'REPORT-PRODUCTION'.
           
       01  WS-CONTROL-FLAGS.
           05  WS-MATERIAL-OK      PIC X VALUE 'N'.
           05  WS-MACHINE-OK       PIC X VALUE 'N'.
           05  WS-QUALITY-OK       PIC X VALUE 'N'.
           05  WS-COST-OK          PIC X VALUE 'N'.
           
       PROCEDURE DIVISION.
       MAIN-PRODUCTION-CONTROL.
           DISPLAY 'Production Scheduler Started'
           PERFORM LOAD-PRODUCTION-DATA
           PERFORM SCHEDULE-PRODUCTION-RUN
           PERFORM ALLOCATE-RESOURCES
           PERFORM EXECUTE-PRODUCTION-BATCH
           PERFORM QUALITY-ASSURANCE
           PERFORM GENERATE-PRODUCTION-REPORT
           DISPLAY 'Production Scheduling Complete'
           STOP RUN.
           
       LOAD-PRODUCTION-DATA.
           MOVE 'ORD-2024-050' TO WS-ORDER-NUMBER
           MOVE 'PROD-2501' TO WS-PRODUCT-CODE
           MOVE 'Electronic Widget Assembly' TO WS-PRODUCT-NAME
           MOVE 10000 TO WS-ORDER-QUANTITY
           MOVE 1 TO WS-PRIORITY
           MOVE 20240125 TO WS-DUE-DATE
           MOVE '01' TO WS-STATUS
           MOVE 10 TO WS-BATCH-COUNT.
           
       SCHEDULE-PRODUCTION-RUN.
           DISPLAY 'Scheduling production run...'
           
      *    CALL scheduling service
           CALL WS-SCHEDULER-SVC USING BY REFERENCE WS-ORDER-NUMBER
                                             WS-PRODUCT-CODE
                                             WS-ORDER-QUANTITY
                                             WS-PRIORITY
                                             WS-DUE-DATE
                                        BY REFERENCE WS-STATUS
                   ON EXCEPTION
                       MOVE 'Y' TO WS-CONTROL-FLAGS(1:1)
                       DISPLAY 'Scheduling failed'
                   NOT ON EXCEPTION
                       MOVE '02' TO WS-STATUS.
           
       ALLOCATE-RESOURCES.
           DISPLAY 'Allocating resources...'
           
      *    CALL to allocate machines for each station
           PERFORM VARYING WS-STATION-IDX FROM 1 BY 1
               UNTIL WS-STATION-IDX > WS-STATION-COUNT
               
               CALL WS-MACHINE-ALLOC USING BY REFERENCE WS-ORDER-NUMBER
                                              WS-STATION-IDX
                                         BY REFERENCE WS-MACHINE-ID
                                                       WS-MACHINE-NAME
                                                       WS-AVAILABILITY
                   ON EXCEPTION
                       ADD 1 TO WS-ERROR-COUNT
                       DISPLAY 'Machine allocation failed at station '
                               WS-STATION-IDX
                   NOT ON EXCEPTION
                       IF WS-AVAILABILITY = 'Y'
                           DISPLAY 'Machine allocated: ' WS-MACHINE-NAME
                       END-IF
           END-PERFORM
           
      *    CALL to request required materials
           CALL WS-MATERIAL-REQ USING BY REFERENCE WS-ORDER-NUMBER
                                          WS-PRODUCT-CODE
                                          WS-ORDER-QUANTITY
                                     BY REFERENCE WS-MATERIAL-ID
                                                   WS-MATERIAL-NAME
                                                   WS-QUANTITY-USED
                                                   WS-MATERIAL-COST
                   RETURNING WS-MATERIAL-OK
                   ON EXCEPTION
                       DISPLAY 'Material request failed'
                       MOVE 'N' TO WS-MATERIAL-OK.
           
       EXECUTE-PRODUCTION-BATCH.
           DISPLAY 'Executing production batch...'
           
      *    CALL production run for each batch
           PERFORM VARYING WS-BATCH-IDX FROM 1 BY 1
               UNTIL WS-BATCH-IDX > WS-BATCH-COUNT
               
      *        Calculate batch size
               MOVE 1000 TO WS-BATCH-SIZE
               
      *        CALL production execution service
               CALL WS-PRODUCTION-RUN USING BY REFERENCE WS-ORDER-NUMBER
                                              WS-BATCH-IDX
                                              WS-BATCH-SIZE
                                              WS-MACHINE-ID
                                         BY REFERENCE WS-UNITS-PRODUCED
                                                       WS-UNITS-REJECTED
                   RETURNING WS-BATCH-ID
                   ON EXCEPTION
                       ADD 1 TO WS-ERROR-COUNT
                       DISPLAY 'Production run failed for batch '
                               WS-BATCH-IDX
                   NOT ON EXCEPTION
                       ADD WS-UNITS-PRODUCED TO WS-TOTAL-UNITS
                       CALCULATE WS-DEFECT-RATE = 
                           WS-UNITS-REJECTED / WS-BATCH-SIZE
           END-PERFORM.
           
       QUALITY-ASSURANCE.
           DISPLAY 'Performing quality assurance...'
           
      *    CALL quality inspection service
           CALL WS-QA-INSPECTION USING BY REFERENCE WS-ORDER-NUMBER
                                             WS-TOTAL-UNITS
                                             WS-UNITS-REJECTED
                                        BY REFERENCE WS-QUALITY-SCORE
                                                      WS-QUALITY-OK
                   ON EXCEPTION
                       DISPLAY 'QA inspection failed'
                       MOVE 'N' TO WS-QUALITY-OK.
           
           IF WS-UNITS-REJECTED > 0
      *        CALL reject processing service
               CALL WS-REJECT-HANDLER USING BY REFERENCE WS-ORDER-NUMBER
                                              WS-UNITS-REJECTED
                                              WS-DEFECT-RATE
                   ON EXCEPTION
                       DISPLAY 'Reject handling failed'
           END-IF.
           
       GENERATE-PRODUCTION-REPORT.
           DISPLAY 'Generating production report...'
           
      *    CALL cost calculator service
           CALL WS-COST-CALCULATOR USING BY REFERENCE WS-ORDER-NUMBER
                                              WS-TOTAL-UNITS
                                              WS-MATERIAL-COST
                                              WS-PRODUCTION-TIME
                                         BY REFERENCE WS-TOTAL-COST
                                                       WS-COST-OK
                   RETURNING WS-TOTAL-COST
                   ON EXCEPTION
                       DISPLAY 'Cost calculation failed'.
           
      *    CALL reporting service
           CALL WS-REPORTING-SVC USING BY REFERENCE WS-ORDER-NUMBER
                                             WS-TOTAL-UNITS
                                             WS-UNITS-REJECTED
                                             WS-TOTAL-COST
                                             WS-QUALITY-SCORE
                   ON EXCEPTION
                       DISPLAY 'Report generation failed'
                   NOT ON EXCEPTION
                       DISPLAY 'Report generated successfully'.
           
       END PROGRAM PRODUCTION-SCHEDULER.
