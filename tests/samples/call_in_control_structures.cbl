      *****************************************************************
      * Real-World COBOL Example: CALL in Control Structures
      * Demonstrates: CALL statements inside various control flow
      * Use Case: Order processing with conditional service calls
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALL-IN-CONTROL-STRUCTURES.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ORDER-DATA.
           05  WS-ORDER-ID         PIC 9(12).
           05  WS-CUSTOMER-ID      PIC 9(10).
           05  WS-PRODUCT-CODE     PIC X(20).
           05  WS-QUANTITY         PIC 9(5).
           05  WS-AMOUNT           PIC 9(9)V99 COMP-3.
           
       01  WS-CONTROL-DATA.
           05  WS-STATUS-CODE      PIC 99.
           05  WS-PRIORITY-LEVEL   PIC 9.
           05  WS-COUNTER          PIC 9(3).
           05  WS-INDEX            PIC 9(3).
           
       01  WS-FLAGS.
           05  WS-APPROVED-FLAG    PIC X VALUE 'N'.
           05  WS-URGENT-FLAG      PIC X VALUE 'N'.
           05  WS-VIP-FLAG         PIC X VALUE 'N'.
           
       PROCEDURE DIVISION.
       MAIN-CONTROL-FLOW.
           DISPLAY 'CALL in Control Structures'.
           PERFORM IF-EXAMPLES.
           PERFORM PERFORM-EXAMPLES.
           PERFORM EVALUATE-EXAMPLES.
           PERFORM NESTED-EXAMPLES.
           STOP RUN.
           
       IF-EXAMPLES.
      *    CALL inside simple IF block
           IF WS-AMOUNT > 1000.00
               CALL 'HIGH-VALUE-CHECK' USING WS-AMOUNT
                                             WS-STATUS-CODE
           END-IF.
           
      *    CALL inside IF with multiple statements
           IF WS-APPROVED-FLAG = 'Y'
               DISPLAY 'Processing approved order'
               CALL 'PROCESS-ORDER' USING WS-ORDER-ID
                                          WS-AMOUNT
               DISPLAY 'Order processed'
           END-IF.
           
      *    CALL inside ELSE block
           IF WS-AMOUNT < 100.00
               CALL 'SMALL-ORDER-PROCESS' USING WS-ORDER-ID
           ELSE
               CALL 'STANDARD-ORDER-PROCESS' USING WS-ORDER-ID
           END-IF.
           
      *    CALL in both IF and ELSE
           IF WS-VIP-FLAG = 'Y'
               CALL 'VIP-PROCESSING' USING WS-CUSTOMER-ID
                                           WS-ORDER-ID
           ELSE
               CALL 'REGULAR-PROCESSING' USING WS-CUSTOMER-ID
                                               WS-ORDER-ID
           END-IF.
           
      *    CALL inside nested IF
           IF WS-APPROVED-FLAG = 'Y'
               IF WS-AMOUNT > 5000.00
                   CALL 'MANAGER-APPROVAL' USING WS-ORDER-ID
                                                 WS-AMOUNT
               END-IF
           END-IF.
           
      *    CALL inside nested IF-ELSE
           IF WS-PRIORITY-LEVEL = 1
               IF WS-URGENT-FLAG = 'Y'
                   CALL 'URGENT-HIGH-PRIORITY' USING WS-ORDER-ID
               ELSE
                   CALL 'NORMAL-HIGH-PRIORITY' USING WS-ORDER-ID
               END-IF
           ELSE
               IF WS-URGENT-FLAG = 'Y'
                   CALL 'URGENT-LOW-PRIORITY' USING WS-ORDER-ID
               ELSE
                   CALL 'NORMAL-LOW-PRIORITY' USING WS-ORDER-ID
               END-IF
           END-IF.
           
      *    CALL with complex condition
           IF WS-AMOUNT > 1000.00 AND WS-VIP-FLAG = 'Y'
               CALL 'VIP-HIGH-VALUE' USING WS-CUSTOMER-ID
                                           WS-AMOUNT
           END-IF.
           
       PERFORM-EXAMPLES.
      *    CALL inside PERFORM UNTIL
           PERFORM UNTIL WS-STATUS-CODE = 0
               CALL 'RETRY-SERVICE' USING WS-ORDER-ID
                                          WS-STATUS-CODE
           END-PERFORM.
           
      *    CALL inside PERFORM VARYING
           PERFORM VARYING WS-COUNTER FROM 1 BY 1
               UNTIL WS-COUNTER > 10
               CALL 'BATCH-ITEM-PROCESS' USING WS-COUNTER
                                               WS-ORDER-ID
           END-PERFORM.
           
      *    CALL inside PERFORM VARYING with condition
           PERFORM VARYING WS-INDEX FROM 1 BY 1
               UNTIL WS-INDEX > 100 OR WS-STATUS-CODE NOT = 0
               CALL 'SEQUENTIAL-PROCESS' USING WS-INDEX
                                               WS-STATUS-CODE
           END-PERFORM.
           
      *    CALL inside PERFORM THRU
           PERFORM PROCESS-ITEM THRU PROCESS-ITEM-END.
           
       PROCESS-ITEM.
           CALL 'ITEM-VALIDATION' USING WS-PRODUCT-CODE
                                        WS-QUANTITY.
           
       PROCESS-ITEM-CONTINUE.
           CALL 'ITEM-PRICING' USING WS-PRODUCT-CODE
                                     WS-QUANTITY
                                     WS-AMOUNT.
           
       PROCESS-ITEM-END.
           CALL 'ITEM-FINALIZATION' USING WS-ORDER-ID
                                          WS-AMOUNT.
           
       EVALUATE-EXAMPLES.
      *    CALL inside EVALUATE WHEN
           EVALUATE WS-PRIORITY-LEVEL
               WHEN 1
                   CALL 'PRIORITY-ONE-PROCESS' USING WS-ORDER-ID
               WHEN 2
                   CALL 'PRIORITY-TWO-PROCESS' USING WS-ORDER-ID
               WHEN 3
                   CALL 'PRIORITY-THREE-PROCESS' USING WS-ORDER-ID
               WHEN OTHER
                   CALL 'DEFAULT-PROCESS' USING WS-ORDER-ID
           END-EVALUATE.
           
      *    CALL inside EVALUATE with multiple statements
           EVALUATE WS-STATUS-CODE
               WHEN 0
                   DISPLAY 'Success status'
                   CALL 'SUCCESS-HANDLER' USING WS-ORDER-ID
               WHEN 1
                   DISPLAY 'Warning status'
                   CALL 'WARNING-HANDLER' USING WS-ORDER-ID
                                                WS-STATUS-CODE
               WHEN OTHER
                   DISPLAY 'Error status'
                   CALL 'ERROR-HANDLER' USING WS-ORDER-ID
                                              WS-STATUS-CODE
           END-EVALUATE.
           
      *    CALL inside EVALUATE TRUE
           EVALUATE TRUE
               WHEN WS-AMOUNT > 10000.00
                   CALL 'LARGE-ORDER-PROCESS' USING WS-ORDER-ID
                                                    WS-AMOUNT
               WHEN WS-AMOUNT > 1000.00
                   CALL 'MEDIUM-ORDER-PROCESS' USING WS-ORDER-ID
                                                     WS-AMOUNT
               WHEN OTHER
                   CALL 'SMALL-ORDER-PROCESS' USING WS-ORDER-ID
                                                    WS-AMOUNT
           END-EVALUATE.
           
       NESTED-EXAMPLES.
      *    CALL inside nested PERFORM loops
           PERFORM VARYING WS-COUNTER FROM 1 BY 1
               UNTIL WS-COUNTER > 5
               PERFORM VARYING WS-INDEX FROM 1 BY 1
                   UNTIL WS-INDEX > 3
                   CALL 'NESTED-PROCESS' USING WS-COUNTER
                                               WS-INDEX
                                               WS-ORDER-ID
               END-PERFORM
           END-PERFORM.
           
      *    CALL inside IF within PERFORM
           PERFORM VARYING WS-COUNTER FROM 1 BY 1
               UNTIL WS-COUNTER > 10
               IF WS-COUNTER > 5
                   CALL 'SECOND-HALF-PROCESS' USING WS-COUNTER
               ELSE
                   CALL 'FIRST-HALF-PROCESS' USING WS-COUNTER
               END-IF
           END-PERFORM.
           
      *    CALL inside EVALUATE within IF
           IF WS-APPROVED-FLAG = 'Y'
               EVALUATE WS-PRIORITY-LEVEL
                   WHEN 1
                       CALL 'APPROVED-PRIORITY-ONE' USING WS-ORDER-ID
                   WHEN 2
                       CALL 'APPROVED-PRIORITY-TWO' USING WS-ORDER-ID
                   WHEN OTHER
                       CALL 'APPROVED-DEFAULT' USING WS-ORDER-ID
               END-EVALUATE
           END-IF.
           
      *    CALL inside IF within EVALUATE
           EVALUATE WS-STATUS-CODE
               WHEN 0
                   IF WS-VIP-FLAG = 'Y'
                       CALL 'VIP-SUCCESS-HANDLER' USING WS-CUSTOMER-ID
                   ELSE
                       CALL 'REGULAR-SUCCESS-HANDLER' USING WS-CUSTOMER-ID
                   END-IF
               WHEN OTHER
                   CALL 'ERROR-HANDLER' USING WS-STATUS-CODE
           END-EVALUATE.
           
      *    CALL inside PERFORM within EVALUATE
           EVALUATE WS-PRIORITY-LEVEL
               WHEN 1
                   PERFORM VARYING WS-COUNTER FROM 1 BY 1
                       UNTIL WS-COUNTER > 3
                       CALL 'PRIORITY-ONE-BATCH' USING WS-COUNTER
                                                        WS-ORDER-ID
                   END-PERFORM
               WHEN OTHER
                   CALL 'STANDARD-BATCH' USING WS-ORDER-ID
           END-EVALUATE.
           
      *    Triple nested: PERFORM > IF > EVALUATE with CALL
           PERFORM VARYING WS-COUNTER FROM 1 BY 1
               UNTIL WS-COUNTER > 5
               IF WS-COUNTER > 2
                   EVALUATE WS-PRIORITY-LEVEL
                       WHEN 1
                           CALL 'COMPLEX-NESTED-PROCESS' USING WS-COUNTER
                                                               WS-PRIORITY-LEVEL
                                                               WS-ORDER-ID
                   END-EVALUATE
               END-IF
           END-PERFORM.
           
       END PROGRAM CALL-IN-CONTROL-STRUCTURES.
