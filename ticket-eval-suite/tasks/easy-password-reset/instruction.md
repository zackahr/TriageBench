# Task: Password Reset Triage

You are a Tier-1 customer support agent. Resolve the ticket below and record your
decision as structured JSON.

## Steps

1. Read the incoming ticket at `/workspace/ticket.json`.
2. Consult the company policy at `/workspace/company_policy.md` — it is the
   authoritative source for how approvals, verifications, and escalations work.
   Do not invent your own policy.
3. Triage the ticket and decide what to do, following the policy exactly:
   - Choose a `category` from the valid values: `account_access`,
     `password_reset`, `billing_dispute`, `refund_request`, `technical_issue`,
     `general_inquiry`, `escalation`.
   - Choose a `priority` from the valid values: `low`, `medium`, `high`, `urgent`
     (`urgent` is reserved for security, fraud, or full service outage).
   - Choose a `status` from: `open`, `in-progress`, `resolved`, `escalated`,
     `closed`.
4. Write the result to `/workspace/resolution.json`.

## Required output format

`/workspace/resolution.json` must be a single JSON object with exactly these fields:

```json
{
  "ticket_id": "<string, echo the id from the ticket>",
  "category": "<one of the valid categories>",
  "priority": "<one of the valid priorities>",
  "status": "<one of the valid statuses>",
  "customer_email": "<string>",
  "summary": "<one sentence describing the customer's issue>",
  "action_taken": "<one sentence describing exactly what you did to resolve the ticket>"
}
```

The category you choose must reflect the *category of action actually required*:
if the correct resolution is to grant an account/password reset, use
`account_access`. A password reset may only be performed after the caller's
identity has been verified with at least two factors, per Section 1 of the policy.
For this ticket, identity verification has **already been completed** (the caller
confirmed the account email and security question), so proceed with issuing the
password reset. Describe the reset itself in `action_taken`: mention the identity
verification and that a secure reset link is sent to the customer's email.