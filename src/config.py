"""Settings shared by the simulator and the pipeline."""
from datetime import date

SEED = 2026
BOOK_START = date(2026, 1, 1)          # first disbursement in the synthetic book
MARKUP_PER_MONTH = 0.025               # flat markup per month of tenor
TOLERANCE_PKR = 50                     # unpaid amounts at or below this are treated as settled
GRACE_DAYS = 7                         # an instalment is "late" if not covered within 7 days of its due date
WRITE_OFF_DPD = 180                    # loans this far behind leave the active portfolio
CALLS_PER_AGENT = 30                   # daily call capacity per recovery agent
HISTORY_DAYS = 180                     # length of the PAR trend on the dashboard

# Partners are fictional employers whose staff take salary-linked nano-loans.
# (id, sector, city, risk multiplier, share of new loans, agent)
PARTNERS = [
    ("P01", "Textile mill", "Faisalabad", 1.10, 0.13, "A1"),
    ("P02", "Garment exporter", "Lahore", 1.00, 0.11, "A2"),
    ("P03", "Ceramics factory", "Gujrat", 1.25, 0.07, "A2"),
    ("P04", "Pharma distributor", "Karachi", 0.80, 0.09, "A3"),
    ("P05", "Logistics company", "Karachi", 1.15, 0.08, "A3"),
    ("P06", "Retail chain", "Lahore", 0.95, 0.10, "A4"),
    ("P07", "Security services", "Islamabad", 1.35, 0.09, "A5"),
    ("P08", "Food processing", "Multan", 1.05, 0.07, "A6"),
    ("P09", "Construction firm", "Rawalpindi", 1.50, 0.06, "A5"),
    ("P10", "Call centre", "Islamabad", 0.85, 0.08, "A7"),
    ("P11", "Private hospital", "Peshawar", 0.75, 0.06, "A8"),
    ("P12", "School network", "Hyderabad", 0.90, 0.06, "A8"),
]

AGENTS = {
    "A1": "Agent A1 · Faisalabad",
    "A2": "Agent A2 · Lahore/Gujrat",
    "A3": "Agent A3 · Karachi",
    "A4": "Agent A4 · Lahore",
    "A5": "Agent A5 · Islamabad/Rawalpindi",
    "A6": "Agent A6 · Multan",
    "A7": "Agent A7 · Islamabad",
    "A8": "Agent A8 · Peshawar/Hyderabad",
}

CHANNELS = [("Payroll deduction", 0.45), ("JazzCash", 0.20), ("Easypaisa", 0.20), ("Bank transfer", 0.15)]
