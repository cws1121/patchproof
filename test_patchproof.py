import app
import harness
import pytest
from catalog import TASKS, source
from fastapi.testclient import TestClient
from policy import PolicyError, evaluate, parse
from store import Store


@pytest.fixture
def storage(tmp_path):
    return Store(tmp_path / "runs.sqlite3"), tmp_path / "runs"


def perform(storage, task="shipping", mode="fixture_good", strategy="test_guided"):
    store, root = storage
    run = harness.new_run(task, mode, strategy)
    store.save(run)
    harness.execute(run["id"], store, root)
    return store.get(run["id"])


@pytest.mark.parametrize(
    "expression",
    [
        '__import__("os").system("whoami")',
        "total.__class__",
        "[x for x in range(100)]",
        "(lambda: 1)()",
        'open("file")',
        '"x" * 1000',
        "sum([1,2])",
        "True\n# extra content",
    ],
)
def test_model_code_outside_language_is_rejected(expression):
    with pytest.raises(PolicyError):
        parse(expression, ["total"])


def test_numeric_budgets_and_short_circuit():
    with pytest.raises(PolicyError):
        evaluate("2 ** 1000000", {})
    assert evaluate("True or 1 // 0", {}) is True
    assert evaluate("False and 1 // 0", {}) is False
    assert evaluate("5 if total < 10 else 0", {"total": 8}) == 5


@pytest.mark.parametrize("task", list(TASKS))
def test_correct_fixtures_apply_diff_and_pass_frozen_tests(storage, task):
    run = perform(storage, task)
    assert run["status"] == "needs_review" and run["gate"]["passed"]
    assert run["baseline"]["passed"] < run["baseline"]["total"]
    artifact = storage[1] / run["id"] / "workspace" / TASKS[task]["file"]
    assert artifact.read_text() == source(TASKS[task], TASKS[task]["correct"])
    assert run["gate"]["holdout"]["total"] == 8


@pytest.mark.parametrize("task", list(TASKS))
def test_overfit_proposals_pass_public_but_fail_regression(storage, task):
    run = perform(storage, task, "fixture_overfit")
    assert run["status"] == "rejected"
    assert run["gate"]["visible"]["passed"] == run["gate"]["visible"]["total"]
    assert run["gate"]["holdout"]["passed"] < run["gate"]["holdout"]["total"]
    with pytest.raises(ValueError):
        harness.approve(run["id"], run["artifact_sha"], "reviewed", *storage)


def test_unsafe_proposal_never_reaches_patch_or_test_execution(storage):
    run = perform(storage, mode="fixture_unsafe")
    assert run["status"] == "rejected" and run["gate"] is None and run["diff"] is None
    assert run["attempts"][0]["policy"] == "rejected"


def test_approval_binds_verified_artifact_and_is_idempotent(storage):
    store, root = storage
    run = perform(storage)
    with pytest.raises(ValueError):
        harness.approve(run["id"], "0" * 64, "reviewed", store, root)
    approved = harness.approve(
        run["id"], run["artifact_sha"], "Checked the boundary", store, root
    )
    assert approved["status"] == "approved"
    assert (
        harness.approve(run["id"], run["artifact_sha"], "again", store, root)
        == approved
    )
    another = perform(storage)
    artifact = root / another["id"] / "workspace" / TASKS["shipping"]["file"]
    artifact.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError):
        harness.approve(another["id"], another["artifact_sha"], "reviewed", store, root)


def test_retry_uses_only_public_failures_and_counts_real_usage(storage, monkeypatch):
    calls = []

    def proposal(task, context, feedback, strategy):
        calls.append(feedback)
        if feedback:
            assert all(c["inputs"]["total"] == 50 for c in feedback["failures"])
        return {
            "expression": task["buggy"] if len(calls) == 1 else task["correct"],
            "summary": "Test provider",
            "usage": {"total_tokens": 10},
            "latency_ms": 1,
            "model": "test-only",
            "prompt": [],
        }

    monkeypatch.setattr(harness.provider, "propose", proposal)
    run = perform(storage, mode="local_llm")
    assert run["status"] == "needs_review" and len(calls) == 2 and calls[0] is None
    assert run["total_tokens"] == 20


def test_provider_failure_is_not_replaced_by_fake_success(storage, monkeypatch):
    def broken(*args):
        raise ConnectionError("offline")

    monkeypatch.setattr(harness.provider, "propose", broken)
    run = perform(storage, mode="local_llm")
    assert run["status"] == "error" and run["gate"] is None and not run["attempts"]


def test_restart_marks_incomplete_runs_interrupted(storage):
    store, _ = storage
    run = harness.new_run("shipping", "local_llm", "test_guided")
    store.save(run)
    store.recover()
    assert store.get(run["id"])["status"] == "interrupted"


def test_api_export_gate_origin_and_model_availability(storage, monkeypatch):
    store, root = storage
    monkeypatch.setattr(app, "store", store)
    monkeypatch.setattr(app, "RUNS", root)
    monkeypatch.setattr(app.provider, "health", lambda: False)
    client = TestClient(app.app)
    assert client.post("/api/runs", json={"task_id": "shipping"}).status_code == 503
    assert (
        client.post(
            "/api/runs",
            json={"task_id": "shipping"},
            headers={"Origin": "https://example.com"},
        ).status_code
        == 403
    )
    run = perform(storage)
    assert client.get("/api/runs/" + run["id"] + "/patch").status_code == 409
    result = client.post(
        "/api/runs/" + run["id"] + "/approve",
        json={
            "artifact_sha": run["artifact_sha"],
            "note": "Reviewed boundary behavior",
        },
    )
    assert result.status_code == 200
    patch = client.get("/api/runs/" + run["id"] + "/patch")
    assert (
        patch.status_code == 200
        and "+    return fee if total < threshold else 0" in patch.text
    )
    assert (
        client.get("/api/runs/" + run["id"] + "/report").json()["approval"][
            "artifact_sha"
        ]
        == run["artifact_sha"]
    )
