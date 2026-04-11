      *****************************************************************
      * IMS DLI Sample: Order Management and Fulfillment System
      * Program-ID: ORDIMS01
      * Interface:  CBLTDLI
      *
      * IMS Database Hierarchy (ORDERDB):
      *   ORDER    (root - order header)
      *     LINEITEM (child - each product line)
      *       SHIPMENT (grandchild - shipment tracking)
      *
      * Operations demonstrated:
      *   GU   - get order header by order number (qualified SSA)
      *   GN   - scan through all LINEITEMs for an order
      *   GNP  - get next SHIPMENT within current LINEITEM parent
      *   ISRT - insert a new SHIPMENT record
      *   DLET - delete a cancelled LINEITEM (after GHU)
      *   GHU  - hold LINEITEM before delete
      *
      * Edge cases in this program:
      *   - MOVE used to set the SSA target segment dynamically
      *     (WS-SEGMENT-NAME is set by MOVE then used in SSA-DYNAMIC)
      *   - Conditional DLI calls (inside IF and EVALUATE)
      *   - GNP demonstrates a third-level hierarchy call
      *   - DLET with no SSA (uses position from prior GHU)
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDIMS01.
       AUTHOR. ENTERPRISE-COBOL-TEAM.
       DATE-WRITTEN. 2024-06-10.

       ENVIRONMENT DIVISION.

       DATA DIVISION.
       WORKING-STORAGE SECTION.

      *-----------------------------------------------------------------
      * IMS DLI Function Codes
      *-----------------------------------------------------------------
       01  DLI-FUNCTION-CODES.
           05  DLI-GU          PIC X(4) VALUE 'GU  '.
           05  DLI-GN          PIC X(4) VALUE 'GN  '.
           05  DLI-GNP         PIC X(4) VALUE 'GNP '.
           05  DLI-GHU         PIC X(4) VALUE 'GHU '.
           05  DLI-ISRT        PIC X(4) VALUE 'ISRT'.
           05  DLI-DLET        PIC X(4) VALUE 'DLET'.

      *-----------------------------------------------------------------
      * PCB Mask
      *-----------------------------------------------------------------
       01  ORDER-PCB.
           05  ORD-PCB-DBD         PIC X(8).
           05  ORD-PCB-LEVEL       PIC XX.
           05  ORD-PCB-STATUS      PIC XX.
           05  ORD-PCB-OPTIONS     PIC X(4).
           05  ORD-PCB-RESERVED    PIC S9(5) COMP.
           05  ORD-PCB-SEG-NAME    PIC X(8).
           05  ORD-PCB-KEY-LEN     PIC S9(5) COMP.
           05  ORD-PCB-SENS-SEGS   PIC S9(5) COMP.
           05  ORD-PCB-KEY-FB      PIC X(40).

      *-----------------------------------------------------------------
      * Segment I/O Areas
      *-----------------------------------------------------------------
       01  ORDER-IO.
           05  ORD-NUMBER          PIC X(12).
           05  ORD-CUSTOMER-ID     PIC X(10).
           05  ORD-DATE            PIC X(8).
           05  ORD-STATUS          PIC X(2).
               88  ORD-PENDING     VALUE 'PE'.
               88  ORD-SHIPPED     VALUE 'SH'.
               88  ORD-CANCELLED   VALUE 'CA'.
           05  ORD-TOTAL-AMOUNT    PIC S9(10)V99 COMP-3.

       01  LINEITEM-IO.
           05  LINE-NUMBER         PIC 9(4).
           05  LINE-PRODUCT-ID     PIC X(12).
           05  LINE-PRODUCT-DESC   PIC X(40).
           05  LINE-QTY-ORDERED    PIC 9(6) COMP.
           05  LINE-QTY-SHIPPED    PIC 9(6) COMP.
           05  LINE-UNIT-PRICE     PIC S9(8)V99 COMP-3.
           05  LINE-STATUS         PIC X(2).
               88  LINE-ACTIVE     VALUE 'AC'.
               88  LINE-CANCELLED  VALUE 'CA'.
               88  LINE-FILLED     VALUE 'FL'.

       01  SHIPMENT-IO.
           05  SHIP-TRACKING-NUM   PIC X(20).
           05  SHIP-DATE           PIC X(8).
           05  SHIP-CARRIER        PIC X(10).
           05  SHIP-QTY            PIC 9(6) COMP.
           05  SHIP-STATUS         PIC X(2).

      *-----------------------------------------------------------------
      * SSAs - fixed (static VALUE clause for segment name)
      *-----------------------------------------------------------------

      * ORDER qualified SSA - select by order number
       01  SSA-ORDER.
           05  SSA-ORD-SEG         PIC X(8) VALUE 'ORDER   '.
           05  SSA-ORD-OPEN        PIC X(1) VALUE '('.
           05  SSA-ORD-FIELD       PIC X(8) VALUE 'ORD-NUM '.
           05  SSA-ORD-OPER        PIC X(2) VALUE '= '.
           05  SSA-ORD-KEY         PIC X(12).
           05  SSA-ORD-CLOSE       PIC X(1) VALUE ')'.

      * LINEITEM unqualified SSA
       01  SSA-LINEITEM.
           05  SSA-LINE-SEG        PIC X(8) VALUE 'LINEITEM'.
           05  FILLER              PIC X(1) VALUE ' '.

      * SHIPMENT unqualified SSA
       01  SSA-SHIPMENT.
           05  SSA-SHIP-SEG        PIC X(8) VALUE 'SHIPMENT'.
           05  FILLER              PIC X(1) VALUE ' '.

      *-----------------------------------------------------------------
      * Dynamic SSA - segment name is set via MOVE at runtime
      * Used to demonstrate MOVE-based segment name tracking.
      * The analyzer resolves this by tracking the MOVE statement.
      *-----------------------------------------------------------------
       01  SSA-DYNAMIC             PIC X(9).
       01  WS-SEGMENT-NAME         PIC X(8) VALUE 'LINEITEM'.

      *-----------------------------------------------------------------
      * Working fields
      *-----------------------------------------------------------------
       01  WS-ORDER-NUMBER         PIC X(12).
       01  WS-PROCESS-COUNT        PIC 9(6) COMP VALUE ZERO.
       01  WS-CANCEL-FLAG          PIC X VALUE 'N'.
           88  CANCEL-PENDING      VALUE 'Y'.

       LINKAGE SECTION.
       01  LS-ORDER-NUMBER         PIC X(12).

       PROCEDURE DIVISION USING LS-ORDER-NUMBER.

       MAIN-LOGIC.
           MOVE LS-ORDER-NUMBER TO WS-ORDER-NUMBER
           PERFORM GET-ORDER-HEADER
           PERFORM PROCESS-LINE-ITEMS
           STOP RUN.

      *-----------------------------------------------------------------
      * GET-ORDER-HEADER
      * GU with qualified ORDER SSA - single segment retrieval
      *-----------------------------------------------------------------
       GET-ORDER-HEADER.
           MOVE WS-ORDER-NUMBER TO SSA-ORD-KEY
           CALL 'CBLTDLI' USING DLI-GU
                                ORDER-PCB
                                ORDER-IO
                                SSA-ORDER
           IF ORD-PCB-STATUS NOT = SPACES
               DISPLAY 'ORDER NOT FOUND: ' WS-ORDER-NUMBER
               STOP RUN
           END-IF.

      *-----------------------------------------------------------------
      * PROCESS-LINE-ITEMS
      * GN loop through all LINEITEMs under the positioned ORDER
      * For each LINEITEM, conditionally scan SHIPMENTs
      *-----------------------------------------------------------------
       PROCESS-LINE-ITEMS.
           CALL 'CBLTDLI' USING DLI-GN
                                ORDER-PCB
                                LINEITEM-IO
                                SSA-LINEITEM
           PERFORM UNTIL ORD-PCB-STATUS = 'GE'
               ADD 1 TO WS-PROCESS-COUNT
               EVALUATE TRUE
                   WHEN LINE-CANCELLED
                       PERFORM HOLD-AND-DELETE-LINEITEM
                   WHEN LINE-FILLED
                       PERFORM SCAN-SHIPMENTS
                   WHEN OTHER
                       CONTINUE
               END-EVALUATE
               CALL 'CBLTDLI' USING DLI-GN
                                    ORDER-PCB
                                    LINEITEM-IO
                                    SSA-LINEITEM
           END-PERFORM.

      *-----------------------------------------------------------------
      * SCAN-SHIPMENTS
      * GNP: get-next-in-parent, scans SHIPMENTs under current LINEITEM
      * GNP restricts retrieval to children of the current LINEITEM.
      *-----------------------------------------------------------------
       SCAN-SHIPMENTS.
           CALL 'CBLTDLI' USING DLI-GNP
                                ORDER-PCB
                                SHIPMENT-IO
                                SSA-SHIPMENT
           PERFORM UNTIL ORD-PCB-STATUS = 'GE'
               DISPLAY 'SHIPMENT: ' SHIP-TRACKING-NUM
               CALL 'CBLTDLI' USING DLI-GNP
                                    ORDER-PCB
                                    SHIPMENT-IO
                                    SSA-SHIPMENT
           END-PERFORM.

      *-----------------------------------------------------------------
      * HOLD-AND-DELETE-LINEITEM
      * GHU to hold the LINEITEM, then DLET (no SSA after hold)
      *-----------------------------------------------------------------
       HOLD-AND-DELETE-LINEITEM.
           CALL 'CBLTDLI' USING DLI-GHU
                                ORDER-PCB
                                LINEITEM-IO
                                SSA-LINEITEM
           IF ORD-PCB-STATUS = SPACES
               CALL 'CBLTDLI' USING DLI-DLET
                                    ORDER-PCB
                                    LINEITEM-IO
           END-IF.

      *-----------------------------------------------------------------
      * INSERT-SHIPMENT-DYNAMIC
      * Demonstrates MOVE-based (dynamic) SSA segment name.
      * WS-SEGMENT-NAME has VALUE 'LINEITEM', MOVEd into SSA-DYNAMIC.
      * The IMSSegmentAnalyzer should resolve this to 'LINEITEM'.
      *-----------------------------------------------------------------
       INSERT-SHIPMENT-DYNAMIC.
           MOVE WS-SEGMENT-NAME TO SSA-DYNAMIC
           CALL 'CBLTDLI' USING DLI-ISRT
                                ORDER-PCB
                                LINEITEM-IO
                                SSA-DYNAMIC.
