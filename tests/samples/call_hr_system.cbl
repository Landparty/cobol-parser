      *****************************************************************
      * Real-World COBOL Example: Human Resources System
      * Demonstrates: Dynamic CALL, complex parameter passing
      * Use Case: Employee management and benefits processing
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HR-MANAGEMENT-SYSTEM.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-EMPLOYEE-RECORD.
           05  WS-EMP-ID           PIC 9(6).
           05  WS-EMP-NAME         PIC X(40).
           05  WS-DEPARTMENT       PIC X(20).
           05  WS-POSITION         PIC X(25).
           05  WS-HIRE-DATE        PIC 9(8).
           05  WS-SALARY           PIC 9(9)V99 COMP-3.
           05  WS-SALARY-GRADE     PIC X(3).
           
       01  WS-BENEFITS-INFO.
           05  WS-HEALTH-PLAN      PIC X(10).
           05  WS-DENTAL-PLAN      PIC X(10).
           05  WS-VISION-PLAN      PIC X(10).
           05  WS-RETIREMENT-PLAN  PIC X(10).
           05  WS-EMPLOYEE-CONTRIB PIC 9(6)V99 COMP-3.
           05  WS-EMPLOYER-CONTRIB PIC 9(6)V99 COMP-3.
           
       01  WS-PERFORMANCE-DATA.
           05  WS-REVIEW-DATE      PIC 9(8).
           05  WS-RATING           PIC 9.
           05  WS-REVIEW-NOTES     PIC X(100).
           05  WS-RAISE-PERCENT    PIC 9V99.
           05  WS-NEW-SALARY       PIC 9(9)V99 COMP-3.
           
       01  WS-LEAVE-MANAGEMENT.
           05  WS-VACATION-DAYS    PIC 999.
           05  WS-SICK-DAYS        PIC 999.
           05  WS-PERSONAL-DAYS    PIC 999.
           05  WS-UNUSED-VACATION  PIC 999.
           05  WS-LEAVE-TYPE       PIC X(10).
           05  WS-LEAVE-DAYS       PIC 999.
           05  WS-LEAVE-START      PIC 9(8).
           05  WS-LEAVE-END        PIC 9(8).
           
       01  WS-PROCESSING-FLAGS.
           05  WS-ELIGIBLE-FLAG    PIC X VALUE 'N'.
           05  WS-VERIFIED-FLAG    PIC X VALUE 'N'.
           05  WS-PROCESSED-FLAG   PIC X VALUE 'N'.
           05  WS-ERROR-FLAG       PIC X VALUE 'N'.
           
       01  WS-PROCESSING-CODES.
           05  WS-OPERATION        PIC X(15).
           05  WS-RESULT-CODE      PIC 999.
           05  WS-MESSAGE          PIC X(100).
           
       01  WS-SERVICE-DIRECTORY.
           05  WS-VALIDATION-SVC   PIC X(20) VALUE 'VALIDATE-EMPLOYEE'.
           05  WS-BENEFITS-SVC     PIC X(20) VALUE 'ENROLL-BENEFITS'.
           05  WS-REVIEW-SVC       PIC X(20) VALUE 'PROCESS-REVIEW'.
           05  WS-SALARY-SVC       PIC X(20) VALUE 'UPDATE-SALARY'.
           05  WS-LEAVE-SVC        PIC X(20) VALUE 'MANAGE-LEAVE'.
           05  WS-TAX-SVC          PIC X(20) VALUE 'CALC-TAX'.
           05  WS-COMPLIANCE-SVC   PIC X(20) VALUE 'CHECK-COMPLIANCE'.
           05  WS-REPORT-SVC       PIC X(20) VALUE 'GENERATE-REPORT'.
           
       PROCEDURE DIVISION.
       MAIN-HR-PROCESS.
           DISPLAY 'HR Management System Started'
           PERFORM LOAD-EMPLOYEE-DATA
           PERFORM PROCESS-ENROLLMENT
           PERFORM PROCESS-PERFORMANCE-REVIEW
           PERFORM PROCESS-LEAVE-REQUEST
           PERFORM GENERATE-HR-REPORT
           DISPLAY 'HR Processing Complete'
           STOP RUN.
           
       LOAD-EMPLOYEE-DATA.
           MOVE 100025 TO WS-EMP-ID
           MOVE 'Sarah Johnson' TO WS-EMP-NAME
           MOVE 'Engineering' TO WS-DEPARTMENT
           MOVE 'Senior Developer' TO WS-POSITION
           MOVE 20150310 TO WS-HIRE-DATE
           MOVE 125000.00 TO WS-SALARY
           MOVE 'E-3' TO WS-SALARY-GRADE.
           
       PROCESS-ENROLLMENT.
           DISPLAY 'Processing benefit enrollment...'
           
      *    CALL validation service first
           CALL WS-VALIDATION-SVC USING WS-EMP-ID
                                        WS-HIRE-DATE
                                   BY REFERENCE WS-ELIGIBLE-FLAG
                   ON EXCEPTION
                       MOVE 'Y' TO WS-ERROR-FLAG
                       MOVE 001 TO WS-RESULT-CODE
           
           IF WS-ELIGIBLE-FLAG = 'Y'
      *        CALL benefits enrollment service
               CALL WS-BENEFITS-SVC USING BY REFERENCE WS-EMP-ID
                                              WS-EMP-NAME
                                              WS-SALARY
                                         BY REFERENCE WS-HEALTH-PLAN
                                                       WS-DENTAL-PLAN
                                                       WS-VISION-PLAN
                                                       WS-RETIREMENT-PLAN
                                                       WS-EMPLOYEE-CONTRIB
                                                       WS-EMPLOYER-CONTRIB
                   RETURNING WS-PROCESSED-FLAG
                   ON EXCEPTION
                       MOVE 'Y' TO WS-ERROR-FLAG
                       MOVE 002 TO WS-RESULT-CODE
                   NOT ON EXCEPTION
                       IF WS-PROCESSED-FLAG = 'Y'
                           DISPLAY 'Enrollment completed'
                       END-IF
           ELSE
               DISPLAY 'Employee not yet eligible for benefits'
           END-IF.
           
       PROCESS-PERFORMANCE-REVIEW.
           DISPLAY 'Processing performance review...'
           
           MOVE 20240115 TO WS-REVIEW-DATE
           MOVE 4 TO WS-RATING
           MOVE 'Excellent performer' TO WS-REVIEW-NOTES
           MOVE 3.50 TO WS-RAISE-PERCENT
           
      *    CALL performance review service
           CALL WS-REVIEW-SVC USING BY REFERENCE WS-EMP-ID
                                        WS-REVIEW-DATE
                                        WS-RATING
                                        WS-REVIEW-NOTES
                                   BY REFERENCE WS-PROCESSED-FLAG
                   ON EXCEPTION
                       MOVE 'Y' TO WS-ERROR-FLAG
                       MOVE 003 TO WS-RESULT-CODE
           
           IF WS-PROCESSED-FLAG = 'Y'
      *        CALL salary update service
               CALL WS-SALARY-SVC USING BY REFERENCE WS-EMP-ID
                                             WS-SALARY
                                             WS-RAISE-PERCENT
                                        BY REFERENCE WS-NEW-SALARY
                   RETURNING WS-RESULT-CODE
                   ON EXCEPTION
                       MOVE 'Y' TO WS-ERROR-FLAG
                       MOVE 004 TO WS-RESULT-CODE
                   NOT ON EXCEPTION
                       MOVE WS-NEW-SALARY TO WS-SALARY
                       DISPLAY 'Salary updated to: ' WS-NEW-SALARY
           END-IF.
           
       PROCESS-LEAVE-REQUEST.
           DISPLAY 'Processing leave request...'
           
           MOVE 'VACATION' TO WS-LEAVE-TYPE
           MOVE 5 TO WS-LEAVE-DAYS
           MOVE 20240201 TO WS-LEAVE-START
           MOVE 20240205 TO WS-LEAVE-END
           
      *    CALL leave management service
           CALL WS-LEAVE-SVC USING BY REFERENCE WS-EMP-ID
                                        WS-LEAVE-TYPE
                                        WS-LEAVE-DAYS
                                        WS-LEAVE-START
                                        WS-LEAVE-END
                                   BY REFERENCE WS-VERIFIED-FLAG
                   ON EXCEPTION
                       MOVE 'Y' TO WS-ERROR-FLAG
                       MOVE 005 TO WS-RESULT-CODE
                   NOT ON EXCEPTION
                       IF WS-VERIFIED-FLAG = 'Y'
                           DISPLAY 'Leave approved'
                       END-IF.
           
       GENERATE-HR-REPORT.
           DISPLAY 'Generating HR report...'
           
      *    CALL compliance check
           CALL WS-COMPLIANCE-SVC USING BY REFERENCE WS-EMP-ID
                                             WS-RESULT-CODE
                   ON EXCEPTION
                       DISPLAY 'Compliance check failed'
           
      *    CALL report generation service
           CALL WS-REPORT-SVC USING BY REFERENCE WS-EMP-ID
                                        WS-EMP-NAME
                                        WS-DEPARTMENT
                                        WS-SALARY
                                        WS-HEALTH-PLAN
                                        WS-RETIREMENT-PLAN
                   RETURNING WS-MESSAGE
                   ON EXCEPTION
                       DISPLAY 'Report generation failed'
                   NOT ON EXCEPTION
                       DISPLAY 'Report generated: ' WS-MESSAGE.
           
       END PROGRAM HR-MANAGEMENT-SYSTEM.
