       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDEDIT.
      * NIGHTLY ORDER EDIT: VALIDATE, PRICE AND ROUTE DAILY ORDERS
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ORDER-IN  ASSIGN TO ORDIN
               FILE STATUS IS WS-IN-STAT.
           SELECT ORDER-OK  ASSIGN TO ORDGOOD
               FILE STATUS IS WS-OK-STAT.
           SELECT ORDER-BAD ASSIGN TO ORDREJ
               FILE STATUS IS WS-BAD-STAT.
       DATA DIVISION.
       FILE SECTION.
       FD  ORDER-IN
           RECORDING MODE IS F.
           COPY ORDREC.
       FD  ORDER-OK
           RECORDING MODE IS F.
       01  OK-REC                    PIC X(120).
       FD  ORDER-BAD
           RECORDING MODE IS F.
       01  BAD-REC.
           05  BAD-ORD-ID            PIC X(10).
           05  BAD-REASON            PIC X(30).
           05  FILLER                PIC X(80).
       WORKING-STORAGE SECTION.
       01  WS-IN-STAT                PIC XX.
       01  WS-OK-STAT                PIC XX.
       01  WS-BAD-STAT               PIC XX.
       01  WS-EOF-SW                 PIC X     VALUE 'N'.
           88  WS-EOF                          VALUE 'Y'.
       01  WS-VAL-RC                 PIC S9(4) COMP VALUE 0.
       01  WS-GROSS                  PIC S9(9)V99 COMP-3.
       01  WS-HOLD-LIMIT             PIC S9(9)V99 COMP-3
                                     VALUE 50000.00.
       01  WS-COUNTS.
           05  WS-READ-CNT           PIC 9(7) VALUE 0.
           05  WS-OK-CNT             PIC 9(7) VALUE 0.
           05  WS-REJ-CNT            PIC 9(7) VALUE 0.
           05  WS-HELD-CNT           PIC 9(7) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT ORDER-IN
                OUTPUT ORDER-OK ORDER-BAD
           PERFORM 1000-READ
           PERFORM 2000-EDIT-ORDER UNTIL WS-EOF
           CLOSE ORDER-IN ORDER-OK ORDER-BAD
           DISPLAY 'ORDEDIT READ ' WS-READ-CNT ' OK ' WS-OK-CNT
                   ' REJ ' WS-REJ-CNT ' HELD ' WS-HELD-CNT
           GOBACK.
       1000-READ.
           READ ORDER-IN
               AT END SET WS-EOF TO TRUE
               NOT AT END ADD 1 TO WS-READ-CNT
           END-READ.
       2000-EDIT-ORDER.
           IF ORD-QTY NOT > 0 OR ORD-CUST-ID = ZERO
               MOVE 'QTY OR CUSTOMER MISSING' TO BAD-REASON
               PERFORM 8000-REJECT
           ELSE
               CALL 'ORDVAL' USING ORD-REC WS-VAL-RC
               IF WS-VAL-RC NOT = 0
                   MOVE 'FAILED ORDVAL' TO BAD-REASON
                   PERFORM 8000-REJECT
               ELSE
                   PERFORM 3000-PRICE-ORDER
                   PERFORM 4000-WRITE-GOOD
               END-IF
           END-IF
           PERFORM 1000-READ.
       3000-PRICE-ORDER.
           COMPUTE WS-GROSS = ORD-QTY * ORD-UNIT-PRICE
           IF ORD-WEB
               COMPUTE ORD-AMT ROUNDED =
                   WS-GROSS * (1 - ORD-DISC-PCT)
           ELSE
               MOVE WS-GROSS TO ORD-AMT
           END-IF
           IF ORD-AMT > WS-HOLD-LIMIT
               SET ORD-HELD TO TRUE
               ADD 1 TO WS-HELD-CNT
           ELSE
               SET ORD-NEW TO TRUE
           END-IF.
       4000-WRITE-GOOD.
           WRITE OK-REC FROM ORD-REC
           ADD 1 TO WS-OK-CNT.
       8000-REJECT.
           SET ORD-REJECTED TO TRUE
           MOVE ORD-ID TO BAD-ORD-ID
           WRITE BAD-REC
           ADD 1 TO WS-REJ-CNT.
