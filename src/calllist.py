"""Turn loan status + risk scores into today's work: agent call lists and automatic SMS reminders.

Each agent can make CALLS_PER_AGENT calls a day. Up to PRE_DUE_SLOTS of those go to borrowers
the model expects to pay late *before* their due date (prevention); the rest go to the most
valuable overdue accounts. Everyone else who is a little late, or medium-risk, gets an automatic SMS.
"""
from __future__ import annotations

import pandas as pd

from .config import AGENTS, CALLS_PER_AGENT

# bucket -> (action, weight on the amount at stake)
ACTIONS = {
    "1-30": ("Reminder call", 1.0),
    "31-60": ("Call employer HR + borrower", 1.6),
    "61-90": ("Field visit", 1.4),
    "91-180": ("Final notice via employer", 0.8),
}
PRE_DUE_ACTION = "Courtesy call before due date"
PRE_DUE_MIN_RISK = 0.45     # high risk: agent call before the due date
SMS_MIN_RISK = 0.25         # medium risk: automatic SMS before the due date
PRE_DUE_SLOTS = 8           # calls per agent reserved for prevention

COLS = ["agent_id", "agent", "rank_for_agent", "action", "loan_id", "borrower_id", "partner_id", "sector", "city",
        "dpd", "amount_to_collect", "installment", "next_due", "risk", "last_payment_date"]


def build(status: pd.DataFrame, scores: pd.DataFrame, partners: pd.DataFrame, as_of):
    s = status.merge(partners[["partner_id", "sector", "city", "agent_id"]], on="partner_id")
    s = s.merge(scores[["loan_id", "risk", "due_date"]].rename(columns={"due_date": "next_due"}), on="loan_id", how="left")
    horizon = pd.Timestamp(as_of) + pd.Timedelta(days=7)

    overdue = s[s.bucket.isin(ACTIONS)].copy()
    overdue["action"] = overdue.bucket.map(lambda b: ACTIONS[b][0])
    overdue["amount_to_collect"] = overdue.amount_overdue
    overdue["priority"] = (overdue.amount_overdue * overdue.bucket.map(lambda b: ACTIONS[b][1])
                           * (1 + overdue.risk.fillna(0.5)))

    upcoming = s[(s.bucket == "Current") & s.risk.notna() & (s.next_due <= horizon)].copy()
    upcoming["amount_to_collect"] = upcoming.installment
    upcoming["priority"] = upcoming.installment * upcoming.risk
    pre = upcoming[upcoming.risk >= PRE_DUE_MIN_RISK].sort_values("priority", ascending=False).copy()
    pre["action"] = PRE_DUE_ACTION
    pre = pre[pre.groupby("agent_id").cumcount() < PRE_DUE_SLOTS]

    free = (CALLS_PER_AGENT - pre.groupby("agent_id").size()).reindex(list(AGENTS), fill_value=CALLS_PER_AGENT)
    overdue = overdue.sort_values("priority", ascending=False)
    overdue_pick = overdue[overdue.groupby("agent_id").cumcount() < overdue.agent_id.map(free)]

    calls = pd.concat([pre, overdue_pick], ignore_index=True).sort_values("priority", ascending=False)
    calls["rank_for_agent"] = calls.groupby("agent_id").cumcount() + 1
    calls["agent"] = calls.agent_id.map(AGENTS)
    calls["risk"] = calls.risk.round(2)
    calls["next_due"] = calls.next_due.dt.strftime("%Y-%m-%d")
    calls = calls[COLS].sort_values(["agent_id", "rank_for_agent"]).reset_index(drop=True)

    called = set(calls.loan_id)
    sms_overdue = overdue[(overdue.bucket == "1-30") & ~overdue.loan_id.isin(called)].assign(
        message="Overdue reminder")
    sms_pre = upcoming[(upcoming.risk >= SMS_MIN_RISK) & ~upcoming.loan_id.isin(called)].assign(
        message="Reminder: instalment due soon")
    sms = pd.concat([sms_overdue, sms_pre], ignore_index=True)
    sms["next_due"] = sms.next_due.dt.strftime("%Y-%m-%d")
    sms = sms[["loan_id", "borrower_id", "partner_id", "message", "dpd", "amount_to_collect", "next_due"]]
    return calls, sms
