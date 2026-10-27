"""Daily collections run.

    python -m src.run_pipeline                      # yesterday (Pakistan time)
    python -m src.run_pipeline --as-of 2026-10-26   # any business date
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from . import brief, calllist, db, model
from .config import AGENTS, BOOK_START, GRACE_DAYS, HISTORY_DAYS, TOLERANCE_PKR, WRITE_OFF_DPD
from .simulate import build_book

ROOT = Path(__file__).resolve().parent.parent
PKT = timezone(timedelta(hours=5))


def kpis_for(con, table: str) -> dict:
    k = db.query(con, "04_portfolio_kpis.sql", status=table).iloc[0].fillna(0).to_dict()
    base = k["portfolio_outstanding"] or 1
    k.update(par1=k["par1_amount"] / base, par30=k["par30_amount"] / base, par90=k["par90_amount"] / base)
    return k


def status_on(con, day: date, table: str) -> None:
    db.materialise(con, "03_loan_status.sql", table,
                   {"as_of": day.isoformat(), "tol": TOLERANCE_PKR, "write_off_dpd": WRITE_OFF_DPD})


def run(as_of: date, out: Path) -> dict:
    if as_of < BOOK_START + timedelta(days=150):
        raise SystemExit(f"Need about 5 months of loan history; choose a date after {BOOK_START + timedelta(days=150)}.")
    partners, loans, insts, pays = build_book(as_of)
    con = db.load(partners, loans, insts, pays)
    db.run_script(con, "01_reconcile.sql", {"tol": TOLERANCE_PKR})
    db.run_script(con, "02_installment_coverage.sql", {"tol": TOLERANCE_PKR})

    status_on(con, as_of, "loan_status")
    status_on(con, as_of - timedelta(days=30), "loan_status_prev")
    k = kpis_for(con, "loan_status")

    # PAR trend: re-run the same status logic for each past day
    history = []
    for n in range(HISTORY_DAYS - 1, -1, -1):
        day = as_of - timedelta(days=n)
        if n == 0:
            hk = k
        else:
            status_on(con, day, "loan_status_hist")
            hk = kpis_for(con, "loan_status_hist")
        history.append({"date": day.isoformat(), "par30": hk["par30"], "par90": hk["par90"],
                        "outstanding": hk["portfolio_outstanding"]})
    week_ago = history[-8]

    daily = db.query(con, "05_daily_collections.sql", {"as_of": as_of.isoformat(), "days": 60})
    mtd = daily[daily.day >= as_of.replace(day=1).isoformat()]
    k.update(
        collected_day=float(daily.collected.iloc[-1]), payments_day=int(daily.payments.iloc[-1]),
        collected_mtd=float(mtd.collected.sum()), due_mtd=float(mtd.due.sum()),
        collection_efficiency_mtd=float(mtd.collected.sum() / max(mtd.due.sum(), 1)),
        par30_change_7d=k["par30"] - week_ago["par30"], par90_change_7d=k["par90"] - week_ago["par90"],
    )

    partner_watch = db.query(con, "06_partner_watch.sql", {"as_of": as_of.isoformat(), "grace": GRACE_DAYS})

    roll = db.query(con, "07_roll_rates.sql")
    order = ["Current", "1-30", "31-60", "61-90", "91-180", "Written off", "Closed"]
    matrix = roll.pivot_table(index="from_bucket", columns="to_bucket", values="loans", aggfunc="sum", fill_value=0)
    matrix = matrix.reindex(index=[b for b in order[:5] if b in matrix.index], columns=order, fill_value=0)
    shares = matrix.div(matrix.sum(axis=1), axis=0)
    roll_1_30 = float(shares.loc["1-30", ["31-60", "61-90", "91-180", "Written off"]].sum()) if "1-30" in shares.index else None

    recon = pd.read_sql_query("SELECT * FROM recon_exceptions ORDER BY txn_date DESC, amount DESC", con)
    recon7 = recon[recon.txn_date > (as_of - timedelta(days=7)).isoformat()]

    # Early-warning model
    ic = pd.read_sql_query(
        "SELECT c.loan_id, c.inst_no, c.due_date, c.covered_date, l.partner_id, l.tenor_months, l.principal, "
        "l.disb_date, l.installment FROM installment_coverage c JOIN loans l USING (loan_id)", con,
        parse_dates=["due_date", "covered_date", "disb_date"])
    pm = pd.read_sql_query("SELECT loan_id, txn_date FROM payments_matched", con, parse_dates=["txn_date"])
    status = pd.read_sql_query("SELECT * FROM loan_status", con)
    active = status[~status.bucket.isin(["Closed", "Written off"])].loan_id
    asof_ts = pd.Timestamp(as_of)
    upcoming = ic[ic.loan_id.isin(active) & (ic.due_date > asof_ts) & (ic.due_date <= asof_ts + pd.Timedelta(days=14))
                  & ic.covered_date.isna()]
    upcoming = upcoming.sort_values("inst_no").drop_duplicates("loan_id")[["loan_id", "inst_no", "due_date", "installment"]]
    scores, metrics = model.train_and_score(ic, pm, upcoming[["loan_id", "inst_no"]], as_of)
    scores = scores.merge(upcoming[["loan_id", "due_date", "installment"]], on="loan_id", suffixes=("_f", ""))

    calls, sms = calllist.build(status, scores, partners, as_of)
    current_ids = status[status.bucket == "Current"].loan_id
    week = scores[(scores.due_date <= asof_ts + pd.Timedelta(days=7)) & scores.loan_id.isin(current_ids)]
    flagged = week[week.risk >= calllist.PRE_DUE_MIN_RISK]
    scored_week = {"n": int(len(flagged)), "expected_late": float((week.installment * week.risk).sum())}
    k["expected_late_7d"] = scored_week["expected_late"]
    k["due_next_7d"] = float(week.installment.sum())

    as_of_label = as_of.strftime("%d %b %Y")
    brief_lines = brief.write(k, partner_watch, recon7, calls, sms, scored_week, roll_1_30, as_of_label)

    buckets = status.groupby("bucket").agg(loans=("loan_id", "size"), outstanding=("outstanding", "sum"))
    dash = {
        "meta": {
            "as_of": as_of.isoformat(), "as_of_label": as_of_label,
            "generated_at": datetime.now(PKT).strftime("%d %b %Y, %H:%M PKT"),
            "note": "Synthetic loan book generated for this demo. No real borrowers.",
            "grace_days": GRACE_DAYS, "write_off_dpd": WRITE_OFF_DPD,
        },
        "kpis": {key: (float(v) if isinstance(v, (int, float)) else v) for key, v in k.items()},
        "brief": brief_lines,
        "history": history,
        "collections": daily.to_dict(orient="records"),
        "buckets": [{"bucket": b, **{c: float(buckets.loc[b, c]) for c in buckets.columns}}
                    for b in order if b in buckets.index],
        "partners": partner_watch.fillna(0).to_dict(orient="records"),
        "roll": {"from": list(shares.index), "to": list(shares.columns),
                 "share": shares.round(4).values.tolist(), "loans": matrix.values.tolist()},
        "recon": {
            "summary": recon7.groupby("issue").amount.agg(["size", "sum"]).reset_index()
                             .rename(columns={"size": "count", "sum": "amount"}).to_dict(orient="records"),
            "rows": recon7.head(25).to_dict(orient="records"),
            "all_time_open": int(len(recon)),
        },
        "calls": {
            "per_agent": calls.groupby(["agent_id", "agent"]).agg(calls=("loan_id", "size"),
                                                                  amount=("amount_to_collect", "sum"))
                             .reset_index().to_dict(orient="records"),
            "by_action": calls.groupby("action").agg(calls=("loan_id", "size"), amount=("amount_to_collect", "sum"))
                              .reset_index().to_dict(orient="records"),
            "top": pd.concat([
                calls[calls.action != calllist.PRE_DUE_ACTION]
                .sort_values(["rank_for_agent", "amount_to_collect"], ascending=[True, False]).head(12),
                calls[calls.action == calllist.PRE_DUE_ACTION].sort_values("risk", ascending=False).head(8),
            ]).fillna("").to_dict(orient="records"),
            "total": int(len(calls)),
            "sms": int(len(sms)),
            "pre_due": int((calls.action == calllist.PRE_DUE_ACTION).sum()),
        },
        "model": metrics,
    }

    out.mkdir(parents=True, exist_ok=True)
    (out / "data").mkdir(exist_ok=True)
    (out / "call_lists").mkdir(exist_ok=True)
    (out / "data" / "dashboard.json").write_text(json.dumps(dash, indent=1, default=str), encoding="utf-8")
    calls.to_csv(out / "call_lists" / "all_agents.csv", index=False)
    sms.to_csv(out / "call_lists" / "sms_reminders.csv", index=False)
    for aid, grp in calls.groupby("agent_id"):
        grp.to_csv(out / "call_lists" / f"agent_{aid}.csv", index=False)
    md = [f"# CEO morning brief, {as_of_label}", ""] + [f"- {line}" for line in brief_lines] + [
        "", f"_Generated {dash['meta']['generated_at']} from a synthetic loan book._"]
    (out / "ceo_brief.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    for f in (ROOT / "web").iterdir():
        shutil.copy(f, out / f.name)
    return dash


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--as-of", type=date.fromisoformat,
                    default=(datetime.now(PKT) - timedelta(days=1)).date(),
                    help="business date to report on (default: yesterday, Pakistan time)")
    ap.add_argument("--out", type=Path, default=ROOT / "site")
    a = ap.parse_args()
    d = run(a.as_of, a.out)
    print("\n".join(d["brief"]))


if __name__ == "__main__":
    main()
