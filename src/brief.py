"""Write the CEO morning brief: a handful of plain sentences on what changed and what to do."""
from __future__ import annotations


def rs(x: float) -> str:
    x = float(x)
    if abs(x) >= 1e6:
        return f"Rs {x / 1e6:,.1f}m"
    if abs(x) >= 1e4:
        return f"Rs {x / 1e3:,.0f}k"
    return f"Rs {x:,.0f}"


def pct(x: float, d: int = 1) -> str:
    return f"{100 * x:.{d}f}%"


def pts(x: float) -> str:
    return f"{'up' if x > 0 else 'down'} {abs(100 * x):.2f} pts" if abs(x) >= 0.00005 else "unchanged"


def write(k: dict, partners, recon7, calls, sms, scored_week, roll, as_of_label: str) -> list[str]:
    out = [
        f"**Cash:** collected **{rs(k['collected_day'])}** from {int(k['payments_day']):,} payments on {as_of_label}. "
        f"Month to date **{rs(k['collected_mtd'])}**, which is **{pct(k['collection_efficiency_mtd'], 0)}** "
        f"of the {rs(k['due_mtd'])} that fell due this month.",
        f"**Portfolio quality:** PAR30 is **{pct(k['par30'], 2)}** ({rs(k['par30_amount'])}), "
        f"{pts(k['par30_change_7d'])} on last week. PAR90 is {pct(k['par90'], 2)}. "
        f"Amount receivable {rs(k['portfolio_outstanding'])} (principal + markup) across {int(k['active_loans']):,} active loans.",
    ]
    alerts = partners[partners.status == "Alert"]
    for _, p in alerts.iterrows():
        out.append(
            f"**Employer alert, {p.sector} ({p.city}, {p.partner_id}):** **{pct(p.recent_late_rate, 0)}** of instalments "
            f"due 1-3 weeks ago were paid late, against {pct(p.baseline_late_rate, 0)} normally. "
            f"{int(p.active_loans):,} active loans, {rs(p.outstanding)} receivable. A jump this sudden across one employer "
            f"usually means delayed salaries: call their HR today before it turns into defaults."
        )
    watch = partners[partners.status == "Watch"]
    if len(watch):
        names = ", ".join(f"{p.sector} ({p.partner_id})" for _, p in watch.iterrows())
        out.append(f"**On watch:** {names}: late payments rising, not yet critical.")
    if len(alerts) == 0 and len(watch) == 0:
        out.append("**Employers:** no unusual jump in late payments at any partner this week.")

    if len(recon7):
        by = recon7.groupby("issue").amount.agg(["size", "sum"])
        parts = "; ".join(f"{int(r['size'])} {i.lower()}{'s' if r['size'] != 1 else ''}" for i, r in by.iterrows())
        unapplied = recon7[recon7.issue != "Duplicate transaction"].amount.sum()
        out.append(
            f"**Payments ops:** {len(recon7)} payment exceptions in the last 7 days ({parts}). "
            f"{rs(unapplied)} has been received but not applied to the right loan, which makes good borrowers "
            f"look late, so clear these before agents call."
        )
    if roll is not None:
        out.append(
            f"**Roll rate:** {pct(roll, 0)} of loans that were 1-30 days late a month ago are now more than 30 days late."
        )
    out.append(
        f"**Early warning:** among borrowers who are up to date, the model flags **{scored_week['n']:,}** with "
        f"instalments due in the next 7 days as likely to pay late ({rs(scored_week['expected_late'])} expected to "
        f"arrive late). The riskiest get a call before their due date, the next tier an SMS."
    )
    out.append(
        f"**Today's work:** {len(calls):,} calls assigned across {calls.agent_id.nunique()} agents, "
        f"targeting {rs(calls.amount_to_collect.sum())}, plus {len(sms):,} automatic SMS reminders."
    )
    return out
