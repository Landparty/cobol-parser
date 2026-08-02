      *****************************************************************
      * TXNDATA -- transaction record used by the CSV test-data        *
      * generator tests. Deliberately exercises every construct the    *
      * generator has to reason about: level-88 domains, OCCURS,       *
      * REDEFINES, FILLER, COMP-3/COMP usage, edited pictures, and a   *
      * VALUE clause.                                                  *
      *****************************************************************
       01 TXN-RECORD.
           05 TXN-TYPE               PIC X.
              88 TXN-DEPOSIT         VALUE 'D'.
              88 TXN-WITHDRAWAL      VALUE 'W'.
              88 TXN-TRANSFER        VALUE 'T'.
           05 TXN-STATUS             PIC 9.
              88 ST-PENDING          VALUE 1.
              88 ST-SETTLED          VALUE 2 THRU 4.
           05 TXN-ID                 PIC 9(8).
           05 CUST-NAME              PIC X(30).
           05 CUST-CITY              PIC X(20).
           05 CUST-STATE             PIC X(2).
           05 TXN-AMT                PIC S9(7)V99 COMP-3.
           05 DISPLAY-BAL            PIC -ZZ,ZZ9.99.
           05 POST-DATE              PIC 9(8).
           05 LINE-CNT               PIC 9(4) COMP.
           05 ITEM-TAB OCCURS 3 TIMES.
              10 ITEM-CODE           PIC X(4).
              10 ITEM-QTY            PIC 9(3).
           05 RAW-AREA               PIC X(12).
           05 SPLIT-AREA REDEFINES RAW-AREA.
              10 PART-A              PIC X(6).
              10 PART-B              PIC X(6).
           05 FILLER                 PIC X(5).
           05 ACTIVE-FLAG            PIC X VALUE 'Y'.
