# Task: Billing Dispute — Duplicate Enterprise Charge

You are a Tier-1 customer support agent. A customer is disputing an overcharge on
their Enterprise subscription. Investigate the charge, calculate the refund,
write a customer-facing reply, and record the refund as structured JSON.

## Steps

1. Read the incoming ticket at `/workspace/ticket.json`.
2. Consult the company policy at `/workspace/company_policy.md` — it is the
   authoritative source for refund approval limits, payment-method rules, and
   escalation paths. Do not invent your own policy.
3. Analyze the customer's transaction history at
   `/workspace/transactions.csv`. The CSV columns are:
   `transaction_id,created_at,description,amount,currency,status,customer_email,payment_method`.
   Diff the charged amounts against the customer's normal billing pattern and
   determine whether any charge was duplicated.
4. Decide the refund, following policy Section 2 exactly:
   - The refund amount is the erroneous duplicate charge in full.
   - Refunds up to **$50** may be approved directly by an agent; refunds above
     $50 must be routed to Billing Management.
   - Refunds must be issued to the original payment method on file, never as a
     store credit unless the customer explicitly agrees.
5. Write a customer-facing reply to `/workspace/reply.txt`:
   - Tone is empathetic and professional: acknowledge the customer's frustration
     and apologize for the billing error.
   - Explicitly confirm the exact refund amount ($45.00) for the duplicate
     enterprise-plan charge.
   - Confirm the refund is issued to the original payment method on file.
   - Do NOT promise any refund, credit, feature, timeline, compensation, or
     policy exception that company_policy.md does not allow.
6. Record the refund decision in `/workspace/refund_log.json` using the schema
   below.

## Required output: `/workspace/reply.txt`

A plain-text, customer-facing email. It must be readable on its own and must not
contain `refund_log` JSON or internal notes.

## Required output: `/workspace/refund_log.json`

A single JSON object with **exactly** these fields:

```json
{
  "ticket_id": "<string, echo the id from the ticket>",
  "customer_email": "<string, echo the email from the ticket>",
  "transaction_id": "<string, the exact transaction_id of the duplicate charge from transactions.csv>",
  "refund_amount": 45.0,
  "refund_status": "approved",
  "refund_method": "original_payment_method",
  "reason": "<one sentence describing the duplicate charge>"
}
```

Notes:

- `transaction_id` must be the **exact** id of the erroneous duplicate charge —
  the later of the two identical $45.00 enterprise-plan charges on the most
  recent renewal invoice (same invoice, same amount, same day). Identify it from
  `transactions.csv`; do not guess.
- `refund_amount` must be the number `45.0`.
- `refund_status` must be `approved` — $45.00 is within the agent approval limit
  in policy Section 2, so no escalation is required.
- `refund_method` must be `original_payment_method` per policy Section 2.