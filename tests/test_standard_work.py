from hivemind.github_client import GitHub
from hivemind.models import State
from hivemind.standard_work import Rule, StandardWork, reconcile


class Source(GitHub):
    def __init__(self, paths):
        super().__init__("")
        self.paths = paths

    def get(self, path):
        if path == "/repos/owner/math":
            return {"default_branch": "main"}
        if "/commits/" in path:
            return {"sha": "b" * 40}
        if "/compare/" in path:
            return {"status": "ahead", "files": [{"filename": p} for p in self.paths]}
        raise AssertionError(path)


def rules():
    return StandardWork(
        rules=[
            Rule(
                id="generalize",
                version=1,
                paths=["*.lean", "**/*.lean"],
                skill="mathematics-generalization",
            )
        ]
    )


def test_push_creates_one_provenance_task_and_replay_does_not_duplicate(settings):
    state = State(standard_cursor="a" * 40)
    source = Source(["Math/Theorem.lean"])
    assert reconcile(state, settings, rules(), source, "config", 100) == 1
    task = state.projects[0].tasks[0]
    assert task.provenance is not None
    assert task.provenance["commit"] == "b" * 40
    assert reconcile(state, settings, rules(), source, "config", 100) == 0
    assert len(state.projects[0].tasks) == 1


def test_review_only_commit_does_not_recurse_and_install_does_not_backfill(settings):
    state = State(standard_cursor="a" * 40)
    assert (
        reconcile(
            state,
            settings,
            rules(),
            Source([".hivemind/reviews/a.lean"]),
            "config",
            100,
        )
        == 0
    )
    state = State()
    assert (
        reconcile(state, settings, rules(), Source(["Math/New.lean"]), "config", 100)
        == 0
    )
    assert not state.projects
