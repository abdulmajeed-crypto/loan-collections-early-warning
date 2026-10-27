"""Synthetic loan book for a salary-linked nano-lender.

Everything is generated from fixed seeds, so the book is identical on every run:
running the pipeline for a later date only reveals more of the same history.
The data is fictional and contains no real borrowers.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .config import BOOK_START, CHANNELS, MARKUP_PER_MONTH, PARTNERS, SEED

# Partner stress episodes (e.g. delayed payroll). One starts every 47 days.
_EPISODE_ORDER = ["P09", "P03", "P05", "P01", "P08", "P07", "P02", "P12", "P06", "P04", "P11", "P10"]
_EPISODE_EVERY = 47
_EPISODE_LENGTH = 35
_FIRST_EPISODE = date(2026, 2, 10)


def stress_episodes(until: date) -> list[tuple[str, date, date]]:
    out, start, i = [], _FIRST_EPISODE, 0
    while start <= until + timedelta(days=400):
        out.append((_EPISODE_ORDER[i % len(_EPISODE_ORDER)], start, start + timedelta(days=_EPISODE_LENGTH)))
        start += timedelta(days=_EPISODE_EVERY)
        i += 1
    return out


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, 28, calendar.monthrange(y, m)[1]))


def _daily_rate(d: date) -> float:
    """New loans per day: grows from 8 to 22 over the first ten months, then levels off."""
    months = (d - BOOK_START).days / 30.4
    return min(8 + 1.4 * months, 22)


def _corrupt(ref: str, rng: np.random.Generator) -> str:
    """Typical reference mistakes made by payers: a letter O for zero, a dropped digit, swapped digits."""
    kind = rng.integers(3)
    if kind == 0 and "0" in ref[1:]:
        i = ref.index("0", 1)
        return ref[:i] + "O" + ref[i + 1:]
    if kind == 1:
        return ref[:-1]
    i = int(rng.integers(2, len(ref) - 1))
    return ref[:i] + ref[i + 1] + ref[i] + ref[i + 2:]


def build_book(as_of: date):
    """Return partners, loans, installments and the raw payment feed up to and including as_of."""
    partners = pd.DataFrame(PARTNERS, columns=["partner_id", "sector", "city", "risk", "share", "agent_id"])
    p_ids = partners.partner_id.to_numpy()
    p_share = partners.share.to_numpy() / partners.share.sum()
    p_risk = dict(zip(partners.partner_id, partners.risk))
    episodes = stress_episodes(as_of)
    ch_names = [c for c, _ in CHANNELS]
    ch_p = np.array([p for _, p in CHANNELS])

    loans, insts, pays = [], [], []
    d = BOOK_START
    while d <= as_of:
        day_rng = np.random.default_rng([SEED, d.toordinal()])
        n_new = day_rng.poisson(_daily_rate(d))
        for k in range(n_new):
            num = int(d.strftime("%y%m%d")) * 1000 + k
            loan_id = f"L{num}"
            rng = np.random.default_rng([SEED, num])
            partner = p_ids[rng.choice(len(p_ids), p=p_share)]
            r = p_risk[partner]
            principal = int(np.clip(round(rng.lognormal(np.log(40000), 0.55), -3), 10000, 200000))
            tenor = int(rng.choice([3, 6, 9, 12], p=[0.25, 0.40, 0.20, 0.15]))
            total = round(principal * (1 + MARKUP_PER_MONTH * tenor), -1)
            inst_amt = round(total / tenor, -1)
            total = inst_amt * tenor
            u = rng.random()
            profile = ("defaulter" if u < 0.03 * r else
                       "deteriorating" if u < 0.09 * r else
                       "late" if u < 0.25 * r else "reliable")
            loans.append((loan_id, f"B{num:09d}", partner, d, principal, tenor, inst_amt, total, profile))

            stop_after = int(rng.integers(0, 3))          # defaulters: instalments paid before stopping
            turn_at = int(rng.integers(2, tenor + 1))     # deteriorating: instalment where trouble starts
            seq = 0

            def pay(when: date, amount: float, inst_no: int):
                nonlocal seq
                seq += 1
                txn = f"TX{num}{inst_no:02d}{seq}"
                ch = ch_names[rng.choice(len(ch_names), p=ch_p)]
                ref = _corrupt(loan_id, rng) if rng.random() < 0.004 else loan_id
                pays.append((txn, when, ch, ref, float(amount)))
                if rng.random() < 0.005:                   # channel re-sends the same transaction
                    pays.append((txn, when, ch, ref, float(amount)))

            for i in range(1, tenor + 1):
                due = _add_months(d, i)
                insts.append((loan_id, i, due, inst_amt))
                stressed = any(p == partner and s <= due <= e for p, s, e in episodes)

                if profile == "defaulter":
                    if i <= stop_after:
                        pay(due + timedelta(days=int(rng.integers(-3, 6))), inst_amt, i)
                    elif i == stop_after + 1 and rng.random() < 0.2:
                        pay(due + timedelta(days=int(rng.integers(60, 150))), round(inst_amt * rng.uniform(0.3, 1.0), -1), i)
                    continue

                if profile == "deteriorating" and i >= turn_at:
                    pm, pl = 0.55, 0.35
                elif profile == "late":
                    pm, pl = 0.02, 0.58
                else:
                    pm, pl = 0.005, 0.045
                if stressed:
                    pm, pl = pm + 0.06, pl + 0.40

                u = rng.random()
                if u < pm:                                  # missed; sometimes caught up much later
                    if rng.random() < 0.3:
                        pay(due + timedelta(days=int(rng.integers(30, 100))), inst_amt, i)
                elif u < pm + pl:                           # late
                    lo, hi = (10, 46) if stressed else (4, 41) if profile != "reliable" else (4, 21)
                    pay(due + timedelta(days=int(rng.integers(lo, hi))), inst_amt, i)
                elif profile == "late" and rng.random() < 0.1:   # partial now, rest later
                    part = round(inst_amt * rng.uniform(0.4, 0.8), -1)
                    pay(due + timedelta(days=int(rng.integers(-1, 4))), part, i)
                    pay(due + timedelta(days=int(rng.integers(20, 51))), inst_amt - part, i)
                else:                                       # on time
                    pay(due + timedelta(days=int(rng.integers(-5, 4))), inst_amt, i)
        d += timedelta(days=1)

    loans = pd.DataFrame(loans, columns=["loan_id", "borrower_id", "partner_id", "disb_date", "principal",
                                         "tenor_months", "installment", "total_repayable", "profile"])
    insts = pd.DataFrame(insts, columns=["loan_id", "inst_no", "due_date", "amount_due"])
    pays = pd.DataFrame(pays, columns=["txn_id", "txn_date", "channel", "reference", "amount"])
    pays = pays[pays.txn_date <= as_of].reset_index(drop=True)
    return partners, loans, insts, pays
