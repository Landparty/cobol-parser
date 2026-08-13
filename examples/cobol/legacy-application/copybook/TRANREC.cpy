      *****************************************************************
      * TRANSACTION RECORD LAYOUT                                    *
      * COPYBOOK: TRANREC                                            *
      * DESCRIPTION: Banking transaction record structure            *
      * USED BY: EODPROC, INTCALC, STMTGEN, CHKCLR, CTRRPT,       *
      *          ACHPROC, GLRECON                                    *
      *****************************************************************
       01  TRANSACTION-RECORD.
           05  TRAN-ID                   PIC X(16).
           05  TRAN-ACCT-NUMBER          PIC X(12).
           05  TRAN-TYPE                 PIC X(02).
               88  TRAN-DEBIT            VALUE 'DR'.
               88  TRAN-CREDIT           VALUE 'CR'.
           05  TRAN-CODE                 PIC X(04).
               88  TRAN-DEPOSIT          VALUE 'DEP '.
               88  TRAN-WITHDRAWAL       VALUE 'WDL '.
               88  TRAN-TRANSFER-IN      VALUE 'XFI '.
               88  TRAN-TRANSFER-OUT     VALUE 'XFO '.
               88  TRAN-CHECK            VALUE 'CHK '.
               88  TRAN-ACH-CREDIT       VALUE 'ACHC'.
               88  TRAN-ACH-DEBIT        VALUE 'ACHD'.
               88  TRAN-WIRE-IN          VALUE 'WRI '.
               88  TRAN-WIRE-OUT         VALUE 'WRO '.
               88  TRAN-INTEREST         VALUE 'INT '.
               88  TRAN-FEE              VALUE 'FEE '.
               88  TRAN-ADJUSTMENT       VALUE 'ADJ '.
               88  TRAN-LOAN-PMT         VALUE 'LPM '.
               88  TRAN-ATM-WDL          VALUE 'ATM '.
               88  TRAN-POS              VALUE 'POS '.
           05  TRAN-AMOUNT               PIC S9(13)V99 COMP-3.
           05  TRAN-EFFECTIVE-DATE       PIC X(10).
           05  TRAN-POST-DATE            PIC X(10).
           05  TRAN-VALUE-DATE           PIC X(10).
           05  TRAN-DESCRIPTION          PIC X(40).
           05  TRAN-REFERENCE-NUM        PIC X(20).
           05  TRAN-CHECK-NUMBER         PIC X(10).
           05  TRAN-BRANCH-CODE          PIC X(04).
           05  TRAN-TELLER-ID           PIC X(06).
           05  TRAN-CHANNEL              PIC X(03).
               88  TRAN-BRANCH           VALUE 'BRN'.
               88  TRAN-ONLINE           VALUE 'OLN'.
               88  TRAN-MOBILE           VALUE 'MOB'.
               88  TRAN-ATM-CHAN         VALUE 'ATM'.
               88  TRAN-BATCH            VALUE 'BAT'.
           05  TRAN-STATUS               PIC X(01).
               88  TRAN-POSTED           VALUE 'P'.
               88  TRAN-PENDING          VALUE 'N'.
               88  TRAN-REVERSED         VALUE 'R'.
               88  TRAN-HELD             VALUE 'H'.
           05  TRAN-RUNNING-BAL          PIC S9(13)V99 COMP-3.
           05  TRAN-TIMESTAMP            PIC X(26).
           05  FILLER                    PIC X(10).
