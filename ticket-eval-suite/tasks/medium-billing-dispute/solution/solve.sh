#!/bin/sh
# Golden solution: derive the duplicate charge from the transaction history,
# compute the refund, and write both the customer reply and the refund log.

python3 - <<'PY'
import csv
import json
import re
from pathlib import Path

TRANSACTIONS = Path("/workspace/transactions.csv")
TICKET = json.loads(Path("/workspace/ticket.json").read_text())


def invoice_of(description):
    match = re.search(r"INV-\d+", description)
    return match.group(0) if match else description.strip()


rows = list(csv.DictReader(TRANSACTIONS.open(newline="")))
groups = {}
for row in rows:
    key = (invoice_of(row["description"]), abs(float(row["amount"])))
    groups.setdefault(key, []).append(row)

# A charge is duplicated when the same invoice + amount appears more than once.
duplicated = [m for members in groups.values() if len(members) > 1 for m in members]
assert duplicated, "no duplicate charge found in transactions.csv"

# The erroneous duplicate is the later charge on the same invoice and amount.
target = max(duplicated, key=lambda row: row["created_at"])
refund_amount = round(abs(float(target["amount"])), 2)
refund_tx_id = target["transaction_id"]
invoice = invoice_of(target["description"])

reply = f"""Dear {TICKET['customer_email'].split('@')[0]},

Thank you for reaching out about the duplicate charge on your Enterprise
plan. I can understand how frustrating it is to see an unexpected charge, and
I apologize for the confusion this has caused.

After reviewing your account, I confirmed that your Enterprise subscription
({invoice}) was billed twice for the same renewal on {target['created_at'][:10]}. You
should only be charged once per billing period, so I have approved a refund of
$45.00 for the duplicate charge (transaction {refund_tx_id}).

The refund has been issued to the original payment method on file. We
appreciate your business and apologize again for the inconvenience. Please
reply to this email if there is anything else we can help with.

Best regards,
TriageBench Customer Support
"""

refund_log = {
    "ticket_id": TICKET["ticket_id"],
    "customer_email": TICKET["customer_email"],
    "transaction_id": refund_tx_id,
    "refund_amount": refund_amount,
    "refund_status": "approved",
    "refund_method": "original_payment_method",
    "reason": (
        f"Duplicate charge: {invoice} Enterprise plan was billed twice on "
        f"{target['created_at'][:10]} ({refund_tx_id}); refunding the erroneous "
        f"${refund_amount:.2f} charge."
    ),
}

Path("/workspace/reply.txt").write_text(reply)
Path("/workspace/refund_log.json").write_text(
    json.dumps(refund_log, indent=2) + "\n"
)
print(f"wrote /workspace/reply.txt and /workspace/refund_log.json "
      f"(refund ${refund_amount:.2f} for {refund_tx_id})")
PY