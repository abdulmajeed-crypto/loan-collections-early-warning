"""Checks the SQL logic on a tiny hand-made book where the right answers are known.

Run: python -m unittest discover -s tests -v
"""
import unittest
from datetime import date

import pandas as pd

from src import db

PARTNERS = pd.DataFrame([("P01", "Test employer", "Lahore", "A1")], columns=["partner_id", "sector", "city", "agent_id"])
LOANS = pd.DataFrame([
    # loan, borrower, partner, disbursed, principal, tenor, instalment, total, (hidden profile)
    ("L1", "B1", "P01", date(2026, 1, 10), 9000, 3, 3000, 9000, "x"),   # pays 1st on time, 2nd half, 3rd nothing
    ("L2", "B2", "P01", date(2026, 1, 10), 6000, 2, 3000, 6000, "x"),   # fully paid, plus one duplicate
    ("L3", "B3", "P01", date(2026, 1, 10), 3000, 1, 3000, 3000, "x"),   # overpaid
], columns=["loan_id", "borrower_id", "partner_id", "disb_date", "principal", "tenor_months", "installment",
            "total_repayable", "profile"])
INSTS = pd.DataFrame([
    ("L1", 1, date(2026, 2, 10), 3000), ("L1", 2, date(2026, 3, 10), 3000), ("L1", 3, date(2026, 4, 10), 3000),
    ("L2", 1, date(2026, 2, 10), 3000), ("L2", 2, date(2026, 3, 10), 3000),
    ("L3", 1, date(2026, 2, 10), 3000),
], columns=["loan_id", "inst_no", "due_date", "amount_due"])
PAYS = pd.DataFrame([
    ("T1", date(2026, 2, 9), "JazzCash", "L1", 3000.0),
    ("T2", date(2026, 3, 20), "JazzCash", "L1", 1500.0),
    ("T3", date(2026, 2, 10), "Bank transfer", "L2", 3000.0),
    ("T4", date(2026, 3, 12), "Bank transfer", "L2", 3000.0),
    ("T4", date(2026, 3, 12), "Bank transfer", "L2", 3000.0),     # duplicate feed row
    ("T5", date(2026, 2, 10), "Easypaisa", "L3", 3000.0),
    ("T6", date(2026, 2, 11), "Easypaisa", "L3", 2000.0),         # overpayment
    ("T7", date(2026, 2, 12), "Easypaisa", "LX99", 500.0),        # unknown reference
], columns=["txn_id", "txn_date", "channel", "reference", "amount"])

PARAMS = {"tol": 50, "write_off_dpd": 180}


class SqlLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = db.load(PARTNERS, LOANS, INSTS, PAYS)
        db.run_script(cls.con, "01_reconcile.sql", {"tol": 50})
        db.run_script(cls.con, "02_installment_coverage.sql", {"tol": 50})
        db.materialise(cls.con, "03_loan_status.sql", "loan_status", {"as_of": "2026-04-20", **PARAMS})

    def status(self, loan):
        return pd.read_sql_query("SELECT * FROM loan_status WHERE loan_id = ?", self.con, params=[loan]).iloc[0]

    def test_duplicate_is_ignored_and_reported(self):
        paid = self.con.execute("SELECT SUM(amount) FROM payments_matched WHERE loan_id = 'L2'").fetchone()[0]
        self.assertEqual(paid, 6000)
        issues = dict(self.con.execute("SELECT issue, COUNT(*) FROM recon_exceptions GROUP BY issue").fetchall())
        self.assertEqual(issues["Duplicate transaction"], 1)

    def test_unknown_reference_is_reported(self):
        refs = [r[0] for r in self.con.execute(
            "SELECT reference FROM recon_exceptions WHERE issue = 'Unknown loan reference'")]
        self.assertEqual(refs, ["LX99"])

    def test_overpayment_is_reported(self):
        row = self.con.execute("SELECT reference, amount FROM recon_exceptions WHERE issue = 'Overpaid loan'").fetchone()
        self.assertEqual(row, ("L3", 2000.0))

    def test_partial_payment_ages_from_oldest_unpaid_instalment(self):
        s = self.status("L1")
        # 4,500 paid against 9,000 due by 20 Apr: instalment 2 (due 10 Mar) is the oldest not fully paid
        self.assertEqual(s.dpd, 41)
        self.assertEqual(s.amount_overdue, 4500)
        self.assertEqual(s.bucket, "31-60")

    def test_paid_up_loan_is_closed(self):
        self.assertEqual(self.status("L2").bucket, "Closed")

    def test_coverage_dates(self):
        rows = dict(((l, n), c) for l, n, c in self.con.execute(
            "SELECT loan_id, inst_no, covered_date FROM installment_coverage"))
        self.assertEqual(rows[("L1", 1)], "2026-02-09")
        self.assertIsNone(rows[("L1", 2)])            # only half paid
        self.assertEqual(rows[("L2", 2)], "2026-03-12")

    def test_status_on_an_earlier_date_ignores_later_payments(self):
        db.materialise(self.con, "03_loan_status.sql", "ls_early", {"as_of": "2026-03-01", **PARAMS})
        s = pd.read_sql_query("SELECT * FROM ls_early WHERE loan_id = 'L1'", self.con).iloc[0]
        self.assertEqual(s.dpd, 0)
        self.assertEqual(s.bucket, "Current")


if __name__ == "__main__":
    unittest.main()
