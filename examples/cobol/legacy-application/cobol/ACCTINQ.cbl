       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTINQ.
      *****************************************************************
      * PROGRAM:   ACCTINQ                                            *
      * PURPOSE:   ONLINE ACCOUNT BALANCE INQUIRY (CICS TRANSACTION)  *
      *            COMMAREA-DRIVEN SERVICE CALLED BY TELLER/API       *
      *            FRONT ENDS TO RETURN CURRENT BALANCE, AVAILABLE    *
      *            BALANCE, HOLD AMOUNT, AND ACCOUNT STATUS.          *
      * INPUT:     DFHCOMMAREA - TLR-COMM-AREA REQUEST HALF           *
      *            (ACCOUNT NUMBER, TELLER ID, BRANCH CODE)           *
      * OUTPUT:    DFHCOMMAREA - TLR-COMM-AREA RESPONSE HALF          *
      * FILES:     ACCTMST (CICS FCT-DEFINED VSAM KSDS ON ACCT-NUMBER)*
      * TRANSID:   ACIQ                                                *
      * PCT:       ACIQ -> ACCTINQ (CICS-DEFINED, NO BATCH JCL)       *
      * FREQ:      ON DEMAND - ONLINE TELLER / API GATEWAY            *
      *****************************************************************

       ENVIRONMENT DIVISION.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY WSCOMMON.
           COPY ERRORCD.
           COPY ACCTMAST.

       01  WS-CICS-RESP              PIC S9(08) COMP.
       01  WS-ACCT-KEY               PIC X(12).

       LINKAGE SECTION.
       01  DFHCOMMAREA.
           COPY TLRCOMM.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           EXEC CICS HANDLE CONDITION
               NOTFND(2000-NOTFND-HANDLER)
               ERROR(9999-ABEND-HANDLER)
           END-EXEC

           IF EIBCALEN = ZERO
               MOVE SPACES TO TLR-COMM-AREA
               MOVE ERR-PROGRAM-ERROR TO TLR-RESP-STATUS-CODE
               MOVE 'NO COMMAREA RECEIVED ON ACIQ TRANSACTION'
                   TO TLR-RESP-MESSAGE
           ELSE
               MOVE TLR-REQ-ACCT-NUMBER TO WS-ACCT-KEY
               PERFORM 1000-READ-ACCOUNT-MASTER
               PERFORM 1500-BUILD-RESPONSE
           END-IF

           EXEC CICS RETURN
               COMMAREA(TLR-COMM-AREA)
               LENGTH(LENGTH OF TLR-COMM-AREA)
           END-EXEC.

       1000-READ-ACCOUNT-MASTER.
           EXEC CICS READ
               FILE('ACCTMST')
               INTO(ACCOUNT-MASTER-RECORD)
               RIDFLD(WS-ACCT-KEY)
               RESP(WS-CICS-RESP)
           END-EXEC

           EVALUATE WS-CICS-RESP
               WHEN DFHRESP(NORMAL)
                   MOVE ERR-SUCCESS TO TLR-RESP-STATUS-CODE
               WHEN DFHRESP(NOTFND)
                   MOVE ERR-ACCT-NOT-FOUND TO TLR-RESP-STATUS-CODE
                   MOVE SPACES TO ACCOUNT-MASTER-RECORD
               WHEN OTHER
                   MOVE ERR-DB2-ERROR TO TLR-RESP-STATUS-CODE
                   MOVE SPACES TO ACCOUNT-MASTER-RECORD
           END-EVALUATE.

       1500-BUILD-RESPONSE.
           MOVE ACCT-TYPE           TO TLR-RESP-ACCT-TYPE
           MOVE ACCT-STATUS         TO TLR-RESP-ACCT-STATUS
           MOVE ACCT-CURRENT-BALANCE   TO TLR-RESP-CURR-BALANCE
           MOVE ACCT-AVAILABLE-BALANCE TO TLR-RESP-AVAIL-BALANCE
           MOVE ACCT-HOLD-AMOUNT    TO TLR-RESP-HOLD-AMOUNT
           IF TLR-RESP-STATUS-CODE = ERR-SUCCESS
               MOVE 'ACCOUNT INQUIRY SUCCESSFUL' TO TLR-RESP-MESSAGE
           ELSE
               MOVE 'ACCOUNT NOT FOUND OR READ ERROR'
                   TO TLR-RESP-MESSAGE
           END-IF.

       2000-NOTFND-HANDLER.
           MOVE SPACES TO TLR-COMM-AREA
           MOVE ERR-ACCT-NOT-FOUND TO TLR-RESP-STATUS-CODE
           MOVE 'ACCOUNT NOT FOUND' TO TLR-RESP-MESSAGE
           EXEC CICS RETURN
               COMMAREA(TLR-COMM-AREA)
               LENGTH(LENGTH OF TLR-COMM-AREA)
           END-EXEC.

       9999-ABEND-HANDLER.
           EXEC CICS ABEND
               ABCODE('ACIQ')
           END-EXEC.
