from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Literal

import provider
from catalog import public_tasks
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from harness import approve, execute, new_run
from pydantic import BaseModel, Field
from store import Store

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runtime" / "runs"
store = Store(ROOT / "runtime" / "patchproof.sqlite3")
store.recover()
executor = ThreadPoolExecutor(max_workers=1)
queue_lock = Lock()
app = FastAPI(
    title="PatchProof",
    description="A bounded local coding-agent evaluation and review lab.",
)


@app.middleware("http")
async def local_only(request: Request, call_next):
    if request.url.hostname not in ("127.0.0.1", "localhost", "testserver"):
        return JSONResponse({"detail": "Local demo only"}, status_code=403)
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        return JSONResponse({"detail": "Origin rejected"}, status_code=403)
    return await call_next(request)


@app.get("/api/tasks")
def tasks():
    return public_tasks()


@app.get("/api/status")
def status():
    return {
        "model_ready": provider.health(),
        "model": provider.MODEL,
        "provider": "local llama.cpp",
        "prompt_version": "expression-repair-v1",
    }


class RunRequest(BaseModel):
    task_id: Literal["shipping", "pagination", "access", "retry"]
    mode: Literal["local_llm", "fixture_good", "fixture_overfit", "fixture_unsafe"] = (
        "local_llm"
    )
    strategy: Literal["context_only", "test_guided"] = "test_guided"


@app.post("/api/runs", status_code=202)
def create(body: RunRequest):
    with queue_lock:
        if any(r["status"] in ("queued", "running") for r in store.all()):
            raise HTTPException(
                409, "One local run is already active. Wait for it to finish."
            )
        if body.mode == "local_llm" and not provider.health():
            raise HTTPException(
                503,
                "Local model is offline. Start with python run.py, or choose a labeled fixture mode.",
            )
        run = new_run(body.task_id, body.mode, body.strategy)
        store.save(run)
        executor.submit(execute, run["id"], store, RUNS)
        return run


@app.get("/api/runs")
def history():
    return [
        {
            k: r[k]
            for k in (
                "id",
                "task_id",
                "title",
                "mode",
                "strategy",
                "status",
                "total_tokens",
                "elapsed_ms",
                "created_at",
            )
        }
        for r in store.all()
    ]


def lookup(run_id):
    try:
        return store.get(run_id)
    except KeyError:
        raise HTTPException(404, "Run not found")


@app.get("/api/runs/{run_id}")
def read(run_id: str):
    return lookup(run_id)


class Approval(BaseModel):
    artifact_sha: str = Field(min_length=64, max_length=64)
    note: str = Field(min_length=3, max_length=500)


@app.post("/api/runs/{run_id}/approve")
def approval(run_id: str, body: Approval):
    lookup(run_id)
    if len(body.note.strip()) < 3:
        raise HTTPException(422, "Add a meaningful review note")
    try:
        return approve(run_id, body.artifact_sha, body.note.strip(), store, RUNS)
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.get("/api/runs/{run_id}/patch")
def patch(run_id: str):
    run = lookup(run_id)
    if run["status"] != "approved":
        raise HTTPException(409, "A passing gate and human approval are required")
    return PlainTextResponse(
        run["diff"],
        headers={
            "Content-Disposition": f'attachment; filename="{run["task_id"]}-{run_id[:8]}.diff"'
        },
    )


@app.get("/api/runs/{run_id}/report")
def report(run_id: str):
    return JSONResponse(
        lookup(run_id),
        headers={"Content-Disposition": 'attachment; filename="patchproof-run.json"'},
    )


@app.get("/api/scoreboard")
def scoreboard():
    groups = {}
    for run in store.all():
        if run["status"] in ("queued", "running", "interrupted"):
            continue
        key = run["mode"] + "/" + run["strategy"]
        g = groups.setdefault(
            key,
            {
                "name": key,
                "runs": 0,
                "passed_gate": 0,
                "errors": 0,
                "tokens": 0,
                "elapsed_ms": 0,
            },
        )
        g["runs"] += 1
        g["passed_gate"] += int(bool(run["gate"] and run["gate"]["passed"]))
        g["errors"] += int(run["status"] == "error")
        g["tokens"] += run["total_tokens"]
        g["elapsed_ms"] += run["elapsed_ms"]
    return {
        "scope": "Last 100 local runs; mixed tasks and repeated attempts, not a representative model benchmark. Fixture rows contain no inference.",
        "groups": list(groups.values()),
    }


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
