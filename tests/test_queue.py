import pytest

from hivemind.models import State
from hivemind.queue import Queue


def add(queue, request="1", **kwargs):
    return queue.apply(
        "math",
        "add",
        {"title": "Prove result", "criteria": "A proof passes CI", **kwargs},
        "human",
        request,
        100,
    )["id"]


def test_fenced_claims_and_expiry(settings):
    queue = Queue(State(), settings)
    task = add(queue)
    actor = settings.agents[0].id
    first = queue.apply("math", "claim", {}, actor, "first", 100)["task"]
    assert queue.apply("math", "claim", {}, actor, "other", 100)["task"] is None
    queue.expire(7301)
    second = queue.apply("math", "claim", {}, actor, "second", 7301)["task"]
    assert first["claim_id"] != second["claim_id"]
    with pytest.raises(ValueError, match="claim ID"):
        queue.apply(
            "math",
            "heartbeat",
            {"task": task, "claim_id": "first"},
            actor,
            "renew",
            7302,
        )


def test_edits_reject_stale_revision_and_invalidate_claim(settings):
    queue = Queue(State(), settings)
    task = add(queue)
    actor = settings.agents[0].id
    claimed = queue.apply("math", "claim", {}, actor, "claim", 100)["task"]
    with pytest.raises(ValueError, match="revision conflict"):
        queue.apply(
            "math",
            "edit",
            {"task": task, "expected_revision": 1, "title": "New"},
            "human",
            "edit",
            101,
        )
    with pytest.raises(ValueError, match="release-claim"):
        queue.apply(
            "math",
            "edit",
            {"task": task, "expected_revision": claimed["revision"], "title": "New"},
            "human",
            "edit",
            101,
        )
    changed = queue.apply(
        "math",
        "edit",
        {
            "task": task,
            "expected_revision": claimed["revision"],
            "title": "New",
            "release_claim": True,
        },
        "human",
        "edit",
        101,
    )["task"]
    assert changed["status"] == "queued"
    assert changed["claim_id"] is None


def test_cycles_include_parents_and_dependencies(settings):
    queue = Queue(State(), settings)
    parent = add(queue)
    with pytest.raises(ValueError, match="cycle"):
        add(queue, "2", parent=parent, dependencies=[parent])


def test_child_blocks_parent_and_cancel_blocks_dependents(settings):
    queue = Queue(State(), settings)
    parent = add(queue)
    child = add(queue, "2", parent=parent)
    project = queue.project("math")
    assert queue.blockers(project, queue.task(project, parent)) == [child]
    queue.apply(
        "math",
        "cancel",
        {"task": child, "expected_revision": 1},
        "human",
        "cancel",
        100,
    )
    assert queue.blockers(project, queue.task(project, parent)) == [child]


def test_queue_revision_and_ordering(settings):
    queue = Queue(State(), settings)
    first, second = add(queue), add(queue, "2")
    project = queue.project("math")
    with pytest.raises(ValueError, match="revision conflict"):
        queue.apply(
            "math",
            "prioritize",
            {"tasks": [second, first], "expected_revision": 1},
            "human",
            "order",
            100,
        )
    queue.apply(
        "math",
        "prioritize",
        {"tasks": [second, first], "expected_revision": project.revision},
        "human",
        "order",
        100,
    )
    claimed = queue.apply("math", "claim", {}, settings.agents[0].id, "claim", 100)[
        "task"
    ]
    assert claimed["id"] == second


def test_scope_revocation_expires_claim(settings):
    state = State()
    queue = Queue(state, settings)
    add(queue)
    queue.apply("math", "claim", {}, settings.agents[0].id, "claim", 100)
    settings.agents[0].projects = []
    queue = Queue(state, settings)
    queue.expire(101)
    assert state.projects[0].tasks[0].status == "queued"


def test_edit_cannot_clear_required_fields_with_null(settings):
    queue = Queue(State(), settings)
    task = add(queue)
    with pytest.raises(ValueError, match="null"):
        queue.apply(
            "math",
            "edit",
            {"task": task, "expected_revision": 1, "title": None},
            "human",
            "edit",
            101,
        )
    assert queue.project("math").tasks[0].title == "Prove result"
