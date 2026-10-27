"""Early-warning model: probability that a borrower's next instalment will be late.

Late = not fully paid within GRACE_DAYS of its due date.
Every feature is computed only from information available the day before the instalment
falls due, so the model never sees the future.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .config import GRACE_DAYS, SEED

FEATURES = {
    "days_to_due": "Days until the instalment is due",
    "prior_late_ratio": "Share of earlier instalments paid late",
    "prior_late_count": "Number of earlier instalments paid late",
    "dpd_now": "Days past due right now",
    "days_since_payment": "Days since last payment",
    "partner_late_rate": "Employer's recent late-payment rate",
    "first_installment": "First instalment (no history yet)",
    "tenor_progress": "How far through the loan",
    "log_principal": "Loan size (log)",
}


def _late_flags(ic: pd.DataFrame) -> pd.Series:
    deadline = ic.due_date + pd.Timedelta(days=GRACE_DAYS)
    return (ic.covered_date.isna() | (ic.covered_date > deadline)).astype(int)


def _partner_rate(ic: pd.DataFrame, at: pd.Series, partner: pd.Series) -> np.ndarray:
    """Late rate of the partner's instalments due 21..7 days before each date in `at`."""
    known = ic.assign(late=_late_flags(ic))
    daily = known.groupby(["partner_id", "due_date"]).late.agg(["sum", "count"]).reset_index()
    out = np.zeros(len(at))
    for pid, grp in daily.groupby("partner_id"):
        idx = pd.date_range(grp.due_date.min() - pd.Timedelta(days=30), at.max() + pd.Timedelta(days=1))
        s = grp.set_index("due_date")[["sum", "count"]].reindex(idx, fill_value=0)
        cs, cn = s["sum"].cumsum(), s["count"].cumsum()
        mask = (partner == pid).to_numpy()
        if not mask.any():
            continue
        t = at[mask]
        hi = (t - pd.Timedelta(days=GRACE_DAYS)).clip(lower=idx[0])
        lo = (t - pd.Timedelta(days=GRACE_DAYS + 15)).clip(lower=idx[0])
        late = cs.reindex(hi).to_numpy() - cs.reindex(lo).to_numpy()
        n = cn.reindex(hi).to_numpy() - cn.reindex(lo).to_numpy()
        out[mask] = np.where(n >= 5, late / np.maximum(n, 1), np.nan)
    return out


def build_features(ic: pd.DataFrame, pays: pd.DataFrame, targets: pd.DataFrame) -> pd.DataFrame:
    """targets: loan_id, inst_no, t (the 'as at' date for the features). Returns one feature row per target.
    partner_late_rate is left missing where unknown; the caller fills it with the training mean."""
    ns = "datetime64[ns]"
    ic = ic.astype({"due_date": ns, "covered_date": ns, "disb_date": ns})
    pays = pays.astype({"txn_date": ns})
    targets = targets.astype({"t": ns})
    ic["late"] = _late_flags(ic)
    tg = targets.merge(ic[["loan_id", "inst_no", "due_date", "partner_id", "tenor_months", "principal", "disb_date"]],
                       on=["loan_id", "inst_no"], how="left")

    prior = tg[["loan_id", "inst_no", "t"]].merge(ic[["loan_id", "inst_no", "due_date", "covered_date", "late"]],
                                                  on="loan_id", suffixes=("", "_p"))
    prior = prior[(prior.inst_no_p < prior.inst_no) &
                  (prior.due_date + pd.Timedelta(days=GRACE_DAYS) < prior.t)]
    prior["open"] = prior.covered_date.isna() | (prior.covered_date > prior.t)
    agg = prior.groupby(["loan_id", "inst_no"]).agg(prior_n=("late", "size"), prior_late_count=("late", "sum"))
    oldest_open = prior[prior.open].groupby(["loan_id", "inst_no"]).due_date.min().rename("oldest_open")
    tg = tg.join(agg, on=["loan_id", "inst_no"]).join(oldest_open, on=["loan_id", "inst_no"])
    tg[["prior_n", "prior_late_count"]] = tg[["prior_n", "prior_late_count"]].fillna(0)
    tg["prior_late_ratio"] = np.where(tg.prior_n > 0, tg.prior_late_count / tg.prior_n.clip(lower=1), 0.0)
    tg["dpd_now"] = (tg.t - tg.oldest_open).dt.days.clip(lower=0).fillna(0)

    p = pays[["loan_id", "txn_date"]].sort_values("txn_date")
    tg = tg.sort_values("t")
    tg = pd.merge_asof(tg, p.rename(columns={"txn_date": "last_pay"}), left_on="t", right_on="last_pay",
                       by="loan_id", allow_exact_matches=True, direction="backward")
    ref = tg.last_pay.fillna(tg.disb_date)
    tg["days_since_payment"] = (tg.t - ref).dt.days.clip(lower=0)

    tg["partner_late_rate"] = _partner_rate(ic, tg.t.reset_index(drop=True), tg.partner_id.reset_index(drop=True))
    tg["days_to_due"] = (tg.due_date - tg.t).dt.days
    tg["first_installment"] = (tg.inst_no == 1).astype(int)
    tg["tenor_progress"] = tg.inst_no / tg.tenor_months
    tg["log_principal"] = np.log(tg.principal)
    return tg


def _scores(y, p) -> tuple[float, float]:
    """AUC and the share of all late instalments found in the riskiest 20%."""
    if len(y) < 20 or y.nunique() < 2:
        return float("nan"), float("nan")
    top = p >= np.quantile(p, 0.8)
    return float(roc_auc_score(y, p)), float(y[top].sum() / y.sum())


def train_and_score(ic: pd.DataFrame, pays: pd.DataFrame, to_score: pd.DataFrame, as_of: date):
    """Fit on instalments whose outcome is known, test on the most recent month, score open instalments.

    Training mirrors how the model is used: each historical instalment is looked at 1-14 days before
    its due date, and only if it was still unpaid at that moment (instalments paid early are dropped,
    because the model is never asked about them).
    """
    asof = pd.Timestamp(as_of)
    last_known = asof - pd.Timedelta(days=GRACE_DAYS + 1)
    hist = ic[(ic.due_date <= last_known) & (ic.due_date > asof - pd.Timedelta(days=240))]
    hist = hist[["loan_id", "inst_no", "due_date", "covered_date"]].copy()
    lead = np.random.default_rng(SEED).integers(1, 15, len(hist))
    hist["t"] = hist.due_date - pd.to_timedelta(lead, unit="D")
    hist = hist[hist.covered_date.isna() | (hist.covered_date > hist.t)]

    X = build_features(ic, pays, hist[["loan_id", "inst_no", "t"]])
    X = X.merge(ic[["loan_id", "inst_no"]].assign(y=_late_flags(ic)), on=["loan_id", "inst_no"])

    split = last_known - pd.Timedelta(days=30)
    train, test = X[X.due_date <= split].copy(), X[X.due_date > split].copy()
    fill = train.partner_late_rate.mean()
    for df in (train, test, X):
        df["partner_late_rate"] = df.partner_late_rate.fillna(fill)
    cols = list(FEATURES)
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
    model.fit(train[cols], train.y)
    p_test = model.predict_proba(test[cols])[:, 1]
    auc, capture = _scores(test.y, p_test)
    current = (test.dpd_now == 0).to_numpy()
    auc_cur, capture_cur = _scores(test.y[current], p_test[current])

    model.fit(X[cols], X.y)                       # refit on everything known for today's scoring
    coefs = model.named_steps["logisticregression"].coef_[0]
    S = build_features(ic, pays, to_score.assign(t=asof))
    S["partner_late_rate"] = S.partner_late_rate.fillna(X.partner_late_rate.mean())
    S["risk"] = model.predict_proba(S[cols])[:, 1]

    metrics = {
        "trained_on": int(len(X)),
        "test_from": str((split + pd.Timedelta(days=1)).date()),
        "test_to": str(last_known.date()),
        "test_size": int(len(test)),
        "test_late_rate": float(test.y.mean()),
        "auc": auc,
        "top20_capture": capture,
        "current_test_size": int(current.sum()),
        "current_late_rate": float(test.y[current].mean()),
        "auc_current": auc_cur,
        "top20_capture_current": capture_cur,
        "drivers": sorted(({"feature": FEATURES[c], "weight": float(w)} for c, w in zip(cols, coefs)),
                          key=lambda d: -abs(d["weight"])),
    }
    return S, metrics
