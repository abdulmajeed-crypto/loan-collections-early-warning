-- 01 Reconcile the raw payment feed against the loan book.
-- Input : payments_raw (everything the payment channels sent), loans
-- Output: payments_matched  (clean, de-duplicated payments applied to a known loan)
--         recon_exceptions   (payments ops must review before they can be applied)

DROP TABLE IF EXISTS payments_ranked;
CREATE TEMP TABLE payments_ranked AS
SELECT p.*,
       ROW_NUMBER() OVER (PARTITION BY txn_id ORDER BY rowid) AS copy_no
FROM payments_raw AS p;

DROP TABLE IF EXISTS payments_matched;
CREATE TABLE payments_matched AS
SELECT r.txn_id, r.txn_date, r.channel, r.reference AS loan_id, r.amount
FROM payments_ranked AS r
JOIN loans AS l ON l.loan_id = r.reference
WHERE r.copy_no = 1;

CREATE INDEX ix_pm_loan ON payments_matched (loan_id, txn_date);

DROP TABLE IF EXISTS recon_exceptions;
CREATE TABLE recon_exceptions AS
SELECT txn_id, txn_date, channel, reference, amount,
       'Duplicate transaction' AS issue,
       'Ignored the repeat; confirm with channel before any refund' AS action
FROM payments_ranked
WHERE copy_no > 1
UNION ALL
SELECT r.txn_id, r.txn_date, r.channel, r.reference, r.amount,
       'Unknown loan reference' AS issue,
       'Money received but not applied; match manually' AS action
FROM payments_ranked AS r
WHERE r.copy_no = 1
  AND NOT EXISTS (SELECT 1 FROM loans AS l WHERE l.loan_id = r.reference)
UNION ALL
SELECT 'LOAN-' || l.loan_id, MAX(m.txn_date), 'Various', l.loan_id,
       SUM(m.amount) - l.total_repayable,
       'Overpaid loan' AS issue,
       'Paid more than owed: likely another borrower''s payment with a wrong reference, or a refund is due' AS action
FROM payments_matched AS m
JOIN loans AS l USING (loan_id)
GROUP BY l.loan_id
HAVING SUM(m.amount) - l.total_repayable > :tol;
