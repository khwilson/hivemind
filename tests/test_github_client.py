import pytest

from hivemind.client import Client
from hivemind.github_client import GitHub
from hivemind.models import CheckPolicy


class ProofGitHub(GitHub):
    def __init__(self, conclusion="success", app_id=42, drift=False):
        super().__init__("")
        self.conclusion, self.app_id, self.drift = conclusion, app_id, drift
        self.reads = 0

    def get(self, path):
        if "/pulls/" in path:
            self.reads += 1
            return {
                "base": {"repo": {"full_name": "owner/math"}},
                "head": {
                    "sha": "b" * 40 if self.drift and self.reads > 1 else "a" * 40
                },
                "state": "open",
                "html_url": "https://github.com/owner/math/pull/1",
            }
        return {"total_count": 0}

    def pages(self, path, key=None):
        return [
            {
                "id": 1,
                "name": "quality",
                "app": {"id": self.app_id},
                "status": "completed",
                "conclusion": self.conclusion,
            }
        ]


@pytest.mark.parametrize(
    "conclusion,issuer,drift",
    [
        ("failure", 42, False),
        ("skipped", 42, False),
        ("success", 999, False),
        ("success", 42, True),
    ],
)
def test_proof_rejects_failure_wrong_issuer_and_head_drift(conclusion, issuer, drift):
    with pytest.raises(ValueError):
        ProofGitHub(conclusion, issuer, drift).verify(
            "owner/math", "a" * 40, 1, [CheckPolicy(name="quality", app_id=42)]
        )


def test_successful_proof_keeps_issuer_and_commit():
    proof = ProofGitHub().verify(
        "owner/math", "a" * 40, 1, [CheckPolicy(name="quality", app_id=42)]
    )
    assert proof["commit"] == "a" * 40
    assert proof["checks"][0]["app_id"] == 42


class InboxGitHub(GitHub):
    def __init__(self):
        super().__init__("")
        self.body = None

    def get(self, path):
        return {"id": 1}

    def request(self, path, method="GET", data=None):
        assert data is not None
        self.body = data["body"]
        return {"number": 3, "html_url": "https://github.com/owner/math/issues/3"}


def test_pending_receipt_does_not_grant_claim_ownership(tmp_path):
    from hivemind.signing import generate

    key = tmp_path / "key.pem"
    generate(key)
    api = InboxGitHub()
    result = Client("owner/math", key, wait=0, api=api).send("math", "claim", {})
    assert result["status"] == "pending"
    assert "task" not in result
    assert api.body is not None
    assert "signature" in api.body


def test_unsigned_agent_claim_never_posts_issue():
    api = InboxGitHub()
    with pytest.raises(ValueError, match="signing key"):
        Client("owner/math", wait=0, api=api).send("math", "claim", {})
    assert api.body is None
