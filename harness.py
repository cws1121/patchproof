"""Bounded repair orchestration. Verification is independent of model claims."""

import ast
import difflib
import hashlib
import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import provider
from catalog import get_task, source
from policy import parse

ROOT = Path(__file__).resolve().parent
PROMPT_VERSION = "expression-repair-v1"


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def context_for(task):
    text = source(task)
    fn = ast.parse(text).body[0]
    lines = text.splitlines()
    return {
        "file": task["file"],
        "symbol": fn.name,
        "start_line": fn.lineno,
        "end_line": fn.end_lineno,
        "text": "\n".join(
            f"{i + 1}: {lines[i]}" for i in range(fn.lineno - 1, fn.end_lineno)
        ),
        "source": text,
        "sha256": digest(text),
        "method": "Ticket target → AST function slice",
    }


def new_run(task_id, mode, strategy):
    task = get_task(task_id)
    return {
        "id": uuid.uuid4().hex,
        "task_id": task_id,
        "title": task["title"],
        "ticket": task["ticket"],
        "mode": mode,
        "strategy": strategy,
        "status": "queued",
        "created_at": now(),
        "events": [],
        "attempts": [],
        "context": None,
        "baseline": None,
        "gate": None,
        "diff": None,
        "artifact_sha": None,
        "approval": None,
        "prompt_version": PROMPT_VERSION,
        "total_tokens": 0,
        "elapsed_ms": 0,
        "error": None,
    }


def check_worker(workspace, task_id, split):
    path = workspace / get_task(task_id)["file"]
    r = subprocess.run(
        [sys.executable, str(ROOT / "verify_worker.py"), str(path), task_id, split],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        shell=False,
        check=False,
    )
    if r.returncode:
        raise RuntimeError("Verification worker failed: " + r.stderr[-600:])
    return json.loads(r.stdout)


def make_patch(task, expression):
    return "".join(
        difflib.unified_diff(
            source(task).splitlines(True),
            source(task, expression).splitlines(True),
            fromfile="a/" + task["file"],
            tofile="b/" + task["file"],
        )
    )


def execute(run_id, store, root):
    run = store.get(run_id)
    task = get_task(run["task_id"])
    started = time.perf_counter()
    directory = Path(root) / run_id
    workspace = directory / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    artifact = workspace / task["file"]
    artifact.parent.mkdir(parents=True, exist_ok=True)

    def event(stage, message, **details):
        run["events"].append(
            {"at": now(), "stage": stage, "message": message, **details}
        )
        run["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
        if run["status"] in ("queued", "running"):
            store.save(run)

    try:
        run["status"] = "running"
        run["context"] = context_for(task)
        event(
            "context",
            "Built a minimal source context from the ticket target and Python AST.",
            source_sha=run["context"]["sha256"],
        )
        artifact.write_text(source(task), encoding="utf-8")
        run["baseline"] = check_worker(workspace, run["task_id"], "visible")
        event(
            "baseline",
            f"Bug reproduced: {run['baseline']['total'] - run['baseline']['passed']} public cases fail.",
        )
        feedback = None
        limit = (
            3 if run["strategy"] == "test_guided" and run["mode"] == "local_llm" else 1
        )
        for attempt_no in range(1, limit + 1):
            event(
                "model" if run["mode"] == "local_llm" else "fixture",
                f"Proposal {attempt_no}/{limit}: "
                + (
                    "local Qwen inference"
                    if run["mode"] == "local_llm"
                    else "explicit deterministic test fixture"
                ),
            )
            if run["mode"] == "local_llm":
                proposal = provider.propose(
                    task, run["context"]["text"], feedback, run["strategy"]
                )
            else:
                key = {"fixture_good": "correct", "fixture_overfit": "overfit"}.get(
                    run["mode"]
                )
                proposal = {
                    "expression": task[key] if key else '__import__("os").getcwd()',
                    "summary": "Deterministic "
                    + run["mode"]
                    + " fixture; no model inference.",
                    "usage": {},
                    "latency_ms": 0,
                    "model": "fixture / no inference",
                    "prompt": [],
                }
            proposal["number"] = attempt_no
            proposal["policy"] = "pending"
            proposal["tests"] = None
            run["attempts"].append(proposal)
            run["total_tokens"] += proposal["usage"].get("total_tokens", 0)
            try:
                parse(proposal["expression"], task["args"])
            except ValueError as exc:
                proposal["policy"] = "rejected"
                proposal["policy_reason"] = str(exc)
                run["status"] = "rejected"
                event("policy", "Patch blocked before verification: " + str(exc))
                return
            proposal["policy"] = "passed"
            run["diff"] = make_patch(task, proposal["expression"])
            artifact.write_text(source(task), encoding="utf-8")
            patch_path = directory / "proposal.diff"
            patch_path.write_text(run["diff"], encoding="utf-8")
            if run["diff"]:
                for args in (["--check"], []):
                    result = subprocess.run(
                        ["git", "apply", *args, str(patch_path.resolve())],
                        cwd=workspace,
                        capture_output=True,
                        text=True,
                        timeout=10,
                        shell=False,
                        check=False,
                    )
                    if result.returncode:
                        raise RuntimeError(
                            "Patch could not apply to the disposable fixture: "
                            + result.stderr[-300:]
                        )
            event(
                "patch",
                "Applied an allowlisted expression change to a disposable fixture copy.",
                file=task["file"],
            )
            visible = check_worker(workspace, run["task_id"], "visible")
            proposal["tests"] = visible
            event(
                "verify",
                f"Public tests: {visible['passed']}/{visible['total']} passed.",
            )
            if visible["passed"] == visible["total"]:
                break
            feedback = {
                "expression": proposal["expression"],
                "failures": [x for x in visible["cases"] if not x["passed"]],
            }
        # One final gate only. Its cases are never fed back into this run's model loop.
        held = check_worker(workspace, run["task_id"], "holdout")
        run["gate"] = {
            "visible": proposal["tests"],
            "holdout": held,
            "tests_sha": digest(json.dumps(task["holdout"], sort_keys=True)),
            "passed": proposal["tests"]["passed"] == proposal["tests"]["total"]
            and held["passed"] == held["total"],
        }
        run["artifact_sha"] = digest(artifact.read_text(encoding="utf-8"))
        run["status"] = "needs_review" if run["gate"]["passed"] else "rejected"
        event(
            "gate",
            f"Regression gate: {held['passed']}/{held['total']} passed. "
            + (
                "Ready for human review."
                if run["gate"]["passed"]
                else "Export blocked."
            ),
        )
    except Exception as exc:  # noqa: BLE001 - persist every failed background run instead of losing its state
        run["status"] = "error"
        run["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        event("error", run["error"])
    finally:
        run["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
        store.save(run)


def approve(run_id, expected_sha, note, store, root):
    with store.lock:
        run = store.get(run_id)
        if run["status"] == "approved":
            if expected_sha != run["artifact_sha"]:
                raise ValueError("Stale artifact digest")
            return run
        if (
            run["status"] != "needs_review"
            or not run["gate"]
            or not run["gate"]["passed"]
        ):
            raise ValueError("Only a passing patch can be approved")
        artifact = Path(root) / run_id / "workspace" / get_task(run["task_id"])["file"]
        current = digest(artifact.read_text(encoding="utf-8"))
        if expected_sha != run["artifact_sha"] or current != expected_sha:
            raise ValueError("Artifact changed after verification; start a fresh run")
        run["status"] = "approved"
        run["approval"] = {
            "at": now(),
            "actor": "local reviewer",
            "note": note,
            "artifact_sha": current,
        }
        run["events"].append(
            {
                "at": now(),
                "stage": "approval",
                "message": "Reviewer approved this exact artifact digest.",
            }
        )
        store.save(run)
        return run
