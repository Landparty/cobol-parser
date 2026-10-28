      * ORDER RECORD -- SHARED BY THE ORDER SUITE
       01  ORD-REC.
           05  ORD-ID                PIC X(10).
           05  ORD-CUST-ID           PIC 9(8).
           05  ORD-DATE              PIC 9(8).
           05  ORD-QTY               PIC S9(5)      COMP-3.
           05  ORD-UNIT-PRICE        PIC S9(7)V99   COMP-3.
           05  ORD-AMT               PIC S9(9)V99   COMP-3.
           05  ORD-STATUS            PIC X.
               88  ORD-NEW           VALUE 'N'.
               88  ORD-HELD          VALUE 'H'.
               88  ORD-REJECTED      VALUE 'R'.
               88  ORD-POSTED        VALUE 'P'.
           05  ORD-SHIP-ADDR.
               COPY ADDRREC.
           05  ORD-DISC-PCT          PIC V999       COMP-3.
           05  ORD-CHANNEL           PIC X.
               88  ORD-WEB           VALUE 'W'.
               88  ORD-PHONE         VALUE 'P'.
           05  FILLER                PIC X(9).
