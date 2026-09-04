import json
from pathlib import Path

RESULT_PATH = Path("/workspace/resolution.json")

VALID_CATEGORIES = {
    "account_access",
    "password_reset",
    "billing_dispute",
    "refund_request",
    "technical_issue",
    "general_inquiry",
    "escalation",
}

VALID_PRIORITIES = {"low", "medium", "high", "urgent"}
VALID_STATUSES = {"open", "in-progress", "resolved", "escalated", "closed"}

REQUIRED_FIELDS = {
    "ticket_id",
    "category",
    "priority",
    "status",
    "customer_email",
    "summary",
    "action_taken",
}


def load_resolution():
    assert RESULT_PATH.exists(), f"missing resolution file: {RESULT_PATH}"
    data = json.loads(RESULT_PATH.read_text())
    assert isinstance(data, dict), "resolution must be a JSON object"
    return data


def test_resolution_file_exists_and_is_valid_json():
    assert RESULT_PATH.is_file(), "resolution.json was not written"
    data = load_resolution()
    assert data, "resolution must not be empty"


def test_all_required_fields_present():
    data = load_resolution()
    missing = REQUIRED_FIELDS - set(data.keys())
    assert not missing, f"missing fields: {sorted(missing)}"


def test_category_is_account_access():
    data = load_resolution()
    assert data["category"] == "account_access", (
        f"expected category 'account_access', got {data['category']!r}"
    )


def test_priority_is_low_or_medium():
    data = load_resolution()
    assert data["priority"] in {"low", "medium"}, (
        f"expected priority low or medium, got {data['priority']!r}"
    )


def test_action_taken_matches_standard_password_reset_procedure():
    data = load_resolution()
    action = data["action_taken"]
    assert isinstance(action, str) and action.strip(), "action_taken must be a non-empty string"
    normalized = action.lower()
    assert "reset" in normalized, "action_taken must describe a password reset"
    assert "email" in normalized or "link" in normalized, (
        "action_taken must describe delivery via secure email link"
    )
    assert "verif" in normalized, "action_taken must mention identity verification"


def test_category_priority_status_are_valid_enum_values():
    data = load_resolution()
    assert data["category"] in VALID_CATEGORIES
    assert data["priority"] in VALID_PRIORITIES
    assert data["status"] in VALID_STATUSES