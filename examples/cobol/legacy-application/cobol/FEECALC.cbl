       IDENTIFICATION DIVISION.
       PROGRAM-ID. FEECALC.
      *****************************************************************
      * PROGRAM:   FEECALC                                            *
      * PURPOSE:   TRANSACTION FEE SCHEDULE CALCULATOR                *
      *            SORTS THE DAILY TRANSACTION EXTRACT BY ACCOUNT     *
      *            NUMBER, THEN LOOKS UP EACH TRANSACTION'S FEE VIA   *
      *            A BINARY SEARCH OF AN IN-MEMORY FEE SCHEDULE TABLE *
      *            KEYED BY TRANSACTION CODE, AND WRITES A FEE        *
      *            ASSESSMENT REPORT.                                *
      * INPUT:     TRANS-IN - DAILY TRANSACTION EXTRACT (TRANREC)     *
      * OUTPUT:    FEERPT   - FEE ASSESSMENT REPORT                   *
      *            (SORT WORK: SORTWK01, INTERMEDIATE: TRANS-SORTED)  *
      * PROC:      COBCOMP (STANDARD COBOL COMPILE/LINK)               *
      * FREQ:      DAILY - SUBMITTED VIA FEECALCJ.JCL                 *
      *****************************************************************

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TRANS-IN     ASSIGN TO TRANIN
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL.
           SELECT TRANS-SORTED ASSIGN TO TRANSORT
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-TRANSORT-STATUS.
           SELECT SORT-WORK    ASSIGN TO SORTWK01.
           SELECT FEERPT       ASSIGN TO FEERPT
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
      *    Equal-level COPY nests as a SIBLING, not a child -- an 01
      *    wrapper around "COPY TRANREC." would leave the wrapper
      *    empty and TRANSACTION-RECORD floating beside it. REPLACING
      *    renames the copybook's own 01 so each FD gets one genuinely
      *    populated top-level record, still OF-qualifiable below.
       FD  TRANS-IN
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
           COPY TRANREC
               REPLACING ==TRANSACTION-RECORD== BY ==TRANS-IN-REC==.

       FD  TRANS-SORTED
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
           COPY TRANREC
               REPLACING ==TRANSACTION-RECORD== BY ==TRANS-SORTED-REC==.

       SD  SORT-WORK
           RECORDING MODE IS F.
           COPY TRANREC
               REPLACING ==TRANSACTION-RECORD== BY ==SORT-WORK-REC==.

       FD  FEERPT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  RPT-RECORD               PIC X(133).

       WORKING-STORAGE SECTION.
           COPY WSCOMMON.
           COPY ERRORCD.

       01  WS-TRANSORT-STATUS       PIC X(02).
           88  WS-TRANSORT-OK       VALUE '00'.

      *-----------------------------------------------------------------
      * FEE SCHEDULE TABLE - LOADED FROM LITERALS AT 1000-INITIALIZE,
      * SEARCHED WITH SEARCH ALL (BINARY SEARCH ON THE ASCENDING KEY)
      *-----------------------------------------------------------------
       01  FEE-SCHEDULE-TABLE.
           05  FEE-SCHEDULE-ENTRY OCCURS 8 TIMES
               ASCENDING KEY IS FT-TRAN-CODE
               INDEXED BY FT-IDX.
               10  FT-TRAN-CODE      PIC X(04).
               10  FT-FEE-AMOUNT     PIC S9(05)V99 COMP-3.
               10  FT-FEE-DESC       PIC X(20).

       01  WS-SEARCH-CODE            PIC X(04).
       01  WS-CALC-FEE                PIC S9(05)V99 COMP-3.
       01  WS-NEW-BALANCE             PIC S9(13)V99 COMP-3.
       01  WS-FEE-FOUND-FLAG          PIC X(01) VALUE 'N'.
           88  WS-FEE-FOUND           VALUE 'Y'.
           88  WS-FEE-NOT-FOUND       VALUE 'N'.

       01  WS-FEE-COUNTERS.
           05  WS-TRANS-READ          PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-FEES-ASSESSED       PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-FEES-WAIVED         PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-TOTAL-FEES          PIC S9(11)V99 COMP-3 VALUE ZERO.

       01  WS-HDR.
           05  FILLER PIC X(16) VALUE 'TRAN-ID         '.
           05  FILLER PIC X(14) VALUE 'ACCOUNT       '.
           05  FILLER PIC X(06) VALUE 'CODE  '.
           05  FILLER PIC X(14) VALUE 'FEE-AMOUNT    '.
           05  FILLER PIC X(20) VALUE 'DESCRIPTION         '.

       01  WS-DETAIL.
           05  WS-DET-TRAN-ID         PIC X(16).
           05  FILLER                 PIC X(02) VALUE SPACES.
           05  WS-DET-ACCT            PIC X(12).
           05  FILLER                 PIC X(02) VALUE SPACES.
           05  WS-DET-CODE            PIC X(04).
           05  FILLER                 PIC X(02) VALUE SPACES.
           05  WS-DET-FEE             PIC Z,ZZ9.99-.
           05  FILLER                 PIC X(02) VALUE SPACES.
           05  WS-DET-DESC            PIC X(20).
           05  FILLER                 PIC X(51) VALUE SPACES.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-INITIALIZE
           PERFORM 2000-SORT-TRANSACTIONS
           PERFORM 3000-PROCESS-SORTED-FILE
           PERFORM 4000-FINALIZE
           GOBACK.

       1000-INITIALIZE.
           DISPLAY 'FEECALC: FEE SCHEDULE CALCULATOR STARTED'
           PERFORM 1100-LOAD-FEE-SCHEDULE
           OPEN OUTPUT FEERPT
           WRITE RPT-RECORD FROM WS-HDR.

      *    FEE SCHEDULE MUST BE LOADED IN ASCENDING TRAN-CODE ORDER
      *    FOR SEARCH ALL TO BINARY-SEARCH IT CORRECTLY.
       1100-LOAD-FEE-SCHEDULE.
           MOVE 'ACHD' TO FT-TRAN-CODE(1)
           MOVE 1.50   TO FT-FEE-AMOUNT(1)
           MOVE 'ACH DEBIT RETURN FEE' TO FT-FEE-DESC(1)
           MOVE 'ATM ' TO FT-TRAN-CODE(2)
           MOVE 2.50   TO FT-FEE-AMOUNT(2)
           MOVE 'NON-NETWORK ATM FEE' TO FT-FEE-DESC(2)
           MOVE 'CHK ' TO FT-TRAN-CODE(3)
           MOVE 0.00   TO FT-FEE-AMOUNT(3)
           MOVE 'CHECK - NO FEE' TO FT-FEE-DESC(3)
           MOVE 'DEP ' TO FT-TRAN-CODE(4)
           MOVE 0.00   TO FT-FEE-AMOUNT(4)
           MOVE 'DEPOSIT - NO FEE' TO FT-FEE-DESC(4)
           MOVE 'LPM ' TO FT-TRAN-CODE(5)
           MOVE 15.00  TO FT-FEE-AMOUNT(5)
           MOVE 'LATE LOAN PMT FEE' TO FT-FEE-DESC(5)
           MOVE 'POS ' TO FT-TRAN-CODE(6)
           MOVE 0.00   TO FT-FEE-AMOUNT(6)
           MOVE 'POINT OF SALE - NO FEE' TO FT-FEE-DESC(6)
           MOVE 'WDL ' TO FT-TRAN-CODE(7)
           MOVE 0.00   TO FT-FEE-AMOUNT(7)
           MOVE 'WITHDRAWAL - NO FEE' TO FT-FEE-DESC(7)
           MOVE 'WRI ' TO FT-TRAN-CODE(8)
           MOVE 25.00  TO FT-FEE-AMOUNT(8)
           MOVE 'INCOMING WIRE FEE' TO FT-FEE-DESC(8).

       2000-SORT-TRANSACTIONS.
           SORT SORT-WORK
               ON ASCENDING KEY TRAN-ACCT-NUMBER OF SORT-WORK-REC
               ON ASCENDING KEY TRAN-EFFECTIVE-DATE OF SORT-WORK-REC
               USING TRANS-IN
               GIVING TRANS-SORTED.

       3000-PROCESS-SORTED-FILE.
           OPEN INPUT TRANS-SORTED
           PERFORM 3900-READ-NEXT-TRAN
           PERFORM UNTIL WS-EOF
               ADD 1 TO WS-TRANS-READ
               PERFORM 3100-LOOKUP-FEE
               PERFORM 3200-WRITE-DETAIL
               PERFORM 3900-READ-NEXT-TRAN
           END-PERFORM
           CLOSE TRANS-SORTED.

       3100-LOOKUP-FEE.
           MOVE TRAN-CODE OF TRANS-SORTED-REC TO WS-SEARCH-CODE
           MOVE ZERO TO WS-CALC-FEE
           SET WS-FEE-NOT-FOUND TO TRUE
           SET FT-IDX TO 1
           SEARCH ALL FEE-SCHEDULE-ENTRY
               AT END
                   SET WS-FEE-NOT-FOUND TO TRUE
               WHEN FT-TRAN-CODE(FT-IDX) = WS-SEARCH-CODE
                   MOVE FT-FEE-AMOUNT(FT-IDX) TO WS-CALC-FEE
                   SET WS-FEE-FOUND TO TRUE
           END-SEARCH
           IF WS-FEE-FOUND AND WS-CALC-FEE > ZERO
               ADD 1 TO WS-FEES-ASSESSED
               ADD WS-CALC-FEE TO WS-TOTAL-FEES
           ELSE
               ADD 1 TO WS-FEES-WAIVED
           END-IF.

       3200-WRITE-DETAIL.
           MOVE TRAN-ID OF TRANS-SORTED-REC       TO WS-DET-TRAN-ID
           MOVE TRAN-ACCT-NUMBER OF TRANS-SORTED-REC TO WS-DET-ACCT
           MOVE WS-SEARCH-CODE                    TO WS-DET-CODE
           MOVE WS-CALC-FEE                       TO WS-DET-FEE
           IF WS-FEE-FOUND
               MOVE FT-FEE-DESC(FT-IDX)           TO WS-DET-DESC
           ELSE
               MOVE 'UNKNOWN TRAN CODE'            TO WS-DET-DESC
           END-IF
           WRITE RPT-RECORD FROM WS-DETAIL.

       3900-READ-NEXT-TRAN.
           READ TRANS-SORTED
               AT END
                   SET WS-EOF TO TRUE
               NOT AT END
                   CONTINUE
           END-READ.

       4000-FINALIZE.
           CLOSE FEERPT
           DISPLAY 'FEECALC: FEE CALCULATION COMPLETE'
           DISPLAY 'TRANSACTIONS READ:  ' WS-TRANS-READ
           DISPLAY 'FEES ASSESSED:      ' WS-FEES-ASSESSED
           DISPLAY 'FEES WAIVED:        ' WS-FEES-WAIVED
           DISPLAY 'TOTAL FEES:         ' WS-TOTAL-FEES
           MOVE ZERO TO RETURN-CODE.
