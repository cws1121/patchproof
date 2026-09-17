"""Run the fixed repair suite and preserve real metrics. Fixture and LLM modes stay separate."""

import argparse
import json
from pathlib import Path

import provider
from catalog import TASKS
from harness import execute, new_run
from store import Store

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["local_llm", "fixture_good", "fixture_overfit", "fixture_unsafe"],
        default="fixture_good",
    )
    parser.add_argument(
        "--strategy", choices=["context_only", "test_guided"], default="test_guided"
    )
    args = parser.parse_args()
    if args.mode == "local_llm" and not provider.health():
        raise SystemExit(
            "Local model is not ready. Start python run.py and wait for model readiness, then rerun."
        )
    store = Store(ROOT / "runtime" / "evaluation.sqlite3")
    results = []
    for task_id in TASKS:
        run = new_run(task_id, args.mode, args.strategy)
        store.save(run)
        execute(run["id"], store, ROOT / "runtime" / "eval-runs")
        run = store.get(run["id"])
        result = {
            "task": task_id,
            "status": run["status"],
            "attempts": len(run["attempts"]),
            "gate_passed": bool(run["gate"] and run["gate"]["passed"]),
            "tokens": run["total_tokens"],
            "elapsed_ms": run["elapsed_ms"],
            "expression": run["attempts"][-1]["expression"]
            if run["attempts"]
            else None,
            "error": run["error"],
        }
        results.append(result)
        print(json.dumps(result), flush=True)
    report = {
        "mode": args.mode,
        "strategy": args.strategy,
        "scope": "Four public synthetic tasks; held-out-from-prompt regression cases; not a general coding benchmark.",
        "passed": sum(r["gate_passed"] for r in results),
        "total": len(results),
        "results": results,
    }
    target = ROOT / "runtime" / f"evaluation-{args.mode}-{args.strategy}.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        f"Gate pass: {report['passed']}/{report['total']}; saved {target.name}",
        flush=True,
    )
    if any(r["error"] for r in results):
        raise SystemExit(1)
    if args.mode == "fixture_good" and report["passed"] != 4:
        raise SystemExit(1)
    if args.mode in ("fixture_overfit", "fixture_unsafe") and report["passed"] != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
