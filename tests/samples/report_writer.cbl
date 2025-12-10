      *****************************************************************
      * Report Writer Module
      * Tests: REPORT SECTION, RD, control breaks, summary reports
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. REPORTWR.
       
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INPUT-FILE ASSIGN TO 'SALES.DAT'
               ORGANIZATION IS SEQUENTIAL.
               
           SELECT REPORT-FILE ASSIGN TO 'REPORT.TXT'
               ORGANIZATION IS SEQUENTIAL.
               
       DATA DIVISION.
       FILE SECTION.
       FD  INPUT-FILE.
       01  INPUT-RECORD.
           05  IN-REGION           PIC X(10).
           05  IN-SALESPERSON      PIC X(20).
           05  IN-PRODUCT          PIC X(15).
           05  IN-QUANTITY         PIC 9(5).
           05  IN-AMOUNT           PIC 9(7)V99.
           
       FD  REPORT-FILE
           REPORT IS SALES-REPORT.
           
       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG             PIC X VALUE 'N'.
           88  EOF-REACHED         VALUE 'Y'.
           
       01  WS-PAGE-NUMBER          PIC 9(3) VALUE 1.
       01  WS-LINE-COUNT           PIC 9(2) VALUE ZERO.
       
       REPORT SECTION.
       RD  SALES-REPORT
           CONTROLS ARE FINAL
                        IN-REGION
                        IN-SALESPERSON
           PAGE LIMIT IS 60 LINES
           HEADING 1
           FIRST DETAIL 10
           LAST DETAIL 50
           FOOTING 55.
           
       01  TYPE IS PAGE HEADING.
           05  LINE NUMBER IS 1.
               10  COLUMN 1        PIC X(20) VALUE 'SALES REPORT'.
               10  COLUMN 50       PIC X(6) VALUE 'PAGE: '.
               10  COLUMN 56       PIC ZZ9 SOURCE WS-PAGE-NUMBER.
               
           05  LINE NUMBER IS 2.
               10  COLUMN 1        PIC X(80) VALUE ALL '-'.
               
           05  LINE NUMBER IS 4.
               10  COLUMN 1        PIC X(10) VALUE 'REGION'.
               10  COLUMN 15       PIC X(20) VALUE 'SALESPERSON'.
               10  COLUMN 40       PIC X(15) VALUE 'PRODUCT'.
               10  COLUMN 60       PIC X(10) VALUE 'QUANTITY'.
               10  COLUMN 72       PIC X(8) VALUE 'AMOUNT'.
               
           05  LINE NUMBER IS 5.
               10  COLUMN 1        PIC X(80) VALUE ALL '='.
               
       01  TYPE IS CONTROL HEADING IN-REGION.
           05  LINE NUMBER IS PLUS 2.
               10  COLUMN 1        PIC X(8) VALUE 'REGION: '.
               10  COLUMN 9        PIC X(10) SOURCE IN-REGION.
               
       01  TYPE IS CONTROL HEADING IN-SALESPERSON.
           05  LINE NUMBER IS PLUS 1.
               10  COLUMN 3        PIC X(13) VALUE 'SALESPERSON: '.
               10  COLUMN 16       PIC X(20) SOURCE IN-SALESPERSON.
               
       01  DETAIL-LINE TYPE IS DETAIL.
           05  LINE NUMBER IS PLUS 1.
               10  COLUMN 1        PIC X(10) SOURCE IN-REGION.
               10  COLUMN 15       PIC X(20) SOURCE IN-SALESPERSON.
               10  COLUMN 40       PIC X(15) SOURCE IN-PRODUCT.
               10  COLUMN 60       PIC ZZZ,ZZ9 SOURCE IN-QUANTITY.
               10  COLUMN 70       PIC $$$,$$$,$$9.99 
                   SOURCE IN-AMOUNT.
                   
       01  TYPE IS CONTROL FOOTING IN-SALESPERSON.
           05  LINE NUMBER IS PLUS 1.
               10  COLUMN 40       PIC X(20) VALUE 'SALESPERSON TOTAL: '.
               10  COLUMN 60       PIC ZZZ,ZZ9 
                   SUM IN-QUANTITY
                   RESET ON IN-SALESPERSON.
               10  COLUMN 70       PIC $$$,$$$,$$9.99
                   SUM IN-AMOUNT
                   RESET ON IN-SALESPERSON.
                   
       01  TYPE IS CONTROL FOOTING IN-REGION.
           05  LINE NUMBER IS PLUS 2.
               10  COLUMN 40       PIC X(15) VALUE 'REGION TOTAL: '.
               10  COLUMN 60       PIC ZZZ,ZZ9
                   SUM IN-QUANTITY
                   RESET ON IN-REGION.
               10  COLUMN 70       PIC $$$,$$$,$$9.99
                   SUM IN-AMOUNT
                   RESET ON IN-REGION.
                   
           05  LINE NUMBER IS PLUS 1.
               10  COLUMN 1        PIC X(80) VALUE ALL '-'.
               
       01  TYPE IS CONTROL FOOTING FINAL.
           05  LINE NUMBER IS PLUS 3.
               10  COLUMN 1        PIC X(80) VALUE ALL '='.
               
           05  LINE NUMBER IS PLUS 1.
               10  COLUMN 40       PIC X(15) VALUE 'GRAND TOTAL: '.
               10  COLUMN 60       PIC ZZZ,ZZ9
                   SUM IN-QUANTITY.
               10  COLUMN 70       PIC $$$,$$$,$$9.99
                   SUM IN-AMOUNT.
                   
           05  LINE NUMBER IS PLUS 1.
               10  COLUMN 1        PIC X(80) VALUE ALL '='.
               
       01  TYPE IS PAGE FOOTING.
           05  LINE NUMBER IS 58.
               10  COLUMN 1        PIC X(80) VALUE ALL '-'.
               
           05  LINE NUMBER IS 59.
               10  COLUMN 30       PIC X(20) VALUE 'END OF PAGE'.
               
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN INPUT INPUT-FILE
           OPEN OUTPUT REPORT-FILE
           
           INITIATE SALES-REPORT
           
           MOVE 'N' TO WS-EOF-FLAG
           PERFORM UNTIL EOF-REACHED
               READ INPUT-FILE
                   AT END
                       SET EOF-REACHED TO TRUE
                   NOT AT END
                       GENERATE DETAIL-LINE
               END-READ
           END-PERFORM
           
           TERMINATE SALES-REPORT
           
           CLOSE INPUT-FILE
           CLOSE REPORT-FILE
           
           DISPLAY 'Report generation completed'
           STOP RUN.
           
      *****************************************************************
      * Alternative: Report with USE BEFORE REPORTING
      *****************************************************************
       REPORT SECTION.
       RD  SUMMARY-REPORT
           CONTROLS ARE FINAL IN-REGION
           PAGE LIMIT IS 66 LINES
           HEADING 1
           FIRST DETAIL 8
           LAST DETAIL 60
           FOOTING 63.
           
       01  SUMMARY-HEADING TYPE IS PAGE HEADING.
           05  LINE NUMBER IS 1.
               10  COLUMN 1        PIC X(30) VALUE 'SALES SUMMARY REPORT'.
               
       01  SUMMARY-DETAIL TYPE IS DETAIL.
           05  LINE NUMBER IS PLUS 1.
               10  COLUMN 1        PIC X(10) SOURCE IN-REGION.
               10  COLUMN 15       PIC ZZZ,ZZ9 SUM IN-QUANTITY.
               10  COLUMN 25       PIC $$$,$$$,$$9.99 SUM IN-AMOUNT.
               
       PROCEDURE DIVISION.
       
       DECLARATIVES.
       SUMMARY-REPORT-DECL SECTION.
           USE BEFORE REPORTING SUMMARY-DETAIL.
       BEFORE-REPORTING-PARA.
      *    Custom logic before printing detail line
           IF IN-QUANTITY > 1000
               DISPLAY 'High volume sale: ' IN-REGION
           END-IF.
           
       END DECLARATIVES.
