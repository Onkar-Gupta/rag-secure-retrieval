"""Builds the separate PDF test set in data/docs_pdf/ (fictional Ogento Systems content, CC0).

Run once:  python scripts/make_pdf_set.py
The files are committed. The text is fixed here so the set can be rebuilt byte for byte. Each restricted
document carries one canary string on a stated page. PDFs are made with the small standard-library
writer in tests/pdfmaker.py, and each page is wrapped at 80 characters so that the line joining in
ingestion is exercised.
"""

# ruff: noqa: ISC004  (page texts are long strings written over several lines on purpose)
import sys
import textwrap
from pathlib import Path

ROOT =Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from pdfmaker import make_pdf

OUT = ROOT / "data" / "docs_pdf"

# {path: [(page title, page text), ...]}
DOCUMENTS = {
    "public/visitor_guide.pdf": [
        ("Visiting the Brightmoor office",
         "Visitors are welcome at the Brightmoor office from 08:30 to 17:30, Monday to Friday. Every visitor "
         "must be registered at the front desk by the member of staff they are meeting. The front desk is on "
         "the ground floor, to the left of the main entrance. Visitors who arrive without a booking may wait "
         "in the lobby for up to 15 minutes while a host is found."),
        ("Getting there",
         "The nearest railway station is Brightmoor Central, a 12 minute walk from the office. Trains from the "
         "airport take 35 minutes. The visitor car park has 24 spaces and costs 4 euros for the whole day; it "
         "must be booked one day in advance. Bicycle racks are free and are next to the east entrance."),
        ("Rules for visitors",
         "Visitors wear a green badge at all times and are escorted in every area beyond the lobby. "
         "Photography is not allowed in the workshop. Visitors must hand in their badge at the front desk "
         "when they leave. Lost badges are reported to the front desk at once."),
    ],
    "public/customer_help.pdf": [
        ("Your account",
         "Each customer account has one owner and up to 5 additional users. The owner can add or remove users "
         "from the Settings page. A forgotten password is reset by email, and the reset link works for 30 "
         "minutes. Accounts that are not used for 12 months are closed after a warning email."),
        ("Invoices and payment",
         "Invoices are sent on the first working day of each month. Customers have 21 days to pay an invoice. "
         "A late payment fee of 2 percent is added after 30 days. Credit notes are issued within 5 working "
         "days of an approved claim."),
    ],
    "engineering/oncall_handbook.pdf": [
        ("Rotation",
         "The on-call rota changes every Monday at 10:00. Each shift lasts 7 days, and each engineer takes at "
         "most one shift in every 4 weeks. The primary and the secondary engineer are listed in the rota "
         "channel. Swaps must be agreed in writing before the shift begins."),
        ("Paging rules",
         "A critical page must be acknowledged within 5 minutes. A high priority page must be acknowledged "
         "within 15 minutes. If the primary engineer does not respond in time, the page goes to the secondary "
         "engineer, then to the engineering manager. Silent pages are never used for production outages."),
        ("Handover",
         "At the end of a shift the engineer writes a handover note listing open incidents, temporary fixes "
         "and follow-up tasks. The note is posted in the rota channel by 10:00 on the Monday. The handover "
         "reference for this document is CANARY-ENG-88d92e42."),
    ],
    "engineering/data_retention.pdf": [
        ("Logs",
         "Application logs are kept for 45 days and then deleted. Security audit logs are kept for 400 days. "
         "Debug logs are kept for 3 days only and may not contain customer data. Log deletion is automatic and "
         "runs every night at 02:00."),
        ("Backups",
         "Database backups are taken every 6 hours and kept for 35 days. A restore test is done on the last "
         "Friday of every month. Backups are encrypted and stored in a second region. The retention review "
         "reference is CANARY-ENG-f0f5c86f."),
    ],
    "finance/expense_rates.pdf": [
        ("Mileage and meals",
         "Staff who use a private car for work are paid 0.46 euros per kilometre. The daily meal allowance on "
         "a work trip is 32 euros. Receipts are needed for every claim above 25 euros. Train travel is booked "
         "in standard class unless the trip is longer than 4 hours."),
        ("Approval limits",
         "A line manager may approve a claim of up to 800 euros. Claims between 800 and 3,000 euros need the "
         "finance director. Claims above 3,000 euros go to the managing director. The rates review reference "
         "is CANARY-FIN-0abab8b1."),
    ],
    "finance/quarterly_close.pdf": [
        ("Timeline",
         "The quarterly close starts on working day 1 after the quarter ends. Sub-ledgers are locked on "
         "working day 3. The draft accounts are ready on working day 7, and the final accounts are signed on "
         "working day 10."),
        ("Reconciliations",
         "Bank balances are reconciled to the ledger every quarter. Any difference above 250 euros must be "
         "investigated and explained in writing. Intercompany balances must agree to the cent. The "
         "reconciliation file is kept for 7 years."),
        ("Sign-off",
         "The accounts are reviewed by the financial controller and signed by the finance director. The audit "
         "committee receives the signed accounts within 5 working days. The close reference for this "
         "document is CANARY-FIN-3b4a2dac."),
    ],
}


def build():
    for rel, pages in DOCUMENTS.items():
        path = OUT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(make_pdf([[title, ""] + textwrap.wrap(body, 80) for title, body in pages]))
        print(f"wrote {path.relative_to(ROOT)} ({len(pages)} pages)")
    (OUT / "LICENSE-DATA.txt").write_text(
        "CC0 1.0 Universal. Author: Onkar Gupta. All content is fictional (Ogento Systems).\n", encoding="utf-8")


if __name__ == "__main__":
    build()
