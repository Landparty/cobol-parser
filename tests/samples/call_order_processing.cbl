      *****************************************************************
      * Real-World COBOL Example: Order Processing System
      * Demonstrates: Multiple nested CALL statements, complex logic
      * Use Case: E-commerce order fulfillment pipeline
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDER-PROCESSING-ENGINE.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ORDER-HEADER.
           05  WS-ORDER-ID         PIC X(10).
           05  WS-CUSTOMER-ID      PIC X(8).
           05  WS-ORDER-DATE       PIC 9(8).
           05  WS-ORDER-STATUS     PIC X(2).
               88  STATUS-NEW      VALUE '01'.
               88  STATUS-CONFIRMED VALUE '02'.
               88  STATUS-PICKING  VALUE '03'.
               88  STATUS-SHIPPED  VALUE '04'.
               88  STATUS-DELIVERED VALUE '05'.
               88  STATUS-CANCELLED VALUE '99'.
           05  WS-TOTAL-AMOUNT     PIC 9(8)V99 COMP-3.
           05  WS-TAX-AMOUNT       PIC 9(8)V99 COMP-3.
           05  WS-SHIPPING-COST    PIC 9(6)V99 COMP-3.
           
       01  WS-ORDER-LINES.
           05  WS-LINE-ITEM-COUNT  PIC 99 COMP.
           05  WS-ITEM-ID          PIC X(8).
           05  WS-ITEM-QUANTITY    PIC 9(5) COMP-3.
           05  WS-ITEM-PRICE       PIC 9(6)V99 COMP-3.
           
       01  WS-CUSTOMER-INFO.
           05  WS-CUSTOMER-NAME    PIC X(40).
           05  WS-SHIPPING-ADDR    PIC X(50).
           05  WS-BILLING-ADDR     PIC X(50).
           05  WS-PAYMENT-METHOD   PIC X(10).
           05  WS-CREDIT-LIMIT     PIC 9(8)V99 COMP-3.
           
       01  WS-PROCESSING-STATUS.
           05  WS-VALIDATION-OK    PIC X VALUE 'N'.
           05  WS-INVENTORY-OK     PIC X VALUE 'N'.
           05  WS-PAYMENT-OK       PIC X VALUE 'N'.
           05  WS-FULFILLMENT-OK   PIC X VALUE 'N'.
           05  WS-SHIPMENT-ID      PIC X(10).
           05  WS-TRACKING-NUMBER  PIC X(20).
           
       01  WS-EXCEPTION-HANDLING.
           05  WS-EXCEPTION-CODE   PIC 999 VALUE 0.
           05  WS-EXCEPTION-MSG    PIC X(100).
           05  WS-ROLLBACK-FLAG    PIC X VALUE 'N'.
           
       01  WS-SERVICE-NAMES.
           05  WS-VALIDATION-SVC   PIC X(20) VALUE 'VALIDATE-ORDER'.
           05  WS-INVENTORY-SVC    PIC X(20) VALUE 'CHECK-INVENTORY'.
           05  WS-PRICING-SVC      PIC X(20) VALUE 'CALC-PRICING'.
           05  WS-PAYMENT-SVC      PIC X(20) VALUE 'PROCESS-PAYMENT'.
           05  WS-FULFILL-SVC      PIC X(20) VALUE 'CREATE-SHIPMENT'.
           05  WS-NOTIFY-SVC       PIC X(20) VALUE 'SEND-NOTIFICATION'.
           05  WS-ARCHIVE-SVC      PIC X(20) VALUE 'ARCHIVE-ORDER'.
           
       PROCEDURE DIVISION.
       MAIN-ORDER-PROCESS.
           DISPLAY 'Order Processing Engine Started'
           PERFORM LOAD-ORDER-DATA
           PERFORM VALIDATE-ORDER
           PERFORM CHECK-INVENTORY
           PERFORM CALCULATE-PRICING
           PERFORM PROCESS-PAYMENT
           PERFORM FULFILL-ORDER
           PERFORM SEND-NOTIFICATIONS
           PERFORM ARCHIVE-ORDER
           DISPLAY 'Order Processing Complete'
           STOP RUN.
           
       LOAD-ORDER-DATA.
           MOVE 'ORD-000001' TO WS-ORDER-ID
           MOVE 'CUST-0042' TO WS-CUSTOMER-ID
           MOVE 20240115 TO WS-ORDER-DATE
           MOVE '01' TO WS-ORDER-STATUS
           MOVE 'John Doe' TO WS-CUSTOMER-NAME
           MOVE '123 Main St, City, ST 12345' TO WS-SHIPPING-ADDR
           MOVE 1 TO WS-LINE-ITEM-COUNT
           MOVE 'PROD-1234' TO WS-ITEM-ID
           MOVE 5 TO WS-ITEM-QUANTITY
           MOVE 99.99 TO WS-ITEM-PRICE.
           
       VALIDATE-ORDER.
           DISPLAY 'Validating order...'
           
      *    CALL order validation service
           CALL WS-VALIDATION-SVC USING BY REFERENCE WS-ORDER-ID
                                             WS-CUSTOMER-ID
                                             WS-ORDER-DATE
                                        BY REFERENCE WS-VALIDATION-OK
                   ON EXCEPTION
                       MOVE 001 TO WS-EXCEPTION-CODE
                       MOVE 'Validation service error' TO WS-EXCEPTION-MSG
                       MOVE 'Y' TO WS-ROLLBACK-FLAG
           
           IF WS-VALIDATION-OK = 'N' OR WS-ROLLBACK-FLAG = 'Y'
               PERFORM ROLLBACK-ORDER-PROCESS
               STOP RUN
           END-IF.
           
       CHECK-INVENTORY.
           DISPLAY 'Checking inventory...'
           
      *    CALL inventory check for each line item
           PERFORM VARYING WS-LINE-ITEM-COUNT FROM 1 BY 1
               UNTIL WS-LINE-ITEM-COUNT > 1
               
               CALL WS-INVENTORY-SVC USING WS-ITEM-ID
                                           WS-ITEM-QUANTITY
                                      BY REFERENCE WS-INVENTORY-OK
                   ON EXCEPTION
                       MOVE 002 TO WS-EXCEPTION-CODE
                       MOVE 'Inventory service error' TO WS-EXCEPTION-MSG
                       MOVE 'Y' TO WS-ROLLBACK-FLAG
                   NOT ON EXCEPTION
                       IF WS-INVENTORY-OK = 'N'
                           DISPLAY 'Item out of stock: ' WS-ITEM-ID
                           MOVE 'Y' TO WS-ROLLBACK-FLAG
                       END-IF
           END-PERFORM
           
           IF WS-ROLLBACK-FLAG = 'Y'
               PERFORM ROLLBACK-ORDER-PROCESS
               STOP RUN
           END-IF.
           
       CALCULATE-PRICING.
           DISPLAY 'Calculating pricing...'
           
      *    CALL pricing calculation service
           CALL WS-PRICING-SVC USING WS-ITEM-PRICE
                                     WS-ITEM-QUANTITY
                                BY REFERENCE WS-TOTAL-AMOUNT
                                            WS-TAX-AMOUNT
                                            WS-SHIPPING-COST
                   RETURNING WS-TOTAL-AMOUNT
                   ON EXCEPTION
                       MOVE 003 TO WS-EXCEPTION-CODE
                       MOVE 'Pricing calculation error' TO WS-EXCEPTION-MSG
                       MOVE 'Y' TO WS-ROLLBACK-FLAG.
           
       PROCESS-PAYMENT.
           DISPLAY 'Processing payment...'
           
      *    CALL payment processing service
           CALL WS-PAYMENT-SVC USING BY REFERENCE WS-CUSTOMER-ID
                                           WS-PAYMENT-METHOD
                                           WS-TOTAL-AMOUNT
                                      BY REFERENCE WS-PAYMENT-OK
                   ON EXCEPTION
                       MOVE 004 TO WS-EXCEPTION-CODE
                       MOVE 'Payment processing error' TO WS-EXCEPTION-MSG
                       MOVE 'Y' TO WS-ROLLBACK-FLAG
                   NOT ON EXCEPTION
                       IF WS-PAYMENT-OK = 'N'
                           MOVE 'Y' TO WS-ROLLBACK-FLAG
                       ELSE
                           MOVE '02' TO WS-ORDER-STATUS
                       END-IF.
           
           IF WS-ROLLBACK-FLAG = 'Y'
               PERFORM ROLLBACK-ORDER-PROCESS
               STOP RUN
           END-IF.
           
       FULFILL-ORDER.
           DISPLAY 'Creating shipment...'
           
      *    CALL fulfillment service to create shipment
           CALL WS-FULFILL-SVC USING BY REFERENCE WS-ORDER-ID
                                           WS-CUSTOMER-ID
                                           WS-ITEM-ID
                                           WS-ITEM-QUANTITY
                                           WS-SHIPPING-ADDR
                                      BY REFERENCE WS-SHIPMENT-ID
                                                    WS-TRACKING-NUMBER
                                                    WS-FULFILLMENT-OK
                   RETURNING WS-SHIPMENT-ID
                   ON EXCEPTION
                       MOVE 005 TO WS-EXCEPTION-CODE
                       MOVE 'Fulfillment service error' TO WS-EXCEPTION-MSG
                       MOVE 'Y' TO WS-ROLLBACK-FLAG.
           
           IF WS-FULFILLMENT-OK = 'Y'
               MOVE '04' TO WS-ORDER-STATUS
           END-IF.
           
       SEND-NOTIFICATIONS.
           DISPLAY 'Sending notifications...'
           
      *    CALL notification service
           CALL WS-NOTIFY-SVC USING BY VALUE WS-ORDER-ID
                                      BY REFERENCE WS-CUSTOMER-ID
                                                    WS-CUSTOMER-NAME
                                                    WS-TRACKING-NUMBER
                   ON EXCEPTION
                       MOVE 006 TO WS-EXCEPTION-CODE
                       DISPLAY 'Notification service error'.
           
       ARCHIVE-ORDER.
           DISPLAY 'Archiving order...'
           
      *    CALL archive service
           CALL WS-ARCHIVE-SVC USING BY REFERENCE WS-ORDER-ID
                                           WS-ORDER-STATUS
                                           WS-TOTAL-AMOUNT
                   ON EXCEPTION
                       DISPLAY 'Archive service error'.
           
       ROLLBACK-ORDER-PROCESS.
           DISPLAY 'Rolling back order...'
           MOVE '99' TO WS-ORDER-STATUS
           DISPLAY 'Exception Code: ' WS-EXCEPTION-CODE
           DISPLAY 'Exception Message: ' WS-EXCEPTION-MSG.
           
       END PROGRAM ORDER-PROCESSING-ENGINE.
