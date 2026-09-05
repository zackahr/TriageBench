# Task: Multi-Step Escalation & Failure Recovery — Checkout Outage (P1)

You are the on-call site reliability engineer assigned to a P1 incident. A
high-urgency outage report was filed for the `checkout-payments` service, but
the report is **incomplete**: it does not record which environment/region the
failing cluster runs in. Resolve the incident across three steps — detect the
missing information and request clarification, apply the configuration fix once
the environment is confirmed, then file the executive incident report.

## Step 1 — Detect the missing information and request clarification

1. Read the outage report at `/workspace/outage_ticket.json` **first**.
2. Read the current service configuration at `/workspace/config.yaml` and the
   escalation guidelines in `/workspace/company_policy.md` (Section 3).
3. Identify the critical system identifier the ticket is missing — the
   environment/region the incident is happening in. A safe fix cannot be
   applied without it.
4. Write a clarification query log to `/workspace/clarification_needed.txt`:
   - state exactly what piece of information is missing,
   - ask the precise question whose answer unblocks the fix,
   - name the artifact that will carry the reply.

## Step 2 — Apply the configuration fix after the reply arrives

1. Check `/workspace/user_response.txt`. If the file is not present, simulate
   the on-call escalation reply and write it to `/workspace/user_response.txt`
   so the incident can proceed.
2. Extract the confirmed environment/region from the reply.
3. Edit `/workspace/config.yaml` so it matches the confirmed production
   environment:
   - correct `service.environment` and `service.region` to match live traffic
     (per the reply),
   - point `database.host` at the production database and use a
     production-sized `database.pool_size`,
   - disable the test-only `feature_flags.auth_bypass_for_tests` in live
     traffic.
4. Validate that the result is parseable YAML with no syntax errors.

Do not change the file in ways that leave the corrupted values in place.

## Step 3 — File the executive incident report

Write `/workspace/incident_report.md` as a concise executive incident report
covering:
- impact: what broke, who was affected, how severely, for how long,
- root cause: precisely why it broke (name the misconfiguration, not a generic
  "service error"),
- the fix applied: what changed and in which file,
- the clarification step: what was missing, what you asked, and what was
  confirmed,
- any follow-up items that remain open.

## Context

| Path | Role |
|---|---|
| `/workspace/outage_ticket.json` | The incomplete P1 outage report — read it first. |
| `/workspace/config.yaml` | The corrupted service configuration; the file you repair. |
| `/workspace/user_response.txt` | Mock escalation reply with the confirmed environment (may be pre-seeded). |
| `/workspace/company_policy.md` | Escalation guidelines — Section 3 governs how escalations must be handled. |

## Scoring

All three steps are verified:

- `/workspace/clarification_needed.txt` exists and genuinely requests the
  missing environment information (Step 1).
- `/workspace/config.yaml` parses as valid YAML and contains the correct
  production fix — environment/region, production database host, production
  pool size, and the auth-bypass test flag disabled (Step 2).
- `/workspace/incident_report.md` is graded by an LLM judge on root-cause
  accuracy and completeness (Step 3).