-- 05 Daily cash collected vs instalments falling due, for the last :days days up to :as_of.

WITH RECURSIVE days(day) AS (
    SELECT date(:as_of, '-' || (:days - 1) || ' day')
    UNION ALL
    SELECT date(day, '+1 day') FROM days WHERE day < :as_of
),
collected AS (
    SELECT txn_date AS day, SUM(amount) AS collected, COUNT(*) AS payments
    FROM payments_matched
    WHERE txn_date BETWEEN date(:as_of, '-' || (:days - 1) || ' day') AND :as_of
    GROUP BY txn_date
),
falling_due AS (
    SELECT due_date AS day, SUM(amount_due) AS due, COUNT(*) AS installments
    FROM installments
    WHERE due_date BETWEEN date(:as_of, '-' || (:days - 1) || ' day') AND :as_of
    GROUP BY due_date
)
SELECT d.day,
       COALESCE(c.collected, 0)    AS collected,
       COALESCE(c.payments, 0)     AS payments,
       COALESCE(f.due, 0)          AS due,
       COALESCE(f.installments, 0) AS installments_due
FROM days AS d
LEFT JOIN collected   AS c USING (day)
LEFT JOIN falling_due AS f USING (day)
ORDER BY d.day;
