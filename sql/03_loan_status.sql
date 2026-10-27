-- 03 Status of every loan on a given date: balance, amount overdue, days past due (DPD), bucket.
-- Params: :as_of (YYYY-MM-DD), :tol, :write_off_dpd
-- DPD = days since the oldest instalment that is still not fully covered by payments made up to :as_of.
-- Amount overdue counts only instalments due before :as_of (one due today is not late yet).
-- Write-off is permanent: once any instalment went more than :write_off_dpd days unpaid, the loan stays
-- written off even if money arrives later (that money is a recovery, not a return to the active book).

WITH book AS (
    SELECT * FROM loans WHERE disb_date <= :as_of
),
schedule AS (
    SELECT i.loan_id, i.inst_no, i.due_date, i.amount_due,
           SUM(i.amount_due) OVER (PARTITION BY i.loan_id ORDER BY i.inst_no) AS cum_due
    FROM installments AS i
    JOIN book AS b USING (loan_id)
),
paid AS (
    SELECT loan_id, SUM(amount) AS paid_to_date, MAX(txn_date) AS last_payment_date
    FROM payments_matched
    WHERE txn_date <= :as_of
    GROUP BY loan_id
),
due_so_far AS (
    SELECT loan_id, SUM(amount_due) AS due_to_date
    FROM schedule
    WHERE due_date < :as_of
    GROUP BY loan_id
),
written_off AS (
    SELECT DISTINCT c.loan_id
    FROM installment_coverage AS c
    JOIN book AS b USING (loan_id)
    WHERE date(c.due_date, '+' || (:write_off_dpd + 1) || ' day') <= :as_of
      AND (c.covered_date IS NULL OR c.covered_date > date(c.due_date, '+' || :write_off_dpd || ' day'))
),
uncovered AS (
    SELECT s.loan_id,
           MIN(CASE WHEN s.due_date <= :as_of THEN s.due_date END) AS oldest_unpaid_due,
           MIN(CASE WHEN s.due_date >  :as_of THEN s.due_date END) AS next_due_date
    FROM schedule AS s
    LEFT JOIN paid AS p USING (loan_id)
    WHERE s.cum_due - COALESCE(p.paid_to_date, 0) > :tol
    GROUP BY s.loan_id
),
status AS (
    SELECT b.loan_id, b.borrower_id, b.partner_id, b.disb_date, b.principal, b.tenor_months,
           b.installment, b.total_repayable,
           COALESCE(p.paid_to_date, 0)                                   AS paid_to_date,
           b.total_repayable - COALESCE(p.paid_to_date, 0)               AS outstanding,
           CASE WHEN COALESCE(d.due_to_date, 0) - COALESCE(p.paid_to_date, 0) > :tol
                THEN COALESCE(d.due_to_date, 0) - COALESCE(p.paid_to_date, 0) ELSE 0 END AS amount_overdue,
           CASE WHEN u.oldest_unpaid_due IS NULL THEN 0
                ELSE CAST(julianday(:as_of) - julianday(u.oldest_unpaid_due) AS INTEGER) END AS dpd,
           p.last_payment_date,
           u.next_due_date,
           CASE WHEN w.loan_id IS NOT NULL THEN 1 ELSE 0 END AS is_written_off
    FROM book AS b
    LEFT JOIN paid       AS p USING (loan_id)
    LEFT JOIN due_so_far AS d USING (loan_id)
    LEFT JOIN uncovered  AS u USING (loan_id)
    LEFT JOIN written_off AS w USING (loan_id)
)
SELECT status.*,
       CASE WHEN outstanding <= :tol           THEN 'Closed'
            WHEN is_written_off = 1            THEN 'Written off'
            WHEN dpd = 0                       THEN 'Current'
            WHEN dpd <= 30                     THEN '1-30'
            WHEN dpd <= 60                     THEN '31-60'
            WHEN dpd <= 90                     THEN '61-90'
            ELSE                                    '91-180' END AS bucket
FROM status;
