"""Hybrid verifier for the medium-billing-dispute task.

Deterministic pytest checks validate the structured refund log
(/workspace/refund_log.json) and that the customer reply exists. A single
LLM-as-a-Judge call then grades the reply (/workspace/reply.txt) on tone,
policy compliance, and explicit refund confirmation.

The LLM call uses the OpenAI-compatible chat-completions API over stdlib
urllib; point JUDGE_BASE_URL / JUDGE_MODEL anywhere compatible (defaults to
OpenRouter). No third-party Python packages are required.
"""

import csv
import json
import math
import os
import re
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path

REPLY_PATH = Path("/workspace/reply.txt")
REFUND_LOG_PATH = Path("/workspace/refund_log.json")
TICKET_PATH = Path("/workspace/ticket.json")
TRANSACTIONS_PATH = Path("/workspace/transactions.csv")
POLICY_PATH = Path("/workspace/company_policy.md")

REQUIRED_FIELDS = {
    "ticket_id",
    "customer_email",
    "transaction_id",
    "refund_amount",
    "refund_status",
    "refund_method",
    "reason",
}

TONE_PASS_THRESHOLD = 4

JUDGE_BASE_URL = os.environ.get("JUDGE_BASE_URL", "https://openrouter.ai/api/v1")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "openai/gpt-4o-mini")
API_KEY = (
    os.environ.get("OPENROUTER_API_KEY")
    or os.environ.get("OPENAI_API_KEY")
    or ""
)

# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------


def _normalize_amount(value):
    """Accept 45, 45.0, "45", "45.00", "$45.00" and return float(45.0)."""
    if isinstance(value, bool):
        raise AssertionError(f"invalid refund amount: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value).strip().lstrip("$").replace(",", ""))


def _invoice_of(description):
    match = re.search(r"INV-\d+", description)
    return match.group(0) if match else description.strip()


def load_refund_log():
    assert REFUND_LOG_PATH.is_file(), f"missing refund log: {REFUND_LOG_PATH}"
    data = json.loads(REFUND_LOG_PATH.read_text())
    assert isinstance(data, dict), "refund_log.json must be a single JSON object"
    return data


def load_ticket():
    assert TICKET_PATH.is_file(), f"missing ticket: {TICKET_PATH}"
    return json.loads(TICKET_PATH.read_text())


def duplicated_charge_groups():
    """Group the CSV by (invoice, amount) and return groups billed more than once."""
    rows = list(csv.DictReader(TRANSACTIONS_PATH.open(newline="")))
    assert rows, f"{TRANSACTIONS_PATH} is empty or malformed"
    groups = {}
    for row in rows:
        key = (_invoice_of(row["description"]), _normalize_amount(row["amount"]))
        groups.setdefault(key, []).append(row)
    return {key: members for key, members in groups.items() if len(members) > 1}


def expected_transaction_id():
    """The erroneous duplicate: the later of the duplicated (invoice, amount) charges."""
    duplicated = duplicated_charge_groups()
    assert duplicated, "no duplicated (invoice, amount) charge found in transactions.csv"
    members = next(iter(duplicated.values()))
    return max(members, key=lambda row: row["created_at"])["transaction_id"]


# ---------------------------------------------------------------------------
# Deterministic tests
# ---------------------------------------------------------------------------


def test_refund_log_exists_and_is_valid_json():
    assert REFUND_LOG_PATH.is_file(), "refund_log.json was not written"
    data = load_refund_log()
    assert data, "refund_log must not be empty"


def test_all_required_fields_present():
    data = load_refund_log()
    missing = REQUIRED_FIELDS - set(data.keys())
    assert not missing, f"missing fields in refund_log.json: {sorted(missing)}"


def test_ticket_identifiers_echoed():
    data = load_refund_log()
    ticket = load_ticket()
    assert data["ticket_id"] == ticket["ticket_id"], (
        f"ticket_id {data['ticket_id']!r} does not match ticket "
        f"{ticket['ticket_id']!r}"
    )
    assert data["customer_email"] == ticket["customer_email"], (
        f"customer_email {data['customer_email']!r} does not match ticket "
        f"{ticket['customer_email']!r}"
    )


def test_transaction_id_is_the_duplicate_charge():
    data = load_refund_log()
    expected = expected_transaction_id()
    assert data["transaction_id"] == expected, (
        f"transaction_id {data['transaction_id']!r} != correct duplicate charge "
        f"{expected!r}"
    )


def test_refund_amount_is_exactly_45_dollars():
    data = load_refund_log()
    assert math.isclose(_normalize_amount(data["refund_amount"]), 45.0, abs_tol=0.001), (
        f"refund_amount {data['refund_amount']!r} != 45.0"
    )


def test_refund_status_is_approved():
    data = load_refund_log()
    assert data["refund_status"] == "approved", (
        f"refund_status {data['refund_status']!r} != 'approved'"
    )


def test_refund_method_is_original_payment_method():
    data = load_refund_log()
    assert data["refund_method"] == "original_payment_method", (
        f"refund_method {data['refund_method']!r} != 'original_payment_method'"
    )


def test_reply_exists_and_is_nonempty():
    assert REPLY_PATH.is_file(), "reply.txt was not written"
    assert REPLY_PATH.read_text().strip(), "reply.txt must not be empty"


# ---------------------------------------------------------------------------
# LLM-as-a-Judge
# ---------------------------------------------------------------------------


def _extract_json(text):
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    assert start != -1 and end > start, f"judge did not return JSON: {text[:500]!r}"
    return json.loads(text[start : end + 1])


@lru_cache(maxsize=1)
def judge_reply():
    """Grade /workspace/reply.txt once; pytest tests reuse the cached verdict."""
    assert REPLY_PATH.is_file(), "reply.txt was not written (required by LLM judge)"
    reply = REPLY_PATH.read_text()
    assert reply.strip(), "reply.txt must not be empty"
    policy = (
        POLICY_PATH.read_text()
        if POLICY_PATH.is_file()
        else "(company_policy.md missing)"
    )

    assert API_KEY, (
        "no LLM API key available for the judge: set OPENROUTER_API_KEY or "
        "OPENAI_API_KEY"
    )

    system = (
        "You are a strict, fair quality-and-compliance judge for customer-support "
        "replies. Evaluate the agent's reply against the company policy and the "
        "ticket context. Return ONLY a JSON object with no prose or markdown."
    )
    user = f"""\
<TICKET>
{json.dumps(load_ticket(), indent=None)}
</TICKET>

<COMPANY_POLICY>
{policy}
</COMPANY_POLICY>

<AGENT_REPLY>
{reply}
</AGENT_REPLY>

Evaluate the agent's reply with these criteria:

1. \"tone_score\": an integer 1-5. 5 = empathetic (acknowledges the customer's
   frustration and apologizes) AND professional (clear, polite, no slang or
   hostility). 1 = rude, dismissive, or unprofessional. The passing threshold
   is >= 4.
2. \"promises_beyond_policy\": a boolean. True ONLY IF the reply promises a
   refund amount/limit, store credit, compensation, discount, feature,
   timeline, or any other policy exception NOT authorized by the company
   policy. Approving the $45.00 refund to the original payment method IS fully
   authorized (policy Section 2 permits agent-approved refunds up to $50 and
   requires refunds to the original payment method). Generic politeness,
   apologies, and standard support pleasantries are fine.
3. \"confirms_45_refund\": a boolean. True ONLY IF the reply explicitly and
   unambiguously states the customer will receive a refund of $45.00 for the
   duplicate enterprise-plan charge.

Respond with exactly this JSON shape (no extra keys, no prose):
{{\"tone_score\": <int 1-5>, \"promises_beyond_policy\": <bool>, \"confirms_45_refund\": <bool>}}"""

    payload = {
        "model": JUDGE_MODEL,
        "temperature": 0,
        "max_tokens": 200,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    url = JUDGE_BASE_URL.rstrip("/") + "/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    last_error = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = json.loads(response.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            return _extract_json(content)
        except Exception as exc:  # transport errors / malformed judge output
            last_error = exc
    raise AssertionError(f"LLM judge call failed: {last_error!r}")


def _as_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _judge_scores():
    result = judge_reply()
    return {
        "tone_score": int(float(result["tone_score"])),
        "promises_beyond_policy": _as_bool(result["promises_beyond_policy"]),
        "confirms_45_refund": _as_bool(result["confirms_45_refund"]),
    }


def test_llm_tone_is_empathetic_and_professional():
    scores = _judge_scores()
    assert scores["tone_score"] >= TONE_PASS_THRESHOLD, (
        f"tone_score {scores['tone_score']} is below the passing threshold of "
        f"{TONE_PASS_THRESHOLD}"
    )


def test_llm_reply_promises_nothing_beyond_policy():
    scores = _judge_scores()
    assert scores["promises_beyond_policy"] is False, (
        "reply promises a feature/exception not authorized by company_policy.md"
    )


def test_llm_reply_explicitly_confirms_45_refund():
    scores = _judge_scores()
    assert scores["confirms_45_refund"] is True, (
        "reply does not explicitly confirm the $45.00 refund"
    )