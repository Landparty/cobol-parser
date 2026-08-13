       IDENTIFICATION DIVISION.
       PROGRAM-ID. JOBDISP.
      *****************************************************************
      * PROGRAM:   JOBDISP                                            *
      * PURPOSE:   GENERIC BATCH STEP DISPATCHER                     *
      *            READS CONTROL CARDS NAMING A SHARED BANKING        *
      *            UTILITY MODULE AND A FUNCTION CODE, RESOLVES THE   *
      *            MODULE CODE TO A PROGRAM NAME AT RUN TIME, AND     *
      *            DYNAMICALLY CALLS IT WITH A GENERIC PARAMETER      *
      *            BLOCK. LETS OPERATIONS ADD NEW DRIVER STEPS BY     *
      *            SUPPLYING NEW CONTROL CARDS INSTEAD OF NEW JCL.    *
      * INPUT:     DISPCTL - DISPATCH CONTROL CARDS (MODULE CODE,     *
      *            FUNCTION CODE, FREE-FORM INPUT DATA)               *
      * OUTPUT:    DISPRPT - DISPATCH ACTIVITY LOG                    *
      * CALLS:     DATEUTIL, ACCTVAL, INTRATE, CURRFMT (ASM, VIA      *
      *            DYNAMIC CALL - TARGET RESOLVED FROM CONTROL CARD)  *
      * PROC:      COBCOMP (STANDARD COBOL COMPILE/LINK)               *
      * FREQ:      ON DEMAND - SUBMITTED VIA JOBDISPJ.JCL             *
      *****************************************************************

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT DISPCTL  ASSIGN TO DISPCTL
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-DISPCTL-STATUS.
           SELECT DISPRPT  ASSIGN TO DISPRPT
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  DISPCTL
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  DISPCTL-REC.
           05  DC-MODULE-CODE       PIC X(02).
           05  DC-FUNCTION-CODE     PIC X(01).
           05  DC-INPUT-DATA        PIC X(77).

       FD  DISPRPT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  RPT-RECORD               PIC X(100).

       WORKING-STORAGE SECTION.
           COPY WSCOMMON.
           COPY ERRORCD.

       01  WS-DISPCTL-STATUS        PIC X(02).
           88  WS-DISPCTL-OK        VALUE '00'.

       01  WS-CALL-PROGRAM          PIC X(08) VALUE SPACES.

       01  WS-DISPATCH-PARMS.
           05  WS-DP-FUNCTION       PIC X(01).
           05  WS-DP-DATA           PIC X(77).

       01  WS-DISP-COUNTERS.
           05  WS-CARDS-READ        PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-CALLS-MADE        PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-CALLS-REJECTED    PIC 9(05) COMP-3 VALUE ZERO.

       01  WS-LOG-DETAIL.
           05  WS-LOG-MODULE        PIC X(08).
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-LOG-FUNCTION      PIC X(01).
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-LOG-DATA          PIC X(40).
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-LOG-ACTION        PIC X(20).

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-INITIALIZE
           PERFORM 2000-DISPATCH-CONTROL-CARDS
               UNTIL WS-EOF
           PERFORM 3000-FINALIZE
           GOBACK.

       1000-INITIALIZE.
           DISPLAY 'JOBDISP: BATCH STEP DISPATCHER STARTED'
           OPEN INPUT  DISPCTL
           OPEN OUTPUT DISPRPT
           PERFORM 2900-READ-NEXT-CARD.

       2000-DISPATCH-CONTROL-CARDS.
           ADD 1 TO WS-CARDS-READ
           PERFORM 2100-RESOLVE-MODULE-NAME
           IF WS-CALL-PROGRAM NOT = SPACES
               MOVE DC-FUNCTION-CODE TO WS-DP-FUNCTION
               MOVE DC-INPUT-DATA    TO WS-DP-DATA
               CALL WS-CALL-PROGRAM USING WS-DISPATCH-PARMS
               ADD 1 TO WS-CALLS-MADE
               MOVE 'DISPATCHED'    TO WS-LOG-ACTION
           ELSE
               ADD 1 TO WS-CALLS-REJECTED
               MOVE 'REJECTED-BAD-CODE'  TO WS-LOG-ACTION
           END-IF
           PERFORM 2500-WRITE-LOG-DETAIL
           PERFORM 2900-READ-NEXT-CARD.

       2100-RESOLVE-MODULE-NAME.
      *    MODULE CODE -> CALLEE NAME. EVERY BRANCH MOVES A LITERAL
      *    SO A DYNAMIC-CALL VALUE-TRACKING PASS CAN ENUMERATE ALL
      *    FOUR POSSIBLE TARGETS OF THE CALL BELOW.
           EVALUATE DC-MODULE-CODE
               WHEN 'DT'
                   MOVE 'DATEUTIL' TO WS-CALL-PROGRAM
               WHEN 'AV'
                   MOVE 'ACCTVAL ' TO WS-CALL-PROGRAM
               WHEN 'IR'
                   MOVE 'INTRATE ' TO WS-CALL-PROGRAM
               WHEN 'CF'
                   MOVE 'CURRFMT ' TO WS-CALL-PROGRAM
               WHEN OTHER
                   MOVE SPACES     TO WS-CALL-PROGRAM
           END-EVALUATE.

       2500-WRITE-LOG-DETAIL.
           MOVE WS-CALL-PROGRAM     TO WS-LOG-MODULE
           MOVE DC-FUNCTION-CODE    TO WS-LOG-FUNCTION
           MOVE DC-INPUT-DATA(1:40) TO WS-LOG-DATA
           WRITE RPT-RECORD FROM WS-LOG-DETAIL.

       2900-READ-NEXT-CARD.
           READ DISPCTL
               AT END
                   SET WS-EOF TO TRUE
               NOT AT END
                   CONTINUE
           END-READ.

       3000-FINALIZE.
           CLOSE DISPCTL
           CLOSE DISPRPT
           DISPLAY 'JOBDISP: DISPATCHER COMPLETE'
           DISPLAY 'CARDS READ:       ' WS-CARDS-READ
           DISPLAY 'CALLS DISPATCHED: ' WS-CALLS-MADE
           DISPLAY 'CALLS REJECTED:   ' WS-CALLS-REJECTED
           IF WS-CALLS-REJECTED > ZERO
               MOVE 4 TO RETURN-CODE
           ELSE
               MOVE ZERO TO RETURN-CODE
           END-IF.
