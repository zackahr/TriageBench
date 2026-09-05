"""Hybrid verifier for the hard-multi-step-escalation task.

Deterministic pytest checks validate the two intermediate/final artifacts:

- /workspace/clarification_needed.txt  (Step 1: the agent detected the missing
  environment identifier and logged a clarification query)
- /workspace/config.yaml               (Step 2: valid YAML carrying the correct
  production fix)

A single LLM-as-a-Judge call then grades /workspace/incident_report.md (Step 3)
on root-cause accuracy and completeness.

The LLM call uses the OpenAI-compatible chat-completions API over stdlib
urllib; point JUDGE_BASE_URL / JUDGE_MODEL anywhere compatible (defaults to
OpenRouter). No third-party Python packages beyond PyYAML (installed in the
image) are required.
"""

import json
import os
import re
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path

import yaml

CLARIFICATION_PATH = Path("/workspace/clarification_needed.txt")
CONFIG_PATH = Path("/workspace/config.yaml")
TICKET_PATH = Path("/workspace/outage_ticket.json")
RESPONSE_PATH = Path("/workspace/user_response.txt")
REPORT_PATH = Path("/workspace/incident_report.md")
POLICY_PATH = Path("/workspace/company_policy.md")

ROOT_CAUSE_PASS_THRESHOLD = 4

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


def load_config():
    assert CONFIG_PATH.is_file(), f"missing config: {CONFIG_PATH}"
    data = yaml.safe_load(CONFIG_PATH.read_text())
    assert isinstance(data, dict), "config.yaml must parse to a YAML mapping"
    return data


def load_ticket():
    assert TICKET_PATH.is_file(), f"missing ticket: {TICKET_PATH}"
    return json.loads(TICKET_PATH.read_text())


def _as_int(value):
    if isinstance(value, bool):
        raise AssertionError(f"invalid integer value: {value!r}")
    if isinstance(value, int):
        return value
    return int(str(value).strip())

# ---------------------------------------------------------------------------
# Step 1 — clarification artifact
# ---------------------------------------------------------------------------


def test_clarification_log_exists():
    assert CLARIFICATION_PATH.is_file(), (
        "clarification_needed.txt was not written (Step 1)"
    )
    assert CLARIFICATION_PATH.read_text().strip(), (
        "clarification_needed.txt must not be empty"
    )


def test_clarification_requests_the_missing_environment():
    assert CLARIFICATION_PATH.is_file(), "clarification_needed.txt missing"
    lowered = CLARIFICATION_PATH.read_text().lower()
    assert "environment" in lowered or "region" in lowered, (
        "clarification must reference the missing environment/region identifier"
    )
    assert any(
        marker in lowered
        for marker in ("what", "which", "confirm", "please provide", "?")
    ), "clarification must pose a question that unblocks the fix"


def test_clarification_names_the_reply_artifact():
    assert CLARIFICATION_PATH.is_file(), "clarification_needed.txt missing"
    lowered = CLARIFICATION_PATH.read_text().lower()
    assert "user_response" in lowered, (
        "clarification must point at /workspace/user_response.txt as the reply "
        "path"
    )

# ---------------------------------------------------------------------------
# Step 2 — config fix
# ---------------------------------------------------------------------------


def test_config_exists_and_is_valid_yaml():
    assert CONFIG_PATH.is_file(), "config.yaml was not written"
    config = load_config()
    assert config, "config.yaml must not be an empty mapping"


def test_config_environment_is_production():
    config = load_config()
    assert config.get("service", {}).get("environment") == "production", (
        f"service.environment {config.get('service', {}).get('environment')!r} "
        "!= 'production'"
    )


def test_config_region_is_production_west():
    config = load_config()
    assert config.get("service", {}).get("region") == "us-west-2", (
        f"service.region {config.get('service', {}).get('region')!r} != "
        "'us-west-2'"
    )


def test_config_database_points_at_production():
    config = load_config()
    assert config.get("database", {}).get("host") == (
        "checkout-db.production.internal"
    ), (
        f"database.host {config.get('database', {}).get('host')!r} != "
        "'checkout-db.production.internal'"
    )


def test_config_database_pool_size_is_production_sized():
    config = load_config()
    assert _as_int(config.get("database", {}).get("pool_size")) == 64, (
        "database.pool_size must be 64 (production-sized pool)"
    )


def test_config_auth_bypass_test_flag_disabled():
    config = load_config()
    assert config.get("feature_flags", {}).get("auth_bypass_for_tests") is False, (
        "feature_flags.auth_bypass_for_tests must be disabled in production"
    )


def test_config_service_name_unchanged():
    config = load_config()
    assert config.get("service", {}).get("name") == "checkout-payments", (
        "service.name must remain 'checkout-payments'"
    )

# ---------------------------------------------------------------------------
# Step 3 — incident report (LLM-as-a-Judge)
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
def judge_report():
    """Grade /workspace/incident_report.md once; pytest tests reuse the verdict."""
    assert REPORT_PATH.is_file(), (
        "incident_report.md was not written (required by LLM judge)"
    )
    report = REPORT_PATH.read_text()
    assert report.strip(), "incident_report.md must not be empty"

    def _text_or_missing(path):
        return path.read_text() if path.is_file() else f"({path.name} missing)"

    assert API_KEY, (
        "no LLM API key available for the judge: set OPENROUTER_API_KEY or "
        "OPENAI_API_KEY"
    )

    system = (
        "You are a strict, fair incident-report judge for a site-reliability "
        "review. Evaluate the agent's executive incident report against the "
        "incident context and the correct root cause. Return ONLY a JSON "
        "object with no prose or markdown."
    )
    user = f"""\
<TICKET>
{json.dumps(load_ticket(), indent=None)}
</TICKET>

<ESCALATION_REPLY>
{_text_or_missing(RESPONSE_PATH)}
</ESCALATION_REPLY>

<FIXED_CONFIG>
{_text_or_missing(CONFIG_PATH)}
</FIXED_CONFIG>

<CLARIFICATION_LOG>
{_text_or_missing(CLARIFICATION_PATH)}
</CLARIFICATION_LOG>

<AGENT_REPORT>
{report}
</AGENT_REPORT>

Ground truth: the outage root cause is a misconfigured environment. The
checkout-payments service ran production live traffic against the STAGING
database (checkout-db.staging.internal) with the test-only
"auth_bypass_for_tests" flag enabled and a staging-sized connection pool that
could not absorb production load, causing database connection-pool exhaustion,
100% HTTP 500s, and a complete checkout outage. The ticket omitted which
environment/region was affected, so the fix only became possible after a
clarification/escalation step confirmed production in us-west-2. The applied
fix pointed the configuration at the production database (host, region, pool
size 64) and disabled the auth-bypass test flag.

Evaluate the agent's report with these criteria:

1. "root_cause_score": an integer 1-5. 5 = the report names the
   production-to-staging misconfiguration (staging database, wrong
   environment/region, or connection-pool exhaustion under production load) as
   the cause and does NOT attribute the outage to an unrelated cause (e.g.
   DDoS, hacking, or customer fault). 1 = wrong or missing root cause. The
   passing threshold is >= 4.
2. "impact_described": a boolean. True ONLY IF the report states the impact
   (checkout service down, 100% failure/error rate, affected customers unable
   to pay, roughly 45 minutes).
3. "fix_described": a boolean. True ONLY IF the report describes the applied
   fix: switching the configuration to the production database / correct
   environment and region (us-west-2) with a production-sized pool and/or
   disabling the auth_bypass_for_tests flag.
4. "clarification_noted": a boolean. True ONLY IF the report notes that the
   original ticket was missing the environment/region identifier and that a
   clarification (escalation) step was required before the fix could be
   applied.

Respond with exactly this JSON shape (no extra keys, no prose):
{{"root_cause_score": <int 1-5>, "impact_described": <bool>, "fix_described": <bool>, "clarification_noted": <bool>}}"""

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
    result = judge_report()
    return {
        "root_cause_score": int(float(result["root_cause_score"])),
        "impact_described": _as_bool(result["impact_described"]),
        "fix_described": _as_bool(result["fix_described"]),
        "clarification_noted": _as_bool(result["clarification_noted"]),
    }


def test_report_exists_and_is_nonempty():
    assert REPORT_PATH.is_file(), "incident_report.md was not written (Step 3)"
    assert REPORT_PATH.read_text().strip(), "incident_report.md must not be empty"


def test_llm_root_cause_is_accurate():
    scores = _judge_scores()
    assert scores["root_cause_score"] >= ROOT_CAUSE_PASS_THRESHOLD, (
        f"root_cause_score {scores['root_cause_score']} is below the passing "
        f"threshold of {ROOT_CAUSE_PASS_THRESHOLD}"
    )


def test_llm_impact_described():
    scores = _judge_scores()
    assert scores["impact_described"] is True, (
        "report does not describe the incident impact"
    )


def test_llm_fix_described():
    scores = _judge_scores()
    assert scores["fix_described"] is True, (
        "report does not describe the configuration fix applied"
    )


def test_llm_clarification_noted():
    scores = _judge_scores()
    assert scores["clarification_noted"] is True, (
        "report does not note the missing environment / clarification step"
    )