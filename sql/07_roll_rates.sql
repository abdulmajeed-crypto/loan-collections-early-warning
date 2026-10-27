-- 07 Roll rates: where did loans in each DPD bucket 30 days ago end up today?
-- Compares the snapshot 30 days ago (loan_status_prev) with today's (loan_status).

SELECT p.bucket              AS from_bucket,
       t.bucket              AS to_bucket,
       COUNT(*)              AS loans,
       SUM(p.outstanding)    AS outstanding_then
FROM loan_status_prev AS p
JOIN loan_status      AS t USING (loan_id)
WHERE p.bucket NOT IN ('Closed', 'Written off')
GROUP BY p.bucket, t.bucket;
