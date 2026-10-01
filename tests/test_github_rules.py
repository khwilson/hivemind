from copy import deepcopy

import pytest

from hivemind.github_rules import ruleset_matches
from hivemind.installation import setup_plan


def review_rule():
    return setup_plan("owner/project", "main", 42)["rulesets"][2]


def live_rule():
    actual = deepcopy(review_rule())
    actual["id"] = 24339693
    actual["rules"][0]["parameters"].update(
        allowed_merge_methods=["merge", "squash", "rebase"],
        required_reviewers=[],
        require_extra_approval_for_unattributed_changes=True,
    )
    return actual


def test_live_github_defaults_match_without_mutating_input():
    actual = live_rule()
    before = deepcopy(actual)
    assert ruleset_matches(actual, review_rule())
    assert actual == before


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("required_approving_review_count", 0),
        ("require_code_owner_review", False),
        ("allowed_merge_methods", ["squash"]),
        ("required_reviewers", [{"type": "Team", "id": 1}]),
        ("require_extra_approval_for_unattributed_changes", False),
        ("unknown_policy", True),
    ],
)
def test_changed_or_unknown_review_policy_still_requires_reconciliation(key, value):
    actual = live_rule()
    actual["rules"][0]["parameters"][key] = value
    assert not ruleset_matches(actual, review_rule())


def test_bypass_actors_and_missing_rules_are_not_normalized():
    actual = live_rule()
    actual["bypass_actors"] = [
        {"actor_type": "RepositoryRole", "actor_id": 5, "bypass_mode": "always"}
    ]
    assert not ruleset_matches(actual, review_rule())
    actual = live_rule()
    actual["rules"].pop()
    assert not ruleset_matches(actual, review_rule())
