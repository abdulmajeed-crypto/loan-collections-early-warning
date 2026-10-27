-- 06 Partner early-warning: compare each partner's recent late-payment rate with its own baseline.
-- An instalment is late if it is not fully paid within :grace days of its due date.
-- recent   = instalments due 7-21 days ago (grace period over)
-- baseline = instalments due in the 90 days before that
-- Alert when the recent rate doubles the partner's own normal, or is very high in absolute terms
-- (a long problem raises the baseline, so a relative test alone can miss it).
-- Params: :as_of, :grace

WITH graded AS (
    SELECT l.partner_id,
           CASE WHEN c.covered_date IS NULL
                  OR c.covered_date > date(c.due_date, '+' || :grace || ' day') THEN 1 ELSE 0 END AS late,
           CASE WHEN c.due_date BETWEEN date(:as_of, '-' || (:grace + 14)  || ' day')
                                    AND date(:as_of, '-' || :grace         || ' day') THEN 'recent'
                WHEN c.due_date BETWEEN date(:as_of, '-' || (:grace + 104) || ' day')
                                    AND date(:as_of, '-' || (:grace + 15)  || ' day') THEN 'baseline'
           END AS period
    FROM installment_coverage AS c
    JOIN loans AS l USING (loan_id)
),
rates AS (
    SELECT partner_id,
           SUM(CASE WHEN period = 'recent'   THEN 1 ELSE 0 END)    AS recent_n,
           AVG(CASE WHEN period = 'recent'   THEN late END)        AS recent_late_rate,
           SUM(CASE WHEN period = 'baseline' THEN 1 ELSE 0 END)    AS baseline_n,
           AVG(CASE WHEN period = 'baseline' THEN late END)        AS baseline_late_rate
    FROM graded
    WHERE period IS NOT NULL
    GROUP BY partner_id
),
book AS (
    SELECT partner_id,
           SUM(CASE WHEN bucket NOT IN ('Closed', 'Written off') THEN outstanding ELSE 0 END)              AS outstanding,
           SUM(CASE WHEN bucket NOT IN ('Closed', 'Written off') THEN 1 ELSE 0 END)                        AS active_loans,
           SUM(CASE WHEN bucket NOT IN ('Closed', 'Written off') AND dpd > 30 THEN outstanding ELSE 0 END) AS par30_amount
    FROM loan_status
    GROUP BY partner_id
)
SELECT p.partner_id, p.sector, p.city, p.agent_id,
       b.active_loans, b.outstanding,
       CASE WHEN b.outstanding > 0 THEN b.par30_amount * 1.0 / b.outstanding ELSE 0 END AS par30,
       r.recent_n, COALESCE(r.recent_late_rate, 0)   AS recent_late_rate,
       r.baseline_n, COALESCE(r.baseline_late_rate, 0) AS baseline_late_rate,
       CASE WHEN r.recent_n >= 15 AND (
                    (r.recent_late_rate >= 0.15 AND r.recent_late_rate >= 2.0 * r.baseline_late_rate)
                 OR r.recent_late_rate >= 0.40
                 OR r.recent_late_rate - r.baseline_late_rate >= 0.20) THEN 'Alert'
            WHEN r.recent_n >= 15 AND r.recent_late_rate >= 0.10
                 AND r.recent_late_rate >= 1.5 * r.baseline_late_rate THEN 'Watch'
            ELSE 'Normal' END AS status
FROM partners AS p
LEFT JOIN book  AS b USING (partner_id)
LEFT JOIN rates AS r USING (partner_id)
ORDER BY CASE status WHEN 'Alert' THEN 0 WHEN 'Watch' THEN 1 ELSE 2 END, par30 DESC;
