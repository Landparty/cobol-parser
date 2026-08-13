      *****************************************************************
      * TELLER INQUIRY COMMUNICATION AREA                            *
      * COPYBOOK: TLRCOMM                                            *
      * DESCRIPTION: CICS COMMAREA layout for the online account     *
      * inquiry transaction. Front half is the caller's request      *
      * (account number, teller/branch identification); back half    *
      * is the response the transaction hands back.                  *
      * USED BY: ACCTINQ                                              *
      *****************************************************************
       01  TLR-COMM-AREA.
           05  TLR-REQUEST.
               10  TLR-REQ-ACCT-NUMBER       PIC X(12).
               10  TLR-REQ-TELLER-ID         PIC X(06).
               10  TLR-REQ-BRANCH-CODE       PIC X(04).
           05  TLR-RESPONSE.
               10  TLR-RESP-STATUS-CODE      PIC X(04).
               10  TLR-RESP-ACCT-TYPE        PIC X(03).
               10  TLR-RESP-ACCT-STATUS      PIC X(01).
               10  TLR-RESP-CURR-BALANCE     PIC S9(13)V99 COMP-3.
               10  TLR-RESP-AVAIL-BALANCE    PIC S9(13)V99 COMP-3.
               10  TLR-RESP-HOLD-AMOUNT      PIC S9(11)V99 COMP-3.
               10  TLR-RESP-MESSAGE          PIC X(40).
