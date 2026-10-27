-- 04 Portfolio quality from a loan-status snapshot ({status} is filled in by the pipeline).
-- PAR-n (portfolio at risk) = outstanding balance of loans more than n days past due
--                             / outstanding balance of the active portfolio.
-- Active portfolio excludes closed and written-off loans.

SELECT
    SUM(CASE WHEN bucket NOT IN ('Closed', 'Written off') THEN outstanding ELSE 0 END)            AS portfolio_outstanding,
    SUM(CASE WHEN bucket NOT IN ('Closed', 'Written off') THEN 1 ELSE 0 END)                      AS active_loans,
    SUM(CASE WHEN bucket NOT IN ('Closed', 'Written off') AND dpd > 0  THEN outstanding ELSE 0 END) AS par1_amount,
    SUM(CASE WHEN bucket NOT IN ('Closed', 'Written off') AND dpd > 30 THEN outstanding ELSE 0 END) AS par30_amount,
    SUM(CASE WHEN bucket NOT IN ('Closed', 'Written off') AND dpd > 90 THEN outstanding ELSE 0 END) AS par90_amount,
    SUM(CASE WHEN bucket NOT IN ('Closed', 'Written off') THEN amount_overdue ELSE 0 END)          AS amount_overdue,
    SUM(CASE WHEN bucket = 'Written off' THEN outstanding ELSE 0 END)                             AS written_off_amount,
    SUM(CASE WHEN bucket = 'Written off' THEN 1 ELSE 0 END)                                       AS written_off_loans,
    SUM(CASE WHEN bucket = 'Closed' THEN 1 ELSE 0 END)                                            AS closed_loans
FROM {status};
