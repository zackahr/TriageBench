#!/bin/sh

cat > /workspace/resolution.json <<'EOF'
{
  "ticket_id": "TKT-000123",
  "category": "account_access",
  "priority": "medium",
  "status": "resolved",
  "customer_email": "r.morgan@example.com",
  "summary": "Customer could not log in and requested a password reset.",
  "action_taken": "Verified the customer's identity via account email and security question, then sent a secure password reset link to their email; the link expires in 30 minutes and the password must be changed on first login."
}
EOF