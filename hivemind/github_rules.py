"""Compare protected rules without mistaking GitHub defaults for policy drift."""

from copy import deepcopy
from typing import Any


def ruleset_matches(actual: dict[str, Any], desired: dict[str, Any]) -> bool:
    policy = {key: deepcopy(actual.get(key)) for key in desired}
    desired_rules = {rule["type"]: rule for rule in desired["rules"]}
    for rule in policy.get("rules") or []:
        if rule.get("type") != "pull_request":
            continue
        parameters = rule.get("parameters", {})
        expected = desired_rules.get("pull_request", {}).get("parameters", {})
        # The REST API supplies these defaults even when the request omits them.
        # Nondefault values and unknown parameters still require reconciliation.
        defaults = {
            "allowed_merge_methods": ["merge", "squash", "rebase"],
            "required_reviewers": [],
            "require_extra_approval_for_unattributed_changes": True,
        }
        for key, value in defaults.items():
            if key not in expected and parameters.get(key) == value:
                parameters.pop(key)
    return policy == desired
