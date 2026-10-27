-- 02 When was each instalment fully paid?
-- Payments are applied oldest-instalment-first: instalment n is covered on the first
-- date the loan's running total of payments reaches the cumulative amount due up to n.
-- Params: :tol (unpaid amounts at or below this count as settled)

DROP TABLE IF EXISTS pay_running;
CREATE TEMP TABLE pay_running AS
SELECT loan_id, txn_date,
       SUM(amount) OVER (PARTITION BY loan_id ORDER BY txn_date, txn_id
                         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cum_paid
FROM payments_matched;

CREATE INDEX ix_pr_loan ON pay_running (loan_id, cum_paid);

DROP TABLE IF EXISTS installment_coverage;
CREATE TABLE installment_coverage AS
WITH schedule AS (
    SELECT loan_id, inst_no, due_date, amount_due,
           SUM(amount_due) OVER (PARTITION BY loan_id ORDER BY inst_no) AS cum_due
    FROM installments
)
SELECT s.loan_id, s.inst_no, s.due_date, s.amount_due, s.cum_due,
       MIN(r.txn_date) AS covered_date
FROM schedule AS s
LEFT JOIN pay_running AS r
       ON r.loan_id = s.loan_id
      AND r.cum_paid >= s.cum_due - :tol
GROUP BY s.loan_id, s.inst_no;

CREATE INDEX ix_ic_loan ON installment_coverage (loan_id, inst_no);
CREATE INDEX ix_ic_due ON installment_coverage (due_date);
