import json

import pytest

from hivemind.broker import Hub, process, run
from hivemind.github import ApiError, GitHub
from hivemind.models import Payload, State
from hivemind.signing import authorize, canonical, sign


def payload(**kwargs):
    return Payload(
        hub="owner/math",
        project="math",
        action="add",
        request_id="a" * 32,
        issued_at=100,
        expires_at=200,
        key_id="",
        args={"title": "Result", "criteria": "Proof"},
        **kwargs,
    )


def test_signature_binds_author_and_complete_payload(settings, tmp_path):
    envelope = sign(payload(), tmp_path / "key.pem")
    assert authorize(envelope, 2, settings, 101) == settings.agents[0].id
    with pytest.raises(ValueError, match="authorized"):
        authorize(envelope, 3, settings, 101)
    envelope.payload.args["title"] = "Tampered"
    with pytest.raises(ValueError, match="signature"):
        authorize(envelope, 2, settings, 101)
    with pytest.raises(ValueError, match="integers"):
        canonical({"float": 1.1})


def test_receipt_audits_envelope_and_replay(settings, tmp_path, monkeypatch):
    monkeypatch.setattr("hivemind.broker.time.time", lambda: 101)
    envelope = sign(payload(), tmp_path / "key.pem")
    issue = {"number": 1, "body": envelope.model_dump_json(), "user": {"id": 2}}
    state = State()
    receipt = process(state, settings, issue, GitHub(""), GitHub(""), "config", 101)
    assert receipt.accepted
    assert receipt.envelope == envelope.model_dump()
    issue["number"] = 2
    replay = process(state, settings, issue, GitHub(""), GitHub(""), "config", 101)
    assert not replay.accepted
    assert len(state.projects[0].tasks) == 1


def test_failed_transition_does_not_mutate_tasks(settings, tmp_path, monkeypatch):
    monkeypatch.setattr("hivemind.broker.time.time", lambda: 101)
    value = payload()
    value.args["dependencies"] = ["missing"]
    issue = {
        "number": 1,
        "body": sign(value, tmp_path / "key.pem").model_dump_json(),
        "user": {"id": 2},
    }
    state = State()
    receipt = process(state, settings, issue, GitHub(""), GitHub(""), "config", 101)
    assert not receipt.accepted
    assert not state.projects


class MemoryGitHub(GitHub):
    def __init__(self):
        super().__init__("")
        self.ref = None
        self.trees = {}
        self.commits = {}
        self.issues = []
        self.conflict_once = False

    def get(self, path):
        if "/git/ref/" in path:
            if self.ref is None:
                raise ApiError(404, "absent")
            return {"object": {"sha": self.ref}}
        if "/git/commits/" in path:
            return self.commits[path.rsplit("/", 1)[1]]
        raise AssertionError(path)

    def request(self, path, method="GET", data=None):
        assert data is not None
        if path.endswith("/git/trees"):
            tree = dict(self.trees[data["base_tree"]]) if "base_tree" in data else {}
            tree.update(
                {
                    entry["path"]: json.loads(entry["content"])
                    if entry["path"].endswith(".json")
                    else entry["content"]
                    for entry in data["tree"]
                }
            )
            identity = str(len(self.trees))
            self.trees[identity] = tree
            return {"sha": identity}
        if path.endswith("/git/commits"):
            identity = str(len(self.commits))
            self.commits[identity] = {
                "tree": {"sha": data["tree"]},
                "parents": data["parents"],
            }
            return {"sha": identity}
        if "/git/refs" in path:
            if self.conflict_once:
                self.conflict_once = False
                raise ApiError(409, "competing writer")
            if method == "PATCH":
                assert data["force"] is False
                assert self.commits[data["sha"]]["parents"] == [self.ref]
            self.ref = data["sha"]
            return {}
        if "/issues/" in path:
            return {}
        raise AssertionError(path)

    def json_file(self, repo, path, ref):
        assert ref in self.commits
        return self.trees[self.commits[ref]["tree"]["sha"]][path]

    def pages(self, path, key=None):
        return self.issues


def test_atomic_history_and_cas_retry(settings, tmp_path, monkeypatch):
    monkeypatch.setattr("hivemind.broker.time.time", lambda: 101)
    monkeypatch.setattr("hivemind.broker.time.sleep", lambda _: None)
    api = MemoryGitHub()
    hub = Hub(settings, api)
    initial = hub.publish(None, State(), "initialize")
    api.issues = [
        {
            "number": 1,
            "title": "[Hivemind] add",
            "body": sign(payload(), tmp_path / "key.pem").model_dump_json(),
            "user": {"id": 2},
        }
    ]
    api.conflict_once = True
    result = run(settings, api, api, "config")
    assert result["accepted"] == 1
    assert api.commits[api.ref]["parents"] == [initial]
    receipt = api.json_file(settings.hub, "receipts/" + "a" * 32 + ".json", api.ref)
    snapshot = api.json_file(settings.hub, "index.json", api.ref)
    assert receipt["accepted"]
    assert len(snapshot["projects"][0]["tasks"]) == 1
    assert len(hub.load()[1].projects[0].tasks) == 1


def test_live_config_refresh_rejects_newly_revoked_key(settings, tmp_path, monkeypatch):
    monkeypatch.setattr("hivemind.broker.time.time", lambda: 101)
    settings.agents[0].revoked = True

    class CurrentConfig(MemoryGitHub):
        def get(self, path):
            if path == "/repos/owner/math":
                return {"default_branch": "main"}
            if path == "/repos/owner/math/commits/main":
                return {"sha": "f" * 40}
            return super().get(path)

        def json_file(self, repo, path, ref):
            if path == ".hivemind/config.json":
                return settings.model_dump()
            if path == ".hivemind/standard-work.json":
                return {"version": 1, "rules": []}
            return super().json_file(repo, path, ref)

    api = CurrentConfig()
    api.issues = [
        {
            "number": 1,
            "title": "[Hivemind] add",
            "body": sign(payload(), tmp_path / "key.pem").model_dump_json(),
            "user": {"id": 2},
        }
    ]
    result = run(settings, api, api, "old-config", refresh_config=True)
    assert result["accepted"] == 0
    assert not Hub(settings, api).load()[1].projects[0].tasks


@pytest.mark.parametrize("complete", [False, True])
def test_standard_review_requires_committed_report(
    settings, tmp_path, monkeypatch, complete
):
    from hivemind.queue import Queue

    monkeypatch.setattr("hivemind.broker.time.time", lambda: 101)
    state = State()
    queue = Queue(state, settings)
    task_id = queue.apply(
        "math", "add", {"title": "Review", "criteria": "Report"}, "broker", "new", 100
    )["id"]
    task = queue.project("math").tasks[0]
    task.provenance = {"kind": "standard-work", "commit": "a" * 40}
    queue.apply("math", "claim", {}, settings.agents[0].id, "claim", 100)
    request = Payload(
        hub="owner/math",
        project="math",
        action="submit",
        request_id="c" * 32,
        issued_at=100,
        expires_at=200,
        key_id="",
        args={
            "task": task_id,
            "claim_id": "claim",
            "commit": "b" * 40,
            "pr": 1,
            "summary": "Inspected",
        },
    )

    class Evidence(GitHub):
        def verify(self, repo, commit, pr_number, required_checks):
            return {"commit": commit, "pr": pr_number}

        def text_file(self, repo, path, ref):
            if not complete:
                raise ApiError(404, "missing report")
            return (
                "Source: "
                + "a" * 40
                + "\n"
                + "\n".join(
                    "## " + heading
                    for heading in [
                        "Theorem references",
                        "Assumptions",
                        "Findings",
                        "Validation",
                        "Follow-ups",
                    ]
                )
            )

    issue = {
        "number": 1,
        "body": sign(request, tmp_path / "key.pem").model_dump_json(),
        "user": {"id": 2},
    }
    api = Evidence("")
    receipt = process(state, settings, issue, api, api, "config", 101)
    assert receipt.accepted == complete
    assert state.projects[0].tasks[0].status == ("done" if complete else "active")
