      *****************************************************************
      * Real-World COBOL Example: Inventory Management System
      * Demonstrates: Multiple CALL statements, nested calls, errors
      * Use Case: Complex inventory processing with database operations
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INVENTORY-MANAGER.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-INVENTORY-RECORD.
           05  WS-ITEM-ID          PIC X(10).
           05  WS-ITEM-DESC        PIC X(50).
           05  WS-QUANTITY-ON-HAND PIC 9(7) COMP-3.
           05  WS-REORDER-POINT    PIC 9(7) COMP-3.
           05  WS-UNIT-COST        PIC 9(7)V99 COMP-3.
           05  WS-WAREHOUSE-LOC    PIC X(10).
           
       01  WS-TRANSACTION-INFO.
           05  WS-TRANSACTION-ID   PIC X(12).
           05  WS-TRANS-TYPE       PIC X(10).
               88  RECEIVE-STOCK   VALUE 'RECEIVE'.
               88  PICK-STOCK      VALUE 'PICK'.
               88  ADJUST-STOCK    VALUE 'ADJUST'.
               88  RETURN-STOCK    VALUE 'RETURN'.
           05  WS-QUANTITY-DELTA   PIC S9(7) COMP-3.
           05  WS-REASON-CODE      PIC X(5).
           
       01  WS-PROCESSING-RESULTS.
           05  WS-NEW-QUANTITY     PIC 9(7) COMP-3.
           05  WS-INVENTORY-VALUE  PIC 9(10)V99 COMP-3.
           05  WS-STATUS-CODE      PIC 99 COMP.
           05  WS-ALERT-FLAG       PIC X VALUE 'N'.
           05  WS-ALERT-MSG        PIC X(100).
           
       01  WS-DATABASE-VARS.
           05  WS-DB-PROG-NAME     PIC X(20) VALUE 'DBACCESS'.
           05  WS-AUDIT-PROG       PIC X(20) VALUE 'AUDITLOG'.
           05  WS-EMAIL-PROG       PIC X(20) VALUE 'EMAILSVC'.
           
       PROCEDURE DIVISION.
       MAIN-INVENTORY-PROCESS.
           DISPLAY 'Inventory Management System Started'
           
           PERFORM INITIALIZE-TRANSACTION
           PERFORM PROCESS-INVENTORY-UPDATE
           PERFORM GENERATE-ALERTS
           
           DISPLAY 'Inventory Management Complete'
           STOP RUN.
           
       INITIALIZE-TRANSACTION.
           MOVE 'INV-001-2024' TO WS-TRANSACTION-ID
           MOVE 'RECEIVE' TO WS-TRANS-TYPE
           MOVE 'ITEM-12345' TO WS-ITEM-ID
           MOVE 'Widget Component' TO WS-ITEM-DESC
           MOVE 500 TO WS-QUANTITY-ON-HAND
           MOVE 100 TO WS-REORDER-POINT
           MOVE 25.50 TO WS-UNIT-COST
           MOVE 'ZONE-A-1' TO WS-WAREHOUSE-LOC
           MOVE 250 TO WS-QUANTITY-DELTA.
           
       PROCESS-INVENTORY-UPDATE.
           DISPLAY 'Processing inventory update...'
           
      *    Verify transaction with database
           CALL WS-DB-PROG-NAME USING WS-TRANSACTION-ID
                                      WS-TRANS-TYPE
                                      BY REFERENCE WS-STATUS-CODE
           
           IF WS-STATUS-CODE = 0
      *        Update inventory quantity
               CALL 'INVUPDATE' USING BY REFERENCE WS-ITEM-ID
                                            WS-QUANTITY-DELTA
                                            WS-NEW-QUANTITY
                                            WS-STATUS-CODE
                   RETURNING WS-INVENTORY-VALUE
                   
      *        Check if reorder needed
               IF WS-NEW-QUANTITY < WS-REORDER-POINT
                   CALL 'GENORDER' USING WS-ITEM-ID
                                         WS-REORDER-POINT
                                         WS-NEW-QUANTITY
                                   BY REFERENCE WS-ALERT-FLAG
                   
      *            If order generated, send alert
                   IF WS-ALERT-FLAG = 'Y'
                       CALL WS-EMAIL-PROG USING WS-ITEM-ID
                                                 WS-ITEM-DESC
                                                 WS-NEW-QUANTITY
                                                 'LOW-STOCK'
                   END-IF
               END-IF
               
      *        Log transaction to audit trail
               CALL WS-AUDIT-PROG USING BY REFERENCE 
                                        WS-TRANSACTION-ID
                                        WS-TRANS-TYPE
                                        WS-ITEM-ID
                                        WS-QUANTITY-DELTA
                                        WS-NEW-QUANTITY
                   ON EXCEPTION
                       DISPLAY 'Audit logging failed'
           ELSE
               DISPLAY 'Transaction validation failed: ' 
                       WS-STATUS-CODE
           END-IF.
           
       GENERATE-ALERTS.
           DISPLAY 'Generating alerts if needed'
           
           IF WS-ALERT-FLAG = 'Y'
      *        Call notification service
               CALL 'NOTIFIER' USING BY VALUE WS-INVENTORY-VALUE
                                      BY REFERENCE WS-ALERT-MSG
                   ON EXCEPTION
                       MOVE 'Alert notification failed' TO WS-ALERT-MSG
                   NOT ON EXCEPTION
                       DISPLAY 'Alert sent: ' WS-ALERT-MSG
           END-IF.
           
       END PROGRAM INVENTORY-MANAGER.
