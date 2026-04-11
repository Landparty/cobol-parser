      *****************************************************************
      * IMS DLI Sample: Banking Account Management System
      * Program-ID: BNKIMS01
      * Interface:  CBLTDLI (AIBTDLI in alternate entry)
      *
      * IMS Database Hierarchy (BANKDB):
      *   CUSTOMER   (root)
      *     ACCOUNT  (level 2)
      *       TRANSACT (level 3 - 8-char limit on segment names)
      *
      * Operations demonstrated:
      *   GHU  - get-hold-unique CUSTOMER+ACCOUNT for debit/credit
      *   REPL - replace held ACCOUNT after balance update
      *   ISRT - insert new TRANSACT under ACCOUNT
      *   GN   - loop through all TRANSACTs for a statement
      *   CHKP - periodic checkpoint during batch run
      *
      * The GHU+REPL pattern is the canonical IMS way to update a
      * record atomically.  The hold prevents other programs from
      * modifying the record between the read and the write.
      *
      * Two PCBs are used:
      *   CUST-PCB    - BANKDB, full update access
      *   AUDIT-PCB   - AUDITDB, insert-only for audit trail
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BNKIMS01.
       AUTHOR. ENTERPRISE-COBOL-TEAM.
       DATE-WRITTEN. 2024-03-01.

       ENVIRONMENT DIVISION.

       DATA DIVISION.
       WORKING-STORAGE SECTION.

      *-----------------------------------------------------------------
      * IMS DLI Function Codes
      *-----------------------------------------------------------------
       01  DLI-GHU             PIC X(4) VALUE 'GHU '.
       01  DLI-GN              PIC X(4) VALUE 'GN  '.
       01  DLI-REPL            PIC X(4) VALUE 'REPL'.
       01  DLI-ISRT            PIC X(4) VALUE 'ISRT'.
       01  DLI-CHKP            PIC X(4) VALUE 'CHKP'.

      *-----------------------------------------------------------------
      * PCB Masks (two databases)
      *-----------------------------------------------------------------
       01  CUST-PCB.
           05  CUST-PCB-DBD        PIC X(8).
           05  CUST-PCB-LEVEL      PIC XX.
           05  CUST-PCB-STATUS     PIC XX.
           05  CUST-PCB-OPTIONS    PIC X(4).
           05  CUST-PCB-RESERVED   PIC S9(5) COMP.
           05  CUST-PCB-SEG-NAME   PIC X(8).
           05  CUST-PCB-KEY-LEN    PIC S9(5) COMP.
           05  CUST-PCB-SENS-SEGS  PIC S9(5) COMP.
           05  CUST-PCB-KEY-FB     PIC X(24).

       01  AUDIT-PCB.
           05  AUDIT-PCB-DBD       PIC X(8).
           05  AUDIT-PCB-LEVEL     PIC XX.
           05  AUDIT-PCB-STATUS    PIC XX.
           05  AUDIT-PCB-OPTIONS   PIC X(4).
           05  AUDIT-PCB-RESERVED  PIC S9(5) COMP.
           05  AUDIT-PCB-SEG-NAME  PIC X(8).
           05  AUDIT-PCB-KEY-LEN   PIC S9(5) COMP.
           05  AUDIT-PCB-SENS-SEGS PIC S9(5) COMP.
           05  AUDIT-PCB-KEY-FB    PIC X(24).

      *-----------------------------------------------------------------
      * Segment I/O Areas
      *-----------------------------------------------------------------
       01  CUSTOMER-IO.
           05  CUST-ID             PIC X(10).
           05  CUST-NAME           PIC X(30).
           05  CUST-TAX-ID         PIC X(11).
           05  CUST-SINCE          PIC X(8).
           05  CUST-RATING         PIC X(1).

       01  ACCOUNT-IO.
           05  ACCT-NUMBER         PIC X(12).
           05  ACCT-TYPE           PIC X(2).
               88  ACCT-CHECKING   VALUE 'CK'.
               88  ACCT-SAVINGS    VALUE 'SV'.
               88  ACCT-LOAN       VALUE 'LN'.
           05  ACCT-BALANCE        PIC S9(12)V99 COMP-3.
           05  ACCT-OPEN-DATE      PIC X(8).
           05  ACCT-LAST-TXN-DATE  PIC X(8).
           05  ACCT-STATUS         PIC X(1).

       01  TRANSACT-IO.
           05  TXN-ID              PIC X(16).
           05  TXN-DATE            PIC X(8).
           05  TXN-TYPE            PIC X(2).
           05  TXN-AMOUNT          PIC S9(10)V99 COMP-3.
           05  TXN-DESCRIPTION     PIC X(40).
           05  TXN-BALANCE-AFTER   PIC S9(12)V99 COMP-3.

       01  AUDIT-ENTRY-IO.
           05  AUDIT-TIMESTAMP     PIC X(26).
           05  AUDIT-PROG-ID       PIC X(8).
           05  AUDIT-CUST-ID       PIC X(10).
           05  AUDIT-ACCT-NUM      PIC X(12).
           05  AUDIT-ACTION        PIC X(10).
           05  AUDIT-AMOUNT        PIC S9(10)V99 COMP-3.

      *-----------------------------------------------------------------
      * Segment Search Arguments
      *-----------------------------------------------------------------

      * CUSTOMER qualified SSA
       01  SSA-CUSTOMER.
           05  SSA-CUST-SEG        PIC X(8) VALUE 'CUSTOMER'.
           05  SSA-CUST-OPEN       PIC X(1) VALUE '('.
           05  SSA-CUST-FIELD      PIC X(8) VALUE 'CUST-ID '.
           05  SSA-CUST-OPER       PIC X(2) VALUE '= '.
           05  SSA-CUST-KEY        PIC X(10).
           05  SSA-CUST-CLOSE      PIC X(1) VALUE ')'.

      * ACCOUNT qualified SSA
       01  SSA-ACCOUNT.
           05  SSA-ACCT-SEG        PIC X(8) VALUE 'ACCOUNT '.
           05  SSA-ACCT-OPEN       PIC X(1) VALUE '('.
           05  SSA-ACCT-FIELD      PIC X(8) VALUE 'ACCT-NUM'.
           05  SSA-ACCT-OPER       PIC X(2) VALUE '= '.
           05  SSA-ACCT-KEY        PIC X(12).
           05  SSA-ACCT-CLOSE      PIC X(1) VALUE ')'.

      * TRANSACT unqualified SSA (for sequential retrieval)
       01  SSA-TRANSACT.
           05  SSA-TXN-SEG         PIC X(8) VALUE 'TRANSACT'.
           05  FILLER              PIC X(1) VALUE ' '.

      * AUDIT-ENTRY SSA for the audit database
       01  SSA-AUDIT-ENTRY.
           05  SSA-AUDIT-SEG       PIC X(8) VALUE 'AUDITENT'.
           05  FILLER              PIC X(1) VALUE ' '.

      *-----------------------------------------------------------------
      * Working fields
      *-----------------------------------------------------------------
       01  WS-CUST-KEY             PIC X(10).
       01  WS-ACCT-KEY             PIC X(12).
       01  WS-TXN-AMOUNT           PIC S9(10)V99 COMP-3.
       01  WS-CHKP-ID              PIC X(8) VALUE 'BNK00001'.
       01  WS-RECORD-COUNT         PIC 9(6) COMP VALUE ZERO.
       01  WS-ERROR-FLAG           PIC X VALUE 'N'.
           88  WS-ERROR-OCCURRED   VALUE 'Y'.

       LINKAGE SECTION.
       01  LS-CUSTOMER-ID          PIC X(10).
       01  LS-ACCOUNT-NUMBER       PIC X(12).
       01  LS-TRANSACTION-AMOUNT   PIC S9(10)V99 COMP-3.

       PROCEDURE DIVISION USING LS-CUSTOMER-ID
                                  LS-ACCOUNT-NUMBER
                                  LS-TRANSACTION-AMOUNT.

       MAIN-LOGIC.
           MOVE LS-CUSTOMER-ID        TO WS-CUST-KEY
           MOVE LS-ACCOUNT-NUMBER     TO WS-ACCT-KEY
           MOVE LS-TRANSACTION-AMOUNT TO WS-TXN-AMOUNT
           PERFORM DEBIT-ACCOUNT
           IF NOT WS-ERROR-OCCURRED
               PERFORM INSERT-TRANSACTION
               PERFORM WRITE-AUDIT-TRAIL
               PERFORM ISSUE-CHECKPOINT
           END-IF
           STOP RUN.

      *-----------------------------------------------------------------
      * DEBIT-ACCOUNT
      * GHU+REPL pattern: get-hold the account, deduct amount, replace
      * Uses two PCB (CUST-PCB), path call CUSTOMER+ACCOUNT
      *-----------------------------------------------------------------
       DEBIT-ACCOUNT.
           MOVE WS-CUST-KEY TO SSA-CUST-KEY
           MOVE WS-ACCT-KEY TO SSA-ACCT-KEY
           CALL 'CBLTDLI' USING DLI-GHU
                                CUST-PCB
                                ACCOUNT-IO
                                SSA-CUSTOMER
                                SSA-ACCOUNT
           IF CUST-PCB-STATUS NOT = SPACES
               DISPLAY 'GHU FAILED: ' CUST-PCB-STATUS
               MOVE 'Y' TO WS-ERROR-FLAG
           ELSE
               SUBTRACT WS-TXN-AMOUNT FROM ACCT-BALANCE
               CALL 'CBLTDLI' USING DLI-REPL
                                    CUST-PCB
                                    ACCOUNT-IO
               IF CUST-PCB-STATUS NOT = SPACES
                   DISPLAY 'REPL FAILED: ' CUST-PCB-STATUS
                   MOVE 'Y' TO WS-ERROR-FLAG
               END-IF
           END-IF.

      *-----------------------------------------------------------------
      * INSERT-TRANSACTION
      * ISRT: insert a new TRANSACT segment under the held ACCOUNT
      * Uses CUST-PCB, path call CUSTOMER+ACCOUNT+TRANSACT
      *-----------------------------------------------------------------
       INSERT-TRANSACTION.
           MOVE SPACES        TO TRANSACT-IO
           MOVE WS-TXN-AMOUNT TO TXN-AMOUNT
           MOVE 'DR'          TO TXN-TYPE
           MOVE ACCT-BALANCE  TO TXN-BALANCE-AFTER
           CALL 'CBLTDLI' USING DLI-ISRT
                                CUST-PCB
                                TRANSACT-IO
                                SSA-CUSTOMER
                                SSA-ACCOUNT
                                SSA-TRANSACT
           IF CUST-PCB-STATUS NOT = SPACES
               DISPLAY 'ISRT FAILED: ' CUST-PCB-STATUS
               MOVE 'Y' TO WS-ERROR-FLAG
           END-IF.

      *-----------------------------------------------------------------
      * WRITE-AUDIT-TRAIL
      * ISRT into AUDIT-PCB (second database)
      * Demonstrates: same program writing to two IMS databases
      *-----------------------------------------------------------------
       WRITE-AUDIT-TRAIL.
           MOVE SPACES        TO AUDIT-ENTRY-IO
           MOVE 'BNKIMS01'    TO AUDIT-PROG-ID
           MOVE WS-CUST-KEY   TO AUDIT-CUST-ID
           MOVE WS-ACCT-KEY   TO AUDIT-ACCT-NUM
           MOVE 'DEBIT'       TO AUDIT-ACTION
           MOVE WS-TXN-AMOUNT TO AUDIT-AMOUNT
           CALL 'CBLTDLI' USING DLI-ISRT
                                AUDIT-PCB
                                AUDIT-ENTRY-IO
                                SSA-AUDIT-ENTRY
           IF AUDIT-PCB-STATUS NOT = SPACES
               DISPLAY 'AUDIT ISRT FAILED: ' AUDIT-PCB-STATUS
           END-IF.

      *-----------------------------------------------------------------
      * ISSUE-CHECKPOINT
      * CHKP: periodic checkpoint - no segment access
      *-----------------------------------------------------------------
       ISSUE-CHECKPOINT.
           CALL 'CBLTDLI' USING DLI-CHKP
                                CUST-PCB
                                WS-CHKP-ID.
