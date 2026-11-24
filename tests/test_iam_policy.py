"""Static checks on `iam/policy.json`: least-privilege and code parity.

Not an AWS test (no boto3 call) — just a guard rail so the IAM policy
shipped in the repo can never silently grow write permissions or drift
from the actions the code actually calls.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_POLICY_PATH = _REPO_ROOT / "iam" / "policy.json"
_COST_EXPLORER_SRC = _REPO_ROOT / "src" / "mcp_aws_finops" / "sources" / "cost_explorer.py"

# Action-name verbs that would mutate AWS state; none of these may appear
# in the shipped policy.
_WRITE_VERB_RE = re.compile(
    r":(Create|Delete|Put|Update|Modify|Terminate|Start|Stop|Reboot|Attach|Detach|"
    r"Associate|Disassociate|Allocate|Release|Authorize|Revoke|Run|Enable|Disable|"
    r"Tag|Untag|Copy|Import|Export|Reset|Cancel|Purchase|Accept|Reject)",
    re.IGNORECASE,
)


def _load_policy() -> dict:
    return json.loads(_POLICY_PATH.read_text())


def _policy_actions() -> set[str]:
    policy = _load_policy()
    actions: set[str] = set()
    for stmt in policy["Statement"]:
        stmt_actions = stmt["Action"]
        if isinstance(stmt_actions, str):
            stmt_actions = [stmt_actions]
        actions.update(stmt_actions)
    return actions


def _code_actions() -> set[str]:
    """Extract the boto3 method calls the source file makes, mapped to
    their IAM action names (read-only API calls use the same verb as the
    IAM action, modulo CamelCase vs snake_case)."""
    src = _COST_EXPLORER_SRC.read_text()
    ce_methods = set(re.findall(r"self\._ce_client\.(\w+)\(", src))
    ec2_methods = set(re.findall(r'"(describe_\w+)"', src))
    cloudwatch_methods = set(re.findall(r"self\._cloudwatch_client\.(\w+)\(", src))

    def to_action(service: str, method: str) -> str:
        pascal = "".join(part.capitalize() for part in method.split("_"))
        return f"{service}:{pascal}"

    actions = {to_action("ce", m) for m in ce_methods}
    actions |= {to_action("ec2", m) for m in ec2_methods}
    actions |= {to_action("cloudwatch", m) for m in cloudwatch_methods}
    return actions


def test_policy_file_is_valid_json_with_statements() -> None:
    policy = _load_policy()
    assert policy["Version"] == "2012-10-17"
    assert policy["Statement"]


def test_policy_has_no_write_actions() -> None:
    actions = _policy_actions()
    offenders = [a for a in actions if _WRITE_VERB_RE.search(a)]
    assert offenders == [], f"Policy grants non-read actions: {offenders}"


def test_policy_has_no_wildcard_actions() -> None:
    actions = _policy_actions()
    assert not any("*" in a for a in actions), actions


def test_policy_actions_match_actions_used_in_code() -> None:
    policy_actions = _policy_actions()
    code_actions = _code_actions()
    # Every action the code actually calls must be covered by the policy.
    missing = code_actions - policy_actions
    assert missing == set(), f"Code calls actions not granted by policy.json: {missing}"
    # The policy should not grant actions the code never calls (keeps it
    # truly least-privilege), except ce:GetCostForecast/GetAnomalies which
    # are optional convenience wrappers exercised directly, not via the
    # auto-detected `self._ce_client.<method>(` pattern used for the rest.
    allowed_extra = {"ce:GetCostForecast", "ce:GetAnomalies", "cloudwatch:GetMetricStatistics"}
    extra = policy_actions - code_actions - allowed_extra
    assert extra == set(), f"Policy grants actions the code never calls: {extra}"


def test_policy_statements_use_allow_only() -> None:
    policy = _load_policy()
    for stmt in policy["Statement"]:
        assert stmt["Effect"] == "Allow"
